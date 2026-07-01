# ORCHESTRATOR.md — LangGraph 编排层约束

> **定位**: 本层是系统的核心调度引擎。所有工作流的图结构定义、状态管理、条件路由和 checkpoint 持久化均在此层实现。

**目录**: [文件清单](#1-文件清单) | [公共接口](#2-公共接口) | [图构建规范](#3-图构建规范) | [状态模型约束](#4-状态模型约束) | [Checkpoint 策略](#5-checkpoint-策略) | [路由约束](#6-路由约束) | [执行引擎规范](#7-执行引擎规范) | [编码规范](#8-编码规范) | [测试要求](#9-测试要求)

---

## 1. 文件清单

| 文件 | 角色 | 抽象级别 |
|------|------|---------|
| `graphs/base.py` | `BaseWorkflowGraph` — 所有工作流的抽象基类，实现 `GraphExtension` 协议 | 抽象 |
| `state/schema.py` | `GraphState` — 继承 `GraphStateBase` 的兼容类型 | 抽象 |
| `state/manager.py` | `StateManager` — 状态 CRUD 封装 | 具体 |
| `router/conditional_router.py` | `ConditionalRouter` — 三种路由策略 | 工具类 |
| `engine/executor.py` | `GraphExecutor` — 工作流注册/执行调度 | 具体 (对外入口) |
| `engine/checkpoint.py` | PostgresSaver 工厂函数 | 工具 |

---

## 2. 公共接口

### 2.1 对外暴露符号

```python
# 唯一入口 — gateway 层只能通过此接口调用
from orchestrator.engine.executor import GraphExecutor

# 状态定义 — 编排层内部使用的兼容类型（继承 GraphStateBase）
from orchestrator.state.schema import GraphState

# 抽象基类 — 业务新增工作流时继承（已实现 GraphExtension 协议）
from orchestrator.graphs.base import BaseWorkflowGraph

# 协议 — 产品↔业务隔离的关键（一般不需直接导入，通过基类自动满足）
from common.contracts import GraphExtension
```

### 2.2 依赖关系

```
orchestrator/
  ├── 依赖 → common/contracts/graph_extension.py  (GraphExtension, 协议校验)
  ├── 依赖 → common/contracts/state_schema.py      (GraphStateBase)
  ├── 依赖 → business/__init__.py                  (REGISTRY 列表, 启动时读一次)
  ├── 依赖 → capabilities/agents/base.py           (BaseAgent, 图节点中调用)
  ├── 依赖 → capabilities/chains/                  (RAGChain 等, 图节点中调用)
  ├── 依赖 → capabilities/tools/registry.py         (ToolRegistry, 图节点中获取工具)
  ├── 依赖 → capabilities/models/interfaces.py      (ModelInterface)
  ├── 依赖 → common/config/settings.py              (get_settings)
  ├── 依赖 → common/models/schemas.py               (RunResponse 等)
  ├── 依赖 → common/exceptions/base.py              (WorkflowError)
  ├── 依赖 → common/utils/logger.py                 (get_logger)
  └── 依赖 → common/utils/metrics.py                (request_total, chain_duration)

orchestrator/ 禁止直接依赖:
  ❌ gateway/              (任何 gateway 模块)
  ❌ infrastructure/       (不应直接操作连接池)
  ❌ capabilities/tools/   (具体工具函数, 使用 ToolRegistry 接口)
  ❌ business/*/graph.py   (业务图内部实现, 通过 REGISTRY + 协议发现)
  ❌ business/*/nodes.py   (业务节点内部实现)
```

---

## 3. 图构建规范

### 3.1 BaseWorkflowGraph 契约

```python
from common.contracts import GraphExtension

class BaseWorkflowGraph(GraphExtension, ABC):
    """实现 GraphExtension 协议的工作流基类。"""

    graph_name: str              # 子类必须覆盖 (类属性)

    @abstractmethod
    def _build_graph(self) -> StateGraph:  # 子类必须实现
        ...

    # ── GraphExtension 协议实现 ──
    async def initialize(self) -> None:    # 编译图 + 创建 checkpointer
    async def run(self, input_data, config) -> dict:
    async def stream(self, input_data, config) -> AsyncIterator[dict]:
    async def get_state(self, thread_id) -> Optional[dict]:
    async def close(self) -> None:
```

**协议隔离说明**: 业务图继承 `BaseWorkflowGraph` 后自动满足 `GraphExtension` 协议，
`GraphExecutor` 只需校验 `issubclass(graph_cls, GraphExtension)`，无需知道具体图类名。

### 3.2 _build_graph() 约束

```python
# ✅ 正确: 使用业务域专用 State（继承自 GraphStateBase）
from common.contracts.state_schema import GraphStateBase

class MyDomainState(GraphStateBase, total=False):
    my_field: str

def _build_graph(self) -> StateGraph:
    workflow = StateGraph(MyDomainState)  # 域专用 State（包含 GraphStateBase 全部字段）
    workflow.add_node("node_a", self._node_a)
    workflow.add_edge(START, "node_a")
    workflow.add_conditional_edges("node_a", self._route)
    workflow.add_edge("node_b", END)
    return workflow

# ❌ 错误: 不继承 GraphStateBase 的 State
class MyState(TypedDict):
    my_field: str  # 缺少 messages, input, data, error 等基础字段

# ❌ 错误: 在 _build_graph 中执行异步操作
async def _build_graph(self) -> StateGraph:  # 必须是同步方法
```

### 3.3 新增工作流检查清单

- [ ] 在 `business/<domain>/` 下创建域目录
- [ ] 继承 `BaseWorkflowGraph`（自动满足 `GraphExtension` 协议）
- [ ] 设置 `graph_name` 类属性（全小写下划线命名，如 `my_workflow`）
- [ ] 实现 `_build_graph()` — 同步方法，返回未编译的 `StateGraph(MyDomainState)`
- [ ] `MyDomainState` 必须继承 `GraphStateBase`
- [ ] 每个节点方法返回 `dict` 类型（用于更新 state）
- [ ] 在 `business/__init__.py` 的 `REGISTRY` 中注册
- [ ] 节点方法内不直接创建 LLM 实例 — 通过依赖注入/初始化参数传入
- [ ] 所有节点方法为 `async def`

### 3.4 节点方法规范

```python
# ✅ 正确: 节点方法签名
async def _my_node(self, state: GraphState) -> dict:
    # 读取输入
    user_input = state["input"].get("query", "")
    # 处理
    result = await some_processing(user_input)
    # 返回更新 (仅返回变化的字段)
    return {"data": {**state["data"], "my_result": result}}

# ❌ 错误: 节点方法修改 state 内部字段的引用
async def _my_node(self, state: GraphState) -> dict:
    state["data"]["my_result"] = result  # 直接修改 state 引用
    return state                         # 返回原始引用
```

**关键规则**: 节点方法**必须**返回新 dict 而非修改 state 引用，确保 state 不可变性。

---

## 4. 状态模型约束

### 4.1 GraphState 字段语义

`GraphState` 继承自 `common.contracts.state_schema.GraphStateBase`，
直接复用契约层的字段定义，保证编排层与业务域的状态基础结构一致。

```python
from common.contracts.state_schema import GraphStateBase

class GraphState(GraphStateBase, total=False):
    """
    LangGraph 图状态 — 编排层内部使用的状态类型。
    各业务域应继承 GraphStateBase 定义自己的 State 并追加域专用字段。
    """
    pass
```

### 4.2 字段使用规则（字段定义来自 GraphStateBase）

| 字段 | 谁写入 | 谁读取 | 规则 |
|------|--------|--------|------|
| `input` | GraphExecutor (run/stream 入口) | 所有节点 | 只读！节点不得修改 |
| `data` | 所有节点 | 所有节点 | 通过返回 dict 更新，`{**state["data"], key: val}` |
| `messages` | Agent/Chain 节点 | Agent/Chain 节点 | 增量 append，不清空 |
| `next_node` | 条件路由函数 | 框架 | 不得在普通节点中设置 |
| `metadata` | GraphExecutor (初始化) | 所有节点 | 只读 |
| `error` | 异常处理节点 | 路由函数 | 非 None 时路由到错误处理分支 |

---

## 5. Checkpoint 策略

### 5.1 持久化规则

```python
# 自动 checkpoint: 每个 superstep 后 LangGraph 自动写入
# 无需手动调用 saver.put()

# 检查点存储位置
AsyncPostgresSaver
├── checkpoints        表: 每个 thread_id 的每个 checkpoint 状态快照
├── checkpoint_writes  表: 每个 checkpoint 的挂起写入
└── checkpoint_blobs   表: 大对象 blob 存储
```

### 5.2 使用约束

- **MUST**: 所有生产环境工作流**必须**使用 Postgres Checkpoint（不允许 MemorySaver）
- **MUST**: `AsyncPostgresSaver.setup()` 在应用启动时调用一次
- **MUST NOT**: 手动操作 `checkpoints` / `checkpoint_writes` / `checkpoint_blobs` 表
- **MUST**: 每个工作流使用唯一的 `thread_id`（默认 uuid4）
- **可复用**: 同一 `thread_id` 的多次 `run()` 调用在同一对话上下文中继续

### 5.3 断点续跑

```python
# 查询状态以支持断点续跑
state = await graph.get_state(thread_id)
if state:
    # 恢复到上次 checkpoint
    result = await graph.run(input_data, config={"thread_id": thread_id})
```

---

## 6. 路由约束

### 6.1 三种策略适用场景

| 策略 | 方法 | 适用场景 |
|------|------|---------|
| 规则路由 | `rule_based(state)` | 确定性分支（如意图分类、阈值判断） |
| LLM 路由 | `llm_based(state, available_nodes)` | 需要语义理解的不确定性分支 |
| 多条件路由 | `multi_criteria(state, criteria)` | 多个独立条件按优先级匹配 |

### 6.2 条件路由函数规范

```python
# ✅ 正确: 使用 Literal 标注返回值
from typing import Literal

def _route_after_classify(self, state: GraphState) -> Literal["answer", "escalate"]:
    intent = state["data"].get("intent")
    return "escalate" if intent in {"complaint", "refund"} else "answer"

# ✅ 正确: 在 add_conditional_edges 中显式列出所有路由目标
workflow.add_conditional_edges(
    "classify",
    self._route_after_classify,
    {"answer": "answer", "escalate": "escalate"},  # 显式映射
)

# ❌ 错误: 路由函数返回不在映射表中的值
def _route(self, state) -> str:
    return "unknown_node"  # 未在映射表中声明，会导致运行时错误
```

---

## 7. 执行引擎规范

### 7.1 GraphExecutor 职责

```python
class GraphExecutor:
    # 生命周期
    async def initialize(self) -> None:     # 注册并初始化所有工作流图
    async def close(self) -> None:          # 关闭所有图的 checkpointer 连接

    # 执行
    async def run(workflow_name, input_data, config) -> dict:
    async def stream(workflow_name, input_data, config) -> AsyncIterator[dict]:

    # 管理
    async def get_status(run_id) -> Optional[dict]:
    async def cancel(run_id) -> bool:

    # 注册（接受任何满足 GraphExtension 协议的对象）
    def register_graph(graph: GraphExtension) -> None:
```

### 7.2 工作流注册

```python
# 在 initialize() 中通过 REGISTRY 加载
# GraphExecutor 从 business.REGISTRY 读取图类列表，实例化并初始化
async def initialize(self) -> None:
    for graph_cls in self._load_registry():  # 读取 business.REGISTRY
        self._register(graph_cls(self.postgres_uri))
    for graph in self._graphs.values():
        await graph.initialize()
```

**新增工作流无需修改 executor** — 只需在 `business/__init__.py` 的 `REGISTRY` 中添加。
所有注册图类通过 `issubclass(graph_cls, GraphExtension)` 协议校验。

### 7.3 限制

- **MUST NOT**: 在 `run()` 中修改 `input_data` 参数（保持原始输入不变）
- **MUST**: `_running` 字典仅用于内存中的运行追踪，不替代 Postgres checkpoint
- **MUST**: `cancel()` 为 best-effort 语义，不保证即时中断

---

## 8. 编码规范

### 8.1 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 工作流图类 | `XxxGraph` | `CustomerServiceGraph` |
| 节点方法 | `_<verb>_<noun>` | `_classify_intent`, `_generate_answer` |
| 路由方法 | `_route_after_<stage>` | `_route_after_classify` |
| graph_name | `snake_case` | `customer_service`, `risk_control` |

### 8.2 节点方法必须异步

```python
# ✅ 正确
async def _process_data(self, state: GraphState) -> dict: ...

# ❌ 错误
def _process_data(self, state: GraphState) -> dict: ...
```

### 8.3 错误处理

```python
# 节点内异常应转为 WorkflowError 抛出
async def _risky_node(self, state: GraphState) -> dict:
    try:
        result = await self.model.generate(...)
    except Exception as e:
        raise WorkflowError(f"Node 'risky_node' failed: {e}") from e

# 或在 state 中设置 error 字段让路由处理
async def _risky_node(self, state: GraphState) -> dict:
    try:
        result = await self.model.generate(...)
        return {"data": {**state["data"], "result": result}}
    except Exception as e:
        return {"error": str(e)}
```

---

## 9. 测试要求

### 9.1 测试范围

| 测试对象 | 类型 | 重点 |
|----------|------|------|
| 每个具体图类 | 单元 | 图的节点和边结构正确 |
| 每个节点方法 | 单元 | 输入 → 输出变换正确（Mock 能力层） |
| 条件路由 | 单元 | 每个分支被正确触发 |
| GraphExecutor | 单元 | 工作流注册、执行调度 |
| 完整图 | 集成 | Mock Postgres，端到端执行 |

### 9.2 测试约束

```python
# 单元测试节点 — Mock 能力层依赖
async def test_classify_intent():
    graph = CustomerServiceGraph(postgres_uri="mock://")
    graph._app = AsyncMock()  # 不真正编译图
    result = await graph._classify_intent({"input": {"query": "我想退款"}, "data": {}})
    assert result["data"]["intent"] == "complaint"

# 集成测试完整图 — 使用 MemorySaver 代替 Postgres (CI 环境)
async def test_customer_service_workflow():
    graph = CustomerServiceGraph.__new__(CustomerServiceGraph)
    # 使用临时 memory saver
    ...
```
