import json

import httpx
import pytest
from openai import AsyncOpenAI

from backend.worker import llm_client
from backend.worker.protocol_tasks import extract_chunk


@pytest.mark.parametrize('base_url,model,host', [
    (None, None, 'api.orcarouter.ai'),
    ('https://dedicated.example.org/v1', 'vendor/model-id', 'dedicated.example.org'),
])
async def test_orcarouter_openai_requests_and_protocol_stream(monkeypatch, base_url, model, host):
    requests = []
    payload = {'outcome': 'no_protocol', 'events': [], 'summary': 'Test fixture'}

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.host == host
        assert request.url.path == '/v1/chat/completions'
        assert request.headers['authorization'] == 'Bearer test-orca'
        assert body['model'] == (model or 'orcarouter/auto')
        if body.get('stream'):
            chunk = {'id': 'test', 'object': 'chat.completion.chunk', 'created': 0,
                     'model': body['model'], 'choices': [{'index': 0,
                     'delta': {'content': json.dumps(payload)}, 'finish_reason': 'stop'}]}
            return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                                  text='data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 0,
            'model': body['model'], 'choices': [{'index': 0, 'message': {'role': 'assistant',
            'content': 'ok'}, 'finish_reason': 'stop'}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
        monkeypatch.setattr(llm_client, 'AsyncOpenAI', lambda **kwargs: AsyncOpenAI(**kwargs, http_client=transport))
        client = llm_client.LLMClient('orcarouter', 'test-orca', base_url=base_url, model=model)
        assert await client.test_connection() is True
        assert await extract_chunk(client, {'samples': []}, []) == payload
        assert len(requests) == 2 and requests[1]['stream'] is True
        await client._client.close()
