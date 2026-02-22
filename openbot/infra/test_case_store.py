from __future__ import annotations

from typing import Any

from openbot.infra.database import Database
from openbot.schemas.test_case_spec import TestCaseSpec


class TestResult(dict):
    """简单的测试结果占位结构。"""


class TestCaseStore:
    """测试用例存储，集成 SQLite 数据库持久化。"""

    def __init__(self, database: Database | None = None) -> None:
        """初始化 TestCaseStore。
        
        Args:
            database: Database 实例，如果为 None 则自动创建。
        """
        self._db = database or Database()
        self._cases: dict[str, list[TestCaseSpec]] = {}  # 内存缓存

    def add(self, test_case: TestCaseSpec) -> None:
        """添加测试用例，同时保存到数据库和内存缓存"""
        self._cases.setdefault(test_case.capability, []).append(test_case)
        self._db.save_test_case(test_case)

    def get_by_capability(self, capability: str) -> list[TestCaseSpec]:
        """根据能力名称获取测试用例，优先从内存缓存读取，否则从数据库读取"""
        # 先查内存缓存
        if capability in self._cases:
            return list(self._cases[capability])
        
        # 从数据库读取
        cases = self._db.list_test_cases(capability=capability)
        # 更新内存缓存
        self._cases[capability] = cases
        return cases

    def execute(self, test_case: TestCaseSpec) -> TestResult:
        """占位：真实实现会调用 ExecutionAgent 运行测试。

        这里先返回一个固定结构，方便后续接入。
        """
        _ = test_case
        return TestResult({"passed": False, "reason": "not implemented"})

