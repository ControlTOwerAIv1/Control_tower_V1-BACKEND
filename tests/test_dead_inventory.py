"""
tests/test_dead_inventory.py
==============================
Unit tests for services/dead_inventory.py -- dead inventory detection.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from services.dead_inventory import _days_since, get_dead_inventory


class TestDaysSince:
    """Tests for the _days_since helper function."""

    def test_date_older_than_60_days(self):
        """A date 90 days ago should return 90."""
        old_date = date.today() - timedelta(days=90)
        result = _days_since(old_date)
        assert result == 90

    def test_date_within_60_days(self):
        """A date 30 days ago should return 30."""
        recent_date = date.today() - timedelta(days=30)
        result = _days_since(recent_date)
        assert result == 30

    def test_none_date_returns_none(self):
        """None date (never sold) should return None."""
        result = _days_since(None)
        assert result is None

    def test_today_returns_zero(self):
        """Today's date should return 0 days."""
        result = _days_since(date.today())
        assert result == 0


class TestGetDeadInventory:
    """Tests for get_dead_inventory with mocked DB."""

    def _setup_mock_db(self, mock_db, products, stock_rows, last_sold_map):
        """Configure mock DB session for get_dead_inventory."""
        # First call: db.query(Product.id, Product.name, Product.SKU).all()
        product_query = MagicMock()
        product_query.all.return_value = products

        # Second call: warehouse stock query
        stock_query = MagicMock()
        stock_query.group_by.return_value = stock_query
        stock_query.all.return_value = stock_rows

        mock_db.query.side_effect = [product_query, stock_query]

        return last_sold_map

    @patch("services.dead_inventory.get_last_sold_dates")
    def test_product_older_than_60_days_flagged(self, mock_last_sold, mock_db_session):
        """Product with last_sold_date > 60 days ago should be flagged."""
        old_date = date.today() - timedelta(days=90)

        products = [(1, "Old Toy", "SKU-001")]
        stock_rows = [(1, 10)]
        mock_last_sold.return_value = {1: old_date}

        self._setup_mock_db(mock_db_session, products, stock_rows, {1: old_date})

        result = get_dead_inventory(mock_db_session, threshold_days=60)

        assert len(result) == 1
        assert result[0]["product_id"] == 1
        assert result[0]["never_sold"] is False

    @patch("services.dead_inventory.get_last_sold_dates")
    def test_product_within_60_days_not_flagged(self, mock_last_sold, mock_db_session):
        """Product with last_sold_date within 60 days should NOT be flagged."""
        recent_date = date.today() - timedelta(days=30)

        products = [(1, "Fresh Toy", "SKU-002")]
        stock_rows = [(1, 50)]
        mock_last_sold.return_value = {1: recent_date}

        self._setup_mock_db(mock_db_session, products, stock_rows, {1: recent_date})

        result = get_dead_inventory(mock_db_session, threshold_days=60)

        assert len(result) == 0

    @patch("services.dead_inventory.get_last_sold_dates")
    def test_product_never_sold_flagged(self, mock_last_sold, mock_db_session):
        """Product with no sales record should be flagged as dead."""
        products = [(1, "Unsold Toy", "SKU-003")]
        stock_rows = [(1, 100)]
        mock_last_sold.return_value = {}  # No sales record for product 1

        self._setup_mock_db(mock_db_session, products, stock_rows, {})

        result = get_dead_inventory(mock_db_session, threshold_days=60)

        assert len(result) == 1
        assert result[0]["never_sold"] is True

    @patch("services.dead_inventory.get_last_sold_dates")
    def test_threshold_is_60_days(self, mock_last_sold, mock_db_session):
        """Verify the 60-day threshold is correctly applied."""
        # Product sold exactly 59 days ago -> NOT dead
        # Product sold exactly 60 days ago -> IS dead
        date_59 = date.today() - timedelta(days=59)
        date_60 = date.today() - timedelta(days=60)

        products = [(1, "Toy A", "SKU-A"), (2, "Toy B", "SKU-B")]
        stock_rows = [(1, 10), (2, 10)]
        mock_last_sold.return_value = {1: date_59, 2: date_60}

        self._setup_mock_db(mock_db_session, products, stock_rows, {})

        result = get_dead_inventory(mock_db_session, threshold_days=60)

        flagged_ids = [r["product_id"] for r in result]
        assert 1 not in flagged_ids  # 59 days < 60 threshold
        assert 2 in flagged_ids      # 60 days >= 60 threshold
