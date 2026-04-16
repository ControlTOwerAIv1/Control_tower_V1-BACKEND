"""
rag/sql_tools.py
=========================
SQLAlchemy-backed tool functions for live-facts Q&A.

These wrappers reuse existing service-layer logic.
"""

import logging
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from services.avg_daily_sales import get_avg_daily_sales, get_global_lead_time
from services.dead_inventory import get_dead_inventory
from services.reorder import get_reorder_recommendations
from services.stockout import get_all_stock_levels, get_stockout_risks

logger = logging.getLogger(__name__)


def get_inventory_summary_tool(db: Session, days_window: int = 30) -> Dict[str, Any]:
    avg_sales = get_avg_daily_sales(db, days=days_window)
    lead_time = get_global_lead_time(db)
    stock_levels = get_all_stock_levels(db, avg_sales, lead_time)
    stockout_risks = get_stockout_risks(db, avg_sales, lead_time)
    reorder = get_reorder_recommendations(db, avg_sales, lead_time)
    dead = get_dead_inventory(db)

    return {
        "summary": {
            "total_skus": len(stock_levels),
            "critical_stockouts": len(stockout_risks),
            "items_to_reorder": len(reorder),
            "dead_inventory_count": len(dead),
            "lead_time_days": lead_time,
            "days_window": days_window,
        },
        "citations": [
            {
                "id": "S1",
                "source": "services.avg_daily_sales/get_avg_daily_sales",
            },
            {
                "id": "S2",
                "source": "services.stockout/get_all_stock_levels,get_stockout_risks",
            },
            {
                "id": "S3",
                "source": "services.reorder/get_reorder_recommendations",
            },
            {
                "id": "S4",
                "source": "services.dead_inventory/get_dead_inventory",
            },
        ],
    }


def get_stockout_risks_tool(db: Session, limit: int = 10, days_window: int = 30) -> Dict[str, Any]:
    avg_sales = get_avg_daily_sales(db, days=days_window)
    lead_time = get_global_lead_time(db)
    risks = get_stockout_risks(db, avg_sales, lead_time)[:limit]

    return {
        "stockout_risks": risks,
        "citations": [{"id": "S2", "source": "services.stockout/get_stockout_risks"}],
    }


def get_reorder_recommendations_tool(
    db: Session,
    limit: int = 10,
    days_window: int = 30,
    buffer_days: int = 7,
) -> Dict[str, Any]:
    avg_sales = get_avg_daily_sales(db, days=days_window)
    lead_time = get_global_lead_time(db)
    recs = get_reorder_recommendations(
        db,
        avg_sales,
        lead_time,
        buffer_days=buffer_days,
    )[:limit]

    return {
        "reorder_recommendations": recs,
        "citations": [{"id": "S3", "source": "services.reorder/get_reorder_recommendations"}],
    }


def get_dead_inventory_tool(db: Session, limit: int = 10, threshold_days: int = 60) -> Dict[str, Any]:
    dead_items = get_dead_inventory(db, threshold_days=threshold_days)[:limit]

    return {
        "dead_inventory": dead_items,
        "citations": [{"id": "S4", "source": "services.dead_inventory/get_dead_inventory"}],
    }


def find_products_tool(db: Session, query: str, limit: int = 8, days_window: int = 30) -> Dict[str, Any]:
    avg_sales = get_avg_daily_sales(db, days=days_window)
    lead_time = get_global_lead_time(db)
    rows: List[Dict[str, Any]] = get_all_stock_levels(db, avg_sales, lead_time)

    needle = query.strip().lower()
    matches = []
    for row in rows:
        name = str(row.get("product_name", "")).lower()
        sku = str(row.get("sku", "")).lower()
        if needle in name or needle in sku:
            matches.append(row)

    matches = matches[:limit]

    return {
        "matching_products": matches,
        "citations": [{"id": "S2", "source": "services.stockout/get_all_stock_levels"}],
    }
