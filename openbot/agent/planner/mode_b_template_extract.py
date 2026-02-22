"""Mode B: Template Extraction - 从成功执行日志抽象 Workflow."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from openbot.infra.capability_registry import CapabilityRegistry
from openbot.providers.base import LLMProvider, LLMResponse
from openbot.schemas.audit_report import AuditReport
from openbot.schemas.execution_trace import ExecutionTraceModel as ExecutionTrace
from openbot.schemas.workflow_spec import CandidateWorkflowSpec, WorkflowStepSpec


class ModeBTemplateExtract:
    """模式 B: 从成功执行日志抽象 Workflow。
    
    读取 ExecutionTrace，过滤和抽象步骤，生成 CandidateWorkflowSpec。
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        capability_registry: CapabilityRegistry,
        model: str,
        temperature: float = 0.7,
    ) -> None:
        self._provider = provider
        self._cap_reg = capability_registry
        self._model = model
        self._temperature = temperature

    async def extract_workflow(
        self,
        trace: ExecutionTrace,
        audit_report: AuditReport | None = None,
    ) -> CandidateWorkflowSpec:
        """从执行轨迹提取 Workflow 模板。
        
        Args:
            trace: 执行轨迹
            audit_report: 可选的审计报告
        
        Returns:
            CandidateWorkflowSpec 对象
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
        
        # 解析 LLM 响应为 CandidateWorkflowSpec
        workflow = self._parse_response(response, trace)
        return workflow

    def _get_system_prompt(self) -> str:
        """获取系统提示词。"""
        return """你是一个工作流模板提取专家。你的职责是从成功的执行轨迹中提取可重用的工作流模板。

**重要：错误步骤过滤**
- 必须跳过所有失败的步骤（outputs.status="fail" 或包含 error）
- 必须跳过所有被后续步骤修正的错误步骤
- 只保留最终成功的、核心的业务逻辑步骤
- 如果审计报告指出了问题步骤，应该跳过这些步骤

要求：
1. **过滤错误步骤**：
   - 检查每个步骤的 outputs.status
   - 如果 status="fail" 或包含 error，跳过该步骤
   - 如果审计报告指出某个步骤有问题且被后续步骤修正，跳过该步骤
2. **保留核心步骤**：
   - 保留所有成功的业务逻辑步骤
   - 保留创建文件、执行命令等核心操作
3. **抽象步骤参数**：
   - 将具体参数抽象为 schema 定义
   - 识别哪些参数是固定的，哪些是可变的
4. **识别依赖关系**：
   - 识别步骤之间的依赖关系
   - 识别条件分支（如果有）
5. **输出格式**：
   - 必须是有效的 JSON 格式，符合 CandidateWorkflowSpec Schema

输出格式：
{
  "workflow_id": "candidate_xxx",
  "name": "工作流名称",
  "description": "描述（说明跳过了哪些错误步骤）",
  "steps": [
    {
      "step_id": 1,  // 重新编号，跳过错误步骤
      "capability": "能力名称",
      "capability_level": "workflow|skill|atomic",
      "inputs_schema": {
        "type": "object",
        "properties": {...}
      },
      "conditions": {...},
      "retry": {...}
    }
  ],
  "skipped_steps": [3, 5],  // 可选：跳过的步骤 ID 列表
  "extraction_notes": "提取说明"
}"""

    def _build_prompt(
        self,
        trace: ExecutionTrace,
        audit_report: AuditReport | None,
    ) -> str:
        """构建用户提示词。"""
        parts = []
        
        parts.append(f"执行轨迹 ID: {trace.trace_id}")
        parts.append(f"任务: {trace.task}")
        parts.append(f"状态: {trace.status}")
        parts.append(f"开始时间: {trace.started_at}")
        parts.append(f"结束时间: {trace.ended_at}")
        
        if audit_report:
            parts.append(f"\n审计结果: {audit_report.verdict}")
            if audit_report.issues:
                parts.append("审计问题:")
                for issue in audit_report.issues:
                    parts.append(f"- {issue.type}: {issue.description}")
                    if issue.evidence and issue.evidence.step_id:
                        parts.append(f"  问题步骤: {issue.evidence.step_id}")
        
        parts.append("\n执行步骤:")
        for step in trace.steps:
            # 标记错误步骤
            step_outputs = step.outputs if isinstance(step.outputs, dict) else {}
            step_status = step_outputs.get("status", "unknown")
            is_error = (
                step_status == "fail" 
                or "error" in str(step_outputs).lower()
                or (isinstance(step_outputs, dict) and "error" in step_outputs)
            )
            
            # 检查审计报告是否标记了此步骤
            is_audit_issue = False
            if audit_report:
                for issue in audit_report.issues:
                    if issue.evidence and issue.evidence.step_id == step.step_id:
                        is_audit_issue = True
                        break
            
            status_marker = "[错误 - 应跳过]" if (is_error or is_audit_issue) else "[成功]"
            parts.append(f"\n步骤 {step.step_id}: {status_marker}")
            parts.append(f"  能力: {step.capability} ({step.capability_level})")
            parts.append(f"  输入: {json.dumps(step.inputs, ensure_ascii=False, indent=2)}")
            parts.append(f"  输出: {json.dumps(step.outputs, ensure_ascii=False, indent=2)}")
            if step.llm_decision:
                parts.append(f"  LLM 决策: {step.llm_decision[:200]}...")
        
        parts.append("\n请从上述执行轨迹中提取可重用的工作流模板。")
        parts.append("**重要**：必须跳过所有标记为 [错误 - 应跳过] 的步骤，只保留成功的核心步骤。")
        
        return "\n".join(parts)

    def _parse_response(
        self,
        response: LLMResponse,
        trace: ExecutionTrace,
    ) -> CandidateWorkflowSpec:
        """解析 LLM 响应为 CandidateWorkflowSpec。"""
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
            # 如果解析失败，创建一个基本的工作流
            return CandidateWorkflowSpec(
                workflow_id=f"candidate_{uuid.uuid4().hex[:8]}",
                name="Extracted Workflow",
                description="Extracted from execution trace",
                source_trace_id=trace.trace_id,
                created_at=datetime.utcnow(),
                steps=[],
            )
        
        # 验证并转换数据
        workflow_id = data.get("workflow_id", f"candidate_{uuid.uuid4().hex[:8]}")
        name = data.get("name", "Extracted Workflow")
        description = data.get("description", "")
        steps_data = data.get("steps", [])
        skipped_steps = data.get("skipped_steps", [])
        extraction_notes = data.get("extraction_notes", "")
        
        # 如果有跳过的步骤，添加到描述中
        if skipped_steps:
            description += f"\n\n注意：已跳过以下错误步骤: {skipped_steps}"
        if extraction_notes:
            description += f"\n\n提取说明: {extraction_notes}"
        
        steps = []
        for step_data in steps_data:
            step = WorkflowStepSpec(
                step_id=step_data.get("step_id", len(steps) + 1),
                capability=step_data.get("capability", ""),
                capability_level=step_data.get("capability_level", "skill"),
                inputs_schema=step_data.get("inputs_schema", {}),
                conditions=step_data.get("conditions"),
                retry=step_data.get("retry"),
            )
            steps.append(step)
        
        return CandidateWorkflowSpec(
            workflow_id=workflow_id,
            name=name,
            description=description,
            source_trace_id=trace.trace_id,
            created_at=datetime.utcnow(),
            steps=steps,
        )
