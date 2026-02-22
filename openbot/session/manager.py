from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Session:
    key: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
            **kwargs,
        }
        self.messages.append(msg)
        self.updated_at = datetime.utcnow()

    def get_history(self, max_messages: int = 100) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in self.messages[-max_messages:]:
            entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in m:
                    entry[k] = m[k]
            out.append(entry)
        return out


class SessionManager:
    """简化版会话管理，学习 nanobot 精华并加入 Session 上下文接口。"""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.sessions_dir = (self.workspace / "sessions")
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Session] = {}

    def _get_session_path(self, key: str) -> Path:
        safe_key = key.replace(":", "_")
        return self.sessions_dir / f"{safe_key}.jsonl"

    def get_or_create(self, key: str) -> Session:
        if key in self._cache:
            return self._cache[key]
        session = self._load(key) or Session(key=key)
        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        path = self._get_session_path(key)
        if not path.exists():
            return None
        messages: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {}
        created_at: datetime | None = None
        last_consolidated = 0
        try:
            # 优先尝试 UTF-8 编码
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        ca = data.get("created_at")
                        created_at = datetime.fromisoformat(ca) if ca else None
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)
        except (UnicodeDecodeError, UnicodeError):
            # 如果 UTF-8 读取失败，尝试用 errors='replace' 容错读取
            try:
                with path.open(encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            if data.get("_type") == "metadata":
                                metadata = data.get("metadata", {})
                                ca = data.get("created_at")
                                created_at = datetime.fromisoformat(ca) if ca else None
                                last_consolidated = data.get("last_consolidated", 0)
                            else:
                                messages.append(data)
                        except json.JSONDecodeError:
                            # 跳过无效的 JSON 行
                            continue
            except Exception:
                # 如果还是失败，返回 None，让系统创建新会话
                return None
        except Exception:
            # 其他异常（如 JSON 解析错误），返回 None
            return None
        return Session(
            key=key,
            messages=messages,
            created_at=created_at or datetime.utcnow(),
            metadata=metadata,
            last_consolidated=last_consolidated,
        )

    def save(self, session: Session) -> None:
        path = self._get_session_path(session.key)
        with path.open("w", encoding="utf-8") as f:
            meta_line = {
                "_type": "metadata",
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_consolidated": session.last_consolidated,
            }
            f.write(json.dumps(meta_line, ensure_ascii=False) + "\n")
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self._cache[session.key] = session

    def get_context_for_task_understanding(self, session: Session) -> dict[str, Any]:
        """获取用于理解任务的 Session 上下文（占位实现）。"""
        # 后续可以加入长期记忆、用户偏好、项目上下文等
        history = session.get_history(max_messages=20)
        return {
            "user_history": history,
            "long_term_memory": "",
            "project_context": {},
            "user_preferences": {},
        }

    def update_context(self, session: Session, new_info: dict[str, Any]) -> None:
        """更新 Session 上下文（简单合并到 metadata）。"""
        session.metadata.update(new_info)
        session.updated_at = datetime.utcnow()
        self.save(session)

