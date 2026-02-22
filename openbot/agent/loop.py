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
        1. 任务接收与初始化（包括生成 PlanSpec）
        2. 按 PlanSpec 执行子任务（每个子任务内部使用 React 模式） 
        3. 任务结束处理
        """
        # 阶段 1: 任务接收与初始化
        
        # 步骤 1.0: 命令处理（在任务规范化之前）
        command_result = self._handle_commands(task, session)
        if command_result is not None:
            # 命令已处理，直接返回结果
            return command_result
        
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
        
        try:
            # 步骤 1.1: 调用 Planner 生成 PlanSpec
            from openbot.agent.planner import OrchestrationAgent
            from openbot.infra.template_registry import TemplateRegistry
            from openbot.infra.test_case_store import TestCaseStore
            
            database = self._log_svc._db
            template_registry = TemplateRegistry(database=database)
            test_case_store = TestCaseStore(database=database)
            
            planner = OrchestrationAgent(
                provider=self._provider,
                capability_registry=self._cap_reg,
                log_service=self._log_svc,
                template_registry=template_registry,
                test_case_store=test_case_store,
                model=self._model,
                temperature=0.7,
            )
            
            # Planner 需要 Session 上下文和历史来理解任务意图
            plan = await planner.plan_task(
                task, 
                context=execution_context,
                session=session,
                context_builder=self._ctx_builder,
            )
            logger.info(f"Plan generated: {plan.plan_id} with {len(plan.steps)} steps")
            
            # 保存 Plan 到数据库
            database.save_plan(plan)
            
            # 阶段 2: 按 PlanSpec 执行子任务
            final_result = await self._execute_plan(
                plan=plan,
                session=session,
                execution_context=execution_context,
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
                    
                    # 如果审计失败/高风险/有中间错误，触发 Mode D 构建失败经验
                    should_build_failure = (
                        audit_report.verdict == "fail" or
                        audit_report.risk_level == "high" or
                        any(issue.type == "intermediate_error" for issue in audit_report.issues)
                    )
                     
                    if should_build_failure:
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
                            
                            # 获取 plan_id（如果有）
                            plan_id = None
                            trace = self._log_svc.get_trace(trace_id)
                            if trace and hasattr(trace, 'plan_id'):
                                plan_id = trace.plan_id
                            
                            failure_exp = await planner.build_failure_experience(
                                trace_id, audit_report, plan_id
                            )
                            
                            # 保存失败经验到数据库
                            database.save_failure_experience(failure_exp)
                            
                            logger.info(
                                f"Failure experience built and saved: {failure_exp.failure_id} "
                                f"(type={failure_exp.failure_type}, stage={failure_exp.failure_stage})"
                            )
                        except Exception as fe:
                            logger.warning(
                                f"Failure experience building failed for {trace_id}: {fe}",
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

    def _handle_commands(
        self,
        task: str,
        session: Session | None,
    ) -> str | None:
        """处理命令（在任务规范化之前）。
        
        按照 SPEC.md 2.1.4：支持 /new, /help, /audit, /template, /memory 等命令。
        
        Returns:
            如果任务是命令，返回命令处理结果字符串；否则返回 None。
        """
        task_stripped = task.strip()
        
        # /new - 开始新会话
        if task_stripped.lower() == "/new":
            if session:
                # 清空当前会话消息
                session.messages.clear()
                self._session_mgr.save(session)
                logger.info("Session cleared via /new command")
            return "✅ 新会话已开始。之前的对话历史已清空。"
        
        # /help - 显示帮助信息
        if task_stripped.lower() == "/help":
            help_text = """📖 OpenBot 帮助信息

可用命令：
  /new              - 开始新会话（清空当前对话历史）
  /help             - 显示此帮助信息
  /audit <trace_id> - 触发指定执行轨迹的审计
  /template <id>    - 查看指定 Workflow 模板信息
  /memory           - 查看长期记忆

使用说明：
  - 直接输入任务描述，系统会自动规划并执行
  - 系统会按 Plan 逐步执行子任务
  - 所有执行过程都会被记录和审计

示例：
  查询项目并重构为 JavaScript
  创建一个新的 Python 项目
"""
            return help_text
        
        # /audit <trace_id> - 触发审计
        if task_stripped.lower().startswith("/audit "):
            trace_id = task_stripped[7:].strip()
            if not trace_id:
                return "❌ 错误：请提供 trace_id。用法：/audit <trace_id>"
            
            # 异步触发审计（不阻塞）
            import asyncio
            asyncio.create_task(self._handle_audit_command(trace_id))
            return f"🔄 正在触发审计：{trace_id}（后台执行中）"
        
        # /template <workflow_id> - 查看模板信息
        if task_stripped.lower().startswith("/template "):
            workflow_id = task_stripped[10:].strip()
            if not workflow_id:
                return "❌ 错误：请提供 workflow_id。用法：/template <workflow_id>"
            
            return self._handle_template_command(workflow_id)
        
        # /memory - 查看长期记忆
        if task_stripped.lower() == "/memory":
            return self._handle_memory_command(session)
        
        # 不是命令，返回 None 继续正常处理流程
        return None
    
    async def _handle_audit_command(self, trace_id: str) -> None:
        """处理 /audit 命令（异步执行）。"""
        try:
            from openbot.agent.auditor import AuditorAgent
            from openbot.infra.template_registry import TemplateRegistry
            
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
            logger.info(
                f"Audit completed for {trace_id}: verdict={audit_report.verdict}, "
                f"risk_level={audit_report.risk_level}"
            )
        except Exception as e:
            logger.error(f"Error executing audit command for {trace_id}: {e}", exc_info=True)
    
    def _handle_template_command(self, workflow_id: str) -> str:
        """处理 /template 命令。"""
        try:
            from openbot.infra.template_registry import TemplateRegistry
            
            database = self._log_svc._db
            template_registry = TemplateRegistry(database=database)
            
            workflow = template_registry.get(workflow_id)
            if not workflow:
                return f"❌ 未找到 Workflow 模板：{workflow_id}"
            
            # 格式化输出
            steps_info = "\n".join(
                f"  {i+1}. {step.capability} ({step.capability_level})"
                for i, step in enumerate(workflow.steps)
            )
            
            return f"""📋 Workflow 模板信息

ID: {workflow.workflow_id}
名称: {workflow.name}
描述: {workflow.description or '（无描述）'}
创建时间: {workflow.created_at}
来源轨迹: {workflow.source_trace_id or '（无）'}

步骤列表（共 {len(workflow.steps)} 步）：
{steps_info}
"""
        except Exception as e:
            logger.error(f"Error executing template command for {workflow_id}: {e}", exc_info=True)
            return f"❌ 错误：无法获取模板信息：{str(e)}"
    
    def _handle_memory_command(self, session: Session | None) -> str:
        """处理 /memory 命令。"""
        # TODO: 实现长期记忆查看功能
        # 目前返回占位信息
        if session:
            message_count = len(session.messages)
            return f"""🧠 长期记忆信息

当前会话消息数: {message_count}
最后更新时间: {session.updated_at}

注意：完整的长期记忆功能正在开发中。
"""
        else:
            return "🧠 长期记忆信息\n\n当前没有活动会话。"
    
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

    async def _execute_plan(
        self,
        plan: Any,  # PlanSpec
        session: Session,
        execution_context: dict[str, Any],
        trace_id: str,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str | None:
        """按 PlanSpec 执行所有子任务。

        按照 SPEC.md：逐个执行 PlanSpec.steps，每个子任务内部使用 React 模式。
        """
        from openbot.schemas.plan_spec import PlanSpec, PlanStep
        
        if not isinstance(plan, PlanSpec):
            raise TypeError(f"Expected PlanSpec, got {type(plan)}")
        
        completed_steps: dict[int, dict[str, Any]] = {}  # step_id -> 执行结果
        final_result: str | None = None
        
        # 按依赖顺序执行步骤（简单实现：先执行无依赖的，再执行有依赖的）
        remaining_steps = {step.step_id: step for step in plan.steps}
        
        while remaining_steps:
            # 找到所有可以执行的步骤（依赖已满足或没有依赖）
            ready_steps = [
                step for step in remaining_steps.values()
                if all(dep_id in completed_steps for dep_id in step.dependencies)
            ]
            
            if not ready_steps:
                # 循环依赖或错误，记录并退出
                logger.error(f"Circular dependency or missing dependencies in plan {plan.plan_id}")
                break
            
            # 执行所有就绪的步骤（支持并行执行无依赖的步骤）
            if len(ready_steps) == 1:
                # 单个步骤，直接执行
                step = ready_steps[0]
                step_result = await self._execute_subtask(
                    step=step,
                    plan=plan,
                    session=session,
                    execution_context=execution_context,
                    completed_steps=completed_steps,
                    trace_id=trace_id,
                    on_progress=on_progress,
                )
                completed_steps[step.step_id] = step_result
                remaining_steps.pop(step.step_id)
                
                # 如果步骤失败且不是可选的，可以提前终止
                if step_result.get("status") == "fail" and not step.optional:
                    logger.warning(f"Step {step.step_id} failed and is not optional, stopping plan execution")
                    return step_result.get("result", "Plan execution stopped due to step failure")
            else:
                # 多个步骤，并行执行
                import asyncio
                
                async def execute_step_with_metrics(step: PlanStep) -> tuple[int, dict[str, Any]]:
                    """执行单个步骤并返回 (step_id, result)"""
                    import time
                    start_time = time.time()
                    
                    result = await self._execute_subtask(
                        step=step,
                        plan=plan,
                        session=session,
                        execution_context=execution_context,
                        completed_steps=completed_steps,
                        trace_id=trace_id,
                        on_progress=on_progress,
                    )
                    
                    duration = time.time() - start_time
                    result["execution_duration_seconds"] = duration
                    result["step_id"] = step.step_id
                    
                    return (step.step_id, result)
                
                # 并行执行所有就绪的步骤
                tasks = [execute_step_with_metrics(step) for step in ready_steps]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # 处理结果
                for result in results:
                    if isinstance(result, Exception):
                        logger.error(f"Error executing step in parallel: {result}", exc_info=True)
                        continue
                    
                    step_id, step_result = result
                    completed_steps[step_id] = step_result
                    remaining_steps.pop(step_id)
                    
                    # 检查是否有失败的非可选步骤
                    step = next(s for s in ready_steps if s.step_id == step_id)
                    if step_result.get("status") == "fail" and not step.optional:
                        logger.warning(f"Step {step_id} failed and is not optional, stopping plan execution")
                        return step_result.get("result", "Plan execution stopped due to step failure")
        
        # 汇总最终结果和执行指标
        if completed_steps:
            # 计算总体执行指标
            total_duration = sum(
                step_result.get("execution_duration_seconds", 0)
                for step_result in completed_steps.values()
            )
            total_retries = sum(
                step_result.get("retry_count", 0)
                for step_result in completed_steps.values()
            )
            failed_steps = [
                step_id for step_id, result in completed_steps.items()
                if result.get("status") == "fail"
            ]
            
            logger.info(
                f"Plan {plan.plan_id} execution completed: "
                f"total_duration={total_duration:.2f}s, "
                f"total_retries={total_retries}, "
                f"failed_steps={len(failed_steps)}/{len(completed_steps)}"
            )
            
            # 取最后一个步骤的结果作为最终结果
            last_step_id = max(completed_steps.keys())
            final_result = completed_steps[last_step_id].get("result")
            
            # 如果有失败的步骤，在结果中记录
            if failed_steps:
                final_result = (
                    f"{final_result or 'Plan execution completed'}\n\n"
                    f"⚠️ Note: {len(failed_steps)} step(s) failed: {failed_steps}"
                )
        
        return final_result or "Plan execution completed"
    
    async def _execute_subtask(
        self,
        step: Any,  # PlanStep
        plan: Any,  # PlanSpec
        session: Session,
        execution_context: dict[str, Any],
        completed_steps: dict[int, dict[str, Any]],
        trace_id: str,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """执行单个子任务（内部使用 React 模式，支持重试和超时）。

        按照 SPEC.md 阶段 2：在子任务范围内运行 React 循环。
        
        Returns:
            包含执行结果的字典，包含以下字段：
            - status: "success" | "fail"
            - result: 结果文本
            - execution_duration_seconds: 执行耗时（秒）
            - retry_count: 重试次数
            - error: 错误信息（如果失败）
        """
        from openbot.schemas.plan_spec import PlanStep
        import asyncio
        import time
        
        if not isinstance(step, PlanStep):
            raise TypeError(f"Expected PlanStep, got {type(step)}")
        
        logger.info(f"Executing subtask {step.step_id}: {step.subtask_goal}")
        
        # 获取能力清单（渐进式加载）
        capability_list = self._cap_reg.get_for_llm(include_details=False)
        
        # 实现重试逻辑
        retry_policy = step.retry_policy
        max_attempts = (retry_policy.max_retries + 1) if retry_policy else 1
        attempt = 0
        last_error: Exception | None = None
        start_time = time.time()
        
        while attempt < max_attempts:
            attempt += 1
            if attempt > 1:
                delay_ms = self._calculate_backoff_delay(
                    attempt - 1, retry_policy
                )
                logger.info(
                    f"Retrying step {step.step_id}, attempt {attempt}/{max_attempts}, "
                    f"delay {delay_ms}ms"
                )
                await asyncio.sleep(delay_ms / 1000.0)
            
            try:
                # 实现超时控制
                timeout_seconds = step.timeout_seconds
                if timeout_seconds:
                    result = await asyncio.wait_for(
                        self._run_subtask_react_loop(
                            step=step,
                            session=session,
                            execution_context=execution_context,
                            capability_list=capability_list,
                            completed_steps=completed_steps,
                            trace_id=trace_id,
                            on_progress=on_progress,
                        ),
                        timeout=timeout_seconds,
                    )
                else:
                    result = await self._run_subtask_react_loop(
                        step=step,
                        session=session,
                        execution_context=execution_context,
                        capability_list=capability_list,
                        completed_steps=completed_steps,
                        trace_id=trace_id,
                        on_progress=on_progress,
                    )
                
                # 添加执行指标
                execution_duration = time.time() - start_time
                result["execution_duration_seconds"] = execution_duration
                result["retry_count"] = attempt - 1
                result["step_id"] = step.step_id
                
                # 如果成功，返回结果
                if result.get("status") == "success":
                    logger.info(
                        f"Step {step.step_id} completed successfully in {execution_duration:.2f}s "
                        f"(retries: {result['retry_count']})"
                    )
                    return result
                
                # 如果失败但还有重试机会，继续循环
                last_error = Exception(result.get("result", "Subtask failed"))
                
            except asyncio.TimeoutError:
                timeout_seconds = step.timeout_seconds or 0
                last_error = TimeoutError(
                    f"Step {step.step_id} timed out after {timeout_seconds} seconds"
                )
                logger.warning(f"Step {step.step_id} timeout: {last_error}")
                if attempt >= max_attempts:
                    execution_duration = time.time() - start_time
                    return {
                        "status": "fail",
                        "result": f"Subtask timed out after {timeout_seconds}s",
                        "error": str(last_error),
                        "execution_duration_seconds": execution_duration,
                        "retry_count": attempt - 1,
                        "step_id": step.step_id,
                    }
            except Exception as e:
                last_error = e
                logger.error(f"Step {step.step_id} error on attempt {attempt}: {e}", exc_info=True)
                if attempt >= max_attempts:
                    execution_duration = time.time() - start_time
                    return {
                        "status": "fail",
                        "result": f"Subtask failed after {max_attempts} attempts",
                        "error": str(last_error),
                        "execution_duration_seconds": execution_duration,
                        "retry_count": attempt - 1,
                        "step_id": step.step_id,
                    }
        
        # 所有重试都失败
        execution_duration = time.time() - start_time
        return {
            "status": "fail",
            "result": f"Subtask failed after {max_attempts} attempts",
            "error": str(last_error) if last_error else "Unknown error",
            "execution_duration_seconds": execution_duration,
            "retry_count": max_attempts - 1,
            "step_id": step.step_id,
        }
    
    async def _run_subtask_react_loop(
        self,
        step: Any,  # PlanStep
        session: Session,
        execution_context: dict[str, Any],
        capability_list: list[dict[str, Any]],
        completed_steps: dict[int, dict[str, Any]],
        trace_id: str,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """子任务内部 React 循环。

        按照 SPEC.md 阶段 2：针对单个子任务，运行局部 React 循环。
        """
        import json
        
        iteration = 0
        max_iterations = 10  # 子任务级最大迭代次数
        final_result: str | None = None
        
        # 构建子任务上下文（包含 subtask_goal 和推荐完成方式）
        subtask_context = {
            **execution_context,
            "subtask_goal": step.subtask_goal,
            "recommended_capability": step.capability,
            "capability_level": step.capability_level,
            "recommended_inputs": step.inputs,
            "success_criteria": step.success_criteria.model_dump() if step.success_criteria else None,
        }
        
        # 初始化消息列表
        # Execution Agent 不需要 Session 上下文和历史，只按 Plan 执行
        messages = self._ctx_builder.build_messages(
            session=session,
            execution_context=subtask_context,
            current_message=f"子任务目标：{step.subtask_goal}",
            capability_list=capability_list,
            include_session_context=False,  # Execution Agent 不需要 Session 上下文
            include_session_history=False,   # Execution Agent 不需要 Session 历史
        )
        
        while iteration < max_iterations:
            goal_achieved = False  # 当 success_criteria 通过时用于跳出外层循环
            iteration += 1
            logger.debug(f"Subtask {step.step_id} React loop iteration {iteration}/{max_iterations}")
            
            # 更新 system prompt
            # Execution Agent 不需要 Session 上下文
            system_prompt = self._ctx_builder.build_system_prompt(
                session, 
                subtask_context, 
                capability_list,
                include_session_context=False,  # Execution Agent 不需要 Session 上下文
            )
            messages[0] = {"role": "system", "content": system_prompt}
            
            # 调用 LLM
            response = await self._provider.chat(
                messages=messages,
                tools=self._cap_reg.get_for_llm(include_details=True),
                model=self._model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            
            # 记录 LLM 决策
            if on_progress and response.content:
                await on_progress(response.content)
            
            # 如果有工具调用
            if response.has_tool_calls:
                # 将 assistant 消息加入对话
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
                    capability = self._cap_reg.get(tool_call.name)
                    if not capability:
                        error_msg = f"Capability '{tool_call.name}' not found"
                        logger.warning(error_msg)
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
                        step_id=step.step_id,
                    )
                    
                    # 添加 tool 结果到消息
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                    
                    # 精简输入输出
                    summarized_inputs = self._summarize_inputs(tool_call.name, tool_call.arguments)
                    summarized_outputs = self._summarize_outputs(tool_call.name, result)
                    
                    # 更新瘦上下文
                    self._ctx_mgr.update_step_history({
                        "step_id": step.step_id,
                        "action": tool_call.name,
                        "result_summary": str(result.get("result", result))[:100],
                    })
                    self._ctx_mgr.update_tool_io({
                        "capability": tool_call.name,
                        "inputs_summary": summarized_inputs,
                        "outputs_summary": summarized_outputs,
                    })
                    subtask_context = self._ctx_mgr.get_context()
                    
                    # 记录到日志
                    self._log_svc.log_step(trace_id, {
                        "step_id": step.step_id,
                        "capability": tool_call.name,
                        "capability_level": capability.level,
                        "inputs": summarized_inputs,
                        "outputs": summarized_outputs,
                        "llm_decision": response.content or f"Called {tool_call.name}",
                        "duration_ms": result.get("duration_ms"),
                    })
                    
                    # 校验 success_criteria（如果提供）- 按照 SPEC.md：确定性校验优先
                    if step.success_criteria:
                        validation_result = self._validate_success_criteria(
                            step.success_criteria, result, step.step_id
                        )
                        if validation_result["passed"]:
                            # ✅ 校验通过，直接判定子任务成功，结束循环
                            logger.info(
                                f"Subtask {step.step_id} success_criteria validated, goal achieved: {step.subtask_goal}"
                            )
                            final_result = str(result.get("result", "Subtask completed successfully"))
                            goal_achieved = True
                            break  # 结束当前工具循环，稍后跳出外层 while
                        else:
                            # ❌ 校验失败，判断状态是否明确
                            error_msg = (
                                f"Step {step.step_id} success_criteria validation failed: "
                                f"{validation_result['errors']}"
                            )
                            logger.warning(error_msg)
                            
                            # 判断状态是否明确（成功或失败）
                            result_status = result.get("status", "unknown")
                            result_text = str(result.get("result", "")).lower()
                            
                            # 明确的失败指示：错误信息、非零退出码、明确的错误关键词
                            has_clear_failure = (
                                result_status == "failed"
                                or "error" in result_text
                                or "failed" in result_text
                                or "exception" in result_text
                                or "traceback" in result_text
                                or result.get("exit_code", 0) != 0
                            )
                            
                            # 明确的成功指示：成功状态、成功关键词
                            has_clear_success = (
                                result_status == "success"
                                or "success" in result_text
                                or "passed" in result_text
                                or "completed" in result_text
                            )
                            
                            # 状态不明确：既不是明确的成功也不是明确的失败
                            status_ambiguous = not has_clear_failure and not has_clear_success
                            
                            if status_ambiguous:
                                # 状态不明确，交给 LLM 判断
                                logger.info(
                                    f"Step {step.step_id} status ambiguous after validation failure, "
                                    "delegating to LLM for judgment"
                                )
                                # 在消息中告知 LLM 需要判断状态
                                messages.append({
                                    "role": "system",
                                    "content": (
                                        f"⚠️ Success criteria validation failed for step {step.step_id}: "
                                        f"{', '.join(validation_result['errors'])}. "
                                        f"However, the execution result status is ambiguous (neither clearly success nor failure). "
                                        f"Please evaluate whether the subtask goal '{step.subtask_goal}' has been achieved "
                                        f"based on the actual result."
                                    ),
                                })
                                # 标记为需要 LLM 评估
                                result["validation_failed"] = True
                                result["validation_errors"] = validation_result["errors"]
                                result["status_ambiguous"] = True
                            else:
                                # 状态明确，根据 execution_mode 决定策略
                                if step.execution_mode == "strict":
                                    # strict 模式下，校验失败应该记录到结果中
                                    # 但继续执行让 LLM 决定下一步（可能重试或调整策略）
                                    result["validation_failed"] = True
                                    result["validation_errors"] = validation_result["errors"]
                                    # 在消息中告知 LLM 校验失败
                                    messages.append({
                                        "role": "system",
                                        "content": f"⚠️ Success criteria validation failed for step {step.step_id}: {', '.join(validation_result['errors'])}. Please adjust your approach.",
                                    })
                                else:
                                    # flexible 模式下，仅记录警告，不影响执行
                                    result["validation_warning"] = validation_result["errors"]
                
                # 如果本轮工具调用已经满足 success_criteria，则跳出外层 React 循环
                if goal_achieved:
                    break
            else:
                # 没有工具调用，需要评估子任务目标是否达成
                final_result = response.content
                
                # 检查是否有状态不明确的标记（需要 LLM 判断）
                needs_llm_judgment = any(
                    msg.get("content", "").find("status is ambiguous") != -1
                    for msg in messages
                    if msg.get("role") == "system"
                )
                
                # 可选 LLM 评估：当前子任务是否已经达到目标
                if final_result and step.subtask_goal:
                    # 启发式检查：如果结果看起来已经完成（包含关键信息），先进行简单检查
                    goal_keywords = ["完成", "已", "状态", "结构", "列表", "总结", "结果", "done", "complete", "finished", "summary"]
                    result_lower = final_result.lower()
                    has_completion_indicators = any(keyword in result_lower for keyword in goal_keywords)
                    
                    # 如果结果较长（>200字符）且包含完成指示词，可能已经完成
                    # 但还是要进行 LLM 评估以确保准确性
                    # 如果状态不明确，强制进行 LLM 评估
                    if needs_llm_judgment:
                        logger.info(
                            f"Step {step.step_id} status ambiguous, forcing LLM evaluation "
                            "to determine if goal is achieved"
                        )
                    
                    goal_achieved = await self._evaluate_subtask_goal_achievement(
                        step=step,
                        current_result=final_result,
                        execution_context=subtask_context,
                        messages=messages,
                        force_evaluation=needs_llm_judgment,  # 状态不明确时强制评估
                    )
                    
                    if goal_achieved:
                        logger.info(
                            f"Subtask {step.step_id} goal achieved: {step.subtask_goal}"
                        )
                        break
                    elif iteration >= max_iterations:
                        # 达到最大迭代次数，判定为未完成
                        logger.warning(
                            f"Subtask {step.step_id} did not achieve goal after {max_iterations} iterations"
                        )
                        final_result = (
                            f"{final_result}\n\n"
                            f"⚠️ 注意：子任务目标 '{step.subtask_goal}' 可能未完全达成。"
                        )
                        break
                    elif iteration >= 3 and has_completion_indicators and len(final_result) > 200:
                        # 如果已经迭代多次，结果看起来完整，但 LLM 评估认为未完成
                        # 可能是评估过于严格，记录警告但继续执行一次
                        logger.warning(
                            f"Subtask {step.step_id} evaluation may be too strict, "
                            f"result seems complete but LLM says not achieved. Continuing one more iteration."
                        )
                        # 将当前结果加入消息，让 LLM 继续尝试
                        messages.append({
                            "role": "assistant",
                            "content": final_result,
                        })
                        messages.append({
                            "role": "user",
                            "content": f"如果子任务目标 '{step.subtask_goal}' 已经达成，请明确说明已完成。否则请继续完成。",
                        })
                        final_result = None  # 重置，继续循环
                    else:
                        # 目标未达成，继续循环
                        logger.debug(
                            f"Subtask {step.step_id} goal not yet achieved, continuing..."
                        )
                        # 将当前结果加入消息，让 LLM 继续尝试
                        messages.append({
                            "role": "assistant",
                            "content": final_result,
                        })
                        messages.append({
                            "role": "user",
                            "content": f"请继续完成子任务目标：{step.subtask_goal}",
                        })
                        final_result = None  # 重置，继续循环
                else:
                    # 没有目标或结果，直接结束
                    break
        
        return {
            "status": "success" if final_result else "fail",
            "result": final_result or "Subtask execution incomplete",
            "iterations": iteration,
        }
    
    async def _evaluate_subtask_goal_achievement(
        self,
        step: Any,  # PlanStep
        current_result: str,
        execution_context: dict[str, Any],
        messages: list[dict[str, Any]],
        force_evaluation: bool = False,
    ) -> bool:
        """评估子任务目标是否已达成（使用 LLM 评估）。
        
        按照 SPEC.md：这是"可选 LLM 评估"，用于没有 success_criteria 或需要更灵活判断的情况。
        
        Args:
            force_evaluation: 如果为 True，跳过启发式检查，强制进行 LLM 评估（用于状态不明确的情况）
        
        Returns:
            True 如果目标已达成，False 否则。
        """
        from openbot.schemas.plan_spec import PlanStep
        
        if not isinstance(step, PlanStep):
            return False
        
        # 先进行启发式检查：如果结果明确显示已完成，直接返回 True（除非强制评估）
        if not force_evaluation:
            completion_keywords = [
                "完成", "已创建", "已生成", "已写入", "成功", "完成！", "✅",
                "done", "completed", "created", "success", "finished", "succeeded"
            ]
            result_lower = current_result.lower()
            has_clear_completion = any(
                keyword in result_lower for keyword in completion_keywords
            )
            
            # 如果结果明确显示已完成，且包含子任务目标相关的关键词，倾向于认为已完成
            goal_lower = step.subtask_goal.lower()
            goal_keywords = ["目录", "结构", "文件", "创建", "生成", "写入", "运行", "测试"]
            has_goal_related = any(
                keyword in goal_lower for keyword in goal_keywords
            )
        else:
            # 强制评估时，不进行启发式检查
            has_clear_completion = False
            has_goal_related = False
        
        # 构建评估提示（限制结果长度避免 token 过多）
        result_preview = current_result[:1000] + ("..." if len(current_result) > 1000 else "")
        
        # 如果强制评估，添加更明确的提示
        if force_evaluation:
            evaluation_prompt = f"""请仔细评估以下子任务是否已经达成目标。

子任务目标：{step.subtask_goal}

当前执行结果：
{result_preview}

**重要**：success_criteria 验证失败，但执行结果状态不明确（既不是明确的成功也不是明确的失败）。
请根据实际执行结果，判断子任务目标是否已经达成。

请回答：
- 如果子任务目标已经达成，回答 "YES"
- 如果还需要继续执行，回答 "NO"
- **必须只回答 YES 或 NO，不要添加任何其他内容，不要解释，不要换行。**
"""
            system_prompt = (
                "你是一个任务评估专家。请根据子任务目标和当前执行结果，判断目标是否已达成。\n\n"
                "**重要**：当前状态不明确，success_criteria 验证失败但执行结果既不是明确的成功也不是明确的失败。"
                "请仔细分析实际执行结果，判断子任务目标是否已经达成。\n\n"
                "**必须只回答 YES 或 NO，不要添加任何其他内容。**"
            )
        else:
            evaluation_prompt = f"""请评估以下子任务是否已经达成目标。

子任务目标：{step.subtask_goal}

当前执行结果：
{result_preview}

请回答：
- 如果子任务目标已经达成，回答 "YES"
- 如果还需要继续执行，回答 "NO"
- **必须只回答 YES 或 NO，不要添加任何其他内容，不要解释，不要换行。**
"""
            system_prompt = "你是一个任务评估专家。请根据子任务目标和当前执行结果，判断目标是否已达成。\n\n**重要**：你必须只回答 YES 或 NO，不要添加任何其他内容。"
        
        try:
            # 调用 LLM 进行评估
            eval_messages = [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": evaluation_prompt},
            ]
            
            try:
                response = await self._provider.chat(
                    messages=eval_messages,
                    model=self._model,
                    temperature=0.0 if force_evaluation else 0.1,  # 强制评估时使用更低温度
                    max_tokens=50,  # 增加 token 限制，避免响应被截断（虽然只需要 YES/NO，但某些模型可能需要更多上下文）
                )
            except Exception as e:
                logger.warning(
                    f"LLM evaluation call failed for step {step.step_id}: {e}, "
                    f"using heuristic check result"
                )
                return has_clear_completion and (has_goal_related or len(current_result) > 100)
            
            # 解析响应（更宽松的解析）
            answer = (response.content or "").strip().upper()
            
            # 记录完整响应以便调试
            logger.debug(f"Goal evaluation response for step {step.step_id}: '{answer}' (full: '{response.content}')")
            
            # 如果响应为空，使用启发式检查结果
            if not answer:
                logger.warning(
                    f"Empty goal evaluation response for step {step.step_id}, "
                    f"using heuristic check result: {has_clear_completion and (has_goal_related or len(current_result) > 100)}"
                )
                return has_clear_completion and (has_goal_related or len(current_result) > 100)
            
            # 支持多种肯定回答格式
            positive_indicators = ["YES", "Y", "TRUE", "T", "达成", "完成", "已达成", "已完成", "ACHIEVED", "DONE", "是", "对"]
            negative_indicators = ["NO", "N", "FALSE", "F", "未达成", "未完成", "NOT", "CONTINUE", "否", "不对"]
            
            # 检查是否包含肯定指示词
            for indicator in positive_indicators:
                if indicator in answer:
                    return True
            
            # 检查是否包含否定指示词
            for indicator in negative_indicators:
                if indicator in answer:
                    return False
            
            # 如果都不匹配，使用启发式检查结果
            logger.warning(
                f"Unclear goal evaluation response: '{answer}', "
                f"using heuristic check result: {has_clear_completion and (has_goal_related or len(current_result) > 100)}"
            )
            return has_clear_completion and (has_goal_related or len(current_result) > 100)
            
        except Exception as e:
            logger.warning(
                f"Error evaluating subtask goal achievement: {e}, "
                f"using heuristic check result: {has_clear_completion and (has_goal_related or len(current_result) > 100)}"
            )
            # 评估失败时，使用启发式检查结果
            return has_clear_completion and (has_goal_related or len(current_result) > 100)
    
    async def _run_execution_loop(
        self,
        task: str,
        session: Session,
        execution_context: dict[str, Any],
        capability_list: list[dict[str, Any]],
        trace_id: str,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str | None:
        """（已废弃）旧的执行循环，保留用于向后兼容或测试。

        新代码应使用 _execute_plan + _execute_subtask。
        """
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
        # 注意：这是废弃的方法，但为了保持一致性，Execution Agent 不包含 Session 上下文
        messages = self._ctx_builder.build_messages(
            session=session,
            execution_context=execution_context,
            current_message=task,
            capability_list=capability_list,
            include_session_context=False,  # Execution Agent 不需要 Session 上下文
            include_session_history=False,   # Execution Agent 不需要 Session 历史
        )
        
        while iteration < self._max_iterations:
            iteration += 1
            logger.debug(f"Execution loop iteration {iteration}/{self._max_iterations}")
            
            # 更新 system prompt（因为 execution_context 可能已更新）
            # Execution Agent 不需要 Session 上下文
            system_prompt = self._ctx_builder.build_system_prompt(
                session, 
                execution_context, 
                capability_list,
                include_session_context=False,  # Execution Agent 不需要 Session 上下文
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
    
    def _validate_success_criteria(
        self,
        success_criteria: Any,  # SuccessCriteria
        result: dict[str, Any],
        step_id: int,
    ) -> dict[str, Any]:
        """校验执行结果是否符合 success_criteria。

        Returns:
            {
                "passed": bool,
                "errors": list[str]
            }
        """
        from openbot.schemas.plan_spec import SuccessCriteria
        
        if not isinstance(success_criteria, SuccessCriteria):
            return {"passed": True, "errors": []}  # 如果没有标准，默认通过
        
        errors: list[str] = []
        
        # 1. 检查 status 字段
        result_status = result.get("status", "unknown")
        expected_status = success_criteria.status
        
        if expected_status == "success":
            if result_status != "success":
                errors.append(
                    f"Expected status 'success', got '{result_status}'"
                )
        elif expected_status == "partial":
            if result_status not in ("success", "partial"):
                errors.append(
                    f"Expected status 'success' or 'partial', got '{result_status}'"
                )
        # "any" 表示不检查状态
        
        # 2. 检查 required_fields
        for field in success_criteria.required_fields:
            if field not in result:
                errors.append(f"Missing required field: {field}")
        
        # 3. 检查 field_checks（JSON Schema 验证）
        for field_name, field_schema in success_criteria.field_checks.items():
            if field_name not in result:
                continue  # 已在 required_fields 中检查
            
            field_value = result[field_name]
            field_errors = self._validate_value_against_schema(
                field_value, field_schema, field_name
            )
            errors.extend(field_errors)
        
        # 4. custom_validator 暂不支持（需要安全执行环境）
        if success_criteria.custom_validator:
            logger.debug(
                f"Step {step_id}: custom_validator provided but not executed "
                "(requires secure execution environment)"
            )
        
        return {
            "passed": len(errors) == 0,
            "errors": errors,
        }
    
    def _validate_value_against_schema(
        self, value: Any, schema: dict[str, Any], path: str = ""
    ) -> list[str]:
        """根据 JSON Schema 片段验证值。

        Args:
            value: 要验证的值
            schema: JSON Schema 片段
            path: 字段路径（用于错误消息）

        Returns:
            错误列表（空列表表示验证通过）
        """
        errors: list[str] = []
        schema_type = schema.get("type")
        
        # 类型检查
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        
        if schema_type in type_map:
            expected_type = type_map[schema_type]
            if not isinstance(value, expected_type):
                errors.append(
                    f"{path} should be {schema_type}, got {type(value).__name__}"
                )
                return errors  # 类型不匹配，不再继续检查
        
        # Enum 验证
        if "enum" in schema and value not in schema["enum"]:
            errors.append(
                f"{path} must be one of {schema['enum']}, got {value}"
            )
        
        # 数值范围验证
        if schema_type in ("integer", "number") and isinstance(value, (int, float)):
            if "minimum" in schema and value < schema["minimum"]:
                errors.append(
                    f"{path} must be >= {schema['minimum']}, got {value}"
                )
            if "maximum" in schema and value > schema["maximum"]:
                errors.append(
                    f"{path} must be <= {schema['maximum']}, got {value}"
                )
        
        # 字符串长度验证
        if schema_type == "string" and isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                errors.append(
                    f"{path} must be at least {schema['minLength']} chars, "
                    f"got {len(value)}"
                )
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                errors.append(
                    f"{path} must be at most {schema['maxLength']} chars, "
                    f"got {len(value)}"
                )
            # Pattern 验证（正则表达式）
            if "pattern" in schema:
                import re
                pattern = schema["pattern"]
                # 使用 re.search 而不是 re.match，允许在任意位置匹配
                # 首先尝试大小写敏感匹配
                if re.search(pattern, value):
                    pass  # 匹配成功
                # 如果失败，尝试大小写不敏感匹配（容错机制）
                elif re.search(pattern, value, re.IGNORECASE):
                    # 大小写不敏感匹配成功，记录警告但不报错
                    logger.debug(
                        f"{path} matched pattern '{pattern}' with case-insensitive fallback"
                    )
                else:
                    # 两种方式都失败，报错（添加调试信息）
                    value_preview = value[:200] + ("..." if len(value) > 200 else "")
                    logger.debug(
                        f"Pattern '{pattern}' did not match value (preview: '{value_preview}')"
                    )
                    errors.append(
                        f"{path} does not match pattern '{pattern}'"
                    )
        
        # 对象验证
        if schema_type == "object" and isinstance(value, dict):
            obj_props = schema.get("properties", {})
            for k, v in value.items():
                if k in obj_props:
                    errors.extend(
                        self._validate_value_against_schema(
                            v, obj_props[k], f"{path}.{k}" if path else k
                        )
                    )
        
        # 数组验证
        if schema_type == "array" and isinstance(value, list):
            if "items" in schema:
                for i, item in enumerate(value):
                    errors.extend(
                        self._validate_value_against_schema(
                            item, schema["items"], f"{path}[{i}]" if path else f"[{i}]"
                        )
                    )
            if "minItems" in schema and len(value) < schema["minItems"]:
                errors.append(
                    f"{path} must have at least {schema['minItems']} items, "
                    f"got {len(value)}"
                )
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                errors.append(
                    f"{path} must have at most {schema['maxItems']} items, "
                    f"got {len(value)}"
                )
        
        return errors
    
    def _calculate_backoff_delay(
        self, attempt: int, retry_policy: Any  # RetryPolicy
    ) -> int:
        """计算重试延迟（毫秒）。

        Args:
            attempt: 当前尝试次数（从 0 开始）
            retry_policy: 重试策略

        Returns:
            延迟时间（毫秒）
        """
        from openbot.schemas.plan_spec import RetryPolicy
        
        if not isinstance(retry_policy, RetryPolicy):
            return 1000  # 默认 1 秒
        
        initial_delay = retry_policy.initial_delay_ms
        max_delay = retry_policy.max_delay_ms
        strategy = retry_policy.backoff_strategy
        
        if strategy == "fixed":
            delay = initial_delay
        elif strategy == "linear":
            delay = initial_delay * (attempt + 1)
        elif strategy == "exponential":
            delay = initial_delay * (2 ** attempt)
        else:
            delay = initial_delay
        
        # 限制在 max_delay 内
        return min(delay, max_delay)
    
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

