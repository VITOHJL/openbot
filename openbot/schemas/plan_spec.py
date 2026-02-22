from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


CapabilityLevel = Literal["workflow", "skill", "atomic"]


class SuccessCriteria(BaseModel):
    """子任务成功标准（结构化，可在执行时进行确定性校验）"""

    status: Literal["success", "partial", "any"] = Field(
        "success", description="期望的状态"
    )
    required_fields: list[str] = Field(
        default_factory=list, description="输出中必须包含的字段"
    )
    field_checks: dict[str, dict] = Field(
        default_factory=dict, description="字段验证规则（JSON Schema 片段或约定格式）"
    )
    custom_validator: str | None = Field(
        None, description="自定义验证逻辑（Python 代码字符串或 DSL，可选）"
    )


class RetryPolicy(BaseModel):
    """子任务级重试策略"""

    max_retries: int = Field(3, ge=0, le=10)
    backoff_strategy: Literal["linear", "exponential", "fixed"] = Field(
        "exponential"
    )
    initial_delay_ms: int = Field(1000, ge=0)
    max_delay_ms: int = Field(60000, ge=0)


class PlanStep(BaseModel):
    """单个子任务步骤定义"""

    step_id: int = Field(..., ge=1, description="步骤 ID（从 1 开始）")

    # 子任务目标与推荐完成方式
    subtask_goal: str = Field(
        ..., min_length=1, description="子任务目标（要达到的状态）"
    )
    capability: str = Field(
        "", description="推荐使用的能力名称（可为空，表示暂不指定）"
    )
    capability_level: CapabilityLevel = Field(
        "atomic", description="推荐能力层级（workflow/skill/atomic）"
    )

    # 输入与 Schema
    inputs: dict[str, Any] = Field(
        default_factory=dict, description="推荐的输入参数（可由执行阶段进一步补全）"
    )
    inputs_schema: dict[str, Any] | None = Field(
        default=None,
        description="输入参数的 JSON Schema 定义（可选，若提供则用于执行期参数校验）",
    )

    # 成功标准与依赖
    success_criteria: SuccessCriteria = Field(
        default_factory=SuccessCriteria, description="成功标准（结构化，可验证）"
    )
    dependencies: list[int] = Field(
        default_factory=list, description="依赖的步骤 ID 列表"
    )
    optional: bool = Field(False, description="是否可选步骤")

    # 执行控制
    retry_policy: RetryPolicy | None = Field(
        default=None, description="重试策略（如果为 None，则不额外重试）"
    )
    timeout_seconds: int | None = Field(
        default=None, ge=1, description="子任务超时限制（秒，可选）"
    )
    execution_mode: Literal["strict", "flexible"] = Field(
        "strict", description="子任务执行模式：strict=严格按 Plan，flexible=允许一定偏离"
    )
    deviation_allowed: bool = Field(
        False, description="是否允许在执行阶段偏离推荐方式"
    )
    deviation_reason_required: bool = Field(
        True, description="偏离时是否需要记录原因（供日志/审计使用）"
    )

    @field_validator("inputs_schema")
    @classmethod
    def validate_inputs_schema(cls, v: dict | None) -> dict | None:
        """若提供 inputs_schema，则必须是 type=object 的合法 JSON Schema 片段"""
        if v is None:
            return v
        if not isinstance(v, dict):
            raise ValueError("inputs_schema 必须是字典（JSON Schema 片段）")
        if v.get("type") != "object":
            raise ValueError("inputs_schema.type 必须为 'object'")
        return v

    @field_validator("dependencies")
    @classmethod
    def validate_dependencies(cls, v: list[int], info) -> list[int]:
        # 简单防御：步骤不能依赖自己；更复杂的检查在 PlanSpec 级别完成
        step_id = info.data.get("step_id")
        if step_id in v:
            raise ValueError(f"步骤 {step_id} 不能依赖自己")
        return v


class PlanSpec(BaseModel):
    """任务执行 Plan 规范"""

    plan_id: str = Field(..., min_length=1, description="Plan 唯一 ID")
    task: str = Field(..., min_length=1, description="任务描述")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    steps: list[PlanStep] = Field(
        ..., min_length=1, description="执行步骤列表（至少一个步骤）"
    )

    execution_mode: Literal["strict", "flexible"] = Field(
        "strict", description="整体 Plan 执行模式"
    )
    max_deviations: int = Field(
        0, ge=0, description="允许的最大偏离次数（0 表示不允许偏离）"
    )
    deviation_log_required: bool = Field(
        True, description="是否要求对所有偏离记录详细日志"
    )

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, v: list[PlanStep]) -> list[PlanStep]:
        if not v:
            raise ValueError("Plan 必须包含至少一个步骤")
        step_ids = [s.step_id for s in v]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("步骤 ID 必须唯一")
        all_step_ids = set(step_ids)
        for step in v:
            for dep_id in step.dependencies:
                if dep_id not in all_step_ids:
                    raise ValueError(f"步骤 {step.step_id} 依赖的步骤 {dep_id} 不存在")
        return v