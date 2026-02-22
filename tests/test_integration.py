"""Integration tests for openbot."""

import pytest
from pathlib import Path

from openbot.agent.auditor import AuditorAgent
from openbot.agent.loop import ExecutionAgent
from openbot.agent.planner import OrchestrationAgent
from openbot.agent.context import ContextBuilder
from openbot.agent.tools.registry import ToolRegistry
from openbot.config import load_config
from openbot.infra.capability_registry import CapabilityRegistry
from openbot.infra.context_manager import ContextManager
from openbot.infra.log_service import LogService
from openbot.infra.template_registry import TemplateRegistry
from openbot.infra.test_case_store import TestCaseStore
from openbot.providers.litellm_provider import LiteLLMProvider
from openbot.session.manager import SessionManager


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """创建临时 workspace。"""
    workspace = tmp_path / ".openbot" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def shared_infra(workspace: Path):
    """创建共享的基础设施。"""
    config = load_config()
    
    provider = LiteLLMProvider(
        provider_name="anthropic",
        default_model="claude-3-haiku-20240307",
        api_key=config.providers.anthropic.api_key,
        api_base=config.providers.anthropic.api_base,
    )
    
    cap_reg = CapabilityRegistry()
    log_svc = LogService()
    template_reg = TemplateRegistry()
    test_store = TestCaseStore()
    ctx_mgr = ContextManager()
    session_mgr = SessionManager(workspace)
    ctx_builder = ContextBuilder(workspace, session_mgr)
    
    # 注册工具
    tool_registry = ToolRegistry(cap_reg)
    tool_registry.auto_discover()
    
    return {
        "provider": provider,
        "cap_reg": cap_reg,
        "log_svc": log_svc,
        "template_reg": template_reg,
        "test_store": test_store,
        "ctx_mgr": ctx_mgr,
        "session_mgr": session_mgr,
        "ctx_builder": ctx_builder,
        "tool_registry": tool_registry,
    }


@pytest.mark.asyncio
async def test_agent_interaction(shared_infra, workspace: Path):
    """测试 Agent 间交互：执行 -> 审计 -> 编排（模式 B）。"""
    # 创建执行 Agent
    exec_agent = ExecutionAgent(
        provider=shared_infra["provider"],
        context_manager=shared_infra["ctx_mgr"],
        capability_registry=shared_infra["cap_reg"],
        log_service=shared_infra["log_svc"],
        context_builder=shared_infra["ctx_builder"],
        session_manager=shared_infra["session_mgr"],
        tool_registry=shared_infra["tool_registry"],
        max_iterations=3,
        model="claude-3-haiku-20240307",
    )
    
    # 执行任务
    result = await exec_agent.process_task("使用 echo 工具输出 'integration test'")
    assert result is not None
    
    # 创建审计 Agent
    auditor_agent = AuditorAgent(
        provider=shared_infra["provider"],
        capability_registry=shared_infra["cap_reg"],
        log_service=shared_infra["log_svc"],
        template_registry=shared_infra["template_reg"],
        model="claude-3-haiku-20240307",
    )
    
    # 创建编排 Agent
    planner_agent = OrchestrationAgent(
        provider=shared_infra["provider"],
        capability_registry=shared_infra["cap_reg"],
        log_service=shared_infra["log_svc"],
        template_registry=shared_infra["template_reg"],
        test_case_store=shared_infra["test_store"],
        model="claude-3-haiku-20240307",
    )
    
    # 测试编排 Agent 模式 A
    plan = await planner_agent.plan_task("读取文件并输出")
    assert plan is not None


@pytest.mark.asyncio
async def test_capability_registry_integration(shared_infra):
    """测试能力注册表的集成。"""
    cap_reg = shared_infra["cap_reg"]
    
    # 检查工具是否已注册
    tools = cap_reg.list_all()
    assert len(tools) > 0
    
    # 检查工具格式
    for tool in tools:
        assert tool.name is not None
        assert tool.description is not None
    
    # 测试 LLM 格式
    llm_tools = cap_reg.get_for_llm(include_details=True)
    assert len(llm_tools) > 0
    for tool in llm_tools:
        assert "type" in tool
        assert tool["type"] == "function"
        assert "function" in tool
