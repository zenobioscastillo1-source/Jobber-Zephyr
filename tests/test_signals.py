import json
from pathlib import Path

import pytest

from src.signals import FollowUpStrategy, classify

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "fake_quotes.json"


@pytest.fixture
def quotes():
    data = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    return {q["quoteNumber"]: q for q in data["data"]["quotes"]["nodes"]}


class TestStrategyClassification:
    def test_warm_engaged_viewed_high_value(self, quotes):
        # Q-101: viewed + $1,200 (> $500)
        signals = classify(quotes["Q-101"], nudge_history={})
        assert signals.strategy == FollowUpStrategy.WARM_ENGAGED
        assert signals.was_viewed is True
        assert signals.quote_total == 1200.0

    def test_ensure_delivery_not_viewed_high_value(self, quotes):
        # Q-102: not viewed + $950 (> $500)
        signals = classify(quotes["Q-102"], nudge_history={})
        assert signals.strategy == FollowUpStrategy.ENSURE_DELIVERY
        assert signals.was_viewed is False
        assert signals.quote_total == 950.0

    def test_gentle_nudge_viewed_standard_value(self, quotes):
        # Q-103: viewed + $280 (<= $500)
        signals = classify(quotes["Q-103"], nudge_history={})
        assert signals.strategy == FollowUpStrategy.GENTLE_NUDGE
        assert signals.was_viewed is True
        assert signals.quote_total == 280.0

    def test_soft_reminder_not_viewed_standard_value(self, quotes):
        # Q-104: not viewed + $150 (<= $500)
        signals = classify(quotes["Q-104"], nudge_history={})
        assert signals.strategy == FollowUpStrategy.SOFT_REMINDER
        assert signals.was_viewed is False
        assert signals.quote_total == 150.0

    def test_final_check_overrides_on_second_nudge(self, quotes):
        # Q-105: would be WARM_ENGAGED ($600, viewed) but nudge_count=1 → FINAL_CHECK
        nudge_history = {
            "Q-105": {
                "nudge_count": 1,
                "last_nudged_at": "2026-05-31T08:00:00+00:00",
                "strategy_used": "warm_engaged",
            }
        }
        signals = classify(quotes["Q-105"], nudge_history=nudge_history)
        assert signals.strategy == FollowUpStrategy.FINAL_CHECK
        assert signals.nudge_count == 1

    def test_final_check_applies_regardless_of_quadrant(self, quotes):
        # Q-104 would be SOFT_REMINDER but nudge_count=1 → FINAL_CHECK
        nudge_history = {
            "Q-104": {
                "nudge_count": 1,
                "last_nudged_at": "2026-06-03T08:00:00+00:00",
                "strategy_used": "soft_reminder",
            }
        }
        signals = classify(quotes["Q-104"], nudge_history=nudge_history)
        assert signals.strategy == FollowUpStrategy.FINAL_CHECK


class TestEdgeCases:
    def test_zero_dollar_quote_is_soft_reminder(self, quotes):
        # Q-106: $0.00, not viewed → soft_reminder (not high value)
        signals = classify(quotes["Q-106"], nudge_history={})
        assert signals.strategy == FollowUpStrategy.SOFT_REMINDER
        assert signals.quote_total == 0.0

    def test_exactly_at_threshold_is_not_high_value(self, quotes):
        # Clone Q-103 with total exactly at threshold
        quote = {**quotes["Q-103"], "amounts": {**quotes["Q-103"]["amounts"], "total": 500.0}}
        signals = classify(quote, nudge_history={}, high_value_threshold=500.0)
        # 500 is NOT > 500, so not high value → GENTLE_NUDGE (viewed)
        assert signals.strategy == FollowUpStrategy.GENTLE_NUDGE

    def test_just_above_threshold_is_high_value(self, quotes):
        quote = {**quotes["Q-103"], "amounts": {**quotes["Q-103"]["amounts"], "total": 500.01}}
        signals = classify(quote, nudge_history={}, high_value_threshold=500.0)
        assert signals.strategy == FollowUpStrategy.WARM_ENGAGED

    def test_custom_high_value_threshold(self, quotes):
        # With threshold=1000, $950 quote is NOT high value
        signals = classify(quotes["Q-102"], nudge_history={}, high_value_threshold=1000.0)
        assert signals.strategy == FollowUpStrategy.SOFT_REMINDER

    def test_null_first_name_falls_back_to_name(self, quotes):
        quote = {**quotes["Q-101"]}
        quote["client"] = {**quote["client"], "firstName": None, "name": "Marcus Reyes"}
        signals = classify(quote, nudge_history={})
        assert signals.client_name == "Marcus Reyes"

    def test_null_title_falls_back_to_your_project(self, quotes):
        quote = {**quotes["Q-101"], "title": None}
        signals = classify(quote, nudge_history={})
        assert signals.service_type == "your project"

    def test_signals_fields_populated_correctly(self, quotes):
        signals = classify(quotes["Q-101"], nudge_history={})
        assert signals.quote_id == "Q-101"
        assert signals.client_name == "Marcus"
        assert signals.service_type == "Kitchen exhaust fan installation"
        assert signals.days_aging >= 6  # transitionedAt 2026-05-30, at least 6 full days ago
        assert signals.nudge_count == 0
