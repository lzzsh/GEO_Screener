# llm_client.py 结构分析

## 📋 文件整体结构

```
llm_client.py
├── 导入和配置（第 1-13 行）
├── 提示词模板（第 15-230 行）
│   ├── LABEL_PROMPT_TEMPLATE（GSE 标签提示词）
│   ├── GSM_LABEL_PROMPT_TEMPLATE（GSM 标签提示词）
│   ├── SCREENING_PROMPT_TEMPLATE（筛选提示词）
│   └── PAPER_CALIBRATION_PROMPT_TEMPLATE（论文校准提示词）
└── LLMClient 类（第 232-370 行）
    ├── __init__（初始化）
    ├── _build_label_spec（标签规范生成）
    ├── _create_chat_completion（API 调用）
    ├── screen_dataset（数据集筛选）
    ├── calibrate_with_paper（论文校准）
    ├── extract_labels（标签提取）
    ├── annotate_gsm（GSM 标注）
    ├── _parse_json（JSON 解析）
    └── test_connection（连接测试）
```

---

## 🔧 可灵活更改的部分

### 1️⃣ **提示词模板**（最灵活）

#### LABEL_PROMPT_TEMPLATE（第 15-104 行）
**用途**：GSE 级别的数据集筛选和标签提取

**可更改内容**：
- ✅ **纳入标准**（第 22-46 行）
  - 修改筛选条件
  - 调整排除标准
  - 更新数据类型要求
  
- ✅ **输出格式**（第 61-73 行）
  - 修改 JSON 结构
  - 调整字段名称
  - 改变输出要求

- ✅ **判定规则**（第 77-103 行）
  - 调整判定逻辑
  - 修改字段填写规则
  - 更新标准化值

**示例**：
```python
# 修改纳入标准
LABEL_PROMPT_TEMPLATE = """\
你是一个数据筛选助手...

## 纳入标准

本研究纳入"心脏分化相关的单细胞数据"，具体要求如下：
1. 起始细胞：心脏前体细胞、心肌细胞或相关细胞系
2. 数据类型：scRNA-seq、scATAC-seq 等单细胞数据
...
"""
```

#### GSM_LABEL_PROMPT_TEMPLATE（第 106-184 行）
**用途**：GSM 级别的样本标注

**可更改内容**：
- ✅ **纳入标准**（第 113-118 行）
- ✅ **输出格式**（第 136-145 行）
- ✅ **判定规则**（第 149-183 行）

#### SCREENING_PROMPT_TEMPLATE（第 186-205 行）
**用途**：基于用户自定义标准的筛选

**可更改内容**：
- ✅ **输出格式**（第 198-204 行）
- ✅ **指令**（第 197 行）

#### PAPER_CALIBRATION_PROMPT_TEMPLATE（第 207-230 行）
**用途**：使用论文全文进行校准

**可更改内容**：
- ✅ **优先级规则**（第 209 行）
- ✅ **输出格式**（第 223-229 行）

---

### 2️⃣ **LLMClient 类方法**（中等灵活）

#### `_build_label_spec()` 方法（第 242-265 行）
**用途**：将标签定义转换为提示词中的字段说明

**可更改内容**：
- ✅ **字段描述格式**（第 253-260 行）
  ```python
  # 当前：使用"；"分隔
  value = "；".join(parts)
  
  # 可改为：使用其他分隔符
  value = "\n".join(parts)  # 换行分隔
  value = " | ".join(parts)  # 竖线分隔
  ```

- ✅ **类型处理逻辑**（第 254-259 行）
  ```python
  # 可添加新的类型处理
  elif ltype == "boolean":
      parts.append("true 或 false")
  elif ltype == "number":
      parts.append("数字格式")
  ```

- ✅ **默认值处理**（第 260 行）
  ```python
  # 当前：所有字段都加"无原文依据则填空字符串"
  # 可改为：根据类型不同处理
  if ltype == "enum":
      parts.append("无原文依据则填空字符串")
  elif ltype == "array":
      parts.append("无原文依据则填 []")
  ```

#### `_create_chat_completion()` 方法（第 267-275 行）
**用途**：调用 LLM API 并处理重试

**可更改内容**：
- ✅ **重试策略**（第 268-275 行）
  ```python
  # 当前：3 次重试，指数退避
  # 可改为：
  retry_statuses = {429, 500, 502, 503, 504, 408}  # 添加 408
  for attempt in range(5):  # 改为 5 次
      await asyncio.sleep(1.0 * (attempt + 1))  # 改为线性退避
  ```

- ✅ **错误处理**（第 272-274 行）
  ```python
  # 可添加日志记录
  logger.warning(f"API error {exc.status_code}, retrying...")
  ```

#### `extract_labels()` 方法（第 309-320 行）
**用途**：提取 GSE 标签

**可更改内容**：
- ✅ **温度参数**（第 316 行）
  ```python
  # 当前：temperature=0（确定性）
  # 可改为：temperature=0.1（略有变化）
  ```

- ✅ **提示词模板**（第 311 行）
  ```python
  # 可使用不同的模板
  prompt = CUSTOM_LABEL_TEMPLATE.format(...)
  ```

#### `annotate_gsm()` 方法（第 322-342 行）
**用途**：标注 GSM 样本

**可更改内容**：
- ✅ **字段处理**（第 325-327 行）
  ```python
  # 当前：添加逗号
  # 可改为：添加其他分隔符或格式
  ```

- ✅ **错误处理**（第 339-341 行）
  ```python
  # 可改为返回默认值而不是抛出异常
  if not raw:
      return {"avail": "unknown", "response": "No response"}
  ```

#### `_parse_json()` 方法（第 344-361 行）
**用途**：解析 LLM 返回的 JSON

**可更改内容**：
- ✅ **容错策略**（第 345-361 行）
  ```python
  # 可添加更多容错逻辑
  # 例如：自动修复常见的 JSON 错误
  text = text.replace("'", '"')  # 单引号改双引号
  text = re.sub(r',\s*}', '}', text)  # 移除末尾逗号
  ```

---

### 3️⃣ **配置部分**（低灵活性，但可扩展）

#### PROVIDER_DEFAULTS（第 7-13 行）
**用途**：LLM 提供商配置

**可更改内容**：
- ✅ **添加新提供商**
  ```python
  PROVIDER_DEFAULTS: dict[str, dict] = {
      "deepseek": {...},
      "glm": {...},
      "minimax": {...},
      "campus-minimax": {...},
      "campus-glm": {...},
      "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4"},  # 新增
      "claude": {"base_url": "https://api.anthropic.com/v1", "model": "claude-3"},  # 新增
  }
  ```

- ✅ **修改现有提供商**
  ```python
  "deepseek": {
      "base_url": "https://api.deepseek.com/v1",
      "model": "deepseek-chat-v2",  # 更新模型版本
  }
  ```

---

## 📊 灵活性等级对比

| 部分 | 灵活性 | 影响范围 | 修改难度 |
|------|--------|---------|---------|
| **提示词模板** | ⭐⭐⭐⭐⭐ | 全局 | 简单 |
| **_build_label_spec()** | ⭐⭐⭐⭐ | 标签处理 | 简单 |
| **extract_labels()** | ⭐⭐⭐ | 标签提取 | 中等 |
| **_create_chat_completion()** | ⭐⭐⭐ | API 调用 | 中等 |
| **_parse_json()** | ⭐⭐⭐ | JSON 解析 | 中等 |
| **PROVIDER_DEFAULTS** | ⭐⭐ | 配置 | 简单 |
| **LLMClient.__init__()** | ⭐⭐ | 初始化 | 简单 |

---

## 🎯 常见修改场景

### 场景 1：修改筛选标准
```python
# 修改 LABEL_PROMPT_TEMPLATE 中的"纳入标准"部分
# 例如：从"PSC 分化"改为"心脏分化"

LABEL_PROMPT_TEMPLATE = """\
...
## 纳入标准

本研究仅纳入"心脏分化过程中的单细胞数据"，具体要求如下：

1. 起始细胞
- 必须为心脏前体细胞或相关细胞系
...
"""
```

### 场景 2：添加新的标签类型
```python
# 在 _build_label_spec() 中添加新类型处理
elif ltype == "date":
    parts.append("日期格式 (YYYY-MM-DD)")
elif ltype == "url":
    parts.append("URL 格式")
```

### 场景 3：修改输出格式
```python
# 修改 LABEL_PROMPT_TEMPLATE 中的输出要求
# 从 JSON 改为其他格式（如 CSV、XML）

JSON 必须使用以下结构：
{
  "GSE_ID": "{dataset_id}",
  "reasoning_text": "...",
  "final_conclusion": "...",
  ...
}
```

### 场景 4：添加新的 LLM 提供商
```python
# 在 PROVIDER_DEFAULTS 中添加
"custom-provider": {
    "base_url": "https://custom.api.com/v1",
    "model": "custom-model-v1"
}

# 然后使用
client = LLMClient(provider="custom-provider", api_key="...")
```

### 场景 5：修改重试策略
```python
# 在 _create_chat_completion() 中修改
retry_statuses = {429, 500, 502, 503, 504, 408, 409}
for attempt in range(5):  # 改为 5 次
    try:
        return await self._client.chat.completions.create(**kwargs)
    except APIStatusError as exc:
        if exc.status_code not in retry_statuses or attempt == 4:
            raise
        wait_time = 2 ** attempt  # 指数退避
        await asyncio.sleep(wait_time)
```

---

## ⚠️ 修改时的注意事项

### 1. 提示词修改
- ✅ 可以自由修改纳入标准
- ✅ 可以修改输出格式
- ⚠️ 修改后需要测试 LLM 是否能正确理解
- ⚠️ 修改输出格式后需要更新 `_parse_json()` 方法

### 2. 方法修改
- ✅ 可以修改内部逻辑
- ⚠️ 不要改变方法签名（参数和返回值）
- ⚠️ 修改后需要运行测试确保兼容性

### 3. 配置修改
- ✅ 可以添加新提供商
- ✅ 可以修改现有提供商配置
- ⚠️ 确保 base_url 和 model 正确

---

## 🔗 与其他文件的关系

```
llm_client.py
├── 被调用者
│   ├── backend/worker/tasks.py（任务工作流）
│   ├── backend/routers/annotate.py（API 路由）
│   └── backend/tests/test_llm_client.py（测试）
│
├── 依赖
│   ├── openai（AsyncOpenAI 客户端）
│   ├── asyncio（异步处理）
│   └── json（JSON 解析）
│
└── 配置来源
    ├── backend/models.py（LLMConfig 模型）
    └── backend/label_schema.py（标签定义）
```

---

## 📝 修改检查清单

修改前：
- [ ] 理解当前逻辑
- [ ] 确认修改范围
- [ ] 备份原始代码

修改中：
- [ ] 保持方法签名不变
- [ ] 添加必要的注释
- [ ] 遵循现有代码风格

修改后：
- [ ] 运行单元测试
- [ ] 测试 LLM 输出
- [ ] 检查向后兼容性
- [ ] 更新相关文档

---

## 💡 推荐修改顺序

1. **第一步**：修改提示词模板（最安全）
2. **第二步**：修改 `_build_label_spec()` 方法
3. **第三步**：修改 `_create_chat_completion()` 重试策略
4. **第四步**：修改 `_parse_json()` 容错逻辑
5. **第五步**：添加新的 LLM 提供商

每一步都应该独立测试，确保不会破坏现有功能。
