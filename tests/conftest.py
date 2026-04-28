"""
tests/conftest.py
==================
Shared pytest fixtures for the KOL Inventory Control Tower test suite.
"""

from unittest.mock import MagicMock
from typing import Any, Dict, List

import pytest


@pytest.fixture
def mock_db_session() -> MagicMock:
    """Return a MagicMock SQLAlchemy session for use in unit tests."""
    return MagicMock()


@pytest.fixture
def sample_products() -> List[Dict[str, Any]]:
    """Return a list of 5 mock product dicts."""
    return [
        {"id": 1, "name": "Toy Car",       "current_stock": 100, "avg_daily_sales": 5.0},
        {"id": 2, "name": "Toy Train",      "current_stock": 50,  "avg_daily_sales": 2.5},
        {"id": 3, "name": "Action Figure",  "current_stock": 0,   "avg_daily_sales": 10.0},
        {"id": 4, "name": "Board Game",     "current_stock": 200, "avg_daily_sales": 0.0},
        {"id": 5, "name": "Puzzle Set",     "current_stock": 30,  "avg_daily_sales": 1.0},
    ]
