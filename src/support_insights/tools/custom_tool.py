import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Optional, Type

from pydantic import BaseModel, Field

from crewai.tools import BaseTool

DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "support_tickets.json"


def _load_tickets() -> list[dict]:
    with open(DATA_PATH) as f:
        return json.load(f)


class SupportTicketFetchInput(BaseModel):
    """Input schema for SupportTicketFetchTool."""

    category: Optional[str] = Field(
        default=None,
        description=(
            "Optional category filter. One of: billing, technical, account, "
            "shipping, product_feedback. Leave empty to include all categories."
        ),
    )
    keyword: Optional[str] = Field(
        default=None,
        description=(
            "Optional free-text keyword to search for in the ticket subject, "
            "description, or root_cause (case-insensitive substring match). "
            "Use this to focus on a specific issue the user asked about, e.g. "
            "'refund' or 'login'."
        ),
    )


class SupportTicketFetchTool(BaseTool):
    name: str = "fetch_support_tickets"
    description: str = (
        "Fetches simulated customer support ticket data as JSON. Supports "
        "optional filtering by category (billing, technical, account, "
        "shipping, product_feedback) and/or a free-text keyword. Use this "
        "first to pull the raw tickets relevant to the analysis, especially "
        "when the user has asked to focus on a specific area (e.g. billing "
        "tickets only)."
    )
    args_schema: Type[BaseModel] = SupportTicketFetchInput

    def _run(self, category: Optional[str] = None, keyword: Optional[str] = None) -> str:
        tickets = _load_tickets()

        if category:
            category_norm = category.strip().lower().replace(" ", "_")
            tickets = [t for t in tickets if t["category"] == category_norm]

        if keyword:
            kw = keyword.strip().lower()
            tickets = [
                t
                for t in tickets
                if kw in t["subject"].lower()
                or kw in t["description"].lower()
                or kw in t["root_cause"].lower()
            ]

        if not tickets:
            return (
                f"No tickets found for category={category!r} keyword={keyword!r}. "
                "Try broadening the filter or omitting it."
            )

        return json.dumps(
            {
                "matched_ticket_count": len(tickets),
                "filters_applied": {"category": category, "keyword": keyword},
                "tickets": tickets,
            },
            indent=2,
        )


class SupportTicketStatsInput(BaseModel):
    """Input schema for SupportTicketStatsTool."""

    category: Optional[str] = Field(
        default=None,
        description=(
            "Optional category filter. One of: billing, technical, account, "
            "shipping, product_feedback. Leave empty to compute stats across "
            "all categories."
        ),
    )


class SupportTicketStatsTool(BaseTool):
    name: str = "support_ticket_stats"
    description: str = (
        "Computes aggregate statistics over the simulated support ticket "
        "dataset: volume by category, root-cause frequency, average "
        "resolution time, average first-response time, escalation rate, "
        "reopen rate, and average CSAT. Optionally scope to a single "
        "category. Use this to identify recurring problems and bottlenecks "
        "quantitatively rather than reading every ticket by hand."
    )
    args_schema: Type[BaseModel] = SupportTicketStatsInput

    def _run(self, category: Optional[str] = None) -> str:
        tickets = _load_tickets()

        if category:
            category_norm = category.strip().lower().replace(" ", "_")
            tickets = [t for t in tickets if t["category"] == category_norm]
            if not tickets:
                return f"No tickets found for category={category!r}."

        total = len(tickets)
        category_counts = Counter(t["category"] for t in tickets)
        root_cause_counts = Counter(t["root_cause"] for t in tickets)
        priority_counts = Counter(t["priority"] for t in tickets)
        channel_counts = Counter(t["channel"] for t in tickets)
        plan_counts = Counter(t["customer_plan"] for t in tickets)

        resolution_hours = [t["resolution_hours"] for t in tickets if t["resolution_hours"] is not None]
        first_response = [t["first_response_minutes"] for t in tickets]
        csat_scores = [t["csat_score"] for t in tickets if t["csat_score"] is not None]

        escalated_count = sum(1 for t in tickets if t["escalated"])
        reopened_count = sum(1 for t in tickets if t["reopen_count"] > 0)

        stats = {
            "scope": {"category": category or "all"},
            "total_tickets": total,
            "volume_by_category": dict(category_counts.most_common()),
            "top_root_causes": [
                {"root_cause": cause, "count": count}
                for cause, count in root_cause_counts.most_common(10)
            ],
            "volume_by_priority": dict(priority_counts.most_common()),
            "volume_by_channel": dict(channel_counts.most_common()),
            "volume_by_customer_plan": dict(plan_counts.most_common()),
            "avg_resolution_hours": round(mean(resolution_hours), 2) if resolution_hours else None,
            "max_resolution_hours": round(max(resolution_hours), 2) if resolution_hours else None,
            "avg_first_response_minutes": round(mean(first_response), 2) if first_response else None,
            "escalation_rate_pct": round(100 * escalated_count / total, 1) if total else None,
            "reopen_rate_pct": round(100 * reopened_count / total, 1) if total else None,
            "avg_csat": round(mean(csat_scores), 2) if csat_scores else None,
            "csat_sample_size": len(csat_scores),
        }

        return json.dumps(stats, indent=2)
