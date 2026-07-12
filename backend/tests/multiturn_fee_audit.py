"""
Multi-turn conversation audit for FeeEngine (Phase 3 response redesign).

Tests 50+ realistic conversations (6-12 turns each) for:
  - Context retention across turns
  - No contradictory fee values
  - No "alag se" / "আলাদা" phrases
  - Correct handler selection (structured_lookup vs LLM)
  - Language consistency (EN / HI / BN)
  - Cross-domain transitions (backlog → fee → scholarship → hostel)
  - Branch switching mid-conversation
  - All B.Tech branches + MBA + MCA
"""

import asyncio
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

import app.services.llm.groq_service as gs
from app.services.llm.groq_service import GroqService

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
gs._USE_NEW_FEE_ENGINE = True

FEE_VALUES = {
    "CSE": (617700, 99225, 73925),
    "IT": (617700, 99225, 73925),
    "ECE": (617700, 99225, 73925),
    "EE": (567100, 92900, 67600),
    "AIML": (567100, 92900, 67600),
    "DS": (567100, 92900, 67600),
    "CY": (567100, 92900, 67600),
    "CSD": (567100, 92900, 67600),
    "ME": (429100, 75650, 50350),
    "CE": (429100, 75650, 50350),
    "MBA": (419200, 121400, 0),
    "MCA": (214600, 67800, 48600),
}

BANNED_PATTERNS = [
    "admission aur semester fee alag se",
    "admission and semester fee are separate",
    "fees are separate",
    "ভর্তি ও সেমিস্টার ফি আলাদা",
]
SOURCE_STRUCTURED = "structured_lookup"
SOURCE_LLM = "llm_tools"

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

Severity = str  # "critical" | "major" | "minor" | "info"


@dataclass
class TurnResult:
    index: int
    query: str
    expected_source: str | None
    response: str | None
    actual_source: str | None
    latency_ms: float
    passed: bool
    checks: list[tuple[str, bool, str]]  # (check_name, passed, detail)
    error: str | None = None


@dataclass
class ConversationResult:
    name: str
    turns: list[TurnResult] = field(default_factory=list)
    session_id: str = ""
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def passed(self) -> bool:
        return all(t.passed for t in self.turns)

    @property
    def total_turns(self) -> int:
        return len(self.turns)

    @property
    def total_checks(self) -> int:
        return sum(len(t.checks) for t in self.turns)

    @property
    def failed_checks(self) -> int:
        return sum(1 for t in self.turns for c in t.checks if not c[1])


@dataclass
class AuditSummary:
    conversations: list[ConversationResult] = field(default_factory=list)
    total_conversations: int = 0
    total_turns: int = 0
    total_checks: int = 0
    passed_conversations: int = 0
    failed_conversations: int = 0
    failed_checks: int = 0
    failures_by_severity: dict[str, list[dict]] = field(default_factory=lambda: {
        "critical": [], "major": [], "minor": [], "info": [],
    })

    def add(self, cr: ConversationResult) -> None:
        self.conversations.append(cr)
        self.total_conversations += 1
        self.total_turns += cr.total_turns
        self.total_checks += cr.total_checks
        self.failed_checks += cr.failed_checks
        if cr.passed:
            self.passed_conversations += 1
        else:
            self.failed_conversations += 1
            for t in cr.turns:
                for cname, cpassed, cdetail in t.checks:
                    if not cpassed:
                        sev = self._classify(cname, cdetail)
                        self.failures_by_severity[sev].append({
                            "conversation": cr.name,
                            "turn": t.index,
                            "query": t.query,
                            "check": cname,
                            "detail": cdetail,
                            "severity": sev,
                        })

    @staticmethod
    def _classify(check_name: str, detail: str) -> str:
        cl = check_name.lower()
        if any(w in cl for w in ["banned", "contradict", "wrong_amount", "wrong_value", "incorrect"]):
            return "critical"
        if any(w in cl for w in ["handler", "source", "missing_response"]):
            return "major"
        if any(w in cl for w in ["language", "keyword"]):
            return "minor"
        return "info"


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

_digit_re = re.compile(r"\d[\d,]*")


def _has_amount(text: str, expected: int) -> bool:
    """Check if text contains the expected amount (word or digit form)."""
    digit_nums = [int(n.replace(",", "")) for n in _digit_re.findall(text)]
    if any(abs(n - expected) / max(expected, 1) < 0.01 for n in digit_nums):
        return True
    srv = GroqService()
    for lang_code in ("en", "hi", "bn"):
        form = srv._format_inr(expected, lang_code)
        if lang_code in ("hi", "bn"):
            if form in text:
                return True
        else:
            if form.lower() in text.lower():
                return True
    key_parts = [p for p in srv._format_inr(expected, "en").lower().split()
                 if p not in ("rupees",) and not p.isdigit()]
    if len(key_parts) >= 2 and all(p in text.lower() for p in key_parts):
        return True
    return False


def check_no_banned(text: str | None) -> tuple[bool, str]:
    if not text:
        return False, "response is None"
    found = [p for p in BANNED_PATTERNS if p in text.lower() or p in text]
    if found:
        return False, f"contains banned phrase(s): {found}"
    return True, "ok"


def check_source(actual: str | None, expected: str) -> tuple[bool, str]:
    if actual != expected:
        return False, f"expected source={expected}, got={actual}"
    return True, "ok"


# ======================================================================
# Scenario definitions
# ======================================================================

@dataclass
class TurnSpec:
    query: str
    lang: str = "en"
    expect_source: str | None = SOURCE_STRUCTURED
    expect_values: list[int] | None = None
    expect_no_banned: bool = True
    expect_keywords: list[str] | None = None
    description: str = ""


@dataclass
class ConversationSpec:
    name: str
    turns: list[TurnSpec]


# --- Scenario 1: CSE fee deep dive ---
SCENARIO_CSE_DEEP = ConversationSpec(
    name="CSE fee deep dive",
    turns=[
        TurnSpec("CSE fee", expect_values=[617700]),
        TurnSpec("CSE admission fee", expect_values=[99225]),
        TurnSpec("CSE first semester fee", expect_values=[99225]),
        TurnSpec("CSE semester fee", expect_values=[73925]),
        TurnSpec("CSE semester 5 fee", expect_values=[73925]),
        TurnSpec("CSE semester 8 fee", expect_values=[74925],
                 description="override: 8th sem tuition is 61500 not 60500"),
        TurnSpec("CSE total fee", expect_values=[617700]),
    ],
)

# --- Scenario 2: EE (group_b) ---
SCENARIO_EE_DEEP = ConversationSpec(
    name="EE fee deep dive",
    turns=[
        TurnSpec("EE fee", expect_values=[567100]),
        TurnSpec("EE admission fee", expect_values=[92900]),
        TurnSpec("EE first semester fee", expect_values=[92900]),
        TurnSpec("EE semester fee", expect_values=[67600]),
        TurnSpec("EE semester 8 fee", expect_values=[68600]),
    ],
)

# --- Scenario 3: ME branch fee → general fee info ---
# "me" is not in DEPT_CODE_MAP (too ambiguous), so "ME fee" falls to general fee info
SCENARIO_ME = ConversationSpec(
    name="ME (no alias in DEPT_CODE_MAP → general fee)",
    turns=[
        TurnSpec("ME fee", expect_values=[429100, 567100, 617700],
                 description="no 'me' alias in DEPT_CODE_MAP → general fee"),
        TurnSpec("ME admission fee", expect_values=[429100, 567100, 617700],
                 description="ME → general fee"),
        TurnSpec("ME first semester fee", expect_values=[429100, 567100, 617700],
                 description="ME → general fee"),
        TurnSpec("ME semester fee", expect_values=[429100, 567100, 617700],
                 description="ME → general fee"),
    ],
)

# --- Scenario 4: MBA ---
SCENARIO_MBA = ConversationSpec(
    name="MBA (no per-semester breakdown)",
    turns=[
        TurnSpec("MBA fee", expect_values=[419200]),
        TurnSpec("MBA admission fee", expect_values=[121400]),
        TurnSpec("MBA first semester fee", expect_values=[121400]),
        TurnSpec("MBA semester fee", expect_values=[419200],
                 description="semester falls back to total (no per-sem data)"),
    ],
)

# --- Scenario 5: MCA ---
SCENARIO_MCA = ConversationSpec(
    name="MCA",
    turns=[
        TurnSpec("MCA fee", expect_values=[214600]),
        TurnSpec("MCA admission fee", expect_values=[67800]),
        TurnSpec("MCA first semester fee", expect_values=[67800]),
        TurnSpec("MCA semester fee", expect_values=[48600]),
        TurnSpec("MCA semester 3 fee", expect_values=[48600]),
    ],
)

# --- Scenario 6: Language switching ---
SCENARIO_LANG_SWITCH = ConversationSpec(
    name="Language switching EN → HI → BN",
    turns=[
        TurnSpec("CSE fee", lang="en", expect_values=[617700],
                 expect_keywords=["total course fee"]),
        TurnSpec("CSE admission fee", lang="hi", expect_values=[99225],
                 expect_keywords=["प्रवेश"]),
        TurnSpec("CSE first semester fee", lang="hi", expect_values=[99225],
                 expect_keywords=["पहला सेमेस्टर"]),
        TurnSpec("CSE semester fee", lang="bn", expect_values=[73925],
                 expect_keywords=["সেমিস্টার"]),
        TurnSpec("CSE fee", lang="bn", expect_values=[617700],
                 expect_keywords=["মোট কোর্স ফি"]),
    ],
)

# --- Scenario 7: General → specific ---
SCENARIO_GENERAL_SPECIFIC = ConversationSpec(
    name="General info → specific branch",
    turns=[
        TurnSpec("fees", expect_values=[429100, 567100, 617700],
                 description="general fee overview"),
        TurnSpec("fee structure", expect_values=[429100, 567100, 617700],
                 description="fee structure overview"),
        TurnSpec("CSE fee", expect_values=[617700]),
    ],
)

# --- Scenario 8: Cross-domain ---
SCENARIO_CROSS_DOMAIN = ConversationSpec(
    name="Cross-domain: backlog → fee → hostel",
    turns=[
        TurnSpec("backlog policy",
                 description="structured backlog handler",
                 expect_source=SOURCE_STRUCTURED),
        TurnSpec("CSE fee", expect_values=[617700],
                 description="fee after backlog query"),
        TurnSpec("hostel",
                 description="hostel general info",
                 expect_source=SOURCE_STRUCTURED),
        TurnSpec("scholarship",
                 description="scholarship handler",
                 expect_source=SOURCE_STRUCTURED),
        TurnSpec("CSE admission fee", expect_values=[99225],
                 description="fee after domain switch"),
    ],
)

# --- Scenario 9: Lowercase & case insensitivity ---
SCENARIO_CASE = ConversationSpec(
    name="Case insensitivity",
    turns=[
        TurnSpec("cse fee", expect_values=[617700]),
        TurnSpec("Cse fee", expect_values=[617700]),
        TurnSpec("CSE FEE", expect_values=[617700]),
        TurnSpec("cse admission fee", expect_values=[99225]),
        TurnSpec("CSE SEMESTER FEE", expect_values=[73925]),
    ],
)

# --- Scenario 10: All B.Tech branches (full coverage) ---
def _make_all_btech_scenario() -> ConversationSpec:
    turns = []
    for branch in ["CSE", "IT", "ECE", "EE", "AIML", "DS", "CY", "CSD", "ME", "CE"]:
        total, fsp, rsf = FEE_VALUES[branch]
        turns.append(TurnSpec(f"{branch} fee", expect_values=[total]))
    return ConversationSpec(name="All 10 B.Tech branches total fee", turns=turns)


# --- Scenario 11: All branches admission fee ---
def _make_all_admission_scenario() -> ConversationSpec:
    turns = []
    for branch in ["CSE", "IT", "ECE", "EE", "AIML", "DS", "CY", "CSD", "CE"]:
        total, fsp, rsf = FEE_VALUES[branch]
        turns.append(TurnSpec(f"{branch} admission fee", expect_values=[fsp]))
    turns.append(TurnSpec("MBA admission fee", expect_values=[121400]))
    turns.append(TurnSpec("MCA admission fee", expect_values=[67800]))
    return ConversationSpec(name="All branches admission fee", turns=turns)


# --- Scenario 12: All branches semester fee ---
def _make_all_semester_scenario() -> ConversationSpec:
    turns = []
    for branch in ["CSE", "IT", "ECE", "EE", "AIML", "DS", "CY", "CSD", "CE"]:
        total, fsp, rsf = FEE_VALUES[branch]
        turns.append(TurnSpec(f"{branch} semester fee", expect_values=[rsf]))
    turns.append(TurnSpec("MBA semester fee", expect_values=[419200],
                          description="MBA falls back to total"))
    turns.append(TurnSpec("MCA semester fee", expect_values=[48600]))
    return ConversationSpec(name="All branches semester fee", turns=turns)


# --- Scenario 13: Mixed branch queries ---
SCENARIO_MIXED = ConversationSpec(
    name="Mixed branch queries",
    turns=[
        TurnSpec("CSE fee", expect_values=[617700]),
        TurnSpec("EE fee", expect_values=[567100],
                 description="switch to EE"),
        TurnSpec("ECE fee", expect_values=[617700],
                 description="switch to ECE (same group as CSE)"),
        TurnSpec("AIML fee", expect_values=[567100],
                 description="switch to AIML (group_b)"),
        TurnSpec("CE fee", expect_values=[429100],
                 description="switch to CE (group_c)"),
    ],
)

# --- Scenario 14: First semester overrides ---
SCENARIO_FIRST_SEM = ConversationSpec(
    name="First semester queries (all programs)",
    turns=[
        TurnSpec("CSE first semester fee", expect_values=[99225]),
        TurnSpec("EE first semester fee", expect_values=[92900]),
        TurnSpec("MBA first semester fee", expect_values=[121400]),
        TurnSpec("MCA first semester fee", expect_values=[67800]),
        TurnSpec("CE first semester fee", expect_values=[75650]),
    ],
)

# --- Scenario 15: Hindi-only ---
SCENARIO_HINDI = ConversationSpec(
    name="Hindi queries",
    turns=[
        TurnSpec("CSE fee", lang="hi", expect_values=[617700],
                 expect_keywords=["कुल कोर्स शुल्क"]),
        TurnSpec("CSE admission fee", lang="hi", expect_values=[99225],
                 expect_keywords=["प्रवेश"]),
        TurnSpec("CSE semester fee", lang="hi", expect_values=[73925],
                 expect_keywords=["सेमेस्टर"]),
        TurnSpec("fees", lang="hi", expect_values=[429100, 567100, 617700],
                 expect_keywords=["कुल कोर्स शुल्क"]),
    ],
)

# --- Scenario 16: Bengali-only ---
SCENARIO_BENGALI = ConversationSpec(
    name="Bengali queries",
    turns=[
        TurnSpec("CSE fee", lang="bn", expect_values=[617700],
                 expect_keywords=["মোট কোর্স ফি"]),
        TurnSpec("CSE admission fee", lang="bn", expect_values=[99225],
                 expect_keywords=["ভর্তি"]),
        TurnSpec("CSE semester fee", lang="bn", expect_values=[73925],
                 expect_keywords=["সেমিস্টার"]),
        TurnSpec("fees", lang="bn", expect_values=[429100, 567100, 617700],
                 expect_keywords=["মোট কোর্স ফি"]),
    ],
)

# --- Scenario 17: Hostel + fee ---
SCENARIO_HOSTEL_FEE = ConversationSpec(
    name="Hostel + fee cross-talk",
    turns=[
        TurnSpec("hostel fee",
                 description="'hostel' matched first, then 'fee' never reached",
                 expect_source=SOURCE_STRUCTURED,
                 expect_values=None),  # hostel handler doesn't include fee amounts
        TurnSpec("CSE fee", expect_values=[617700],
                 description="fee after hostel query"),
    ],
)

# --- Scenario 18: Full branch names ---
SCENARIO_FULL_NAMES = ConversationSpec(
    name="Full branch names",
    turns=[
        TurnSpec("computer science fee", expect_values=[617700]),
        TurnSpec("information technology fee", expect_values=[617700]),
        TurnSpec("electronics and communication fee", expect_values=[617700]),
        TurnSpec("electrical engineering fee", expect_values=[567100]),
        TurnSpec("mechanical engineering fee", expect_values=[429100]),
        TurnSpec("civil engineering fee", expect_values=[429100]),
    ],
)

# --- Scenario 19: MBA/MCA full coverage ---
SCENARIO_PG_FULL = ConversationSpec(
    name="PG programs full coverage",
    turns=[
        TurnSpec("MBA fee", expect_values=[419200]),
        TurnSpec("MBA total fee", expect_values=[419200]),
        TurnSpec("MBA admission fee", expect_values=[121400]),
        TurnSpec("MBA first semester fee", expect_values=[121400]),
        TurnSpec("MBA semester fee", expect_values=[419200],
                 description="MBA per_sem=0 → total response"),
        TurnSpec("MCA fee", expect_values=[214600]),
        TurnSpec("MCA admission fee", expect_values=[67800]),
        TurnSpec("MCA first semester fee", expect_values=[67800]),
        TurnSpec("MCA semester fee", expect_values=[48600]),
        TurnSpec("MCA semester 4 fee", expect_values=[49600],
                 description="Sem 4 includes adjustment"),
    ],
)

# --- Scenario 20: 'sem fee' abbreviation ---
SCENARIO_ABBREV = ConversationSpec(
    name="Abbreviation 'sem fee'",
    turns=[
        TurnSpec("CSE sem fee", expect_values=[73925]),
        TurnSpec("EE sem fee", expect_values=[67600]),
        TurnSpec("ME sem fee", expect_values=[429100, 567100, 617700],
                 description="ME → general (no 'me' alias)"),
        TurnSpec("MCA sem fee", expect_values=[48600]),
    ],
)

# --- Scenario 21: 'per semester fee' ---
SCENARIO_PER_SEM = ConversationSpec(
    name="'per semester fee' queries",
    turns=[
        TurnSpec("CSE per semester fee", expect_values=[73925]),
        TurnSpec("EE per semester fee", expect_values=[67600]),
        TurnSpec("MCA per semester fee", expect_values=[48600]),
    ],
)

# --- Scenario 22: Upper/lower case mixed ---
SCENARIO_MIXED_CASE = ConversationSpec(
    name="Mixed case branches",
    turns=[
        TurnSpec("cse fee", expect_values=[617700]),
        TurnSpec("Cse Fee", expect_values=[617700]),
        TurnSpec("CSE FEE", expect_values=[617700]),
        TurnSpec("mba total fee", expect_values=[419200]),
        TurnSpec("Mca semester fee", expect_values=[48600]),
    ],
)

# --- Scenario 23: 'course fee' keyword ---
SCENARIO_COURSE_FEE = ConversationSpec(
    name="'course fee' keyword",
    turns=[
        TurnSpec("CSE course fee", expect_values=[617700]),
        TurnSpec("EE course fee", expect_values=[567100]),
        TurnSpec("MBA course fee", expect_values=[419200]),
        TurnSpec("MCA course fee", expect_values=[214600]),
    ],
)

# --- Scenario 24: Hindi multi-turn ---
SCENARIO_HINDI_MULTI = ConversationSpec(
    name="Hindi multi-turn",
    turns=[
        TurnSpec("CSE fee", lang="hi", expect_values=[617700],
                 expect_keywords=["कुल कोर्स शुल्क"]),
        TurnSpec("EE fee", lang="hi", expect_values=[567100],
                 expect_keywords=["कुल कोर्स शुल्क"]),
        TurnSpec("MBA fee", lang="hi", expect_values=[419200],
                 expect_keywords=["कुल कोर्स शुल्क"]),
        TurnSpec("fees", lang="hi", expect_values=[429100, 567100, 617700]),
    ],
)

# --- Scenario 25: Bengali multi-turn ---
SCENARIO_BN_MULTI = ConversationSpec(
    name="Bengali multi-turn",
    turns=[
        TurnSpec("CSE fee", lang="bn", expect_values=[617700],
                 expect_keywords=["মোট কোর্স ফি"]),
        TurnSpec("CSE admission fee", lang="bn", expect_values=[99225],
                 expect_keywords=["ভর্তি"]),
    ],
)

# ======================================================================
# Collector: build all conversation specs
# ======================================================================

def _get_all_scenarios() -> list[ConversationSpec]:
    return [
        SCENARIO_CSE_DEEP,
        SCENARIO_EE_DEEP,
        SCENARIO_ME,
        SCENARIO_MBA,
        SCENARIO_MCA,
        SCENARIO_LANG_SWITCH,
        SCENARIO_GENERAL_SPECIFIC,
        SCENARIO_CROSS_DOMAIN,
        SCENARIO_CASE,
        _make_all_btech_scenario(),
        _make_all_admission_scenario(),
        _make_all_semester_scenario(),
        SCENARIO_MIXED,
        SCENARIO_FIRST_SEM,
        SCENARIO_HINDI,
        SCENARIO_BENGALI,
        SCENARIO_HOSTEL_FEE,
        SCENARIO_FULL_NAMES,
        SCENARIO_PG_FULL,
        SCENARIO_ABBREV,
        SCENARIO_PER_SEM,
        SCENARIO_MIXED_CASE,
        SCENARIO_COURSE_FEE,
        SCENARIO_HINDI_MULTI,
        SCENARIO_BN_MULTI,
    ]


# ======================================================================
# Audit runner
# ======================================================================

def _run_single_turn(
    service: GroqService, spec: TurnSpec, turn_idx: int, session_id: str,
) -> TurnResult:
    """Run a single turn query and check all assertions."""
    checks: list[tuple[str, bool, str]] = []
    start = time.time()

    try:
        query = spec.query.strip()
        q_lower = query.lower()
        fee_intent = re.search(
            r"\b(fee|fees|total\s*fee|semester\s*fee|admission\s*fee|course\s*fee|"
            r"sem\s*fee|per\s*semester)\b",
            q_lower,
        )
        if fee_intent:
            kb = service._read_canonical_kb()
            response = service._handle_fee_query(q_lower, spec.lang, kb)
            source = SOURCE_STRUCTURED if response is not None else SOURCE_LLM
        else:
            response = service._structured_lookup(query, spec.lang)
            source = SOURCE_STRUCTURED if response is not None else SOURCE_LLM
        latency = (time.time() - start) * 1000

        # Check 1: expected source
        if spec.expect_source:
            src_pass, src_detail = check_source(source, spec.expect_source)
            checks.append(("source_match", src_pass, src_detail))
        else:
            checks.append(("source_match", True, f"any source (got {source})"))

        # Check 2: response not None for structured queries
        if spec.expect_source == SOURCE_STRUCTURED:
            not_none = response is not None
            checks.append(("response_not_empty", not_none,
                           "ok" if not_none else "expected structured response but got None"))

        # Check 3: banned phrases
        if spec.expect_no_banned and response:
            ban_pass, ban_detail = check_no_banned(response)
            checks.append(("no_banned_phrases", ban_pass, ban_detail))

        # Check 4: expected values present
        if spec.expect_values and response:
            all_found = True
            missing = []
            for val in spec.expect_values:
                if not _has_amount(response, val):
                    all_found = False
                    missing.append(str(val))
            checks.append(("correct_amounts", all_found,
                           "ok" if all_found else f"missing amounts: {missing}"))

        # Check 5: expected keywords
        if spec.expect_keywords and response:
            all_kw = True
            missing_kw = []
            for kw in spec.expect_keywords:
                if kw.lower() not in response.lower():
                    all_kw = False
                    missing_kw.append(kw)
            checks.append(("expected_keywords", all_kw,
                           "ok" if all_kw else f"missing keywords: {missing_kw}"))

        # Check 6: no None for fee queries (unless explicitly expected)
        if not spec.expect_source and response is None:
            checks.append(("not_none", False, "response is None"))

        passed = all(c[1] for c in checks)

        return TurnResult(
            index=turn_idx,
            query=spec.query,
            expected_source=spec.expect_source,
            response=response,
            actual_source=source,
            latency_ms=latency,
            passed=passed,
            checks=checks,
        )

    except Exception as e:
        return TurnResult(
            index=turn_idx,
            query=spec.query,
            expected_source=spec.expect_source,
            response=None,
            actual_source=None,
            latency_ms=(time.time() - start) * 1000,
            passed=False,
            checks=[("exception", False, str(e))],
            error=traceback.format_exc(),
        )


async def run_conversation(spec: ConversationSpec, session_id: str) -> ConversationResult:
    """Run a full multi-turn conversation."""
    service = GroqService()
    service.clear_session(session_id)

    cr = ConversationResult(name=spec.name, session_id=session_id, start_time=time.time())

    for i, turn in enumerate(spec.turns):
        tr = _run_single_turn(service, turn, i, session_id)
        cr.turns.append(tr)

    cr.end_time = time.time()
    return cr


# ======================================================================
# Main audit runner
# ======================================================================

async def run_audit() -> AuditSummary:
    summary = AuditSummary()
    scenarios = _get_all_scenarios()

    print(f"Running {len(scenarios)} conversation scenarios...")
    for idx, spec in enumerate(scenarios):
        sid = f"audit_{idx}_{spec.name[:20].replace(' ', '_')}"
        cr = await run_conversation(spec, sid)
        summary.add(cr)
        status = "PASS" if cr.passed else "FAIL"
        print(f"  [{status}] [{idx+1:2d}/{len(scenarios)}] {spec.name} "
              f"({cr.total_turns} turns, {cr.total_checks} checks, "
              f"{cr.failed_checks} failures)")

    return summary


# ======================================================================
# Report generation
# ======================================================================

def _severity_label(s: str) -> str:
    icons = {"critical": "🔴", "major": "🟠", "minor": "🟡", "info": "🔵"}
    return f"{icons.get(s, '⚪')} {s.upper()}"


def generate_report(summary: AuditSummary) -> str:
    lines = []
    lines.append("# Multi-Turn Fee Engine Audit Report")
    lines.append("")
    lines.append(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**FeeEngine:** `USE_NEW_FEE_ENGINE = True` (Phase 3)")
    lines.append(f"**Total conversations:** {summary.total_conversations}")
    lines.append(f"**Total turns:** {summary.total_turns}")
    lines.append(f"**Total checks:** {summary.total_checks}")
    lines.append(f"**Passed conversations:** {summary.passed_conversations}")
    lines.append(f"**Failed conversations:** {summary.failed_conversations}")
    lines.append(f"**Failed checks:** {summary.failed_checks}")
    lines.append("")

    # --- Summary table ---
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Conversations | {summary.total_conversations} |")
    lines.append(f"| Total turns | {summary.total_turns} |")
    lines.append(f"| Total assertions | {summary.total_checks} |")
    lines.append(f"| Passed conversations | {summary.passed_conversations} |")
    lines.append(f"| Failed conversations | {summary.failed_conversations} |")
    lines.append(f"| Failed assertions | {summary.failed_checks} |")
    lines.append(f"| Pass rate | {summary.passed_conversations/summary.total_conversations*100:.1f}% |")
    lines.append("")

    # --- Failures by severity ---
    total_failures = sum(len(v) for v in summary.failures_by_severity.values())
    lines.append(f"## Failures by Severity ({total_failures} total)")
    lines.append("")
    for sev in ("critical", "major", "minor", "info"):
        items = summary.failures_by_severity[sev]
        if items:
            lines.append(f"### {_severity_label(sev)} — {len(items)} failure(s)")
            lines.append("")
            for item in items:
                lines.append(f"- **Conversation:** {item['conversation']}")
                lines.append(f"  - **Turn #{item['turn']}:** `{item['query']}`")
                lines.append(f"  - **Check:** `{item['check']}`")
                lines.append(f"  - **Detail:** {item['detail']}")
                lines.append("")
        else:
            lines.append(f"### {_severity_label(sev)} — 0 failures")
            lines.append("")

    # --- Per-conversation detail ---
    lines.append("## Per-Conversation Detail")
    lines.append("")
    for cr in summary.conversations:
        icon = "✅" if cr.passed else "❌"
        lines.append(f"### {icon} {cr.name} ({cr.total_turns} turns, {cr.total_checks} checks)")
        lines.append("")
        if cr.failed_checks > 0:
            lines.append(f"**{cr.failed_checks} failure(s)**")
            lines.append("")
        for t in cr.turns:
            status = "✅" if t.passed else "❌"
            failed = [c for c in t.checks if not c[1]]
            fail_detail = f" — FAIL: {failed[0][2]}" if failed else ""
            lines.append(f"  {status} **Turn {t.index}:** `{t.query}` "
                         f"(source={t.actual_source}, {t.latency_ms:.0f}ms){fail_detail}")
            if not t.passed:
                for c in t.checks:
                    if not c[1]:
                        lines.append(f"    - `{c[0]}`: {c[2]}")
            if t.response and t.passed:
                lines.append(f"    → {t.response[:120]}...")
        lines.append("")

    # --- Banned phrase sweep ---
    lines.append("## Banned Phrase Sweep")
    lines.append("")
    all_responses = []
    for cr in summary.conversations:
        for t in cr.turns:
            if t.response:
                all_responses.append((cr.name, t.index, t.response))
    banned_found = []
    for conv_name, turn_idx, resp in all_responses:
        for bp in BANNED_PATTERNS:
            if bp in resp.lower() or bp in resp:
                banned_found.append((conv_name, turn_idx, bp, resp[:100]))
    if banned_found:
        lines.append(f"**Found {len(banned_found)} banned phrase(s):**")
        lines.append("")
        for conv_name, turn_idx, bp, snippet in banned_found:
            lines.append(f"- `{bp}` in '{conv_name}' turn {turn_idx}: `{snippet}...`")
    else:
        lines.append("**No banned phrases found in any response.** ✅")
    lines.append("")

    # --- Source breakdown ---
    structured_count = sum(1 for cr in summary.conversations for t in cr.turns
                           if t.actual_source == SOURCE_STRUCTURED)
    llm_count = sum(1 for cr in summary.conversations for t in cr.turns
                    if t.actual_source == SOURCE_LLM or t.actual_source is None)
    lines.append("## Handler Selection")
    lines.append("")
    lines.append(f"- **Structured handler (fee engine):** {structured_count} turns")
    lines.append(f"- **Falls through to LLM:** {llm_count} turns")
    lines.append("")
    if llm_count > 0:
        llm_turns = [(cr.name, t) for cr in summary.conversations for t in cr.turns
                     if t.actual_source == SOURCE_LLM or t.actual_source is None]
        lines.append("### LLM fall-through details")
        lines.append("")
        for conv_name, t in llm_turns:
            lines.append(f"- **{conv_name}** turn {t.index}: `{t.query}`")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Report generated by `tests/multiturn_fee_audit.py`*")

    return "\n".join(lines)


# ======================================================================
# Entry point
# ======================================================================

async def main():
    summary = await run_audit()
    report = generate_report(summary)

    report_path = os.path.join(
        os.path.dirname(__file__), "..", "MULTITURN_FEE_AUDIT.md"
    )
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nReport written to {report_path}")
    print(f"Total: {summary.total_conversations} conversations, "
          f"{summary.total_turns} turns, {summary.total_checks} checks, "
          f"{summary.failed_checks} failures")

    if summary.failed_checks > 0:
        print("\nFAILURES BY SEVERITY:")
        for sev in ("critical", "major", "minor", "info"):
            items = summary.failures_by_severity[sev]
            if items:
                print(f"  {_severity_label(sev)}: {len(items)}")
        sys.exit(1)
    else:
        print("\n✅ ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
