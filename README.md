# CrewAI Homework Projects

This repo holds two crewAI projects:

| Project | Command | What it does |
|---|---|---|
| **Contract vs. Invoice Audit** | `uv run audit` | Extracts a purchase contract and an invoice from PDF and reports every billing discrepancy between them |
| **Support Insights** | `uv run kickoff` | Analyzes simulated support ticket data into a COO report |

---

# 1. Contract vs. Invoice Discrepancy Audit

A four-agent crewAI crew that reads a purchase contract and an invoice
straight from PDF, extracts both into structured data, and produces a
discrepancy report a finance manager can act on before paying.

## The crew

| # | Agent | Tool | Produces |
|---|---|---|---|
| 1 | Commercial Contract Analyst | `read_document_text` | `ContractTerms` — agreed unit prices, payment window, permitted methods, tax responsibility |
| 2 | Accounts Payable Invoice Analyst | `read_document_text` | `InvoiceData` — every billed line, subtotal, tax, total, dates |
| 3 | Contract Compliance & Billing Discrepancy Auditor | `compare_contract_to_invoice` | Verified findings, grouped by severity |
| 4 | Audit Report Writer | — | `output/discrepancy_report.md` |

Tasks run sequentially, each receiving the previous tasks as context.

### Why the math is not done by the LLM

Agents 1 and 2 do extraction — reading a document and deciding what a number
means — which is what LLMs are good at. Every comparison and every
calculation happens in Python, inside `compare_contract_to_invoice`. No agent
is ever asked to multiply a quantity by a unit price or judge whether two
figures match, because a hallucinated total in a document someone pays
against is an expensive failure mode.

The extraction tasks use crewAI's `output_pydantic`, so agent output is
validated into the same models the comparison tool parses. A sloppy
extraction fails loudly at the task boundary instead of quietly producing an
empty audit.

## What it checks

- **Unit price** of each billed line against the contracted rate, split into
  overcharges and undercharges, with the cash impact of each
- **Unauthorized items** — billed but absent from the contract's scope
- **Contracted but not invoiced** items (reported as informational, since
  undelivered work is a normal state)
- **Invoice arithmetic** — each line total vs. qty x unit price, the subtotal
  vs. the lines, the tax vs. the stated rate, the grand total vs. subtotal + tax
- **Repricing at contract rates** — catches the case where individual lines
  are wrong but the errors offset, leaving a correct-looking total
- **Payment terms and due date** — the printed due date must honour the
  contract's payment window, counted from the invoice date
- **Payment method** against the contract's permitted list, respecting any
  catch-all clause such as "or other mutually agreed method"
- **Document linkage** — the invoice number the contract governs, and the
  vendor named on each document

Item descriptions are matched exactly first, then by similarity, so reworded
line items are matched rather than reported as unauthorized.

## Findings on the sample documents

`data/documents/` ships the assignment's two PDFs. The audit finds four
discrepancies on them:

| Item | Qty | Contract | Invoiced | Impact |
|---|---|---|---|---|
| Website design consultation | 2 | $85.00 | $85.00 | correct |
| Homepage wireframe and revisions | 1 | $210.00 | $220.00 | **+$10.00 overcharge** |
| Product photo retouching package | 1 | $150.00 | $145.00 | -$5.00 undercharge |
| Monthly hosting setup | 1 | $65.00 | $60.00 | -$5.00 undercharge |

Overbilled $10.00, underbilled $10.00, **net impact $0.00** — three of the
four lines are priced wrong, yet they cancel out exactly. The invoice's
subtotal ($595.00), tax ($49.09 at 8.25%) and total ($644.09) are all
internally correct, and the Net 14 due date of April 5 is correct for a
March 22 invoice date. An audit that only compared bottom lines would pass
this invoice. The report flags it as `totals_agree_despite_line_errors`.

## Running it

```bash
uv sync                       # or: crewai install
cp .env.example .env          # then add your GROQ_API_KEY
uv run audit
```

Outputs land in `output/`:

| File | Contents |
|---|---|
| `discrepancy_report.md` | The final report |
| `audit_findings.md` | The auditor's verified findings |
| `contract_terms.json` | Structured contract extraction |
| `invoice_data.json` | Structured invoice extraction |

### LLM provider

The crew runs on Groq (`groq/openai/gpt-oss-120b`) at `temperature=0` —
extraction and auditing want the least creative output available. `MODEL` is
a LiteLLM string, so switching providers means changing it and supplying that
provider's key:

```bash
MODEL=openai/gpt-4o OPENAI_API_KEY=sk-... uv run audit
```

Groq's free tier allows 8,000 tokens per minute, and prompts carrying whole
documents brush against it. Two things keep a run alive:

- `max_rpm` (default 2) spaces the crew's calls out. Raise it via `MAX_RPM` on
  a paid tier.
- `RateLimitAwareLLM` in `llm.py` reads the provider's own "try again in Xs"
  and sleeps it. LiteLLM's built-in `num_retries` retries almost immediately,
  which is useless against a rolling per-minute budget — it just burns the
  attempts while the window is still full.

A typical run takes a few minutes and prints
`[rate limited — waiting Ns before retrying]` when it has to wait.

### Auditing other documents

Drop the PDFs into `data/documents/` and point the env vars at them — the
agents keep saying "contract" and "invoice", so no prompt changes are needed:

```bash
CONTRACT_PDF=acme_msa.pdf INVOICE_PDF=acme_march.pdf uv run audit
```

Or pass a trigger payload:

```bash
uv run audit_with_trigger '{"contract_pdf": "acme_msa.pdf", "invoice_pdf": "acme_march.pdf"}'
```

## Tests

The comparison engine is pure Python and is where a wrong answer costs money,
so it is tested directly — including the offsetting-errors case, each
arithmetic check, unauthorized and uninvoiced items, fuzzy description
matching, terms and due-date checks, and malformed tool input:

```bash
uv run pytest tests/ -q      # 21 passed
```

## Note on dependencies

`pyproject.toml` pins `crewai>=1.9.0,<1.10.0` and declares a `[tool.uv]`
required environment. This is a platform constraint, not a preference: this
machine is an Intel Mac, and `lancedb` (required by crewai 1.10+) and recent
`onnxruntime` no longer publish x86_64 macOS wheels. On Apple Silicon or
Linux you can raise the pin to `>=1.15.20,<2.0.0` and delete the `[tool.uv]`
block. The `[tools]` extra was dropped because nothing here imports
`crewai_tools` — both crews define their own `BaseTool` subclasses. `litellm`
is explicit because crewai routes non-native providers such as Groq through
it.

---

# 2. Support Insights Crew

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

Note that this crew does not set an `llm=` on its agents, so it uses crewAI's
default provider and needs an `OPENAI_API_KEY` in `.env`. Only the audit crew
(project 1) is wired to Groq. To run this one on Groq too, give its agents
`llm=get_llm()` the same way `audit_crew.py` does.

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
crewai-customer-support-agent/
├── data/
│   ├── documents/                        # contract + invoice PDFs
│   └── support_tickets.json              # simulated ticket dataset
├── src/
│   ├── contract_audit/                   # project 1: discrepancy audit
│   │   ├── crews/audit_crew/
│   │   │   ├── config/agents.yaml        # 4 agents
│   │   │   ├── config/tasks.yaml         # 4 sequential tasks
│   │   │   └── audit_crew.py
│   │   ├── tools/document_tools.py       # PDF reader + comparison engine
│   │   ├── models.py                     # shared extraction schemas
│   │   └── main.py                       # Flow: locate docs -> audit -> save
│   └── support_insights/                 # project 2: support insights
│       ├── crews/support_crew/
│       ├── tools/custom_tool.py
│       └── main.py
├── tests/test_audit_engine.py
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
