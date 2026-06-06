from unittest.mock import MagicMock, patch

import pytest

from src.draft import generate_draft, validate_draft
from src.signals import FollowUpStrategy, QuoteSignals


@pytest.fixture
def base_signals():
    return QuoteSignals(
        quote_id="Q-101",
        client_name="Marcus",
        service_type="Kitchen exhaust fan installation",
        quote_total=1200.0,
        days_aging=7,
        was_viewed=True,
        nudge_count=0,
        strategy=FollowUpStrategy.WARM_ENGAGED,
    )


class TestGroundingGate:
    def test_clean_draft_passes(self, base_signals):
        draft = (
            "Hi Marcus, just wanted to follow up on the quote I sent over for your "
            "kitchen exhaust fan. Let me know if you have any questions!"
        )
        passed, reason = validate_draft(draft, base_signals)
        assert passed is True
        assert reason == "OK"

    def test_fail_on_discount_offer(self, base_signals):
        draft = "Hi Marcus, I can offer you a discount if you sign up this week."
        passed, reason = validate_draft(draft, base_signals)
        assert passed is False
        assert "discount" in reason.lower()

    def test_fail_on_percentage_off(self, base_signals):
        draft = "Hi Marcus, we're offering 10% off for new clients this month."
        passed, reason = validate_draft(draft, base_signals)
        assert passed is False
        assert "FAIL" in reason

    def test_fail_on_false_urgency_limited_time(self, base_signals):
        draft = "Hi Marcus, this is a limited time offer — act now!"
        passed, reason = validate_draft(draft, base_signals)
        assert passed is False
        assert "FAIL" in reason

    def test_fail_on_false_urgency_expires(self, base_signals):
        draft = "Hi Marcus, your quote expires at the end of the week."
        passed, reason = validate_draft(draft, base_signals)
        assert passed is False
        assert "FAIL" in reason

    def test_fail_on_last_chance(self, base_signals):
        draft = "Hi Marcus, this is your last chance to get this rate."
        passed, reason = validate_draft(draft, base_signals)
        assert passed is False
        assert "FAIL" in reason

    def test_fail_on_final_offer(self, base_signals):
        draft = "Hi Marcus, this is our final offer on this project."
        passed, reason = validate_draft(draft, base_signals)
        assert passed is False
        assert "FAIL" in reason

    def test_fail_on_tracking_reveal_viewed(self, base_signals):
        draft = "Hi Marcus, I saw you viewed the quote but haven't replied."
        passed, reason = validate_draft(draft, base_signals)
        assert passed is False
        assert "FAIL" in reason

    def test_fail_on_tracking_reveal_opened(self, base_signals):
        draft = "Hi Marcus, I noticed you opened the quote link yesterday."
        passed, reason = validate_draft(draft, base_signals)
        assert passed is False
        assert "FAIL" in reason

    def test_fail_on_our_system_shows(self, base_signals):
        draft = "Hi Marcus, our system shows the quote was received on Monday."
        passed, reason = validate_draft(draft, base_signals)
        assert passed is False
        assert "FAIL" in reason

    def test_multiple_fails_reported_together(self, base_signals):
        draft = "Hi Marcus, limited time discount available — act before it expires!"
        passed, reason = validate_draft(draft, base_signals)
        assert passed is False
        assert reason.count("FAIL") >= 2

    def test_warn_on_over_100_words_does_not_fail(self, base_signals, capsys):
        long_draft = "word " * 101
        passed, reason = validate_draft(long_draft, base_signals)
        assert passed is True
        assert reason == "OK"
        captured = capsys.readouterr()
        assert "WARN" in captured.out

    def test_exactly_100_words_does_not_warn(self, base_signals, capsys):
        draft_100 = "word " * 100
        passed, _ = validate_draft(draft_100.strip(), base_signals)
        assert passed is True
        captured = capsys.readouterr()
        assert "WARN" not in captured.out

    def test_case_insensitive_detection(self, base_signals):
        draft = "Hi Marcus, DISCOUNT available if you respond today."
        passed, _ = validate_draft(draft, base_signals)
        assert passed is False


class TestGenerateDraft:
    def test_generate_draft_calls_anthropic(self, base_signals, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="Hi Marcus, just following up on your quote.")]

        with patch("src.draft.anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create.return_value = mock_message

            result = generate_draft(base_signals, "Reyes Home Services", "Carlo")

        assert result == "Hi Marcus, just following up on your quote."
        mock_client.messages.create.assert_called_once()

    def test_generate_draft_uses_correct_model(self, base_signals, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="Draft text.")]

        with patch("src.draft.anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create.return_value = mock_message

            generate_draft(base_signals, "Reyes Home Services", "Carlo")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_generate_draft_strips_whitespace(self, base_signals, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="  Hi Marcus.  \n")]

        with patch("src.draft.anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create.return_value = mock_message

            result = generate_draft(base_signals, "Reyes Home Services", "Carlo")

        assert result == "Hi Marcus."
