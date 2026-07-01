"""
模型工厂
-------
根据 models.yaml 配置文件创建并缓存各类模型实例，支持多模型类型和多提供商。

配置文件: capabilities/models/models.yaml
模型类型: LLM | Embedding | Reranker | TTS | STT | Vision | Image
"""
import os
from typing import Optional

import yaml

from capabilities.models.interfaces import ModelInterface
from common.config.settings import get_settings


_MODEL_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models.yaml")


def _load_config() -> dict:
    if os.path.isfile(_MODEL_CONFIG_PATH):
        with open(_MODEL_CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


class ModelFactory:
    """
    模型工厂 — 按 类型 (LLM/Embedding/Reranker/...) × 名称 创建模型实例。

    使用方式:
        factory = ModelFactory()

        # LLM
        llm = await factory.create_llm("claude-sonnet-4-6").get_llm()

        # Embedding
        emb = factory.create_embedding("text-embedding-3-large")

        # Reranker
        rrk = factory.create_reranker("bge-reranker-v2-m3")
    """

    def __init__(self, config_path: Optional[str] = None):
        self._settings = get_settings()
        self._config = _load_config()
        if config_path and os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}

        # 各类型的实例缓存:  {(model_name,): instance}
        self._cache: dict[tuple, object] = {}

    # =====================================================================
    # 公共入口
    # =====================================================================

    def create_llm(self, model_name: Optional[str] = None) -> ModelInterface:
        """
        创建 LLM (Chat) 模型。

        支持 'provider::model' 格式来区分同名模型:
          - 'anthropic::claude-sonnet-4-6' → 强制使用 Anthropic provider
          - 'llama_cpp::qwen3-72b'        → 强制使用 llama.cpp 端点
          - 'qwen3-72b'                   → 自动匹配第一个找到的 provider
        """
        provider_key = None
        if model_name and "::" in model_name:
            provider_key, model_name = model_name.split("::", 1)
        return self._create_model("llm", model_name or self._default_for("llm", "claude-sonnet-4-6"), provider_key)

    def create_embedding(self, model_name: Optional[str] = None):
        """创建 Embedding 模型 (返回 LangChain Embeddings 实例)。"""
        return self._create_embedding_model(model_name or self._default_for("embedding", "text-embedding-3-large"))

    def create_reranker(self, model_name: Optional[str] = None):
        """创建 Reranker 模型。"""
        return self._create_reranker_model(model_name or self._default_for("reranker", "bge-reranker-v2-m3"))

    def create_tts(self, model_name: Optional[str] = None):
        """创建 TTS (文字转语音) 模型。"""
        return self._create_tts_model(model_name or self._default_for("tts", "tts-1"))

    def create_stt(self, model_name: Optional[str] = None):
        """创建 STT (语音转文字) 模型。"""
        return self._create_stt_model(model_name or self._default_for("stt", "whisper-1"))

    def create_vision(self, model_name: Optional[str] = None) -> ModelInterface:
        """创建 Vision (多模态) 模型。"""
        return self._create_model("vision", model_name or self._default_for("vision", "claude-sonnet-4-6"))

    def create_image(self, model_name: Optional[str] = None):
        """创建 Image (图片生成) 模型。"""
        return self._create_image_model(model_name or self._default_for("image", "dall-e-3"))

    # =====================================================================
    # 类型 → 提供商 → 模型详情
    # =====================================================================

    def provider_for(self, model_type: str, model_name: str) -> Optional[str]:
        """查找模型所属的 provider key (anthropic / openai / custom)。"""
        providers = self._config.get(model_type, {})
        for pkey, pconf in providers.items():
            if model_name in pconf.get("models", {}):
                return pkey
        return None

    def _params_for(self, model_type: str, model_name: str) -> dict:
        """查找模型的参数配置。"""
        providers = self._config.get(model_type, {})
        for pconf in providers.values():
            if model_name in pconf.get("models", {}):
                return pconf["models"][model_name]
        return {}

    def _provider_config_for(self, model_type: str, model_name: str) -> dict:
        """查找模型的提供商配置。"""
        providers = self._config.get(model_type, {})
        for pconf in providers.values():
            if model_name in pconf.get("models", {}):
                return pconf
        return {}

    def _default_for(self, model_type: str, fallback: str) -> str:
        return self._config.get(f"default_{model_type}") or self._config.get("default_llm") or fallback

    # =====================================================================
    # LLM / Vision — 返回 ChatModel (ModelInterface)
    # =====================================================================

    _LLM_TYPES = {"llm", "vision"}

    def _create_model(self, model_type: str, model_name: str, provider_key: Optional[str] = None) -> ModelInterface:
        cache_key = (model_type, provider_key or "__auto__", model_name)
        if cache_key in self._cache:
            return self._cache[cache_key]

        provider = provider_key or self.provider_for(model_type, model_name)
        if provider is None:
            raise ValueError(f"Model '{model_name}' not found in '{model_type}' section of models.yaml")

        params = self._params_for(model_type, model_name)
        provider_config = self._provider_config_for(model_type, model_name)

        if model_type == "vision" or provider == "anthropic":
            instance = self._build_anthropic_chat(model_name, params, provider)
        elif provider == "openai":
            instance = self._build_openai_chat(model_name, params, provider)
        else:
            instance = self._build_openai_compatible_chat(model_name, params, provider_config)

        self._cache[cache_key] = instance
        return instance

    # ------------------------------------------------------------------
    # LLM 适配器
    # ------------------------------------------------------------------

    def _build_anthropic_chat(self, name: str, params: dict, provider: str) -> ModelInterface:
        from langchain_anthropic import ChatAnthropic

        class _M(ModelInterface):
            _name = name
            _params = params
            _settings = get_settings()
            _llm = None

            async def get_llm(self):
                if self._llm is None:
                    self._llm = ChatAnthropic(
                        model=self._name,
                        api_key=self._settings.anthropic_api_key,
                        temperature=self._params.get("temperature", 0),
                        max_tokens=self._params.get("max_tokens", 4096),
                    )
                return self._llm

            def model_name(self): return self._name

            async def token_count(self, text: str):
                return (await self.get_llm()).get_num_tokens(text)

            async def get_pricing(self):
                return self._params.get("pricing", {"input": 0.0, "output": 0.0})

        return _M()

    def _build_openai_chat(self, name: str, params: dict, provider: str) -> ModelInterface:
        from langchain_openai import ChatOpenAI

        class _M(ModelInterface):
            _name = name
            _params = params
            _settings = get_settings()
            _llm = None

            async def get_llm(self):
                if self._llm is None:
                    self._llm = ChatOpenAI(
                        model=self._name,
                        api_key=self._settings.openai_api_key,
                        temperature=self._params.get("temperature", 0),
                        max_tokens=self._params.get("max_tokens", 4096),
                    )
                return self._llm

            def model_name(self): return self._name

            async def token_count(self, text: str):
                return (await self.get_llm()).get_num_tokens(text)

            async def get_pricing(self):
                return self._params.get("pricing", {"input": 0.0, "output": 0.0})

        return _M()

    def _build_openai_compatible_chat(self, name: str, params: dict, provider_config: dict) -> ModelInterface:
        from langchain_openai import ChatOpenAI

        class _M(ModelInterface):
            _name = name
            _params = params
            _provider_config = provider_config
            _settings = get_settings()
            _llm = None

            async def get_llm(self):
                if self._llm is None:
                    # base_url 优先级: YAML 中的 base_url > 环境变量 CUSTOM_LLM_BASE_URL
                    base_url = (
                        self._provider_config.get("base_url")
                        or self._settings.custom_llm_base_url
                    )
                    api_key = self._settings.custom_llm_api_key or "not-needed"
                    self._llm = ChatOpenAI(
                        model=self._name,
                        base_url=base_url,
                        api_key=api_key,
                        temperature=self._params.get("temperature", 0),
                        max_tokens=self._params.get("max_tokens", 4096),
                    )
                return self._llm

            def model_name(self): return self._name

            async def token_count(self, text: str):
                return (await self.get_llm()).get_num_tokens(text)

            async def get_pricing(self):
                return self._params.get("pricing", {"input": 0.0, "output": 0.0})

        return _M()

    # =====================================================================
    # Embedding
    # =====================================================================

    def _create_embedding_model(self, model_name: str):
        cache_key = ("embedding", model_name)
        if cache_key in self._cache:
            return self._cache[cache_key]

        provider = self.provider_for("embedding", model_name)
        if provider is None:
            raise ValueError(f"Embedding model '{model_name}' not found in models.yaml")

        params = self._params_for("embedding", model_name)
        provider_config = self._provider_config_for("embedding", model_name)

        if provider == "openai":
            from langchain_openai import OpenAIEmbeddings
            instance = OpenAIEmbeddings(
                model=model_name,
                api_key=self._settings.openai_api_key,
                dimensions=params.get("dimensions"),
            )
        elif provider == "anthropic":
            from langchain_voyageai import VoyageAIEmbeddings
            instance = VoyageAIEmbeddings(
                model=model_name,
                voyage_api_key=self._settings.anthropic_api_key,
            )
        else:
            from langchain_openai import OpenAIEmbeddings
            # base_url 优先级: YAML > 环境变量
            base_url = provider_config.get("base_url") or self._settings.custom_llm_base_url
            instance = OpenAIEmbeddings(
                model=model_name,
                base_url=base_url,
                api_key=self._settings.custom_llm_api_key or "not-needed",
                dimensions=params.get("dimensions"),
            )

        self._cache[cache_key] = instance
        return instance

    # =====================================================================
    # Reranker
    # =====================================================================

    def _create_reranker_model(self, model_name: str):
        cache_key = ("reranker", model_name)
        if cache_key in self._cache:
            return self._cache[cache_key]

        provider = self.provider_for("reranker", model_name)
        if provider is None:
            raise ValueError(f"Reranker model '{model_name}' not found in models.yaml")

        params = self._params_for("reranker", model_name)
        provider_config = self._provider_config_for("reranker", model_name)

        base_url = provider_config.get("base_url") or self._settings.custom_llm_base_url
        instance = {
            "model": model_name,
            "top_n": params.get("top_n", 10),
            "provider": provider,
            "base_url": base_url,
            "api_key": self._settings.custom_llm_api_key or "not-needed",
        }

        self._cache[cache_key] = instance
        return instance

    # =====================================================================
    # TTS
    # =====================================================================

    def _create_tts_model(self, model_name: str):
        cache_key = ("tts", model_name)
        if cache_key in self._cache:
            return self._cache[cache_key]

        provider = self.provider_for("tts", model_name)
        if provider is None:
            raise ValueError(f"TTS model '{model_name}' not found in models.yaml")

        params = self._params_for("tts", model_name)

        from openai import AsyncOpenAI

        instance = AsyncOpenAI(api_key=self._settings.openai_api_key)
        wrapped = {
            "client": instance,
            "model": model_name,
            "voice": params.get("voice", "alloy"),
            "format": params.get("format", "mp3"),
            "speed": params.get("speed", 1.0),
        }

        self._cache[cache_key] = wrapped
        return wrapped

    # =====================================================================
    # STT
    # =====================================================================

    def _create_stt_model(self, model_name: str):
        cache_key = ("stt", model_name)
        if cache_key in self._cache:
            return self._cache[cache_key]

        provider = self.provider_for("stt", model_name)
        if provider is None:
            raise ValueError(f"STT model '{model_name}' not found in models.yaml")

        params = self._params_for("stt", model_name)

        from openai import AsyncOpenAI

        instance = AsyncOpenAI(api_key=self._settings.openai_api_key)
        wrapped = {
            "client": instance,
            "model": model_name,
            "language": params.get("language", "zh"),
            "format": params.get("response_format", "text"),
        }

        self._cache[cache_key] = wrapped
        return wrapped

    # =====================================================================
    # Image
    # =====================================================================

    def _create_image_model(self, model_name: str):
        cache_key = ("image", model_name)
        if cache_key in self._cache:
            return self._cache[cache_key]

        provider = self.provider_for("image", model_name)
        if provider is None:
            raise ValueError(f"Image model '{model_name}' not found in models.yaml")

        params = self._params_for("image", model_name)

        from openai import AsyncOpenAI

        instance = AsyncOpenAI(api_key=self._settings.openai_api_key)
        wrapped = {
            "client": instance,
            "model": model_name,
            "size": params.get("size", "1024x1024"),
            "quality": params.get("quality", "standard"),
            "style": params.get("style", "vivid"),
        }

        self._cache[cache_key] = wrapped
        return wrapped

    # =====================================================================
    # 管理
    # =====================================================================

    def list_by_type(self, model_type: str) -> list[str]:
        """列出某类型下所有模型名称。"""
        names = []
        providers = self._config.get(model_type, {})
        for pconf in providers.values():
            names.extend(pconf.get("models", {}).keys())
        return sorted(names)

    def list_types(self) -> list[str]:
        """列出所有模型类型 (llm, embedding, reranker, tts, stt, vision, image)。"""
        return [k for k in self._config if not k.startswith("default_") and isinstance(self._config[k], dict)]

    def model_info(self, model_type: str, model_name: str) -> Optional[dict]:
        """获取模型的完整配置信息。"""
        params = self._params_for(model_type, model_name)
        provider_cfg = self._provider_config_for(model_type, model_name)
        provider_key = self._provider_for(model_type, model_name)
        if not params:
            return None
        return {
            "type": model_type,
            "name": model_name,
            "provider": provider_cfg.get("provider", provider_key),
            "api_key_env": provider_cfg.get("api_key_env", ""),
            "base_url_env": provider_cfg.get("base_url_env", ""),
            "params": params,
        }

    def reload_config(self) -> None:
        """重新加载 models.yaml，清空所有缓存。"""
        self._config = _load_config()
        self._cache.clear()
