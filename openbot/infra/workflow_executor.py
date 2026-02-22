"""Workflow executor for executing workflow templates."""

from __future__ import annotations

from typing import Any

from openbot.infra.capability_registry import Capability
from openbot.infra.template_registry import TemplateRegistry


class WorkflowExecutor:
    """执行 Workflow 层能力（按模板执行）。"""

    def __init__(
        self,
        template_registry: TemplateRegistry,
        execution_agent: Any,  # ExecutionAgent 实例，用于递归执行
    ) -> None:
        self._template_registry = template_registry
        self._execution_agent = execution_agent

    async def execute(
        self,
        workflow: Capability,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """执行 Workflow 能力。
        
        从 TemplateRegistry 获取 Workflow 模板，然后按步骤执行。
        """
        # 从 TemplateRegistry 获取模板
        template = self._template_registry.get(workflow.name)
        if not template:
            return {
                "error": f"Workflow template '{workflow.name}' not found",
                "status": "fail"
            }
        
        # TODO: 按照模板的步骤定义执行
        # 目前返回占位实现
        return {
            "result": f"Workflow '{workflow.name}' executed (placeholder)",
            "status": "success",
            "note": "Workflow execution not fully implemented yet"
        }
