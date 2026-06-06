import json
import os
from datetime import datetime, timedelta, timezone

_NUDGE_LOG_TAB = "Nudge Log"


def load_log(path: str = "nudge_log.json") -> dict:
    """Load the nudge log from disk. Returns empty dict if file doesn't exist."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_log(log: dict, path: str = "nudge_log.json") -> None:
    """Persist the nudge log to disk."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


def should_skip(
    quote_number: str,
    log: dict,
    max_nudges: int,
    min_days: int,
) -> tuple[bool, str]:
    """Decide whether to skip a quote this run.

    Returns (skip, reason). Reason is an empty string when skip is False.
    """
    entry = log.get(quote_number)
    if entry is None:
        return False, ""

    if entry["nudge_count"] >= max_nudges:
        return True, f"max nudges reached ({entry['nudge_count']}/{max_nudges})"

    last_nudged = datetime.fromisoformat(entry["last_nudged_at"])
    if last_nudged.tzinfo is None:
        last_nudged = last_nudged.replace(tzinfo=timezone.utc)
    since_last = datetime.now(timezone.utc) - last_nudged
    if since_last < timedelta(days=min_days):
        days_remaining = min_days - since_last.days
        return True, f"nudged too recently ({days_remaining} day(s) until next allowed)"

    return False, ""


def seed_from_sheet(service, sheet_id: str) -> dict:
    """Rebuild the nudge log from the Nudge Log Sheet tab.

    Called at the start of each GitHub Actions run so nudge state persists across
    runs without requiring a committed nudge_log.json in the repo.

    Nudge Log columns: Quote # | Client | Service | Amount | Strategy | Nudge # | Logged At
    Indices:              0        1         2         3         4          5         6
    """
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=f"{_NUDGE_LOG_TAB}!A2:G")
        .execute()
    )
    rows = result.get("values", [])

    log: dict = {}
    for row in rows:
        if len(row) < 7:
            continue
        quote_number = row[0]
        strategy = row[4]
        nudge_count = int(row[5]) if row[5].isdigit() else 1
        logged_at = row[6]

        existing = log.get(quote_number)
        if existing is None or nudge_count > existing["nudge_count"]:
            log[quote_number] = {
                "nudge_count": nudge_count,
                "last_nudged_at": logged_at,
                "strategy_used": strategy,
            }

    return log


def record_nudge(quote_number: str, strategy: str, log: dict) -> dict:
    """Record a successful nudge. Returns the updated log (caller must call save_log)."""
    entry = log.get(quote_number, {"nudge_count": 0})
    updated = {
        "nudge_count": entry["nudge_count"] + 1,
        "last_nudged_at": datetime.now(timezone.utc).isoformat(),
        "strategy_used": strategy,
    }
    return {**log, quote_number: updated}
