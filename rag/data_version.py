"""
rag/data_version.py
============================
Compute a compact data version string from live DB tables.

This is used to key response cache entries so cache invalidates
naturally when inventory/sales/lead-time data changes.
"""

import logging
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    Invoice,
    InvoiceDetails,
    LeadTimeSetting,
    Product,
    WarehouseProductManagement,
)

logger = logging.getLogger(__name__)


def _safe_max_id(db: Session, model) -> int:
    value: Optional[int] = db.query(func.max(model.id)).scalar()
    if value is None:
        return 0
    return int(value)


def compute_data_version(db: Session) -> str:
    """Return a deterministic version string for current live data state."""
    if db is None:
        raise ValueError("db must not be None")

    try:
        product_max = _safe_max_id(db, Product)
        warehouse_max = _safe_max_id(db, WarehouseProductManagement)
        invoice_max = _safe_max_id(db, Invoice)
        invoice_details_max = _safe_max_id(db, InvoiceDetails)
        lead_time_max = _safe_max_id(db, LeadTimeSetting)

        # Short, stable key for cache partitioning.
        return (
            f"p:{product_max}|w:{warehouse_max}|"
            f"i:{invoice_max}|d:{invoice_details_max}|l:{lead_time_max}"
        )
    except Exception as exc:
        logger.warning("Failed to compute data version, using fallback: %s", exc)
        return "unknown"
