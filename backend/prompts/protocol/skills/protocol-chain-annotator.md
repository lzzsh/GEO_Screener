---
name: protocol-chain-annotator
description: When a paper cites an external differentiation protocol without listing details, trace citation chains to find the original protocol source, verify small molecules/concentrations, and output perturbation-extractor-compatible TSV annotation
---

# Protocol Chain Annotator

## 概述

生物医学论文中常见写法："Cells were differentiated using a 7-step protocol as previously described (refs)"，但论文本身不列出protocol的具体成分、浓度和时间。本skill用于：

1. 追溯引用链：论文 → 直接引用的refs → refs再引用的原始protocol来源
2. 验证protocol一致性：跨多个同实验室来源交叉验证
3. 提取完整扰动信息：小分子、生长因子、浓度、时间窗口、培养基配方
4. 查询PubChem/CHEMBL ID
5. 输出与 perturbation-extractor skill 兼容的 TSV 格式

## 前置条件

- 已加载 `perturbation-extractor` skill（提供 TSV 列定义和基本提取规则）
- 已获取论文全文PDF或可搜索文本（至少包含 Methods 部分和参考文献列表）
- 需要网络搜索能力（用于查阅外部protocol来源）

## 工作流程

### Step 1: 定位protocol引用

在论文 Methods 中找到分化/重编程等protocol描述。典型句式：

> "SCs were differentiated into pancreatic β-like cells using a seven-step protocol as previously described **(18, 20, 73, 74)**."

或：

> "iPSCs were differentiated into beta cells using a 7-step protocol previously published by our group [12]."

**关键**: 确定论文中哪条(或哪些)引用标注对应protocol来源。

### Step 2: 追溯引用链

对Step 1找到的每个引用编号，在论文参考文献列表中查找对应的论文。分析每篇被引论文的Methods，看其中是否包含protocol细节，或者它们是否进一步引用其他来源：

**典型链式引用模式：**

```
目标论文
  └─ cites ref X
       └─ ref X 的 Methods 写 "as previously described [ref Y]"
            └─ ref Y 才是真正的原始 protocol 来源论文
```

**⚠️ 关键判断规则：**

- 如果直接引用的refs的Methods中也只写了"as previously described [other ref]"，没有列出具体配方 → 继续追溯
- 一直追到某篇论文的方法部分或补充材料中**实际列出了培养基配方、小分子浓度和时间点**
- 该原始来源论文（可能是较早期的研究论文或专门的protocol论文）才是真正的protocol源头

**不要：**
- 跳过追溯链，直接用自己知道的外部protocol文章（如未在引用链中的STAR Protocols等）
- 论文仅引用外部protocol但未列出具体成分、浓度和时间时，直接回溯编造外部protocol内容

**要：**
- 沿引用链逐级追溯，直到找到包含实际配方细节的原始论文
- 当溯源到原始protocol论文后，可以用该原始论文的配方作为注释依据
- 引用链中的中间论文（仅引用"as previously described"但无详情的）不能作为配方来源

### Step 3: 验证protocol一致性

找到原始protocol来源后，用以下方法验证其准确性：

1. **跨论文交叉验证**：同一实验室后续发表的论文是否引用同一protocol配方？
2. **多源一致性检查**：检查 2-3 篇使用同一protocol的独立论文，看stage配方是否一致
3. **浓度合理性检查**：小分子浓度是否在文献报道的有效范围内？
   - CHIR-99021: 通常在 1-10 μM 范围
   - Retinoic Acid: 0.1-2 μM
   - Y-27632: 5-10 μM
   - LDN-193189: 50-500 nM
   - SANT1: 0.1-1 μM
4. **小心混淆**：
   - 不同实验室的分化protocol可能有不同的stage定义和配方
   - 不要把不同protocol的小分子混在一起
   - 确认protocol名称、stage数量和关键特征匹配

### Step 4: 提取protocol细节

从原始protocol来源论文中提取以下信息：

#### 每阶段必须提取：
| 字段 | 说明 |
|------|------|
| Stage name | 阶段名称（如 "Definitive endoderm"）|
| Stage days | D0-D2, D3-D5 等时间窗口 |
| 基础培养基 | MCDB131, RPMI, CMRL 1066 等 |
| 培养基添加物 | BSA, ITS-X, GlutaMAX, NaHCO₃, glucose, Pen/Strep 等 |
| 小分子 | 名称 + 浓度，如 "CHIR-99021 3 μM" |
| 生长因子/蛋白 | 名称 + 浓度，如 "Activin A 100 ng/mL" |
| 培养体系 | 2D monolayer / 3D suspension / microwell |
| Day 0 = 开始分化的时间点 | 不记录 Day 0 之前的 iPSC maintenance |

#### 培养基成分分离规则（复用 perturbation-extractor 规则）：

- **FBS、血清、B27、N2、GlutaMAX、NEAA、2-ME、Pen-Strep、HEPES** 等营养添加物/培养基补剂 → 不单独成行，放入 culture_medium 字段
- **ITS-X** → 培养基补剂，放入 culture_medium
- **小分子抑制剂/激动剂**（CHIR-99021, SANT1, RA, LDN-193189, TPB, Y-27632, GC1, GSiXX, ALK5inhII, ZM-447439 等）→ 单独成行
- **生长因子/重组蛋白**（Activin A, FGF-7, hEGF, BTC 等）→ 单独成行
- **激素**（T3, N-acetylcysteine）→ 单独成行
- **Nicotinamide、Vitamin C** → 如有明确的阶段特异性添加和浓度，单独成行；如为基础培养基恒定组分，放入 culture_medium

### Step 5: 查询PubChem/CHEMBL标识

为每个小分子查找数据库标识：

| 查询工具 | 用法 |
|----------|------|
| PubChem | websearch/PubChem REST API：`https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/<NAME>/cids/JSON` |
| CHEMBL | PubChem搜索结果中通常包含CHEMBL ID，或通过websearch查找 |

**常见小分子PubChem CID参考：**

| 小分子 | PubChem CID | CHEMBL ID |
|--------|-------------|-----------|
| CHIR-99021 | 9956119 | CHEMBL3616262 |
| SANT1 | 1354657 | CHEMBL2403124 |
| Retinoic Acid | 444795 | CHEMBL38 |
| LDN-193189 | 25182332 | NA |
| TPB | 16739646 | NA |
| Y-27632 | 448042 | CHEMBL2219872 |
| GC1 (Sobetirome) | 9862248 | CHEMBL107400 |
| GSiXX (DBZ) | 11454028 | NA |
| ALK5 Inhibitor II (RepSox) | 449054 | CHEMBL185238 |
| ZM-447439 | 9914412 | CHEMBL202721 |
| N-Acetylcysteine | 12035 | CHEMBL600 |
| T3 (Liothyronine) | 5920 | CHEMBL1544 |
| Nicotinamide | 936 | CHEMBL1140 |
| Vitamin C (Ascorbic acid) | 54670067 | NA |
| Forskolin | 47936 | CHEMBL2029088 |

### Step 6: 输出TSV

使用 **perturbation-extractor** 定义的 TSV 格式和列：

```
GSE_id	GSM_id	Article_title	Start_cell_type	Final_cell_type	Stage_name	Stage_order	Pert_name	Addition_context	Pert_type	pubchem_cid	chembl_id	dose_value	dose_unit	time_pert_start	time_pert_end	duration_pert	time_unit	time_collection	Culture_medium	Culture_system	Batch_id	Collection_methods	Reference
```

**关键输出规范：**
- 每个小分子/生长因子一条记录
- 所有不确定字段填 `NA`，不留空
- 不添加额外解释文字
- Reference 列标注实际使用的protocol来源论文
- 实验处理阶段（如 IFNα 处理、untreated control）单独一行，Stage_order 延续编号

## 常见错误与对策

### 错误1: 错误的protocol论文
**现象**: 用户以为论文引用了某篇protocol，实际上论文引用的是其他研究论文
**对策**: 先读论文原文的citation编号，在参考文献列表中确认每篇引用的实际内容，不要预设

### 错误2: 过度回溯
**现象**: 原始protocol引用了更早的基础protocol（如 Rezania 2014, Pagliuca 2014）
**对策**: 使用论文直接引用的来源 + 该来源引用的最近一级protocol。如果原始protocol明确基于更早protocol但有自身修改，使用该原始protocol的配方（因为包含了修改）

### 错误3: 不同protocol混用
**现象**: 把同一实验室不同版本protocol的成分混在一起
**对策**: 聚焦引用链中首次明确列出配方的论文，且该论文发表时间应早于目标论文。后续优化版本（如Barsby 2022相对Cosentino 2018的改动）如果目标论文发表时已存在且同实验室，可以作为验证参考但不应作为唯一来源

### 错误4: 忽略小分子浓度验证
**现象**: Barsby 2022中Stage 3 Supplement的SANT1 stock是0.625 mM → 1:2500稀释后工作液是0.25 μM，注意换算
**对策**: 区分stock浓度和工作浓度，always计算稀释比例

## 应用实例

以下是我们实际处理过的case（Otonkoski lab 7-stage SC-islet protocol）：

**输入**: Szymczak 2022, Sci Adv 8:eabn5732
- Methods: "differentiated using a seven-step protocol as previously described (18, 20, 73, 74)"
- 引用链: refs 18,20,73,74 的 methods 都写 "as previously described [ref]" → 源头 Cosentino 2018
- 原始protocol: Cosentino et al. 2018, Nucleic Acids Res 46:10302-10318 (Supp Table S2,S3)
- 验证: Balboa 2022 Nat Biotechnol + Barsby 2022 STAR Protocols（同实验室一致）
- 输出: 33行扰动记录 + 1行实验处理

**处理原则总结**：
1. 用论文直接引用的refs作为protocol来源
2. 如果refs再引用其他论文作为protocol来源，追溯至原始protocol论文
3. 在同一实验室的其他论文中交叉验证配方
4. 确保小分子名称、浓度、时间窗口都正确
5. 查询并填写PubChem/CHEMBL ID
