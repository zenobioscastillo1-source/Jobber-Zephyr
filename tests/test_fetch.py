import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.fetch import fetch_all_aging_quotes, is_aging

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "fake_quotes.json"


@pytest.fixture
def fake_quotes():
    data = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    return data["data"]["quotes"]["nodes"]


def _make_quote(days_old: int) -> dict:
    transitioned = datetime.now(timezone.utc) - timedelta(days=days_old)
    return {
        "quoteNumber": "Q-TEST",
        "transitionedAt": transitioned.isoformat(),
        "amounts": {"total": 100.0},
        "client": {"firstName": "Test", "name": "Test User"},
        "clientHubViewedAt": None,
        "title": "Test service",
    }


class TestIsAging:
    def test_quote_older_than_threshold_is_aging(self):
        quote = _make_quote(days_old=4)
        assert is_aging(quote, threshold_days=3) is True

    def test_quote_just_under_threshold_is_not_aging(self):
        # A quote that is 10 seconds shy of the threshold is not aging
        transitioned = datetime.now(timezone.utc) - timedelta(days=3) + timedelta(seconds=10)
        quote = {"quoteNumber": "Q-TEST", "transitionedAt": transitioned.isoformat()}
        assert is_aging(quote, threshold_days=3) is False

    def test_quote_younger_than_threshold_is_not_aging(self):
        quote = _make_quote(days_old=1)
        assert is_aging(quote, threshold_days=3) is False

    def test_quote_much_older_is_aging(self):
        quote = _make_quote(days_old=30)
        assert is_aging(quote, threshold_days=3) is True

    def test_configurable_threshold(self):
        quote = _make_quote(days_old=2)
        assert is_aging(quote, threshold_days=1) is True
        assert is_aging(quote, threshold_days=3) is False

    def test_naive_datetime_handled(self):
        # Jobber may return datetimes without timezone info
        transitioned = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)).isoformat()
        quote = {"quoteNumber": "Q-X", "transitionedAt": transitioned}
        assert is_aging(quote, threshold_days=3) is True


class TestFetchAllAgingQuotes:
    def test_returns_only_aging_quotes(self, fake_quotes):
        # Q-101 through Q-106 have transitionedAt dates varying from ~3 to ~11 days ago
        # relative to 2026-06-06. Threshold=3 means >3 days old.
        # Q-104 was set to 2026-06-02 (4 days ago) — should be included.
        # All 6 fixtures are >3 days old relative to 2026-06-06.
        single_page = {
            "data": {
                "quotes": {
                    "nodes": fake_quotes,
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }
        mock_response = MagicMock()
        mock_response.json.return_value = single_page
        mock_response.raise_for_status.return_value = None

        with patch("src.fetch.httpx.post", return_value=mock_response):
            results = fetch_all_aging_quotes("fake-token", threshold_days=3)

        assert len(results) == 6

    def test_filters_out_recent_quotes(self, fake_quotes):
        # Insert a quote only 1 day old
        recent = _make_quote(days_old=1)
        recent["quoteNumber"] = "Q-NEW"
        nodes = fake_quotes + [recent]

        single_page = {
            "data": {
                "quotes": {
                    "nodes": nodes,
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }
        mock_response = MagicMock()
        mock_response.json.return_value = single_page
        mock_response.raise_for_status.return_value = None

        with patch("src.fetch.httpx.post", return_value=mock_response):
            results = fetch_all_aging_quotes("fake-token", threshold_days=3)

        quote_numbers = [q["quoteNumber"] for q in results]
        assert "Q-NEW" not in quote_numbers
        assert len(results) == 6

    def test_pagination_fetches_all_pages(self, fake_quotes):
        page1_quotes = fake_quotes[:3]
        page2_quotes = fake_quotes[3:]

        page1 = {
            "data": {
                "quotes": {
                    "nodes": page1_quotes,
                    "pageInfo": {"hasNextPage": True, "endCursor": "cursor-abc"},
                }
            }
        }
        page2 = {
            "data": {
                "quotes": {
                    "nodes": page2_quotes,
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }

        responses = [MagicMock(), MagicMock()]
        responses[0].json.return_value = page1
        responses[0].raise_for_status.return_value = None
        responses[1].json.return_value = page2
        responses[1].raise_for_status.return_value = None

        with patch("src.fetch.httpx.post", side_effect=responses) as mock_post:
            results = fetch_all_aging_quotes("fake-token", threshold_days=3)

        assert mock_post.call_count == 2
        assert len(results) == 6

    def test_second_page_request_includes_cursor(self, fake_quotes):
        page1 = {
            "data": {
                "quotes": {
                    "nodes": fake_quotes[:1],
                    "pageInfo": {"hasNextPage": True, "endCursor": "cursor-xyz"},
                }
            }
        }
        page2 = {
            "data": {
                "quotes": {
                    "nodes": fake_quotes[1:2],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }

        responses = [MagicMock(), MagicMock()]
        responses[0].json.return_value = page1
        responses[0].raise_for_status.return_value = None
        responses[1].json.return_value = page2
        responses[1].raise_for_status.return_value = None

        with patch("src.fetch.httpx.post", side_effect=responses) as mock_post:
            fetch_all_aging_quotes("fake-token", threshold_days=3)

        second_call_kwargs = mock_post.call_args_list[1].kwargs
        variables = second_call_kwargs["json"]["variables"]
        assert variables["cursor"] == "cursor-xyz"
