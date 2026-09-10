"""Durable item-level extraction, leaving screening decisions untouched."""
import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import httpx
from openai import APIStatusError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from backend.database import AsyncSessionLocal
from backend.models import LLMConfig, ProtocolItem, ProtocolJob, ProtocolDocument, ProtocolRevision
from backend.protocol_schema import COLUMNS, SCHEMA_VERSION, validate_extraction
from backend.worker.celery_app import celery_app
from backend.worker.geo_fetcher import fetch_gse_detail
from backend.worker.llm_client import LLMClient
from backend.worker.pdf_fetcher import fetch_pdf, PDF_DIR
from backend.worker.protocol_documents import document_context, material_chunks, save_document, document_root, MAX_FILE_BYTES

logger = logging.getLogger(__name__)
ACTIVE_STATUSES = {'queued', 'fetching', 'extracting'}
PROMPT_PATH = Path(os.getenv('PROMPT_DIR', Path(__file__).resolve().parents[1] / 'prompts')) / 'protocol/extract_v1.txt'


class NeedMaterials(ValueError):
    pass


@celery_app.task(name='worker.protocol_tasks.run_protocol_item')
def run_protocol_item(item_id, token, extract=True):
    asyncio.run(process_protocol_item(item_id, token, extract))


async def _progress(item_id, token, status, message=None):
    async with AsyncSessionLocal() as db:
        result = await db.execute(update(ProtocolItem).where(
            ProtocolItem.id == item_id, ProtocolItem.run_token == token,
        ).values(status=status, error=message, updated_at=datetime.utcnow()))
        await db.commit()
        return bool(result.rowcount)


async def acquire_material(item_id, snapshot):
    """Prefer the existing local PDF; ambiguous publication matching needs user input."""
    legacy = snapshot.get('pdf_path')
    if legacy:
        pdf_root = Path(PDF_DIR).resolve()
        path = (pdf_root / Path(legacy).name) if Path(legacy).parts[0] == 'pdfs' else Path(legacy).resolve()
        if path.is_relative_to(pdf_root) and path.is_file():
            if path.stat().st_size > MAX_FILE_BYTES:
                raise NeedMaterials('已有 PDF 超过 30 MB，请拆分后上传')
            content = await asyncio.to_thread(path.read_bytes)
            stored = await asyncio.to_thread(save_document, content, path.name, item_id)
            return stored, snapshot.get('doi') or snapshot.get('pmid') or '已有 PDF'
    gse = snapshot['dataset_id']
    if not re.fullmatch(r'GSE\d+', gse):
        raise NeedMaterials('此记录没有可用于自动定位的 GSE，请上传正文')
    pmid = snapshot.get('pmid')
    if not pmid:
        detail = await fetch_gse_detail(gse)
        pmids = list(dict.fromkeys(detail.get('pmids') or ([detail['pmid']] if detail.get('pmid') else [])))
        if len(pmids) > 1:
            raise NeedMaterials('关联多篇论文，请核对后上传对应正文。PMID: ' + ', '.join(pmids))
        if not pmids:
            raise NeedMaterials('GEO 没有明确关联的 PMID，请上传正文及补充材料')
        pmid = pmids[0]
    directory = document_root() / str(item_id) / 'download'
    path, doi = await fetch_pdf(pmid, gse, output_dir=str(directory))
    if not path:
        raise NeedMaterials(f'未取得可用全文（PMID {pmid}），请上传 PDF 或文本材料')
    file = Path(path)
    if file.stat().st_size > MAX_FILE_BYTES:
        raise NeedMaterials('下载文件超过 30 MB，请拆分后上传')
    stored = await asyncio.to_thread(save_document, file.read_bytes(), file.name, item_id)
    return stored, doi or f'PMID:{pmid}'


async def extract_chunk(llm, snapshot, chunk):
    prompt = PROMPT_PATH.read_text(encoding='utf-8')
    response = await llm._create_chat_completion(
        model=llm.model, temperature=0, stream=True, max_tokens=8192,
        messages=[{'role': 'system', 'content': prompt}, {'role': 'user', 'content': json.dumps({
            'columns': COLUMNS, 'dataset': snapshot,
            'allowed_gsm_ids': [s['gsm_id'] for s in snapshot.get('samples', [])],
            'source_materials': chunk,
        }, ensure_ascii=False)}],
    )
    parts = []
    finish_reason = None
    try:
        async for chunk in response:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.delta.content:
                parts.append(choice.delta.content)
            if choice.finish_reason:
                finish_reason = choice.finish_reason
    finally:
        await response.close()
    if finish_reason == 'length':
        raise ValueError('模型输出达到 8192 token 限制，请减少本次材料或使用非深度推理模型')
    if not parts:
        raise ValueError('模型没有返回可解析的 protocol JSON')
    return llm._parse_json(''.join(parts))


def merge_chunks(results):
    events, requests, summaries, seen = [], [], [], {}
    for payload in results:
        if not isinstance(payload, dict) or payload.get('outcome') not in {'extracted', 'no_protocol', 'needs_sources'}:
            raise ValueError('模型未返回有效的 protocol 结果')
        if not isinstance(payload.get('events'), list):
            raise ValueError('模型未返回 events 列表')
        if payload['outcome'] == 'extracted' and not payload['events']:
            raise ValueError('模型声称已提取但没有事件')
        if payload['outcome'] == 'no_protocol' and payload['events']:
            raise ValueError('模型声称没有 protocol 却返回了事件')
        refs = payload.get('reference_requests', [])
        if not isinstance(refs, list) or any(not isinstance(r, str) for r in refs):
            raise ValueError('模型的引用请求格式不正确')
        requests.extend(refs)
        if payload['outcome'] == 'needs_sources' and not refs:
            requests.append(str(payload.get('summary') or '需要补充引用的 protocol 来源'))
        if payload.get('summary'):
            summaries.append(str(payload['summary']))
        for event in payload['events']:
            signature = json.dumps([event.get('protocol_name'), event.get('values')], sort_keys=True, ensure_ascii=False)
            if signature in seen:
                previous = seen[signature]
                for evidence in event.get('evidence', []):
                    if evidence not in previous.setdefault('evidence', []):
                        previous['evidence'].append(evidence)
            else:
                seen[signature] = event
                events.append(event)
    return {'outcome': 'needs_sources' if requests else ('extracted' if events else 'no_protocol'),
            'summary': '\n'.join(summaries), 'reference_requests': list(dict.fromkeys(requests)), 'events': events}


async def process_protocol_item(item_id, token, extract=True):
    async with AsyncSessionLocal() as db:
        # A delivery may be repeated by the broker. Exactly one worker claims it.
        claim = await db.execute(update(ProtocolItem).where(
            ProtocolItem.id == item_id, ProtocolItem.run_token == token, ProtocolItem.status == 'queued',
        ).values(status='fetching', updated_at=datetime.utcnow()))
        await db.commit()
        if not claim.rowcount:
            return
        item = await db.get(ProtocolItem, item_id)
        job = await db.get(ProtocolJob, item.job_id)
        snapshot = json.loads(item.snapshot_json)
        owner_id = job.owner_id
    llm = None
    try:
        async with AsyncSessionLocal() as db:
            documents = list((await db.execute(select(ProtocolDocument).where(ProtocolDocument.item_id == item_id))).scalars())
        if not documents:
            stored, reference = await acquire_material(item_id, snapshot)
            async with AsyncSessionLocal() as db:
                current = await db.get(ProtocolItem, item_id)
                if current.run_token != token:
                    return
                db.add(ProtocolDocument(item_id=item_id, kind='main', reference=reference, **stored))
                try:
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                documents = list((await db.execute(select(ProtocolDocument).where(ProtocolDocument.item_id == item_id))).scalars())
        if not extract:
            async with AsyncSessionLocal() as db:
                current = await db.get(ProtocolItem, item_id)
                revision = await db.get(ProtocolRevision, current.active_revision_id) if current.active_revision_id else None
            await _progress(item_id, token, 'reviewed' if revision and revision.reviewed else ('needs_review' if revision else 'ready'))
            return
        async with AsyncSessionLocal() as db:
            config = (await db.execute(select(LLMConfig).where(LLMConfig.owner_id == owner_id, LLMConfig.is_active == True))).scalar_one_or_none()
            if not config or not config.api_key:
                raise ValueError('请先在 Settings 配置并启用 LLM')
            llm = LLMClient(config.provider, config.api_key, config.base_url, config.model, temperature=0)
            llm._client = llm._client.with_options(timeout=httpx.Timeout(90, connect=15), max_retries=1)
        chunks = material_chunks(documents)
        if len(chunks) > 80:
            raise ValueError('材料超过单次 80 个文本块限制，请按 protocol 分批上传')
        results = []
        for index, chunk in enumerate(chunks, 1):
            if not await _progress(item_id, token, 'extracting', f'正在提取材料块 {index}/{len(chunks)}'):
                return
            results.append(await asyncio.wait_for(extract_chunk(llm, snapshot, chunk), timeout=300))
        payload = validate_extraction(merge_chunks(results), document_context(documents), snapshot['dataset_id'],
                                      [s['gsm_id'] for s in snapshot.get('samples', [])])
        doc_warnings = [f'{doc.name}: {warning}' for doc in documents for warning in json.loads(doc.warnings_json)]
        payload['warnings'].extend(doc_warnings)
        provenance = {'schema_version': SCHEMA_VERSION, 'model': llm.model,
                      'prompt_sha256': hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest(),
                      'documents': [{'id': doc.id, 'sha256': doc.sha256} for doc in documents], 'chunks': len(chunks)}
        async with AsyncSessionLocal() as db:
            current = await db.get(ProtocolItem, item_id)
            if current.run_token != token:
                return
            previous = await db.get(ProtocolRevision, current.active_revision_id) if current.active_revision_id else None
            revision = ProtocolRevision(item_id=item_id, source='machine',
                                        payload_json=json.dumps(payload, ensure_ascii=False),
                                        provenance_json=json.dumps(provenance, ensure_ascii=False))
            db.add(revision); await db.flush()
            if not previous or previous.source != 'human':
                current.active_revision_id = revision.id
                current.status = {'needs_sources': 'needs_sources', 'no_protocol': 'no_protocol'}.get(payload['outcome'], 'needs_review')
            else:
                current.status = 'reviewed' if previous.reviewed else 'needs_review'
            current.error = None
            current.updated_at = datetime.utcnow()
            await db.commit()
    except NeedMaterials as exc:
        await _progress(item_id, token, 'waiting_material', str(exc))
    except Exception as exc:
        # Never return upstream request headers or credentials to the UI.
        if isinstance(exc, APIStatusError):
            message = f'模型服务返回 HTTP {exc.status_code}，请检查 Settings 中的服务配置或稍后重试'
        else:
            message = str(exc) if isinstance(exc, ValueError) else f'提取失败（{type(exc).__name__}），请检查材料或模型连接后重试'
        logger.warning('Protocol extraction failed for item=%s (%s)', item_id, type(exc).__name__)
        await _progress(item_id, token, 'failed', message[:1000])
    finally:
        if llm:
            await llm._client.close()
