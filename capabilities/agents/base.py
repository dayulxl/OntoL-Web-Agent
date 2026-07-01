"""
基础 Agent 抽象
--------------
所有 Agent 的基类，定义统一的 Agent 接口和执行生命周期。
"""
from abc import ABC, abstractmethod
from typing import Any, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.prebuilt import create_react_agent

from capabilities.models.interfaces import ModelInterface


class BaseAgent(ABC):
    """
    Agent 基类。

    子类需实现：
      - agent_name: 返回 Agent 名称
      - _get_system_prompt(): 返回系统提示词
      - _get_tools(): 返回工具列表
    """

    agent_name: str = "base"

    def __init__(self, model: ModelInterface):
        self.model = model
        self._agent = None

    # ------------------------------------------------------------------
    # 子类必须实现
    # ------------------------------------------------------------------

    @abstractmethod
    def _get_system_prompt(self) -> str:
        """
        返回 Agent 的系统提示词。

        子类应从 PromptRegistry 加载，不使用硬编码字符串。
        """
        ...

    @abstractmethod
    def _get_tools(self) -> list[BaseTool]:
        """返回 Agent 可用的工具列表。"""
        ...

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """初始化 Agent（使用 LangGraph ReAct Agent 预构建）。"""
        llm = await self.model.get_llm()
        tools = self._get_tools()
        system_prompt = self._get_system_prompt()

        self._agent = create_react_agent(
            model=llm,
            tools=tools,
            prompt=system_prompt,
        )

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    async def run(self, user_input: str, thread_id: Optional[str] = None) -> dict:
        """
        运行 Agent，处理用户输入。

        Args:
            user_input: 用户消息文本。
            thread_id: 线程 ID（用于多轮对话记忆）。

        Returns:
            包含 Agent 最终响应的字典。
        """
        if self._agent is None:
            await self.initialize()

        config = {"configurable": {"thread_id": thread_id or "default"}}

        result = await self._agent.ainvoke(
            {"messages": [("user", user_input)]},
            config,
        )

        return {
            "agent": self.agent_name,
            "output": result["messages"][-1].content,
            "messages": result["messages"],
        }

    async def stream(self, user_input: str, thread_id: Optional[str] = None):
        """流式运行 Agent。"""
        if self._agent is None:
            await self.initialize()

        config = {"configurable": {"thread_id": thread_id or "default"}}

        async for event in self._agent.astream_events(
            {"messages": [("user", user_input)]},
            config,
            version="v2",
        ):
            yield event
