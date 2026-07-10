"""Red-team test framework for automated pipeline capture and evaluation."""

from .pipeline_hooks import PipelineCapture, StageCapture, stage_capture_context
from .cases import P0_CASES, P1_CASES, ALL_CASES, SUMMARY, TestCase, Turn
from .runner import RedTeamRunner, TestResult
from .report import RedTeamReport

__all__ = [
    "PipelineCapture",
    "StageCapture",
    "stage_capture_context",
    "P0_CASES",
    "P1_CASES",
    "ALL_CASES",
    "TestCase",
    "Turn",
    "SUMMARY",
    "RedTeamRunner",
    "TestResult",
    "RedTeamReport",
]
