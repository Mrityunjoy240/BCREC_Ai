"""
Task 9: Engineering Summary
============================
Synthesizes all analysis results into a markdown report with
evidence-based recommendations.
"""

import json


def generate_summary(all_reports: dict, output_path: str):
    """Generate a markdown engineering summary with recommendations."""
    r = all_reports

    # Extract key findings
    latency = r.get("latency", {})
    root_cause = r.get("root_cause", {})
    quality = r.get("quality", {})
    retrieval = r.get("retrieval", {})
    llm = r.get("llm", {})
    coverage = r.get("coverage", [])

    # Determine top bottlenecks
    bottlenecks = _rank_bottlenecks(latency)

    # Determine top failures
    failures = _rank_failures(root_cause)

    # Language performance
    lang_conf = retrieval.get("avg_confidence_by_language", {})
    best_lang = max(lang_conf, key=lang_conf.get) if lang_conf else "N/A"
    worst_lang = min(lang_conf, key=lang_conf.get) if lang_conf else "N/A"

    # Where latency is spent
    llm_total = latency.get("llm_total", {})
    retrieval_lat = latency.get("retrieval", {})
    tts_lat = latency.get("tts", {})
    total_avg = (
        (llm_total.get("avg_ms", 0) or 0)
        + (retrieval_lat.get("avg_ms", 0) or 0)
        + (tts_lat.get("avg_ms", 0) or 0)
    )
    if total_avg == 0:
        total_avg = 1
    llm_pct = round((llm_total.get("avg_ms", 0) or 0) / total_avg * 100, 1)
    retrieval_pct = round((retrieval_lat.get("avg_ms", 0) or 0) / total_avg * 100, 1)
    tts_pct = round((tts_lat.get("avg_ms", 0) or 0) / total_avg * 100, 1)

    md = f"""# Engineering Summary Report

Generated: {__import__("datetime").datetime.now().isoformat()}

## 1. Top 10 Bottlenecks

| # | Component | Avg Latency | P95 | P99 | Impact |
|---|-----------|------------|-----|-----|--------|
"""
    for i, b in enumerate(bottlenecks[:10], 1):
        c = latency.get(b["key"], {})
        md += f"| {i} | {b['label']} | {c.get('avg_ms', 0):.0f}ms | {c.get('p95_ms', 0):.0f}ms | {c.get('p99_ms', 0):.0f}ms | {b['impact']} |\n"

    md += f"""
## 2. Top 10 Conversation Failures

| # | Error Type | Count | % of Errors | Avg Elapsed | Affected Sessions |
|---|-----------|-------|------------|-------------|------------------|
"""
    cats = root_cause.get("categories", {})
    for i, (etype, cat) in enumerate(sorted(cats.items(), key=lambda x: -x[1]["count"])[:10], 1):
        md += f"| {i} | {etype} | {cat['count']} | {cat['percentage']}% | {cat['avg_elapsed_ms']:.0f}ms | {cat['affected_sessions']} |\n"

    md += f"""
## 3. Language Performance

| Language | Avg Confidence |
|----------|---------------|
"""
    for lang, conf in sorted(lang_conf.items(), key=lambda x: -x[1]):
        md += f"| {lang} | {conf:.4f} |\n"

    md += f"""
**Best performing language:** {best_lang} (confidence: {lang_conf.get(best_lang, 0):.4f})
**Worst performing language:** {worst_lang} (confidence: {lang_conf.get(worst_lang, 0):.4f})

## 4. Where Is Latency Spent?

```
Pipeline Stage        Avg Latency    % of Total
----------------------------------------------
LLM (total)           {llm_total.get("avg_ms", 0):>8.0f}ms      {llm_pct:>5.1f}%
  ├─ TTFT             {latency.get("llm_ttft", {}).get("avg_ms", 0):>8.0f}ms
  ├─ Generation       {latency.get("llm_generation", {}).get("avg_ms", 0):>8.0f}ms
  └─ Post-processing  {latency.get("llm_postprocessing", {}).get("avg_ms", 0):>8.0f}ms
Retrieval             {retrieval_lat.get("avg_ms", 0):>8.0f}ms      {retrieval_pct:>5.1f}%
TTS                   {tts_lat.get("avg_ms", 0):>8.0f}ms      {tts_pct:>5.1f}%
```

## 5. Quality Metrics

"""
    raw_counts = quality.get("raw_counts", {})
    rates = quality.get("rates_per_turn_pct", {})
    md += f"""| Metric | Count | Rate per Turn |
|--------|-------|-------------|
"""
    for metric in [
        "clarification_prompts",
        "repeat_requests",
        "language_switches",
        "follow_up_queries",
        "hallucination_guards_triggered",
        "low_confidence_retrievals",
        "ambiguous_queries",
        "interruptions",
    ]:
        c = raw_counts.get(metric, 0)
        r = rates.get(metric, 0)
        md += f"| {metric.replace('_', ' ').title()} | {c} | {r}% |\n"

    md += f"""
## 6. LLM Performance

| Metric | Value |
|--------|-------|
| Avg output length | {llm.get("output_length_chars", {}).get("avg", 0)} chars |
| Avg completion tokens | {llm.get("completion_tokens", {}).get("avg", 0)} |
| Avg tokens/sec | {llm.get("tokens_per_second", {}).get("avg", 0)} |
| Avg TTFT | {llm.get("ttft_ms", {}).get("avg", 0)}ms |
| Correlation: prompt tokens ↔ latency | {llm.get("correlation_with_latency", {}).get("prompt_tokens_rank_corr", "N/A")} |
| Correlation: chunks ↔ latency | {llm.get("correlation_with_latency", {}).get("retrieved_chunks_rank_corr", "N/A")} |
| Correlation: output length ↔ latency | {llm.get("correlation_with_latency", {}).get("output_chars_rank_corr", "N/A")} |

## 7. Recommendations

Based on actual telemetry evidence:
"""

    recommendations = []

    # Check if LLM is the dominant bottleneck
    if llm_pct > 60:
        recommendations.append(
            f"**Optimize LLM latency** ({llm_pct}% of total pipeline time). "
            f"Avg LLM call takes {llm_total.get('avg_ms', 0):.0f}ms. "
            f"Consider: (a) switching to a faster model, (b) reducing prompt size "
            f"(currently avg {llm.get('prompt_tokens', {}).get('avg', 0)} tokens), "
            f"(c) enabling response streaming if not already used."
        )

    if latency.get("llm_ttft", {}).get("avg_ms", 0) > 2000:
        recommendations.append(
            f"**High TTFT detected** — avg {latency['llm_ttft']['avg_ms']:.0f}ms, "
            f"P95 {latency['llm_ttft']['p95_ms']:.0f}ms. This suggests slow model startup "
            f"or provider-side queuing. Consider keep-warm strategies or a different provider."
        )

    if root_cause.get("total_errors", 0) > 0:
        top_error = max(cats.items(), key=lambda x: x[1]["count"]) if cats else (None, None)
        if top_error and top_error[0]:
            recommendations.append(
                f"**Reduce {top_error[0]} errors** ({top_error[1]['count']} occurrences, "
                f"{top_error[1]['percentage']}% of all errors). "
                f"Most common exception: {top_error[1]['most_common_exception']}. "
                f"Review error handling for this failure mode."
            )

    if retrieval.get("empty_contexts", 0) > 0:
        recommendations.append(
            f"**Improve retrieval coverage** — {retrieval['empty_contexts']} empty context(s) detected. "
            f"Average retrieval confidence: {retrieval.get('avg_confidence', 0):.4f}. "
            f"Consider reviewing KB content coverage for low-confidence topics."
        )

    if retrieval.get("hallucination_guard_triggers", 0) > 0:
        recommendations.append(
            f"**Hallucination guard triggered {retrieval['hallucination_guard_triggers']} times** — "
            f"responses contained entities not found in retrieved context. "
            f"Review retrieval chunk quality and LLM instruction to stay within context."
        )

    if quality.get("raw_counts", {}).get("clarification_prompts", 0) > 0:
        rate = quality.get("rates_per_turn_pct", {}).get("clarification_prompts", 0)
        recommendations.append(
            f"**High clarification rate** ({rate}% of turns) — users frequently need to rephrase. "
            f"Consider improving STT accuracy or query expansion for ambiguous inputs."
        )

    if not recommendations:
        recommendations.append("No actionable bottlenecks identified from current telemetry data.")

    for i, rec in enumerate(recommendations, 1):
        md += f"\n{i}. {rec}"

    md += f"""

---
*This report was generated automatically from telemetry JSONL logs.
All statistics reference actual telemetry events — no simulated or assumed data.*
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)

    return output_path


def _rank_bottlenecks(latency: dict) -> list:
    """Rank components by average latency to identify bottlenecks."""
    components = [
        ("llm_total", "LLM Total"),
        ("llm_generation", "LLM Generation"),
        ("llm_ttft", "LLM TTFT"),
        ("tts", "TTS"),
        ("llm_postprocessing", "LLM Post-processing"),
        ("retrieval", "Retrieval"),
        ("overall_turn", "Overall Turn"),
    ]
    ranked = []
    for key, label in components:
        c = latency.get(key, {})
        avg = c.get("avg_ms", 0) or 0
        p95 = c.get("p95_ms", 0) or 0
        ranked.append(
            {
                "key": key,
                "label": label,
                "avg_ms": avg,
                "impact": f"{'Critical' if avg > 5000 else 'High' if avg > 1000 else 'Medium' if avg > 200 else 'Low'}",
            }
        )
    ranked.sort(key=lambda x: -x["avg_ms"])
    return ranked


def _rank_failures(root_cause: dict) -> list:
    """Rank failure categories by count."""
    cats = root_cause.get("categories", {})
    ranked = sorted(cats.items(), key=lambda x: -x[1]["count"])
    return [{"type": etype, **cat} for etype, cat in ranked]
