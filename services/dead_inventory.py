"""
services/dead_inventory.py
===========================
Detect products not sold for N or more consecutive days (default 60).
Products never sold are also flagged.

SCHEMA CORRECTION:
    - Uses Invoice + InvoiceDetails (NOT SalesBill/SalesBillDetails)
    - invoice_date (datetime) is the sale date
    - invoice_details.invoice_id is the FK to invoice.id
    - invoice_details.product_id links to product.id
    - invoice_details.quantity is units sold
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from models import Product, Invoice, InvoiceDetails, WarehouseProductManagement

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_db_session(db: Session) -> None:
    if db is None:
        raise ValueError("Database session (db) must not be None")


def _validate_threshold_days(threshold_days: int) -> None:
    if not isinstance(threshold_days, int):
        raise TypeError(f"threshold_days must be an integer, got {type(threshold_days).__name__}")
    if threshold_days <= 0:
        raise ValueError(f"threshold_days must be positive, got {threshold_days}")


def _validate_product_id(product_id: int) -> None:
    if product_id is None:
        raise TypeError("product_id must not be None")
    if not isinstance(product_id, int):
        raise TypeError(f"product_id must be an integer, got {type(product_id).__name__}")
    if product_id <= 0:
        raise ValueError(f"product_id must be positive, got {product_id}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        logger.warning("Could not parse date value: %s", value)
        return None


def _days_since(last_date: Optional[date]) -> Optional[int]:
    if last_date is None:
        return None
    delta = (date.today() - last_date).days
    if delta < 0:
        logger.warning("last_sold_date %s is in the future. Clamping to 0.", last_date)
        return 0
    return delta


# ---------------------------------------------------------------------------
# Diagnostic (call once on startup to verify JOIN is working)
# ---------------------------------------------------------------------------

def run_dead_inventory_diagnostic(db: Session) -> None:
    """
    Run raw COUNT queries to confirm invoice JOIN is finding data.
    Remove this call from main.py once confirmed working.
    """
    _validate_db_session(db)

    try:
        total_details = db.execute(text("SELECT COUNT(*) FROM invoice_details")).scalar()
        details_with_invoice_id = db.execute(
            text("SELECT COUNT(*) FROM invoice_details WHERE invoice_id IS NOT NULL")
        ).scalar()
        total_invoices = db.execute(text("SELECT COUNT(*) FROM invoice")).scalar()
        invoices_with_date = db.execute(
            text("SELECT COUNT(*) FROM invoice WHERE invoice_date IS NOT NULL")
        ).scalar()
        joined_rows = db.execute(text("""
            SELECT COUNT(*)
            FROM invoice_details id2
            JOIN invoice i ON i.id = id2.invoice_id
            WHERE id2.invoice_id IS NOT NULL
              AND i.invoice_date IS NOT NULL
        """)).scalar()

        logger.info("=== Dead Inventory JOIN Diagnostic ===")
        logger.info("  invoice_details total rows      : %s", total_details)
        logger.info("  invoice_details with invoice_id : %s", details_with_invoice_id)
        logger.info("  invoice total rows              : %s", total_invoices)
        logger.info("  invoice with date               : %s", invoices_with_date)
        logger.info("  Rows surviving JOIN + filters   : %s", joined_rows)
        logger.info("=======================================")

        if joined_rows == 0:
            logger.error("DIAGNOSTIC: Zero rows survived the JOIN. Check invoice_details.invoice_id -> invoice.id")
        else:
            logger.info("DIAGNOSTIC: JOIN working. %s matched rows found.", joined_rows)

    except Exception as exc:
        logger.error("Diagnostic query failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_last_sold_dates(db: Session) -> Dict[int, Optional[date]]:
    """
    Get the most recent sale date per product using invoice + invoice_details.

    Query:
        SELECT id2.product_id, MAX(i.invoice_date)
        FROM invoice_details id2
        JOIN invoice i ON i.id = id2.invoice_id
        WHERE id2.invoice_id IS NOT NULL
          AND i.invoice_date IS NOT NULL
        GROUP BY id2.product_id
    """
    _validate_db_session(db)

    try:
        rows = (
            db.query(
                InvoiceDetails.product_id,
                func.max(Invoice.invoice_date).label("last_sale"),
            )
            .filter(InvoiceDetails.invoice_id.isnot(None))
            .join(Invoice, Invoice.id == InvoiceDetails.invoice_id)
            .filter(Invoice.invoice_date.isnot(None))
            .group_by(InvoiceDetails.product_id)
            .all()
        )

        result: Dict[int, Optional[date]] = {}
        for pid, last_sale in rows:
            if pid is not None:
                result[pid] = _to_date(last_sale)

        logger.info("Loaded last-sold dates for %d products.", len(result))
        return result

    except ValueError:
        raise
    except Exception as exc:
        logger.error("Failed to load last-sold dates: %s", exc, exc_info=True)
        raise RuntimeError(f"Failed to load last-sold dates: {exc}") from exc


def get_last_sold_date(db: Session, product_id: int) -> Optional[date]:
    """Return most recent sale date for a single product."""
    _validate_db_session(db)
    _validate_product_id(product_id)

    try:
        last_sale = (
            db.query(func.max(Invoice.invoice_date))
            .join(InvoiceDetails, Invoice.id == InvoiceDetails.invoice_id)
            .filter(
                InvoiceDetails.product_id == product_id,
                InvoiceDetails.invoice_id.isnot(None),
                Invoice.invoice_date.isnot(None),
            )
            .scalar()
        )
        return _to_date(last_sale)

    except (TypeError, ValueError):
        raise
    except Exception as exc:
        logger.error("Failed to get last sold date for product %d: %s", product_id, exc, exc_info=True)
        raise RuntimeError(f"Failed to get last sold date for product {product_id}: {exc}") from exc


def get_dead_inventory(db: Session, threshold_days: int = 60) -> List[Dict[str, Any]]:
    """
    Detect products not sold for threshold_days or more.
    Products never sold are also included (never_sold=True).
    """
    _validate_db_session(db)
    _validate_threshold_days(threshold_days)

    try:
        products = db.query(Product.id, Product.name, Product.SKU).all()

        if not products:
            logger.warning("No products found in the product table.")
            return []

        stock_rows = (
            db.query(
                WarehouseProductManagement.product_id,
                func.coalesce(func.sum(WarehouseProductManagement.quantity), 0).label("total_stock"),
            )
            .group_by(WarehouseProductManagement.product_id)
            .all()
        )
        stock_map: Dict[int, float] = {
            row[0]: float(row[1]) for row in stock_rows if row[0] is not None
        }

        last_sold_map = get_last_sold_dates(db)

        dead: List[Dict[str, Any]] = []

        for pid, name, sku in products:
            last_sold = last_sold_map.get(pid)
            days_since = _days_since(last_sold)
            never_sold = last_sold is None
            current_stock = stock_map.get(pid, 0.0)

            if never_sold or (days_since is not None and days_since >= threshold_days):
                dead.append({
                    "product_id": pid,
                    "product_name": name or "Unknown",
                    "sku": sku or "",
                    "last_sold_date": last_sold.isoformat() if last_sold else None,
                    "days_since_last_sale": days_since,
                    "current_stock": current_stock,
                    "never_sold": never_sold,
                })

        dead.sort(key=lambda d: (
            not d["never_sold"],
            -(d["days_since_last_sale"] if d["days_since_last_sale"] is not None else float("inf")),
        ))

        logger.info(
            "Identified %d dead/slow-moving items (threshold=%d days) out of %d products.",
            len(dead), threshold_days, len(products),
        )
        return dead

    except (TypeError, ValueError):
        raise
    except Exception as exc:
        logger.error("Failed to detect dead inventory: %s", exc, exc_info=True)
        raise RuntimeError(f"Failed to detect dead inventory: {exc}") from exc