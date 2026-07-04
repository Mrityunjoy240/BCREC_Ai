"""
Text normalization pipeline for STT output normalization and TTS input preprocessing.

Usage:
    from backend.app.services.normalization import normalize_query, normalize_for_tts

    query = normalize_query("what is iml fee")  # → "what is aiml fee"
    tts_text = normalize_for_tts("CSE HOD is Dr. X")  # → "C S E Head of Department is Dr. X"
"""

from .normalizer import normalize_query, normalize_for_tts, NormalizationLog

__all__ = ["normalize_query", "normalize_for_tts", "NormalizationLog"]
