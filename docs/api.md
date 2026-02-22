# openbot API 文档

## 核心 API

### ExecutionAgent

**位置**: `openbot.agent.loop.ExecutionAgent`

#### `process_task(task: str, *, session: Session | None = None, on_progress: Callable | None = None) -> str`

处理单次任务的高层入口。

**参数**:
- `task`: 任务描述（文本）
- `session`: 可选的会话对象
- `on_progress`: 可选的进度回调函数

**返回**: 任务执行结果（文本）

**示例**:
```python
from openbot.agent.loop import ExecutionAgent

agent = ExecutionAgent(...)
result = await agent.process_task("读取文件 test.txt")
```

### OrchestrationAgent

**位置**: `openbot.agent.planner.OrchestrationAgent`

#### `plan_task(task: str, context: dict | None = None) -> PlanSpec`

模式 A: 任务拆解 Plan 设计。

**参数**:
- `task`: 任务描述
- `context`: 可选上下文信息

**返回**: `PlanSpec` 对象

**示例**:
```python
from openbot.agent.planner import OrchestrationAgent

planner = OrchestrationAgent(...)
plan = await planner.plan_task("读取文件并输出内容")
```

#### `extract_workflow(trace_id: str, audit_report: AuditReport | None = None) -> CandidateWorkflowSpec`

模式 B: 从成功执行日志抽象 Workflow。

**参数**:
- `trace_id`: 执行轨迹 ID
- `audit_report`: 可选的审计报告

**返回**: `CandidateWorkflowSpec` 对象

**示例**:
```python
workflow = await planner.extract_workflow("exec_abc123")
```

#### `generate_test_cases(capability_name: str, test_types: list | None = None) -> list[TestCaseSpec]`

模式 C: 为能力/Workflow 生成测试用例。

**参数**:
- `capability_name`: 能力名称
- `test_types`: 要生成的测试类型列表（normal/boundary/error/extreme）

**返回**: `TestCaseSpec` 列表

**示例**:
```python
test_cases = await planner.generate_test_cases("read_file", ["normal", "boundary"])
```

### AuditorAgent

**位置**: `openbot.agent.auditor.AuditorAgent`

#### `audit_trace(trace_id: str, user_view: dict | None = None) -> AuditReport`

审计执行轨迹。

**参数**:
- `trace_id`: 执行轨迹 ID
- `user_view`: 可选的用户视图（用户看到的回复）

**返回**: `AuditReport` 对象

**示例**:
```python
from openbot.agent.auditor import AuditorAgent

auditor = AuditorAgent(...)
report = await auditor.audit_trace("exec_abc123")
```

## 基础设施 API

### CapabilityRegistry

**位置**: `openbot.infra.capability_registry.CapabilityRegistry`

#### `register(capability: Capability) -> None`

注册能力。

#### `get(name: str) -> Capability | None`

获取能力。

#### `list_all() -> list[Capability]`

列出所有能力。

#### `get_for_llm(include_details: bool = False) -> list[dict]`

获取用于 LLM 的工具列表。

**参数**:
- `include_details`: 如果为 True，返回完整的工具定义；如果为 False，只返回轻量信息

### ContextManager

**位置**: `openbot.infra.context_manager.ContextManager`

#### `init_context(task: dict) -> None`

初始化瘦上下文。

#### `update_step_history(step: dict) -> None`

更新步骤历史。

#### `get_context() -> dict`

获取当前瘦上下文。

### LogService

**位置**: `openbot.infra.log_service.LogService`

#### `start_trace(trace_id: str, task: str) -> None`

启动执行轨迹。

#### `log_step(trace_id: str, step: dict) -> None`

记录步骤。

#### `finish_trace(trace_id: str, status: str, final_result: str) -> None`

完成执行轨迹。

#### `get_trace(trace_id: str) -> ExecutionTrace | None`

获取执行轨迹。

## Schema 定义

所有 Agent 间通信使用严格的 JSON Schema，定义在 `openbot.schemas` 模块中：

- `PlanSpec`: 编排 Agent 模式 A 输出
- `ExecutionTrace`: 执行 Agent 写入 LogService
- `CandidateWorkflowSpec`: 编排 Agent 模式 B 输出
- `AuditReport`: 审计 Agent 输出
- `TestCaseSpec`: 编排 Agent 模式 C 输出

详细定义见各 Schema 文件。
