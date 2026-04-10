"""
alerts/email_alert.py
======================
Sends a daily inventory alert email using SMTP.
Reads from the current snapshot — does not query the DB.

Edge cases handled:
    - SMTP credentials missing → returns False with a logged error
    - SMTP connection fails → caught, logged, returns False
    - Snapshot has no critical items → sends a clean "no issues" digest
    - Recipient not set → logs error, returns False
    - Snapshot is None or invalid → returns False with logged error

Input validations:
    - All environment variables must be set and non-empty
    - snapshot must be a non-None dict

Assumptions NOT made:
    - Not assuming SMTP server is always reachable
    - Not assuming credentials are always valid
    - Not assuming snapshot always has critical items
    - Not assuming email content is always HTML (we include plain text fallback)

Environment variables:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_RECIPIENT
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration loader
# ---------------------------------------------------------------------------

def _get_smtp_config() -> Optional[Dict[str, str]]:
    """
    Load SMTP configuration from environment variables.

    Returns:
        Dict with host, port, user, password, recipient — or None if
        any required variable is missing.
    """
    required = {
        "host": "SMTP_HOST",
        "port": "SMTP_PORT",
        "user": "SMTP_USER",
        "password": "SMTP_PASSWORD",
        "recipient": "ALERT_EMAIL_RECIPIENT",
    }

    config: Dict[str, str] = {}
    missing: list[str] = []

    for key, env_var in required.items():
        value = os.getenv(env_var, "").strip()
        if not value:
            missing.append(env_var)
        else:
            config[key] = value

    if missing:
        logger.error(
            "Missing SMTP environment variables: %s. Email alert will not be sent.",
            ", ".join(missing),
        )
        return None

    return config


# ---------------------------------------------------------------------------
# Email body builder
# ---------------------------------------------------------------------------

def build_email_body(snapshot: Dict[str, Any]) -> str:
    """
    Format the snapshot summary into a readable HTML email body.

    Includes critical stockouts, reorder recommendations, dead inventory
    count, and a concise daily digest.

    Args:
        snapshot: The current inventory snapshot dict.

    Returns:
        HTML string for the email body.

    Raises:
        TypeError: If snapshot is not a dict.
    """
    if not isinstance(snapshot, dict):
        raise TypeError(f"snapshot must be a dict, got {type(snapshot).__name__}")

    summary = snapshot.get("summary", {})
    generated_at = snapshot.get("generated_at", "Unknown")
    stockout_risks = snapshot.get("stockout_risks", [])
    reorder_recs = snapshot.get("reorder_recommendations", [])
    dead_inv = snapshot.get("dead_inventory", [])

    # Build stockout rows
    stockout_rows = ""
    for item in stockout_risks[:10]:
        stockout_rows += (
            f"<tr>"
            f"<td>{item.get('product_id', '—')}</td>"
            f"<td>{item.get('product_name', '—')}</td>"
            f"<td>{item.get('current_stock', '—')}</td>"
            f"<td>{item.get('days_left', '—')}</td>"
            f"<td>{item.get('lead_time_days', '—')}</td>"
            f"</tr>"
        )

    # Build reorder rows
    reorder_rows = ""
    for item in reorder_recs[:10]:
        reorder_rows += (
            f"<tr>"
            f"<td>{item.get('product_id', '—')}</td>"
            f"<td>{item.get('product_name', '—')}</td>"
            f"<td>{item.get('current_stock', '—')}</td>"
            f"<td>{item.get('reorder_quantity', '—')}</td>"
            f"</tr>"
        )

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            h2 {{ color: #1a73e8; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #1a73e8; color: white; }}
            .summary {{ background: #f0f4ff; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
            .critical {{ color: #d32f2f; font-weight: bold; }}
        </style>
    </head>
    <body>
        <h2>📦 KOL Distributor Toys — Daily Inventory Alert</h2>
        <p>Snapshot generated at: <strong>{generated_at}</strong></p>

        <div class="summary">
            <p>📊 <strong>Total SKUs:</strong> {summary.get('total_skus', 0)}</p>
            <p class="critical">🚨 <strong>Critical Stockouts:</strong> {summary.get('critical_stockouts', 0)}</p>
            <p>🔄 <strong>Items Needing Reorder:</strong> {summary.get('items_to_reorder', 0)}</p>
            <p>💤 <strong>Dead Inventory Items:</strong> {summary.get('dead_inventory_count', 0)}</p>
        </div>

        {"<h3>🚨 Top Stockout Risks</h3>" + '''
        <table>
            <tr><th>ID</th><th>Product</th><th>Stock</th><th>Days Left</th><th>Lead Time</th></tr>
            ''' + stockout_rows + "</table>" if stockout_rows else "<p>✅ No critical stockout risks.</p>"}

        {"<h3>🔄 Top Reorder Recommendations</h3>" + '''
        <table>
            <tr><th>ID</th><th>Product</th><th>Current Stock</th><th>Order Qty</th></tr>
            ''' + reorder_rows + "</table>" if reorder_rows else "<p>✅ No reorder recommendations.</p>"}

        <p>💤 <strong>Dead inventory items:</strong> {len(dead_inv)}</p>

        <hr>
        <p style="color: #999; font-size: 12px;">
            This is an automated alert from KOL Distributor Toys Inventory Control Tower.
        </p>
    </body>
    </html>
    """

    return html


# ---------------------------------------------------------------------------
# Email sender
# ---------------------------------------------------------------------------

def send_email_alert(snapshot: Dict[str, Any]) -> bool:
    """
    Build and send a daily inventory alert email.

    Args:
        snapshot: The current inventory snapshot dict.

    Returns:
        True if the email was sent successfully, False otherwise.
        Never raises — catches all exceptions and logs them.
    """
    if snapshot is None or not isinstance(snapshot, dict):
        logger.error("Cannot send email alert: snapshot is None or invalid.")
        return False

    # Load SMTP config
    config = _get_smtp_config()
    if config is None:
        return False

    try:
        # Build the email
        body_html = build_email_body(snapshot)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "📦 KOL Inventory Alert — Daily Digest"
        msg["From"] = config["user"]
        msg["To"] = config["recipient"]

        # Plain text fallback
        summary = snapshot.get("summary", {})
        plain_text = (
            f"KOL Distributor Toys — Daily Inventory Alert\n"
            f"Generated: {snapshot.get('generated_at', 'Unknown')}\n\n"
            f"Total SKUs: {summary.get('total_skus', 0)}\n"
            f"Critical Stockouts: {summary.get('critical_stockouts', 0)}\n"
            f"Items to Reorder: {summary.get('items_to_reorder', 0)}\n"
            f"Dead Inventory: {summary.get('dead_inventory_count', 0)}\n"
        )

        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        # Send via SMTP
        port = int(config["port"])

        if port == 465:
            # SSL
            with smtplib.SMTP_SSL(config["host"], port, timeout=30) as server:
                server.login(config["user"], config["password"])
                server.sendmail(config["user"], config["recipient"], msg.as_string())
        else:
            # STARTTLS (ports 587, 25, etc.)
            with smtplib.SMTP(config["host"], port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(config["user"], config["password"])
                server.sendmail(config["user"], config["recipient"], msg.as_string())

        logger.info(
            "Email alert sent successfully to %s.", config["recipient"]
        )
        return True

    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP authentication failed: %s", exc)
        return False
    except smtplib.SMTPException as exc:
        logger.error("SMTP error while sending email alert: %s", exc)
        return False
    except ConnectionError as exc:
        logger.error("Could not connect to SMTP server: %s", exc)
        return False
    except Exception as exc:
        logger.error(
            "Unexpected error sending email alert: %s", exc, exc_info=True
        )
        return False
