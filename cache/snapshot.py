"""
cache/snapshot.py
==================
The materialized view of the entire inventory state.  Computed once on app
startup and refreshed every few hours by the scheduler.

All four service scripts are called here, and their combined output is
stored in a module-level dict.  The AI layer and the dashboard API both
read from this snapshot — neither queries the DB directly.

Edge cases handled:
    - DB connection fails during build → raises RuntimeError
    - One service call fails → entire build fails (partial snapshots are unsafe)
    - Snapshot never built → get_snapshot() raises RuntimeError
    - Concurrent refresh calls → protected by a threading lock
    - Empty product table → valid snapshot with zero counts

Input validations:
    - db session must not be None

Assumptions NOT made:
    - Not assuming services always succeed
    - Not assuming snapshot exists at startup
    - Not assuming single-threaded access pattern
"""

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from services.avg_daily_sales import get_avg_daily_sales, get_global_lead_time
from services.dead_inventory import get_dead_inventory
from services.reorder import get_reorder_recommendations
from services.stockout import get_all_stock_levels, get_stockout_risks

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_snapshot: Optional[Dict[str, Any]] = None
_snapshot_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_db_session(db: Session) -> None:
    """Validate that the database session is not None."""
    if db is None:
        raise ValueError("Database session (db) must not be None")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_snapshot(db: Session) -> Dict[str, Any]:
    """
    Build a complete inventory snapshot by calling all service modules.

    Execution order:
        1. get_global_lead_time() — global setting needed by steps 3 & 4
        2. get_avg_daily_sales() — foundation for steps 3 & 4
        3. get_stockout_risks() and get_all_stock_levels() — depend on avg sales + lead time
        4. get_reorder_recommendations() — depends on avg sales + lead time
        5. get_dead_inventory() — independent

    Args:
        db: Active SQLAlchemy DB session (caller-managed).

    Returns:
        A snapshot dict containing generated_at, summary, stockout_risks,
        reorder_recommendations, dead_inventory, and all_stock_levels.

    Raises:
        ValueError: If db is None.
        RuntimeError: If any service call fails.
    """
    _validate_db_session(db)

    start_time = time.monotonic()
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info("Starting snapshot build at %s …", generated_at)

    try:
        # Step 1: Global lead time (needed by stockout and reorder)
        lead_time = get_global_lead_time(db)
        logger.info("  ✓ global lead time loaded: %d days.", lead_time)

        # Step 2: Foundation — average daily sales
        avg_sales = get_avg_daily_sales(db)
        logger.info("  ✓ avg_daily_sales computed for %d products.", len(avg_sales))

        # Step 3: Stockout analysis
        stockout_risks = get_stockout_risks(db, avg_sales, lead_time)
        all_stock_levels = get_all_stock_levels(db, avg_sales, lead_time)
        logger.info(
            "  ✓ stockout analysis complete — %d risks identified.", len(stockout_risks)
        )

        # Step 4: Reorder recommendations
        reorder_recommendations = get_reorder_recommendations(db, avg_sales, lead_time)
        logger.info(
            "  ✓ reorder recommendations generated — %d items.",
            len(reorder_recommendations),
        )

        # Step 5: Dead inventory (independent)
        dead_inventory = get_dead_inventory(db)
        logger.info(
            "  ✓ dead inventory scan complete — %d items flagged.",
            len(dead_inventory),
        )

        # Assemble snapshot
        snapshot: Dict[str, Any] = {
            "generated_at": generated_at,
            "summary": {
                "total_skus": len(all_stock_levels),
                "critical_stockouts": len(stockout_risks),
                "items_to_reorder": len(reorder_recommendations),
                "dead_inventory_count": len(dead_inventory),
            },
            "stockout_risks": stockout_risks,
            "reorder_recommendations": reorder_recommendations,
            "dead_inventory": dead_inventory,
            "all_stock_levels": all_stock_levels,
        }

        elapsed = round(time.monotonic() - start_time, 2)
        logger.info("Snapshot build completed in %.2f seconds.", elapsed)

        return snapshot

    except Exception as exc:
        elapsed = round(time.monotonic() - start_time, 2)
        logger.error(
            "Snapshot build FAILED after %.2f seconds: %s", elapsed, exc, exc_info=True
        )
        raise RuntimeError(f"Snapshot build failed: {exc}") from exc


def get_snapshot() -> Dict[str, Any]:
    """
    Return the current in-memory snapshot.

    Returns:
        The most recently built snapshot dict.

    Raises:
        RuntimeError: If no snapshot has been built yet.
    """
    if _snapshot is None:
        raise RuntimeError(
            "No snapshot available. The snapshot has not been built yet. "
            "Call build_snapshot() or refresh_snapshot() first."
        )
    return _snapshot


def refresh_snapshot(db: Session) -> None:
    """
    Rebuild the snapshot and atomically replace the in-memory version.

    Thread-safe: uses a lock so that concurrent refresh calls do not
    produce a half-written snapshot.

    Args:
        db: Active SQLAlchemy DB session (caller-managed).

    Raises:
        ValueError: If db is None.
        RuntimeError: If the build fails.
    """
    global _snapshot

    _validate_db_session(db)

    logger.info("Refreshing snapshot …")

    with _snapshot_lock:
        new_snapshot = build_snapshot(db)
        _snapshot = new_snapshot

    logger.info(
        "Snapshot refreshed successfully at %s.", _snapshot["generated_at"]
    )
