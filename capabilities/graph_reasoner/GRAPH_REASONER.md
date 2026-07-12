# GRAPH_REASONER.md — 图推理引擎模块约束

> **定位**: 推理机协调者。为页面和智能体提供图推理服务。推理机本身在**另一个项目**，本模块负责协调：翻译规则 → 管理快照 → 调用外部推理机 → 收集结果 → 计算置信度。Python 这边只做简单操作，底层算法不在此模块。

**目录**: [架构分层](#1-架构分层) | [文件清单](#2-文件清单) | [核心接口](#3-核心接口) | [数据库规范](#4-数据库规范) | [编码规范](#5-编码规范) | [异常处理](#6-异常处理) | [配置与安全](#7-配置与安全) | [变更历史](#8-变更历史)

---

## 1. 架构分层

### 1.1 一句话总结

**graph_reasoner 是推理机协调者** — 嵌套了智能体（ChatAgent），为前端页面和对话提供图推理服务。推理机在另一个项目，本模块通过 API 调用它，自己只做字符串翻译、简单 DB 读写、结果组装。

### 1.2 五层架构中的位置

```
gateway/ ──► orchestrator/ ──► business/ ──► capabilities/
                                                  │
                                        graph_reasoner/  ← 推理机协调者
                                        (页面 + 智能体 + DB查询)
                                                  │
                                    ┌─────────────┼─────────────┐
                                    ▼                           ▼
                            infrastructure/db/          推理机（另一个项目）
                            (Memgraph / SQLite)         (复杂算法)
```

### 1.3 职责边界

| 本模块做什么 | 本模块不做什么 |
|-------------|---------------|
| 推理流程协调 — 翻译→快照→调用→收集→置信度 | 推理算法实现 — 推理机（另一个项目）做 |
| 前端页面数据服务 — 返回图数据和推理结果 | 图遍历算法 — 推理机做 |
| 智能体对话 — ChatAgent 调用图查询/推理 | 推理计算 — 推理机做 |
| 语义标签 → Cypher 字符串翻译（纯字符串操作） | OWL2/SWRL 语义推理 — 推理机做 |
| cope_version 版本标记管理（简单 DB 读写） | 图快照物理复制 |
| 调用外部推理机 API | 推理机实现 |
| func: 调用路由（查表分发，不含业务逻辑） | 函数实现逻辑 |
| 边属性字段校验（非空/格式检查） | 语义校验规则 |
| 置信度汇总（加权平均，简单数学） | 概率推理 |

### 1.4 依赖约束

**MUST — 硬性约束**:

| 规则 | 说明 |
|------|------|
| **MUST 向下依赖** | 只能 import `common/` 和 `infrastructure/` |
| **MUST NOT 反向 Import** | 绝对禁止 import `business/`、`orchestrator/`、`gateway/` |
| **MUST NOT 同层耦合** | 不与 `capabilities/agents/`、`capabilities/chains/` 等同层模块直接 import；通过 `common/` 的抽象接口通信 |
| **MUST NOT 跨层跳过** | 不直接访问 `gateway/`，业务层调用必须经过 `business/` 中转 |

```
capabilities/graph_reasoner/
  ├── 可依赖 → common/            (AppException, settings, structlog, utils)
  ├── 可依赖 → infrastructure/    (db/neo4j, db/sqlite_db)
  └── 不可依赖 → business/, orchestrator/, gateway/
```

---

## 2. 文件清单

```
capabilities/graph_reasoner/
├── __init__.py               # 公共 API 导出
├── GRAPH_REASONER.md         # 本文档
│
├── core/                     # 推理流程协调
│   ├── __init__.py
│   ├── engine.py             # InferenceEngine — 智能体调用入口
│   ├── scheduler.py          # Scheduler — 规则排序
│   └── confidence.py         # ConfidenceCalculator — 置信度加权平均
│
├── translators/              # 语义标签 → Cypher 字符串翻译
│   ├── __init__.py
│   ├── base.py               # ICypherTranslator — 翻译器抽象接口
│   ├── owl2.py               # Owl2Translator — OWL2 → Cypher
│   └── swrl.py               # SwrlTranslator — SWRL → Cypher
│
├── versioning/               # 版本标记管理
│   ├── __init__.py
│   └── manager.py            # VersionControlService — cope_version CRUD
│
└── actions/                  # 动作路由与字段校验
    ├── __init__.py
    ├── router.py             # ActionRouter — func: 查表分发
    └── validator.py          # EdgeValidator — 边属性字段检查
```

---

## 3. 核心接口

### 3.1 InferenceEngine — 智能体调用入口

```python
class InferenceEngine:
    """
    图推理协调入口。由智能体（ChatAgent）调用。

    推理机在另一个项目，本类只做协调:
      1. 把规则翻译成 Cypher 字符串（translators）
      2. 给图打上 cope_version 标记（versioning）
      3. 按优先级排一下规则顺序（scheduler）
      4. 调用外部推理机 API（另一个项目）
      5. 把结果算个加权平均分（confidence）
      6. 返回 InferenceResult

    不做的事:
      - 推理算法 → 推理机做
      - 图遍历 → 推理机做
      - 复杂计算 → 推理机做
    """

    def __init__(self, driver):
        """
        Args:
            driver: Memgraph AsyncDriver（从 infrastructure/db/neo4j.py 获取）。
        """
        ...

    async def execute(self, context: InferenceContext) -> InferenceResult:
        """
        执行推理流程。

        Args:
            context: InferenceContext Pydantic 模型（不可用裸 dict）。

        Returns:
            InferenceResult Pydantic 模型（不可用裸 dict）。
        """
        ...
```

### 3.2 ICypherTranslator — 翻译器抽象接口

```python
class ICypherTranslator(ABC):
    """语义标签 → Cypher 字符串翻译器。纯字符串操作，无 I/O。"""

    @property
    @abstractmethod
    def source_syntax(self) -> str:
        """返回源语法标识: "owl2" | "swrl"."""
        ...

    @abstractmethod
    def translate(self, source_syntax: str) -> str:
        """
        翻译为 Cypher 字符串。

        Raises:
            TranslationError: 翻译失败。
        """
        ...
```

### 3.3 VersionControlService — 版本标记管理

```python
class VersionControlService:
    """
    cope_version 版本标记管理。

    轻量操作：只写标记节点，不复制图数据。
    生成规则：cope_{timestamp}_{uuid8}
    """

    def __init__(self, driver): ...

    async def create_snapshot(self) -> str:
        """生成 cope_version，写入 CopeVersion 标记节点。返回版本号。"""
        ...

    async def cleanup(self, cope_version: str) -> None:
        """删除指定版本的标记节点。"""
        ...
```

### 3.4 ActionRouter — 动作路由

```python
class ActionRouter:
    """
    func: 调用路由。查表分发，不含业务逻辑。

    func: 调用格式: {"id": "节点ID", "func": "函数名", ...params}
    """

    def register(self, func_name: str, handler: Callable) -> None:
        """注册 func: 处理函数。"""
        ...

    async def dispatch(self, func_name: str, payload: FuncPayload) -> FuncResult:
        """
        查表 → 调用 → 返回。未注册的 func 跳过 + warning（宽容执行）。
        """
        ...
```

### 3.5 EdgeValidator — 边属性校验

```python
class EdgeValidator:
    """
    边属性字段检查。

    只做非空/格式检查，不做语义校验:
      - validationType = "Strong": 必填字段为空 → 阻断
      - validationType = "Weak":   缺字段 → 仅 warning，放行
      - 无 validationType 字段:    默认 Weak（宽容执行）
    """

    def validate(self, edge_props: EdgeProps) -> ValidationResult:
        """返回 {passed, level, message, issues}。"""
        ...
```

---

## 4. 数据库规范

### 4.1 Memgraph（图数据库）

| 规范 | 要求 |
|------|------|
| **节点/边 ID** | Snowflake 64 位纯数字整数（int64），纪元 2020-01-01 |
| **副本节点 ID** | `{原节点ID}-{副本编码}`（如 `node_abc-V1.0`），全局唯一 |
| **边属性** | key-value 标量类型，不支持嵌套 JSON/Map |
| **查询语言** | openCypher（Memgraph 原生支持） |
| **驱动** | `infrastructure/db/neo4j.py` — 唯一入口，不自行创建连接 |

### 4.2 SQLite（本体模型元数据）

若 graph_reasoner 需要读/写 `ontol_*` 表：

| 规范 | 要求 |
|------|------|
| **ID** | 后端 `uuid.uuid4().hex[:16]` 生成，前端不可传入 |
| **CRUD** | Insert: id + create_time 自动生成；Update: 刷新 update_time/update_user；Delete: 仅软删除 `delete_flag='1'` |
| **查询** | 必须追加 `WHERE delete_flag = '0'` |
| **表名前缀** | 必须以 `ontol_` 为前缀 |
| **通用字段** | id, create_time, create_user, update_time, update_user, delete_flag, is_system |

---

## 5. 编码规范

### 5.1 语言与编码

- **Python 3.14** — 强制版本
- **UTF-8 无 BOM** — 所有文本文件（.py, .md, .txt 等）
- **类型提示** — 强制使用。层间通信使用 TypedDict 或 Pydantic 模型，**禁止传递裸 dict**
- **命名** — PEP 8 snake_case，环境变量 UPPER_SNAKE_CASE
- **HTML 属性值必须转义** — 动态内容嵌入 HTML 属性时，必须用 `escHtml()` 转义 `&` `<` `>` `"`，否则含引号的字符串会截断属性值

### 5.2 函数单一职责

每个函数只做一件事，区分两种类型：

| 类型 | 职责 | 约束 |
|------|------|------|
| **技术函数** | 纯数据转换，无副作用 | 只通过 return 输出，不操作 DOM/状态/网络 |
| **业务函数** | 编排调度，处理副作用 | 调用技术函数完成转换，自身负责 DOM/API/状态 |

```javascript
// ✅ 技术函数 — 纯计算
function _buildNodeMap(rawNodes) { ... }
function _applyDirectedLayout(nodeMap, edgeList, centerId, centerX, centerY) { ... }

// ✅ 业务函数 — 编排
function _renderCopeGraph(raw) {
    var nodeMap = _buildNodeMap(raw.nodes);
    var edgeList = _buildEdgeList(raw.edges);
    var layout = _applyDirectedLayout(nodeMap, edgeList, initId, 600, 400);
    _setFlowNodes(layout.nodes, layout.edges);
    _updateCopeHeader(raw);
}
```

```python
# ✅ 技术函数 — 纯计算
def _calc_confidence(scores: list[dict]) -> float: ...
def _translate_owl_to_cypher(axiom: str) -> str: ...

# ✅ 业务函数 — 编排副作用
async def execute(self, context: InferenceContext) -> InferenceResult:
    queries = [t.translate(r) for r in rules]  # 技术
    result = await _call_reasoner(queries)       # 副作用
    confidence = _calc_confidence(result)         # 技术
    return InferenceResult(...)
```

### 5.3 保持简单

- Python 慢 → 不做算法，只做调用和组装
- 智能体慢 → 减少 LLM 调用次数，数据一次查好
- 推理机在另一个项目 → 只负责调它，不实现推理逻辑
- 所有方法保持 O(1) ~ O(n) 简单操作

### 5.3 无状态设计

- 所有类不持有请求级业务状态（Worker 进程无状态）
- 上下文通过 Pydantic 模型传入，结果通过 Pydantic 模型返回
- 需要持久化的状态写入 Memgraph / SQLite

### 5.4 宽容执行

| 场景 | 处理 |
|------|------|
| 字段缺失 | `dict.get()` 取默认值，不抛异常 |
| 规则翻译失败 | 跳过该规则，继续处理剩余规则 |
| 推理机超时/错误 | 降级返回已有结果 |
| func: 未注册 | logger.warning() + 跳过 |
| 边属性缺少校验字段 | 默认 `required=False`，`validationType="Weak"` |
| 快照创建失败 | 降级在主图上执行 |

### 5.5 日志

- 统一使用 `structlog`（`common/utils/logger.py`）
- 禁止 `print()` 和裸 `logging.getLogger()`

---

## 6. 异常处理

### 6.1 硬性约束

| 规则 | 说明 |
|------|------|
| **MUST** 继承 `AppException` | 所有业务异常继承 `common.exceptions.base.AppException` |
| **MUST NOT** 抛裸 `Exception` | 严禁 `raise Exception("...")` |

### 6.2 本模块异常

| 异常类 | 父类 | 说明 |
|--------|------|------|
| `TranslationError` | `AppException` | 语义规则翻译失败 |
| `VersioningError` | `AppException` | 快照操作失败 |
| `InferenceExecutionError` | `AppException` | 推理执行流程错误 |
| `ActionDispatchError` | `AppException` | func: 分发失败 |

### 6.3 异常使用规则

- capabilities 层抛出的异常应使用 `ModelError` 或自定义子类
- 捕获 infrastructure 层异常后转换为本层异常再向上抛
- 绝不捕获异常后静默吞掉（`except ...: pass`）

---

## 7. 配置与安全

### 7.1 配置读取

- **静态配置**：唯一入口 `common/config/settings.py::get_settings()`
- **动态配置**：唯一入口 `infrastructure/config/dynamic.py::DynamicConfig`
- **优先级**：Redis 动态配置 > 环境变量 > `.env` 文件 > 代码默认值
- 禁止硬编码任何连接字符串或配置值

### 7.2 密钥管理

- **MUST NOT** 在代码中硬编码 API Key、Token 或密码
- **MUST** 所有凭据通过环境变量注入，由 `common/config/settings.py` 统一读取
- 环境变量命名：`UPPER_SNAKE_CASE`（如 `KG_SERVER_URL`、`ANTHROPIC_API_KEY`）

### 7.3 推理机连接配置

- 推理机地址：环境变量 `KG_SERVER_URL`
- 本模块不存储推理机凭据，调用时从 Settings 获取

---

## 8. 变更历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-07-12 | 初始规范：四子模块骨架 + 核心接口定义 |
