import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src.tracker import load_log, record_nudge, save_log, seed_from_sheet, should_skip


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class TestLoadAndSaveLog:
    def test_load_returns_empty_dict_when_file_missing(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        assert load_log(path) == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "nudge_log.json")
        log = {
            "Q-101": {
                "nudge_count": 1,
                "last_nudged_at": _days_ago(5),
                "strategy_used": "warm_engaged",
            }
        }
        save_log(log, path)
        loaded = load_log(path)
        assert loaded == log

    def test_save_creates_file(self, tmp_path):
        path = str(tmp_path / "nudge_log.json")
        save_log({}, path)
        assert os.path.exists(path)


class TestShouldSkip:
    def test_new_quote_not_in_log_is_not_skipped(self):
        skip, reason = should_skip("Q-NEW", log={}, max_nudges=2, min_days=3)
        assert skip is False
        assert reason == ""

    def test_max_nudges_reached_skips(self):
        log = {
            "Q-101": {
                "nudge_count": 2,
                "last_nudged_at": _days_ago(10),
                "strategy_used": "warm_engaged",
            }
        }
        skip, reason = should_skip("Q-101", log=log, max_nudges=2, min_days=3)
        assert skip is True
        assert "max nudges" in reason

    def test_one_below_max_is_not_skipped(self):
        log = {
            "Q-101": {
                "nudge_count": 1,
                "last_nudged_at": _days_ago(10),
                "strategy_used": "warm_engaged",
            }
        }
        skip, _ = should_skip("Q-101", log=log, max_nudges=2, min_days=3)
        assert skip is False

    def test_nudged_too_recently_skips(self):
        log = {
            "Q-102": {
                "nudge_count": 1,
                "last_nudged_at": _days_ago(1),
                "strategy_used": "ensure_delivery",
            }
        }
        skip, reason = should_skip("Q-102", log=log, max_nudges=2, min_days=3)
        assert skip is True
        assert "nudged too recently" in reason

    def test_nudged_exactly_at_min_days_is_not_skipped(self):
        log = {
            "Q-102": {
                "nudge_count": 1,
                "last_nudged_at": _days_ago(3),
                "strategy_used": "ensure_delivery",
            }
        }
        skip, _ = should_skip("Q-102", log=log, max_nudges=2, min_days=3)
        # timedelta(days=3) is NOT < timedelta(days=3), so not skipped
        assert skip is False

    def test_both_limits_max_nudges_takes_precedence(self):
        # At max nudges AND recently nudged — both would block, max_nudges check runs first
        log = {
            "Q-103": {
                "nudge_count": 2,
                "last_nudged_at": _days_ago(1),
                "strategy_used": "soft_reminder",
            }
        }
        skip, reason = should_skip("Q-103", log=log, max_nudges=2, min_days=3)
        assert skip is True
        assert "max nudges" in reason

    def test_min_days_one_means_daily_nudges_allowed(self):
        log = {
            "Q-104": {
                "nudge_count": 1,
                "last_nudged_at": _days_ago(2),
                "strategy_used": "gentle_nudge",
            }
        }
        skip, _ = should_skip("Q-104", log=log, max_nudges=5, min_days=1)
        assert skip is False


class TestRecordNudge:
    def test_new_quote_initialized_with_count_one(self):
        updated = record_nudge("Q-NEW", "warm_engaged", log={})
        assert updated["Q-NEW"]["nudge_count"] == 1
        assert updated["Q-NEW"]["strategy_used"] == "warm_engaged"
        assert "last_nudged_at" in updated["Q-NEW"]

    def test_existing_quote_increments_count(self):
        log = {
            "Q-101": {
                "nudge_count": 1,
                "last_nudged_at": _days_ago(5),
                "strategy_used": "warm_engaged",
            }
        }
        updated = record_nudge("Q-101", "final_check", log=log)
        assert updated["Q-101"]["nudge_count"] == 2
        assert updated["Q-101"]["strategy_used"] == "final_check"

    def test_record_nudge_does_not_mutate_original_log(self):
        log = {}
        updated = record_nudge("Q-NEW", "soft_reminder", log=log)
        assert "Q-NEW" not in log
        assert "Q-NEW" in updated

    def test_other_quotes_preserved_after_record(self):
        log = {
            "Q-101": {"nudge_count": 1, "last_nudged_at": _days_ago(5), "strategy_used": "warm_engaged"}
        }
        updated = record_nudge("Q-102", "gentle_nudge", log=log)
        assert "Q-101" in updated
        assert updated["Q-101"]["nudge_count"] == 1

    def test_last_nudged_at_is_recent(self):
        before = datetime.now(timezone.utc)
        updated = record_nudge("Q-NEW", "soft_reminder", log={})
        after = datetime.now(timezone.utc)

        recorded = datetime.fromisoformat(updated["Q-NEW"]["last_nudged_at"])
        assert before <= recorded <= after


class TestSeedFromSheet:
    def _make_service(self, rows: list[list]) -> MagicMock:
        mock_service = MagicMock()
        (
            mock_service.spreadsheets()
            .values()
            .get()
            .execute
            .return_value
        ) = {"values": rows}
        return mock_service

    def test_empty_sheet_returns_empty_log(self):
        service = self._make_service([])
        log = seed_from_sheet(service, "sheet-id")
        assert log == {}

    def test_single_row_builds_entry(self):
        rows = [["Q-101", "Marcus", "Kitchen fan", "$1200.00", "warm_engaged", "1", "2026-06-01T08:00:00+00:00"]]
        service = self._make_service(rows)
        log = seed_from_sheet(service, "sheet-id")
        assert "Q-101" in log
        assert log["Q-101"]["nudge_count"] == 1
        assert log["Q-101"]["strategy_used"] == "warm_engaged"
        assert log["Q-101"]["last_nudged_at"] == "2026-06-01T08:00:00+00:00"

    def test_multiple_rows_same_quote_keeps_highest_nudge_count(self):
        rows = [
            ["Q-101", "Marcus", "Kitchen fan", "$1200.00", "warm_engaged", "1", "2026-06-01T08:00:00+00:00"],
            ["Q-101", "Marcus", "Kitchen fan", "$1200.00", "final_check", "2", "2026-06-05T08:00:00+00:00"],
        ]
        service = self._make_service(rows)
        log = seed_from_sheet(service, "sheet-id")
        assert log["Q-101"]["nudge_count"] == 2
        assert log["Q-101"]["strategy_used"] == "final_check"
        assert log["Q-101"]["last_nudged_at"] == "2026-06-05T08:00:00+00:00"

    def test_multiple_quotes_all_seeded(self):
        rows = [
            ["Q-101", "Marcus", "Kitchen fan", "$1200.00", "warm_engaged", "1", "2026-06-01T08:00:00+00:00"],
            ["Q-102", "Diane", "Water filter", "$950.00", "ensure_delivery", "1", "2026-06-02T08:00:00+00:00"],
        ]
        service = self._make_service(rows)
        log = seed_from_sheet(service, "sheet-id")
        assert "Q-101" in log
        assert "Q-102" in log

    def test_short_rows_skipped_without_error(self):
        rows = [
            ["Q-101", "Marcus"],  # too short
            ["Q-102", "Diane", "Water filter", "$950.00", "ensure_delivery", "1", "2026-06-02T08:00:00+00:00"],
        ]
        service = self._make_service(rows)
        log = seed_from_sheet(service, "sheet-id")
        assert "Q-101" not in log
        assert "Q-102" in log
