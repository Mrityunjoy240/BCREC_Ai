"""
STT (Speech-to-Text) API endpoint using Sarvam.ai

POST /qa/stt - Transcribe audio to text
GET /qa/stt/languages - List supported languages
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
import logging

from app.config import settings
from app.services.sarvam_service import get_sarvam_service, init_sarvam_service

logger = logging.getLogger(__name__)
router = APIRouter()

SUPPORTED_FORMATS = ["wav", "mp3", "webm", "ogg", "aac", "flac", "m4a"]

def _init_sarvam():
    """Initialize Sarvam service if not already done"""
    if settings.sarvam_api_key:
        init_sarvam_service(settings.sarvam_api_key)
    return get_sarvam_service()


@router.post("/stt")
async def speech_to_text(
    audio: UploadFile = File(...),
    language: str = Form("en-IN"),
    model: str = Form("saaras:v3")
):
    """
    Transcribe speech to text using Sarvam AI STT API or Local Qwen3-ASR.
    """
    sarvam = _init_sarvam()
    
    if not sarvam.is_available():
        raise HTTPException(
            status_code=503,
            detail="Sarvam STT service not available. Please check SARVAM_API_KEY."
        )
    
    content_type = audio.content_type or ""
    filename = audio.filename or "audio"
    
    file_ext = filename.split(".")[-1].lower() if "." in filename else "wav"
    
    if file_ext not in SUPPORTED_FORMATS and not any(fmt in content_type for fmt in SUPPORTED_FORMATS):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format. Supported: {', '.join(SUPPORTED_FORMATS)}"
        )
    
    try:
        audio_bytes = await audio.read()
        
        if len(audio_bytes) < 1000:
            raise HTTPException(status_code=400, detail="Audio file too small")
        
        if len(audio_bytes) > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 50MB)")
        
        result = await sarvam.speech_to_text(
            audio_bytes=audio_bytes,
            language=language,
            model=model
        )
        
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "STT failed"))
        
        detected_lang = result.get("language", language)
        transcript_text = result.get("text", "")
        
        logger.info(f"STT: '{transcript_text[:100]}...' detected={detected_lang}")
        
        return {
            "text": transcript_text,
            "language": detected_lang,
            "confidence": 0.95,
            "model": model
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"STT error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stt/languages")
async def list_languages():
    """List supported STT languages"""
    sarvam = _init_sarvam()
    return {
        "languages": {
            "en-IN": "English (India)",
            "hi-IN": "Hindi",
            "bn-IN": "Bengali",
            "ta-IN": "Tamil",
            "te-IN": "Telugu",
            "kn-IN": "Kannada",
            "ml-IN": "Malayalam",
            "mr-IN": "Marathi",
            "gu-IN": "Gujarati",
            "pa-IN": "Punjabi",
            "od-IN": "Odia",
            "auto": "Auto-detect"
        },
        "default": "en-IN"
    }
