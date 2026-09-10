"""Regression coverage for legacy UI/API paths using synthetic local data."""
import json
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select


@pytest.fixture
async def legacy_client():
    from backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        name = 'legacy_' + uuid4().hex[:10]
        r = await client.post('/auth/register', json={'username':name, 'email':name+'@test.com', 'password':'test'})
        client.owner_id = r.json()['id']
        await client.post('/auth/login', json={'username':name,'password':'test'})
        yield client


async def seed(client, *, owner_id=None, sample=False):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult, GeoSample, GsmLabel
    async with AsyncSessionLocal() as db:
        task = ScreeningTask(name='Legacy fixture', source='geo', criteria_text='human', owner_id=owner_id or client.owner_id)
        db.add(task); await db.flush()
        row = ScreeningResult(task_id=task.id, dataset_id='GSE123', title='Synthetic example', description='Human samples')
        db.add(row); await db.flush()
        sid = None
        if sample:
            gsm = GeoSample(result_id=row.id, gsm_id='GSM123', title='Synthetic sample')
            db.add(gsm); await db.flush(); sid=gsm.id
            db.add(GsmLabel(sample_id=sid,key='avail',value='true',source='human'))
        await db.commit()
        return task.id,row.id,sid


async def test_csv_form_from_new_task_page_is_accepted(legacy_client):
    with patch('backend.routers.tasks.dispatch_or_run_inline',return_value='queued') as dispatch:
        r=await legacy_client.post('/tasks',data={'name':'CSV UI','source':'csv','criteria_text':'human'},
            files={'file':('input.csv',b'GSE,title,summary\nGSE123,Example,Human cells\n','text/csv')})
    assert r.status_code==201,r.text
    assert r.json()['total']==1
    dispatch.assert_called_once()


async def test_bad_csv_is_reported_without_creating_task(legacy_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask
    r=await legacy_client.post('/tasks',params={'name':'Bad CSV','source':'csv'},files={'file':('bad.csv',b'title\nmissing ID\n','text/csv')})
    assert r.status_code==400,r.text
    async with AsyncSessionLocal() as db:
        assert not (await db.scalars(select(ScreeningTask).where(ScreeningTask.owner_id==legacy_client.owner_id))).all()


async def test_annotation_records_are_private(legacy_client):
    from backend.database import AsyncSessionLocal
    from backend.models import User
    async with AsyncSessionLocal() as db:
        other=User(username='other_'+uuid4().hex,email=uuid4().hex+'@test.com',hashed_password='unused')
        db.add(other);await db.commit(); other_id=other.id
    _,rid,sid=await seed(legacy_client,owner_id=other_id,sample=True)
    routes=[('GET',f'/annotate/results/{rid}/labels'),('PUT',f'/annotate/results/{rid}/labels'),
            ('POST',f'/annotate/results/{rid}/run'),('POST',f'/annotate/results/{rid}/gsm-labels/run'),
            ('GET',f'/annotate/samples/{sid}/labels'),('PUT',f'/annotate/samples/{sid}/labels')]
    with patch('backend.routers.annotate.dispatch_or_run_inline') as dispatch:
        for method,url in routes:
            r=await legacy_client.request(method,url,json={'key':'avail','value':'false'} if method=='PUT' else None)
            assert r.status_code==404,(method,url,r.text)
        dispatch.assert_not_called()


async def test_delete_parent_keeps_child_and_removes_sample_labels(legacy_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, GsmLabel
    tid,rid,sid=await seed(legacy_client,sample=True)
    async with AsyncSessionLocal() as db:
        child=ScreeningTask(name='GSM child',source='geo',criteria_text='',task_type='gsm_annotation',parent_task_id=tid,owner_id=legacy_client.owner_id)
        db.add(child);await db.commit();cid=child.id
    r=await legacy_client.delete(f'/tasks/{tid}')
    assert r.status_code==200,r.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(ScreeningTask,cid)).parent_task_id is None
        assert not (await db.scalars(select(GsmLabel).where(GsmLabel.sample_id==sid))).all()


async def test_single_annotation_preserves_human_decision(legacy_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult, GeoLabel, LLMConfig
    from backend.worker.tasks import _run_single_result_annotation_async
    tid,rid,_=await seed(legacy_client)
    async with AsyncSessionLocal() as db:
        task=await db.get(ScreeningTask,tid);task.label_schema='["final_conclusion"]'
        row=await db.get(ScreeningResult,rid);row.decision='exclude'
        db.add(GeoLabel(result_id=rid,key='final_conclusion',value='不可用',source='human'))
        db.add(LLMConfig(owner_id=legacy_client.owner_id,provider='deepseek',api_key='fake',is_active=True))
        await db.commit()
    llm=AsyncMock();llm.extract_labels.return_value={'final_conclusion':'可用'}
    with patch('backend.worker.tasks.LLMClient',return_value=llm),patch('backend.worker.tasks._geo_context_for_result',return_value='Human samples'):
        await _run_single_result_annotation_async(rid)
    async with AsyncSessionLocal() as db:
        assert (await db.get(ScreeningResult,rid)).decision=='exclude'


async def test_library_deduplicates_batch_and_protects_labels(legacy_client):
    from backend.database import AsyncSessionLocal
    from backend.models import User, Library, LibraryEntry
    own=(await legacy_client.post('/library',json={'name':'Test library'})).json()['id']
    r=await legacy_client.post(f'/library/{own}/entries',json={'entries':[{'gse_id':'GSE123'},{'gse_id':'GSE123'}]})
    assert r.json()=={'added':1,'skipped':1}
    async with AsyncSessionLocal() as db:
        other=User(username='other_'+uuid4().hex,email=uuid4().hex+'@test.com',hashed_password='unused')
        db.add(other);await db.flush()
        lib=Library(name='Private',owner_id=other.id);db.add(lib);await db.flush()
        entry=LibraryEntry(library_id=lib.id,gse_id='GSE456');db.add(entry);await db.commit();eid=entry.id
    assert (await legacy_client.get(f'/library/entries/{eid}/labels')).status_code==404
    assert (await legacy_client.put(f'/library/entries/{eid}/labels',json={'key':'test','value':'value'})).status_code==404


async def test_gsm_legacy_worker_passes_configured_schema(legacy_client):
    from unittest.mock import create_autospec
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, LLMConfig, GsmLabel
    from backend.worker.llm_client import LLMClient
    from backend.worker.tasks import _run_gsm_annotation_async
    tid,rid,sid=await seed(legacy_client,sample=True)
    labels=[{'name':'target_cell','type':'free_text'}]
    async with AsyncSessionLocal() as db:
        task=await db.get(ScreeningTask,tid);task.label_schema=json.dumps({'gse':[],'gsm':labels})
        db.add(LLMConfig(owner_id=legacy_client.owner_id,provider='deepseek',is_active=True,api_key='fake'))
        await db.commit()
    llm=create_autospec(LLMClient,instance=True)
    llm.annotate_gsm.return_value={'avail':'true','target_cell':'neural cells'}
    # Remove completion marker so this sample actually needs annotation.
    from sqlalchemy import delete
    async with AsyncSessionLocal() as db:
        await db.execute(delete(GsmLabel).where(GsmLabel.sample_id==sid));await db.commit()
    with patch('backend.worker.tasks.LLMClient',return_value=llm):
        await _run_gsm_annotation_async(rid)
    llm.annotate_gsm.assert_awaited_once()
    assert llm.annotate_gsm.await_args.kwargs['gsm_labels']==labels


async def test_pdf_retrieval_uses_geo_identity_and_retries_failure(legacy_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningResult
    from backend.worker.tasks import _fetch_one_paper, _fetch_papers_async
    tid,rid,_=await seed(legacy_client)
    with patch('backend.worker.tasks.fetch_gse_detail',return_value={'pmids':['123','456']}),patch('backend.worker.tasks.fetch_pdf',new_callable=AsyncMock) as download:
        await _fetch_one_paper(rid)
    download.assert_not_awaited()
    async with AsyncSessionLocal() as db:
        row=await db.get(ScreeningResult,rid)
        assert row.pdf_status=='failed'
        assert '123' in row.error_msg and '456' in row.error_msg
        row.decision='include';await db.commit()
    with patch('backend.worker.tasks._fetch_one_paper',new_callable=AsyncMock) as retry:
        await _fetch_papers_async(tid)
    retry.assert_awaited_once_with(rid)


async def test_pdf_route_checks_owner(legacy_client,tmp_path,monkeypatch):
    import backend.main as main
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningResult, User
    monkeypatch.setattr(main,'PDF_DIR',str(tmp_path))
    pdf=tmp_path/'GSE123.pdf';pdf.write_bytes(b'%PDF-1.4\nTest')
    _,rid,_=await seed(legacy_client)
    async with AsyncSessionLocal() as db:
        row=await db.get(ScreeningResult,rid);row.pdf_path=str(pdf);row.pdf_status='available';await db.commit()
    assert (await legacy_client.get('/pdfs/GSE123.pdf')).status_code==200
    from backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as other:
        assert (await other.get('/pdfs/GSE123.pdf')).status_code==401


async def test_annotation_progress_does_not_double_count_screened_results(legacy_client):
    from backend.database import AsyncSessionLocal
    from backend.models import ScreeningTask, ScreeningResult, LLMConfig
    from backend.worker.tasks import _run_annotation_async
    tid, rid, _ = await seed(legacy_client)
    async with AsyncSessionLocal() as db:
        task = await db.get(ScreeningTask, tid)
        task.label_schema = '["final_conclusion"]'
        task.total = task.processed = 2
        row = await db.get(ScreeningResult, rid)
        row.status, row.decision = 'done', 'include'
        db.add(ScreeningResult(task_id=tid, dataset_id='GSE124', status='done', decision='include'))
        db.add(LLMConfig(owner_id=legacy_client.owner_id, provider='deepseek', api_key='fake', is_active=True))
        await db.commit()
    observed = []

    async def extraction(**kwargs):
        async with AsyncSessionLocal() as db:
            observed.append((await db.get(ScreeningTask, tid)).processed)
        return {'final_conclusion': '可用'}

    llm = AsyncMock()
    llm.extract_labels.side_effect = extraction
    with patch('backend.worker.tasks.LLMClient', return_value=llm), patch('backend.worker.tasks._geo_context_for_result', return_value='Human samples'):
        await _run_annotation_async(tid)
    assert observed == [2, 2]


async def test_screening_receives_design_and_sample_evidence(legacy_client):
    from backend.database import AsyncSessionLocal
    from backend.models import LLMConfig
    from backend.worker.tasks import _run_screening_async
    tid, rid, _ = await seed(legacy_client, sample=True)
    async with AsyncSessionLocal() as db:
        db.add(LLMConfig(owner_id=legacy_client.owner_id, provider='deepseek', api_key='fake', is_active=True))
        await db.commit()
    llm = AsyncMock()
    llm.screen_dataset.return_value = {'decision':'include', 'confidence':0.9, 'summary':'Human iPSC sample evidence', 'rule_checks':[]}
    with patch('backend.worker.tasks.LLMClient', return_value=llm), \
         patch('backend.worker.tasks.fetch_gse_detail', return_value={'overall_design':'RNA-seq of differentiated cells'}), \
         patch('backend.worker.tasks.fetch_gsm_samples', return_value=[{'gsm_id':'GSM123', 'organism':'Homo sapiens', 'characteristics':{'cell_type':'iPSC-derived cardiomyocytes'}}]):
        await _run_screening_async(tid)
    context = llm.screen_dataset.await_args.args[2]
    assert 'RNA-seq of differentiated cells' in context
    assert 'iPSC-derived cardiomyocytes' in context
    assert 'Homo sapiens' in context
