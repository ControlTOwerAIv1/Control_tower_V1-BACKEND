"""
services/avg_daily_sales.py
============================
Calculate average daily sales for products over a configurable rolling
window. Also provides the global lead time lookup.

SCHEMA CORRECTION:
    - Uses Invoice + InvoiceDetails (NOT SalesBill/SalesBillDetails)
    - invoice_date (datetime) is the sale date column
    - invoice_details.quantity (int) is units sold
    - invoice_details.invoice_id is the FK to invoice.id
    - lead_time_setting.days is VARCHAR, global (no product_id)
"""

import logging
from datetime import date, timedelta
from typing import Dict, Optional

from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from models import LeadTimeSetting, Product, Invoice, InvoiceDetails

logger = logging.getLogger(__name__)

_DEFAULT_LEAD_TIME_DAYS: int = 7


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_days(days: int) -> None:
    if not isinstance(days, int):
        raise TypeError(f"days must be an integer, got {type(days).__name__}")
    if days <= 0:
        raise ValueError(f"days must be a positive integer, got {days}")


def _validate_product_id(product_id: int) -> None:
    if product_id is None:
        raise TypeError("product_id must not be None")
    if not isinstance(product_id, int):
        raise TypeError(f"product_id must be an integer, got {type(product_id).__name__}")
    if product_id <= 0:
        raise ValueError(f"product_id must be a positive integer, got {product_id}")


def _validate_db_session(db: Session) -> None:
    if db is None:
        raise ValueError("Database session (db) must not be None")


# ---------------------------------------------------------------------------
# Core helper
# ---------------------------------------------------------------------------

def _compute_avg(total_sold: Optional[float], days: int) -> float:
    if total_sold is None or total_sold == 0:
        return 0.0
    return round(float(total_sold) / days, 4)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_avg_daily_sales(db: Session, days: int = 30) -> Dict[int, float]:
    """
    Calculate average daily sales for ALL products over the last N days.

    Uses invoice + invoice_details tables.
    invoice_date is the sale date. quantity is units sold.

    Returns:
        Dict mapping product_id -> average daily sales.
        Every product gets an entry (0.0 if no sales in window).
    """
    _validate_db_session(db)
    _validate_days(days)

    try:
        all_product_ids = [
            row[0] for row in db.query(Product.id).filter(Product.status == 1).all()
        ]

        if not all_product_ids:
            logger.warning("No active products (status=1) found in the product table.")
            return {}

        end_date: date = date.today()
        start_date: date = end_date - timedelta(days=days - 1)  # inclusive window of exactly `days` days

        logger.info(
            "Querying sales from %s to %s for %d active products.",
            start_date, end_date, len(all_product_ids),
        )

        sales_query = (
            db.query(
                InvoiceDetails.product_id,
                func.coalesce(func.sum(InvoiceDetails.quantity), 0).label("total_sold"),
            )
            .join(Invoice, Invoice.id == InvoiceDetails.invoice_id)
            .filter(
                InvoiceDetails.invoice_id.isnot(None),
                Invoice.invoice_date.isnot(None),
                func.date(Invoice.invoice_date) >= start_date,
                func.date(Invoice.invoice_date) <= end_date,
            )
            .group_by(InvoiceDetails.product_id)
            .all()
        )

        logger.info("Sales query returned %d product rows with sales.", len(sales_query))

        sales_lookup: Dict[int, float] = {
            row[0]: float(row[1]) for row in sales_query if row[0] is not None
        }

        result: Dict[int, float] = {}
        for pid in all_product_ids:
            total_sold = sales_lookup.get(pid, 0.0)
            result[pid] = _compute_avg(total_sold, days)

        logger.info(
            "Computed avg daily sales for %d products over %d-day window. "
            "%d products had sales.",
            len(result), days, len(sales_lookup),
        )
        return result

    except (TypeError, ValueError):
        raise
    except Exception as exc:
        logger.error("Failed to compute avg daily sales: %s", exc, exc_info=True)
        raise RuntimeError(f"Failed to compute avg daily sales: {exc}") from exc


def get_avg_for_product(db: Session, product_id: int, days: int = 30) -> float:
    """
    Calculate average daily sales for a single product.
    """
    _validate_db_session(db)
    _validate_product_id(product_id)
    _validate_days(days)

    try:
        product_exists = db.query(Product.id).filter(Product.id == product_id).first()
        if product_exists is None:
            logger.warning("Product ID %d not found. Returning 0.0.", product_id)
            return 0.0

        end_date: date = date.today()
        start_date: date = end_date - timedelta(days=days - 1)  # inclusive window of exactly `days` days

        total_sold = (
            db.query(func.coalesce(func.sum(InvoiceDetails.quantity), 0))
            .join(Invoice, Invoice.id == InvoiceDetails.invoice_id)
            .filter(
                InvoiceDetails.product_id == product_id,
                InvoiceDetails.invoice_id.isnot(None),
                Invoice.invoice_date.isnot(None),
                func.date(Invoice.invoice_date) >= start_date,
                func.date(Invoice.invoice_date) <= end_date,
            )
            .scalar()
        )

        avg = _compute_avg(total_sold, days)
        logger.info("Avg daily sales for product %d over %d days: %.4f", product_id, days, avg)
        return avg

    except (TypeError, ValueError):
        raise
    except Exception as exc:
        logger.error("Failed to compute avg for product %d: %s", product_id, exc, exc_info=True)
        raise RuntimeError(f"Failed to compute avg for product {product_id}: {exc}") from exc


def get_global_lead_time(db: Session) -> int:
    """
    Get active global lead time from lead_time_setting.
    Most recent row (highest id) is used. days column is VARCHAR.
    Returns 7 as default if table is empty or value is invalid.
    """
    _validate_db_session(db)

    try:
        latest_row = (
            db.query(LeadTimeSetting)
            .order_by(desc(LeadTimeSetting.id))
            .first()
        )

        if latest_row is None:
            logger.warning("lead_time_setting table is empty. Using default: %d days.", _DEFAULT_LEAD_TIME_DAYS)
            return _DEFAULT_LEAD_TIME_DAYS

        try:
            lead_time = int(latest_row.days)
        except (ValueError, TypeError):
            logger.warning("lead_time_setting.days='%s' not castable to int. Using default.", latest_row.days)
            return _DEFAULT_LEAD_TIME_DAYS

        if lead_time <= 0:
            logger.warning("lead_time_setting.days=%d not positive. Using default.", lead_time)
            return _DEFAULT_LEAD_TIME_DAYS

        logger.info("Global lead time loaded: %d days (id=%d).", lead_time, latest_row.id)
        return lead_time

    except ValueError:
        raise
    except Exception as exc:
        logger.error("Failed to load lead time: %s. Using default.", exc, exc_info=True)
        return _DEFAULT_LEAD_TIME_DAYS