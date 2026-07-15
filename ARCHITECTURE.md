# ARCHITECTURE.md — 架构约束

> **定位**: 本文档定义全局性架构规则与跨层约束。各层的实现细节、编码规范、接口契约见各自模块文档。

**版本**: 3.1.0 | **更新**: 2026-07-14

**主题**: 对话元数据 DB 化 + 审核记录类型化 + 模块间调用规范

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
d:/langchain/                        # 项目根（Git 仓库根）
├── gateway/                          # API 网关层
│   ├── __init__.py
│   ├── app.py                        # FastAPI 应用入口
│   ├── GATEWAY.md                    # 网关层约束文档
│   ├── routes/                       # 路由定义
│   │   ├── __init__.py
│   │   ├── chat_routes.py             # 对话 SSE 流式 API（7步管道 + 动态提示词）
│   │   ├── langgraph_routes.py         # LangGraph 工作流 API
│   │   ├── page_routes.py              # Jinja2 页面路由（加载 webAPP/templates/）
│   │   ├── ontology_routes.py          # 本体建模 + 场景 + 提示词 + 对话 + 图 CRUD
│   │   ├── datamanage_routes.py        # 数据源/动态API/内置代码/日志 管理
│   │   └── reasoning_routes.py         # 🆕 图推理机 SSE 流式接口
│   ├── middleware/                   # 中间件
│   │   ├── __init__.py
│   │   ├── auth.py                   # 鉴权 (JWT / API-Key)
│   │   ├── logging.py                # 请求日志
│   │   └── rate_limiter.py           # 限流 (Redis 滑动窗口)
│   ├── templates/                    # ⚠️ 遗留模板目录（14 页，page_routes.py 不使用）
│   │   ├── base.html
│   │   ├── components/navbar.html
│   │   └── pages/                    # chat/sandbox_wargame/upload/ontology/...
│   └── static/                       # 遗留静态资源
│       ├── css/main.css
│       ├── js-treeview.css
│       └── js-treeview.js
│
├── webAPP/                           # Web 前端（运行时 Jinja2 模板 + 静态资源）
│   ├── templates/                    # Jinja2 模板（page_routes.py 实际加载）
│   │   ├── components/
│   │   │   └── navbar.html            # 导航栏组件
│   │   └── pages/                    # 业务页面（12 个）
│   │       ├── chat.html              # AI 对话
│   │       ├── prompt_manager.html    # 场景管理（左场景右提示词）
│   │       ├── ontology.html          # 本体建模（图可视化+CRUD）
│   │       ├── ontology_template.html # 本体语义（树形字段管理）
│   │       ├── sandbox_wargame.html   # 沙盘推演（ReactFlow+推理机）
│   │       ├── upload.html            # 文件上传+AI解析+图导入
│   │       ├── datamanage.html        # 数据管理（卡片式）
│   │       ├── metadata.html          # 元数据管理
│   │       ├── dictionary.html        # 维度管理
│   │       ├── function_manager.html  # 动态函数管理
│   │       ├── llm_config.html        # LLM 模型配置
│   │       └── reasoning_ui.html      # 🆕 推理机控制台
│   └── static/
│       └── js/
│           └── graph-layout.js        # 有向图布局引擎
│
├── orchestrator/                     # LangGraph 编排层（核心调度引擎）
│   ├── __init__.py
│   ├── ORCHESTRATOR.md
│   ├── graphs/
│   │   ├── __init__.py
│   │   └── base.py                   # BaseWorkflowGraph 抽象基类（实现 GraphExtension）
│   ├── state/
│   │   ├── __init__.py
│   │   ├── schema.py                 # GraphState TypedDict
│   │   └── manager.py                # StateManager (Postgres checkpoint)
│   ├── router/
│   │   ├── __init__.py
│   │   └── conditional_router.py     # ConditionalRouter
│   └── engine/
│       ├── __init__.py
│       ├── executor.py               # GraphExecutor (工作流注册·调度)
│       └── checkpoint.py             # PostgresSaver 工厂
│
├── capabilities/                     # LangChain 能力层（可复用 AI 单元）
│   ├── __init__.py
│   ├── CAPABILITIES.md
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── AGENTS.md
│   │   ├── base.py                   # BaseAgent 抽象类 (ReAct)
│   │   └── chat_agent.py             # ChatAgent（ReAct + 7工具 + 动态提示词）
│   ├── chains/
│   │   ├── __init__.py
│   │   └── CHAINS.md
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── TOOLS.md
│   │   ├── registry.py               # ToolRegistry（类级单例，MCP 兼容）
│   │   └── knowledge_graph.py         # 知识图谱 HTTP API 工具
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── PROMPTS.md
│   │   ├── registry.py               # PromptRegistry（文件加载 + 热更新）
│   │   ├── agents/                   # Agent 提示词 (.txt)
│   │   │   ├── coding.txt
│   │   │   ├── master.txt
│   │   │   ├── research.txt
│   │   │   ├── route_planning.txt
│   │   │   └── strike_decision.txt
│   │   └── chains/                   # Chain 模板 (.txt)
│   │       ├── rag.txt
│   │       └── summary.txt
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── MEMORY.md
│   │   └── graph_memory.py           # GraphMemory（Memgraph/Neo4j 知识图谱）
│   ├── models/
│   │   ├── __init__.py
│   │   ├── MODELS.md
│   │   ├── interfaces.py             # ModelInterface 抽象
│   │   ├── factory.py                # ModelFactory（按类型+名称路由）
│   │   └── models.yaml               # 模型配置
│   └── graph_reasoner/              # 图推理引擎 — 推理机协调者
│       ├── GRAPH_REASONER.md
│       ├── core/                     # 推理核心（待实现）
│       ├── actions/                  # 推理动作（待实现）
│       ├── translators/              # 本体查询翻译器（待实现）
│       └── versioning/               # 版本管理（待实现）
│
├── business/                         # 业务域层
│   ├── __init__.py
│   ├── BUSINESS.md
│   ├── api/                         # 🆕 对外接口层 — 唯一合法入口，不写业务，只做 re-export + 转换 + 分发
│   │   └── __init__.py               #   facade：from business.api import submit_audit（按需扩展子模块）
│   ├── master_agent.py               # MasterAgent — 跨域总调度
│   ├── prompts/
│   │   └── master.txt                # master agent 提示词
│   ├── upload/                      # 🆕 文件上传 & AI 实体解析业务域
│   │   ├── auto_import/               #   全自动导入四步管线
│   │   │   ├── __init__.py            #     统一入口: run_parse_pipeline/validate_entities/enrich_entities/import_to_graph
│   │   │   ├── step1_parse.py         #     Step 1: AI 本体解析
│   │   │   ├── step2_validate.py      #     Step 2: 模板校验 & 字段补全
│   │   │   ├── step3_enrich.py        #     Step 3: 符号语言填充 & 推理机校验
│   │   │   └── step4_import.py        #     Step 4: 导入 Memgraph 图数据库
│   │   ├── parser.py                  #   文件文本提取 + JSON 解析 + 两阶段 LLM 管线
│   │   ├── prompts.py                 #   LLM 提示词构建 (分类/字段提取)
│   │   ├── validation.py              #   模板匹配 + 继承链缺失字段计算
│   │   └── import_service.py          #   雪花ID映射 + Memgraph写入 + 场景绑定
│   │   ├── excel_service.py           #   Excel 批量导入导出
│   ├── route_planning/               # 航路规划域
│   │   ├── __init__.py
│   │   ├── graph.py                  # RoutePlanningGraph
│   │   ├── state.py                  # RoutePlanningState
│   │   ├── nodes.py                  # 域节点实现
│   │   ├── agent.py                  # RoutePlanningAgent (ReAct)
│   │   ├── prompts/agent.txt         # 域专用提示词
│   │   └── tools/__init__.py
│   ├── strike_decision/              # 打击决策域
│   │   ├── __init__.py
│   │   ├── graph.py                  # StrikeDecisionGraph
│   │   ├── state.py                  # StrikeDecisionState
│   │   ├── nodes.py                  # 域节点实现
│   │   ├── agent.py                  # StrikeDecisionAgent (ReAct)
│   │   ├── prompts/agent.txt         # 域专用提示词
│   │   └── tools/__init__.py
│   ├── reasoning/                    # 🆕 图推理机业务域（四步流水线）
│   │   ├── __init__.py               #   公共 API：ReasoningEngine, run_reasoning, run_reasoning_on_nodes
│   │   ├── engine.py                 #   编排器：管理共享状态 (cm/ancestors/log)，按序调用四步
│   │   ├── step1_clone.py            #   Step 1: 复制推理关联对象（种子+祖先+下游→副本空间）
│   │   ├── step2_relink.py           #   Step 2: 副本节点间重建边关系
│   │   ├── step3_inherit.py          #   Step 3: owl2:subClassOf 属性继承
│   │   ├── step4_reason.py           #   Step 4: 逐节点推理叙述（precondition→effect→边属性）
│   │   ├── rules.py                  #   规则定义/校验/效果路由/置信度传播
│   │   └── graph_ops.py              #   底层图原子操作（查/克隆/建边/属性合并/遍历/Cypher）
│   ├── audit/                        # 🆕 审核记录业务域
│   │   ├── __init__.py               #   出口：submit_audit / record_audit_result / query_by_node ...
│   │   └── audit_service.py          #   ontol_audit_log 表 CRUD + Pydantic 模型 + 便捷函数
│   ├── chat/                         # 🆕 对话元数据管理
│   │   ├── __init__.py
│   │   └── chat_service.py           # ontol_char 表 CRUD（列表/创建/更新/删除）
│   └── transformation/               # 🆕 转换层：本体语言 → Cypher
│       ├── __init__.py
│       ├── rdfs_converter.py         # ① RDFS (rdfs: 前缀)
│       ├── owl2_converter.py         # ② OWL2 DL (owl2: 前缀)
│       ├── swrl_converter.py         # ③ SWRL (swrl: 前缀)
│       ├── shacl_converter.py        # ④ SHACL (sh: 前缀)
│       ├── rule_converter.py         # ⑤ 规则设定 (rule: 前缀)
│       ├── func_converter.py         # ⑥ 动态函数 (func: 前缀)
│       └── jsonpath_converter.py     # ⑦ JSONPath ($. 前缀，RFC 9535)
│
├── infrastructure/                   # 基础设施层
│   ├── __init__.py
│   ├── INFRASTRUCTURE.md
│   ├── db/                            # 关系型数据库 (SQLite / PostgreSQL)
│   │   ├── __init__.py
│   │   ├── sqlite_db.py              # SQLite 自动建表+种子 (21 张表)
│   │   ├── base_repo.py              # 对象↔SQL 双向映射层 (insert/update/delete/list/search/upsert)
│   │   ├── postgres.py               # asyncpg 连接池 + 健康检查
│   │   ├── ontology_repo.py          # 领域实现: 树形查询 + 批量导入模型/字段 (调用 base_repo)
│   │   └── ontol.db                  # 本体模型数据库文件
│   ├── graph/                         # 图数据库 (Memgraph/Neo4j)
│   │   ├── neo4j.py                  # Memgraph 驱动 (memgraph://→bolt:// 连接池)
│   │   ├── base_graph_repo.py        # 对象→Cypher 转换器 (create_node/merge_edge/delete/search)
│   │   └── ontology_graph_repo.py    # 领域实现: Label映射 + 关系类型常量 + 图遍历
│   ├── cache/
│   │   ├── __init__.py
│   │   └── redis.py                  # Redis 客户端（缓存 + PubSub）
│   └── config/
│       ├── __init__.py
│       └── dynamic.py                # DynamicConfig（Redis 热更新）
│
├── common/                           # 共享层
│   ├── __init__.py
│   ├── COMMON.md
│   ├── contracts/
│   │   ├── __init__.py
│   │   ├── graph_extension.py        # GraphExtension Protocol
│   │   └── state_schema.py           # GraphStateBase TypedDict
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py               # Pydantic Settings（环境变量）
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py                # RunRequest, RunResponse, StreamEvent 等
│   ├── exceptions/
│   │   ├── __init__.py
│   │   └── base.py                   # 异常层次（1 基类 + 9 子类）
│   └── utils/
│       ├── __init__.py
│       └── logger.py                 # structlog 结构化日志
│
├── tests/                            # 测试
│   ├── __init__.py
│   └── TESTS.md
│
├── deployments/                      # Docker & K8s 部署配置
│   ├── DEPLOYMENTS.md
│   └── k8s/                          # 9 个 K8s YAML
│
├── scripts/                          # 运维脚本
├── pyproject.toml                    # Poetry 项目配置
├── ARCHITECTURE.md                   # 本文档（全局架构约束）
├── CLAUDE.md                         # 项目指令 + 关键功能 + 设计原则
└── README.md                         # 项目说明
```

### 1.3 硬性约束 (MUST / MUST NOT)

| 规则 | 说明 |
|------|------|
| **MUST** 向下依赖 | 上层可依赖下层，绝对禁止反向 import |
| **MUST NOT** 跨层跳过 | `gateway/` 不得直接 import `capabilities/`；必须经过 `orchestrator/` |
| **MUST NOT** 同层耦合 | 同层模块间不得直接 import，通过 `common/` 或抽象接口通信 |
| **MUST** 接口隔离 | 层间通过抽象类或 TypedDict 通信，不得依赖具体实现 |
| **MUST** 无状态 | Worker 进程不得在内存中持有业务状态，状态全部外置到 Postgres / Redis |
| **MUST NOT** 硬编码密钥 | API Key、Token、密码等一律通过环境变量注入 |
| **MUST** 异常统一 | 所有业务异常继承 `common.exceptions.base.AppException` |
| **MUST** UTF-8 无 BOM | 所有文本文件必须 UTF-8 编码，不含 BOM 头 |
| **MUST** 新业务入 business/ | 新增业务工作流必须放在 `business/<domain>/` 下 |
| **MUST NOT** 依赖 Docker | 开发环境优先本地服务，不强制依赖 Docker |
| **MUST** id 为技术主键 | `id` 是唯一技术标识符，前端不可修改 |
| **MUST** id 由后端 UUID 生成 | 所有表 `id` 由 `uuid.uuid4().hex[:16]` 自动生成 |
| **MUST** 推理机副本节点 ID | 格式 `{原节点ID}-{副本编码}`（如 `node_abc-V1.0`） |
| **MUST** 图节点/边 ID 用 Snowflake | Memgraph 中所有节点和边 `id` 为 64 位纯数字整数 (int64) |
| **MUST** `ontol_` 表名前缀 | SQLite 中所有配置/元数据表名必须以 `ontol_` 为前缀 |
| **MUST** `business/<domain>/` 暴露函数接口 | 内部模块间调用 MUST 走 Python import，**禁止**内部 HTTP 调用；函数签名：必填参数前置 + keyword-only 可选 + Pydantic 模型辅助 |
| **MUST** 新增按钮在顶部 | 前端新增按钮放在内容区域顶部 |
| **MUST** 编辑/删除按钮在行右 | 列表行的编辑和删除按钮放在行右侧 |
| **MUST** 卡片按钮在右上角 | 卡片布局的编辑/删除按钮放在卡片右上角 |
| **MUST** 操作按钮必须可见 | 所有 CRUD 操作必须有可见页面按钮 |
| **MUST** HTML 属性值转义 | 动态内容嵌入 HTML 属性时用 `escHtml()` 转义 |
| **MUST** 批量数据双端确认 | 批量处理涉及 Memgraph + SQLite 双端数据时，操作前后必须分别查询两端，对比一致后再提交；任一端异常立即回滚，不可静默跳过 |
| **MUST** 本体字段宽容执行 | 节点/边上有这个字段就校验，没有就默认放行往下走，不阻断、不报错、不抛异常 |

### 1.5 本体字段宽容执行规范

> 本体系统中节点和边的属性是**可选**的。任何字段都可能存在也可能不存在。

**核心原则**：

| 情况 | 行为 |
|------|------|
| 有这个字段 | 用它、校验它 |
| 没有这个字段 | 跳过，**默认放行**，继续下一步 |
| 有这个值 | 处理它 |
| 没有这个值 | 用默认值兜底，不中断 |

**推理机执行约定**：

```
节点有 hasPrecondition → 校验，不满足则阻断
节点无 hasPrecondition → 跳过，默认放行

节点有 hasEffect       → 按前缀路由到 SWRL/SHACL/OWL2 引擎
节点无 hasEffect       → 跳过，默认放行

节点有 hasCost         → 记录消耗
节点无 hasCost         → 跳过

节点有 confidence      → 相乘传播，低于阈值阻断
节点无 confidence      → 维持当前置信度，不阻断

边有 required=true + validationType=Strong → 阻断
边无 required / validationType             → 默认放行，不阻断
```

**反模式**（禁止）：

- 字段缺失抛 `KeyError` / `AttributeError` 中断整个推理链
- 强制要求某字段存在才能推理
- 写死 `obj["field"]` 取值 → 一律用 `obj.get("field")`

### 1.6 批量数据双端确认规范

> ⚠️ 图数据库（Memgraph）和元数据库（SQLite）是两套独立存储，批量操作涉及双端数据时容易出现数据不一致。

**适用场景**：

| 场景 | Memgraph 操作 | SQLite 操作 |
|------|--------------|-------------|
| 节点 CRUD | 创建/更新/删除节点和边 | 写 `ontol_data_his` 历史记录 + 递增 `version` |
| 场景绑定 | 查图节点 | 写 `ontol_node_scene_relation` |
| 导入实体 | 批量创建节点 + 关系 | 写 `ontol_node_scene_relation` + 历史 |
| 推演副本 | 创建副本节点 + 边 | 更新 `ontol_cope_version` 状态 |
| 推理机写回 | 修改节点属性 + 建新边 | 写推理日志/历史 |

**操作流程**：

```
1. 操作前 → 查询 Memgraph 确认节点/边存在
2. 操作前 → 查询 SQLite 确认关联记录一致
3. 对比双端 → 不一致立即报错，禁止继续
4. 执行操作 → 先写 Memgraph，再写 SQLite
5. 任一失败 → 回滚另一端已写入的数据
6. 操作后 → 再次对比双端，确认一致后返回成功
```

**反模式**（禁止）：

- 只操作一端，失败不报错，留不一致数据在线上
- 批量导入中间某条失败不回头检查已写入数据
- Memgraph 写入成功但 SQLite 写入失败时不理，让历史表缺口永久存在

### 1.4 层级职责边界

| 层 | 目录 | 允许做的事 | 不允许做的事 |
|----|------|-----------|-------------|
| 网关 | `gateway/` | HTTP 路由、中间件、请求校验、SSE 流封装、Jinja2 模板渲染、静态文件服务 | 持有 LLM 实例、直接操作数据库、包含业务逻辑 |
| 编排 | `orchestrator/` | 图定义/编译/执行、状态管理、条件路由、checkpoint 持久化 | 直接构造 Prompt、定义 Tool 实现、管理连接池 |
| 业务 | `business/` | 定义域专用图/状态/节点、编排域业务流程、暴露 Python 函数给其他模块调用（禁止内部 HTTP） | 跨域直接 import、导入 `gateway/`、模块间走 HTTP |
| 能力 | `capabilities/` | Agent 定义、Chain 构建、Tool 实现、记忆存取、模型适配 | 处理 HTTP 请求、管理图状态、管理数据库连接 |
| 基础设施 | `infrastructure/db/` | 对象↔SQL 双向映射、连接池、Repository | 包含 AI 逻辑、业务判断 |
| 图数据库 | `infrastructure/graph/` | 对象→Cypher 转换、图遍历、Label/关系映射 | 包含业务标签、理解本体语义逻辑 |
| 共享 | `common/` | 配置读取、Pydantic Schema、异常类、工具函数 | 依赖任何上层或同层模块 |

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
        → infrastructure/ (DB/Cache)
```

### 2.3 场景管理 & 提示词数据流

```
prompt_manager.html → POST /api/v1/scenes/{id}/prompts → SQLite ontol_scene_prompt 表
chat.html → 选择场景+提示词 → POST /api/v1/chat {prompt_id}
  → chat_routes.py 从 DB 加载 prompt_content
  → chat_agent.py 用 custom_prompt 替代 SYSTEM_PROMPT
  → LangChain ReAct Agent 按自定义提示词推理
```

### 2.4 图推理机数据流 🆕

```
reasoning_ui.html → POST /api/v1/reasoning/run (SSE)
  → reasoning_routes.py → business/reasoning/engine.py (编排)
    ├─ step1_clone.py   graph_ops.clone_node + climb_subclass_chain + walk_inference_chain
    ├─ step2_relink.py  graph_ops.clone_edge
    ├─ step3_inherit.py graph_ops.merge_inherited_props + update_node_props
    └─ step4_reason.py  rules (check_precondition/classify_effect) + graph_ops.get_relationships
  → SSE 流式推送实时日志 → reasoning_ui.html
```

### 2.5 全自动导入四步管线 🆕

```
upload.html (🤖 全自动导入按钮) → POST /api/v1/upload/parse (Step 1)
  → auto_import/step1_parse.py → parser.py (文本提取→分块→LLM分类→LLM字段提取)
  → {entities, relationships, type_counts}

upload.html → POST /api/v1/upload/validate-entities (Step 2)
  → auto_import/step2_validate.py → validation.py (ontol_model模板匹配+继承链缺失字段)

upload.html → POST /api/v1/upload/enrich-entities (Step 3)
  → auto_import/step3_enrich.py (7种前缀识别+边属性填充+SWRL/SHACL/func结构校验)

upload.html → POST /api/v1/upload/import-entities (Step 4)
  → auto_import/step4_import.py → import_service.py (雪花ID→MERGE节点→MERGE关系→场景绑定)
```

**Step 3 符号语言覆盖**：

| # | 语言 | 前缀 | 边属性填充 | 结构校验 |
|---|------|------|-----------|---------|
| 1 | RDFS | `rdfs:` | actionType/validationType/msg | 前缀识别即合法 |
| 2 | OWL2 DL | `owl2:` | actionType/validationType/msg | 前缀识别即合法 |
| 3 | SWRL | `swrl:` | actionType=inference, validationType=Strong | antecedent→consequent 结构 |
| 4 | SHACL | `sh:` | actionType/validationType | 已知约束类型检查 |
| 5 | 规则设定 | `rule:` | ruleId=forwardChain/backwardChain | 方向枚举校验 |
| 6 | 动态函数 | `func:` | actionType=inference | 合法JSON + id/func字段 |
| 7 | JSONPath | `$.` | actionType=data | 路径段解析 |

所有四步均通过 `business/api/` re-export 统一入口，路由层只做薄壳调用。



**四步通过 Python 函数参数传递共享状态**（不经过路由、不走 HTTP）：

```python
cm:       dict[int, tuple[dict, int]]   # {原生ID: (原生节点dict, 副本ID)}  Step1填充→Step2-4消费
ancestors: list[dict]                   # OWL2 祖先链，Step1填充→Step3-4消费
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

### 3.3 模块间调用约束 🆕

**内部模块之间禁止走 HTTP，必须走 Python 函数调用。** 且所有外部调用必须经过 `business/api/` 中转。

**两层约束**：

```
外部调用方
  │
  ▼
business/api/__init__.py     ← 唯一合法入口（只做 re-export + 数据转换，不写业务逻辑）
  │
  ▼
business/<domain>/           ← 内部实现（业务逻辑在此）
```

| 层 | 目录 | 允许 | 禁止 |
|----|------|------|------|
| API 门面 | `business/api/` | re-export 透传、数据格式转换、入参校验、路由分发 | **任何业务逻辑**：SQL、LLM 调用、文件解析、复杂计算 |
| 业务域 | `business/<domain>/` | 业务规则、流程编排、DB 操作、LLM 调用 | 直接暴露内部实现给外部调用方 |

**代码示范**：

```python
# ✅ business/api/__init__.py — 只做 re-export
from business.audit.audit_service import submit_audit, record_audit_result

# ✅ business/api/audit_api.py — 有转换需求时，只写转换代码
def submit_audit(node_id: str, batch_id: str, data: dict) -> str:
    """外部格式 → 内部格式转换后透传。"""
    return _submit(node_id, batch_id, json.dumps(data, ensure_ascii=False))
```

```python
# ❌ business/api/ 里写 SQL — 禁止！业务逻辑属于 domain 层
def submit_audit(node_id, batch_id, data):
    conn = sqlite3.connect(...)
    conn.execute("INSERT INTO ...")
```

**调用链**：

```
外部模块 (任意层)
  → from business.api import submit_audit      # ✅ 唯一合法入口
  → business/api/__init__.py (re-export)        #   不写业务，只透传
  → business/audit/audit_service.py (实现)        #   直接操作 DB / LLM
```

**反模式**（禁止）：

```
外部模块 → POST http://127.0.0.1:8000/api/v1/audit-logs  # ❌ 内部走 HTTP
外部模块 → from business.audit import submit_audit        # ❌ 绕过 api 层
business/api/ 里面写 SQL / 调 LLM                         # ❌ 门面层写业务
```

**函数签名约束**：

| 规则 | 示例 |
|------|------|
| 必填参数前置 | `submit_audit(node_id, batch_id, input_snapshot)` |
| 可选参数 keyword-only | `submit_audit("n1", "b1", "{}", trigger_source="MANUAL")` |
| 合理默认值 | `batch_id` 不传自动生成 `uuid4().hex[:12]` |
| 复杂入参用 Pydantic | `AuditLogCreate(node_id="n1", batch_id="b1")` |
| 返回 Python 对象 | `str` / `bool` / `list[dict]` / Pydantic 模型，不返回 HTTP Response |
| 异常用 AppException | 不抛 HTTPException（那是路由层职责） |

**`__init__.py` 导出约束**：外部 import 只写到 `business.api`，不深入内部：

```python
from business.api import submit_audit              # ✅ 唯一合法形式
from business.audit.audit_service import ...        # ❌ 绕过 api 层
```

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
├── ConfigurationError      → HTTP 500
└── ReasonerError           → HTTP 502 (自动降级)
```

### 4.2 各层异常使用规则

| 层 | 抛出 | 捕获 |
|----|------|------|
| gateway | 不抛业务异常（转换 HTTPException） | 捕获所有 AppException → HTTPException |
| orchestrator | WorkflowError | 捕获 capabilities 层的异常 → WorkflowError |
| capabilities | ModelError | 捕获 infrastructure 层异常 → ModelError |
| infrastructure | InfrastructureError | 不捕获上层异常 |
| common | 定义异常类（不抛出也不捕获） | — |

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
| gateway | 请求体缺字段不 400；响应缺字段用 `None` |
| orchestrator | 图节点缺 `hasPrecondition` 就跳过；checkpoint 恢复失败 → 重头执行 |
| capabilities | LLM 提取字段缺就留空；工具调用参数缺就用 schema default |
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

| 模块 | 文档 | 说明 |
|------|------|------|
| gateway | [gateway/GATEWAY.md](gateway/GATEWAY.md) | HTTP API 规范、中间件约束、路由设计 |
| orchestrator | [orchestrator/ORCHESTRATOR.md](orchestrator/ORCHESTRATOR.md) | 图构建/执行约束、状态管理规范 |
| business | [business/BUSINESS.md](business/BUSINESS.md) | 业务域组织规范、MasterAgent 调度规则 |
| capabilities | [capabilities/CAPABILITIES.md](capabilities/CAPABILITIES.md) | 能力层总览、跨子模块约束 |
| capabilities/agents | [capabilities/agents/AGENTS.md](capabilities/agents/AGENTS.md) | Agent 实现约束、ReAct 规范 |
| capabilities/prompts | [capabilities/prompts/PROMPTS.md](capabilities/prompts/PROMPTS.md) | Prompt 管理规范、模板语法 |
| capabilities/graph_reasoner | [capabilities/graph_reasoner/GRAPH_REASONER.md](capabilities/graph_reasoner/GRAPH_REASONER.md) | 图推理引擎约束 |
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
| LangGraph | 0.3 | 编排层统一入口 |
| Pydantic | v2 | 配置与数据校验 |
| Memgraph | Neo4j 兼容 | 图存储，Bolt 协议连接 |
| SQLite | 内嵌 | 本体模型 + 场景 + 提示词元数据存储 |
| Jinja2 | FastAPI 集成 | 服务端模板渲染 |
| structlog | latest | 结构化日志 |

---

## 8. 数据库表总览 🆕

### 8.1 SQLite (ontol.db) — 17 张表

| # | 表 | 用途 |
|---|----|------|
| 1 | `ontol_model` | 本体模型定义（树形结构，10 个种子节点 M0-M7 + ME + MT） |
| 2 | `ontol_model_attr` | 模型属性字段（16 列，attr_is_system 区分系统预设/自定义） |
| 3 | `ontol_model_scene` | 推演场景（scene_is_system 区分系统预设/自定义） |
| 4 | `ontol_scene_prompt` | 场景提示词模板（场景内可建多个） |
| 5 | `ontol_scene_dictionary` | 场景词典词条（边属性 + 字段语义描述） |
| 6 | `ontol_dictionary_type` | 词典词条分类 |
| 7 | `ontol_datasource_type` | 数据源类型 |
| 8 | `ontol_datasource` | 数据源配置（MySQL/PG/Oracle 等） |
| 9 | `ontol_datasource_log` | 数据源同步日志（批次号 + 业务流水号） |
| 10 | `ontol_scene_dictionary_relation` | 场景 ↔ 词典词条关联（多对多） |
| 11 | `ontol_llm_config` | LLM 模型配置（url/key/model） |
| 12 | `ontol_llm_type_config` | LLM 类型与子类型配置 |
| 13 | `ontol_function_type` | 动态函数类型 |
| 14 | `ontol_function` | 动态函数配置（classpath/method/超时/重试） |
| 15 | `ontol_cope_version` | 推演副本（状态 00/01/02/03 + 初始节点 + 置信度） |
| 16 | `ontol_chat_cope_version_relation` | 对话 ↔ 推演副本关联（多对一） |
| 17 | `ontol_char` | 🆕 对话主表（id=chart_id，对话元数据存 DB，消息内容存浏览器 localStorage） |

**运行时自动创建的表**（不在此 DDL 中，由 ontology_routes.py 按需创建）：

| 表 | 用途 |
|----|------|
| `ontol_data_his` | 图数据变更历史（节点 CRUD 自动记录 + 版本递增） |
| `ontol_char_scene_relation` | 对话 ↔ 场景绑定 |
| `ontol_node_scene_relation` | 图节点 ↔ 场景绑定 |

### 8.2 表设计约束规范 🆕

> ⚠️ **核心约束**：所有 SQLite 表（`ontol_*`）在建表时 **必须** 包含以下 9 个通用字段。如果建表语句缺少任一字段，`sqlite_db.py` 启动迁移自动补上。

#### 8.2.1 通用字段定义

| 字段名称 | 数据类型 | 约束条件 | 说明 |
|----------|---------|----------|------|
| `id` | TEXT | PRIMARY KEY, NOT NULL | UUID，由后端 `uuid.uuid4().hex[:16]` 自动生成 |
| `name` | TEXT | NOT NULL, DEFAULT `''` | 名称 |
| `code` | TEXT | NOT NULL | 编码，本表唯一 |
| `create_time` | TEXT | NOT NULL, DEFAULT `(datetime('now'))` | 记录创建时间 |
| `create_user` | TEXT | NOT NULL, DEFAULT `''` | 记录创建人标识 |
| `update_time` | TEXT | NOT NULL, DEFAULT `''` | 记录最后更新时间 |
| `update_user` | TEXT | NOT NULL, DEFAULT `''` | 记录最后更新人标识 |
| `delete_flag` | TEXT/INTEGER | NOT NULL, DEFAULT `'0'` | 逻辑删除标志（0-未删除，1-已删除） |
| `is_system` | TEXT | NOT NULL, DEFAULT `'0'` | `'0'`-自定义，`'1'`-系统预设，不可修改 |

#### 8.2.2 后端 CRUD 行为规范

| 操作 | 字段行为 |
|------|----------|
| **INSERT** | `id` 自动生成 UUID；`create_time` 取当前时间；`create_user` 从请求上下文注入；`delete_flag` 默认 `'0'` |
| **UPDATE** | `update_time` 自动刷新；`update_user` 从请求上下文注入；`id`/`create_time`/`create_user`/`code` 不可更新 |
| **DELETE** | 仅软删除：`UPDATE SET delete_flag = '1'`；**绝不**执行物理 `DELETE FROM` |
| **SELECT** | 所有查询必须追加 `WHERE delete_flag = '0'` |

### 8.3 Memgraph (图数据库)

- **ID 标准**：所有节点和边的 `id` 属性使用 **Snowflake 算法** 生成 **64 位纯数字整数**（`int64`，不转字符串）
- **ID 生成**：由 `SnowflakeGenerator`（`gateway/routes/ontology_routes.py`）生成，先查询图中已有 ID 去重
- **ID 替换**：LLM 随机生成的字符串 ID 在写入前替换为 Snowflake ID，相同随机串映射到相同 Snowflake ID
- **推理机副本节点 ID**：格式 `{原节点ID}-{副本编码}`
- **边属性**：仅支持标量类型（string/bool），不支持嵌套 JSON/Map。标准边属性 9 个：`actionType`/`required`/`validationType`/`ruleId`/`func`/`id`/`msg`/`synonym`/`queryVariant`

---

## 9. 变更历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 3.3.0 | 2026-07-14 | 上传管道重构 — 四步解耦为独立文件 (step1_parse/step2_validate/step3_enrich/step4_import)；新增 Step 3 符号语言填充 & 推理机校验 (7种本体语言前缀识别+边属性填充+结构校验)；新增 `/api/v1/upload/enrich-entities` 端点；`business/api/` 统一 re-export 四个 step 入口；路由层清除 7 个死引用 (parser.py/prompts.py) |
| 3.2.0 | 2026-07-14 | 推理机引擎拆分 — engine.py 四步流水线拆为独立模块：step1_clone/step2_relink/step3_inherit/step4_reason；engine.py 变为薄编排层（191行）；新增 walk_inference_chain 到底层 graph_ops；四步间纯 Python 函数调用串联，不经过路由/HTTP |
| 3.1.0 | 2026-07-14 | 新增 `ontol_char` 对话主表（第 17 张表）；新增 `business/chat/` `business/api/` 模块；重构 `business/audit/` — Pydantic 模型 + submit_audit/record_audit_result 便捷函数；对话 CRUD API；审核记录 API 类型化；**模块间调用规范**（禁止内部 HTTP，必须走 Python import，见 §3.3）
| 3.0.0 | 2026-07-13 | 架构文档案重写 — 基于真实文件清单；新增 reasoning/transformation/reasoning_routes；修正 gateway vs webAPP 模板目录；移除虚构文件；SQLite 表 14→16 张；Git 仓库范围扩大至项目根 |
| 2.4.1 | 2026-07-10 | 图节点/边 Snowflake ID 标准（64 位）；OWL2+SWRL+SHACL 语义规范；本体类型 M1-M7 枚举 |
| 2.4.0 | 2026-07-09 | 新增场景管理 + 提示词（ontol_scene_prompt 表 + CRUD）；宽容执行加固 |
| 2.3.1 | 2026-06-30 | 初始文档 |
