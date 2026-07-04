"""
Event Loader
============
Loads telemetry events from JSONL files, indexes by session and type.
"""

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Any, Optional


def load_events(input_dir: str, session_filter: Optional[str] = None) -> List[Dict]:
    """Load all events from JSONL files in input_dir.

    Args:
        input_dir: Path to directory containing session_*.jsonl files
        session_filter: Optional session_id prefix to filter (e.g. "sim_" or "live_")

    Returns:
        List of parsed event dicts, each with an added "_source_file" key.
    """
    events = []
    path = Path(input_dir)
    if not path.exists():
        return events

    for fp in sorted(path.glob("session_*.jsonl")):
        if session_filter and session_filter not in fp.stem:
            continue
        with open(fp, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    ev["_source_file"] = fp.name
                    events.append(ev)
                except json.JSONDecodeError:
                    events.append(
                        {
                            "type": "PARSE_ERROR",
                            "_source_file": fp.name,
                            "_raw": line[:200],
                        }
                    )
    return events


def index_by_session(events: List[Dict]) -> Dict[str, List[Dict]]:
    """Group events by session_id."""
    sessions = defaultdict(list)
    for ev in events:
        sid = ev.get("session_id", "unknown")
        sessions[sid].append(ev)
    return dict(sessions)


def index_by_type(events: List[Dict]) -> Dict[str, List[Dict]]:
    """Group events by event type."""
    by_type = defaultdict(list)
    for ev in events:
        by_type[ev.get("type", "UNKNOWN")].append(ev)
    return dict(by_type)


def get_session_file(session_id: str, log_dir: str) -> Optional[Path]:
    """Find the JSONL file for a given session_id."""
    path = Path(log_dir)
    for fp in path.glob(f"*{session_id}*.jsonl"):
        return fp
    return None


def percentile(sorted_vals, p):
    """Compute the p-th percentile (0-100) from a sorted list."""
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p / 100.0
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_vals) else f
    return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])


def safe_avg(vals):
    """Compute average, returning 0 for empty list."""
    return sum(vals) / max(len(vals), 1)


def safe_median(sorted_vals):
    """Compute median from a sorted list."""
    if not sorted_vals:
        return 0.0
    return percentile(sorted_vals, 50)


def safe_stdev(vals):
    """Compute population standard deviation."""
    if len(vals) < 2:
        return 0.0
    avg = sum(vals) / len(vals)
    return (sum((x - avg) ** 2 for x in vals) / len(vals)) ** 0.5


def detect_outliers(vals, n_sigma=2):
    """Return indices of values more than n_sigma std devs from mean."""
    if len(vals) < 2:
        return []
    avg = sum(vals) / len(vals)
    sigma = safe_stdev(vals)
    if sigma == 0:
        return []
    return [i for i, v in enumerate(vals) if abs(v - avg) > n_sigma * sigma]


_DEFAULT_INPUT = Path(__file__).resolve().parent.parent.parent / "data" / "logs" / "conversations"
_DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent.parent / "data" / "logs" / "reports"
