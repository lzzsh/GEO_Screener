---
name: "perturbation-extractor"
description: "Extract structured TSV tables of cell perturbations (small molecules, growth factors, cytokines, media) from biomedical protocol text, Methods sections, GEO metadata. Output tab-separated rows with columns: GSE_id, GSM_id, Article_title, Start_cell_type, Final_cell_type, Stage_name, Stage_order, Pert_name, Addition_context, Pert_type, pubchem_cid, chembl_id, dose_value, dose_unit, time_pert_start, time_pert_end, duration_pert, time_unit, time_collection, Culture_medium, Culture_system, Batch_id, Collection_methods, Reference"
---

# Perturbation Extractor

## 概述

从生物医学论文 Methods、Experimental Design、Supplementary Materials、GEO metadata、GSE/GSM sample records 中提取结构化细胞扰动 protocol，输出 TSV 格式表格。

## 核心目标

主要研究分化过程中的小分子、重组蛋白、细胞因子、生长因子、激素、培养基添加物、基质、血清、抗生素、抑制剂等 perturbation 对细胞分化状态的影响。

只整理从 iPSC/ESC 开始分化/诱导 Day 0 之后，到该 GSM 样本最终采样时刻之前，明确加入过且可能影响细胞培养、分化、成熟或实验处理状态的成分。

## 输出格式

TSV（Tab-separated values），每行一条扰动记录。**输出时直接给出纯 TSV 文本块**，列：

```
GSE_id	GSM_id	Article_title	Start_cell_type	Final_cell_type	Stage_name	Stage_order	Pert_name	Addition_context	Pert_type	pubchem_cid	chembl_id	dose_value	dose_unit	time_pert_start	time_pert_end	duration_pert	time_unit	time_collection	Culture_medium	Culture_system	Batch_id	Collection_methods	Reference
```

### 列说明

| 列名 | 说明 | 缺省值 |
|---|---|---|
| GSE_id | GEO Series 编号，如 GSE230051 | NA |
| GSM_id | GEO Sample 编号，如 GSM7184537 | NA |
| Article_title | 论文标题 | NA |
| Start_cell_type | 实验起点细胞类型，写详细，如 "hiPSC, male control (CD10)" 或 "hiPSC, cell line 72_3" | NA |
| Final_cell_type | 终点细胞类型，写大概场景，如 "cerebral organoid"、"cortical neural cells"、"fetal liver organoids" | NA |
| Stage_name | 只能使用: differentiation, reprogramming, sample culture, external treatment, endpoint processing, other, N/A | NA |
| Stage_order | 同一样本内按时间顺序编号（1, 2, 3...），同一条件同一编号 | NA |
| Pert_name | 扰动名称，只写一个。如 "SB431542"、"CHIR99021"、"BMP4"。basal medium 阶段填 NA | NA |
| Addition_context | 只能使用: perturbation 或 basal medium | NA |
| Pert_type | 只能使用: small_molecule, growth_factor, recombinant_protein, cytokine, hormone, CRISPR, siRNA, shRNA, matrix, basal_medium_component, supplement_component, antibiotic, serum_or_serum_replacement, vitamin, amino_acid, metabolite, lipid, inorganic_salt, carbohydrate, enzyme, dissociation_reagent, other, N/A | NA |
| pubchem_cid | small molecule 的 PubChem CID，非小分子填 NA | NA |
| chembl_id | small molecule 的 ChEMBL ID，非小分子填 NA | NA |
| dose_value | 浓度数值，如 10、0.5、3。不确定填 NA | NA |
| dose_unit | 浓度单位，如 uM、nM、ng/mL、%。不确定填 NA | NA |
| time_pert_start | 加药/培养开始时间点，如 D0、D3 | NA |
| time_pert_end | 停药/培养结束时间点，如 D1、D5（duration = time_pert_end − time_pert_start） | NA |
| duration_pert | 持续时间数值（= time_pert_end − time_pert_start） | NA |
| time_unit | 只能使用: hours, days | NA |
| time_collection | 样本收样时间，如 D10、D150 | NA |
| Culture_medium | 基础培养基及其恒定添加物。要求详尽，例如 "knockout DMEM/F12, 15% v/v knockout serum replacement, 1X GlutaMAX, 1% (v/v) penicillin-streptomycin, 1X MEM non-essential amino acids, 55 µM 2-mercaptoethanol" | NA |
| Culture_system | 如 "2D"、"3D"、"3D organoid (Matrigel dome)"、"organoid"、"EB" | NA |
| Batch_id | 同一 study 的不同 batch；不确定填 NA | NA |
| Collection_methods | 记录是否有 population enrichment 或 gene capture enrichment。如 FACS sort、magnetic bead selection 等。无则填 "N/A" | N/A |
| Reference | 引用 | NA |

**重要输出规范：**
1. 所有不确定或不适用的字段统一填 `NA`，不得留空
2. 输出时**只给出纯 TSV 表格文本块**，不加任何额外解释、标记、说明文字或格式修饰
3. 文本块直接以 tab 分隔的行序列呈现
4. basal medium 行：Stage_name 填 differentiation 或 sample culture，Pert_name/Addition_context/Pert_type 等为 NA

## 提取规则

### 时间规则
- **Day 0** = iPSC/ESC 开始分化的时间点
- 不记录 Day 0 之前的 iPSC/ESC maintenance
- `duration = time_pert_end − time_pert_start`（例如 D0-D3 = 3 days；D6-D10 = 4 days）
- time_pert_end 是停药/换液的时间点（即该药最后出现的天数+1，如果 D5 是最后含药日，time_pert_end = D6）

### 培养基与扰动规则
- **perturbation 行**：每个具体添加的小分子/因子单独一行
- **culture_medium 列**：写该阶段使用的基础培养基及其恒定添加物。如果某个成分在整个阶段都存在（如 FBS 在 Activin A 阶段全程存在），写入 culture_medium 字段而不是单独成行
- **FBS、血清、B27、N2、GlutaMAX** 等营养添加物/培养基补剂，不单独成行，放在 culture_medium 字段
- **basal medium 行**：某一阶段无任何特定扰动（纯培养基）时，才单独输出一行 basal medium 行，此时 Pert_name 等字段留空
- **commercial medium 或 proprietary kit 的未知成分不得拆分**，用 kit 名称表示
- 如果某成分同时是多个扰动的共同背景（如 RPMI 1640 + FBS 是 Activin A 和 BMP4 的共同培养基），各自行中的 culture_medium 字段都包含该背景

### pert_type 选择指南
| 成分类型 | pert_type |
|---|---|
| CHIR99021, SB431542, LDN-193189, Y27632 等 | small_molecule |
| BMP4, Activin A, FGF2, FGF4, HGF 等 | growth_factor |
| 细胞因子（IL 系列、IFN 系列、TNF 系列等） | cytokine |
| 激素（地塞米松等） | hormone |
| 血清（FBS、KSR 等） | 不单独成行，放入 culture_medium |
| B27、N2、GlutaMAX、NEAA 等 | 不单独成行，放入 culture_medium |
| Matrigel、Laminin 等基质 | 不单独成行，放入 culture_medium |

### pert_type 完整枚举（仅供查表）
`small_molecule`, `protein`, `recombinant_protein`, `cytokine`, `growth_factor`, `hormone`, `CRISPR`, `siRNA`, `shRNA`, `matrix`, `basal_medium_component`, `supplement_component`, `antibiotic`, `serum_or_serum_replacement`, `vitamin`, `amino_acid`, `metabolite`, `lipid`, `inorganic_salt`, `carbohydrate`, `enzyme`, `dissociation_reagent`, `other`, `N/A`

### 排除项
- Day 0 之前的 iPSC/ESC maintenance（mTeSR、Matrigel、ReLeSR、Primocin 等）
- 采样后/建库前技术流程中的 wash buffer、BSA、DPBS、PBS、HBSS、DNase、papain、trypsin inhibitor、lysis buffer、cell strainer、10X Genomics kit reagent 等
- 纯物理/设备条件：centrifugation、filtering、trituration、orbital shaker、incubator、sequencing platform
- 论文仅引用外部 protocol 但未列出具体成分、浓度和时间时，不得回溯编造外部 protocol 内容
- 营养成分（FBS、B27、N2、GlutaMAX、NEAA、2-ME、Pen-Strep、HEPES 等）不单独成行，放入 culture_medium 字段

### 标注优先级
1. 样本元数据绝对优先（GSM 页面的直接字段）
2. 论文内容补充（Methods、Figure Legends、Supplementary Data）
3. 矛盾时以样本元数据为准
4. 明确缺失或无法推断的字段统一留空
5. 严禁编造或过度外推

## 使用示例

### 输入
```
For co-induction of endoderm and hemogenic mesoderm, medium was changed to RPMI 1640 medium containing 100 ng/ml Activin A and 50 ng/ml BMP4 at day 0; 100 ng/ml Activin A and 0.2% FBS at day 1, and 100 ng/ml Activin A and 2% FBS on day 2. From day 3 on, cells were maintained in basal media consisting of advanced DMEM/F12 supplemented with 2% B27, 1% N2, 1% GlutaMAX, 1% HEPES, and 1% Pen-Strep. During the posterior foregut stage (day 3-5), basal media was supplemented with 500 ng/ml FGF4 and 3 μM CHIR99021...
```

### 输出

直接以纯文本表格形式给出，不添加额外解释或标记：

```
GSE230051	GSM7184537	NA	hiPSC (cell line 72_3)	fetal liver organoids	differentiation	NA	BMP4	perturbation	growth_factor	NA	NA	50	ng/mL	D0	D1	1	day	D10	RPMI 1640	2D	NA	N/A	NA
GSE230051	GSM7184537	NA	hiPSC (cell line 72_3)	fetal liver organoids	differentiation	NA	Activin A	perturbation	growth_factor	NA	NA	100	ng/mL	D0	D3	3	days	D10	RPMI 1640, FBS (Cytiva)	2D	NA	N/A	NA
GSE230051	GSM7184537	NA	hiPSC (cell line 72_3)	fetal liver organoids	differentiation	NA	FGF4	perturbation	growth_factor	NA	NA	500	ng/mL	D3	D6	3	days	D10	advanced DMEM/F12, 2% B27, 1% N2, 1% GlutaMAX, 1% HEPES, 1% Pen-Strep	2D	NA	N/A	NA
GSE230051	GSM7184537	NA	hiPSC (cell line 72_3)	fetal liver organoids	differentiation	NA	CHIR99021	perturbation	small_molecule	9956119	CHEMBL3616262	3	uM	D3	D6	3	days	D10	advanced DMEM/F12, 2% B27, 1% N2, 1% GlutaMAX, 1% HEPES, 1% Pen-Strep	2D	NA	N/A	NA
GSE230051	GSM7184537	NA	hiPSC (cell line 72_3)	fetal liver organoids	differentiation	NA	BMP4	perturbation	growth_factor	NA	NA	20	ng/mL	D6	D10	4	days	D10	advanced DMEM/F12, 2% B27, 1% N2, 1% GlutaMAX, 1% HEPES, 1% Pen-Strep	3D organoid (Matrigel dome)	NA	N/A	NA
GSE230051	GSM7184537	NA	hiPSC (cell line 72_3)	fetal liver organoids	differentiation	NA	FGF2	perturbation	growth_factor	NA	NA	10	ng/mL	D6	D10	4	days	D10	advanced DMEM/F12, 2% B27, 1% N2, 1% GlutaMAX, 1% HEPES, 1% Pen-Strep	3D organoid (Matrigel dome)	NA	N/A	NA
```

### 另一个示例：含 basal medium 阶段的情况

当某时间窗口内无任何特定扰动，仅有纯培养基维持培养时，输出一条 basal medium 行（pert_name 等填 NA）：

```
GSE325791	GSM9613476	NA	hiPSC, male control (CD10)	cortical neural cells	differentiation	NA	NA	basal medium	NA	NA	NA	NA	NA	D11	D110	100	days	NA	B27 neurobasal medium, 1X GlutaMax, N-2 DMEM/F-12 medium, MEM non-essential amino acid solution, 2% penicillin-streptomycin, 100 µM 2-mecaptoethanol	2D	NA	N/A	NA
```
