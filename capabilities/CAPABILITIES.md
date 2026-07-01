# CAPABILITIES.md — LangChain 能力层约束

> **定位**: 本层封装所有可复用的 AI 能力单元。Agent、Chain、Tool、Memory、Model、Prompts 六个子模块各自独立，通过抽象接口组合。

**目录**: [子模块总览](#1-子模块总览) | [跨子模块约束](#2-跨子模块约束) | [公共接口](#3-公共接口) | [依赖边界](#4-依赖边界) | [子模块文档](#5-子模块文档)

---

## 1. 子模块总览

```
capabilities/
├── agents/        → [AGENTS.md](agents/AGENTS.md)
├── chains/        → [CHAINS.md](chains/CHAINS.md)
├── tools/         → [TOOLS.md](tools/TOOLS.md)
├── memory/        → [MEMORY.md](memory/MEMORY.md)
├── models/        → [MODELS.md](models/MODELS.md)
└── prompts/       → [PROMPTS.md](prompts/PROMPTS.md)
```

| 子模块 | 职责 | 对外出口 |
|--------|------|---------|
| agents | Agent 定义与执行 (ReAct) + 调度 | `BaseAgent` 抽象类, `MasterAgent` 总调度 |
| chains | LCEL Chain 构建 | `RAGChain`, `SummaryChain` |
| tools | 工具注册/发现/MCP 导出 | `ToolRegistry` 类级单例 |
| memory | 短期(Redis) / 长期(向量库) / 图记忆(Neo4j) | `ShortTermMemory`, `LongTermMemory`, `GraphMemory` |
| models | 多模型提供商抽象 | `ModelInterface` 抽象 + `ModelFactory` 工厂 |
| prompts | 提示词集中管理与版本化 | `PromptRegistry` 类级单例 |

---

## 2. 跨子模块约束

### 2.1 子模块间通信规则

```
agents/
  ├── 可依赖 → models/      (通过 ModelInterface)
  ├── 可依赖 → tools/       (通过 ToolRegistry)
  ├── 可依赖 → memory/      (通过 ShortTermMemory / LongTermMemory)
  └── 不可依赖 → chains/    (Agent 内部使用 ReAct，不使用 Chain)

chains/
  ├── 可依赖 → models/      (通过 ModelInterface)
  └── 不可依赖 → agents/, tools/, memory/

tools/
  └── 不可依赖 → 任何其他子模块 (工具是纯函数)

prompts/
  ├── 可依赖 → common/config/     (仅 settings，文件路径等)
  └── 不可依赖 → agents/, chains/, tools/, memory/, models/ (提示词是数据，不调用任何能力)

memory/
  ├── 可依赖 → infrastructure/ (Redis, 向量库客户端)
  └── 不可依赖 → agents/, chains/, tools/, models/

models/
  ├── 可依赖 → common/config/
  └── 不可依赖 → 任何其他子模块
```

### 2.2 组合规则

- Agent 可以包含 Tool（通过 `_get_tools()` 注入）
- Agent 可以使用 Memory（通过构造函数注入）
- Chain 不得包含 Agent
- Tool 不得包含 Agent 或 Chain

---

## 3. 公共接口

### 3.1 对外暴露

```python
# 编排层通过以下抽象接口使用能力层:
from capabilities.agents.base import BaseAgent
from capabilities.tools.registry import ToolRegistry
from capabilities.models.interfaces import ModelInterface

# 基础设施层不依赖能力层
```

### 3.2 抽象层次

```
                  BaseAgent (ABC)           ← 编排层使用此抽象
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ResearchAgent  CodingAgent   ... (新 Agent)
```

```
                  ModelInterface (ABC)      ← 整个能力层使用此抽象
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    AnthropicModel OpenAIModel OpenAICompatible
```

---

## 4. 依赖边界

```
capabilities/
  ├── 可依赖 → common/            (config, exceptions, utils)
  ├── 可依赖 → infrastructure/    (cache/redis, db/postgres 等客户端函数)
  └── 不可依赖 → gateway/, orchestrator/

特别说明:
  - capabilities/ 中的代码不应知道 gateway/ 或 orchestrator/ 的存在
  - 此层的异常应使用 ModelError (common/exceptions/base.py)
  - 此层不应处理 HTTP 概念（status_code, request, response）
```

---

## 5. 子模块文档

每个子模块有独立的约束文档：

| 文档 | 内容 |
|------|------|
| [agents/AGENTS.md](agents/AGENTS.md) | Agent 基类规范、ReAct 实现约束、新增 Agent 流程 |
| [chains/CHAINS.md](chains/CHAINS.md) | LCEL Chain 构建约束、RAG/Summary 策略规范 |
| [tools/TOOLS.md](tools/TOOLS.md) | ToolRegistry 注册规范、Tool 实现约束、MCP 兼容 |
| [memory/MEMORY.md](memory/MEMORY.md) | 短期/长期记忆存储策略与接口约束 |
| [models/MODELS.md](models/MODELS.md) | ModelInterface 规范、ModelFactory 路由规则、新增提供商 |
| [prompts/PROMPTS.md](prompts/PROMPTS.md) | PromptRegistry 规范、提示词文件管理、热更新策略 |
