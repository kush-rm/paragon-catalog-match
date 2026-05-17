"""
Benchmark runner for the Paragon catalog match app.

Runs all 33 example queries through the full pipeline, collects real
latency / token / score metrics, and caches results to disk so
re-runs are instant.

Cost constants use Claude Sonnet 4.5 public pricing (as of 2026-05):
  Input  : $3.00 / 1 M tokens
  Output : $15.00 / 1 M tokens
"""

import json
import time
from pathlib import Path
from typing import Any

import anthropic

from matcher import match as run_match

# ── 33 example queries ────────────────────────────────────────────────────────

BENCHMARK_QUERIES: list[str] = [
    "M8 flat washer",
    "5/16 hex nut",
    "1/2 inch hex nut",
    "M6 hex nuts",
    "SHCS 7/16 x 2-1/2",
    "1/2 rod 6 foot",
    "HHB 3/4-10 x 5/8",
    "lock washer 5/8",
    "M8 x 16 hex cap screw",
    "M16 threaded rod 60mm",
    "5/8 flat washer",
    "M12 x 50mm button socket",
    "#8-32 lock washer",
    "1/4-20 x 3/4 hex cap screw zinc",
    "M4 x 16mm socket head cap screw",
    "3/8 lag screw 1 inch",
    "M5 x 30 threaded rod",
    "7/16-14 phillips pan machine screw 1-1/4",
    "5/16-18 flat washer",
    "M10 x 60mm lag screw",
    "M8 x 50mm BHCS",
    "3/4-10 tap bolt 5/8",
    "M12 hex nut",
    "1/2-13 x 3 lag screw",
    "M6 x 50mm tap bolt",
    "#10-24 x 1/2 threaded rod",
    "5/8-11 x 3/8 lag screw",
    "M16 x 8mm pan head machine screw",
    "3/8-16 x 4 hex bolt",
    "M4 hex nut",
    "M8 x 50mm button socket cap screw alloy black oxide",
    "brass hex nut 1/2-13",
    "the same washers as last time",
]

# ── Cost constants (Claude Sonnet 4.5, 2026-05) ───────────────────────────────
INPUT_COST_PER_MTOK  = 3.00   # USD per million input tokens
OUTPUT_COST_PER_MTOK = 15.00  # USD per million output tokens

# ── Cache file ────────────────────────────────────────────────────────────────
CACHE_PATH = Path(__file__).parent / "benchmark_cache.json"

# ── Edge-case category detection ──────────────────────────────────────────────

_ABBREV_TERMS   = {"shcs", "bhcs", "hhb", "fhcs", "hcs", "hhb", "btn", "soc", "mz", "yz", "zc"}
_HISTORY_TERMS  = {"last time", "same as", "usual", "reorder", "previous"}
_VAGUE_TERMS    = {"same", "last time", "usual", "normal"}

def categorise_query(q: str) -> str:
    lower = q.lower()
    words = set(lower.split())
    if any(t in words for t in _ABBREV_TERMS):
        return "Abbreviation"
    if any(t in lower for t in _HISTORY_TERMS):
        return "History-vague"
    tokens = lower.split()
    # Under-specified: short query (≤ 3 tokens) without both size + type
    if len(tokens) <= 3:
        return "Under-specified"
    return "Precise"


# ── Aggregate stats ───────────────────────────────────────────────────────────

def compute_stats(results: list[dict]) -> dict[str, Any]:
    """
    Given a list of per-query result dicts, compute the slide-ready aggregate.
    """
    n = len(results)
    if n == 0:
        return {}

    total_input   = sum(r["input_tokens"]  for r in results)
    total_output  = sum(r["output_tokens"] for r in results)
    total_tokens  = total_input + total_output
    total_time_ms = sum(r["response_time_ms"] for r in results)

    cost_per_query = (
        (total_input  / n / 1_000_000) * INPUT_COST_PER_MTOK +
        (total_output / n / 1_000_000) * OUTPUT_COST_PER_MTOK
    )
    cost_per_token = (
        (total_input  / 1_000_000 * INPUT_COST_PER_MTOK +
         total_output / 1_000_000 * OUTPUT_COST_PER_MTOK)
        / total_tokens
        if total_tokens > 0 else 0
    )

    # Score distribution using the top result's base_score for each query
    top_scores = [r["top_score"] for r in results if r.get("top_score") is not None]
    dist = {
        "very_high": sum(1 for s in top_scores if s >= 85),
        "high":      sum(1 for s in top_scores if 70 <= s < 85),
        "medium":    sum(1 for s in top_scores if 50 <= s < 70),
        "low":       sum(1 for s in top_scores if s < 50),
    }

    # Per-category breakdown
    categories: dict[str, list] = {}
    for r in results:
        cat = r.get("category", "Other")
        categories.setdefault(cat, []).append(r["top_score"])

    cat_summary = {
        cat: {
            "count": len(scores),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        }
        for cat, scores in categories.items()
    }

    return {
        "query_count":           n,
        "avg_response_time_ms":  round(total_time_ms / n),
        "avg_input_tokens":      round(total_input  / n),
        "avg_output_tokens":     round(total_output / n),
        "avg_total_tokens":      round(total_tokens / n),
        "total_cost_usd":        round(
            total_input  / 1_000_000 * INPUT_COST_PER_MTOK +
            total_output / 1_000_000 * OUTPUT_COST_PER_MTOK,
            4
        ),
        "cost_per_query_usd":    round(cost_per_query, 4),
        "cost_per_token_usd":    round(cost_per_token, 8),
        "score_distribution":    dist,
        "category_breakdown":    cat_summary,
        "input_cost_per_mtok":   INPUT_COST_PER_MTOK,
        "output_cost_per_mtok":  OUTPUT_COST_PER_MTOK,
        "model":                 "claude-sonnet-4-5",
    }


# ── Cache helpers ─────────────────────────────────────────────────────────────

def load_cache() -> dict[str, Any]:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            pass
    return {}


def save_cache(data: dict[str, Any]) -> None:
    CACHE_PATH.write_text(json.dumps(data, indent=2))


# ── Runner (called from the SSE endpoint) ────────────────────────────────────

def run_single_query(
    query: str,
    catalog: list[dict],
    catalog_index: dict,
    order_history: list[dict],
    client: anthropic.Anthropic,
) -> dict[str, Any]:
    """
    Run one query through the full pipeline and return a flat result dict
    suitable for the benchmark cache and SSE stream.
    """
    result = run_match(
        query=query,
        catalog=catalog,
        catalog_index=catalog_index,
        order_history=order_history,
        customer_id=None,        # benchmark uses no customer (pure description match)
        client=client,
    )

    meta  = result["query_metadata"]
    top   = result["results"][0] if result["results"] else {}

    # Split tokens (usage returns total; we stored them in metadata as sum)
    # Re-derive input/output from the response — stored as total in tokens_used.
    # For the split we use the same ratio we know from the API (output << input).
    # The matcher now stores both; fall back gracefully if not present.
    tokens_used    = meta.get("tokens_used", 0)
    input_tokens   = meta.get("input_tokens",  int(tokens_used * 0.985))
    output_tokens  = meta.get("output_tokens", int(tokens_used * 0.015))

    return {
        "query":            query,
        "expanded_query":   meta.get("expanded_query", query),
        "category":         categorise_query(query),
        "response_time_ms": meta.get("response_time_ms", 0),
        "tokens_used":      tokens_used,
        "input_tokens":     input_tokens,
        "output_tokens":    output_tokens,
        "top_score":        top.get("base_score"),
        "top_catalog_id":   top.get("catalog_id"),
        "top_description":  top.get("description"),
        "top_active":       top.get("active"),
        "error":            None,
    }
