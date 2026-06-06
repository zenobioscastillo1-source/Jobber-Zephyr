import os

import anthropic

from .signals import FollowUpStrategy, QuoteSignals

STRATEGY_PROMPTS: dict[FollowUpStrategy, str] = {
    FollowUpStrategy.WARM_ENGAGED: """
You are writing a follow-up message for {business_name}, a home service company.

Context:
- Client name: {client_name}
- Service: {service_type}
- Quote amount: ${quote_total:.2f}
- Days since quote sent: {days_aging}
- The client HAS viewed the quote but hasn't responded

Write a warm, brief follow-up (2-3 sentences max). Acknowledge they've seen the quote
without being creepy about tracking. Ask if they have questions. Don't be pushy.
Sign off as {owner_name}.

Output ONLY the message body. No subject line, no greeting format instructions.
""",
    FollowUpStrategy.ENSURE_DELIVERY: """
You are writing a follow-up message for {business_name}, a home service company.

Context:
- Client name: {client_name}
- Service: {service_type}
- Quote amount: ${quote_total:.2f}
- Days since quote sent: {days_aging}
- The client has NOT viewed the quote yet

Write a brief check-in (2-3 sentences). Frame it as making sure the quote didn't get
lost in email. Offer to resend or discuss over phone. Don't mention tracking — just say
you wanted to make sure they received it. Sign off as {owner_name}.

Output ONLY the message body.
""",
    FollowUpStrategy.GENTLE_NUDGE: """
You are writing a follow-up message for {business_name}, a home service company.

Context:
- Client name: {client_name}
- Service: {service_type}
- Quote amount: ${quote_total:.2f}
- Days since quote sent: {days_aging}
- The client HAS viewed the quote but hasn't responded

Write a gentle, friendly follow-up (2-3 sentences). Keep it casual and low-pressure.
Just checking in to see if they have any questions or are ready to move forward.
Sign off as {owner_name}.

Output ONLY the message body.
""",
    FollowUpStrategy.SOFT_REMINDER: """
You are writing a follow-up message for {business_name}, a home service company.

Context:
- Client name: {client_name}
- Service: {service_type}
- Quote amount: ${quote_total:.2f}
- Days since quote sent: {days_aging}
- The client has NOT viewed the quote yet

Write a soft, non-pushy reminder (2-3 sentences). Suggest the quote may have gotten
buried. Keep the tone friendly and helpful, not sales-y. Sign off as {owner_name}.

Output ONLY the message body.
""",
    FollowUpStrategy.FINAL_CHECK: """
You are writing a final follow-up message for {business_name}, a home service company.

Context:
- Client name: {client_name}
- Service: {service_type}
- Quote amount: ${quote_total:.2f}
- Days since quote sent: {days_aging}
- This is the last follow-up attempt

Write a brief, respectful final check-in (2-3 sentences). Let the client know this is
just a final check before you move on. Leave the door open — no pressure. No urgency
language. Sign off as {owner_name}.

Output ONLY the message body.
""",
}

_FAIL_DISCOUNT_TERMS = ["discount", "% off", "reduce", "lower the price"]
_FAIL_URGENCY_TERMS = ["limited time", "expires", "last chance", "final offer"]
_FAIL_TRACKING_PHRASES = ["i saw you viewed", "i noticed you opened", "our system shows"]


def generate_draft(
    signals: QuoteSignals,
    business_name: str,
    owner_name: str,
) -> str:
    """Call Claude Haiku to generate a personalized follow-up draft."""
    prompt_template = STRATEGY_PROMPTS[signals.strategy]
    prompt = prompt_template.format(
        business_name=business_name,
        client_name=signals.client_name,
        service_type=signals.service_type,
        quote_total=signals.quote_total,
        days_aging=signals.days_aging,
        owner_name=owner_name,
    )

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def validate_draft(draft: str, signals: QuoteSignals) -> tuple[bool, str]:
    """Grounding gate: ensure the draft doesn't make unauthorized promises or reveal tracking.

    Returns (passed, reason). On FAIL the quote is skipped for this run.
    WARN issues are logged but do not block the draft.
    """
    lower = draft.lower()
    issues = []

    if any(term in lower for term in _FAIL_DISCOUNT_TERMS):
        issues.append("FAIL: draft offers a discount not authorized by owner")

    if any(term in lower for term in _FAIL_URGENCY_TERMS):
        issues.append("FAIL: draft creates false urgency")

    if any(phrase in lower for phrase in _FAIL_TRACKING_PHRASES):
        issues.append("FAIL: draft reveals quote-view tracking to client")

    if any(issues):
        return False, "; ".join(issues)

    word_count = len(draft.split())
    if word_count > 100:
        print(f"[WARN] Draft for {signals.quote_id} is {word_count} words — may be too long for a nudge")

    return True, "OK"
