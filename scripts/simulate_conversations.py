"""
Simulated Conversation Harness
==============================
Validates telemetry pipeline by generating 30 conversations against the running
backend. Uses real API calls for a representative subset and direct telemetry
injection for the remainder to keep runtime feasible (~5 min).

Usage:
    python scripts/simulate_conversations.py

Requires:
    - Backend running on http://localhost:8000
    - httpx (auto-installed if missing)
"""

import asyncio
import json
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT / "backend"))

try:
    import httpx
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx

from app.utils.conversation_logger import get_telemetry

BASE_URL = "http://localhost:8000"
API_QUERY = f"{BASE_URL}/qa/query"
API_CLEAR = f"{BASE_URL}/qa/session/clear"
LOG_DIR = _PROJECT_ROOT / "data" / "logs" / "conversations"
LOG_DIR.mkdir(parents=True, exist_ok=True)

REQUIRED_EVENT_TYPES = [
    "SESSION_START",
    "TURN_INPUT",
    "TURN_RETRIEVAL",
    "TURN_LLM_COMPLETE",
    "TURN_LLM_LIFECYCLE",
    "TURN_ERROR",
    "TURN_VALIDATION",
    "TURN_VOICE",
    "SPECIAL_EVENT",
    "SESSION_SUMMARY",
]

# ---------------------------------------------------------------------------
# 30 conversation definitions (10 English, 10 Hindi/Bengali, 10 Mixed)
# ---------------------------------------------------------------------------

EN_SESSIONS = [
    {
        "name": "en_cse_fees",
        "turns": [
            "Hello",
            "What is the fee for CSE?",
            "fees",
            "What about hostel fees and mess charges?",
            "Who is the principal of this college?",
            "What is the placement percentage of CSE?",
            "tell me more about the chemistry department",
        ],
    },
    {
        "name": "en_admission",
        "turns": [
            "Hi there",
            "How can I apply for admission?",
            "seats",
            "What is the eligibility criteria and what documents are needed?",
            "Is there any scholarship for SC students?",
            "What is the last date of application?",
            "Does the college have a swimming pool?",
        ],
    },
    {
        "name": "en_placement_hostel",
        "turns": [
            "Good morning",
            "What is the average placement package?",
            "principal",
            "Tell me about the hostel facilities and the mess fees",
            "What companies visited for CSE placements?",
            "Is there a girl's hostel?",
            "Who is the CEO of Google?",
        ],
    },
    {
        "name": "en_ece_ee",
        "turns": [
            "Hello",
            "What is the fee for ECE?",
            "How many seats in EE?",
            "What is the placement of ECE and what companies come for EE?",
            "seats",
            "Does ECE have a separate building?",
            "What is the cutoff for WBJEE?",
            "Tell me about the Mars mission internship",
        ],
    },
    {
        "name": "en_it_general",
        "turns": [
            "Hi",
            "What courses are offered in IT?",
            "fees",
            "What is the placement rate of IT and how many companies visited?",
            "Who is the HOD of IT?",
            "Is there any sports facility?",
            "Can I get admission with 50 percent in boards?",
            "Is BCREC affiliated to MAKAUT?",
        ],
    },
    {
        "name": "en_me_ce",
        "turns": [
            "Hello",
            "Tell me about Mechanical Engineering fees",
            "seats",
            "What is the placement of ME and what about Civil Engineering?",
            "What is the library timings?",
            "Is there any canteen in the college?",
            "Does the college have an NSS chapter?",
        ],
    },
    {
        "name": "en_csd_aiml",
        "turns": [
            "Hi there",
            "What is CSD and AIML?",
            "Tell me more about the fees for AIML",
            "Who is the best teacher in CSE?",
            "What is the salary after CSD?",
            "How to apply for lateral entry?",
            "Does the college have a medical college?",
        ],
    },
    {
        "name": "en_scholarship_transport",
        "turns": [
            "Good morning",
            "Is there scholarship for OBC students?",
            "seats",
            "What is the transport facility and bus fee?",
            "What is the lab facilities for CSE?",
            "principal",
            "Is there any airport near the college?",
        ],
    },
    {
        "name": "en_faq_repeat",
        "turns": [
            "Hello",
            "What is the college timing?",
            "repeat",
            "What are the documents needed for admission and what is the fees?",
            "What is the dress code?",
            "fees",
            "Who is the founder of Microsoft?",
        ],
    },
    {
        "name": "en_general_knowledge",
        "turns": [
            "Hi",
            "What is the address of BCREC?",
            "How many departments are there?",
            "What are the research labs and what is the PhD program?",
            "principal name",
            "What is the student intake per year?",
            "Is there a robotics lab?",
            "Tell me about the cricket team captain of India",
        ],
    },
]

HI_BN_SESSIONS = [
    {
        "name": "hi_cse_fees",
        "turns": [
            "नमस्ते",
            "CSE ki fees kitni hai?",
            "fees",
            "Hostel fees aur mess charges kya hain?",
            "principal kaun hain?",
            "CSE ka placement percentage kya hai?",
            "chemistry department ke baare mein batao",
        ],
    },
    {
        "name": "bn_admission",
        "turns": [
            "হ্যালো",
            "ভর্তি হতে কী কী লাগবে?",
            "সিট কতগুলো",
            "এলিজিবিলিটি কী আর কী কী ডকুমেন্ট লাগবে?",
            "SC স্টুডেন্টদের জন্য কি কোনো স্কলারশিপ আছে?",
            "আবেদনের শেষ তারিখ কবে?",
            "কলেজে কি সুইমিং পুল আছে?",
        ],
    },
    {
        "name": "hi_placement",
        "turns": [
            "नमस्ते",
            "Average placement package kya hai?",
            "principal",
            "Hostel ki suvidha aur mess fees ke baare mein batao",
            "CSE placement mein kaun kaun si companies aayi?",
            "Kya ladkiyon ka alag hostel hai?",
            "Google ka CEO kaun hai?",
        ],
    },
    {
        "name": "bn_ece_ee",
        "turns": [
            "হ্যালো",
            "ECE er fees koto?",
            "EE te kitna seat ache?",
            "ECE r placement kemon ar EE te ki ki company ashe?",
            "সিট কত",
            "ECE er ki alada building ache?",
            "WBJEE er cutoff koto?",
            "মঙ্গল মিশন internship সম্পর্কে বলো",
        ],
    },
    {
        "name": "hi_it_general",
        "turns": [
            "हाय",
            "IT mein kaun se courses hain?",
            "fees",
            "IT ka placement rate kya hai aur kitni companies aayi?",
            "IT ka HOD kaun hai?",
            "Koi sports ki facility hai?",
            "Kya main 50 percent marks se admission le sakta hoon?",
            "Kya BCREC MAKAUT se affiliated hai?",
        ],
    },
    {
        "name": "bn_me_ce",
        "turns": [
            "হ্যালো",
            "মেকানিক্যাল ইঞ্জিনিয়ারিং এর ফিস কত?",
            "সিট সংখ্যা কত?",
            "ME r placement kemon ar CE te ki?",
            "লাইব্রেরীর সময় কত?",
            "কলেজে কি ক্যান্টিন আছে?",
            "NSS চ্যাপ্টার আছে?",
        ],
    },
    {
        "name": "hi_csd_aiml",
        "turns": [
            "नमस्ते",
            "CSD aur AIML kya hai?",
            "AIML ki fees ke baare mein batao",
            "CSE mein sabse achha teacher kaun hai?",
            "CSD ke baad kitni salary milti hai?",
            "Lateral entry ke liye kaise apply karein?",
            "क्या कॉलेज में मेडिकल कॉलेज है?",
        ],
    },
    {
        "name": "bn_scholarship",
        "turns": [
            "সুপ্রভাত",
            "OBC ছাত্রদের জন্য কি স্কলারশিপ আছে?",
            "সিট কতগুলো",
            "পরিবহন সুবিধা আর বাস ভাড়া কত?",
            "CSE er lab ki ki ache?",
            "প্রিন্সিপাল কে?",
            "কলেজের কাছে কি এয়ারপোর্ট আছে?",
        ],
    },
    {
        "name": "hi_faq_repeat",
        "turns": [
            "हैलो",
            "College ka timing kya hai?",
            "repeat",
            "Admission ke liye kya documents chahiye aur fees kitni hai?",
            "Dress code kya hai?",
            "fees kya hai",
            "Microsoft ka founder kaun hai?",
        ],
    },
    {
        "name": "bn_general",
        "turns": [
            "হাই",
            "BCREC এর ঠিকানা কী?",
            "কয়টা ডিপার্টমেন্ট আছে?",
            "Research labs ki ache aur PhD program ki?",
            "প্রিন্সিপালের নাম কী",
            "প্রতি বছর কত ছাত্র ভর্তি হয়?",
            "রোবোটিক্স ল্যাব আছে?",
            "ভারতের ক্রিকেট অধিনায়ক কে?",
        ],
    },
]

MIXED_SESSIONS = [
    {
        "name": "mx_codeswitch_fees",
        "turns": [
            "Hello",
            "CSE ka fee structure kya hai? Batao na",
            "fees",
            "Hostel fee batao aur mess ka bhi. Total kitna hoga?",
            "Principal ke baare mein batao",
            "Aur placement kaisa hai CSE mein?",
            "What is the cutoff for JEE?",
            "Bhai Mars mission kaise join karein?",
        ],
    },
    {
        "name": "mx_confused_admission",
        "turns": [
            "Hi",
            "Mujhe admission lena hai. Kya karna hoga?",
            "seats",
            "Documents ki list do aur fees bhi batao please",
            "chemistry teacher kaisa hai?",
            "Lab facilities ache hain?",
            "Scholarship milti hai kya?",
            "Does the college have space for parking?",
        ],
    },
    {
        "name": "mx_bangla_hinglish",
        "turns": [
            "Hello dada",
            "CSE er fees koto bolben?",
            "Aur placement kemon?",
            "Fees, seats, placement, hostel — sab batao",
            "principal",
            "Ei college ki BCREC bolte?",
            "Tell me about genetic engineering course",
        ],
    },
    {
        "name": "mx_rapid_fire",
        "turns": [
            "Hey",
            "fees",
            "seats",
            "placement",
            "principal",
            "hostel",
            "admission",
            "What is the full address of this college?",
        ],
    },
    {
        "name": "mx_ambigous_repeat",
        "turns": [
            "Hello",
            "CSE ke baare mein batao",
            "?",
            "Fees, placement, faculty sab batao detail mein",
            "repeat",
            "I don't think you answered properly",
            "What is the meaning of life?",
        ],
    },
    {
        "name": "mx_scholarship_mess",
        "turns": [
            "Hi",
            "AIML course hai kya?",
            "Fees kitni hai AIML ki?",
            "Aur placement kya hai? Who visits for placement?",
            "Scholarship SC ko milta hai?",
            "Mess ka khana kaisa hai?",
            "Does the college have an auditorium?",
            "Who is the chief minister of West Bengal?",
        ],
    },
    {
        "name": "mx_lateral_docs",
        "turns": [
            "Hello",
            "Lateral entry available hai?",
            "seats",
            "Documents kya chahiye lateral ke liye aur fees kitni?",
            "CSE mein lateral ke kitne seats?",
            "placement bhi batao lateral walo ka",
            "Is there a gym in the college?",
        ],
    },
    {
        "name": "mx_ee_placement",
        "turns": [
            "Hi",
            "EE department ke baare mein batao",
            "fees",
            "EE ka placement aur companies both batao",
            "Girls hostel hai kya?",
            "What is the fee for girls hostel?",
            "Can I pay fees in installments?",
        ],
    },
    {
        "name": "mx_short_queries",
        "turns": [
            "Hello",
            "CSE",
            "fees",
            "placement",
            "hostel",
            "library",
            "sports",
            "Who invented the internet?",
        ],
    },
    {
        "name": "mx_bn_en_chaos",
        "turns": [
            "Hi",
            "B.Tech er kon kon department ache?",
            "Placement kemon? Maximum package koto?",
            "Fees, seats, cutoff — three things batao",
            "Repeat karo",
            "CSE te kitna admission hoy?",
            "Does the college accept donations for admission?",
        ],
    },
]

ALL_SESSIONS = (
    [("en", s) for s in EN_SESSIONS]
    + [("hi-bn", s) for s in HI_BN_SESSIONS]
    + [("mx", s) for s in MIXED_SESSIONS]
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def clear_session(client: httpx.AsyncClient, session_id: str):
    try:
        await client.post(API_CLEAR, json={"session_id": session_id})
    except Exception:
        pass


async def send_query(client: httpx.AsyncClient, session_id: str, message: str) -> dict:
    # Simulated STT pipeline delay
    await asyncio.sleep(random.randint(50, 200) / 1000)

    payload = {"message": message, "session_id": session_id}
    t0 = time.time()
    resp = await client.post(API_QUERY, json=payload, timeout=120)
    elapsed = (time.time() - t0) * 1000

    # Simulated TTS pipeline delay
    await asyncio.sleep(random.randint(100, 400) / 1000)

    result = (
        resp.json() if resp.status_code == 200 else {"error": resp.text, "status": resp.status_code}
    )
    result["_elapsed_ms"] = round(elapsed, 1)
    return result


def generate_synthetic_events(session_id: str, turn_number: int, message: str, lang: str = "en"):
    """Generate synthetic telemetry events matching real pipeline output."""
    telemetry = get_telemetry()
    telemetry._ensure_session(session_id)

    # Simulate language detection
    detected_lang = lang
    if any("\u0900" <= c <= "\u097f" for c in message):
        detected_lang = "hi"
    elif any("\u0980" <= c <= "\u09ff" for c in message):
        detected_lang = "bn"

    is_greeting = message.lower() in (
        "hello",
        "hi",
        "hey",
        "hi there",
        "good morning",
        "नमस्ते",
        "হ্যালো",
        "হাই",
        "সুপ্রভাত",
        "हाय",
        "हैलो",
    )
    is_ambiguous = message.lower() in (
        "fees",
        "seats",
        "principal",
        "placement",
        "hostel",
        "admission",
        "library",
        "sports",
        "repeat",
        "সিট",
        "সিট কত",
        "সিট কতগুলো",
        "সিট সংখ্যা কত?",
        "fees kya hai",
        "principal kaun hain?",
    )
    is_repeat = message.lower() in ("repeat", "repeat karo") or message == "?"

    intent = "greeting" if is_greeting else ("repeat" if is_repeat else "rag_query")

    # TURN_INPUT
    telemetry.log_turn_input(
        session_id,
        turn_number=turn_number,
        raw_transcript=message,
        expanded_transcript=message if is_ambiguous else "",
        detected_language=detected_lang,
        detected_intent=intent,
        follow_up_topic=message if is_repeat else "",
    )

    # TURN_RETRIEVAL
    sim_confidence = round(random.uniform(0.6, 0.95), 4)
    sim_latency = round(random.uniform(80, 350), 1)
    top_chunks = [
        {
            "rank": i + 1,
            "similarity_score": round(random.uniform(0.5, 0.95), 4),
            "section": s,
            "subsection": "",
            "source": "kb_faq",
            "document_id": f"doc_{i}",
            "preview": f"Sample chunk {i + 1} from {s}...",
        }
        for i, s in enumerate(
            random.sample(
                ["fees", "admission", "placement", "hostel", "courses", "about"],
                k=min(6, random.randint(3, 6)),
            )
        )
    ]
    discarded = (
        [
            {"reason": r, "section": s, "subsection": "", "preview": "dup chunk..."}
            for r, s in [
                ("duplicate section:subsection", "fees"),
                ("duplicate section:subsection", "placement"),
            ]
        ]
        if random.random() > 0.5
        else []
    )
    telemetry.log_retrieval(
        session_id,
        turn_number=turn_number,
        retrieval_query=message,
        confidence=sim_confidence,
        latency_ms=sim_latency,
        top_chunks=top_chunks,
        chunks_passed=len(top_chunks) - len(discarded),
        chunks_discarded=discarded,
    )

    # SPECIAL_EVENT for follow-up / empty context
    if is_ambiguous:
        telemetry.log_special_event(
            session_id,
            turn_number=turn_number,
            event_type="FOLLOW_UP_QUERY",
            details={"original": message, "expanded": f"tell me about {message}"},
        )

    # TURN_PROMPT
    telemetry.log_prompt(
        session_id,
        turn_number=turn_number,
        total_prompt_chars=random.randint(2000, 8000),
        context_chars=random.randint(500, 3000),
        history_chars=random.randint(200, 2000),
        history_turns=min(turn_number - 1, 10),
    )

    # TURN_LLM_START + TURN_LLM_COMPLETE
    telemetry.log_llm_start(session_id, turn_number=turn_number)
    sim_answer = f"This is a simulated answer for: {message[:80]}."
    sim_llm_latency = round(random.uniform(1000, 8000), 1)
    telemetry.log_llm_complete(
        session_id,
        turn_number=turn_number,
        ttft_ms=round(random.uniform(200, 1500), 1),
        completion_time_ms=round(random.uniform(800, 6000), 1),
        response=sim_answer,
        model="llama-3.1-8b-instant",
        tokens_prompt=random.randint(200, 1500),
        tokens_completion=random.randint(50, 400),
        latency_ms=sim_llm_latency,
    )

    # TURN_LLM_LIFECYCLE (detailed timing)
    now = time.time()
    sim_ttft = round(random.uniform(200, 1500), 1)
    sim_gen = round(sim_llm_latency * random.uniform(0.6, 0.9), 1)
    sim_post = round(sim_llm_latency - sim_ttft - sim_gen, 1)
    telemetry.log_llm_lifecycle(
        session_id,
        turn_number=turn_number,
        request_start=now - (sim_ttft + sim_gen + sim_post) / 1000,
        api_request_sent=now - (sim_gen + sim_post) / 1000,
        first_token_received=now - (sim_gen + sim_post) / 1000 + sim_ttft / 1000,
        last_token_received=now - sim_post / 1000,
        postprocessing_start=now - sim_post / 1000,
        postprocessing_end=now,
        ttft_ms=sim_ttft,
        generation_duration_ms=sim_gen,
        postprocessing_duration_ms=sim_post,
        total_llm_duration_ms=sim_llm_latency,
        output_tokens=random.randint(50, 400),
        estimated_tokens_per_second=round(random.uniform(10, 60), 2),
        streaming_duration_ms=round(sim_gen * random.uniform(0.8, 1.0), 1),
        model="llama-3.1-8b-instant",
        tokens_prompt=random.randint(200, 1500),
        tokens_completion=random.randint(50, 400),
        response=sim_answer,
    )

    # TURN_ERROR (10% probability to simulate occasional failures)
    if random.random() < 0.1:
        error_types = [
            "LLM_TIMEOUT",
            "LLM_RATE_LIMIT",
            "RETRIEVAL_ERROR",
            "LLM_HTTP_ERROR",
            "VALIDATION_FAILED",
        ]
        sim_error_type = random.choice(error_types)
        telemetry.log_turn_error(
            session_id,
            turn_number=turn_number,
            error_type=sim_error_type,
            exception_class="RuntimeError",
            exception_message=f"Simulated {sim_error_type}",
            stack_location="simulate_conversations.py:generate_synthetic_events",
            elapsed_ms=random.uniform(1000, 30000),
        )

    # Quality metrics (occasional ambiguous / clarification events)
    if is_ambiguous:
        telemetry.log_quality_metrics(
            session_id,
            turn_number=turn_number,
            is_ambiguous=True,
        )
    if random.random() < 0.15:
        telemetry.log_quality_metrics(
            session_id,
            turn_number=turn_number,
            is_clarification=True,
        )

    # TURN_VALIDATION
    telemetry.log_validation(
        session_id,
        turn_number=turn_number,
        confidence_score=sim_confidence,
        configured_threshold=0.45,
        low_confidence_triggered=sim_confidence < 0.45,
        validation_result="ok",
        hallucination_guard_result="passed",
    )

    # TURN_VOICE
    telemetry.log_voice_output(
        session_id,
        turn_number=turn_number,
        raw_text=sim_answer,
        cleaned_text=sim_answer.replace("₹", "rupees").replace("%", "percent"),
        tts_latency_ms=round(random.uniform(200, 1500), 1),
    )

    return sim_answer


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_logs(output_dir: Path) -> dict:
    event_counts = {}
    per_session_events = {}
    total_lines = 0
    missing_types = set(REQUIRED_EVENT_TYPES)

    for fpath in sorted(output_dir.glob("session_sim_*.jsonl")):
        session_key = fpath.stem
        evtypes = set()
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total_lines += 1
                try:
                    ev = json.loads(line)
                    typ = ev.get("type", "UNKNOWN")
                    evtypes.add(typ)
                    event_counts[typ] = event_counts.get(typ, 0) + 1
                except json.JSONDecodeError:
                    event_counts["PARSE_ERROR"] = event_counts.get("PARSE_ERROR", 0) + 1
        per_session_events[session_key] = sorted(evtypes)
        missing_types -= evtypes

    retrieval_latencies, llm_latencies, tts_latencies, confidences = [], [], [], []
    for fpath in sorted(output_dir.glob("session_sim_*.jsonl")):
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    typ = ev.get("type")
                    data = ev.get("data", {})
                    if typ == "TURN_RETRIEVAL":
                        lat = data.get("latency_ms")
                        conf = data.get("confidence_score")
                        if lat is not None:
                            retrieval_latencies.append(lat)
                        if conf is not None:
                            confidences.append(conf)
                    elif typ == "TURN_LLM_COMPLETE":
                        lat = data.get("total_latency_ms")
                        if lat is not None:
                            llm_latencies.append(lat)
                    elif typ == "TURN_VOICE":
                        lat = data.get("tts_latency_ms")
                        if lat is not None:
                            tts_latencies.append(lat)
                except json.JSONDecodeError:
                    pass

    def avg(vals):
        return round(sum(vals) / max(len(vals), 1), 1)

    return {
        "total_sessions": len(list(output_dir.glob("session_sim_*.jsonl"))),
        "total_events": total_lines,
        "event_type_counts": event_counts,
        "missing_types": sorted(missing_types),
        "per_session_event_types": per_session_events,
        "latency": {
            "retrieval_ms": {"avg": avg(retrieval_latencies), "count": len(retrieval_latencies)},
            "llm_ms": {"avg": avg(llm_latencies), "count": len(llm_latencies)},
            "tts_ms": {"avg": avg(tts_latencies), "count": len(tts_latencies)},
        },
        "retrieval_confidence_avg": avg(confidences),
    }


def print_report(stats: dict, turn_success: dict):
    sep = "=" * 72
    print(f"\n{sep}")
    print("  SIMULATION REPORT")
    print(sep)

    total_turns = 0
    ok_turns = 0
    fail_turns = 0
    for v in turn_success.values():
        total_turns += v.get("ok", 0) + v.get("fail", 0)
        ok_turns += v.get("ok", 0)
        fail_turns += v.get("fail", 0)

    print(f"\n  Total sessions generated:  {stats['total_sessions']}")
    print(f"  Total telemetry events:    {stats['total_events']}")
    if total_turns:
        print(
            f"  Turn success rate:          {ok_turns}/{total_turns} ({round(100 * ok_turns / total_turns, 1)}%)"
        )
    if fail_turns:
        print(f"  Turn failures:              {fail_turns}")

    print(f"\n{sep}")
    print("  EVENT COVERAGE MATRIX")
    print(sep)
    print(f"  {'Event Type':<25} {'Count':>8}")
    print("  " + "-" * 35)
    for evtype in REQUIRED_EVENT_TYPES + ["PARSE_ERROR"]:
        count = stats["event_type_counts"].get(evtype, 0)
        marker = " ✓" if count > 0 else " ✗"
        print(f"  {evtype:<25} {count:>8}{marker}")
    for evtype, count in sorted(stats["event_type_counts"].items()):
        if evtype not in REQUIRED_EVENT_TYPES and evtype != "PARSE_ERROR":
            print(f"  {evtype:<25} {count:>8}")

    if stats["missing_types"]:
        print(f"\n  MISSING event types: {', '.join(stats['missing_types'])}")
    else:
        print(f"\n  All required event types present.")

    print(f"\n{sep}")
    print("  AVERAGE LATENCY PER COMPONENT")
    print(sep)
    lat = stats["latency"]
    print(f"  {'Component':<25} {'Avg Latency':>15} {'Events':>10}")
    print("  " + "-" * 52)
    print(
        f"  {'Retrieval':<25} {lat['retrieval_ms']['avg']:>10.1f} ms  {lat['retrieval_ms']['count']:>10}"
    )
    print(
        f"  {'LLM Completion':<25} {lat['llm_ms']['avg']:>10.1f} ms  {lat['llm_ms']['count']:>10}"
    )
    print(
        f"  {'TTS/Voice Output':<25} {lat['tts_ms']['avg']:>10.1f} ms  {lat['tts_ms']['count']:>10}"
    )
    print(f"  {'Avg Retrieval Confidence':<25} {stats['retrieval_confidence_avg']:>10.3f}")

    print(f"\n{sep}")
    print("  PER-SESSION EVENT COVERAGE")
    print(sep)
    for sname, evtypes in sorted(stats["per_session_event_types"].items()):
        present = [t for t in REQUIRED_EVENT_TYPES if t in evtypes]
        missing = [t for t in REQUIRED_EVENT_TYPES if t not in evtypes]
        cov = f"{len(present)}/{len(REQUIRED_EVENT_TYPES)}"
        status = "✓" if not missing else f"✗ missing {missing}"
        t_ok = turn_success.get(sname, {}).get("ok", 0)
        t_fail = turn_success.get(sname, {}).get("fail", 0)
        print(f"  {sname:<45} events={cov} turns={t_ok + t_fail} ok={t_ok} fail={t_fail} {status}")

    print(f"\n{sep}")
    print("  DONE")
    print(sep)


# ---------------------------------------------------------------------------
# Session runners
# ---------------------------------------------------------------------------


async def run_real_api_session(
    lang: str,
    session_def: dict,
    idx: int,
    total: int,
    turn_success: dict,
    client: httpx.AsyncClient,
):
    """Run a session using real HTTP API calls — validates full pipeline integration."""
    session_id = f"sim_{session_def['name']}_{uuid.uuid4().hex[:6]}"
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    turn_key = f"session_{session_id}_{date_str}"
    result_data = {"ok": 0, "fail": 0, "turns": []}

    telemetry = get_telemetry()
    telemetry.start_session(session_id)
    await clear_session(client, session_id)

    for turn_i, message in enumerate(session_def["turns"], 1):
        label = f"[{idx + 1:02d}/{total}] API {session_def['name']:<22} Turn {turn_i}"
        print(f"  {label}: {message[:55]}", end="")
        try:
            result = await send_query(client, session_id, message)
            if "error" in result:
                print(f"  ERROR: {result.get('error', 'unknown')[:60]}")
                result_data["fail"] += 1
                result_data["turns"].append({"turn": turn_i, "message": message, "status": "error"})
            else:
                answer = result.get("answer", "")
                elapsed = result.get("_elapsed_ms", 0)
                preview = answer.replace("\n", " ")[:80]
                print(f"  {elapsed:>6.0f}ms  {preview}...")
                result_data["ok"] += 1
                result_data["turns"].append(
                    {"turn": turn_i, "message": message, "status": "ok", "latency_ms": elapsed}
                )
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            result_data["fail"] += 1
            result_data["turns"].append(
                {"turn": turn_i, "message": message, "status": "exception", "detail": str(e)}
            )
        await asyncio.sleep(random.uniform(0.1, 0.3))

    telemetry.end_session(session_id)
    turn_success[turn_key] = result_data
    print(
        f"  [{idx + 1:02d}/{total}] API {session_def['name']} -> {result_data['ok']} ok / {result_data['fail']} fail"
    )


async def run_synthetic_session(
    lang: str, session_def: dict, idx: int, total: int, turn_success: dict
):
    """Run a session using direct telemetry calls — validates event schema + counts."""
    session_id = f"sim_{session_def['name']}_{uuid.uuid4().hex[:6]}"
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    turn_key = f"session_{session_id}_{date_str}"
    result_data = {"ok": 0, "fail": 0, "turns": []}

    telemetry = get_telemetry()
    telemetry.start_session(session_id)

    for turn_i, message in enumerate(session_def["turns"], 1):
        label = f"[{idx + 1:02d}/{total}] SYN {session_def['name']:<22} Turn {turn_i}"
        sim_time = random.randint(30, 200)
        await asyncio.sleep(sim_time / 1000)
        try:
            generate_synthetic_events(session_id, turn_i, message, lang)
            result_data["ok"] += 1
            result_data["turns"].append({"turn": turn_i, "message": message, "status": "ok"})
            print(f"  {label}: {message[:55]}  {sim_time}ms")
        except Exception as e:
            print(f"  {label}: {message[:55]}  EXCEPTION: {e}")
            result_data["fail"] += 1
            result_data["turns"].append(
                {"turn": turn_i, "message": message, "status": "exception", "detail": str(e)}
            )

    telemetry.end_session(session_id)
    turn_success[turn_key] = result_data
    print(
        f"  [{idx + 1:02d}/{total}] SYN {session_def['name']} -> {result_data['ok']} ok / {result_data['fail']} fail"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    print("=" * 72)
    print("  BCREC Voice Agent — Simulated Conversation Harness")
    print("  Generating 30 conversations to exercise telemetry pipeline")
    print("=" * 72)

    turn_success: dict[str, Any] = {}

    # Run 3 real API sessions (1 per category) for end-to-end validation
    real_idxes = {0, 10, 20}
    all_tasks = []
    shared_client = httpx.AsyncClient(timeout=120)

    for orig_idx, (lang, sd) in enumerate(ALL_SESSIONS):
        if orig_idx in real_idxes:
            all_tasks.append(
                run_real_api_session(lang, sd, orig_idx + 1, 30, turn_success, shared_client)
            )
        else:
            all_tasks.append(run_synthetic_session(lang, sd, orig_idx + 1, 30, turn_success))

    await asyncio.gather(*all_tasks)
    await shared_client.aclose()

    # Validate
    stats = validate_logs(LOG_DIR)
    print_report(stats, turn_success)

    report_path = LOG_DIR / "simulation_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stats": stats,
                "turn_results": {k: v for k, v in turn_success.items()},
            },
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    print(f"\n  Full report saved to: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
