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
async def test_screen_dataset_calls_api():
    client = LLMClient(provider="deepseek", api_key="fake")
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = '{"decision":"include","confidence":0.95,"summary":"fits","rule_checks":{}}'
    with patch.object(client._client.chat.completions, "create", new=AsyncMock(return_value=mock_resp)):
        result = await client.screen_dataset("GSE001", "Test", "A study", "Must be human")
    assert result["decision"] == "include"


def test_default_label_schema_uses_compact_annotation_fields():
    assert json.loads(default_label_schema_json()) == [
        "数据模态",
        "分化起点",
        "扰动类型",
        "分化体系",
        "分化终点",
        "数据平台",
        "是否提供原始测序数据",
    ]


@pytest.mark.asyncio
async def test_extract_labels_uses_standardized_geo_screening_prompt():
    client = LLMClient(provider="deepseek", api_key="fake")
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = '{"reasoning_text":"证据不足，待确认。","final_conclusion":"待确认","数据模态":"","分化起点":"","扰动类型":"","分化体系":"","分化终点":"","数据平台":"","是否提供原始测序数据":""}'

    with patch.object(client._client.chat.completions, "create", new=AsyncMock(return_value=mock_resp)) as create:
        await client.extract_labels("GSE001", "PSC differentiation", "Summary text", ["最终结论"])

    prompt = create.await_args.kwargs["messages"][0]["content"]
    assert "人源多能干细胞分化过程中的单细胞数据" in prompt
    assert '"reasoning_text"' in prompt
    assert '"数据模态": "实际观察到的数据模态，如 scRNA-seq / scATAC-seq / spatial transcriptomics / CITE-seq / multiome / bulk RNA-seq / ribosome profiling；无明确证据则为空字符串"' in prompt
    assert '"分化起点": "iPSC / ESC / PSC；无明确证据则为空字符串"' in prompt
    assert '"扰动类型": "TF / 小分子 / CRISPR / 其他；无明确扰动则为空字符串"' in prompt
    assert '"分化体系": "2D / 3D；无明确证据则为空字符串"' in prompt
    assert '"分化终点": "心肌细胞 / 神经细胞 / 类器官等简短终点；无明确证据则为空字符串"' in prompt
    assert '"数据平台": "10x Genomics / Smart-seq2 / Illumina / 其他平台；无明确证据则为空字符串"' in prompt
    assert '"是否提供原始测序数据": "是 / 否 / 不明确；无明确证据则为空字符串"' in prompt
    assert '"data_type"' not in prompt
    assert '"starting_cell"' not in prompt
    assert '"genetic_background"' not in prompt
    assert '"differentiation_system"' not in prompt
    assert '"experimental_environment"' not in prompt
    assert '"final_conclusion": "可用 / 不可用 / 待确认"' in prompt
    assert "不要分条、不要分块、不要按 1-5 点输出" in prompt
    assert "reasoning_text 必须是一整段连续文字" in prompt
    assert "reasoning_text 必须按固定顺序依次覆盖：数据类型、起始细胞、遗传背景、分化体系、实验环境、最终判断" in prompt
    assert "可以在同一段中使用“数据类型：”“起始细胞：”“遗传背景：”“分化体系：”“实验环境：”“最终判断：”作为句内标签" in prompt
    assert "七个简短标注字段只填标准化短词或短语，不写推理；没有原文证据时必须填空字符串" in prompt
    assert "数据模态不是纳入状态字段；即使数据类型不符合纳入标准，也必须填写实际观察到的数据模态" in prompt
    assert "出现“bulk RNA sequencing”“bulk RNA-seq”“RNA-Seq”且无单细胞证据时，数据模态填写“bulk RNA-seq”" in prompt
    assert "出现“ribosome sequencing”“ribosome profiling”“Ribo-seq”时，数据模态填写“ribosome profiling”" in prompt
    assert "若 GEO 元数据上下文包含“GEO Raw Data Availability: yes”，则“是否提供原始测序数据”填写“是”" in prompt
    assert "若 GEO 元数据上下文包含“GEO Raw Data Availability: no”，则“是否提供原始测序数据”填写“否”" in prompt
    assert "请严格输出 JSON" in prompt
    assert "只有当数据类型、起始细胞、遗传背景、分化体系、实验环境均明确符合时" in prompt
    assert "任一关键项为“信息不足”，且没有明确排除证据时，必须判定为“待确认”" in prompt
    assert "必须存在明确分化路径或分化目标" not in prompt
    assert "不要求 GEO 明确写出完整分化过程、路径或目标的详细信息" in prompt
    assert "除明确 embryo model、organoid、3D suspension" in prompt
    assert "不得因为未明确写出 2D 而判定为信息不足或不符合" in prompt
