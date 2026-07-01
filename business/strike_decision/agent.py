"""
打击决策 Agent
------------
专注于目标证据采集、风险评估和打击/监控/放行决策的 Agent。

属于 business/strike_decision/ 业务域，使用域专用工具和提示词。
"""
import os
from typing import Optional

from langchain_core.tools import BaseTool

from capabilities.agents.base import BaseAgent
from capabilities.prompts.registry import PromptRegistry
from capabilities.tools.registry import ToolRegistry

# Agent 所在目录，用于加载域专用提示词文件
_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))


class StrikeDecisionAgent(BaseAgent):
    """
    打击决策 Agent。

    职责:
      - 采集目标相关证据数据（多源情报）
      - 评估目标风险等级（调用风险评估模型）
      - 做出打击 / 监控 / 放行的最终决策

    工具集（从 ToolRegistry 按名获取）:
      - evidence_collector: 多源证据采集
      - risk_assessor: 风险评估
      - strike_executor: 打击执行
      - monitor_registrar: 监控注册
      - audit_logger: 审计日志记录

    提示词:
      优先加载 business/strike_decision/prompts/agent.txt；
      若文件缺失则回退到 PromptRegistry 默认值。
    """

    agent_name = "strike_decision"

    # ------------------------------------------------------------------
    # BaseAgent 抽象方法实现
    # ------------------------------------------------------------------

    def _get_system_prompt(self) -> str:
        """加载域专用提示词，文件缺失时回退到 PromptRegistry。"""
        prompt_file = os.path.join(_AGENT_DIR, "prompts", "agent.txt")
        if os.path.isfile(prompt_file):
            with open(prompt_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        return PromptRegistry.get_agent("strike_decision")

    def _get_tools(self) -> list[BaseTool]:
        """返回打击决策专用工具列表。"""
        tools = []
        for tool_name in (
            "evidence_collector",
            "risk_assessor",
            "strike_executor",
            "monitor_registrar",
            "audit_logger",
        ):
            tool = ToolRegistry.get(tool_name)
            if tool:
                tools.append(tool)
        return tools
