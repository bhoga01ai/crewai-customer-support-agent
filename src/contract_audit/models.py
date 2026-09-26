"""Structured shapes the extraction agents fill in, shared with the audit tool.

Keeping these in one place means the Pydantic models that constrain each
extraction task's output are literally the same models the comparison tool
validates its input against — so a malformed extraction fails loudly at the
tool boundary instead of silently producing an empty discrepancy report.
"""

from typing import Optional

from pydantic import BaseModel, Field


class ContractLineItem(BaseModel):
    """A single priced good or service as the contract defines it."""

    description: str = Field(
        description="The item name exactly as written in the contract."
    )
    unit_price: float = Field(
        description="Agreed price per unit, as a number without currency symbols."
    )
    pricing_basis: Optional[str] = Field(
        default=None,
        description="How the price is charged, e.g. 'per unit', 'per hour', 'flat fee'.",
    )


class ContractTerms(BaseModel):
    """Everything the audit needs from the contract side."""

    vendor: Optional[str] = Field(default=None, description="Vendor / supplier name.")
    buyer: Optional[str] = Field(
        default=None,
        description="Buyer name, or a note if the contract only references 'the Buyer'.",
    )
    referenced_invoice_number: Optional[str] = Field(
        default=None,
        description="Invoice number the contract governs, if it names one.",
    )
    line_items: list[ContractLineItem] = Field(
        default_factory=list,
        description="Every priced deliverable listed in the contract.",
    )
    payment_terms_net_days: Optional[int] = Field(
        default=None,
        description="Payment window in days, e.g. 14 for 'Net 14 days'.",
    )
    payment_methods: list[str] = Field(
        default_factory=list,
        description="Payment methods the contract permits.",
    )
    tax_responsibility: Optional[str] = Field(
        default=None,
        description="What the contract says about sales tax and who pays it.",
    )
    governing_law: Optional[str] = Field(default=None)
    other_obligations: list[str] = Field(
        default_factory=list,
        description=(
            "Other clauses that could affect billing — revision policy, delivery "
            "and acceptance windows, termination, IP transfer conditions."
        ),
    )


class InvoiceLineItem(BaseModel):
    """A single billed line as the invoice presents it."""

    description: str = Field(
        description="The item name exactly as written on the invoice."
    )
    quantity: float = Field(description="Quantity billed.")
    unit_price: float = Field(description="Price per unit, as a number.")
    amount: float = Field(
        description="Line total as printed on the invoice — do NOT recompute it."
    )


class InvoiceData(BaseModel):
    """Everything the audit needs from the invoice side."""

    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = Field(
        default=None, description="Invoice date exactly as printed."
    )
    due_date: Optional[str] = Field(
        default=None, description="Due date exactly as printed."
    )
    vendor: Optional[str] = None
    bill_to: Optional[str] = Field(default=None, description="Customer being billed.")
    payment_terms: Optional[str] = Field(
        default=None, description="Terms as printed, e.g. 'Net 14'."
    )
    payment_method: Optional[str] = None
    currency: str = Field(default="USD")
    line_items: list[InvoiceLineItem] = Field(default_factory=list)
    subtotal: Optional[float] = Field(
        default=None, description="Subtotal as printed — do NOT recompute it."
    )
    tax_rate_pct: Optional[float] = Field(
        default=None, description="Tax rate as a percentage number, e.g. 8.25."
    )
    tax_amount: Optional[float] = Field(
        default=None, description="Tax amount as printed."
    )
    total_due: Optional[float] = Field(
        default=None, description="Grand total as printed."
    )
