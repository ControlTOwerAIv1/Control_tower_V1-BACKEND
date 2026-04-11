"""
alerts/telegram_alert.py
=========================
Sends a daily inventory alert via Telegram Bot API.
Reads from the current snapshot — does not query the DB.

Edge cases handled:
    - Telegram credentials missing → returns False with a logged error
    - HTTP request fails → caught, logged, returns False
    - Message exceeds 4096 characters → truncated to fit Telegram limits
    - Snapshot is None or invalid → returns False with logged error
    - No critical items in snapshot → sends a clean "all clear" message
    - Non-200 response from Telegram → logged with status code and body

Input validations:
    - TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set and non-empty
    - snapshot must be a non-None dict

Assumptions NOT made:
    - Not assuming Telegram API is always reachable
    - Not assuming credentials are always valid
    - Not assuming message content always fits within Telegram limits
    - Not assuming snapshot always has critical items

Environment variables:
    TELEGRAM_BOT_TOKEN   — bot token from BotFather (e.g. 123456:ABC-DEF...)
    TELEGRAM_CHAT_ID     — chat/group/channel ID to send the message to
"""

import logging
import os
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Telegram hard limit for a single message
_MAX_MESSAGE_LENGTH: int = 4096

_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


# ---------------------------------------------------------------------------
# Configuration loader
# ---------------------------------------------------------------------------

def _get_telegram_config() -> Optional[Dict[str, str]]:
    """
    Load Telegram configuration from environment variables.

    Returns:
        Dict with bot_token and chat_id — or None if any required
        variable is missing.
    """
    required = {
        "bot_token": "TELEGRAM_BOT_TOKEN",
        "chat_id": "TELEGRAM_CHAT_ID",
    }

    config: Dict[str, str] = {}
    missing: List[str] = []

    for key, env_var in required.items():
        value = os.getenv(env_var, "").strip()
        if not value:
            missing.append(env_var)
        else:
            config[key] = value

    if missing:
        logger.error(
            "Missing Telegram environment variables: %s. "
            "Telegram alert will not be sent.",
            ", ".join(missing),
        )
        return None

    return config


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------

def build_telegram_message(snapshot: Dict[str, Any]) -> str:
    """
    Format the snapshot summary into a Telegram-friendly plain text message.

    Uses Telegram's MarkdownV2-compatible bold syntax (*text*).
    Kept under 4096 characters (Telegram's limit).

    Args:
        snapshot: The current inventory snapshot dict.

    Returns:
        A plain text string suitable for Telegram delivery.

    Raises:
        TypeError: If snapshot is not a dict.
    """
    if not isinstance(snapshot, dict):
        raise TypeError(f"snapshot must be a dict, got {type(snapshot).__name__}")

    summary = snapshot.get("summary", {})
    generated_at = snapshot.get("generated_at", "Unknown")
    stockout_risks = snapshot.get("stockout_risks", [])
    reorder_recs = snapshot.get("reorder_recommendations", [])
    dead_inventory = snapshot.get("dead_inventory", [])

    lines: List[str] = [
        "📦 *KOL Inventory Alert*",
        f"🕐 {generated_at}",
        "",
        f"📊 Total SKUs: {summary.get('total_skus', 0)}",
        f"🚨 Stockout Risks: {summary.get('critical_stockouts', 0)}",
        f"🔄 Reorder Needed: {summary.get('items_to_reorder', 0)}",
        f"💤 Dead Inventory: {summary.get('dead_inventory_count', 0)}",
    ]

    # Top stockout risks (limit to 5 — Telegram has more room than WhatsApp)
    if stockout_risks:
        lines.append("")
        lines.append("*🚨 Top Stockout Risks:*")
        for item in stockout_risks[:5]:
            days_left = item.get("days_left")
            days_left_str = "∞" if days_left is None else str(days_left)
            lines.append(
                f"  ⚠️ {item.get('product_name', '?')} "
                f"(Stock: {item.get('current_stock', '?')}, "
                f"Days Left: {days_left_str})"
            )

    # Top reorder items (limit to 5)
    if reorder_recs:
        lines.append("")
        lines.append("*🔄 Top Reorder Items:*")
        for item in reorder_recs[:5]:
            lines.append(
                f"  🔄 {item.get('product_name', '?')} "
                f"(Order: {item.get('reorder_quantity', '?')} units)"
            )

    # Top dead inventory (limit to 5)
    if dead_inventory:
        lines.append("")
        lines.append("*💤 Dead / Slow-Moving:*")
        for item in dead_inventory[:5]:
            if item.get("never_sold"):
                sale_info = "never sold"
            else:
                sale_info = f"{item.get('days_since_last_sale', '?')}d ago"
            lines.append(
                f"  💤 {item.get('product_name', '?')} "
                f"(Stock: {item.get('current_stock', '?')}, Last sold: {sale_info})"
            )

    # All-clear message when nothing is critical
    if not stockout_risks and not reorder_recs and not dead_inventory:
        lines.append("")
        lines.append("✅ All inventory levels are healthy!")

    message = "\n".join(lines)

    # Truncate if exceeds Telegram's limit
    if len(message) > _MAX_MESSAGE_LENGTH:
        truncated = message[: _MAX_MESSAGE_LENGTH - 20]
        last_newline = truncated.rfind("\n")
        if last_newline > 0:
            truncated = truncated[:last_newline]
        message = truncated + "\n\n… (truncated)"

    return message


# ---------------------------------------------------------------------------
# Telegram sender
# ---------------------------------------------------------------------------

def send_telegram_alert(snapshot: Dict[str, Any]) -> bool:
    """
    Build and send a daily inventory alert via the Telegram Bot API.

    Args:
        snapshot: The current inventory snapshot dict.

    Returns:
        True if the message was sent successfully, False otherwise.
        Never raises — catches all exceptions and logs them.
    """
    if snapshot is None or not isinstance(snapshot, dict):
        logger.error("Cannot send Telegram alert: snapshot is None or invalid.")
        return False

    config = _get_telegram_config()
    if config is None:
        return False

    try:
        message_body = build_telegram_message(snapshot)

        url = _TELEGRAM_API_BASE.format(token=config["bot_token"])

        payload = {
            "chat_id": config["chat_id"],
            "text": message_body,
            "parse_mode": "Markdown",
        }

        response = requests.post(url, json=payload, timeout=15)

        if response.status_code == 200:
            logger.info(
                "Telegram alert sent successfully to chat_id=%s.",
                config["chat_id"],
            )
            return True

        logger.error(
            "Telegram API returned HTTP %d: %s",
            response.status_code,
            response.text[:200],
        )
        return False

    except requests.exceptions.ConnectionError as exc:
        logger.error("Could not connect to Telegram API: %s", exc)
        return False
    except requests.exceptions.Timeout as exc:
        logger.error("Telegram API request timed out: %s", exc)
        return False
    except Exception as exc:
        logger.error(
            "Unexpected error sending Telegram alert: %s", exc, exc_info=True
        )
        return False
