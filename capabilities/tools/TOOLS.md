# TOOLS.md — 工具注册中心子模块约束

> **定位**: `ToolRegistry` 是类级单例，所有工具集中注册、统一管理。提供 MCP 协议兼容的导出能力。

**目录**: [文件清单](#1-文件清单) | [ToolRegistry 契约](#2-toolregistry-契约) | [新增工具规范](#3-新增工具规范) | [Tool 实现约束](#4-tool-实现约束) | [MCP 兼容](#5-mcp-兼容) | [测试要求](#6-测试要求)

---

## 1. 文件清单

| 文件 | 角色 | 类型 |
|------|------|------|
| `registry.py` | `ToolRegistry` — 工具注册中心（类级单例） | 核心 |
| `weather.py` | `get_weather` — 天气查询工具示例 | 示例 |
| `database.py` | `query_database` — SQL 查询工具示例 | 示例 |
| `knowledge_graph.py` | **动态工具集** — 启动时从 Rust 服务 GET /tools 拉取工具列表，JSON Schema → Python 函数动态注册，通过 POST /tools/call 统一调用。当前 12 工具 | 核心 |

---

## 2. ToolRegistry 契约

### 2.1 公共方法

```python
class ToolRegistry:
    _tools: dict[str, BaseTool] = {}          # 类级存储

    @classmethod
    def register(cls, name=None) -> Callable:  # 装饰器注册
    @classmethod
    def register_tool(cls, name, tool) -> None:  # 实例注册
    @classmethod
    def get(cls, name) -> Optional[BaseTool]:  # 按名获取
    @classmethod
    def get_all(cls) -> list[BaseTool]:        # 获取全部
    @classmethod
    def list_names(cls) -> list[str]:          # 列出名称
    @classmethod
    def unregister(cls, name) -> None:         # 移除
    @classmethod
    def clear(cls) -> None:                    # 清空
    @classmethod
    def to_mcp_tools(cls) -> list[dict]:       # MCP 导出
```

### 2.2 注册方式

```python
# 方式 1: 装饰器注册 (推荐 — 函数自动包装为 @tool)
@ToolRegistry.register("weather_search")
def get_weather(city: str) -> str:
    """查询指定城市的实时天气。"""
    return f"{city}: 晴，25°C"

# 方式 2: 实例注册 (适用于已创建的 StructuredTool 等)
from langchain_core.tools import StructuredTool

my_tool = StructuredTool.from_function(func=..., name="my_tool", ...)
ToolRegistry.register_tool("my_tool", my_tool)
```

### 2.3 约束

| 规则 | 说明 |
|------|------|
| **MUST** 使用 `@ToolRegistry.register()` | 不使用 `@tool` 后手动 `register_tool` |
| **MUST** 提供 docstring | 工具的 description 来自函数的 docstring |
| **MUST NOT** 在 Tool 中调用 LLM | 工具是纯函数，不包含 AI 逻辑 |
| **MUST NOT** 工具间互相调用 | 每个工具独立，无依赖 |

---

## 3. 新增工具规范

### 3.1 步骤

1. 在 `tools/` 下创建新文件 `my_tool.py`
2. 定义一个纯函数，添加类型注解和 docstring
3. 使用 `@ToolRegistry.register("tool_name")` 装饰
4. **工具名称**使用 `snake_case`

### 3.2 完整示例

```python
from capabilities.tools.registry import ToolRegistry


@ToolRegistry.register("search_documents")
def search_documents(query: str, top_k: int = 5) -> str:
    """
    在知识库中搜索相关文档。

    Args:
        query: 搜索关键词。
        top_k: 返回结果数量，默认 5。

    Returns:
        JSON 格式的搜索结果列表。
    """
    # TODO: 实现搜索逻辑
    import json
    return json.dumps({"results": [], "count": 0})
```

### 3.3 包装外部 HTTP API

当外部系统通过 HTTP 暴露工具端点时，本地工具作为薄包装层，遵循 `_invoke() → ToolRegistry` 两层结构：

```python
# knowledge_graph.py 模式
import json
import requests
from capabilities.tools.registry import ToolRegistry
from common.config.settings import get_settings

def _invoke(tool_name: str, arguments: dict) -> str:
    """统一 HTTP 调用 + 错误处理。"""
    server = get_settings().kg_server_url
    try:
        resp = requests.post(f"{server}/tools/{tool_name}", json=arguments, timeout=30)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        return json.dumps({"error": str(e)})

@ToolRegistry.register("tool_name")
def tool_name(param: str) -> str:
    """工具描述 — 与外部定义一致。"""
    return _invoke("tool_name", locals())
```

| 规则 | 说明 |
|------|------|
| **MUST** 服务地址通过 Settings 统一管理 | `get_settings().kg_server_url`，可由环境变量 `KG_SERVER_URL` 覆盖 |
| **MUST** HTTP 异常转为 JSON 错误字符串 | 避免 Agent 收到非 JSON 响应而解析失败 |
| **MUST** 工具名与外部系统一致 | `@ToolRegistry.register("search_entities")` 名称 = 远端工具名 |
| **MUST NOT** 在工具内添加业务逻辑 | 本地工具仅做转发，不可添加规则判断或数据转换 |

---

## 4. Tool 实现约束

### 4.1 函数签名规范

```python
# ✅ 正确: 类型明确的参数，有 docstring
@ToolRegistry.register("my_tool")
def my_tool(param_a: str, param_b: int = 10) -> str:
    """简洁描述工具的功能。"""

# ❌ 错误: 无类型注解
@ToolRegistry.register("my_tool")
def my_tool(param_a, param_b):
    ...

# ❌ 错误: 无 docstring (LangChain 无法生成描述)
@ToolRegistry.register("my_tool")
def my_tool(param_a: str) -> str:
    return "..."
```

### 4.2 纯函数约束

```python
# ✅ 正确: 工具是纯函数，通过参数获取依赖
@ToolRegistry.register("db_query")
def db_query(sql: str, db_conn) -> str:  # db_conn 作为参数传入
    ...

# ❌ 错误: 工具内部直接操作全局连接
@ToolRegistry.register("db_query")
def db_query(sql: str) -> str:
    global db_pool                         # 不要这样做
    ...
```

### 4.3 返回值

- 工具返回值**推荐**为 `str` 类型（LangChain Agent 的标准约定）
- 若需返回结构化数据，使用 `json.dumps()` 序列化为字符串
- 避免返回复杂嵌套对象

---

## 5. MCP 兼容

### 5.1 to_mcp_tools() 输出格式

```python
tools = ToolRegistry.to_mcp_tools()
# 返回:
# [
#     {
#         "name": "weather_search",
#         "description": "查询指定城市的实时天气。",
#         "inputSchema": {"type": "object", "properties": {...}}
#     },
#     ...
# ]
```

### 5.2 约束

- 工具的函数签名自动转为 `inputSchema`（JSON Schema 格式）
- description 取自函数的 docstring 首行
- 不支持的参数类型会导致 `inputSchema` 为空 `{}`

---

## 6. 测试要求

| 测试对象 | 类型 | 重点 |
|----------|------|------|
| ToolRegistry | 单元 | register/get/get_all/unregister/clear 全部操作 |
| to_mcp_tools | 单元 | 输出格式符合 MCP 规范 |
| 每个具体工具 | 单元 | 正常参数 / 边界参数 / 异常参数的返回 |

```python
def test_tool_registry():
    ToolRegistry.clear()

    @ToolRegistry.register("test_tool")
    def test_func(x: str) -> str:
        """Test description."""
        return f"got: {x}"

    assert "test_tool" in ToolRegistry.list_names()
    tool = ToolRegistry.get("test_tool")
    assert tool is not None
    assert len(ToolRegistry.get_all()) == 1

    mcp = ToolRegistry.to_mcp_tools()
    assert mcp[0]["name"] == "test_tool"
    assert mcp[0]["description"] == "Test description."

    ToolRegistry.clear()
    assert len(ToolRegistry.get_all()) == 0
```
