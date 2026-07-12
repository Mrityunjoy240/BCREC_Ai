# CODEBASE_MAP.md — Every Module Analyzed

> Status legend: ✅ ACTIVE | 🟡 LEGACY | 🔴 UNUSED | ❓ UNKNOWN

---

## backend/app/ — FastAPI Application

### main.py (139 lines) ✅ ACTIVE
- **Purpose:** FastAPI app entry point. Initializes logging, DB, vector store. Mounts routers and frontend static files.
- **Who calls it:** `uvicorn app.main:app` (via `start_server.ps1`, `scripts/start_server.py`)
- **Who it calls:** `setup_logging()`, `init_db()`, `get_vector_store()`, all routers, `StaticFiles.mount()`
- **Key routers mounted:** qa (x5), conversations, tts, stt, ws_voice, monitoring, health, auth_routes, admin, knowledge_base, voice

### config.py (106 lines) ✅ ACTIVE
- **Purpose:** Pydantic Settings singleton. Loads `.env` from multiple paths. Initializes Groq and Sarvam API clients.
- **Who calls it:** Almost every module via `from app.config import settings`
- **Who it calls:** `dotenv.load_dotenv()`, `Groq()`, `AsyncGroq()`, `SarvamAI()`
- **Bug:** `CORS_ORIGINS` is defined in env sample but the code uses a hardcoded allow_origins list (line 67-76 of main.py ignores the env var)

### auth.py (68 lines) ✅ ACTIVE
- **Purpose:** JWT auth logic — password verification, token creation, `get_current_admin` dependency.
- **Who calls it:** `api/auth_routes.py`, `api/admin.py`, `api/knowledge_base.py`
- **Who it calls:** `jose.jwt`, `passlib.context`

### database.py (53 lines) ✅ ACTIVE
- **Purpose:** SQLite init (conversations.db) with WAL mode.
- **Who calls it:** `main.py`, `api/conversations.py`, `scripts/livekit_agent.py`
- **Who it calls:** `sqlite3`

### limiter.py (5 lines) ✅ ACTIVE
- **Purpose:** Rate limiter (slowapi, 10 req/min/IP).
- **Who calls it:** `main.py`

### logging_config.py (72 lines) ✅ ACTIVE
- **Purpose:** JSON + console logging setup. Rotating file handler.
- **Who calls it:** `main.py`

---

## backend/app/api/ — REST/WebSocket Endpoints

### qa.py (182 lines) ✅ ACTIVE
- **Purpose:** `/qa/query` (POST), `/qa/query-stream` (POST), `/qa/session/clear` (POST), `/qa/health` (GET), `/qa/debug` (POST)
- **Who calls it:** FastAPI router
- **Who it calls:** `get_groq_service()`, `post_process_response()`, `detect_language()`
- **Routes:** QueryResponse, QueryStream, ClearSession, Health, Debug

### tts.py (252 lines) ✅ ACTIVE
- **Purpose:** `/qa/tts-direct` (POST), `/qa/tts` (POST), `/qa/tts/voices` (GET), `/qa/tts/languages` (GET), TTS cache endpoints
- **Who calls it:** FastAPI router
- **Who it calls:** `get_sarvam_service()`, `tts_cache`
- **Notes:** Auto-detects language from script (Bengali/Hindi Unicode ranges)

### stt.py (112 lines) ✅ ACTIVE
- **Purpose:** `/qa/stt` (POST), `/qa/stt/languages` (GET)
- **Who calls it:** FastAPI router
- **Who it calls:** `get_sarvam_service()`
- **Notes:** Validates format + size (min 1KB, max 50MB)

### voice.py (186 lines) ✅ ACTIVE
- **Purpose:** `/voice/token` (POST), `/voice/call-me` (POST), `/voice/twiml/outbound` (POST), WebSocket `/voice/stream`
- **Who calls it:** FastAPI router
- **Who it calls:** `get_livekit_service()`, `get_twilio_service()`, `audioop`, `api.AccessToken`, `rtc.Room`
- **Notes:** The Twilio-LiveKit bridge WebSocket endpoint. Converts μ-law ↔ PCM, resamples 8kHz ↔ 16kHz.

### ws_voice.py (117 lines) ✅ ACTIVE
- **Purpose:** WebSocket `/qa/ws/voice` — streaming voice pipeline (text → LLM tokens + sentence-level TTS)
- **Who calls it:** FastAPI router
- **Who it calls:** `get_groq_service()`, `get_sarvam_service()`, `detect_language_bcp47()`
- **Notes:** Sentence buffer flushes on `.`, `!`, `?`, `\n`. Background TTS worker via `asyncio.Queue`.

### admin.py (307 lines) ✅ ACTIVE
- **Purpose:** Protected admin endpoints: file upload, backup, KB FAQ management, cache ops, semantic anchors.
- **Who calls it:** FastAPI router
- **Who it calls:** `get_groq_service()`, `get_current_admin`, `BackupService`, `DocumentProcessor`, `ingest_knowledge_base.ingest_kb`

### auth_routes.py (35 lines) ✅ ACTIVE
- **Purpose:** `/token` (POST) — OAuth2 login.
- **Who calls it:** FastAPI router
- **Who it calls:** `create_access_token()`, `verify_password()`

### conversations.py (277 lines) ✅ ACTIVE
- **Purpose:** Full CRUD for conversations + messages in SQLite.
- **Who calls it:** FastAPI router
- **Who it calls:** `get_db()`

### health.py (45 lines) ✅ ACTIVE
- **Purpose:** `/health/` (GET), `/health/tts` (GET)
- **Who calls it:** FastAPI router
- **Who it calls:** `get_sarvam_service()`

### knowledge_base.py (95 lines) ✅ ACTIVE
- **Purpose:** `/admin/reindex` (POST) — clear and re-index vector store.
- **Who calls it:** FastAPI router
- **Who it calls:** `get_current_admin`, `DocumentProcessor`, `get_vector_store`

### monitoring.py (7 lines) ✅ ACTIVE
- **Purpose:** `GET /monitoring/` → `{"status": "healthy"}`
- **Who calls it:** FastAPI router
- **Who it calls:** None

---

## backend/app/services/ — Business Logic

### llm/groq_service.py (4359 lines) ✅ ACTIVE
- **Purpose:** Core LLM/RAG pipeline. Everything: language detection, normalization, intent classification, structured lookup, vector retrieval, Groq LLM call, hallucination guard, session memory, caching, telemetry.
- **Who calls it:** `api/qa.py`, `api/admin.py`, `api/ws_voice.py`, `services/voice_session.py`, `scripts/livekit_agent.py`, 10+ test files
- **Who it calls:** `settings`, `get_vector_store`, `detect_language`, `get_telemetry`, `normalize_query`, `normalize_for_tts`, `IntentClassifier`, `safe_point`
- **Key internal methods:**
  - `generate_response()` — Main async entry point (700+ lines)
  - `stream_response()` — Streaming variant
  - `_structured_lookup()` — KB handler chain (~400 lines)
  - `_retrieve_context()` — ChromaDB vector search
  - `_resolve_faculty_name()` — Fuzzy name matching
  - `_build_faculty_index()` — Faculty indexer
  - `_classify_intent()` — Regex-based intent detection
  - `_detect_domain()` — Domain classification
  - `_track_domain()` — Cross-domain conversation tracking
  - `_extract_dept_code()` — Department extraction
  - `_llm_generate()` — Groq API call wrapper
  - `clear_session()` — Reset session memory

### llm/intent_classifier.py (510 lines) ✅ ACTIVE
- **Purpose:** Embedding-based intent classifier with keyword fallback. 30+ intents.
- **Who calls it:** Used internally by `groq_service.py`
- **Who it calls:** `VectorStoreService`, `numpy`

### llm/safe_point.py (274 lines) ✅ ACTIVE (conditional)
- **Purpose:** Demo safety guard. Handoff detection, unknown response replacement, Bengali low-confidence filter.
- **Who calls it:** `groq_service.py`, `api/qa.py`, `scripts/livekit_agent.py`
- **Who it calls:** `settings`

### llm/base.py (37 lines) 🔴 UNUSED
- **Purpose:** Abstract `BaseLLM` class with `chat()`, `chat_complete()`, `structured_output()`, `is_available()`.
- **Why unused:** No implementation inherits from it. `GroqService` does not extend it.
- **Status:** Skeleton — never instantiated.

### conversation/context.py (94 lines) ✅ ACTIVE
- **Purpose:** `ConversationContext` (per-session state) and `ConversationManager` (global registry).
- **Who calls it:** `conversation/intent.py`, tests
- **Who it calls:** None

### conversation/intent.py (409 lines) 🟡 LEGACY
- **Purpose:** Rule-based intent classifier (GREETING, GOODBYE, THANKS, FOLLOW_UP, etc.) with regex patterns.
- **Who calls it:** Only direct import is `tests/test_intent.py`
- **Who it calls:** `.context.ConversationContext`
- **Note:** Superseded by `llm/intent_classifier.py` (embedding-based). Original simpler classifier kept as legacy.

### conversation/responses.py (50 lines) 🔴 UNUSED
- **Purpose:** Multilingual response templates for conversation intents.
- **Who calls it:** No production code imports it.
- **Note:** `groq_service.py` has its own inline response strings. `safe_point.py` has its own greetings.

### vector_store.py (153 lines) ✅ ACTIVE
- **Purpose:** ChromaDB singleton with BGE-M3 embeddings. `search()`, `search_with_scores()`, `add_documents()`, `clear_collection()`.
- **Who calls it:** `groq_service.py`, `intent_classifier.py`, `main.py`, `knowledge_base.py`, test files
- **Who it calls:** `Chroma`, `HuggingFaceEmbeddings`

### sarvam_service.py (305 lines) ✅ ACTIVE
- **Purpose:** Sarvam AI TTS/STT integration. `text_to_speech()`, `text_to_speech_streamed()`, `speech_to_text()`.
- **Who calls it:** `api/tts.py`, `api/stt.py`, `api/ws_voice.py`, `voice_session.py`, `scripts/livekit_agent.py`
- **Who it calls:** `sarvamai.SarvamAI`, `voice_utils.clean_for_voice()`

### livekit_session.py (71 lines) ✅ ACTIVE
- **Purpose:** LiveKit token generation. `generate_token()`, `is_available()`.
- **Who calls it:** `api/voice.py`
- **Who it calls:** `livekit.api.AccessToken`

### voice_session.py (95 lines) ❓ UNKNOWN
- **Purpose:** Pipeline coordinator: Deepgram STT → Groq LLM → Sarvam TTS.
- **Who calls it:** No reverse dependencies found in audit scope. Possibly imported by an API route not scanned, or dead code.
- **Who it calls:** `get_groq_service()`, `get_sarvam_service()`, `deepgram`
- **Status:** Function exists but no consumer found. May be wired into WebSocket voice pipeline.

### document_processor.py (214 lines) ✅ ACTIVE
- **Purpose:** File ingestion/chunking. PDF, CSV, Excel, TXT → smart recursive chunks.
- **Who calls it:** `api/admin.py`, `api/knowledge_base.py`, `scripts/ingest_knowledge_base.py`
- **Who it calls:** `pypdf`, `pandas`, `openpyxl`

### tts_cache.py (104 lines) ✅ ACTIVE
- **Purpose:** In-memory + disk TTS audio cache. MD5 key → WAV bytes.
- **Who calls it:** `api/tts.py`
- **Who it calls:** None

### query_logger.py (85 lines) 🔴 UNUSED
- **Purpose:** Append-only JSONL query/response logger.
- **Who calls it:** No production code imports it.
- **Note:** Superseded by `conversation_logger.py` (ConversationTelemetry). The file still exists but is not wired.

### backup.py (37 lines) 🟡 LEGACY (placeholder)
- **Purpose:** Placeholder backup service — creates dummy files.
- **Who calls it:** `api/admin.py`
- **Who it calls:** None
- **Note:** Docstring explicitly says "placeholder." No real archive logic.

### telephony/base_adapter.py (22 lines) 🔴 UNUSED
- **Purpose:** Abstract `TelephonyAdapter` class with `handle_incoming_call()`, `disconnect_call()`.
- **Why unused:** No implementation inherits from it. `twilio_service.TwilioService` does not extend it.

### telephony/twilio_service.py (49 lines) ✅ ACTIVE
- **Purpose:** Twilio outbound calling. `make_outbound_call()`.
- **Who calls it:** `api/voice.py`
- **Who it calls:** `twilio.rest.Client`

### normalization/normalizer.py (499 lines) ✅ ACTIVE
- **Purpose:** Text normalization pipeline: unicode → lowercase → STT correction → alias → fuzzy entity resolution.
- **Who calls it:** `groq_service.py`, `scripts/livekit_agent.py`
- **Who it calls:** `json` (entity dictionary)

---

## backend/app/utils/ — Utilities

### language_detect.py (274 lines) ✅ ACTIVE
- **Purpose:** FastText + keyword fallback language detection. `detect_language()`, `detect_language_bcp47()`.
- **Who calls it:** 10+ modules (most imported utility)
- **Who it calls:** `fasttext` (downloaded on first use)

### voice_utils.py (610 lines) ✅ ACTIVE
- **Purpose:** TTS text normalization. `clean_for_voice()` (acronyms, Indian numbers, symbols), `split_into_tts_chunks()`, `indian_number_to_words()`.
- **Who calls it:** `sarvam_service.py`, `groq_service.py`, `scripts/livekit_agent.py`
- **Who it calls:** `inflect`

### conversation_logger.py (710 lines) ✅ ACTIVE
- **Purpose:** Full conversation telemetry (JSONL). Session lifecycle, turn input, retrieval, LLM, validation, voice output.
- **Who calls it:** `groq_service.py`, `scripts/livekit_agent.py`
- **Who it calls:** None (pure file I/O)

### stage_profiler.py (40 lines) ✅ ACTIVE
- **Purpose:** Pipeline performance profiler. `start()`, `mark()`, `report()`.
- **Who calls it:** `groq_service.py` (lazy import)
- **Who it calls:** None

---

## scripts/ — Scripts

### livekit_agent.py (712 lines) ✅ ACTIVE
- **Purpose:** LiveKit voice agent worker. Defines SarvamSTT, SarvamTTS, BCRECGroqLLM wrappers. Contains `prewarm()`, `entrypoint()`, connection diagnostics.
- **Entry point:** `python scripts/livekit_agent.py start`
- **Who calls it:** `start_agent.py`, `run_agent.py`, `start_agent.bat`, `start_agent_now.ps1`

### build.py (87 lines) ✅ ACTIVE
- **Purpose:** Build pipeline orchestrator. Runs: validate_kb → generate_kb → generate_markdown → generate_faq → generate_embeddings.
- **Entry point:** `python scripts/build.py`

### generate_kb.py (516 lines) ✅ ACTIVE
- **Purpose:** Generates `combined_kb.json` from `knowledge_base.json`.

### generate_markdown.py (699 lines) ✅ ACTIVE
- **Purpose:** Generates `.md` files from `knowledge_base.json` for vector ingestion.

### generate_embeddings.py (49 lines) ✅ ACTIVE
- **Purpose:** Rebuilds ChromaDB vector store.

### generate_faq.py (76 lines) ✅ ACTIVE
- **Purpose:** Generates `admin_faq.json` from `combined_kb.json`.

### validate_kb.py (172 lines) ✅ ACTIVE
- **Purpose:** Schema + null + cross-field validation of `knowledge_base.json`.

### ingest_knowledge_base.py (255 lines) ✅ ACTIVE
- **Purpose:** Core ingestion engine: clears ChromaDB, processes markdown + JSON + uploaded files.

### dispatch_agent.py (45 lines) 🔴 UNUSED
- **Purpose:** CLI tool to dispatch agent to a named LiveKit room.
- **Who calls it:** No one. Superseded by `join_room.py` and LiveKit Playground.

### run_agent.py (69 lines) 🟡 LEGACY
- **Purpose:** Combined launcher: free port → spawn agent → wait → dispatch to hardcoded room.
- **Note:** Hardcoded room name. Superseded by modular scripts.

### start_agent.py (48 lines) 🟡 LEGACY
- **Purpose:** Start agent + dispatch to hardcoded room.
- **Note:** Hardcoded `room: console-f7d1f37e`. Superseded.

### server_bg.py (25 lines) 🟡 LEGACY
- **Purpose:** Start uvicorn as background process.
- **Note:** Overlaps with root `start_server.ps1`.

### start_server.py (20 lines) 🟡 LEGACY
- **Purpose:** Start uvicorn with offline HF env vars.
- **Note:** Overlaps with `start_server.ps1`, `start_backend.ps1`, `start_backend.bat`.

### join_room.py (59 lines) 🟡 LEGACY
- **Purpose:** Connect to LiveKit room and dispatch agent.
- **Note:** Manual utility script. No callers.

### energy_vad.py (199 lines) 🔴 UNUSED
- **Purpose:** Energy-based VAD using `audioop.rms()`.
- **Note:** `livekit_agent.py` uses `silero.VAD` instead. Never imported.

### download_pdfs.py (37 lines) 🟡 LEGACY
- **Purpose:** Download official BCREC PDFs from website.
- **Note:** One-time data collection.

### parse_all_pdfs.py (35 lines), parse_fee_pdfs.py (53 lines), scrape_official_site.py (56 lines) 🟡 LEGACY
- **Purpose:** PDF data extraction scripts.
- **Note:** One-time data collection. Not wired into build pipeline.

### update_kb_from_pdfs.py (219 lines) 🟡 LEGACY
- **Purpose:** Update KB JSON files with PDF-extracted fee data.
- **Note:** Manual data update script. Run when PDFs change.

### validate_retrieval.py (345 lines) 🔴 UNUSED
- **Purpose:** Test 100+ queries against ChromaDB retrieval quality.
- **Note:** Standalone validation tool.

### performance_report.py (369 lines) 🔴 UNUSED
- **Purpose:** Read telemetry JSONL → latency stats, failure breakdown.
- **Note:** Standalone analysis tool.

### simulate_conversations.py (992 lines) 🔴 UNUSED
- **Purpose:** Generate 30 simulated conversations → validate telemetry.
- **Note:** Standalone test harness.

### demo_readiness_test.py (402 lines) 🔴 UNUSED
- **Purpose:** End-to-end demo readiness test.
- **Note:** Standalone test script.

### system_test.py (153 lines) 🔴 UNUSED
- **Purpose:** Full system integration test.
- **Note:** Standalone test script.

### test_15_quick.py (99 lines), test_faq_comprehensive.py (260 lines), test_rag_150.py (406 lines), test_vp_fix.py (34 lines) 🔴 UNUSED
- **Purpose:** Various ad-hoc test scripts.
- **Note:** All standalone. Not wired into CI or pytest.

### start_backend.ps1 (3 lines), start_backend.bat (3 lines), start_agent.bat (3 lines) 🟡 LEGACY
- **Purpose:** Launcher scripts.
- **Note:** Multiple overlapping launchers for same purpose.

---

## backend/tests/ — Pytest Suite

### conftest.py ✅ ACTIVE (test fixture)
### test_groq_service.py ✅ ACTIVE
### test_async_groq.py ✅ ACTIVE
### test_intent.py ✅ ACTIVE
### test_language_consistency.py ✅ ACTIVE
### test_normalization.py ✅ ACTIVE
### test_regression_ux.py ✅ ACTIVE
### test_session_isolation.py ✅ ACTIVE
### test_structured_memory_regression.py ✅ ACTIVE
### test_api_robustness.py ✅ ACTIVE
### red_team/ (7 files) ✅ ACTIVE
### verify_demo_phases.py ✅ ACTIVE

## tests/ (root)

### test_analytics.py ❓ UNKNOWN
### test_telemetry.py ✅ ACTIVE
