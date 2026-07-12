"""
TTS (Text-to-Speech) API endpoint using Sarvam.ai

POST /qa/tts - Generate speech from text
GET /qa/tts/voices - List available voices
GET /qa/tts/languages - List supported languages
"""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from typing import Optional
import logging
import os
import time
import uuid

from app.config import settings
from app.services.sarvam_service import get_sarvam_service, init_sarvam_service
from app.services import tts_cache  # Phase 3 Lite: in-memory + disk audio cache

logger = logging.getLogger(__name__)
router = APIRouter()


class TTSRequest(BaseModel):
    text: str
    language: Optional[str] = "en-IN"
    speaker: Optional[str] = "shubh"
    pace: Optional[float] = 1.0
    session_id: Optional[str] = None


class TTSResponse(BaseModel):
    audio_url: str
    format: str
    language: str
    speaker: str


def _init_sarvam():
    """Initialize Sarvam service if not already done"""
    if settings.sarvam_api_key:
        init_sarvam_service(settings.sarvam_api_key)
    return get_sarvam_service()


@router.post("/tts-direct")
async def text_to_speech_direct(request_data: TTSRequest, request: Request):
    """
    Convert text to speech and return audio bytes directly.
    Bypasses disk I/O for maximum speed.
    """
    if not request_data.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    
    language = request_data.language or "en-IN"
    
    # Auto-detect language based on script if frontend sends wrong default language
    import re
    if re.search(r"[\u0980-\u09FF]", request_data.text):
        language = "bn-IN"
    elif re.search(r"[\u0900-\u097F]", request_data.text):
        language = "hi-IN"

    speaker = request_data.speaker or "shubh"
    
    # Map languages to natural-sounding native speakers
    language_speaker_map = {
        "hi-IN": "aditya",
        "hi": "aditya",
        "bn-IN": "ritu",
        "bn": "ritu",
        "en-IN": "shubh"
    }
    
    if language in language_speaker_map and not request_data.speaker:
        speaker = language_speaker_map[language]

    sarvam = _init_sarvam()

    if not sarvam.is_available():
        raise HTTPException(status_code=503, detail="Sarvam service not available")

    session_id = request_data.session_id or getattr(request.state, 'session_id', 'default')

    try:
        # Phase 3 Lite: check audio cache first (skips Sarvam API entirely on hit)
        cached = tts_cache.get_cached_audio(request_data.text, language, speaker)
        if cached is not None:
            logger.info(f"[{session_id}] TTS direct CACHE HIT ({len(cached)} bytes)")
            return Response(content=cached, media_type="audio/wav", headers={"X-TTS-Cache": "hit"})

        start_time = time.time()
        result = await sarvam.text_to_speech(
            text=request_data.text,
            language=language,
            speaker=speaker,
            pace=request_data.pace or 1.0
        )
        
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "TTS failed"))

        audio_bytes = result["audio_bytes"]

        # Phase 3 Lite: warm the cache for future requests
        try:
            tts_cache.store_audio(request_data.text, language, speaker, audio_bytes)
        except Exception as e:
            logger.debug(f"TTS cache store failed: {e}")

        elapsed = time.time() - start_time
        logger.info(f"[{session_id}] TTS direct generated in {elapsed:.2f}s ({len(audio_bytes)} bytes)")

        return Response(content=audio_bytes, media_type="audio/wav", headers={"X-TTS-Cache": "miss"})
        
    except Exception as e:
        logger.error(f"TTS direct error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tts", response_model=TTSResponse)
async def text_to_speech(request_data: TTSRequest, request: Request):
    """
    Convert text to speech using Sarvam AI TTS API.
    """
    if not request_data.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    
    # Auto-select speaker based on language for better accent
    language = request_data.language or "en-IN"
    
    # Auto-detect language based on script if frontend sends wrong default language
    import re
    if re.search(r"[\u0980-\u09FF]", request_data.text):
        language = "bn-IN"
    elif re.search(r"[\u0900-\u097F]", request_data.text):
        language = "hi-IN"

    speaker = request_data.speaker or "shubh"
    
    # Map languages to natural-sounding native speakers
    language_speaker_map = {
        "hi-IN": "aditya",  # Clear Hindi male voice
        "hi": "aditya",
        "bn-IN": "ritu",    # Clear Bengali female voice
        "bn": "ritu",
        "en-IN": "shubh"    # Standard Indian English voice
    }
    
    if language in language_speaker_map and not request_data.speaker:
        speaker = language_speaker_map[language]

    sarvam = _init_sarvam()
    
    if not sarvam.is_available():
        raise HTTPException(
            status_code=503,
            detail="Sarvam TTS service not available. Please check SARVAM_API_KEY."
        )
    
    session_id = request_data.session_id or getattr(request.state, 'session_id', 'default')
    
    try:
        result = await sarvam.text_to_speech(
            text=request_data.text,
            language=language,
            speaker=speaker,
            pace=request_data.pace or 1.0
        )
        
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "TTS generation failed"))
        
        audio_bytes = result["audio_bytes"]
        
        filename = f"tts_{session_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}.wav"
        filepath = os.path.join(settings.temp_audio_dir, filename)
        
        os.makedirs(settings.temp_audio_dir, exist_ok=True)
        
        with open(filepath, "wb") as f:
            f.write(audio_bytes)
        
        logger.info(f"[{session_id}] TTS generated: {filename} ({len(audio_bytes)} bytes)")
        
        return TTSResponse(
            audio_url=f"/audio/{filename}",
            format=result.get("format", "wav"),
            language=result.get("language", request_data.language or "en-IN"),
            speaker=result.get("speaker", request_data.speaker or "shubh")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tts/voices")
async def list_voices():
    """List available TTS voices"""
    sarvam = _init_sarvam()
    return {
        "voices": sarvam.get_available_voices(),
        "default": "shubh"
    }


@router.get("/tts/languages")
async def list_languages():
    """List supported languages"""
    sarvam = _init_sarvam()
    return {
        "languages": sarvam.get_supported_languages(),
        "default": "en-IN"
    }


# ---------------------------------------------------------------------------
# Phase 3 Lite — TTS cache endpoints (for the principal demo)
# ---------------------------------------------------------------------------
@router.get("/tts/cache/stats")
async def tts_cache_stats():
    """Show TTS cache hit/miss stats — perfect for the demo dashboard."""
    return tts_cache.get_stats()


@router.post("/tts/cache/invalidate")
async def tts_cache_invalidate():
    """Manually clear all TTS cache (memory + disk)."""
    # Memory
    in_memory = tts_cache.get_stats().get("memory_entries", 0)
    # Disk
    import os, glob
    disk_files = 0
    cache_dir = tts_cache._CACHE_DIR
    if os.path.isdir(cache_dir):
        for f in glob.glob(os.path.join(cache_dir, "*.wav")):
            try:
                os.remove(f)
                disk_files += 1
            except Exception:
                pass
    # Reset in-memory dict
    tts_cache._MEMORY_CACHE.clear()
    return {
        "in_memory_cleared": in_memory,
        "on_disk_cleared": disk_files,
    }
