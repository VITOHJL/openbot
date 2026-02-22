from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Capability:
    name: str
    description: str
    level: str  # "atomic" | "skill" | "workflow"
    schema: dict
    usage_guide: str | None = None
    examples: list[dict[str, Any]] | None = None

    def to_summary_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "level": self.level}

    def to_full_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "level": self.level,
            "schema": self.schema,
            "usage_guide": self.usage_guide,
            "examples": self.examples,
        }


class CapabilityRegistry:
    """简化版能力注册表，支持渐进式加载给 LLM。"""

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def list_all(self) -> list[Capability]:
        return list(self._capabilities.values())

    def get_for_llm(self, include_details: bool = False) -> list[dict[str, Any]]:
        """获取用于 LLM 的工具列表。
        
        Args:
            include_details: 如果为 True，返回完整的工具定义（用于工具调用）；
                           如果为 False，返回摘要信息（用于提示词）。
        
        Returns:
            工具列表，格式符合 OpenAI 工具调用规范：
            [
                {
                    "type": "function",
                    "function": {
                        "name": "...",
                        "description": "...",
                        "parameters": {...}  # JSON Schema
                    }
                }
            ]
        """
        if include_details:
            # 返回完整的 OpenAI 格式工具定义
            tools = []
            for cap in self._capabilities.values():
                tool = {
                    "type": "function",
                    "function": {
                        "name": cap.name,
                        "description": cap.description,
                        "parameters": cap.schema,  # 应该是 JSON Schema 格式
                    }
                }
                tools.append(tool)
            return tools
        else:
            # 返回摘要信息（用于提示词，不需要完整格式）
            return [cap.to_summary_dict() for cap in self._capabilities.values()]

