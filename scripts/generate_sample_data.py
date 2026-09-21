#!/usr/bin/env python
"""Generates a realistic simulated customer support ticket dataset.

Run with: uv run python scripts/generate_sample_data.py
Writes to: data/support_tickets.json
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

CATEGORIES = {
    "billing": {
        "subjects": [
            "Charged twice for monthly subscription",
            "Invoice shows incorrect amount",
            "Unable to update credit card on file",
            "Refund not received after cancellation",
            "Unexpected charge after free trial ended",
            "Coupon code not applied at checkout",
            "Annual plan billed at wrong rate",
            "Currency conversion charge dispute",
            "Failed payment keeps retrying and failing",
            "Requesting itemized invoice for accounting",
            "Downgrade did not reduce next bill",
            "Tax calculated incorrectly on invoice",
        ],
        "root_causes": [
            "duplicate charge due to webhook retry bug in payment processor",
            "stale pricing cache showing old plan rate",
            "credit card update form silently failing on validation error",
            "refund workflow requires manual finance approval, no SLA tracking",
            "trial-end reminder email not sent, so cancellation window missed",
            "coupon engine not validating against updated promo rules",
            "proration logic error on annual-plan billing cycle",
            "FX rate locked at signup, not current rate, no disclosure",
            "payment retry loop not respecting card decline reason codes",
            "invoice generation tool lacks itemization for enterprise tier",
            "downgrade takes effect next cycle but UI implies immediate",
            "tax jurisdiction misdetected from billing address parsing",
        ],
    },
    "technical": {
        "subjects": [
            "App crashes on startup after latest update",
            "Cannot upload files larger than 10MB",
            "Integration with Slack stopped syncing",
            "Dashboard charts not loading",
            "API returns 500 error intermittently",
            "Mobile app login loop, never reaches home screen",
            "Export to CSV produces corrupted file",
            "Search feature returns no results for valid queries",
            "SSO login fails with 'invalid assertion' error",
            "Webhook deliveries delayed by hours",
        ],
        "root_causes": [
            "null pointer exception in new onboarding module, not caught in QA",
            "file upload limit hardcoded, not surfaced in UI before upload attempt",
            "Slack OAuth token refresh logic broken after API version bump",
            "frontend charting library version mismatch after deploy",
            "database connection pool exhaustion under peak load",
            "session token race condition on mobile SSO redirect",
            "CSV export missing UTF-8 BOM causing encoding corruption",
            "search index falling behind due to reindexing job failures",
            "SAML clock skew tolerance too strict for customer's IdP",
            "webhook queue worker under-provisioned during traffic spikes",
        ],
    },
    "account": {
        "subjects": [
            "Locked out of account after password reset",
            "Cannot invite team members, invite link broken",
            "Two-factor authentication codes not arriving",
            "Account merge request after accidental duplicate signup",
            "Permission changes not saving for sub-admin role",
            "Email change confirmation link expired immediately",
            "Unable to delete account, GDPR request",
        ],
        "root_causes": [
            "password reset email link uses expired token TTL of 5 minutes",
            "invite link generation broken for workspaces created before migration",
            "SMS provider rate-limiting during high signup volume",
            "no self-serve account merge tool, requires manual DB intervention",
            "role permissions cache not invalidated on update",
            "confirmation link TTL misconfigured to seconds instead of hours",
            "account deletion requires manual ticket to compliance team, no automation",
        ],
    },
    "shipping": {
        "subjects": [
            "Order marked delivered but never arrived",
            "Wrong item shipped in order",
            "Tracking number not updating for 5 days",
            "Package damaged in transit",
            "International shipping delayed beyond estimate",
            "Return label not generated after RMA approval",
        ],
        "root_causes": [
            "carrier scan marked delivered prematurely, no proof-of-delivery photo",
            "warehouse pick-pack error during peak volume",
            "carrier tracking API integration returning stale data",
            "packaging spec insufficient for fragile item category",
            "customs clearance process not communicated to customer upfront",
            "RMA system and shipping label generator not integrated, manual step",
        ],
    },
    "product_feedback": {
        "subjects": [
            "Requesting dark mode for dashboard",
            "Feature request: bulk export for reports",
            "UI confusing when switching between workspaces",
            "Would like calendar integration",
            "Onboarding flow too long, dropped off users",
        ],
        "root_causes": [
            "not a defect — logged as product enhancement request",
            "not a defect — logged as product enhancement request",
            "workspace switcher lacks visual indicator of active context",
            "not a defect — logged as product enhancement request",
            "onboarding has 9 sequential steps with no save-and-resume",
        ],
    },
}

CHANNELS = ["email", "chat", "phone", "in_app_widget", "twitter_dm"]
PRIORITIES = ["low", "medium", "high", "urgent"]
AGENTS = [
    "Maria Chen", "Jordan Lee", "Priya Patel", "Sam O'Brien",
    "Aisha Khan", "Diego Ramirez", "Lena Novak", "Tom Baker",
]
STATUSES = ["resolved", "resolved", "resolved", "escalated", "reopened"]

CUSTOMER_FIRST = ["Alex", "Jamie", "Taylor", "Morgan", "Casey", "Riley", "Jordan",
                  "Avery", "Quinn", "Skyler", "Drew", "Reese", "Rowan", "Emerson"]
CUSTOMER_LAST = ["Smith", "Johnson", "Williams", "Brown", "Davis", "Miller",
                 "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson"]

PLANS = ["free", "starter", "pro", "business", "enterprise"]

# Roughly weight categories so billing is the largest bucket (~35%) —
# useful for testing category-focused reporting like "billing tickets only".
CATEGORY_WEIGHTS = {
    "billing": 0.35,
    "technical": 0.28,
    "account": 0.16,
    "shipping": 0.11,
    "product_feedback": 0.10,
}


def weighted_category() -> str:
    r = random.random()
    cumulative = 0.0
    for cat, weight in CATEGORY_WEIGHTS.items():
        cumulative += weight
        if r <= cumulative:
            return cat
    return "billing"


def random_datetime_in_last_days(days: int) -> datetime:
    start = datetime(2026, 9, 20) - timedelta(days=days)
    delta_seconds = random.randint(0, days * 24 * 3600)
    return start + timedelta(seconds=delta_seconds)


def generate_ticket(ticket_id: int) -> dict:
    category = weighted_category()
    bucket = CATEGORIES[category]
    idx = random.randrange(len(bucket["subjects"]))
    subject = bucket["subjects"][idx]
    root_cause = bucket["root_causes"][idx]

    created_at = random_datetime_in_last_days(90)

    # Billing and technical issues skew toward longer resolution + higher priority
    if category in ("billing", "technical"):
        priority = random.choices(PRIORITIES, weights=[0.15, 0.35, 0.35, 0.15])[0]
        resolution_hours = round(random.uniform(2, 96), 1)
    else:
        priority = random.choices(PRIORITIES, weights=[0.35, 0.40, 0.20, 0.05])[0]
        resolution_hours = round(random.uniform(0.5, 48), 1)

    status = random.choices(STATUSES, weights=[0.70, 0.70, 0.70, 0.15, 0.15])[0]
    resolved_at = created_at + timedelta(hours=resolution_hours) if status != "escalated" else None

    csat = None
    if status in ("resolved", "reopened"):
        # Lower CSAT correlates with reopened tickets and long resolution times
        base = 4.5 if status == "resolved" else 2.5
        penalty = 0.5 if resolution_hours > 48 else 0
        csat = max(1, min(5, round(random.gauss(base - penalty, 0.8))))

    customer_name = f"{random.choice(CUSTOMER_FIRST)} {random.choice(CUSTOMER_LAST)}"
    customer_email = f"{customer_name.lower().replace(' ', '.')}{ticket_id}@example.com"

    first_response_minutes = round(random.uniform(2, 240), 1)
    reopen_count = 1 if status == "reopened" else 0
    escalated = status == "escalated"

    return {
        "ticket_id": f"TCK-{10000 + ticket_id}",
        "created_at": created_at.isoformat() + "Z",
        "resolved_at": (resolved_at.isoformat() + "Z") if resolved_at else None,
        "category": category,
        "subject": subject,
        "description": f"Customer reports: {subject.lower()}. Root cause on file: {root_cause}.",
        "root_cause": root_cause,
        "channel": random.choice(CHANNELS),
        "priority": priority,
        "status": status,
        "assigned_agent": random.choice(AGENTS),
        "customer_name": customer_name,
        "customer_email": customer_email,
        "customer_plan": random.choices(PLANS, weights=[0.15, 0.25, 0.30, 0.20, 0.10])[0],
        "first_response_minutes": first_response_minutes,
        "resolution_hours": resolution_hours if status != "escalated" else None,
        "reopen_count": reopen_count,
        "csat_score": csat,
        "escalated": escalated,
    }


def main():
    num_tickets = 400
    tickets = [generate_ticket(i) for i in range(1, num_tickets + 1)]
    tickets.sort(key=lambda t: t["created_at"])

    out_path = Path(__file__).resolve().parent.parent / "data" / "support_tickets.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(tickets, f, indent=2)

    print(f"Generated {num_tickets} tickets -> {out_path}")

    # Quick category breakdown for sanity check
    from collections import Counter
    counts = Counter(t["category"] for t in tickets)
    for cat, count in counts.most_common():
        print(f"  {cat}: {count} ({count / num_tickets:.0%})")


if __name__ == "__main__":
    main()
