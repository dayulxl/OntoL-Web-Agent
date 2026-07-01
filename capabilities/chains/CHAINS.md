# CHAINS.md — LCEL Chain 子模块约束

> **定位**: 所有 Chain 必须使用 LangChain Expression Language (LCEL) 构建，以保证可测试性、可观测性和流式兼容性。

**目录**: [文件清单](#1-文件清单) | [LCEL 构建约束](#2-lcel-构建约束) | [RAGChain 规范](#3-ragchain-规范) | [SummaryChain 规范](#4-summarychain-规范) | [新增 Chain 规范](#5-新增-chain-规范) | [测试要求](#6-测试要求)

---

## 1. 文件清单

| 文件 | 角色 | 策略 |
|------|------|------|
| `rag_chain.py` | `RAGChain` — 检索增强生成 | 单策略 |
| `summary_chain.py` | `SummaryChain` — 文本摘要 | stuff / map_reduce / refine |

---

## 2. LCEL 构建约束

### 2.1 硬性规则

| 规则 | 说明 |
|------|------|
| **MUST** 使用 `|` 管道符 | 所有 Chain 表达式必须使用 LCEL 管道符构建 |
| **MUST NOT** 子类化 `Chain` | 不继承 `langchain.Chain` 基类，使用 Runnable 组合 |
| **MUST** 惰性初始化 | 不在 `__init__` 中调用 LLM，在首次 `initialize()` 中构建 |
| **MUST** 通过 `ModelInterface` 获取 LLM | 不得在 Chain 中直接实例化 `ChatAnthropic` 等具体类 |

### 2.2 标准模板

```python
class MyChain:
    def __init__(self, model: ModelInterface, ...):
        self.model = model
        self._chain: Runnable = None

    async def initialize(self) -> None:
        """构造 LCEL 管道。"""
        llm = await self.model.get_llm()
        prompt = ChatPromptTemplate.from_template("...")
        self._chain = prompt | llm | StrOutputParser()

    async def invoke(self, **kwargs) -> str:
        """执行 Chain。"""
        if self._chain is None:
            await self.initialize()
        return await self._chain.ainvoke(kwargs)
```

### 2.3 LCEL 管道设计约束

```python
# ✅ 正确: 使用 RunnableParallel 并行获取多个输入
self._chain = (
    RunnableParallel({
        "context": itemgetter("question") | retriever,
        "question": itemgetter("question"),
    })
    | prompt
    | llm
    | StrOutputParser()
)

# ✅ 正确: 使用 RunnablePassthrough 传递原始输入
self._chain = (
    {"input": RunnablePassthrough()}
    | prompt
    | llm
)

# ❌ 错误: 在管道外手动调用 LLM
async def invoke(self, **kwargs):
    context = self.retriever.get_relevant_documents(...)
    response = self.llm.invoke(f"Context: {context}")  # 绕过了 LCEL
```

---

## 3. RAGChain 规范

### 3.1 管道结构

```
用户问题 → 向量检索 → 格式化文档 → 拼接上下文 → LLM 生成 → 输出
```

### 3.2 实现约束

```python
class RAGChain:
    def __init__(self, model: ModelInterface, retriever):
        # retriever: 任何实现了 invoke/ainvoke 的 LangChain 检索器
        # 不关心底层是 Chroma/PGVector/Milvus

    async def query(self, question: str) -> str:
        # 单一入口，返回回答字符串
```

- **MUST**: `retriever` 通过构造函数注入，不得在 Chain 内部创建
- **MUST**: 使用 `_format_docs` 函数拼接文档，不得在 prompt 模板中直接拼接
- **MUST NOT**: 在 Chain 内管理向量库连接

### 3.3 文档格式化

```python
def _format_docs(docs: list) -> str:
    """每个文档附带序号来源标记。"""
    return "\n\n".join(
        f"[来源 {i+1}]: {doc.page_content}"
        for i, doc in enumerate(docs)
    )
```

---

## 4. SummaryChain 规范

### 4.1 策略约束

| 策略 | 适用场景 | 说明 |
|------|---------|------|
| `stuff` | 文本 < 模型上下文窗口 | 一次性传入全部文本 |
| `map_reduce` | 长文本，可并行 | 分段摘要 → 拼接 → 再摘要 |
| `refine` | 长文本，需高质量 | 逐段迭代优化摘要 |

### 4.2 策略切换

```python
class SummaryChain:
    VALID_STRATEGIES = {"stuff", "map_reduce", "refine"}

    def __init__(self, model: ModelInterface, strategy: str = "stuff"):
        if strategy not in self.VALID_STRATEGIES:
            raise ValueError(f"Invalid strategy: {strategy}")
        # 不在 __init__ 中选择具体实现路径
```

---

## 5. 新增 Chain 规范

### 5.1 步骤

1. 在 `chains/` 下新建文件
2. 类命名 `XxxChain`
3. 构造函数只接收依赖（不构建管道）
4. `initialize()` 中构建 LCEL 管道
5. 提供单一入口方法（如 `query()`, `summarize()`）

### 5.2 必须遵守

```python
# ✅ 必须
class NewChain:
    async def initialize(self): ...   # 惰性构建
    async def invoke(self, **kwargs): # 包含惰性初始化检查

# ❌ 禁止
class NewChain(Chain):               # 不继承 langchain Chain
class NewChain:
    def __init__(self):               # 不在构造中构建管道
        self.chain = prompt | llm
```

---

## 6. 测试要求

| 测试对象 | 类型 | 重点 |
|----------|------|------|
| 管道结构 | 单元 | 验证 Runnable 序列正确（`_chain.steps` 或 `_chain.get_graph()`） |
| RAG query | 单元 | Mock LLM + retriever，验证文档格式化和 prompt 构造 |
| Summary 各策略 | 单元 | 每个策略的执行路径 |
| 流式输出 | 集成 | 验证 astream 可用 |

```python
async def test_rag_chain(mock_model, mock_retriever):
    chain = RAGChain(model=mock_model, retriever=mock_retriever)
    answer = await chain.query("test question")
    assert isinstance(answer, str)
    assert len(answer) > 0
```
