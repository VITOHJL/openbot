"""
ContextBuilder for openbot.

负责构建两层上下文：
- Session 上下文：用于理解任务（用户历史、长期记忆等）
- 执行上下文：用于执行任务（瘦上下文，4 类信息）

按照 SPEC.md 5.6 实现两层上下文构建。
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from openbot.agent.memory import MemoryStore
from openbot.session.manager import Session, SessionManager


class ContextBuilder:
    """两层上下文构建器。

    按照 SPEC.md 实现：
    - Session 上下文：用于理解任务
    - 执行上下文：用于执行任务（瘦上下文）
    """

    def __init__(self, workspace: Path, session_manager: SessionManager) -> None:
        self.workspace = workspace
        self.session_manager = session_manager
        self.memory = MemoryStore(workspace)
        self.session_window = 50  # Session 历史窗口大小

    def build_system_prompt(
        self,
        session: Session,
        execution_context: dict[str, Any],
        capability_list: list[dict[str, Any]],
    ) -> str:
        """构建系统提示（两层上下文）。
        
        Args:
            session: 会话对象
            execution_context: 执行上下文（瘦上下文，4类信息）
            capability_list: 能力清单
        
        Returns:
            完整的系统提示
        """
        parts = []
        
        # 1. 身份和约束（固定）
        parts.append(self._get_identity())
        
        # 2. Session 上下文（用于理解任务）
        session_context = self.session_manager.get_context_for_task_understanding(session)
        parts.append(self._format_session_context(session_context))
        
        # 3. 执行上下文（瘦上下文，用于执行任务）
        parts.append(self._format_execution_context(execution_context))
        
        # 4. 能力清单
        parts.append(self._format_capability_list(capability_list))
        
        return "\n\n---\n\n".join(parts)

    def build_messages(
        self,
        session: Session,
        execution_context: dict[str, Any],
        current_message: str,
        capability_list: list[dict[str, Any]],
        media: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """构建完整的消息列表。
        
        Args:
            session: 会话对象
            execution_context: 执行上下文（瘦上下文）
            current_message: 当前用户消息
            capability_list: 能力清单
            media: 可选媒体文件列表
        
        Returns:
            消息列表（包含 system prompt + history + current message）
        """
        messages = []
        
        # System prompt
        system_prompt = self.build_system_prompt(session, execution_context, capability_list)
        messages.append({"role": "system", "content": system_prompt})
        
        # Session 历史（用于理解任务，但也要控制长度）
        session_history = session.get_history(max_messages=self.session_window)
        messages.extend(session_history)
        
        # 当前消息（支持媒体）
        user_content = self._build_user_content(current_message, media)
        messages.append({"role": "user", "content": user_content})
        
        return messages

    def _get_identity(self) -> str:
        """获取身份和约束信息。"""
        from datetime import datetime
        import platform
        import time as _time
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = _time.strftime("%Z") or "UTC"
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"
        
        return f"""# openbot

You are openbot, a single-agent AI assistant. You have access to tools that allow you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch web pages
- Control browsers
- Use MCP capabilities

## Current Time
{now} ({tz})

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Long-term memory: {workspace_path}/memory/MEMORY.md
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable)

## Important Rules
1. You can ONLY use capabilities from the provided capability list. Do not invent or call non-existent capabilities.
2. You must be honest about execution results. Do not fabricate success or hide failures.
3. All your decisions and tool calls are logged for auditing purposes.
4. When a task is completed successfully, the execution trace may be extracted as a candidate workflow template.

Always be helpful, accurate, and concise. Before calling tools, briefly tell the user what you're about to do."""

    def _format_session_context(self, session_context: dict[str, Any]) -> str:
        """格式化 Session 上下文。"""
        parts = []
        
        if session_context.get("long_term_memory"):
            parts.append(f"## Long-term Memory\n{session_context['long_term_memory']}")
        
        if session_context.get("user_preferences"):
            parts.append(f"## User Preferences\n{session_context['user_preferences']}")
        
        if session_context.get("project_context"):
            parts.append(f"## Project Context\n{session_context['project_context']}")
        
        return "\n\n".join(parts) if parts else ""

    def _format_execution_context(self, execution_context: dict[str, Any]) -> str:
        """格式化执行上下文（瘦上下文）。"""
        parts = []
        
        if execution_context.get("task"):
            task = execution_context["task"]
            parts.append(f"## Current Task\nGoal: {task.get('goal', 'N/A')}")
            if task.get("constraints"):
                parts.append(f"Constraints: {', '.join(task['constraints'])}")
        
        if execution_context.get("step_history"):
            parts.append("## Recent Steps")
            for step in execution_context["step_history"][-5:]:  # 只显示最近 5 步
                parts.append(f"- Step {step.get('step_id', '?')}: {step.get('action', 'N/A')} -> {step.get('result_summary', 'N/A')}")
        
        if execution_context.get("env_state"):
            parts.append(f"## Environment State\n{execution_context['env_state']}")
        
        return "\n\n".join(parts) if parts else ""

    def _format_capability_list(self, capability_list: list[dict[str, Any]]) -> str:
        """格式化能力清单。"""
        if not capability_list:
            return "## Available Capabilities\nNo capabilities available."
        
        parts = ["## Available Capabilities"]
        parts.append("You can use the following capabilities:")
        
        # 按层级分组
        by_level: dict[str, list[dict[str, Any]]] = {}
        for cap in capability_list:
            level = cap.get("level", "unknown")
            if level not in by_level:
                by_level[level] = []
            by_level[level].append(cap)
        
        for level in ["workflow", "skill", "atomic"]:
            if level in by_level:
                parts.append(f"\n### {level.upper()} Level:")
                for cap in by_level[level]:
                    parts.append(f"- {cap['name']}: {cap.get('description', 'No description')}")
        
        parts.append("\n\nIMPORTANT: You can ONLY use capabilities from this list. Do not invent or call non-existent capabilities.")
        
        return "\n".join(parts)

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """构建用户消息内容（支持图片等媒体）。"""
        if not media:
            return text
        
        # 处理图片（base64 编码）
        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if p.is_file() and mime and mime.startswith("image/"):
                b64 = base64.b64encode(p.read_bytes()).decode()
                images.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"}
                })
        
        if not images:
            return text
        return images + [{"type": "text", "text": text}]

