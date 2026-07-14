"""
Step 1 — AI 本体解析
====================
两阶段 AI 解析管线：文本提取 → LLM 分类 → LLM 字段提取。

单入口: run_parse_pipeline(filename, model) -> dict
纯函数无副作用，内部调用不查库不写文件（LLM 调用除外）。
"""


async def run_parse_pipeline(filename: str, model: str = "") -> dict:
    """两阶段 AI 解析管线 — 单入口。

    阶段1: LLM 分类 (每个文本块识别实体名→本体类型 + 三元组关系)
    阶段2: LLM 字段提取 (每种类型一组，从原文提取属性值)

    Returns: {filename, entity_count, relationship_count, type_counts,
              entities, relationships, chunks_total, chunks_success,
              chunks_failed, chunk_errors}
    """
    from business.upload.parser import _run_parse_pipeline as _run
    return await _run(filename, model)
