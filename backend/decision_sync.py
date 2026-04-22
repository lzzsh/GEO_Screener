from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import GeoLabel, ScreeningResult, ScreeningTask


DECISION_TO_CONCLUSION = {
    "include": "可用",
    "exclude": "不可用",
    "uncertain": "待确认",
}

CONCLUSION_TO_DECISION = {value: key for key, value in DECISION_TO_CONCLUSION.items()}


async def recompute_task_decision_counts(db: AsyncSession, task: ScreeningTask) -> None:
    counts = (await db.execute(
        select(ScreeningResult.decision, func.count().label("n"))
        .where(ScreeningResult.task_id == task.id)
        .group_by(ScreeningResult.decision)
    )).all()
    count_map = {row.decision: row.n for row in counts}
    task.included_count = count_map.get("include", 0)
    task.excluded_count = count_map.get("exclude", 0)
    task.uncertain_count = count_map.get("uncertain", 0)


async def sync_final_conclusion_label(
    db: AsyncSession,
    result_id: int,
    decision: str,
    source: str = "human",
) -> GeoLabel:
    conclusion = DECISION_TO_CONCLUSION[decision]
    label = (await db.execute(
        select(GeoLabel).where(
            GeoLabel.result_id == result_id,
            GeoLabel.key == "final_conclusion",
        )
    )).scalar_one_or_none()
    if label:
        label.value = conclusion
        label.source = source
        return label
    label = GeoLabel(
        result_id=result_id,
        key="final_conclusion",
        value=conclusion,
        source=source,
    )
    db.add(label)
    return label
