"""Mode A: Task Planning - 任务拆解 Plan 设计."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from openbot.infra.capability_registry import CapabilityRegistry
from openbot.providers.base import LLMProvider, LLMResponse
from openbot.schemas.plan_spec import (
    PlanSpec,
    PlanStep,
    SuccessCriteria,
)


class ModeATaskPlan:
    """模式 A: 任务拆解 Plan 设计。
    
    基于能力清单和历史案例，使用 LLM 拆解任务为执行计划。
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

    async def generate_plan(
        self,
        task: str,
        context: dict | None = None,
        session=None,  # Session 对象
        context_builder=None,  # ContextBuilder 对象
    ) -> PlanSpec:
        """生成任务执行计划。
        
        Args:
            task: 任务描述
            context: 可选上下文信息
            session: 可选的 Session 对象（用于获取 Session 上下文）
            context_builder: 可选的 ContextBuilder 对象（用于构建完整上下文）
        
        Returns:
            PlanSpec 对象
        """
        # 获取能力清单（轻量信息）
        capability_list = self._cap_reg.get_for_llm(include_details=False)
        
        # 构建完整的提示词（包含能力清单和上下文）
        prompt = self._build_prompt(task, capability_list, context)
        
        # 构建系统提示（Planner 需要自己的系统提示）
        system_prompt = self._get_system_prompt()
        
        # 如果有 context_builder 和 session，添加 Session 上下文和历史
        if context_builder and session:
            # 获取 Session 上下文（用于理解任务）
            session_context = context_builder.session_manager.get_context_for_task_understanding(session)
            session_context_str = context_builder._format_session_context(session_context)
            
            # 将 Session 上下文添加到系统提示中
            if session_context_str:
                system_prompt = f"{system_prompt}\n\n---\n\n## Session Context (for task understanding)\n{session_context_str}"
            
            # 构建消息列表
            messages = [{"role": "system", "content": system_prompt}]
            
            # 添加 Session 历史（用于理解任务意图）
            session_history = session.get_history(max_messages=context_builder.session_window)
            messages.extend(session_history)
            
            # 添加当前任务消息
            messages.append({"role": "user", "content": prompt})
        else:
            # 降级方案：只有 system prompt + user prompt
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
        
        response = await self._provider.chat(
            messages=messages,
            model=self._model,
            temperature=self._temperature,
            max_tokens=4096,
        )
        
        # 检查响应是否为空
        if not response.content or not response.content.strip():
            raise ValueError("LLM returned empty response")
        
        # 解析 LLM 响应为 PlanSpec
        plan = self._parse_response(response, task)
        return plan

    def _get_system_prompt(self) -> str:
        """获取系统提示词。

        约束 LLM 生成符合新版 PlanSpec 的 JSON。
        """
        return """你是一个任务规划专家。你的职责是将用户任务拆解为**多个子任务步骤（Plan）**。

要求：
1. 只能使用提供的能力清单中的能力，不能编造。
2. 每个步骤都必须有清晰的子任务目标 `subtask_goal`，说明这一小步要达到的状态。
3. **必须**为每个步骤推荐一个完成方式：`capability`（能力名称，从能力清单中选择）+ `capability_level` + `inputs`。
   不能将 `capability` 留空，必须从能力清单中选择最合适的能力。
4. 步骤之间可以有依赖关系（前置步骤的输出，为后续步骤服务）。
5. 优先使用 Workflow 层能力，如果合适的话，其次是 Skill，最后是 Atomic。
6. 输出必须是**有效 JSON**，不要包含任何多余文字或 Markdown 代码块。
7. **重要**：`success_criteria.field_checks` 必须是字典，其中每个值也必须是字典（JSON Schema 片段），不能是字符串。
   例如：`{"result": {"type": "string", "pattern": ".*success.*"}}` 是正确的，
   而 `{"result": "success"}` 是错误的。
8. **关键**：工具执行返回格式为 `{"result": "...", "status": "success"}`，所以 `field_checks` 必须检查 `result` 字段，而不是 `output` 字段。
   - 对于命令执行（execute_shell）：检查 `result` 字段，pattern 应该匹配命令输出（可能包含 STDOUT、STDERR 等）
   - 对于文件操作（read_file、write_file）：检查 `result` 字段，pattern 应该匹配操作结果文本
   - 示例：`{"result": {"type": "string", "pattern": ".*All tests passed.*"}}` 用于检查测试命令输出
9. **关键：实际输出格式匹配** - 当设计 `success_criteria.field_checks` 的 pattern 时，必须匹配**实际命令输出格式**，而不是理想化的格式：
   - **pytest 测试**：实际输出格式为 `5 passed in 0.04s`（小写 `passed`，不是大写 `PASSED`），pattern 应该使用 `".*\\d+ passed.*"` 或 `".*passed.*"`，而不是 `".*PASSED.*"`
   - **Python 脚本执行**：实际输出在 `STDOUT:` 和 `STDERR:` 标签后，pattern 应该匹配实际输出内容
   - **npm test / jest**：实际输出格式为 `Tests: X passed` 或 `PASS`，需要根据实际工具调整
   - **通用原则**：pattern 必须匹配实际输出文本，使用小写、实际关键词，不要使用理想化的大写或不存在的关键词
   - **示例（正确）**：`{"result": {"type": "string", "pattern": ".*\\d+ passed.*"}}` 用于匹配 pytest 输出
   - **示例（错误）**：`{"result": {"type": "string", "pattern": ".*PASSED.*"}}` 或 `{"result": {"type": "string", "pattern": ".*5 tests.*"}}` 不会匹配实际输出
10. 如果一时无法设计复杂的 success_criteria，可以先给出一个简单的结构（空数组/空字典），后续再迭代。

输出格式示例（请严格按照字段名输出）：
{
  "plan_id": "plan_xxx",
  "task": "任务描述",
  "execution_mode": "strict",
  "max_deviations": 0,
  "deviation_log_required": true,
  "steps": [
    {
      "step_id": 1,
      "subtask_goal": "明确描述这一小步要完成的目标（必填）",
      "capability": "推荐的能力名称（必填，必须从能力清单中选择，不能为空）",
      "capability_level": "workflow|skill|atomic",
      "inputs": {
        "param1": "value1"
      },
      "inputs_schema": {
        "type": "object",
        "properties": {
          "param1": { "type": "string" }
        }
      },
      "success_criteria": {
        "status": "success",
        "required_fields": ["field1", "field2"],
        "field_checks": {
          "result": {
            "type": "string",
            "pattern": ".*success.*"
          }
        }
      },
      "dependencies": [],
      "optional": false,
      "retry_policy": {
        "max_retries": 3,
        "backoff_strategy": "exponential",
        "initial_delay_ms": 1000,
        "max_delay_ms": 60000
      },
      "timeout_seconds": 60,
      "execution_mode": "strict",
      "deviation_allowed": false,
      "deviation_reason_required": true
    }
  ]
}"""

    def _build_prompt(
        self,
        task: str,
        capability_list: list[dict],
        context: dict | None,
    ) -> str:
        """构建用户提示词。"""
        parts = []
        
        parts.append(f"任务：{task}\n")
        
        if context:
            parts.append(f"上下文信息：\n{json.dumps(context, ensure_ascii=False, indent=2)}\n")
        
        parts.append("\n可用能力清单：")
        for cap in capability_list:
            parts.append(f"- {cap['name']} ({cap['level']}): {cap['description']}")
        
        parts.append("\n请为上述任务生成执行计划。")
        
        return "\n".join(parts)

    def _parse_response(self, response: LLMResponse, task: str) -> PlanSpec:
        """解析 LLM 响应为 PlanSpec（严格按新版格式）。"""
        content = (response.content or "").strip()
        
        # 如果内容为空，抛出更明确的错误
        if not content:
            raise ValueError("LLM response is empty")

        # 尝试提取 JSON（可能包含 markdown 代码块）
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end == -1:
                # 没有找到结束标记，尝试使用整个内容
                content = content[start:].strip()
            else:
                content = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end == -1:
                # 没有找到结束标记，尝试使用整个内容
                content = content[start:].strip()
            else:
                content = content[start:end].strip()

        # 如果提取后内容仍为空，记录原始内容用于调试
        if not content:
            raise ValueError(
                f"Failed to extract JSON from LLM response. "
                f"Original response (first 500 chars): {response.content[:500] if response.content else 'None'}"
            )

        try:
            data: dict[str, Any] = json.loads(content)
        except json.JSONDecodeError as e:
            # 提供更详细的错误信息，包括原始响应的前500个字符
            error_msg = (
                f"Failed to parse LLM response as JSON: {e}\n"
                f"Extracted content (first 500 chars): {content[:500]}\n"
                f"Full response length: {len(response.content) if response.content else 0} chars"
            )
            raise ValueError(error_msg) from e

        plan_id = data.get("plan_id", f"plan_{uuid.uuid4().hex[:8]}")
        execution_mode = data.get("execution_mode", "strict")
        max_deviations = data.get("max_deviations", 0)
        deviation_log_required = data.get("deviation_log_required", True)

        steps_data = data.get("steps", []) or []
        if not steps_data:
            raise ValueError("Plan must contain at least one step")

        steps: list[PlanStep] = []

        for raw in steps_data:
            # 严格要求 subtask_goal 必须存在
            subtask_goal = raw.get("subtask_goal")
            if not subtask_goal or not isinstance(subtask_goal, str):
                raise ValueError(f"Step {raw.get('step_id', '?')} missing required field: subtask_goal")

            # success_criteria 必须是对象
            sc_raw = raw.get("success_criteria", {})
            if isinstance(sc_raw, dict):
                # 规范化 field_checks：如果值是字符串，转换为字典格式
                if "field_checks" in sc_raw and isinstance(sc_raw["field_checks"], dict):
                    normalized_field_checks = {}
                    for key, value in sc_raw["field_checks"].items():
                        # 自动修正常见的字段名错误：output -> result
                        # 工具返回格式是 {"result": "...", "status": "success"}，不是 {"output": "..."}
                        normalized_key = "result" if key in ("output", "stdout", "output_text") else key
                        
                        if isinstance(value, str):
                            # 字符串值转换为简单的 pattern 检查
                            normalized_field_checks[normalized_key] = {
                                "type": "string",
                                "pattern": f".*{value}.*"
                            }
                        elif isinstance(value, dict):
                            # 已经是字典，直接使用
                            normalized_field_checks[normalized_key] = value
                        else:
                            # 其他类型，转换为字符串模式
                            normalized_field_checks[normalized_key] = {
                                "type": "string",
                                "pattern": f".*{str(value)}.*"
                            }
                    sc_raw["field_checks"] = normalized_field_checks
                
                success_criteria = SuccessCriteria(**sc_raw)
            else:
                raise ValueError(f"Step {raw.get('step_id', '?')} success_criteria must be an object")

            # retry_policy 可选，但必须是对象
            retry_policy = None
            if "retry_policy" in raw and raw["retry_policy"] is not None:
                from openbot.schemas.plan_spec import RetryPolicy
                retry_policy = RetryPolicy(**raw["retry_policy"])

            # 兼容两种字段名：capability 和 recommended_capability
            capability = raw.get("capability") or raw.get("recommended_capability", "")
            
            step = PlanStep(
                step_id=raw.get("step_id", len(steps) + 1),
                subtask_goal=subtask_goal,
                capability=capability,
                capability_level=raw.get("capability_level", "atomic"),
                inputs=raw.get("inputs", {}),
                inputs_schema=raw.get("inputs_schema"),
                success_criteria=success_criteria,
                dependencies=raw.get("dependencies", []),
                optional=raw.get("optional", False),
                retry_policy=retry_policy,
                timeout_seconds=raw.get("timeout_seconds"),
                execution_mode=raw.get("execution_mode", "strict"),
                deviation_allowed=raw.get("deviation_allowed", False),
                deviation_reason_required=raw.get("deviation_reason_required", True),
            )
            steps.append(step)

        return PlanSpec(
            plan_id=plan_id,
            task=task,
            created_at=datetime.utcnow(),
            steps=steps,
            execution_mode=execution_mode,
            max_deviations=max_deviations,
            deviation_log_required=deviation_log_required,
        )
