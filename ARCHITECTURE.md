# ARCHITECTURE.md — 架构约束

> **定位**: 本文档定义全局性架构规则与跨层约束。各层的实现细节、编码规范、接口契约见各自模块文档。

**版本**: 2.3.1 | **更新**: 2026-06-30

---

## 1. 架构总览与硬性约束

### 1.1 五层模型

```
                    common/contracts/
               (GraphExtension + GraphStateBase)
                  ↗                    ↖
       (协议校验) │                      │ (继承实现)
                 │                      │
gateway/ ──► orchestrator/          business/
                │    │                  │
                │    └──► REGISTRY ────►│  (显式注册)
                │                       │
                ▼                       ▼
         capabilities/ ◄───────────────┘
                │
                ▼
        infrastructure/
```

**隔离核心**: `common/contracts/` 是产品↔业务的唯一交集。产品通过 `GraphExtension` 协议定义对业务的期待，业务通过继承实现该协议，产品无需知道业务内部实现。

### 1.2 项目目录结构

```
project-root/
├── gateway/                          # API 网关层
│   ├── __init__.py
│   ├── app.py                        # FastAPI 应用入口
│   ├── routes/                       # 路由定义
│   │   ├── __init__.py
│   │   ├── langgraph_routes.py       # API 路由 (/run, /stream, /status...)
│   │   ├── page_routes.py            # 页面路由 (Jinja2 模板)
│   │   └── ontology_routes.py        # 本体建模 API 路由
│   ├── middleware/                   # 中间件
│   │   ├── __init__.py
│   │   ├── auth.py                   # 鉴权 (JWT / API-Key)
│   │   ├── logging.py                # 请求日志
│   │   └── rate_limiter.py           # 限流 (Redis 滑动窗口)
│   ├── templates/                    # Jinja2 模板文件
│   │   ├── base.html                 # 基础布局
│   │   ├── pages/                    # 业务页面
│   │   └── components/               # 可复用组件
│   └── static/                       # 静态资源 (CSS / JS / 图片)
│
├── orchestrator/                     # LangGraph 编排层 (核心调度引擎)
│   ├── __init__.py
│   ├── graphs/                       # 图构建框架
│   │   ├── __init__.py
│   │   └── base.py                   # BaseWorkflowGraph 抽象基类 (实现 GraphExtension 协议)
│   ├── state/                        # 状态管理
│   │   ├── __init__.py
│   │   ├── schema.py                 # GraphState TypedDict
│   │   └── manager.py                # StateManager (Postgres checkpoint)
│   ├── router/                       # 动态路由
│   │   ├── __init__.py
│   │   └── conditional_router.py     # ConditionalRouter (3 种策略)
│   └── engine/                       # 执行引擎
│       ├── __init__.py
│       ├── executor.py               # GraphExecutor (工作流注册·调度)
│       └── checkpoint.py             # PostgresSaver 工厂
│
├── capabilities/                     # LangChain 能力层 (可复用 AI 单元)
│   ├── __init__.py
│   ├── agents/                       # Agent 抽象基类
│   │   ├── __init__.py
│   │   └── base.py                   # BaseAgent 抽象类 (ReAct)
│   │   (具体 Agent 已迁移至 business/ 层)
│   ├── chains/                       # LCEL Chain 定义
│   │   ├── __init__.py
│   │   ├── rag_chain.py              # RAGChain (检索增强生成)
│   │   └── summary_chain.py          # SummaryChain (stuff/map_reduce/refine)
│   ├── tools/                        # 工具注册中心
│   │   ├── __init__.py
│   │   ├── registry.py               # ToolRegistry (类级单例, MCP 兼容)
│   │   ├── weather.py                # 天气查询工具
│   │   ├── database.py               # SQL 查询工具
│   │   └── knowledge_graph.py        # 知识图谱 HTTP API 工具
│   ├── prompts/                      # 提示词管理
│   │   ├── __init__.py
│   │   ├── registry.py               # PromptRegistry (文件加载, 热更新)
│   │   ├── agents/                   # Agent 提示词 (.txt)
│   │   └── chains/                   # Chain 模板 (.txt)
│   ├── memory/                       # 记忆管理
│   │   ├── __init__.py
│   │   ├── short_term.py             # ShortTermMemory (Redis, 会话级)
│   │   ├── long_term.py              # LongTermMemory (向量库, 跨会话)
│   │   └── graph_memory.py           # GraphMemory (Neo4j, 知识图谱)
│   └── models/                       # 模型抽象层 (7 种类型 × 3 提供商 = 33 个模型)
│       ├── __init__.py
│       ├── interfaces.py             # ModelInterface 抽象
│       ├── factory.py                # ModelFactory (按类型+名称路由)
│       └── models.yaml               # 模型配置 (LLM/Embedding/Reranker/TTS/STT/Vision/Image)
│
├── business/                           # 业务域层 (按业务域组织的工作流 + Agent)
│   ├── __init__.py                     # 业务层入口 + REGISTRY 列表
│   ├── master_agent.py                 # MasterAgent — 跨域总调度 (意图识别 → 分派 → 聚合)
│   ├── prompts/                        # 跨域共享提示词 (master.txt)
│   ├── ontology/                       # 本体语义域 (PostgreSQL 本体模型管理)
│   │   ├── __init__.py
│   │   └── models.py                   # OntolModel / OntolModelAttr Pydantic 数据模型
│   ├── route_planning/                 # 航路规划域
│   │   ├── graph.py                    # RoutePlanningGraph
│   │   ├── state.py                    # RoutePlanningState
│   │   ├── nodes.py                    # 域节点实现
│   │   ├── agent.py                    # RoutePlanningAgent (ReAct)
│   │   ├── prompts/                    # 域专用提示词 (agent.txt)
│   │   └── tools/                      # 域专用工具
│   └── strike_decision/                # 打击决策域
│       ├── graph.py                    # StrikeDecisionGraph
│       ├── state.py                    # StrikeDecisionState
│       ├── nodes.py                    # 域节点实现
│       ├── agent.py                    # StrikeDecisionAgent (ReAct)
│       ├── prompts/                    # 域专用提示词 (agent.txt)
│       └── tools/                      # 域专用工具
│
├── infrastructure/                   # 基础设施层
│   ├── __init__.py
│   ├── db/                           # 数据库
│   │   ├── __init__.py
│   │   ├── base_repo.py               # BaseRepository 通用异步 CRUD 基类
│   │   ├── postgres.py                # asyncpg 连接池 + 健康检查 + 迁移执行器
│   │   ├── ontology_repo.py           # OntologyRepo — 本体模型数据访问层
│   │   ├── neo4j.py                   # Neo4j 驱动 + 连接池 + 健康检查
│   │   └── migrations/                # SQL 迁移文件 (启动时自动执行)
│   ├── cache/                        # 缓存
│   │   ├── __init__.py
│   │   └── redis.py                  # Redis 客户端 (缓存 + PubSub)
│   ├── config/                       # 动态配置
│   │   ├── __init__.py
│   │   └── dynamic.py                # DynamicConfig (Redis 热更新)
│   ├── queue/                        # 消息队列
│   │   ├── __init__.py
│   │   └── task_queue.py             # Celery 任务队列封装
│   └── storage/                      # 对象存储
│       ├── __init__.py
│       └── object_store.py           # S3 兼容 (MinIO / AWS / OSS)
│
├── common/                           # 共享层
│   ├── __init__.py
│   ├── contracts/                     # 产品↔业务隔离契约
│   │   ├── __init__.py
│   │   ├── graph_extension.py         # GraphExtension Protocol
│   │   └── state_schema.py            # GraphStateBase TypedDict
│   ├── config/                       # 配置管理
│   │   ├── __init__.py
│   │   └── settings.py               # Pydantic Settings (环境变量)
│   ├── models/                       # 共享数据模型
│   │   ├── __init__.py
│   │   └── schemas.py                # RunRequest, RunResponse, StreamEvent 等
│   ├── exceptions/                   # 统一异常定义
│   │   ├── __init__.py
│   │   ├── base.py                   # 异常层次 (1 基类 + 9 子类)
│   │   └── handlers.py               # FastAPI 全局异常处理器
│   └── utils/                        # 工具函数
│       ├── __init__.py
│       ├── logger.py                 # structlog 结构化日志
│       ├── metrics.py                # Prometheus 指标定义
│       └── tracer.py                 # OpenTelemetry + LangSmith 追踪
│
├── tests/                            # 测试
│   ├── __init__.py
│   └── conftest.py                   # 全局 fixtures
│
├── scripts/                          # 运维脚本
│   ├── build.sh                      # Docker 镜像构建
│   └── migrate.sh                    # 数据库迁移 (Alembic)
│
├── deployments/                      # 部署配置
│   ├── k8s/                          # Kubernetes (集群拆分)
│   │   ├── deployment-gateway.yaml   # Gateway Deployment (接收请求)
│   │   ├── deployment-worker.yaml    # Worker Deployment (执行任务)
│   │   ├── deployment-scheduler.yaml # Scheduler Deployment (可选, 定时任务)
│   │   ├── service-gateway.yaml      # Service (暴露 Gateway)
│   │   ├── ingress.yaml              # Ingress (nginx + TLS)
│   │   ├── hpa-gateway.yaml          # HPA: Gateway (CPU 70%)
│   │   ├── hpa-worker.yaml           # HPA/KEDA: Worker (Queue Depth)
│   │   ├── statefulset-postgres.yaml # StatefulSet: Postgres 集群
│   │   └── statefulset-redis.yaml    # StatefulSet: Redis 集群
│   └── docker/                       # Docker
│       └── Dockerfile                # 单镜像多角色 (Gateway/Worker/Scheduler 共用)
│
├── pyproject.toml                    # Poetry 依赖管理
├── .env.example                      # 环境变量模板
├── README.md                         # 项目快速入门
├── ARCHITECTURE.md                   # 本文档 (全局架构约束)
│
├── gateway/GATEWAY.md                # 网关层约束文档
├── orchestrator/ORCHESTRATOR.md      # 编排层约束文档
├── business/BUSINESS.md              # 业务域层约束文档
├── capabilities/CAPABILITIES.md      # 能力层总览文档
├── capabilities/agents/AGENTS.md     # Agent 约束文档
├── capabilities/chains/CHAINS.md     # Chain 约束文档
├── capabilities/tools/TOOLS.md       # Tool 约束文档
├── capabilities/prompts/PROMPTS.md   # Prompt 约束文档
├── capabilities/memory/MEMORY.md     # Memory 约束文档
├── capabilities/models/MODELS.md     # Model 约束文档
├── infrastructure/INFRASTRUCTURE.md  # 基础设施约束文档
├── common/COMMON.md                  # 共享层约束文档
├── tests/TESTS.md                    # 测试规范文档
└── deployments/DEPLOYMENTS.md        # 部署规范文档
```

### 1.3 硬性约束 (MUST / MUST NOT)

| 规则 | 说明 |
|------|------|
| **MUST** 向下依赖 | 上层可依赖下层，绝对禁止反向 import |
| **MUST NOT** 跨层跳过 | `gateway/` 不得直接 import `capabilities/`；必须经过 `orchestrator/` |
| **MUST NOT** 同层耦合 | 同层模块间（如 `agents/` 与 `chains/`）不得直接 import，通过 `common/` 或抽象接口通信 |
| **MUST** 接口隔离 | 层间通过抽象类或 TypedDict 通信，不得依赖具体实现 |
| **MUST** 无状态 | 任何 worker 进程不得在内存中持有业务状态（缓存、会话等），状态全部外置到 Postgres / Redis |
| **MUST NOT** 硬编码密钥 | API Key、Token、密码等一律通过环境变量注入，由 `common/config/settings.py` 统一读取 |
| **MUST** 异常统一 | 所有业务异常继承 `common.exceptions.base.AppException`，不得抛裸 `Exception` |
| **MUST** UTF-8 无 BOM | 所有文本文件（.py / .yaml / .md / .html / .css / .js / .txt / .toml / .sh）必须 UTF-8 编码，不含 BOM 头 |
| **MUST** 新业务入 business/ | 新增业务工作流必须放在 `business/<domain>/` 下，按 `graph.py` + `state.py` + `nodes.py` 约定组织；禁止直接放 `orchestrator/graphs/` |
| **MUST NOT** 依赖 Docker | 开发与运行环境尽量直接使用本地服务，不强制依赖 Docker 容器；中间件（Postgres/Redis/Neo4j）优先本地安装或远程连接 |

### 1.4 层级职责边界

| 层 | 目录 | 允许做的事 | 不允许做的事 |
|----|------|-----------|-------------|
| 网关 | `gateway/` | HTTP 路由、中间件（鉴权/限流/日志）、请求校验、SSE 流封装、Jinja2 模板渲染、静态文件服务 | 持有 LLM 实例、直接操作数据库、包含业务逻辑 |
| 编排 | `orchestrator/` | 图定义/编译/执行、状态管理、条件路由、checkpoint 持久化 | 直接构造 Prompt、定义 Tool 实现、管理连接池 |
| 业务 | `business/` | 定义域专用图/状态/节点、编排域业务流程；继承 `orchestrator` 抽象基类和 `capabilities` 接口 | 跨域直接 import、导入 `gateway/`、依赖 `infrastructure/` 内部实现 |
| 能力 | `capabilities/` | Agent 定义、LCEL Chain 构建、Tool 实现、记忆存取、模型适配 | 处理 HTTP 请求、管理图状态、管理数据库连接 |
| 基础设施 | `infrastructure/` | 连接池封装、客户端实例化、健康检查 | 包含 AI 逻辑、理解 LangChain/LangGraph 概念 |
| 共享 | `common/` | 配置读取、Pydantic Schema、异常类、工具函数（日志/指标/追踪） | 依赖任何上层或同层模块 |

---

## 2. 层间契约 (Interface Contracts)

### 2.0 Business → Orchestrator + Capabilities（契约隔离）

**产品 ↔ 业务隔离边界**: `common/contracts/GraphExtension` 协议 + `business/REGISTRY`

```python
# ── 产品侧 (orchestrator) ──
# executor 通过协议校验业务图，不直接 import 业务内部模块
from common.contracts import GraphExtension

class GraphExecutor:
    async def initialize(self) -> None:
        from business import REGISTRY
        for graph_cls in REGISTRY:
            assert issubclass(graph_cls, GraphExtension)  # 协议校验
            self._register(graph_cls(postgres_uri))

# ── 业务侧 (business) ──
# 业务图继承 BaseWorkflowGraph（实现了 GraphExtension 协议）
from orchestrator.graphs.base import BaseWorkflowGraph
from common.contracts.state_schema import GraphStateBase
from capabilities.tools.registry import ToolRegistry

class MyDomainGraph(BaseWorkflowGraph):
    graph_name = "my_domain"

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(MyDomainState)
        # ... 添加节点和边
        return workflow

# 在 business/__init__.py 显式注册：
# from business.my_domain.graph import MyDomainGraph
# REGISTRY = [..., MyDomainGraph]
```

- **允许 import (业务侧)**: `orchestrator.graphs.base.BaseWorkflowGraph`、`common.contracts.*`、`capabilities.*` 的注册中心/接口
- **禁止 import (业务侧)**: `gateway/` 任何内容、其他业务域的内部模块、`infrastructure/` 内部实现
- **允许 import (产品侧)**: `business.REGISTRY` 列表、`common.contracts.GraphExtension`
- **禁止 import (产品侧)**: `business/*/graph.py`、`business/*/nodes.py` 等业务内部模块
- **显式注册**: 业务域在 `business/__init__.py` 的 `REGISTRY` 中声明，替代 `pkgutil` 自动扫描

### 2.1 Gateway → Orchestrator

```python
# 唯一入口：gateway 只能通过 GraphExecutor 调用编排层
from orchestrator.engine.executor import GraphExecutor

executor = GraphExecutor(postgres_uri=...)
await executor.initialize()
result = await executor.run(workflow_name, input_data, config)
```

- **允许 import**: `orchestrator.engine.executor.GraphExecutor`
- **禁止 import**: `orchestrator.graphs.*`, `orchestrator.state.*`, `orchestrator.router.*`
- **错误处理**: `orchestrator` 层的异常必须转换为 `common.exceptions` 中的类型再抛出

### 2.2 Orchestrator → Capabilities

```python
# 编排层使用能力层通过抽象接口
from capabilities.agents.base import BaseAgent
from capabilities.tools.registry import ToolRegistry
from capabilities.models.interfaces import ModelInterface
```

- **允许 import**: 抽象基类 (BaseAgent)、注册中心类 (ToolRegistry)、接口 (ModelInterface)
- **禁止 import**: 具体 Agent 实现 (ResearchAgent)、具体 Chain 类、具体 Tool 函数
- 图节点内可通过 `BaseAgent.run()` 调用 Agent，通过 `ToolRegistry.get_all()` 获取工具

### 2.3 Capabilities → Infrastructure

```python
# 能力层使用基础设施通过封装好的客户端
from infrastructure.cache.redis import cache_get, cache_set
from infrastructure.db.postgres import get_pool
```

- **允许 import**: 公开的客户端函数（cache_get, get_pool 等）
- **禁止 import**: 内部实现细节（连接池的私有变量、原始驱动对象）

### 2.4 所有层 → Common

```python
# 所有层都可以依赖 common/
from common.config.settings import get_settings
from common.models.schemas import RunRequest, RunResponse
from common.exceptions.base import AppException, ValidationError
from common.utils.logger import get_logger
from common.utils.metrics import request_total, chain_duration
```

---

## 3. 数据流约束

### 3.1 请求数据流

```
Client → Ingress → Gateway → Orchestrator → Capabilities → Infrastructure
                         │            │              │              │
                    鉴权/限流    图调度/状态     AI 执行       DB/缓存/MQ
                         │            │              │              │
                         └────────────┴──────────────┴──────────────┘
                                          │
                                     common/ (全链路可见)
```

### 3.2 状态流约束

| 状态类型 | 存储位置 | 读写方式 |
|----------|---------|---------|
| 图执行状态 | Postgres (checkpoint) | `AsyncPostgresSaver` 自动管理，禁止手动写入 |
| 会话消息 | Redis (TTL 30min) | `ShortTermMemory` → `infrastructure/cache/redis.py` |
| 用户长期记忆 | 向量数据库 | `LongTermMemory` → 向量存储适配器 |
| 本体模型/字段 | Postgres (ontol_model / ontol_model_attr) | `OntologyRepo` → `BaseRepository` CRUD |
| 请求上下文 | ContextVar (单请求) | `gateway/middleware/auth.py` 注入，全局读取 |
| 动态配置 | Redis (热更新) | `common/config/dynamic.py` |

### 3.3 跨 Pod 通信

```
Pod A ──(同组消费)──► Redis PubSub ──► Pod B
Pod A ──(同组消费)──► Redis PubSub ──► Pod C
```

- 唯一允许的 Pod 间通信方式：Redis PubSub
- 禁止基于内存的事件总线、本地消息队列

---

## 4. 错误处理约束

### 4.1 异常层次

```
AppException (必继承)
├── ValidationError         → HTTP 400
├── AuthenticationError     → HTTP 401
├── AuthorizationError      → HTTP 403
├── NotFoundError           → HTTP 404
├── RateLimitError          → HTTP 429
├── WorkflowError           → HTTP 500
├── ModelError              → HTTP 502
├── InfrastructureError     → HTTP 503
└── ConfigurationError      → HTTP 500
```

### 4.2 各层异常使用规则

| 层 | 抛出 | 捕获 |
|----|------|------|
| gateway | 不抛业务异常（转换 HTTPException） | 捕获所有 AppException → HTTPException |
| orchestrator | WorkflowError | 捕获 capabilities 层的异常 → WorkflowError |
| capabilities | ModelError | 捕获 infrastructure 层异常 → ModelError |
| infrastructure | InfrastructureError | 不捕获上层异常 |
| common | 定义异常类（不抛出也不捕获） | — |

> 详细规范见 [common/COMMON.md](common/COMMON.md)

---

## 5. 配置约束

### 5.1 配置来源优先级

```
Redis 动态配置  >  环境变量  >  .env 文件  >  Settings 默认值
```

### 5.2 环境变量命名

- 所有配置项使用 `UPPER_SNAKE_CASE`
- 数据库 URI: `POSTGRES_URI`, `REDIS_URI`
- API Key: `<PROVIDER>_API_KEY` (如 `ANTHROPIC_API_KEY`)
- 不得在代码中硬编码任何连接字符串或凭据

### 5.3 配置读取入口

- **静态配置**: 唯一入口 `common/config/settings.py::get_settings()`
- **动态配置**: 唯一入口 `infrastructure/config/dynamic.py::DynamicConfig`

> 详细规范见 [common/COMMON.md](common/COMMON.md)

---

## 6. 模块文档索引

每个模块目录包含自己的约束文档，定义该模块的实现细节和编码规范：

| 模块 | 文档 | 内容 |
|------|------|------|
| gateway | [gateway/GATEWAY.md](gateway/GATEWAY.md) | HTTP API 规范、中间件约束、路由设计 |
| orchestrator | [orchestrator/ORCHESTRATOR.md](orchestrator/ORCHESTRATOR.md) | 图构建规范、状态模型、checkpoint 策略 |
| business | [business/BUSINESS.md](business/BUSINESS.md) | 业务域层总览、域拆分规范、显式注册机制 |
| business/ontology | [business/ontology/](#) | 本体语义 Pydantic 模型 (ontol_model / ontol_model_attr) |
| common/contracts | [common/contracts/](#) | GraphExtension 协议、GraphStateBase、产品↔业务隔离边界 |
| capabilities | [capabilities/CAPABILITIES.md](capabilities/CAPABILITIES.md) | 能力层总览、跨子模块约束 |
| capabilities/agents | [capabilities/agents/AGENTS.md](capabilities/agents/AGENTS.md) | Agent 实现约束、ReAct 规范 |
| capabilities/chains | [capabilities/chains/CHAINS.md](capabilities/chains/CHAINS.md) | LCEL Chain 构建规范 |
| capabilities/tools | [capabilities/tools/TOOLS.md](capabilities/tools/TOOLS.md) | 工具注册/实现规范、MCP 兼容 |
| capabilities/prompts | [capabilities/prompts/PROMPTS.md](capabilities/prompts/PROMPTS.md) | 提示词管理、模板加载、版本化 |
| capabilities/memory | [capabilities/memory/MEMORY.md](capabilities/memory/MEMORY.md) | 短期/长期记忆管理规范 |
| capabilities/models | [capabilities/models/MODELS.md](capabilities/models/MODELS.md) | 模型抽象 & 工厂规范 |
| infrastructure | [infrastructure/INFRASTRUCTURE.md](infrastructure/INFRASTRUCTURE.md) | 连接池/客户端封装规范 |
| common | [common/COMMON.md](common/COMMON.md) | 配置/异常/日志/指标/追踪规范 |
| tests | [tests/TESTS.md](tests/TESTS.md) | 测试策略与规范 |
| deployments | [deployments/DEPLOYMENTS.md](deployments/DEPLOYMENTS.md) | K8s/Docker 部署规范 |

---

## 7. 技术栈约束

| 类别 | 必选技术 | 版本 | 禁止替代 |
|------|---------|------|---------|
| Web 框架 | FastAPI | 0.115+ | ❌ Flask, Django |
| 模板引擎 | Jinja2 | 3.0+ | ❌ Mako, Cheetah |
| 静态文件 | aiofiles | 24.0+ | ❌ 同步文件 IO |
| AI 编排 | LangGraph | 0.3+ | ❌ 手写状态机 |
| AI 能力 | LangChain + LCEL | 0.3+ | ❌ 裸 HTTP 调用 LLM |
| 配置管理 | Pydantic Settings | 2.0+ | ❌ 自定义 config parser |
| 配置格式 | YAML (PyYAML) | 6.0+ | ❌ JSON 手动解析 |
| 数据库 | asyncpg (Postgres) | 0.30+ | ❌ SQLAlchemy sync engine |
| 缓存 | redis-py (async) | 5.0+ | ❌ memcached, 本地 dict |
| 日志 | structlog | 24.0+ | ❌ print(), logging 裸用 |
| 指标 | prometheus-client | 0.21+ | ❌ 自定义指标协议 |
| 追踪 | OpenTelemetry | 1.28+ | ❌ 自定义 trace |

---

## 8. 反模式清单 (Anti-Patterns)

以下做法在项目中**严格禁止**：

| 反模式 | 错误示例 | 正确做法 |
|--------|---------|---------|
| 跨层 import | `gateway/` 直接导入 `capabilities/` 的具体类 | 通过 `orchestrator/` 中转 |
| 产品扫描业务 | `pkgutil.iter_modules(business.__path__)` 自动扫描 | 通过 `business.REGISTRY` 显式注册 + `GraphExtension` 协议校验 |
| 产品 import 业务内部 | `from business.route_planning.nodes import classify_intent` | 通过协议方法 `graph.run()` 调用，内部节点对产品不可见 |
| 进程内状态 | 在模块级定义 `dict` 存储会话数据 | 使用 Redis / Postgres |
| 硬编码密钥 | `api_key = "sk-xxx"` | `get_settings().anthropic_api_key` |
| 裸 Exception | `raise Exception("出错了")` | `raise WorkflowError("出错了")` |
| 直接操作驱动 | 在能力层操作 `asyncpg.Pool` | 通过 `BaseRepository` 或 `OntologyRepo` |
| 裸 SQL 拼接 | `f"SELECT * FROM {table}"` | 使用 `BaseRepository` 的参数化方法 |
| 循环依赖 | A import B, B import A | 抽取公共接口到 `common/` |
| logging 裸用 | `logging.info("...")` | `get_logger(__name__).info(...)` |
| 本地消息队列 | `asyncio.Queue`, `multiprocessing.Queue` | `infrastructure/queue/task_queue.py` (Celery) |
| 本地文件缓存 | `with open()`, `pathlib` 读写共享文件 | `infrastructure/storage/object_store.py` (S3/MinIO) |
| 内存缓存业务数据 | `@lru_cache` 缓存会话/Token 数据 | Redis `cache_get`/`cache_set` |
| Worker 无 thread_id | `executor.run(workflow, input)` 无 config | `executor.run(workflow, input, config={"thread_id": ...})` |

---

## 9. 集群拆分设计

### 9.1 核心原则

**代码目录结构完全不变**。集群拆分仅通过部署配置实现，不同容器选装不同的 Python 模块子集。

### 9.2 容器加载矩阵

**单镜像，多角色** — 所有 Deployment 使用完全相同的 Docker 镜像，仅通过 `command`/`args` 和环境变量区分角色。

| 代码模块 | Gateway 容器 | Worker 容器 | Scheduler 容器 |
|---------|-------------|------------|---------------|
| `gateway/` | ✅ 运行中 | ✅ 存在但不加载 | ✅ 存在但不加载 |
| `orchestrator/` | ✅ 存在但不加载 | ✅ 运行中 | ❌ 不需要 |
| `business/` | ✅ 存在但不加载 | ✅ 运行中 | ❌ 不需要 |
| `capabilities/` | ✅ 存在但不加载 | ✅ 运行中 | ❌ 不需要 |
| `infrastructure/cache/` | ✅ 使用 | ✅ 使用 | ❌ 不需要 |
| `infrastructure/db/` | ✅ (ontology 路由 + lifespan 迁移) | ✅ 使用 | ❌ 不需要 |
| `infrastructure/queue/` | ✅ 使用 (投递) | ✅ 使用 (消费) | ✅ 使用 (beat) |
| `infrastructure/storage/` | ✅ 使用 (读) | ✅ 使用 (读写) | ❌ 不需要 |
| `common/` | ✅ 使用 | ✅ 使用 | ✅ 使用 |

> **关键点**: 镜像 COPY 全部代码目录，角色隔离**不在构建时**（Dockerfile），而在**运行时**（K8s command 覆盖）。

### 9.3 容器启动命令

**单镜像，多角色** — 镜像默认 `CMD` 启动 Gateway，Worker/Scheduler 由 K8s 的 `command` + `args` 覆盖。

| 角色 | command | args | SERVICE_ROLE |
|------|---------|------|-------------|
| **Gateway** | `["uvicorn"]` | `["gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]` | `gateway` |
| **Worker** | `["celery"]` | `["-A", "infrastructure.queue.task_queue", "worker", "--loglevel=info", "--concurrency=4"]` | `worker` |
| **Scheduler** | `["celery"]` | `["-A", "infrastructure.queue.task_queue", "beat", "--loglevel=info"]` | `scheduler` |

### 9.4 集群拓扑图

```
                              Internet
                                 │
                    ┌────────────▼────────────┐
                    │   Ingress (Nginx)        │
                    │   TLS + cert-manager     │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Gateway Cluster         │  3~10 Pods
                    │  (FastAPI + Jinja2 + SSE)│  HPA: CPU 70%
                    │  ┌────────────────────┐  │
                    │  │ gateway/           │  │
                    │  │ common/ (subset)   │  │
                    │  │ infra/cache,queue  │  │
                    │  └────────────────────┘  │──┐
                    └────────────┬────────────┘   │
                                 │                 │
                   1. 鉴权/限流  │                 │ 4. SSE Stream
                     校验/路由   │                 │ (实时推送进度)
                                 │                 │
                    ┌────────────▼────────────┐   │
                    │  Message Queue          │   │
                    │  (Celery + Redis)       │   │
                    │  ┌──────────┐           │   │
                    │  │ 2. 投递  │           │   │
                    │  └──────────┘           │   │
                    └────────────┬────────────┘   │
                                 │                 │
                                 │ 3. 消费执行     │
                    ┌────────────▼────────────┐   │
                    │  Worker Cluster          │   │
                    │  (LangGraph + LCEL)      │   │
                    │  ┌────────────────────┐  │   │
                    │  │ orchestrator/      │  │   │
                    │  │ business/          │  │   │
                    │  │ capabilities/      │  │   │
                    │  │ common/ (full)     │  │   │
                    │  │ infra/db,cache,q   │  │   │
                    │  └────────────────────┘  │───┘
                    └────────────┬────────────┘
                       HPA: CPU 70%
                       KEDA: Queue Depth > 10
                                 │
                    5. 读写      │
                    ┌────────────▼────────────┐
                    │  Postgres Cluster        │
                    │  (StatefulSet)           │
                    │  ┌────────────────────┐  │
                    │  │ checkpoint         │  │  ← 图执行状态
                    │  │ schemas            │  │  ← 业务数据
                    │  │ migrations         │  │
                    │  └────────────────────┘  │
                    └──────────────────────────┘

                    ┌──────────────────────────┐
                    │  Redis Cluster            │
                    │  (StatefulSet / Sentinel) │
                    │  ┌────────────────────┐  │
                    │  │ Cache (TTL 会话)   │  │
                    │  │ PubSub (Pod 通信)  │  │
                    │  │ Broker (Celery 队列)│  │
                    │  └────────────────────┘  │
                    └──────────────────────────┘

                    ┌──────────────────────────┐
                    │  MinIO / S3               │
                    │  ┌────────────────────┐  │
                    │  │ 静态资源 (CDN)     │  │
                    │  │ 用户上传文件       │  │
                    │  │ 模型权重 (可选)    │  │
                    │  └────────────────────┘  │
                    └──────────────────────────┘
```

### 9.5 Gateway ↔ Worker 通信协议

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│   Client    │──SSE──►│   Gateway    │──RPC──►│   Worker    │
│             │◄───────│              │◄───────│             │
└─────────────┘         └──────┬───────┘         └──────┬──────┘
                               │                        │
                               │  POST /run             │
                               │  ─────────────────►    │
                               │  Celery Task (async)   │
                               │                        │ executor.run()
                               │                        │ ──► Postgres
                               │                        │     (checkpoint)
                               │                        │
                               │  PubSub: run.{id}.done │
                               │  ◄─────────────────    │
                               │                        │
                               │  SSE event             │
          data: {"status":     │  ◄────────             │
            "completed"}       │                        │
```

**同步模式** (`POST /api/v1/run`):
1. Gateway 将请求投递到 Celery 队列
2. Worker 消费执行 → 结果写入 Postgres
3. Worker 发布 `run.{id}.done` 到 Redis PubSub
4. Gateway 通过 PubSub 感知完成 → 返回 RunResponse

**流式模式** (`POST /api/v1/stream`):
1. Gateway 投递到 Celery 队列
2. Worker 开始执行，每个节点完成后发布 `run.{id}.node_done` 到 PubSub
3. Gateway 订阅 PubSub → 转为 SSE event 推送给 Client
4. Worker 完成后发布 `run.{id}.done` → Gateway 发送 `data: [DONE]`

### 9.6 弹性伸缩策略 (拆分后)

| 集群 | 伸缩指标 | 触发条件 | 范围 |
|------|---------|---------|------|
| Gateway | CPU 利用率 | > 70% | 3 ~ 10 Pods |
| Gateway | 内存利用率 | > 80% | 3 ~ 10 Pods |
| Worker | CPU 利用率 | > 70% | 3 ~ 20 Pods |
| Worker | **KEDA: 队列深度** | `celery_queue_length > 10` | 3 ~ 50 Pods |
| Worker | 内存利用率 | > 80% | 3 ~ 20 Pods |

### 9.7 集群反模式 (Cluster Anti-Patterns)

| 反模式 | 单机风险 | 集群风险 | 修复方案 |
|--------|---------|---------|---------|
| 进程内状态 | 重启丢数据 | Worker 重启丢任务上下文 | 强制使用 `PostgresSaver`，每次 `executor.run()` 必须携带 `thread_id` |
| 本地消息队列 | 单机可用 | 跨 Pod 无法感知事件 | 删除所有本地 `asyncio.Queue`，统一替换为 `infrastructure/queue/` 和 Redis PubSub |
| 同步文件 IO | 性能问题 | 多 Pod 争抢日志/静态资源 | 静态资源放 CDN 或对象存储 (`infrastructure/storage/`)，日志必须输出到 stdout（由 ELK 采集） |
| 内存缓存 | 重启丢失 | Pod 间缓存不一致 | 所有缓存统一走 Redis，禁止 `functools.lru_cache` 缓存业务数据 |
| 本地 Checkpoint | 单机容错 | Worker 宕机任务无法接管 | 强制 PostgresSaver，其他 Worker 可通过 `thread_id` 从最近的 checkpoint 恢复 |
| Gateway 直连 Worker | — | 耦合导致无法独立伸缩 | Gateway 通过 Celery 队列投递任务，不直接 import Worker 内部模块 |

### 9.8 集群运维指标

拆分后必须新增的 Prometheus 指标（详见 [common/COMMON.md](common/COMMON.md)）：

| 指标 | 类型 | 用途 |
|------|------|------|
| `langgraph_queue_length` | Gauge | KEDA 伸缩依据 |
| `langgraph_worker_busy` | Gauge | Worker 繁忙度监控 |
| `langgraph_pubsub_latency_seconds` | Histogram | 跨 Pod 通信延迟 |
| `langgraph_checkpoint_recovery_total` | Counter | Checkpoint 恢复次数（衡量故障切换） |

---

## 10. 扩展与变更规则

### 10.1 新增模块

1. 确定模块属于哪一层
2. 创建 `__init__.py` 说明模块职责
3. 继承/实现所在层的抽象基类
4. 在对应层文档中补充说明
5. **跨层模块需在本文档更新契约**

### 10.2 修改层间契约

1. 先更新本文档的"层间契约"章节
2. 更新涉及的两个模块文档
3. 同步更新相关接口的 docstring
4. 所有调用方适配后再合并

### 10.3 新增技术依赖

- 必须在 `pyproject.toml` 中明确声明
- 不得引入与现有技术栈冲突的库（见第 7 节）
- 新增中间件基础设施（如 Kafka、MongoDB）需评估必要性并更新架构文档
