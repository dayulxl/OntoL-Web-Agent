# INFRASTRUCTURE.md — 基础设施层约束

> **定位**: 本层封装所有外部中间件的客户端。上层代码通过本层提供的函数间接操作 Postgres/Redis/消息队列/对象存储，不直接接触驱动。

**目录**: [文件清单](#1-文件清单) | [通用约束](#2-通用约束) | [Postgres 规范](#3-postgres-规范) | [Redis 规范](#4-redis-规范) | [消息队列规范](#5-消息队列规范) | [对象存储规范](#6-对象存储规范) | [集群约束](#7-集群约束) | [测试要求](#8-测试要求)

---

## 1. 文件清单

| 子模块 | 文件 | 角色 |
|--------|------|------|
| db | `base_repo.py` | **BaseRepository** — 通用异步 CRUD 基类 (insert/list/search/update/delete/upsert/事务) |
| db | `postgres.py` | asyncpg 连接池封装，健康检查，迁移执行器 |
| db | `ontology_repo.py` | **OntologyRepo** — 本体模型 PG 数据访问层 |
| db | `sqlite_db.py` | **SQLite 文件数据库** — 自包含，无需外部服务，自动建表+种子 |
| db | `sqlite_repo.py` | **SQLiteOntologyRepo** — 接口兼容 OntologyRepo，自动适配 SQL 方言 |
| db | `ontol.db` | SQLite 数据库文件 (自动生成，位于 infrastructure/db/ 下) |
| db | `neo4j.py` | Neo4j 异步驱动封装，连接池管理，健康检查 |
| db | `migrations/` | **SQL 迁移文件** (启动时按序执行，幂等) |
| cache | `redis.py` | 异步 Redis 客户端，缓存 + PubSub |
| config | `dynamic.py` | DynamicConfig — Redis 热更新配置（从 common/ 迁入） |
| queue | `task_queue.py` | Celery 任务队列封装 |
| storage | `object_store.py` | S3 兼容对象存储客户端 |
| storage | `uploads/` | 用户上传文件存储目录 (自动创建) |
| storage | `uploads/.history.json` | 历史上传记录 |

---

## 2. 通用约束

### 2.1 硬性规则

| 规则 | 说明 |
|------|------|
| **MUST** 全局单例 | 每个客户端的连接池/实例是模块级全局单例，通过 `create_*` 初始化 |
| **MUST** 提供 `check_*` | 每个子模块必须实现健康检查函数，供 `/ready` 端点使用 |
| **MUST** 提供 `close_*` | 每个子模块必须实现优雅关闭函数 |
| **MUST NOT** 在 `__init__` 中连接 | 不在 import 时建立连接，通过显式的 `create_*` 函数 |
| **MUST** `async/await` | 所有客户端操作使用异步接口 |

### 2.2 生命周期模式

```python
# 所有客户端遵循统一的生命周期模式:

# 模块级全局变量
_client: Optional[Client] = None

async def create_client(url: str) -> Client:   # 初始化
async def get_client() -> Client:              # 获取 (未初始化时抛异常)
async def check_xxx() -> bool:                 # 健康检查
async def close_client() -> None:              # 优雅关闭
```

### 2.3 依赖边界

```
infrastructure/
  ├── 可依赖 → common/config/settings.py  (get_settings)
  ├── 可依赖 → common/utils/logger.py     (get_logger)
  └── 不可依赖 → gateway/, orchestrator/, capabilities/
```

本层是**最底层**（除 `common/` 外），不应依赖任何业务逻辑。

---

## 3. Postgres 规范

### 3.1 文件: `db/postgres.py`

```python
_pool: Optional[Pool] = None

async def create_pool(dsn: str, min_size=5, max_size=20) -> Pool:
async def get_pool() -> Pool:
async def check_postgres() -> bool:
async def close_pool() -> None:
```

### 3.2 使用约束

| 规则 | 说明 |
|------|------|
| **MUST** 通过 `get_pool()` 获取 | 不得在业务代码中直接持有 `_pool` 引用 |
| **MUST** 使用 `async with pool.acquire()` | 每次查询获取连接，用完自动归还 |
| **MUST NOT** 裸 SQL 拼接 | 若需 SQL，使用参数化查询 `$1, $2` |
| **MUST NOT** 在此模块操作 checkpoint 表 | LangGraph checkpoint 由 `AsyncPostgresSaver` 管理 |

### 3.3 健康检查

```python
async def check_postgres() -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:
        return False
```

- **MUST**: 使用轻量查询 `SELECT 1`
- **MUST**: 捕获所有异常返回 `False`（不给调用方抛异常）

### 3.4 文件: `db/base_repo.py` — 通用 CRUD 基类

```python
class BaseRepository:
    """任意表的通用异步 CRUD"""

    def __init__(self, pool, table, *, pk="id", soft_delete=False, auto_timestamps=True)

    # CREATE
    async def insert(data, *, conn=None) -> dict

    # READ
    async def get_by_id(pk_value, ...) -> Optional[dict]
    async def list(*, where, order_by, limit, offset, ...) -> list[dict]
    async def search(keyword, columns, *, extra_where, ...) -> list[dict]  # 多列 ILIKE
    async def count(*, where, ...) -> int
    async def exists(pk_value) -> bool

    # UPDATE
    async def update(pk_value, data, *, where, ...) -> Optional[dict]

    # DELETE
    async def delete(pk_value, *, soft=True, ...) -> bool        # 单行软/硬删除
    async def delete_where(where, *, soft=True, ...) -> int       # 批量条件删除

    # UPSERT
    async def upsert(data, conflict_columns, *, update_columns=None, ...) -> dict

    # 事务 & 原始查询
    async def transaction() -> Connection
    async def execute_raw(sql, *params, ...) -> list[dict]
```

**设计要点**:
- 参数化查询 (`$1/$2`) 防 SQL 注入
- 可选软删除 (`delete_flag` 列)
- 可选自动时间戳 (`create_time` / `update_time`)
- 所有方法支持 `conn=` 参数实现事务链

**继承使用**:
```python
class OntologyRepo:
    def __init__(self, pool):
        self.model = BaseRepository(pool, "ontol_model", pk="id", soft_delete=True)
        self.attr  = BaseRepository(pool, "ontol_model_attr", pk="id", soft_delete=True)
```

### 3.5 文件: `db/ontology_repo.py` — 本体模型 Repository

```python
class OntologyRepo:
    def __init__(self, pool: Pool):
        self.model = BaseRepository(pool, "ontol_model", pk="id", soft_delete=True)
        self.attr  = BaseRepository(pool, "ontol_model_attr", pk="id", soft_delete=True)

    # 树形查询
    async def get_tree(root_id=None) -> list[dict]                 # 递归 CTE
    async def get_full_tree_with_attrs(root_id=None) -> list[dict] # 树 + 属性字段
    async def get_children(parent_id) -> list[dict]                # 直接子节点

    # 模型 + 属性
    async def get_model_with_attrs(model_id) -> Optional[dict]
    async def get_attrs_by_model(model_id, *, relation_flag=None) -> list[dict]

    # 搜索 & 统计
    async def search_models(keyword, limit=50) -> list[dict]       # 名称/描述 ILIKE
    async def get_stats() -> dict                                  # {model_count, attr_count}
```

### 3.6 文件: `db/postgres.py` — 迁移执行器

```python
async def run_migrations() -> list[str]:
    """
    按序执行 infrastructure/db/migrations/ 目录下所有 .sql 文件。
    每个文件幂等执行（依赖 SQL 自身的 IF NOT EXISTS / ON CONFLICT DO NOTHING）。
    在应用 lifespan 启动时自动调用。
    """
```

**迁移规范**:
- 文件名: `NNN_descriptive_name.sql` (如 `001_ontol_model.sql`)
- 使用 `CREATE TABLE IF NOT EXISTS` + `COMMENT ON` 语句
- 种子数据用 `INSERT ... ON CONFLICT (id) DO NOTHING`
- 每个迁移文件包裹在 `BEGIN` / `COMMIT` 事务中
- **MUST NOT** 在迁移中使用应用层 Python 逻辑

---

## 4. Redis 规范

### 4.1 文件: `cache/redis.py`

```python
_redis_client: Optional[Redis] = None

async def create_client(redis_url: str) -> Redis:
async def get_client() -> Redis:
async def check_redis() -> bool:
async def close_client() -> None:

# 缓存操作
async def cache_get(key: str) -> Optional[str]:
async def cache_set(key: str, value: str, ttl: int = 300) -> None:
async def cache_delete(key: str) -> None:

# PubSub 操作
async def publish(channel: str, message: str) -> None:
async def subscribe(channel: str) -> PubSub:
```

### 4.2 Redis 双重角色

```
Redis 实例 (同一个)
├── DB 0: 缓存 (Cache)
│   ├── cache_get / cache_set / cache_delete
│   └── ShortTermMemory (会话历史)
├── DB 1: Celery Broker
│   └── task_queue.py
└── PubSub: 实例间通信
    └── publish / subscribe
```

### 4.3 使用约束

| 规则 | 说明 |
|------|------|
| **MUST** 使用 `decode_responses=True` | `get_client()` 返回已解码的字符串，无需手动 decode |
| **MUST NOT** 在缓存中存储敏感数据 | Token、密码等不得进 Redis |
| **MUST** 设置 TTL | `cache_set` 的 ttl 默认 300s，不设永不过期的缓存除非有明确理由 |
| **MUST NOT** 直接使用 `_redis_client` | 业务代码通过 `cache_get`/`cache_set` 等封装函数访问 |

### 4.4 PubSub 约束

```python
# ✅ 正确: 通过封装函数
await publish("channel:workflow_status", json.dumps({"run_id": "...", "status": "completed"}))

# ❌ 错误: 绕过封装
client = await get_client()
await client.publish("chan", "msg")  # 使用封装好的 publish 函数
```

- PubSub 仅用于集群内实例间的状态通知
- 消息体使用 JSON 格式
- channel 名使用 `snake_case`，带命名空间前缀（如 `workflow:`, `config:`）

---

## 5. 消息队列规范

### 5.1 文件: `queue/task_queue.py`

```python
class TaskQueue:
    def __init__(self, broker_url: str):
    def register(self, name: str, func: Callable) -> None:
    async def enqueue(self, task_name: str, *args, **kwargs) -> str:
    async def schedule(self, task_name: str, eta: int, *args, **kwargs) -> str:
    async def get_status(self, task_id: str) -> Optional[str]:
    async def cancel(self, task_id: str) -> bool:
```

### 5.2 使用约束

| 规则 | 说明 |
|------|------|
| **MUST** 先 `register` 后 `enqueue` | 未注册的任务名称调用 `enqueue` 会抛 `ValueError` |
| **MUST** 任务函数是可序列化的纯函数 | Celery 需要通过网络投递任务参数 |
| **MUST NOT** 在任务函数中传递 ORM 对象 | 只传基本类型（str/int/dict/list） |
| **MUST NOT** 同步阻塞 | 任务函数应为 `async def` 或使用 Celery 的同步 worker |

### 5.3 死信处理

- 重试次数耗尽的任务进入死信队列
- 死信保留时间: 7 天
- 运维告警应监控死信队列堆积

---

## 6. 对象存储规范

### 6.1 文件: `storage/object_store.py`

```python
class ObjectStore:
    def __init__(self, endpoint, access_key, secret_key, bucket, region="us-east-1"):
    async def initialize(self) -> None:
    async def put(self, key: str, data: bytes, content_type: str = ...) -> None:
    async def get(self, key: str) -> Optional[bytes]:
    async def delete(self, key: str) -> None:
    async def exists(self, key: str) -> bool:
    async def list(self, prefix: str = "", max_keys: int = 100) -> list[str]:
    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
```

### 6.2 使用约束

| 规则 | 说明 |
|------|------|
| **MUST** 调用 `initialize()` | 在首次使用前确保 bucket 存在 |
| **MUST** key 使用路径格式 | `"workflows/{workflow_name}/{date}/{uuid}.json"` |
| **MUST NOT** 存储 > 100MB 对象 | 大文件应走分片上传或专用 CDN |
| **MUST NOT** key 含特殊字符 | 只用字母、数字、`/`、`-`、`_`、`.` |

---

## 7. 集群约束

### 7.1 集群模式下的反模式

| 反模式 | 错误做法 | 集群风险 | 正确做法 |
|--------|---------|---------|---------|
| 本地消息队列 | `asyncio.Queue` 广播事件 | 跨 Pod 无法感知 | `infrastructure/queue/task_queue.py` (Celery) |
| 本地文件 IO | `open()` / `pathlib` 读写共享文件 | 多 Pod 读写冲突 | `infrastructure/storage/object_store.py` (S3/MinIO) |
| 内存进程锁 | `threading.Lock` / `asyncio.Lock` 跨请求 | 仅限单 Pod 内 | Redis 分布式锁 (`SETNX`) |
| 本地缓存 | `@lru_cache` / 模块级 `dict` 缓存业务数据 | Pod 间数据不一致 | Redis `cache_get`/`cache_set` |
| 直接连数据库 IP | 硬编码 `postgres://10.0.1.5:5432` | Pod 迁移后失效 | K8s Service DNS (`postgres:5432`) |

### 7.2 集群兼容的客户端初始化

```python
# ✅ 正确: 使用 K8s Service DNS 名称
redis_url = "redis://redis:6379/0"
postgres_uri = "postgresql://langgraph:pass@postgres:5432/langgraph"

# ✅ 正确: 初始化失败时重试 (等待基础设施就绪)
async def create_pool_with_retry(dsn: str, max_retries=5, delay=2):
    for i in range(max_retries):
        try:
            return await create_pool(dsn)
        except Exception:
            if i == max_retries - 1:
                raise
            await asyncio.sleep(delay)

# ❌ 错误: 硬编码 IP
postgres_uri = "postgresql://10.0.1.5:5432/langgraph"  # Pod 重启 IP 变化
```

### 7.3 Celery 队列命名规范

```
队列命名: {service}_{priority}
├── langgraph_tasks       # 默认任务队列
├── langgraph_high        # 高优先级 (实时推理)
├── langgraph_low         # 低优先级 (批量处理)
└── langgraph_dlq         # 死信队列 (失败任务)
```

### 7.4 PubSub Channel 命名规范

```
channel 命名: {domain}:{entity}:{event}
├── workflow:run:started      # 工作流开始
├── workflow:run:{id}:node    # 节点完成 (实时 SSE)
├── workflow:run:{id}:done    # 工作流完成
├── workflow:run:{id}:error   # 工作流异常
├── config:updated:{key}      # 动态配置变更
└── worker:heartbeat:{pod}    # Worker 心跳
```

---

## 8. 测试要求

| 测试对象 | 类型 | 重点 |
|----------|------|------|
| 连接池创建 | 单元 | Mock asyncpg，验证连接参数 |
| **BaseRepository CRUD** | **单元** | **验证 insert/list/search/update/delete/upsert 参数化查询** |
| **BaseRepository 软删除** | **单元** | **验证 delete_flag 过滤和软/硬删除切换** |
| **OntologyRepo 树查询** | **单元** | **验证递归 CTE 返回正确的 depth 层级** |
| **迁移执行器** | **单元** | **验证 SQL 文件按序执行和幂等性** |
| 健康检查 | 单元 | 正常返回 True，异常返回 False |
| 连接池关闭 | 单元 | 验证 close 被调用 |
| 缓存操作 | 单元 | Mock Redis，验证 TTL 传递 |
| PubSub | 单元 | Mock PubSub，验证 channel 名和消息格式 |
| 任务注册 | 单元 | 验证未注册任务抛异常 |
| **集群重试** | **单元** | **验证连接失败重试逻辑** |

```python
async def test_cache_set_ttl():
    # Mock Redis 客户端
    mock_redis = AsyncMock()
    with patch("infrastructure.cache.redis.get_client", return_value=mock_redis):
        await cache_set("key", "value", ttl=60)
        mock_redis.set.assert_called_once_with("key", "value", ex=60)
```
