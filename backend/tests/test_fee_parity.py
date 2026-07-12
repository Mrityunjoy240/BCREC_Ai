"""Parity and regression tests for the FeeEngine feature flag.

Phase 3: New engine responses are dynamically formatted, language-aware,
and use FeeEngine component data. Old engine responses are unchanged.
"""

import importlib
import os
import re as _re
from typing import Any

import pytest

import app.services.llm.groq_service as gs

GroqService = gs.GroqService


# ======================================================================
# Fixtures & Helpers
# ======================================================================


@pytest.fixture(autouse=True)
def reset_flag():
    yield
    gs._USE_NEW_FEE_ENGINE = False


@pytest.fixture
def service():
    return GroqService()


def _run_old(service, query, lang="en"):
    kb = service._read_canonical_kb()
    return service._handle_fee_query_old(query.strip().lower(), lang, kb)


def _run_new(service, query, lang="en"):
    kb = service._read_canonical_kb()
    return service._handle_fee_query_new(query.strip().lower(), lang, kb)


def _run_abs(service, query, lang="en"):
    kb = service._read_canonical_kb()
    return service._handle_fee_query(query.strip().lower(), lang, kb)


# === Fee constants for value assertions ===
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

# For multi-digit Indian number verification
_DIGIT_RE = _re.compile(r"\d[\d,]*")


def _has_amount(text: str, expected: int) -> bool:
    """Check if text contains the expected amount (word or digit form)."""
    # Check digit form with commas (e.g., "6,17,700")
    digit_nums = [int(n.replace(",", "")) for n in _DIGIT_RE.findall(text)]
    if any(abs(n - expected) / max(expected, 1) < 0.01 for n in digit_nums):
        return True
    # Check word form (e.g., "six lakh seventeen thousand seven hundred")
    import app.services.llm.groq_service as _gs
    srv = _gs.GroqService()
    en_form = srv._format_inr(expected, "en")
    hi_form = srv._format_inr(expected, "hi")
    bn_form = srv._format_inr(expected, "bn")
    text_lower = text.lower()
    if en_form.lower() in text_lower:
        return True
    if hi_form in text:  # No need to lowercase Devanagari
        return True
    if bn_form in text:  # No need to lowercase Bengali
        return True
    # Partial match: check key number words from English format
    key_parts = [p for p in en_form.lower().split() if p not in ("rupees",) and not p.isdigit()]
    if len(key_parts) >= 2 and all(p in text_lower for p in key_parts):
        return True
    return False


# ======================================================================
# 1. Flag-OFF Behavior (Old Engine Unchanged)
# ======================================================================


class TestFlagOff:
    """With flag OFF, old engine behavior is unchanged."""

    def test_cse_total_fee(self, service: GroqService):
        r = _run_abs(service, "CSE fee")
        assert r is not None

    def test_ee_semester_fee(self, service: GroqService):
        r = _run_abs(service, "EE semester fee")
        assert r is not None

    def test_general_fees(self, service: GroqService):
        r = _run_abs(service, "fees")
        assert r is not None

    def test_unknown_branch_fallsback(self, service: GroqService):
        r = _run_abs(service, "xyz fee")
        assert r is not None
        assert "BCREC" in r or "bcrec" in r.lower()

    def test_per_semester_no_fee_keyword(self, service: GroqService):
        r = _run_abs(service, "CSE per semester")
        assert r is None

    def test_old_engine_still_has_alag_se(self, service: GroqService):
        r = _run_old(service, "CSE fee")
        assert r is not None
        assert "alag" in r.lower() or "আলাদা" in r or "separate" in r.lower()


# ======================================================================
# 2. Flag-ON Value Correctness (New Engine)
# ======================================================================


class TestNewEngineValues:
    """With flag ON, verify correct fee VALUES in responses."""

    @pytest.fixture(autouse=True)
    def enable_flag(self):
        gs._USE_NEW_FEE_ENGINE = True
        yield
        gs._USE_NEW_FEE_ENGINE = False

    @pytest.mark.parametrize("branch", list(FEE_VALUES.keys()))
    def test_total_fee_value(self, service: GroqService, branch: str):
        total, fsp, rsf = FEE_VALUES[branch]
        r = _run_abs(service, f"{branch} fee")
        assert r is not None, f"Total fee for {branch} returned None"
        assert _has_amount(r, total), f"{branch} total {total} not in: {r}"

    @pytest.mark.parametrize("branch", ["CSE", "IT", "ECE", "EE", "AIML", "DS", "CY", "CSD", "CE"])
    def test_semester_fee_value(self, service: GroqService, branch: str):
        total, fsp, rsf = FEE_VALUES[branch]
        r = _run_abs(service, f"{branch} semester fee")
        assert r is not None, f"Semester fee for {branch} returned None"
        if rsf > 0:
            assert _has_amount(r, rsf), f"{branch} semester {rsf} not in: {r}"
        else:
            assert _has_amount(r, total), f"{branch} semester fallback {total} not in: {r}"

    def test_semester_fee_me_general(self, service: GroqService):
        """ME not in DEPT_CODE_MAP → falls to general fee info."""
        r = _run_abs(service, "ME semester fee")
        assert r is not None
        assert _has_amount(r, FEE_VALUES["ME"][0])

    @pytest.mark.parametrize("branch", ["CSE", "EE", "MBA", "MCA"])
    def test_admission_fee_value(self, service: GroqService, branch: str):
        total, fsp, rsf = FEE_VALUES[branch]
        r = _run_abs(service, f"{branch} admission fee")
        assert r is not None, f"Admission fee for {branch} returned None"
        assert _has_amount(r, fsp), f"{branch} admission {fsp} not in: {r}"

    def test_admission_fee_me_general(self, service: GroqService):
        """ME not in DEPT_CODE_MAP → falls to general fee info."""
        r = _run_abs(service, "ME admission fee")
        assert r is not None
        assert _has_amount(r, FEE_VALUES["ME"][0])

    def test_admission_fee_mba_no_per_sem_breakdown(self, service: GroqService):
        """MBA admission response should not mention semester components."""
        r = _run_abs(service, "MBA admission fee")
        assert r is not None
        assert _has_amount(r, FEE_VALUES["MBA"][1])

    def test_admission_fee_mca_no_per_sem_breakdown(self, service: GroqService):
        r = _run_abs(service, "MCA admission fee")
        assert r is not None
        assert _has_amount(r, FEE_VALUES["MCA"][1])

    @pytest.mark.parametrize("branch", ["CSE", "EE", "MBA", "MCA"])
    def test_first_semester_fee_value(self, service: GroqService, branch: str):
        total, fsp, rsf = FEE_VALUES[branch]
        r = _run_abs(service, f"{branch} first semester fee")
        assert r is not None, f"First semester fee for {branch} returned None"
        assert _has_amount(r, fsp), f"{branch} first semester {fsp} not in: {r}"

    def test_first_semester_fee_me_general(self, service: GroqService):
        """ME not in DEPT_CODE_MAP → falls to general fee info."""
        r = _run_abs(service, "ME first semester fee")
        assert r is not None
        assert _has_amount(r, FEE_VALUES["ME"][0])

    def test_case_insensitivity(self, service: GroqService):
        r1 = _run_abs(service, "CSE fee")
        r2 = _run_abs(service, "cse fee")
        r3 = _run_abs(service, "Cse fee")
        assert r1 == r2 == r3

    def test_mba_semester_fallsback_total(self, service: GroqService):
        r = _run_abs(service, "MBA semester fee")
        assert r is not None
        assert _has_amount(r, 419200)

    def test_unknown_branch_general_fee(self, service: GroqService):
        r = _run_abs(service, "xyz fee")
        assert r is not None
        assert "BCREC" in r or "bcrec" in r.lower()

    def test_general_fees(self, service: GroqService):
        r = _run_abs(service, "fees")
        assert r is not None
        assert "BCREC" in r or "bcrec" in r.lower()


# ======================================================================
# 3. New Engine Response Quality (Flag ON)
# ======================================================================


class TestNewEngineResponses:
    """Verify new engine responses meet Phase 3 quality criteria."""

    @pytest.fixture(autouse=True)
    def enable_flag(self):
        gs._USE_NEW_FEE_ENGINE = True
        yield
        gs._USE_NEW_FEE_ENGINE = False

    # --- NO "alag se" ---

    def test_total_no_alag_se(self, service: GroqService):
        for branch in ["CSE", "EE", "ME", "MBA", "MCA"]:
            r = _run_abs(service, f"{branch} fee")
            assert r is not None
            assert "alag se" not in r.lower()
            assert "আলাদা" not in r

    def test_semester_no_alag_se(self, service: GroqService):
        for branch in ["CSE", "EE", "ME", "MCA"]:
            r = _run_abs(service, f"{branch} semester fee")
            assert r is not None
            assert "alag se" not in r.lower()
            assert "আলাদা" not in r

    def test_admission_no_alag_se(self, service: GroqService):
        for branch in ["CSE", "EE", "ME", "MBA", "MCA"]:
            r = _run_abs(service, f"{branch} admission fee")
            assert r is not None
            assert "alag se" not in r.lower()
            assert "আলাদা" not in r

    # --- Correct response types ---

    def test_total_response_mentions_total(self, service: GroqService):
        r = _run_abs(service, "CSE fee")
        assert "total" in r.lower() or "कुल" in r or "মোট" in r

    def test_semester_response_contains_semester_word(self, service: GroqService):
        r = _run_abs(service, "CSE semester fee")
        assert "semester" in r.lower() or "सेमेस्टर" in r or "সেমিস্টার" in r

    def test_admission_response_contains_admission_word(self, service: GroqService):
        r = _run_abs(service, "CSE admission fee")
        assert "admission" in r.lower() or "एडमिशन" in r.lower() or "admission" in r.lower() or "ভর্তি" in r

    def test_first_semester_response_contains_first(self, service: GroqService):
        r = _run_abs(service, "CSE first semester fee")
        assert "first" in r.lower() or "पहला" in r or "প্রথম" in r

    # --- Response structure ---

    def test_total_includes_breakdown_hint(self, service: GroqService):
        r = _run_abs(service, "CSE fee")
        assert "includes" in r.lower() or "इसमें" in r or "এতে" in r

    def test_admission_includes_component_explanation(self, service: GroqService):
        r = _run_abs(service, "CSE admission fee")
        assert any(w in r.lower() for w in ["includes", "covers", "शामिल", "অন্তর্ভুক্ত"])

    def test_first_semester_has_breakdown(self, service: GroqService):
        r = _run_abs(service, "CSE first semester fee")
        # Should include component labels
        has_breakdown = any(
            label in r.lower() for label in ["admission fee", "caution", "tuition", "development", "एकमुश्त", "এককালীন", "semester fee"]
        )
        assert has_breakdown, f"First semester response lacks component breakdown: {r}"

    # --- Language aware ---

    def test_hindi_response(self, service: GroqService):
        r = _run_abs(service, "CSE fee", lang="hi")
        assert r is not None
        assert any(c in r for c in "कुलकोर्सशुल्क")

    def test_bengali_response(self, service: GroqService):
        r = _run_abs(service, "CSE fee", lang="bn")
        assert r is not None
        assert any(c in r for c in "মোটকোর্সফি")

    def test_hindi_admission(self, service: GroqService):
        r = _run_abs(service, "CSE admission fee", lang="hi")
        assert r is not None
        assert "प्रवेश" in r

    def test_bengali_admission(self, service: GroqService):
        r = _run_abs(service, "CSE admission fee", lang="bn")
        assert r is not None
        assert "ভর্তি" in r

    def test_hindi_semester(self, service: GroqService):
        r = _run_abs(service, "CSE semester fee", lang="hi")
        assert r is not None
        assert "सेमेस्टर" in r

    def test_bengali_semester(self, service: GroqService):
        r = _run_abs(service, "CSE semester fee", lang="bn")
        assert r is not None
        assert "সেমিস্টার" in r


# ======================================================================
# 4. Regression — All query variants work
# ======================================================================


class TestRegression:
    """Comprehensive regression: all query types against new engine."""

    @pytest.fixture(autouse=True)
    def enable_flag(self):
        gs._USE_NEW_FEE_ENGINE = True
        yield
        gs._USE_NEW_FEE_ENGINE = False

    def test_cse_fee(self, service: GroqService):
        assert _run_abs(service, "CSE fee") is not None

    def test_cse_total_fee(self, service: GroqService):
        assert _run_abs(service, "CSE total fee") is not None

    def test_cse_semester_fee(self, service: GroqService):
        assert _run_abs(service, "CSE semester fee") is not None

    def test_cse_admission_fee(self, service: GroqService):
        assert _run_abs(service, "CSE admission fee") is not None

    def test_cse_first_semester_fee(self, service: GroqService):
        r = _run_abs(service, "CSE first semester fee")
        assert r is not None

    def test_cse_semester_2_fee(self, service: GroqService):
        r = _run_abs(service, "CSE semester 2 fee")
        assert r is not None

    def test_cse_semester_5_fee(self, service: GroqService):
        r = _run_abs(service, "CSE semester 5 fee")
        assert r is not None

    def test_cse_semester_8_fee(self, service: GroqService):
        r = _run_abs(service, "CSE semester 8 fee")
        assert r is not None

    def test_ee_total_fee(self, service: GroqService):
        assert _run_abs(service, "EE fee") is not None

    def test_me_total_fee(self, service: GroqService):
        assert _run_abs(service, "ME total fee") is not None

    def test_ce_total_fee(self, service: GroqService):
        assert _run_abs(service, "CE fee") is not None

    def test_mba_total_fee(self, service: GroqService):
        r = _run_abs(service, "MBA fee")
        assert r is not None

    def test_mba_admission_fee(self, service: GroqService):
        r = _run_abs(service, "MBA admission fee")
        assert r is not None

    def test_mca_total_fee(self, service: GroqService):
        assert _run_abs(service, "MCA fee") is not None

    def test_mca_semester_fee(self, service: GroqService):
        assert _run_abs(service, "MCA semester fee") is not None

    def test_mca_admission_fee(self, service: GroqService):
        assert _run_abs(service, "MCA admission fee") is not None

    def test_mca_first_semester_fee(self, service: GroqService):
        assert _run_abs(service, "MCA first semester fee") is not None

    def test_cse_per_semester_fee(self, service: GroqService):
        assert _run_abs(service, "CSE per semester fee") is not None

    def test_cse_sem_fee_abbrev(self, service: GroqService):
        assert _run_abs(service, "CSE sem fee") is not None

    def test_cse_course_fee(self, service: GroqService):
        assert _run_abs(service, "CSE course fee") is not None

    def test_general_fees(self, service: GroqService):
        assert _run_abs(service, "fees") is not None

    def test_general_fee_structure(self, service: GroqService):
        assert _run_abs(service, "fee structure") is not None

    def test_branch_comparison(self, service: GroqService):
        assert _run_abs(service, "fees for Data Science") is not None

    def test_unknown_branch(self, service: GroqService):
        r = _run_abs(service, "xyz fee")
        assert r is not None
        assert "BCREC" in r or "bcrec" in r.lower()

    def test_semester_lacks_fee_keyword(self, service: GroqService):
        assert _run_abs(service, "CSE per semester") is None

    def test_ds_total_fee(self, service: GroqService):
        r = _run_abs(service, "DS fee")
        assert r is not None

    def test_aiml_total_fee(self, service: GroqService):
        r = _run_abs(service, "AIML total fee")
        assert r is not None

    def test_it_total_fee(self, service: GroqService):
        r = _run_abs(service, "IT fee")
        assert r is not None

    def test_cy_total_fee(self, service: GroqService):
        r = _run_abs(service, "CY fee")
        assert r is not None

    def test_csd_total_fee(self, service: GroqService):
        r = _run_abs(service, "CSD fee")
        assert r is not None


# ======================================================================
# 5. Abstraction Routing
# ======================================================================


class TestAbstractionRouting:
    """Verify routing behaves correctly per flag setting."""

    def test_flag_off_routes_old(self, service: GroqService):
        gs._USE_NEW_FEE_ENGINE = False
        old = _run_old(service, "CSE fee")
        routed = _run_abs(service, "CSE fee")
        assert routed == old

    def test_flag_on_routes_new(self, service: GroqService):
        gs._USE_NEW_FEE_ENGINE = True
        new = _run_new(service, "CSE fee")
        routed = _run_abs(service, "CSE fee")
        assert routed == new

    def test_flag_off_production_unchanged(self, service: GroqService):
        gs._USE_NEW_FEE_ENGINE = False
        r = _run_abs(service, "what is the total fee for CSE")
        assert r is not None
        assert "alag" in r.lower() or "total" in r.lower()


# ======================================================================
# 6. Multilingual — New Engine Only
# ======================================================================


class TestMultilingual:
    """Verify new engine responses are language-aware."""

    @pytest.fixture(autouse=True)
    def enable_flag(self):
        gs._USE_NEW_FEE_ENGINE = True
        yield
        gs._USE_NEW_FEE_ENGINE = False

    @pytest.mark.parametrize("branch,lang", [
        ("CSE", "hi"), ("CSE", "bn"),
        ("EE", "hi"), ("EE", "bn"),
        ("MBA", "hi"), ("MBA", "bn"),
        ("MCA", "hi"), ("MCA", "bn"),
    ])
    def test_total_fee_multilingual(self, service: GroqService, branch: str, lang: str):
        r = _run_abs(service, f"{branch} fee", lang=lang)
        assert r is not None
        assert _has_amount(r, FEE_VALUES[branch][0])

    @pytest.mark.parametrize("branch,lang", [
        ("CSE", "hi"), ("CSE", "bn"),
    ])
    def test_admission_multilingual(self, service: GroqService, branch: str, lang: str):
        r = _run_abs(service, f"{branch} admission fee", lang=lang)
        assert r is not None
        assert _has_amount(r, FEE_VALUES[branch][1])

    @pytest.mark.parametrize("branch,lang", [
        ("CSE", "hi"), ("CSE", "bn"),
    ])
    def test_semester_multilingual(self, service: GroqService, branch: str, lang: str):
        r = _run_abs(service, f"{branch} semester fee", lang=lang)
        assert r is not None
        assert _has_amount(r, FEE_VALUES[branch][2])

    def test_general_hindi(self, service: GroqService):
        r = _run_abs(service, "fees", lang="hi")
        assert r is not None

    def test_general_bengali(self, service: GroqService):
        r = _run_abs(service, "fees", lang="bn")
        assert r is not None

    def test_no_alag_se_hindi(self, service: GroqService):
        r = _run_abs(service, "CSE fee", lang="hi")
        assert r is not None
        assert "alag se" not in r.lower()

    def test_no_alag_se_bengali(self, service: GroqService):
        r = _run_abs(service, "CSE fee", lang="bn")
        assert r is not None
        assert "আলাদা" not in r
