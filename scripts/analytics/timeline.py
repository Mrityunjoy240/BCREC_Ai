"""
Task 7: Session Timeline Generator
===================================
Generates an interactive HTML timeline for a given session,
showing every event with color-coded status.
"""

import json
from datetime import datetime, timezone


def generate_timeline_html(session_id: str, events: list, output_path: str):
    """Generate an interactive HTML timeline for a single session."""
    events.sort(key=lambda e: e.get("timestamp_unix", 0))

    turns = {}
    for ev in events:
        tn = ev.get("turn_number", 0)
        if tn not in turns:
            turns[tn] = []
        turns[tn].append(ev)

    cards_html = ""
    turn_keys = sorted(turns.keys())

    for tn in turn_keys:
        evts = turns[tn]
        items_html = ""
        for ev in evts:
            etype = ev.get("type", "?")
            ts = ev.get("timestamp", "")
            data = ev.get("data", {}) or {}

            color = "#e8f5e9"  # green for success
            icon = "✓"
            label = "Success"

            if etype == "TURN_ERROR":
                color = "#ffebee"
                icon = "✗"
                label = f"Error: {data.get('error_type', '?')}"
            elif etype == "TURN_VALIDATION":
                if data.get("hallucination_guard_result") == "blocked":
                    color = "#fff3e0"
                    icon = "⚡"
                    label = "Hallucination Guard Triggered"
            elif etype == "SPECIAL_EVENT":
                event_name = ev.get("event", "")
                if event_name in ("EMPTY_CONTEXT", "OUT_OF_KB", "LOW_CONFIDENCE_RETRIEVAL"):
                    color = "#fff3e0"
                    icon = "⚠"
                    label = event_name

            # Build detail info
            details = []
            if etype == "TURN_RETRIEVAL":
                details.append(f"Confidence: {data.get('confidence_score', '?'):.4f}")
                details.append(f"Latency: {data.get('latency_ms', '?'):.0f}ms")
                details.append(f"Chunks: {data.get('chunks_passed_to_llm', '?')}")
            elif etype == "TURN_LLM_LIFECYCLE":
                details.append(f"TTFT: {data.get('ttft_ms', '?'):.0f}ms")
                details.append(f"Generation: {data.get('generation_duration_ms', '?'):.0f}ms")
                details.append(f"Total: {data.get('total_llm_duration_ms', '?'):.0f}ms")
                details.append(f"Tokens: {data.get('tokens_completion', '?')}")
                tok_sec = data.get("estimated_tokens_per_second", 0)
                if tok_sec:
                    details.append(f"Tok/s: {tok_sec:.1f}")
            elif etype == "TURN_VOICE":
                details.append(f"TTS: {data.get('tts_latency_ms', '?'):.0f}ms")
            elif etype == "TURN_INPUT":
                raw = data.get("raw_stt_transcript", "")
                details.append(f"Query: {raw[:100]}")
            elif etype == "TURN_ERROR":
                details.append(f"Type: {data.get('error_type', '?')}")
                details.append(f"Msg: {data.get('exception_message', '?')[:80]}")
                details.append(f"Elapsed: {data.get('elapsed_ms', '?'):.0f}ms")

            detail_str = " | ".join(details) if details else ""

            items_html += f"""
            <div class="event" style="background:{color}">
                <span class="event-icon">{icon}</span>
                <span class="event-type">{etype}</span>
                <span class="event-ts">{ts[11:19] if len(ts) > 19 else ts}</span>
                <span class="event-label">{label}</span>
                <span class="event-detail">{detail_str}</span>
            </div>"""

        cards_html += f"""
        <div class="turn-card">
            <div class="turn-header" onclick="toggleTurn(this)">
                <span>Turn {tn}</span>
                <span class="turn-arrow">▶</span>
            </div>
            <div class="turn-body">
                {items_html}
            </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Session Timeline — {session_id}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #f5f5f5; margin: 20px; color: #333; }}
h1 {{ font-size: 18px; margin-bottom: 4px; }}
.sub {{ color: #666; font-size: 13px; margin-bottom: 20px; }}
.turn-card {{ background: white; border-radius: 8px; margin-bottom: 8px;
              box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }}
.turn-header {{ padding: 10px 14px; cursor: pointer; display: flex;
               justify-content: space-between; font-weight: 600;
               background: #fafafa; border-bottom: 1px solid #eee; }}
.turn-header:hover {{ background: #f0f0f0; }}
.turn-arrow {{ transition: transform 0.2s; }}
.turn-arrow.open {{ transform: rotate(90deg); }}
.turn-body {{ padding: 8px 14px; }}
.event {{ padding: 6px 10px; margin: 4px 0; border-radius: 4px;
          font-size: 13px; display: flex; gap: 8px; align-items: center; }}
.event-icon {{ font-weight: bold; width: 20px; }}
.event-type {{ font-weight: 600; color: #555; min-width: 110px; }}
.event-ts {{ color: #999; font-family: monospace; font-size: 11px; min-width: 60px; }}
.event-label {{ color: #666; font-size: 12px; min-width: 140px; }}
.event-detail {{ color: #444; font-size: 12px; }}
.summary {{ background: #e3f2fd; padding: 12px; border-radius: 8px; margin-top: 16px;
            font-size: 13px; line-height: 1.6; }}
</style>
</head>
<body>
<h1>Session Timeline</h1>
<div class="sub">{session_id} — {len(events)} events across {len(turn_keys)} turns</div>
{cards_html}
<script>
function toggleTurn(el) {{
    var body = el.nextElementSibling;
    var arrow = el.querySelector('.turn-arrow');
    if (body.style.display === 'none' || body.style.display === '') {{
        body.style.display = 'block';
        arrow.classList.add('open');
    }} else {{
        body.style.display = 'none';
        arrow.classList.remove('open');
    }}
}}
// Start with all turns collapsed
document.querySelectorAll('.turn-body').forEach(function(el) {{
    el.style.display = 'none';
}});
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def generate_all_timelines(events_by_session: dict, output_dir: str, max_sessions: int = 20):
    """Generate timelines for all sessions."""
    from pathlib import Path

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    generated = []
    # Only generate for sessions with at least 2 events
    candidates = [(sid, evts) for sid, evts in events_by_session.items() if len(evts) >= 2]
    # Sort by event count descending, take top N
    candidates.sort(key=lambda x: -len(x[1]))

    for sid, evts in candidates[:max_sessions]:
        path = out / f"timeline_{sid.replace('/', '_')}.html"
        generate_timeline_html(sid, evts, str(path))
        generated.append(str(path))

    return generated
