import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from backend.worker.llm_client import LLMClient

@pytest.mark.asyncio
async def test_parse_clean_json():
    client = LLMClient(provider="deepseek", api_key="fake")
    result = client._parse_json('{"decision":"include","confidence":0.9,"summary":"ok","rule_checks":{}}')
    assert result["decision"] == "include"

@pytest.mark.asyncio
async def test_parse_fenced_json():
    client = LLMClient(provider="deepseek", api_key="fake")
    raw = '```json\n{"decision":"exclude","confidence":0.8,"summary":"no","rule_checks":{}}\n```'
    result = client._parse_json(raw)
    assert result["decision"] == "exclude"

@pytest.mark.asyncio
async def test_screen_dataset_calls_api():
    client = LLMClient(provider="deepseek", api_key="fake")
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = '{"decision":"include","confidence":0.95,"summary":"fits","rule_checks":{}}'
    with patch.object(client._client.chat.completions, "create", new=AsyncMock(return_value=mock_resp)):
        result = await client.screen_dataset("GSE001", "Test", "A study", "Must be human")
    assert result["decision"] == "include"
