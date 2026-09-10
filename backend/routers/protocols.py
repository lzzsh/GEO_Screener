import asyncio
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from kombu.exceptions import OperationalError
from pydantic import BaseModel, Field
from sqlalchemy import select, update, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.auth import get_current_user
from backend.database import get_db
from backend.models import (User, ScreeningTask, ScreeningResult, LLMConfig, ProtocolJob,
                            ProtocolItem, ProtocolDocument, ProtocolRevision, ProtocolSample)
from backend.protocol_schema import COLUMNS, validate_extraction, to_tsv
from backend.worker.protocol_documents import save_document, document_context, document_root, MAX_FILE_BYTES, read_material_manifest, protocol_pages
from backend.worker.protocol_tasks import ACTIVE_STATUSES, process_protocol_item, run_protocol_item, process_protocol_sample, run_protocol_sample

router = APIRouter(prefix='/api/protocols', tags=['protocols'])
_inline_tasks = set()


class CreateJob(BaseModel):
    extraction_unit: Literal['gsm', 'article'] = 'gsm'
    task_id: int
    result_ids: list[int] | None = Field(default=None, max_length=2000)
    name: str | None = Field(default=None, max_length=256)


class SaveRevision(BaseModel):
    payload: dict
    base_revision_id: int | None = None
    expected_active_revision_id: int | None = None
    reviewed: bool = False


async def owned_job(db, job_id, user):
    job = await db.get(ProtocolJob, job_id)
    if not job or job.owner_id != user.id:
        raise HTTPException(404, '提取任务不存在')
    return job


async def owned_item(db, item_id, user):
    item = await db.get(ProtocolItem, item_id)
    if not item:
        raise HTTPException(404, '提取记录不存在')
    await owned_job(db, item.job_id, user)
    return item


def item_data(item):
    snapshot = json.loads(item.snapshot_json)
    return {'id': item.id, 'job_id': item.job_id, 'source_result_id': item.source_result_id,
            'dataset_id': snapshot['dataset_id'], 'title': snapshot.get('title', ''),
            'status': item.status, 'error': item.error, 'updated_at': item.updated_at,
            'active_revision_id': item.active_revision_id,
            'stale': item.status in ACTIVE_STATUSES and item.updated_at < datetime.utcnow() - timedelta(minutes=20)}


async def owned_sample(db, sample_id, user):
    sample = await db.get(ProtocolSample, sample_id)
    if not sample:
        raise HTTPException(404, 'GSM 提取记录不存在')
    item = await owned_item(db, sample.item_id, user)
    return sample, item


def sample_data(sample, item):
    result = item_data(item)
    result.update(id=sample.id, source_item_id=item.id, gsm_id=sample.gsm_id,
                  article_title=result['title'], title=json.loads(sample.snapshot_json).get('title', ''),
                  status=sample.status, error=sample.error, active_revision_id=sample.active_revision_id,
                  updated_at=sample.updated_at,
                  stale=sample.status in ACTIVE_STATUSES and sample.updated_at < datetime.utcnow() - timedelta(minutes=20))
    if sample.status in {'ready', 'waiting_material'} and item.status in ACTIVE_STATUSES:
        result.update(status=item.status, error=item.error)
    elif not sample.error and item.error and item.status in {'failed', 'waiting_material'}:
        result['error'] = item.error
    return result


async def job_records(db, job):
    parents = list((await db.execute(select(ProtocolItem).where(ProtocolItem.job_id == job.id).order_by(ProtocolItem.id))).scalars())
    if job.extraction_unit != 'gsm':
        return parents, [item_data(item) for item in parents]
    lookup = {item.id: item for item in parents}
    samples = list((await db.execute(select(ProtocolSample).where(ProtocolSample.item_id.in_(lookup)).order_by(ProtocolSample.id))).scalars())
    return samples, [sample_data(sample, lookup[sample.item_id]) for sample in samples]


async def enqueue_sample(sample_id, token):
    if os.getenv('PROTOCOL_EXECUTION', 'celery') != 'inline':
        try:
            await asyncio.to_thread(run_protocol_sample.apply_async, args=[sample_id, token], retry=False)
            return
        except OperationalError:
            pass
    task = asyncio.create_task(process_protocol_sample(sample_id, token))
    _inline_tasks.add(task)
    task.add_done_callback(_inline_tasks.discard)


async def queue_sample(db, sample):
    parent = await db.get(ProtocolItem, sample.item_id)
    if parent.status in ACTIVE_STATUSES:
        return False
    token = str(uuid4())
    # Lock the shared material container in the same transaction as the sample claim.
    guard = await db.execute(update(ProtocolItem).where(ProtocolItem.id == parent.id,
        ProtocolItem.status.not_in(ACTIVE_STATUSES)).values(updated_at=datetime.utcnow()))
    if not guard.rowcount:
        await db.rollback()
        return False
    claim = await db.execute(update(ProtocolSample).where(ProtocolSample.id == sample.id,
        or_(ProtocolSample.status.not_in(ACTIVE_STATUSES), ProtocolSample.updated_at < datetime.utcnow() - timedelta(minutes=20)))
        .values(status='queued', run_token=token, error=None, updated_at=datetime.utcnow()))
    await db.commit()
    if not claim.rowcount:
        return False
    try:
        await enqueue_sample(sample.id, token)
    except Exception:
        await db.execute(update(ProtocolSample).where(ProtocolSample.id == sample.id, ProtocolSample.run_token == token)
            .values(status='failed', error='无法提交任务，请重试'))
        await db.commit()
        raise HTTPException(503, '无法提交任务，请重试')
    return True


async def enqueue(item_id, token, extract, target_sample_id=None):
    if os.getenv('PROTOCOL_EXECUTION', 'celery') != 'inline':
        try:
            await asyncio.to_thread(run_protocol_item.apply_async, args=[item_id, token, extract, target_sample_id], retry=False)
            return
        except OperationalError:
            pass
    task = asyncio.create_task(process_protocol_item(item_id, token, extract, target_sample_id))
    _inline_tasks.add(task)
    task.add_done_callback(_inline_tasks.discard)


async def queue_item(db, item, extract=True, target_sample_id=None):
    active = await db.scalar(select(ProtocolSample.id).where(ProtocolSample.item_id == item.id, ProtocolSample.status.in_(ACTIVE_STATUSES), ProtocolSample.updated_at >= datetime.utcnow() - timedelta(minutes=20)).limit(1))
    if active:
        return False
    token = str(uuid4())
    claim = await db.execute(update(ProtocolItem).where(
        ProtocolItem.id == item.id,
        ~select(ProtocolSample.id).where(ProtocolSample.item_id == item.id, ProtocolSample.status.in_(ACTIVE_STATUSES), ProtocolSample.updated_at >= datetime.utcnow() - timedelta(minutes=20)).exists(),
        or_(ProtocolItem.status.not_in(ACTIVE_STATUSES),
            ProtocolItem.updated_at < datetime.utcnow() - timedelta(minutes=20)),
    ).values(status='queued', run_token=token, error=None, updated_at=datetime.utcnow()))
    await db.commit()
    if not claim.rowcount:
        return False
    try:
        if target_sample_id is None:
            await enqueue(item.id, token, extract)
        else:
            await enqueue(item.id, token, extract, target_sample_id)
    except Exception:
        await db.execute(update(ProtocolItem).where(ProtocolItem.id == item.id, ProtocolItem.run_token == token)
                         .values(status='failed', error='无法提交任务，请重试'))
        await db.commit()
        raise HTTPException(503, '无法提交任务，请重试')
    return True


async def require_llm(db, user):
    config = (await db.execute(select(LLMConfig).where(LLMConfig.owner_id == user.id, LLMConfig.is_active == True))).scalar_one_or_none()
    if not config or not config.api_key:
        raise HTTPException(400, '请先在 Settings 配置并启用 LLM')


@router.post('/jobs', status_code=201)
async def create_job(body: CreateJob, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    task = await db.get(ScreeningTask, body.task_id)
    if not task or task.owner_id != user.id:
        raise HTTPException(404, '筛选任务不存在')
    query = select(ScreeningResult).options(selectinload(ScreeningResult.samples)).where(ScreeningResult.task_id == task.id)
    if body.result_ids is None:
        query = query.where(ScreeningResult.decision == 'include')
    else:
        if not body.result_ids:
            raise HTTPException(422, '请勾选至少一条记录')
        query = query.where(ScreeningResult.id.in_(body.result_ids))
    results = list((await db.execute(query.order_by(ScreeningResult.id))).scalars())
    if body.result_ids is not None and {r.id for r in results} != set(body.result_ids):
        raise HTTPException(404, '所选记录不属于该筛选任务')
    if not results:
        raise HTTPException(400, '没有 Included 记录；也可以手动勾选待提取的记录')
    job = ProtocolJob(owner_id=user.id, source_task_id=task.id,
                      name=(body.name or f'{task.name} · Protocol')[:256], extraction_unit=body.extraction_unit)
    db.add(job); await db.flush()
    for row in results:
        snapshot = {'dataset_id': row.dataset_id, 'title': row.title, 'description': row.description,
                    'pmid': row.pmid, 'doi': row.doi, 'pdf_path': row.pdf_path,
                    'decision': row.decision, 'criteria_text': task.criteria_text,
                    'samples': [{'gsm_id': s.gsm_id, 'title': s.title, 'organism': s.organism} for s in row.samples]}
        if body.extraction_unit == 'gsm' and not snapshot['samples']:
            from backend.worker.geo_fetcher import fetch_gsm_samples
            try:
                snapshot['samples'] = await fetch_gsm_samples(row.dataset_id, full=True)
            except Exception:
                raise HTTPException(422, f'{row.dataset_id} 的 GSM 列表未能获取，请稍后重试')
            if not snapshot['samples']:
                raise HTTPException(422, f'{row.dataset_id} 没有可识别的 GSM，无法创建样本级提取')
        item = ProtocolItem(job_id=job.id, source_result_id=row.id, snapshot_json=json.dumps(snapshot, ensure_ascii=False))
        db.add(item); await db.flush()
        if body.extraction_unit == 'gsm':
            for gsm in {gsm['gsm_id']: gsm for gsm in snapshot['samples']}.values():
                db.add(ProtocolSample(item_id=item.id, gsm_id=gsm['gsm_id'], snapshot_json=json.dumps(gsm, ensure_ascii=False)))
    await db.commit()
    return {'id': job.id, 'name': job.name, 'count': len(results)}


@router.get('/jobs')
async def list_jobs(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    jobs = list((await db.execute(select(ProtocolJob).where(ProtocolJob.owner_id == user.id).order_by(ProtocolJob.id.desc()))).scalars())
    result = []
    for job in jobs:
        records, _ = await job_records(db, job)
        result.append({'id': job.id, 'name': job.name, 'source_task_id': job.source_task_id,
            'created_at': job.created_at, 'extraction_unit': job.extraction_unit,
            'counts': dict(Counter(row.status for row in records)), 'total': len(records)})
    return result


@router.get('/jobs/{job_id}')
async def get_job(job_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    job = await owned_job(db, job_id, user)
    records, items = await job_records(db, job)
    return {'id': job.id, 'name': job.name, 'source_task_id': job.source_task_id,
            'extraction_unit': job.extraction_unit, 'items': items, 'columns': COLUMNS}


@router.post('/jobs/{job_id}/run')
async def run_job(job_id: int, retry_only: bool = False, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    job = await owned_job(db, job_id, user)
    await require_llm(db, user)
    items = list((await db.execute(select(ProtocolItem).where(ProtocolItem.job_id == job_id))).scalars())
    queued = 0
    for item in items:
        if job.extraction_unit == 'gsm':
            samples = list((await db.execute(select(ProtocolSample).where(ProtocolSample.item_id == item.id))).scalars())
            if any(sample.status in {'ready', 'waiting_material', 'failed'} or (sample.status in ACTIVE_STATUSES and sample.updated_at < datetime.utcnow() - timedelta(minutes=20)) for sample in samples):
                if await queue_item(db, item):
                    queued += 1
            continue
        eligible = item.status in ({'failed', 'waiting_material'} if retry_only else {'ready', 'waiting_material', 'failed'})
        eligible = eligible or (item.status in ACTIVE_STATUSES and item.updated_at < datetime.utcnow() - timedelta(minutes=20))
        if eligible and await queue_item(db, item):
            queued += 1
    return {'queued': queued}


@router.get('/items/{item_id}')
async def get_item(item_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    item = await owned_item(db, item_id, user)
    documents = list((await db.execute(select(ProtocolDocument).where(ProtocolDocument.item_id == item.id))).scalars())
    revisions = list((await db.execute(select(ProtocolRevision).where(ProtocolRevision.item_id == item.id, ProtocolRevision.sample_id.is_(None)).order_by(ProtocolRevision.id.desc()))).scalars())
    return {**item_data(item), 'snapshot': json.loads(item.snapshot_json), 'columns': COLUMNS,
            'materials_manifest': read_material_manifest(item_id), 'material_coverage': protocol_pages(documents)[1],
            'documents': [{'id': d.id, 'name': d.name, 'kind': d.kind, 'reference': d.reference,
                           'pages': len(json.loads(d.pages_json)), 'warnings': json.loads(d.warnings_json)} for d in documents],
            'revisions': [{'id': r.id, 'source': r.source, 'reviewed': r.reviewed, 'created_at': r.created_at,
                           'payload': json.loads(r.payload_json), 'provenance': json.loads(r.provenance_json)} for r in revisions]}


@router.post('/items/{item_id}/documents', status_code=201)
async def upload_document(item_id: int, file: UploadFile = File(...),
                          kind: Literal['main', 'supplement', 'reference'] = Form('main'),
                          reference: str = Form('', max_length=2000),
                          db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    item = await owned_item(db, item_id, user)
    if item.status in ACTIVE_STATUSES:
        raise HTTPException(409, '提取进行中，完成后可添加材料')
    documents = list((await db.execute(select(ProtocolDocument).where(ProtocolDocument.item_id == item_id))).scalars())
    if len(documents) >= 20:
        raise HTTPException(400, '每条记录最多 20 份材料')
    if kind == 'reference' and not reference.strip():
        raise HTTPException(422, '引用材料须注明目标论文的引用编号或引用关系')
    content = await file.read(MAX_FILE_BYTES + 1)
    try:
        stored = await asyncio.to_thread(save_document, content, file.filename or '', item_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    existing = next((d for d in documents if d.sha256 == stored['sha256']), None)
    if existing:
        return {'id': existing.id, 'duplicate': True}
    # Do not attach new documents to an in-flight extraction snapshot.
    claim = await db.execute(update(ProtocolItem).where(ProtocolItem.id == item_id, ProtocolItem.status.not_in(ACTIVE_STATUSES))
                             .values(updated_at=datetime.utcnow()))
    active_sample = await db.scalar(select(ProtocolSample.id).where(ProtocolSample.item_id == item_id, ProtocolSample.status.in_(ACTIVE_STATUSES)).limit(1))
    if not claim.rowcount or active_sample:
        await db.rollback()
        raise HTTPException(409, '提取已开始，请稍后上传')
    doc = ProtocolDocument(item_id=item.id, kind=kind, reference=reference.strip(), **stored)
    db.add(doc)
    if not item.active_revision_id:
        item.status = 'ready'
    item.error = None
    await db.commit()
    return {'id': doc.id, 'warnings': json.loads(doc.warnings_json)}


@router.get('/documents/{document_id}')
async def get_document(document_id: int, page: int | None = Query(None, ge=1),
                       db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    doc = await db.get(ProtocolDocument, document_id)
    if not doc:
        raise HTTPException(404, '材料不存在')
    await owned_item(db, doc.item_id, user)
    if page is not None:
        match = next((p for p in json.loads(doc.pages_json) if p['page'] == page), None)
        if not match:
            raise HTTPException(404, '页码不存在')
        return match
    path = Path(doc.path).resolve()
    if not path.is_relative_to(document_root()) or not path.is_file():
        raise HTTPException(404, '材料文件不可用，请重新上传')
    import mimetypes
    media_type = mimetypes.guess_type(doc.name)[0] or 'application/octet-stream'
    return FileResponse(path, media_type=media_type, filename=doc.name,
                        content_disposition_type='inline' if path.suffix == '.pdf' else 'attachment',
                        headers={'X-Content-Type-Options': 'nosniff'})


@router.post('/items/{item_id}/run')
async def start_item(item_id: int, extract: bool = True, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    item = await owned_item(db, item_id, user)
    if extract:
        await require_llm(db, user)
    if not await queue_item(db, item, extract):
        raise HTTPException(409, '该记录正在处理，请等待；20 分钟无进度后可重试')
    return {'status': 'queued'}


@router.post('/items/{item_id}/revisions', status_code=201)
async def save_revision(item_id: int, body: SaveRevision, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    item = await owned_item(db, item_id, user)
    return await save_record_revision(db, item, item, body)


async def save_record_revision(db, item, source_item, body):
    item_id = source_item.id
    sample_id = item.id if isinstance(item, ProtocolSample) else None
    record_type = type(item)
    if item.status in ACTIVE_STATUSES:
        raise HTTPException(409, '提取进行中，请稍后保存')
    if body.expected_active_revision_id != item.active_revision_id:
        raise HTTPException(409, '结果已在其他窗口更新，请刷新后重试')
    base = await db.get(ProtocolRevision, body.base_revision_id) if body.base_revision_id else None
    if body.base_revision_id and (not base or base.item_id != item_id or base.sample_id != sample_id):
        raise HTTPException(404, '来源版本不存在')
    documents = list((await db.execute(select(ProtocolDocument).where(ProtocolDocument.item_id == item_id))).scalars())
    if not documents:
        raise HTTPException(400, '请先添加来源材料')
    if sample_id:
        from backend.worker.protocol_tasks import sample_documents
        documents = sample_documents(documents, item.gsm_id)
    snapshot = json.loads(source_item.snapshot_json)
    try:
        payload = validate_extraction(body.payload, document_context(documents), snapshot['dataset_id'],
                                      [s['gsm_id'] for s in snapshot.get('samples', [])], required_gsm_id=item.gsm_id if sample_id else None)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if body.reviewed and payload['blockers']:
        raise HTTPException(422, '无法标记已复核：' + '；'.join(payload['blockers'][:5]))
    guard = await db.execute(update(record_type).where(
        record_type.id == item.id, record_type.active_revision_id == body.expected_active_revision_id,
        record_type.status.not_in(ACTIVE_STATUSES),
    ).values(updated_at=datetime.utcnow()))
    if not guard.rowcount:
        await db.rollback()
        raise HTTPException(409, '记录已更新或开始提取，请刷新后重试')
    provenance = json.loads(base.provenance_json) if base else {}
    provenance['review_documents'] = [{'id': doc.id, 'sha256': doc.sha256} for doc in documents]
    revision = ProtocolRevision(item_id=item_id, sample_id=sample_id, parent_id=body.base_revision_id, source='human', reviewed=body.reviewed,
                                payload_json=json.dumps(payload, ensure_ascii=False),
                                provenance_json=json.dumps(provenance, ensure_ascii=False))
    db.add(revision); await db.flush()
    item.active_revision_id = revision.id
    item.status = 'reviewed' if body.reviewed else 'needs_review'
    item.error = None
    await db.commit()
    return {'id': revision.id, 'payload': payload}


@router.get('/jobs/{job_id}/export')
async def export_job(job_id: int, draft: bool = False, format: Literal['tsv', 'evidence', 'issues'] = 'tsv',
                     db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    job = await owned_job(db, job_id, user)
    items, _ = await job_records(db, job)
    revisions = list((await db.execute(select(ProtocolRevision).where(ProtocolRevision.id.in_(
        [i.active_revision_id for i in items if i.active_revision_id])))).scalars())
    selected = [r for r in revisions if draft or r.reviewed]
    if not selected:
        raise HTTPException(400, '没有可导出的已复核结果；未复核内容请使用草稿导出' if not draft else '尚无可导出的结果')
    sample_ids = {record.id: record.gsm_id for record in items if isinstance(record, ProtocolSample)}
    events, evidence, issues = [], [], []
    for revision in selected:
        payload = json.loads(revision.payload_json)
        issues.append({'item_id': revision.item_id, 'sample_id': revision.sample_id, 'gsm_id': sample_ids.get(revision.sample_id), 'revision_id': revision.id, 'reviewed': revision.reviewed,
                       'outcome': payload['outcome'], 'warnings': payload['warnings'], 'blockers': payload['blockers'],
                       'reference_requests': payload['reference_requests']})
        for row in payload['events']:
            events.append(row)
            evidence.append({'row': len(events), 'item_id': revision.item_id, 'sample_id': revision.sample_id, 'gsm_id': sample_ids.get(revision.sample_id), 'revision_id': revision.id,
                             'protocol_name': row['protocol_name'], 'evidence': row['evidence'],
                             'provenance': json.loads(revision.provenance_json)})
    if format == 'tsv':
        content, media, extension = to_tsv(events), 'text/tab-separated-values; charset=utf-8', 'tsv'
    else:
        content = json.dumps(evidence if format == 'evidence' else issues, ensure_ascii=False, indent=2)
        media, extension = 'application/json', 'json'
    name = f'protocol_{job_id}_{"draft" if draft else "reviewed"}_{format}.{extension}'
    return Response(content, media_type=media, headers={'Content-Disposition': f'attachment; filename="{name}"'})


@router.get('/samples/{sample_id}')
async def get_sample(sample_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    sample, item = await owned_sample(db, sample_id, user)
    result = await get_item(item.id, db, user)
    revisions = list((await db.execute(select(ProtocolRevision).where(ProtocolRevision.sample_id == sample.id).order_by(ProtocolRevision.id.desc()))).scalars())
    from backend.worker.protocol_tasks import sample_documents
    docs = list((await db.execute(select(ProtocolDocument).where(ProtocolDocument.item_id == item.id))).scalars())
    allowed = {d.id for d in sample_documents(docs, sample.gsm_id)}
    result.update(sample_data(sample, item))
    result['documents'] = [d for d in result['documents'] if d['id'] in allowed]
    result['material_coverage'] = [d for d in result['material_coverage'] if d['document_id'] in allowed]
    result['sample_snapshot'] = json.loads(sample.snapshot_json)
    result['revisions'] = [{'id': r.id, 'source': r.source, 'reviewed': r.reviewed, 'created_at': r.created_at,
        'payload': json.loads(r.payload_json), 'provenance': json.loads(r.provenance_json)} for r in revisions]
    return result


@router.post('/samples/{sample_id}/run')
async def start_sample(sample_id: int, extract: bool = True, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    sample, item = await owned_sample(db, sample_id, user)
    if extract:
        await require_llm(db, user)
    has_docs = await db.scalar(select(ProtocolDocument.id).where(ProtocolDocument.item_id == item.id).limit(1))
    manifest = read_material_manifest(item.id)
    needs_preparation = bool(json.loads(item.snapshot_json).get('pmid')) and (manifest.get('collection_status') != 'collected' or manifest.get('sample_metadata_version') != 'full-v1')
    if not extract or not has_docs or needs_preparation:
        # Preparation is shared. A single-sample request never starts siblings implicitly.
        if not await queue_item(db, item, extract, sample.id if extract else None):
            raise HTTPException(409, '共享材料正在处理，请等待后开始样本提取')
        return {'status': 'queued', 'preparing_materials': True}
    if not await queue_sample(db, sample):
        raise HTTPException(409, '该样本或共享材料正在处理，请稍后重试')
    return {'status': 'queued'}


@router.post('/samples/{sample_id}/revisions', status_code=201)
async def save_sample_revision(sample_id: int, body: SaveRevision, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    sample, item = await owned_sample(db, sample_id, user)
    return await save_record_revision(db, sample, item, body)
