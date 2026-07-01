# BUSINESS.md — 业务域层约束

> **定位**: 按业务域组织 LangGraph 工作流，每个域自包含图定义、状态 Schema、节点实现和专用提示词/工具。

**版本**: 1.1.0 | **更新**: 2026-06-30

---

## 1. 业务域列表

| 域 | 子包 | graph_name | 图类 | 流程 |
|----|------|-----------|------|------|
| 航路规划 | `business/route_planning/` | `route_planning` | `RoutePlanningGraph` | classify → fetch → generate → evaluate → log |
| 打击决策 | `business/strike_decision/` | `strike_decision` | `StrikeDecisionGraph` | collect → assess → decide → [strike/monitor/dismiss] |

---

## 2. 域目录约定

每个业务域子包必须包含以下文件：

```
business/<domain_name>/
    __init__.py       # 域说明 docstring
    graph.py          # 工作流图类 (继承 BaseWorkflowGraph)，必须设置 graph_name
    state.py          # 域专用 State TypedDict (total=False)
    nodes.py          # 图节点实现 (async 函数，接收 state 返回 dict)
    prompts/          # 域专用提示词模板 (.txt)，可选
    tools/            # 域专用工具定义，可选
```

### 2.1 graph.py 约定

- 必须定义一个继承 `BaseWorkflowGraph` 的类（从而满足 `GraphExtension` 协议）
- 必须设置 `graph_name` 类属性（唯一标识，供 API 通过 `workflow_name` 调用）
- 必须实现 `_build_graph() -> StateGraph` 方法
- 一个域可定义多个图类（每个都需在 `REGISTRY` 中显式注册）

### 2.2 state.py 约定

- **必须**继承 `common.contracts.state_schema.GraphStateBase`（自动获得框架基础字段）
- 追加域专用字段（如航路规划的 `route_type`、打击决策的 `decision`）
- 使用 `TypedDict(total=False)` 语义

```python
from common.contracts.state_schema import GraphStateBase

class MyDomainState(GraphStateBase, total=False):
    # GraphStateBase 已提供: messages, input, current_step, next_node, data, metadata, error
    # 此处只追加域专用字段
    my_field: str
    my_result: Optional[dict]
```

### 2.3 nodes.py 约定

- 每个节点是 `async def node_name(state: DomainState) -> dict` 形式的函数
- 返回的状态更新字典会合并到当前 state
- 节点函数应保持纯函数风格，依赖通过参数注入

---

## 3. 显式注册机制

`GraphExecutor._load_registry()` 从 `business/__init__.py` 的 `REGISTRY` 列表加载图类：

1. 读取 `business.REGISTRY` 列表
2. 校验每个条目是类且满足 `GraphExtension` 协议
3. 实例化并注册到执行器

**关键**:
- 不再使用 `pkgutil` 自动扫描 — 业务域必须显式注册
- 每个注册的类必须满足 `GraphExtension` 协议（继承 `BaseWorkflowGraph` 即可）
- `GraphExecutor` 不再直接依赖 business 包内部实现

**注册示例** (`business/__init__.py`):

```python
from business.route_planning.graph import RoutePlanningGraph
from business.strike_decision.graph import StrikeDecisionGraph
from business.new_domain.graph import NewDomainGraph  # 新增域在这里 import

REGISTRY = [
    RoutePlanningGraph,
    StrikeDecisionGraph,
    NewDomainGraph,  # 新增域在这里添加
]
```

GraphExecutor 启动时读取此列表，逐项校验 `issubclass(graph_cls, GraphExtension)`，通过后实例化并初始化。

---

## 4. 新增业务域步骤

1. 创建 `business/<new_domain>/` 目录
2. 写 `__init__.py`（域说明 docstring）
3. 写 `state.py`（定义域 State TypedDict，**必须**继承 `GraphStateBase`）
4. 写 `nodes.py`（实现图节点函数）
5. 写 `graph.py`（定义图类，设置 graph_name）
6. （可选）在 `prompts/` 和 `tools/` 下添加域专用资源
7. **在 `business/__init__.py` 的 `REGISTRY` 中添加导入和注册**

---

## 5. 编码规范

```python
# ✅ 正确: 从基类继承，使用域专用 State
from orchestrator.graphs.base import BaseWorkflowGraph
from business.my_domain.state import MyDomainState
from business.my_domain.nodes import step_one, step_two

class MyDomainGraph(BaseWorkflowGraph):
    graph_name = "my_domain"

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(MyDomainState)
        # ...
        return workflow

# ❌ 错误: 跨业务域 import
from business.other_domain.nodes import some_node  # 禁止

# ❌ 错误: 跳过基类直接创建 StateGraph
workflow = StateGraph(...)  # 必须继承 BaseWorkflowGraph

# ❌ 错误: 导入 gateway 或 infrastructure 内部实现
from gateway.routes import ...      # 禁止
from infrastructure.db.postgres import get_pool  # 禁止，通过接口

# ❌ 错误: 忘记注册
# 创建了新业务域但未在 business/__init__.py 的 REGISTRY 中添加
# GraphExecutor 将无法发现该域

# ❌ 错误: 不继承 GraphStateBase
class MyState(TypedDict, total=False):  # 缺少框架要求的基础字段
    my_field: str
```

---

## 6. Agent 规范

每个业务域可包含一个或多个 Agent（继承 `capabilities.agents.base.BaseAgent`）。

### 6.1 域 Agent 约定

- 文件名 `agent.py`，放在域目录下（如 `business/route_planning/agent.py`）
- 继承 `BaseAgent`，设置 `agent_name`
- 提示词优先从本地 `prompts/agent.txt` 加载，文件缺失时回退到 `PromptRegistry`
- 工具通过 `ToolRegistry.get(name)` 按名获取，不直接 import 工具模块

### 6.2 MasterAgent — 跨域总调度

`MasterAgent` 位于 `business/master_agent.py`，是业务层的统一入口：

```
用户输入
    │
    ▼
MasterAgent.run()
    ├── Step 1: 意图识别 (ReAct Agent + business/prompts/master.txt)
    │       └── 输出 JSON: {intent, reason, sub_queries}
    │
    ├── Step 2: 按意图分派子 Agent（惰性 import，在 initialize() 中加载）
    │   ├── overall         → RoutePlanningAgent + StrikeDecisionAgent
    │   ├── route_planning  → RoutePlanningAgent
    │   └── strike_decision → StrikeDecisionAgent
    │
    └── Step 3: 聚合返回
```

**意图分类**:

| 意图 | 触发条件 | 调用的子 Agent |
|------|---------|---------------|
| `overall` | "整体规划"、同时涉及航路+打击 | RoutePlanningAgent + StrikeDecisionAgent |
| `route_planning` | 仅涉及航路/路线/飞行规划 | RoutePlanningAgent |
| `strike_decision` | 仅涉及打击/威胁/风险评估 | StrikeDecisionAgent |

### 6.3 MasterAgent 使用示例

```python
from capabilities.models.factory import ModelFactory
from business.master_agent import MasterAgent

# 创建模型
model = ModelFactory.create("claude-sonnet-4-6")

# 创建并初始化 MasterAgent（自动加载子 Agent）
master = MasterAgent(model)
await master.initialize()

# 执行
result = await master.run("帮我做一次全面的航路规划和打击评估")
print(result["intent"])          # "overall"
print(result["route_planning"])  # 航路规划结果
print(result["strike_decision"]) # 打击决策结果
```

---

## 7. 与各层的关系

```
                          common/contracts/
                     (GraphExtension + GraphStateBase)
                     ↗          ↑           ↖
        (协议校验)  /           │            \ (继承实现)
                   /            │             \
          orchestrator/    (唯一交集)       business/
          executor.py                       __init__.py
                │                           │    │
                │  读取 REGISTRY ──────────►│    │
                │                           │    │
                │  graph.run() ──协议调用───►│    │
                │  graph.stream()            │    │
                │  graph.close()             │    │
                │                           │    │
                ▼                           ▼    ▼
         capabilities/              route_planning/
         infrastructure/            strike_decision/
         common/                    (内部不可见)
```

**隔离核心逻辑**:
1. `common/contracts/GraphExtension` — 产品定义"业务必须能做什么"（Protocol，纯契约）
2. `business/REGISTRY` — 业务声明"我提供了这些图"（List[type]，显式注册）
3. `BaseWorkflowGraph` — 产品提供默认实现（但产品不依赖业务选择用哪个实现）
4. 产品代码**不知道也不需要知道**每个业务域内部有几个节点、怎么路由
