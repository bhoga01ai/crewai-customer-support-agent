#!/usr/bin/env python
"""Flow entrypoint for the contract vs. invoice discrepancy audit."""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

from crewai.flow import Flow, listen, start

from contract_audit.crews.audit_crew.audit_crew import ContractInvoiceAuditCrew
from contract_audit.tools.document_tools import _resolve_document

# The script entrypoints are run directly (uv run audit), not through the
# crewai CLI, so .env has to be loaded here.
load_dotenv()

OUTPUT_DIR = Path("output")
REPORT_PATH = OUTPUT_DIR / "discrepancy_report.md"


class AuditState(BaseModel):
    contract_path: str = ""
    invoice_path: str = ""
    report: str = ""


class ContractInvoiceAuditFlow(Flow[AuditState]):

    @start()
    def locate_documents(self, crewai_trigger_payload: dict = None):
        """Resolve and verify both PDFs before spending tokens on the crew."""
        if crewai_trigger_payload:
            print(f"Using trigger payload: {crewai_trigger_payload}")
            if contract := crewai_trigger_payload.get("contract_pdf"):
                os.environ["CONTRACT_PDF"] = contract
            if invoice := crewai_trigger_payload.get("invoice_pdf"):
                os.environ["INVOICE_PDF"] = invoice

        contract_path = _resolve_document("contract")
        invoice_path = _resolve_document("invoice")

        missing = [str(p) for p in (contract_path, invoice_path) if not p.exists()]
        if missing:
            raise FileNotFoundError(
                "Cannot run the audit — missing document(s): "
                + ", ".join(missing)
                + ". Place the PDFs in data/documents/, or set CONTRACT_PDF / "
                "INVOICE_PDF to point at them."
            )

        self.state.contract_path = str(contract_path)
        self.state.invoice_path = str(invoice_path)
        print(f"Contract: {contract_path.name}")
        print(f"Invoice:  {invoice_path.name}")

    @listen(locate_documents)
    def run_audit(self):
        print("Running the contract vs. invoice discrepancy audit crew")
        result = ContractInvoiceAuditCrew().crew().kickoff(
            inputs={
                "contract_path": self.state.contract_path,
                "invoice_path": self.state.invoice_path,
                # Supplied rather than left to the writer, which otherwise
                # guesses a date onto a document finance will act on.
                "audit_date": date.today().strftime("%B %d, %Y"),
            }
        )
        self.state.report = result.raw
        print("Audit complete")

    @listen(run_audit)
    def save_report(self):
        OUTPUT_DIR.mkdir(exist_ok=True)
        REPORT_PATH.write_text(self.state.report)
        print(f"Discrepancy report saved to {REPORT_PATH}")
        print(
            "Supporting artifacts: output/contract_terms.json, "
            "output/invoice_data.json, output/audit_findings.md"
        )


def kickoff():
    """Run the discrepancy audit end to end."""
    ContractInvoiceAuditFlow().kickoff()


def plot():
    ContractInvoiceAuditFlow().plot()


def run_with_trigger():
    """
    Run the audit against a specific document pair, e.g.:
    uv run audit_with_trigger '{"contract_pdf": "other_contract.pdf", "invoice_pdf": "other_invoice.pdf"}'
    """
    import json
    import sys

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    flow = ContractInvoiceAuditFlow()
    try:
        return flow.kickoff({"crewai_trigger_payload": trigger_payload})
    except Exception as e:
        raise Exception(f"An error occurred while running the audit flow: {e}")


if __name__ == "__main__":
    kickoff()
