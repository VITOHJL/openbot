"""Tests for Execution Agent."""

import pytest
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


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """创建临时 workspace。"""
    workspace = tmp_path / ".openbot" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def agent(workspace: Path) -> ExecutionAgent:
    """创建 ExecutionAgent 实例。"""
    config = load_config()
    
    # 创建 Provider
    provider = LiteLLMProvider(
        provider_name="anthropic",
        default_model="claude-3-haiku-20240307",  # 使用较便宜的模型进行测试
        api_key=config.providers.anthropic.api_key,
        api_base=config.providers.anthropic.api_base,
    )
    
    # 创建基础设施
    ctx_mgr = ContextManager()
    cap_reg = CapabilityRegistry()
    log_svc = LogService()
    session_mgr = SessionManager(workspace)
    ctx_builder = ContextBuilder(workspace, session_mgr)
    
    # 创建工具注册表并自动发现工具
    tool_registry = ToolRegistry(cap_reg)
    tool_registry.auto_discover()
    
    return ExecutionAgent(
        provider=provider,
        context_manager=ctx_mgr,
        capability_registry=cap_reg,
        log_service=log_svc,
        context_builder=ctx_builder,
        session_manager=session_mgr,
        tool_registry=tool_registry,
        max_iterations=5,  # 测试时限制迭代次数
        model="claude-3-haiku-20240307",
        temperature=0.7,
        max_tokens=2048,
    )


@pytest.mark.asyncio
async def test_exec_agent_simple_task(agent: ExecutionAgent):
    """测试执行 Agent 处理简单任务。"""
    result = await agent.process_task("使用 echo 工具输出 'Hello, World!'")
    
    assert result is not None
    assert len(result) > 0


@pytest.mark.asyncio
async def test_exec_agent_file_operations(agent: ExecutionAgent, workspace: Path):
    """测试执行 Agent 文件操作。"""
    test_file = workspace / "test.txt"
    test_content = "Hello, Test!"
    
    # 直接调用 write_file 工具（不依赖 LLM 决策）
    from openbot.agent.tools.filesystem import WriteFileTool
    write_tool = WriteFileTool()
    await write_tool.execute(file_path=str(test_file), content=test_content)
    
    # 验证文件已创建
    assert test_file.exists()
    assert test_file.read_text() == test_content
    
    # 直接调用 read_file 工具
    from openbot.agent.tools.filesystem import ReadFileTool
    read_tool = ReadFileTool()
    result = await read_tool.execute(file_path=str(test_file))
    assert result is not None
    assert test_content in result


@pytest.mark.asyncio
async def test_exec_agent_context_management(agent: ExecutionAgent):
    """测试执行 Agent 的上下文管理。"""
    # 执行一个任务
    await agent.process_task("使用 echo 工具输出 'test'")
    
    # 检查上下文是否已初始化
    context = agent._ctx_mgr.get_context()
    assert context is not None
    assert "task" in context or "task_info" in context


@pytest.mark.asyncio
async def test_exec_agent_logging(agent: ExecutionAgent):
    """测试执行 Agent 的日志记录。"""
    result = await agent.process_task("使用 echo 工具输出 'test logging'")
    
    # 检查日志服务是否有记录
    # 注意：这里需要 LogService 提供查询接口
    assert result is not None
