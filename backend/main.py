"""
FastAPI backend for Paragon Catalog Match.

Endpoints:
  POST /api/match            — semantic catalog search
  GET  /api/customers        — customer list for the dropdown
  GET  /api/health           — liveness check
  GET  /api/benchmark/queries  — returns the 33 example query strings
  GET  /api/benchmark/cache    — returns cached benchmark results (if any)
  GET  /api/benchmark/stream   — SSE stream: runs all 33 queries live
  DELETE /api/benchmark/cache  — clears cached results so next stream re-runs
"""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

# Load .env from the backend directory (if present) so developers can set
# ANTHROPIC_API_KEY without exporting it globally.
load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from benchmark import (
    BENCHMARK_QUERIES,
    compute_stats,
    load_cache,
    run_single_query,
    save_cache,
)
from data_loader import (
    build_catalog_index,
    build_customer_list,
    load_catalog,
    load_order_history,
)
from matcher import match


# ── App state (loaded once at startup) ───────────────────────────────────────

class AppState:
    catalog:          list[dict]
    catalog_index:    dict[str, dict]
    order_history:    list[dict]
    customers:        list[dict]
    anthropic_client: anthropic.Anthropic


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load data and initialise the Anthropic client on startup."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set.\n"
            "Copy backend/.env.example → backend/.env and fill in your key,\n"
            "or export ANTHROPIC_API_KEY=<your-key> before running."
        )

    state.anthropic_client = anthropic.Anthropic(api_key=api_key)
    state.catalog           = load_catalog()
    state.catalog_index     = build_catalog_index(state.catalog)
    state.order_history     = load_order_history()
    state.customers         = build_customer_list(state.order_history)

    print(f"✅ Loaded {len(state.catalog)} catalog items "
          f"({sum(1 for c in state.catalog if c['active'])} active)")
    print(f"✅ Loaded {len(state.order_history)} order lines "
          f"for {len(state.customers)} customers")
    yield


app = FastAPI(
    title="Paragon Catalog Match API",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow the Vite dev server (port 5173) and any localhost origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response schemas ────────────────────────────────────────────────

class MatchRequest(BaseModel):
    query:       str
    customer_id: str | None = None


class MatchResult(BaseModel):
    catalog_id:         str
    sku:                str
    description:        str
    active:             bool
    base_score:         int
    personalized_score: int
    score_explanation:  str
    history_signal:     str


class QueryMetadata(BaseModel):
    original_query:   str
    expanded_query:   str
    tokens_used:      int
    response_time_ms: int
    customer_pattern: str


class MatchResponse(BaseModel):
    results:        list[MatchResult]
    query_metadata: QueryMetadata


# ── Standard endpoints ────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "catalog_size": len(state.catalog)}


@app.get("/api/customers")
def list_customers() -> list[dict[str, Any]]:
    """Return all customers for the frontend dropdown."""
    return state.customers


@app.post("/api/match", response_model=MatchResponse)
def match_endpoint(req: MatchRequest) -> dict[str, Any]:
    """
    Match a free-form query against the fastener catalog.
    Optional customer_id triggers history-based re-ranking.
    """
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty.")

    try:
        result = match(
            query=req.query.strip(),
            catalog=state.catalog,
            catalog_index=state.catalog_index,
            order_history=state.order_history,
            customer_id=req.customer_id,
            client=state.anthropic_client,
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")

    return result


# ── Benchmark endpoints ───────────────────────────────────────────────────────

@app.get("/api/benchmark/queries")
def benchmark_queries() -> list[str]:
    """Return the 33 example query strings."""
    return BENCHMARK_QUERIES


@app.get("/api/benchmark/cache")
def benchmark_cache_get() -> dict[str, Any]:
    """Return cached benchmark results (empty dict if none yet)."""
    return load_cache()


@app.delete("/api/benchmark/cache")
def benchmark_cache_delete() -> dict[str, str]:
    """Clear the on-disk benchmark cache so the next stream re-runs everything."""
    from benchmark import CACHE_PATH
    if CACHE_PATH.exists():
        CACHE_PATH.unlink()
    return {"status": "cleared"}


@app.get("/api/benchmark/stream")
async def benchmark_stream():
    """
    Server-Sent Events stream that runs all 33 queries sequentially.

    Events emitted:
      {"type": "start",    "total": 33}
      {"type": "progress", "index": 0,  "query": "...", "result": {...}}
      {"type": "done",     "stats": {...}, "results": [...]}
      {"type": "error",    "index": 0,  "query": "...", "message": "..."}

    Cached queries are re-emitted instantly without an API call.
    Rate-limit retries are handled inside run_single_query (backoff in matcher.py).
    """
    loop = asyncio.get_event_loop()

    async def event_gen():
        # Check cache — resume from where we left off
        cache = load_cache()
        cached_results: list[dict] = cache.get("results", [])
        cached_queries = {r["query"] for r in cached_results}

        yield f"data: {json.dumps({'type': 'start', 'total': len(BENCHMARK_QUERIES), 'cached': len(cached_queries)})}\n\n"
        await asyncio.sleep(0)   # flush

        all_results: list[dict] = list(cached_results)

        for idx, query in enumerate(BENCHMARK_QUERIES):
            # Serve from cache instantly
            if query in cached_queries:
                cached_row = next(r for r in cached_results if r["query"] == query)
                payload = json.dumps({
                    "type":    "progress",
                    "index":   idx,
                    "query":   query,
                    "cached":  True,
                    "result":  cached_row,
                })
                yield f"data: {payload}\n\n"
                await asyncio.sleep(0)
                continue

            # Run live in thread pool (blocking I/O off the async loop)
            try:
                row = await loop.run_in_executor(
                    None,
                    run_single_query,
                    query,
                    state.catalog,
                    state.catalog_index,
                    state.order_history,
                    state.anthropic_client,
                )
                all_results.append(row)
                save_cache({"results": all_results, "stats": compute_stats(all_results)})

                payload = json.dumps({
                    "type":   "progress",
                    "index":  idx,
                    "query":  query,
                    "cached": False,
                    "result": row,
                })
                yield f"data: {payload}\n\n"

            except Exception as exc:
                err_row = {
                    "query":   query,
                    "error":   str(exc),
                    "category": "Other",
                }
                payload = json.dumps({
                    "type":    "error",
                    "index":   idx,
                    "query":   query,
                    "message": str(exc),
                })
                yield f"data: {payload}\n\n"

            await asyncio.sleep(0)   # yield control between queries

        stats = compute_stats(all_results)
        save_cache({"results": all_results, "stats": stats})
        yield f"data: {json.dumps({'type': 'done', 'stats': stats, 'results': all_results})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
