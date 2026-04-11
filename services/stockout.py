"""
services/stockout.py
=====================
Calculate days of stock remaining per product and flag stockout risks.

Real schema usage:
    - Current stock: SUM(quantity) FROM warehouse_product_management
      GROUP BY product_id (summed across all warehouses)
    - Product PK is product.id (NOT product_id)
    - Lead time is a global int passed in from avg_daily_sales.get_global_lead_time()

Edge cases handled:
    - Product not in warehouse_product_management → stock = 0
    - avg_daily_sales = 0 → days_left = inf (stock never depletes)
    - current_stock = 0 → days_left = 0.0
    - Both zero → days_left = 0.0 (no stock beats infinite horizon)
    - Negative stock → clamped to 0
    - Product has NULL name → "Unknown"
    - avg_sales dict is empty → every product gets 0.0 avg

Input validations:
    - db session must not be None
    - avg_sales must be a dict
    - lead_time must be a non-negative int

Assumptions NOT made:
    - Not assuming every product has warehouse records
    - Not assuming avg_sales dict contains all product IDs
    - Not assuming stock values are never negative
    - Not assuming lead_time is always positive
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Product, WarehouseProductManagement

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_db_session(db: Session) -> None:
    """Validate that the database session is not None."""
    if db is None:
        raise ValueError("Database session (db) must not be None")


def _validate_avg_sales(avg_sales: Dict[int, float]) -> None:
    """Validate that avg_sales is a non-None dictionary."""
    if avg_sales is None:
        raise TypeError("avg_sales must not be None")
    if not isinstance(avg_sales, dict):
        raise TypeError(f"avg_sales must be a dict, got {type(avg_sales).__name__}")


def _validate_lead_time(lead_time: int) -> None:
    """Validate that lead_time is a non-negative integer."""
    if not isinstance(lead_time, int):
        raise TypeError(f"lead_time must be an int, got {type(lead_time).__name__}")
    if lead_time < 0:
        raise ValueError(f"lead_time must be non-negative, got {lead_time}")


# ---------------------------------------------------------------------------
# Stock query
# ---------------------------------------------------------------------------

def get_current_stock_all(db: Session) -> Dict[int, float]:
    """
    Get total current stock per product across all warehouses.

    Query:
        SELECT product_id, SUM(quantity)
        FROM warehouse_product_management
        GROUP BY product_id

    Args:
        db: Active SQLAlchemy DB session (caller-managed).

    Returns:
        Dict mapping product_id → total stock (float).
        Products not in this table are absent from the dict.

    Raises:
        ValueError: If db is None.
        RuntimeError: If the DB query fails.
    """
    _validate_db_session(db)

    try:
        rows = (
            db.query(
                WarehouseProductManagement.product_id,
                func.coalesce(
                    func.sum(WarehouseProductManagement.quantity), 0
                ).label("total_stock"),
            )
            .group_by(WarehouseProductManagement.product_id)
            .all()
        )

        stock_map: Dict[int, float] = {
            row[0]: float(row[1]) for row in rows if row[0] is not None
        }

        logger.info("Loaded current stock for %d products.", len(stock_map))
        return stock_map

    except ValueError:
        raise
    except Exception as exc:
        logger.error("Failed to load current stock: %s", exc, exc_info=True)
        raise RuntimeError(f"Failed to load current stock: {exc}") from exc


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def calculate_days_left(current_stock: float, avg_daily_sales: float) -> Optional[float]:
    """
    Calculate how many days of stock remain at the current sales rate.

    Formula: Days Left = Current Stock / Avg Daily Sales

    Args:
        current_stock: Current quantity on hand. Clamped to 0 if negative.
        avg_daily_sales: Average units sold per day. Must be >= 0.

    Returns:
        - 0.0 if current_stock <= 0 (no stock on hand)
        - None if avg_daily_sales <= 0 and stock > 0 (stock exists but no sales —
          no depletion expected; None is JSON-safe and displayed as "∞")
        - Positive float otherwise (rounded to 2 decimal places)

    Raises:
        ValueError: If avg_daily_sales is negative.
    """
    if current_stock is None:
        current_stock = 0.0
    if avg_daily_sales is None:
        avg_daily_sales = 0.0

    current_stock = float(current_stock)
    avg_daily_sales = float(avg_daily_sales)

    if avg_daily_sales < 0:
        raise ValueError(
            f"avg_daily_sales must be non-negative, got {avg_daily_sales}"
        )

    # No stock on hand — zero days regardless of sales rate
    if current_stock <= 0:
        return 0.0

    # Stock exists but no sales history — no depletion expected
    if avg_daily_sales <= 0:
        return None

    return round(current_stock / avg_daily_sales, 2)


# ---------------------------------------------------------------------------
# Internal helper: build product-level records
# ---------------------------------------------------------------------------

def _build_stock_records(
    db: Session,
    avg_sales: Dict[int, float],
    lead_time: int,
) -> List[Dict[str, Any]]:
    """
    Build a list of stock-level dicts for every product.

    Args:
        db: Active SQLAlchemy DB session.
        avg_sales: Dict mapping product_id → avg daily sales.
        lead_time: Global lead time in days.

    Returns:
        List of dicts with full product stock detail.
    """
    # Fetch all products
    products = db.query(Product.id, Product.name, Product.SKU).filter(Product.status == 1).all()

    if not products:
        logger.warning("No products found in the product table.")
        return []

    # Fetch current stock
    stock_map = get_current_stock_all(db)

    records: List[Dict[str, Any]] = []
    for pid, name, sku in products:
        avg = avg_sales.get(pid, 0.0)
        stock = stock_map.get(pid, 0.0)
        days_left = calculate_days_left(stock, avg)

        # days_left is None when stock > 0 but avg = 0 (no depletion).
        # None means "not at risk" — stock won't run out if nothing is selling.
        is_risk = days_left is not None and days_left <= lead_time

        records.append(
            {
                "product_id": pid,
                "product_name": name or "Unknown",
                "sku": sku or "",
                "current_stock": stock,
                "avg_daily_sales": avg,
                "days_left": days_left,
                "lead_time_days": lead_time,
                "is_stockout_risk": is_risk,
            }
        )

    return records


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_stockout_risks(
    db: Session,
    avg_sales: Dict[int, float],
    lead_time: int,
) -> List[Dict[str, Any]]:
    """
    Identify products at risk of stockout.

    A product is at risk when its remaining days of stock (days_left)
    is less than or equal to the global lead time.

    Args:
        db: Active SQLAlchemy DB session (caller-managed).
        avg_sales: Dict mapping product_id → avg daily sales.
        lead_time: Global lead time in days (from get_global_lead_time).

    Returns:
        List of dicts — one per at-risk product — sorted by days_left
        ascending (most urgent first).

    Raises:
        ValueError: If db is None or lead_time < 0.
        TypeError: If avg_sales is not a dict.
        RuntimeError: If the DB query fails.
    """
    _validate_db_session(db)
    _validate_avg_sales(avg_sales)
    _validate_lead_time(lead_time)

    try:
        records = _build_stock_records(db, avg_sales, lead_time)

        risks = [r for r in records if r["is_stockout_risk"]]

        # Sort by urgency — fewest days left first.
        # days_left is never None for stockout risks (None means no depletion → not a risk).
        risks.sort(key=lambda r: r["days_left"] if r["days_left"] is not None else float("inf"))

        logger.info(
            "Identified %d stockout risks out of %d products.",
            len(risks), len(records),
        )
        return risks

    except (TypeError, ValueError):
        raise
    except Exception as exc:
        logger.error("Failed to compute stockout risks: %s", exc, exc_info=True)
        raise RuntimeError(f"Failed to compute stockout risks: {exc}") from exc


def get_all_stock_levels(
    db: Session,
    avg_sales: Dict[int, float],
    lead_time: int,
) -> List[Dict[str, Any]]:
    """
    Return stock-level details for ALL products (not just at-risk ones).

    Used for the full inventory summary on the dashboard.

    Args:
        db: Active SQLAlchemy DB session (caller-managed).
        avg_sales: Dict mapping product_id → avg daily sales.
        lead_time: Global lead time in days.

    Returns:
        List of dicts — one per product — sorted by days_left ascending.

    Raises:
        ValueError: If db is None or lead_time < 0.
        TypeError: If avg_sales is not a dict.
        RuntimeError: If the DB query fails.
    """
    _validate_db_session(db)
    _validate_avg_sales(avg_sales)
    _validate_lead_time(lead_time)

    try:
        records = _build_stock_records(db, avg_sales, lead_time)

        # Sort by days_left ascending — most urgent first.
        # None (no depletion) goes to the end.
        records.sort(key=lambda r: r["days_left"] if r["days_left"] is not None else float("inf"))

        logger.info("Computed stock levels for %d products.", len(records))
        return records

    except (TypeError, ValueError):
        raise
    except Exception as exc:
        logger.error("Failed to compute stock levels: %s", exc, exc_info=True)
        raise RuntimeError(f"Failed to compute stock levels: {exc}") from exc
