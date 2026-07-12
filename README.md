# LangGraph Cluster

面向集群部署的 **Python + LangChain/LangGraph** 智能知识图谱推理平台。

## 架构总览

```
        ┌─────────────────────────────────┐
        │     浏览器 / API 客户端           │
        └──────────────┬──────────────────┘
                       │
        ┌──────────────▼──────────────────┐
        │  API 网关层 (gateway/)           │
        │  FastAPI + Jinja2 + SSE Stream   │
        └──────┬───────────────┬──────────┘
               │               │
    ┌──────────▼──────┐  ┌─────▼───────────┐
    │ Chat Agent      │  │ Upload Pipeline  │
    │ (ReAct 推理管道) │  │ (本体解析→Neo4j) │
    └──┬──┬──┬───┬────┘  └─────────────────┘
       │  │  │   │
       ▼  ▼  ▼   ▼
    ┌──────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
    │Neo4j │ │SQLite  │ │DeepSeek  │ │KG Reasoner│
    │图数据库│ │本体模型 │ │ LLM API  │ │(外部推理机)│
    └──────┘ └────────┘ └──────────┘ └──────────┘
```

## 快速开始

### 1. 环境准备

```bash
# 安装 Poetry
pip install poetry

# 安装依赖
poetry install

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入实际值（LLM API Key、Neo4j 连接信息等）
```

### 2. 启动服务

```bash
poetry run python -m gateway.app
```

服务启动后访问:
- 态势总览: `http://localhost:8000/`
- AI 对话: `http://localhost:8000/chat`
- 文件上传 & 本体解析: `http://localhost:8000/upload`
- 本体模型管理: `http://localhost:8000/ontology`
- API 文档: `http://localhost:8000/docs`

### 3. Docker 部署

```bash
bash scripts/build.sh
docker run -p 8000:8000 --env-file .env langgraph:latest
```

### 4. Kubernetes 部署

```bash
kubectl apply -f deployments/k8s/deployment.yaml
kubectl apply -f deployments/k8s/service.yaml
kubectl apply -f deployments/k8s/hpa.yaml
```

## 项目结构

```
project-root/
├── gateway/                  # API 网关层
│   ├── app.py                # FastAPI 应用入口（lifespan: Neo4j + SQLite）
│   ├── routes/               # 路由定义
│   │   ├── chat_routes.py    # 多步推理 Agent 对话（SSE 流式）
│   │   ├── langgraph_routes.py # LangGraph 工作流执行
│   │   ├── ontology_routes.py  # Neo4j CRUD + 文件解析导入 + 本体模型
│   │   └── page_routes.py    # Jinja2 页面渲染
│   ├── templates/pages/      # 前端页面
│   │   ├── chat.html         # AI 对话页（管道步骤指示器 + 工具调用卡片 + 副本选择）
│   │   ├── sandbox_wargame.html # 沙盘推演（ReactFlow + 推演副本 + 有向图布局 + 推理机调用）
│   │   ├── upload.html       # 文件上传 & 本体解析导入
│   │   └── index.html        # 态势总览（Neo4j 态势图）
│   ├── static/               # 静态资源
│   │   └── js/
│   │       └── graph-layout.js # 有向图布局引擎（source左target右）
│   └── middleware/            # 中间件（鉴权、限流、日志）
├── capabilities/             # LangChain 能力层
│   ├── agents/
│   │   ├── chat_agent.py     # ReAct Agent（7工具 6步管道）
│   │   └── base.py           # Agent 基类
│   ├── chains/               # LCEL Chain
│   ├── tools/                # 工具注册中心 + 知识图谱工具同步
│   │   ├── registry.py       # ToolRegistry（MCP 兼容）
│   │   └── knowledge_graph.py # 外部 KG 工具动态注册
│   ├── memory/
│   │   └── graph_memory.py   # Neo4j 图记忆（CRUD / Schema / 遍历）
│   ├── graph_reasoner/       # 🆕 图推理引擎 — 推理机协调者
│   └── models/
│       ├── factory.py        # 模型工厂（7种类型 × 4提供商）
│       ├── models.yaml       # 模型定义配置
│       └── interfaces.py     # 模型接口
├── orchestrator/             # LangGraph 编排层
│   ├── graphs/               # 业务图定义
│   ├── state/                # 状态管理
│   ├── router/               # 动态路由
│   └── engine/               # 执行引擎
├── infrastructure/           # 基础设施层
│   ├── db/
│   │   ├── neo4j.py          # Neo4j 驱动管理
│   │   ├── sqlite_db.py      # SQLite 本体模型数据库
│   │   ├── ontology_repo.py  # 本体模型 Repository
│   │   ├── base_repo.py      # 通用 CRUD Repository
│   │   └── postgres.py       # Postgres 连接池（可选）
│   ├── cache/                # Redis
│   ├── queue/                # 消息队列 (Celery)
│   └── storage/              # 对象存储 (S3)
├── common/                   # 共享层
│   ├── config/settings.py    # Pydantic Settings（.env 加载）
│   ├── models/               # 数据模型
│   ├── exceptions/           # 异常定义
│   └── utils/                # 工具（日志、指标、追踪）
├── tests/                    # 单元测试 & 集成测试
├── scripts/                  # 运维脚本
├── deployments/              # 部署配置
│   ├── k8s/                  # Kubernetes YAML
│   └── docker/               # Dockerfile
├── pyproject.toml            # 依赖管理
└── .env.example              # 环境变量示例
```

## 核心特性

### 多步推理对话管道 (Chat Agent)

`http://localhost:8000/chat` 收到用户消息后，Agent 严格按以下管道执行：

| 步骤 | 说明 | 工具 |
|------|------|------|
| 1. 意图解析 | 拆解用户目标为明确的实体/关系/本体查询 | LLM 分析 |
| 2. 知识检索 | 搜索 Neo4j 图谱 + SQLite 本体模型 | `search_knowledge_graph`, `search_ontology_models`, `get_ontology_tree` |
| 3. 推理校验 | 调用外部推理机验证规则 | `call_reasoner`, `list_reasoner_tools` |
| 4. 图遍历 | 推理机不可达时，在 Neo4j 遍历最多 4 层关系 | `traverse_graph`, `get_model_detail` |
| 5. 步骤生成 | 动态拆分执行步骤，每步骤含验收标准 | LLM 生成 |
| 6. 自校验 | 最多 3 次重试验收，未通过标记风险 | LLM 自检 |
| 7. 方案输出 | 结构化输出：目标理解 → 知识依据 → 执行步骤 → 风险 | LLM 汇总 |

前端实时显示管道步骤进度条、可展开的工具调用卡片和流式文本。

### 本体类型识别 & 文件导入

上传文件后，LLM 自动将内容按 9 种本体类型分类：

| 本体类型 | Neo4j 标签 | 说明 |
|----------|-----------|------|
| M_ENTITY | Entity | 物理/逻辑对象（装备、平台、设施） |
| M_BEHAVIOR | Behavior | 动作/操作（任务、行为） |
| M_RULE | Rule | 约束/推理规则 |
| M_SCENE | Scene | 时空上下文（区域、海域） |
| M_AGENT | Agent | 决策智能体（指挥官、AI） |
| M_EXCEPTION | Exception | 异常处理/补偿机制 |
| M_QUALITY | Quality | 数据质量约束 |
| M_EVENT | Event | 状态变化事件 |
| M_TEMPLATE | Template | 可复用模板 |

每个实体按类型填充对应属性字段（id、name、code、desc 等），导入 Neo4j 时自动打上类型标签。

### 模型配置

支持 7 种模型类型 × 4 提供商（Anthropic、OpenAI、自定义 OpenAI 兼容、llama.cpp）：

- **LLM**: Claude Opus/Sonnet/Haiku, GPT-4o/o1/o3, DeepSeek V4 Pro/Flash, Qwen, Llama
- **Embedding**: text-embedding-3, Voyage, BGE, GTE-Qwen, Nomic
- **Reranker**: BGE, Cohere
- **TTS/STT**: OpenAI TTS-1, Whisper
- **Vision/Image**: Claude Vision, GPT-4o, DALL-E

通过 `capabilities/models/models.yaml` 配置，环境变量注入 API Key。

### 沙盘推演 & 推演副本 🆕

`http://localhost:8000/sandbox-wargame` 提供基于 ReactFlow 的图编辑 + 推演能力：

| 功能 | 说明 |
|------|------|
| 图编辑 | 节点/关系 CRUD，ReactFlow 拖拽交互 |
| 有向图布局 | source(上游)放左边，target(下游)放右边，BFS 递归排列 |
| 推演副本模式 | URL `?id={cope_id}` 进入，图数据按 `cope_version` 隔离 |
| 调用推理机 | 推演模式下点击「推演」→ `POST /tools/call {infer_on_nodes_id}` → 状态自动更新 |
| 重置 | 根据 `graph_id` 用原节点数据覆盖副本节点 |
| 置信度 | 页面滑块控制，推演时传入推理机，联动副本表 `confidence` 字段 |

**副本状态机**: `00 待处理` → `01 推理中` → `02 推理完成` / `03 已删除`

**图数据查询**: status=00 → 查无 `cope_version` 属性的原始节点；status≠00 → 查 `cope_version={id}` 的副本节点

## API 端点

### 知识图谱 (Neo4j) — `/api/v1/ontology`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ontology/schema` | 图谱 Schema（标签、关系类型、节点/边计数） |
| GET | `/ontology/nodes` | 节点列表（支持 label、keyword、limit 过滤） |
| GET | `/ontology/nodes/{id}` | 节点详情（含邻接关系） |
| POST | `/ontology/nodes` | 创建节点 |
| PUT | `/ontology/nodes/{id}` | 更新节点属性 |
| DELETE | `/ontology/nodes/{id}` | 删除节点及关系 |
| POST | `/ontology/edges` | 创建关系 |
| DELETE | `/ontology/edges/{id}` | 删除关系 |
| GET | `/ontology/search` | 关键词搜索节点 |

### 本体模型 (SQLite) — `/api/v1/ontology-models`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ontology-models` | 模型树（含属性字段） |
| GET | `/ontology-models/stats` | 模型/属性统计 |
| GET | `/ontology-models/search` | 关键词搜索 |
| GET | `/ontology-models/{id}` | 单个模型详情 |
| POST | `/ontology-models` | 创建模型 |
| PUT | `/ontology-models/{id}` | 更新模型 |
| DELETE | `/ontology-models/{id}` | 软删除模型 |
| GET | `/ontology-models/{id}/attrs` | 模型属性列表 |
| POST | `/ontology-models/{id}/attrs` | 创建属性 |
| PUT | `/ontology-models/{id}/attrs/{attr_id}` | 更新属性 |
| DELETE | `/ontology-models/{id}/attrs/{attr_id}` | 删除属性 |

### 文件上传 & 解析导入 — `/api/v1/upload`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/upload/history` | 上传历史 |
| POST | `/upload` | 上传文件 (≤50MB) |
| GET | `/upload/preview/{filename}` | 预览/下载文件 |
| DELETE | `/upload/{filename}` | 删除文件 |
| **POST** | **`/upload/parse`** | **LLM 解析文件 → 本体类型实体 + 关系** |
| **POST** | **`/upload/import-entities`** | **导入分类后的实体到 Neo4j** |
| POST | `/upload/import-triples` | 兼容旧三元组导入 |

### AI 对话 — `/api/v1/chat`

| 方法 | 路径 | 说明 |
|------|------|------|
| **POST** | **`/chat`** | **SSE 流式对话（多步推理管道 + 工具调用）** |

### 推演副本管理 🆕 — `/api/v1/cope-versions`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/cope-versions` | 查询所有有效副本 |
| POST | `/cope-versions` | 新增副本 |
| PUT | `/cope-versions/{id}` | 更新副本（名称/状态/置信度等） |
| DELETE | `/cope-versions/{id}` | 软删除副本 |
| GET | `/cope-versions/{id}/graph` | 获取副本图数据（节点+关系，status决定查询条件） |
| DELETE | `/cope-versions/{id}/nodes` | 删除副本对应的 Memgraph 节点 |

### 对话-副本绑定 🆕 — `/api/v1/chat-cope-versions`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat-cope-versions/bind` | 绑定对话到副本（先删旧再插新） |
| GET | `/chat-cope-versions/{chat_id}` | 查询对话绑定的副本（JOIN 副本名+状态） |
| DELETE | `/chat-cope-versions/{id}` | 软删除绑定 |

### LangGraph 工作流 — `/api/v1`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/run` | 同步执行工作流 |
| POST | `/stream` | SSE 流式执行工作流 |
| GET | `/runs/{run_id}/status` | 查询运行状态 |
| POST | `/runs/{run_id}/cancel` | 取消运行 |
| GET | `/health` | 存活检查 |
| GET | `/ready` | 就绪检查 |

## 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `NEO4J_URI` | Neo4j 连接地址 | `bolt+ssc://xxx.databases.neo4j.io` |
| `NEO4J_USER` | Neo4j 用户名 | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j 密码 | （AuraDB 密码） |
| `ANTHROPIC_API_KEY` | Anthropic API Key | `sk-ant-...` |
| `OPENAI_API_KEY` | OpenAI API Key | `sk-...` |
| `CUSTOM_LLM_BASE_URL` | 自定义 LLM 端点 | `https://api.deepseek.com/v1` |
| `CUSTOM_LLM_API_KEY` | 自定义 LLM Key | DeepSeek API Key |
| `DEFAULT_MODEL` | 默认 LLM 模型 | `deepseek-v4-pro` |
| `KG_SERVER_URL` | 外部推理机地址 | `http://localhost:8085` |
| `POSTGRES_URI` | Postgres 连接（可选） | `postgresql://...` |
| `REDIS_URI` | Redis 连接 | `redis://localhost:6379/0` |
| `CELERY_BROKER_URL` | Celery 消息队列 | `redis://localhost:6379/1` |
| `DEBUG` | 调试模式（开启 /docs） | `true` 或 `false` |
| `LOG_LEVEL` | 日志级别 | `INFO` |

## 运行测试

```bash
poetry run pytest
```

## 技术栈

| 组件 | 技术选型 |
|------|---------|
| Web 框架 | FastAPI + Uvicorn |
| AI 编排 | LangGraph (ReAct Agent) |
| AI 能力 | LangChain |
| 图数据库 | Memgraph/Neo4j (Bolt 协议) |
| 本体模型存储 | SQLite (ontol.db，包含 ontol_cope_version + ontol_chat_cope_version_relation 等表) |
| 状态存储 | Postgres / SQLite (checkpoint) |
| 缓存/通信 | Redis |
| 消息队列 | Celery + Redis |
| 对象存储 | S3 兼容 (MinIO/OSS) |
| LLM 提供商 | DeepSeek / Anthropic / OpenAI / llama.cpp |
| 可观测性 | structlog + Prometheus + OpenTelemetry + LangSmith |
| 容器编排 | Kubernetes + HPA |
