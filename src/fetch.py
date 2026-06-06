import os
from datetime import datetime, timedelta, timezone

import httpx

JOBBER_GRAPHQL_URL = "https://api.getjobber.com/api/graphql"

AGING_QUOTES_QUERY = """
query AgingQuotes($first: Int!, $cursor: String) {
  quotes(
    first: $first
    after: $cursor
    filter: { quoteStatus: AWAITING_RESPONSE }
  ) {
    nodes {
      id
      quoteNumber
      quoteStatus
      title
      message
      transitionedAt
      clientHubViewedAt
      createdAt
      previewUrl
      amounts {
        depositAmount
        discountAmount
        nonTaxAmount
        outstandingDepositAmount
        subtotal
        taxAmount
        total
      }
      client {
        id
        name
        firstName
        emails { address }
        phones { number }
        companyName
        isCompany
      }
      property {
        address {
          street1
          street2
          city
          province
          postalCode
        }
      }
      lineItems(first: 10) {
        nodes {
          name
          description
          quantity
          unitPrice
          totalPrice
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""


def is_aging(quote: dict, threshold_days: int) -> bool:
    """True if the quote has been in AWAITING_RESPONSE longer than threshold_days."""
    transitioned = datetime.fromisoformat(quote["transitionedAt"])
    if transitioned.tzinfo is None:
        transitioned = transitioned.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - transitioned
    return age > timedelta(days=threshold_days)


def fetch_all_aging_quotes(access_token: str, threshold_days: int = 3) -> list[dict]:
    """Paginate through all AWAITING_RESPONSE quotes and return those past the age threshold.

    Filtering is done in Python rather than GraphQL because Jobber's filter API
    does not support date arithmetic. The threshold is configurable via AGING_THRESHOLD_DAYS.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-JOBBER-GRAPHQL-VERSION": "2025-04-16",
    }

    aging = []
    cursor = None
    page_size = 50

    while True:
        variables = {"first": page_size}
        if cursor:
            variables["cursor"] = cursor

        response = httpx.post(
            JOBBER_GRAPHQL_URL,
            json={"query": AGING_QUOTES_QUERY, "variables": variables},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        quotes_data = data["data"]["quotes"]
        for quote in quotes_data["nodes"]:
            if is_aging(quote, threshold_days):
                aging.append(quote)

        page_info = quotes_data["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    return aging
