from __future__ import annotations

import httpx

from app.services.llm.base import LLMClient


class OpenAICompatClient(LLMClient):
    """OpenAI 兼容协议客户端。

    豆包（火山方舟）、DeepSeek、OpenRouter 免费模型等只要提供
    base_url + api_key + model 即可复用本客户端。
    """

    name = "openai_compat"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 120.0,
    ) -> None:
        if not base_url or not api_key or not model:
            raise ValueError(
                "openai_compat 需要 TTK_LLM_BASE_URL / TTK_LLM_API_KEY / TTK_LLM_MODEL"
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]
