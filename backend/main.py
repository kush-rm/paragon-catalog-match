"""
FastAPI backend for Paragon Catalog Match.

Single endpoint: POST /api/match
Also exposes:  GET  /api/customers  — list for the dropdown
               GET  /api/health     — liveness check
"""

import os
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
from pydantic import BaseModel

from data_loader import (
    build_catalog_index,
    build_customer_list,
    load_catalog,
    load_order_history,
)
from matcher import match


# ── App state (loaded once at startup) ───────────────────────────────────────

class AppState:
    catalog:        list[dict]
    catalog_index:  dict[str, dict]
    order_history:  list[dict]
    customers:      list[dict]
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


# ── Endpoints ─────────────────────────────────────────────────────────────────

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
