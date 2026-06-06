from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class FollowUpStrategy(Enum):
    WARM_ENGAGED = "warm_engaged"        # Viewed + high value
    ENSURE_DELIVERY = "ensure_delivery"  # Not viewed + high value
    GENTLE_NUDGE = "gentle_nudge"        # Viewed + standard value
    SOFT_REMINDER = "soft_reminder"      # Not viewed + standard value
    FINAL_CHECK = "final_check"          # Second nudge, any category


@dataclass
class QuoteSignals:
    quote_id: str
    client_name: str
    service_type: str
    quote_total: float
    days_aging: int
    was_viewed: bool
    nudge_count: int
    strategy: FollowUpStrategy


def _calculate_age_days(transitioned_at: str) -> int:
    dt = datetime.fromisoformat(transitioned_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    return delta.days


def classify(
    quote: dict,
    nudge_history: dict,
    high_value_threshold: float = 500.0,
) -> QuoteSignals:
    """Classify a quote into a follow-up strategy using the 2x2 signal matrix.

    Axes: (viewed? / not viewed) x (high value / standard value).
    A second nudge always escalates to FINAL_CHECK regardless of quadrant.
    """
    viewed = quote.get("clientHubViewedAt") is not None
    total = float(quote["amounts"]["total"] or 0)
    high_value = total > high_value_threshold

    quote_number = quote["quoteNumber"]
    existing = nudge_history.get(quote_number, {})
    nudge_count = existing.get("nudge_count", 0)

    if nudge_count >= 1:
        strategy = FollowUpStrategy.FINAL_CHECK
    elif viewed and high_value:
        strategy = FollowUpStrategy.WARM_ENGAGED
    elif not viewed and high_value:
        strategy = FollowUpStrategy.ENSURE_DELIVERY
    elif viewed and not high_value:
        strategy = FollowUpStrategy.GENTLE_NUDGE
    else:
        strategy = FollowUpStrategy.SOFT_REMINDER

    client = quote.get("client", {})
    first_name = client.get("firstName") or client.get("name") or "there"

    return QuoteSignals(
        quote_id=quote_number,
        client_name=first_name,
        service_type=quote.get("title") or "your project",
        quote_total=total,
        days_aging=_calculate_age_days(quote["transitionedAt"]),
        was_viewed=viewed,
        nudge_count=nudge_count,
        strategy=strategy,
    )
