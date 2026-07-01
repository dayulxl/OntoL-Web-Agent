"""
工具注册中心
----------
提供工具的注册、发现和获取功能。支持通过装饰器注册，兼容 MCP 协议标准化。
"""
from typing import Callable, Optional

from langchain_core.tools import tool, BaseTool


class ToolRegistry:
    """
    工具注册中心（类级单例模式）。

    使用方式:
        # 注册工具
        @ToolRegistry.register("weather_search")
        def get_weather(city: str) -> str:
            '''查询城市天气'''
            ...

        # 获取工具
        weather_tool = ToolRegistry.get("weather_search")
        all_tools = ToolRegistry.get_all()
    """

    _tools: dict[str, BaseTool] = {}

    @classmethod
    def register(cls, name: Optional[str] = None) -> Callable:
        """
        装饰器：将函数注册为 LangChain Tool。

        Args:
            name: 工具名称（若不提供则使用函数名）。
        """
        def decorator(func: Callable) -> BaseTool:
            tool_name = name or func.__name__
            wrapped = tool(func)
            cls._tools[tool_name] = wrapped
            return wrapped
        return decorator

    @classmethod
    def register_tool(cls, name: str, tool_instance: BaseTool) -> None:
        """直接注册一个已创建的 Tool 实例。"""
        cls._tools[name] = tool_instance

    @classmethod
    def get(cls, name: str) -> Optional[BaseTool]:
        """按名称获取工具。"""
        return cls._tools.get(name)

    @classmethod
    def get_all(cls) -> list[BaseTool]:
        """获取所有已注册的工具。"""
        return list(cls._tools.values())

    @classmethod
    def list_names(cls) -> list[str]:
        """列出所有已注册的工具名称。"""
        return list(cls._tools.keys())

    @classmethod
    def unregister(cls, name: str) -> None:
        """移除一个已注册的工具。"""
        cls._tools.pop(name, None)

    @classmethod
    def clear(cls) -> None:
        """清空所有已注册的工具。"""
        cls._tools.clear()

    # ------------------------------------------------------------------
    # MCP 协议兼容
    # ------------------------------------------------------------------

    @classmethod
    def to_mcp_tools(cls) -> list[dict]:
        """
        将所有注册的工具转换为 MCP 协议格式的工具描述。

        返回格式符合 Model Context Protocol (MCP) 规范。
        """
        mcp_tools = []
        for name, t in cls._tools.items():
            mcp_tools.append({
                "name": name,
                "description": t.description or "",
                "inputSchema": t.args_schema.schema() if t.args_schema else {},
            })
        return mcp_tools
