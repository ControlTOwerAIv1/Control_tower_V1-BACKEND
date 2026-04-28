"""
tests/test_stockout.py
=======================
Unit tests for services/stockout.py -- stockout prediction logic.
"""

import pytest

from services.stockout import calculate_days_left


class TestCalculateDaysLeft:
    """Tests for the calculate_days_left pure function."""

    def test_zero_stock_zero_sales_flagged_as_risk(self):
        """current_stock=0, avg_daily_sales=0 should return 0.0 (flagged)."""
        result = calculate_days_left(0, 0)
        assert result == 0.0
        # With any positive lead_time, 0.0 <= lead_time is True => risk

    def test_days_left_lte_lead_time_is_risk(self):
        """When days_left <= lead_time_days, the product is at risk."""
        lead_time = 7
        # stock=14, avg=2 => days_left = 7.0, exactly equal to lead_time
        days_left = calculate_days_left(14, 2)
        assert days_left == 7.0
        assert days_left <= lead_time

    def test_days_left_gt_lead_time_not_risk(self):
        """When days_left > lead_time_days, the product is NOT at risk."""
        lead_time = 7
        # stock=100, avg=2 => days_left = 50.0
        days_left = calculate_days_left(100, 2)
        assert days_left == 50.0
        assert days_left > lead_time

    def test_division_by_zero_handled_gracefully(self):
        """avg_daily_sales=0 with positive stock should return inf, not raise."""
        result = calculate_days_left(100, 0)
        assert result == float("inf")

    def test_negative_stock_clamped_to_zero(self):
        """Negative stock should be treated as zero days left."""
        result = calculate_days_left(-5, 2)
        assert result == 0.0

    def test_both_zero_returns_zero(self):
        """Both zero: no stock takes priority over no sales."""
        result = calculate_days_left(0, 0)
        assert result == 0.0
