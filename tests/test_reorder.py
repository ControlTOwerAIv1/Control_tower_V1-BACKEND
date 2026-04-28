"""
tests/test_reorder.py
======================
Unit tests for services/reorder.py -- reorder calculation logic.
"""

import pytest

from services.reorder import calculate_reorder_quantity, calculate_reorder_point


class TestCalculateReorderQuantity:
    """Tests for the calculate_reorder_quantity pure function."""

    def test_reorder_quantity_formula(self):
        """Formula: (avg * (lead_time + buffer)) - current_stock."""
        # avg=10, lead_time=7, buffer=7, stock=50
        # Expected: (10 * (7 + 7)) - 50 = 140 - 50 = 90
        result = calculate_reorder_quantity(
            avg_daily_sales=10.0,
            lead_time=7,
            current_stock=50.0,
            buffer_days=7,
        )
        assert result == 90.0

    def test_reorder_quantity_never_negative(self):
        """If formula produces negative (overstocked), result must be 0."""
        # avg=1, lead_time=5, buffer=5, stock=500
        # Expected: (1 * (5 + 5)) - 500 = 10 - 500 = -490 => clamped to 0
        result = calculate_reorder_quantity(
            avg_daily_sales=1.0,
            lead_time=5,
            current_stock=500.0,
            buffer_days=5,
        )
        assert result == 0.0

    def test_zero_avg_daily_sales_no_error(self):
        """avg_daily_sales=0 must not raise and must return a valid number."""
        result = calculate_reorder_quantity(
            avg_daily_sales=0.0,
            lead_time=7,
            current_stock=100.0,
            buffer_days=7,
        )
        # (0 * 14) - 100 = -100 => clamped to 0
        assert result == 0.0

    def test_zero_stock_gives_full_target(self):
        """With zero stock, reorder qty equals the full target stock."""
        result = calculate_reorder_quantity(
            avg_daily_sales=5.0,
            lead_time=7,
            current_stock=0.0,
            buffer_days=7,
        )
        # (5 * 14) - 0 = 70
        assert result == 70.0


class TestCalculateReorderPoint:
    """Tests for the calculate_reorder_point pure function."""

    def test_basic_reorder_point(self):
        """Reorder point = avg * lead_time."""
        result = calculate_reorder_point(avg_daily_sales=5.0, lead_time=7)
        assert result == 35.0

    def test_zero_avg_gives_zero_point(self):
        """Zero avg daily sales means reorder point is 0."""
        result = calculate_reorder_point(avg_daily_sales=0.0, lead_time=7)
        assert result == 0.0
