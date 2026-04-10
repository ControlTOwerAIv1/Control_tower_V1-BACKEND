"""
services/reorder.py
====================
Calculate reorder point and recommended reorder quantity per product.

Real schema usage:
    - Current stock: SUM(quantity) FROM warehouse_product_management
      GROUP BY product_id (via stockout.get_current_stock_all)
    - Product PK is product.id
    - Lead time is a global int passed in from avg_daily_sales.get_global_lead_time()

Formulas:
    Reorder Point    = Avg Daily Sales × Lead Time
    Reorder Quantity = (Avg Daily Sales × (Lead Time + Buffer Days)) − Current Stock

Edge cases handled:
    - avg_daily_sales = 0 → reorder_point = 0, reorder_qty = 0
    - lead_time = 0 → reorder_point = 0 (instant replenishment)
    - Reorder quantity negative (overstocked) → clamped to 0.0
    - buffer_days < 0 → raises ValueError
    - Product not in warehouse → current_stock = 0
    - Product not in avg_sales dict → avg = 0.0

Input validations:
    - avg_daily_sales, lead_time, current_stock must be non-negative
    - buffer_days must be >= 0 (0 means no buffer)
    - db session must not be None
    - avg_sales must be a dict

Assumptions NOT made:
    - Not assuming every product requires reorder
    - Not assuming buffer_days is always 7
    - Not assuming lead_time is always > 0
    - Not assuming all products have warehouse records
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import Product
from services.stockout import get_current_stock_all

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


def _validate_non_negative(value: Optional[float], name: str) -> float:
    """
    Ensure a numeric value is non-negative (None → 0.0).

    Args:
        value: The value to validate.
        name: Parameter name for error messages.

    Returns:
        The validated float.

    Raises:
        ValueError: If value is negative.
    """
    if value is None:
        return 0.0
    value = float(value)
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}")
    return value


def _validate_buffer_days(buffer_days: int) -> None:
    """
    Validate that buffer_days is a non-negative integer.

    Args:
        buffer_days: Number of extra buffer days.

    Raises:
        TypeError: If buffer_days is not an integer.
        ValueError: If buffer_days is negative.
    """
    if not isinstance(buffer_days, int):
        raise TypeError(
            f"buffer_days must be an integer, got {type(buffer_days).__name__}"
        )
    if buffer_days < 0:
        raise ValueError(f"buffer_days must be non-negative, got {buffer_days}")


def _validate_lead_time(lead_time: int) -> None:
    """Validate that lead_time is a non-negative integer."""
    if not isinstance(lead_time, int):
        raise TypeError(f"lead_time must be an int, got {type(lead_time).__name__}")
    if lead_time < 0:
        raise ValueError(f"lead_time must be non-negative, got {lead_time}")


# ---------------------------------------------------------------------------
# Core calculations
# ---------------------------------------------------------------------------

def calculate_reorder_point(avg_daily_sales: float, lead_time: int) -> float:
    """
    Calculate the reorder point for a product.

    Formula: Reorder Point = Avg Daily Sales × Lead Time

    Args:
        avg_daily_sales: Average units sold per day. Must be >= 0.
        lead_time: Global lead time in days. Must be >= 0.

    Returns:
        Reorder point as a float, rounded to 2 decimal places.
        Returns 0.0 if either input is 0.

    Raises:
        ValueError: If either input is negative.
    """
    avg_daily_sales = _validate_non_negative(avg_daily_sales, "avg_daily_sales")
    lead_time_f = _validate_non_negative(float(lead_time), "lead_time")

    if avg_daily_sales == 0 or lead_time_f == 0:
        return 0.0

    return round(avg_daily_sales * lead_time_f, 2)


def calculate_reorder_quantity(
    avg_daily_sales: float,
    lead_time: int,
    current_stock: float,
    buffer_days: int = 7,
) -> float:
    """
    Calculate the recommended reorder quantity.

    Formula:
        Reorder Qty = (Avg Daily Sales × (Lead Time + Buffer Days)) − Current Stock

    If the result is negative or zero (already overstocked), returns 0.0.

    Args:
        avg_daily_sales: Average units sold per day. Must be >= 0.
        lead_time: Global lead time in days. Must be >= 0.
        current_stock: Current inventory on hand. Must be >= 0.
        buffer_days: Extra safety-stock days. Must be >= 0. Default 7.

    Returns:
        Recommended quantity to order, rounded to 2 decimal places.
        Minimum 0.0 (never negative).

    Raises:
        TypeError: If buffer_days is not an integer.
        ValueError: If any numeric input is negative.
    """
    avg_daily_sales = _validate_non_negative(avg_daily_sales, "avg_daily_sales")
    lead_time_f = _validate_non_negative(float(lead_time), "lead_time")
    current_stock = _validate_non_negative(current_stock, "current_stock")
    _validate_buffer_days(buffer_days)

    target_stock = avg_daily_sales * (lead_time_f + buffer_days)
    reorder_qty = target_stock - current_stock

    return round(max(reorder_qty, 0.0), 2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_reorder_recommendations(
    db: Session,
    avg_sales: Dict[int, float],
    lead_time: int,
    buffer_days: int = 7,
) -> List[Dict[str, Any]]:
    """
    Generate reorder recommendations for products where current stock
    is at or below the reorder point.

    Args:
        db: Active SQLAlchemy DB session (caller-managed).
        avg_sales: Dict mapping product_id → avg daily sales.
        lead_time: Global lead time in days (from get_global_lead_time).
        buffer_days: Safety-stock buffer in days. Default 7.

    Returns:
        List of dicts — one per product needing reorder — sorted by
        reorder_quantity descending (largest order first).

    Raises:
        ValueError: If db is None or lead_time/buffer_days invalid.
        TypeError: If avg_sales is not a dict.
        RuntimeError: If the DB query fails.
    """
    _validate_db_session(db)
    _validate_avg_sales(avg_sales)
    _validate_lead_time(lead_time)
    _validate_buffer_days(buffer_days)

    try:
        # Fetch all products
        products = db.query(Product.id, Product.name, Product.SKU).all()

        if not products:
            logger.warning("No products found in the product table.")
            return []

        # Fetch current stock
        stock_map = get_current_stock_all(db)

        recommendations: List[Dict[str, Any]] = []

        for pid, name, sku in products:
            avg = avg_sales.get(pid, 0.0)
            stock = stock_map.get(pid, 0.0)

            reorder_point = calculate_reorder_point(avg, lead_time)
            reorder_qty = calculate_reorder_quantity(avg, lead_time, stock, buffer_days)

            # Only include products at or below reorder point
            if stock <= reorder_point:
                recommendations.append(
                    {
                        "product_id": pid,
                        "product_name": name or "Unknown",
                        "sku": sku or "",
                        "current_stock": stock,
                        "reorder_point": reorder_point,
                        "reorder_quantity": reorder_qty,
                        "avg_daily_sales": avg,
                        "lead_time_days": lead_time,
                        "buffer_days": buffer_days,
                    }
                )

        # Sort by reorder urgency — largest reorder_quantity first
        recommendations.sort(key=lambda r: r["reorder_quantity"], reverse=True)

        logger.info(
            "Generated %d reorder recommendations out of %d products.",
            len(recommendations), len(products),
        )
        return recommendations

    except (TypeError, ValueError):
        raise
    except Exception as exc:
        logger.error(
            "Failed to compute reorder recommendations: %s", exc, exc_info=True
        )
        raise RuntimeError(
            f"Failed to compute reorder recommendations: {exc}"
        ) from exc
