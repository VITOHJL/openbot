"""Audit case builder - 构建审计 Case."""

from __future__ import annotations

import json
from typing import Any

from openbot.infra.capability_registry import CapabilityRegistry
from openbot.infra.template_registry import TemplateRegistry
from openbot.schemas.execution_trace import ExecutionTraceModel as ExecutionTrace


class AuditCaseBuilder:
    """构建审计 Case。
    
    组装审计输入（JSON），包含执行轨迹、用户视图、能力定义等。
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        template_registry: TemplateRegistry,
    ) -> None:
        self._cap_reg = capability_registry
        self._template_reg = template_registry

    def build_case(
        self,
        trace: ExecutionTrace,
        user_view: dict | None = None,
    ) -> dict[str, Any]:
        """构建审计 Case。
        
        Args:
            trace: 执行轨迹
            user_view: 可选的用户视图
        
        Returns:
            审计 Case 字典
        """
        case = {
            "trace_id": trace.trace_id,
            "task": trace.task,
            "status": trace.status,
            "started_at": trace.started_at.isoformat() if trace.started_at else None,
            "ended_at": trace.ended_at.isoformat() if trace.ended_at else None,
            "final_result": trace.final_result,
            "steps": [],
        }
        
        # 添加步骤信息
        for step in trace.steps:
            step_info = {
                "step_id": step.step_id,
                "capability": step.capability,
                "capability_level": step.capability_level,
                "inputs": step.inputs,
                "outputs": step.outputs,
                "duration_ms": step.duration_ms,
                "llm_decision": step.llm_decision,
            }
            
            # 获取能力定义（如果有）
            capability = self._cap_reg.get(step.capability)
            if capability:
                step_info["capability_definition"] = {
                    "name": capability.name,
                    "description": capability.description,
                    "level": capability.level,
                    "schema": capability.schema,
                }
            
            case["steps"].append(step_info)
        
        # 添加用户视图（如果有）
        if user_view:
            case["user_view"] = user_view
        
        return case
