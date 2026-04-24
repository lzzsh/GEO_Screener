# 注解模式配置指南

## 概述

注解模式（Annotation Schema）允许你定义可重用的标签集合，用于自动提取 GEO 数据集的元数据。每个模式包含 GSE 级别和 GSM 级别的标签定义。

## 快速开始

### 1. 访问模式管理页面

1. 登录系统
2. 点击顶部导航栏的 **Criteria** 链接
3. 切换到 **Annotation Schemas** 标签页

### 2. 使用默认模式

最简单的方式是基于默认模式创建：

1. 点击 **📋 Use Default Template** 按钮
2. 修改模式名称（例如："我的 PSC 分化研究"）
3. 修改描述（可选）
4. 点击 **Save** 保存

默认模式包含：
- **7 个 GSE 标签**：用于数据集级别的标注
- **18 个 GSM 标签**：用于样本级别的标注

### 3. 创建自定义模式

1. 点击 **+ New Schema** 按钮
2. 输入模式名称和描述
3. 添加 GSE 标签和 GSM 标签
4. 点击 **Save**

## 标签类型说明

### GSE 标签（数据集级别）

| 标签名 | 类型 | 说明 | 可选值 |
|--------|------|------|--------|
| 数据模态 | enum | 实际观察到的数据模态 | scRNA-seq, scATAC-seq, spatial transcriptomics, CITE-seq, multiome, bulk RNA-seq, ribosome profiling |
| 分化起点 | enum | 起始细胞类型 | iPSC, ESC, PSC |
| 扰动类型 | enum | 实验扰动类型 | TF, 小分子, CRISPR, 其他 |
| 分化体系 | enum | 分化培养体系 | 2D, 3D |
| 分化终点 | free_text | 分化目标细胞类型 | - |
| 数据平台 | free_text | 测序平台 | - |
| 是否提供原始测序数据 | enum | 原始数据可用性 | 是, 否, 不明确 |

### GSM 标签（样本级别）

| 标签名 | 类型 | 说明 |
|--------|------|------|
| start_cell | enum | 起始细胞类型 |
| genetic_background | free_text | 遗传背景 |
| target_cell | free_text | 分化终点细胞类型 |
| culture_sys | enum | 培养体系 |
| diff_path | free_text | 分化方案描述 |
| time_pts | array | 时间点 |
| modality | array | 数据模态 |
| perturb | object_array | 扰动信息 |
| platform | free_text | 测序平台 |
| cell_line | free_text | 细胞系名称 |
| sex | enum | 性别 |
| age | free_text | 年龄 |
| reprog | free_text | 重编程方法 |
| passage | free_text | 传代信息 |
| matrix | free_text | 基质信息 |
| medium | free_text | 培养基信息 |
| density | free_text | 密度信息 |
| o2_lvl | free_text | 氧气浓度 |

## 标签类型详解

### enum（枚举）
- 用于有限的预定义选项
- LLM 会从允许的值中选择
- 示例：`["是", "否", "不明确"]`

### free_text（自由文本）
- 用于开放式的文本输入
- LLM 可以生成任意文本
- 示例：细胞系名称、年龄等

### array（数组）
- 用于多个值的列表
- LLM 生成 JSON 数组
- 示例：`["time_point_1", "time_point_2"]`

### object_array（对象数组）
- 用于复杂的结构化数据
- LLM 生成对象数组
- 示例：`[{"type": "CRISPR", "method": "..."}]`

## 在任务中使用模式

### 创建新任务时

1. 进入 **New Screening Task** 页面
2. 选择 **GEO Search** 标签页
3. 在 **Annotation Schema (Optional)** 下拉菜单中选择你的模式
4. 如果不选择，将使用默认模式
5. 创建任务

### 模式快照

- 创建任务时，选定的模式会被快照保存
- 后续修改模式不会影响已创建的任务
- 每个任务保留其创建时的标签定义

## 最佳实践

### 1. 命名规范
- 使用清晰的名称：`PSC 分化研究 v1`
- 包含版本号便于追踪
- 避免过长的名称

### 2. 标签设计
- 保持标签数量合理（不超过 20 个）
- 为每个标签提供清晰的描述
- 对于 enum 类型，列出所有可能的值

### 3. 版本管理
- 创建新版本而不是修改现有模式
- 在描述中记录变更内容
- 保留旧版本以便参考

### 4. 测试
- 在小规模任务中测试新模式
- 检查 LLM 提取的标签质量
- 根据结果调整标签定义

## 常见问题

### Q: 如何修改已使用的模式？
A: 创建一个新版本的模式，不要修改旧版本。这样可以保持数据一致性。

### Q: 可以删除模式吗？
A: 可以。删除模式不会影响已创建的任务，因为任务保存了模式的快照。

### Q: 如何导出/导入模式？
A: 目前需要手动复制标签定义。未来版本会支持导出/导入功能。

### Q: 标签顺序重要吗？
A: 是的。标签顺序会影响 LLM 的提示词生成。建议按逻辑顺序排列。

## 示例：创建自定义模式

假设你想创建一个针对"心脏分化"研究的模式：

1. 点击 **📋 Use Default Template**
2. 修改名称为："心脏分化研究"
3. 修改描述为："用于心脏分化相关研究的标注模式"
4. 在 GSE 标签中，修改"分化终点"的描述为："心脏细胞类型（心肌细胞、心房细胞等）"
5. 在 GSM 标签中，添加新标签：
   - 名称：`cardiac_marker`
   - 描述：`心脏标志物表达`
   - 类型：`free_text`
6. 点击 **Save**

现在你可以在创建任务时选择这个自定义模式。

## 技术细节

### API 端点

- `GET /annotation-schemas/default-template` - 获取默认模板
- `GET /annotation-schemas` - 列出用户的所有模式
- `POST /annotation-schemas` - 创建新模式
- `GET /annotation-schemas/{id}` - 获取特定模式
- `PUT /annotation-schemas/{id}` - 更新模式
- `DELETE /annotation-schemas/{id}` - 删除模式

### 数据格式

模式以 JSON 格式存储：

```json
{
  "id": 1,
  "name": "PSC 分化研究",
  "description": "用于 PSC 分化研究的标注模式",
  "gse_labels": [
    {
      "name": "数据模态",
      "description": "实际观察到的数据模态",
      "type": "enum",
      "allowed_values": ["scRNA-seq", "scATAC-seq", ...]
    }
  ],
  "gsm_labels": [...]
}
```

## 获取帮助

如有问题，请：
1. 检查本指南的常见问题部分
2. 查看默认模式的标签定义
3. 在小规模任务中测试
