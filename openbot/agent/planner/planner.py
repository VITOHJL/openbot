"""Orchestration Agent main entry point."""

from __future__ import annotations

from typing import Literal

from openbot.agent.planner.mode_a_task_plan import ModeATaskPlan
from openbot.agent.planner.mode_b_template_extract import ModeBTemplateExtract
from openbot.agent.planner.mode_c_test_generation import ModeCTestGeneration
from openbot.infra.capability_registry import CapabilityRegistry
from openbot.infra.log_service import LogService
from openbot.infra.template_registry import TemplateRegistry
from openbot.infra.test_case_store import TestCaseStore
from openbot.providers.base import LLMProvider
from openbot.schemas.audit_report import AuditReport
from openbot.schemas.execution_trace import ExecutionTraceModel as ExecutionTrace
from openbot.schemas.plan_spec import PlanSpec
from openbot.schemas.test_case_spec import TestCaseSpec
from openbot.schemas.workflow_spec import CandidateWorkflowSpec


class OrchestrationAgent:
    """编排 Agent 主入口。
    
    支持三种模式：
    - Mode A: 任务拆解 Plan 设计
    - Mode B: 从成功执行日志抽象 Workflow
    - Mode C: 为能力/Workflow 生成测试用例
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        capability_registry: CapabilityRegistry,
        log_service: LogService,
        template_registry: TemplateRegistry,
        test_case_store: TestCaseStore,
        model: str | None = None,
        temperature: float = 0.7,
    ) -> None:
        self._provider = provider
        self._cap_reg = capability_registry
        self._log_svc = log_service
        self._template_reg = template_registry
        self._test_store = test_case_store
        self._model = model or provider.get_default_model()
        self._temperature = temperature
        
        # 初始化三种模式
        self._mode_a = ModeATaskPlan(
            provider=provider,
            capability_registry=capability_registry,
            model=self._model,
            temperature=self._temperature,
        )
        self._mode_b = ModeBTemplateExtract(
            provider=provider,
            capability_registry=capability_registry,
            model=self._model,
            temperature=self._temperature,
        )
        self._mode_c = ModeCTestGeneration(
            provider=provider,
            capability_registry=capability_registry,
            test_case_store=test_case_store,
            model=self._model,
            temperature=self._temperature,
        )

    async def plan_task(
        self,
        task: str,
        context: dict | None = None,
    ) -> PlanSpec:
        """模式 A: 任务拆解 Plan 设计。
        
        Args:
            task: 任务描述
            context: 可选上下文信息
        
        Returns:
            PlanSpec 对象
        """
        return await self._mode_a.generate_plan(task, context)

    async def extract_workflow(
        self,
        trace_id: str,
        audit_report: AuditReport | None = None,
    ) -> CandidateWorkflowSpec:
        """模式 B: 从成功执行日志抽象 Workflow。
        
        Args:
            trace_id: 执行轨迹 ID
            audit_report: 可选的审计报告
        
        Returns:
            CandidateWorkflowSpec 对象
        """
        # 读取执行轨迹
        trace = self._log_svc.get_trace(trace_id)
        if not trace:
            raise ValueError(f"Execution trace not found: {trace_id}")
        
        return await self._mode_b.extract_workflow(trace, audit_report)

    async def generate_test_cases(
        self,
        capability_name: str,
        test_types: list[Literal["normal", "boundary", "error", "extreme"]] | None = None,
    ) -> list[TestCaseSpec]:
        """模式 C: 为能力/Workflow 生成测试用例。
        
        Args:
            capability_name: 能力名称
            test_types: 要生成的测试类型列表，如果为 None 则生成所有类型
        
        Returns:
            TestCaseSpec 列表
        """
        if test_types is None:
            test_types = ["normal", "boundary", "error", "extreme"]
        
        return await self._mode_c.generate_test_cases(capability_name, test_types)
