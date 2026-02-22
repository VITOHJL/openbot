"""Mode A: Task Planning - 任务拆解 Plan 设计."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from openbot.infra.capability_registry import CapabilityRegistry
from openbot.providers.base import LLMProvider, LLMResponse
from openbot.schemas.plan_spec import PlanSpec, PlanStep


class ModeATaskPlan:
    """模式 A: 任务拆解 Plan 设计。
    
    基于能力清单和历史案例，使用 LLM 拆解任务为执行计划。
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        capability_registry: CapabilityRegistry,
        model: str,
        temperature: float = 0.7,
    ) -> None:
        self._provider = provider
        self._cap_reg = capability_registry
        self._model = model
        self._temperature = temperature

    async def generate_plan(
        self,
        task: str,
        context: dict | None = None,
    ) -> PlanSpec:
        """生成任务执行计划。
        
        Args:
            task: 任务描述
            context: 可选上下文信息
        
        Returns:
            PlanSpec 对象
        """
        # 获取能力清单（轻量信息）
        capability_list = self._cap_reg.get_for_llm(include_details=False)
        
        # 构建提示词
        prompt = self._build_prompt(task, capability_list, context)
        
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
        
        # 解析 LLM 响应为 PlanSpec
        plan = self._parse_response(response, task)
        return plan

    def _get_system_prompt(self) -> str:
        """获取系统提示词。"""
        return """你是一个任务规划专家。你的职责是将用户任务拆解为可执行的步骤计划。

要求：
1. 只能使用提供的能力清单中的能力，不能编造
2. 每个步骤应该明确指定使用的能力名称和能力层级（atomic/skill/workflow）
3. 步骤之间可以有依赖关系
4. 优先使用 Workflow 层能力，如果合适的话
5. 输出必须是有效的 JSON 格式，符合 PlanSpec Schema

输出格式：
{
  "plan_id": "plan_xxx",
  "task": "任务描述",
  "steps": [
    {
      "step_id": 1,
      "capability": "能力名称",
      "capability_level": "workflow|skill|atomic",
      "inputs": {...},
      "success_criteria": "成功标准",
      "dependencies": [],
      "optional": false
    }
  ]
}"""

    def _build_prompt(
        self,
        task: str,
        capability_list: list[dict],
        context: dict | None,
    ) -> str:
        """构建用户提示词。"""
        parts = []
        
        parts.append(f"任务：{task}\n")
        
        if context:
            parts.append(f"上下文信息：\n{json.dumps(context, ensure_ascii=False, indent=2)}\n")
        
        parts.append("\n可用能力清单：")
        for cap in capability_list:
            parts.append(f"- {cap['name']} ({cap['level']}): {cap['description']}")
        
        parts.append("\n请为上述任务生成执行计划。")
        
        return "\n".join(parts)

    def _parse_response(self, response: LLMResponse, task: str) -> PlanSpec:
        """解析 LLM 响应为 PlanSpec。"""
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
        except json.JSONDecodeError as e:
            # 如果解析失败，创建一个基本的计划
            return PlanSpec(
                plan_id=f"plan_{uuid.uuid4().hex[:8]}",
                task=task,
                created_at=datetime.utcnow(),
                steps=[],
            )
        
        # 验证并转换数据
        plan_id = data.get("plan_id", f"plan_{uuid.uuid4().hex[:8]}")
        steps_data = data.get("steps", [])
        
        steps = []
        for step_data in steps_data:
            step = PlanStep(
                step_id=step_data.get("step_id", len(steps) + 1),
                capability=step_data.get("capability", ""),
                capability_level=step_data.get("capability_level", "atomic"),
                inputs=step_data.get("inputs", {}),
                success_criteria=step_data.get("success_criteria", ""),
                dependencies=step_data.get("dependencies", []),
                optional=step_data.get("optional", False),
            )
            steps.append(step)
        
        return PlanSpec(
            plan_id=plan_id,
            task=task,
            created_at=datetime.utcnow(),
            steps=steps,
        )
