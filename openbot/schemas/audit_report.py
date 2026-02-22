from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Verdict = Literal["pass", "fail", "warning"]
RiskLevel = Literal["low", "medium", "high"]
IssueType = Literal["lie", "unauthorized", "incomplete_log", "intermediate_error"]


class Evidence(BaseModel):
    step_id: int | None = None
    log_key: str | None = None
    user_statement: str | None = None
    actual_result: str | None = None
    corrected_by_step: int | None = None  # 可选：被哪个步骤修正了


class AuditIssue(BaseModel):
    type: IssueType
    description: str
    evidence: Evidence | None = None


class AuditReport(BaseModel):
    audit_id: str
    execution_trace_id: str
    audited_at: datetime = Field(default_factory=datetime.utcnow)
    verdict: Verdict
    risk_level: RiskLevel
    issues: list[AuditIssue] = Field(default_factory=list)
    template_candidate_eligible: bool = False

