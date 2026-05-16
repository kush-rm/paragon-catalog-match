"""
Loads catalog.csv and order_history.csv at application startup.

Both files live two directories up from this file (project root).
Paths are resolved relative to this file so the app works regardless
of the working directory from which uvicorn is launched.
"""

import csv
import os
from pathlib import Path
from typing import Any

# Resolve data directory: backend/ → project root → data files
_HERE = Path(__file__).parent
DATA_DIR = _HERE.parent.parent  # …/PARAGON AI- ASSESS/


def _csv_path(filename: str) -> Path:
    p = DATA_DIR / filename
    if not p.exists():
        raise FileNotFoundError(
            f"Data file not found: {p}\n"
            f"Expected location: {DATA_DIR}"
        )
    return p


# ── Catalog ──────────────────────────────────────────────────────────────────

def load_catalog() -> list[dict[str, Any]]:
    """
    Returns a list of dicts with keys:
        catalog_id, sku, catalog_description, active (bool)
    """
    rows = []
    with open(_csv_path("catalog.csv"), newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "catalog_id":          row["catalog_id"].strip(),
                "sku":                 row["sku"].strip(),
                "catalog_description": row["catalog_description"].strip(),
                "active":              row["active"].strip().upper() == "Y",
            })
    return rows


def build_catalog_index(catalog: list[dict]) -> dict[str, dict]:
    """Return a dict keyed by catalog_id for O(1) lookup."""
    return {item["catalog_id"]: item for item in catalog}


# ── Order History ─────────────────────────────────────────────────────────────

def load_order_history() -> list[dict[str, Any]]:
    """
    Returns a list of dicts with keys:
        customer_id, customer_name, order_date, sku,
        catalog_description, quantity (int)
    """
    rows = []
    with open(_csv_path("order_history.csv"), newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "customer_id":         row["customer_id"].strip(),
                "customer_name":       row["customer_name"].strip(),
                "order_date":          row["order_date"].strip(),
                "sku":                 row["sku"].strip(),
                "catalog_description": row["catalog_description"].strip(),
                "quantity":            int(row["quantity"].strip()),
            })
    return rows


def build_customer_list(order_history: list[dict]) -> list[dict]:
    """
    Return a deduplicated list of customers sorted by customer_id:
        [{"customer_id": "CUST-001", "customer_name": "Midwest Industrial Supply"}, …]
    """
    seen = {}
    for row in order_history:
        cid = row["customer_id"]
        if cid not in seen:
            seen[cid] = row["customer_name"]
    return [
        {"customer_id": k, "customer_name": v}
        for k, v in sorted(seen.items())
    ]


def get_customer_orders(order_history: list[dict], customer_id: str) -> list[dict]:
    """Filter order history to a single customer."""
    return [r for r in order_history if r["customer_id"] == customer_id]
