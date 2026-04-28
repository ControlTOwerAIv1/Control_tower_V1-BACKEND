"""
tests/test_avg_daily_sales.py
==============================
Unit tests for services/avg_daily_sales.py -- compute_avg_daily_sales logic.
"""

from unittest.mock import MagicMock, patch

import pytest

from services.avg_daily_sales import get_avg_daily_sales, _compute_avg


class TestComputeAvg:
    """Tests for the _compute_avg helper."""

    def test_none_total_returns_zero(self):
        """Total sold of None should return 0.0."""
        assert _compute_avg(None, 30) == 0.0

    def test_zero_total_returns_zero(self):
        """Total sold of 0 should return 0.0."""
        assert _compute_avg(0, 30) == 0.0

    def test_normal_calculation(self):
        """Average should be total_sold / days, rounded to 4 decimals."""
        assert _compute_avg(150, 30) == 5.0
        assert _compute_avg(100, 30) == round(100 / 30, 4)


class TestGetAvgDailySales:
    """Tests for get_avg_daily_sales using a mocked DB session."""

    def test_zero_sales_rows_all_products_get_zero(self, mock_db_session):
        """When DB returns no sales rows, all products should have avg 0.0."""
        # Mock: db.query(Product.id).all() returns 3 product IDs
        product_query = MagicMock()
        product_query.all.return_value = [(1,), (2,), (3,)]

        # Mock: sales query returns empty list (no sales in window)
        sales_chain = MagicMock()
        sales_chain.join.return_value = sales_chain
        sales_chain.filter.return_value = sales_chain
        sales_chain.group_by.return_value = sales_chain
        sales_chain.all.return_value = []

        # db.query() should return product_query first, then sales_chain
        mock_db_session.query.side_effect = [product_query, sales_chain]

        result = get_avg_daily_sales(mock_db_session, days=30)

        assert result == {1: 0.0, 2: 0.0, 3: 0.0}

    def test_sales_data_for_three_products(self, mock_db_session):
        """Sales data for 3 products should produce correct averages."""
        product_query = MagicMock()
        product_query.all.return_value = [(1,), (2,), (3,)]

        # Product 1: 300 units in 30 days = 10.0/day
        # Product 2: 150 units in 30 days = 5.0/day
        # Product 3: 90 units in 30 days = 3.0/day
        sales_chain = MagicMock()
        sales_chain.join.return_value = sales_chain
        sales_chain.filter.return_value = sales_chain
        sales_chain.group_by.return_value = sales_chain
        sales_chain.all.return_value = [
            (1, 300),
            (2, 150),
            (3, 90),
        ]

        mock_db_session.query.side_effect = [product_query, sales_chain]

        result = get_avg_daily_sales(mock_db_session, days=30)

        assert result[1] == round(300 / 30, 4)
        assert result[2] == round(150 / 30, 4)
        assert result[3] == round(90 / 30, 4)

    def test_product_with_no_matching_sales_defaults_to_zero(self, mock_db_session):
        """A product not in the sales result should default to 0.0."""
        product_query = MagicMock()
        product_query.all.return_value = [(1,), (2,), (3,)]

        # Only product 1 has sales
        sales_chain = MagicMock()
        sales_chain.join.return_value = sales_chain
        sales_chain.filter.return_value = sales_chain
        sales_chain.group_by.return_value = sales_chain
        sales_chain.all.return_value = [(1, 60)]

        mock_db_session.query.side_effect = [product_query, sales_chain]

        result = get_avg_daily_sales(mock_db_session, days=30)

        assert result[1] == round(60 / 30, 4)
        assert result[2] == 0.0
        assert result[3] == 0.0
