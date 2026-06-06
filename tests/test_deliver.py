from unittest.mock import MagicMock, patch

import pytest

from src.deliver import get_approved_drafts, mark_sent, send_draft


def _make_sheets_service(rows: list[list]) -> MagicMock:
    service = MagicMock()
    (
        service.spreadsheets()
        .values()
        .get()
        .execute
        .return_value
    ) = {"values": rows}
    return service


class TestGetApprovedDrafts:
    def test_returns_approved_rows(self):
        rows = [
            ["Q-101", "Marcus", "Kitchen fan", "$1200.00", "7", "Yes", "warm_engaged",
             "Hi Marcus, just checking in.", "APPROVED", ""],
            ["Q-102", "Diane", "Water filter", "$950.00", "6", "No", "ensure_delivery",
             "Hi Diane, wanted to make sure.", "PENDING", ""],
        ]
        service = _make_sheets_service(rows)
        approved = get_approved_drafts(service, "sheet-id")
        assert len(approved) == 1
        assert approved[0]["row"]["quote_number"] == "Q-101"

    def test_returns_edited_rows(self):
        rows = [
            ["Q-103", "Leo", "Ceiling fan", "$280.00", "8", "Yes", "gentle_nudge",
             "Hi Leo, following up.", "EDITED", ""],
        ]
        service = _make_sheets_service(rows)
        approved = get_approved_drafts(service, "sheet-id")
        assert len(approved) == 1
        assert approved[0]["row"]["status"] == "EDITED"

    def test_skips_pending_rows(self):
        rows = [
            ["Q-104", "Carmen", "Drain snake", "$150.00", "4", "No", "soft_reminder",
             "Hi Carmen, just checking.", "PENDING", ""],
        ]
        service = _make_sheets_service(rows)
        approved = get_approved_drafts(service, "sheet-id")
        assert len(approved) == 0

    def test_skips_sent_rows(self):
        rows = [
            ["Q-101", "Marcus", "Kitchen fan", "$1200.00", "7", "Yes", "warm_engaged",
             "Hi Marcus.", "SENT", "2026-06-06T08:00:00Z"],
        ]
        service = _make_sheets_service(rows)
        approved = get_approved_drafts(service, "sheet-id")
        assert len(approved) == 0

    def test_skips_rejected_rows(self):
        rows = [
            ["Q-105", "Felix", "HVAC plan", "$600.00", "9", "Yes", "final_check",
             "Hi Felix.", "REJECTED", ""],
        ]
        service = _make_sheets_service(rows)
        approved = get_approved_drafts(service, "sheet-id")
        assert len(approved) == 0

    def test_row_index_is_1_based_with_header_offset(self):
        rows = [
            ["Q-101", "Marcus", "Kitchen fan", "$1200.00", "7", "Yes", "warm_engaged",
             "Hi Marcus.", "APPROVED", ""],
            ["Q-102", "Diane", "Water filter", "$950.00", "6", "No", "ensure_delivery",
             "Hi Diane.", "APPROVED", ""],
        ]
        service = _make_sheets_service(rows)
        approved = get_approved_drafts(service, "sheet-id")
        assert approved[0]["row_index"] == 2  # row 1 = header, data starts at row 2
        assert approved[1]["row_index"] == 3

    def test_empty_sheet_returns_empty_list(self):
        service = _make_sheets_service([])
        approved = get_approved_drafts(service, "sheet-id")
        assert approved == []

    def test_status_matching_is_case_insensitive(self):
        rows = [
            ["Q-101", "Marcus", "Kitchen fan", "$1200.00", "7", "Yes", "warm_engaged",
             "Hi Marcus.", "approved", ""],
        ]
        service = _make_sheets_service(rows)
        approved = get_approved_drafts(service, "sheet-id")
        assert len(approved) == 1

    def test_short_row_skipped(self):
        rows = [["Q-101", "Marcus"]]  # too short to have status
        service = _make_sheets_service(rows)
        approved = get_approved_drafts(service, "sheet-id")
        assert len(approved) == 0


class TestSendDraft:
    def test_returns_true_on_202(self):
        row = {
            "quote_number": "Q-101",
            "client": "Marcus",
            "client_email": "marcus@example.com",
            "service": "Kitchen fan",
            "draft": "Hi Marcus, just checking in on the quote.",
        }
        mock_response = MagicMock()
        mock_response.status_code = 202

        with patch("src.deliver.sendgrid.SendGridAPIClient") as mock_sg_cls:
            mock_sg = MagicMock()
            mock_sg_cls.return_value = mock_sg
            mock_sg.send.return_value = mock_response

            result = send_draft(row, "from@example.com", "test-sg-key")

        assert result is True
        mock_sg.send.assert_called_once()

    def test_returns_false_on_non_202(self):
        row = {
            "client_email": "marcus@example.com",
            "service": "Kitchen fan",
            "draft": "Hi Marcus.",
        }
        mock_response = MagicMock()
        mock_response.status_code = 400

        with patch("src.deliver.sendgrid.SendGridAPIClient") as mock_sg_cls:
            mock_sg = MagicMock()
            mock_sg_cls.return_value = mock_sg
            mock_sg.send.return_value = mock_response

            result = send_draft(row, "from@example.com", "test-sg-key")

        assert result is False

    def test_returns_false_when_no_client_email(self, capsys):
        row = {
            "client": "Marcus",
            "service": "Kitchen fan",
            "draft": "Hi Marcus.",
        }
        result = send_draft(row, "from@example.com", "test-sg-key")
        assert result is False
        captured = capsys.readouterr()
        assert "No email" in captured.out


class TestMarkSent:
    def test_writes_sent_status_and_timestamp(self):
        service = MagicMock()
        mark_sent(service, "sheet-id", row_index=3)

        update_call = service.spreadsheets().values().update
        update_call.assert_called_once()
        call_kwargs = update_call.call_args.kwargs
        assert call_kwargs["range"] == "Pending Drafts!I3:J3"
        values = call_kwargs["body"]["values"][0]
        assert values[0] == "SENT"
        assert "T" in values[1]  # ISO timestamp format
