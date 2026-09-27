"""Pydantic models for statement imports."""
from typing import Optional, List
from pydantic import BaseModel, Field


class RowCorrectionIn(BaseModel):
    transaction_date: Optional[str] = None
    direction: Optional[str] = None
    amount: Optional[float] = None
    narration: Optional[str] = Field(None, max_length=500)
    bank_reference: Optional[str] = Field(None, max_length=80)


class SendIn(BaseModel):
    rows: List[int] = Field(..., min_length=1, max_length=2000)
