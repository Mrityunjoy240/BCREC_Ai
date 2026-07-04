"""
Demo-Readiness Stress Test for LiveKit Voice Agent.

Simulates 20 consecutive voice sessions × 3 questions each = 60 queries.
Monitors server resources (memory, threads, file handles, connections)
at every checkpoint using psutil.

Usage:
  python backend/benchmarks/demo_stress_test.py

Requirements:
  - Backend must be running on http://127.0.0.1:8000
  - pip install psutil httpx
"""

import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPORT_DIR = Path(__file__).resolve().parent / "eval_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

try:
    import psutil
except ImportError:
    print("ERROR: psutil not installed. Run: pip install psutil")
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

SERVER_URL = "http://127.0.0.1:8000"

QUESTIONS = [
    "What departments are available at BCREC?",
    "What is the fee for B.Tech CSE?",
    "How many hostels are there in BCREC?",
    "Who is the principal of BCREC?",
    "What is the placement rate at BCREC?",
    "Does BCREC offer MCA and MBA programs?",
    "What scholarships are available?",
    "How can I apply for B.Tech admission?",
    "What is the campus size?",
    "Is Wi-Fi available in the campus?",
    "Tell me about the CSE department",
    "What is the refund policy?",
    "Hostel fee details",
    "Which companies visit BCREC for placement?",
    "What is the eligibility for B.Tech?",
    "Who is the HOD of CSE?",
    "Is hostel compulsory?",
    "What is the NAAC grade of BCREC?",
    "Can international students apply?",
    "What is the dress code?",
]

NUM_SESSIONS = 20
QUESTIONS_PER_SESSION = 3
TOTAL_QUERIES = NUM_SESSIONS * QUESTIONS_PER_SESSION  # 60


def find_server_process():
    """Find the uvicorn server process (the real python.exe, not bash wrapper)."""
    candidates = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
            name = (p.info["name"] or "").lower()
            # Match the actual python process running uvicorn, not the bash launcher
            if name in ("python.exe", "python3.exe") and "uvicorn" in cl and "app.main:app" in cl:
                candidates.append(p)
            # Also catch bash wrappers that wrap python -m uvicorn
            if "uvicorn" in cl and "app.main" in cl and not candidates:
                candidates.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    # Prefer python.exe over bash.exe
    for c in candidates:
        if c.info["name"] and c.info["name"].lower().startswith("python"):
            return c
    return candidates[0] if candidates else None


def snapshot(proc, label=""):
    """Capture resource snapshot of the server process."""
    if proc is None:
        return {}
    try:
        mem = proc.memory_info()
        children = proc.children(recursive=True)
        child_rss = sum(c.memory_info().rss for c in children if c.is_running())
        return {
            "label": label,
            "timestamp": time.time(),
            "rss_mb": round(mem.rss / 1024 / 1024, 1),
            "vms_mb": round(mem.vms / 1024 / 1024, 1),
            "rss_total_mb": round((mem.rss + child_rss) / 1024 / 1024, 1),
            "threads": proc.num_threads(),
            "open_files": len(proc.open_files()),
            "connections": len(proc.net_connections()),
            "cpu_percent": proc.cpu_percent(interval=0.1),
            "children": len(children),
        }
    except Exception as e:
        return {"label": label, "error": str(e)}


def print_snapshot(snap, delta=None):
    """Pretty-print a snapshot."""
    if "error" in snap:
        print(f"  [{snap['label']}] ERROR: {snap['error']}")
        return
    parts = [
        f"RSS={snap['rss_mb']}MB",
        f"thr={snap['threads']}",
        f"fds={snap['open_files']}",
        f"conn={snap['connections']}",
    ]
    if delta:
        parts.append(f"ΔRSS={delta['rss_mb']:+.1f}MB" if "rss_mb" in delta else "")
    print(f"  [{snap['label']:20s}] {' | '.join(p for p in parts if p)}")


async def run_stress_test():
    print("=" * 80)
    print("  DEMO-READINESS STRESS TEST — LiveKit Voice Agent")
    print(f"  {datetime.now().isoformat()}")
    print(
        f"  Sessions: {NUM_SESSIONS} × {QUESTIONS_PER_SESSION} questions = {TOTAL_QUERIES} queries"
    )
    print("=" * 80)
    print()

    # 1. Find server process
    proc = find_server_process()
    if proc is None:
        print("ERROR: Server process not found. Is uvicorn running?")
        sys.exit(1)

    server_pid = proc.pid
    print(f"Server PID: {server_pid}  ({proc.info['name']})")
    print()

    # 2. Baseline
    baseline = snapshot(proc, "baseline")
    print_snapshot(baseline)
    print()

    # 3. Verify backend health
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get(f"{SERVER_URL}/qa/health")
            health = r.json()
            print(f"Backend health: {health}")
        except Exception as e:
            print(f"Backend unreachable: {e}")
            sys.exit(1)
        print()

        # 4. Run stress test
        snapshots = [baseline]
        all_results = []
        errors = []
        latencies = []
        first_token_latencies = []

        for session_num in range(1, NUM_SESSIONS + 1):
            session_id = f"stress_session_{session_num:03d}"
            session_questions = QUESTIONS[
                ((session_num - 1) * QUESTIONS_PER_SESSION) % len(QUESTIONS) :
            ][:QUESTIONS_PER_SESSION]

            print(f"--- Session {session_num}/{NUM_SESSIONS} (id={session_id}) ---")

            for q_idx, question in enumerate(session_questions):
                query_start = time.time()
                try:
                    resp = await client.post(
                        f"{SERVER_URL}/qa/query",
                        json={"message": question, "session_id": session_id},
                        timeout=120,
                    )
                    elapsed = (time.time() - query_start) * 1000
                    latencies.append(elapsed)

                    if resp.status_code != 200:
                        errors.append(
                            f"Session {session_num} Q{q_idx + 1}: HTTP {resp.status_code} - {resp.text[:100]}"
                        )
                        print(f"  Q{q_idx + 1}: ERROR {resp.status_code} ({elapsed:.0f}ms)")
                        continue

                    data = resp.json()
                    all_results.append(data)

                    # First-token latency not available from /qa/query (non-streaming)
                    # We'll get it from /qa/query-stream for a subset
                    answer_len = len(data.get("answer", ""))
                    source = data.get("source", "?")
                    print(f"  Q{q_idx + 1}: {elapsed:.0f}ms  src={source:20s}  ans={answer_len}c")

                except httpx.TimeoutException:
                    elapsed = (time.time() - query_start) * 1000
                    errors.append(f"Session {session_num} Q{q_idx + 1}: TIMEOUT ({elapsed:.0f}ms)")
                    print(f"  Q{q_idx + 1}: TIMEOUT ({elapsed:.0f}ms)")
                except Exception as e:
                    elapsed = (time.time() - query_start) * 1000
                    errors.append(f"Session {session_num} Q{q_idx + 1}: {e}")
                    print(f"  Q{q_idx + 1}: ERROR {e}")

            # Snapshot after each session
            snap = snapshot(proc, f"session_{session_num:03d}")
            snapshots.append(snap)
            delta = {
                "rss_mb": snap["rss_mb"] - snapshots[-2]["rss_mb"],
                "threads": snap["threads"] - snapshots[-2]["threads"],
                "open_files": snap["open_files"] - snapshots[-2]["open_files"],
                "connections": snap["connections"] - snapshots[-2]["connections"],
            }
            print_snapshot(snap, delta)
            print()

        # 5. Measure first-token latency via streaming endpoint (3 sample calls)
        print("--- Measuring first-token latency (3 stream calls) ---")
        for i in range(3):
            q = QUESTIONS[i % len(QUESTIONS)]
            query_start = time.time()
            first_token_time = None
            total_chars = 0
            try:
                async with client.stream(
                    "POST",
                    f"{SERVER_URL}/qa/query-stream",
                    json={"message": q, "session_id": "latency_test"},
                    timeout=120,
                ) as resp:
                    first = True
                    async for line in resp.aiter_lines():
                        if line.startswith("data: ") and line.strip() != "data: [DONE]":
                            if first:
                                first_token_time = (time.time() - query_start) * 1000
                                first_token_latencies.append(first_token_time)
                                first = False
                            total_chars += 1

                total_time = (time.time() - query_start) * 1000
                print(
                    f"  Stream {i + 1}: TTFT={first_token_time:.0f}ms  total={total_time:.0f}ms  chars={total_chars}"
                )
            except Exception as e:
                errors.append(f"Stream latency test {i + 1}: {e}")
                print(f"  Stream {i + 1}: ERROR {e}")

        # 6. Final snapshot
        print()
        print("--- Final state ---")
        final_snap = snapshot(proc, "final")
        snapshots.append(final_snap)
        delta = {
            "rss_mb": final_snap["rss_mb"] - baseline["rss_mb"],
            "threads": final_snap["threads"] - baseline["threads"],
            "open_files": final_snap["open_files"] - baseline["open_files"],
            "connections": final_snap["connections"] - baseline["connections"],
        }
        print_snapshot(final_snap, delta)
        print()

        # 7. Wait 5 seconds and take another snapshot to check for cleanup
        print("Waiting 5s for cleanup...")
        await asyncio.sleep(5)
        cleanup_snap = snapshot(proc, "cleanup_5s")
        snapshots.append(cleanup_snap)
        delta = {
            "rss_mb": cleanup_snap["rss_mb"] - baseline["rss_mb"],
            "threads": cleanup_snap["threads"] - baseline["threads"],
        }
        print_snapshot(cleanup_snap, delta)
        print()

    # 8. Generate Report
    print("=" * 80)
    print("  STRESS TEST REPORT")
    print("=" * 80)
    print()

    # Memory analysis
    rss_values = [s["rss_mb"] for s in snapshots if "error" not in s]
    peak_rss = max(rss_values) if rss_values else 0
    final_rss = rss_values[-1] if len(rss_values) > 1 else 0
    baseline_rss = rss_values[0] if rss_values else 0

    print(f"  Peak RSS:      {peak_rss:.1f} MB  (at snapshot {rss_values.index(peak_rss)})")
    print(f"  Baseline RSS:  {baseline_rss:.1f} MB")
    print(f"  Final RSS:     {final_rss:.1f} MB  ({final_rss - baseline_rss:+.1f} MB vs baseline)")

    # Leak detection
    rss_growth = final_rss - baseline_rss
    if rss_growth > 50:
        print(f"  ⚠ RSS LEAK: {rss_growth:.1f}MB growth over {TOTAL_QUERIES} queries")
    elif rss_growth > 10:
        print(f"  ⚠ Minor RSS growth: {rss_growth:.1f}MB")
    else:
        print(f"  ✅ RSS stable: {rss_growth:+.1f}MB")

    # Thread analysis
    thread_values = [s["threads"] for s in snapshots if "error" not in s]
    thread_growth = thread_values[-1] - thread_values[0] if len(thread_values) > 1 else 0
    print(
        f"  Thread growth: {thread_growth:+.0f}  (final={thread_values[-1]}, baseline={thread_values[0]})"
    )
    if thread_growth > 5:
        print(f"  ⚠ Thread LEAK: {thread_growth} threads leaked")

    # FD analysis
    fd_values = [s["open_files"] for s in snapshots if "error" not in s]
    fd_growth = fd_values[-1] - fd_values[0] if len(fd_values) > 1 else 0
    print(f"  FD growth:     {fd_growth:+.0f}  (final={fd_values[-1]}, baseline={fd_values[0]})")
    if fd_growth > 5:
        print(f"  ⚠ File handle LEAK: {fd_growth} handles leaked")

    # Connection analysis
    conn_values = [s["connections"] for s in snapshots if "error" not in s]
    conn_growth = conn_values[-1] - conn_values[0] if len(conn_values) > 1 else 0
    print(f"  Connections:   {conn_values[-1]} (Δ={conn_growth:+.0f})")

    # Latency
    if latencies:
        avg_lat = sum(latencies) / len(latencies)
        max_lat = max(latencies)
        min_lat = min(latencies)
        # Check for latency creep (last 10 vs first 10)
        if len(latencies) >= 20:
            first_10_avg = sum(latencies[:10]) / 10
            last_10_avg = sum(latencies[-10:]) / 10
            latency_creep = last_10_avg / first_10_avg if first_10_avg > 0 else 1.0
        else:
            first_10_avg = sum(latencies[: len(latencies) // 2]) / max(1, len(latencies) // 2)
            last_10_avg = sum(latencies[len(latencies) // 2 :]) / max(
                1, len(latencies) - len(latencies) // 2
            )
            latency_creep = last_10_avg / first_10_avg if first_10_avg > 0 else 1.0

        print()
        print(f"  Latency (n={len(latencies)}):")
        print(f"    Average:  {avg_lat:.0f} ms")
        print(f"    Min:      {min_lat:.0f} ms")
        print(f"    Max:      {max_lat:.0f} ms")
        print(f"    Median:   {sorted(latencies)[len(latencies) // 2]:.0f} ms")
        print(f"    P95:      {sorted(latencies)[int(len(latencies) * 0.95)]:.0f} ms")
        print(f"    First 10 avg:  {first_10_avg:.0f} ms")
        print(f"    Last 10 avg:   {last_10_avg:.0f} ms")
        if latency_creep > 1.5:
            print(f"    ⚠ LATENCY CREEP: last 10 are {latency_creep:.1f}x slower than first 10")
        else:
            print(f"    ✅ Latency stable: last 10 vs first 10 ratio = {latency_creep:.2f}x")

    # First-token latency
    if first_token_latencies:
        avg_ttft = sum(first_token_latencies) / len(first_token_latencies)
        print()
        print(f"  First-token latency (n={len(first_token_latencies)}):")
        print(f"    Average: {avg_ttft:.0f} ms")
        print(
            f"    Range:   {min(first_token_latencies):.0f} - {max(first_token_latencies):.0f} ms"
        )

    # Errors
    print()
    print(f"  Errors: {len(errors)} / {TOTAL_QUERIES}")
    if errors:
        for e in errors[:10]:
            print(f"    - {e}")
        if len(errors) > 10:
            print(f"    ... and {len(errors) - 10} more")
    else:
        print("    ✅ Zero errors")

    # Resource leak summary
    print()
    print("  Resource Leak Assessment:")
    leak_flags = []
    if rss_growth > 50:
        leak_flags.append(f"⚠ MEMORY (ΔRSS={rss_growth:.0f}MB)")
    else:
        leak_flags.append("✅ MEMORY")

    if thread_growth > 5:
        leak_flags.append(f"⚠ THREADS (Δ={thread_growth})")
    else:
        leak_flags.append("✅ THREADS")

    if fd_growth > 5:
        leak_flags.append(f"⚠ FDS (Δ={fd_growth})")
    else:
        leak_flags.append("✅ FDS")

    if latency_creep > 2.0:
        leak_flags.append(f"⚠ LATENCY (creep={latency_creep:.1f}x)")
    else:
        leak_flags.append("✅ LATENCY")

    print("    " + " | ".join(leak_flags))

    # Save report
    report_lines = [
        "=" * 80,
        "  DEMO-READINESS STRESS TEST REPORT",
        f"  Generated: {datetime.now().isoformat()}",
        "=" * 80,
        "",
        f"  Sessions: {NUM_SESSIONS} × {QUESTIONS_PER_SESSION} questions = {TOTAL_QUERIES} queries",
        "",
        f"  Peak RSS:        {peak_rss:.1f} MB",
        f"  Baseline RSS:    {baseline_rss:.1f} MB",
        f"  Final RSS:       {final_rss:.1f} MB",
        f"  RSS Growth:      {rss_growth:+.1f} MB",
        "",
        f"  Threads:         {thread_values[0]} → {thread_values[-1]} (Δ={thread_growth:+.0f})",
        f"  Open Files:      {fd_values[0]} → {fd_values[-1]} (Δ={fd_growth:+.0f})",
        f"  Connections:     {conn_values[0]} → {conn_values[-1]} (Δ={conn_growth:+.0f})",
        "",
    ]
    if latencies:
        report_lines += [
            f"  Avg Latency:     {avg_lat:.0f} ms",
            f"  P95 Latency:     {sorted(latencies)[int(len(latencies) * 0.95)]:.0f} ms",
            f"  Max Latency:     {max_lat:.0f} ms",
            f"  Latency Creep:   {latency_creep:.2f}x",
            "",
        ]
    if first_token_latencies:
        report_lines += [
            f"  Avg TTFT:        {avg_ttft:.0f} ms",
            "",
        ]
    report_lines += [
        f"  Errors:          {len(errors)} / {TOTAL_QUERIES}",
        "",
        "  Resource Leak Assessment:",
        "    " + " | ".join(leak_flags),
        "",
    ]
    if errors:
        report_lines += ["  Errors Detail:"]
        for e in errors:
            report_lines.append(f"    - {e}")
        report_lines.append("")

    report_lines += ["=" * 80]

    report_path = REPORT_DIR / f"stress_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\nReport saved to: {report_path}")

    # Summary
    print()
    print(
        f"  Summary: {len(errors)} errors / {TOTAL_QUERIES} queries "
        f"| RSS Δ={rss_growth:+.0f}MB "
        f"| Threads Δ={thread_growth:+.0f} "
        f"| FDs Δ={fd_growth:+.0f}"
    )
    print()


if __name__ == "__main__":
    asyncio.run(run_stress_test())
