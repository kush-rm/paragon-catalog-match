"""
Core matching logic for the Paragon catalog search app.

Pipeline:
  1. expand_abbreviations()  — deterministic, runs before Claude sees the query
  2. call_claude()           — semantic matching over the full active catalog
  3. apply_history_boost()   — re-rank using customer purchase patterns

Design notes:
  - We pass the full active catalog (~955 rows) in a single prompt.  At this
    scale it fits comfortably inside Claude's 200K-token context window and
    avoids the silent failure modes of retrieval-augmented search (if the
    retriever returns wrong candidates, Claude reasons over wrong data with
    high confidence).  Threshold to switch to embeddings + vector search:
    ~5,000+ active SKUs.
  - temperature=0 ensures deterministic results — same query always returns
    the same ranking, which is essential for calibration and debugging.
  - We ask Claude for the top-10 candidates and then slice to 3 after
    applying the history boost, so re-ranking has room to move results.
"""

import json
import os
import time
from typing import Any

import anthropic

from abbreviations import expand_abbreviations

# ── Retry config ──────────────────────────────────────────────────────────────
# Each query sends ~34 K tokens. Free-tier accounts have a 30 K TPM limit,
# so rapid back-to-back queries hit 429s. We retry with exponential backoff
# so a single user doesn't see an error just because they searched twice quickly.
_MAX_RETRIES    = 3
_RETRY_BASE_SEC = 15   # wait 15 s → 30 s → 60 s before giving up

# ── Constants ─────────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 1500   # JSON output for 10 matches is well under 1 000 tokens;
                    # 1 500 gives headroom for verbose reasoning fields.

MATERIAL_KEYWORDS = ["STEEL", "BRASS", "ALLOY", "18-8 SS", "316 SS", "A2 SS", "STAINLESS STEEL"]
FINISH_KEYWORDS   = ["ZINC", "BLACK OXIDE", "HOT DIP GALVANIZED", "PLAIN",
                     "YELLOW ZINC", "MECHANICAL ZINC", "MECH ZINC", "HDG"]

DOMINANT_THRESHOLD = 0.60   # >60 % of orders must share the pattern to call it "dominant"
SPARSE_ORDER_LIMIT = 3      # customers with fewer orders get no boost


SYSTEM_PROMPT = """You are a fastener catalog matching system for an industrial distributor.
Your job is to find the top 10 catalog entries most likely to match the user's query.

The catalog uses inconsistent abbreviations and mixed imperial/metric units.
The user's query has already had common abbreviations expanded.

For each match, return:
- catalog_id
- match_score (0-100): how well the description matches the query
- reasoning: one sentence explaining the match

Rules:
- A score of 90-100 means near-certain match (exact size, type, material/finish all match)
- A score of 70-89 means good match but some attributes unspecified or inferred
- A score of 50-69 means possible match, significant ambiguity
- A score below 50 means weak match, include only if nothing better exists
- If the query references attributes not in the catalog (e.g. a brand name, a specific standard not listed), note this and lower the score accordingly
- Return ONLY valid JSON, no markdown fences, no preamble

Return format:
{"matches": [{"catalog_id": "CAT-XXXX", "match_score": 85, "reasoning": "..."}]}"""


# ── Catalog prompt builder ────────────────────────────────────────────────────

def build_catalog_block(catalog: list[dict]) -> str:
    """
    Render the active catalog as a compact line-per-row block.
    Inactive rows are excluded — we only want Claude ranking live inventory.
    """
    lines = []
    for item in catalog:
        if item["active"]:
            lines.append(f"{item['catalog_id']} | {item['catalog_description']}")
    return "\n".join(lines)


# ── History analysis ──────────────────────────────────────────────────────────

def analyse_customer_history(orders: list[dict]) -> dict[str, Any]:
    """
    Extract the dominant material and finish from a customer's order history.

    Returns:
      {
        "order_count": int,
        "sparse": bool,                      # True if < SPARSE_ORDER_LIMIT orders
        "dominant_material": str | None,
        "dominant_finish":   str | None,
        "material_counts":   dict,
        "finish_counts":     dict,
        "pattern_summary":   str,            # human-readable for the UI
      }
    """
    n = len(orders)
    if n < SPARSE_ORDER_LIMIT:
        return {
            "order_count": n,
            "sparse": True,
            "dominant_material": None,
            "dominant_finish": None,
            "material_counts": {},
            "finish_counts": {},
            "pattern_summary": f"Sparse history — using description match only ({n} order{'s' if n != 1 else ''})",
        }

    material_counts: dict[str, int] = {}
    finish_counts: dict[str, int] = {}

    for order in orders:
        desc = order["catalog_description"].upper()

        # Check materials — longer/more-specific patterns first to avoid
        # "STEEL" matching inside "STAINLESS STEEL".
        for mat in sorted(MATERIAL_KEYWORDS, key=len, reverse=True):
            if mat in desc:
                material_counts[mat] = material_counts.get(mat, 0) + 1
                break  # count only the most specific material per order

        for fin in sorted(FINISH_KEYWORDS, key=len, reverse=True):
            if fin in desc:
                finish_counts[fin] = finish_counts.get(fin, 0) + 1
                break  # count only the most specific finish per order

    dominant_material = None
    dominant_finish   = None

    if material_counts:
        top_mat, top_mat_count = max(material_counts.items(), key=lambda x: x[1])
        if top_mat_count / n >= DOMINANT_THRESHOLD:
            dominant_material = top_mat

    if finish_counts:
        top_fin, top_fin_count = max(finish_counts.items(), key=lambda x: x[1])
        if top_fin_count / n >= DOMINANT_THRESHOLD:
            dominant_finish = top_fin

    # Build a human-readable summary
    parts = []
    if dominant_material:
        mat_count = material_counts[dominant_material]
        parts.append(f"{dominant_material} ({mat_count}/{n} orders)")
    if dominant_finish:
        fin_count = finish_counts[dominant_finish]
        parts.append(f"{dominant_finish} ({fin_count}/{n} orders)")

    if parts:
        pattern_summary = " | ".join(parts)
    elif material_counts or finish_counts:
        pattern_summary = f"No dominant pattern ({n} orders)"
    else:
        pattern_summary = f"No pattern detected ({n} orders)"

    return {
        "order_count": n,
        "sparse": False,
        "dominant_material": dominant_material,
        "dominant_finish": dominant_finish,
        "material_counts": material_counts,
        "finish_counts": finish_counts,
        "pattern_summary": pattern_summary,
    }


def apply_history_boost(
    base_score: int,
    description: str,
    history_analysis: dict[str, Any],
) -> tuple[int, str]:
    """
    Apply up to +8 points per matching dominant attribute.

    Returns (personalized_score, history_signal_str).
    """
    if history_analysis["sparse"]:
        return base_score, history_analysis["pattern_summary"]

    boost = 0
    signals = []
    desc_upper = description.upper()

    dom_mat = history_analysis["dominant_material"]
    dom_fin = history_analysis["dominant_finish"]

    if dom_mat and dom_mat in desc_upper:
        boost += 8
        signals.append(f"material match ({dom_mat})")

    if dom_fin and dom_fin in desc_upper:
        boost += 8
        signals.append(f"finish match ({dom_fin})")

    personalized = min(100, base_score + boost)
    effective_boost = personalized - base_score   # actual score improvement (≤ boost due to cap)
    signal_str = history_analysis["pattern_summary"]
    if signals:
        # Show the effective boost (post-cap) so the UI "+N history boost" label matches
        # the history_signal explanation.  The raw boost (+8/+16) is implicit from the
        # attribute count shown in the pattern summary.
        signal_str += f" — +{effective_boost} for {', '.join(signals)}"

    return personalized, signal_str


# ── Claude API call ───────────────────────────────────────────────────────────

def call_claude(
    expanded_query: str,
    catalog_block: str,
    client: anthropic.Anthropic,
) -> tuple[list[dict], int, int]:
    """
    Ask Claude to rank the catalog against expanded_query.

    Returns:
      (matches_list, input_tokens, output_tokens)

    matches_list items:  {"catalog_id": str, "match_score": int, "reasoning": str}
    """
    user_message = (
        f"CATALOG:\n{catalog_block}\n\n"
        f"QUERY: {expanded_query}\n\n"
        "Return the top 10 matches as JSON."
    )

    # Retry loop — handles transient 429 rate-limit errors with backoff.
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                temperature=0,   # deterministic — same query → same ranking
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            break   # success
        except anthropic.RateLimitError as exc:
            last_exc = exc
            wait = _RETRY_BASE_SEC * (2 ** attempt)
            print(f"[matcher] Rate limit hit (attempt {attempt+1}/{_MAX_RETRIES}), "
                  f"retrying in {wait}s…")
            time.sleep(wait)
    else:
        raise last_exc  # type: ignore[misc]

    raw = response.content[0].text.strip()

    # Strip accidental markdown fences (defensive — prompt says no fences)
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = "\n".join(raw.split("\n")[:-1])

    parsed = json.loads(raw)
    matches = parsed.get("matches", [])

    input_tokens  = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    return matches, input_tokens, output_tokens


# ── Main entry point ──────────────────────────────────────────────────────────

def match(
    query: str,
    catalog: list[dict],
    catalog_index: dict[str, dict],
    order_history: list[dict],
    customer_id: str | None,
    client: anthropic.Anthropic,
) -> dict[str, Any]:
    """
    Full pipeline: expand → Claude → enrich → history boost → top-3.

    Returns the response dict that main.py forwards to the frontend.
    """
    t_start = time.monotonic()

    # ── Step 1: Abbreviation expansion ───────────────────────────────────────
    expanded_query = expand_abbreviations(query)

    # ── Step 2: Build catalog context ────────────────────────────────────────
    catalog_block = build_catalog_block(catalog)

    # ── Step 3: Claude semantic matching ─────────────────────────────────────
    try:
        claude_matches, input_tokens, output_tokens = call_claude(
            expanded_query, catalog_block, client
        )
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned non-JSON output: {e}")
    except anthropic.APIError as e:
        raise ValueError(f"Claude API error: {e}")

    tokens_used = input_tokens + output_tokens

    # ── Step 4: Enrich with catalog data ─────────────────────────────────────
    # Filter out catalog_ids Claude hallucinated (not in index)
    enriched = []
    for m in claude_matches:
        cid = m.get("catalog_id", "")
        item = catalog_index.get(cid)
        if item is None:
            continue  # Claude occasionally hallucinates IDs; skip them
        enriched.append({
            "catalog_id":   cid,
            "sku":          item["sku"],
            "description":  item["catalog_description"],
            "active":       item["active"],
            "base_score":   int(m.get("match_score", 0)),
            "reasoning":    m.get("reasoning", ""),
        })

    # ── Step 5: History analysis + boost ─────────────────────────────────────
    history_analysis: dict[str, Any] = {
        "order_count": 0,
        "sparse": True,
        "dominant_material": None,
        "dominant_finish": None,
        "pattern_summary": "No customer selected",
    }
    customer_pattern = "No customer selected"

    if customer_id:
        customer_orders = [r for r in order_history if r["customer_id"] == customer_id]
        history_analysis = analyse_customer_history(customer_orders)
        customer_pattern = history_analysis["pattern_summary"]

    results = []
    for item in enriched:
        base = item["base_score"]
        personalized, history_signal = apply_history_boost(
            base, item["description"], history_analysis
        )
        results.append({
            **item,
            "personalized_score":  personalized,
            "score_explanation":   item["reasoning"],
            "history_signal":      history_signal,
        })

    # ── Step 6: Sort + prioritise active ─────────────────────────────────────
    # Primary key: active (True first), secondary: personalized_score desc
    results.sort(key=lambda r: (not r["active"], -r["personalized_score"]))

    top3 = results[:3]

    response_time_ms = int((time.monotonic() - t_start) * 1000)

    return {
        "results": top3,
        "query_metadata": {
            "original_query":   query,
            "expanded_query":   expanded_query,
            "tokens_used":      tokens_used,
            "response_time_ms": response_time_ms,
            "customer_pattern": customer_pattern,
        },
    }
