import json
from datetime import datetime, timezone

from google.oauth2 import service_account
from googleapiclient.discovery import build

from .signals import QuoteSignals

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

PENDING_DRAFTS_TAB = "Pending Drafts"
NUDGE_LOG_TAB = "Nudge Log"

PENDING_DRAFTS_HEADER = [
    "Quote #", "Client", "Service", "Amount", "Days Aging",
    "Viewed?", "Strategy", "Draft Message", "Status", "Approved At",
]

NUDGE_LOG_HEADER = [
    "Quote #", "Client", "Service", "Amount", "Strategy", "Nudge #", "Logged At",
]


def get_sheets_client(credentials_json: str):
    """Build an authenticated Google Sheets API client.

    credentials_json is the raw JSON string of a service account key.
    """
    info = json.loads(credentials_json)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def _ensure_header(service, sheet_id: str, tab: str, header: list[str]) -> None:
    """Write the header row if the tab is empty."""
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=f"{tab}!A1:Z1")
        .execute()
    )
    if not result.get("values"):
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            body={"values": [header]},
        ).execute()


def append_draft_row(service, sheet_id: str, signals: QuoteSignals, draft: str) -> None:
    """Append one row to the Pending Drafts tab for owner review."""
    _ensure_header(service, sheet_id, PENDING_DRAFTS_TAB, PENDING_DRAFTS_HEADER)

    row = [
        signals.quote_id,
        signals.client_name,
        signals.service_type,
        f"${signals.quote_total:.2f}",
        signals.days_aging,
        "Yes" if signals.was_viewed else "No",
        signals.strategy.value,
        draft,
        "PENDING",
        "",
    ]
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"{PENDING_DRAFTS_TAB}!A1",
        valueInputOption="RAW",
        body={"values": [row]},
    ).execute()


def append_nudge_log_row(service, sheet_id: str, signals: QuoteSignals) -> None:
    """Append a record to the Nudge Log tab (running history for the owner)."""
    _ensure_header(service, sheet_id, NUDGE_LOG_TAB, NUDGE_LOG_HEADER)

    row = [
        signals.quote_id,
        signals.client_name,
        signals.service_type,
        f"${signals.quote_total:.2f}",
        signals.strategy.value,
        signals.nudge_count + 1,
        datetime.now(timezone.utc).isoformat(),
    ]
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"{NUDGE_LOG_TAB}!A1",
        valueInputOption="RAW",
        body={"values": [row]},
    ).execute()
