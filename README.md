# Support Insights Crew

A [crewAI](https://crewai.com) Flow that analyzes simulated customer support
ticket data, identifies recurring problems and process bottlenecks, and
compiles a concise, board-ready report for a COO — with a user-steerable
focus area (e.g. "billing tickets only").

## What it does

1. **Fetch & analyze** — a Data Analyst agent pulls ticket data (via custom
   tools) and computes volume, resolution time, escalation/reopen rate, and
   CSAT metrics, scoped to whatever focus area the user asks for.
2. **Identify patterns** — a Problem & Bottleneck Analyst ranks recurring
   root causes and process bottlenecks by business impact.
3. **Recommend actions** — a Process Improvement Strategist turns those
   findings into prioritized, concrete recommendations with owner, effort,
   and expected impact.
4. **Compile the report** — an Executive Communications Writer compiles
   everything into a <600-word COO report with an executive summary, key
   metrics, top problems, recommended actions, and an explicit "what we need
   from you" section.

## Sample data

`data/support_tickets.json` contains 400 simulated support tickets across
five categories — `billing`, `technical`, `account`, `shipping`,
`product_feedback` — with realistic subjects, root causes, priorities,
channels, resolution times, escalation/reopen flags, and CSAT scores.

Regenerate it anytime with:

```bash
uv run python scripts/generate_sample_data.py
```

## Installation

Requires Python >=3.10 <3.14. Uses [uv](https://docs.astral.sh/uv/) for
dependency management.

```bash
crewai install
```

Add your `OPENAI_API_KEY` (or another provider's key + `LLM` override) to
`.env`.

## Running it — with a focus area

The whole point of this flow is that you can steer the report toward a
specific area the user cares about. Three ways to set the focus area:

**1. Environment variable (simplest):**
```bash
FOCUS_AREA="billing" crewai run
```

**2. Interactive prompt** — if `FOCUS_AREA` isn't set, `crewai run` will ask:
```
What should the report focus on? (e.g. 'billing', 'technical', 'all tickets') [all tickets]:
```

**3. Trigger payload** (for programmatic/CI use):
```bash
uv run run_with_trigger '{"focus_area": "billing"}'
```

The focus area can be one of the dataset's categories (`billing`,
`technical`, `account`, `shipping`, `product_feedback`) or a free-text
keyword (e.g. `"refund"`, `"login"`, `"SSO"`) — the data tools handle both
via category match and keyword search, and fall back gracefully if nothing
matches. Leave it blank / use `"all tickets"` for a support-wide report.

The final report is written to `output/coo_report.md`.

## Project structure

```
support_insights/
├── data/
│   └── support_tickets.json          # simulated ticket dataset
├── scripts/
│   └── generate_sample_data.py       # regenerates the dataset
├── src/support_insights/
│   ├── crews/support_crew/
│   │   ├── config/
│   │   │   ├── agents.yaml           # 4 agents
│   │   │   └── tasks.yaml            # 4 sequential tasks
│   │   └── support_crew.py
│   ├── tools/
│   │   └── custom_tool.py            # fetch_support_tickets, support_ticket_stats
│   └── main.py                       # Flow: set focus area -> run crew -> save report
├── .env
└── pyproject.toml
```

## Observability

This project supports crewAI's free trace collection:

```bash
crewai traces enable
crewai run
```

## Support

- [crewAI docs](https://docs.crewai.com)
- [crewAI GitHub](https://github.com/joaomdmoura/crewai)
