"""
知识图谱工具集（动态注册）
------------------------
启动时从 Rust 知识图谱服务 (GET /tools) 拉取工具列表，
动态注册到 ToolRegistry，通过 POST /tools/call 统一调用。

服务地址通过 get_settings().kg_server_url 获取，可由环境变量 KG_SERVER_URL 覆盖。
"""

import json
import inspect
from typing import Any, Optional

import requests

from langchain_core.tools import tool

from capabilities.tools.registry import ToolRegistry
from common.config.settings import get_settings
from common.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 服务地址
# ---------------------------------------------------------------------------

def _kg_server_url() -> str:
    return get_settings().kg_server_url


def _invoke(tool_name: str, arguments: dict) -> str:
    """通过 POST /tools/call 统一调用知识图谱服务端的任意工具。"""
    try:
        resp = requests.post(
            f"{_kg_server_url()}/tools/call",
            json={"name": tool_name, "arguments": arguments},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        return json.dumps({"error": str(e), "tool": tool_name})


# ---------------------------------------------------------------------------
# JSON Schema type → Python type hint 映射
# ---------------------------------------------------------------------------

_JSON_TYPE_MAP = {
    "string":  str,
    "integer": int,
    "number":  float,
    "boolean": bool,
    "array":   list,
    "object":  dict,
}


def _json_to_python_type(prop: dict) -> type:
    """将 JSON Schema 属性转为 Python 类型注解。"""
    jt = prop.get("type", "string")
    return _JSON_TYPE_MAP.get(jt, str)


# ---------------------------------------------------------------------------
# 动态工具注册
# ---------------------------------------------------------------------------

def sync_tools_from_server(url: Optional[str] = None) -> int:
    """
    从知识图谱服务端拉取工具列表，动态注册到 ToolRegistry。

    Args:
        url: 服务地址，默认从 settings 读取。

    Returns:
        成功注册的工具数量。
    """
    server = url or _kg_server_url()
    try:
        resp = requests.get(f"{server}/tools", timeout=10)
        resp.raise_for_status()
        tools_list = resp.json()
    except requests.RequestException as e:
        logger.warning("无法从知识图谱服务拉取工具列表", extra={"error": str(e), "server": server})
        return 0

    count = 0
    for entry in tools_list:
        fn = entry.get("function", entry)
        name = fn.get("name", "")
        desc = fn.get("description", "")
        params = fn.get("parameters", {})

        if not name:
            continue

        # 如果已注册则跳过
        if ToolRegistry.get(name):
            logger.debug("工具已注册，跳过", extra={"tool": name})
            count += 1
            continue

        # 构建动态工具函数
        _register_dynamic_tool(name, desc, params)
        count += 1

    logger.info("知识图谱工具同步完成", extra={"count": count, "server": server})
    return count


def _register_dynamic_tool(name: str, desc: str, params: dict) -> None:
    """
    根据 JSON Schema 参数定义，动态创建一个 LangChain tool 并注册。

    参数 JSON Schema 格式 (OpenAI function calling 兼容):
    {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Entity.code"},
            "depth": {"type": "integer", "description": "深度", "default": 2}
        },
        "required": ["code"]
    }
    """
    properties = params.get("properties", {})
    required_fields = set(params.get("required", []))

    # 构建函数签名参数
    func_params: list[inspect.Parameter] = []
    param_defaults: dict[str, Any] = {}
    param_annotations: dict[str, type] = {}

    for pname, pdef in properties.items():
        ptype = _json_to_python_type(pdef)
        has_default = "default" in pdef or pname not in required_fields

        if has_default:
            default_val = pdef.get("default", None)
            param_defaults[pname] = default_val
            param = inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, default=default_val)
        else:
            param = inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY)

        func_params.append(param)
        param_annotations[pname] = ptype

    # 额外内置参数
    func_params.append(
        inspect.Parameter("_extra_args", inspect.Parameter.VAR_KEYWORD)
    )

    # 动态创建函数
    def dynamic_tool_func(*, _tool_name=name, _param_names=list(properties.keys()), **kwargs):
        """
        {desc}
        """
        # 只传定义内的参数
        payload = {}
        for k in _param_names:
            v = kwargs.get(k)
            if v is not None:
                payload[k] = v
        # 合并额外参数
        extra = kwargs.get("_extra_args", {})
        if extra:
            payload.update(extra)
        return _invoke(_tool_name, payload)

    # 设置函数元信息
    dynamic_tool_func.__name__ = name
    dynamic_tool_func.__qualname__ = name
    dynamic_tool_func.__doc__ = desc
    dynamic_tool_func.__annotations__ = param_annotations
    dynamic_tool_func.__signature__ = inspect.Signature(
        parameters=func_params,
        return_annotation=str,
    )

    # 注册到 LangChain ToolRegistry
    ToolRegistry.register_tool(name, tool(dynamic_tool_func))


# ---------------------------------------------------------------------------
# 手动强制刷新
# ---------------------------------------------------------------------------

def refresh_tools(url: Optional[str] = None) -> int:
    """清空已注册的知识图谱工具并重新同步。"""
    # 只清掉 KG 工具，不影响 ToolRegistry 里其他工具
    # 先拉取服务器工具列表，按名称清 + 重注册
    server = url or _kg_server_url()
    try:
        resp = requests.get(f"{server}/tools", timeout=10)
        resp.raise_for_status()
        tools_list = resp.json()
    except requests.RequestException as e:
        logger.warning("刷新失败: 无法获取工具列表", extra={"error": str(e)})
        return 0

    names = [entry.get("function", entry).get("name", "") for entry in tools_list]
    for n in names:
        if n:
            ToolRegistry.unregister(n)

    return sync_tools_from_server(url)


# ---------------------------------------------------------------------------
# 模块加载时自动同步
# ---------------------------------------------------------------------------

_sync_count = 0

def _auto_sync() -> int:
    global _sync_count
    try:
        _sync_count = sync_tools_from_server()
    except Exception as e:
        logger.warning("知识图谱工具初始化同步失败", extra={"error": str(e)})
    return _sync_count


# import 时触发
_sync_count = _auto_sync()
