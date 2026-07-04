"""
Task 6: LLM Analysis
=====================
Analyzes LLM behavior: token usage, lengths, correlations.
"""

from collections import defaultdict
from .loader import safe_avg, percentile, safe_stdev


def analyze_llm(events_by_session: dict, all_events: list) -> dict:
    """Analyze LLM completion metrics and correlations."""
    output_lengths = []
    completion_tokens = []
    prompt_tokens = []
    tokens_per_sec = []
    ttfts = []
    models = defaultdict(int)

    # For correlation analysis
    prompt_chars_list = []
    retrieved_chunks_list = []
    output_lengths_for_corr = []
    latencies_for_corr = []

    turn_data = []  # (latency, prompt_len, chunks, output_len)

    for ev in all_events:
        etype = ev.get("type", "")
        data = ev.get("data", {})

        if etype == "TURN_LLM_LIFECYCLE":
            ot = data.get("output_tokens", 0) or data.get("tokens_completion", 0)
            pt = data.get("tokens_prompt", 0)
            ct = data.get("tokens_completion", 0)
            tps = data.get("estimated_tokens_per_second", 0)
            ttft = data.get("ttft_ms", 0)
            lat = data.get("total_llm_duration_ms", 0)
            model = data.get("model", "unknown")
            resp_len = data.get("response_length_chars", 0) or len(data.get("response", "") or "")

            if ot > 0:
                completion_tokens.append(ct)
            if pt > 0:
                prompt_tokens.append(pt)
            if tps > 0:
                tokens_per_sec.append(tps)
            if ttft > 0:
                ttfts.append(ttft)

            output_lengths.append(resp_len)
            models[model] += 1

            # Collect for correlation
            prompt_chars = data.get("response_length_chars", resp_len)
            turn_data.append((lat, pt, 0, resp_len))

        elif etype == "TURN_RETRIEVAL":
            top_chunks = data.get("top_chunks", [])
            retrieved_chunks = len(top_chunks) if top_chunks else 0
            # We need to match retrieval to LLM lifecycle by turn
            # Store per-turn chunk counts
            sid = ev.get("session_id", "")
            tn = ev.get("turn_number", 0)
            # We'll correlate below

    # Correlate retrieval chunk counts with LLM latency
    retrieval_chunks_by_turn = {}
    for ev in all_events:
        if ev.get("type") == "TURN_RETRIEVAL":
            data = ev.get("data", {})
            sid = ev.get("session_id", "")
            tn = ev.get("turn_number", 0)
            top_chunks = data.get("top_chunks", [])
            retrieval_chunks_by_turn[(sid, tn)] = len(top_chunks) if top_chunks else 0

    correlation_data = []
    for ev in all_events:
        if ev.get("type") == "TURN_LLM_LIFECYCLE":
            data = ev.get("data", {})
            sid = ev.get("session_id", "")
            tn = ev.get("turn_number", 0)
            lat = data.get("total_llm_duration_ms", 0)
            pt = data.get("tokens_prompt", 0)
            ct = data.get("tokens_completion", 0)
            resp_len = data.get("response_length_chars", 0) or len(data.get("response", "") or "")
            chunks = retrieval_chunks_by_turn.get((sid, tn), 0)
            correlation_data.append(
                {
                    "latency_ms": lat,
                    "prompt_tokens": pt,
                    "completion_tokens": ct,
                    "output_chars": resp_len,
                    "retrieved_chunks": chunks,
                }
            )

    # Compute correlation coefficients (Spearman-like rank)
    def rank_corr(xs, ys):
        """Simple rank correlation."""
        n = min(len(xs), len(ys))
        if n < 3:
            return 0.0
        xr = [sorted(xs).index(v) for v in xs]
        yr = [sorted(ys).index(v) for v in ys]
        d2 = sum((xr[i] - yr[i]) ** 2 for i in range(n))
        return round(1 - (6 * d2) / (n * (n * n - 1)), 4)

    corr_prompt = rank_corr(
        [d["prompt_tokens"] for d in correlation_data if d["prompt_tokens"] > 0],
        [d["latency_ms"] for d in correlation_data if d["prompt_tokens"] > 0],
    )
    corr_chunks = rank_corr(
        [d["retrieved_chunks"] for d in correlation_data],
        [d["latency_ms"] for d in correlation_data],
    )
    corr_output = rank_corr(
        [d["output_chars"] for d in correlation_data if d["output_chars"] > 0],
        [d["latency_ms"] for d in correlation_data if d["output_chars"] > 0],
    )

    # Longest/shortest completions
    sorted_by_output = sorted(correlation_data, key=lambda x: -x["output_chars"])
    sorted_by_latency = sorted(correlation_data, key=lambda x: -x["latency_ms"])

    output_lengths.sort()
    ttfts.sort()

    report = {
        "total_llm_calls": len(correlation_data),
        "output_length_chars": {
            "avg": round(safe_avg(output_lengths), 1),
            "median": round(percentile(output_lengths, 50), 1),
            "min": round(output_lengths[0], 1) if output_lengths else 0,
            "max": round(output_lengths[-1], 1) if output_lengths else 0,
        },
        "completion_tokens": {
            "avg": round(safe_avg(completion_tokens), 1),
            "median": round(percentile(completion_tokens, 50), 1),
            "count": len(completion_tokens),
        },
        "prompt_tokens": {
            "avg": round(safe_avg(prompt_tokens), 1),
            "median": round(percentile(prompt_tokens, 50), 1),
            "count": len(prompt_tokens),
        },
        "tokens_per_second": {
            "avg": round(safe_avg(tokens_per_sec), 2),
            "median": round(percentile(sorted(tokens_per_sec), 50), 2),
            "count": len(tokens_per_sec),
        },
        "ttft_ms": {
            "avg": round(safe_avg(ttfts), 1),
            "median": round(percentile(sorted(ttfts), 50), 1),
            "p95": round(percentile(sorted(ttfts), 95), 1),
        },
        "model_distribution": dict(models),
        "correlation_with_latency": {
            "prompt_tokens_rank_corr": corr_prompt,
            "retrieved_chunks_rank_corr": corr_chunks,
            "output_chars_rank_corr": corr_output,
        },
        "longest_completions": [
            {"output_chars": d["output_chars"], "latency_ms": round(d["latency_ms"], 1)}
            for d in sorted_by_output[:5]
        ],
        "shortest_completions": [
            {"output_chars": d["output_chars"], "latency_ms": round(d["latency_ms"], 1)}
            for d in sorted_by_output[-5:]
        ],
        "highest_latency_calls": [
            {
                "latency_ms": round(d["latency_ms"], 1),
                "output_chars": d["output_chars"],
                "prompt_tokens": d["prompt_tokens"],
            }
            for d in sorted_by_latency[:5]
        ],
    }
    return report


def print_llm_report(report: dict):
    """Pretty-print LLM analysis."""
    print(f"\n{'=' * 60}")
    print("  LLM ANALYSIS")
    print(f"{'=' * 60}")
    print(f"  Total LLM calls: {report['total_llm_calls']}")
    print(
        f"  Avg output: {report['output_length_chars']['avg']} chars  |  "
        f"Median: {report['output_length_chars']['median']}  |  "
        f"Max: {report['output_length_chars']['max']}"
    )
    print(
        f"  Avg completion tokens: {report['completion_tokens']['avg']}  |  "
        f"Avg prompt tokens: {report['prompt_tokens']['avg']}"
    )
    print(
        f"  Avg tokens/sec: {report['tokens_per_second']['avg']}  |  "
        f"Avg TTFT: {report['ttft_ms']['avg']}ms"
    )
    print()
    print(f"  Model Distribution:")
    for model, count in sorted(report["model_distribution"].items(), key=lambda x: -x[1]):
        print(f"    {model:<40} {count}")
    print()
    print(f"  Correlation with Latency (rank correlation):")
    corr = report["correlation_with_latency"]
    print(f"    Prompt tokens:  {corr['prompt_tokens_rank_corr']:+.4f}")
    print(f"    Retrieved chunks: {corr['retrieved_chunks_rank_corr']:+.4f}")
    print(f"    Output chars:   {corr['output_chars_rank_corr']:+.4f}")
