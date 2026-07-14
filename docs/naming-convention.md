# 数据库命名规范

> **版本**: v1.1  
> **生效日期**: 2026-07-14  
> **适用范围**: SQLite (`ontol.db`) 全部表、列、索引 + Memgraph 图节点/边属性

---

## 1. 核心原则

**所有表名和列名必须使用 `snake_case`（小写下划线），禁止使用 `camelCase`（驼峰式）。**

> ⚠️ **硬性规则**：新增字段必须遵守此规范。发现驼峰命名 → 立即修正，不得提交。

| 规范 | ✅ 正确 | ❌ 错误 |
|------|---------|---------|
| snake_case | `create_time` | `createTime` |
| snake_case | `ontol_model_id` | `ontolModelId` |
| snake_case | `cope_version_status` | `copeVersionStatus` |
| snake_case | `is_system` | `isSystem` |
| snake_case | `is_composed_of` | `isComposedOf` |
| snake_case | `query_variant` | `queryVariant` |

---

## 1.1 图数据库时间戳规范

**Memgraph 中所有节点和边的 `create_time` 和 `update_time` 属性，必须使用 Unix 时间戳格式。**

| 规范 | ✅ 正确 | ❌ 错误 |
|------|---------|---------|
| create_time | `1718345600` (Unix 秒级时间戳) | `"2026-07-14 12:00:00"` |
| update_time | `1718345600` (整数) | `"2026-07-14T12:00:00"` (ISO 字符串) |

**规则**：
- **类型**：整数（int64），不做字符串存储
- **精度**：秒级（10位），必要时可用毫秒（13位）
- **时区**：UTC
- **写入时机**：`create_time` 在节点/边创建时由系统自动写入；`update_time` 在每次属性修改时更新
- **前端展示**：由前端自行格式化为本地时间显示，数据库层始终存整数时间戳

**与 SQLite 的区别**：
| 存储 | 格式 | 类型 |
|------|------|------|
| SQLite `ontol_*` 表 | `"2026-07-14 12:00:00"` 字符串 | TEXT |
| Memgraph 节点/边属性 | `1718345600` 整数 | int64 |

> 为什么：Unix 时间戳避免了时区歧义、字符串解析开销和格式不一致问题。图推理引擎和 Cypher 查询可直接做数值比较（`WHERE n.create_time > 1718345600`），无需 `datetime()` 转换。

---

## 2. 分层命名策略

### 2.1 总则

**数据库层统一使用 `snake_case`，API/应用层按需转换为消费者习惯的命名风格。**

```
┌──────────────────────────────┐
│  前端 (JS/TS)                │  ← camelCase（JS 惯例）
│  { createTime, ontolModelId }│
├──────────────────────────────┤
│  API 响应 / Pydantic Schema  │  ← 转换边界：alias 映射
│  by_alias=True               │
├──────────────────────────────┤
│  业务层 / ORM / Repository   │  ← snake_case（与 DB 一致）
│  create_time, ontol_model_id │
├──────────────────────────────┤
│  SQLite / Memgraph           │  ← snake_case（唯一事实来源）
│  ontol_model                 │
└──────────────────────────────┘
```

### 2.2 各层职责

| 层 | 命名风格 | 说明 |
|----|----------|------|
| **数据库** (SQLite / Memgraph) | `snake_case` | 唯一事实来源，所有列名、表名均为 snake_case |
| **Repository / ORM** | `snake_case` | 与数据库字段一一对应，不做转换 |
| **Pydantic Schema** | `snake_case` 字段 + `alias` | 使用 `Field(alias="camelCaseName")` 映射到前端期望的命名 |
| **API 响应 JSON** | 按消费者约定 | 内部管理后台可用 snake_case；对外 API 或前端组件按需转 camelCase |
| **前端 JS/TS** | `camelCase` | JavaScript/TypeScript 惯例 |

### 2.3 转换位置

转换必须在 **API 边界** 完成，不得渗透到数据库层或业务层。

**正确做法 — Pydantic alias**：

```python
from pydantic import BaseModel, Field

class ModelAttrResponse(BaseModel):
    ontol_model_id: str = Field(alias="ontolModelId")
    attr_data_type: str = Field(alias="attrDataType")
    attr_is_system: str = Field(alias="attrIsSystem")

    class Config:
        populate_by_name = True  # 允许同时接受 snake_case 和 camelCase

# 序列化时转 camelCase
response = ModelAttrResponse.model_validate(db_row).model_dump(by_alias=True)
# → {"ontolModelId": "M_ROOT", "attrDataType": "VARCHAR", ...}
```

**反模式 — 在数据库层转换**：

```python
# ❌ 禁止：SQL 查询中直接 AS 重命名为 camelCase
cursor.execute("SELECT create_time AS createTime FROM ontol_model")
```

**反模式 — 在业务层混合风格**：

```python
# ❌ 禁止：字典 key 混用 snake_case 和 camelCase
result = {"ontolModelId": row["ontol_model_id"], "create_time": row["create_time"]}
```

### 2.4 Memgraph 图数据

Memgraph 节点/边属性 key 直接使用 `ontol_model_attr.code`（均为 snake_case），**不再做二次转换**。前端渲染图节点详情时，由前端自行映射为展示用名称。

---

## 3. 表命名规范

### 3.1 前缀

- **所有业务配置/元数据表必须以 `ontol_` 为前缀**
- 前缀与业务名之间用下划线连接

### 3.2 命名模式

```
ontol_{实体名}_{子实体名}
```

### 3.3 当前表清单（19 张业务表）

| 表名 | 实体 | 说明 |
|------|------|------|
| `ontol_model` | 本体模型 | 树形结构，`ontol_parent_id` 父子关系 |
| `ontol_model_attr` | 本体模型属性 | 字段定义，含系统预设 `attr_is_system='1'` |
| `ontol_model_scene` | 推演场景 | 场景 CRUD，`scene_is_system='1'` 受保护 |
| `ontol_scene_prompt` | 场景提示词 | 与场景一对多 |
| `ontol_scene_dictionary` | 场景字典 | 维度管理 |
| `ontol_scene_dictionary_relation` | 场景-字典关联 | 多对多关联表 |
| `ontol_char_scene_relation` | 对话-场景绑定 | chart_id → 实际指向 chat |
| `ontol_chat_cope_version_relation` | 对话-副本关联 | 对话绑定推演副本 |
| `ontol_cope_version` | 推演副本 | 副本状态 00/01/02/03 |
| `ontol_data_his` | 数据变更历史 | 节点 CRUD 自动记录 |
| `ontol_node_scene_relation` | 节点-场景关系 | 图节点绑定场景 |
| `ontol_datasource` | 数据源配置 | MySQL/PG/Oracle 等 |
| `ontol_datasource_type` | 数据源类型 | `is_system='1'` 系统预设 |
| `ontol_datasource_log` | 数据源日志 | 日志记录 |
| `ontol_dictionary_type` | 字典类型 | 关系类型/实体标签词典 |
| `ontol_function` | 动态函数 | classpath + method |
| `ontol_function_type` | 函数类型 | 函数分类 |
| `ontol_llm_config` | LLM 模型配置 | url/key/model，外键关联 type |
| `ontol_llm_type_config` | LLM 类型配置 | provider 协议定义 |

> **注意**：`ontol_char_scene_relation` 中 `char` 是 `chat` 的历史拼写遗留，表名暂不修改（需同步修改所有路由和前端引用）。

---

## 4. 列命名规范

### 4.1 通用约定

- **全部小写**，单词之间用下划线分隔
- **禁止使用驼峰命名**（如 `createdBy`、`bizId`）
- **布尔字段**以 `is_` 开头（如 `is_system`、`is_composite_check`）
- **外键字段**以 `_id` 结尾（如 `scene_id`、`ontol_model_id`）
- **时间字段**以 `_time` 结尾（如 `create_time`、`update_time`、`executed_time`）
- **标记字段**以 `_flag` 结尾（如 `delete_flag`）

### 4.2 外键命名规则

外键列名遵循以下优先级：

1. **同一 schema 内**：`{target_table}_id`  
   例：`ontol_model_attr.ontol_model_id` → 指向 `ontol_model`
2. **跨表关联简化**：去掉 `ontol_` 前缀，直接用实体名  
   例：`ontol_scene_prompt.scene_id`（而非 `ontol_model_scene_id`）
3. **关联表（中间表）**：两端都用简化形式  
   例：`ontol_char_scene_relation` 中 `scene_id`（而非 `ontol_model_scene_id`）

### 4.3 通用列（每个表都应包含）

| 列名 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `id` | TEXT | UUID | 主键，16 位 hex |
| `create_time` | TEXT | `datetime('now')` | 创建时间（系统接管） |
| `create_user` | TEXT | `''` | 创建人 |
| `update_time` | TEXT | `''` | 更新时间（系统接管） |
| `update_user` | TEXT | `''` | 更新人 |
| `delete_flag` | TEXT | `'0'` | 软删除标记 |
| `is_system` | TEXT | `'0'` | 系统预设标记 |

### 4.4 通用列（业务表可选）

| 列名 | 类型 | 说明 |
|------|------|------|
| `code` | TEXT | 业务编码 |
| `name` | TEXT | 名称 |

---

## 5. 已修正问题记录

### 5.1 列名修正（2026-07-14 已完成）

| 表 | 旧名称 (camelCase) | 新名称 (snake_case) | 操作 |
|----|-------------------|---------------------|------|
| `ontol_model_attr` | `hasPrecondition` | `erecondition` | 删除后重建 |
| `ontol_model_attr` | `hasEffect` | `effect` | 删除后重建 |
| `ontol_model_attr` | `hasCost` | `cost` | 删除后重建 |
| `ontol_model_attr` | `hasDuration` | `duration` | 删除后重建 |
| `ontol_model_attr` | `hasPriority` | `priority` | 删除后重建 |
| `ontol_model_attr` | `leven` | `level` | 重命名 |
| `ontol_model_attr` | `isComposedOf` | `is_composed_of` | 重命名 |
| `ontol_model_attr` | `queryVariant` | `query_variant` | 重命名 |
| `ontol_model_attr` | `isCompositeCheck` | `is_composite_check` | 重命名 |

**当前状态**：`ontol_model_attr` 所有有效 code 列均已为纯 `snake_case`，零驼峰。

### 5.2 历史遗留（待后续批次修正）

以下文件中仍引用旧名称，暂不修改：

| 文件 | 旧引用 | 说明 |
|------|--------|------|
| `infrastructure/db/sqlite_db.py` | `hasPrecondition`, `hasEffect`, `hasCost` | 种子数据，需更新为新 code 后重新初始化 |
| `business/reasoning/engine.py` | `props.get("hasPrecondition")` 等 | 推理引擎读图节点属性，需随 Memgraph 图数据迁移同步改 |
| `business/reasoning/rules.py` | `hasPrecondition` 等 key 常量 | 同上 |
| `CLAUDE.md` | 多处引用旧属性名 | 文档需同步更新 |
| `ARCHITECTURE.md` | 同上 | 同上 |

### 5.3 已知的其他不一致

| 表 | 列名 | 问题 | 建议 |
|----|------|------|------|
| `ontol_char_scene_relation` | `chart_id` | 拼写 `chart` 应为 `chat` | 改为 `chat_id` |
| `ontol_model_attr` | `attr_cascade_colum` | `colum` 应为 `column` | 改为 `attr_cascade_column` |
| `ontol_datasource` | `jdbc_url`, `driver_class`, `password_cipher`, `config_extra`, `created_by` | 混合了 Java 风格和 DB 风格 | 统一为 snake_case 语义命名 |
| `ontol_cope_version` | `init_note_id`, `init_note_name` | `note` 疑似拼写错误，应为 `node` | 改为 `init_node_id`, `init_node_name` |
| `ontol_model_scene` | `scene_is_system` | 与其他表 `is_system` 不一致 | 统一为 `is_system` |
| `ontol_model_scene` | `scene_desc` | 与其他表 `description` 不一致 | 统一为 `description` |
| `ontol_scene_prompt` | `prompt_desc` + `prompt_description` | 冗余字段，两列含义重叠 | 合并为一个 `description` |
| `ontol_datasource_type` | `datasource_description` | 前缀冗余 | 改为 `description` |
| `ontol_dictionary_type` | `dictionary_description` | 前缀冗余 | 改为 `description` |
| `ontol_function_type` | `function_description` | 前缀冗余 | 改为 `description` |

---

## 6. 新建表/列检查清单

创建新表或新增列时，必须逐项确认：

- [ ] 表名以 `ontol_` 开头
- [ ] 表名全部小写，单词间用下划线
- [ ] 所有列名全部小写，单词间用下划线
- [ ] 无驼峰命名（包括 `camelCase` 和 `PascalCase`）
- [ ] 无数字开头
- [ ] 外键以 `_id` 结尾
- [ ] 布尔标记以 `is_` 开头
- [ ] 时间字段以 `_time` 结尾
- [ ] 包含 7 个通用列：`id`, `create_time`, `create_user`, `update_time`, `update_user`, `delete_flag`, `is_system`
- [ ] SQL 关键字不冲突（避免 `order`、`group`、`index` 等作为列名，若必须用则用 `_` 后缀如 `attr_order`）

---

## 7. 命名对照速查表

### 7.1 camelCase → snake_case 自动转换规则

当发现驼峰命名的字段时，按以下规则转换：

```
hasPrecondition   →  erecondition          (业务约定：去 has 前缀)
hasEffect         →  effect
hasCost           →  cost
hasDuration       →  duration
hasPriority       →  priority
isComposedOf      →  is_composed_of
queryVariant      →  query_variant
isCompositeCheck  →  is_composite_check
createdBy         →  created_by
bizId             →  biz_id
batchNo           →  batch_no
jdbcUrl           →  jdbc_url
driverClass       →  driver_class
```

### 7.2 Memgraph 图节点属性命名

Memgraph 中节点/边的属性 key 遵循与 SQLite 相同的 `snake_case` 规范。属性名来自 `ontol_model_attr.code`，因此只要 SQLite 中 code 列正确，图属性自动正确。

---

> **维护者**: 开发团队  
> **相关文档**: [[CLAUDE.md]], [[ARCHITECTURE.md]]  
> **关联规范**: 表命名前缀 `ontol_`，外键 `_id`，软删除 `delete_flag`，时间戳 `create_time` + `update_time`
