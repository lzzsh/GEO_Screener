# 注解模式快速参考

## 🚀 5 分钟快速开始

### 步骤 1：打开模式管理
- 登录 → 点击 **Criteria** → 切换到 **Annotation Schemas** 标签

### 步骤 2：使用默认模式
- 点击 **📋 Use Default Template** 按钮
- 修改名称（例如："我的研究"）
- 点击 **Save**

### 步骤 3：在任务中使用
- 创建新任务 → GEO Search 标签页
- 在 **Annotation Schema** 下拉菜单选择你的模式
- 创建任务

完成！LLM 会自动使用你的标签定义提取数据。

---

## 📋 默认模式包含的标签

### GSE 标签（7 个）
```
✓ 数据模态 (enum)
✓ 分化起点 (enum)
✓ 扰动类型 (enum)
✓ 分化体系 (enum)
✓ 分化终点 (free_text)
✓ 数据平台 (free_text)
✓ 是否提供原始测序数据 (enum)
```

### GSM 标签（18 个）
```
✓ start_cell, genetic_background, target_cell
✓ culture_sys, diff_path, time_pts, modality
✓ perturb, platform, cell_line, sex, age
✓ reprog, passage, matrix, medium, density, o2_lvl
```

---

## 🎯 常见操作

| 操作 | 步骤 |
|------|------|
| **创建新模式** | 点击 **+ New Schema** → 填写信息 → Save |
| **基于默认创建** | 点击 **📋 Use Default Template** → 修改名称 → Save |
| **编辑模式** | 点击模式 → 修改信息 → Save |
| **删除模式** | 点击模式 → 点击 **Delete** → 确认 |
| **添加标签** | 在编辑器中点击 **+ Add Label** |
| **删除标签** | 点击标签右侧的 **✕** |

---

## 🏷️ 标签类型

| 类型 | 用途 | 示例 |
|------|------|------|
| **enum** | 预定义选项 | `["是", "否", "不明确"]` |
| **free_text** | 自由输入 | 细胞系名称、年龄 |
| **array** | 多个值 | `["time_1", "time_2"]` |
| **object_array** | 复杂结构 | `[{"type": "CRISPR"}]` |

---

## 💡 提示

- 📌 **版本管理**：创建新版本而不是修改旧版本
- 🔍 **测试**：在小规模任务中先测试新模式
- 📝 **命名**：使用清晰的名称和版本号
- ⚡ **快照**：任务创建时会保存模式快照，后续修改不影响已有任务

---

## ❓ 常见问题

**Q: 如何修改已使用的模式？**
A: 创建新版本，不要修改旧版本。

**Q: 删除模式会影响已有任务吗？**
A: 不会。任务保存了模式的快照。

**Q: 可以导出模式吗？**
A: 目前需要手动复制。未来版本会支持。

**Q: 标签顺序重要吗？**
A: 是的。顺序会影响 LLM 提示词。

---

## 📞 需要帮助？

查看完整指南：`ANNOTATION_SCHEMA_GUIDE.md`
