# ARCHITECTURE.md — BCREC College Voice Agent

## Overview

A multilingual (English/Hindi/Bengali) voice-enabled college information agent for Dr. B.C. Roy Engineering College, Durgapur. Exposes a REST API, WebSocket voice pipeline, and a LiveKit-powered real-time voice agent. Uses a "Clean Hybrid RAG" architecture: structured lookup from a canonical JSON knowledge base + vector search retrieval + Groq LLM.

---

## Runtime Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        EXTERNAL CLIENTS                         │
│  Browser (Web UI)  │  Phone (Twilio)  │  LiveKit Playground    │
└─────────┬──────────┴────────┬─────────┴───────────┬─────────────┘
          │                   │                     │
          │ HTTP/WSS          │ Media Stream WSS    │ WebRTC
          ▼                   ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI SERVER (8001)                         │
│  app.main → uvicorn                                              │
│                                                                  │
│  ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐ ┌─────────┐ │
│  │ QA API  │ │ TTS/STT  │ │ Voice   │ │ Admin    │ │ WS Voice│ │
│  │ /qa/*   │ │ /qa/tts  │ │ /voice/*│ │ /admin/* │ │ /qa/ws  │ │
│  └────┬────┘ │ /qa/stt  │ └──┬──────┘ └────┬─────┘ └────┬────┘ │
│       │      └────┬──────┘    │             │            │      │
│       ▼           ▼           ▼             ▼            ▼      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    SERVICES                                │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐  │   │
│  │  │ GroqService  │ │ SarvamService│ │ VectorStore      │  │   │
│  │  │ (LLM + RAG)  │ │ (TTS + STT)  │ │ (ChromaDB/BGE-M3)│  │   │
│  │  └──────┬───────┘ └──────┬───────┘ └────────┬─────────┘  │   │
│  │         │                │                   │             │   │
│  │  ┌──────┴───────┐ ┌──────┴───────┐           │             │   │
│  │  │ IntentClassi-│ │ VoiceSession │           │             │   │
│  │  │ bomb()→ fier │ │ Manager      │           │             │   │
│  │  └──────┬───────┘ └──────┬───────┘           │             │   │
│  │         │                │                   │             │   │
│  │  ┌──────┴───────┐ ┌──────┴───────┐ ┌────────┴─────────┐   │   │
│  │  │ Normalizer   │ │ TTS Cache    │ │ Conversation     │   │   │
│  │  │ (STT fix)    │ │ (mem+disk)   │ │ Telemetry        │   │   │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    UTILITIES                               │   │
│  │  Language Detect │ Voice Utils │ Stage Profiler           │   │
│  │  Conversation    │ Auth (JWT)  │ Rate Limiter (slowapi)   │   │
│  │  Logger          │ SQLite DB   │ Logging Config           │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
          │
          │ WebRTC (LiveKit Cloud)
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LIVEKIT AGENT (scripts/livekit_agent.py)      │
│  Connects to LiveKit Cloud wss://ai-voice-agent-64sbd6v0...     │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ VAD      │  │ STT      │  │ LLM      │  │ TTS            │  │
│  │ Silero   │  │ SarvamSTT│  │ BCRECGroq│  │ SarvamTTS      │  │
│  │          │  │ (Sarvam) │  │ (Groq)   │  │ + StreamAdapter│  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────────┘  │
│                                                                  │
│  Components prewarmed once per worker process.                   │
│  Entrypoint: voice.AgentSession → voice.Agent                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## REST Flow

### POST /qa/query
```
Client → FastAPI → GroqService.generate_response()
  → detect_language()
  → normalize_query()
  → _classify_intent() / IntentClassifier.classify()
  → [STRUCTURED PATH] _structured_lookup()
     → KB checks for fees, hostel, admission, placement, etc.
     → Return exact answer
  → [RAG + LLM PATH]
     → _retrieve_context() (ChromaDB vector search)
     → _build_prompt() (system + context + conversation history)
     → Groq LLM call (llama-3.3-70b)
     → post_process_response() (if DEMO_SAFEPOINT)
     → Return answer, source, intent
  → [Optional safe_point guard]
```

### POST /qa/tts-direct
```
Client → FastAPI → check TTS Cache → hit? return cached WAV
  → miss? → SarvamService.text_to_speech()
  → store in TTS Cache → return WAV bytes
```

### POST /qa/stt
```
Client (audio upload) → FastAPI → SarvamService.speech_to_text()
  → return transcript + language
```

---

## WebSocket Flow

### /qa/ws/voice
```
Client → WebSocket connect
  → receive JSON {type: "text", data: "query"}
  → detect_language_bcp47()
  → GroqService.stream_response() → token stream
  → for each token: send {type: "token", data: token}
  → sentence buffer (terminated by . ! ? \n)
  → for each sentence: SarvamService.text_to_speech_streamed()
  → send {type: "audio", data: base64, format: "wav"}
  → send {type: "done"}
```

---

## LiveKit Flow

### scripts/livekit_agent.py
```
CLI: python livekit_agent.py start
  → _run_connection_diagnostics() (DNS → TCP → TLS → WebSocket)
  → cli.run_app(WorkerOptions)
    → prewarm(proc):
      - silero.VAD.load()
      - SarvamSTT()
      - BCRECGroqLLM()
      - StreamAdapter(SarvamTTS)
    → entrypoint(ctx):
      - ctx.connect() to LiveKit room
      - Create voice.Agent(instructions=SYSTEM_PROMPT + voice rules)
      - voice.AgentSession(...).start(agent, room)
      - session.say(greeting)
      - Wait for room disconnect
      - clear_session() + telemetry.end_session()
```

### LiveKit-Twilio Bridge (voice.py)
```
Twilio Call → POST /voice/twiml/outbound → TwiML <Stream>
  → WebSocket /voice/stream
  → Create LiveKit room + token
  → Connect to LiveKit as publisher
  → Forward Twilio μ-law audio ↔ LiveKit AudioSource/AudioStream
  → LiveKit Agent receives audio, processes, sends audio back
```

---

## TTS/STT Flow

### TTS Chain:
```
GroqService.generate_response()
  → answer text
  → normalize_for_tts() (expand abbreviations, Indian numbers)
  → [SarvamService.text_to_speech() OR text_to_speech_streamed()]
  → WAV bytes
  → [tts_cache for repeated phrases]
```

### STT Chain:
```
SarvamSTT class (in livekit_agent.py):
  → speech_to_text() calls SarvamService
  → _fix_stt_acronyms() normalizes common mis-transcriptions
  → returns text

REST STT: /qa/stt → SarvamService.speech_to_text()
```

---

## LLM Flow

```
GroqService.generate_response(query, session_id):
1. Language detection (FastText → keyword fallback)
2. Normalize query (STT recovery, alias resolution)
3. Check query cache (MD5 hash, TTL 10min)
4. Rate limiter / circuit breaker check
5. Detect greeting / thanks / small talk → return canned
6. Detect repeat intent → return previous answer
7. Detect yes/no follow-up → expand context
8. Structured lookup:
   a. Principal/VP info
   b. Fee lookup (with dept extraction)
   c. Hostel info
   d. Admission info
   e. Placement stats
   f. Seat intake
   g. Cutoff ranks
   h. HOD info
   i. Faculty name resolution (aliases → fuzzy match)
   j. Department info
   k. Contact info
   l. Scholarship info
   m. Campus facilities
   n. Backlog/policy info
   o. Language help (Hindi/Bengali)
9. If no structured match:
   a. Vector search (ChromaDB)
   b. Build system prompt + context + history
   c. Call Groq LLM (stream or complete)
   d. Hallucination guard (entity validation)
   e. Post-process (safe_point personality)
10. Log telemetry (retrieval, LLM, validation)
11. Cache result
12. Return {answer, voice_text, source, intent}
```

---

## Memory Flow

### In-memory session memory (per session_id):
```
GroqService._sessions: Dict[session_id, SessionMemory]
  - history: List of {role, content} (last N turns)
  - last_intent, last_answer, last_question
  - intent_counts: track repeated intents
  - follow_up_context: cross-domain state tracking

ConversationContext (per session_id):
  - language: str
  - last_intent: Intent
  - recent_entities: Dict
  - recent_numeric_values: Dict
  - recent_topics: List
  - last_question: str
  - last_answer: str

ConversationTelemetry:
  - Per-session JSONL log file
  - Captures: input, retrieval, prompt, LLM start/complete, validation, output
```

### SQLite persistence:
```
database.py: conversations.db
  - conversations table (id, phone_number, title, created_at, updated_at)
  - messages table (id, conversation_id, role, content, created_at)
```

---

## Session Flow

### REST Session:
```
Each REST request carries session_id (or "default")
In-memory state per session_id
Session.clear() resets state
```

### LiveKit Session:
```
LiveKit room name = session key per entrypoint()
session.say(greeting) at start
Voice pipeline handles turn-by-turn
session.say() triggers STT → LLM → TTS loop
On disconnect: clear_session() + telemetry.end_session()
```

### Twilio Call Session:
```
Phone call → Twilio → WebSocket /voice/stream
  → LiveKit bridge → LiveKit Agent (same agent)
Phone number attached to metadata during bridge
```

---

## Retrieval Flow

### ChromaDB vector store:
```
VectorStoreService (singleton)
  - Embeddings: BGE-M3 via HuggingFaceEmbeddings(all-MiniLM-L6-v2)
  - Collection: "knowledge_base" in chroma_db/
  - search(query, k=5) → [Document, ...]
  - search_with_scores(query, k=8) → [(Document, score), ...]
  - Threshold: 0.15 relevance score
  - Only returns confidence if > threshold
```

### Build pipeline (scripts/build.py):
```
1. validate_kb.py — validate knowledge_base.json schema
2. generate_kb.py — build combined_kb.json (voice_ready_answers)
3. generate_markdown.py — build .md files from KB
4. generate_faq.py — build admin_faq.json
5. generate_embeddings.py — clear + re-ingest ChromaDB
   → ingest_knowledge_base.ingest_kb() — process markdown + JSON
```

---

## Startup Sequence

```
main.py (FastAPI)
1. setup_logging() — JSON + console logging
2. init_db() — SQLite tables
3. Pre-warm VectorStore (lazy if fails)
4. Create FastAPI app
5. Add session_id middleware
6. Rate limiter (slowapi)
7. CORS middleware
8. Mount /audio static
9. Include routers: qa, conversations, tts, stt, ws_voice, monitoring,
   health, auth_routes, admin, knowledge_base, voice
10. Mount frontend static (try 4 paths)
11. If __name__ == "__main__": uvicorn.run(host="0.0.0.0", port=8000)

livekit_agent.py
1. Set env vars (TRANSFORMERS_OFFLINE, PYTHONUTF8)
2. Load .env
3. init_db()
4. _run_connection_diagnostics() (DNS/TCP/TLS/WebSocket tests)
5. cli.run_app(WorkerOptions)
   → prewarm() loads VAD, STT, LLM, TTS
   → entrypoint() runs job loop
```

---

## Environment Variables Used

| Variable | Source | Used By |
|----------|--------|---------|
| GROQ_API_KEY | .env / env | Groq LLM client |
| SARVAM_API_KEY | .env / env | Sarvam TTS/STT |
| GEMINI_API_KEY | .env / env | (defined but unused in codebase) |
| DEEPGRAM_API_KEY | .env / env | voice_session.py |
| LIVEKIT_URL | .env / env | livekit_session.py, livekit_agent.py |
| LIVEKIT_API_KEY | .env / env | livekit_session.py, livekit_agent.py |
| LIVEKIT_API_SECRET | .env / env | livekit_session.py, livekit_agent.py |
| TWILIO_ACCOUNT_SID | .env / env | twilio_service.py |
| TWILIO_AUTH_TOKEN | .env / env | twilio_service.py |
| TWILIO_PHONE_NUMBER | .env / env | twilio_service.py |
| ADMIN_USERNAME | .env / env | auth.py |
| ADMIN_PASSWORD | .env / env | auth.py |
| SECRET_KEY | .env / env | JWT signing |
| CORS_ORIGINS | .env / env | CORS config (defined but unused) |
| ACCESS_TOKEN_EXPIRE_MINUTES | .env / env | JWT expiry |
| DB_DIR | .env / env | SQLite path |
| UPLOAD_DIR | .env / env | File uploads |
| TEMP_AUDIO_DIR | .env / env | Temp audio files |
| DEMO_SAFEPOINT | .env / env | Enable safe_point guard |
| COLLEGE_NAME | .env / env | College info |
| ADMISSIONS_PHONE | .env / env | College phone |
| SUPPORT_EMAIL | .env / env | College email |
| HALLUCINATION_GUARD_ENABLED | env | groq_service.py |
| RETRIEVAL_CONFIDENCE_THRESHOLD | env | groq_service.py |
| MAX_VOICE_RESPONSE_CHARS | env | groq_service.py |

---

## External Services

| Service | Purpose | Key | Cost |
|---------|---------|-----|------|
| **Groq** (groq.com) | LLM inference (llama-3.3-70b) | `GROQ_API_KEY` | Free tier |
| **Sarvam AI** (sarvam.ai) | TTS (Bulbul v3) + STT (Saaras v3) | `SARVAM_API_KEY` | Paid |
| **LiveKit Cloud** (livekit.cloud) | WebRTC voice transport | `LIVEKIT_*` | Paid |
| **Twilio** (twilio.com) | PSTN phone calling | `TWILIO_*` | Paid |
| **HuggingFace** (huggingface.co) | BGE-M3 model download (chroma_db) | None | Free |

---

## Entry Points

| Entry Point | File | Mode |
|-------------|------|------|
| FastAPI Server | `backend/app/main.py` | `uvicorn app.main:app --port 8001` |
| LiveKit Agent | `scripts/livekit_agent.py start` | `python scripts/livekit_agent.py start` |
| Build Pipeline | `scripts/build.py` | `python scripts/build.py` |

---

## Module Index (Important Modules)

| Module | Lines | Role |
|--------|-------|------|
| `app/services/llm/groq_service.py` | 4359 | Core LLM/RAG pipeline |
| `app/services/llm/intent_classifier.py` | 510 | Embedding-based intent detection |
| `app/services/llm/safe_point.py` | 274 | Demo safety guard |
| `app/services/sarvam_service.py` | 305 | TTS/STT integration |
| `app/services/vector_store.py` | 153 | ChromaDB vector search |
| `app/services/voice_session.py` | 95 | Voice pipeline coordinator |
| `app/services/tts_cache.py` | 104 | TTS audio caching |
| `app/services/normalization/normalizer.py` | 499 | Text normalization |
| `app/utils/language_detect.py` | 274 | Language detection |
| `app/utils/voice_utils.py` | 610 | TTS text prep |
| `app/utils/conversation_logger.py` | 710 | Telemetry |
| `scripts/livekit_agent.py` | 712 | LiveKit worker |
| `scripts/build.py` | 87 | Build orchestration |
| `scripts/ingest_knowledge_base.py` | 255 | KB ingestion |
