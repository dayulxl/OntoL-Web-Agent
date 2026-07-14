"""文件上传 & 实体解析业务域。

子模块:
- prompts: LLM 提示词构建 (分类 / 字段提取)
- parser: 文件文本提取 + LLM JSON 解析
- validation: 实体校验 (模板匹配 + 缺失字段)
- snowflake: 雪花 ID 生成
- import_service: 图数据库导入 (节点/关系/场景绑定)
"""
