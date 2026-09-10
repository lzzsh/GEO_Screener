import json
from unittest.mock import AsyncMock
import pytest
from backend.models import GeoSample
from backend.tests.test_protocols_router import protocol_env, upload, payload


@pytest.mark.asyncio
async def test_gsm_revisions_are_independent_and_mapping_is_required(protocol_env):
    client, task, included, excluded, other, sessions, queue = protocol_env
    async with sessions() as db:
        db.add(GeoSample(result_id=included.id, gsm_id='GSM2', title='day 5'))
        await db.commit()
    response = await client.post('/api/protocols/jobs', json={'task_id': task.id})
    assert response.status_code == 201, response.text
    job_id = response.json()['id']
    job = (await client.get(f'/api/protocols/jobs/{job_id}')).json()
    assert job['extraction_unit'] == 'gsm'
    assert [s['gsm_id'] for s in job['items']] == ['GSM1', 'GSM2']
    first, second = job['items']
    assert first['source_item_id'] == second['source_item_id']
    doc = await upload(client, first['source_item_id'])
    body = payload(doc)
    body['events'][0]['values']['GSM_id'] = 'NA'
    url = f"/api/protocols/samples/{first['id']}/revisions"
    assert (await client.post(url, json={'payload': body, 'reviewed': True})).status_code == 422
    body['events'][0]['values']['GSM_id'] = 'GSM1'
    saved = await client.post(url, json={'payload': body, 'reviewed': True})
    assert saved.status_code == 201, saved.text
    sibling = (await client.get(f"/api/protocols/samples/{second['id']}")).json()
    assert sibling['revisions'] == [] and sibling['active_revision_id'] is None
    assert (await client.post(f"/api/protocols/samples/{second['id']}/revisions", json={
        'payload': body, 'base_revision_id': saved.json()['id']})).status_code == 404
    export = await client.get(f'/api/protocols/jobs/{job_id}/export')
    assert export.status_code == 200 and 'GSM1' in export.text and 'GSM2' not in export.text
    from backend.auth import get_current_user
    from backend.main import app
    app.dependency_overrides[get_current_user] = lambda: other
    assert (await client.get(f"/api/protocols/samples/{first['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_gsm_worker_targets_one_sample_and_preserves_human_revision(protocol_env, monkeypatch):
    from backend.worker import protocol_tasks as worker
    from backend.routers import protocols
    client, task, included, excluded, other, sessions, queue = protocol_env
    response = await client.post('/api/protocols/jobs', json={'task_id': task.id})
    job = (await client.get('/api/protocols/jobs/' + str(response.json()['id']))).json()
    sample = job['items'][0]
    doc = await upload(client, sample['source_item_id'])
    calls = []
    async def extract(llm, snapshot, chunk):
        calls.append(snapshot)
        assert snapshot['target_gsm_id'] == 'GSM1'
        assert [s['gsm_id'] for s in snapshot['samples']] == ['GSM1']
        result = payload(doc); result['events'][0]['values']['GSM_id'] = 'GSM1'
        return result
    monkeypatch.setattr(worker, 'extract_chunk', extract)
    dispatch = AsyncMock()
    monkeypatch.setattr(protocols, 'enqueue_sample', dispatch)
    url = f"/api/protocols/samples/{sample['id']}"
    assert (await client.post(url + '/run')).status_code == 200
    assert (await client.post(url + '/run')).status_code == 409
    assert (await client.post(f"/api/protocols/items/{sample['source_item_id']}/documents", files={'file':('new.txt',b'New shared Methods source material. '*10)})).status_code == 409
    await worker.process_protocol_sample(*dispatch.await_args.args)
    detail = (await client.get(url)).json()
    assert detail['status'] == 'needs_review', detail['error']
    rev = detail['revisions'][0]
    assert (await client.post(url + '/revisions', json={'payload':rev['payload'], 'expected_active_revision_id':rev['id'], 'base_revision_id':rev['id'], 'reviewed':True})).status_code == 201
    human = (await client.get(url)).json()['active_revision_id']
    await client.post(url + '/run')
    await worker.process_protocol_sample(*dispatch.await_args.args)
    await worker.process_protocol_sample(*dispatch.await_args.args)
    detail = (await client.get(url)).json()
    assert len(calls) == 2 and detail['active_revision_id'] == human
    assert detail['status'] == 'reviewed'


@pytest.mark.asyncio
async def test_prepare_one_gsm_downloads_shared_sources_then_dispatches_only_target(protocol_env, monkeypatch):
    from backend.worker import protocol_tasks as worker
    from backend.routers import protocols
    client, task, included, excluded, other, sessions, queue = protocol_env
    async with sessions() as db:
        db.add(GeoSample(result_id=included.id, gsm_id='GSM2', title='other arm')); await db.commit()
    r = await client.post('/api/protocols/jobs', json={'task_id':task.id})
    job = (await client.get('/api/protocols/jobs/'+str(r.json()['id']))).json()
    first, second = job['items']
    async def acquire(item_id, snapshot):
        from backend.worker.protocol_documents import save_document
        return save_document(b'Cells received CHIR99021 at 3 uM from day 0 to day 3.', 'Methods.txt', item_id), 'test source'
    monkeypatch.setattr(worker, 'acquire_material', acquire)
    dispatch = AsyncMock(); monkeypatch.setattr(protocols, 'enqueue_sample', dispatch)
    r = await client.post(f"/api/protocols/samples/{first['id']}/run")
    assert r.status_code == 200
    await worker.process_protocol_item(*queue.await_args.args)
    assert dispatch.await_count == 1 and dispatch.await_args.args[0] == first['id']
    sibling = (await client.get(f"/api/protocols/samples/{second['id']}")).json()
    assert sibling['status'] == 'ready' and sibling['revisions'] == []
    assert len(sibling['documents']) == 1


@pytest.mark.asyncio
async def test_full_geo_metadata_reads_channel_protocols(monkeypatch):
    import httpx
    from backend.worker.geo_fetcher import fetch_gsm_samples
    xml = '<MINiML xmlns="http://www.ncbi.nlm.nih.gov/geo/info/MINiML"><Sample><Accession>GSM1</Accession><Channel><Growth-Protocol>differentiate to day 5</Growth-Protocol><Treatment-Protocol>vehicle control</Treatment-Protocol></Channel></Sample></MINiML>'
    async def get(self, url, params):
        assert params['view'] == 'full'
        return httpx.Response(200, text=xml, request=httpx.Request('GET',url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    samples = await fetch_gsm_samples('GSE1', full=True)
    assert samples[0]['growth_protocol'] == 'differentiate to day 5'
    assert samples[0]['treatment_protocol'] == 'vehicle control'


@pytest.mark.asyncio
async def test_gsm_migration_preserves_legacy_jobs_and_revisions(tmp_path):
    import sqlite3
    from sqlalchemy.ext.asyncio import create_async_engine
    from backend.database import _run_sqlite_migrations
    path = tmp_path/'legacy.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE protocol_jobs (id INTEGER PRIMARY KEY, name TEXT)')
        db.execute('CREATE TABLE protocol_revisions (id INTEGER PRIMARY KEY, payload_json TEXT)')
        db.execute("INSERT INTO protocol_jobs VALUES (7, 'legacy')")
        db.execute("INSERT INTO protocol_revisions VALUES (9, 'preserve me')")
    engine = create_async_engine(f'sqlite+aiosqlite:///{path}')
    async with engine.begin() as conn:
        await _run_sqlite_migrations(conn)
        await _run_sqlite_migrations(conn)
    await engine.dispose()
    with sqlite3.connect(path) as db:
        assert db.execute('select name,extraction_unit from protocol_jobs').fetchone() == ('legacy','article')
        assert db.execute('select payload_json,sample_id from protocol_revisions').fetchone() == ('preserve me',None)
