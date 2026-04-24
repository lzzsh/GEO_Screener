# Prompt 文件存储系统

## 概述

现在每个 annotation schema 都可以拥有自己的 prompt 模板文件。这样你可以：
- 直接修改文件，提高可见性
- 为不同的研究类型定制 prompt
- 在前端编辑并保存 prompt
- 不同 schema 使用不同的 prompt

## 文件结构

```
backend/prompts/
├── default/                          # 默认 prompt 文件
│   ├── label_prompt.txt             # GSE 级别 prompt
│   ├── gsm_label_prompt.txt         # GSM 级别 prompt
│   ├── screening_prompt.txt         # 筛选 prompt
│   └── paper_calibration_prompt.txt # 论文校准 prompt
└── {schema_name}/                   # 每个 schema 一个目录
    ├── label_prompt.txt
    ├── gsm_label_prompt.txt
    ├── screening_prompt.txt
    └── paper_calibration_prompt.txt
```

## 工作流程

### 1. 创建 Schema 时
- 后端自动在 `backend/prompts/{schema_name}/` 创建目录
- 从 `backend/prompts/default/` 复制默认 prompt 文件

### 2. 使用 Schema 时
- 任务执行时，llm_client 会加载对应 schema 的 prompt
- 加载优先级：
  1. `backend/prompts/{schema_name}/{prompt_type}.txt`
  2. `backend/prompts/default/{prompt_type}.txt`
  3. 代码中的常量（后备）

### 3. 编辑 Prompt
- 在前端 Criteria 页面，选择 schema 后点击 "Prompts" 标签
- 选择要编辑的 prompt 类型
- 修改内容后点击 "Save Prompt"
- 文件会被保存到 `backend/prompts/{schema_name}/{prompt_type}.txt`

### 4. 删除 Schema 时
- 后端自动删除对应的 prompt 文件目录

## API 端点

### 获取 Prompt
```
GET /annotation-schemas/{schema_id}/prompts/{prompt_type}
```

返回：
```json
{
  "content": "prompt 文本内容"
}
```

### 保存 Prompt
```
PUT /annotation-schemas/{schema_id}/prompts/{prompt_type}
```

请求体：
```json
{
  "content": "新的 prompt 文本内容"
}
```

## 代码修改

### llm_client.py
- 添加 `_load_prompt(schema_name, prompt_type)` 方法
- `extract_labels()` 现在接收 `schema_name` 参数
- `annotate_gsm()` 现在接收 `schema_name` 参数

### tasks.py
- 从 AnnotationSchema 获取 schema 名称
- 调用 llm_client 方法时传递 `schema_name` 参数

### annotation_schema.py
- 创建 schema 时自动创建 prompt 文件
- 删除 schema 时自动删除 prompt 文件

### prompts.py（新文件）
- 提供 GET/PUT 端点管理 prompt 文件

### criteria.html
- 添加 "Prompts" 标签页
- 支持选择和编辑不同的 prompt 类型
- 实时保存到文件

## 示例

### 创建自定义 Schema
1. 登录系统
2. 点击 "Criteria" → "Annotation Schemas"
3. 点击 "📋 Use Default Template"
4. 修改名称为 "心脏分化研究"
5. 点击 "Save"

### 编辑 Prompt
1. 选择刚创建的 schema
2. 点击 "Prompts" 标签
3. 选择 "GSE Label Prompt"
4. 修改纳入标准为心脏分化相关内容
5. 点击 "Save Prompt"

### 使用自定义 Prompt
1. 创建新任务
2. 在 "Annotation Schema" 下拉菜单选择 "心脏分化研究"
3. 创建任务
4. LLM 会自动使用自定义的 prompt

## 注意事项

- 修改 prompt 文件后，新的任务会使用新 prompt
- 已有的任务不受影响（使用创建时的 prompt）
- 删除 schema 会删除对应的 prompt 文件
- 默认 prompt 文件不应该被删除（作为后备）
