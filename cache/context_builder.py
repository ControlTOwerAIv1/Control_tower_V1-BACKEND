"""
cache/context_builder.py
=========================
Takes the in-memory snapshot and formats it into a structured plain-text
context string that is injected into every Claude API call as the system
prompt.  Rebuilt once per snapshot refresh — NOT per user query.

Edge cases handled:
    - Snapshot is None or empty → raises RuntimeError
    - Snapshot missing expected keys → handled with .get() and defaults
    - Huge inventory (hundreds of SKUs) → truncated to top 20 per section
    - Context never built → get_current_context() raises RuntimeError
    - Stockout/reorder lists are empty → section says "None at this time"

Input validations:
    - snapshot must be a non-None, non-empty dict

Assumptions NOT made:
    - Not assuming snapshot always contains all expected keys
    - Not assuming inventory is small enough to embed completely
    - Not assuming context string length is always safe for Claude's window
"""

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_context_string: Optional[str] = None
_context_lock = threading.Lock()

# Maximum items to include per section to stay within context window limits
_MAX_ITEMS_PER_SECTION: int = 20


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_snapshot(snapshot: Dict[str, Any]) -> None:
    """
    Validate that the snapshot is a non-None, non-empty dict.

    Args:
        snapshot: The inventory snapshot to validate.

    Raises:
        TypeError: If snapshot is not a dict.
        ValueError: If snapshot is empty.
    """
    if snapshot is None:
        raise TypeError("snapshot must not be None")
    if not isinstance(snapshot, dict):
        raise TypeError(f"snapshot must be a dict, got {type(snapshot).__name__}")
    if not snapshot:
        raise ValueError("snapshot must not be empty")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_summary(summary: Dict[str, Any]) -> str:
    """
    Format the summary section of the context string.

    Args:
        summary: The summary dict from the snapshot.

    Returns:
        Formatted summary block as a string.
    """
    return (
        "SUMMARY:\n"
        f"  Total SKUs tracked: {summary.get('total_skus', 'N/A')}\n"
        f"  Critical stockout risks: {summary.get('critical_stockouts', 'N/A')}\n"
        f"  Items needing reorder: {summary.get('items_to_reorder', 'N/A')}\n"
        f"  Dead inventory items: {summary.get('dead_inventory_count', 'N/A')}\n"
    )


def _format_stockout_risks(risks: List[Dict[str, Any]]) -> str:
    """
    Format the stockout risks section, limited to top N items.

    Args:
        risks: List of stockout risk dicts from the snapshot.

    Returns:
        Formatted stockout risks block.
    """
    if not risks:
        return "TOP STOCKOUT RISKS (by urgency):\n  None at this time.\n"

    lines = [f"TOP STOCKOUT RISKS (by urgency, showing top {min(len(risks), _MAX_ITEMS_PER_SECTION)}):"]
    for item in risks[:_MAX_ITEMS_PER_SECTION]:
        days_left = item.get("days_left")
        if days_left is None:
            days_left_str = "∞ (no sales)"
        else:
            days_left_str = str(days_left)

        lines.append(
            f"  - ID {item.get('product_id', '?')}: {item.get('product_name', 'Unknown')} | "
            f"Stock: {item.get('current_stock', '?')} | "
            f"Avg Sales/Day: {item.get('avg_daily_sales', '?')} | "
            f"Days Left: {days_left_str} | "
            f"Lead Time: {item.get('lead_time_days', '?')} days"
        )

    if len(risks) > _MAX_ITEMS_PER_SECTION:
        lines.append(f"  … and {len(risks) - _MAX_ITEMS_PER_SECTION} more.")

    return "\n".join(lines) + "\n"


def _format_reorder_recommendations(recommendations: List[Dict[str, Any]]) -> str:
    """
    Format the reorder recommendations section, limited to top N items.

    Args:
        recommendations: List of reorder recommendation dicts.

    Returns:
        Formatted reorder block.
    """
    if not recommendations:
        return "TOP REORDER RECOMMENDATIONS:\n  None at this time.\n"

    lines = [f"TOP REORDER RECOMMENDATIONS (showing top {min(len(recommendations), _MAX_ITEMS_PER_SECTION)}):"]
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
        lines.append(
            f"  … and {len(recommendations) - _MAX_ITEMS_PER_SECTION} more."
        )

    return "\n".join(lines) + "\n"


def _format_dead_inventory(dead: List[Dict[str, Any]]) -> str:
    """
    Format the dead / slow-moving inventory section, limited to top N items.

    Args:
        dead: List of dead inventory dicts.

    Returns:
        Formatted dead inventory block.
    """
    if not dead:
        return "DEAD OR SLOW-MOVING INVENTORY:\n  None at this time.\n"

    lines = [f"DEAD OR SLOW-MOVING INVENTORY (showing top {min(len(dead), _MAX_ITEMS_PER_SECTION)}):"]
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
        lines.append(f"  … and {len(dead) - _MAX_ITEMS_PER_SECTION} more.")

    return "\n".join(lines) + "\n"


def _build_instruction_block() -> str:
    """
    Build the instruction block that tells Claude how to behave.

    Returns:
        The instruction string appended to every context.
    """
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_context_string(snapshot: Dict[str, Any]) -> str:
    """
    Format the snapshot into a structured plain-text context string for Claude.

    The resulting string serves as the system prompt for every Claude API
    call, providing the AI with current inventory data.

    Args:
        snapshot: The inventory snapshot dict from cache/snapshot.py.

    Returns:
        A formatted plain-text string containing summary, stockout risks,
        reorder recommendations, dead inventory, and behaviour instructions.

    Raises:
        TypeError: If snapshot is not a dict or is None.
        ValueError: If snapshot is empty.
    """
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
    """
    Return the currently stored context string.

    Returns:
        The context string most recently built by refresh_context().

    Raises:
        RuntimeError: If no context has been built yet.
    """
    if _context_string is None:
        raise RuntimeError(
            "No context string available. The context has not been built yet. "
            "Call refresh_context() first."
        )
    return _context_string


def refresh_context(snapshot: Dict[str, Any]) -> None:
    """
    Rebuild and store the context string from a new snapshot.

    Thread-safe: uses a lock so concurrent calls do not produce a
    half-written context string.

    Args:
        snapshot: The new inventory snapshot dict.

    Raises:
        TypeError: If snapshot is not a dict or is None.
        ValueError: If snapshot is empty.
    """
    global _context_string

    _validate_snapshot(snapshot)

    with _context_lock:
        new_context = build_context_string(snapshot)
        _context_string = new_context

    logger.info("Context string refreshed (%d characters).", len(_context_string))
