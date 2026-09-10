"""Durable item-level extraction, leaving screening decisions untouched."""
import asyncio
import hashlib
import json
import logging
import os
import re
import weakref
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from openai import APIStatusError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from backend.database import AsyncSessionLocal
from backend.models import LLMConfig, ProtocolItem, ProtocolJob, ProtocolDocument, ProtocolRevision, ProtocolSample
from backend.protocol_schema import COLUMNS, SCHEMA_VERSION, validate_extraction
from backend.worker.celery_app import celery_app
from backend.worker.geo_fetcher import fetch_gse_detail, fetch_gsm_samples
from backend.worker.llm_client import LLMClient
from backend.worker.pdf_fetcher import fetch_pdf, PDF_DIR
from backend.worker.protocol_documents import (document_context, material_chunks, save_document, document_root,
    MAX_FILE_BYTES, protocol_pages, material_manifest_path, read_material_manifest)
from backend.worker.protocol_sources import collect_article_sources

logger = logging.getLogger(__name__)
ACTIVE_STATUSES = {'queued', 'fetching', 'extracting'}
PROMPT_PATH = Path(os.getenv('PROMPT_DIR', Path(__file__).resolve().parents[1] / 'prompts')) / 'protocol/extract_v1.txt'
SKILL_DIR = Path(__file__).resolve().parents[1] / 'prompts/protocol/skills'


def extraction_prompt():
    from backend.prompt_store import BUNDLED_PROMPTS
    paths = [SKILL_DIR / (name + '.md') for name in ('perturbation-extractor', 'protocol-chain-annotator')]
    if any(not path.is_file() for path in paths):
        raise ValueError('Protocol skill files are missing; reinstall the complete release package')
    skills = '\n\n'.join(path.read_text(encoding='utf-8') for path in paths)
    contract = PROMPT_PATH.read_text(encoding='utf-8') if PROMPT_PATH.is_file() else ''
    if not contract.strip():
        contract = (BUNDLED_PROMPTS / 'protocol/extract_v1.txt').read_text(encoding='utf-8')
    gsm_contract = (BUNDLED_PROMPTS / 'protocol/gsm_contract.txt').read_text(encoding='utf-8')
    return skills + '\n\n# Application output contract (overrides conflicting skill examples)\n\n' + contract + '\n\n' + gsm_contract


class NeedMaterials(ValueError):
    pass


class OutputLimitError(ValueError):
    pass


@celery_app.task(name='worker.protocol_tasks.run_protocol_item')
def run_protocol_item(item_id, token, extract=True, target_sample_id=None):
    asyncio.run(process_protocol_item(item_id, token, extract, target_sample_id))


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
    snapshot['pmid'] = str(pmid)
    directory = document_root() / str(item_id) / 'download'
    path, doi = await fetch_pdf(pmid, gse, output_dir=str(directory))
    if not path:
        raise NeedMaterials(f'未取得可用全文（PMID {pmid}），请上传 PDF 或文本材料')
    file = Path(path)
    if file.stat().st_size > MAX_FILE_BYTES:
        raise NeedMaterials('下载文件超过 30 MB，请拆分后上传')
    stored = await asyncio.to_thread(save_document, file.read_bytes(), file.name, item_id)
    return stored, doi or f'PMID:{pmid}'


async def enrich_materials(item_id, token, snapshot, documents):
    """Collect same-article Methods/supplements and preserve a reviewable inventory."""
    manifest = read_material_manifest(item_id)
    new_documents = []
    incomplete = any(entry['status'] in {'unavailable', 'parse_failed'} for entry in manifest.get('inventory', []))
    if snapshot.get('pmid') and (manifest.get('collection_status') != 'collected' or incomplete):
        await _progress(item_id, token, 'fetching', '正在获取 Methods 与补充材料')
        try:
            collected = await collect_article_sources(snapshot['pmid'])
            new_documents = collected.pop('documents')
            manifest.update(collected, collection_status='collected')
            manifest.pop('collection_error', None)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            manifest.update(collection_status='unavailable',
                            collection_error=f'自动 Methods / 补充材料获取失败（{type(exc).__name__}），保留已有材料，请核对来源')
    elif not snapshot.get('pmid'):
        manifest.update(collection_status='manual', collection_note='未关联明确 PMID，使用已上传材料，请确认补充材料齐全')
    if snapshot.get('pmid') and manifest.get('sample_metadata_version') != 'full-v1':
        try:
            samples = {s['gsm_id']: s for s in await fetch_gsm_samples(snapshot['dataset_id'], full=True)}
            matched = [dict(s, **{k: v for k, v in samples.get(s['gsm_id'], {}).items() if v}) for s in snapshot.get('samples', [])]
            snapshot['samples'] = matched
            manifest['sample_metadata_collected'] = bool(samples)
            if samples:
                manifest['sample_metadata_version'] = 'full-v1'
            if matched and samples:
                new_documents.append({'name': snapshot['dataset_id'] + '-GSM-metadata.json.txt', 'kind': 'metadata',
                    'reference': 'https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=' + snapshot['dataset_id'],
                    'content': json.dumps(matched, ensure_ascii=False, indent=2).encode('utf-8')})
        except (httpx.HTTPError, ValueError):
            manifest['sample_metadata_collected'] = False
    known = {doc.sha256 for doc in documents}
    async with AsyncSessionLocal() as db:
        current = await db.get(ProtocolItem, item_id)
        if current.run_token != token:
            raise asyncio.CancelledError
        for source in new_documents:
            entry = next((e for e in manifest.get('inventory', []) if e['name'] == source['name']), None)
            try:
                stored = await asyncio.to_thread(save_document, source['content'], source['name'], item_id)
            except Exception as exc:
                if entry is not None:
                    entry.update(status='parse_failed', reason=f'附件未成功解析（{type(exc).__name__}），请核对原文件')
                continue
            if stored['sha256'] not in known:
                db.add(ProtocolDocument(item_id=item_id, kind=source['kind'], reference=source['reference'], **stored))
                known.add(stored['sha256'])
            if entry is not None:
                entry.update(status='parsed', sha256=stored['sha256'], warnings=json.loads(stored['warnings_json']))
        current.snapshot_json = json.dumps(snapshot, ensure_ascii=False)
        await db.commit()
        documents = list((await db.execute(select(ProtocolDocument).where(ProtocolDocument.item_id == item_id))).scalars())
    _, manifest['coverage'] = protocol_pages(documents)
    destination = material_manifest_path(item_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.' + token + '.partial')
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(destination)
    return documents, manifest


async def extract_chunk(llm, snapshot, chunk):
    prompt = extraction_prompt()
    response = await llm._create_chat_completion(
        model=llm.model, temperature=0, stream=True,
        messages=[{'role': 'system', 'content': prompt}, {'role': 'user', 'content': json.dumps({
            'columns': COLUMNS, 'dataset': snapshot,
            'target_gsm_id': snapshot.get('target_gsm_id'),
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
        raise OutputLimitError('模型服务截断了 protocol 输出，请将材料进一步拆分后重试')
    if not parts:
        raise ValueError('模型没有返回可解析的 protocol JSON')
    return llm._parse_json(''.join(parts))


async def extract_with_split(llm, snapshot, chunk, progress, depth=0):
    """Retry only a truncated block, with a bounded split and unchanged source pages."""
    if not await progress():
        raise asyncio.CancelledError
    try:
        request = asyncio.create_task(extract_chunk(llm, snapshot, chunk))
        try:
            while not request.done():
                done, _ = await asyncio.wait({request}, timeout=30)
                if not done and not await progress():
                    raise asyncio.CancelledError
            return [await request]
        finally:
            if not request.done():
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
    except OutputLimitError:
        if depth >= 2:
            raise
        if len(chunk) > 1:
            middle = len(chunk) // 2
            halves = [chunk[:middle], chunk[middle:]]
        elif chunk and len(chunk[0]['text']) > 4000:
            section = chunk[0]
            middle = len(section['text']) // 2
            # Preserve a boundary overlap; evidence still points to the original page.
            halves = [[dict(section, text=section['text'][:middle + 250])],
                      [dict(section, text=section['text'][middle - 250:])]]
        else:
            raise
        results = []
        for half in halves:
            results.extend(await extract_with_split(llm, snapshot, half, progress, depth + 1))
        return results


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
        if refs is None:
            refs = []
        elif isinstance(refs, str):
            refs = [refs]
        if isinstance(refs, list):
            # Some compatible models return structured citation requests. Keep every field
            # as reviewable text instead of discarding the otherwise valid extraction.
            refs = [json.dumps(ref, ensure_ascii=False, sort_keys=True) if isinstance(ref, dict) else ref for ref in refs]
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


async def process_protocol_item(item_id, token, extract=True, target_sample_id=None):
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
        pdf_warning = None
        if not documents:
            try:
                stored, reference = await acquire_material(item_id, snapshot)
            except NeedMaterials as exc:
                if not snapshot.get('pmid'):
                    raise
                stored, pdf_warning = None, str(exc)
            async with AsyncSessionLocal() as db:
                current = await db.get(ProtocolItem, item_id)
                if current.run_token != token:
                    return
                current.snapshot_json = json.dumps(snapshot, ensure_ascii=False)
                if stored:
                    db.add(ProtocolDocument(item_id=item_id, kind='main', reference=reference, **stored))
                try:
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                documents = list((await db.execute(select(ProtocolDocument).where(ProtocolDocument.item_id == item_id))).scalars())
        documents, manifest = await enrich_materials(item_id, token, snapshot, documents)
        if pdf_warning:
            manifest['pdf_warning'] = pdf_warning
            material_manifest_path(item_id).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        if not documents:
            raise NeedMaterials('未取得可用 Methods 或全文，请补充正文及方法附件')
        snapshot['materials_manifest'] = manifest
        if job.extraction_unit == 'gsm':
            async with AsyncSessionLocal() as db:
                samples = list((await db.execute(select(ProtocolSample).where(ProtocolSample.item_id == item_id))).scalars())
                metadata = {sample['gsm_id']: sample for sample in snapshot.get('samples', [])}
                for sample in samples:
                    sample.snapshot_json = json.dumps(metadata.get(sample.gsm_id, json.loads(sample.snapshot_json)), ensure_ascii=False)
                    if sample.status == 'waiting_material':
                        sample.status = 'ready'
                await db.commit()
            await _progress(item_id, token, 'ready')
            if extract:
                from backend.routers.protocols import queue_sample
                async with AsyncSessionLocal() as db:
                    samples = list((await db.execute(select(ProtocolSample).where(ProtocolSample.item_id == item_id))).scalars())
                    for sample in samples:
                        if (target_sample_id is None and (sample.status in {'ready', 'waiting_material', 'failed'} or (sample.status in ACTIVE_STATUSES and sample.updated_at < datetime.utcnow() - timedelta(minutes=20)))) or sample.id == target_sample_id:
                            await queue_sample(db, sample)
            return
        if not extract:
            async with AsyncSessionLocal() as db:
                current = await db.get(ProtocolItem, item_id)
                revision = await db.get(ProtocolRevision, current.active_revision_id) if current.active_revision_id else None
            await _progress(item_id, token, 'reviewed' if revision and revision.reviewed else ('needs_review' if revision else 'ready'))
            return
        await extract_materials(item_id, token, snapshot, documents, manifest, owner_id,
            lambda status, message=None: _progress(item_id, token, status, message))
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


async def extract_materials(item_id, token, snapshot, documents, manifest, owner_id, progress_callback, sample_id=None):
    llm = None
    try:
        async with AsyncSessionLocal() as db:
            config = (await db.execute(select(LLMConfig).where(LLMConfig.owner_id == owner_id, LLMConfig.is_active == True))).scalar_one_or_none()
            if not config or not config.api_key:
                raise ValueError('请先在 Settings 配置并启用 LLM')
            llm = LLMClient(config.provider, config.api_key, config.base_url, config.model, temperature=0)
            llm._client = llm._client.with_options(timeout=httpx.Timeout(90, connect=15), max_retries=1)
        chunks = [protocol_pages(documents)[0]] if sample_id else material_chunks(documents)
        if not chunks or not chunks[0]:
            raise NeedMaterials('没有可供提取的 Methods 或补充材料正文')
        results = []
        for index, chunk in enumerate(chunks, 1):
            snapshot['material_chunk'] = {'index': index, 'total': len(chunks)}
            async def progress():
                return await progress_callback('extracting', f'正在提取材料块 {index}/{len(chunks)}')
            parts = await extract_with_split(llm, snapshot, chunk, progress)
            # Retain the raw model result for diagnosing schema errors without another paid call.
            run_directory = document_root() / str(item_id) / 'runs' / token
            run_directory.mkdir(parents=True, exist_ok=True)
            (run_directory / f'chunk-{index}.json').write_text(json.dumps(parts, ensure_ascii=False), encoding='utf-8')
            results.extend(parts)
        merged = merge_chunks(results)
        gaps = [entry['name'] for entry in manifest.get('inventory', []) if entry['status'] in {'unavailable', 'parse_failed', 'unsupported'}]
        if manifest.get('collection_error'):
            gaps.append(manifest['collection_error'])
        if gaps:
            merged['outcome'] = 'needs_sources'
            merged['reference_requests'].extend('需人工核对材料覆盖：' + name for name in gaps)
        payload = validate_extraction(merged, document_context(documents), snapshot['dataset_id'],
                                      [s['gsm_id'] for s in snapshot.get('samples', [])], required_gsm_id=snapshot.get('target_gsm_id'))
        doc_warnings = [f'{doc.name}: {warning}' for doc in documents for warning in json.loads(doc.warnings_json)]
        payload['warnings'].extend(doc_warnings)
        provenance = {'schema_version': SCHEMA_VERSION, 'target_gsm_id': snapshot.get('target_gsm_id'),
                      'sample_metadata': snapshot.get('target_sample'), 'model': llm.model,
                      'prompt_sha256': hashlib.sha256(extraction_prompt().encode('utf-8')).hexdigest(),
                      'skills': {p.stem: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(SKILL_DIR.glob('*.md'))},
                      'materials_manifest': manifest,
                      'documents': [{'id': doc.id, 'sha256': doc.sha256} for doc in documents],
                      'chunks': len(chunks), 'extraction_parts': len(results)}
        async with AsyncSessionLocal() as db:
            current = await db.get(ProtocolSample if sample_id else ProtocolItem, sample_id or item_id)
            if current.run_token != token:
                return
            previous = await db.get(ProtocolRevision, current.active_revision_id) if current.active_revision_id else None
            revision = ProtocolRevision(item_id=item_id, sample_id=sample_id, source='machine',
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
    finally:
        if llm:
            await llm._client.close()


def sample_documents(documents, gsm_id):
    return [doc for doc in documents if doc.kind != 'metadata' or doc.name == gsm_id + '-metadata.json.txt']


@celery_app.task(name='worker.protocol_tasks.run_protocol_sample')
def run_protocol_sample(sample_id, token):
    asyncio.run(process_protocol_sample(sample_id, token))


async def _sample_progress(sample_id, token, status, message=None):
    async with AsyncSessionLocal() as db:
        result = await db.execute(update(ProtocolSample).where(
            ProtocolSample.id == sample_id, ProtocolSample.run_token == token,
        ).values(status=status, error=message, updated_at=datetime.utcnow()))
        await db.commit()
        return bool(result.rowcount)


_sample_limits = weakref.WeakKeyDictionary()


async def process_protocol_sample(sample_id, token):
    loop = asyncio.get_running_loop()
    limiter = _sample_limits.setdefault(loop, asyncio.Semaphore(5))
    while True:
        try:
            await asyncio.wait_for(limiter.acquire(), timeout=30)
            break
        except asyncio.TimeoutError:
            if not await _sample_progress(sample_id, token, 'queued'):
                return
    try:
        await _process_protocol_sample(sample_id, token)
    finally:
        limiter.release()


async def _process_protocol_sample(sample_id, token):
    async with AsyncSessionLocal() as db:
        claim = await db.execute(update(ProtocolSample).where(ProtocolSample.id == sample_id,
            ProtocolSample.run_token == token, ProtocolSample.status == 'queued')
            .values(status='extracting', updated_at=datetime.utcnow()))
        await db.commit()
        if not claim.rowcount:
            return
        sample = await db.get(ProtocolSample, sample_id)
        item = await db.get(ProtocolItem, sample.item_id)
        job = await db.get(ProtocolJob, item.job_id)
        snapshot = json.loads(item.snapshot_json)
        target = next((s for s in snapshot.get('samples', []) if s['gsm_id'] == sample.gsm_id), json.loads(sample.snapshot_json))
        snapshot.update(target_gsm_id=sample.gsm_id, target_sample=target, samples=[target])
        documents = list((await db.execute(select(ProtocolDocument).where(ProtocolDocument.item_id == item.id))).scalars())
    try:
        stored = await asyncio.to_thread(save_document, json.dumps(target, ensure_ascii=False, indent=2).encode(),
                                        sample.gsm_id + '-metadata.json.txt', item.id)
        async with AsyncSessionLocal() as db:
            existing = await db.scalar(select(ProtocolDocument).where(ProtocolDocument.item_id == item.id,
                                                                    ProtocolDocument.sha256 == stored['sha256']))
            if not existing:
                db.add(ProtocolDocument(item_id=item.id, kind='metadata',
                    reference='https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=' + sample.gsm_id, **stored))
                await db.commit()
            documents = list((await db.execute(select(ProtocolDocument).where(ProtocolDocument.item_id == item.id))).scalars())
        documents = sample_documents(documents, sample.gsm_id)
        manifest = read_material_manifest(item.id)
        snapshot['materials_manifest'] = manifest
        await extract_materials(item.id, token, snapshot, documents, manifest, job.owner_id,
            lambda status, message=None: _sample_progress(sample_id, token, status, message), sample_id=sample_id)
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else f'样本提取失败（{type(exc).__name__}），请检查材料或模型连接后重试'
        if isinstance(exc, APIStatusError):
            message = f'模型服务返回 HTTP {exc.status_code}，请检查配置或稍后重试'
        await _sample_progress(sample_id, token, 'failed', message[:1000])
