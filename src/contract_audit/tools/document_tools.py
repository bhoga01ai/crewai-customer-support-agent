"""Tools the audit crew uses to read source documents and compare them.

Division of labour: the agents read and extract (a judgement task LLMs are
good at), and this module does every comparison and every piece of arithmetic
in Python (a task LLMs are bad at). No agent is ever asked to multiply a
quantity by a unit price or decide whether two numbers are equal.
"""

import difflib
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Type

from pydantic import BaseModel, Field, ValidationError

from crewai.tools import BaseTool

from contract_audit.models import ContractTerms, InvoiceData

DOCUMENTS_DIR = Path(__file__).resolve().parents[3] / "data" / "documents"

# Named shortcuts so an agent can say "contract" instead of carrying a path.
DOCUMENT_ALIASES = {
    "contract": "purchase_terms_conditions.pdf",
    "terms": "purchase_terms_conditions.pdf",
    "purchase_terms_conditions": "purchase_terms_conditions.pdf",
    "invoice": "sample_invoice.pdf",
    "sample_invoice": "sample_invoice.pdf",
}

# Point these at other PDFs to audit a different contract/invoice pair.
ALIAS_ENV_VARS = {
    "contract": "CONTRACT_PDF",
    "terms": "CONTRACT_PDF",
    "purchase_terms_conditions": "CONTRACT_PDF",
    "invoice": "INVOICE_PDF",
    "sample_invoice": "INVOICE_PDF",
}

# Money is compared at cent precision; anything smaller is float noise.
TOLERANCE = 0.005

# Below this similarity two item descriptions are treated as different items.
MATCH_THRESHOLD = 0.72

DATE_FORMATS = (
    "%B %d, %Y",
    "%b %d, %Y",
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d %B %Y",
    "%d/%m/%Y",
)


def _resolve_document(document: str) -> Path:
    """Turn an alias, bare filename, or path into a concrete PDF path.

    CONTRACT_PDF / INVOICE_PDF let a different document pair be audited
    without touching the task prompts, which keep saying "contract" and
    "invoice".
    """
    key = document.strip().lower().removesuffix(".pdf")

    env_override = ALIAS_ENV_VARS.get(key)
    if env_override:
        configured = os.environ.get(env_override, "").strip()
        if configured:
            candidate = Path(configured).expanduser()
            return candidate if candidate.is_absolute() else DOCUMENTS_DIR / candidate

    if key in DOCUMENT_ALIASES:
        return DOCUMENTS_DIR / DOCUMENT_ALIASES[key]

    candidate = Path(document).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return candidate

    return DOCUMENTS_DIR / Path(document).name


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation and filler so descriptions can be matched."""
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    raw = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _net_days_from_terms(terms: Optional[str]) -> Optional[int]:
    """Pull the day count out of free text like 'Net 14' or 'net 30 days'."""
    if not terms:
        return None
    match = re.search(r"net\s*(\d+)", terms, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _money(value: float) -> float:
    return round(value + 0.0, 2)


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE


class PdfExtractInput(BaseModel):
    """Input schema for PdfTextExtractTool."""

    document: str = Field(
        description=(
            "Which document to read. Use 'contract' for the purchase terms and "
            "conditions, or 'invoice' for the invoice. A filename or absolute "
            "path to another PDF also works."
        )
    )


class PdfTextExtractTool(BaseTool):
    name: str = "read_document_text"
    description: str = (
        "Reads a PDF from the project's document folder and returns its full "
        "text, page by page. Use 'contract' to read the purchase terms and "
        "conditions, or 'invoice' to read the invoice. Always read a document "
        "with this tool before stating anything about its contents — never "
        "rely on memory or assumption about what a document says."
    )
    args_schema: Type[BaseModel] = PdfExtractInput

    def _run(self, document: str) -> str:
        try:
            from pypdf import PdfReader
        except ImportError:  # pragma: no cover - dependency is declared in pyproject
            return (
                "pypdf is not installed. Run `crewai install` (or `uv sync`) "
                "to install project dependencies, then retry."
            )

        path = _resolve_document(document)
        if not path.exists():
            available = sorted(p.name for p in DOCUMENTS_DIR.glob("*.pdf"))
            return (
                f"No PDF found at {path}. Available documents: {available}. "
                "Use 'contract' or 'invoice'."
            )

        reader = PdfReader(str(path))
        pages = []
        for number, page in enumerate(reader.pages, start=1):
            pages.append(f"--- page {number} of {len(reader.pages)} ---\n{page.extract_text() or ''}")

        return f"Source: {path.name}\n\n" + "\n\n".join(pages)


class DiscrepancyCheckInput(BaseModel):
    """Input schema for DiscrepancyCheckTool."""

    contract_json: str = Field(
        description=(
            "The extracted contract as a JSON object string, matching the "
            "ContractTerms shape: vendor, buyer, referenced_invoice_number, "
            "line_items[{description, unit_price, pricing_basis}], "
            "payment_terms_net_days, payment_methods, tax_responsibility."
        )
    )
    invoice_json: str = Field(
        description=(
            "The extracted invoice as a JSON object string, matching the "
            "InvoiceData shape: invoice_number, invoice_date, due_date, vendor, "
            "bill_to, payment_terms, line_items[{description, quantity, "
            "unit_price, amount}], subtotal, tax_rate_pct, tax_amount, total_due."
        )
    )


class DiscrepancyCheckTool(BaseTool):
    name: str = "compare_contract_to_invoice"
    description: str = (
        "Compares extracted contract terms against extracted invoice data and "
        "returns every discrepancy as structured JSON: per-item unit price "
        "differences, items billed that the contract never authorized, "
        "contracted items that were not billed, line-total and subtotal and "
        "tax and grand-total arithmetic checks, payment-terms and due-date "
        "conflicts, and the net financial impact. All arithmetic is done "
        "inside this tool — pass it the extracted data and use the numbers it "
        "returns rather than calculating anything yourself."
    )
    args_schema: Type[BaseModel] = DiscrepancyCheckInput

    def _run(self, contract_json: str, invoice_json: str) -> str:
        try:
            contract = ContractTerms.model_validate_json(contract_json)
            invoice = InvoiceData.model_validate_json(invoice_json)
        except ValidationError as exc:
            return (
                "Could not parse the extracted data. Fix the JSON and call the "
                f"tool again. Validation errors:\n{exc}"
            )
        except Exception as exc:  # malformed JSON string
            return f"Input was not valid JSON: {exc}"

        findings: list[dict] = []
        findings.extend(_check_line_items(contract, invoice))
        findings.extend(_check_invoice_arithmetic(invoice))
        findings.extend(_check_contract_expected_total(contract, invoice))
        findings.extend(_check_payment_terms(contract, invoice))
        findings.extend(_check_identifiers(contract, invoice))

        severity_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
        findings.sort(key=lambda f: (severity_rank.get(f["severity"], 9), f["item"]))

        overbilled = _money(
            sum(f.get("financial_impact", 0.0) for f in findings if f.get("financial_impact", 0.0) > 0)
        )
        underbilled = _money(
            sum(f.get("financial_impact", 0.0) for f in findings if f.get("financial_impact", 0.0) < 0)
        )

        summary = {
            "invoice_number": invoice.invoice_number,
            "vendor": invoice.vendor or contract.vendor,
            "buyer": invoice.bill_to or contract.buyer,
            "invoice_total_due": invoice.total_due,
            "discrepancies_found": len(findings),
            "by_severity": {
                level: sum(1 for f in findings if f["severity"] == level)
                for level in ("high", "medium", "low", "info")
            },
            "overbilled_amount": overbilled,
            "underbilled_amount": underbilled,
            "net_financial_impact_to_buyer": _money(overbilled + underbilled),
            "net_impact_note": (
                "Positive means the buyer was billed more than the contract "
                "supports; negative means less. A net of 0.00 does not mean the "
                "invoice is correct — offsetting line-item errors cancel out."
            ),
        }

        return json.dumps({"summary": summary, "discrepancies": findings}, indent=2)


def _match_contract_item(contract_index: dict, description: str):
    """Find the contract item for an invoice line: exact key, else closest match."""
    key = _normalize(description)
    if key in contract_index:
        return contract_index[key]
    close = difflib.get_close_matches(key, list(contract_index), n=1, cutoff=MATCH_THRESHOLD)
    return contract_index[close[0]] if close else None


def _check_line_items(contract: ContractTerms, invoice: InvoiceData) -> list[dict]:
    """Match invoice lines to contract items and compare unit prices."""
    findings: list[dict] = []
    contract_index = {_normalize(item.description): item for item in contract.line_items}
    matched_contract_keys: set[str] = set()

    for line in invoice.line_items:
        key = _normalize(line.description)
        match = contract_index.get(key)
        match_key = key
        match_quality = "exact"

        if match is None:
            close = difflib.get_close_matches(
                key, list(contract_index), n=1, cutoff=MATCH_THRESHOLD
            )
            if close:
                match_key = close[0]
                match = contract_index[match_key]
                match_quality = "fuzzy"

        if match is None:
            findings.append(
                {
                    "item": line.description,
                    "type": "unauthorized_item",
                    "severity": "high",
                    "detail": (
                        f"'{line.description}' is billed on the invoice but no "
                        "matching item appears in the contract's scope or price list."
                    ),
                    "contract_value": None,
                    "invoice_value": _money(line.amount),
                    "financial_impact": _money(line.amount),
                }
            )
            continue

        matched_contract_keys.add(match_key)

        if match_quality == "fuzzy":
            findings.append(
                {
                    "item": line.description,
                    "type": "description_mismatch",
                    "severity": "low",
                    "detail": (
                        f"Invoice line '{line.description}' was matched to contract "
                        f"item '{match.description}' by similarity, not exact wording. "
                        "Confirm they are the same deliverable."
                    ),
                    "contract_value": match.description,
                    "invoice_value": line.description,
                    "financial_impact": 0.0,
                }
            )

        if not _close(line.unit_price, match.unit_price):
            delta_per_unit = _money(line.unit_price - match.unit_price)
            impact = _money(delta_per_unit * line.quantity)
            overcharge = delta_per_unit > 0
            findings.append(
                {
                    "item": line.description,
                    "type": "unit_price_overcharge" if overcharge else "unit_price_undercharge",
                    "severity": "high" if overcharge else "medium",
                    "detail": (
                        f"Contract price is {match.unit_price:.2f} per unit but the "
                        f"invoice bills {line.unit_price:.2f} per unit — a difference of "
                        f"{delta_per_unit:+.2f} per unit across {line.quantity:g} unit(s), "
                        f"worth {impact:+.2f} "
                        f"{'in the vendor' if overcharge else 'in the buyer'}'s favour."
                    ),
                    "contract_value": _money(match.unit_price),
                    "invoice_value": _money(line.unit_price),
                    "quantity": line.quantity,
                    "financial_impact": impact,
                }
            )

    for key, item in contract_index.items():
        if key not in matched_contract_keys:
            findings.append(
                {
                    "item": item.description,
                    "type": "contracted_but_not_invoiced",
                    "severity": "info",
                    "detail": (
                        f"'{item.description}' is priced in the contract at "
                        f"{item.unit_price:.2f} per unit but does not appear on this "
                        "invoice. This may be expected if it has not been delivered yet."
                    ),
                    "contract_value": _money(item.unit_price),
                    "invoice_value": None,
                    "financial_impact": 0.0,
                }
            )

    return findings


def _check_invoice_arithmetic(invoice: InvoiceData) -> list[dict]:
    """Verify the invoice adds up on its own terms, before any contract comparison."""
    findings: list[dict] = []

    for line in invoice.line_items:
        expected = _money(line.quantity * line.unit_price)
        if not _close(expected, line.amount):
            findings.append(
                {
                    "item": line.description,
                    "type": "line_total_arithmetic_error",
                    "severity": "high",
                    "detail": (
                        f"{line.quantity:g} x {line.unit_price:.2f} = {expected:.2f}, but "
                        f"the invoice prints {line.amount:.2f} for this line."
                    ),
                    "contract_value": None,
                    "invoice_value": _money(line.amount),
                    "financial_impact": _money(line.amount - expected),
                }
            )

    computed_subtotal = _money(sum(line.amount for line in invoice.line_items))
    if invoice.subtotal is not None and not _close(computed_subtotal, invoice.subtotal):
        findings.append(
            {
                "item": "Subtotal",
                "type": "subtotal_arithmetic_error",
                "severity": "high",
                "detail": (
                    f"Line amounts sum to {computed_subtotal:.2f} but the invoice prints "
                    f"a subtotal of {invoice.subtotal:.2f}."
                ),
                "contract_value": None,
                "invoice_value": _money(invoice.subtotal),
                "financial_impact": _money(invoice.subtotal - computed_subtotal),
            }
        )

    subtotal = invoice.subtotal if invoice.subtotal is not None else computed_subtotal

    expected_tax = None
    if invoice.tax_rate_pct is not None:
        expected_tax = _money(subtotal * invoice.tax_rate_pct / 100)
        if invoice.tax_amount is not None and not _close(expected_tax, invoice.tax_amount):
            findings.append(
                {
                    "item": "Sales tax",
                    "type": "tax_calculation_error",
                    "severity": "high",
                    "detail": (
                        f"{invoice.tax_rate_pct:g}% of {subtotal:.2f} is {expected_tax:.2f}, "
                        f"but the invoice charges {invoice.tax_amount:.2f}."
                    ),
                    "contract_value": None,
                    "invoice_value": _money(invoice.tax_amount),
                    "financial_impact": _money(invoice.tax_amount - expected_tax),
                }
            )

    tax = invoice.tax_amount if invoice.tax_amount is not None else (expected_tax or 0.0)
    if invoice.total_due is not None:
        expected_total = _money(subtotal + tax)
        if not _close(expected_total, invoice.total_due):
            findings.append(
                {
                    "item": "Total due",
                    "type": "total_arithmetic_error",
                    "severity": "high",
                    "detail": (
                        f"Subtotal {subtotal:.2f} + tax {tax:.2f} = {expected_total:.2f}, "
                        f"but the invoice demands {invoice.total_due:.2f}."
                    ),
                    "contract_value": None,
                    "invoice_value": _money(invoice.total_due),
                    "financial_impact": _money(invoice.total_due - expected_total),
                }
            )

    return findings


def _check_contract_expected_total(contract: ContractTerms, invoice: InvoiceData) -> list[dict]:
    """Reprice the invoice at contract rates and compare the bottom line.

    This is what catches the case where individual lines are wrong but the
    errors offset, leaving a correct-looking total.
    """
    if not contract.line_items or not invoice.line_items:
        return []

    contract_index = {_normalize(item.description): item for item in contract.line_items}
    expected_subtotal = 0.0
    priced_every_line = True

    for line in invoice.line_items:
        match = _match_contract_item(contract_index, line.description)
        if match is None:
            priced_every_line = False
            expected_subtotal += line.amount
        else:
            expected_subtotal += match.unit_price * line.quantity

    expected_subtotal = _money(expected_subtotal)
    actual_subtotal = (
        invoice.subtotal
        if invoice.subtotal is not None
        else _money(sum(line.amount for line in invoice.line_items))
    )

    rate = invoice.tax_rate_pct or 0.0
    expected_total = _money(expected_subtotal * (1 + rate / 100))

    if _close(expected_subtotal, actual_subtotal):
        offsetting = any(
            (match := _match_contract_item(contract_index, line.description)) is not None
            and not _close(line.unit_price, match.unit_price)
            for line in invoice.line_items
        )
        detail = (
            f"Repricing every billed line at contract rates also gives a subtotal of "
            f"{expected_subtotal:.2f}, matching the invoice."
        )
        if offsetting:
            detail += (
                " The line-item price discrepancies listed above offset each other "
                "exactly — the bottom line looks correct, but the individual charges "
                "do not match the contract."
            )
        return [
            {
                "item": "Invoice total vs contract pricing",
                "type": "totals_agree_despite_line_errors" if offsetting else "totals_agree",
                "severity": "medium" if offsetting else "info",
                "detail": detail,
                "contract_value": expected_subtotal,
                "invoice_value": _money(actual_subtotal),
                "financial_impact": 0.0,
            }
        ]

    note = (
        ""
        if priced_every_line
        else " Some billed lines had no contract price and were taken at invoice value."
    )
    return [
        {
            "item": "Invoice total vs contract pricing",
            "type": "total_vs_contract_mismatch",
            "severity": "high",
            "detail": (
                f"Repricing every billed line at contract rates gives a subtotal of "
                f"{expected_subtotal:.2f} (total with {rate:g}% tax: {expected_total:.2f}), "
                f"but the invoice subtotal is {actual_subtotal:.2f}.{note}"
            ),
            "contract_value": expected_subtotal,
            "invoice_value": _money(actual_subtotal),
            "financial_impact": _money(actual_subtotal - expected_subtotal),
        }
    ]


def _check_payment_terms(contract: ContractTerms, invoice: InvoiceData) -> list[dict]:
    """Compare the payment window, and check the printed due date honours it."""
    findings: list[dict] = []
    contract_days = contract.payment_terms_net_days
    invoice_days = _net_days_from_terms(invoice.payment_terms)

    if contract_days is not None and invoice_days is not None and contract_days != invoice_days:
        findings.append(
            {
                "item": "Payment terms",
                "type": "payment_terms_mismatch",
                "severity": "medium",
                "detail": (
                    f"The contract sets Net {contract_days} days from the invoice date, "
                    f"but the invoice states Net {invoice_days}."
                ),
                "contract_value": f"Net {contract_days}",
                "invoice_value": invoice.payment_terms,
                "financial_impact": 0.0,
            }
        )

    effective_days = contract_days if contract_days is not None else invoice_days
    invoice_date = _parse_date(invoice.invoice_date)
    due_date = _parse_date(invoice.due_date)

    if effective_days is not None and invoice_date and due_date:
        expected_due = invoice_date + timedelta(days=effective_days)
        if expected_due.date() != due_date.date():
            actual_gap = (due_date - invoice_date).days
            findings.append(
                {
                    "item": "Due date",
                    "type": "due_date_mismatch",
                    "severity": "medium",
                    "detail": (
                        f"Invoice date {invoice_date:%B %d, %Y} plus Net {effective_days} "
                        f"is {expected_due:%B %d, %Y}, but the invoice states a due date of "
                        f"{due_date:%B %d, %Y} ({actual_gap} days)."
                    ),
                    "contract_value": f"{expected_due:%B %d, %Y}",
                    "invoice_value": invoice.due_date,
                    "financial_impact": 0.0,
                }
            )

    if contract.payment_methods and invoice.payment_method:
        permitted = [_normalize(m) for m in contract.payment_methods]
        used = _normalize(invoice.payment_method)
        # The contract's catch-all ("or other mutually agreed method") makes any
        # method permissible, so only flag when no such escape hatch exists.
        has_catch_all = any("agreed" in m or "other" in m for m in permitted)
        if not has_catch_all and not any(used in m or m in used for m in permitted):
            findings.append(
                {
                    "item": "Payment method",
                    "type": "payment_method_mismatch",
                    "severity": "low",
                    "detail": (
                        f"The invoice requests payment by '{invoice.payment_method}', which "
                        f"is not among the contract's permitted methods: "
                        f"{', '.join(contract.payment_methods)}."
                    ),
                    "contract_value": ", ".join(contract.payment_methods),
                    "invoice_value": invoice.payment_method,
                    "financial_impact": 0.0,
                }
            )

    return findings


def _check_identifiers(contract: ContractTerms, invoice: InvoiceData) -> list[dict]:
    """Confirm the two documents actually refer to each other."""
    findings: list[dict] = []

    if contract.referenced_invoice_number and invoice.invoice_number:
        if _normalize(contract.referenced_invoice_number) != _normalize(invoice.invoice_number):
            findings.append(
                {
                    "item": "Invoice number",
                    "type": "document_linkage_mismatch",
                    "severity": "high",
                    "detail": (
                        f"The contract governs invoice "
                        f"'{contract.referenced_invoice_number}' but this invoice is "
                        f"'{invoice.invoice_number}' — the documents may not correspond."
                    ),
                    "contract_value": contract.referenced_invoice_number,
                    "invoice_value": invoice.invoice_number,
                    "financial_impact": 0.0,
                }
            )

    if contract.vendor and invoice.vendor:
        if _normalize(contract.vendor) not in _normalize(invoice.vendor) and _normalize(
            invoice.vendor
        ) not in _normalize(contract.vendor):
            findings.append(
                {
                    "item": "Vendor",
                    "type": "vendor_mismatch",
                    "severity": "medium",
                    "detail": (
                        f"The contract names vendor '{contract.vendor}' but the invoice is "
                        f"issued by '{invoice.vendor}'."
                    ),
                    "contract_value": contract.vendor,
                    "invoice_value": invoice.vendor,
                    "financial_impact": 0.0,
                }
            )

    return findings
