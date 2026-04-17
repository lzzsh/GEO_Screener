import json

DEFAULT_LABEL_DIMENSIONS = [
    "数据模态",
    "分化起点",
    "扰动类型",
    "分化体系",
    "分化终点",
    "数据平台",
    "是否提供原始测序数据",
]


def default_label_schema_json() -> str:
    return json.dumps(DEFAULT_LABEL_DIMENSIONS, ensure_ascii=False)
