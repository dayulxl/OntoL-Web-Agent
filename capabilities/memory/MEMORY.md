# MEMORY.md — 记忆管理子模块约束

> **定位**: 提供短期（会话级）和长期（跨会话）两种记忆管理。短期记忆基于 Redis 自动过期，长期记忆基于向量数据库语义检索。

**目录**: [文件清单](#1-文件清单) | [短期记忆规范](#2-短期记忆规范-shorttermmemory) | [长期记忆规范](#3-长期记忆规范-longtermmemory) | [记忆类型选择指南](#4-记忆类型选择指南) | [编码规范](#5-编码规范) | [测试要求](#6-测试要求)

---

## 1. 文件清单

| 文件 | 角色 | 存储后端 |
|------|------|---------|
| `short_term.py` | `ShortTermMemory` — 会话级对话历史 | Redis |
| `long_term.py` | `LongTermMemory` — 跨会话语义记忆 | 向量数据库 |
| `graph_memory.py` | `GraphMemory` — 知识图谱存储与检索 | Neo4j |

---

## 2. 短期记忆规范 (ShortTermMemory)

### 2.1 设计约束

| 维度 | 值 | 原因 |
|------|-----|------|
| 存储 | Redis | 低延迟、TTL 自动过期 |
| 隔离 | 按 `session_id` | 不同会话/用户互不干扰 |
| 过期 | TTL 30 分钟 (默认) | 对话超时自动清理 |
| 截断 | 最近 40 条消息 (默认) | 防止上下文窗口溢出 |
| 持久化 | 不需要 | 会话级数据，丢失可接受 |

### 2.2 公共接口

```python
class ShortTermMemory:
    def __init__(self, redis_url: str, ttl: int = 1800, max_messages: int = 40):

    def get_history(self, session_id: str) -> RedisChatMessageHistory:
        """获取底层 LangChain MessageHistory 对象。"""

    async def get_messages(self, session_id: str) -> list:
        """获取会话消息列表（已截断）。"""

    async def add_message(self, session_id: str, message) -> None:
        """追加一条消息。"""

    async def clear(self, session_id: str) -> None:
        """清除会话所有消息。"""
```

### 2.3 使用约束

```python
# ✅ 正确: 通过 session_id 隔离
memory = ShortTermMemory(redis_url="redis://...")
await memory.add_message("user-123:session-456", HumanMessage(...))
await memory.add_message("user-789:session-000", HumanMessage(...))
# 两个会话完全隔离

# ❌ 错误: 使用全局 session_id
await memory.add_message("global", message)  # 所有用户共享 = 信息泄露
```

---

## 3. 长期记忆规范 (LongTermMemory)

### 3.1 设计约束

| 维度 | 值 | 原因 |
|------|-----|------|
| 存储 | 向量数据库 (Chroma / PGVector / Milvus) | 支持语义相似度搜索 |
| 隔离 | 按 `user_id` 过滤 | 不同用户的记忆互不可见 |
| 持久化 | 必须持久化 | 跨会话需要保留 |
| 索引 | 文本 embedding + metadata filter | 高效检索 |

### 3.2 公共接口

```python
class LongTermMemory:
    def __init__(self, vector_store):
        # vector_store: LangChain 兼容的向量存储实例

    async def store(self, user_id: str, content: str, metadata=None) -> None:
        """存储一条长期记忆。"""

    async def retrieve(self, user_id: str, query: str, k: int = 5) -> list:
        """语义检索相关记忆。"""

    async def delete(self, user_id: str, memory_id: str) -> None:
        """删除指定记忆。"""

    async def summarize(self, user_id: str, query: str) -> str:
        """基于检索结果生成总结。"""
```

### 3.3 使用约束

```python
# ✅ 正确: vector_store 从外部注入
from langchain_chroma import Chroma

vector_store = Chroma(
    embedding_function=my_embedding,
    persist_directory="./chroma_db",
)
memory = LongTermMemory(vector_store=vector_store)

# ❌ 错误: 在 LongTermMemory 内部创建 vector_store
class LongTermMemory:
    def __init__(self):
        self.vector_store = Chroma(...)  # 硬编码了 Chroma，无法切换
```

- **MUST**: `vector_store` 通过构造函数注入，内部不创建向量库实例
- **MUST NOT**: 在 memory 模块中管理 embedding 模型（由调用方提供）
- **MUST**: `retrieve()` 始终使用 `filter={"user_id": user_id}` 确保隔离

---

## 4. 记忆类型选择指南

| 场景 | 使用 | 原因 |
|------|------|------|
| 单次对话上下文 | `ShortTermMemory` | 会话结束后无需保留 |
| 多轮对话 | `ShortTermMemory` (相同 session_id) | TTL 期间自动维持 |
| 用户偏好/历史 | `LongTermMemory` | 跨会话持久化 |
| 知识库查询 | `LongTermMemory` (向量检索) | 语义匹配 |
| 用户反馈/评价 | `LongTermMemory` | 需要持久留存 |

---

## 5. 编码规范

### 5.1 ShortTermMemory

```python
# ✅ 正确: 使用 LangChain RedisChatMessageHistory
from langchain_community.chat_message_histories import RedisChatMessageHistory

def get_history(self, session_id: str) -> RedisChatMessageHistory:
    return RedisChatMessageHistory(
        session_id=session_id,
        url=self.redis_url,
        ttl=self.ttl,
    )

# ❌ 错误: 自己拼接 Redis key 存储消息
async def add_message(self, session_id, message):
    await redis.set(f"chat:{session_id}:{idx}", str(message))  # 破坏 LangChain 兼容性
```

### 5.2 LongTermMemory

```python
# ✅ 正确: 使用 vector_store 的异步方法
await self.vector_store.aadd_texts(texts=[content], metadatas=[meta])
results = await self.vector_store.asimilarity_search(query, k=k, filter={"user_id": user_id})

# ❌ 错误: 使用同步方法
self.vector_store.add_texts(...)  # 阻塞 event loop
```

---

## 6. 测试要求

| 测试对象 | 类型 | 重点 |
|----------|------|------|
| ShortTermMemory | 单元 | Mock RedisChatMessageHistory，验证 add/get/clear |
| ShortTermMemory | 单元 | 验证 TTL 和 max_messages 参数传递正确 |
| LongTermMemory | 单元 | Mock vector_store，验证 store/retrieve/delete |
| LongTermMemory | 单元 | 验证 user_id filter 注入正确 |

```python
async def test_short_term_memory():
    memory = ShortTermMemory(redis_url="redis://test", ttl=60, max_messages=10)
    # Mock RedisChatMessageHistory
    await memory.add_message("session-1", HumanMessage(content="hello"))
    messages = await memory.get_messages("session-1")
    assert len(messages) > 0
```
