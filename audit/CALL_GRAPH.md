# CALL_GRAPH.md — Execution Paths From Every Entry Point

---

## ENTRY POINT 1: FastAPI Server (`backend/app/main.py`)

```
uvicorn app.main:app --port 8001
  → app.logging_config.setup_logging()
  → app.database.init_db()
    → sqlite3: create conversations + messages tables
  → app.services.vector_store.get_vector_store()
    → Chroma(collection_name="knowledge_base", embedding_function=BGE-M3)
  → FastAPI() instance
  → Middleware: session_id, CORS, rate_limiter
  → Mount static: /audio → temp_audio/
  → Include routers:
    ├── api.qa.router         → /qa/query, /qa/query-stream, /qa/session/clear
    ├── api.conversations.router → /api/conversations (CRUD)
    ├── api.tts.router        → /qa/tts-direct, /qa/tts, /qa/tts/voices, /qa/tts/languages
    ├── api.stt.router        → /qa/stt, /qa/stt/languages
    ├── api.ws_voice.router   → /qa/ws/voice (WebSocket)
    ├── api.monitoring.router → /monitoring/
    ├── api.health.router     → /health/, /health/tts
    ├── api.auth_routes.router → /token
    ├── api.admin.router      → /admin/upload, /admin/backup/*, /admin/kb/*
    ├── api.knowledge_base.router → /admin/reindex
    └── api.voice.router      → /voice/token, /voice/call-me, /voice/twiml/outbound, /voice/stream (WS)
  → Mount static: / → frontend/dist/index.html
```

### REST: POST /qa/query
```
Client → api.qa.query_endpoint()
  → session_id = data.session_id or "default"
  → GroqService.generate_response(message, session_id)
    → detect_language(query)                    [language_detect.py]
    → normalize_query(query)                    [normalization/normalizer.py]
    → _classify_intent(query) → intent, domain  [inline regex → IntentClassifier]
    → [if GREETING/THANKS/GOODBYE] → return canned response
    → [if REPEAT] → return previous answer
    → [if YES/NO follow-up] → expand context
    → _structured_lookup(query, lang)            [handler chain]
      ├── Principal/VP combined lookup
      ├── Principal info
      ├── Vice Principal info
      ├── Fee lookup → _extract_dept_code()
      ├── Hostel info
      ├── Admission info
      ├── Student life info
      ├── Scholarship info
      ├── Language help
      ├── HOD list
      ├── Faculty name resolution → _resolve_faculty_name()
      │     ├── Alias table check
      │     └── Fuzzy match (difflib) against 219-entry faculty index
      ├── Placement stats
      ├── Seat intake
      ├── Cutoff ranks
      ├── Contact info
      ├── Campus facilities
      ├── Department info
      ├── Backlog/policy info
      ├── "Or kya" / "What else" follow-up → pass to LLM
      └── Campus visit info
    → [if None returned from structured] fallback to:
      → _retrieve_context(query)                 [vector_store.search_with_scores()]
      → _build_prompt(context, history)
      → _llm_generate(prompt) → Groq API call
      → [if safe_point] post_process_response()
    → _track_domain(query, intent)
    → telemetry.log_turn(...)                   [conversation_logger.py]
    → cache result (MD5 key, 600s TTL)
    → return {answer, voice_text, source, intent}
  → [if DEMO_SAFEPOINT] post_process_response()
  → return QueryResponse
```

### REST: POST /qa/query-stream
```
Client → api.qa.query_stream_endpoint()
  → GroqService.stream_response(query)
  → AsyncGenerator yields tokens
  → yield SSE: data: {"text": chunk}\n\n
  → yield SSE: data: [DONE]\n\n
```

### REST: POST /qa/tts-direct
```
Client → api.tts.text_to_speech_direct()
  → auto-detect language (script Unicode ranges)
  → tts_cache.get_cached_audio(text, lang, speaker) → hit? return cached.
  → SarvamService.text_to_speech(text, language, speaker, pace)
    → sarvamai.SarvamAI.text_to_speech()
  → tts_cache.store_audio(text, lang, speaker, audio_bytes)
  → return Response(audio_bytes, media_type="audio/wav")
```

### REST: GET /qa/tts/voices, /qa/tts/languages
```
→ SarvamService.get_available_voices() or get_supported_languages()
```

### REST: POST /qa/stt
```
Client (upload audio) → api.stt.speech_to_text()
  → validate format (wav/mp3/webm/ogg/aac/flac/m4a)
  → validate size (1KB - 50MB)
  → SarvamService.speech_to_text(audio_bytes, language, model="saaras:v3")
  → return {text, language, confidence}
```

### WebSocket: /qa/ws/voice
```
Client → ws_voice.voice_pipeline()
  → accept WebSocket
  → init Sarvam if key set
  → receive JSON {type:"text", data:"..."}
  → detect_language_bcp47(query)
  → create asyncio.Queue for TTS
  → start TTS worker (background task)
  → GroqService.stream_response(query) → token stream
  → for each token:
    → send {type:"token", data:token}
    → buffer into sentence
    → if sentence ends (. ! ? \n) → put in TTS queue
  → flush remaining buffer
  → TTS worker:
    → SarvamService.text_to_speech_streamed(sentence, lang)
    → send {type:"audio", data:base64(chunk)}
  → send {type:"done"}
```

### WebSocket: /voice/stream (Twilio Bridge)
```
Client (Twilio) → api.voice.twilio_stream()
  → accept WebSocket
  → create LiveKit room + token
  → connect to LiveKit room
  → publish local audio track (AudioSource 16kHz)
  → subscribe to remote audio track → forward to Twilio (μ-law)
  → loop: receive Twilio media events:
    → "start" → capture streamSid
    → "media" → decode μ-law → resample 8→16kHz → capture_frame()
    → "stop" → disconnect
```

### REST: POST /voice/token
```
→ LiveKitService.generate_token(room_name, identity)
  → livekit.api.AccessToken(api_key, secret).with_identity().with_grants().to_jwt()
```

### REST: POST /voice/call-me
```
→ TwilioService.make_outbound_call(phone, webhook_url)
  → twilio.rest.Client.calls.create(url=webhook_url, to=phone, from=twilio_number)
```

---

## ENTRY POINT 2: LiveKit Agent (`scripts/livekit_agent.py start`)

```
python scripts/livekit_agent.py start
  → Set env: TRANSFORMERS_OFFLINE=1, PYTHONUTF8=1
  → Load .env from backend/.env
  → sys.path.append(../backend)
  → app.database.init_db()
  → _run_connection_diagnostics()
    → DNS resolution check
    → TCP connectivity check (per IP)
    → TLS handshake check (per IP)
    → Authenticated WebSocket test (async)
  → livekit.agents.cli.run_app(WorkerOptions(
      entrypoint_fnc=entrypoint,
      prewarm_fnc=prewarm,
      agent_name="bcrec-agent",
    ))
```

### prewarm(proc)
```
→ silero.VAD.load(min_speech_duration=0.3, min_silence_duration=1.5)
→ SarvamSTT()          [wraps SarvamService.speech_to_text()]
→ BCRECGroqLLM()       [wraps GroqService]
→ StreamAdapter(tts=SarvamTTS(), sentence_tokenizer=SentenceTokenizer())
```

### entrypoint(ctx)
```
→ Load prewarmed components: VAD, STT, LLM, TTS from proc.userdata
→ Build INSTRUCTIONS = SYSTEM_PROMPT + "VOICE TELEPHONY RULES..."
→ voice.Agent(instructions, stt, tts, llm, vad, turn_handling)
→ voice.AgentSession(stt, tts, llm, vad)
→ ctx.connect() → LiveKit room
→ session_key = ctx.room.name
→ llm_comp.session_id = session_key
→ telemetry.start_session(session_key)
→ session.start(agent, room=ctx.room)
→ session.say("Hello! BCREC AI assistant here. How can I help you today?")
→ while room connected → sleep(1)
→ on disconnect:
  → get_groq_service().clear_session(session_key)
  → telemetry.end_session(session_key)
```

### Voice Turn Flow (LiveKit internal)
```
User speaks → Silero VAD detects speech → SarvamSTT transcribes
  → BCRECGroqLLM.generate_response(text, session_id)
    → [same as REST GroqService.generate_response()]
  → answer text → normalize_for_tts()
  → apply_lexicon() → convert_phone_numbers()
  → SarvamTTS.synthesize(text)
    → SarvamService.text_to_speech(text, language)
    → Parse WAV, extract data chunk
    → Push in 100ms chunks (4800 bytes @ 24000Hz)
  → Play audio to user (SarvamChunkedStream)
```

---

## ENTRY POINT 3: Build Pipeline (`scripts/build.py`)

```
python scripts/build.py [--validate] [--skip-embeddings]

1. validate_kb.py
   → check_schema() — 13 required sections
   → check_null_values() — recursive null scan
   → check_cross_field() — intake/fees/HOD consistency

2. generate_kb.py
   → read knowledge_base.json
   → generate_voice_answers() — trilingual TTS-ready answers
   → generate_quick_answers() — short form answers
   → write combined_kb.json

3. generate_markdown.py
   → read knowledge_base.json
   → generate 11 topic .md files
   → generate per-department .md files
   → write to knowledge_base/{topics,departments}/

4. generate_faq.py
   → read combined_kb.json
   → extract voice_ready_answers
   → write admin_faq.json

5. generate_embeddings.py
   → ingest_knowledge_base.ingest_kb()
     → get_vector_store().clear_collection()
     → process knowledge_base/**/*.md → Document chunks
     → process combined_kb.json (answers, quick_answers, flat data)
     → process uploads/ (PDF, CSV, xlsx, txt)
     → add_documents() to ChromaDB
```

---

## ENTRY POINT 4: Admin Scripts (miscellaneous)

### bash: start_server.ps1
```
→ uvicorn app.main:app --host 127.0.0.1 --port 8001 --log-level info
```

### bash: start_agent_now.ps1
```
→ python scripts/livekit_agent.py start
```

### python: scripts/system_test.py (standalone)
```
→ core imports check
→ vector store search (EN/BN/HI)
→ language detection
→ TTS cache
→ Groq LLM (EN + BN)
→ query cache hit
→ hallucination guard
```

### python: scripts/validate_retrieval.py (standalone)
```
→ VectorStoreService.search_with_scores() for 180+ test queries
→ Check duplicates, conflicts, category coverage
```

### python: scripts/performance_report.py (standalone)
```
→ Read telemetry JSONL from data/logs/conversations/
→ Compute avg/p95/p99 for retrieval, LLM, TTS
→ Failure breakdown, language distribution, CSV output
```

### python: scripts/simulate_conversations.py (standalone)
```
→ 30 simulated conversations (10 EN, 10 HI/BN, 10 Mixed)
→ Real HTTP API calls for 3 sessions
→ Synthetic telemetry for 27 sessions
→ Validate event coverage
```
