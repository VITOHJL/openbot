"""Mode C: Test Case Generation - 为能力/Workflow 生成测试用例."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from openbot.infra.capability_registry import CapabilityRegistry
from openbot.infra.test_case_store import TestCaseStore
from openbot.providers.base import LLMProvider, LLMResponse
from openbot.schemas.test_case_spec import TestCaseSpec, TestCaseType, ToleranceSpec


class ModeCTestGeneration:
    """模式 C: 为能力/Workflow 生成测试用例。
    
    基于能力定义，使用 LLM 设计测试用例矩阵。
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        capability_registry: CapabilityRegistry,
        test_case_store: TestCaseStore,
        model: str,
        temperature: float = 0.7,
    ) -> None:
        self._provider = provider
        self._cap_reg = capability_registry
        self._test_store = test_case_store
        self._model = model
        self._temperature = temperature

    async def generate_test_cases(
        self,
        capability_name: str,
        test_types: list[Literal["normal", "boundary", "error", "extreme"]],
    ) -> list[TestCaseSpec]:
        """为能力生成测试用例。
        
        Args:
            capability_name: 能力名称
            test_types: 要生成的测试类型列表
        
        Returns:
            TestCaseSpec 列表
        """
        # 获取能力定义
        capability = self._cap_reg.get(capability_name)
        if not capability:
            raise ValueError(f"Capability not found: {capability_name}")
        
        # 获取现有测试用例（如果有）
        existing_tests = self._test_store.get_by_capability(capability_name)
        
        # 构建提示词
        prompt = self._build_prompt(capability, existing_tests, test_types)
        
        # 调用 LLM
        messages = [
            {"role": "system", "content": self._get_system_prompt()},
            {"role": "user", "content": prompt},
        ]
        
        response = await self._provider.chat(
            messages=messages,
            model=self._model,
            temperature=self._temperature,
            max_tokens=4096,
        )
        
        # 解析 LLM 响应为 TestCaseSpec 列表
        test_cases = self._parse_response(response, capability_name, test_types)
        return test_cases

    def _get_system_prompt(self) -> str:
        """获取系统提示词。"""
        return """你是一个测试用例设计专家。你的职责是为能力/工作流设计全面的测试用例。

要求：
1. 设计测试用例矩阵，覆盖正常、边界、异常、极端情况
2. 每个测试用例应该包含明确的输入和预期输出
3. 考虑容差设置（哪些字段可以忽略，是否需要精确匹配）
4. 输出必须是有效的 JSON 格式，符合 TestCaseSpec Schema

测试类型说明：
- normal: 正常情况测试
- boundary: 边界值测试
- error: 错误情况测试
- extreme: 极端情况测试

输出格式：
[
  {
    "test_id": "test_xxx",
    "capability": "能力名称",
    "type": "normal|boundary|error|extreme",
    "input": {...},
    "expected_output": {...},
    "tolerance": {
      "exact_match": false,
      "fields_to_ignore": ["timestamp"]
    }
  }
]"""

    def _build_prompt(
        self,
        capability: Any,
        existing_tests: list[TestCaseSpec],
        test_types: list[str],
    ) -> str:
        """构建用户提示词。"""
        from openbot.infra.capability_registry import Capability
        
        parts = []
        
        parts.append(f"能力名称: {capability.name}")
        parts.append(f"能力层级: {capability.level}")
        parts.append(f"能力描述: {capability.description}")
        parts.append(f"\n能力参数 Schema:")
        parts.append(json.dumps(capability.schema, ensure_ascii=False, indent=2))
        
        if capability.usage_guide:
            parts.append(f"\n使用指导:\n{capability.usage_guide}")
        
        if capability.examples:
            parts.append(f"\n使用示例:")
            for example in capability.examples:
                parts.append(json.dumps(example, ensure_ascii=False, indent=2))
        
        if existing_tests:
            parts.append(f"\n现有测试用例 ({len(existing_tests)} 个):")
            for test in existing_tests[:5]:  # 只显示前 5 个
                parts.append(f"- {test.test_id} ({test.type}): {test.input}")
        
        parts.append(f"\n请为上述能力生成以下类型的测试用例: {', '.join(test_types)}")
        
        return "\n".join(parts)

    def _parse_response(
        self,
        response: LLMResponse,
        capability_name: str,
        test_types: list[str],
    ) -> list[TestCaseSpec]:
        """解析 LLM 响应为 TestCaseSpec 列表。"""
        content = response.content.strip()
        
        # 尝试提取 JSON（可能包含 markdown 代码块）
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            content = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            content = content[start:end].strip()
        
        try:
            data = json.loads(content)
            if not isinstance(data, list):
                data = [data]
        except json.JSONDecodeError:
            # 如果解析失败，返回空列表
            return []
        
        # 验证并转换数据
        test_cases = []
        for test_data in data:
            test_id = test_data.get("test_id", f"test_{uuid.uuid4().hex[:8]}")
            test_type = test_data.get("type", "normal")
            if test_type not in ["normal", "boundary", "error", "extreme"]:
                test_type = "normal"
            
            tolerance_data = test_data.get("tolerance", {})
            tolerance = ToleranceSpec(
                exact_match=tolerance_data.get("exact_match", False),
                fields_to_ignore=tolerance_data.get("fields_to_ignore", []),
            )
            
            test_case = TestCaseSpec(
                test_id=test_id,
                capability=capability_name,
                type=test_type,
                input=test_data.get("input", {}),
                expected_output=test_data.get("expected_output", {}),
                tolerance=tolerance,
                created_at=datetime.utcnow(),
            )
            test_cases.append(test_case)
        
        return test_cases
