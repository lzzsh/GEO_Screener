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
async def test_streamed_json_is_reassembled_and_truncated_output_rejected():
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
    llm = SimpleNamespace(model='test-model', _create_chat_completion=AsyncMock(return_value=stream),
                          _parse_json=lambda raw: json.loads(raw))
    result = await extract_chunk(llm, {'dataset_id':'GSE1'}, [])
    assert result['outcome'] == 'no_protocol' and stream.closed
    assert llm._create_chat_completion.call_args.kwargs['stream'] is True
    llm._create_chat_completion.return_value = Stream('length')
    with pytest.raises(ValueError, match='8192'):
        await extract_chunk(llm, {'dataset_id':'GSE1'}, [])
