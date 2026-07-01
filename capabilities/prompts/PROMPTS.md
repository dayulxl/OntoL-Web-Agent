# PROMPTS.md — 提示词管理规范

> **定位**: `PromptRegistry` 是所有 LLM 提示词的唯一来源。Agent 系统提示词和 Chain 模板都从文件加载，不硬编码在 Python 源码中。

**目录**: [文件清单](#1-文件清单) | [设计原则](#2-设计原则) | [PromptsRegistry 契约](#3-promptregistry-契约) | [新增/修改提示词](#4-新增修改提示词) | [编码规范](#5-编码规范) | [测试要求](#6-测试要求)

---

## 1. 文件清单

```
capabilities/prompts/
├── __init__.py
├── registry.py              # PromptRegistry — 提示词加载/缓存/回退
├── agents/                  # Agent 系统提示词 (.txt)
│   ├── master.txt           # MasterAgent 意图识别调度提示词
│   ├── research.txt
│   ├── coding.txt
│   ├── route_planning.txt   # RoutePlanningAgent 航路规划提示词
│   └── strike_decision.txt  # StrikeDecisionAgent 打击决策提示词
└── chains/                  # Chain 提示词模板 (.txt)
    ├── rag.txt
    └── summary.txt
```

| 文件 | 角色 |
|------|------|
| `registry.py` | `PromptRegistry` — 类级单例，从文件加载提示词，带缓存和内建回退 |
| `agents/*.txt` | Agent 系统提示词 — 纯文本，角色描述 + 行为约束 |
| `chains/*.txt` | Chain 提示词模板 — 使用 `{variable}` 占位符，兼容 LangChain `from_template()` |

---

## 2. 设计原则

| 原则 | 说明 |
|------|------|
| **文件即源** | `.txt` 文件是提示词的唯一事实来源，Python 代码只是加载器 |
| **代码有回退** | 文件缺失时使用内置默认值，确保程序不崩溃 |
| **热更新可控** | 调用 `PromptRegistry.reload()` 即可从文件重新加载，配合 `DynamicConfig` 可实现无重启更新 |
| **非技术人员友好** | 修改 `.txt` 文件不需要懂 Python，运营/产品可直接编辑 |
| **版本可追溯** | `.txt` 文件纳入 Git，每次修改都有 diff 记录 |

---

## 3. PromptRegistry 契约

### 3.1 公共方法

```python
class PromptRegistry:
    # Agent 提示词
    @classmethod
    def get_agent(cls, name: str) -> str: ...

    # Chain 模板
    @classmethod
    def get_chain_template(cls, name: str) -> str: ...
    @classmethod
    def get_chain_prompt(cls, name: str) -> ChatPromptTemplate: ...

    # 缓存管理
    @classmethod
    def reload(cls, name: Optional[str] = None) -> None: ...

    # 列出可用
    @classmethod
    def list_agents(cls) -> list[str]: ...
    @classmethod
    def list_chains(cls) -> list[str]: ...
```

### 3.2 加载优先级

```
文件加载 (.txt)  >  内置默认值 (Python 字典)
       │                    │
       └─────────┬──────────┘
                 ▼
            内存缓存 (_agent_cache / _chain_cache)
                 │
                 ▼
             返回给调用方
```

### 3.3 缓存行为

- **首次调用**时从文件加载，写入缓存
- **后续调用**直接返回缓存（不重新读磁盘）
- **`reload()`** 清空缓存，下次调用时重新读取文件
- **`reload()` 未调用时**，修改 `.txt` 不会生效（重启才会）

---

## 4. 新增/修改提示词

### 4.1 修改现有提示词

```bash
# 直接编辑文件即可
vim capabilities/prompts/agents/research.txt

# 若需立即生效（不重启）：
# 在程序中调用 PromptRegistry.reload("research")
```

### 4.2 添加新 Agent 提示词

1. 创建 `capabilities/prompts/agents/my_agent.txt`
2. 在 `PromptRegistry._agent_default()` 中添加对应的回退默认值
3. Agent 类中通过 `PromptRegistry.get_agent("my_agent")` 读取

### 4.3 添加新 Chain 模板

1. 创建 `capabilities/prompts/chains/my_chain.txt`
2. 使用 `{variable_name}` 占位符
3. 在 `PromptRegistry._chain_default()` 中添加回退默认值

---

## 5. 编码规范

### 5.1 Agent 提示词文件格式

```
你是一个 <角色描述>。你的职责是：
1. <职责1>
2. <职责2>
...
当信息不足时，<行为指引>。
```

### 5.2 Chain 模板文件格式

```
<角色/场景描述>

上下文:
{context}

<其他变量>: {variable_name}

指令:
```

### 5.3 Python 调用规范

```python
# ✅ 正确: 从 PromptRegistry 加载
from capabilities.prompts.registry import PromptRegistry

prompt_text = PromptRegistry.get_agent("research")
template = PromptRegistry.get_chain_prompt("rag")

# ❌ 错误: 硬编码提示词字符串
prompt_text = """你是一个助手..."""  # 禁止！用 PromptRegistry

# ❌ 错误: 在 Agent/Chain 中直接读文件
with open("some_prompt.txt") as f: ...  # 禁止！用 PromptRegistry
```

---

## 6. 测试要求

| 测试对象 | 类型 | 重点 |
|----------|------|------|
| `get_agent()` | 单元 | 文件存在 → 返回文件内容；文件缺失 → 返回默认值 |
| `get_chain_prompt()` | 单元 | 返回的 `ChatPromptTemplate` 可正常 `ainvoke` |
| `reload()` | 单元 | 清空缓存后重新从文件读取 |
| 缓存 | 单元 | 首次调用读文件，第二次命中缓存 |
| 所有现有 `.txt` 文件 | 验证 | 文件内容非空、编码 UTF-8 |

```python
def test_agent_prompt_fallback():
    """文件不存在时回退到默认值。"""
    prompt = PromptRegistry.get_agent("nonexistent_agent")
    assert isinstance(prompt, str)
    assert len(prompt) > 0

def test_chain_prompt_valid():
    """返回的 ChatPromptTemplate 可正常使用。"""
    prompt = PromptRegistry.get_chain_prompt("rag")
    assert "{context}" in prompt.format(context="test", question="q")
```
