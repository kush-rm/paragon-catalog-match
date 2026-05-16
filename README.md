# Paragon Catalog Match

A single-page web app that matches free-form natural-language product descriptions against a 1,000-row industrial fastener catalog, powered by the Claude API for semantic understanding.

Built for the Paragon AI take-home assessment.

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- An Anthropic API key

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...

uvicorn main:app --reload
# → API running at http://localhost:8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# → UI running at http://localhost:5173
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Matching Approach

### Why Claude API instead of keyword search or TF-IDF?

Fastener catalogs are written by many people over many years. The same product appears as:
- `SHCS 7/16-14 X 2-1/2 STEEL ZINC`
- `socket head cap screw 7/16 x 2.5" zinc plated`
- `SOC HEAD 7/16 ZC`

TF-IDF fails here because it scores on term frequency — it doesn't know that `SHCS` and `socket head cap screw` are the same thing, or that `ZC` and `zinc` refer to the same finish.

A rules-based expander could handle *known* abbreviations, but it can't handle:
- Informal synonyms ("zinc plated" vs "zinc")
- Transposed word order ("zinc 7/16 socket")
- Partial descriptions that need inference ("M8 bolt" → likely SOCKET HEAD CAP SCREW given context)

Claude understands fastener terminology semantically. It knows what a "button head" is, can infer that an unspecified material query probably means steel, and handles abbreviation variants it has never been explicitly taught.

### Why pass the full catalog in context instead of using retrieval (embeddings + vector search)?

At ~955 active rows, the full catalog is ~60 KB of text — it fits comfortably in Claude's 200K-token context window. Single-pass reasoning is:

1. **More reliable**: if a retriever returns wrong candidates, Claude reasons over wrong data with high confidence and you get a plausible-sounding but wrong answer. With the full catalog, Claude always has access to the correct answer.
2. **More debuggable**: every run uses identical context, so differences in output are attributable to the query, not to retrieval variation.
3. **Simpler**: no embedding model, no vector database, no chunking strategy.

**Threshold to switch**: ~5,000+ active SKUs, at which point the catalog would exceed the context window. At that scale, embed the catalog, retrieve the top-50 candidates, then pass those 50 to Claude for final ranking.

### Pipeline

```
User query
    │
    ▼
expand_abbreviations()          ← deterministic Python (policy in code)
    │  SHCS → SOCKET HEAD CAP SCREW
    │  ZC   → ZINC
    │  FT   → FULL THREAD
    │
    ▼
Claude API (claude-sonnet-4-20250514)
    │  Full active catalog in context
    │  temperature=0  ← deterministic
    │  Returns top-10 matches with scores
    │
    ▼
Enrich from catalog index       ← join back to get SKU, active status
    │
    ▼
apply_history_boost()           ← if customer_id provided
    │
    ▼
Sort: active first, then by personalized_score desc
    │
    ▼
Return top 3
```

---

## Confidence Score

### What it means

The `base_score` (0–100) is Claude's assessment of how well a catalog entry matches the user's query. It measures alignment across:
- **Size/thread** (e.g. M8-1.25, 3/8-16)
- **Type** (socket head cap screw, hex nut, flat washer…)
- **Material** (steel, brass, alloy, 18-8 SS…)
- **Finish** (zinc, black oxide, yellow zinc…)

### Score bands

| Range | Meaning | Example |
|-------|---------|---------|
| 90–100 | Near-certain match — size, type, material, finish all agree | Query: "M8 socket head cap screw steel zinc", Result: "M8-1.25 X 30MM SOCKET HEAD CAP SCR STEEL ZINC" |
| 70–89 | Good match — one attribute unspecified or inferred | Query: "M8 socket head cap screw", Result: matches size + type but material not specified |
| 50–69 | Possible match — significant ambiguity | Query: "M8 bolt", multiple bolt types and materials qualify |
| < 50 | Weak match — included only if nothing better exists | Query mentions a brand or standard not in the catalog |

### Why these bands?

The bands mirror how a sales rep would think about a match: "I'm certain" vs "I'm pretty sure" vs "could be" vs "last resort". A score of 72 should never be shown to a customer as "highly confident" — the yellow colour signals genuine ambiguity.

### Colour coding in the UI

- Green (85+): safe to order
- Yellow (65–84): confirm with customer before ordering
- Orange (50–64): needs clarification
- Red (<50): do not order without confirmation

---

## History Re-ranking

### What signal is extracted

For each customer, we scan their `order_history` and count material and finish keywords in the catalog descriptions of items they've ordered:

**Materials checked**: STEEL, BRASS, ALLOY, 18-8 SS, 316 SS, A2 SS, STAINLESS STEEL  
**Finishes checked**: ZINC, BLACK OXIDE, HOT DIP GALVANIZED, PLAIN, YELLOW ZINC, MECHANICAL ZINC, HDG

We use longest-match-first to avoid counting "STEEL" inside "STAINLESS STEEL" incorrectly.

### How the boost is applied

If a material or finish appears in **>60%** of a customer's past orders, it's called the "dominant" preference.

```
personalized_score = base_score
  + 8 if description contains dominant_material
  + 8 if description contains dominant_finish
  (capped at 100)
```

Both `base_score` and `personalized_score` are shown in the UI so the rep can see whether the ranking is driven by description match or purchase history.

### Why 60% as the threshold?

Below 60%, the signal is too noisy to act on reliably. Consider CUST-005 (6 orders, 4 different material/finish combinations): no single pattern dominates, so boosting on any one material would be a guess, not a signal. The threshold is conservative by design — false certainty is worse than no certainty.

### Sparse history

If a customer has **fewer than 3 orders**, no boost is applied. The UI displays:
> "Sparse history — using description match only (N orders)"

This applies to CUST-005 (Summit General Maintenance, 6 orders but mixed patterns). Rather than fake a pattern, we surface the ambiguity.

---

## Customer Patterns (from the data)

| Customer | Pattern | Signal |
|----------|---------|--------|
| CUST-001 Midwest Industrial Supply | STEEL + ZINC | Dominant in 16/18 orders |
| CUST-002 CleanRoom Pharma MFG | 18-8 SS + PLAIN | Dominant in 15/16 orders |
| CUST-003 Marine Electrical Corp | BRASS + MECH ZINC | Brass dominant, finish mixed |
| CUST-004 Heavy Machinery Solutions | ALLOY + BLACK OXIDE | Dominant in 17/18 orders |
| CUST-005 Summit General Maintenance | Mixed | Sparse — no boost applied |

---

## Edge Cases Considered

**Abbreviation queries** — expanded before Claude sees the query, so `SHCS 7/16` and `socket head cap screw 7/16` produce identical reasoning from Claude.

**Under-specified queries** — "M8 bolt" legitimately matches many entries. Claude assigns 65–75 scores reflecting genuine ambiguity. We don't force a high-confidence answer.

**Impossible/nonsensical queries** — "purple titanium M8 bolt" will get low scores (<50) for everything because the catalog has no titanium. We show weak matches rather than hiding results.

**Vague history queries** ("same washers as last time") — the UI detects these phrases and nudges the user to select a customer when no customer is chosen.

**Inactive products** — excluded from Claude's reasoning context (so they never rank high). If a customer has no active matches, we'd surface inactive ones; currently all queries return active results first. Inactive results get an `⚠ INACTIVE` badge in amber.

**Metric vs imperial** — Claude understands both natively. "M8" and "M8-1.25" and "8mm" all map to the same thread. The abbreviation expander normalises "6FT" format so "6 foot rod" finds "6FT FULL THREAD ROD".

**Mixed case** — all queries are uppercased before processing. Catalog descriptions are passed as-is (mixed case) because Claude handles them correctly.

---

## Known Limitations

1. **Latency**: passing ~955 catalog rows to Claude takes 1.5–3s per query. For production, pre-embedding the catalog and doing retrieval first would cut this to ~200ms.

2. **Token cost**: each query uses ~15,000–18,000 input tokens (the full catalog). At current pricing this is ~$0.04–0.05 per query. Acceptable for a low-volume internal tool; would need caching or retrieval for high-volume use.

3. **History signal is order-level, not quantity-weighted**: CUST-001 ordering 3,000 flat washers and 50 rods both count as 1 order each. Weighting by quantity would give a stronger signal.

4. **No caching**: identical queries always call the Claude API. Adding a Redis cache keyed on `(expanded_query, customer_id)` would eliminate repeat costs.

5. **Customer pattern is binary per attribute**: we detect one dominant material and one dominant finish. A customer who orders 50% STEEL ZINC and 50% STEEL BLACK OXIDE has no dominant finish but a clear STEEL preference — the current logic handles material correctly but misses the partial finish signal.

6. **No streaming**: the UI shows a spinner for the full duration. Streaming the Claude response would let us show results as they arrive.

---

## Design Decisions for the Technical Review

| Decision | Rationale |
|----------|-----------|
| `temperature=0` | Deterministic matching — same query always returns same results. Essential for calibration and debugging. |
| Full catalog in context | Avoids silent retrieval failures; simpler to debug; fits in 200K window. |
| Abbreviation expansion before Claude | "Policy in code" — don't trust the LLM to catch every abbreviation every time. Deterministic expansion is fast and testable. |
| Show both `base_score` and `personalized_score` | Transparency: the rep should understand *why* a result ranked — description match or purchase history are different trust levels. |
| 60% threshold for dominant pattern | Conservative by design. Below 60%, boosting any material is a guess not a signal. |
| Active catalog only passed to Claude | Inactive items never compete for top slots. They're surfaced only via the enrichment step and always ranked below active matches. |
