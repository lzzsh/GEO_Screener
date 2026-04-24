import json

DEFAULT_GSE_LABELS = [
    {"name": "数据模态", "description": "实际观察到的数据模态", "type": "enum",
     "allowed_values": ["scRNA-seq", "scATAC-seq", "spatial transcriptomics", "CITE-seq", "multiome", "bulk RNA-seq", "ribosome profiling"]},
    {"name": "分化起点", "description": "起始细胞类型", "type": "enum",
     "allowed_values": ["iPSC", "ESC", "PSC"]},
    {"name": "扰动类型", "description": "实验扰动类型", "type": "enum",
     "allowed_values": ["TF", "小分子", "CRISPR", "其他"]},
    {"name": "分化体系", "description": "分化培养体系", "type": "enum",
     "allowed_values": ["2D", "3D"]},
    {"name": "分化终点", "description": "分化目标细胞类型", "type": "free_text"},
    {"name": "数据平台", "description": "测序平台", "type": "free_text"},
    {"name": "是否提供原始测序数据", "description": "是否提供原始测序数据", "type": "enum",
     "allowed_values": ["是", "否", "不明确"]},
]

DEFAULT_GSM_LABELS = [
    {"name": "start_cell", "description": "起始细胞类型", "type": "enum",
     "allowed_values": ["iPSC", "ESC", "PSC"]},
    {"name": "genetic_background", "description": "遗传背景", "type": "free_text"},
    {"name": "target_cell", "description": "分化终点细胞类型", "type": "free_text"},
    {"name": "culture_sys", "description": "培养体系", "type": "enum",
     "allowed_values": ["2D", "3D", "2D/3D Mixed"]},
    {"name": "diff_path", "description": "分化方案描述", "type": "free_text"},
    {"name": "time_pts", "description": "时间点", "type": "array"},
    {"name": "modality", "description": "数据模态", "type": "array"},
    {"name": "perturb", "description": "扰动信息", "type": "object_array"},
    {"name": "platform", "description": "测序平台", "type": "free_text"},
    {"name": "cell_line", "description": "细胞系名称", "type": "free_text"},
    {"name": "sex", "description": "性别", "type": "enum",
     "allowed_values": ["Female", "Male", "Unknown"]},
    {"name": "age", "description": "年龄", "type": "free_text"},
    {"name": "reprog", "description": "重编程方法", "type": "free_text"},
    {"name": "passage", "description": "传代信息", "type": "free_text"},
    {"name": "matrix", "description": "基质信息", "type": "free_text"},
    {"name": "medium", "description": "培养基信息", "type": "free_text"},
    {"name": "density", "description": "密度信息", "type": "free_text"},
    {"name": "o2_lvl", "description": "氧气浓度", "type": "free_text"},
]


def default_label_schema_json() -> str:
    return json.dumps({
        "gse": DEFAULT_GSE_LABELS,
        "gsm": DEFAULT_GSM_LABELS,
    }, ensure_ascii=False)
