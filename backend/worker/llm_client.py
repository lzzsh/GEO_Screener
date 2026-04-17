import json
import re
from typing import Optional
from openai import AsyncOpenAI

PROVIDER_DEFAULTS: dict[str, dict] = {
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "glm":      {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4"},
    "minimax":  {"base_url": "https://api.minimax.chat/v1", "model": "abab6.5s-chat"},
}

LABEL_PROMPT_TEMPLATE = """\
你是一个严格的数据筛选助手，需要根据提供的 GEO 元数据判断该数据是否符合纳入标准。

你只能基于提供的 GEO 元数据进行判断，不允许使用外部知识，不允许猜测未提供的信息。若关键信息缺失，必须标注为“信息不足”，并在最终结论中使用“待确认”，不得因信息不足直接判定为“不可用”。

---

## 纳入标准

本研究仅纳入“人源多能干细胞分化过程中的单细胞数据”，具体要求如下：

1. 起始细胞
- 必须为人源 iPSC、ESC 或 PSC
- 来源需为正常供体或标准细胞系
- 允许 CRISPR、小分子等实验扰动，但必须基于 WT 背景
- 排除疾病来源 iPSC、携带先天遗传缺陷的细胞系

2. 数据类型
- 必须为单细胞数据，例如 scRNA-seq、scATAC-seq、spatial transcriptomics、CITE-seq、multiome
- 排除 bulk RNA-seq 或非单细胞数据

3. 分化体系
- 必须为 PSC 分化过程
- 可接受常规 PSC 单细胞分化数据，也可接受 3D 模型，例如 organoid、blastoid、gastruloid、embryo model
- 不要求 GEO 明确写出完整分化过程、路径或目标的详细信息；只要文本能够支持其为 PSC 分化相关单细胞数据即可
- 2D/3D 不作为硬性纳入条件。除明确 embryo model、organoid、3D suspension、spheroid、aggregate、gastruloid、blastoid 等 3D 或胚胎模型证据外，常规 PSC 细胞系分化单细胞数据可按常规 2D/非 3D 分化理解
- 不得因为未明确写出 2D 而判定为信息不足或不符合

4. 实验环境
- 必须为 in vitro
- 排除 in vivo 或体内移植后数据

---

## GEO 元数据

GSE_ID: {dataset_id}

Title:
{title}

Summary / Description / Overall Design:
{description}

---

## 可选补充标注维度

如果以下维度能从原文明确判断，可在 JSON 末尾增加同名字段；若不能判断，值为 null。不得影响固定筛选字段。

{dimensions}

---

## 输出要求

请严格输出 JSON，不要输出 Markdown，不要输出代码块，不要输出 JSON 之外的任何文字。

JSON 必须使用以下结构：

{{
  "GSE_ID": "{dataset_id}",
  "reasoning_text": "一整段连续中文推理文字，必须按固定顺序依次覆盖：数据类型、起始细胞、遗传背景、分化体系、实验环境、最终判断；可以在同一段中使用“数据类型：”“起始细胞：”“遗传背景：”“分化体系：”“实验环境：”“最终判断：”作为句内标签；不要分条、不要分块、不要按 1-5 点输出",
  "final_conclusion": "可用 / 不可用 / 待确认",
  "数据模态": "实际观察到的数据模态，如 scRNA-seq / scATAC-seq / spatial transcriptomics / CITE-seq / multiome / bulk RNA-seq / ribosome profiling；无明确证据则为空字符串",
  "分化起点": "iPSC / ESC / PSC；无明确证据则为空字符串",
  "扰动类型": "TF / 小分子 / CRISPR / 其他；无明确扰动则为空字符串",
  "分化体系": "2D / 3D；无明确证据则为空字符串",
  "分化终点": "心肌细胞 / 神经细胞 / 类器官等简短终点；无明确证据则为空字符串",
  "数据平台": "10x Genomics / Smart-seq2 / Illumina / 其他平台；无明确证据则为空字符串",
  "是否提供原始测序数据": "是 / 否 / 不明确；无明确证据则为空字符串"
}}

---

## 判定规则

- final_conclusion 只能是“可用”、“不可用”或“待确认”
- 只有当数据类型、起始细胞、遗传背景、分化体系、实验环境均明确符合时，才能判定为“可用”
- 任一关键项为“不符合”，必须判定为“不可用”
- 任一关键项为“信息不足”，且没有明确排除证据时，必须判定为“待确认”
- 同时存在“不符合”和“信息不足”时，优先判定为“不可用”
- 分化体系判断只需确认是否为 PSC 分化相关单细胞数据；不得要求原文提供详细分化路径、步骤、时序或目标细胞说明
- 2D/3D 仅作为辅助描述：明确出现 embryo model、organoid、3D suspension、spheroid、aggregate、gastruloid、blastoid 等证据时可说明为 3D/模型体系；否则不要因缺少 2D/3D 字样降低结论
- reasoning_text 必须是一整段连续文字，不要分条、不要分块、不要按 1-5 点输出
- reasoning_text 必须按固定顺序依次覆盖：数据类型、起始细胞、遗传背景、分化体系、实验环境、最终判断
- 可以在同一段中使用“数据类型：”“起始细胞：”“遗传背景：”“分化体系：”“实验环境：”“最终判断：”作为句内标签，但这些标签之间不能换行或拆成列表
- reasoning_text 每个判断点都需引用提供的 GEO 元数据原文关键词作为证据；若某点证据不足，直接在对应位置写“信息不足”
- reasoning_text 必须客观、简洁、学术化
- 七个简短标注字段只填标准化短词或短语，不写推理；没有原文证据时必须填空字符串
- 数据模态不是纳入状态字段；即使数据类型不符合纳入标准，也必须填写实际观察到的数据模态
- “数据模态”优先填写原文直接支持的数据模态，例如 scRNA-seq、scATAC-seq、spatial transcriptomics、CITE-seq、multiome、bulk RNA-seq、ribosome profiling
- 出现“bulk RNA sequencing”“bulk RNA-seq”“RNA-Seq”且无单细胞证据时，数据模态填写“bulk RNA-seq”
- 出现“ribosome sequencing”“ribosome profiling”“Ribo-seq”时，数据模态填写“ribosome profiling”
- “分化起点”填写 iPSC、ESC 或 PSC；没有明确证据则为空字符串
- “扰动类型”填写 TF、小分子、CRISPR 或其他简短扰动；无明确扰动则为空字符串
- “分化体系”只填写 2D 或 3D；无明确证据则为空字符串
- “分化终点”填写简短终点，如心肌细胞、神经细胞、midbrain organoid；无明确证据则为空字符串
- “数据平台”填写原文可见的平台或测序技术平台，如 10x Genomics、Smart-seq2、Illumina；无明确证据则为空字符串
- “是否提供原始测序数据”只填写“是”“否”或“不明确”；无明确证据则为空字符串
- 若 GEO 元数据上下文包含“GEO Raw Data Availability: yes”，则“是否提供原始测序数据”填写“是”
- 若 GEO 元数据上下文包含“GEO Raw Data Availability: no”，则“是否提供原始测序数据”填写“否”
"""

SCREENING_PROMPT_TEMPLATE = """\
You are a systematic review screener. Evaluate the following dataset against the criteria.

## Screening Criteria
{criteria_text}

## Dataset Information
ID: {dataset_id}
Title: {title}
Description: {description}

## Instructions
Return ONLY valid JSON with this exact structure:
{{
  "decision": "include" | "exclude" | "uncertain",
  "confidence": 0.0-1.0,
  "summary": "one sentence rationale",
  "rule_checks": {{"criterion_key": true|false}}
}}
"""

class LLMClient:
    def __init__(self, provider: str, api_key: str, base_url: Optional[str] = None, model: Optional[str] = None, temperature: float = 0.1):
        defaults = PROVIDER_DEFAULTS.get(provider, {})
        self.model = model or defaults.get("model", "gpt-3.5-turbo")
        self.temperature = temperature
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or defaults.get("base_url"),
        )

    async def screen_dataset(self, dataset_id: str, title: str, description: str, criteria_text: str) -> dict:
        prompt = SCREENING_PROMPT_TEMPLATE.format(
            criteria_text=criteria_text,
            dataset_id=dataset_id,
            title=title,
            description=description,
        )
        response = await self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        return self._parse_json(raw)

    async def extract_labels(self, dataset_id: str, title: str, description: str,
                              dimensions: list[str]) -> dict:
        prompt = LABEL_PROMPT_TEMPLATE.format(
            dimensions="\n".join(f"- {d}" for d in dimensions),
            dataset_id=dataset_id, title=title, description=description,
        )
        response = await self._client.chat.completions.create(
            model=self.model, temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        return self._parse_json(raw)

    def _parse_json(self, raw: str) -> dict:
        # Strip markdown code fences if present
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
        text = match.group(1) if match else raw
        return json.loads(text)

    async def test_connection(self) -> bool:
        response = await self._client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            max_tokens=5,
        )
        return bool(response.choices[0].message.content)
