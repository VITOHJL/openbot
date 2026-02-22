from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


CapabilityLevel = Literal["workflow", "skill", "atomic"]


class PlanStep(BaseModel):
    step_id: int = Field(..., description="步骤 ID")
    capability: str = Field(..., description="能力名称")
    capability_level: CapabilityLevel = Field(..., description="能力层级")
    inputs: dict = Field(default_factory=dict, description="输入参数")
    success_criteria: str = Field("", description="成功标准描述")
    dependencies: list[int] = Field(default_factory=list, description="依赖的步骤 ID 列表")
    optional: bool = Field(False, description="是否可选步骤")


class PlanSpec(BaseModel):
    plan_id: str = Field(..., description="Plan 唯一 ID")
    task: str = Field(..., description="任务描述")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    steps: list[PlanStep] = Field(default_factory=list)

