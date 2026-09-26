"""Tests for the deterministic half of the audit.

The agents' extraction quality needs an LLM to evaluate, but the comparison
engine is pure Python and is where a wrong answer would actually cost money —
so it gets real tests. The baseline fixtures are the true contents of
data/documents/*.pdf, which means these also assert that the audit reports
the right findings for the shipped sample documents.
"""

import json

import pytest

from contract_audit.tools.document_tools import DiscrepancyCheckTool


CONTRACT = {
    "vendor": "Brightleaf Studio",
    "buyer": "Northwind Books",
    "referenced_invoice_number": "INV-2026-104",
    "line_items": [
        {"description": "Website design consultation", "unit_price": 85.00},
        {"description": "Homepage wireframe and revisions", "unit_price": 210.00},
        {"description": "Product photo retouching package", "unit_price": 150.00},
        {"description": "Monthly hosting setup", "unit_price": 65.00},
    ],
    "payment_terms_net_days": 14,
    "payment_methods": ["Bank transfer", "other mutually agreed method"],
}

INVOICE = {
    "invoice_number": "INV-2026-104",
    "invoice_date": "March 22, 2026",
    "due_date": "April 05, 2026",
    "vendor": "Brightleaf Studio",
    "bill_to": "Northwind Books",
    "payment_terms": "Net 14",
    "payment_method": "Bank transfer",
    "line_items": [
        {"description": "Website design consultation", "quantity": 2, "unit_price": 85.00, "amount": 170.00},
        {"description": "Homepage wireframe and revisions", "quantity": 1, "unit_price": 220.00, "amount": 220.00},
        {"description": "Product photo retouching package", "quantity": 1, "unit_price": 145.00, "amount": 145.00},
        {"description": "Monthly hosting setup", "quantity": 1, "unit_price": 60.00, "amount": 60.00},
    ],
    "subtotal": 595.00,
    "tax_rate_pct": 8.25,
    "tax_amount": 49.09,
    "total_due": 644.09,
}


def audit(contract=None, invoice=None) -> dict:
    result = DiscrepancyCheckTool()._run(
        json.dumps(contract or CONTRACT), json.dumps(invoice or INVOICE)
    )
    assert not result.startswith("Could not parse"), result
    return json.loads(result)


def types_found(report: dict) -> set[str]:
    return {d["type"] for d in report["discrepancies"]}


def finding(report: dict, kind: str) -> dict:
    matches = [d for d in report["discrepancies"] if d["type"] == kind]
    assert matches, f"expected a {kind} finding, got {sorted(types_found(report))}"
    return matches[0]


def replace_line(invoice: dict, target: str, **changes) -> dict:
    """Copy the invoice with one line's fields overridden."""
    clone = json.loads(json.dumps(invoice))
    for line in clone["line_items"]:
        if line["description"] == target:
            line.update(changes)
    return clone


class TestSampleDocuments:
    """The shipped contract/invoice pair has three unit-price errors that offset."""

    def test_finds_the_overcharged_line(self):
        item = finding(audit(), "unit_price_overcharge")
        assert item["item"] == "Homepage wireframe and revisions"
        assert item["contract_value"] == 210.00
        assert item["invoice_value"] == 220.00
        assert item["financial_impact"] == 10.00
        assert item["severity"] == "high"

    def test_finds_both_undercharged_lines(self):
        undercharges = {
            d["item"]: d
            for d in audit()["discrepancies"]
            if d["type"] == "unit_price_undercharge"
        }
        assert set(undercharges) == {
            "Product photo retouching package",
            "Monthly hosting setup",
        }
        assert all(d["financial_impact"] == -5.00 for d in undercharges.values())

    def test_correctly_priced_line_is_not_flagged(self):
        flagged = {d["item"] for d in audit()["discrepancies"]}
        assert "Website design consultation" not in flagged

    def test_offsetting_errors_are_called_out_despite_matching_total(self):
        report = audit()
        assert report["summary"]["overbilled_amount"] == 10.00
        assert report["summary"]["underbilled_amount"] == -10.00
        assert report["summary"]["net_financial_impact_to_buyer"] == 0.00
        # A zero net must not be reported as a clean invoice.
        assert "totals_agree_despite_line_errors" in types_found(report)

    def test_no_false_positives_on_arithmetic_terms_or_identifiers(self):
        """Every number on the sample invoice is internally consistent."""
        assert types_found(audit()).isdisjoint(
            {
                "line_total_arithmetic_error",
                "subtotal_arithmetic_error",
                "tax_calculation_error",
                "total_arithmetic_error",
                "payment_terms_mismatch",
                "due_date_mismatch",
                "payment_method_mismatch",
                "document_linkage_mismatch",
                "vendor_mismatch",
                "unauthorized_item",
            }
        )


class TestArithmeticChecks:
    def test_line_total_that_does_not_equal_qty_times_price(self):
        invoice = replace_line(INVOICE, "Website design consultation", amount=180.00)
        invoice["subtotal"] = 605.00
        invoice["tax_amount"] = 49.91
        invoice["total_due"] = 654.91
        item = finding(audit(invoice=invoice), "line_total_arithmetic_error")
        assert item["financial_impact"] == 10.00

    def test_subtotal_that_does_not_match_the_lines(self):
        invoice = json.loads(json.dumps(INVOICE))
        invoice["subtotal"] = 620.00
        assert "subtotal_arithmetic_error" in types_found(audit(invoice=invoice))

    def test_wrong_tax_amount(self):
        invoice = json.loads(json.dumps(INVOICE))
        invoice["tax_amount"] = 59.50
        invoice["total_due"] = 654.50
        item = finding(audit(invoice=invoice), "tax_calculation_error")
        assert item["financial_impact"] == pytest.approx(10.41, abs=0.01)

    def test_grand_total_that_does_not_match_subtotal_plus_tax(self):
        invoice = json.loads(json.dumps(INVOICE))
        invoice["total_due"] = 700.00
        assert "total_arithmetic_error" in types_found(audit(invoice=invoice))

    def test_rounded_tax_within_half_a_cent_is_accepted(self):
        """8.25% of 595.00 is 49.0875; the invoice's 49.09 is correct rounding."""
        assert "tax_calculation_error" not in types_found(audit())


class TestScopeChecks:
    def test_item_billed_but_never_contracted(self):
        invoice = json.loads(json.dumps(INVOICE))
        invoice["line_items"].append(
            {"description": "Rush delivery fee", "quantity": 1, "unit_price": 75.00, "amount": 75.00}
        )
        invoice["subtotal"] = 670.00
        item = finding(audit(invoice=invoice), "unauthorized_item")
        assert item["item"] == "Rush delivery fee"
        assert item["severity"] == "high"
        assert item["financial_impact"] == 75.00

    def test_contracted_item_that_was_not_billed(self):
        contract = json.loads(json.dumps(CONTRACT))
        contract["line_items"].append(
            {"description": "Logo redesign", "unit_price": 400.00}
        )
        item = finding(audit(contract=contract), "contracted_but_not_invoiced")
        assert item["item"] == "Logo redesign"
        # Not yet delivered is a normal state, so this must not read as an error.
        assert item["severity"] == "info"
        assert item["financial_impact"] == 0.0

    def test_reworded_item_is_matched_not_reported_as_unauthorized(self):
        invoice = replace_line(
            INVOICE,
            "Product photo retouching package",
            description="Product photo retouching pkg",
        )
        found = types_found(audit(invoice=invoice))
        assert "unauthorized_item" not in found
        assert "description_mismatch" in found


class TestTermsChecks:
    def test_payment_window_shorter_than_the_contract_allows(self):
        invoice = json.loads(json.dumps(INVOICE))
        invoice["payment_terms"] = "Net 7"
        invoice["due_date"] = "March 29, 2026"
        item = finding(audit(invoice=invoice), "payment_terms_mismatch")
        assert item["invoice_value"] == "Net 7"

    def test_due_date_that_does_not_honour_the_contract_window(self):
        invoice = json.loads(json.dumps(INVOICE))
        invoice["due_date"] = "March 29, 2026"
        item = finding(audit(invoice=invoice), "due_date_mismatch")
        assert item["contract_value"] == "April 05, 2026"

    def test_catch_all_payment_clause_permits_any_method(self):
        invoice = json.loads(json.dumps(INVOICE))
        invoice["payment_method"] = "Credit card"
        assert "payment_method_mismatch" not in types_found(audit(invoice=invoice))

    def test_method_outside_a_closed_list_is_flagged(self):
        contract = json.loads(json.dumps(CONTRACT))
        contract["payment_methods"] = ["Bank transfer"]
        invoice = json.loads(json.dumps(INVOICE))
        invoice["payment_method"] = "Credit card"
        assert "payment_method_mismatch" in types_found(
            audit(contract=contract, invoice=invoice)
        )


class TestDocumentLinkage:
    def test_invoice_number_the_contract_does_not_govern(self):
        invoice = json.loads(json.dumps(INVOICE))
        invoice["invoice_number"] = "INV-2026-999"
        item = finding(audit(invoice=invoice), "document_linkage_mismatch")
        assert item["severity"] == "high"

    def test_different_vendor_on_each_document(self):
        invoice = json.loads(json.dumps(INVOICE))
        invoice["vendor"] = "Someone Else LLC"
        assert "vendor_mismatch" in types_found(audit(invoice=invoice))


class TestMalformedInput:
    def test_bad_json_is_reported_rather_than_crashing(self):
        """The agent gets a retryable message, not an exception that kills the run."""
        result = DiscrepancyCheckTool()._run("not json at all", json.dumps(INVOICE))
        assert "Could not parse" in result
        assert "call the tool again" in result

    def test_wrong_shape_is_reported_so_the_agent_can_retry(self):
        result = DiscrepancyCheckTool()._run(
            json.dumps({"line_items": [{"description": "x"}]}), json.dumps(INVOICE)
        )
        assert "Could not parse" in result
