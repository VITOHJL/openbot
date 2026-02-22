"""
LogService for openbot.

负责记录 ExecutionTrace，集成 SQLite 数据库持久化。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from openbot.infra.database import Database
from openbot.schemas.execution_trace import ExecutionStepModel, ExecutionTraceModel as ExecutionTrace


class LogService:
    """LogService 实现，支持内存缓存和 SQLite 持久化。

    运行时使用内存缓存提高性能，任务结束时持久化到数据库。
    """

    def __init__(self, database: Database | None = None) -> None:
        """初始化 LogService。
        
        Args:
            database: Database 实例，如果为 None 则自动创建。
        """
        self._db = database or Database()
        self._traces: dict[str, ExecutionTrace] = {}  # 内存缓存

    def start_trace(self, trace_id: str, task: str) -> None:
        """开始记录执行轨迹"""
        self._traces[trace_id] = ExecutionTrace(trace_id=trace_id, task=task)

    def log_step(self, trace_id: str, step: dict[str, Any]) -> None:
        """记录执行步骤"""
        trace = self._traces.get(trace_id)
        if not trace:
            return
        trace.steps.append(ExecutionStepModel(**step))

    def log_decision(self, trace_id: str, decision: dict[str, Any]) -> None:
        """占位：可将 LLM 决策单独记录，目前合并在步骤里。"""
        _ = (trace_id, decision)

    def finish_trace(self, trace_id: str, status: str, final_result: str) -> None:
        """完成执行轨迹记录，并持久化到数据库"""
        trace = self._traces.get(trace_id)
        if not trace:
            return
        trace.status = status
        trace.final_result = final_result
        trace.ended_at = datetime.utcnow()
        
        # 持久化到数据库（失败时仅记录日志，不抛出异常，避免影响任务结果返回）
        try:
            self._db.save_execution_trace(trace)
        except Exception as e:
            logger.warning(
                f"Failed to persist execution trace {trace_id}: {e}. "
                "Trace remains in memory cache."
            )

    def get_trace(self, trace_id: str) -> ExecutionTrace | None:
        """获取执行轨迹，优先从内存缓存读取，否则从数据库读取"""
        # 先查内存缓存
        if trace_id in self._traces:
            return self._traces[trace_id]
        
        # 从数据库读取
        trace = self._db.get_execution_trace(trace_id)
        if trace:
            # 加载到内存缓存
            self._traces[trace_id] = trace
        return trace

    def list_traces(self, filters: dict[str, Any] | None = None) -> list[ExecutionTrace]:
        """列出执行轨迹，从数据库读取"""
        status = filters.get("status") if filters else None
        limit = filters.get("limit", 100) if filters else 100
        return self._db.list_execution_traces(limit=limit, status=status)

