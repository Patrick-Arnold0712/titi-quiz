from __future__ import annotations

from app.services.llm.base import LLMClient


class MockClient(LLMClient):
    """离线占位客户端。

    不联网、不花钱，返回可预测的占位内容，用于先把整条流水线跑通。
    配置真实 provider 后即可无缝替换。
    """

    name = "mock"

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        last = messages[-1]["content"] if messages else ""
        preview = last[:60].replace("\n", " ")
        return (
            "[mock 占位回复] 当前未接入真实模型。"
            f"收到请求：{preview}..."
            " 配置 TTK_LLM_PROVIDER=openai_compat 并填入 base_url/key/model 后生效。"
        )

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        return "[]"
