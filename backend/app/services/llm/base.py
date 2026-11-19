from __future__ import annotations

import abc


class LLMClient(abc.ABC):
    """可插拔大模型客户端。所有上层逻辑只依赖这个接口。"""

    name: str = "base"

    @abc.abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """给定对话消息（OpenAI 风格），返回文本回复。"""

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        """要求模型返回 JSON 文本（由调用方解析）。"""

        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)
