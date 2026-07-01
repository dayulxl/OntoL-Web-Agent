# TESTS.md — 测试规范与约束

> **定位**: 定义项目的测试策略、覆盖要求、Mock 规范和 CI 流程。所有测试代码位于 `tests/` 目录。

**目录**: [文件清单](#1-文件清单) | [测试策略](#2-测试策略) | [测试工具约束](#3-测试工具约束) | [Mock 规范](#4-mock-规范) | [命名与组织](#5-命名与组织) | [CI 要求](#6-ci-要求)

---

## 1. 文件清单

| 文件 | 角色 |
|------|------|
| `__init__.py` | 空文件，标记包 |
| `conftest.py` | 全局 fixtures (mock_settings, mock_llm, sample_graph_state) |

---

## 2. 测试策略

### 2.1 测试金字塔

```
         ┌──────┐
         │ E2E  │  ← 关键路径 (1-2 条)
         └──────┘
       ┌──────────┐
       │ 集成测试  │  ← 层间契约 (核心场景)
       └──────────┘
    ┌────────────────┐
    │    单元测试     │  ← 每个函数/类 (主力)
    └────────────────┘
```

### 2.2 各层测试重点

| 层 | 单元测试 | 集成测试 | 不测试的 |
|----|---------|---------|---------|
| gateway | 中间件逻辑、路由处理 | 完整 HTTP 请求 (Mock executor) | LangChain/LangGraph 框架内部 |
| orchestrator | 图结构、节点方法、路由条件 | 完整图执行 (MemorySaver) | Postgres checkpoint 机制本身 |
| capabilities | Agent/Chain/Tool 的输入输出 | Agent + Tool 联合执行 | LLM API 的真实网络调用 |
| infrastructure | 客户端封装、参数传递 | 真实连接池行为 (testcontainers) | asyncpg/redis-py 内部 |
| common | Settings 解析、异常 status_code、schema 校验 | — | Pydantic/structlog 内部 |

### 2.3 覆盖率要求

| 指标 | 最低 | 目标 |
|------|------|------|
| 行覆盖率 | 80% | 90%+ |
| 分支覆盖率 | 70% | 85%+ |
| 关键路径覆盖率 | 100% | 100% |

关键路径定义:
- `POST /api/v1/run` → 正常返回 200
- `POST /api/v1/run` → 异常返回 4xx/5xx
- `/health` / `/ready` → 正常/异常
- 条件路由的每个分支
- 工具注册/获取

---

## 3. 测试工具约束

| 工具 | 用途 | 版本 |
|------|------|------|
| pytest | 测试框架 | 8.0+ |
| pytest-asyncio | 异步测试支持 | 0.24+ |
| pytest-cov | 覆盖率报告 | 5.0+ |
| httpx | HTTP 客户端 (gateway 测试) | 0.28+ |
| unittest.mock | Mock 对象 | 标准库 |

### 3.1 配置

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"      # 自动检测 async 测试函数
testpaths = ["tests"]
addopts = "-v --cov=. --cov-report=term-missing"
```

### 3.2 约束

| 规则 | 说明 |
|------|------|
| **MUST** 使用 `pytest-asyncio` | 异步测试函数: `async def test_...` |
| **MUST** `asyncio_mode = "auto"` | 不需要 `@pytest.mark.asyncio` 装饰器 |
| **MUST NOT** 用 `time.sleep` | 异步测试中用 `await asyncio.sleep` |
| **MUST** conftest fixtures 放 `tests/conftest.py` | 全局共享，不放各模块 |

---

## 4. Mock 规范

### 4.1 允许 Mock 的对象

```python
# ✅ 允许 Mock
- LLM 实例 (避免真实 API 调用)
- 数据库连接 (避免需要真实 Postgres/Redis)
- 外部 API 调用
- 文件系统操作

# ❌ 不允许 Mock
- 被测函数本身
- Pydantic 模型 (它们就是数据)
```

### 4.2 Mock 分层

| 层 | 集成测试 Mock 策略 |
|----|-------------------|
| gateway 测试 | Mock `GraphExecutor`，不 Mock HTTP |
| orchestrator 测试 | Mock 能力层的 LLM/Tool，使用 MemorySaver (不用 Postgres) |
| capabilities 测试 | Mock LLM，不 Mock ToolRegistry |
| infrastructure 测试 | Mock 驱动库 (asyncpg, redis) |

### 4.3 Fixture 规范

```python
# conftest.py

@pytest.fixture
def mock_settings():
    """所有测试共享: 提供默认配置。"""
    return Settings(postgres_uri="postgresql://test:test@localhost/test", ...)

@pytest.fixture
def mock_llm():
    """Mock LLM — 返回固定文本。"""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="mock response"))
    llm.get_num_tokens = MagicMock(return_value=42)
    return llm
```

---

## 5. 命名与组织

### 5.1 文件命名

```
tests/
├── conftest.py                          # 全局 fixtures
├── gateway/
│   ├── test_app.py                      # 测试 gateway/app.py
│   ├── test_routes.py                   # 测试 gateway/routes/
│   └── middleware/
│       ├── test_auth.py
│       └── test_rate_limiter.py
├── orchestrator/
│   ├── graphs/
│   │   ├── test_customer_service.py
│   │   └── test_risk_control.py
│   ├── test_executor.py
│   └── test_router.py
├── capabilities/
│   ├── agents/
│   │   └── test_base_agent.py
│   ├── tools/
│   │   └── test_registry.py
│   └── models/
│       └── test_factory.py
├── infrastructure/
│   ├── test_postgres.py
│   └── test_redis.py
└── common/
    ├── test_settings.py
    └── test_exceptions.py
```

### 5.2 命名约定

| 对象 | 约定 | 示例 |
|------|------|------|
| 测试文件 | `test_<module>.py` | `test_routes.py` |
| 测试函数 | `test_<what>_<condition>` | `test_run_workflow_invalid_auth` |
| 测试类 (可选) | `Test<ClassName>` | `TestGraphExecutor` |

---

## 6. CI 要求

### 6.1 检查项

```bash
# 1. 代码格式
poetry run ruff check .
poetry run black --check .

# 2. 类型检查
poetry run mypy .

# 3. 测试 + 覆盖率
poetry run pytest --cov=. --cov-report=xml --cov-fail-under=80

# 4. 依赖安全检查
poetry run pip-audit
```

### 6.2 约束

- **MUST**: PR 合并前 CI 全部通过
- **MUST**:覆盖率不得下降
- **MUST**: `ruff` 和 `black` 零告警
- 建议: 本地提交前运行 `poetry run pytest` 确保不引入回归
