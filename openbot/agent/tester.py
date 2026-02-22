"""Tester Agent - 测试用例执行和结果汇总."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from openbot.infra.capability_registry import CapabilityRegistry
from openbot.infra.test_case_store import TestCaseStore
from openbot.schemas.test_case_spec import TestCaseSpec, ToleranceSpec


class TestResult:
    """测试结果结构。"""

    def __init__(
        self,
        *,
        test_id: str,
        passed: bool,
        actual_output: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        self.test_id = test_id
        self.passed = passed
        self.actual_output = actual_output
        self.error = error
        self.duration_ms = duration_ms

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "test_id": self.test_id,
            "passed": self.passed,
            "actual_output": self.actual_output,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


class TestSummary:
    """测试汇总结果。"""

    def __init__(self) -> None:
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.results: list[TestResult] = []

    def add_result(self, result: TestResult) -> None:
        """添加测试结果。"""
        self.total += 1
        if result.passed:
            self.passed += 1
        else:
            self.failed += 1
        self.results.append(result)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.passed / self.total if self.total > 0 else 0.0,
            "results": [r.to_dict() for r in self.results],
        }


class TesterAgent:
    """测试 Agent，负责执行测试用例并汇总结果。
    
    按照 SPEC.md 2.2.4：测试 Agent 可以基于 Mode C 生成的测试用例执行实际调用，并汇总结果。
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        test_case_store: TestCaseStore,
    ) -> None:
        self._cap_reg = capability_registry
        self._test_store = test_case_store

    async def execute_test_case(
        self,
        test_case: TestCaseSpec,
        executor: Any,  # ExecutionAgent 或类似的可执行能力的对象
    ) -> TestResult:
        """执行单个测试用例。
        
        Args:
            test_case: 测试用例
            executor: 执行器，需要有 _execute_capability 方法
        
        Returns:
            TestResult 对象
        """
        import time
        start_time = time.time()
        
        try:
            # 获取能力
            capability = self._cap_reg.get(test_case.capability)
            if not capability:
                return TestResult(
                    test_id=test_case.test_id,
                    passed=False,
                    error=f"Capability not found: {test_case.capability}",
                    duration_ms=0,
                )
            
            # 执行能力
            actual_output = await executor._execute_capability(
                capability=capability,
                arguments=test_case.input,
                trace_id=f"test_{test_case.test_id}",
                step_id=1,
            )
            
            # 比较结果
            passed = self._compare_outputs(
                actual_output=actual_output,
                expected_output=test_case.expected_output,
                tolerance=test_case.tolerance,
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            return TestResult(
                test_id=test_case.test_id,
                passed=passed,
                actual_output=actual_output,
                duration_ms=duration_ms,
            )
            
        except Exception as e:
            logger.error(f"Error executing test case {test_case.test_id}: {e}", exc_info=True)
            duration_ms = int((time.time() - start_time) * 1000)
            return TestResult(
                test_id=test_case.test_id,
                passed=False,
                error=str(e),
                duration_ms=duration_ms,
            )

    async def execute_test_suite(
        self,
        capability_name: str,
        executor: Any,
        test_types: list[str] | None = None,
    ) -> TestSummary:
        """执行测试套件（某个能力的所有测试用例）。
        
        Args:
            capability_name: 能力名称
            executor: 执行器
            test_types: 要执行的测试类型列表，如果为 None 则执行所有类型
        
        Returns:
            TestSummary 对象
        """
        # 获取测试用例
        test_cases = self._test_store.get_by_capability(capability_name)
        
        # 过滤测试类型
        if test_types:
            test_cases = [tc for tc in test_cases if tc.type in test_types]
        
        if not test_cases:
            logger.warning(f"No test cases found for capability: {capability_name}")
            return TestSummary()
        
        # 执行所有测试用例
        summary = TestSummary()
        for test_case in test_cases:
            result = await self.execute_test_case(test_case, executor)
            summary.add_result(result)
            logger.info(
                f"Test {test_case.test_id} ({test_case.type}): "
                f"{'PASS' if result.passed else 'FAIL'}"
            )
        
        return summary

    def _compare_outputs(
        self,
        actual_output: dict[str, Any],
        expected_output: dict[str, Any],
        tolerance: ToleranceSpec,
    ) -> bool:
        """比较实际输出和预期输出。
        
        Args:
            actual_output: 实际输出
            expected_output: 预期输出
            tolerance: 容差设置
        
        Returns:
            是否匹配
        """
        # 如果要求精确匹配
        if tolerance.exact_match:
            return self._deep_equal(actual_output, expected_output, tolerance.fields_to_ignore)
        
        # 否则进行字段级别的比较
        return self._compare_fields(actual_output, expected_output, tolerance.fields_to_ignore)

    def _deep_equal(
        self,
        actual: Any,
        expected: Any,
        ignore_fields: list[str],
    ) -> bool:
        """深度比较两个值是否相等（忽略指定字段）。"""
        if isinstance(actual, dict) and isinstance(expected, dict):
            # 过滤掉要忽略的字段
            actual_filtered = {k: v for k, v in actual.items() if k not in ignore_fields}
            expected_filtered = {k: v for k, v in expected.items() if k not in ignore_fields}
            
            if set(actual_filtered.keys()) != set(expected_filtered.keys()):
                return False
            
            for key in actual_filtered:
                if not self._deep_equal(actual_filtered[key], expected_filtered[key], ignore_fields):
                    return False
            return True
        
        if isinstance(actual, list) and isinstance(expected, list):
            if len(actual) != len(expected):
                return False
            for a, e in zip(actual, expected):
                if not self._deep_equal(a, e, ignore_fields):
                    return False
            return True
        
        return actual == expected

    def _compare_fields(
        self,
        actual: dict[str, Any],
        expected: dict[str, Any],
        ignore_fields: list[str],
    ) -> bool:
        """字段级别的比较（不要求精确匹配，只检查关键字段）。"""
        # 过滤掉要忽略的字段
        actual_filtered = {k: v for k, v in actual.items() if k not in ignore_fields}
        expected_filtered = {k: v for k, v in expected.items() if k not in ignore_fields}
        
        # 检查所有预期字段是否存在于实际输出中
        for key, expected_value in expected_filtered.items():
            if key not in actual_filtered:
                return False
            
            actual_value = actual_filtered[key]
            
            # 如果值是字典，递归比较
            if isinstance(expected_value, dict) and isinstance(actual_value, dict):
                if not self._compare_fields(actual_value, expected_value, ignore_fields):
                    return False
            # 如果值是列表，检查是否包含相同元素
            elif isinstance(expected_value, list) and isinstance(actual_value, list):
                if len(expected_value) != len(actual_value):
                    return False
                # 简单比较（可以改进为更复杂的匹配逻辑）
                for ev, av in zip(expected_value, actual_value):
                    if isinstance(ev, dict) and isinstance(av, dict):
                        if not self._compare_fields(av, ev, ignore_fields):
                            return False
                    elif ev != av:
                        return False
            # 其他情况直接比较
            else:
                if actual_value != expected_value:
                    return False
        
        return True
