"""
提示词注册中心 (Prompt Registry)
-------------------------------
集中管理所有 LLM 提示词模板。提示词以文件形式存储（.txt 或 .yaml），
按 domain/name 组织，支持版本化、默认值和回退策略。

设计目标：
  - 非技术人员也可编辑提示词（纯文本文件）
  - 修改提示词不需要重新部署代码（配合 DynamicConfig 热加载）
  - 提示词按业务域分组管理
  - 支持 A/B 测试（多版本共存）

目录结构:
    capabilities/prompts/
    ├── registry.py          # 本文件 — PromptRegistry
    ├── agents/              # Agent 系统提示词
    │   ├── master.txt       # 总调度 Agent（意图识别）
    │   ├── research.txt
    │   ├── coding.txt
    │   ├── route_planning.txt
    │   └── strike_decision.txt
    └── chains/              # Chain 提示词模板
        ├── rag.txt
        └── summary.txt
"""
import os
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate


# 提示词文件根目录
_PROMPTS_ROOT = os.path.dirname(os.path.abspath(__file__))


class PromptRegistry:
    """
    提示词注册中心（类级单例）。

    加载策略:
      1. 先从缓存读取
      2. 缓存未命中则从文件加载
      3. 文件不存在则返回内置默认值

    使用方式:
        # Agent 提示词
        prompt = PromptRegistry.get_agent("research")

        # Chain 提示词模板
        template = PromptRegistry.get_chain_template("rag")
    """

    _agent_cache: dict[str, str] = {}
    _chain_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Agent 提示词
    # ------------------------------------------------------------------

    @classmethod
    def get_agent(cls, name: str) -> str:
        """
        获取 Agent 系统提示词。

        Args:
            name: Agent 名称（如 "research", "coding"）。

        Returns:
            提示词文本。若文件未找到则返回内置默认值。
        """
        if name in cls._agent_cache:
            return cls._agent_cache[name]

        prompt = cls._load_file(f"agents/{name}.txt")
        if prompt is None:
            prompt = cls._agent_default(name)

        cls._agent_cache[name] = prompt
        return prompt

    @classmethod
    def _agent_default(cls, name: str) -> str:
        """Agent 提示词的内置默认值 — 当文件不存在时的回退。"""
        defaults = {
            "research": (
                "你是一个专业的研究助手。你的职责是：\n"
                "1. 根据用户的问题，制定检索计划\n"
                "2. 使用搜索工具查找相关信息\n"
                "3. 综合多源信息，给出准确、有引用的回答\n"
                "4. 当信息不足时，诚实地告知用户并建议进一步搜索的方向"
            ),
            "coding": (
                "你是一个专业的编程助手。你的职责是：\n"
                "1. 理解用户的编程需求\n"
                "2. 编写清晰、可维护的代码\n"
                "3. 考虑边界情况和错误处理\n"
                "4. 提供代码解释和最佳实践建议"
            ),
            "route_planning": (
                "你是一个专业的航路规划助手。你的职责是：\n"
                "1. 解析用户的航路查询意图（新建航路、修改现有航路、对比方案等）\n"
                "2. 解析起止点和途经点坐标信息\n"
                "3. 调用航路生成工具生成最优路线\n"
                "4. 评估多条备选路线，按距离/时间/安全等多维度排序\n"
                "5. 输出格式化的航路报告供用户决策\n"
                "当输入信息不足时，主动向用户询问必要信息。"
            ),
            "strike_decision": (
                "你是一个专业的打击决策助手。你的职责是：\n"
                "1. 从多源情报采集目标相关证据（行为模式、关联关系、威胁等级）\n"
                "2. 调用风险评估模型对目标进行量化分析\n"
                "3. 根据风险评分做出打击/监控/放行决策\n"
                "4. 对每项决策提供充分的证据支撑和审计记录\n"
                "当证据不足或风险评分处于临界区间时，必须明确标注不确定性并建议保守决策。"
            ),
            "master": (
                "你是一个意图识别调度器。分析用户输入，判断应调用哪个业务 Agent。\n\n"
                "三种意图:\n"
                "  - route_planning: 航路/路线规划相关（关键词：航路、航线、规划、途径点、飞行）\n"
                "  - strike_decision: 打击/决策相关（关键词：打击、目标、威胁、风险、决策、评估）\n"
                "  - overall: 同时涉及以上两者，需要整体规划（关键词：整体、全面、综合、协同、联合）\n\n"
                "必须输出 JSON:\n"
                '{"intent": "<route_planning|strike_decision|overall>",'
                '"reason": "<简短理由>",'
                '"sub_queries": {"route_planning": "<子查询或null>", "strike_decision": "<子查询或null>"}}\n'
                "无法判断或与航路/打击均无关时默认选择 overall。只输出 JSON，不要额外文字。"
            ),
        }
        return defaults.get(name, "你是一个智能助手。请根据用户需求提供帮助。")

    # ------------------------------------------------------------------
    # Chain 提示词模板
    # ------------------------------------------------------------------

    @classmethod
    def get_chain_template(cls, name: str) -> str:
        """
        获取 Chain 提示词模板。

        模板使用 {variable_name} 占位符语法,
        与 LangChain ChatPromptTemplate.from_template() 兼容。

        Args:
            name: Chain 名称（如 "rag", "summary"）。

        Returns:
            模板字符串。
        """
        if name in cls._chain_cache:
            return cls._chain_cache[name]

        template = cls._load_file(f"chains/{name}.txt")
        if template is None:
            template = cls._chain_default(name)

        cls._chain_cache[name] = template
        return template

    @classmethod
    def get_chain_prompt(cls, name: str) -> ChatPromptTemplate:
        """
        获取已格式化的 ChatPromptTemplate 对象。

        Args:
            name: Chain 名称。

        Returns:
            可直接用于 LCEL 管道的 ChatPromptTemplate。
        """
        template = cls.get_chain_template(name)
        return ChatPromptTemplate.from_template(template)

    @classmethod
    def _chain_default(cls, name: str) -> str:
        """Chain 模板的内置默认值。"""
        defaults = {
            "rag": (
                "你是一个知识助手。请根据以下上下文回答用户的问题。\n\n"
                "上下文:\n"
                "{context}\n\n"
                "问题: {question}\n\n"
                "回答:"
            ),
            "summary": (
                "请对以下文本进行简洁的摘要：\n\n"
                "文本:\n"
                "{text}\n\n"
                "摘要:"
            ),
        }
        return defaults.get(name, "请处理以下输入:\n{input}")

    # ------------------------------------------------------------------
    # 文件加载
    # ------------------------------------------------------------------

    @classmethod
    def _load_file(cls, relative_path: str) -> Optional[str]:
        """从文件加载提示词。返回 None 表示文件不存在。"""
        file_path = os.path.join(_PROMPTS_ROOT, relative_path)
        if os.path.isfile(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        return None

    # ------------------------------------------------------------------
    # 缓存管理
    # ------------------------------------------------------------------

    @classmethod
    def reload(cls, name: Optional[str] = None) -> None:
        """
        清除缓存，强制从文件重新加载。

        Args:
            name: 指定名称（仅重载该条目）；None 表示全部重载。
        """
        if name:
            cls._agent_cache.pop(name, None)
            cls._chain_cache.pop(name, None)
        else:
            cls._agent_cache.clear()
            cls._chain_cache.clear()

    @classmethod
    def list_agents(cls) -> list[str]:
        """列出所有已知的 Agent 提示词。"""
        agents_dir = os.path.join(_PROMPTS_ROOT, "agents")
        if os.path.isdir(agents_dir):
            return sorted(
                f.replace(".txt", "")
                for f in os.listdir(agents_dir)
                if f.endswith(".txt")
            )
        return []

    @classmethod
    def list_chains(cls) -> list[str]:
        """列出所有已知的 Chain 提示词模板。"""
        chains_dir = os.path.join(_PROMPTS_ROOT, "chains")
        if os.path.isdir(chains_dir):
            return sorted(
                f.replace(".txt", "")
                for f in os.listdir(chains_dir)
                if f.endswith(".txt")
            )
        return []
