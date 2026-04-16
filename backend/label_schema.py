import json

DEFAULT_LABEL_DIMENSIONS = [
    "起始细胞类型",
    "分化体系",
    "数据平台",
    "是否提供原始测序数据",
    "单细胞测序数据类型",
]


def default_label_schema_json() -> str:
    return json.dumps(DEFAULT_LABEL_DIMENSIONS, ensure_ascii=False)
