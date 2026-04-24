import asyncio
import json
import re
from typing import Optional
from openai import APIStatusError, AsyncOpenAI

PROVIDER_DEFAULTS: dict[str, dict] = {
    "deepseek":        {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "glm":             {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4"},
    "minimax":         {"base_url": "https://api.minimax.chat/v1", "model": "abab6.5s-chat"},
    "campus-minimax":  {"base_url": "http://10.28.0.22:30530/v1", "model": "minimax"},
    "campus-glm":      {"base_url": "http://10.28.0.22:30530/v1", "model": "glm"},
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
不要输出 <think>、分析过程、解释、前言或后记。

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

GSM_LABEL_PROMPT_TEMPLATE = """\
你是一个严格的样本级数据标注助手，需要根据提供的 GSM 元数据和所属 GSE 背景，判断该样本是否符合纳入标准，并提取样本级标注信息。

你只能基于提供的元数据原文进行判断，严禁猜测、推断或使用外部知识。标注字段的值必须能在下方元数据中找到直接文字依据，否则填 Unknown。

---

## 纳入标准（与 GSE 筛选标准一致，在样本级别进一步确认）

1. 起始细胞：必须为人源 iPSC、ESC 或 PSC；来源需为正常供体或标准细胞系；排除疾病来源或携带先天遗传缺陷的细胞系
2. 数据类型：必须为单细胞数据（scRNA-seq、scATAC-seq、spatial transcriptomics、CITE-seq、multiome 等）；排除 bulk RNA-seq
3. 分化体系：必须为 PSC 分化过程；可接受 2D 或 3D 模型（organoid、blastoid、gastruloid 等）
4. 实验环境：必须为 in vitro；排除 in vivo 或体内移植后数据

---

## GSE 背景

{gse_summary}

## GSM 元数据

GSM_ID: {gsm_id}
Title: {title}
Organism: {organism}
BioSample: {biosample_id}
{characteristics}

---

## 输出要求

请严格输出 JSON，不要输出 Markdown，不要输出代码块，不要输出 JSON 之外的任何文字。

{{
  "response": "分条推理，每条以序号开头，必须直接引用元数据原文词句（用单引号标注）。依次覆盖：1. avail/start_cell（起始细胞判断） 2. genetic_background（遗传背景/健康或疾病来源/WT或突变信息） 3. 数据类型/modality 4. 分化体系/culture_sys 5. 实验环境 6. raw_data 7. target_cell 8. diff_path/time_pts 9. platform/cell_line 10. perturb 11. 其余字段（sex/age/reprog/passage/matrix/medium/density/o2_lvl）。无原文证据时写'元数据中无明确记载'",
  "avail": "true / false / unknown",
  "start_cell": "iPSC / ESC / PSC；无原文直接依据则填 Unknown",
  "genetic_background": "正常供体 / 标准细胞系 / WT / 疾病来源 / 遗传缺陷 / 突变或编辑背景 / Unknown；必须直接来自 GSM 元数据，无法判断填 Unknown",
  "target_cell": "分化终点英文名；无原文直接依据则填 Unknown",
  "culture_sys": "2D / 3D / 2D/3D Mixed；无原文直接依据则填 Unknown",
  "diff_path": "直接引用元数据中的分化方案描述；无原文直接依据则填 Unknown",
  "time_pts": ["仅填元数据中明确出现的时间点"],
  "modality": ["multiome / scRNA-seq / scATAC-seq / spatial transcriptomics / CITE-seq / bulk RNA-seq 等"],
  "perturb": [{{"type": "None", "method": "Vehicle/Control", "dose": "N/A", "start": "", "end": "", "dur": ""}}],
  "platform": "直接引用元数据中的测序平台；无原文直接依据则填 Unknown",
  "cell_line": "直接引用元数据中的细胞系名称；无原文直接依据则填 Unknown",
  "sex": "Female / Male / Unknown",
  "age": "直接引用元数据中的年龄；无原文直接依据则填 Unknown",
  "reprog": "直接引用元数据中的重编程方法；无原文直接依据则填 Unknown",
  "passage": "直接引用元数据中的传代信息；无原文直接依据则填 Unknown",
  "matrix": "直接引用元数据中的基质信息；无原文直接依据则填 Unknown",
  "medium": "直接引用元数据中的培养基信息；无原文直接依据则填 Unknown",
  "density": "直接引用元数据中的密度信息；无原文直接依据则填 Unknown",
  "o2_lvl": "直接引用元数据中的氧气浓度；无原文直接依据则填 Unknown",
  "raw_data": "Yes / No / Unspecified"
}}

---

## 判定规则

### avail 判定
- avail = "true"：四条纳入标准在样本级别均明确符合
- avail = "false"：任一纳入标准在样本级别原文明确不符合
- avail = "unknown"：任一纳入标准信息不足，且无明确排除证据
- GSE 已被判定为 include 不代表每个 GSM 都符合，需独立判断

### start_cell 推断规则（重要）
- Title 或 Characteristics 中出现 "iPSC-derived"、"hiPSC"、"human iPSC" 等词，start_cell = iPSC，avail 不得因此降为 unknown
- "iPSC-derived microglia" 表示起始细胞为 iPSC，分化终点为 microglia
- "ESC-derived"、"hESC" 等词，start_cell = ESC
- 仅凭 GSE 背景中提及 iPSC 不足以确认该 GSM 的 start_cell，需 GSM 元数据本身有依据

### genetic_background 判定规则（重要）
- genetic_background 必须基于 GSM 元数据中的 cell line、donor、genotype、disease、mutation、WT、wild-type、control、healthy、normal、CRISPR、knockout、knockdown、overexpression 等直接证据
- 出现 KhES1、H1、H9、WA09、standard/control hESC/iPSC line 等标准细胞系证据时，可填“标准细胞系”
- 出现 WT、wild-type、control、healthy donor、normal donor 等证据时，按原文填“WT”“正常供体”或“标准细胞系”
- 出现 disease、patient-derived、mutation、genetic defect、trisomy、knockout、CRISPR edited 等证据时，必须在 genetic_background 中写明；若属于疾病来源或先天遗传缺陷，avail 应为 "false"
- GSM 元数据没有遗传背景直接证据时，genetic_background = "Unknown"，不要只凭 GSE 背景推断

### modality 判定规则（重要）
- Title 或 Library-Strategy 中出现 "multiome"、"10x Multiome"、"ATAC+RNA" 等词，modality = ["multiome"]，不要拆分为 scATAC-seq 和 snRNA-seq
- "ATAC-seq" 单独出现（无 RNA 联合）→ ["scATAC-seq"]
- 判断 modality 时优先参考 GSM 页面中的 Library-Strategy、Library-Source、Data-Processing 和 Supplementary-Data/补充文件说明；这几项比 GSE 背景更优先
- 若 Library-Strategy = "RNA-Seq"、Library-Source = "transcriptomic"，且 Data-Processing 或补充文件说明出现 gene-level/transcript-level TPM、read counts、expression quantification、BCL to FASTQ、DRAGEN、featureCounts、HTSeq 等常规表达矩阵处理，同时没有 single-cell、10x、cell barcode、UMI、scRNA-seq、single nucleus 等单细胞证据，则 modality = ["bulk RNA-seq"]
- "RNA-seq" 单独出现且有单细胞证据 → ["scRNA-seq"]
- "RNA-seq" 单独出现且无单细胞证据 → ["bulk RNA-seq"]
- Library-Strategy = "OTHER" 时，优先参考 Title 和 GSE 背景中的数据类型描述

### 其他规则
- time_pts 和 modality 必须为 JSON 数组；无原文证据则填 []
- perturb 必须为 JSON 对象数组；无扰动原文证据时填 [{{"type": "None", "method": "Vehicle/Control", "dose": "N/A", "start": "", "end": "", "dur": ""}}]
- 若 GSE 背景含 "GEO Raw Data Availability: yes" 则 raw_data 填 "Yes"；含 "no" 则填 "No"
- 严禁根据 GSE 背景推断 GSM 级别细节字段（passage、matrix、medium、density、o2_lvl 必须来自 GSM 元数据本身）
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

PAPER_CALIBRATION_PROMPT_TEMPLATE = """\
You are a systematic review screener. Evaluate the following dataset against the criteria.
When the paper full-text conflicts with GEO metadata, the paper takes priority.

## Screening Criteria
{criteria_text}

## Dataset Information
ID: {dataset_id}
Title: {title}
Description: {description}

## 文章全文（节选）
{paper_text}

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

    async def _create_chat_completion(self, **kwargs):
        retry_statuses = {429, 500, 502, 503, 504}
        for attempt in range(3):
            try:
                return await self._client.chat.completions.create(**kwargs)
            except APIStatusError as exc:
                if exc.status_code not in retry_statuses or attempt == 2:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))

    async def screen_dataset(self, dataset_id: str, title: str, description: str, criteria_text: str) -> dict:
        prompt = SCREENING_PROMPT_TEMPLATE.format(
            criteria_text=criteria_text,
            dataset_id=dataset_id,
            title=title,
            description=description,
        )
        response = await self._create_chat_completion(
            model=self.model,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        return self._parse_json(raw)

    async def calibrate_with_paper(self, dataset_id: str, title: str, description: str,
                                    paper_text: str, criteria_text: str) -> dict:
        prompt = PAPER_CALIBRATION_PROMPT_TEMPLATE.format(
            criteria_text=criteria_text,
            dataset_id=dataset_id,
            title=title,
            description=description,
            paper_text=paper_text[:8000],
        )
        response = await self._create_chat_completion(
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
        response = await self._create_chat_completion(
            model=self.model, temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        return self._parse_json(raw)

    async def annotate_gsm(self, gsm_id: str, title: str, organism: str,
                            biosample_id: str, characteristics: str,
                            gse_summary: str) -> dict:
        prompt = GSM_LABEL_PROMPT_TEMPLATE.format(
            gsm_id=gsm_id, title=title, organism=organism,
            biosample_id=biosample_id, characteristics=characteristics,
            gse_summary=gse_summary,
        )
        response = await self._create_chat_completion(
            model=self.model, temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = (response.choices[0].message.content or "").strip()
        if not raw:
            finish = response.choices[0].finish_reason
            raise ValueError(f"Empty response from model (finish_reason={finish})")
        return self._parse_json(raw)

    def _parse_json(self, raw: str) -> dict:
        # Strip markdown code fences if present
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
        text = match.group(1) if match else raw
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            decoder = json.JSONDecoder()
            for idx, char in enumerate(text):
                if char != "{":
                    continue
                try:
                    parsed, _ = decoder.raw_decode(text[idx:])
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
            raise ValueError(f"Invalid JSON from model: {e}\nRaw: {raw[:200]}")

    async def test_connection(self) -> bool:
        response = await self._create_chat_completion(
            model=self.model,
            temperature=0,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        )
        return bool(response.choices[0].message.content)
