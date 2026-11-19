from fastapi import APIRouter

from app.core.config import get_settings
from app.services.llm import PROVIDER_PRESETS, get_llm_client, resolve_provider

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "app": settings.app_name, "llm_provider": settings.llm_provider}


@router.get("/info")
def info() -> dict:
    settings = get_settings()
    return {
        "app": settings.app_name,
        "llm_provider": settings.llm_provider,
        "model": settings.llm_model or None,
        "data_dir": str(settings.data_dir),
        "providers": sorted(PROVIDER_PRESETS.keys()),
    }


@router.get("/llm/test")
def llm_test() -> dict:
    llm = get_llm_client()
    try:
        reply = llm.chat(
            [{"role": "user", "content": "只回复四个字：连接成功"}],
            max_tokens=32,
        )
        return {"provider": llm.name, "ok": True, "reply": reply}
    except Exception as exc:  # noqa: BLE001
        return {"provider": llm.name, "ok": False, "error": str(exc)}
