from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.services.llm.base import LLMClient
from app.services.llm.mock import MockClient
from app.services.llm.openai_compat import OpenAICompatClient

# OpenAI 兼容协议的常见平台预设：配好 TTK_LLM_API_KEY 即可用，无需再填 base_url。
PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-7B-Instruct",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5.3-flash",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "doubao": {
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "deepseek/deepseek-chat-v3-0324:free",
    },
}


def resolve_provider(name: str) -> dict[str, str]:
    """把 provider 名字解析成 {base_url, model}（用户显式配置优先）。"""

    settings = get_settings()
    preset = PROVIDER_PRESETS.get(name, {})
    return {
        "base_url": settings.llm_base_url or preset.get("base_url", ""),
        "model": settings.llm_model or preset.get("model", ""),
    }


def create_llm_client() -> LLMClient:
    settings = get_settings()
    provider = (settings.llm_provider or "mock").lower()
    if provider in ("mock", ""):
        return MockClient()
    resolved = resolve_provider(provider)
    return OpenAICompatClient(
        base_url=resolved["base_url"],
        api_key=settings.llm_api_key,
        model=resolved["model"],
    )


@lru_cache
def get_llm_client() -> LLMClient:
    return create_llm_client()
