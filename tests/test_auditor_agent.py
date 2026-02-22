"""Tests for Auditor Agent."""

import pytest
from pathlib import Path

from openbot.agent.auditor import AuditorAgent
from openbot.config import load_config
from openbot.infra.capability_registry import CapabilityRegistry
from openbot.infra.log_service import LogService
from openbot.infra.template_registry import TemplateRegistry
from openbot.providers.litellm_provider import LiteLLMProvider


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """创建临时 workspace。"""
    workspace = tmp_path / ".openbot" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def auditor_agent_with_trace(workspace: Path):
    """创建 AuditorAgent 实例，并预先创建一条执行轨迹。"""
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
    
    # 预先创建一条执行轨迹
    trace_id = "test_trace_001"
    log_svc.start_trace(trace_id, "测试任务")
    log_svc.log_step(trace_id, {
        "step_id": 1,
        "capability": "echo",
        "capability_level": "atomic",
        "inputs": {"text": "Hello"},
        "outputs": {"result": "Echo: Hello", "status": "success"},
        "duration_ms": 100,
        "llm_decision": "使用 echo 工具输出 Hello",
    })
    log_svc.finish_trace(trace_id, "success", "任务完成")
    
    auditor = AuditorAgent(
        provider=provider,
        capability_registry=cap_reg,
        log_service=log_svc,
        template_registry=template_reg,
        model="claude-3-haiku-20240307",
        temperature=0.3,
    )
    
    return auditor, trace_id


@pytest.mark.asyncio
async def test_auditor_audit_trace(auditor_agent_with_trace):
    """测试审计执行轨迹。"""
    auditor_agent, trace_id = auditor_agent_with_trace
    
    report = await auditor_agent.audit_trace(trace_id)
    assert report is not None
    assert report.audit_id is not None
    assert report.execution_trace_id == trace_id
    assert report.verdict in ["pass", "fail", "warning"]
    assert report.risk_level in ["low", "medium", "high"]
