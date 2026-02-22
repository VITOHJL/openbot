"""
Execution Agent main loop for openbot.

按照 SPEC.md 实现单执行 Agent 的核心逻辑：
- 任务规范化与初始化
- 瘦执行上下文管理 (ContextManager)
- React 模式执行循环
- 能力解析与调用 (CapabilityRegistry)
- ExecutionTrace 日志写入 (LogService)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable

from loguru import logger

from openbot.agent.context import ContextBuilder
from openbot.infra.capability_registry import CapabilityRegistry
from openbot.infra.context_manager import ContextManager
from openbot.infra.log_service import LogService
from openbot.providers.base import LLMProvider
from openbot.session.manager import Session, SessionManager


class ExecutionAgent:
    """单执行 Agent 实现。

    按照 SPEC.md 规范实现：
    - 唯一在线执行者
    - 在瘦上下文约束下进行 React 模式决策
    - 所有能力调用必须经过 CapabilityRegistry 验证
    - 所有行为必须记录到 LogService
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        context_manager: ContextManager,
        capability_registry: CapabilityRegistry,
        log_service: LogService,
        context_builder: ContextBuilder,
        session_manager: SessionManager,
        tool_registry: Any | None = None,  # ToolRegistry 实例
        max_iterations: int = 20,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> None:
        self._provider = provider
        self._ctx_mgr = context_manager
        self._cap_reg = capability_registry
        self._log_svc = log_service
        self._ctx_builder = context_builder
        self._session_mgr = session_manager
        self._tool_registry = tool_registry
        self._max_iterations = max_iterations
        self._model = model or provider.get_default_model()
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def process_task(
        self,
        task: str,
        *,
        session: Session | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """处理单次任务的高层入口。

        按照 SPEC.md 阶段 1-3 实现：
        1. 任务接收与初始化
        2. 执行循环（React 模式）
        3. 任务结束处理
        """
        # 阶段 1: 任务接收与初始化
        trace_id = f"exec_{uuid.uuid4().hex[:8]}"
        logger.info(f"Processing task: {task[:80]}...")
        
        # 任务规范化解析
        normalized_task = self._normalize_task(task)
        
        # 初始化瘦上下文
        self._ctx_mgr.init_context(normalized_task)
        execution_context = self._ctx_mgr.get_context()
        
        # 启动 ExecutionTrace
        self._log_svc.start_trace(trace_id, task)
        
        # 获取或创建 Session
        if not session:
            session = self._session_mgr.get_or_create("cli:direct")
        
        # 获取能力清单（渐进式加载：先只返回轻量信息）
        capability_list = self._cap_reg.get_for_llm(include_details=False)
        
        try:
            # 阶段 2: 执行循环（React 模式）
            final_result = await self._run_execution_loop(
                task=task,
                session=session,
                execution_context=execution_context,
                capability_list=capability_list,
                trace_id=trace_id,
                on_progress=on_progress,
            )
            
            # 阶段 3: 任务结束处理
            status = "success" if final_result else "fail"
            self._log_svc.finish_trace(trace_id, status, final_result or "")
            
            # 自动触发审计（仅当有工具调用时）
            # 如果没有工具调用，则不存在主要风险（撒谎/越权），无需审计以节省 token
            trace = self._log_svc.get_trace(trace_id)
            if trace and trace.steps:
                try:
                    from openbot.agent.auditor import AuditorAgent
                    from openbot.infra.template_registry import TemplateRegistry
                    
                    # 共享 LogService 的 Database 实例，减少连接竞争
                    database = self._log_svc._db
                    template_registry = TemplateRegistry(database=database)
                    
                    auditor = AuditorAgent(
                        provider=self._provider,
                        capability_registry=self._cap_reg,
                        log_service=self._log_svc,
                        template_registry=template_registry,
                        database=database,
                        model=self._model,
                        temperature=0.3,
                    )
                    
                    audit_report = await auditor.audit_trace(trace_id)
                    
                    # 记录审计结果到日志
                    logger.info(
                        f"Audit completed for {trace_id}: verdict={audit_report.verdict}, "
                        f"risk_level={audit_report.risk_level}, "
                        f"issues={len(audit_report.issues)}, "
                        f"template_candidate_eligible={audit_report.template_candidate_eligible}"
                    )
                    
                    # 如果审计通过且可升级，自动提取并注册工作流
                    if (audit_report.verdict == "pass" and 
                        audit_report.template_candidate_eligible):
                        try:
                            from openbot.agent.planner import OrchestrationAgent
                            from openbot.infra.test_case_store import TestCaseStore

                            # 复用同一 Database 实例
                            test_case_store = TestCaseStore(database=database)

                            planner = OrchestrationAgent(
                                provider=self._provider,
                                capability_registry=self._cap_reg,
                                log_service=self._log_svc,
                                template_registry=template_registry,
                                test_case_store=test_case_store,
                                model=self._model,
                                temperature=0.5,
                            )
                            workflow = await planner.extract_workflow(trace_id, audit_report)
                            # 使用 trace_id 确保唯一性，避免覆盖
                            workflow = workflow.model_copy(
                                update={"workflow_id": f"wf_{trace_id}"}
                            )
                            template_registry.register(workflow)
                            logger.info(
                                f"Workflow extracted and registered: {workflow.name} "
                                f"(id={workflow.workflow_id}, steps={len(workflow.steps)})"
                            )
                        except Exception as we:
                            logger.warning(
                                f"Workflow extraction failed for {trace_id}: {we}",
                                exc_info=True,
                            )
                except Exception as e:
                    logger.warning(f"Audit failed for {trace_id}: {e}", exc_info=True)
            else:
                logger.debug(f"Skipping audit for {trace_id}: no tool calls (no risk)")
            
            # 保存 Session
            session.add_message("user", task)
            session.add_message("assistant", final_result or "Task failed")
            self._session_mgr.save(session)
            
            return final_result or "Task completed but no result was generated."
            
        except Exception as e:
            logger.error(f"Error processing task: {e}", exc_info=True)
            self._log_svc.finish_trace(trace_id, "fail", f"Error: {str(e)}")
            return f"Error processing task: {str(e)}"

    def _normalize_task(self, task: str) -> dict[str, Any]:
        """任务规范化解析（确定性代码）。
        
        提取：目标、约束条件、输出格式、上下文键
        """
        # 简化实现：后续可以增强
        return {
            "goal": task,
            "constraints": [],
            "output_format": "text",
            "context_keys": [],
        }
    
    def _get_content_preview(self, content: str, max_lines: int = 10) -> dict[str, Any]:
        """获取内容预览（前 N 行 + 后 N 行）。
        
        用于节省 token，同时保留足够的上下文用于审计和调试。
        """
        if not isinstance(content, str):
            return {"raw": content}
        
        lines = content.split("\n")
        total_lines = len(lines)
        
        if total_lines <= max_lines * 2:
            # 内容不多，直接返回
            return {
                "full_content": content,
                "total_lines": total_lines,
                "total_chars": len(content),
            }
        
        # 保存前 N 行和后 N 行
        first_lines = "\n".join(lines[:max_lines])
        last_lines = "\n".join(lines[-max_lines:])
        omitted_lines = total_lines - max_lines * 2
        
        return {
            "first_lines": first_lines,
            "last_lines": last_lines,
            "omitted_lines": omitted_lines,
            "total_lines": total_lines,
            "total_chars": len(content),
            "preview_note": f"Content truncated: showing first {max_lines} and last {max_lines} lines (omitted {omitted_lines} lines in between)",
        }
    
    def _summarize_inputs(self, capability_name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """精简输入，对大内容只保存预览。
        
        用于节省 token，同时保留足够的上下文用于审计和调试。
        """
        if capability_name == "write_file":
            content = inputs.get("content", "")
            if isinstance(content, str) and len(content) > 500:
                return {
                    "file_path": inputs.get("file_path"),
                    "content_preview": self._get_content_preview(content),
                }
            # 内容小，直接返回
            return inputs
        
        elif capability_name == "read_file":
            # read_file 的输入通常不大
            return {
                "file_path": inputs.get("file_path"),
                "offset": inputs.get("offset"),
                "limit": inputs.get("limit"),
            }
        
        # 其他工具保持原样
        return inputs
    
    def _summarize_outputs(self, capability_name: str, outputs: dict[str, Any]) -> dict[str, Any]:
        """精简输出，对大内容只保存预览。
        
        用于节省 token，同时保留足够的上下文用于审计和调试。
        """
        result = outputs.get("result", "")
        
        if capability_name == "write_file":
            # write_file 的输出通常是状态信息，不大
            return {
                "status": outputs.get("status"),
                "result": outputs.get("result"),  # 通常是 "Successfully wrote X characters"
            }
        
        elif capability_name == "read_file":
            if isinstance(result, str) and len(result) > 500:
                return {
                    "status": outputs.get("status"),
                    "content_preview": self._get_content_preview(result),
                }
            # 内容小，直接返回
            return outputs
        
        # 其他工具保持原样
        return outputs

    async def _run_execution_loop(
        self,
        task: str,
        session: Session,
        execution_context: dict[str, Any],
        capability_list: list[dict[str, Any]],
        trace_id: str,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str | None:
        """执行循环（React 模式）。
        
        按照 SPEC.md 阶段 2 实现：
        - LLM 规划下一步
        - 能力解析与验证
        - 参数构造
        - 执行能力调用
        - 更新上下文与日志
        - 结果校验
        - 下一步决策
        """
        import json
        
        iteration = 0
        final_result: str | None = None
        
        # 初始化消息列表（包含初始用户消息）
        messages = self._ctx_builder.build_messages(
            session=session,
            execution_context=execution_context,
            current_message=task,
            capability_list=capability_list,
        )
        
        while iteration < self._max_iterations:
            iteration += 1
            logger.debug(f"Execution loop iteration {iteration}/{self._max_iterations}")
            
            # 更新 system prompt（因为 execution_context 可能已更新）
            system_prompt = self._ctx_builder.build_system_prompt(
                session, execution_context, capability_list
            )
            messages[0] = {"role": "system", "content": system_prompt}
            
            # 调用 LLM（使用累积的消息）
            response = await self._provider.chat(
                messages=messages,
                tools=self._cap_reg.get_for_llm(include_details=True),  # 需要完整定义用于工具调用
                model=self._model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            
            # 记录 LLM 决策
            if on_progress and response.content:
                await on_progress(response.content)
            
            # 如果有工具调用
            if response.has_tool_calls:
                # 将 assistant 消息（含 tool_calls）加入对话
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": response.content or "",
                }
                if response.tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False)
                                if isinstance(tc.arguments, dict)
                                else str(tc.arguments),
                            },
                        }
                        for tc in response.tool_calls
                    ]
                messages.append(assistant_msg)
                
                # 执行工具并添加 tool 结果消息
                for tool_call in response.tool_calls:
                    # 能力解析与验证
                    capability = self._cap_reg.get(tool_call.name)
                    if not capability:
                        error_msg = f"Capability '{tool_call.name}' not found"
                        logger.warning(error_msg)
                        self._log_svc.log_step(trace_id, {
                            "step_id": iteration,
                            "capability": tool_call.name,
                            "capability_level": "unknown",
                            "inputs": tool_call.arguments,
                            "outputs": {"error": error_msg},
                            "llm_decision": f"Attempted to call {tool_call.name}",
                        })
                        # 添加错误结果到消息
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps({"error": error_msg}, ensure_ascii=False),
                        })
                        continue
                    
                    # 执行能力调用
                    result = await self._execute_capability(
                        capability=capability,
                        arguments=tool_call.arguments,
                        trace_id=trace_id,
                        step_id=iteration,
                    )
                    
                    # 添加 tool 结果到消息
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                    
                    # 精简输入输出（节省 token）
                    summarized_inputs = self._summarize_inputs(tool_call.name, tool_call.arguments)
                    summarized_outputs = self._summarize_outputs(tool_call.name, result)
                    
                    # 更新瘦上下文
                    self._ctx_mgr.update_step_history({
                        "step_id": iteration,
                        "action": tool_call.name,
                        "result_summary": str(result.get("result", result))[:100],
                    })
                    self._ctx_mgr.update_tool_io({
                        "capability": tool_call.name,
                        "inputs_summary": summarized_inputs,
                        "outputs_summary": summarized_outputs,
                    })
                    execution_context = self._ctx_mgr.get_context()
                    
                    # 记录到日志（使用精简后的输入输出）
                    self._log_svc.log_step(trace_id, {
                        "step_id": iteration,
                        "capability": tool_call.name,
                        "capability_level": capability.level,
                        "inputs": summarized_inputs,
                        "outputs": summarized_outputs,
                        "llm_decision": response.content or f"Called {tool_call.name}",
                        "duration_ms": result.get("duration_ms"),
                        # 移除 context_snapshot 以节省 token，只保留关键信息
                        "context_summary": {
                            "task": execution_context.get("task"),
                            "step_count": execution_context.get("step_count", 0),
                        },
                    })
            else:
                # 没有工具调用，任务完成
                final_result = response.content
                break
        
        return final_result

    async def _execute_capability(
        self,
        capability: Any,
        arguments: dict[str, Any],
        trace_id: str,
        step_id: int,
    ) -> dict[str, Any]:
        """执行能力调用。
        
        按照能力层级执行：
        - Atomic: 直接执行工具
        - Skill: 组合执行
        - Workflow: 按模板执行
        """
        import time
        start_time = time.time()
        
        try:
            # 参数校验
            errors = self._validate_arguments(capability, arguments)
            if errors:
                return {"error": f"Invalid arguments: {', '.join(errors)}", "status": "fail"}
            
            # 根据能力层级执行
            if capability.level == "atomic":
                result = await self._execute_atomic(capability, arguments)
            elif capability.level == "skill":
                result = await self._execute_skill(capability, arguments)
            elif capability.level == "workflow":
                result = await self._execute_workflow(capability, arguments)
            else:
                result = {"error": f"Unknown capability level: {capability.level}", "status": "fail"}
            
            duration_ms = int((time.time() - start_time) * 1000)
            result["duration_ms"] = duration_ms
            result["status"] = result.get("status", "success")
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing capability {capability.name}: {e}", exc_info=True)
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "error": str(e),
                "status": "fail",
                "duration_ms": duration_ms
            }
    
    def _validate_arguments(self, capability: Any, arguments: dict[str, Any]) -> list[str]:
        """验证参数是否符合 schema。"""
        errors = []
        schema = capability.schema
        
        if schema.get("type") != "object":
            return errors
        
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        
        # 检查必填字段
        for field in required:
            if field not in arguments:
                errors.append(f"missing required parameter: {field}")
        
        # 检查字段类型（简化实现）
        for key, value in arguments.items():
            if key in properties:
                prop_schema = properties[key]
                expected_type = prop_schema.get("type")
                if expected_type:
                    type_map = {
                        "string": str,
                        "integer": int,
                        "number": (int, float),
                        "boolean": bool,
                        "array": list,
                        "object": dict,
                    }
                    if expected_type in type_map:
                        if not isinstance(value, type_map[expected_type]):
                            errors.append(f"{key} should be {expected_type}, got {type(value).__name__}")
        
        return errors
    
    async def _execute_atomic(self, capability: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """执行 Atomic 能力。
        
        从工具注册表中查找并执行工具。
        """
        tool_name = capability.name
        
        try:
            # 优先使用传入的 tool_registry
            if self._tool_registry:
                tool = self._tool_registry.get_tool(tool_name)
                if tool:
                    result = await tool.execute(**arguments)
                    return {"result": result, "status": "success"}
            
            # 如果没有 tool_registry，尝试自动发现
            from openbot.agent.tools.registry import ToolRegistry
            temp_registry = ToolRegistry(self._cap_reg)
            temp_registry.auto_discover()
            
            tool = temp_registry.get_tool(tool_name)
            if tool:
                result = await tool.execute(**arguments)
                return {"result": result, "status": "success"}
            
            return {"error": f"Tool '{tool_name}' not found in registry", "status": "fail"}
            
        except Exception as e:
            return {"error": f"Error executing tool '{tool_name}': {str(e)}", "status": "fail"}
    
    async def _execute_skill(self, capability: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """执行 Skill 能力（组合多个 Atomic 工具）。"""
        if not self._tool_registry:
            return {"error": "Tool registry not available", "status": "fail"}
        
        try:
            from openbot.infra.skill_executor import SkillExecutor
            executor = SkillExecutor(self._tool_registry)
            return await executor.execute(capability, arguments)
        except Exception as e:
            return {"error": f"Error executing skill '{capability.name}': {str(e)}", "status": "fail"}
    
    async def _execute_workflow(self, capability: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """执行 Workflow 能力（按模板执行）。"""
        try:
            from openbot.infra.template_registry import TemplateRegistry
            from openbot.infra.workflow_executor import WorkflowExecutor
            
            # 创建 TemplateRegistry（目前是内存实现）
            template_registry = TemplateRegistry()
            executor = WorkflowExecutor(template_registry, self)
            return await executor.execute(capability, arguments)
        except Exception as e:
            return {"error": f"Error executing workflow '{capability.name}': {str(e)}", "status": "fail"}

