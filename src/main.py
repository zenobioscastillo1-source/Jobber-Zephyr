import asyncio
import os

from dotenv import load_dotenv

from .auth import refresh_jobber_token
from .deliver import get_approved_drafts, mark_sent, send_draft
from .draft import generate_draft, validate_draft
from .fetch import fetch_all_aging_quotes
from .signals import classify
from .tracker import load_log, record_nudge, save_log, seed_from_sheet, should_skip
from .write import append_draft_row, append_nudge_log_row, get_sheets_client

load_dotenv()


async def main() -> None:
    aging_threshold = int(os.getenv("AGING_THRESHOLD_DAYS", "3"))
    max_nudges = int(os.getenv("MAX_NUDGES_PER_QUOTE", "2"))
    min_days = int(os.getenv("MIN_DAYS_BETWEEN_NUDGES", "3"))
    high_value_threshold = float(os.getenv("HIGH_VALUE_THRESHOLD", "500"))
    business_name = os.environ["BUSINESS_NAME"]
    owner_name = os.environ["OWNER_NAME"]
    sheet_id = os.environ["GOOGLE_SHEET_ID"]
    sheets_creds = os.environ["GOOGLE_SHEETS_CREDENTIALS"]
    enable_delivery = os.getenv("ENABLE_DELIVERY", "false").lower() == "true"

    print("[Zephyr] Refreshing Jobber token...")
    access_token = await refresh_jobber_token()

    sheets = get_sheets_client(sheets_creds)

    # Seed nudge log from Sheet so state persists across GitHub Actions runs.
    # Falls back to local JSON for runs without Sheet credentials (e.g. dry runs).
    print("[Zephyr] Loading nudge history from Sheet...")
    nudge_log = seed_from_sheet(sheets, sheet_id)
    if not nudge_log:
        nudge_log = load_log()

    print(f"[Zephyr] Fetching quotes older than {aging_threshold} day(s)...")
    quotes = fetch_all_aging_quotes(access_token, threshold_days=aging_threshold)
    print(f"[Zephyr] Found {len(quotes)} aging quote(s).")

    drafted = 0
    skipped_tracker = 0
    skipped_gate = 0

    for quote in quotes:
        quote_number = quote["quoteNumber"]

        skip, reason = should_skip(quote_number, nudge_log, max_nudges, min_days)
        if skip:
            print(f"[skip] {quote_number}: {reason}")
            skipped_tracker += 1
            continue

        signals = classify(quote, nudge_log, high_value_threshold)

        draft = generate_draft(signals, business_name, owner_name)
        passed, gate_reason = validate_draft(draft, signals)
        if not passed:
            print(f"[gate-fail] {quote_number}: {gate_reason}")
            skipped_gate += 1
            continue

        append_draft_row(sheets, sheet_id, signals, draft)
        append_nudge_log_row(sheets, sheet_id, signals)
        nudge_log = record_nudge(quote_number, signals.strategy.value, nudge_log)
        save_log(nudge_log)

        print(f"[drafted] {quote_number} ({signals.strategy.value}) — {signals.client_name}")
        drafted += 1

    print(
        f"\n[Zephyr] Draft pass done. {drafted} drafted, "
        f"{skipped_tracker} skipped (tracker), "
        f"{skipped_gate} skipped (grounding gate)."
    )

    # Delivery pass — only runs when explicitly opted in via ENABLE_DELIVERY=true
    if enable_delivery:
        sendgrid_key = os.environ["SENDGRID_API_KEY"]
        from_email = os.environ["FROM_EMAIL"]

        print("\n[Zephyr] Delivery pass — sending approved drafts...")
        approved = get_approved_drafts(sheets, sheet_id)
        print(f"[Zephyr] {len(approved)} approved draft(s) to send.")

        sent = 0
        for item in approved:
            success = send_draft(item["row"], from_email, sendgrid_key)
            if success:
                mark_sent(sheets, sheet_id, item["row_index"])
                print(f"[sent] row {item['row_index']} — {item['row'].get('client', '?')}")
                sent += 1
            else:
                print(f"[send-fail] row {item['row_index']} — will retry next run")

        print(f"[Zephyr] Delivery done. {sent}/{len(approved)} sent.")
    else:
        print("[Zephyr] Delivery skipped (ENABLE_DELIVERY=false). Set to true to auto-send approved drafts.")


if __name__ == "__main__":
    asyncio.run(main())
