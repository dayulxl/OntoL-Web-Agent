"""
Step 2 — 模板校验 & 字段补全
===========================
检查 AI 解析产出的实体是否匹配 ontol_model 模板，计算缺失字段。

单入口: validate_entities(entities) -> dict
纯 Python，不查库不调 LLM（本体类型从缓存加载）。
"""


def validate_entities(entities: list[dict]) -> dict:
    """校验实体：本体模板匹配 + 继承链缺失字段计算。

    Returns: {valid, type_counts, unknown_types, missing_fields, summary}
    """
    from business.upload.validation import validate_entities_for_import as _validate
    return _validate(entities)
