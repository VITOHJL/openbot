from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .plan_spec import CapabilityLevel


TraceStatus = Literal["success", "fail"]


class ExecutionStepModel(BaseModel):
    step_id: int
    capability: str
    capability_level: CapabilityLevel
    inputs: dict
    outputs: dict | None = None
    duration_ms: int | None = None
    llm_decision: str | None = None
    context_snapshot: dict | None = None


class ExecutionTraceModel(BaseModel):
    trace_id: str
    task: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: datetime | None = None
    status: TraceStatus | None = None
    steps: list[ExecutionStepModel] = Field(default_factory=list)
    final_result: str | None = None

