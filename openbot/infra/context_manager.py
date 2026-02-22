"""
ContextManager for openbot.

管理「瘦执行上下文」的占位实现，按 SPEC 包含四类信息：
- 精简任务信息（目标/约束/格式）
- 极简步骤历史（序号/动作/结果摘要）
- 结构化环境状态（JSON/Key-Value）
- 最近 3–5 轮工具 I/O 摘要
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionContext:
    task: dict[str, Any]
    step_history: list[dict[str, Any]] = field(default_factory=list)
    env_state: dict[str, Any] = field(default_factory=dict)
    recent_tool_io: list[dict[str, Any]] = field(default_factory=list)


class ContextManager:
    """瘦执行上下文管理（最小占位实现）。"""

    def __init__(self, *, history_window: int = 10, io_window: int = 5) -> None:
        self._history_window = history_window
        self._io_window = io_window
        self._ctx: ExecutionContext | None = None

    def init_context(self, task: dict[str, Any]) -> dict[str, Any]:
        """初始化执行上下文。"""
        self._ctx = ExecutionContext(task=task)
        return self.get_context()

    def update_step_history(self, step: dict[str, Any]) -> None:
        if not self._ctx:
            return
        self._ctx.step_history.append(step)
        if len(self._ctx.step_history) > self._history_window:
            # 旧历史后续可以写入 LogService，这里先简单丢弃
            self._ctx.step_history = self._ctx.step_history[-self._history_window :]

    def update_tool_io(self, io: dict[str, Any]) -> None:
        if not self._ctx:
            return
        self._ctx.recent_tool_io.append(io)
        if len(self._ctx.recent_tool_io) > self._io_window:
            self._ctx.recent_tool_io = self._ctx.recent_tool_io[-self._io_window :]

    def update_env_state(self, state: dict[str, Any]) -> None:
        if not self._ctx:
            return
        self._ctx.env_state.update(state)

    def get_context(self) -> dict[str, Any]:
        if not self._ctx:
            return {}
        return {
            "task": self._ctx.task,
            "step_history": list(self._ctx.step_history),
            "env_state": dict(self._ctx.env_state),
            "recent_tool_io": list(self._ctx.recent_tool_io),
        }

    def archive_old_history(self) -> None:
        """占位：未来将旧历史写入 LogService，这里暂不实现。"""
        return

