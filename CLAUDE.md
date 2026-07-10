# CLAUDE.md

LangChain/LangGraph 集群化智能服务平台 — FastAPI + LangGraph + Memgraph 知识图谱推理。

## 启动服务

```bash
/c/Users/admin/AppData/Local/pypoetry/Cache/virtualenvs/langgraph-cluster-AHI-zXgB-py3.14/Scripts/python.exe -m gateway.app
```

- **Python 环境**：Poetry 虚拟环境 `langgraph-cluster-AHI-zXgB-py3.14`，Python 3.14
- **工作目录**：`d:\langchain`
- **配置文件**：`.env`（通过 `pydantic-settings` 自动加载）
- **不允许**使用 `poetry run`（bash 环境中 `poetry` 不在 PATH），必须使用虚拟环境中的 Python 解释器

### 启动后验证

| 确认项 | 状态 | 说明 |
|--------|------|------|
| Uvicorn 监听 | `http://0.0.0.0:8000` | `reload=True`，自动监听文件变更 |
| 图数据库驱动初始化 | 日志输出 | 失败时降级（ontology API 不可用） |
| SQLite 初始化 | 日志输出 | |
| 模型配置 | 从 `.env` 加载 | DeepSeek 作为默认 LLM (OpenAI 兼容) |

### 访问地址

| 页面 | URL | 说明 |
|------|-----|------|
| 态势总览 | http://localhost:8000/ | Canvas 态势图 + 兵力编成 + 场景管理入口 |
| AI 对话 | http://localhost:8000/chat | 多轮对话，左侧历史列表，支持场景绑定 + 提示词选择 |
| 场景管理 | http://localhost:8000/prompt-manager | 左场景右提示词，场景+提示词 CRUD |
| 沙盘推演 | http://localhost:8000/sandbox-wargame | ReactFlow 图编辑 + 推理机推演 |
| 本体语义 | http://localhost:8000/ontology-template | 左树右详情，本体模型/字段管理 |
| 本体建模 | http://localhost:8000/ontology | 知识图谱可视化 + 场景管理 + 节点历史 |
| 文件上传 | http://localhost:8000/upload | 上传 + AI 解析 + 图数据库导入 + 场景关联 |
| 元数据管理 | http://localhost:8000/metadata | 图数据库 & SQLite 统计 |
| 维度管理 | http://localhost:8000/dictionary | 关系类型/实体标签词典 |
| 推理机设置 | http://localhost:8000/reasoner-world | 外部推理引擎配置 |
| 情报展示 | http://localhost:8000/intelligence | Entity 节点详情 |
| 数据管理 | http://localhost:8000/datamanage | 数据源/API/内置接口/日志管理（卡片式） |

## 项目结构

```
├── gateway/          # FastAPI 网关 (app.py 入口, routes/, middleware/)
│   └── routes/
│       ├── chat_routes.py           # 对话 SSE API + 动态提示词 (prompt_id)
│       ├── ontology_routes.py       # 图 DB CRUD + 场景管理 + 提示词 CRUD + 文件导入
│       ├── langgraph_routes.py      # LangGraph 工作流 API
│       ├── datamanage_routes.py     # 数据源/动态API/内置代码/日志 管理
│       └── page_routes.py           # Jinja2 页面渲染 (17 个页面)
├── orchestrator/     # 业务流程编排
├── business/         # 业务逻辑层
├── capabilities/     # 能力层 (LLM 调用、工具等)
│   ├── agents/chat_agent.py         # ChatAgent（ReAct + 7工具 + 动态提示词）
│   └── memory/graph_memory.py       # Memgraph 图记忆（标准 Cypher 兼容，增删属性）
├── common/           # 共享设施 (config/settings.py, utils/logger.py)
├── infrastructure/   # 基础设施
│   ├── db/neo4j.py                  # Memgraph 驱动（memgraph:// → bolt:// 自动转换）
│   ├── db/sqlite_db.py              # SQLite 自动建表+种子
│   └── db/ontol.db                  # 本体模型数据库（10 张表）
├── webAPP/           # 前端资源
│   ├── templates/                   # Jinja2 模板（15 个页面 + 组件）
│   │   ├── pages/prompt_manager.html  # 🆕 场景管理（场景+提示词）
│   │   └── components/navbar.html     # 导航栏（12 个链接）
│   ├── static/css/                  # 全局样式
├── tests/            # 测试 (pytest, asyncio)
├── deployments/      # Docker & K8s 部署配置
└── scripts/          # 运维脚本
```

## 关键技术栈

- **Web**: FastAPI + Uvicorn + Jinja2
- **AI 编排**: LangChain 0.3 + LangGraph 0.3
- **LLM**: Anthropic/OpenAI/DeepSeek（通过 models.yaml 配置）
- **数据库**: Memgraph/Neo4j (知识图谱) + SQLite (本体模型 ontol.db，含 12 张表)
- **SQLite 表结构**:
  - `ontol_model` — 本体模型定义（树形结构，ontol_parent_id 父子关系）
  - `ontol_model_attr` — 模型属性字段（`attr_is_system='1'`=系统预设不可删改，28 个有效字段）
  - `ontol_model_scene` — 推演场景（`scene_is_system='1'`=系统预设）
  - `ontol_scene_prompt` — 🆕 场景提示词（场景内可建多个提示词，AI 对话可选择）
  - `ontol_char_scene_relation` — 对话↔场景绑定
  - `ontol_node_scene_relation` — 图节点↔场景关系
  - `ontol_data_his` — 图数据变更历史（节点 CRUD 自动记录 + 版本号递增）
  - `ontol_datasource` — 数据源配置（MySQL/PG/Oracle 等）
  - `ontol_datasource_type` — 数据源类型（`is_system='1'`=系统预设，不可删改）
- **数据主键约定**: 所有表的 `id` 由后端 `uuid.uuid4().hex[:16]` 自动生成，前端表单禁止展示 id 输入框，列表不展示原始 id；`code`/`name` 等仅作业务语义字段
- **表命名规范**: SQLite 中所有本体语义相关的配置/元数据表必须以 `ontol_` 为前缀
- **前端按钮布局规范**: 新增按钮放在内容区顶部，必须有可见按钮不含快捷键；编辑/删除按钮：列表行右侧/卡片右上角
- **配置**: Pydantic Settings (.env)
- **日志**: structlog

## 关键功能

### AI 对话 (/chat)
- 左侧历史对话列表，localStorage 持久化（UUID 键值存储）
- 新建对话时弹出场景多选弹窗 + 提示词选择下拉，绑定关系写入 `ontol_char_scene_relation`
- 选中提示词后 `POST /api/v1/chat` 携带 `prompt_id`，服务端从 `ontol_scene_prompt` 表加载内容
- LangChain ReAct Agent 用选中的提示词替代默认 SYSTEM_PROMPT 驱动推理（工具集不变）
- 切换历史对话时加载对应场景名称，删除对话时自动清理场景绑定
- SSE 流式推理管道，7 步进度指示器 + 工具调用卡片
- 右侧推理机调用面板

### 场景管理 (/prompt-manager)
- 左场景列表（复用 `/api/v1/scenes` CRUD）+ 右提示词卡片列表
- 提示词 CRUD：`GET/POST /api/v1/scenes/{id}/prompts` + `GET/PUT/DELETE /api/v1/prompts/{id}`
- 系统场景（`scene_is_system='1'`）受保护不可删
- 创建提示词时填写名称、描述、提示词内容（textarea）

### 沙盘推演 (/sandbox-wargame)
- ReactFlow 图编辑 + 左侧实体树
- 上下文切换：场景（多选）/ AI 对话历史（单选），互斥
- 推演参数：`code`（实体编码）、`name`、`relation`、`cope_version`、`depth`、`direction`、`confidence_threshold`、`scenes`/`chat_history`
- 置信度滑块 + toggle 开关，全局阈值控制推理命中概率

### 本体语义 (/ontology-template)
- 左树（递归 CTE）右详情布局
- 字段分为「系统预设」（`attr_is_system='1'`，🔒不可删改）和「自定义字段」
- 前端表格禁编辑 + 后端 PUT/DELETE 403 保护

### 本体建模 (/ontology)
- ReactFlow 图可视化 + 侧边栏节点/关系 CRUD + 边上插入节点
- 工具栏场景管理（卡片式 UI + 弹窗多选，系统预设场景受保护）
- 节点创建/更新/删除 + 关系创建/删除 → 自动写 `ontol_data_his` + 递增图节点 `version` 版本号
- 点击节点侧边栏显示「📜 历史版本」— 点击每条可弹窗查看变更前后对比

### 文件上传 & 导入 (/upload)
- LLM 解析文本 → 本体类型识别 + 字段填充
- **导入前校验** (`/api/v1/upload/validate-entities`)：检测 ont_type 模板匹配
  - 无匹配模板 → ⚠️ 红色警告，提示先创建本体模型
  - 有匹配模板 → 📋 列出缺失字段（沿 M_ROOT 继承链计算），确认后自动补全默认值
- 补全规则：M_ROOT 字段全局共用，各类型沿 ontol_parent_id 链向上继承
- 解析完成后弹出场景多选弹窗（默认勾选系统预设场景）
- 导入实体后写入 `ontol_node_scene_relation` 节点-场景绑定

### 数据管理 (/datamanage)
- 左侧标签切换：数据源 / 动态API / 内置接口 / 接口日志
- 卡片式列表（响应式 grid） + 新增卡片入口
- 点击卡片弹出居中编辑弹窗

### 推理机代理
- `POST /api/v1/tools/call` → KG 推理机 (`KG_SERVER_URL`)
- 默认工具名 `infer_forward`，也可调用 `validate`, `check_rule`, `expand`
- **副本节点 ID 规则**：推理机创建副本节点时，节点 ID 必须为 `{原节点ID}-{副本编码}`（如 `node_12345-V1.0`），确保图内全局唯一
- **图节点/边 Snowflake ID**：Memgraph 中所有节点和边的 `id` 使用 **Snowflake 算法** 生成 **64 位纯数字整数**（int64，不转字符串）；导入时 `SnowflakeGenerator` 先查询已有 ID 去重，再将 LLM 随机字符串 ID 替换为纯数字 Snowflake ID，相同随机串映射到相同 Snowflake ID

## 设计原则

### 宽容执行 (Tolerant Execution v1.0)

**所有设计必须是灵活的，不可因缺少字段或值为空而中断执行。**

| 场景 | 处理方式 |
|------|----------|
| 有这个字段 | 用它 |
| 没有这个字段 | 跳过，继续执行 |
| 有这个值 | 处理它 |
| 没有这个值 | 用默认值兜底，继续执行 |

**适用范围**：
- LLM 实体解析 — 文本中提取到字段就填充，提取不到就留空或填默认值，不报错
- 推理机节点执行 — 节点有 `hasPrecondition` 就校验，没有就跳过；`hasCost`/`hasEffect`/`hasDuration` 同理
- 图数据库查询 — 属性存在就返回，不存在就 `None`，不抛异常
- 前端渲染 — 字段有值就展示，没值就隐藏或显示占位符
- 导入/导出 — 源数据有字段就映射，没有就跳过，不阻断整个流程

**反模式**（禁止）：
- `obj["field"]` 直接取值 → 改 `obj.get("field")` 或 `getattr(obj, "field", default)`
- 字段缺失抛异常导致整个流程中断 → 降级处理 + 日志 warning
- 前端 `undefined` 导致白屏 → 可选链 `?.` + 兜底值

## 测试

```bash
/c/Users/admin/AppData/Local/pypoetry/Cache/virtualenvs/langgraph-cluster-AHI-zXgB-py3.14/Scripts/python.exe -m pytest tests/ -v
```
