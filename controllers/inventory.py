"""
controllers/inventory.py
=====================
FastAPI router exposing inventory data endpoints.  All endpoints read from
the in-memory snapshot — no direct DB calls in router functions.

Edge cases handled:
    - Snapshot not built yet → returns 503 Service Unavailable
    - Snapshot refresh fails → returns 500 with descriptive message
    - Empty lists in snapshot → returns empty arrays (valid response)
    - Missing keys in snapshot → handled with .get() and defaults

Input validations:
    - All endpoints validate snapshot availability before returning data
    - POST /refresh-snapshot validates that the DB dependency is available

Assumptions NOT made:
    - Not assuming snapshot is always available
    - Not assuming refresh always succeeds
    - Not assuming the snapshot dict has every key
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from rag.context_builder import refresh_context
from cache.snapshot import get_snapshot, refresh_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inventory", tags=["Inventory"])


# ---------------------------------------------------------------------------
# DB session dependency — must be provided by the main application
# ---------------------------------------------------------------------------

def _get_db():
    """
    Database session dependency placeholder.

    This must be overridden by the main application when including this
    router.  It should yield a SQLAlchemy Session.

    Raises:
        NotImplementedError: Always — must be overridden.
    """
    raise NotImplementedError(
        "Database session dependency not configured. "
        "Override this when mounting the router."
    )


# Store a reference that can be replaced by the application at startup
get_db = _get_db


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _safe_get_snapshot() -> Dict[str, Any]:
    """
    Retrieve the current snapshot, raising a 503 if unavailable.

    Returns:
        The current inventory snapshot dict.

    Raises:
        HTTPException: 503 if no snapshot has been built yet.
    """
    try:
        return get_snapshot()
    except RuntimeError as exc:
        logger.warning("Snapshot not available: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Inventory snapshot is not available yet. Please try again later.",
        ) from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/stockout-alerts", response_model=List[Dict[str, Any]])
async def get_stockout_alerts() -> List[Dict[str, Any]]:
    """
    Return all products currently at risk of stockout.

    These are products where days_left ≤ lead_time.
    """
    snapshot = _safe_get_snapshot()
    return snapshot.get("stockout_risks", [])


@router.get("/reorder-recommendations", response_model=List[Dict[str, Any]])
async def get_reorder_recommendations() -> List[Dict[str, Any]]:
    """
    Return products that need reorder with recommended quantities.

    Only includes products where current_stock ≤ reorder_point.
    """
    snapshot = _safe_get_snapshot()
    return snapshot.get("reorder_recommendations", [])


@router.get("/dead-inventory", response_model=List[Dict[str, Any]])
async def get_dead_inventory() -> List[Dict[str, Any]]:
    """
    Return products flagged as dead or slow-moving inventory.

    A product is dead if it hasn't been sold in 60+ consecutive days
    or has never been sold.
    """
    snapshot = _safe_get_snapshot()
    return snapshot.get("dead_inventory", [])


@router.get("/summary", response_model=Dict[str, Any])
async def get_summary() -> Dict[str, Any]:
    """
    Return the high-level inventory summary with key counts.

    Includes: total_skus, critical_stockouts, items_to_reorder,
    dead_inventory_count.
    """
    snapshot = _safe_get_snapshot()
    return snapshot.get("summary", {})


@router.get("/all-stock-levels", response_model=List[Dict[str, Any]])
async def get_all_stock_levels() -> List[Dict[str, Any]]:
    """
    Return stock-level data for ALL products.

    Used for the full dashboard view — includes every SKU with its
    current stock, avg daily sales, days left, and risk status.
    """
    snapshot = _safe_get_snapshot()
    return snapshot.get("all_stock_levels", [])


@router.post("/refresh-snapshot", response_model=Dict[str, Any])
async def trigger_refresh_snapshot(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Manually trigger a snapshot refresh.

    Rebuilds the entire snapshot from the database, replaces the in-memory
    version, and refreshes the AI context string.

    Returns:
        Confirmation dict with the new snapshot timestamp.
    """
    try:
        refresh_snapshot(db)

        # Also refresh the context for the AI layer
        snapshot = get_snapshot()
        refresh_context(snapshot)

        logger.info("Manual snapshot refresh completed successfully.")

        return {
            "status": "success",
            "message": "Snapshot refreshed successfully.",
            "generated_at": snapshot.get("generated_at", "unknown"),
        }

    except Exception as exc:
        logger.error("Manual snapshot refresh failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Snapshot refresh failed: {exc}",
        ) from exc
