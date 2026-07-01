# GATEWAY.md — API 网关层约束

> **定位**: 本层是整个系统的唯一对外入口。所有外部请求必须经过本层的鉴权、限流和日志中间件后，才能到达编排层。

**目录**: [文件清单](#1-文件清单) | [公共接口](#2-公共接口) | [API 端点规范](#3-api-端点规范) | [中间件约束](#4-中间件约束) | [上下文传递](#5-上下文传递) | [页面服务](#6-页面服务-jinja2--静态文件) | [编码规范](#7-编码规范) | [测试要求](#8-测试要求)

---

## 1. 文件清单

| 文件 | 角色 | 是否对外暴露 |
|------|------|-------------|
| `app.py` | FastAPI 应用工厂 `create_app()` | ✅ 启动入口 |
| `routes/langgraph_routes.py` | API 路由定义，Router 实例名为 `router` | ✅ 路由注册 |
| `routes/page_routes.py` | 页面路由 — Jinja2 模板渲染 & 静态文件挂载 | ✅ 路由注册 |
| `routes/ontology_routes.py` | Neo4j 本体建模 + PostgreSQL CRUD + **文件上传/解析/导入 + 推理代理** | ✅ 路由注册 |
| `templates/pages/ontology_template.html` | **本体语义页面** — 左树右详情 + 字段 CRUD | ❌ 模板资源 |
| `templates/pages/index.html` | **首页态势总览** — Canvas 静态态势图 + 兵力编成面板 | ❌ 模板资源 |
| `templates/pages/sandbox_wargame.html` | **沙盘推演** — ReactFlow 图编辑 + 子树展开 + 推理 | ❌ 模板资源 |
| `templates/pages/upload.html` | **文件上传** — 拖拽上传 + 历史 + AI 解析 + Neo4j 导入 | ❌ 模板资源 |
| `templates/pages/intelligence.html` | **情报展示** — Neo4j Entity 节点详情查看 | ❌ 模板资源 |
| `templates/` | Jinja2 模板文件目录 (`.html`) | ❌ 模板资源 |
| `static/` | 静态文件目录 (CSS / JS / 图片) | ❌ 静态资源 |
| `middleware/auth.py` | 鉴权 + 注入 `request_context` (ContextVar) | ❌ 内部 |
| `middleware/logging.py` | 请求日志记录 | ❌ 内部 |
| `middleware/rate_limiter.py` | 滑动窗口限流 | ❌ 内部 |

---

## 2. 公共接口

### 2.1 唯一对外符号

```python
# gateway/app.py
def create_app() -> FastAPI: ...

# gateway/routes/langgraph_routes.py
router: APIRouter  # prefix="/api/v1", tags=["LangGraph"]

# gateway/middleware/auth.py
request_context: ContextVar[dict]
```

### 2.2 依赖关系

```
gateway/
  ├── 依赖 → orchestrator/engine/executor.py  (GraphExecutor, 通过路由 Depends 注入)
  ├── 依赖 → common/config/settings.py         (get_settings)
  ├── 依赖 → common/models/schemas.py          (RunRequest, RunResponse, 等)
  ├── 依赖 → common/exceptions/base.py         (AppException)
  ├── 依赖 → common/utils/logger.py            (get_logger)
  ├── 依赖 → infrastructure/db/postgres.py     (create_pool / get_pool / check_postgres / run_migrations)
  ├── 依赖 → infrastructure/db/ontology_repo.py (OntologyRepo, 本体模型 CRUD 路由)
  ├── 依赖 → infrastructure/db/neo4j.py        (create_driver / get_driver)
  ├── 依赖 → infrastructure/cache/redis.py     (check_redis, 仅 /ready)
  ├── 依赖 → jinja2                            (模板引擎)
  └── 依赖 → aiofiles                          (静态文件异步 IO)

gateway/ 禁止直接依赖:
  ❌ orchestrator/graphs/  (任何具体图类)
  ❌ capabilities/         (任何能力层模块)
  ❌ infrastructure/db/postgres.py (除 lifespan 初始化 & ontology_routes 外)
```

---

## 3. API 端点规范

### 3.1 端点清单

| Method | Path | 响应类型 | K8s Probe | 鉴权 |
|--------|------|---------|-----------|------|
| POST | `/api/v1/run` | JSON `RunResponse` | — | ✅ |
| POST | `/api/v1/stream` | SSE `text/event-stream` | — | ✅ |
| GET | `/api/v1/runs/{run_id}/status` | JSON `RunStatusResponse` | — | ✅ |
| POST | `/api/v1/runs/{run_id}/cancel` | JSON | — | ✅ |
| POST | `/api/v1/chat` | SSE `text/event-stream` (AI 对话) | — | ✅ |
| GET | `/api/v1/ontology-models` | JSON (本体模型列表+搜索) | — | ❌ |
| GET | `/api/v1/ontology-models/stats` | JSON (模型/字段统计) | — | ❌ |
| GET | `/api/v1/ontology-models/search?keyword=` | JSON (模糊搜索) | — | ❌ |
| GET | `/api/v1/ontology-models/tree?with_attrs=` | JSON (递归 CTE 树) | — | ❌ |
| POST | `/api/v1/ontology-models` | JSON (创建本体模型) | — | ❌ |
| PUT | `/api/v1/ontology-models/{id}` | JSON (更新本体模型) | — | ❌ |
| DELETE | `/api/v1/ontology-models/{id}` | JSON (逻辑/物理删除) | — | ❌ |
| GET | `/api/v1/ontology-models/{id}/attrs` | JSON (模型属性列表) | — | ❌ |
| POST | `/api/v1/ontology-models/{id}/attrs` | JSON (创建属性) | — | ❌ |
| GET PUT DELETE | `/api/v1/ontology-attrs/{id}` | JSON (属性 CRUD) | — | ❌ |
| POST | `/api/v1/tools/call` | JSON (Rust 推理引擎代理) | — | ❌ |
| POST | `/api/v1/upload` | JSON (文件上传) | — | ❌ |
| GET | `/api/v1/upload/history` | JSON (上传历史) | — | ❌ |
| POST | `/api/v1/upload/parse` | JSON (AI 三元组解析) | — | ❌ |
| POST | `/api/v1/upload/import-triples` | JSON (三元组导入 Neo4j) | — | ❌ |
| GET | `/api/v1/upload/preview/{filename}` | JSON/File (文件预览/下载) | — | ❌ |
| DELETE | `/api/v1/upload/{filename}` | JSON (文件删除) | — | ❌ |
| GET | `/api/v1/health` | JSON `{"status":"ok"}` | liveness | ❌ |
| GET | `/api/v1/ready` | JSON `{"ready":bool}` | readiness | ❌ |

### 3.2 路由定义约束

```python
# ✅ 正确: 使用 Pydantic model 作为请求体
@router.post("/run", response_model=RunResponse)
async def run_workflow(request: RunRequest, ...): ...

# ✅ 正确: 流式端点返回 StreamingResponse
@router.post("/stream")
async def stream_workflow(request: RunRequest, ...): ...

# ❌ 错误: 不要返回裸 dict（无法生成 OpenAPI schema）
@router.post("/run")
async def run_workflow(data: dict): ...
```

### 3.3 请求校验

- 所有请求体**必须**使用 `common/models/schemas.py` 中的 Pydantic Model 校验
- 不自定义 Request 级 validator（保持 Schema 纯净）
- 文件上传暂不支持，如需添加需更新本文档

### 3.4 流式响应规范 (SSE)

```python
# 标准 SSE 事件格式
yield f"data: {json.dumps(event)}\n\n"

# 结束标记
yield "data: [DONE]\n\n"

# 错误事件
yield f"data: {{\"error\": \"...\"}}\n\n"
```

- Content-Type: `text/event-stream`
- 不得缓冲整个流（必须 yield）
- 异常由 event_generator 内部捕获并转为 error 事件

---

## 4. 中间件约束

### 4.1 执行顺序

```
请求 → RateLimiterMiddleware → AuthMiddleware → LoggingMiddleware → 路由处理 → 响应
```

在 `app.py` 中通过 `add_middleware` 的**逆序**添加（Starlette 机制）:

```python
app.add_middleware(RateLimiterMiddleware)   # 最先执行
app.add_middleware(AuthMiddleware)          # 第二执行
app.add_middleware(LoggingMiddleware)       # 第三执行
```

### 4.2 AuthMiddleware

- **输入**: 从 Header 提取 `Authorization: Bearer <token>` 或 `X-API-Key: <key>`
- **输出**: 注入 `request_context` ContextVar → `{trace_id, user_id}`
- **跳过**: `/health`, `/ready` 路径
- **trace_id 策略**: 优先使用 `X-Trace-ID` 请求头，缺失时生成 `uuid4`

### 4.3 LoggingMiddleware

- **MUST**: 每条日志含 `trace_id`, `user_id`, `method`, `path`, `status_code`, `elapsed_ms`
- **MUST**: 使用 `common.utils.logger.get_logger(__name__)` 而非裸 `logging`

### 4.4 RateLimiterMiddleware

- **MUST**: 基于 Redis 滑动窗口实现
- **Key 格式**: `ratelimit:{user_id}:{window_ts}`
- **默认阈值**: 60 次/分钟（通过 `RATE_LIMIT_PER_MINUTE` 环境变量覆盖）
- **超限响应**: HTTP 429 + `ErrorResponse(error="RATE_LIMIT_EXCEEDED")`

---

## 5. 上下文传递

### 5.1 request_context 规范

```python
from gateway.middleware.auth import request_context

# 读取上下文（任何层）
ctx = request_context.get()
trace_id = ctx.get("trace_id")
user_id = ctx.get("user_id")

# 写入上下文（仅 AuthMiddleware 允许）
request_context.set({...})
```

**约束**:
- **MUST**: `request_context.set()` **只能**在 `AuthMiddleware` 中调用
- **MUST**: 其他所有代码只能 `request_context.get()` 读取
- **MUST NOT**: 通过函数参数传递 trace_id — 使用 ContextVar 即可

---

## 6. 页面服务 (Jinja2 + 静态文件)

### 6.1 三种页面渲染方式

| 方式 | 依赖 | 适用场景 |
|------|------|---------|
| `HTMLResponse` | 无（starlette 内置） | 简单 HTML 字符串、健康检查页面 |
| `Jinja2Templates` | `jinja2` | 服务端模板渲染、动态数据注入、循环/条件 |
| `StaticFiles` | `aiofiles` | CSS / JS / 图片 / 已编译前端产物 |

### 6.2 目录规范

```
gateway/
├── templates/              # Jinja2 模板文件
│   ├── base.html           # 基础布局 (可继承)
│   ├── pages/              # 业务页面
│   │   ├── index.html      # 首页/管理后台
│   │   └── workflow.html   # 工作流可视化
│   └── components/         # 可复用组件
│       └── navbar.html
└── static/                 # 静态资源
    ├── css/
    ├── js/
    └── img/
```

### 6.3 模板渲染规范

```python
# ✅ 正确: 注入 request 对象 + 业务数据
from fastapi.templating import Jinja2Templates
from gateway.middleware.auth import request_context

templates = Jinja2Templates(directory="gateway/templates")

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    ctx = request_context.get()
    return templates.TemplateResponse("pages/index.html", {
        "request": request,            # MUST: 供 url_for 使用
        "trace_id": ctx.get("trace_id"),
        "user_id": ctx.get("user_id"),
        "workflows": await get_workflow_list(),  # 业务数据
    })
```

### 6.4 Jinja2 模板约束

```html
<!-- ✅ 正确: 继承 base.html -->
{% extends "base.html" %}
{% block content %}
  {% for wf in workflows %}
    <tr>
      <td>{{ wf.name }}</td>
      <td>{{ wf.status }}</td>
    </tr>
  {% endfor %}
{% endblock %}

<!-- ❌ 禁止: 模板中调用 LLM / 数据库 -->
<!-- 数据必须从路由函数注入，模板只负责渲染 -->
```

### 6.5 静态文件挂载规范

```python
# 在 app.py 的 create_app() 中统一挂载
from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory="gateway/static"), name="static")
```

- **MUST**: 挂载路径统一为 `/static`
- **MUST**: 模板中引用使用 `{{ url_for('static', path='css/main.css') }}`
- **MUST NOT**: 硬编码静态资源路径 `href="/static/css/main.css"`
- **MUST**: `StaticFiles` 在 `create_app()` 中挂载，不在路由模块中

### 6.6 鉴权兼容

- `/static/*` 路径不经过 AuthMiddleware（挂载在 app 上，由 Starlette 独立处理）
- 公开页面（登录页等）通过路由函数中显式跳过鉴权
- 管理后台页面 → 由中间件自动鉴权

---

## 7. 编码规范

### 7.1 路由函数签名

```python
# ✅ 推荐: 依赖注入
async def run_workflow(
    request: RunRequest,
    executor: GraphExecutor = Depends(get_executor),
) -> RunResponse: ...

# ✅ 推荐: 显式返回类型
async def health_check() -> dict: ...

# ❌ 禁止: 路由函数中直接实例化 executor
async def run_workflow(request: RunRequest):
    executor = GraphExecutor(...)  # 不要这样做
```

### 7.2 错误处理模板

```python
try:
    result = await executor.run(...)
    return RunResponse(...)
except AppException as e:
    raise HTTPException(status_code=e.status_code, detail=e.detail)
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
```

### 7.3 Import 规范

```python
# ✅ 正确: 从子模块的公开接口 import
from orchestrator.engine.executor import GraphExecutor
from common.models.schemas import RunRequest
from common.exceptions.base import AppException

# ❌ 禁止: 跨层直接 import 内部模块
from orchestrator.graphs.customer_service import CustomerServiceGraph  # NO
from capabilities.agents.base import BaseAgent                        # NO
```

---

## 8. 测试要求

### 8.1 测试范围

| 测试对象 | 测试类型 | 覆盖重点 |
|----------|---------|---------|
| `app.py` | 单元 | FastAPI app 创建、中间件注册 |
| `routes/` | 单元 | 每个端点的正常/异常/边界 |
| `routes/` | 积分 | 端到端（Mock 执行器），SSE 流式测试 |
| `routes/page_routes.py` | 单元 | 模板渲染、数据注入、静态文件路径 |
| `templates/` | 集成 | 模板语法正确性、循环/条件渲染 |
| `middleware/auth.py` | 单元 | 无 token / 无效 token / 有效 token |
| `middleware/rate_limiter.py` | 单元 | 限流触发 / 滑动窗口重置 |

### 8.2 测试约束

- **MUST** 使用 `httpx.AsyncClient` + `pytest-asyncio`
- **MUST** Mock `GraphExecutor` — 集成测试关注 HTTP 层，不测试编排逻辑
- **MUST** 覆盖 SSE 流式端点

```python
# 示例: 流式端点测试
async def test_stream(client):
    async with client.stream("POST", "/api/v1/stream", json={...}) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            assert line.startswith("data: ")
```
