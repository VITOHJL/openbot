from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .plan_spec import CapabilityLevel


class WorkflowStepSpec(BaseModel):
    step_id: int
    capability: str
    capability_level: CapabilityLevel = "skill"
    inputs_schema: dict = Field(default_factory=dict)
    conditions: dict | None = None
    retry: dict | None = None


class WorkflowSpec(BaseModel):
    workflow_id: str
    name: str
    description: str = ""
    source_trace_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    steps: list[WorkflowStepSpec] = Field(default_factory=list)


# CandidateWorkflowSpec 是 WorkflowSpec 的别名（用于模式 B 输出）
CandidateWorkflowSpec = WorkflowSpec

