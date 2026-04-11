"""
alerts/scheduler.py
====================
Runs two recurring background jobs:
    1. Snapshot refresh — every N hours (default 4)
    2. Daily alert dispatch — every morning at a configured time

Uses APScheduler for background job management.

Edge cases handled:
    - DB session factory missing → raises ValueError
    - APScheduler fails to start → logged and re-raised
    - Alert job fails → caught and logged (does not crash scheduler)
    - Snapshot refresh fails → caught and logged (does not crash scheduler)
    - DAILY_ALERT_TIME invalid format → falls back to "08:00"
    - SNAPSHOT_REFRESH_HOURS invalid → falls back to 4

Input validations:
    - db (or db factory) must not be None
    - DAILY_ALERT_TIME must be valid HH:MM format
    - SNAPSHOT_REFRESH_HOURS must be a positive integer

Assumptions NOT made:
    - Not assuming scheduler always starts cleanly
    - Not assuming individual jobs always succeed
    - Not assuming environment variables are always set or valid

Environment variables:
    DAILY_ALERT_TIME       (format: "HH:MM", default "08:00")
    SNAPSHOT_REFRESH_HOURS (integer, default 4)
"""

import logging
import os
from datetime import datetime
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from alerts.email_alert import send_email_alert
from alerts.telegram_alert import send_telegram_alert
from cache.context_builder import refresh_context
from cache.response_cache import invalidate_cache
from cache.snapshot import get_snapshot, refresh_snapshot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_scheduler: Optional[BackgroundScheduler] = None


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _parse_alert_time(time_str: str) -> tuple[int, int]:
    """
    Parse a time string in HH:MM format into hour and minute integers.

    Args:
        time_str: Time string like "08:00" or "14:30".

    Returns:
        Tuple of (hour, minute).

    Falls back to (8, 0) if parsing fails.
    """
    try:
        parts = time_str.strip().split(":")
        if len(parts) != 2:
            raise ValueError(f"Expected HH:MM format, got '{time_str}'")

        hour = int(parts[0])
        minute = int(parts[1])

        if not (0 <= hour <= 23):
            raise ValueError(f"Hour must be 0-23, got {hour}")
        if not (0 <= minute <= 59):
            raise ValueError(f"Minute must be 0-59, got {minute}")

        return hour, minute

    except (ValueError, IndexError) as exc:
        logger.warning(
            "Invalid DAILY_ALERT_TIME '%s': %s. Falling back to 08:00.",
            time_str,
            exc,
        )
        return 8, 0


def _get_refresh_hours() -> int:
    """
    Load the snapshot refresh interval from environment.

    Returns:
        Refresh interval in hours (integer, minimum 1).
        Defaults to 4 if not set or invalid.
    """
    raw = os.getenv("SNAPSHOT_REFRESH_HOURS", "4").strip()

    try:
        hours = int(raw)
        if hours <= 0:
            raise ValueError(f"Must be positive, got {hours}")
        return hours
    except (ValueError, TypeError) as exc:
        logger.warning(
            "Invalid SNAPSHOT_REFRESH_HOURS '%s': %s. Falling back to 4.",
            raw,
            exc,
        )
        return 4


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------

def run_snapshot_refresh(db_factory: Callable[[], Session]) -> None:
    """
    Refresh the snapshot, rebuild the AI context, and invalidate the
    response cache.

    This is called on a schedule — it must NEVER crash the scheduler.
    All errors are caught and logged.

    Args:
        db_factory: A callable that returns a new SQLAlchemy Session.
                    The session is closed after use.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("[%s] Starting scheduled snapshot refresh …", timestamp)

    db: Optional[Session] = None
    try:
        db = db_factory()

        # Step 1: Refresh snapshot
        refresh_snapshot(db)
        logger.info("  ✓ Snapshot refreshed.")

        # Step 2: Rebuild AI context from new snapshot
        snapshot = get_snapshot()
        refresh_context(snapshot)
        logger.info("  ✓ AI context rebuilt.")

        # Step 3: Invalidate stale cached responses
        invalidate_cache()
        logger.info("  ✓ Response cache invalidated.")

        logger.info("[%s] Scheduled snapshot refresh completed successfully.", timestamp)

    except Exception as exc:
        logger.error(
            "[%s] Scheduled snapshot refresh FAILED: %s",
            timestamp,
            exc,
            exc_info=True,
        )

    finally:
        if db is not None:
            try:
                db.close()
            except Exception as close_exc:
                logger.warning("Failed to close DB session: %s", close_exc)


def run_daily_alerts() -> None:
    """
    Send daily alert emails and WhatsApp messages.

    Reads from the current snapshot. Individual channel failures are
    logged but do not affect the other channel. This function must
    NEVER crash the scheduler.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("[%s] Running daily alert dispatch …", timestamp)

    try:
        snapshot = get_snapshot()
    except RuntimeError as exc:
        logger.error(
            "[%s] Cannot send daily alerts — no snapshot available: %s",
            timestamp,
            exc,
        )
        return

    # Email alert
    try:
        email_result = send_email_alert(snapshot)
        logger.info(
            "  Email alert: %s", "SENT" if email_result else "FAILED"
        )
    except Exception as exc:
        logger.error("  Email alert EXCEPTION: %s", exc, exc_info=True)

    # Telegram alert
    try:
        telegram_result = send_telegram_alert(snapshot)
        logger.info(
            "  Telegram alert: %s", "SENT" if telegram_result else "FAILED"
        )
    except Exception as exc:
        logger.error("  Telegram alert EXCEPTION: %s", exc, exc_info=True)

    logger.info("[%s] Daily alert dispatch completed.", timestamp)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_scheduler(db_factory: Callable[[], Session]) -> None:
    """
    Initialise and start the APScheduler with two recurring jobs:
        1. Snapshot refresh — every N hours (from SNAPSHOT_REFRESH_HOURS env var)
        2. Daily alert dispatch — at a configured time (from DAILY_ALERT_TIME env var)

    The scheduler runs in the background and does not block the main thread.

    Args:
        db_factory: A callable that returns a new SQLAlchemy Session.
                    Each scheduled job will call this to get a fresh session.

    Raises:
        ValueError: If db_factory is None.
        RuntimeError: If the scheduler fails to start.
    """
    global _scheduler

    if db_factory is None:
        raise ValueError(
            "db_factory must not be None. Provide a callable that returns "
            "a SQLAlchemy Session."
        )

    # Load configuration from environment
    refresh_hours = _get_refresh_hours()
    alert_time_str = os.getenv("DAILY_ALERT_TIME", "08:00").strip()
    alert_hour, alert_minute = _parse_alert_time(alert_time_str)

    logger.info("Scheduler configuration:")
    logger.info("  Snapshot refresh interval: every %d hour(s)", refresh_hours)
    logger.info("  Daily alert time: %02d:%02d", alert_hour, alert_minute)

    try:
        _scheduler = BackgroundScheduler()

        # Job 1: Snapshot refresh
        _scheduler.add_job(
            func=run_snapshot_refresh,
            trigger=IntervalTrigger(hours=refresh_hours),
            args=[db_factory],
            id="snapshot_refresh",
            name="Snapshot Refresh",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("  ✓ Registered job: Snapshot Refresh (every %dh)", refresh_hours)

        # Job 2: Daily alert dispatch
        _scheduler.add_job(
            func=run_daily_alerts,
            trigger=CronTrigger(hour=alert_hour, minute=alert_minute),
            id="daily_alerts",
            name="Daily Alert Dispatch",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "  ✓ Registered job: Daily Alert Dispatch (at %02d:%02d)",
            alert_hour,
            alert_minute,
        )

        # Start the scheduler
        _scheduler.start()
        logger.info("Scheduler started successfully.")

    except Exception as exc:
        logger.error("Failed to start scheduler: %s", exc, exc_info=True)
        raise RuntimeError(f"Failed to start scheduler: {exc}") from exc


def stop_scheduler() -> None:
    """
    Gracefully shut down the scheduler if it is running.

    Safe to call even if the scheduler was never started.
    """
    global _scheduler

    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
            logger.info("Scheduler shut down successfully.")
        except Exception as exc:
            logger.warning("Error shutting down scheduler: %s", exc)
        finally:
            _scheduler = None
    else:
        logger.debug("Scheduler was not running — nothing to shut down.")
