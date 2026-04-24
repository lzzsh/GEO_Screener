import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from backend.worker.llm_client import LLMClient
from backend.label_schema import default_label_schema_json

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
async def test_parse_json_after_thinking_text():
    client = LLMClient(provider="deepseek", api_key="fake")
    raw = '<think>先分析样本，但这些内容不是 JSON。</think>\n{"avail":"unknown","modality":[]}'
    result = client._parse_json(raw)
    assert result["avail"] == "unknown"
    assert result["modality"] == []

@pytest.mark.asyncio
async def test_screen_dataset_calls_api():
    client = LLMClient(provider="deepseek", api_key="fake")
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = '{"decision":"include","confidence":0.95,"summary":"fits","rule_checks":{}}'
    with patch.object(client._client.chat.completions, "create", new=AsyncMock(return_value=mock_resp)):
        result = await client.screen_dataset("GSE001", "Test", "A study", "Must be human")
    assert result["decision"] == "include"


def test_default_label_schema_uses_new_format():
    schema = json.loads(default_label_schema_json())
    assert "gse" in schema
    assert "gsm" in schema
    assert len(schema["gse"]) == 7
    assert len(schema["gsm"]) == 18
    assert schema["gse"][0]["name"] == "数据模态"
    assert schema["gse"][0]["type"] == "enum"


@pytest.mark.asyncio
async def test_extract_labels_uses_standardized_geo_screening_prompt():
    from backend.label_schema import DEFAULT_GSE_LABELS
    client = LLMClient(provider="deepseek", api_key="fake")
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = '{"reasoning_text":"test","final_conclusion":"待确认"}'

    with patch.object(client._client.chat.completions, "create", new=AsyncMock(return_value=mock_resp)) as create:
        await client.extract_labels("GSE001", "PSC differentiation", "Summary text", DEFAULT_GSE_LABELS)

    prompt = create.await_args.kwargs["messages"][0]["content"]
    assert "人源多能干细胞分化过程中的单细胞数据" in prompt
    assert "reasoning_text" in prompt
    assert "final_conclusion" in prompt
    assert "数据模态" in prompt
    assert "分化起点" in prompt


@pytest.mark.asyncio
async def test_gsm_prompt_prioritizes_library_and_processing_fields():
    client = LLMClient(provider="deepseek", api_key="fake")
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = '{"response":"ok","avail":"false"}'

    with patch.object(client._client.chat.completions, "create", new=AsyncMock(return_value=mock_resp)) as create:
        from backend.label_schema import DEFAULT_GSM_LABELS
        await client.annotate_gsm(
            "GSM001",
            "Sample",
            "Homo sapiens",
            "SAMN001",
            "Library-Strategy: RNA-Seq",
            "GSE context",
            DEFAULT_GSM_LABELS,
        )

    prompt = create.await_args.kwargs["messages"][0]["content"]
    assert "GSM001" in prompt
