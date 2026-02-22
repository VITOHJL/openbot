"""Mode D: Failure Experience - 从失败执行轨迹和审计结果构建失败经验."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from openbot.providers.base import LLMProvider, LLMResponse
from openbot.schemas.audit_report import AuditReport
from openbot.schemas.execution_trace import ExecutionTraceModel as ExecutionTrace
from openbot.schemas.failure_experience import FailureExperience, FailureStage, FailureType


class ModeDFailureExperience:
    """模式 D: 从失败执行轨迹和审计结果构建失败经验。
    
    从审计报告中提取关键问题，从执行轨迹中抽取相关片段，
    总结为结构化 FailureExperience 记录。
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        temperature: float = 0.7,
    ) -> None:
        self._provider = provider
        self._model = model
        self._temperature = temperature

    async def build_failure_experience(
        self,
        trace: ExecutionTrace,
        audit_report: AuditReport,
        plan_id: str | None = None,
    ) -> FailureExperience:
        """从执行轨迹和审计报告构建失败经验。
        
        Args:
            trace: 执行轨迹
            audit_report: 审计报告
            plan_id: 可选的 Plan ID
        
        Returns:
            FailureExperience 对象
        """
        # 构建提示词
        prompt = self._build_prompt(trace, audit_report)
        
        # 调用 LLM
        messages = [
            {"role": "system", "content": self._get_system_prompt()},
            {"role": "user", "content": prompt},
        ]
        
        response = await self._provider.chat(
            messages=messages,
            model=self._model,
            temperature=self._temperature,
            max_tokens=4096,
        )
        
        # 解析 LLM 响应为 FailureExperience
        failure_exp = self._parse_response(response, trace, audit_report, plan_id)
        return failure_exp

    def _get_system_prompt(self) -> str:
        """获取系统提示词。"""
        return """你是一个失败经验分析专家。你的职责是从失败的执行轨迹和审计报告中提取关键问题，总结为结构化的失败经验记录。

要求：
1. **分析失败阶段**：
   - planning: 计划阶段的问题（Plan 假设错误、能力选择错误等）
   - execution: 执行阶段的问题（工具调用失败、环境问题等）
   - audit: 审计阶段发现的问题（撒谎、越权等）

2. **识别失败类型**：
   - tool_missing: 缺少必要的工具/能力
   - env_opaque: 环境不透明，无法获取必要信息
   - plan_assumption_wrong: Plan 假设错误（如假设文件存在但实际不存在）
   - model_understanding_error: 模型理解错误（如误解任务要求）
   - unknown: 未知原因

3. **提取关键信息**：
   - 从审计报告中提取问题描述和证据
   - 从执行轨迹中提取问题发生前后的关键步骤
   - 分析根因假设
   - 总结给未来 Planner 的建议

4. **输出格式**：
   - 必须是有效的 JSON 格式，符合 FailureExperience Schema

输出格式：
{
  "failure_id": "fail_xxx",
  "task": "原始任务描述",
  "plan_id": "plan_xxx",
  "trace_id": "exec_xxx",
  "failure_stage": "planning | execution | audit",
  "failure_step_id": 3,
  "failure_type": "tool_missing | env_opaque | plan_assumption_wrong | model_understanding_error | unknown",
  "summary": "简短人类可读摘要",
  "root_cause_hypothesis": "可能的根因分析",
  "context_snippets": [
    "关键日志片段1",
    "关键日志片段2"
  ],
  "lessons_learned": "给未来 Planner 的建议"
}"""

    def _build_prompt(
        self,
        trace: ExecutionTrace,
        audit_report: AuditReport,
    ) -> str:
        """构建用户提示词。"""
        parts = []
        
        parts.append(f"执行轨迹 ID: {trace.trace_id}")
        parts.append(f"任务: {trace.task}")
        parts.append(f"状态: {trace.status}")
        parts.append(f"开始时间: {trace.started_at}")
        parts.append(f"结束时间: {trace.ended_at}")
        
        parts.append(f"\n审计结果:")
        parts.append(f"- 判定: {audit_report.verdict}")
        parts.append(f"- 风险级别: {audit_report.risk_level}")
        parts.append(f"- 模板候选资格: {audit_report.template_candidate_eligible}")
        
        if audit_report.issues:
            parts.append("\n审计问题:")
            for issue in audit_report.issues:
                parts.append(f"- 类型: {issue.type}")
                parts.append(f"  描述: {issue.description}")
                if issue.evidence:
                    if issue.evidence.step_id:
                        parts.append(f"  问题步骤: {issue.evidence.step_id}")
                    if issue.evidence.actual_result:
                        parts.append(f"  实际结果: {issue.evidence.actual_result}")
                    if issue.evidence.corrected_by_step:
                        parts.append(f"  被步骤 {issue.evidence.corrected_by_step} 修正")
        
        parts.append("\n执行步骤:")
        for step in trace.steps:
            step_outputs = step.outputs if isinstance(step.outputs, dict) else {}
            step_status = step_outputs.get("status", "unknown")
            is_error = (
                step_status == "fail" 
                or "error" in str(step_outputs).lower()
                or (isinstance(step_outputs, dict) and "error" in step_outputs)
            )
            
            status_marker = "[失败]" if is_error else "[成功]"
            parts.append(f"\n步骤 {step.step_id}: {status_marker}")
            parts.append(f"  能力: {step.capability} ({step.capability_level})")
            parts.append(f"  输入: {json.dumps(step.inputs, ensure_ascii=False, indent=2)}")
            parts.append(f"  输出: {json.dumps(step.outputs, ensure_ascii=False, indent=2)}")
            if step.llm_decision:
                parts.append(f"  LLM 决策: {step.llm_decision[:200]}...")
        
        parts.append("\n请从上述执行轨迹和审计报告中提取失败经验。")
        parts.append("重点关注：")
        parts.append("1. 失败发生在哪个阶段（planning/execution/audit）")
        parts.append("2. 失败的根本原因类型")
        parts.append("3. 关键的错误步骤和上下文")
        parts.append("4. 给未来 Planner 的建议（如何避免类似问题）")
        
        return "\n".join(parts)

    def _parse_response(
        self,
        response: LLMResponse,
        trace: ExecutionTrace,
        audit_report: AuditReport,
        plan_id: str | None,
    ) -> FailureExperience:
        """解析 LLM 响应为 FailureExperience。"""
        content = response.content.strip()
        
        # 尝试提取 JSON（可能包含 markdown 代码块）
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            content = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            content = content[start:end].strip()
        
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # 如果解析失败，创建一个基本的失败经验
            return self._create_default_failure_experience(trace, audit_report, plan_id)
        
        # 验证并转换数据
        failure_id = data.get("failure_id", f"fail_{uuid.uuid4().hex[:8]}")
        task = data.get("task", trace.task)
        failure_stage = data.get("failure_stage", "execution")
        if failure_stage not in ["planning", "execution", "audit"]:
            failure_stage = "execution"
        
        failure_type = data.get("failure_type", "unknown")
        if failure_type not in ["tool_missing", "env_opaque", "plan_assumption_wrong", "model_understanding_error", "unknown"]:
            failure_type = "unknown"
        
        # 从审计报告中提取失败步骤 ID
        failure_step_id = data.get("failure_step_id")
        if failure_step_id is None and audit_report.issues:
            for issue in audit_report.issues:
                if issue.evidence and issue.evidence.step_id:
                    failure_step_id = issue.evidence.step_id
                    break
        
        return FailureExperience(
            failure_id=failure_id,
            task=task,
            plan_id=plan_id or data.get("plan_id"),
            trace_id=trace.trace_id,
            failure_stage=failure_stage,
            failure_step_id=failure_step_id,
            failure_type=failure_type,
            summary=data.get("summary", "执行失败"),
            root_cause_hypothesis=data.get("root_cause_hypothesis", "需要进一步分析"),
            context_snippets=data.get("context_snippets", []),
            lessons_learned=data.get("lessons_learned", "需要改进执行策略"),
            created_at=datetime.utcnow(),
        )

    def _create_default_failure_experience(
        self,
        trace: ExecutionTrace,
        audit_report: AuditReport,
        plan_id: str | None,
    ) -> FailureExperience:
        """创建默认的失败经验（当 LLM 解析失败时）。"""
        # 从审计报告中提取关键信息
        failure_step_id = None
        if audit_report.issues:
            for issue in audit_report.issues:
                if issue.evidence and issue.evidence.step_id:
                    failure_step_id = issue.evidence.step_id
                    break
        
        # 根据审计判定确定失败阶段
        if audit_report.verdict == "fail":
            failure_stage: FailureStage = "execution"
        else:
            failure_stage = "audit"
        
        # 根据问题类型推断失败类型
        failure_type: FailureType = "unknown"
        if audit_report.issues:
            issue_types = [issue.type for issue in audit_report.issues]
            if "intermediate_error" in issue_types:
                failure_type = "plan_assumption_wrong"
            elif "unauthorized" in issue_types:
                failure_type = "tool_missing"
        
        summary = f"执行失败: {audit_report.verdict}, 风险级别: {audit_report.risk_level}"
        if audit_report.issues:
            summary += f", 问题数: {len(audit_report.issues)}"
        
        root_cause = "需要进一步分析失败原因"
        if audit_report.issues:
            root_cause = "; ".join([issue.description for issue in audit_report.issues[:3]])
        
        lessons_learned = "建议："
        if failure_type == "tool_missing":
            lessons_learned += "确保在执行前检查所需工具/能力是否可用"
        elif failure_type == "plan_assumption_wrong":
            lessons_learned += "在执行前验证 Plan 的假设条件（如文件是否存在）"
        else:
            lessons_learned += "仔细检查执行环境和上下文信息"
        
        return FailureExperience(
            failure_id=f"fail_{uuid.uuid4().hex[:8]}",
            task=trace.task,
            plan_id=plan_id,
            trace_id=trace.trace_id,
            failure_stage=failure_stage,
            failure_step_id=failure_step_id,
            failure_type=failure_type,
            summary=summary,
            root_cause_hypothesis=root_cause,
            context_snippets=[],
            lessons_learned=lessons_learned,
            created_at=datetime.utcnow(),
        )
