"""
alerts/whatsapp_alert.py
=========================
Sends a daily inventory alert via WhatsApp using the Twilio API.
Reads from the current snapshot — does not query the DB.

Edge cases handled:
    - Twilio credentials missing → returns False with a logged error
    - Twilio API call fails → caught, logged, returns False
    - Message exceeds 1000 characters → truncated to fit WhatsApp limits
    - Snapshot is None or invalid → returns False with logged error
    - No critical items in snapshot → sends a clean "all clear" message

Input validations:
    - All Twilio environment variables must be set and non-empty
    - snapshot must be a non-None dict

Assumptions NOT made:
    - Not assuming Twilio is always reachable
    - Not assuming credentials are always valid
    - Not assuming message content always fits within WhatsApp limits
    - Not assuming snapshot always has critical items

Environment variables:
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, ALERT_TO_NUMBER
"""

import logging
import os
from typing import Any, Dict, List, Optional

from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException

logger = logging.getLogger(__name__)

# WhatsApp messages should be concise — hard limit to keep them readable
_MAX_MESSAGE_LENGTH: int = 1000


# ---------------------------------------------------------------------------
# Configuration loader
# ---------------------------------------------------------------------------

def _get_twilio_config() -> Optional[Dict[str, str]]:
    """
    Load Twilio configuration from environment variables.

    Returns:
        Dict with account_sid, auth_token, from_number, to_number —
        or None if any required variable is missing.
    """
    required = {
        "account_sid": "TWILIO_ACCOUNT_SID",
        "auth_token": "TWILIO_AUTH_TOKEN",
        "from_number": "TWILIO_FROM_NUMBER",
        "to_number": "ALERT_TO_NUMBER",
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
            "Missing Twilio environment variables: %s. "
            "WhatsApp alert will not be sent.",
            ", ".join(missing),
        )
        return None

    return config


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------

def build_whatsapp_message(snapshot: Dict[str, Any]) -> str:
    """
    Format the snapshot summary into a short WhatsApp-friendly plain text message.

    The message is kept under 1000 characters and includes only the most
    critical inventory items.

    Args:
        snapshot: The current inventory snapshot dict.

    Returns:
        A plain text string suitable for WhatsApp delivery.

    Raises:
        TypeError: If snapshot is not a dict.
    """
    if not isinstance(snapshot, dict):
        raise TypeError(f"snapshot must be a dict, got {type(snapshot).__name__}")

    summary = snapshot.get("summary", {})
    generated_at = snapshot.get("generated_at", "Unknown")
    stockout_risks = snapshot.get("stockout_risks", [])
    reorder_recs = snapshot.get("reorder_recommendations", [])

    lines: List[str] = [
        "📦 *KOL Inventory Alert*",
        f"🕐 {generated_at}",
        "",
        f"📊 Total SKUs: {summary.get('total_skus', 0)}",
        f"🚨 Stockout Risks: {summary.get('critical_stockouts', 0)}",
        f"🔄 Reorder Needed: {summary.get('items_to_reorder', 0)}",
        f"💤 Dead Inventory: {summary.get('dead_inventory_count', 0)}",
    ]

    # Add top stockout risks (limit to 3 for brevity)
    if stockout_risks:
        lines.append("")
        lines.append("*Top Stockout Risks:*")
        for item in stockout_risks[:3]:
            days_left = item.get("days_left", "?")
            if isinstance(days_left, float) and days_left == float("inf"):
                days_left = "∞"
            lines.append(
                f"  ⚠️ {item.get('product_name', '?')} "
                f"(Stock: {item.get('current_stock', '?')}, "
                f"Days Left: {days_left})"
            )

    # Add top reorder items (limit to 3 for brevity)
    if reorder_recs:
        lines.append("")
        lines.append("*Top Reorder Items:*")
        for item in reorder_recs[:3]:
            lines.append(
                f"  🔄 {item.get('product_name', '?')} "
                f"(Order: {item.get('reorder_quantity', '?')} units)"
            )

    # If nothing critical, add a positive note
    if not stockout_risks and not reorder_recs:
        lines.append("")
        lines.append("✅ All inventory levels are healthy!")

    message = "\n".join(lines)

    # Truncate if exceeds limit
    if len(message) > _MAX_MESSAGE_LENGTH:
        # Truncate and add ellipsis indicator
        truncated = message[: _MAX_MESSAGE_LENGTH - 20]
        # Cut at last newline to avoid breaking a line mid-word
        last_newline = truncated.rfind("\n")
        if last_newline > 0:
            truncated = truncated[:last_newline]
        message = truncated + "\n\n… (truncated)"

    return message


# ---------------------------------------------------------------------------
# WhatsApp sender
# ---------------------------------------------------------------------------

def send_whatsapp_alert(snapshot: Dict[str, Any]) -> bool:
    """
    Build and send a daily inventory alert via WhatsApp using Twilio.

    Args:
        snapshot: The current inventory snapshot dict.

    Returns:
        True if the message was sent successfully, False otherwise.
        Never raises — catches all exceptions and logs them.
    """
    if snapshot is None or not isinstance(snapshot, dict):
        logger.error("Cannot send WhatsApp alert: snapshot is None or invalid.")
        return False

    # Load Twilio config
    config = _get_twilio_config()
    if config is None:
        return False

    try:
        # Build the message
        message_body = build_whatsapp_message(snapshot)

        # Ensure WhatsApp format for phone numbers
        from_number = config["from_number"]
        to_number = config["to_number"]

        # Twilio WhatsApp requires "whatsapp:" prefix
        if not from_number.startswith("whatsapp:"):
            from_number = f"whatsapp:{from_number}"
        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"

        # Create Twilio client and send
        client = TwilioClient(config["account_sid"], config["auth_token"])

        message = client.messages.create(
            body=message_body,
            from_=from_number,
            to=to_number,
        )

        logger.info(
            "WhatsApp alert sent successfully. SID: %s, To: %s",
            message.sid,
            to_number,
        )
        return True

    except TwilioRestException as exc:
        logger.error("Twilio API error sending WhatsApp alert: %s", exc)
        return False
    except ConnectionError as exc:
        logger.error("Could not connect to Twilio API: %s", exc)
        return False
    except Exception as exc:
        logger.error(
            "Unexpected error sending WhatsApp alert: %s", exc, exc_info=True
        )
        return False
