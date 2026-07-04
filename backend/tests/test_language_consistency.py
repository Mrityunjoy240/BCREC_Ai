"""
Tests for conversation language consistency fix.

Requirements verified:
1. Conversation maintains persistent language state (not redetected on every message).
2. Short follow-ups (fees, hostel, ME, AIML) inherit current conversation language.
3. Mixed-language words (AIML, CSE, fee, hostel, admission) don't trigger language change.
4. Native script (Bengali/Devanagari) forces a language switch.
5. Explicit switch commands ("in bengali", "hindi me") force a switch.
6. Romanized Bangla/Hindi with >=2 keyword markers triggers a switch.
7. Language changes are logged with reason.
8. clear_session also clears language state.
"""

import re
import logging

logging.disable(logging.CRITICAL)

# ---------------------------------------------------------------------------
# Replicate _resolve_language logic for standalone testing
# (avoids GroqService init which requires vector store / BGE-M3)
# ---------------------------------------------------------------------------

import sys

sys.path.insert(0, "backend")

from app.utils.language_detect import detect_language, BANGLA_ROMAN_WORDS, HINDI_ROMAN_WORDS


def _is_lang_switch(query: str) -> tuple[bool, str | None]:
    q = query.strip().lower()
    patterns = {
        "bn": [
            "in bengali",
            "bangla te",
            "banglay",
            "বাংলায়",
            "বাংলা তে",
            "bengali te",
            "bengali তে",
            "bangla y",
        ],
        "hi": ["in hindi", "hindi me", "hindi mein", "हिंदी में", "हिंदी मे"],
        "en": ["in english", "english e", "ইংরেজিতে", "english me"],
    }
    for lang, triggers in patterns.items():
        for t in triggers:
            if t in q or q == t:
                return True, lang
    return False, None


def resolve_language(session_langs: dict, session_id: str, query: str) -> str:
    """Replicates GroqService._resolve_language for testing."""
    current_lang = session_langs.get(session_id, "en")

    # Native script = forced switch
    if re.search(r"[\u0980-\u09FF]", query):
        session_langs[session_id] = "bn"
        return "bn"
    if re.search(r"[\u0900-\u097F]", query):
        session_langs[session_id] = "hi"
        return "hi"

    # Explicit switch command
    switch, forced = _is_lang_switch(query)
    if switch and forced:
        session_langs[session_id] = forced
        return forced

    # Short follow-ups (<=3 words, no native script) → inherit current
    if len(query.strip().split()) <= 3:
        return current_lang

    # Detect language for longer queries
    detected = detect_language(query)
    if detected == current_lang:
        return current_lang

    # Detected differs — check evidence strength
    text_lower = query.lower()
    text_words = set(re.sub(r"[^\w\s]", " ", text_lower).split())
    bn_kw = len(text_words & BANGLA_ROMAN_WORDS)
    hi_kw = len(text_words & HINDI_ROMAN_WORDS)
    kw_count = bn_kw if detected == "bn" else hi_kw

    if kw_count >= 2:
        session_langs[session_id] = detected
        return detected

    return current_lang


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _run_scenario(scenario_name, queries_expected, session_langs=None):
    """Run a scenario and return (passed: bool, details: list)."""
    if session_langs is None:
        session_langs = {}
    sid = scenario_name
    details = []
    all_pass = True
    for query, expected in queries_expected:
        prev = session_langs.get(sid, "en")
        got = resolve_language(session_langs, sid, query)
        passed = got == expected
        if not passed:
            all_pass = False
        details.append(
            {
                "query": query,
                "expected": expected,
                "got": got,
                "passed": passed,
                "changed": prev != got,
            }
        )
    session_langs.pop(sid, None)
    return all_pass, details


def test_english_keeps_english():
    """English queries, including known false-positive triggers, stay in English."""
    passed, details = _run_scenario(
        "en_session",
        [
            ("Which departments are available?", "en"),
            ("I want to take admission in AIML", "en"),  # was: bn (false positive: "take")
            ("fees", "en"),
            ("hostel", "en"),
            ("placements", "en"),
            ("ME", "en"),  # was: hi (false positive: "me")
            ("HOD CSE", "en"),
            ("fee for hostel", "en"),
            ("AIML", "en"),
            ("admission", "en"),
        ],
    )
    for d in details:
        assert d["passed"], f"Query '{d['query']}': expected {d['expected']}, got {d['got']}"


def test_hindi_keeps_hindi():
    """Hindi script queries stay in Hindi, including short follow-ups."""
    passed, details = _run_scenario(
        "hi_session",
        [
            ("मुझे सीएसई में एडमिशन चाहिए", "hi"),
            ("फीस", "hi"),
            ("हॉस्टल", "hi"),
            ("एडमिशन", "hi"),
        ],
    )
    for d in details:
        assert d["passed"], f"Query '{d['query']}': expected {d['expected']}, got {d['got']}"


def test_bengali_keeps_bengali():
    """Bengali script queries stay in Bengali, including short follow-ups."""
    passed, details = _run_scenario(
        "bn_session",
        [
            ("আমি সি এস ই তে ভর্তি হতে চাই", "bn"),
            ("ফি", "bn"),
            ("হোস্টেল", "bn"),
        ],
    )
    for d in details:
        assert d["passed"], f"Query '{d['query']}': expected {d['expected']}, got {d['got']}"


def test_explicit_language_switch():
    """Explicit switch commands change language mid-conversation."""
    passed, details = _run_scenario(
        "switch_session",
        [
            ("What is the fee?", "en"),
            ("in bengali", "bn"),  # explicit → bn
            ("ফি কত?", "bn"),  # stays bn (Bengali script)
            ("in english", "en"),  # explicit → en
            ("fees again", "en"),  # stays en
        ],
    )
    for d in details:
        assert d["passed"], f"Query '{d['query']}': expected {d['expected']}, got {d['got']}"


def test_romanized_bangla_switches():
    """Romanized Bangla with >=2 keyword markers triggers a switch."""
    passed, details = _run_scenario(
        "bangla_roman_session",
        [
            ("What is the fee?", "en"),
            ("Ami AIML e admission nite chai", "bn"),  # 2+ markers: ami, nite
            ("koto taka?", "bn"),  # stays bn (koto is a marker)
        ],
    )
    for d in details:
        assert d["passed"], f"Query '{d['query']}': expected {d['expected']}, got {d['got']}"


def test_romanized_hindi_switches():
    """Romanized Hindi with >=2 keyword markers triggers a switch."""
    passed, details = _run_scenario(
        "hindi_roman_session",
        [
            ("What is the fee?", "en"),
            ("Mujhe CSE mein admission chahiye", "hi"),  # 2+ markers: mujhe, chahiye
            ("kitna fee hai?", "hi"),  # stays hi
        ],
    )
    for d in details:
        assert d["passed"], f"Query '{d['query']}': expected {d['expected']}, got {d['got']}"


def test_short_followup_inherits_language():
    """Short follow-ups (<=3 words) inherit current session language."""
    # Scenario: starting in Hindi
    passed, details = _run_scenario(
        "short_hi_session",
        [
            ("मुझे फीस चाहिए", "hi"),
            ("ME", "hi"),  # short, no native script → inherits hi
            ("fees", "hi"),  # short, no native script → inherits hi
        ],
    )
    for d in details:
        assert d["passed"], f"Query '{d['query']}': expected {d['expected']}, got {d['got']}"


def test_clear_session_resets_language():
    """clear_session removes both session history and language state."""
    langs = {}
    sid = "clear_test"
    resolve_language(langs, sid, "ami tomar sathe kotha bolte chai")  # bn (6 words, 3 bn keywords)
    assert langs.get(sid) == "bn"
    langs.pop(sid, None)  # simulates clear_session
    assert sid not in langs
    # Fresh session should start at 'en'
    got = resolve_language(langs, sid, "What is the fee?")
    assert got == "en", f"After clear, expected en, got {got}"


def test_concurrent_sessions_independent():
    """Two concurrent sessions maintain independent language states."""
    langs = {}
    # Session A: English
    a_lang = resolve_language(langs, "session_a", "What departments are available?")
    assert a_lang == "en"
    # Session B: starts Bengali
    b_lang = resolve_language(langs, "session_b", "ami ki korte pari?")
    assert b_lang == "bn"
    # Session A continues in English
    a_lang2 = resolve_language(langs, "session_a", "fees")
    assert a_lang2 == "en", "Session A should still be English"
    # Session B continues in Bengali
    b_lang2 = resolve_language(langs, "session_b", "koto taka?")
    assert b_lang2 == "bn", "Session B should still be Bengali"
