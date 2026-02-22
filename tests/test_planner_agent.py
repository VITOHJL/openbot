"""Tests for Orchestration Agent."""

import pytest
from pathlib import Path

from openbot.agent.planner import OrchestrationAgent
from openbot.config import load_config
from openbot.infra.capability_registry import CapabilityRegistry
from openbot.infra.log_service import LogService
from openbot.infra.template_registry import TemplateRegistry
from openbot.infra.test_case_store import TestCaseStore
from openbot.providers.litellm_provider import LiteLLMProvider


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """创建临时 workspace。"""
    workspace = tmp_path / ".openbot" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def planner_agent(workspace: Path) -> OrchestrationAgent:
    """创建 OrchestrationAgent 实例。"""
    config = load_config()
    
    # 创建 Provider
    provider = LiteLLMProvider(
        provider_name="anthropic",
        default_model="claude-3-haiku-20240307",
        api_key=config.providers.anthropic.api_key,
        api_base=config.providers.anthropic.api_base,
    )
    
    # 创建基础设施
    cap_reg = CapabilityRegistry()
    log_svc = LogService()
    template_reg = TemplateRegistry()
    test_store = TestCaseStore()
    
    return OrchestrationAgent(
        provider=provider,
        capability_registry=cap_reg,
        log_service=log_svc,
        template_registry=template_reg,
        test_case_store=test_store,
        model="claude-3-haiku-20240307",
        temperature=0.7,
    )


@pytest.mark.asyncio
async def test_planner_mode_a_task_plan(planner_agent: OrchestrationAgent):
    """测试模式 A: 任务拆解 Plan 设计。"""
    plan = await planner_agent.plan_task("读取一个文件并输出内容")
    
    assert plan is not None
    assert plan.plan_id is not None
    assert plan.task is not None
    assert isinstance(plan.steps, list)


@pytest.mark.asyncio
async def test_planner_mode_c_test_generation(planner_agent: OrchestrationAgent):
    """测试模式 C: 测试用例生成。"""
    # 先注册一个测试能力
    from openbot.infra.capability_registry import Capability
    capability = Capability(
        name="test_capability",
        description="A test capability",
        level="atomic",
        schema={
            "type": "object",
            "properties": {
                "input": {"type": "string"}
            },
            "required": ["input"]
        }
    )
    planner_agent._cap_reg.register(capability)
    
    # 生成测试用例
    test_cases = await planner_agent.generate_test_cases(
        "test_capability",
        test_types=["normal", "boundary"]
    )
    
    assert test_cases is not None
    assert len(test_cases) > 0
    for test_case in test_cases:
        assert test_case.test_id is not None
        assert test_case.capability == "test_capability"
        assert test_case.type in ["normal", "boundary", "error", "extreme"]
