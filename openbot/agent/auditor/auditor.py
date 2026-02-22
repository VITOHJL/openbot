"""Auditor Agent main entry point."""

from __future__ import annotations

import uuid
from datetime import datetime

from openbot.agent.auditor.case_builder import AuditCaseBuilder
from openbot.agent.auditor.llm_judge import LLMJudge
from openbot.agent.auditor.report_generator import ReportGenerator
from openbot.infra.capability_registry import CapabilityRegistry
from openbot.infra.database import Database
from openbot.infra.log_service import LogService
from openbot.infra.template_registry import TemplateRegistry
from openbot.providers.base import LLMProvider
from openbot.schemas.audit_report import AuditReport
from openbot.schemas.execution_trace import ExecutionTraceModel as ExecutionTrace


class AuditorAgent:
    """日志监督 Agent 主入口。
    
    负责审计执行日志，判定是否撒谎、伪造成功、越权等。
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        capability_registry: CapabilityRegistry,
        log_service: LogService,
        template_registry: TemplateRegistry,
        database: Database | None = None,
        model: str | None = None,
        temperature: float = 0.3,  # 审计需要更低的温度
    ) -> None:
        self._provider = provider
        self._cap_reg = capability_registry
        self._log_svc = log_service
        self._template_reg = template_registry
        self._db = database or Database()
        self._model = model or provider.get_default_model()
        self._temperature = temperature
        
        # 初始化子组件
        self._case_builder = AuditCaseBuilder(
            capability_registry=capability_registry,
            template_registry=template_registry,
        )
        self._llm_judge = LLMJudge(
            provider=provider,
            model=self._model,
            temperature=self._temperature,
        )
        self._report_generator = ReportGenerator()

    async def audit_trace(
        self,
        trace_id: str,
        user_view: dict | None = None,
    ) -> AuditReport:
        """审计执行轨迹。
        
        Args:
            trace_id: 执行轨迹 ID
            user_view: 可选的用户视图（用户看到的回复）
        
        Returns:
            AuditReport 对象
        """
        # 阶段 1: 读取执行数据
        trace = self._log_svc.get_trace(trace_id)
        if not trace:
            raise ValueError(f"Execution trace not found: {trace_id}")
        
        # 阶段 2: 构建审计 Case
        audit_case = self._case_builder.build_case(trace, user_view)
        
        # 阶段 3: 监督 LLM 评估
        judgment = await self._llm_judge.judge(audit_case)
        
        # 阶段 4: 生成审计报告
        report = self._report_generator.generate_report(
            trace_id=trace_id,
            judgment=judgment,
            trace=trace,
        )
        
        # 阶段 5: 持久化审计报告到数据库
        self._db.save_audit_report(report)
        
        return report
