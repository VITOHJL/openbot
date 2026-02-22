"""
SQLite 数据库服务，统一管理所有持久化数据。

按照 SPEC.md 7.3 节实现。
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

# 写操作重试配置：database is locked 时重试
_DB_WRITE_MAX_RETRIES = 8
_DB_WRITE_RETRY_DELAY = 0.5  # 秒，指数退避

from openbot.config import load_config
from openbot.schemas.audit_report import AuditIssue, AuditReport
from openbot.schemas.execution_trace import ExecutionStepModel, ExecutionTraceModel
from openbot.schemas.failure_experience import FailureExperience
from openbot.schemas.plan_spec import PlanSpec, PlanStep
from openbot.schemas.test_case_spec import TestCaseSpec, ToleranceSpec
from openbot.schemas.workflow_spec import WorkflowSpec, WorkflowStepSpec


class Database:
    """SQLite 数据库服务，统一管理所有持久化数据"""

    def __init__(self, db_path: Path | None = None) -> None:
        """初始化数据库，若 db_path 为 None 则使用 workspace/openbot.db"""
        if db_path is None:
            config = load_config()
            workspace = config.workspace_path
            workspace.mkdir(parents=True, exist_ok=True)
            db_path = workspace / "openbot.db"
        
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接
        
        启用 WAL mode 以支持并发读取，设置 timeout 和 busy_timeout 以处理锁冲突。
        """
        conn = sqlite3.connect(str(self.db_path), timeout=60.0)  # 60秒连接超时
        conn.row_factory = sqlite3.Row  # 使结果可通过列名访问
        
        # 先设置 busy_timeout：等待其他连接释放锁（15秒），而不是立即失败
        conn.execute("PRAGMA busy_timeout = 15000;")
        
        # 启用 WAL mode：支持并发读取，写入更高效，减少锁冲突
        # 如果数据库已被其他连接以 DELETE mode 打开，此操作可能失败，忽略即可
        try:
            result = conn.execute("PRAGMA journal_mode=WAL;").fetchone()
            # 如果返回的不是 'wal'，说明切换失败（可能是其他连接在使用）
            if result and result[0] != 'wal':
                # 数据库可能被其他连接锁定，继续使用当前 mode
                pass
        except sqlite3.OperationalError:
            # 如果设置 WAL mode 失败（数据库被锁），忽略错误，继续使用当前 mode
            pass
        
        return conn

    def _init_schema(self) -> None:
        """初始化/迁移数据库表结构"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # 1. 执行轨迹表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS execution_traces (
                    trace_id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT,
                    final_result TEXT,
                    steps_json TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_traces_started_at ON execution_traces(started_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_traces_status ON execution_traces(status)")
            
            # 2. 审计报告表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_reports (
                    audit_id TEXT PRIMARY KEY,
                    execution_trace_id TEXT NOT NULL,
                    audited_at TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    issues_json TEXT NOT NULL,
                    template_candidate_eligible INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (execution_trace_id) REFERENCES execution_traces(trace_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audits_trace_id ON audit_reports(execution_trace_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audits_verdict ON audit_reports(verdict)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audits_audited_at ON audit_reports(audited_at)")
            
            # 3. 工作流模板表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workflow_templates (
                    workflow_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    source_trace_id TEXT,
                    steps_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_workflows_name ON workflow_templates(name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_workflows_source_trace ON workflow_templates(source_trace_id)")
            
            # 4. 测试用例表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS test_cases (
                    test_id TEXT PRIMARY KEY,
                    capability TEXT NOT NULL,
                    type TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    expected_output_json TEXT NOT NULL,
                    tolerance_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_test_cases_capability ON test_cases(capability)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_test_cases_type ON test_cases(type)")
            
            # 5. 计划表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_plans_created_at ON plans(created_at)")
            
            # 6. 失败经验表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS failure_experiences (
                    failure_id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    plan_id TEXT,
                    trace_id TEXT NOT NULL,
                    failure_stage TEXT NOT NULL,
                    failure_step_id INTEGER,
                    failure_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    root_cause_hypothesis TEXT NOT NULL,
                    context_snippets_json TEXT NOT NULL,
                    lessons_learned TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (trace_id) REFERENCES execution_traces(trace_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_failures_trace_id ON failure_experiences(trace_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_failures_task ON failure_experiences(task)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_failures_type ON failure_experiences(failure_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_failures_stage ON failure_experiences(failure_stage)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_failures_created_at ON failure_experiences(created_at)")
            
            conn.commit()
        finally:
            conn.close()

    def _write_with_retry(self, write_fn) -> None:
        """对写操作进行重试，处理 database is locked"""
        last_err = None
        for attempt in range(_DB_WRITE_MAX_RETRIES):
            try:
                write_fn()
                return
            except sqlite3.OperationalError as e:
                last_err = e
                if "database is locked" in str(e).lower() or "locked" in str(e).lower():
                    if attempt < _DB_WRITE_MAX_RETRIES - 1:
                        time.sleep(_DB_WRITE_RETRY_DELAY * (attempt + 1))
                        continue
                raise
        if last_err:
            raise last_err

    # ========== ExecutionTrace ==========

    def save_execution_trace(self, trace: ExecutionTraceModel) -> None:
        """保存执行轨迹（带重试）"""
        def _do_write():
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO execution_traces
                    (trace_id, task, started_at, ended_at, status, final_result, steps_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    trace.trace_id,
                    trace.task,
                    trace.started_at.isoformat() if trace.started_at else None,
                    trace.ended_at.isoformat() if trace.ended_at else None,
                    trace.status,
                    trace.final_result,
                    json.dumps([step.model_dump() for step in trace.steps], ensure_ascii=False),
                ))
                conn.commit()
            finally:
                conn.close()

        self._write_with_retry(_do_write)

    def get_execution_trace(self, trace_id: str) -> ExecutionTraceModel | None:
        """获取执行轨迹"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM execution_traces WHERE trace_id = ?", (trace_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            steps_data = json.loads(row["steps_json"])
            steps = [ExecutionStepModel(**s) for s in steps_data]
            
            return ExecutionTraceModel(
                trace_id=row["trace_id"],
                task=row["task"],
                started_at=datetime.fromisoformat(row["started_at"]),
                ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
                status=row["status"],
                final_result=row["final_result"],
                steps=steps,
            )
        finally:
            conn.close()

    def list_execution_traces(
        self, limit: int = 100, status: str | None = None
    ) -> list[ExecutionTraceModel]:
        """列出执行轨迹"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if status:
                cursor.execute(
                    "SELECT * FROM execution_traces WHERE status = ? ORDER BY started_at DESC LIMIT ?",
                    (status, limit),
                )
            else:
                cursor.execute("SELECT * FROM execution_traces ORDER BY started_at DESC LIMIT ?", (limit,))
            
            traces = []
            for row in cursor.fetchall():
                steps_data = json.loads(row["steps_json"])
                steps = [ExecutionStepModel(**s) for s in steps_data]
                
                traces.append(
                    ExecutionTraceModel(
                        trace_id=row["trace_id"],
                        task=row["task"],
                        started_at=datetime.fromisoformat(row["started_at"]),
                        ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
                        status=row["status"],
                        final_result=row["final_result"],
                        steps=steps,
                    )
                )
            return traces
        finally:
            conn.close()

    # ========== AuditReport ==========

    def save_audit_report(self, report: AuditReport) -> None:
        """保存审计报告（带重试）"""
        def _do_write():
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO audit_reports
                    (audit_id, execution_trace_id, audited_at, verdict, risk_level, issues_json, template_candidate_eligible)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    report.audit_id,
                    report.execution_trace_id,
                    report.audited_at.isoformat(),
                    report.verdict,
                    report.risk_level,
                    json.dumps([issue.model_dump() for issue in report.issues], ensure_ascii=False),
                    1 if report.template_candidate_eligible else 0,
                ))
                conn.commit()
            finally:
                conn.close()

        self._write_with_retry(_do_write)

    def get_audit_report(self, audit_id: str) -> AuditReport | None:
        """获取审计报告"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM audit_reports WHERE audit_id = ?", (audit_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            issues_data = json.loads(row["issues_json"])
            issues = [AuditIssue(**i) for i in issues_data]
            
            return AuditReport(
                audit_id=row["audit_id"],
                execution_trace_id=row["execution_trace_id"],
                audited_at=datetime.fromisoformat(row["audited_at"]),
                verdict=row["verdict"],
                risk_level=row["risk_level"],
                issues=issues,
                template_candidate_eligible=bool(row["template_candidate_eligible"]),
            )
        finally:
            conn.close()

    def list_audit_reports(
        self, trace_id: str | None = None, verdict: str | None = None
    ) -> list[AuditReport]:
        """列出审计报告"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            conditions = []
            params = []
            
            if trace_id:
                conditions.append("execution_trace_id = ?")
                params.append(trace_id)
            if verdict:
                conditions.append("verdict = ?")
                params.append(verdict)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            cursor.execute(
                f"SELECT * FROM audit_reports WHERE {where_clause} ORDER BY audited_at DESC",
                params,
            )
            
            reports = []
            for row in cursor.fetchall():
                issues_data = json.loads(row["issues_json"])
                issues = [AuditIssue(**i) for i in issues_data]
                
                reports.append(
                    AuditReport(
                        audit_id=row["audit_id"],
                        execution_trace_id=row["execution_trace_id"],
                        audited_at=datetime.fromisoformat(row["audited_at"]),
                        verdict=row["verdict"],
                        risk_level=row["risk_level"],
                        issues=issues,
                        template_candidate_eligible=bool(row["template_candidate_eligible"]),
                    )
                )
            return reports
        finally:
            conn.close()

    # ========== WorkflowSpec ==========

    def save_workflow_template(self, workflow: WorkflowSpec) -> None:
        """保存工作流模板"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO workflow_templates
                (workflow_id, name, description, source_trace_id, steps_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                workflow.workflow_id,
                workflow.name,
                workflow.description,
                workflow.source_trace_id,
                json.dumps([step.model_dump() for step in workflow.steps], ensure_ascii=False),
                workflow.created_at.isoformat(),
            ))
            conn.commit()
        finally:
            conn.close()

    def get_workflow_template(self, workflow_id: str) -> WorkflowSpec | None:
        """获取工作流模板"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workflow_templates WHERE workflow_id = ?", (workflow_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            steps_data = json.loads(row["steps_json"])
            steps = [WorkflowStepSpec(**s) for s in steps_data]
            
            return WorkflowSpec(
                workflow_id=row["workflow_id"],
                name=row["name"],
                description=row["description"] or "",
                source_trace_id=row["source_trace_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                steps=steps,
            )
        finally:
            conn.close()

    def list_workflow_templates(self) -> list[WorkflowSpec]:
        """列出所有工作流模板"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workflow_templates ORDER BY created_at DESC")
            
            workflows = []
            for row in cursor.fetchall():
                steps_data = json.loads(row["steps_json"])
                steps = [WorkflowStepSpec(**s) for s in steps_data]
                
                workflows.append(
                    WorkflowSpec(
                        workflow_id=row["workflow_id"],
                        name=row["name"],
                        description=row["description"] or "",
                        source_trace_id=row["source_trace_id"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        steps=steps,
                    )
                )
            return workflows
        finally:
            conn.close()

    # ========== TestCaseSpec ==========

    def save_test_case(self, test_case: TestCaseSpec) -> None:
        """保存测试用例"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO test_cases
                (test_id, capability, type, input_json, expected_output_json, tolerance_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                test_case.test_id,
                test_case.capability,
                test_case.type,
                json.dumps(test_case.input, ensure_ascii=False),
                json.dumps(test_case.expected_output, ensure_ascii=False),
                json.dumps(test_case.tolerance.model_dump(), ensure_ascii=False),
                test_case.created_at.isoformat(),
            ))
            conn.commit()
        finally:
            conn.close()

    def get_test_case(self, test_id: str) -> TestCaseSpec | None:
        """获取测试用例"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM test_cases WHERE test_id = ?", (test_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            tolerance_data = json.loads(row["tolerance_json"])
            
            return TestCaseSpec(
                test_id=row["test_id"],
                capability=row["capability"],
                type=row["type"],
                input=json.loads(row["input_json"]),
                expected_output=json.loads(row["expected_output_json"]),
                tolerance=ToleranceSpec(**tolerance_data),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
        finally:
            conn.close()

    def list_test_cases(self, capability: str | None = None) -> list[TestCaseSpec]:
        """列出测试用例"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if capability:
                cursor.execute("SELECT * FROM test_cases WHERE capability = ? ORDER BY created_at DESC", (capability,))
            else:
                cursor.execute("SELECT * FROM test_cases ORDER BY created_at DESC")
            
            cases = []
            for row in cursor.fetchall():
                tolerance_data = json.loads(row["tolerance_json"])
                
                cases.append(
                    TestCaseSpec(
                        test_id=row["test_id"],
                        capability=row["capability"],
                        type=row["type"],
                        input=json.loads(row["input_json"]),
                        expected_output=json.loads(row["expected_output_json"]),
                        tolerance=ToleranceSpec(**tolerance_data),
                        created_at=datetime.fromisoformat(row["created_at"]),
                    )
                )
            return cases
        finally:
            conn.close()

    # ========== PlanSpec ==========

    def save_plan(self, plan: PlanSpec) -> None:
        """保存计划（包含 execution_mode 等完整字段）"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # 检查表结构是否需要更新（添加 execution_mode 等字段）
            cursor.execute("PRAGMA table_info(plans)")
            columns = [row[1] for row in cursor.fetchall()]
            
            # 如果表结构不包含新字段，先更新表结构
            if "execution_mode" not in columns:
                try:
                    cursor.execute("ALTER TABLE plans ADD COLUMN execution_mode TEXT")
                    cursor.execute("ALTER TABLE plans ADD COLUMN max_deviations INTEGER")
                    cursor.execute("ALTER TABLE plans ADD COLUMN deviation_log_required INTEGER")
                    conn.commit()
                except Exception:
                    # 如果字段已存在或其他错误，忽略
                    pass
            
            # 保存完整 PlanSpec（包含所有字段）
            cursor.execute("""
                INSERT OR REPLACE INTO plans
                (plan_id, task, steps_json, created_at, execution_mode, max_deviations, deviation_log_required)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                plan.plan_id,
                plan.task,
                json.dumps([step.model_dump() for step in plan.steps], ensure_ascii=False),
                plan.created_at.isoformat(),
                plan.execution_mode,
                plan.max_deviations,
                1 if plan.deviation_log_required else 0,
            ))
            conn.commit()
        finally:
            conn.close()

    def get_plan(self, plan_id: str) -> PlanSpec | None:
        """获取计划（包含 execution_mode 等完整字段）"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM plans WHERE plan_id = ?", (plan_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            steps_data = json.loads(row["steps_json"])
            steps = [PlanStep(**s) for s in steps_data]
            
            # 兼容旧数据（可能没有 execution_mode 字段）
            execution_mode = row.get("execution_mode", "strict")
            max_deviations = row.get("max_deviations", 0)
            deviation_log_required = bool(row.get("deviation_log_required", 1))
            
            return PlanSpec(
                plan_id=row["plan_id"],
                task=row["task"],
                created_at=datetime.fromisoformat(row["created_at"]),
                steps=steps,
                execution_mode=execution_mode,
                max_deviations=max_deviations,
                deviation_log_required=deviation_log_required,
            )
        finally:
            conn.close()

    # ========== FailureExperience ==========

    def save_failure_experience(self, failure: FailureExperience) -> None:
        """保存失败经验（带重试）"""
        def _do_write():
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO failure_experiences
                    (failure_id, task, plan_id, trace_id, failure_stage, failure_step_id,
                     failure_type, summary, root_cause_hypothesis, context_snippets_json,
                     lessons_learned, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    failure.failure_id,
                    failure.task,
                    failure.plan_id,
                    failure.trace_id,
                    failure.failure_stage,
                    failure.failure_step_id,
                    failure.failure_type,
                    failure.summary,
                    failure.root_cause_hypothesis,
                    json.dumps(failure.context_snippets, ensure_ascii=False),
                    failure.lessons_learned,
                    failure.created_at.isoformat(),
                ))
                conn.commit()
            finally:
                conn.close()

        self._write_with_retry(_do_write)

    def get_failure_experience(self, failure_id: str) -> FailureExperience | None:
        """获取失败经验"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM failure_experiences WHERE failure_id = ?", (failure_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            context_snippets = json.loads(row["context_snippets_json"])
            
            return FailureExperience(
                failure_id=row["failure_id"],
                task=row["task"],
                plan_id=row["plan_id"],
                trace_id=row["trace_id"],
                failure_stage=row["failure_stage"],
                failure_step_id=row["failure_step_id"],
                failure_type=row["failure_type"],
                summary=row["summary"],
                root_cause_hypothesis=row["root_cause_hypothesis"],
                context_snippets=context_snippets,
                lessons_learned=row["lessons_learned"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
        finally:
            conn.close()

    def list_failure_experiences(
        self,
        limit: int = 100,
        failure_type: str | None = None,
        failure_stage: str | None = None,
        task_pattern: str | None = None,
    ) -> list[FailureExperience]:
        """列出失败经验
        
        Args:
            limit: 返回数量限制
            failure_type: 过滤失败类型
            failure_stage: 过滤失败阶段
            task_pattern: 任务描述模式（LIKE 查询）
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            conditions = []
            params = []
            
            if failure_type:
                conditions.append("failure_type = ?")
                params.append(failure_type)
            if failure_stage:
                conditions.append("failure_stage = ?")
                params.append(failure_stage)
            if task_pattern:
                conditions.append("task LIKE ?")
                params.append(f"%{task_pattern}%")
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            query = f"SELECT * FROM failure_experiences WHERE {where_clause} ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            
            failures = []
            for row in cursor.fetchall():
                context_snippets = json.loads(row["context_snippets_json"])
                
                failures.append(
                    FailureExperience(
                        failure_id=row["failure_id"],
                        task=row["task"],
                        plan_id=row["plan_id"],
                        trace_id=row["trace_id"],
                        failure_stage=row["failure_stage"],
                        failure_step_id=row["failure_step_id"],
                        failure_type=row["failure_type"],
                        summary=row["summary"],
                        root_cause_hypothesis=row["root_cause_hypothesis"],
                        context_snippets=context_snippets,
                        lessons_learned=row["lessons_learned"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                    )
                )
            
            return failures
        finally:
            conn.close()
