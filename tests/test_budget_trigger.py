"""Tests for budget/trigger.py."""

from budget.trigger import is_budget_mode


class TestIsBudgetMode:
    """Tests for is_budget_mode()."""

    def test_is_budget_mode_true(self):
        """reasoning_effort='budget' returns True."""
        assert is_budget_mode({"reasoning_effort": "budget"}) is True

    def test_is_budget_mode_false_high(self):
        """reasoning_effort='high' returns False."""
        assert is_budget_mode({"reasoning_effort": "high"}) is False

    def test_is_budget_mode_false_missing(self):
        """no reasoning_effort returns False."""
        assert is_budget_mode({}) is False

    def test_is_budget_mode_false_empty(self):
        """reasoning_effort='' returns False."""
        assert is_budget_mode({"reasoning_effort": ""}) is False

    def test_is_budget_mode_false_low(self):
        """reasoning_effort='low' returns False."""
        assert is_budget_mode({"reasoning_effort": "low"}) is False
