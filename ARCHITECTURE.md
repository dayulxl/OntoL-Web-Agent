# ARCHITECTURE.md — 架构约束

> **定位**: 本文档定义全局性架构规则与跨层约束。各层的实现细节、编码规范、接口契约见各自模块文档。

**版本**: 2.4.1 | **更新**: 2026-07-10

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
│   │   ├── chat_routes.py             # 对话 SSE 流式 API（7步管道 + 动态提示词）
│   │   ├── langgraph_routes.py         # LangGraph 工作流 API (/run, /stream, /status...)
│   │   ├── page_routes.py              # Jinja2 页面路由（17 个页面含 /prompt-manager）
│   │   ├── ontology_routes.py          # 本体建模 + 场景 + 提示词 + 图 CRUD + 聊天绑定
│   │   └── datamanage_routes.py        # 数据源/动态API/内置代码/日志 管理
│   ├── middleware/                   # 中间件
│   │   ├── __init__.py
│   │   ├── auth.py                   # 鉴权 (JWT / API-Key)
│   │   ├── logging.py                # 请求日志
│   │   └── rate_limiter.py           # 限流 (Redis 滑动窗口)
│
├── webAPP/                           # Web 前端 (Jinja2 模板 + 静态资源)
│   ├── templates/                    # Jinja2 模板文件
│   │   ├── base.html                 # 基础布局
│   │   ├── pages/                    # 业务页面
│   │   │   ├── index.html              # 态势总览（含场景管理入口）
│   │   │   ├── chat.html               # AI 对话（场景+提示词选择）
│   │   │   ├── prompt_manager.html     # 🆕 场景管理（左场景右提示词）
│   │   │   ├── ontology.html           # 本体建模（图可视化+CRUD）
│   │   │   ├── ontology_template.html  # 本体语义（树形字段管理）
│   │   │   ├── sandbox_wargame.html    # 沙盘推演（ReactFlow+推理机）
│   │   │   ├── upload.html             # 文件上传+AI解析+图导入
│   │   │   ├── datamanage.html         # 数据管理（卡片式）
│   │   │   ├── metadata.html           # 元数据管理
│   │   │   ├── dictionary.html         # 维度管理
│   │   │   ├── reasoner_world.html     # 推理机设置
│   │   │   ├── intelligence.html       # 情报展示
│   │   │   └── ...                     # 其余页面
│   │   ├── components/               # 可复用组件
│   │   │   └── navbar.html             # 导航栏（12 个链接含场景管理）
│   └── static/                       # 静态资源 (CSS / JS / 图片)

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

├── capabilities/                     # LangChain 能力层 (可复用 AI 单元)
│   ├── __init__.py
│   ├── agents/                       # Agent
│   │   ├── __init__.py
│   │   ├── base.py                   # BaseAgent 抽象类 (ReAct)
│   │   └── chat_agent.py             # ChatAgent（ReAct + 7工具 + 动态提示词）
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
│   │   ├── registry.py               # PromptRegistry (文件加载 + 热更新 + 回退默认值)
│   │   ├── pipeline_steps.py         # 管道步骤 SSOT 定义
│   │   ├── agents/                   # Agent 提示词 (.txt)
│   │   └── chains/                   # Chain 模板 (.txt)
│   ├── memory/                       # 记忆管理
│   │   ├── __init__.py
│   │   ├── short_term.py             # ShortTermMemory (Redis, 会话级)
│   │   ├── long_term.py              # LongTermMemory (向量库, 跨会话)
│   │   └── graph_memory.py           # GraphMemory (Memgraph/Neo4j, 知识图谱, 增删属性)
│   └── models/                       # 模型抽象层 (7 种类型 × 4 提供商)
│       ├── __init__.py
│       ├── interfaces.py             # ModelInterface 抽象
│       ├── factory.py                # ModelFactory (按类型+名称路由)
│       └── models.yaml               # 模型配置 (LLM/Embedding/Reranker/TTS/STT/Vision/Image)

├── business/                           # 业务域层 (按业务域组织的工作流 + Agent)
│   ├── __init__.py                     # 业务层入口 + REGISTRY 列表
│   ├── master_agent.py                 # MasterAgent — 跨域总调度 (意图识别 → 分派 → 聚合)
│   ├── prompts/                        # 跨域共享提示词 (master.txt)
│   ├── ontology/                       # 本体语义域
│   │   ├── __init__.py
│   │   └── models.py                   # OntolModel / OntolModelAttr Pydantic 数据模型
│   ├── route_planning/                 # 航路规划域
│   │   ├── graph.py                    # RoutePlanningGraph
│   │   ├── state.py                    # RoutePlanningState
│   │   ├── nodes.py                    # 域节点实现（宽容执行已加固）
│   │   ├── agent.py                    # RoutePlanningAgent (ReAct)
│   │   ├── prompts/                    # 域专用提示词 (agent.txt)
│   │   └── tools/                      # 域专用工具
│   └── strike_decision/                # 打击决策域
│       ├── graph.py                    # StrikeDecisionGraph
│       ├── state.py                    # StrikeDecisionState
│       ├── nodes.py                    # 域节点实现（宽容执行已加固）
│       ├── agent.py                    # StrikeDecisionAgent (ReAct)
│       ├── prompts/                    # 域专用提示词 (agent.txt)
│       └── tools/                      # 域专用工具

├── infrastructure/                   # 基础设施层
│   ├── __init__.py
│   ├── db/                           # 数据库
│   │   ├── __init__.py
│   │   ├── sqlite_db.py               # SQLite 自动建表+种子 (12张表)
│   │   ├── base_repo.py               # BaseRepository 通用异步 CRUD 基类
│   │   ├── postgres.py                # asyncpg 连接池 + 健康检查 + 迁移执行器
│   │   ├── ontology_repo.py           # OntologyRepo — 本体模型数据访问层
│   │   ├── neo4j.py                   # 图数据库驱动 + 连接池（Memgraph/Neo4j）
│   │   ├── ontol.db                   # 本体模型数据库
│   │   │   ├── ontol_model              # 本体模型定义（12行）
│   │   │   ├── ontol_model_attr         # 模型属性字段（28个有效字段）
│   │   │   ├── ontol_model_scene        # 推演场景
│   │   │   ├── ontol_scene_prompt         # 🆕 场景提示词
│   │   │   ├── ontol_char_scene_relation # 对话↔场景绑定
│   │   │   ├── ontol_node_scene_relation # 图节点↔场景绑定
│   │   │   ├── ontol_data_his           # 数据变更历史
│   │   │   ├── ontol_datasource          # 数据源配置
│   │   │   ├── ontol_datasource_type     # 数据源类型
│   │   │   ├── ontol_datasource_type     # 数据源类型
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

├── tests/                            # 测试
│   ├── __init__.py
│   └── conftest.py                   # 全局 fixtures

├── scripts/                          # 运维脚本
│   ├── build.sh                      # Docker 镜像构建
│   └── migrate.sh                    # 数据库迁移 (Alembic)
│
├── ARCHITECTURE.md                   # 本文档 (全局架构约束)
├── CLAUDE.md                         # 项目指令 + 关键功能 + 设计原则
├── gateway/GATEWAY.md                # 网关层约束文档
├── orchestrator/ORCHESTRATOR.md      # 编排层约束文档
├── business/BUSINESS.md              # 业务域层约束文档
├── capabilities/CAPABILITIES.md      # 能力层总览
├── capabilities/agents/AGENTS.md     # Agent 约束文档
├── capabilities/chains/CHAINS.md     # Chain 约束文档
├── capabilities/tools/TOOLS.md       # Tool 约束文档
├── capabilities/prompts/PROMPTS.md   # Prompt 约束文档
├── capabilities/memory/MEMORY.md     # Memory 约束文档
├── capabilities/models/MODELS.md     # Model 约束文档
├── infrastructure/INFRASTRUCTURE.md  # 基础设施约束文档
├── common/COMMON.md                  # 共享层约束文档
└── tests/TESTS.md                    # 测试策略

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
| **MUST NOT** 依赖 Docker | 开发与运行环境尽量直接使用本地服务，不强制依赖 Docker 容器；中间件（Postgres/Redis/图数据库）优先本地安装或远程连接 |
| **MUST** id 为技术主键 | 每个表的 `id` 列是数据的唯一技术标识符，作为锁定数据的技术组件，查询/更新/删除均以 `id` 为锚点，前端不可修改；`code`/`name` 仅用于展示与搜索 |
| **MUST** id 由后端 UUID 生成 | 所有表的 `id` 主键均由后端 `uuid.uuid4().hex[:16]` 自动生成，前端表单禁止展示 id 输入框；列表/表格不展示原始 id 码，用业务语义字段（`name`/`code`/`llm_subtype` 等）代替展示 |
| **MUST** 推理机副本节点 ID | 推理机创建副本/派生节点时，新节点 ID 必须为 `{原节点ID}-{副本编码}`（如 `node_abc-V1.0`），确保图内全局唯一且可追溯 |
| **MUST** 图节点/边 ID 用 Snowflake | 图数据库（Memgraph）中所有节点和边的 `id` 属性必须是 Snowflake 算法生成的 **64 位纯数字整数**（不转字符串，不带连字符）；结构：`timestamp(42bit) \| datacenter(5bit) \| worker(5bit) \| sequence(12bit)`，纪元 2020-01-01；导入前先查询已有 ID 去重，相同随机标识串映射到同一 Snowflake ID |
| **MUST** `ontol_` 表名前缀 | SQLite 中所有配置/元数据表名必须以 `ontol_` 为前缀（如 `ontol_model`、`ontol_scene_prompt`） |
| **MUST** 新增按钮在顶部 | 前端所有列表/树/表格页面，新增按钮放在**内容区域顶部**（标题栏或搜索栏右侧），不在底部 |
| **MUST** 编辑/删除按钮在行右 | 列表、树节点的编辑和删除按钮放在**行右侧**，鼠标悬停时显示或常驻 |
| **MUST** 卡片按钮在右上角 | 卡片布局中，编辑和删除按钮必须放在卡片**右上角**，不占用卡片内容区域 |
| **MUST** 操作按钮必须可见 | 所有 CRUD 操作（新增、编辑、删除）必须提供**可见的页面按钮**，禁止仅通过键盘快捷键触发；快捷键可作为辅助快捷入口，但不能是唯一操作路径 |
| **MUST** 新建按钮必须有可见按钮 | 新增/创建操作必须同时提供**可见页面按钮**，不可仅依赖键盘快捷键（如 Ctrl+N）；快捷键为辅助手段，按钮是主要入口 |

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

### 2.1 GraphExtension 协议（产品→业务）

```python
class GraphExtension(Protocol):
    graph_name: str
    async def initialize(self) -> None: ...
    async def run(self, input_data: dict, config: Optional[dict] = None) -> dict: ...
    async def stream(self, input_data: dict, config: Optional[dict] = None) -> AsyncIterator[dict]: ...
    async def get_state(self, thread_id: str) -> Optional[dict]: ...
    async def close(self) -> None: ...
```

### 2.2 数据流契约

```
gateway/ (HTTP/SSE)
  → orchestrator/ (GraphExecutor)
    → business/ (域图)
      → capabilities/ (Agent/Chain/Tool)
        → infrastructure/ (DB/Cache/Queue)
```

### 2.3 场景管理 & 提示词数据流 🆕

```
prompt_manager.html → POST /api/v1/scenes/{id}/prompts → SQLite ontol_scene_prompt 表
chat.html → 选择场景+提示词 → POST /api/v1/chat {prompt_id}
  → chat_routes.py 从 DB 加载 prompt_content
  → chat_agent.py 用 custom_prompt 替代 SYSTEM_PROMPT
  → LangChain ReAct Agent 按自定义提示词推理
```

---

## 3. 数据流约束

### 3.1 请求生命周期

```
HTTP Request → middleware (auth/log/rate) → route handler
  → orchestrator (GraphExecutor) → business (domain graph)
  → capabilities (agent/chain) → infrastructure (DB/cache)
  → Response (JSON/SSE/HTML)
```

### 3.2 状态流约束

- 所有持久化状态通过 Postgres (checkpoint) + Redis (会话缓存) + Memgraph (知识图谱) 外置
- Worker 进程无状态，可任意扩缩
- LangGraph checkpoint 线程安全，支持并发读取（写操作按 thread_id 序列化）

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

### 4.3 宽容执行 (Tolerant Execution v1.0)

**所有设计必须是灵活的，不可因缺少字段或值为空而中断执行。**

| 场景 | 处理方式 |
|------|----------|
| 有这个字段 | 用它 |
| 没有这个字段 | 跳过，继续执行 |
| 有这个值 | 处理它 |
| 没有这个值 | 用默认值兜底，继续执行 |

**适用各层**：

| 层 | 要求 |
|----|------|
| gateway | 请求体缺字段不 400，缺值字段填默认值；响应缺字段用 `None` 而不是抛异常 |
| orchestrator | 图节点缺 `hasPrecondition` 就跳过校验；`hasCost`/`hasEffect`/`hasDuration`/`hasPriority` 不存在就按默认行为执行；checkpoint 恢复失败 → 重头执行 |
| capabilities | LLM 提取字段缺就留空；工具调用参数缺就用 schema default；记忆检索失败 → 返回空列表不报错 |
| infrastructure | DB 列缺失 → NULL 兜底；外部服务超时 → 降级返回缓存/空值 |
| business | 业务节点缺字段 → 跳过该步骤；输入校验不通过 → warning 日志 + 继续 |

**反模式**（禁止）：

- `obj["field"]` 直接取值 → 改用 `obj.get("field")` 或 `getattr(obj, "field", default)`
- 字段缺失抛异常导致整个流程中断 → 降级处理 + 日志 warning
- 前端 `undefined` 导致白屏 → 可选链 `?.` + 兜底值
- 导入/导出因单条记录缺字段阻断整批 → 跳过坏记录 + 汇总报告

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

---

## 6. 模块约束文档索引

每个模块目录包含自己的约束文档，定义该模块的实现细节和编码规范：

| 模块 | 文档 | 说明 |
|------|------|------|
| gateway | [gateway/GATEWAY.md](gateway/GATEWAY.md) | HTTP API 规范、中间件约束、路由设计 |
| orchestrator | [orchestrator/ORCHESTRATOR.md](orchestrator/ORCHESTRATOR.md) | 图构建/执行约束、状态管理规范 |
| business | [business/BUSINESS.md](business/BUSINESS.md) | 业务域组织规范、MasterAgent 调度规则 |
| capabilities | [capabilities/CAPABILITIES.md](capabilities/CAPABILITIES.md) | 能力层总览、跨子模块约束 |
| capabilities/agents | [capabilities/agents/AGENTS.md](capabilities/agents/AGENTS.md) | Agent 实现约束、ReAct 规范 |
| capabilities/prompts | [capabilities/prompts/PROMPTS.md](capabilities/prompts/PROMPTS.md) | Prompt 管理规范、模板语法 |
| common | [common/COMMON.md](common/COMMON.md) | 公共代码约束、配置与异常规范 |
| infrastructure | [infrastructure/INFRASTRUCTURE.md](infrastructure/INFRASTRUCTURE.md) | 基础设施约束、连接池规范 |
| tests | [tests/TESTS.md](tests/TESTS.md) | 测试策略与覆盖要求 |

---

## 7. 技术栈约束

| 组件 | 版本/方案 | 约束 |
|------|----------|------|
| Python | 3.14 | 必须 |
| FastAPI | latest | 异步优先，SSE 用 StreamingResponse |
| LangChain | 0.3 | 能力层统一入口 |
| LangGraph | 0.3 | 编排层统一入口，用预构建 ReAct Agent |
| Pydantic | v2 | 配置与数据校验 |
| Memgraph | Neo4j 兼容 | 图存储，Bolt 协议连接 |
| SQLite | 内嵌 | 本体模型 + 场景 + 提示词元数据存储 |
| Jinja2 | FastAPI 集成 | 服务端模板渲染 |
| structlog | latest | 结构化日志 |

---

## 8. 数据库表总览 🆕

### 8.1 SQLite (ontol.db) — 14 张表

| 表 | 用途 |
|----|------|
| `ontol_model` | 本体模型定义（树形结构，M_ROOT + 子模型） |
| `ontol_model_attr` | 模型属性字段（28个有效字段，attr_is_system 区分系统预设/自定义） |
| `ontol_model_scene` | 推演场景（scene_is_system 区分系统预设/自定义） |
| `ontol_scene_prompt` | 场景提示词模板（场景内可建多个，AI 对话动态匹配） |
| `ontol_scene_dictionary` | 场景词典词条（ontology 边属性 + 字段语义描述） |
| `ontol_dictionary_type` | 词典词条分类（is_system 区分系统预设/自定义） |
| `ontol_scene_dictionary_relation` | 场景 ↔ 词典词条关联（多对多关系） |
| `ontol_char_scene_relation` | 对话 ↔ 场景绑定（多对多关系） |
| `ontol_node_scene_relation` | 图节点 ↔ 场景绑定（多对多关系） |
| `ontol_data_his` | 图数据变更历史（节点 CRUD 自动记录 + 版本递增） |
| `ontol_datasource` | 数据源配置（MySQL/PG/Oracle 等） |
| `ontol_datasource_type` | 数据源类型（is_system 区分系统预设/自定义） |
| `ontol_datasource_log` | 数据源同步日志（批次号 + 业务流水号） |
| `ontol_llm_config` | LLM 模型配置（url/key/model，对 ontol_llm_type_config 多对一） |
| `ontol_llm_type_config` | LLM 类型与子类型配置 |

### 8.2 表设计约束规范 🆕

> ⚠️ **核心约束**：所有 SQLite 表（`ontol_*`）在建表时 **必须** 包含以下 7 个通用字段。如果建表语句缺少任一字段，必须自动补上。

#### 8.2.1 通用字段定义

| 字段名称 | 数据类型（建议） | 约束条件 | 说明 |
|----------|-----------------|----------|------|
| `id` | TEXT / BIGINT | PRIMARY KEY, NOT NULL | 全局唯一主键，由后端 `uuid.uuid4().hex[:16]` 自动生成；图数据库用 Snowflake int64 |
| `create_time` | TEXT / DATETIME | NOT NULL, DEFAULT `(datetime('now'))` | 记录创建时间，默认值为当前时间，不可由前端传入 |
| `create_user` | TEXT / VARCHAR(64) | NOT NULL, DEFAULT `''` | 记录创建人标识（如用户ID或账号），追溯数据来源 |
| `update_time` | TEXT / DATETIME | NOT NULL, DEFAULT `''` | 记录最后更新时间，每次更新由后端自动刷新为当前时间 |
| `update_user` | TEXT / VARCHAR(64) | NOT NULL, DEFAULT `''` | 记录最后更新人标识，每次更新由后端自动刷新 |
| `delete_flag` | TEXT / TINYINT | NOT NULL, DEFAULT `'0'` | 逻辑删除标志（`'0'`-未删除，`'1'`-已删除），物理删除禁止 |
| `is_system` | TEXT / TINYINT | NOT NULL, DEFAULT `'0'` | 系统预设标志（`'0'`-自定义，`'1'`-系统预设，不可删除不可修改） |

#### 8.2.2 标准 DDL 模板

```sql
CREATE TABLE IF NOT EXISTS ontol_xxx (
    id              TEXT PRIMARY KEY,
    -- ... 业务字段 ...
    create_time     TEXT NOT NULL DEFAULT (datetime('now')),
    create_user     TEXT NOT NULL DEFAULT '',
    update_time     TEXT NOT NULL DEFAULT '',
    update_user     TEXT NOT NULL DEFAULT '',
    delete_flag     TEXT NOT NULL DEFAULT '0',
    is_system       TEXT NOT NULL DEFAULT '0'
);
```

#### 8.2.3 后端 CRUD 行为规范

| 操作 | 字段行为 |
|------|----------|
| **INSERT** | `id` 自动生成 UUID；`create_time` 取当前时间；`create_user` 从请求上下文注入；`update_time`/`update_user` 留空字符串；`delete_flag` 默认 `'0'` |
| **UPDATE** | `update_time` 自动刷新为当前时间；`update_user` 从请求上下文注入；`id`/`create_time`/`create_user` 不可更新 |
| **DELETE** | 仅软删除：`UPDATE SET delete_flag = '1', update_time = datetime('now')`；**绝不**执行物理 `DELETE FROM` |
| **SELECT** | 所有查询必须追加 `WHERE delete_flag = '0'`（除非元数据管理页面显式展示已删除数据） |

#### 8.2.4 现有表合规检查

| 表 | `id` | `create_time` | `create_user` | `update_time` | `update_user` | `delete_flag` | 状态 |
|----|------|---------------|---------------|---------------|---------------|---------------|------|
| `ontol_model` | ✅ TEXT PK | ✅ | ⚠️ `create_id` | ✅ | ⚠️ `update_id` | ✅ | 字段名需对齐 |
| `ontol_model_attr` | ✅ TEXT PK | ✅ | ⚠️ `create_id` | ❌ 缺失 | ❌ 缺失 | ✅ | 待补全 |
| `ontol_model_scene` | ✅ TEXT PK | ✅ | ⚠️ `create_id` | ❌ 缺失 | ❌ 缺失 | ✅ | 待补全 |
| `ontol_scene_prompt` | ✅ TEXT PK | ✅ | ⚠️ `create_id` | ❌ 缺失 | ❌ 缺失 | ✅ | 待补全 |
| `ontol_scene_dictionary` | ✅ TEXT PK | ✅ | ❌ 缺失 | ❌ 缺失 | ❌ 缺失 | ✅ | 待补全 |
| `ontol_dictionary_type` | ✅ TEXT PK | ✅ | ❌ 缺失 | ❌ 缺失 | ❌ 缺失 | ✅ | 待补全 |
| `ontol_datasource_type` | ✅ TEXT PK | ✅ | ❌ 缺失 | ❌ 缺失 | ❌ 缺失 | ✅ | 待补全 |
| `ontol_datasource` | ⚠️ INTEGER PK | ✅ | ⚠️ `created_by` | ❌ 缺失 | ❌ 缺失 | ❌ 缺失 | 待修复 |
| `ontol_datasource_log` | ✅ TEXT PK | ✅ | ❌ 缺失 | ❌ 缺失 | ❌ 缺失 | ❌ 缺失 | 待补全 |
| `ontol_scene_dictionary_relation` | ✅ TEXT PK | ✅ | ❌ 缺失 | ❌ 缺失 | ❌ 缺失 | ✅ | 待补全 |
| `ontol_llm_config` | ✅ TEXT PK | ✅ | ❌ 缺失 | ❌ 缺失 | ❌ 缺失 | ✅ | 待补全 |
| `ontol_llm_type_config` | ✅ TEXT PK | ✅ | ❌ 缺失 | ❌ 缺失 | ❌ 缺失 | ✅ | 待补全 |

#### 8.2.5 迁移规则

1. **新建表**：严格按 8.2.2 模板，6 个通用字段一个不能少
2. **已有表**：通过 `ALTER TABLE ADD COLUMN` 逐字段补全，补充的列使用 `NOT NULL DEFAULT ''` 兼容已有数据
3. **历史命名**：`create_id` → `create_user`，`update_id` → `update_user`，`created_by` → `create_user`
4. **图数据库（Memgraph）**：仅节点/边属性参照执行，`id` 使用 Snowflake int64，其余字段按 key-value 标量类型存储

### 8.3 Memgraph (图数据库)

- **ID 标准**：所有节点和边的 `id` 属性使用 **Snowflake 算法** 生成 **64 位纯数字整数**（`int64`，不转字符串），结构为 `timestamp(42bit) | datacenter(5bit) | worker(5bit) | sequence(12bit)`，纪元 2020-01-01
- **ID 生成**：导入时由 `SnowflakeGenerator`（`gateway/routes/ontology_routes.py`）生成，先查询图中已有 ID 去重，确保全局唯一
- **ID 替换**：LLM 随机生成的字符串 ID 在写入前替换为 Snowflake ID，相同随机串映射到相同 Snowflake ID，保证引用一致性
- 节点属性基于 M_ROOT 28 字段扩展
- 关系类型通过 Cypher 动态定义
- 推理机副本节点 ID 格式：`{原节点ID}-{副本编码}`

---

## 9. 变更历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 2.4.1 | 2026-07-10 | 图节点/边 Snowflake ID 标准（64 位）；OWL2+SWRL+SHACL 语义规范；本体类型 M1-M7 枚举；LLM 解析提示词重构（25 字段 + 关系格式升级）|
| 2.4.0 | 2026-07-10 | 新增场景管理 + 提示词（ontol_scene_prompt 表 + CRUD + chat 集成）；宽容执行加固全代码库；id 技术主键规范；推理机副本节点 ID 规则；M_ROOT 字段扩至 28 个 |
| 2.3.1 | 2026-06-30 | 初始文档 |