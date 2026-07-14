# CLAUDE.md

LangChain/LangGraph 集群化智能服务平台 — FastAPI + LangGraph + Memgraph 知识图谱推理。

## 启动服务

```bash
/c/Users/84578/AppData/Local/pypoetry/Cache/virtualenvs/langgraph-cluster-9zMcaQV9-py3.11/Scripts/python.exe -m gateway.app
```

- **Python 环境**：Poetry 虚拟环境 `langgraph-cluster-9zMcaQV9-py3.11`，Python 3.11
- **工作目录**：`d:\OntoL-Web-Agent`
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
| 首页 | http://localhost:8000/ | 数据质量分析仪表板 — 全维度质量评分 + FrappeCharts 图表 |
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
| LLM 配置 | http://localhost:8000/llm-config | LLM 模型配置 CRUD（类型+配置），为 /chat 和 /upload 提供统一模型接口 |
| 审核记录 | http://localhost:8000/audit-log | ontol_audit_log 审核流水查询，统计卡片 + 筛选 + 详情弹窗 + 分页 |

## 项目结构

```
├── gateway/                # FastAPI 网关 (app.py 入口)
│   ├── routes/             #   路由层
│   │   ├── chat_routes.py          # 对话 SSE API + 动态提示词 (prompt_id)
│   │   ├── ontology_routes.py      # 图 DB CRUD + 场景/提示词 CRUD + 文件导入
│   │   ├── langgraph_routes.py     # LangGraph 工作流 API
│   │   ├── datamanage_routes.py    # 数据源/动态API/内置代码/日志 管理
│   │   ├── reasoning_routes.py     # 🆕 图推理机 SSE 流式接口
│   │   ├── quality_routes.py       # 🆕 数据质量分析 API
│   │   └── page_routes.py          # Jinja2 页面渲染 (14 个活跃页面)
│   ├── middleware/          #   中间件 (auth / logging / rate_limiter)
│   └── templates/          #   [遗留] Jinja2 模板 (14 个页面，未使用，待清理)
├── orchestrator/           # 业务流程编排
├── business/               # 业务逻辑层 (路由只调用此处, 不能在路由写业务)
│   ├── api/                         # 🆕 对外接口层 — 唯一合法入口，不写业务，只做 re-export + 转换 + 分发
│   │   └── __init__.py             #   facade：from business.api import submit_audit（按需扩展子模块）
│   ├── tool/                        # 🆕 通用工具集 (纯工具, 无业务代码, 跨域复用)
│   │   └── snowflake.py             #   SnowflakeGenerator — 64位雪花ID生成；generate_snowflake_ids(entities) 纯算法，不查库
│   │   ├── excel_handler.py           #   通用 Excel 读写 (样式/冻结/筛选) — 无业务逻辑
│   ├── ontology/                    # 🆕 本体类型加载器 (共享基础设施)
│   │   └── __init__.py             #   load_ontology_types + get_inherited_fields
│   ├── reasoning/                  # 图推理机业务域
│   │   ├── engine.py               #   编排器：管理共享状态 + 按序调用四步
│   │   ├── step1_clone.py          #   Step 1: 复制推理关联对象（种子+祖先+下游→副本空间）
│   │   ├── step2_relink.py         #   Step 2: 副本节点间重建边关系
│   │   ├── step3_inherit.py        #   Step 3: owl2:subClassOf 属性继承（顶层基底→子类覆盖）
│   │   ├── step4_reason.py         #   Step 4: 逐节点推理（precondition→effect→边属性叙述）
│   │   ├── rules.py                #   核心：规则定义/校验/效果路由/置信度传播（纯 Python 类/字典）
│   │   └── graph_ops.py            #   核心：底层图操作 (查邻居、克隆、建边、属性合并、遍历)
│   ├── transformation/             # 转换层：本体语言 → Cypher
│   │   ├── rdfs_converter.py       #   ① RDFS (rdfs: 前缀)
│   │   ├── owl2_converter.py       #   ② OWL2 DL (owl2: 前缀)
│   │   ├── swrl_converter.py       #   ③ SWRL (swrl: 前缀)
│   │   ├── shacl_converter.py      #   ④ SHACL (sh: 前缀)
│   │   ├── rule_converter.py       #   ⑤ 规则设定 (rule: 前缀)
│   │   ├── func_converter.py       #   ⑥ 动态函数 (func: 前缀)
│   │   └── jsonpath_converter.py   #   ⑦ JSONPath ($. 前缀, RFC 9535)
│   ├── chat/                       # 🆕 对话元数据管理 (ontol_char 表 CRUD)
│   │   └── chat_service.py           #   对话列表/创建/更新/删除 — DB 查列表，消息仍存浏览器
│   ├── upload/                      # 🆕 文件上传 & AI 实体解析业务域
│   │   ├── auto_import/               #   全自动导入四步管线
│   │   │   ├── __init__.py            #     统一下载入口：run_parse_pipeline / validate_entities / enrich_entities / import_to_graph
│   │   │   ├── step1_parse.py         #     Step 1: AI 本体解析 — run_parse_pipeline(filename,model)
│   │   │   ├── step2_validate.py      #     Step 2: 模板校验 — validate_entities(entities)
│   │   │   ├── step3_enrich.py        #     Step 3: 符号语言填充 & 推理机校验 — enrich_entities(entities,relationships)
│   │   │   └── step4_import.py        #     Step 4: 导入图数据库 — import_to_graph(entities,rels,scene_ids,filename)
│   │   ├── prompts.py               #   LLM 提示词构建 (分类/字段提取/完整本体)
│   │   ├── parser.py                #   文件文本提取 + JSON 解析 + 两阶段解析管线
│   │   ├── validation.py            #   模板匹配 + 继承链缺失字段计算
│   │   ├── import_service.py        #   雪花ID映射→创建节点→创建关系→场景绑定
│   │   ├── excel_service.py           #   Excel 批量导入导出 (新增/修改/删除字段)
│   ├── quality/                      # 🆕 数据质量分析业务域
│   │   └── analyzer.py            #   五维度质量分析 (完整性/一致性/唯一性/时效性/覆盖率)
│   ├── audit/                       # 🆕 审核记录业务域
│   │   ├── __init__.py             #   出口：submit_audit / record_audit_result / query_by_node ...
│   │   └── audit_service.py        #   ontol_audit_log 表 CRUD + Pydantic 模型 (AuditLogCreate/Result/Update)
│   ├── route_planning/             # 航路规划域 (graph / state / nodes / agent)
│   └── strike_decision/            # 打击决策域 (graph / state / nodes / agent)
├── capabilities/           # 能力层
│   ├── agents/chat_agent.py        # ChatAgent (ReAct + 7工具 + 动态提示词)
│   ├── memory/graph_memory.py      # Memgraph 图记忆 (Cypher 兼容)
│   ├── graph_reasoner/             # 图推理引擎
│   │   ├── core/                   #   推理核心
│   │   ├── actions/                #   推理动作
│   │   ├── translators/            #   本体查询翻译器
│   │   └── versioning/             #   版本管理
│   ├── tools/                      # 工具集 (knowledge_graph / registry)
│   ├── models/                     # 模型配置
│   │   ├── factory.py               #   ModelFactory — 多类型/多提供商创建
│   │   ├── resolver.py              #   LLM 共享解析器 (DB 配置 → factory)
│   │   ├── interfaces.py            #   ModelInterface 抽象协议
│   │   └── models.yaml              #   模型注册表 (7 种类型)
│   ├── prompts/                    # 提示词 (agents / chains)
│   └── chains/                     # 链式调用
├── common/                 # 共享设施
│   ├── config/settings.py          # Pydantic Settings (.env)
│   ├── contracts/state_schema.py   # 状态基类契约
│   ├── exceptions/base.py          # 统一异常定义
│   └── utils/logger.py             # structlog 结构化日志
├── infrastructure/         # 基础设施
│   └── db/
│       ├── neo4j.py                # Memgraph 驱动 (memgraph://→bolt://)
│       ├── sqlite_db.py            # SQLite 自动建表+种子
│       ├── base_repo.py            # PostgreSQL/asyncpg 通用 Repository (CRUD 基类)
│       ├── ontology_repo.py        # 本体模型树形查询 + 属性查询
│       └── ontol.db                # 本体模型数据库 (14 张表)
├── webAPP/                 # 前端资源 (运行时加载)
│   ├── templates/                  # Jinja2 模板 (活跃)
│   │   ├── pages/                  #   页面模板 (14 个)
│   │   │   ├── reasoning_ui.html   #     🆕 推理机控制台
│   │   │   ├── quality_dashboard.html  #  🆕 首页数据质量仪表板
│   │   │   ├── audit_log.html      #     🆕 审核记录
│   │   │   ├── prompt_manager.html #     场景管理
│   │   │   ├── chat.html           #     AI 对话
│   │   │   ├── sandbox_wargame.html#     沙盘推演
│   │   │   └── ...                 #     (共 13 页)
│   │   └── components/navbar.html  #   导航栏组件
│   ├── tool/                        # 🆕 前端工具框架 (每个工具独立目录)
│   │   ├── treeview/                 #   js-treeview 树形导航 (js+css)
│   │   ├── alpine/                   #   Alpine.js 轻量响应式框架
│   │   ├── picocss/                  #   Pico.css 轻量 CSS 框架
│   │   └── FrappeCharts/             #   Frappe Charts 图表库
│   └── static/
│       └── js/graph-layout.js      # 有向图布局引擎
├── tests/                  # 测试 (pytest, asyncio)
├── deployments/            # Docker & K8s 部署配置
└── scripts/                # 运维脚本
```

> **注意**：`gateway/templates/` 为遗留目录（14 个旧模板），`page_routes.py` 实际加载 `webAPP/templates/`（14 个活跃模板）。两个目录的页面不完全重叠，部分旧页面（如 workflow、data_ingestion）仅存在于遗留目录，可能已不可用。

## 关键技术栈

- **Web**: FastAPI + Uvicorn + Jinja2
- **AI 编排**: LangChain 0.3 + LangGraph 0.3
- **LLM**: Anthropic/OpenAI/DeepSeek（通过 models.yaml 配置）
- **数据库**: Memgraph/Neo4j (知识图谱) + SQLite (本体模型 ontol.db，含 21 张表)
- **SQLite 表结构**:
  - `ontol_model` — 本体模型定义（17 列，树形结构 ontol_parent_id，`ontol_type`='01'本体/'02'关系，`ontol_model_is_system`='1'系统预设）
  - `ontol_model_attr` — 模型属性字段（23 列，`attr_is_system`='1'=系统预设🔒/='0'=自定义，同一 code 可属于不同 model）
  - `ontol_model_scene` — 推演场景（`scene_is_system='1'`=系统预设）
  - `ontol_scene_prompt` — 场景提示词（场景内可建多个提示词，AI 对话可选择）
  - `ontol_char` — 🆕 对话主表（id=chart_id，对话元数据存 DB，消息内容存浏览器 localStorage）
  - `ontol_char_scene_relation` — 对话↔场景绑定（chart_id）
  - `ontol_node_scene_relation` — 图节点↔场景关系
  - `ontol_data_his` — 图数据变更历史（节点 CRUD 自动记录 + 版本号递增）
  - `ontol_datasource` — 数据源配置（MySQL/PG/Oracle 等）
  - `ontol_datasource_type` — 数据源类型（`is_system='1'`=系统预设，不可删改）
  - `ontol_datasource_log` — 数据源接口日志
  - `ontol_cope_version` — 推演副本表（状态 00/01/02/03 + 初始节点 + 置信度）
  - `ontol_chat_cope_version_relation` — 对话-副本关联表（chat_id + cope_version_id）
  - `ontol_scene_dictionary` — 场景字典（维度管理，字典类型+内容）
  - `ontol_scene_dictionary_relation` — 场景-字典多对多关联
  - `ontol_dictionary_type` — 字典类型（关系类型/实体标签词典）
  - `ontol_function` — 动态函数（classpath + method + timeout/retry）
  - `ontol_function_type` — 函数类型分类
  - `ontol_llm_type_config` — LLM 类型配置（provider 协议：OpenAI/Anthropic/OpenAI-compatible 等）
  - `ontol_llm_config` — LLM 模型实例配置（url/key/model，外键关联 ontol_llm_type_config）
  - `ontol_audit_log` — 🆕 审核记录流水（16 字段，含 batch_id/audit_status/llm_score/suggested_data/input_snapshot/llm_raw_output 等）
- **数据主键约定**: 所有表的 `id` 由后端 `uuid.uuid4().hex[:16]` 自动生成，前端表单禁止展示 id 输入框，列表不展示原始 id；`code`/`name` 等仅作业务语义字段
- **表命名规范**: SQLite 中所有本体语义相关的配置/元数据表必须以 `ontol_` 为前缀
- **前端按钮布局规范**: 新增按钮放在内容区顶部，必须有可见按钮不含快捷键；编辑/删除按钮：列表行右侧/卡片右上角
- **前端工具框架规范**: 所有前端工具框架（JS 库/CSS 主题/第三方组件）必须放在 `webAPP/tool/<工具名>/` 下（如 `webAPP/tool/treeview/`），通过 `app.mount("/static/tool", ...)` 统一挂载，模板中 `url_for('static-tool', path='工具名/文件名')` 引用。挂载顺序 `/static/tool` 必须在 `/static` 之前
- **HTML 属性值转义**: 动态内容嵌入 HTML 属性时必须用 `escHtml()` 转义 `&` `<` `>` `"`，防止含引号的字符串（如 `actionType: "inference"`）截断 `value="..."`
- **JS 变量命名**: 对话/副本 ID 统一用 `chat_id`（前后端一致），前端模块变量用 `currentChatId`
- **配置**: Pydantic Settings (.env)
- **日志**: structlog

## 关键功能

### AI 对话 (/chat)
- **数据分工**：对话列表（id/名称/时间）存 SQLite `ontol_char` 表，消息内容存浏览器 localStorage
- 左侧历史对话列表 — 从 `GET /api/v1/chats`（DB）查询，按 `update_time` 降序；消息条数从 localStorage 补充
- 新建对话时 `POST /api/v1/chats` 写入 DB + 弹出场景多选弹窗 + 提示词选择下拉，绑定关系写入 `ontol_char_scene_relation`
- 对话标题变化时 `PUT /api/v1/chats/{id}` 同步更新 DB
- 删除对话时 DB 软删除 + localStorage 清除 + 场景绑定清除，三端联动
- 首次渲染时懒迁移：localStorage 中有但 DB 中没有的历史对话自动同步到 DB
- 选中提示词后 `POST /api/v1/chat` 携带 `prompt_id`，服务端从 `ontol_scene_prompt` 表加载内容
- LangChain ReAct Agent 用选中的提示词替代默认 SYSTEM_PROMPT 驱动推理（工具集不变）
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
- 推演参数：`code`（实体编码）、`name`、`relation`、`copy_version`、`depth`、`direction`、`confidence_threshold`、`scenes`/`chat_history`
- 置信度滑块 + toggle 开关，全局阈值控制推理命中概率

### 本体语义 (/ontology-template)
- 左侧 **js-treeview** (justinchmura/js-treeview) 树形导航，从 `ontol_model` + `ontol_model_attr` 表直接加载
- 后端 `page_routes._build_model_tree_for_view()` 通用函数输出 js-treeview 格式，两个页面传不同 table/attr_mapping
- 点击树节点名 → 右侧加载模型详情（基本信息 + 预置字段表格 + 自定义字段表格）
- 字段分为「系统预设」（`attr_is_system='1'`，🔒不可删改）和「自定义字段」
- 前端表格禁编辑 + 后端 PUT/DELETE 403 保护
- 工具栏：📂全部展开 / 📁全部折叠 / 🔍搜索过滤
- 静态资源：`webAPP/tool/treeview/` 下，通过 `/static/tool/treeview/` 访问（app.py 单独挂载）

### 本体建模 (/ontology)
- ReactFlow 图可视化 + 侧边栏节点/关系 CRUD + 边上插入节点
- 工具栏场景管理（卡片式 UI + 弹窗多选，系统预设场景受保护）
- 节点创建/更新/删除 + 关系创建/删除 → 自动写 `ontol_data_his` + 递增图节点 `version` 版本号
- 点击节点侧边栏显示「📜 历史版本」— 点击每条可弹窗查看变更前后对比
- **边属性**：创建关系时自动预填 9 个标准边属性（actionType/required/validationType/ruleId/func/id/msg/synonym/queryVariant），支持动态增删自定义属性
- 点击画布上的边 → 查看/编辑边属性（`PUT /ontology/edges/{edge_id}`），仅显示有值的属性；可切换到「边上插入节点」模式
- 关系类型为自由输入框（非下拉）

### 文件上传 & 导入 (/upload)

- 支持 **多格式文件解析**：`.txt` / `.docx`（python-docx 提取段落+表格）/ `.doc`（antiword CLI 提取）
- **全自动导入四步管线**（每步独立 Python 文件，通过 `business/api/` 统一入口）：

```
Step 1: AI 本体解析       auto_import/step1_parse.py    → 文本提取 + 分块 → 两阶段 LLM (分类→字段提取)
Step 2: 模板校验 & 字段补全  auto_import/step2_validate.py → ontol_model 模板匹配 + 继承链缺失字段计算
Step 3: 符号语言填充 & 校验  auto_import/step3_enrich.py   → 7种前缀识别 + 边属性填充 + 推理机结构校验
Step 4: 导入图数据库       auto_import/step4_import.py   → 雪花ID映射 → MERGE节点 → MERGE关系 → 场景绑定
```

- **Step 3 符号语言支持**：扫描实体属性/关系谓词中的 7 种前缀（`rdfs:`/`owl2:`/`swrl:`/`sh:`/`rule:`/`func:`/`$.`），自动填充标准边属性（actionType/required/validationType/ruleId/msg），并对 SWRL 语法/func JSON/SHACL 约束做结构校验
- **API 端点**：`POST /api/v1/upload/parse` | `/validate-entities` | `/enrich-entities` | `/import-entities`
- 解析返回 `chunks_success`/`chunks_failed`（前端日志展示），`chunks_total` 文件分块数
- 补全规则：M_ROOT 字段全局共用，各类型沿 ontol_parent_id 链向上继承
- 解析完成后弹出场景多选弹窗（默认勾选系统预设场景）
- 导入实体后写入 `ontol_node_scene_relation` 节点-场景绑定

### 数据质量首页 (/) 🆕

首页数据质量仪表板，综合评估系统数据健康度。纯原生 JS + FrappeCharts，无框架依赖。

**核心模块**：
- `business/quality/analyzer.py` — 五维度质量分析引擎（~400 行）
- `gateway/routes/quality_routes.py` — `GET /api/v1/quality/report` 返回结构化报告
- `webAPP/templates/pages/quality_dashboard.html` — 首页仪表板 UI（纯原生 JS）

**五大评估维度**：

| 维度 | 分析内容 | 数据源 |
|------|----------|--------|
| 完整性 | 模型属性覆盖率、必填字段默认值缺失 | ontol_model + ontol_model_attr |
| 一致性 | 外键孤儿引用（场景↔提示词，属性↔模型） | 多表 JOIN 检查 |
| 唯一性 | 重复名称/编码检测 | 各表 GROUP BY HAVING |
| 时效性 | 各表最近更新时间，超 30 天未更新比例 | 各表 update_time/cteate_time |
| 覆盖率 | 子系统数据填充度（模型/属性/场景/提示词/LLM/数据源） | 全表扫描计数 |

**仪表板 UI**：
- SVG 环形评分动画 + 五维度 KPI 卡片（点击跳转）
- FrappeCharts 图表：柱状图（维度评分）、饼图（模型类型分布）、折线图（变更趋势）
- 问题清单（error/warning/info 三级着色）
- 可折叠详情表格：模型属性概览、场景提示词覆盖、缺失属性模型、最近变更
- 🔄 刷新按钮 + 立即渲染（先占位再异步加载，避免白屏）

### LLM 配置 (/llm-config) 🆕

统一提供 LLM 模型接口，供 `/chat` 和 `/upload` 两个页面共用。

**架构**：
```
/llm-config (UI) → ontol_llm_config 表 ← resolve_llm(config_id)
                     │                        ↑
                     │ capabilities/models/resolver.py
                     │   ├─ 查 DB ontol_llm_config → create_llm_from_config()
                     │   └─ DB 未命中 → models.yaml 兜底
                     │
              /chat ─┼─ /upload   (两个页面只调用 resolve_llm，不重复实现)
```

**核心模块**：
- `capabilities/models/resolver.py` — 共享解析器，唯一入口 `resolve_llm(config_id)`
- `capabilities/models/factory.py::create_llm_from_config()` — 从外部配置创建 LLM 实例（独立于 models.yaml）
- `gateway/routes/chat_routes.py` — `from capabilities.models.resolver import resolve_llm`
- `gateway/routes/ontology_routes.py` — /upload/parse 共用同一个 `resolve_llm`

**API**：
- `GET/POST/PUT/DELETE /api/v1/llm-type-configs` — LLM 类型配置（provider 协议）
- `GET/POST/PUT/DELETE /api/v1/llm-configs` — LLM 模型实例配置（url/key/model）

**⚠️ 命名注意事项**：`BaseRepository` 中的方法名 `list` 会覆盖 Python 内置 `list` 类型，导致 `list[str]` 类型标注报错 `TypeError: 'function' object is not subscriptable`。该类中已使用 `list_rows` 替代 `list`。新增方法时避免与内置函数重名。

### 数据管理 (/datamanage)
- 左侧标签切换：数据源 / 动态API / 内置接口 / 接口日志
- 卡片式列表（响应式 grid） + 新增卡片入口
- 点击卡片弹出居中编辑弹窗

### 图推理机 (/reasoning) 🆕

自研图推理引擎，直接在 Memgraph 图上执行规则推理，不依赖外部推理机服务。

**核心流程**：选起点节点 → 配推理规则 → 四步流水线 → SSE 实时推送日志

```
engine.py (编排器 — 管理共享状态 cm / ancestors / reasoning_log)
    │
    ├─ Step 1 (step1_clone.py)   克隆种子+OWL2祖先链+inference下游链 → 副本空间
    │     ├─ climb_subclass_chain 沿 owl2:subClassOf 上溯祖先
    │     ├─ walk_inference_chain 沿 actionType=inference 下探下游 (DFS防环)
    │     └─ clone_node ×N        注入 copy_version，填充 cm 映射表
    │
    ├─ Step 2 (step2_relink.py)  遍历 cm，原边 → 副本边 (同类型+同属性)
    │     └─ get_relationships + clone_edge
    │
    ├─ Step 3 (step3_inherit.py) owl2:subClassOf 语义：祖先属性为基底，逐层被子类覆盖
    │     └─ merge_inherited_props + update_node_props (有变化才写回)
    │
    └─ Step 4 (step4_reason.py) 逐节点推理叙述
          ├─ ① precondition  前置条件校验 (支持 "key = val" / "key > N" / "hasProperty:key")
          ├─ ② effect        效果分类 (按7种前缀路由: swrl/sh/owl2/rule/func/$.)
          ├─ ③ cost/duration/priority  消耗指标叙述
          └─ ④ 沿 inference 边读取 9 个标准边属性 → Strong 阻断判定
               │
          SSE 推送实时日志 ──► webAPP/templates/pages/reasoning_ui.html
```

**四步之间通过 Python 函数参数传递共享状态**（cm 克隆映射表、ancestors 祖先链），引擎不包含推理逻辑，只做编排：

```python
# engine.py run() — 纯函数调用串联
async for event in step1_clone(seed_node_id, copy_version, self.cm, self.ancestors):
    yield event                              # async generator (流式)
edge_count = await step2_relink(self.cm)     # async function (返回值)
merged_count = await step3_inherit(self.cm, self.ancestors)
async for event in step4_reason(seed_node_id, self.cm, self.ancestors, threshold):
    yield event
```

**架构分层**：

| 层 | 模块 | 职责 |
|----|------|------|
| Gateway | `reasoning_routes.py` | 接收 HTTP 请求，参数校验，SSE 推流 |
| UI | `webAPP/templates/pages/reasoning_ui.html` | 选起点节点、配规则、看实时执行日志 |
| 业务 | `business/reasoning/` | 四步流水线：克隆→建边→继承→推理，纯 Python 函数串联 |
| 转换 | `business/transformation/` | 7 种本体语言 → Cypher 查询语句 |
| 基础设施 | `infrastructure/db/neo4j.py` | Memgraph 驱动，Bolt 协议连接池 |
| 图操作 | `graph_ops.py` | 原子 DB 操作：查/克隆/建边/属性合并/遍历/Cypher 裸执行 |

**推理机控制台页面** (`webAPP/templates/pages/reasoning_ui.html`)：
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
- **图节点/边 Snowflake ID**：Memgraph 中所有节点和边的 `id` 使用 **Snowflake 算法** 生成 **64 位纯数字整数**（int64，不转字符串）；导入时 `generate_snowflake_ids(entities)` 将 LLM 随机字符串 ID 直接替换为纯数字 Snowflake ID（算法天生唯一，无需查库去重），相同随机串映射到相同 Snowflake ID。只处理实体 properties.id，不碰关系的 start_node_id/end_node_id

### 推演副本管理 🆕
- **表**: `ontol_cope_version` — 副本主键 id + 副本名称 name + 状态 cope_version_status(00待处理/01推理中/02推理完成/03已删除) + 初始节点 init_note_id/init_note_name + 置信度 confidence(0.01~1.00，默认0.8) + 描述 description
- **关联表**: `ontol_chat_cope_version_relation` — id + chat_id + cope_version_id（对话↔副本多对一绑定）
- **API**: `GET/POST/PUT/DELETE /api/v1/cope-versions` + `GET /api/v1/cope-versions/{id}`（单条） + `GET /api/v1/cope-versions/{id}/graph`（副本图数据） + `DELETE /api/v1/cope-versions/{id}/nodes`（删除副本节点）
- **对话-副本绑定 API**: `POST /api/v1/chat-cope-versions/bind`（先删旧再绑新） + `GET /api/v1/chat-cope-versions/{chat_id}` + `DELETE /api/v1/chat-cope-versions/{id}`
- **图数据查询逻辑**: status=00 → 查无 copy_version 属性的原始节点；status≠00 → 查 copy_version={id} 的副本节点
- **沙盘推演副本模式**: `?id={cope_id}` 进入推演模式，工具栏显示推演名称+初始节点，置信度输入框同步副本 confidence 值
- **推理结果展示**: NDJSON → 拆分为 messages 数组 → 按 `═══ Step` 分组 → 再按 `【第N步】` 拆卡片，工具栏下方横向排列
- **重置按钮**: 推演模式下显「🔄 重置」，根据 graph_id 查原节点属性覆盖副本节点
- **节点隔离**: 推演模式下创建的节点/关系自动注入 `copy_version={id}` 属性
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

### 架构分层（强制）

**路由器（`gateway/routes/`）只做路由，禁止写业务代码。**

| 层 | 目录 | 允许 | 禁止 |
|----|------|------|------|
| 路由层 | `gateway/routes/` | HTTP 请求解析、参数校验（Pydantic）、调用业务层、格式化 HTTP 响应 | **任何业务逻辑**：数据库查询、Cypher/LLM 调用、文件解析、数据转换、复杂计算、业务规则判断 |
| 业务层 | `business/<domain>/` | 业务规则、流程编排、领域逻辑、推理引擎 | 直接操作 HTTP 请求/响应对象 |
| 工具层 | `business/tool/` | 纯工具函数：算法、编码器、生成器、格式转换。无状态、无业务判断、可跨域引用 | 写 SQL、调用 LLM、做业务判断 |
| 能力层 | `capabilities/` | 可复用的技术能力：Agent、Memory、工具集、模型、提示词、链 | 业务规则判断 |
| 基础设施 | `infrastructure/` | 数据库驱动、连接池、底层 Repository | 业务逻辑 |

**路由函数应该是"薄的"**，理想不超过 15 行：

```python
@router.get("/items/{item_id}")
async def get_item(item_id: str, repo=Depends(get_repo)):
    result = await business_service.get_item(item_id, repo)  # 调用业务层
    return {"code": 200, "data": result}                      # 格式化响应
```

**反模式**（禁止在路由中）：
- 路由函数超过 30 行 → 拆分到 `business/`
- 路由中直接写 Cypher/Memgraph 查询 → 移到 `business/` 或 `capabilities/memory/`
- 路由中调用 LLM/构建 prompt → 移到 `business/` 或 `capabilities/`
- 路由中写文件解析/数据转换逻辑 → 移到 `business/`
- 路由中定义工具函数（`_xxx()`）→ 移到对应业务模块

**迁移纪律**：发现违反分层规范的代码，发现一处迁移一处，禁止新增违规，禁止累积。

**现状**：`ontology_routes.py` 已将上传解析/校验/符号填充/导入四步全部迁移至 `business/upload/auto_import/stepN_*.py`，路由层只做薄壳调用（每函数 ≤15 行）。清除了 `parser.py`/`prompts.py` 的 7 个死引用。图操作/场景管理/字典管理/LLM 配置等仍有迁移空间。

### 业务模块间调用规范（强制）

**内部模块之间禁止走 HTTP，必须走 Python 函数调用。** 所有外部调用必须经过 `business/api/` 中转，禁止绕过。

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
| API 门面 | `business/api/` | re-export 透传、数据格式转换、入参校验、路由分发 | **任何业务逻辑**：数据库查询、LLM 调用、文件解析、复杂计算 |
| 业务域 | `business/<domain>/` | 业务规则、流程编排、DB 操作、LLM 调用 | 直接暴露内部实现给外部调用方 |

**`business/api/` 代码规范**：

```python
# ✅ 正确 — business/api/__init__.py：只做 re-export
from business.audit.audit_service import submit_audit, record_audit_result

# ✅ 正确 — business/api/audit_api.py：有转换需求时，只写转换代码
from business.audit.audit_service import submit_audit as _submit

def submit_audit(node_id: str, batch_id: str, data: dict) -> str:
    """外部格式 → 内部格式转换后透传。"""
    snapshot = json.dumps(data, ensure_ascii=False)
    return _submit(node_id, batch_id, snapshot)
```

```python
# ❌ 禁止 — business/api/ 里写 SQL
def submit_audit(node_id, batch_id, data):
    conn = sqlite3.connect(...)  # 不行！这是业务逻辑
    conn.execute("INSERT INTO ...")
```

**调用方视角**：

```python
# ✅ 正确 — 外部调用只走 business.api
from business.api import submit_audit, record_audit_result, query_by_node

log_id = submit_audit("node_123", batch_id="B001", input_snapshot=json.dumps(data))
record_audit_result(log_id, audit_status="PASS", llm_score=0.95)
history = query_by_node("node_123")
```

```python
# ❌ 禁止 — 绕过 api 层直接调 domain
from business.audit import submit_audit

# ❌ 禁止 — 内部模块间走 HTTP
import httpx
r = await httpx.post("http://127.0.0.1:8000/api/v1/audit-logs", json={...})
```

**`__init__.py` 导出约定**：外部 import 只写到 `business.api`，不深入内部：

```python
from business.api import submit_audit              # ✅ 唯一合法形式
from business.audit.audit_service import ...        # ❌ 绕过 api 层
```

**函数签名约束**：

| 规则 | 说明 |
|------|------|
| **必填参数前置** | `(node_id, batch_id, ...)` 核心参数位置参数，可选参数 keyword-only |
| **合理默认值** | 调用方只需传最少参数即可工作（如 `batch_id` 不传自动生成） |
| **Pydantic 模型可选** | 复杂入参提供 Pydantic 模型（如 `AuditLogCreate`），简单参数直接用原语 |
| **返回 Python 对象** | 返回 `str`/`bool`/`list[dict]`/Pydantic 模型，不返回 HTTP Response |
| **异常抛 AppException** | 不抛 HTTPException（那是路由层的职责） |

### 显式校验，禁止静默兜底

**缺少必要参数时，必须明确报错，禁止自动生成默认值掩盖问题。**

| 场景 | ✅ 正确做法 | ❌ 禁止 |
|------|------------|---------|
| 必填参数为空 | 校验 → 返回明确错误信息 | 自动生成 UUID/随机值兜底 |
| 配置项缺失 | 抛异常，说明缺少什么 | 用硬编码默认值悄悄填充 |

**为什么**：兜底值会掩盖上游调用方的 bug。比如前端忘了传 `copy_version`，服务端悄悄生成一个 UUID，用户永远不知道推理结果写到了哪个副本，排查困难。

### 时间戳规范（跨页面、跨实体）

**所有数据修改操作，`create_time` 由系统接管，前端不可修改。**

| 操作 | `create_time` | `update_time` |
|------|:--:|:--:|
| 创建（节点/边） | 系统自动写入当前时间 | 系统自动写入当前时间 |
| 更新（节点/边） | 前端传来也 **pop 掉**，不更新数据库 | 强制系统当前时间，不接受前端传值 |
| 克隆（推理副本） | 节点继承原始 / 边新建写入 | 节点继承原始 / 边新建写入 |

**实现位置**：在 `capabilities/memory/graph_memory.py` 的 `create_node`、`update_node`、`create_edge`、`update_edge` 统一处理，路由层和前端不做时间戳逻辑。

**为什么**：创建时间是不可变事实，更新时间反映最后一次真实写入——两者都不能信任前端传值。

### 数据库命名规范（强制）

**所有表名和列名必须使用 `snake_case`（小写下划线），禁止 `camelCase`（驼峰式）。**

> ⚠️ 新增字段必须遵守此规范。发现驼峰 → 立即修正，不得提交。

| ✅ 正确 | ❌ 错误 |
|---------|---------|
| `create_time` | `createTime` |
| `is_composed_of` | `isComposedOf` |
| `query_variant` | `queryVariant` |
| `cope_version_status` | `copeVersionStatus` |

详细规范见 [docs/naming-convention.md](docs/naming-convention.md)。

### 图数据库时间戳规范（强制）

**Memgraph 中所有节点和边的 `create_time` 和 `update_time` 属性，必须使用 Unix 时间戳（int64）。**

| ✅ 正确 | ❌ 错误 |
|---------|---------|
| `n.create_time = 1699887600` | `n.create_time = "2026-07-14 12:00:00"` |

- **类型**：整数 int64，秒级（10位），UTC
- **写入时机**：节点/边创建时系统自动写入；更新时自动刷新
- **与 SQLite 的区别**：SQLite 的 `create_time` 是字符串 `"2026-07-14 12:00:00"`，图数据库用整数时间戳

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

**图节点/边的动态属性读取必须宽容，不可因属性缺失而中断执行。**

> 适用范围仅限于图的动态属性（Memgraph 节点/边的 Key-Value 属性），不适用于函数参数。

| 场景 | 处理方式 |
|------|----------|
| 有这个字段 | 用它 |
| 没有这个字段 | 跳过，继续执行 |
| 有这个值 | 处理它 |
| 没有这个值 | 跳过，继续执行 |

**适用示例**：
- 推理机读节点属性 — `props.get("precondition")` 有则校验，没有则跳过整个校验块
- 图数据库查询 — 属性存在就返回，不存在就 `None`
- 前端渲染图节点详情 — 字段有值就展示，没值就隐藏
- LLM 实体解析 — 文本中提取到字段就填充，提取不到就留空
- 导入/导出 — 源数据有字段就映射，没有就跳过

**反模式**（禁止）：
- `obj["field"]` 直接取值 → 改 `obj.get("field")` 或 `getattr(obj, "field", default)`
- 属性缺失抛异常导致整个流程中断 → 降级处理 + 日志 warning
- 前端 `undefined` 导致白屏 → 可选链 `?.` + 兜底值

## 测试

```bash
/c/Users/84578/AppData/Local/pypoetry/Cache/virtualenvs/langgraph-cluster-9zMcaQV9-py3.11/Scripts/python.exe -m pytest tests/ -v
```
