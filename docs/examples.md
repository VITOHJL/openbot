# openbot 使用示例

## 基本使用

### CLI 单次对话

```bash
openbot agent -m "读取文件 README.md"
```

### CLI 交互式模式

```bash
openbot agent
```

### 配置管理

```bash
# 查看配置
openbot config

# 使用全局配置
openbot config --global
```

## 编程示例

### 使用执行 Agent

```python
import asyncio
from pathlib import Path
from openbot.agent.loop import ExecutionAgent
from openbot.agent.context import ContextBuilder
from openbot.agent.tools.registry import ToolRegistry
from openbot.config import load_config
from openbot.infra.capability_registry import CapabilityRegistry
from openbot.infra.context_manager import ContextManager
from openbot.infra.log_service import LogService
from openbot.providers.litellm_provider import LiteLLMProvider
from openbot.session.manager import SessionManager

async def main():
    config = load_config()
    workspace = Path(".openbot/workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    
    # 创建 Provider
    provider = LiteLLMProvider(
        provider_name="anthropic",
        model=config.agents.defaults.model,
        api_key=config.providers.anthropic.api_key,
        api_base=config.providers.anthropic.api_base,
    )
    
    # 创建基础设施
    ctx_mgr = ContextManager()
    cap_reg = CapabilityRegistry()
    log_svc = LogService()
    session_mgr = SessionManager(workspace)
    ctx_builder = ContextBuilder(workspace, session_mgr)
    
    # 创建工具注册表
    tool_registry = ToolRegistry(cap_reg)
    tool_registry.auto_discover()
    
    # 创建执行 Agent
    agent = ExecutionAgent(
        provider=provider,
        context_manager=ctx_mgr,
        capability_registry=cap_reg,
        log_service=log_svc,
        context_builder=ctx_builder,
        session_manager=session_mgr,
        tool_registry=tool_registry,
    )
    
    # 执行任务
    result = await agent.process_task("读取文件 README.md")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
```

### 使用编排 Agent

```python
from openbot.agent.planner import OrchestrationAgent
from openbot.infra.capability_registry import CapabilityRegistry
from openbot.infra.log_service import LogService
from openbot.infra.template_registry import TemplateRegistry
from openbot.infra.test_case_store import TestCaseStore
from openbot.providers.litellm_provider import LiteLLMProvider

# 创建编排 Agent
planner = OrchestrationAgent(
    provider=provider,
    capability_registry=cap_reg,
    log_service=log_svc,
    template_registry=template_reg,
    test_case_store=test_store,
)

# 模式 A: 生成任务计划
plan = await planner.plan_task("读取文件并输出内容")
print(f"计划 ID: {plan.plan_id}")
print(f"步骤数: {len(plan.steps)}")

# 模式 C: 生成测试用例
test_cases = await planner.generate_test_cases("read_file", ["normal", "boundary"])
for test_case in test_cases:
    print(f"测试 {test_case.test_id}: {test_case.type}")
```

### 使用审计 Agent

```python
from openbot.agent.auditor import AuditorAgent

# 创建审计 Agent
auditor = AuditorAgent(
    provider=provider,
    capability_registry=cap_reg,
    log_service=log_svc,
    template_registry=template_reg,
)

# 审计执行轨迹
report = await auditor.audit_trace("exec_abc123")
print(f"审计结果: {report.verdict}")
print(f"风险级别: {report.risk_level}")
print(f"问题数: {len(report.issues)}")
```

## 添加自定义工具

### 创建工具类

```python
from openbot.agent.tools.base import Tool
from typing import Any

class MyCustomTool(Tool):
    @property
    def name(self) -> str:
        return "my_custom_tool"
    
    @property
    def description(self) -> str:
        return "我的自定义工具"
    
    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "输入参数"}
            },
            "required": ["input"]
        }
    
    async def execute(self, **kwargs: Any) -> str:
        input_value = kwargs.get("input", "")
        return f"处理结果: {input_value}"
```

### 注册工具

工具会自动从 `openbot/agent/tools/` 目录发现并注册。只需将工具文件放在该目录下即可。

## 工作流示例

### 完整流程：执行 -> 审计 -> 提取 Workflow

```python
# 1. 执行任务
result = await exec_agent.process_task("读取文件并输出")

# 2. 获取执行轨迹 ID（需要从 LogService 获取）
trace_id = "exec_abc123"

# 3. 审计执行轨迹
audit_report = await auditor.audit_trace(trace_id)

# 4. 如果审计通过，提取 Workflow
if audit_report.verdict == "pass" and audit_report.template_candidate_eligible:
    workflow = await planner.extract_workflow(trace_id, audit_report)
    print(f"提取的工作流: {workflow.name}")
```

## 配置示例

### 配置文件结构

```json
{
  "agents": {
    "defaults": {
      "workspace": "./.openbot/workspace",
      "model": "claude-3-opus-20240229",
      "maxTokens": 8192,
      "temperature": 0.7,
      "maxToolIterations": 20
    }
  },
  "providers": {
    "anthropic": {
      "apiKey": "your-api-key",
      "apiBase": null
    }
  }
}
```

### 环境变量

所有配置项都可以通过环境变量覆盖，前缀为 `OPENBOT_`：

```bash
export OPENBOT_AGENTS__DEFAULTS__MODEL="claude-3-haiku-20240307"
export OPENBOT_PROVIDERS__ANTHROPIC__APIKEY="your-api-key"
```
