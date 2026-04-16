"""
rag/context_builder.py
===============================
Builds and stores the current prompt context string used by the RAG layer.
"""

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_context_string: Optional[str] = None
_context_lock = threading.Lock()

_MAX_ITEMS_PER_SECTION: int = 20


def _validate_snapshot(snapshot: Dict[str, Any]) -> None:
    if snapshot is None:
        raise TypeError("snapshot must not be None")
    if not isinstance(snapshot, dict):
        raise TypeError(f"snapshot must be a dict, got {type(snapshot).__name__}")
    if not snapshot:
        raise ValueError("snapshot must not be empty")


def _format_summary(summary: Dict[str, Any]) -> str:
    return (
        "SUMMARY:\n"
        f"  Total SKUs tracked: {summary.get('total_skus', 'N/A')}\n"
        f"  Critical stockout risks: {summary.get('critical_stockouts', 'N/A')}\n"
        f"  Items needing reorder: {summary.get('items_to_reorder', 'N/A')}\n"
        f"  Dead inventory items: {summary.get('dead_inventory_count', 'N/A')}\n"
    )


def _format_stockout_risks(risks: List[Dict[str, Any]]) -> str:
    if not risks:
        return "TOP STOCKOUT RISKS (by urgency):\n  None at this time.\n"

    lines = [
        f"TOP STOCKOUT RISKS (by urgency, showing top {min(len(risks), _MAX_ITEMS_PER_SECTION)}):"
    ]
    for item in risks[:_MAX_ITEMS_PER_SECTION]:
        days_left = item.get("days_left")
        days_left_str = "inf (no sales)" if days_left is None else str(days_left)

        lines.append(
            f"  - ID {item.get('product_id', '?')}: {item.get('product_name', 'Unknown')} | "
            f"Stock: {item.get('current_stock', '?')} | "
            f"Avg Sales/Day: {item.get('avg_daily_sales', '?')} | "
            f"Days Left: {days_left_str} | "
            f"Lead Time: {item.get('lead_time_days', '?')} days"
        )

    if len(risks) > _MAX_ITEMS_PER_SECTION:
        lines.append(f"  ... and {len(risks) - _MAX_ITEMS_PER_SECTION} more.")

    return "\n".join(lines) + "\n"


def _format_reorder_recommendations(recommendations: List[Dict[str, Any]]) -> str:
    if not recommendations:
        return "TOP REORDER RECOMMENDATIONS:\n  None at this time.\n"

    lines = [
        f"TOP REORDER RECOMMENDATIONS (showing top {min(len(recommendations), _MAX_ITEMS_PER_SECTION)}):"
    ]
    for item in recommendations[:_MAX_ITEMS_PER_SECTION]:
        lines.append(
            f"  - ID {item.get('product_id', '?')}: {item.get('product_name', 'Unknown')} | "
            f"Stock: {item.get('current_stock', '?')} | "
            f"Reorder Point: {item.get('reorder_point', '?')} | "
            f"Suggested Order Qty: {item.get('reorder_quantity', '?')} | "
            f"Avg Sales/Day: {item.get('avg_daily_sales', '?')} | "
            f"Lead Time: {item.get('lead_time_days', '?')} days | "
            f"Buffer: {item.get('buffer_days', '?')} days"
        )

    if len(recommendations) > _MAX_ITEMS_PER_SECTION:
        lines.append(f"  ... and {len(recommendations) - _MAX_ITEMS_PER_SECTION} more.")

    return "\n".join(lines) + "\n"


def _format_dead_inventory(dead: List[Dict[str, Any]]) -> str:
    if not dead:
        return "DEAD OR SLOW-MOVING INVENTORY:\n  None at this time.\n"

    lines = [
        f"DEAD OR SLOW-MOVING INVENTORY (showing top {min(len(dead), _MAX_ITEMS_PER_SECTION)}):"
    ]
    for item in dead[:_MAX_ITEMS_PER_SECTION]:
        never_sold = item.get("never_sold", False)
        if never_sold:
            sale_info = "NEVER SOLD"
        else:
            last_sold = item.get("last_sold_date", "N/A")
            days_since = item.get("days_since_last_sale", "N/A")
            sale_info = f"Last sold: {last_sold} ({days_since} days ago)"

        lines.append(
            f"  - ID {item.get('product_id', '?')}: {item.get('product_name', 'Unknown')} | "
            f"Stock: {item.get('current_stock', '?')} | "
            f"{sale_info}"
        )

    if len(dead) > _MAX_ITEMS_PER_SECTION:
        lines.append(f"  ... and {len(dead) - _MAX_ITEMS_PER_SECTION} more.")

    return "\n".join(lines) + "\n"


def _build_instruction_block() -> str:
    return (
        "INSTRUCTIONS:\n"
        "  Answer only using the data provided above.\n"
        "  Be specific. Use exact numbers from the data.\n"
        "  Do not make up figures. If data is not present, say so.\n"
        "  Be concise and direct. No filler text.\n"
        "  When listing products, include their ID and name.\n"
        "  If asked about a product not in the data, say the data does not cover it.\n"
        "  Do not speculate about future trends beyond what the data shows.\n"
    )


def build_context_string(snapshot: Dict[str, Any]) -> str:
    _validate_snapshot(snapshot)

    try:
        generated_at = snapshot.get("generated_at", "Unknown")
        summary = snapshot.get("summary", {})
        stockout_risks = snapshot.get("stockout_risks", [])
        reorder_recs = snapshot.get("reorder_recommendations", [])
        dead_inv = snapshot.get("dead_inventory", [])

        sections = [
            "You are an inventory assistant for KOL Distributor Toys.",
            "",
            f"SNAPSHOT TIMESTAMP: {generated_at}",
            "",
            _format_summary(summary),
            _format_stockout_risks(stockout_risks),
            _format_reorder_recommendations(reorder_recs),
            _format_dead_inventory(dead_inv),
            _build_instruction_block(),
        ]

        context = "\n".join(sections)

        logger.info(
            "Context string built: %d characters, snapshot from %s.",
            len(context),
            generated_at,
        )
        return context

    except (TypeError, ValueError):
        raise
    except Exception as exc:
        logger.error("Failed to build context string: %s", exc, exc_info=True)
        raise RuntimeError(f"Failed to build context string: {exc}") from exc


def get_current_context() -> str:
    if _context_string is None:
        raise RuntimeError(
            "No context string available. The context has not been built yet. "
            "Call refresh_context() first."
        )
    return _context_string


def refresh_context(snapshot: Dict[str, Any]) -> None:
    global _context_string

    _validate_snapshot(snapshot)

    with _context_lock:
        new_context = build_context_string(snapshot)
        _context_string = new_context

    logger.info("Context string refreshed (%d characters).", len(_context_string))
