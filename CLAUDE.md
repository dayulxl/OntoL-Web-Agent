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
| 沙盘推演 | http://localhost:8000/sandbox-wargame | ReactFlow 图编辑 + 推理机推演 + 推演副本模式（?id=） |
| 本体语义 | http://localhost:8000/ontology-template | 左树右详情，本体模型/字段管理 |
| 本体建模 | http://localhost:8000/ontology | 知识图谱可视化 + 场景管理 + 节点历史 |
| 文件上传 | http://localhost:8000/upload | 上传 + AI 解析 + 图数据库导入 + 场景关联 |
| 元数据管理 | http://localhost:8000/metadata | 图数据库 & SQLite 统计 |
| 维度管理 | http://localhost:8000/dictionary | 关系类型/实体标签词典 |
| 推理机设置 | http://localhost:8000/reasoner-world | 外部推理引擎配置 |
| 情报展示 | http://localhost:8000/intelligence | Entity 节点详情 |
| 数据管理 | http://localhost:8000/datamanage | 数据源/API/内置接口/日志管理（卡片式） |
| 推理机控制台 | http://localhost:8000/reasoning | 选起点节点、配推理规则、看实时执行日志 |

## 项目结构

```
├── gateway/          # FastAPI 网关 (app.py 入口, routes/, middleware/)
│   └── routes/
│       ├── chat_routes.py           # 对话 SSE API + 动态提示词 (prompt_id)
│       ├── ontology_routes.py       # 图 DB CRUD + 场景管理 + 提示词 CRUD + 文件导入
│       ├── langgraph_routes.py      # LangGraph 工作流 API
│       ├── datamanage_routes.py     # 数据源/动态API/内置代码/日志 管理
│       ├── reasoning_routes.py      # 🆕 图推理机 SSE 流式接口 (触发推理 + 推送日志)
│       └── page_routes.py           # Jinja2 页面渲染 (18 个页面)
├── orchestrator/     # 业务流程编排
├── business/         # 业务逻辑层
│   ├── route_planning/              # 航路规划域
│   ├── strike_decision/             # 打击决策域
│   ├── reasoning/                   # 🆕 图推理机业务域
│   │   ├── engine.py                #   核心：推理引擎主循环 (遍历图 → 匹配规则 → 写回)
│   │   ├── rules.py                 #   核心：规则定义 (纯 Python 类/字典，不走 SWRL)
│   │   └── graph_ops.py             #   核心：底层图操作 (查邻居、改属性、建边)
│   └── transformation/              # 🆕 转换层：本体语言 → Cypher
│       ├── rdfs_converter.py        #   ① RDFS (rdfs: 前缀)
│       ├── owl2_converter.py        #   ② OWL2 DL (owl2: 前缀)
│       ├── swrl_converter.py        #   ③ SWRL (swrl: 前缀)
│       ├── shacl_converter.py       #   ④ SHACL (sh: 前缀)
│       ├── rule_converter.py        #   ⑤ 规则设定 (rule: 前缀，前链/后链)
│       ├── func_converter.py        #   ⑥ 动态函数 (func: 前缀，JSON 调用)
│       └── jsonpath_converter.py    #   ⑦ JSONPath ($. 前缀，RFC 9535)
├── capabilities/     # 能力层 (LLM 调用、工具等)
│   ├── agents/chat_agent.py         # ChatAgent（ReAct + 7工具 + 动态提示词）
│   ├── memory/graph_memory.py       # Memgraph 图记忆（标准 Cypher 兼容，增删属性）
│   └── graph_reasoner/              # 图推理引擎 — 推理机协调者 + 前端服务层
├── common/           # 共享设施 (config/settings.py, utils/logger.py)
├── infrastructure/   # 基础设施
│   ├── db/neo4j.py                  # Memgraph 驱动（memgraph:// → bolt:// 自动转换）
│   ├── db/sqlite_db.py              # SQLite 自动建表+种子
│   └── db/ontol.db                  # 本体模型数据库（10 张表）
├── webAPP/           # 前端资源
│   ├── templates/                   # Jinja2 模板（16 个页面 + 组件）
│   │   ├── pages/prompt_manager.html  # 🆕 场景管理（场景+提示词）
│   │   ├── reasoning_ui.html          # 🆕 推理机控制台（选节点 → 配规则 → 看日志）
│   │   └── components/navbar.html     # 导航栏（12 个链接）
│   ├── static/css/                  # 全局样式
│   └── static/js/
│       └── graph-layout.js           # 有向图布局引擎（source左target右，纯技术函数）
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
  - `ontol_cope_version` — 🆕 推演副本表（状态 00/01/02/03 + 初始节点 + 置信度）
  - `ontol_chat_cope_version_relation` — 🆕 对话-副本关联表（chat_id + cope_version_id）
- **数据主键约定**: 所有表的 `id` 由后端 `uuid.uuid4().hex[:16]` 自动生成，前端表单禁止展示 id 输入框，列表不展示原始 id；`code`/`name` 等仅作业务语义字段
- **表命名规范**: SQLite 中所有本体语义相关的配置/元数据表必须以 `ontol_` 为前缀
- **前端按钮布局规范**: 新增按钮放在内容区顶部，必须有可见按钮不含快捷键；编辑/删除按钮：列表行右侧/卡片右上角
- **HTML 属性值转义**: 动态内容嵌入 HTML 属性时必须用 `escHtml()` 转义 `&` `<` `>` `"`，防止含引号的字符串（如 `actionType: "inference"`）截断 `value="..."`
- **JS 变量命名**: 对话/副本 ID 统一用 `chat_id`（前后端一致），前端模块变量用 `currentChatId`
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
- 左侧 **js-treeview** (justinchmura/js-treeview) 树形导航，从 `ontol_model` + `ontol_model_attr` 表直接加载
- 后端 `page_routes._build_ontology_tree_for_view()` 输出 `[{name, id, typeCode, fieldCount, children, expanded}]` 格式
- 点击树节点名 → 右侧加载模型详情（基本信息 + 预置字段表格 + 自定义字段表格）
- 字段分为「系统预设」（`attr_is_system='1'`，🔒不可删改）和「自定义字段」
- 前端表格禁编辑 + 后端 PUT/DELETE 403 保护
- 工具栏：📂全部展开 / 📁全部折叠 / 🔍搜索过滤
- 静态资源：`webAPP/static/js-treeview.{js,css}`

### 本体建模 (/ontology)
- ReactFlow 图可视化 + 侧边栏节点/关系 CRUD + 边上插入节点
- 工具栏场景管理（卡片式 UI + 弹窗多选，系统预设场景受保护）
- 节点创建/更新/删除 + 关系创建/删除 → 自动写 `ontol_data_his` + 递增图节点 `version` 版本号
- 点击节点侧边栏显示「📜 历史版本」— 点击每条可弹窗查看变更前后对比
- **边属性**：创建关系时自动预填 9 个标准边属性（actionType/required/validationType/ruleId/func/id/msg/synonym/queryVariant），支持动态增删自定义属性
- 点击画布上的边 → 查看/编辑边属性（`PUT /ontology/edges/{edge_id}`），仅显示有值的属性；可切换到「边上插入节点」模式
- 关系类型为自由输入框（非下拉）

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

### 图推理机 (/reasoning) 🆕

自研图推理引擎，直接在 Memgraph 图上执行规则推理，不依赖外部推理机服务。

**核心流程**：选起点节点 → 配推理规则 → 引擎遍历图 → 规则匹配 → 写回结果

```
用户选节点 + 规则 ──► engine.py (主循环)
                         │
                         ├─ traversal:  沿边遍历邻居 (graph_ops.py)
                         ├─ match:      节点属性匹配规则条件 (rules.py)
                         ├─ convert:    规则 DSL → Cypher (transformation/)
                         └─ writeback:  结果写回图节点/边
                              │
                         SSE 推送实时日志 ──► reasoning_ui.html
```

**架构分层**：

| 层 | 模块 | 职责 |
|----|------|------|
| Gateway | `reasoning_routes.py` | 接收 HTTP 请求，参数校验，SSE 推流 |
| UI | `reasoning_ui.html` | 选起点节点、配规则、看实时执行日志 |
| 业务 | `business/reasoning/` | 推理引擎核心，图遍历 + 规则匹配 + 写回 |
| 转换 | `business/transformation/` | 7 种本体语言 → Cypher 查询语句 |
| 基础设施 | `infrastructure/db/neo4j.py` | Memgraph 驱动，Bolt 协议连接池 |

**推理机控制台页面** (`reasoning_ui.html`)：
- 起点节点选择器（按 code/name/ont_type 搜索）
- 规则配置面板（勾选启用的规则、设置推理深度、置信度阈值）
- SSE 实时日志流（节点遍历路径、规则命中/未命中、写回结果）
- 推理结果展示（受影响的节点/边列表）

**转换层** (`business/transformation/`)：将本体语言规则统一转为 Cypher，直接在 Memgraph 执行。支持 7 种本体前缀：

| # | 语言 | 前缀 | 转换器 |
|---|------|------|--------|
| 1 | RDFS | `rdfs:` | `rdfs_converter.py` |
| 2 | OWL2 DL | `owl2:` | `owl2_converter.py` |
| 3 | SWRL | `swrl:` | `swrl_converter.py` |
| 4 | SHACL | `sh:` | `shacl_converter.py` |
| 5 | 规则设定 | `rule:` | `rule_converter.py` |
| 6 | 动态函数 | `func:` | `func_converter.py` |
| 7 | JSONPath | `$.` | `jsonpath_converter.py` |

### 推理机代理
- `POST /api/v1/tools/call` → KG 推理机 (`KG_SERVER_URL`)，支持 `infer_forward`、`validate`、`check_rule`、`expand`
- `POST /api/v1/infer-on-nodes` → KG 推理机 `/infer-on-nodes-id-fc`，NDJSON 响应自动解析为结构化 messages
- **副本节点 ID 规则**：推理机创建副本节点时，节点 ID 必须为 `{原节点ID}-{副本编码}`（如 `node_12345-V1.0`），确保图内全局唯一
- **图节点/边 Snowflake ID**：Memgraph 中所有节点和边的 `id` 使用 **Snowflake 算法** 生成 **64 位纯数字整数**（int64，不转字符串）；导入时 `SnowflakeGenerator` 先查询已有 ID 去重，再将 LLM 随机字符串 ID 替换为纯数字 Snowflake ID，相同随机串映射到相同 Snowflake ID

### 推演副本管理 🆕
- **表**: `ontol_cope_version` — 副本主键 id + 副本名称 name + 状态 cope_version_status(00待处理/01推理中/02推理完成/03已删除) + 初始节点 init_note_id/init_note_name + 置信度 confidence(0.01~1.00，默认0.8) + 描述 description
- **关联表**: `ontol_chat_cope_version_relation` — id + chat_id + cope_version_id（对话↔副本多对一绑定）
- **API**: `GET/POST/PUT/DELETE /api/v1/cope-versions` + `GET /api/v1/cope-versions/{id}`（单条） + `GET /api/v1/cope-versions/{id}/graph`（副本图数据） + `DELETE /api/v1/cope-versions/{id}/nodes`（删除副本节点）
- **对话-副本绑定 API**: `POST /api/v1/chat-cope-versions/bind`（先删旧再绑新） + `GET /api/v1/chat-cope-versions/{chat_id}` + `DELETE /api/v1/chat-cope-versions/{id}`
- **图数据查询逻辑**: status=00 → 查无 cope_version 属性的原始节点；status≠00 → 查 cope_version={id} 的副本节点
- **沙盘推演副本模式**: `?id={cope_id}` 进入推演模式，工具栏显示推演名称+初始节点，置信度输入框同步副本 confidence 值
- **推理结果展示**: NDJSON → 拆分为 messages 数组 → 按 `═══ Step` 分组 → 再按 `【第N步】` 拆卡片，工具栏下方横向排列
- **重置按钮**: 推演模式下显「🔄 重置」，根据 graph_id 查原节点属性覆盖副本节点
- **节点隔离**: 推演模式下创建的节点/关系自动注入 `cope_version={id}` 属性
- **AI 对话绑定**: 新建对话时可选推演副本，未选则自动创建 + 写入关联表

### 本体前缀规范

所有本体语义体系中的编码前缀，用于区分不同作用域的属性和关系类型。

| 序号 | 作用域 | 名称 | 编码前缀 | 格式示例 | 备注 |
|------|--------|------|----------|----------|------|
| 1 | 对象属性 | RDFS 语言 | `rdfs:` | | 也支持 RDFS 核心常量，不写前缀 |
| 2 | 对象属性 | OWL2 DL 语言 | `owl2:` | | OWL2 DL 语言为主 |
| 3 | 对象属性 | SWRL 语言 | `swrl:` | | SWRL 语法 |
| 4 | 对象属性 | SHACL 语言 | `sh:` | | SHACL 语法 |
| 5 | 对象属性 | 规则设定 | `rule:` | `rule:forwardChain` / `rule:backwardChain` | 默认就是前链推理 |
| 6 | 对象属性 | 自定义动态函数 | `func:` | `{"id":"图ID","func":"函数名"}` | 不对接大模型，用 JSON 调用函数实现 |
| 7 | 对象属性/程序属性 | JSONPath | `$.` | `$.node1.node1-1` | 符合 RFC 9535 标准 |
| 8 | 边类型 | 路径标识 | `actionType:` | `actionType: "inference"` | 路由标识：指定执行分支。`inference`=走推理机逻辑判断边属性；其他值=大模型关系，不走推理机 |
| 9 | 边属性 | 自定义动作接口 | 边的 Key-Value | 见下方 | |
| 10 | 图数据操作 | Cypher 查询语言 | `cypher:` | `CYPHER: MATCH (n:Person {name: 'Alice'}) RETURN n` | Memgraph 原生支持 openCypher 标准，用于图数据模式匹配、节点/关系的增删改查 (CRUD) 及图遍历操作 |

**边属性规范 (Memgraph Key-Value)**：边属性仅支持标量类型，不支持嵌套 JSON/Map。标准边属性定义 `STandARD_EDGE_PROPS`（见 `ontology.html`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `actionType` | string | 路由标识（如 `inference` 走推理机） |
| `required` | bool | 阻断控制（`true`/`false`） |
| `validationType` | string | 规则级别：`Strong` 强校验阻断 / `Weak` 弱校验提醒不阻断 |
| `ruleId` | string | 规则本体ID |
| `func` | string | 动态函数编码 |
| `id` | string | 目标本体 |
| `msg` | string | 作用说明 |
| `synonym` | string | 同义词，用于语义匹配 |
| `queryVariant` | string | 错意词/变体词，用于容错查询 |

## 编码规范

### 写代码前必须做的事

1. **完整阅读所有涉及文件** — 不是 grep 关键行，是 Read 完整文件内容
2. **理解关联函数** — 找清所有调用链、全局变量、CSS 类和 DOM ID 的依赖关系
3. **检查冲突** — 写之前确认：
   - 无函数重名（全文件搜索 `function X(` 和 `async function X(`）
   - 无变量重复声明（`const`/`let`/`var` 同名）
   - 无 CSS 类名冲突
   - 无 DOM ID 冲突
   - 无 API 路由冲突

### 写代码后必须做的事

1. **检查括号/大括号平衡** — 用脚本验证 script 块内 `{` `}` 数量相等
2. **检查函数定义次数** — 每个函数在文件中只定义一次
3. **检查全局变量** — 同一作用域 `const`/`let`/`var` 不重复声明

### 发现冲突时的处理

- **必须提醒用户**，说明冲突的具体位置和性质
- **禁止擅自写补偿代码** — 不能静默写额外的修复/桥接代码绕开冲突，用户必须知晓并决定

### 提交前必须做的事

1. **检查 CLAUDE.md 是最新的** — 确认新增/修改的页面功能、API 路由、关键函数、数据规范都已写入文档
2. **更新后再提交** — CLAUDE.md 与代码同步后，才能 `git add -A` + `git commit`
3. **commit message 要体现文档更新** — 如果 CLAUDE.md 被改了，message 里要提

为什么：代码和文档不同步会误导后续开发。CLAUDE.md 是这个项目的唯一事实标准参考。

相关内存：[[update-claude-md-before-commit]] [[warn-on-code-conflict]] [[read-all-code-before-writing]]

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
