"""Report generator - 生成审计报告."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from loguru import logger

from openbot.schemas.audit_report import AuditIssue, AuditReport, Evidence
from openbot.schemas.execution_trace import ExecutionTraceModel as ExecutionTrace


class ReportGenerator:
    """生成审计报告。
    
    将 LLM 评估结果转换为 AuditReport 对象。
    """

    def generate_report(
        self,
        trace_id: str,
        judgment: dict[str, Any],
        trace: ExecutionTrace,
    ) -> AuditReport:
        """生成审计报告。
        
        Args:
            trace_id: 执行轨迹 ID
            judgment: LLM 评估结果
            trace: 执行轨迹
        
        Returns:
            AuditReport 对象
        """
        # 转换 issues，过滤已修正的中间错误
        issues = []
        for issue_data in judgment.get("issues", []):
            issue_type = issue_data.get("type", "incomplete_log")
            evidence_data = issue_data.get("evidence", {})
            
            # 如果是中间错误且已被修正，标记但不阻止工作流提取
            corrected_by = evidence_data.get("corrected_by_step")
            if issue_type == "intermediate_error" and corrected_by:
                # 中间错误但已修正，降低风险等级
                # 仍然记录，但标记为已修正
                issue_data["description"] += f" (已在步骤 {corrected_by} 修正)"
            
            evidence = None
            if evidence_data:
                # 规范化 step_id：如果是字符串，尝试转换；如果是 'all' 等特殊值，设为 None
                step_id_raw = evidence_data.get("step_id")
                step_id = None
                if step_id_raw is not None:
                    if isinstance(step_id_raw, int):
                        step_id = step_id_raw
                    elif isinstance(step_id_raw, str):
                        # 尝试转换为整数
                        if step_id_raw.lower() in ["all", "none", "null", ""]:
                            step_id = None
                        else:
                            try:
                                step_id = int(step_id_raw)
                            except (ValueError, TypeError):
                                logger.warning(f"Invalid step_id format: {step_id_raw}, setting to None")
                                step_id = None
                
                # 规范化 corrected_by_step
                corrected_by_raw = evidence_data.get("corrected_by_step")
                corrected_by = None
                if corrected_by_raw is not None:
                    if isinstance(corrected_by_raw, int):
                        corrected_by = corrected_by_raw
                    elif isinstance(corrected_by_raw, str):
                        if corrected_by_raw.lower() in ["all", "none", "null", ""]:
                            corrected_by = None
                        else:
                            try:
                                corrected_by = int(corrected_by_raw)
                            except (ValueError, TypeError):
                                logger.warning(f"Invalid corrected_by_step format: {corrected_by_raw}, setting to None")
                                corrected_by = None
                
                evidence = Evidence(
                    step_id=step_id,
                    log_key=evidence_data.get("log_key"),
                    user_statement=evidence_data.get("user_statement"),
                    actual_result=evidence_data.get("actual_result"),
                    corrected_by_step=corrected_by,
                )
            
            issue = AuditIssue(
                type=issue_type,
                description=issue_data.get("description", ""),
                evidence=evidence,
            )
            issues.append(issue)
        
        # 如果最终成功，即使有中间错误，也允许工作流提取（除非有严重问题）
        template_eligible = judgment.get("template_candidate_eligible", False)
        if trace.status == "success" and not template_eligible:
            # 检查是否有严重问题（撒谎、越权）
            has_severe_issue = any(
                issue.type in ["lie", "unauthorized"] 
                for issue in issues
            )
            if not has_severe_issue:
                # 只有中间错误，允许工作流提取
                template_eligible = True
        
        return AuditReport(
            audit_id=f"audit_{uuid.uuid4().hex[:8]}",
            execution_trace_id=trace_id,
            audited_at=datetime.utcnow(),
            verdict=judgment.get("verdict", "warning"),
            risk_level=judgment.get("risk_level", "medium"),
            issues=issues,
            template_candidate_eligible=template_eligible,
        )
