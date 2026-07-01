"""
航路规划 Agent
-------------
专注于航路查询、途径点解析、路线生成和备选方案评估的 Agent。

属于 business/route_planning/ 业务域，使用域专用工具和提示词。
"""
import os
from typing import Optional

from langchain_core.tools import BaseTool

from capabilities.agents.base import BaseAgent
from capabilities.prompts.registry import PromptRegistry
from capabilities.tools.registry import ToolRegistry

# Agent 所在目录，用于加载域专用提示词文件
_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))


class RoutePlanningAgent(BaseAgent):
    """
    航路规划 Agent。

    职责:
      - 解析用户航路查询意图（规划、修改、对比）
      - 获取 / 解析途径点信息
      - 调用航路生成工具生成路线
      - 评估并输出备选方案

    工具集（从 ToolRegistry 按名获取）:
      - waypoint_resolver: 途径点解析
      - route_generator: 路线生成
      - route_evaluator: 备选方案评估

    提示词:
      优先加载 business/route_planning/prompts/agent.txt；
      若文件缺失则回退到 PromptRegistry 默认值。
    """

    agent_name = "route_planning"

    # ------------------------------------------------------------------
    # BaseAgent 抽象方法实现
    # ------------------------------------------------------------------

    def _get_system_prompt(self) -> str:
        """加载域专用提示词，文件缺失时回退到 PromptRegistry。"""
        prompt_file = os.path.join(_AGENT_DIR, "prompts", "agent.txt")
        if os.path.isfile(prompt_file):
            with open(prompt_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        return PromptRegistry.get_agent("route_planning")

    def _get_tools(self) -> list[BaseTool]:
        """返回航路规划专用工具列表。"""
        tools = []
        for tool_name in ("waypoint_resolver", "route_generator", "route_evaluator"):
            tool = ToolRegistry.get(tool_name)
            if tool:
                tools.append(tool)
        return tools
