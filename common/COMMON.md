# COMMON.md — 共享层约束

> **定位**: 本层是所有层共享的基础设施。提供产品↔业务隔离契约 (contracts)、配置管理、Pydantic 数据模型、统一异常定义和工具函数（日志/指标/追踪）。本层不依赖任何上层模块。

**目录**: [文件清单](#1-文件清单) | [配置管理规范](#2-配置管理规范) | [数据模型规范](#3-数据模型规范) | [异常体系规范](#4-异常体系规范) | [日志规范](#5-日志规范) | [指标规范](#6-指标规范) | [追踪规范](#7-追踪规范) | [测试要求](#8-测试要求)

---

## 1. 文件清单

| 子模块 | 文件 | 角色 |
|--------|------|------|
| contracts | `graph_extension.py` | `GraphExtension` Protocol — 产品↔业务隔离边界 |
| contracts | `state_schema.py` | `GraphStateBase` TypedDict — 业务 State 基础字段 |
| config | `settings.py` | `Settings` (Pydantic Settings) — 环境变量 → 配置单例 |
| models | `schemas.py` | Pydantic 模型: RunRequest, RunResponse, StreamEvent, ErrorResponse 等 |
| exceptions | `base.py` | 异常层次结构: 1 个基类 + 9 个子类 |
| exceptions | `handlers.py` | FastAPI 全局异常处理器 |
| utils | `logger.py` | structlog 初始化 + `get_logger` 工厂 |
| utils | `metrics.py` | Prometheus 指标定义 + `get_metrics()` |
| utils | `tracer.py` | OpenTelemetry + LangSmith 追踪初始化 |

### 1.1 contracts 模块规范

**定位**: 定义产品代码（orchestrator 等）对业务代码的抽象契约，是产品↔业务的**唯一编译期交集**。

#### GraphExtension 协议

```python
from typing import Any, AsyncIterator, Optional, Protocol, runtime_checkable

@runtime_checkable
class GraphExtension(Protocol):
    """业务工作流图扩展点协议 — 产品对业务的唯一期待。"""
    graph_name: str                                      # 工作流唯一标识名

    async def initialize(self) -> None: ...              # 编译图 + 创建 checkpointer
    async def run(self, input_data: dict, config: Optional[dict]) -> dict: ...
    async def stream(self, input_data: dict, config: Optional[dict]) -> AsyncIterator[dict]: ...
    async def get_state(self, thread_id: str) -> Optional[dict]: ...
    async def close(self) -> None: ...
```

协议定义了 6 个成员：1 个类属性 + 5 个方法。业务图只需满足此接口即可被 `GraphExecutor` 调度，产品代码不需要知道业务图内部有几个节点、怎么路由。

#### GraphStateBase

```python
class GraphStateBase(TypedDict, total=False):
    """所有业务域 State 必须包含的基础字段。"""
    messages: list
    input: dict       # 只读
    current_step: str
    next_node: str
    data: dict        # 节点间传递中间结果
    metadata: dict    # trace_id, user_id, workflow_name
    error: Optional[str]
```

业务域通过继承 `GraphStateBase` 自动获得这些框架字段，然后再追加自己的域专用字段：

```python
from common.contracts.state_schema import GraphStateBase

class MyDomainState(GraphStateBase, total=False):
    # 域专用字段
    my_custom_field: str
    my_result: Optional[dict]
```

**隔离规则**:
| 规则 | 说明 |
|------|------|
| **MUST** 业务 State 继承 `GraphStateBase` | 保证框架所需的基础字段存在 |
| **MUST** 业务图类满足 `GraphExtension` 协议 | 继承 `BaseWorkflowGraph` 是最简方式 |
| **MUST** 在 `business/__init__.py` 的 `REGISTRY` 显式注册 | 替代 pkgutil 自动扫描 |
| **MUST NOT** orchestrator 直接 import 业务内部模块 | 仅通过 `business.REGISTRY` + `GraphExtension` 协议交互 |
| **MUST NOT** 业务 import gateway 或 infrastructure 内部实现 | 通过 capabilities 接口、common 工具间接使用 |

---

## 2. 配置管理规范

### 2.1 Settings (settings.py)

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",               # 自动加载 .env
        env_file_encoding="utf-8",
        extra="ignore",                # 忽略未定义的环境变量
    )

    # 所有字段都有默认值 (敏感字段为 None)
    app_name: str = "LangGraph Cluster Gateway"
    default_model: str = "claude-sonnet-4-6"
    postgres_uri: str = "postgresql://localhost:5432/langgraph"
    kg_server_url: str = "http://192.168.56.1:8085"
    neo4j_uri: str = "neo4j://127.0.0.1:7687"
    anthropic_api_key: Optional[str] = None  # 敏感，无默认值
    ...

@lru_cache()
def get_settings() -> Settings:
    """全局配置单例。"""
    return Settings()
```

### 2.2 配置约束

| 规则 | 说明 |
|------|------|
| **MUST** 通过 `get_settings()` 获取 | 唯一入口，保证单例 |
| **MUST** 环境变量用 `UPPER_SNAKE_CASE` | `POSTGRES_URI`, `REDIS_URI` |
| **MUST** 敏感字段默认 `None` | API Key 等必须在环境变量中提供 |
| **MUST NOT** 直接 `os.getenv()` | 绕过 Settings，破坏配置统一性 |
| **MUST NOT** 在 Settings 中放业务逻辑 | 纯配置容器 |

### 2.3 新增配置项

1. 在 `Settings` 类中添加字段（含类型注解和默认值）
2. 在 `.env.example` 中添加示例值
3. 类型限制: `str`, `int`, `bool`, `list[str]`, `Optional[str]`

### 2.4 动态配置

动态配置已迁移至 `infrastructure/config/dynamic.py`，因为它依赖 Redis 客户端。

```python
from infrastructure.config.dynamic import DynamicConfig
```

**优先级**: Redis 动态值 > 环境变量 > Settings 默认值

**约束**:
- 仅用于需要热更新的配置项（限流阈值、模型切换等）
- 不可用于敏感配置（API Key 不从 Redis 读取）

详见 [infrastructure/INFRASTRUCTURE.md](../infrastructure/INFRASTRUCTURE.md)

---

## 3. 数据模型规范

### 3.1 schemas.py 约束

| 规则 | 说明 |
|------|------|
| **MUST** 所有 API 请求/响应使用 Pydantic BaseModel | 不使用 `dict` 或 `TypedDict` |
| **MUST** 有意义的 Field description | `Field(..., description="...")` |
| **MUST** `Optional` 显式标注 | 可选字段用 `Optional[type] = None` |
| **MUST NOT** 在 Schema 中写业务逻辑 | 纯数据结构，无方法（除 validator） |

### 3.2 请求/响应模型

```python
# 请求: XxxRequest
class RunRequest(BaseModel):
    workflow_name: str = Field(..., description="工作流名称")
    input: dict = Field(..., description="工作流输入数据")
    config: Optional[dict] = Field(None, description="运行时配置")

# 响应: XxxResponse
class RunResponse(BaseModel):
    run_id: str = Field(..., description="运行 ID")
    status: str = Field(..., description="运行状态")
    output: Optional[dict] = Field(None, description="运行输出")

# 事件: XxxEvent (流式)
class StreamEvent(BaseModel):
    event: str = Field(..., description="事件类型")
    name: str = Field("", description="事件来源名称")
    data: Any = Field(None, description="事件数据")
    run_id: str = Field("", description="所属运行 ID")

# 错误: ErrorResponse
class ErrorResponse(BaseModel):
    error: str = Field(..., description="错误类型")
    detail: str = Field(..., description="错误详情")
    trace_id: Optional[str] = Field(None, description="追踪 ID")
```

### 3.3 模型演进

- 新增字段: 设为 `Optional` 保证向后兼容
- 删除字段: 先标记 deprecated，两个版本后删除
- 重命名字段: 不允许 (破坏 API 兼容)

---

## 4. 异常体系规范

### 4.1 异常层次

```
AppException (基类, status_code=500)
├── ValidationError            → 400 Bad Request
├── AuthenticationError        → 401 Unauthorized
├── AuthorizationError         → 403 Forbidden
├── NotFoundError              → 404 Not Found
├── RateLimitError             → 429 Too Many Requests
├── WorkflowError              → 500 Internal Server Error
├── ModelError                 → 502 Bad Gateway
├── InfrastructureError        → 503 Service Unavailable
└── ConfigurationError         → 500 Internal Server Error
```

### 4.2 使用约束

| 规则 | 说明 |
|------|------|
| **MUST** 所有业务异常继承 `AppException` | 不抛裸 `Exception` / `ValueError` |
| **MUST** 选择合适的子类 | 根据错误类型选择对应异常，而不是全用 `AppException` |
| **MUST** `detail` 信息可读 | 面向调用方的描述，不是堆栈信息 |
| **MUST NOT** detail 中包含敏感信息 | 不含 API Key、密码、内部 IP 等 |
| **MUST NOT** 在 common/ 内抛异常 | common/ 只定义，不抛出 |

### 4.3 新增异常子类

```python
class MyNewError(AppException):
    status_code = 4xx              # HTTP 状态码
    error_code = "MY_NEW_ERROR"   # 对外错误码

# 使用时
raise MyNewError("具体描述")
```

### 4.4 异常处理 (handlers.py)

```python
# 在 gateway/app.py 中注册:
from common.exceptions.handlers import register_handlers
register_handlers(app)  # 注册 AppException → JSONResponse 的映射
```

- 全局处理器将 `AppException` 转为 `ErrorResponse` JSON
- 未知异常转为 500 + "An unexpected error occurred."
- **MUST**: 在应用启动时注册（`create_app` 中调用）

---

## 5. 日志规范

### 5.1 初始化

```python
# 在应用启动时调用一次
from common.utils.logger import setup_logging
setup_logging()
```

### 5.2 使用

```python
from common.utils.logger import get_logger

logger = get_logger(__name__)

# 按级别记录
logger.info("message", extra={"key": "value"})
logger.warning("message", ...)
logger.error("message", ...)
logger.exception("message", ...)  # 自动记录堆栈
```

### 5.3 约束

| 规则 | 说明 |
|------|------|
| **MUST** 使用 `get_logger(__name__)` | 不直接用 `logging.getLogger` 或 `print` |
| **MUST** 关键信息放 `extra` | `extra={"trace_id": ..., "user_id": ..., "elapsed_ms": ...}` |
| **MUST** 日志格式 JSON | structlog 配置为 JSONRenderer，每条日志一行 JSON |
| **MUST NOT** 记录敏感信息 | API Key、Token 原文、密码不写入日志 |
| **MUST NOT** f-string 拼接后传入 | `logger.info(f"user {id} did X")` — 应用 `extra={"user_id": id}` |

### 5.4 标准 extra 字段

| 字段 | 含义 | 必填 |
|------|------|------|
| `trace_id` | 请求追踪 ID | ✅ |
| `user_id` | 用户标识 | 可选 |
| `elapsed_ms` | 耗时 (毫秒) | 请求结束时 |
| `status_code` | HTTP 状态码 | gateway 层 |
| `workflow` | 工作流名称 | orchestrator 层 |

---

## 6. 指标规范

### 6.1 指标定义

#### 请求与执行指标

```python
from common.utils.metrics import (
    request_total,        # Counter: 请求数
    chain_duration,       # Histogram: Chain 耗时
    token_usage,          # Counter: Token 消耗
    active_runs,          # Gauge: 活跃运行数
    completed_runs,       # Counter: 完成数
    http_request_duration,# Histogram: HTTP 耗时
)
```

#### 集群维度指标

```python
from common.utils.metrics import (
    queue_length,              # Gauge: 任务队列深度 (KEDA 伸缩依据)
    worker_busy,               # Gauge: 当前繁忙 Worker 数
    pubsub_latency,            # Histogram: Redis PubSub 跨 Pod 延迟
    checkpoint_recovery_total, # Counter: Checkpoint 恢复次数 (故障切换)
    gateway_latency,           # Histogram: Gateway 端到端延迟
)
```

| 集群指标 | 类型 | 标签 | 用途 |
|---------|------|------|------|
| `langgraph_queue_length` | Gauge | queue_name | KEDA 弹性伸缩依据 |
| `langgraph_worker_busy` | Gauge | worker_pod | Worker 利用率监控 |
| `langgraph_pubsub_latency_seconds` | Histogram | channel | 跨 Pod 通信延迟 (buckets: 1ms~5s) |
| `langgraph_checkpoint_recovery_total` | Counter | workflow | Checkpoint 恢复次数，衡量故障切换频率 |
| `langgraph_gateway_e2e_latency_seconds` | Histogram | workflow | 从 Gateway 接收到 Worker 完成的端到端延迟 |

### 6.2 使用约束

| 规则 | 说明 |
|------|------|
| **MUST** Counter 只能递增 | `request_total.labels(...).inc()` |
| **MUST** Gauge 可增可减 | `active_runs.inc()` / `active_runs.dec()` |
| **MUST** Histogram 记录耗时 | `chain_duration.labels(...).observe(duration_s)` |
| **MUST** 带标签标注维度 | 不加标签的指标无法区分来源 |
| **MUST NOT** 标签值动态无限 | 不要用 user_id 当标签 (会导致指标爆炸) |

### 6.3 暴露端点

```python
# 在 routes 中添加 Prometheus metrics 端点
from common.utils.metrics import get_metrics

@router.get("/metrics")
async def metrics():
    return Response(content=get_metrics(), media_type="text/plain")
```

---

## 7. 追踪规范

### 7.1 初始化

```python
from common.utils.tracer import setup_tracing
setup_tracing()  # 在应用启动时调用一次
```

### 7.2 配置

- `LANGSMITH_API_KEY` 设置后自动启用 LangSmith 追踪
- `OTEL_EXPORTER_ENDPOINT` 设置 OpenTelemetry 导出目标

### 7.3 约束

- LangChain/LangGraph 的调用自动获得追踪（框架内置）
- 手动创建 span: `from common.utils.tracer import get_tracer`
- trace_id 与请求的 `X-Trace-ID` 保持一致

---

## 8. 测试要求

| 测试对象 | 类型 | 重点 |
|----------|------|------|
| Settings | 单元 | 环境变量 → 字段映射正确 |
| DynamicConfig | 单元 | (在 infrastructure 中测试) Mock Redis，验证优先级 |
| schemas | 单元 | Pydantic 校验正确/错误用例 |
| 异常 | 单元 | status_code 和 error_code 正确 |
| handlers | 单元 | AppException → ErrorResponse JSON |
| logger | 单元 | structlog 配置正确 |
| metrics | 单元 | Counter/Gauge/Histogram 创建正确 |

```python
def test_app_exception_status_code():
    exc = ValidationError("bad input")
    assert exc.status_code == 400
    assert exc.error_code == "VALIDATION_ERROR"

def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_URI", "postgresql://prod:5432/db")
    settings = Settings()
    assert settings.postgres_uri == "postgresql://prod:5432/db"
```
