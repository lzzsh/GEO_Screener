# GSM 级别标注 + GSE 二轮复核 设计文档

**日期：** 2026-04-17

---

## 背景

第一轮 LLM 筛选（基于 GEO 元数据）完成后，部分 GSE 的 `final_conclusion` 为 `待确认` 或 `可用`，其中存在信息不足或需要文献佐证的情况。同时，现有流程只对 GSE 整体做判断，缺少对 GSM 样本级别的可用性评估。

本设计覆盖两个独立子系统，按顺序交付：
1. **子系统 1：GSM 级别标注**（先做，更独立）
2. **子系统 2：GSE 二轮复核**（后做，依赖文献上传）

---

## 子系统 1：GSM 级别标注

### 目标

对每个 GSE 下的 GSM 样本，由 LLM 自动提取关键维度并给出可用性结论，人工可覆盖。

### 数据模型

新增 `GsmLabel` 表：

```python
class GsmLabel(Base):
    __tablename__ = "gsm_labels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sample_id: Mapped[int] = mapped_column(ForeignKey("geo_samples.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="llm")  # llm | human
    sample: Mapped["GeoSample"] = relationship(back_populates="labels")
```

`GeoSample` 新增 `labels` relationship。

核心标注维度（`key` 的标准值）：
- `细胞来源`：iPSC / ESC / PSC / 其他 / 信息不足
- `分化终点`：心肌细胞 / 神经细胞 / 类器官 / 其他 / 信息不足
- `分化时间点`：D7 / D14 / D30 等，无明确证据则为空字符串
- `是否有原始数据`：是 / 否 / 不明确
- `gsm_available`：可用 / 不可用 / 待确认（核心结论字段）

### LLM Prompt 设计

输入：
- GSM 字段：gsm_id、title、organism、biosample_id、characteristics
- 所属 GSE 的 summary 作为上下文

输出 JSON：
```json
{
  "细胞来源": "iPSC",
  "分化终点": "神经细胞",
  "分化时间点": "D30",
  "是否有原始数据": "是",
  "gsm_available": "可用"
}
```

判定规则：
- `gsm_available = 可用`：细胞来源明确为 iPSC/ESC/PSC，分化终点有证据，原始数据可用
- `gsm_available = 不可用`：任一关键项明确不符合
- `gsm_available = 待确认`：关键信息不足，无法判断

### 后端 API

```
POST /annotate/results/{result_id}/gsm-labels/run
  触发对该 GSE 下所有 GSM 的 LLM 标注

GET  /annotate/samples/{sample_id}/labels
  获取某 GSM 的所有标签

PUT  /annotate/samples/{sample_id}/labels
  body: {key, value}
  人工覆盖某个标签（source 设为 "human"）
```

### 前端交互

- GSE 详情页的 GSM 样本表格新增"标注 GSM"按钮（每个 GSE 一个）
- 每行 GSM 可展开，展示标签列表，支持人工编辑（与现有 GSE 标注交互一致）
- `gsm_available` 结论用颜色标签显示（绿/红/黄）

---

## 子系统 2：GSE 二轮复核

### 目标

对 `final_conclusion` 为 `待确认` 或 `可用` 的 GSE，支持上传文献 PDF 或粘贴摘要，LLM 结合文献重新判断，人工做最终确认。

### 数据模型

新增 `GseReview` 表：

```python
class GseReview(Base):
    __tablename__ = "gse_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("screening_results.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(8), nullable=False)  # pdf | text
    content: Mapped[str] = mapped_column(Text, nullable=False)  # 提取后的文本
    llm_conclusion: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 可用/不可用/待确认
    llm_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_conclusion: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 人工最终确认
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    result: Mapped["ScreeningResult"] = relationship(back_populates="reviews")
```

`ScreeningResult` 新增 `reviews` relationship。

### 复核流程

1. 用户上传 PDF 或粘贴文本
2. 后台提取文本（PDF 用 `pypdf`）
3. LLM 输入：文献文本 + 原始 GEO 元数据，使用与第一轮相同的判定规则（`LABEL_PROMPT_TEMPLATE`）
4. LLM 输出新的 `reasoning_text` + `final_conclusion`
5. 自动更新 `GeoLabel(final_conclusion)` 和 `GeoLabel(reasoning_text)`，同步更新 `sr.decision`
6. 在 UI 展示 LLM 结论，用户可接受或手动覆盖

### 后端 API

```
POST /review/results/{result_id}/upload
  form-data: file (PDF) 或 body: {text}
  触发复核，返回 review_id

GET  /review/results/{result_id}
  返回该 GSE 的所有复核记录（含 llm_conclusion、llm_reasoning、final_conclusion）

PATCH /review/{review_id}/confirm
  body: {final_conclusion}
  人工确认或覆盖结论，同步更新 ScreeningResult
```

### 前端交互

- GSE 详情页对 `待确认` / `可用` 的条目显示"上传文献复核"按钮
- 上传后展示 LLM 新结论和推理文本
- 用户点击"接受"或手动选择最终结论
- 复核历史可查看（时间、来源类型、结论变化）

---

## 交付顺序

1. 子系统 1（GSM 标注）：独立，不依赖文献，可立即开始
2. 子系统 2（GSE 复核）：依赖 `pypdf` 和文献上传流程，在子系统 1 完成后开始

---

## 不在本设计范围内

- 文献自动下载（PubMed/DOI 抓取）：外部工具处理
- GSM 标注维度的自定义配置界面：后续迭代
- 批量复核（一次上传多篇文献）：后续迭代
