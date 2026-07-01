# MODELS.md — 模型抽象层子模块约束

> **定位**: 通过 `models.yaml` 集中管理所有模型配置，按类型分组。`ModelFactory` 统一创建各类模型实例。

**目录**: [文件清单](#1-文件清单) | [模型类型体系](#2-模型类型体系) | [models.yaml 规范](#3-modelsyaml-规范) | [ModelFactory 规范](#4-modelfactory-规范) | [新增模型类型](#5-新增模型类型) | [编码规范](#6-编码规范) | [测试要求](#7-测试要求)

---

## 1. 文件清单

| 文件 | 角色 |
|------|------|
| `models.yaml` | **唯一配置来源** — 按 7 种类型分组，涵盖 3 个提供商的 33 个模型 |
| `interfaces.py` | `ModelInterface` — LLM / Vision 模型的抽象接口 |
| `factory.py` | `ModelFactory` — 按类型+名称路由，从 YAML 读取参数 |

---

## 2. 模型类型体系

```
models.yaml
├── 1. llm          大语言模型 (Chat / Completion)     → 17 个
│     anthropic:  claude-opus-4-8, claude-sonnet-4-6, claude-haiku-4-5
│     openai:     gpt-4o, gpt-4o-mini, o1-pro, o3-mini
│     custom:     qwen3-72b, deepseek-v3, deepseek-v4-pro, deepseek-v4-flash, llama-4-maverick, ollama-default
│     llama_cpp:  qwen3-72b, llama-4-maverick, deepseek-v3, any-model, qwen3.6-27b
│
├── 2. embedding    嵌入式 / 向量化模型                 → 10 个
│     openai:     text-embedding-3-large, text-embedding-3-small, text-embedding-ada-002
│     anthropic:  voyage-3-large, voyage-3, voyage-code-3
│     custom:     bge-m3, bge-large-zh, gte-qwen2-7b-instruct, nomic-embed-text
│     llama_cpp:  bge-m3, nomic-embed-text
│
├── 3. reranker     重排序模型                          → 3 个
│     custom:     bge-reranker-v2-m3, bge-reranker-large, cohere-rerank-v3
│
├── 4. tts          文字转语音 (Text-to-Speech)        → 2 个
│     openai:     tts-1, tts-1-hd
│
├── 5. stt          语音转文字 (Speech-to-Text)        → 1 个
│     openai:     whisper-1
│
├── 6. vision       视觉 / 多模态                       → 4 个
│     anthropic:  claude-opus-4-8, claude-sonnet-4-6
│     openai:     gpt-4o, gpt-4o-mini
│
└── 7. image        图片生成                            → 2 个
      openai:     dall-e-3, dall-e-2
```

### 模型可跨类型复用

同一模型可出现在多个类型中。例如 GPT-4o 同时属于 `llm` 和 `vision`；Claude 同时属于 `llm` 和 `vision`。每种类型下该模型可配置不同的参数。

---

## 3. models.yaml 规范

### 3.1 文件结构

```yaml
# 全局默认
default_llm: "deepseek-v4-pro"
default_embedding: "text-embedding-3-large"

# 类型 → 提供商 → 模型列表
<model_type>:
  <provider_key>:
    provider: anthropic | openai | openai_compatible   # SDK 路由
    api_key_env: ENV_VAR_NAME                          # 文档用，标识密钥来源
    base_url_env: ENV_VAR_NAME                         # (仅 custom)
    models:
      <model_name>:
        <param>: <value>                               # 模型特定参数
```

### 3.2 新增模型

在对应的 `models.yaml` 类型/提供商下添加一行即可，**不需要改 Python 代码**：

```yaml
llm:
  custom:
    models:
      my-new-model:           # ← 加这一行
        temperature: 0
        max_tokens: 8192
```

添加后可通过 `ModelFactory.list_by_type("llm")` 立即看到。

### 3.3 配置约束

| 规则 | 说明 |
|------|------|
| **MUST** 每个模型有默认参数 | temperature / max_tokens / dimensions 等，防止 SDK 默认值不确定 |
| **MUST** API Key 不写入 YAML | 通过 `api_key_env` 引用环境变量名，实际值由 `Settings` 读取 |
| **MUST NOT** 删除正在使用的模型 | 先确认无 Agent/Chain 引用，再删除 |
| **MUST** 跨类型复用模型时参数可不同 | `llm/gpt-4o` 和 `vision/gpt-4o` 可配不同的 max_tokens |

---

## 4. ModelFactory 规范

### 4.1 公共方法

```python
class ModelFactory:
    # ── 按类型创建 ──
    def create_llm(name?) -> ModelInterface          # Chat / Completion
    def create_embedding(name?) -> Embeddings        # 向量化
    def create_reranker(name?) -> dict               # 重排序
    def create_tts(name?) -> dict                    # 文字转语音
    def create_stt(name?) -> dict                    # 语音转文字
    def create_vision(name?) -> ModelInterface       # 多模态
    def create_image(name?) -> dict                  # 图片生成

    # ── 查询 ──
    def list_by_type(type) -> list[str]              # 某类型下的所有模型名
    def list_types() -> list[str]                    # 所有类型: [llm, embedding, ...]
    def model_info(type, name) -> Optional[dict]     # 模型完整配置

    # ── 管理 ──
    def reload_config() -> None                      # 重新加载 YAML + 清空缓存
```

### 4.2 路由逻辑

```
create_<type>(model_name)
        │
        ▼
  查找 models.yaml → <type> → 遍历 provider → 匹配 model_name
        │
        ├── provider = anthropic → langchain_anthropic
        ├── provider = openai    → langchain_openai
        └── provider = openai_compatible → langchain_openai (custom base_url)
```

### 4.3 实例缓存

- **MUST**: 相同 `(type, model_name)` 返回同一实例
- **MUST**: 不同 `type` 下同名模型创建不同实例（可能参数不同）
- `reload_config()` 清空全部缓存

---

## 5. 新增模型类型

### 步骤

1. 在 `models.yaml` 中添加新的顶级类型：
   ```yaml
   classification:       # 新类型
     custom:
       provider: openai_compatible
       models:
         bge-classifier:
           threshold: 0.8
   ```

2. 在 `ModelFactory` 中添加创建方法：
   ```python
   def create_classifier(self, model_name=None):
       return self._create_classifier_model(model_name or "bge-classifier")

   def _create_classifier_model(self, model_name):
       # 实现逻辑
       ...
   ```

3. 在本文档的类型体系图中更新

---

## 6. 编码规范

### 6.1 Python 调用

```python
# ✅ 正确: 通过工厂创建，从 YAML 读取参数
factory = ModelFactory()
llm = factory.create_llm("claude-sonnet-4-6")
embeddings = factory.create_embedding("text-embedding-3-large")

# ✅ 正确: 列出可用模型供用户选择
models = factory.list_by_type("llm")

# ❌ 错误: 绕过工厂直接创建
from langchain_anthropic import ChatAnthropic
llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)  # 硬编码参数

# ❌ 错误: 从环境变量直接读取 API Key
api_key = os.getenv("ANTHROPIC_API_KEY")  # 应通过 get_settings()
```

### 6.2 后端配置隔离

- LLM 参数存储在 `models.yaml` 中（不公开给前端）
- API Key 存储在环境变量 / K8s Secret 中
- 前端 / 管理后台只需知道模型列表（`list_by_type()` / `model_info()`）

---

## 7. 测试要求

| 测试对象 | 类型 | 重点 |
|----------|------|------|
| `list_types()` | 单元 | 返回 7 个类型: llm, embedding, reranker, tts, stt, vision, image |
| `list_by_type(type)` | 单元 | 每种类型返回正确的模型列表 |
| `create_llm()` | 单元 | 默认模型可正常创建 |
| `model_info()` | 单元 | 返回 provider、params 等完整信息 |
| `reload_config()` | 单元 | 清空缓存后可重新加载 |
| 每个适配器 | 单元 | Mock SDK，验证参数传递正确 |
