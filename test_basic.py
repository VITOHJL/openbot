"""Basic test for openbot."""

import asyncio
from pathlib import Path

from openbot.agent.context import ContextBuilder
from openbot.agent.loop import ExecutionAgent
from openbot.infra.capability_registry import Capability, CapabilityRegistry
from openbot.infra.context_manager import ContextManager
from openbot.infra.log_service import LogService
from openbot.providers.litellm_provider import LiteLLMProvider
from openbot.session.manager import SessionManager


async def test_basic():
    """测试基本的执行流程。"""
    workspace = Path("/tmp/openbot_test")
    workspace.mkdir(parents=True, exist_ok=True)
    
    # 初始化组件
    provider = LiteLLMProvider(
        api_key=None,  # 测试时可以不提供，会使用环境变量
        default_model="anthropic/claude-opus-4-5"
    )
    ctx_mgr = ContextManager()
    cap_reg = CapabilityRegistry()
    log_svc = LogService()
    session_mgr = SessionManager(workspace)
    ctx_builder = ContextBuilder(workspace, session_mgr)
    
    # 注册测试能力
    cap_reg.register(Capability(
        name="echo",
        description="Echo back the input (test capability)",
        level="atomic",
        schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to echo"}
            },
            "required": ["text"]
        }
    ))
    
    # 创建 Agent
    agent = ExecutionAgent(
        provider=provider,
        context_manager=ctx_mgr,
        capability_registry=cap_reg,
        log_service=log_svc,
        context_builder=ctx_builder,
        session_manager=session_mgr,
        max_iterations=5,  # 测试时减少迭代次数
    )
    
    # 测试任务
    task = "Use the echo tool to echo 'Hello, openbot!'"
    session = session_mgr.get_or_create("test:session")
    
    print(f"Testing task: {task}")
    result = await agent.process_task(task, session=session)
    print(f"Result: {result}")
    
    # 检查日志
    trace = log_svc.get_trace("exec_" + "test")  # 需要从实际 trace_id 获取
    if trace:
        print(f"Trace status: {trace.status}")
        print(f"Trace steps: {len(trace.steps)}")


if __name__ == "__main__":
    asyncio.run(test_basic())
