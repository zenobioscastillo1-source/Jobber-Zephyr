import os
from datetime import datetime, timezone

import sendgrid
from sendgrid.helpers.mail import Mail

from .write import PENDING_DRAFTS_TAB

# Column indices in the Pending Drafts tab (0-based)
_COL_QUOTE = 0
_COL_CLIENT = 1
_COL_SERVICE = 2
_COL_AMOUNT = 3
_COL_DAYS = 4
_COL_VIEWED = 5
_COL_STRATEGY = 6
_COL_DRAFT = 7
_COL_STATUS = 8
_COL_APPROVED_AT = 9

_SENDABLE_STATUSES = {"APPROVED", "EDITED"}


def get_approved_drafts(service, sheet_id: str) -> list[dict]:
    """Read the Pending Drafts tab and return rows with Status APPROVED or EDITED.

    Returns a list of dicts with keys: row_index (1-based Sheet row), row (column dict),
    client_email (looked up from row data when available).
    """
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=f"{PENDING_DRAFTS_TAB}!A2:J")
        .execute()
    )
    rows = result.get("values", [])

    approved = []
    for i, row in enumerate(rows):
        if len(row) <= _COL_STATUS:
            continue
        status = row[_COL_STATUS].strip().upper()
        if status not in _SENDABLE_STATUSES:
            continue

        approved.append({
            "row_index": i + 2,  # +2: 1-based index + skip header row
            "row": {
                "quote_number": row[_COL_QUOTE] if len(row) > _COL_QUOTE else "",
                "client": row[_COL_CLIENT] if len(row) > _COL_CLIENT else "",
                "service": row[_COL_SERVICE] if len(row) > _COL_SERVICE else "",
                "amount": row[_COL_AMOUNT] if len(row) > _COL_AMOUNT else "",
                "draft": row[_COL_DRAFT] if len(row) > _COL_DRAFT else "",
                "status": status,
            },
        })

    return approved


def send_draft(row: dict, from_email: str, sendgrid_api_key: str) -> bool:
    """Send one approved draft via SendGrid.

    The row dict must contain 'client' (name used as To: display name) and 'draft'.
    Client email is not stored in the Sheet — the owner must supply it or this
    function is extended to look it up from Jobber. For Phase 2 the owner copies
    the approved draft; this function handles the actual send when wired up.

    Returns True on HTTP 202, False otherwise.
    """
    client_email = row.get("client_email", "")
    if not client_email:
        print(f"[deliver] No email for {row.get('client', '?')} — skipping send")
        return False

    message = Mail(
        from_email=from_email,
        to_emails=client_email,
        subject=f"Following up on your quote — {row.get('service', 'your project')}",
        plain_text_content=row["draft"],
    )

    sg = sendgrid.SendGridAPIClient(api_key=sendgrid_api_key)
    response = sg.send(message)
    return response.status_code == 202


def mark_sent(service, sheet_id: str, row_index: int) -> None:
    """Update the row's Status to SENT and write the Approved At timestamp."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    range_notation = f"{PENDING_DRAFTS_TAB}!I{row_index}:J{row_index}"
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=range_notation,
        valueInputOption="RAW",
        body={"values": [["SENT", timestamp]]},
    ).execute()
