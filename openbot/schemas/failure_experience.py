"""FailureExperience Schema - 失败经验记录，编排 Agent 模式 D 输出."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FailureStage = Literal["planning", "execution", "audit"]
FailureType = Literal[
    "tool_missing",
    "env_opaque",
    "plan_assumption_wrong",
    "model_understanding_error",
    "unknown",
]


class FailureExperience(BaseModel):
    """失败经验记录，用于结构化记录一次任务执行中「值得学习的失败或问题」。
    
    为后续 Planner Mode A 提供负面样本参考。
    """

    failure_id: str
    task: str
    plan_id: str | None = None
    trace_id: str
    failure_stage: FailureStage
    failure_step_id: int | None = None
    failure_type: FailureType
    summary: str
    root_cause_hypothesis: str
    context_snippets: list[str] = Field(default_factory=list)
    lessons_learned: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
