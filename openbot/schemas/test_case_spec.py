from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TestCaseType = Literal["normal", "boundary", "error", "extreme"]


class ToleranceSpec(BaseModel):
    exact_match: bool = False
    fields_to_ignore: list[str] = Field(default_factory=list)


class TestCaseSpec(BaseModel):
    test_id: str
    capability: str
    type: TestCaseType = "normal"
    input: dict
    expected_output: dict
    tolerance: ToleranceSpec = Field(default_factory=ToleranceSpec)
    created_at: datetime = Field(default_factory=datetime.utcnow)

