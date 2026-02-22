"""Memory system for persistent agent memory."""

from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists."""
    path.mkdir(parents=True, exist_ok=True)
    return path


class MemoryStore:
    """Two-layer memory: MEMORY.md (long-term facts) + HISTORY.md (grep-searchable log)."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def get_memory_context(self) -> str:
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""
    
    def extract_key_facts(self, execution_trace: Any) -> dict:
        """
        从执行轨迹中提取关键事实（可以由编排 Agent 调用）
        
        Args:
            execution_trace: ExecutionTrace 对象
        
        Returns:
            结构化关键事实字典
        """
        # TODO: 实现智能提取逻辑
        return {}
    
    def append_execution_summary(self, trace: Any) -> None:
        """
        将执行摘要追加到 HISTORY.md（可搜索）
        
        格式：[时间] 任务类型: 关键步骤摘要
        """
        from datetime import datetime
        summary = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {trace.task}: {len(trace.steps)} steps"
        self.append_history(summary)
