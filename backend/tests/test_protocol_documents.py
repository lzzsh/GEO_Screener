import json
from types import SimpleNamespace

import pytest
from backend.worker.protocol_documents import parse_document, material_chunks
from backend.worker.protocol_tasks import merge_chunks


def test_empty_scanned_or_invalid_files_are_not_accepted_as_text():
    for content, name in [(b'', 'file.pdf'), (b'%PDF-fake', 'file.pdf'), (b' ' * 100, 'file.txt'), (b'protocol' * 20, 'file.xlsx')]:
        with pytest.raises(ValueError):
            parse_document(content, name)


def test_chunking_preserves_all_pages_and_document_identifiers():
    pages = [{'page': i, 'text': (f'page {i} content ' * 200)} for i in range(1, 5)]
    doc = SimpleNamespace(id=1, name='supplement.txt', kind='supplement', reference='ref 7', pages_json=json.dumps(pages))
    chunks = material_chunks([doc], max_chars=2000)
    for original in pages:
        rebuilt = ''.join(c['text'] for chunk in chunks for c in chunk if c['page'] == original['page'])
        assert original['text'][:80] in rebuilt and original['text'][-80:] in rebuilt
    assert {c['page'] for chunk in chunks for c in chunk} == {1, 2, 3, 4}
    assert all(c['document_id'] == 1 for chunk in chunks for c in chunk)


def test_merge_keeps_distinct_protocols_and_requests_missing_sources():
    row = {'protocol_name': 'A', 'values': {'Pert_name': 'CHIR99021'}, 'evidence': []}
    other = {**row, 'protocol_name': 'B'}
    merged = merge_chunks([{'outcome': 'extracted', 'events': [row, other]},
                           {'outcome': 'needs_sources', 'events': [row], 'reference_requests': ['ref 7 recipe']}])
    assert len(merged['events']) == 2
    assert merged['outcome'] == 'needs_sources'
    assert merged['reference_requests'] == ['ref 7 recipe']


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["test-model", "deepseek-chat", "deepseek_pro"])
async def test_streamed_json_is_reassembled_and_truncated_output_rejected(model):
    from unittest.mock import AsyncMock
    from backend.worker.protocol_tasks import extract_chunk
    from backend.worker.llm_client import LLMClient
    class Stream:
        def __init__(self, finish='stop'):
            self.finish = finish
            self.closed = False
        async def __aiter__(self):
            for part in ['{"outcome":"no_protocol",', '"events":[]}']:
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=part),finish_reason=None)])
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None),finish_reason=self.finish)])
        async def close(self): self.closed = True
    stream = Stream()
    llm = SimpleNamespace(model=model, _create_chat_completion=AsyncMock(return_value=stream),
                          _parse_json=lambda raw: json.loads(raw))
    result = await extract_chunk(llm, {'dataset_id':'GSE1'}, [])
    assert result['outcome'] == 'no_protocol' and stream.closed
    assert llm._create_chat_completion.call_args.kwargs['stream'] is True
    assert 'max_tokens' not in llm._create_chat_completion.call_args.kwargs
    assert 'max_completion_tokens' not in llm._create_chat_completion.call_args.kwargs
    llm._create_chat_completion.return_value = Stream('length')
    with pytest.raises(ValueError, match='截断'):
        await extract_chunk(llm, {'dataset_id':'GSE1'}, [])


@pytest.mark.asyncio
async def test_output_limit_splits_only_the_failing_material_chunk(monkeypatch):
    from backend.worker import protocol_tasks as worker
    from unittest.mock import AsyncMock
    first = {'document_id':7, 'page':2, 'text':'Methods A ' * 500}
    second = {'document_id':7, 'page':3, 'text':'Methods B ' * 500}
    calls = []

    async def extract(llm, snapshot, chunk):
        calls.append(chunk)
        if len(chunk) > 1:
            raise worker.OutputLimitError('output truncated')
        return {'outcome':'no_protocol', 'events':[], 'summary':chunk[0]['text'][:9]}

    monkeypatch.setattr(worker, 'extract_chunk', extract)
    progress = AsyncMock(return_value=True)
    results = await worker.extract_with_split(SimpleNamespace(model='deepseek_pro'), {}, [first, second], progress)
    assert len(results) == 2
    assert calls == [[first, second], [first], [second]]
    assert progress.await_count == 3


@pytest.mark.asyncio
async def test_output_limit_on_short_material_stops_without_infinite_retry(monkeypatch):
    from backend.worker import protocol_tasks as worker
    from unittest.mock import AsyncMock
    extraction = AsyncMock(side_effect=worker.OutputLimitError('output truncated'))
    monkeypatch.setattr(worker, 'extract_chunk', extraction)
    with pytest.raises(worker.OutputLimitError):
        await worker.extract_with_split(SimpleNamespace(model='deepseek_pro'), {}, [{'text':'Short source'}], AsyncMock(return_value=True))
    assert extraction.await_count == 1


@pytest.mark.asyncio
async def test_long_page_split_preserves_source_text_and_page_identity(monkeypatch):
    from backend.worker import protocol_tasks as worker
    from unittest.mock import AsyncMock
    text = ''.join(str(n).zfill(5) for n in range(1500))
    section = {'document_id':7, 'page':2, 'text':text}
    accepted = []

    async def extract(llm, snapshot, chunk):
        if len(chunk[0]['text']) > 5000:
            raise worker.OutputLimitError('output truncated')
        accepted.append(chunk[0])
        return {'outcome':'no_protocol', 'events':[]}

    monkeypatch.setattr(worker, 'extract_chunk', extract)
    await worker.extract_with_split(SimpleNamespace(model='test-model'), {}, [section], AsyncMock(return_value=True))
    assert len(accepted) == 2
    assert accepted[0]['text'][:-500] + accepted[1]['text'] == text
    assert all(part['document_id'] == 7 and part['page'] == 2 for part in accepted)


@pytest.mark.asyncio
async def test_non_length_error_is_not_retried_as_a_source_split(monkeypatch):
    from backend.worker import protocol_tasks as worker
    from unittest.mock import AsyncMock
    extraction = AsyncMock(side_effect=ValueError('invalid JSON'))
    monkeypatch.setattr(worker, 'extract_chunk', extraction)
    with pytest.raises(ValueError, match='invalid JSON'):
        await worker.extract_with_split(SimpleNamespace(model='test-model'), {}, [{'text':'text ' * 2000}], AsyncMock(return_value=True))
    assert extraction.await_count == 1


@pytest.mark.parametrize('references', [None, 'Reference 7: missing recipe', [{'citation':'Reference 7','missing':'recipe'}]])
async def test_reference_request_format_variants_keep_missing_source_visible(references):
    merged=merge_chunks([{'outcome':'needs_sources','events':[], 'summary':'Need the cited recipe','reference_requests':references}])
    assert merged['outcome']=='needs_sources'
    assert merged['reference_requests'] and all(isinstance(x,str) for x in merged['reference_requests'])
    if isinstance(references,list):
        assert 'Reference 7' in merged['reference_requests'][0] and 'recipe' in merged['reference_requests'][0]
