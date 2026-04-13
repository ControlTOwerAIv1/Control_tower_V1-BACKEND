"""
main.py
========
Entry point for the KOL Inventory Control Tower FastAPI backend.
"""

import os
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

try:
    from database import SessionLocal, get_db as db_dependency
    logger.info("✓ database module loaded.")
except ImportError as exc:
    logger.critical("FAILED to import database module: %s", exc, exc_info=True)
    raise

try:
    from cache.snapshot import build_snapshot, get_snapshot, refresh_snapshot
    logger.info("✓ cache.snapshot module loaded.")
except ImportError as exc:
    logger.critical("FAILED to import cache.snapshot module: %s", exc, exc_info=True)
    raise

try:
    from cache.context_builder import get_current_context, refresh_context
    logger.info("✓ cache.context_builder module loaded.")
except ImportError as exc:
    logger.critical("FAILED to import cache.context_builder module: %s", exc, exc_info=True)
    raise

try:
    from alerts.scheduler import start_scheduler
    logger.info("✓ alerts.scheduler module loaded.")
except ImportError as exc:
    logger.critical("FAILED to import alerts.scheduler module: %s", exc, exc_info=True)
    raise

try:
    from routers.inventory import router as inventory_router
    from routers.inventory import _get_db as _inventory_db_placeholder
    logger.info("✓ routers.inventory module loaded.")
except ImportError as exc:
    logger.critical("FAILED to import routers.inventory module: %s", exc, exc_info=True)
    raise

try:
    from routers.alerts import router as alerts_router
    logger.info("✓ routers.alerts module loaded.")
except ImportError as exc:
    logger.critical("FAILED to import routers.alerts module: %s", exc, exc_info=True)
    raise

try:
    from routers.chat import router as chat_router
    logger.info("✓ routers.chat module loaded.")
except ImportError as exc:
    logger.critical("FAILED to import routers.chat module: %s", exc, exc_info=True)
    raise


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("=" * 60)
    logger.info("KOL Inventory Control Tower - Starting up")
    logger.info("=" * 60)

    db = None
    try:
        db = SessionLocal()
        logger.info("Startup: DB session created.")

        # Temporary diagnostic - remove after Bug #2 is confirmed fixed
        from services.dead_inventory import run_dead_inventory_diagnostic
        run_dead_inventory_diagnostic(db)

        snapshot = build_snapshot(db)
        logger.info(
            "Startup: Snapshot built successfully at %s.",
            snapshot.get("generated_at", "unknown"),
        )

        refresh_context(snapshot)
        logger.info("Startup: AI context string built.")

    except Exception as exc:
        logger.error(
            "Startup: Snapshot build FAILED (non-fatal): %s. "
            "The app will start but data endpoints will return 503 "
            "until the next scheduled refresh succeeds.",
            exc,
            exc_info=True,
        )
    finally:
        if db is not None:
            try:
                db.close()
                logger.info("Startup: DB session closed.")
            except Exception as close_exc:
                logger.warning(
                    "Startup: Failed to close DB session (non-fatal): %s",
                    close_exc,
                )

    try:
        start_scheduler(SessionLocal)
        logger.info("Startup: Background scheduler started.")
    except Exception as exc:
        logger.error(
            "Startup: Scheduler failed to start (non-fatal): %s",
            exc,
            exc_info=True,
        )

    logger.info("=" * 60)
    logger.info("KOL Inventory Control Tower - Ready to serve requests")
    logger.info("=" * 60)

    yield

    logger.info("=" * 60)
    logger.info("KOL Inventory Control Tower - Shutting down gracefully")
    logger.info("=" * 60)


app = FastAPI(
    title="KOL Inventory Control Tower API",
    version="1.0.0",
    description="AI-powered inventory monitoring for KOL Distributor Toys",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.dependency_overrides[_inventory_db_placeholder] = db_dependency
logger.info("✓ DB dependency override registered for inventory router.")

app.include_router(inventory_router)
app.include_router(alerts_router)
app.include_router(chat_router)


@app.get("/", tags=["Health"])
async def root() -> Dict[str, str]:
    return {
        "status": "running",
        "app": "KOL Inventory Control Tower",
    }


@app.get("/chat", tags=["UI"])
async def chat_ui() -> FileResponse:
    chat_ui_path = os.path.join(STATIC_DIR, "chat-ui", "index.html")
    if not os.path.isfile(chat_ui_path):
        raise HTTPException(status_code=404, detail="Chat UI file not found.")
    return FileResponse(chat_ui_path)


@app.get("/health", tags=["Health"])
async def health_check() -> Dict[str, Any]:
    snapshot_available = False
    context_available = False

    try:
        get_snapshot()
        snapshot_available = True
    except RuntimeError:
        pass

    try:
        get_current_context()
        context_available = True
    except RuntimeError:
        pass

    return {
        "status": "ok",
        "snapshot_available": snapshot_available,
        "context_available": context_available,
    }