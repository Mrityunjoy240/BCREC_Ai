from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Any
import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Try to load local.env or .env for local development
for env_file in [".env", "backend/.env", "local.env", "../.env", "../local.env"]:
    if os.path.exists(env_file):
        load_dotenv(env_file, override=True)
        logger.info(f"Loaded environment from {os.path.abspath(env_file)}")
        break

# Graceful Groq check
try:
    from groq import Groq

    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    Groq = None
    logger.warning("Groq library not found in environment")


class Settings(BaseSettings):
    # API Keys - Pydantic will automatically pick these up from system env if available
    groq_api_key: str = ""
    sarvam_api_key: str = ""
    gemini_api_key: str = ""
    deepgram_api_key: str = ""
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # Twilio Settings
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Auth Settings (MUST be set via .env or environment variables)
    admin_username: str = ""
    admin_password: str = ""
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Direct Client initializations
    groq_client: Optional[Any] = None
    async_groq_client: Optional[Any] = None
    sarvam_client: Optional[Any] = None

    # Directories
    db_dir: str = "data"
    upload_dir: str = "uploads"
    temp_audio_dir: str = "temp_audio"

    # Demo Safe Point
    demo_safepoint: bool = False

    # College information
    college_name: str = "Dr. B.C. Roy Engineering College"
    admissions_phone: str = "0343-2501353"
    support_email: str = "info@bcrec.ac.in"

    # Pydantic Config
    model_config = SettingsConfigDict(
        env_file=".env",  # Look for .env by default
        extra="ignore",
        env_prefix="",  # No prefix (e.g. look for GROQ_API_KEY directly)
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Security masking
        def mask(s):
            return f"{s[:4]}...{s[-4:]}" if s and len(s) > 8 else "MISSING"

        # Initialize Groq
        if GROQ_AVAILABLE and self.groq_api_key:
            try:
                from groq import AsyncGroq

                self.groq_client = Groq(api_key=self.groq_api_key)
                self.async_groq_client = AsyncGroq(api_key=self.groq_api_key)
                logger.info("Groq client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Groq client: {e}")
        else:
            logger.info("Groq AI Client: SKIPPED")

        # Initialize Sarvam
        if self.sarvam_api_key:
            try:
                from sarvamai import SarvamAI

                self.sarvam_client = SarvamAI(api_subscription_key=self.sarvam_api_key)
                logger.info("Sarvam Voice Client: INITIALIZED")
            except Exception as e:
                logger.info(f"Sarvam Voice Client: SKIPPED ({e})")


# Singleton
settings = Settings()
