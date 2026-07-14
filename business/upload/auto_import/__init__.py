"""
全自动导入四步管线 — 统一下载入口
=================================
四个步骤各自独立，每步一个 Python 文件，通过 business/api/ 统一暴露。

    from business.upload.auto_import import (
        run_parse_pipeline,   # Step 1: AI 本体解析
        validate_entities,     # Step 2: 模板校验 & 字段补全
        enrich_entities,       # Step 3: 符号语言填充 & 推理机校验
        import_to_graph,       # Step 4: 导入 Memgraph 图数据库
    )
"""
from business.upload.auto_import.step1_parse import run_parse_pipeline      # noqa: F401
from business.upload.auto_import.step2_validate import validate_entities     # noqa: F401
from business.upload.auto_import.step3_enrich import enrich_entities         # noqa: F401
from business.upload.auto_import.step4_import import import_to_graph         # noqa: F401
