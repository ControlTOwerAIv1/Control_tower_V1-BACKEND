"""
routers/lead_time.py
=====================
Endpoints to read and update the global lead time setting.

This solves Bug #3 permanently — instead of manually seeding the DB,
the user can call PUT /api/lead-time from the frontend or Swagger UI
to set the lead time without touching MySQL Workbench.

Endpoints:
    GET  /api/lead-time         — return the current active lead time
    PUT  /api/lead-time         — set a new lead time (inserts a new row)
    POST /api/lead-time/refresh — rebuild snapshot with the new lead time

Edge cases handled:
    - lead_time_setting table is empty → returns default 7 with flag
    - days value is non-numeric → returns 400
    - days value <= 0 → returns 400
    - DB write fails → returns 500

Input validations:
    - days must be a positive integer
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from cache.context_builder import refresh_context
from cache.snapshot import get_snapshot, refresh_snapshot
from models import LeadTimeSetting
from services.avg_daily_sales import get_global_lead_time

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lead-time", tags=["Lead Time"])


# ---------------------------------------------------------------------------
# DB dependency placeholder (overridden via app.dependency_overrides in main)
# ---------------------------------------------------------------------------

def _get_db():
    raise NotImplementedError(
        "Database session dependency not configured. "
        "Override via app.dependency_overrides."
    )


get_db = _get_db


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class LeadTimeUpdateRequest(BaseModel):
    days: int

    @field_validator("days")
    @classmethod
    def days_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"days must be a positive integer, got {v}")
        return v


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=Dict[str, Any])
async def get_lead_time(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Return the current active global lead time.

    Returns:
        Dict with lead_time_days and whether it is a default fallback.
    """
    lead_time = get_global_lead_time(db)

    # Check if the table is actually populated
    latest = (
        db.query(LeadTimeSetting)
        .order_by(LeadTimeSetting.id.desc())
        .first()
    )

    return {
        "lead_time_days": lead_time,
        "is_default_fallback": latest is None,
        "source": "database" if latest is not None else "hardcoded_default",
    }


@router.put("", response_model=Dict[str, Any])
async def update_lead_time(
    body: LeadTimeUpdateRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Insert a new lead time setting row.

    The most recent row (highest id) is always used as the active setting.
    Old rows are kept for audit history.

    Args:
        body: LeadTimeUpdateRequest with a positive integer 'days' field.

    Returns:
        Confirmation dict with the new lead time.
    """
    try:
        new_row = LeadTimeSetting(days=str(body.days))
        db.add(new_row)
        db.commit()
        db.refresh(new_row)

        logger.info(
            "Lead time updated to %d days (id=%d).", body.days, new_row.id
        )

        return {
            "status": "updated",
            "lead_time_days": body.days,
            "record_id": new_row.id,
            "message": (
                f"Lead time set to {body.days} days. "
                "Call POST /api/lead-time/refresh to apply to the snapshot."
            ),
        }

    except Exception as exc:
        db.rollback()
        logger.error("Failed to update lead time: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update lead time: {exc}",
        ) from exc


@router.post("/refresh", response_model=Dict[str, Any])
async def refresh_snapshot_with_new_lead_time(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Rebuild the snapshot after a lead time change.

    Call this after PUT /api/lead-time to apply the new lead time
    to all calculations immediately without waiting for the scheduler.

    Returns:
        Confirmation dict with the new snapshot timestamp.
    """
    try:
        refresh_snapshot(db)
        snapshot = get_snapshot()
        refresh_context(snapshot)

        logger.info("Snapshot refreshed after lead time update.")

        return {
            "status": "success",
            "message": "Snapshot rebuilt with new lead time.",
            "generated_at": snapshot.get("generated_at", "unknown"),
        }

    except Exception as exc:
        logger.error("Snapshot refresh after lead time update failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Snapshot refresh failed: {exc}",
        ) from exc