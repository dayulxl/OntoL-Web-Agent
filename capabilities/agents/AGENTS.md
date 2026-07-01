# AGENTS.md — Agent 子模块约束

> **定位**: 本模块仅包含 `BaseAgent` — Agent 抽象基类。具体业务 Agent 已迁移至 `business/` 层。

**目录**: [文件清单](#1-文件清单) | [BaseAgent 契约](#2-baseagent-契约) | [新增 Agent 规范](#3-新增-agent-规范) | [Agent 生命周期](#4-agent-生命周期) | [编码规范](#5-编码规范) | [测试要求](#6-测试要求)

---

## 1. 文件清单

| 文件 | 角色 | 所在层 |
|------|------|--------|
| `base.py` | `BaseAgent` — Agent 抽象基类（ReAct 模式） | 能力层 (capabilities) |
| `chat_agent.py` | `ChatAgent` — 多步推理管道（7 工具 6 步） | 能力层 (capabilities) |

**已迁移至 business/ 的业务 Agent**:

| Agent | 原位置 | 新位置 |
|-------|--------|--------|
| `MasterAgent` | `capabilities/agents/master_agent.py` | `business/master_agent.py` |
| `RoutePlanningAgent` | `capabilities/agents/route_planning/` | `business/route_planning/agent.py` |
| `StrikeDecisionAgent` | `capabilities/agents/strike_decision/` | `business/strike_decision/agent.py` |

> **迁移原因**: 业务 Agent 包含域专用逻辑和工具编排，属于业务层而非可复用能力层。
> 原位置保留兼容存根，引导使用者迁移。

---

### 1.1 业务 Agent 架构（在 business/ 中）

```
business/
├── master_agent.py           # MasterAgent — 跨域总调度
│   (意图识别 → 分派 → 聚合)
├── route_planning/
│   ├── agent.py              # RoutePlanningAgent — 航路规划 Agent
│   ├── prompts/agent.txt     # 域专用 ReAct 提示词
│   └── tools/                # 域专用工具
└── strike_decision/
    ├── agent.py              # StrikeDecisionAgent — 打击决策 Agent
    ├── prompts/agent.txt     # 域专用 ReAct 提示词
    └── tools/                # 域专用工具
```

**约束**: 业务 Agent 之间不得相互 import；MasterAgent 通过惰性 import (`initialize()`) 加载子 Agent。

---

## 2. BaseAgent 契约

### 2.1 必须实现的抽象方法

```python
class BaseAgent(ABC):
    agent_name: str                           # 类属性, 子类覆盖

    @abstractmethod
    def _get_system_prompt(self) -> str:      # 返回系统提示词
        ...

    @abstractmethod
    def _get_tools(self) -> list[BaseTool]:   # 返回工具列表
        ...
```

### 2.2 提供的具体方法

```python
async def initialize(self) -> None:          # 构造 ReAct Agent
async def run(self, user_input, thread_id) -> dict:  # 同步执行
async def stream(self, user_input, thread_id):        # 流式执行
```

### 2.3 构造函数

```python
def __init__(self, model: ModelInterface):
    # model — 必须通过 ModelFactory 创建，不得硬编码
```

---

## 3. 新增 Agent 规范

### 3.1 步骤

1. 在 `business/<domain>/` 下创建 `agent.py`
2. 继承 `BaseAgent`（`from capabilities.agents.base import BaseAgent`）
3. 覆盖 `agent_name` 类属性（`snake_case`，如 `"my_domain"`）
4. 实现 `_get_system_prompt()` → 优先从域 `prompts/agent.txt` 加载，回退到 `PromptRegistry`
5. 实现 `_get_tools()` → 通过 `ToolRegistry.get(...)` 获取工具
6. **禁止**在 Agent 中直接 import 具体工具模块
7. **禁止**跨域 import 其他业务 Agent

### 3.2 完整示例

```python
# business/my_domain/agent.py
import os
from langchain_core.tools import BaseTool
from capabilities.agents.base import BaseAgent
from capabilities.prompts.registry import PromptRegistry
from capabilities.tools.registry import ToolRegistry

_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))

class MyDomainAgent(BaseAgent):
    agent_name = "my_domain"

    def _get_system_prompt(self) -> str:
        prompt_file = os.path.join(_AGENT_DIR, "prompts", "agent.txt")
        if os.path.isfile(prompt_file):
            with open(prompt_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        return PromptRegistry.get_agent("my_domain")

    def _get_tools(self) -> list[BaseTool]:
        tools = []
        for tool_name in ("tool_a", "tool_b"):
            tool = ToolRegistry.get(tool_name)
            if tool:
                tools.append(tool)
        return tools
```

### 3.3 Tool 注入约束

```python
# ✅ 正确: 通过 ToolRegistry 获取
def _get_tools(self) -> list[BaseTool]:
    return [t for t in ToolRegistry.get_all()
            if t.name in self._required_tool_names]

# ❌ 错误: 直接 import 具体工具
from capabilities.tools.weather import get_weather
def _get_tools(self) -> list[BaseTool]:
    return [get_weather]  # 绕过 ToolRegistry，破坏了工具管理的统一性
```

---

## 4. Agent 生命周期

```
BaseAgent.__init__(model)
        │
        ▼
  (惰性初始化)
        │
    run() / stream() 首次调用
        │
        ▼
  initialize()
    ├── model.get_llm()          → BaseChatModel
    ├── self._get_tools()        → list[BaseTool]
    ├── self._get_system_prompt() → str
    └── create_react_agent(llm, tools, prompt) → _agent
        │
        ▼
  _agent.ainvoke() / _agent.astream_events()
        │
        ▼
  返回结果 dict / AsyncIterator
```

**约束**:
- **MUST**: 惰性初始化 — 不在 `__init__` 中创建 LLM 或 Agent，在首次 `run()`/`stream()` 时创建
- **MUST**: 使用 `create_react_agent` (LangGraph prebuilt)，不得手写 ReAct 循环

---

## 5. 编码规范

### 5.1 系统提示词规范

```python
# ✅ 正确: 结构化、角色明确的提示词
def _get_system_prompt(self) -> str:
    return """你是一个 <角色>。你的职责是：
1. <职责1>
2. <职责2>
当信息不足时，<行为指引>。"""

# ❌ 错误: 过长的单行字符串、缺少行为指引
def _get_system_prompt(self) -> str:
    return "You are a helpful assistant."
```

### 5.2 流式输出规范

```python
# Agent 的 stream 方法使用 astream_events (v2)
async def stream(self, user_input, thread_id=None):
    config = {"configurable": {"thread_id": thread_id or "default"}}
    async for event in self._agent.astream_events(
        {"messages": [("user", user_input)]},
        config,
        version="v2",  # 必须使用 v2
    ):
        yield event
```

### 5.3 多轮对话

- 通过 `thread_id` 参数实现多轮对话
- 相同 `thread_id` = 同一对话上下文
- 不同 `thread_id` = 隔离的对话

---

## 6. 测试要求

| 测试对象 | 类型 | 重点 |
|----------|------|------|
| `_get_system_prompt()` | 单元 | 返回非空字符串 |
| `_get_tools()` | 单元 | 返回正确的工具列表（Mock ToolRegistry） |
| `run()` | 单元 | 使用 Mock LLM，验证 Agent 执行流程 |
| `stream()` | 单元 | 验证流式事件格式 |

```python
# 测试示例
async def test_agent_run(mock_model):
    agent = MyAgent(model=mock_model)
    result = await agent.run("hello")
    assert "output" in result
    assert result["agent"] == "my_agent"
```
