import json
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.database import Base, get_db
from backend.auth import get_current_user
from backend.main import app
from backend.models import User, ScreeningTask, ScreeningResult, GeoSample, LLMConfig, ProtocolItem, ProtocolRevision
from backend.tests.test_protocol_schema import event


@pytest.fixture
async def protocol_env(tmp_path, monkeypatch):
    from backend.routers import protocols
    from backend.worker import protocol_tasks
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/test.db')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        owner = User(username='protocol_owner', email='p@example.org', hashed_password='unused')
        other = User(username='protocol_other', email='o@example.org', hashed_password='unused')
        db.add_all([owner, other]); await db.flush()
        task = ScreeningTask(name='Screening', source='geo', owner_id=owner.id, criteria_text='PSC')
        db.add(task); await db.flush()
        included = ScreeningResult(task_id=task.id, dataset_id='GSE1', title='Test study', decision='include')
        excluded = ScreeningResult(task_id=task.id, dataset_id='GSE2', title='Other study', decision='exclude')
        db.add_all([included, excluded]); await db.flush()
        db.add(GeoSample(result_id=included.id, gsm_id='GSM1', title='day 3'))
        db.add(LLMConfig(owner_id=owner.id, provider='openai', api_key='not-real', is_active=True))
        await db.commit()
    async def session_dependency():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: owner
    monkeypatch.setattr(protocol_tasks, 'AsyncSessionLocal', sessions)
    queue = AsyncMock()
    monkeypatch.setattr(protocols, 'enqueue', queue)
    monkeypatch.setenv('PROTOCOL_DIR', str(tmp_path / 'materials'))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        yield client, task, included, excluded, other, sessions, queue
    app.dependency_overrides.clear()
    await engine.dispose()


async def create_item(client, task):
    response = await client.post('/api/protocols/jobs', json={'task_id': task.id})
    assert response.status_code == 201, response.text
    job_id = response.json()['id']
    job = (await client.get(f'/api/protocols/jobs/{job_id}')).json()
    assert len(job['items']) == 1
    return job_id, job['items'][0]['id']


async def upload(client, item_id):
    response = await client.post(f'/api/protocols/items/{item_id}/documents',
                                files={'file': ('methods.txt', b'Cells received CHIR99021 at 3 uM from day 0 to day 3. These cells were collected at day 3.', 'text/plain')})
    assert response.status_code == 201, response.text
    return response.json()['id']


def payload(doc_id):
    row = event(evidence=[{'document_id': doc_id, 'page': 1, 'quote': 'CHIR99021 at 3 uM from day 0 to day 3'}])
    return {'outcome': 'extracted', 'events': [row], 'summary': 'One protocol'}


@pytest.mark.asyncio
async def test_create_selection_upload_review_export_and_owner_isolation(protocol_env):
    client, task, included, excluded, other, *_ = protocol_env
    job_id, item_id = await create_item(client, task)
    doc_id = await upload(client, item_id)
    assert (await upload(client, item_id)) == doc_id  # content deduplication
    assert (await client.get(f'/api/protocols/jobs/{job_id}/export')).status_code == 400
    response = await client.post(f'/api/protocols/items/{item_id}/revisions', json={'payload': payload(doc_id), 'reviewed': True})
    assert response.status_code == 201, response.text
    export = await client.get(f'/api/protocols/jobs/{job_id}/export')
    assert export.status_code == 200 and 'CHIR99021' in export.text
    assert len(export.text.splitlines()[0].split('\t')) == 24
    app.dependency_overrides[get_current_user] = lambda: other
    for url in [f'/api/protocols/jobs/{job_id}', f'/api/protocols/items/{item_id}',
                f'/api/protocols/documents/{doc_id}', f'/api/protocols/jobs/{job_id}/export']:
        assert (await client.get(url)).status_code == 404
    assert (await client.post(f'/api/protocols/items/{item_id}/run')).status_code == 404
    assert (await client.post(f'/api/protocols/items/{item_id}/revisions', json={'payload': payload(doc_id)})).status_code == 404


@pytest.mark.asyncio
async def test_invalid_material_and_unverified_evidence_cannot_be_reviewed(protocol_env):
    client, task, *_ = protocol_env
    _, item_id = await create_item(client, task)
    bad = await client.post(f'/api/protocols/items/{item_id}/documents', files={'file': ('fake.pdf', b'%PDF-not-a-real-file')})
    assert bad.status_code == 422
    doc_id = await upload(client, item_id)
    result = payload(doc_id); result['events'][0]['evidence'][0]['quote'] = 'Invented BMP4 evidence'
    review = await client.post(f'/api/protocols/items/{item_id}/revisions', json={'payload': result, 'reviewed': True})
    assert review.status_code == 422
    draft = await client.post(f'/api/protocols/items/{item_id}/revisions', json={'payload': result})
    assert draft.status_code == 201


@pytest.mark.asyncio
async def test_worker_rerun_preserves_human_revision_and_rejects_duplicate_dispatch(protocol_env, monkeypatch):
    from backend.worker.protocol_tasks import process_protocol_item
    client, task, _, _, _, sessions, queue = protocol_env
    _, item_id = await create_item(client, task)
    doc_id = await upload(client, item_id)
    human = await client.post(f'/api/protocols/items/{item_id}/revisions', json={'payload': payload(doc_id), 'reviewed': True})
    human_id = human.json()['id']
    assert (await client.post(f'/api/protocols/items/{item_id}/run')).status_code == 200
    assert (await client.post(f'/api/protocols/items/{item_id}/run')).status_code == 409
    args = queue.await_args.args
    extract = AsyncMock(return_value=payload(doc_id))
    monkeypatch.setattr('backend.worker.protocol_tasks.extract_chunk', extract)
    await process_protocol_item(*args)
    await process_protocol_item(*args)
    assert extract.await_count == 1
    detail = (await client.get(f'/api/protocols/items/{item_id}')).json()
    assert detail['active_revision_id'] == human_id
    assert detail['status'] == 'reviewed'
    assert len(detail['revisions']) == 2
    assert detail['revisions'][0]['source'] == 'machine'


@pytest.mark.asyncio
async def test_stale_editor_cannot_overwrite_saved_revision(protocol_env):
    client, task, *_ = protocol_env
    _, item_id = await create_item(client, task)
    doc_id = await upload(client, item_id)
    body = {'payload': payload(doc_id)}
    assert (await client.post(f'/api/protocols/items/{item_id}/revisions', json=body)).status_code == 201
    assert (await client.post(f'/api/protocols/items/{item_id}/revisions', json=body)).status_code == 409


@pytest.mark.asyncio
async def test_worker_failure_is_explicit_and_retryable(protocol_env, monkeypatch):
    from backend.worker.protocol_tasks import process_protocol_item
    client, task, *_, queue = protocol_env
    _, item_id = await create_item(client, task)
    await upload(client, item_id)
    await client.post(f'/api/protocols/items/{item_id}/run')
    monkeypatch.setattr('backend.worker.protocol_tasks.extract_chunk', AsyncMock(side_effect=ValueError('invalid output')))
    await process_protocol_item(*queue.await_args.args)
    detail = (await client.get(f'/api/protocols/items/{item_id}')).json()
    assert detail['status'] == 'failed'
    assert detail['error'] == 'invalid output'
    assert (await client.post(f'/api/protocols/items/{item_id}/run')).status_code == 200


@pytest.mark.asyncio
async def test_expired_run_can_be_reclaimed_and_old_worker_cannot_overwrite(protocol_env, monkeypatch):
    from datetime import datetime, timedelta
    from backend.worker.protocol_tasks import process_protocol_item
    client, task, _, _, _, sessions, queue = protocol_env
    _, item_id = await create_item(client, task)
    doc_id = await upload(client, item_id)
    await client.post(f'/api/protocols/items/{item_id}/run')
    old_args = queue.await_args.args
    async with sessions() as db:
        item = await db.get(ProtocolItem, item_id)
        item.status = 'extracting'; item.updated_at = datetime.utcnow() - timedelta(minutes=21)
        await db.commit()
    assert (await client.post(f'/api/protocols/items/{item_id}/run')).status_code == 200
    new_args = queue.await_args.args
    assert old_args[1] != new_args[1]
    extract = AsyncMock(return_value=payload(doc_id))
    monkeypatch.setattr('backend.worker.protocol_tasks.extract_chunk', extract)
    await process_protocol_item(*old_args)
    assert extract.await_count == 0
    await process_protocol_item(*new_args)
    assert extract.await_count == 1


@pytest.mark.asyncio
async def test_reference_upload_requires_citation_and_empty_selection_is_rejected(protocol_env):
    client, task, *_ = protocol_env
    assert (await client.post('/api/protocols/jobs', json={'task_id': task.id, 'result_ids': []})).status_code == 422
    _, item_id = await create_item(client, task)
    response = await client.post(f'/api/protocols/items/{item_id}/documents', data={'kind':'reference'},
                                files={'file': ('ref.txt', b'reference text '*20)})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_screening_results_link_to_latest_owned_protocol_job(protocol_env):
    client, task, *_ = protocol_env
    job_id, _ = await create_item(client, task)
    response = await client.get(f'/tasks/{task.id}/results')
    assert response.status_code == 200
    included = next(row for row in response.json()['items'] if row['dataset_id'] == 'GSE1')
    excluded = next(row for row in response.json()['items'] if row['dataset_id'] == 'GSE2')
    assert included['protocol'] == {'job_id': job_id, 'status': 'waiting_material'}
    assert excluded['protocol'] is None
