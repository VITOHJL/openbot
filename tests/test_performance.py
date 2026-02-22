  """Performance tests for openbot."""

import time
import pytest
from pathlib import Path

from openbot.infra.capability_registry import CapabilityRegistry
from openbot.infra.context_manager import ContextManager
from openbot.infra.log_service import LogService


@pytest.fixture
def cap_registry():
    """创建能力注册表。"""
    reg = CapabilityRegistry()
    # 注册一些测试能力
    from openbot.infra.capability_registry import Capability
    for i in range(100):
        reg.register(Capability(
            name=f"test_cap_{i}",
            description=f"Test capability {i}",
            level="atomic",
            schema={"type": "object", "properties": {}}
        ))
    return reg


@pytest.fixture
def ctx_manager():
    """创建上下文管理器。"""
    return ContextManager()


@pytest.fixture
def log_service():
    """创建日志服务。"""
    return LogService()


def test_context_management_performance(ctx_manager: ContextManager):
    """测试上下文管理性能（要求 < 10ms）。"""
    # 初始化上下文
    ctx_manager.init_context({"task": "test"})
    
    # 测试更新操作
    start = time.perf_counter()
    for i in range(100):
        ctx_manager.update_step_history({
            "step_id": i,
            "action": f"action_{i}",
            "result": f"result_{i}"
        })
        ctx_manager.get_context()
    elapsed = time.perf_counter() - start
    
    # 平均每次操作应该 < 10ms
    avg_time_ms = (elapsed / 100) * 1000
    assert avg_time_ms < 10, f"Context management too slow: {avg_time_ms:.2f}ms"


def test_log_query_performance(log_service: LogService):
    """测试日志查询性能（要求 < 100ms）。"""
    # 创建一些测试轨迹
    for i in range(100):
        trace_id = f"trace_{i}"
        log_service.start_trace(trace_id, f"task_{i}")
        log_service.log_step(trace_id, {
            "step_id": 1,
            "capability": "test",
            "capability_level": "atomic",
            "inputs": {"test": "value"},
        })
        log_service.finish_trace(trace_id, "success", "done")
    
    # 测试查询性能
    start = time.perf_counter()
    for i in range(100):
        trace = log_service.get_trace(f"trace_{i}")
        assert trace is not None
    elapsed = time.perf_counter() - start
    
    # 平均每次查询应该 < 100ms
    avg_time_ms = (elapsed / 100) * 1000
    assert avg_time_ms < 100, f"Log query too slow: {avg_time_ms:.2f}ms"


def test_capability_matching_performance(cap_registry: CapabilityRegistry):
    """测试能力匹配性能（要求 < 50ms）。"""
    # 测试查找性能
    start = time.perf_counter()
    for i in range(100):
        cap = cap_registry.get(f"test_cap_{i}")
        assert cap is not None
    elapsed = time.perf_counter() - start
    
    # 平均每次匹配应该 < 50ms
    avg_time_ms = (elapsed / 100) * 1000
    assert avg_time_ms < 50, f"Capability matching too slow: {avg_time_ms:.2f}ms"


def test_capability_list_generation_performance(cap_registry: CapabilityRegistry):
    """测试能力清单生成性能。"""
    # 测试轻量清单生成
    start = time.perf_counter()
    for _ in range(10):
        _ = cap_registry.get_for_llm(include_details=False)
    elapsed = time.perf_counter() - start
    
    avg_time_ms = (elapsed / 10) * 1000
    # 轻量清单应该很快
    assert avg_time_ms < 100, f"Lightweight list generation too slow: {avg_time_ms:.2f}ms"
    
    # 测试完整清单生成
    start = time.perf_counter()
    for _ in range(10):
        _ = cap_registry.get_for_llm(include_details=True)
    elapsed = time.perf_counter() - start
    
    avg_time_ms = (elapsed / 10) * 1000
    # 完整清单可能稍慢，但仍然应该 < 200ms
    assert avg_time_ms < 200, f"Full list generation too slow: {avg_time_ms:.2f}ms"
