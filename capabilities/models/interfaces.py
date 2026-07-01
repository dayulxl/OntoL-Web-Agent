"""
标准化模型接口
------------
定义与 LLM 交互的抽象接口，屏蔽不同模型提供商的差异。
"""
from abc import ABC, abstractmethod

from langchain_core.language_models import BaseChatModel


class ModelInterface(ABC):
    """
    模型接口抽象。

    所有模型适配器必须实现此接口。上层代码（Agent、Chain）依赖此接口，
    通过工厂方法注入具体实现，实现模型的可替换性。
    """

    @abstractmethod
    async def get_llm(self) -> BaseChatModel:
        """返回 LangChain 兼容的 ChatModel 实例。"""
        ...

    @abstractmethod
    def model_name(self) -> str:
        """返回模型名称标识。"""
        ...

    @abstractmethod
    async def token_count(self, text: str) -> int:
        """估算文本的 Token 数量。"""
        ...

    @abstractmethod
    async def get_pricing(self) -> dict:
        """返回模型的定价信息。"""
        ...
