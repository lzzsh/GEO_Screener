# GSM 级别标注 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对每个 GSE 下的 GSM 样本，LLM 自动提取细胞来源/分化终点/分化时间点/原始数据可用性并给出 gsm_available 结论，人工可覆盖。

**Architecture:** 新增 GsmLabel 表挂在 GeoSample 下，复用现有 GeoLabel/annotate 路由模式。后端新增 3 个端点（触发标注、读标签、写标签），前端在 tasks_detail.html 的 GSM 表格里加"标注 GSM"按钮和标签展示/编辑。

**Tech Stack:** FastAPI, SQLAlchemy async, SQLite WAL, Alpine.js, 现有 LLMClient.extract_labels 模式

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/models.py` | Modify | 新增 GsmLabel 模型，GeoSample 加 labels relationship |
| `backend/database.py` | Modify | _run_sqlite_migrations 加 gsm_labels 表迁移 |
| `backend/worker/llm_client.py` | Modify | 新增 GSM_LABEL_PROMPT_TEMPLATE 和 annotate_gsm 方法 |
| `backend/worker/tasks.py` | Modify | 新增 _run_gsm_annotation_async |
| `backend/routers/annotate.py` | Modify | 新增 3 个端点 |
| `backend/main.py` | No change | annotate router 已注册 |
| `frontend/templates/tasks_detail.html` | Modify | GSM 表格加标注按钮和标签展示 |
| `backend/tests/test_annotate_router.py` | Modify | 新增 GSM 标注测试 |

---

### Task 1: GsmLabel 数据模型

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/database.py`
- Test: `backend/tests/test_annotate_router.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_annotate_router.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_gsm_label_model_persists(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult, GeoSample, GsmLabel
    import sqlalchemy
    async with AsyncSessionLocal() as db:
        task = ScreeningTask(name="gsm_model_task", source="geo", criteria_text="", owner_id=1)
        db.add(task)
        await db.flush()
        sr = ScreeningResult(task_id=task.id, dataset_id="GSE_GSMTEST")
        db.add(sr)
        await db.flush()
        sample = GeoSample(result_id=sr.id, gsm_id="GSM_TEST1", title="Test sample")
        db.add(sample)
        await db.flush()
        db.add(GsmLabel(sample_id=sample.id, key="细胞来源", value="iPSC", source="llm"))
        await db.commit()
        sample_id = sample.id

    async with AsyncSessionLocal() as db:
        labels = (await db.execute(
            sqlalchemy.select(GsmLabel).where(GsmLabel.sample_id == sample_id)
        )).scalars().all()
    assert len(labels) == 1
    assert labels[0].key == "细胞来源"
    assert labels[0].value == "iPSC"
    assert labels[0].source == "llm"
```

- [ ] **Step 2: 运行确认失败**

```bash
cd /Users/lzz/Documents/GitHub/GEO_search
python -m pytest backend/tests/test_annotate_router.py::test_gsm_label_model_persists -v
```
Expected: FAIL — `cannot import name 'GsmLabel'`

- [ ] **Step 3: 在 backend/models.py 末尾追加 GsmLabel，并给 GeoSample 加 relationship**

在 `GeoSample` 类里加：
```python
    labels: Mapped[list["GsmLabel"]] = relationship(back_populates="sample", cascade="all, delete-orphan")
```

在文件末尾追加：
```python
class GsmLabel(Base):
    __tablename__ = "gsm_labels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sample_id: Mapped[int] = mapped_column(ForeignKey("geo_samples.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="llm")
    sample: Mapped["GeoSample"] = relationship(back_populates="labels")
```

- [ ] **Step 4: 在 backend/database.py 的 _run_sqlite_migrations 里加 gsm_labels 迁移**

`init_db` 调用 `Base.metadata.create_all` 会自动建新表，无需手动 ALTER。确认 `backend/models.py` 被 import 即可（已有 `import backend.models`）。

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m pytest backend/tests/test_annotate_router.py::test_gsm_label_model_persists -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/models.py backend/tests/test_annotate_router.py
git commit -m "feat: add GsmLabel model for GSM-level annotation"
```

---

### Task 2: LLM GSM 标注 Prompt 和方法

**Files:**
- Modify: `backend/worker/llm_client.py`

- [ ] **Step 1: 在 backend/worker/llm_client.py 的 SCREENING_PROMPT_TEMPLATE 之前插入 GSM prompt**

```python
GSM_LABEL_PROMPT_TEMPLATE = """\
你是一个严格的样本级数据标注助手，需要根据提供的 GSM 元数据和所属 GSE 背景，判断该样本是否符合纳入标准。

你只能基于提供的元数据进行判断，不允许猜测未提供的信息。若关键信息缺失，标注为"信息不足"，gsm_available 使用"待确认"。

## 纳入标准

1. 细胞来源：必须为人源 iPSC、ESC 或 PSC
2. 分化终点：必须有明确的分化目标细胞类型或阶段
3. 实验环境：必须为 in vitro

## GSE 背景

{gse_summary}

## GSM 元数据

GSM_ID: {gsm_id}
Title: {title}
Organism: {organism}
BioSample: {biosample_id}
Characteristics: {characteristics}

## 输出要求

请严格输出 JSON，不要输出 Markdown，不要输出代码块。

{{
  "细胞来源": "iPSC / ESC / PSC / 其他 / 信息不足",
  "分化终点": "简短终点描述，无明确证据则为空字符串",
  "分化时间点": "D7 / D14 等，无明确证据则为空字符串",
  "是否有原始数据": "是 / 否 / 不明确",
  "gsm_available": "可用 / 不可用 / 待确认"
}}

## 判定规则

- gsm_available = 可用：细胞来源明确为 iPSC/ESC/PSC，分化终点有证据，in vitro
- gsm_available = 不可用：任一关键项明确不符合
- gsm_available = 待确认：关键信息不足
"""
```

- [ ] **Step 2: 在 LLMClient 类里追加 annotate_gsm 方法**

```python
    async def annotate_gsm(self, gsm_id: str, title: str, organism: str,
                            biosample_id: str, characteristics: str,
                            gse_summary: str) -> dict:
        prompt = GSM_LABEL_PROMPT_TEMPLATE.format(
            gsm_id=gsm_id, title=title, organism=organism,
            biosample_id=biosample_id, characteristics=characteristics,
            gse_summary=gse_summary,
        )
        response = await self._client.chat.completions.create(
            model=self.model, temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        return self._parse_json(raw)
```

- [ ] **Step 3: Commit**

```bash
git add backend/worker/llm_client.py
git commit -m "feat: add GSM annotation prompt and LLMClient.annotate_gsm"
```

---

### Task 3: 后端 worker — _run_gsm_annotation_async

**Files:**
- Modify: `backend/worker/tasks.py`
- Test: `backend/tests/test_annotate_router.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_annotate_router.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_run_gsm_annotation_async_persists_labels(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult, GeoSample, GsmLabel, LLMConfig
    from backend.worker.tasks import _run_gsm_annotation_async
    from unittest.mock import AsyncMock, MagicMock, patch
    import sqlalchemy

    async with AsyncSessionLocal() as db:
        task = ScreeningTask(name="gsm_ann_task", source="geo", criteria_text="", owner_id=1)
        db.add(task)
        await db.flush()
        sr = ScreeningResult(task_id=task.id, dataset_id="GSE_ANN1",
                             description="iPSC differentiation study")
        db.add(sr)
        await db.flush()
        sample = GeoSample(result_id=sr.id, gsm_id="GSM_ANN1",
                           title="Day 10 iPSC", organism="Homo sapiens", biosample_id="SAMN001")
        db.add(sample)
        db.add(LLMConfig(owner_id=1, provider="deepseek", api_key="sk-test2", model="deepseek-chat"))
        await db.commit()
        result_id = sr.id
        sample_id = sample.id

    mock_llm = MagicMock()
    mock_llm.annotate_gsm = AsyncMock(return_value={
        "细胞来源": "iPSC",
        "分化终点": "神经细胞",
        "分化时间点": "D10",
        "是否有原始数据": "是",
        "gsm_available": "可用",
    })
    with patch("backend.worker.tasks.LLMClient", return_value=mock_llm):
        await _run_gsm_annotation_async(result_id)

    async with AsyncSessionLocal() as db:
        labels = (await db.execute(
            sqlalchemy.select(GsmLabel).where(GsmLabel.sample_id == sample_id).order_by(GsmLabel.key)
        )).scalars().all()

    label_map = {l.key: l.value for l in labels}
    assert label_map["细胞来源"] == "iPSC"
    assert label_map["gsm_available"] == "可用"
    assert all(l.source == "llm" for l in labels)
```

- [ ] **Step 2: 运行确认失败**

```bash
python -m pytest backend/tests/test_annotate_router.py::test_run_gsm_annotation_async_persists_labels -v
```
Expected: FAIL — `cannot import name '_run_gsm_annotation_async'`

- [ ] **Step 3: 在 backend/worker/tasks.py 末尾追加 _run_gsm_annotation_async**

先在文件顶部 import 里加 `GsmLabel`（已有 `GeoLabel`，同行追加）：
```python
from backend.models import ScreeningTask, ScreeningResult, LLMConfig, GeoLabel, GsmLabel
```

然后在文件末尾追加：

```python
async def _run_gsm_annotation_async(result_id: int):
    async with AsyncSessionLocal() as db:
        sr = (await db.execute(
            select(ScreeningResult)
            .options(selectinload(ScreeningResult.samples))
            .where(ScreeningResult.id == result_id)
        )).scalar_one_or_none()
        if not sr:
            return
        task = (await db.execute(
            select(ScreeningTask).where(ScreeningTask.id == sr.task_id)
        )).scalar_one_or_none()
        if not task:
            return
        cfg = (await db.execute(
            select(LLMConfig).where(LLMConfig.owner_id == task.owner_id)
        )).scalar_one_or_none()
        if not cfg or not cfg.api_key:
            return
        llm = LLMClient(provider=cfg.provider, api_key=cfg.api_key,
                        base_url=cfg.base_url, model=cfg.model, temperature=0)
        gse_summary = sr.description or ""
        for sample in sr.samples:
            try:
                extracted = await llm.annotate_gsm(
                    gsm_id=sample.gsm_id,
                    title=sample.title or "",
                    organism=sample.organism or "",
                    biosample_id=sample.biosample_id or "",
                    characteristics="",
                    gse_summary=gse_summary,
                )
                existing = (await db.execute(
                    select(GsmLabel).where(GsmLabel.sample_id == sample.id)
                )).scalars().all()
                existing_by_key = {l.key: l for l in existing}
                for key, value in extracted.items():
                    ex = existing_by_key.get(key)
                    if ex and ex.source == "human":
                        continue
                    if ex:
                        ex.value = str(value) if value is not None else None
                    else:
                        db.add(GsmLabel(sample_id=sample.id, key=key,
                                        value=str(value) if value is not None else None,
                                        source="llm"))
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.warning("GSM annotation error for %s: %s", sample.gsm_id, exc)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest backend/tests/test_annotate_router.py::test_run_gsm_annotation_async_persists_labels -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/worker/tasks.py backend/tests/test_annotate_router.py
git commit -m "feat: add _run_gsm_annotation_async worker"
```

---

### Task 4: 后端 API 端点

**Files:**
- Modify: `backend/routers/annotate.py`
- Test: `backend/tests/test_annotate_router.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_annotate_router.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_gsm_label_api_get_put_and_trigger(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult, GeoSample, LLMConfig
    from unittest.mock import patch

    async with AsyncSessionLocal() as db:
        task = ScreeningTask(name="gsm_api_task", source="geo", criteria_text="", owner_id=1)
        db.add(task)
        await db.flush()
        sr = ScreeningResult(task_id=task.id, dataset_id="GSE_API1")
        db.add(sr)
        await db.flush()
        sample = GeoSample(result_id=sr.id, gsm_id="GSM_API1", title="API sample")
        db.add(sample)
        db.add(LLMConfig(owner_id=1, provider="deepseek", api_key="sk-api", model="deepseek-chat"))
        await db.commit()
        result_id = sr.id
        sample_id = sample.id

    # GET labels — empty
    r = await auth_client.get(f"/annotate/samples/{sample_id}/labels")
    assert r.status_code == 200
    assert r.json() == []

    # PUT label — human
    r = await auth_client.put(f"/annotate/samples/{sample_id}/labels",
                               json={"key": "细胞来源", "value": "iPSC"})
    assert r.status_code == 200
    assert r.json()["source"] == "human"
    assert r.json()["value"] == "iPSC"

    # GET labels — now has one
    r = await auth_client.get(f"/annotate/samples/{sample_id}/labels")
    assert len(r.json()) == 1

    # POST trigger
    with patch("backend.routers.annotate.dispatch_or_run_inline", return_value="queued") as m:
        r = await auth_client.post(f"/annotate/results/{result_id}/gsm-labels/run")
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    m.assert_called_once()
```

- [ ] **Step 2: 运行确认失败**

```bash
python -m pytest backend/tests/test_annotate_router.py::test_gsm_label_api_get_put_and_trigger -v
```
Expected: FAIL — 404 on new endpoints

- [ ] **Step 3: 在 backend/routers/annotate.py 追加三个端点**

在文件顶部 import 里加 `GsmLabel`：
```python
from backend.models import ScreeningResult, GeoLabel, ScreeningTask, User, GeoSample, GsmLabel
```

在文件末尾追加：

```python
@router.get("/samples/{sample_id}/labels")
async def get_gsm_labels(sample_id: int, db: AsyncSession = Depends(get_db),
                          user: User = Depends(get_current_user)):
    rows = (await db.execute(
        select(GsmLabel).where(GsmLabel.sample_id == sample_id)
    )).scalars().all()
    return [{"id": r.id, "key": r.key, "value": r.value, "source": r.source} for r in rows]


@router.put("/samples/{sample_id}/labels")
async def upsert_gsm_label(sample_id: int, body: LabelUpsert,
                            db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)):
    existing = (await db.execute(
        select(GsmLabel).where(GsmLabel.sample_id == sample_id, GsmLabel.key == body.key)
    )).scalar_one_or_none()
    if existing:
        existing.value = body.value
        existing.source = "human"
        await db.commit()
        await db.refresh(existing)
        return {"id": existing.id, "key": existing.key, "value": existing.value, "source": existing.source}
    label = GsmLabel(sample_id=sample_id, key=body.key, value=body.value, source="human")
    db.add(label)
    await db.commit()
    await db.refresh(label)
    return {"id": label.id, "key": label.key, "value": label.value, "source": label.source}


@router.post("/results/{result_id}/gsm-labels/run")
async def trigger_gsm_annotation(result_id: int, db: AsyncSession = Depends(get_db),
                                   user: User = Depends(get_current_user)):
    sr = (await db.execute(
        select(ScreeningResult).where(ScreeningResult.id == result_id)
    )).scalar_one_or_none()
    if not sr:
        raise HTTPException(status_code=404, detail="Not found")
    from backend.worker.tasks import _run_gsm_annotation_async
    status = dispatch_or_run_inline(
        delay_call=lambda: None,
        inline_coro_factory=lambda: _run_gsm_annotation_async(result_id),
    )
    return {"status": status}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest backend/tests/test_annotate_router.py::test_gsm_label_api_get_put_and_trigger -v
```
Expected: PASS

- [ ] **Step 5: 运行全套测试确认无回归**

```bash
python -m pytest backend/tests/test_annotate_router.py -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/routers/annotate.py backend/tests/test_annotate_router.py
git commit -m "feat: add GSM label API endpoints"
```

---

### Task 5: 前端 — GSM 标注按钮和标签展示

**Files:**
- Modify: `frontend/templates/tasks_detail.html`

- [ ] **Step 1: 在 GSM 样本表格的展开行里加"标注 GSM"按钮**

找到 `tasks_detail.html` 里 `<div x-show="r.samples && r.samples.length > 0">` 这段，在 `<p class="text-xs font-semibold text-gray-500 mb-2">样本列表 (GSM)</p>` 前插入按钮：

```html
<div class="flex items-center justify-between mb-2">
  <p class="text-xs font-semibold text-gray-500">样本列表 (GSM)</p>
  <button @click="runGsmAnnotation(r.id)"
          class="text-xs bg-blue-50 hover:bg-blue-100 text-blue-700 px-3 py-1 rounded-lg border border-blue-200">
    标注 GSM
  </button>
</div>
```

- [ ] **Step 2: 在 GSM 表格每行加展开标签的交互**

将现有 GSM `<tr>` 改为可点击展开，在其下方加标签行。找到：
```html
<template x-for="s in r.samples" :key="s.gsm_id">
  <tr>
```
替换为：
```html
<template x-for="s in r.samples" :key="s.gsm_id">
  <tr @click="toggleGsm(s.gsm_id)" class="cursor-pointer hover:bg-gray-50">
```

在 `</tr>` 后追加标签展开行：
```html
  <tr x-show="expandedGsm.has(s.gsm_id)" x-data="gsmLabelEditor(s)">
    <td colspan="5" class="px-3 py-2 bg-slate-50">
      <div class="flex flex-wrap gap-1">
        <template x-for="lbl in gsmLabels" :key="lbl.key">
          <span :class="lbl.key === 'gsm_available' ? gsmAvailClass(lbl.value) : 'bg-gray-100 text-gray-700'"
                class="text-xs px-2 py-0.5 rounded-full font-medium"
                x-text="lbl.key + ': ' + (lbl.value || '—')"></span>
        </template>
        <span x-show="gsmLabels.length === 0" class="text-xs text-gray-400">暂无标注</span>
      </div>
    </td>
  </tr>
```

- [ ] **Step 3: 在 taskDetailPage 的 Alpine.js 里加 expandedGsm、toggleGsm、runGsmAnnotation**

在 `return {` 块里加：
```javascript
expandedGsm: new Set(),
toggleGsm(gsmId) {
  if (this.expandedGsm.has(gsmId)) this.expandedGsm.delete(gsmId);
  else this.expandedGsm.add(gsmId);
  this.expandedGsm = new Set(this.expandedGsm);
},
async runGsmAnnotation(resultId) {
  const r = await fetch('/annotate/results/' + resultId + '/gsm-labels/run', {method: 'POST'});
  if (r.ok) {
    await this.loadResults();
  }
},
```

- [ ] **Step 4: 在 script 末尾加 gsmLabelEditor 函数**

```javascript
function gsmLabelEditor(sample) {
  return {
    sampleId: sample.id,
    gsmLabels: [],
    async init() {
      const r = await fetch('/annotate/samples/' + this.sampleId + '/labels');
      if (r.ok) this.gsmLabels = await r.json();
    },
    gsmAvailClass(v) {
      return {
        '可用': 'bg-green-100 text-green-700',
        '不可用': 'bg-red-100 text-red-700',
        '待确认': 'bg-yellow-100 text-yellow-700',
      }[v] || 'bg-gray-100 text-gray-700';
    }
  }
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/templates/tasks_detail.html
git commit -m "feat: add GSM annotation button and label display in task detail"
```

---

### Task 6: 全套测试 + 验收

- [ ] **Step 1: 运行全部测试**

```bash
python -m pytest backend/tests/ -v
```
Expected: all PASS

- [ ] **Step 2: 启动后端，手动验收**

```
uvicorn backend.main:app --reload
```

访问一个有 GSM 样本的 Task 详情页，展开一条 GSE，点击"标注 GSM"，等待完成后展开 GSM 行，确认标签显示正确。

- [ ] **Step 3: 最终 commit（如有遗漏文件）**

```bash
git add -A
git commit -m "feat: GSM annotation complete"
```
