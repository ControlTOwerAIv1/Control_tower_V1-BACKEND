"""
controllers/alerts.py
==================
FastAPI router for alert-related endpoints.

Edge cases handled:
    - Snapshot unavailable → returns 503
    - Email alert fails → logged, status reported as failed
    - Telegram alert fails → logged, status reported as failed
    - Both channels fail → still returns 200 with per-channel failure status
    - Snapshot has no critical items → alerts still sent (empty digest)

Input validations:
    - Snapshot must be available before generating alert content

Assumptions NOT made:
    - Not assuming email or Telegram always succeeds
    - Not assuming snapshot exists at any given moment
    - Not assuming alert infrastructure is always reachable
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from cache.snapshot import get_snapshot
from alerts.email_alert import send_email_alert
from alerts.telegram_alert import send_telegram_alert

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _safe_get_snapshot() -> Dict[str, Any]:
    """
    Retrieve the current snapshot, raising a 503 if unavailable.

    Returns:
        The current inventory snapshot dict.

    Raises:
        HTTPException: 503 if no snapshot has been built yet.
    """
    try:
        return get_snapshot()
    except RuntimeError as exc:
        logger.warning("Snapshot not available for alerts: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Inventory snapshot is not available yet. Cannot generate alerts.",
        ) from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/daily-summary", response_model=Dict[str, Any])
async def get_daily_summary() -> Dict[str, Any]:
    """
    Return a combined summary of all alert types from the snapshot.

    Used by the frontend alert banner to display a quick overview of
    inventory issues needing attention.

    Returns:
        Dict with summary counts, top stockout risks, and reorder items.
    """
    snapshot = _safe_get_snapshot()

    summary = snapshot.get("summary", {})
    stockout_risks = snapshot.get("stockout_risks", [])
    reorder_recs = snapshot.get("reorder_recommendations", [])
    dead_inventory = snapshot.get("dead_inventory", [])

    return {
        "generated_at": snapshot.get("generated_at", "unknown"),
        "summary": summary,
        "top_stockout_risks": stockout_risks[:5],
        "top_reorder_items": reorder_recs[:5],
        "top_dead_inventory": dead_inventory[:5],
        "has_critical_alerts": summary.get("critical_stockouts", 0) > 0,
    }


@router.post("/trigger", response_model=Dict[str, Any])
async def trigger_alerts() -> Dict[str, Any]:
    """
    Manually trigger email and WhatsApp alerts.

    Calls both alert channels and returns per-channel delivery status.
    Individual channel failures are logged but do not cause a 500 —
    the endpoint always returns the result of each attempt.

    Returns:
        Dict with delivery status for each channel.
    """
    snapshot = _safe_get_snapshot()

    results: Dict[str, Any] = {
        "email": {"sent": False, "error": None},
        "telegram": {"sent": False, "error": None},
    }

    # Email alert
    try:
        email_success = send_email_alert(snapshot)
        results["email"]["sent"] = email_success
        if not email_success:
            results["email"]["error"] = "Email send returned False — check logs."
    except Exception as exc:
        logger.error("Email alert trigger failed: %s", exc, exc_info=True)
        results["email"]["error"] = str(exc)

    # Telegram alert
    try:
        telegram_success = send_telegram_alert(snapshot)
        results["telegram"]["sent"] = telegram_success
        if not telegram_success:
            results["telegram"]["error"] = "Telegram send returned False — check logs."
    except Exception as exc:
        logger.error("Telegram alert trigger failed: %s", exc, exc_info=True)
        results["telegram"]["error"] = str(exc)

    overall = results["email"]["sent"] or results["telegram"]["sent"]

    logger.info(
        "Alert trigger completed — email: %s, telegram: %s",
        results["email"]["sent"],
        results["telegram"]["sent"],
    )

    return {
        "status": "completed",
        "any_sent": overall,
        "channels": results,
    }
