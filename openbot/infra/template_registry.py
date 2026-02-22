from __future__ import annotations

from typing import Any

from openbot.infra.database import Database
from openbot.schemas.workflow_spec import WorkflowSpec


class TemplateRegistry:
    """Workflow 模板库，集成 SQLite 数据库持久化。"""

    def __init__(self, database: Database | None = None) -> None:
        """初始化 TemplateRegistry。
        
        Args:
            database: Database 实例，如果为 None 则自动创建。
        """
        self._db = database or Database()
        self._workflows: dict[str, WorkflowSpec] = {}  # 内存缓存

    def register(self, workflow: WorkflowSpec) -> None:
        """注册工作流模板，同时保存到数据库和内存缓存"""
        self._workflows[workflow.workflow_id] = workflow
        self._db.save_workflow_template(workflow)

    def get(self, workflow_id: str) -> WorkflowSpec | None:
        """获取工作流模板，优先从内存缓存读取，否则从数据库读取"""
        # 先查内存缓存
        if workflow_id in self._workflows:
            return self._workflows[workflow_id]
        
        # 从数据库读取
        workflow = self._db.get_workflow_template(workflow_id)
        if workflow:
            # 加载到内存缓存
            self._workflows[workflow_id] = workflow
        return workflow

    def list_all(self) -> list[WorkflowSpec]:
        """列出所有工作流模板，从数据库读取"""
        workflows = self._db.list_workflow_templates()
        # 更新内存缓存
        for workflow in workflows:
            self._workflows[workflow.workflow_id] = workflow
        return workflows

    def match(self, task: dict[str, Any]) -> WorkflowSpec | None:
        """占位：根据任务匹配合适的 Workflow。

        目前简单返回 None，后续可以基于 task_type / 标签等实现真正匹配。
        """
        _ = task
        return None

