# KNOWN_RUNTIME_PATHS.md — What Actually Executes

## Production Runtime Paths (what runs in a deployed system)

### Path 1: FastAPI Server (always runs)
```
backend/app/main.py → all API routes + frontend static serving
  → ALL api/*.py routes are active
  → ALL middleware runs on every request (session_id, CORS, rate_limiter)
  → VectorStore pre-warm runs on startup (best-effort)
```

### Path 2: LiveKit Agent (runs alongside server)
```
scripts/livekit_agent.py start
  → Prewarm loads: Silero VAD, SarvamSTT, BCRECGroqLLM, SarvamTTS+StreamAdapter
  → Entrypoint handles each room connection
  → Connection diagnostics runs once before worker registration
```

### Path 3: Build Pipeline (runs manually or on deploy)
```
scripts/build.py
  → Validates KB → generates combined_kb.json + markdown files + FAQ → re-indexes ChromaDB
  → This is the ONLY path that should update knowledge_base data
```

---

## API Runtime Surfaces (every exposed endpoint)

### REST Endpoints (14 surfaces)
| Method | Path | Executes |
|--------|------|----------|
| POST | /qa/query | qa.py:query_endpoint() → GroqService.generate_response() |
| POST | /qa/query-stream | qa.py:query_stream_endpoint() → GroqService.stream_response() |
| POST | /qa/session/clear | qa.py:clear_session() → GroqService.clear_session() |
| GET | /qa/health | qa.py:health() → inline check |
| POST | /qa/debug | qa.py:debug_endpoint() → detect_language() + _retrieve_context() |
| POST | /qa/tts-direct | tts.py:text_to_speech_direct() → tts_cache → SarvamService |
| POST | /qa/tts | tts.py:text_to_speech() → SarvamService → save to disk |
| GET | /qa/tts/voices | tts.py:list_voices() → SarvamService |
| GET | /qa/tts/languages | tts.py:list_languages() → SarvamService |
| GET | /qa/tts/cache/stats | tts.py:tts_cache_stats() → tts_cache.get_stats() |
| POST | /qa/tts/cache/invalidate | tts.py:tts_cache_invalidate() → clears memory + disk cache |
| POST | /qa/stt | stt.py:speech_to_text() → validate → SarvamService |
| GET | /qa/stt/languages | stt.py:list_languages() → hardcoded dict |
| POST | /qa/debug | qa.py:debug_endpoint() |

| Method | Path | Executes |
|--------|------|----------|
| GET | /health/ | health.py:health_check() |
| GET | /health/tts | health.py:tts_health() → SarvamService |
| GET | /monitoring/ | monitoring.py:health() |

| Method | Path | Executes |
|--------|------|----------|
| POST | /token | auth_routes.py:login() → verify_password → create_access_token |
| POST | /admin/upload | admin.py:upload_file() → DocumentProcessor |
| GET | /admin/files | admin.py:list_files() |
| POST | /admin/backup/create | admin.py:create_backup() → BackupService (placeholder) |
| GET | /admin/backups | admin.py:list_backups() → BackupService |
| DELETE | /admin/backup/{name} | admin.py:delete_backup() → BackupService |
| GET | /admin/kb/faq | admin.py:list_faq() |
| POST | /admin/kb/faq/{key} | admin.py:upsert_faq() |
| DELETE | /admin/kb/faq/{key} | admin.py:delete_faq() |
| POST | /admin/kb/reload | admin.py:reload_kb() → GroqService._load_faq() |
| POST | /admin/cache/invalidate | admin.py:invalidate_cache() → GroqService.clear_cache() |
| GET | /admin/cache/stats | admin.py:cache_stats() → GroqService.get_cache_stats() |
| POST | /admin/kb/update-anchor | admin.py:update_anchor() → GroqService._update_semantic_anchor() |
| POST | /admin/reindex | knowledge_base.py:reindex() → DocumentProcessor + VectorStore |

| Method | Path | Executes |
|--------|------|----------|
| POST | /api/conversations | conversations.py:create_conversation() |
| GET | /api/conversations | conversations.py:list_conversations() |
| GET | /api/conversations/{id} | conversations.py:get_conversation() |
| GET | /api/conversations/{id}/messages | conversations.py:get_messages() |
| POST | /api/conversations/{id}/messages | conversations.py:add_message() |
| PATCH | /api/conversations/{id} | conversations.py:update_title() |
| DELETE | /api/conversations/{id} | conversations.py:delete_conversation() |
| DELETE | /api/conversations | conversations.py:delete_all() |

| Method | Path | Executes |
|--------|------|----------|
| POST | /voice/token | voice.py:get_token() → LiveKitService.generate_token() |
| POST | /voice/call-me | voice.py:call_me() → TwilioService.make_outbound_call() |
| POST | /voice/twiml/outbound | voice.py:twiml_outbound() → returns TwiML XML |
| WS | /voice/stream | voice.py:twilio_stream() → LiveKit bridge |

### WebSocket Endpoints (2 surfaces)
| Path | Executes |
|------|----------|
| /qa/ws/voice | ws_voice.py:voice_pipeline() — streaming text→LLM→TTS |
| /voice/stream | voice.py:twilio_stream() — Twilio→LiveKit bridge |

---

## Non-Runtime Paths (exist but don't execute in production)

### Scripts that are NOT referenced by any production startup:
- `scripts/dispatch_agent.py` — manual dispatch tool
- `scripts/run_agent.py` — superseded combined launcher
- `scripts/start_agent.py` — superseded launcher
- `scripts/server_bg.py` — superseded by start_server.ps1
- `scripts/start_server.py` — superseded by start_server.ps1
- `scripts/join_room.py` — manual utility
- `scripts/download_pdfs.py` — one-time data collection
- `scripts/parse_all_pdfs.py` — one-time data collection
- `scripts/parse_fee_pdfs.py` — one-time data collection
- `scripts/scrape_official_site.py` — one-time data collection
- `scripts/update_kb_from_pdfs.py` — manual data update
- `scripts/validate_retrieval.py` — standalone QA tool
- `scripts/performance_report.py` — standalone analysis tool
- `scripts/simulate_conversations.py` — standalone test harness
- `scripts/demo_readiness_test.py` — standalone test script
- `scripts/system_test.py` — standalone integration test
- `scripts/test_15_quick.py` — standalone test
- `scripts/test_faq_comprehensive.py` — standalone test
- `scripts/test_rag_150.py` — standalone test runner
- `scripts/test_vp_fix.py` — standalone debug script
- `scripts/energy_vad.py` — never imported (silero.VAD used instead)
- `scripts/start_backend.bat` — multiple overlapping launcher
- `scripts/start_backend.ps1` — multiple overlapping launcher
- `scripts/start_agent.bat` — multiple overlapping launcher

### Modules NOT imported by production code:
- `app/services/llm/base.py` — BaseLLM abstract class (0 imports)
- `app/services/conversation/responses.py` — Response templates (0 production imports)
- `app/services/query_logger.py` — QueryLogger (0 imports, superseded by conversation_logger)
- `app/services/telephony/base_adapter.py` — TelephonyAdapter (0 imports)
- `app/services/voice_session.py` — VoiceSessionManager (0 reverse dependencies found)

### Known placeholder / stub:
- `app/services/backup.py` — all methods create dummy files, not real backups
