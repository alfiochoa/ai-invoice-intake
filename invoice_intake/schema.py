from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class LineItem(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: Optional[float] = None
    amount: float

    @field_validator("quantity", mode="before")
    @classmethod
    def _qty(cls, v):
        return 1.0 if v is None else v


class Invoice(BaseModel):
    """Structured output every extractor (LLM or rules) must produce."""

    vendor: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    currency: str = "USD"
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None

    @field_validator("currency", mode="before")
    @classmethod
    def _cur(cls, v):
        return v or "USD"


class Issue(BaseModel):
    code: str
    message: str
    severity: str = "error"  # error -> human review
