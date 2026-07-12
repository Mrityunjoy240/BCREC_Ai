import logging

from fastapi import APIRouter

from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


def _init_sarvam():
    """Initialize Sarvam service if needed"""
    from app.services.sarvam_service import get_sarvam_service, init_sarvam_service

    if settings.sarvam_api_key:
        init_sarvam_service(settings.sarvam_api_key)
    return get_sarvam_service()


@router.get("/")
async def health_root():
    return {"status": "ok", "service": "BCREC Voice Agent"}


@router.get("/tts")
async def tts_health_check():
    """Check which TTS providers are working"""
    sarvam_available = False
    active_provider = "none"

    try:
        if settings.sarvam_api_key:
            sarvam = _init_sarvam()
            sarvam_available = sarvam.is_available()
            if sarvam_available:
                active_provider = "sarvam"
    except Exception as e:
        logger.error(f"TTS health check error: {e}")

    return {
        "sarvam_available": sarvam_available,
        "active_provider": active_provider,
        "status": "healthy" if sarvam_available else "degraded",
        "key_configured": bool(settings.sarvam_api_key),
    }
