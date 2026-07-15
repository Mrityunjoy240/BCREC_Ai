import logging
from app.logging_config import setup_logging

# Configure logging FIRST before anything else
setup_logging()
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from uuid import uuid4

from app.config import settings
from app.database import init_db
from app.api import (
    qa,
    conversations,
    tts,
    stt,
    monitoring,
    auth_routes,
    admin,
    health,
    voice,
    ws_voice,
    knowledge_base,
)

# Initialize Database
init_db()

# Pre-warm vector store (downloads BGE-M3 embeddings if needed)
logger.info("Pre-warming vector store...")
try:
    from app.services.vector_store import get_vector_store

    get_vector_store()
    logger.info("Vector store pre-warmed successfully")
except Exception as e:
    logger.warning(f"Vector store pre-warm failed (will init lazily): {e}")

# ---------------------------------------------------------------------------
# Phase 0: Foundation — interfaces, event bus, DI, feature flags
# ---------------------------------------------------------------------------
from app.core.feature_flags import feature_flags
from app.core.event_bus import InMemoryEventBus
from app.core.di import container

event_bus = InMemoryEventBus()
container.register_singleton("event_bus", event_bus)
container.register_singleton("feature_flags", feature_flags)

if feature_flags.is_enabled("use_pipeline"):
    from app.pipeline.runner import PipelineRunner
    from app.pipeline.stages import (
        LanguageDetectionStage,
        IntentClassificationStage,
        KnowledgeRetrievalStage,
        LLMGenerationStage,
        SafetyGuardStage,
        ResponseFormatterStage,
    )

    pipeline_runner = PipelineRunner(stages=[
        LanguageDetectionStage(),
        IntentClassificationStage(),
        KnowledgeRetrievalStage(),
        LLMGenerationStage(),
        SafetyGuardStage(),
        ResponseFormatterStage(),
    ])
    container.register_singleton("pipeline_runner", pipeline_runner)
    logger.info("Phase 0: Pipeline runner initialized with 6 stages")

from app.core.conversation_engine import ConversationEngine

engine = ConversationEngine(
    pipeline_runner=container.get("pipeline_runner")
)
container.register_singleton("conversation_engine", engine)

if feature_flags.is_enabled("use_channel_adapters"):
    from app.channel.web_adapter import WebChannelAdapter

    web_adapter = WebChannelAdapter(engine=engine)
    container.register_singleton("web_channel_adapter", web_adapter)
    logger.info("Phase 0: Channel adapters enabled")
# ---------------------------------------------------------------------------

# Create FastAPI app
app = FastAPI(title="College Voice Agent API", version="1.0.0")


# Add Session ID Middleware
@app.middleware("http")
async def add_session_id_middleware(request: Request, call_next):
    """Inject a unique session_id into request.state for every request"""
    if not hasattr(request.state, "session_id"):
        request.state.session_id = str(uuid4())
    response = await call_next(request)
    return response


from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.limiter import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:8000",
        "http://localhost:8080",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure temp audio directory exists
os.makedirs(settings.temp_audio_dir, exist_ok=True)

# Mount static directory for audio files
app.mount("/audio", StaticFiles(directory=settings.temp_audio_dir), name="audio")

# Include API routes
app.include_router(qa.router, prefix="/qa", tags=["qa"])
app.include_router(conversations.router, prefix="/api", tags=["conversations"])
app.include_router(tts.router, prefix="/qa", tags=["tts"])
app.include_router(stt.router, prefix="/qa", tags=["stt"])
app.include_router(ws_voice.router, prefix="/qa", tags=["voice"])
app.include_router(monitoring.router, prefix="/monitoring", tags=["monitoring"])
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(auth_routes.router, tags=["auth"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(knowledge_base.router, prefix="/admin", tags=["kb"])
app.include_router(voice.router, prefix="/voice", tags=["voice"])

# Serve Frontend Static Files (if they exist)
# Check multiple possible locations to support both Local and Docker/Railway
possible_paths = [
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "frontend",
        "dist",
    ),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist"),
    os.path.join(os.getcwd(), "frontend", "dist"),
    "/app/frontend/dist",
]

frontend_path = None
logger.info(f"System Check - Current Working Directory: {os.getcwd()}")
logger.info(f"System Check - File Path: {os.path.abspath(__file__)}")

for path in possible_paths:
    exists = os.path.exists(path)
    logger.info(f"Checking frontend path: {path} -> {'FOUND' if exists else 'NOT FOUND'}")
    if exists:
        frontend_path = path
        break

if frontend_path:
    logger.info(f"CRITICAL: Frontend directory found at: {frontend_path}. Mounting static files.")
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
else:
    logger.error("CRITICAL ERROR: Frontend directory NOT found in any expected locations!")

    @app.get("/")
    async def root():
        return {"message": "College Voice Agent API is running! (Frontend not built)"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
