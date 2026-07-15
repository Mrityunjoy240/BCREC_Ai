import asyncio
import json
import logging
import os
import re
import socket
import sys
import ssl
import time
import uuid
from datetime import datetime, timezone
from typing import AsyncIterable, List, Dict, Any, Literal

# Force HuggingFace to load from local disk cache â€” skips all network HEAD/GET
# requests that were causing prewarm to timeout. Model was already downloaded.
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

# Fix Windows cp1252 crash: the rupee symbol (â‚¹) and Bengali chars in LLM
# responses crash the Rich console logger. Force UTF-8 everywhere so child
# processes spawned by LiveKit IPC inherit the correct encoding.
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from dotenv import load_dotenv

_dotenv_path = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
load_dotenv(_dotenv_path, override=True)

from livekit import agents, api, rtc
from livekit.agents import (
    WorkerOptions,
    cli,
    stt,
    tts,
    llm,
    utils,
    voice,
    vad,
)
from livekit.agents.types import APIConnectOptions
from livekit.plugins import silero

from app.database import get_db, init_db
from app.services.llm.groq_service import get_groq_service, SYSTEM_PROMPT
from app.services.normalization.normalizer import normalize_for_tts
from app.services.sarvam_service import get_sarvam_service
from app.utils.conversation_logger import get_telemetry

# Initialize DB
init_db()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("livekit-agent")

# ---------------------------------------------------------------------------
# PHONETIC LEXICON & NUMBER CONVERSION
# ---------------------------------------------------------------------------
LEXICON = {
    "BCREC": "B C Roy Engineering College",
    "MAKAUT": "M A K A U T",
    "CSE": "C S E",
    "ECE": "E C E",
    "EE": "E E",
    "ME": "M E",
    "CE": "C E",
    "AIML": "A I M L",
    "AML": "A I M L",
    "IT": "I T",
    "DS": "D S",
    "CY": "C Y",
    "CSD": "C S D",
    "MBA": "M B A",
    "MCA": "M C A",
    "B.Tech": "B dot Tech",
    "M.Tech": "M dot Tech",
    "HOD": "Head of Department",
    "T&P": "T and P",
    "AICTE": "A I C T E",
    "NBA": "N B A",
    "NAAC": "N A A C",
    "NIRF": "N I R F",
    "WBJEE": "W B J E E",
    "JEE": "J E E",
    "JELET": "J E L E T",
    "LPA": "L P A",
    "CGPA": "C G P A",
}

BN_NUMS = {
    "0": "à¦¶à§‚à¦¨à§à¦¯",
    "1": "à¦à¦•",
    "2": "à¦¦à§à¦‡",
    "3": "à¦¤à¦¿à¦¨",
    "4": "à¦šà¦¾à¦°",
    "5": "à¦ªà¦¾à¦à¦š",
    "6": "à¦›à¦¯à¦¼",
    "7": "à¦¸à¦¾à¦¤",
    "8": "à¦†à¦Ÿ",
    "9": "à¦¨à¦¯à¦¼",
}


def convert_phone_numbers(text: str) -> str:
    """Only converts phone-number-like digit sequences to Bengali words."""
    processed = text

    # Identify phone numbers (7+ digits) and convert them digit-by-digit
    def digit_replacer(match):
        digits = match.group()
        return " ".join([BN_NUMS.get(d, d) for d in digits])

    # Convert sequences of 7 to 11 digits (phone numbers)
    processed = re.sub(r"\d{7,11}", digit_replacer, processed)

    # Also handle specific college numbers with dashes/spaces
    processed = re.sub(r"\d{4}[-\s]\d{7}", digit_replacer, processed)

    return processed


def apply_lexicon(text: str, lang: str) -> str:
    """Apply permanent pronunciation rules."""
    processed = text

    # For Hindi/Bengali: keep acronyms as-is (Sarvam handles them natively)
    # Only expand in English to avoid breaking Indic pronunciation
    if lang not in ("hi-IN", "bn-IN"):
        # Expand technical acronyms based on LEXICON
        for word, phonetic in sorted(LEXICON.items(), key=lambda x: -len(x[0])):
            processed = re.sub(rf"\b{re.escape(word)}\b", phonetic, processed)

        # Normalize AML to AIML for consistency
        processed = re.sub(r"\bAML\b", "A I M L", processed, flags=re.IGNORECASE)

    # 3. Handle phone numbers digit-by-digit
    if lang == "bn-IN":
        processed = convert_phone_numbers(processed)
    elif lang == "hi-IN":
        # Hindi: keep phone numbers as-is (Sarvam reads digits naturally in Hindi)
        pass
    else:
        # English: digit-by-digit for clarity
        # Landline: 0343-2501353 -> 0 3 4 3 2 5 0 1 3 5 3
        processed = re.sub(
            r"\b(\d{3,4})-(\d{7})\b",
            lambda m: " ".join(m.group(1) + m.group(2)),
            processed,
        )
        # Mobile: 9876543210 -> 9 8 7 6 5 4 3 2 1 0
        processed = re.sub(r"\b(\d{10})\b", lambda m: " ".join(m.group(1)), processed)

    # 4. Bengali normalization for natural TTS pronunciation
    if lang == "bn-IN":
        processed = processed.replace("à¦°à§à¦ªà¦¿", "à¦Ÿà¦¾à¦•à¦¾")

    return processed


# ---------------------------------------------------------------------------
# NATIVE LLM WRAPPER (Molding Groq for LiveKit v1.5.x)
# ---------------------------------------------------------------------------
class BCRECGroqLLM(llm.LLM):
    def __init__(self):
        super().__init__()
        self._service = get_groq_service()
        self.session_id = "default"

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: List[llm.Tool] | None = None,
        conn_options: APIConnectOptions = agents.DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: agents.NotGivenOr[bool] = agents.NOT_GIVEN,
        tool_choice: agents.NotGivenOr[llm.ToolChoice] = agents.NOT_GIVEN,
        extra_kwargs: agents.NotGivenOr[Dict[str, Any]] = agents.NOT_GIVEN,
    ) -> llm.LLMStream:
        return BCRECGroqStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
            service=self._service,
            session_id=self.session_id,
        )


class BCRECGroqStream(llm.LLMStream):
    def __init__(self, llm_inst, *, chat_ctx, tools, conn_options, service, session_id="default"):
        super().__init__(llm=llm_inst, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
        self._service = service
        self._session_id = session_id
        self._id = utils.shortuuid()

    async def _run(self):
        t0 = time.time()
        query = ""

        # Collect user + assistant messages only (skip system â€” _build_messages adds SYSTEM_PROMPT)
        history = []
        for msg in self.chat_ctx.messages():
            if msg.role == "system":
                continue
            content_text = ""
            if isinstance(msg.content, str):
                content_text = msg.content
            elif isinstance(msg.content, list):
                parts = []
                for c in msg.content:
                    if isinstance(c, str):
                        parts.append(c)
                    elif hasattr(c, "text"):
                        parts.append(c.text)
                content_text = " ".join(parts)

            if msg.role == "user":
                query = content_text

            if content_text:
                history.append({"role": msg.role, "content": content_text})

        # Cap at last 12 turns (6 user + 6 assistant) to prevent unbounded prompt growth
        if len(history) > 12:
            history = history[-12:]

        logger.info(f"LLM Query: '{query[:100]}...' History: {len(history)} turns")

        first_chunk = True
        response_parts = []
        async for chunk in self._service.stream_response(
            query, session_id=self._session_id, conversation_history=history[:-1]
        ):
            if first_chunk:
                ttft = round((time.time() - t0) * 1000)
                logger.info(f"TURN TTFT={ttft}ms (user speech â†’ LLM first token)")
                first_chunk = False
            response_parts.append(chunk)
            self._event_ch.send_nowait(
                llm.ChatChunk(id=self._id, delta=llm.ChoiceDelta(role="assistant", content=chunk))
            )

        turn_total = round((time.time() - t0) * 1000)
        full_response = "".join(response_parts)
        logger.info(f"TURN COMPLETE total={turn_total}ms (user speech â†’ LLM done)")

        telemetry = get_telemetry()
        telemetry.log_llm_complete(
            self._session_id,
            turn_number=0,
            response=full_response,
            latency_ms=turn_total,
        )

        self._event_ch.close()


# ---------------------------------------------------------------------------
# SARVAM COMPONENTS (Molding for v1.5.x)
# ---------------------------------------------------------------------------
# BCREC acronyms Sarvam STT frequently mis-transcribes
_STT_ACRONYM_FIXES = [
    (r"\bcse[\s-]?aml\b", "CSE-AIML"),
    (r"\bcs e[\s-]?aml\b", "CSE-AIML"),
    (r"\bcciml\b", "AIML"),
    (r"\ba[\s-]?i[\s-]?ml\b", "AIML"),
    (r"\bcsd\b", "CSD"),
    (r"\bdata sci\b", "Data Science"),
    (r"\bcyber sec\b", "Cyber Security"),
    (r"\binfo tech\b", "Information Technology"),
    (r"\belec[ -]?comm\b", "ECE"),
    (r"\bh[\s-]?o[\s-]?d\b", "HOD"),
    (r"\bprincipal\b", "Principal"),
]


def _fix_stt_acronyms(text: str) -> str:
    """Normalize Sarvam STT output before passing to LLM."""
    result = text
    for pattern, replacement in _STT_ACRONYM_FIXES:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    if result != text:
        logger.info(f"STT corrected: '{text}' -> '{result}'")
    return result


class SarvamSTT(stt.STT):
    def __init__(self):
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=False, interim_results=False, diarization=False, offline_recognize=True
            )
        )
        self.service = get_sarvam_service(os.getenv("SARVAM_API_KEY"))

    async def _recognize_impl(
        self,
        buffer: utils.AudioBuffer,
        *,
        language: str | None = None,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        _stt_t0 = time.perf_counter()
        try:
            frame = buffer if isinstance(buffer, rtc.AudioFrame) else utils.merge_frames(buffer)
            audio_data = frame.to_wav_bytes()
            result = await self.service.speech_to_text(
                audio_data, language="auto", model="saaras:v3"
            )
            _stt_ms = (time.perf_counter() - _stt_t0) * 1000
            if result.get("success"):
                text = result.get("text", "")
                text = _fix_stt_acronyms(text)
                logger.info(
                    f"[PERF] STT ............. {_stt_ms:>7.1f} ms  transcript='{text[:60]}'"
                )
                return stt.SpeechEvent(
                    type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                    alternatives=[
                        stt.SpeechData(
                            text=text, confidence=0.95, language=result.get("language", "en-IN")
                        )
                    ],
                )
            logger.info(f"[PERF] STT ............. {_stt_ms:>7.1f} ms  (no result)")
            return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT, alternatives=[])
        except Exception as e:
            _stt_ms = (time.perf_counter() - _stt_t0) * 1000
            logger.error(f"[PERF] STT ............. {_stt_ms:>7.1f} ms  ERROR: {e}")
            return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT, alternatives=[])


class SarvamTTS(tts.TTS):
    def __init__(self):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False), sample_rate=24000, num_channels=1
        )
        self.service = get_sarvam_service(os.getenv("SARVAM_API_KEY"))

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = agents.DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        logger.info(f"SarvamTTS.synthesize called for: {text[:50]}...")
        return SarvamChunkedStream(
            tts=self, input_text=text, conn_options=conn_options, service=self.service
        )


class SarvamChunkedStream(tts.ChunkedStream):
    def __init__(self, *, tts, input_text, conn_options, service):
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self.service = service

    async def _run(self, emitter: tts.AudioEmitter):
        _tts_t0 = time.perf_counter()
        text = self._input_text
        if not text or not text.strip():
            emitter.end_input()
            return

        # Identify language
        lang = (
            "bn-IN"
            if re.search(r"[\u0980-\u09FF]", text)
            else "hi-IN"
            if re.search(r"[\u0900-\u097F]", text)
            else "en-IN"
        )

        # Apply entity_dict TTS normalization, then lexicon and phone formatting before TTS
        text = normalize_for_tts(text.strip())
        from app.services.normalization.normalizer import prepare_numbers_for_tts
        text = prepare_numbers_for_tts(text, lang)
        text = apply_lexicon(text, lang)

        # Pick speaker from shared map
        from app.utils.voice_utils import LANG_SPEAKER_MAP

        speaker = LANG_SPEAKER_MAP.get(lang, "shubh")

        logger.info(f"Synthesizing: {text[:60]}... (lang={lang}, speaker={speaker})")

        # Initialize emitter BEFORE the API call so the audio pipeline is
        # ready as soon as the response arrives â€” reduces perceived stall.
        emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=24000,
            num_channels=1,
            mime_type="audio/pcm",
        )

        # Use streaming TTS — audio chunks arrive and play immediately
        total_bytes = 0
        _play_t0 = time.perf_counter()
        async for chunk in self.service.text_to_speech_streamed(
            text, speaker=speaker, language=lang, normalize=False
        ):
            if chunk:
                # Strip WAV header from each chunk if present
                audio_data = chunk
                if audio_data.startswith(b"RIFF"):
                    i = 12
                    while i < len(audio_data) - 8:
                        chunk_id = audio_data[i:i+4]
                        chunk_size = int.from_bytes(audio_data[i+4:i+8], "little")
                        if chunk_id == b"data":
                            audio_data = audio_data[i+8:i+8+chunk_size]
                            break
                        i += 8 + chunk_size
                emitter.push(audio_data)
                total_bytes += len(audio_data)

        _tts_ms = (time.perf_counter() - _tts_t0) * 1000
        _play_ms = (time.perf_counter() - _play_t0) * 1000
        logger.info(f"[PERF] TTS+Playback .... {_tts_ms:>7.1f} ms  ({total_bytes // 24000 // 2}s audio, streaming)")

        emitter.end_input()


from livekit.agents.tts import StreamAdapter
from livekit.agents.tokenize.basic import SentenceTokenizer


# ---------------------------------------------------------------------------
# PREWARM â€” runs ONCE per worker process, not in every subprocess fork.
# This is the correct LiveKit pattern to avoid re-loading BGE-M3 repeatedly.
# ---------------------------------------------------------------------------
def prewarm(proc: agents.JobProcess):
    logger.info("Prewarming agent components (VAD, STT, LLM, TTS)...")
    proc.userdata["vad"] = silero.VAD.load(min_speech_duration=0.3, min_silence_duration=1.5)
    proc.userdata["stt"] = SarvamSTT()
    proc.userdata["llm"] = BCRECGroqLLM()
    proc.userdata["tts"] = StreamAdapter(tts=SarvamTTS(), sentence_tokenizer=SentenceTokenizer())
    logger.info("Prewarm complete â€” agent is ready to accept jobs.")


# ---------------------------------------------------------------------------
# MAIN ENTRYPOINT (The Worker Model)
# ---------------------------------------------------------------------------
async def entrypoint(ctx: agents.JobContext):
    logger.info(f"Starting agent job {ctx.job.id}")

    # Pull pre-warmed components from process userdata (loaded once by prewarm)
    vad_inst = ctx.proc.userdata["vad"]
    stt_comp = ctx.proc.userdata["stt"]
    llm_comp = ctx.proc.userdata["llm"]
    tts_comp = ctx.proc.userdata["tts"]

    # Single source of truth: SYSTEM_PROMPT from groq_service.py
    # Voice-specific additions layered on top for telephony optimizations.
    INSTRUCTIONS = (
        SYSTEM_PROMPT
        + """

VOICE TELEPHONY RULES (ADDITIONAL):
- Be concise for voice. 2-4 short sentences is fine.
- Use common English loanwords in Bengali (à¦¡à¦¿à¦ªà¦¾à¦°à§à¦Ÿà¦®à§‡à¦¨à§à¦Ÿ, à¦à¦¡à¦®à¦¿à¦¶à¦¨, à¦«à¦¿à¦¸).
- Phone numbers stay as digits (0343-2501353) for digit-by-digit TTS."""
    )

    agent = voice.Agent(
        instructions=INSTRUCTIONS,
        stt=stt_comp,
        tts=tts_comp,
        llm=llm_comp,
        vad=vad_inst,
        turn_handling={
            "interruption": {"enabled": True, "mode": "vad", "min_words": 2},
            "endpointing": {"min_delay": 0.3, "max_delay": 2.0},
        },
    )

    session = voice.AgentSession(
        stt=stt_comp,
        tts=tts_comp,
        llm=llm_comp,
        vad=vad_inst,
    )

    await ctx.connect()
    logger.info(f"Connected to room: {ctx.room.name}")

    # Set participant-specific session key for conversation isolation
    session_key = ctx.room.name
    llm_comp.session_id = session_key
    logger.info(f"Session key: {session_key}")

    # Start conversation telemetry for this session
    telemetry = get_telemetry()
    conv_id = telemetry.start_session(session_key)
    logger.info(f"[TELEMETRY] Session started: {session_key} conv={conv_id}")

    await session.start(agent, room=ctx.room)
    logger.info("Agent session started")

    await asyncio.sleep(0.5)
    logger.info("Sending greeting...")
    # Greeting: interruptible, concise, language-preserving (defaults to English on first visit)
    greeting = "Hello! Welcome to BCREC. I can help you with admissions, fees, placements, or anything about the college. What would you like to know?"
    try:
        from app.services.llm.safe_point import DEMO_SAFEPOINT, get_greeting

        # if DEMO_SAFEPOINT:
        #     greeting = get_greeting()
    except ImportError:
        pass
    session.say(greeting, allow_interruptions=True)

    while ctx.room.isconnected():
        await asyncio.sleep(1)

    get_groq_service().clear_session(session_key)
    telemetry.end_session(session_key)
    logger.info("Room disconnected, session cleared, exiting entrypoint")


# ---------------------------------------------------------------------------
# Connection Diagnostics â€” runs once before worker startup
# ---------------------------------------------------------------------------
def _gather_dns_evidence(hostname: str) -> None:
    """When DNS fails, collect evidence about where the failure came from."""
    import subprocess

    ts = datetime.now(timezone.utc).isoformat()

    try:
        result = subprocess.run(
            ["nslookup", hostname],
            capture_output=True,
            text=True,
            timeout=5,
        )
        logger.info(f"[Diag {ts}] nslookup {hostname}:\n{result.stdout.strip()}")
        if result.stderr.strip():
            logger.warning(f"[Diag {ts}] nslookup stderr: {result.stderr.strip()}")
    except Exception as e:
        logger.warning(f"[Diag {ts}] nslookup failed: {e}")

    hosts_path = r"C:\Windows\System32\drivers\etc\hosts"
    try:
        with open(hosts_path) as f:
            for line in f:
                if hostname in line and not line.strip().startswith("#"):
                    logger.warning(f"[Diag {ts}] Hosts file entry: {line.strip()}")
    except Exception as e:
        logger.warning(f"[Diag {ts}] Cannot read hosts file: {e}")

    for test_host in ["google.com", "livekit.cloud"]:
        try:
            t0 = time.time()
            socket.getaddrinfo(test_host, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
            ms = (time.time() - t0) * 1000
            logger.info(f"[Diag {ts}] DNS cross-check: {test_host} resolves OK ({ms:.1f}ms)")
        except socket.gaierror as e:
            logger.error(
                f"[Diag {ts}] DNS cross-check: {test_host} also FAILED "
                f"(errno={e.args[0]} {e.args[1]})"
            )

    try:
        result = subprocess.run(
            ["ipconfig", "/all"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines():
            lowered = line.strip().lower()
            if "dns" in lowered or "dns-suffix" in lowered:
                logger.info(f"[Diag {ts}] DNS config: {line.strip()}")
    except Exception as e:
        logger.warning(f"[Diag {ts}] ipconfig failed: {e}")


def _run_connection_diagnostics() -> None:
    """Lightweight connectivity check before LiveKit worker starts.
    Logs DNS resolution, TCP, TLS, and WebSocket status with timestamps.
    Never blocks startup â€” just logs results."""
    from urllib.parse import urlparse

    url = os.environ.get("LIVEKIT_URL", "")
    if not url:
        logger.info("[Diag] LIVEKIT_URL not set â€” skipping connection diagnostics")
        return

    parsed = urlparse(url)
    hostname = parsed.netloc
    port = 443
    ts = datetime.now(timezone.utc).isoformat()

    logger.info(f"[Diag {ts}] Target: {hostname}:{port}")

    # ---- 1. DNS resolution ----
    t0 = time.time()
    try:
        addrs = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        dns_ms = (time.time() - t0) * 1000
        ips = list(dict.fromkeys(a[4][0] for a in addrs))
        logger.info(f"[Diag {ts}] DNS OK: {hostname} -> {ips} in {dns_ms:.1f}ms")
    except socket.gaierror as e:
        dns_ms = (time.time() - t0) * 1000
        logger.error(
            f"[Diag {ts}] DNS FAILED: {hostname} errno={e.args[0]} ({e.args[1]}) in {dns_ms:.1f}ms"
        )
        _gather_dns_evidence(hostname)
        return

    # ---- 2. TCP connectivity ----
    tcp_ok = False
    for ip in ips:
        t0 = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            sock.connect((ip, port))
            tcp_ms = (time.time() - t0) * 1000
            logger.info(f"[Diag {ts}] TCP OK: {ip}:{port} in {tcp_ms:.1f}ms")
            tcp_ok = True
            sock.close()
            break
        except Exception as e:
            tcp_ms = (time.time() - t0) * 1000
            logger.error(f"[Diag {ts}] TCP FAILED: {ip}:{port} -> {e} in {tcp_ms:.1f}ms")
        finally:
            sock.close()

    if not tcp_ok:
        logger.error(f"[Diag {ts}] TCP: all IPs unreachable â€” skipping further checks")
        return

    # ---- 3. TLS handshake ----
    tls_ok = False
    for ip in ips:
        t0 = time.time()
        ctx = ssl.create_default_context()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            wrapped = ctx.wrap_socket(sock, server_hostname=hostname)
            wrapped.connect((ip, port))
            tls_ms = (time.time() - t0) * 1000
            logger.info(f"[Diag {ts}] TLS OK: {hostname} ({ip}) in {tls_ms:.1f}ms")
            tls_ok = True
            wrapped.close()
            break
        except Exception as e:
            tls_ms = (time.time() - t0) * 1000
            logger.error(f"[Diag {ts}] TLS FAILED: {hostname} ({ip}) -> {e} in {tls_ms:.1f}ms")
        finally:
            sock.close()

    if not tls_ok:
        logger.error(f"[Diag {ts}] TLS: all IPs failed â€” skipping WebSocket test")
        return

    # ---- 4. Authenticated WebSocket (optional, always logs result) ----
    try:
        from urllib.parse import urljoin

        import aiohttp
        from livekit import api

        api_key = os.environ.get("LIVEKIT_API_KEY", "")
        api_secret = os.environ.get("LIVEKIT_API_SECRET", "")
        token = (
            api.AccessToken(api_key, api_secret).with_grants(api.VideoGrants(agent=True)).to_jwt()
        )

        scheme = parsed.scheme.replace("http", "ws")
        base = f"{scheme}://{parsed.netloc}{parsed.path}".rstrip("/") + "/"
        agent_url = urljoin(base, "agent")

        async def _ws_test():
            t0 = time.time()
            connector = aiohttp.TCPConnector(family=socket.AF_INET)
            session = aiohttp.ClientSession(connector=connector)
            try:
                async with session.ws_connect(
                    agent_url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientWSTimeout(ws_close=5),
                    autoping=True,
                ) as ws:
                    ws_ms = (time.time() - t0) * 1000
                    logger.info(f"[Diag {ts}] WebSocket OK: {agent_url} in {ws_ms:.1f}ms")
                    await ws.close()
            except Exception as e:
                ws_ms = (time.time() - t0) * 1000
                logger.error(
                    f"[Diag {ts}] WebSocket FAILED: {agent_url} -> "
                    f"{type(e).__name__}: {e} in {ws_ms:.1f}ms"
                )
            finally:
                await session.close()

        asyncio.run(_ws_test())
    except Exception as e:
        logger.warning(f"[Diag {ts}] WebSocket test setup error: {e}")


if __name__ == "__main__":
    _run_connection_diagnostics()

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name="bcrec-agent",
            initialize_process_timeout=120.0,  # BGE-M3 needs ~30s to load from cache
        )
    )
