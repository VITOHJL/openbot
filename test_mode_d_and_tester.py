"""测试 Mode D 和 Tester Agent 功能."""

import asyncio
from pathlib import Path

from openbot.agent.planner import OrchestrationAgent
from openbot.agent.tester import TesterAgent
from openbot.config import load_config
from openbot.infra.capability_registry import CapabilityRegistry
from openbot.infra.database import Database
from openbot.infra.log_service import LogService
from openbot.infra.template_registry import TemplateRegistry
from openbot.infra.test_case_store import TestCaseStore
from openbot.providers.litellm_provider import LiteLLMProvider
from openbot.schemas.audit_report import AuditReport, AuditIssue, Evidence
from openbot.schemas.execution_trace import ExecutionTraceModel, ExecutionStepModel
from openbot.schemas.failure_experience import FailureExperience
from openbot.schemas.test_case_spec import TestCaseSpec, ToleranceSpec
from datetime import datetime


async def test_mode_d():
    """测试 Mode D 失败经验构建（仅测试数据结构和数据库操作）。"""
    print("=" * 60)
    print("测试 Mode D: 失败经验构建")
    print("=" * 60)
    
    # 初始化基础设施（不依赖 LLM）
    database = Database()
    log_service = LogService(database=database)
    
    # 创建一个模拟的执行轨迹和审计报告
    trace_id = "test_trace_123"
    trace = ExecutionTraceModel(
        trace_id=trace_id,
        task="测试任务：读取不存在的文件",
        started_at=datetime.utcnow(),
        ended_at=datetime.utcnow(),
        status="fail",
        steps=[
            ExecutionStepModel(
                step_id=1,
                capability="read_file",
                capability_level="atomic",
                inputs={"path": "/nonexistent/file.txt"},
                outputs={"error": "File not found", "status": "fail"},
                duration_ms=100,
                llm_decision="尝试读取文件",
            )
        ],
        final_result="任务失败：文件不存在",
    )
    
    # 保存执行轨迹
    database.save_execution_trace(trace)
    
    # 创建审计报告（失败情况）
    audit_report = AuditReport(
        audit_id="test_audit_123",
        execution_trace_id=trace_id,
        audited_at=datetime.utcnow(),
        verdict="fail",
        risk_level="high",
        issues=[
            AuditIssue(
                type="intermediate_error",
                description="文件不存在，但 Plan 假设文件存在",
                evidence=Evidence(
                    step_id=1,
                    actual_result="File not found",
                ),
            )
        ],
        template_candidate_eligible=False,
    )
    
    # 保存审计报告
    database.save_audit_report(audit_report)
    
    # 测试创建和保存失败经验（不调用 LLM）
    try:
        # 手动创建失败经验（模拟 Mode D 的输出）
        failure_exp = FailureExperience(
            failure_id="test_fail_123",
            task="测试任务：读取不存在的文件",
            plan_id="test_plan_123",
            trace_id=trace_id,
            failure_stage="execution",
            failure_step_id=1,
            failure_type="plan_assumption_wrong",
            summary="Plan 假设文件存在，但实际文件不存在",
            root_cause_hypothesis="Plan 在生成时没有验证文件是否存在",
            context_snippets=[
                "步骤 1: 尝试读取 /nonexistent/file.txt",
                "输出: File not found",
            ],
            lessons_learned="在执行文件操作前，应该先检查文件是否存在",
            created_at=datetime.utcnow(),
        )
        
        print(f"[OK] 失败经验创建成功:")
        print(f"  - Failure ID: {failure_exp.failure_id}")
        print(f"  - 失败阶段: {failure_exp.failure_stage}")
        print(f"  - 失败类型: {failure_exp.failure_type}")
        print(f"  - 摘要: {failure_exp.summary}")
        print(f"  - 根因假设: {failure_exp.root_cause_hypothesis}")
        print(f"  - 经验教训: {failure_exp.lessons_learned}")
        
        # 保存到数据库
        database.save_failure_experience(failure_exp)
        print(f"  - [OK] 已保存到数据库")
        
        # 验证可以从数据库读取
        retrieved = database.get_failure_experience(failure_exp.failure_id)
        if retrieved:
            print(f"  - [OK] 从数据库读取成功")
            print(f"    - 验证数据完整性: {'[OK]' if retrieved.task == failure_exp.task else '[FAIL]'}")
        else:
            print(f"  - [FAIL] 从数据库读取失败")
        
        # 测试列表查询
        failures = database.list_failure_experiences(limit=10)
        print(f"  - 数据库中共有 {len(failures)} 条失败经验")
        
        # 测试过滤查询
        failures_by_type = database.list_failure_experiences(
            limit=10,
            failure_type="plan_assumption_wrong"
        )
        print(f"  - 按类型过滤: {len(failures_by_type)} 条")
        
    except Exception as e:
        print(f"[FAIL] Mode D 测试失败: {e}")
        import traceback
        traceback.print_exc()


async def test_tester_agent():
    """测试 Tester Agent。"""
    print("\n" + "=" * 60)
    print("测试 Tester Agent: 测试用例执行")
    print("=" * 60)
    
    # 初始化基础设施
    config = load_config()
    database = Database()
    cap_reg = CapabilityRegistry()
    test_case_store = TestCaseStore(database=database)
    
    tester = TesterAgent(
        capability_registry=cap_reg,
        test_case_store=test_case_store,
    )
    
    # 创建一个测试用例
    test_case = TestCaseSpec(
        test_id="test_echo_1",
        capability="echo",
        type="normal",
        input={"text": "Hello, World!"},
        expected_output={"output": "Hello, World!", "status": "success"},
        tolerance=ToleranceSpec(
            exact_match=False,
            fields_to_ignore=["timestamp"],
        ),
        created_at=datetime.utcnow(),
    )
    
    # 保存测试用例
    test_case_store.add(test_case)
    print(f"[OK] 测试用例已创建: {test_case.test_id}")
    
    # 注意：实际执行需要 ExecutionAgent，这里只测试结构
    print(f"  - 测试用例结构验证通过")
    print(f"  - 测试用例已保存到数据库")
    
    # 验证可以从数据库读取
    cases = test_case_store.get_by_capability("echo")
    print(f"  - 从数据库读取到 {len(cases)} 个测试用例")
    
    # 测试输出比较逻辑
    actual = {"output": "Hello, World!", "status": "success", "timestamp": "2024-01-01"}
    expected = {"output": "Hello, World!", "status": "success"}
    tolerance = ToleranceSpec(exact_match=False, fields_to_ignore=["timestamp"])
    
    passed = tester._compare_outputs(actual, expected, tolerance)
    print(f"  - 输出比较测试: {'[PASS]' if passed else '[FAIL]'}")


async def main():
    """主函数。"""
    print("开始测试 Mode D 和 Tester Agent...\n")
    
    await test_mode_d()
    await test_tester_agent()
    
    print("\n" + "=" * 60)
    print("所有测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
  