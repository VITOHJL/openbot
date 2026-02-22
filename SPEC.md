# tedbot 项目详细规范 (Specification)

## 版本信息

- **项目名称**: tedbot
- **版本**: 1.0.0
- **最后更新**: 2026-02-21
- **状态**: 设计阶段

---

## 一、项目概述

### 1.1 项目目标

tedbot 是一个**单 Agent 架构**的 AI 助手系统，核心设计理念：

- **轻量、可托管、稳定、低幻觉、可审计**
- **把确定性交给流程，把不确定性交给 AI**
- **能固化成流程的，绝不交给 AI 即兴发挥**
- **AI 只做人类无法提前写死的决策**

### 1.2 核心原则

1. **单执行 Agent**: 唯一在线执行者，所有工具调用都经过它
2. **瘦上下文 + 完整日志**: 上下文只存必要信息，完整行为记录在日志中
3. **三层能力栈**: Atomic/Skill/Workflow，LLM 只能调度已有能力
4. **Workflow 作为高阶工具**: 优先使用，但可偏离，需记录原因
5. **职责分离**: 编排负责设计，执行负责运行，审计负责监督
6. **结构化协议**: 所有 Agent 间通信使用严格 JSON Schema
7. **可审计可追溯**: 所有决策和调用都有日志，支持事后审计
8. **持续演进**: 成功执行 → 审计通过 → 模板抽取 → 人工审核 → 注册为 Workflow

### 1.3 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      tedbot 系统架构                          │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  执行Agent   │    │  编排Agent   │    │  审计Agent   │  │
│  │  (Runtime)   │    │  (Planner)   │    │  (Auditor)   │  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘  │
│         │                   │                    │          │
│         └───────────────────┼────────────────────┘          │
│                             │                               │
│  ┌──────────────────────────┼──────────────────────────┐   │
│  │        能力栈 (CapabilityRegistry)                   │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ Workflow │  │ Skill/   │  │ Atomic   │          │   │
│  │  │   层     │  │  MCP层   │  │   层     │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              基础设施层                                │   │
│  │  ContextManager | LogService | Database (SQLite)     │   │
│  │  TemplateRegistry | CapabilityRegistry | TestCaseStore│   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、Agent 详细设计规范

### 2.1 执行 Agent (Execution Agent)

#### 2.1.1 职责

- 唯一在线执行者，负责实际调用工具、记录日志、返回结果
- 接收「单个子任务」并在其范围内以 React 模式完成目标
- 不负责整体任务拆解与路线设计（由编排 Agent 负责）
- 所有能力调用必须经过 CapabilityRegistry 验证
- 所有行为必须记录到 LogService

#### 2.1.2 核心流程

**阶段 1: 子任务接收与初始化**

1. 接收来自编排 Agent 的「子任务指令」：
   - 主任务描述（只读，用于理解大方向，但不参与重规划）
   - 当前子任务目标 `subtask_goal`（必须）
   - 推荐完成方式：
     - `recommended_capability`
     - `inputs`（推荐初始参数）
   - 可选执行策略：
     - `execution_mode`（如 strict / flexible）
     - 内部重试/React 策略（由确定性代码控制）
2. 初始化瘦上下文（ContextManager）：
   - 写入 4 类信息（均以「当前子任务」为中心）：
     - 精简任务信息（主任务摘要 + 当前子任务目标）
     - 极简步骤历史（序号/动作/结果摘要，初始为空）
     - 结构化环境状态（JSON/Key-Value，初始为空）
     - 最近 3-5 轮工具 I/O（初始为空）
   - 设置滑动窗口：只保留最近几步，超长历史写入日志

**阶段 2: 子任务内部执行循环（React 模式）**

针对单个子任务，运行局部 React 循环（最多子任务级 `max_iterations` 次）：

1. **LLM 规划当前子任务的下一步**
   - 输入：
     - 当前瘦上下文（4 类信息）
     - 能力清单（来自 CapabilityRegistry）
     - 当前子任务目标 `subtask_goal`
     - 推荐完成方式（可作为提示，但非硬约束）
   - LLM 决策点：
     - 理解当前子任务进度
     - 决定下一步要调用的能力与参数草案
   - 约束：
     - 只能从能力清单中选择，不能编造能力

2. **能力解析与验证**
   - 从 CapabilityRegistry 中查找目标能力
   - 确定能力层级（Workflow/Skill/Atomic）
   - 若能力不存在 → 记录失败，并将错误写入日志

3. **参数构造**
   - 根据能力 schema 和当前上下文构造参数
   - 确定性映射 + 可选 LLM 补全文本字段
   - 参数校验（结构化 JSON Schema 校验）

4. **执行能力调用**
   - 调用能力（确定性执行）
   - 执行结果：
     - 成功：返回结果数据
     - 失败：返回错误信息

5. **更新上下文与日志**
   - 更新瘦上下文（步骤历史 + 最近工具 I/O + 环境状态）
   - 写入完整日志到 LogService（结构化 JSON）：
     - 每一步的 LLM 决策、能力调用、输入输出、耗时等

6. **结果校验（针对当前子任务）**
   - 确定性校验：
     - 返回码、结构校验
     - 与当前子任务的 `success_criteria`（若有）比对
   - 可选 LLM 评估：
     - 当前子任务是否已经达到目标

7. **子任务级终止决策**
   - 若判定当前子任务目标达成：
     - 结束子任务执行循环，返回成功状态
   - 若在预算内仍未完成：
     - 继续回到步骤 1（在子任务范围内 React）
   - 若明显不可完成 / 超出内部预算：
     - 结束子任务执行循环，返回失败状态

**阶段 3: 整体任务结束处理**

执行 Agent 仅负责将所有子任务执行过程汇总为 ExecutionTrace，并返回最终结果文本：

- **成功分支**：
  - 返回成功结果给用户
  - 完整 ExecutionTrace 写入数据库
- **失败分支**：
  - 返回失败结果 + 局限性说明给用户
  - 完整 ExecutionTrace 写入数据库

执行 Agent 不直接参与「工作流提取」或「失败经验构建」，只负责提供高质量轨迹给后续 Agent 使用。

#### 2.1.3 核心约束

- ✅ 只能调用 CapabilityRegistry 中存在的能力，不能编造
- ✅ 不能篡改执行结果，不能隐瞒失败
- ✅ 不能自主扩写无关逻辑，不能全程无约束自主规划
- ✅ 所有决策和调用必须记录到日志，供审计

#### 2.1.4 命令处理

执行 Agent 支持以下命令（在任务接收阶段处理）：

- `/new` - 开始新会话
  - 清空当前会话消息
  - 触发内存合并（可选）
  - 重置会话状态
- `/help` - 显示帮助信息
  - 显示可用命令列表
  - 显示系统使用说明
- `/audit <trace_id>` - 触发指定执行轨迹的审计（可选扩展）
- `/template <workflow_id>` - 查看指定 Workflow 模板信息（可选扩展）
- `/memory` - 查看长期记忆（可选扩展）

命令处理在任务规范化解析之前进行，命令不进入执行循环。

#### 2.1.5 实现文件

- `tedbot/agent/loop.py` - 主循环实现
- `tedbot/agent/context.py` - 上下文构建（两层上下文）
- `tedbot/infra/context_manager.py` - ContextManager 实现（执行上下文）
- `tedbot/infra/log_service.py` - LogService 实现

---

### 2.2 编排 Agent (Planner / Orchestration Agent)

#### 2.2.1 职责

- 任务拆解 Plan 设计（模式 A）
- 从成功执行日志抽象 Workflow（模式 B）
- 为能力/Workflow 生成测试用例（模式 C）
- 基于失败执行轨迹和审计结果构建「失败经验」（模式 D）

#### 2.2.2 模式 A: 任务拆解 Plan 设计

**触发时机**：用户提交新任务，或上游渠道请求一次完整的执行计划。

**输入**：
- 任务描述（规范化后）
- 能力清单（来自 CapabilityRegistry）
- Session 上下文（用于理解任务）
- 失败经验库摘要（可选，按任务类型筛选相关 FailureExperience，并以提示形式提供）

**处理流程**：
1. LLM 基于能力清单与失败经验，拆解任务为一组有依赖的子任务；
2. 对每个子任务：
   - 明确 `subtask_goal`（子任务要达到的目标状态）；
   - 给出推荐完成方式：
     - `recommended_capability`
     - 初始 `inputs`
   - 指定依赖关系、是否可选、执行模式（strict/flexible 等）；
   - 给出结构化 `success_criteria`；
3. 输出 PlanSpec（JSON）。

**输出**：`PlanSpec` JSON Schema（见 3.1），是后续执行 Agent 的「高层执行规范」。

**输出去向**：
- 写入 Database（plans 表）以便审计/回放；
- 按子任务粒度传递给执行 Agent（一次一个子任务）。

#### 2.2.3 模式 B: 从成功执行日志抽象 Workflow

**触发时机**：
- 审计 Agent 完成审计，且：
  - `verdict == "pass"` 且
  - `template_candidate_eligible == true`

**输入**：
- ExecutionTrace（来自 LogService / Database）
- AuditReport（来自审计 Agent）

**处理流程**：
1. 读取 ExecutionTrace；
2. 结合 AuditReport 中的 `workflow_extraction_notes`：
   - 跳过探索性、失败且已被纠正的步骤；
   - 跳过与业务无关的杂项操作；
3. 将剩余步骤按「业务逻辑顺序」抽象为 WorkflowStepSpec 列表；
4. 输出 CandidateWorkflowSpec（JSON）。

**输出**：`CandidateWorkflowSpec` JSON Schema（见 3.3）。

**输出去向**：
- 写入 TemplateRegistry 作为「候选工作流」；
- 提交测试 Agent 生成测试用例；
- 最终进入「待人工审批区」，人工批准后正式注册为 Workflow 能力。

#### 2.2.4 模式 C: 为能力/Workflow 生成测试用例

**触发时机**：
- 新工作流候选（CandidateWorkflowSpec）产出后；
- 新 Skill / 原子能力上线前或版本变更时；
- 定期回归测试，需要补充用例。

**输入**：
- 能力定义（CapabilitySchema）或 Workflow 定义（WorkflowSpec/CandidateWorkflowSpec）；
- 可选：历史 ExecutionTrace / AuditReport（可用于反向挖掘重要场景）。

**处理流程**：
1. LLM 设计测试用例矩阵（正常 / 边界 / 异常 / 极端）；
2. 输出 TestCaseSpec 列表（JSON）；
3. 测试 Agent 可以基于这些用例执行实际调用，并汇总结果。

**输出**：`TestCaseSpec` JSON Schema（见 3.5）。

**输出去向**：
- 写入 TestCaseStore，用于后续回归测试；
- 测试结果 + 置信度评估一并进入「待人工审批区」。

#### 2.2.5 模式 D: 失败经验构建

**触发时机**：
- 审计 Agent 完成审计，且：
  - `verdict == "fail"` 或
  - `risk_level == "high"` 或
  - 虽 `pass` 但存在值得记录的 `intermediate_error` 等问题。

**输入**：
- ExecutionTrace；
- AuditReport。

**处理流程**：
1. 从审计报告中提取关键问题：
   - 工具缺失？环境不透明？Plan 假设错误？模型理解错误？；
2. 从执行轨迹中抽取相关片段（问题发生前后步骤、关键 I/O）；
3. 将本次失败/问题总结为结构化 FailureExperience 记录；
4. 保存到经验库（可基于 SQLite 表或文件）。

**输出**：`FailureExperience` JSON（见 3.6）。

**输出去向**：
- 后续 Planner Mode A 在拆解类似任务时，作为「负面样本」提示；
- 供人工复盘使用。

#### 2.2.6 实现文件

- `tedbot/agent/planner.py` - 编排 Agent 主实现
- `tedbot/agent/planner/mode_a_task_plan.py` - 模式 A 实现
- `tedbot/agent/planner/mode_b_template_extract.py` - 模式 B 实现
- `tedbot/agent/planner/mode_c_test_generation.py` - 模式 C 实现
- `tedbot/agent/planner/mode_d_failure_experience.py` - 模式 D 实现

---

### 2.3 日志监督 Agent (Auditor Agent)

#### 2.3.1 职责

- 审计执行日志，判定是否撒谎、伪造成功、越权等
- 为模板升级提供判断依据

#### 2.3.2 核心流程

**阶段 1: 触发审计**

触发时机：
- 执行 Agent 完成任务后（自动触发，**仅当有工具调用时**）
  - 如果没有工具调用（LLM 直接回答），则跳过审计以节省 token
  - 因为没有工具调用 = 不存在主要风险（撒谎/伪造成功、越权）
- 按抽样策略定期审计
- 人工触发

**阶段 2: 读取执行数据**

1. 从 LogService 读取 ExecutionTrace
2. 从 Session 或前端读取用户视图
3. 从 TemplateRegistry 和 CapabilityRegistry 读取相关定义

**阶段 3: 构建审计 Case**

组装审计输入（JSON）

**阶段 4: 监督 LLM 评估**

输入审计 Case 给监督 LLM，要求回答：
1. 是否撒谎/伪造成功
2. 是否越权
3. 日志记录是否充分/准确

**阶段 5: 生成审计报告**

输出 AuditReport（JSON）

**阶段 6: 审计结果处理**

- 若 verdict 为 pass 且 template_candidate_eligible 为 true：
  - 将 ExecutionTrace + AuditReport 传递给编排 Agent 模式 B
- 若 verdict 为 fail 或 risk_level 为 high：
  - 记录审计结果，可触发告警、降权模型、屏蔽某类能力、人工复盘

#### 2.3.3 实现文件

- `tedbot/agent/auditor.py` - 日志监督 Agent 主实现
- `tedbot/agent/auditor/case_builder.py` - 审计 Case 构建
- `tedbot/agent/auditor/llm_judge.py` - 监督 LLM 评估
- `tedbot/agent/auditor/report_generator.py` - 审计报告生成

---

## 三、数据结构与协议规范

### 3.1 PlanSpec（编排 Agent 模式 A 输出）

PlanSpec 是「任务执行规范」，由编排 Agent 负责产生，执行 Agent 只负责按其中的子任务目标执行。

```json
{
  "plan_id": "plan_xxx",
  "task": "任务描述",
  "created_at": "2024-01-01T00:00:00Z",
  "execution_mode": "strict | flexible",
  "max_deviations": 0,
  "deviation_log_required": true,
  "steps": [
    {
      "step_id": 1,
      "subtask_goal": "说明这一步要达到的目标状态",
      "recommended_capability": "workflow_or_skill_or_atomic_name",
      "capability_level": "workflow | skill | atomic",
      "recommended_method": {
        "description": "可选：推荐的完成方式说明",
        "notes": "可选：注意事项"
      },
      "inputs": {
        "param1": "value1"
      },
      "success_criteria": {
        "status": "success | partial | any",
        "required_fields": ["field1", "field2"],
        "field_checks": {
          "field1": {
            "type": "string",
            "pattern": "^[a-z]+$"
          }
        },
        "custom_validator": "可选：自定义校验逻辑描述或代码字符串"
      },
      "dependencies": [],
      "optional": false,
      "execution_mode": "strict | flexible",
      "retry_policy": {
        "max_retries": 3,
        "backoff_strategy": "exponential",
        "initial_delay_ms": 1000,
        "max_delay_ms": 60000
      },
      "timeout_seconds": 60,
      "deviation_allowed": false,
      "deviation_reason_required": true
    }
  ]
}
```

**Schema 定义**: `tedbot/schemas/plan_spec.py`

### 3.2 ExecutionTrace（执行 Agent 写入 LogService）

```json
{
  "trace_id": "exec_xxx",
  "task": "任务描述",
  "started_at": "2024-01-01T00:00:00Z",
  "ended_at": "2024-01-01T00:05:00Z",
  "status": "success|fail",
  "steps": [
    {
      "step_id": 1,
      "capability": "workflow_name",
      "capability_level": "workflow",
      "inputs": {...},
      "outputs": {...},
      "duration_ms": 1000,
      "llm_decision": "LLM的决策内容",
      "context_snapshot": "执行时的上下文摘要"
    }
  ],
  "final_result": "最终结果"
}
```

**Schema 定义**: `tedbot/schemas/execution_trace.py`

### 3.3 CandidateWorkflowSpec（编排 Agent 模式 B 输出）

```json
{
  "workflow_id": "candidate_xxx",
  "name": "工作流名称",
  "description": "描述",
  "source_trace_id": "exec_xxx",
  "created_at": "2024-01-01T00:00:00Z",
  "steps": [
    {
      "step_id": 1,
      "capability": "skill_name",
      "inputs_schema": {
        "type": "object",
        "properties": {...}
      },
      "conditions": {
        "if": "...",
        "then": "..."
      },
      "retry": {
        "max_attempts": 3,
        "backoff": "exponential"
      }
    }
  ]
}
```

**Schema 定义**: `tedbot/schemas/workflow_spec.py`

### 3.4 AuditReport（日志监督 Agent 输出）

```json
{
  "audit_id": "audit_xxx",
  "execution_trace_id": "exec_xxx",
  "audited_at": "2024-01-01T00:06:00Z",
  "verdict": "pass | fail | warning",
  "risk_level": "low | medium | high",
  "issues": [
    {
      "type": "lie | unauthorized | incomplete_log | intermediate_error",
      "description": "问题描述",
      "evidence": {
        "step_id": 3,
        "log_key": "step_3_output",
        "user_statement": "用户看到的回复",
        "actual_result": "实际工具结果",
        "corrected_by_step": 7
      }
    }
  ],
  "template_candidate_eligible": true,
  "workflow_extraction_notes": "可选：对工作流抽取/失败经验构建的建议"
}
```

**说明**：
- `intermediate_error`：表示中间步骤有错误，但已经被后续步骤修正；
- 这种错误不会阻止整体 `verdict` 为 `pass`，但会进入 issues，并影响经验构建；
- `workflow_extraction_notes`：用于指导 Planner Mode B / Mode D 过滤或突出哪些步骤。

**Schema 定义**: `tedbot/schemas/audit_report.py`

### 3.5 TestCaseSpec（编排 Agent 模式 C 输出）

```json
{
  "test_id": "test_xxx",
  "capability": "workflow_name",
  "type": "normal|boundary|error|extreme",
  "input": {...},
  "expected_output": {...},
  "tolerance": {
    "exact_match": false,
    "fields_to_ignore": ["timestamp"]
  },
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Schema 定义**: `tedbot/schemas/test_case_spec.py`

### 3.6 FailureExperience（失败经验记录，编排 Agent 模式 D 输出）

FailureExperience 用于结构化记录一次任务执行中「值得学习的失败或问题」，为后续模式 A 提供负面样本参考。

```json
{
  "failure_id": "fail_xxx",
  "task": "原始任务描述",
  "plan_id": "plan_xxx",
  "trace_id": "exec_xxx",
  "failure_stage": "planning | execution | audit",
  "failure_step_id": 3,
  "failure_type": "tool_missing | env_opaque | plan_assumption_wrong | model_understanding_error | unknown",
  "summary": "简短人类可读摘要",
  "root_cause_hypothesis": "可能的根因分析（来自 Planner/审计）",
  "context_snippets": [
    "关键日志片段1",
    "关键日志片段2"
  ],
  "lessons_learned": "给未来 Planner 的建议",
  "created_at": "2024-01-01T00:07:00Z"
}
```

**Schema 定义**：可新增 `tedbot/schemas/failure_experience.py`（或集成到经验模块），供 Planner Mode A 聚合查询。

---

## 四、能力栈设计规范

### 4.1 三层能力栈

#### 4.1.1 Atomic 层

**定义**: 最底层的原子能力，不可再分解

**示例**:
- 浏览器控制：`navigate`, `click`, `type`, `snapshot`
- 文件操作：`read_file`, `write_file`, `edit_file`, `list_dir`
- HTTP 请求：`http_get`, `http_post`
- Shell 执行：`exec_shell`
- MCP 基础能力：各种 MCP 工具

**实现**: `tedbot/agent/capabilities/atomic.py`

#### 4.1.2 Skill/MCP 层

**定义**: 组合能力或远程 MCP 能力

**示例**:
- `fetch_github_trending`: 组合 HTTP + 解析
- `search_and_summarize`: 组合搜索 + LLM 总结
- 远程 MCP 能力：通过 MCP 协议调用的外部能力

**实现**: `tedbot/agent/capabilities/skill.py`

#### 4.1.3 Workflow 层

**定义**: 成熟可复用的工作流模板

**示例**:
- `github_trending_to_file`: 抓取 GitHub Trending 并保存到文件
- `web_research_report`: 网页研究并生成报告

**实现**: `tedbot/workflows/workflow.py`

### 4.2 CapabilityRegistry

**职责**:
- 注册和管理所有能力（Atomic/Skill/Workflow）
- 提供能力查询接口
- 验证能力是否存在
- 提供能力清单给 LLM（支持渐进式加载）

**实现**: `tedbot/infra/capability_registry.py`

**接口**:
```python
class CapabilityRegistry:
    def register(self, capability: Capability) -> None
    def get(self, name: str) -> Capability | None
    def list_all(self) -> list[Capability]
    
    def get_for_llm(self, include_details: bool = False) -> list[dict]:
        """
        获取能力清单（渐进式加载，学习 nanobot Skills System 精华）
        
        Args:
            include_details: 如果 True，返回完整定义（schema、usage_guide、examples）
                          如果 False，只返回轻量信息（name、description、level）
        
        Returns:
            能力清单列表
        """
        if include_details:
            # 返回完整定义（用于 LLM 需要详细信息时）
            return [cap.to_full_dict() for cap in self._capabilities.values()]
        else:
            # 只返回轻量信息（用于初始能力清单，减少 token）
            return [cap.to_summary_dict() for cap in self._capabilities.values()]
```

**能力定义结构**:
```python
class Capability:
    name: str                    # 能力名称
    description: str            # 简短描述（用于清单）
    level: str                  # atomic/skill/workflow
    schema: dict                # 参数 schema（JSON Schema）
    usage_guide: str | None     # 使用指导（可选，类似 SKILL.md 但结构化）
    examples: list[dict] | None # 使用示例（可选）
    
    def to_summary_dict(self) -> dict:
        """返回轻量信息（用于初始清单）"""
        return {
            "name": self.name,
            "description": self.description,
            "level": self.level
        }
    
    def to_full_dict(self) -> dict:
        """返回完整定义（用于需要详细信息时）"""
        return {
            "name": self.name,
            "description": self.description,
            "level": self.level,
            "schema": self.schema,
            "usage_guide": self.usage_guide,
            "examples": self.examples
        }
```

**渐进式加载策略**:
1. 初始调用：`get_for_llm(include_details=False)` - 只返回轻量信息
2. 需要详细信息时：LLM 可以请求特定能力的完整定义
3. 或直接调用：`get_for_llm(include_details=True)` - 返回所有能力的完整定义

---

## 五、基础设施设计规范

### 5.1 ContextManager（瘦上下文管理）

**职责**:
- 管理瘦上下文（4 类信息）
- 实现滑动窗口机制
- 超长历史写入日志

**实现**: `tedbot/infra/context_manager.py`

**接口**:
```python
class ContextManager:
    def init_context(self, task: dict) -> dict
    def update_step_history(self, step: dict) -> None
    def update_tool_io(self, io: dict) -> None
    def update_env_state(self, state: dict) -> None
    def get_context(self) -> dict  # 返回当前瘦上下文
    def archive_old_history(self) -> None  # 将超长历史写入日志
```

### 5.2 LogService（完整日志服务）

**职责**:
- 记录所有执行轨迹（结构化 JSON）
- 提供日志查询接口
- 支持日志回放

**实现**: `tedbot/infra/log_service.py`

**接口**:
```python
class LogService:
    def log_step(self, trace_id: str, step: dict) -> None
    def log_decision(self, trace_id: str, decision: dict) -> None
    def get_trace(self, trace_id: str) -> ExecutionTrace | None
    def list_traces(self, filters: dict) -> list[ExecutionTrace]
```

**存储**: 使用 SQLite 持久化（见 7.3 节），通过 Database 类统一管理

### 5.3 TemplateRegistry（Workflow 模板库）

**职责**:
- 存储成熟 Workflow 模板
- 提供模板匹配接口
- 支持模板版本管理

**实现**: `openbot/infra/template_registry.py`

**存储**: 使用 SQLite 持久化（见 7.3 节），通过 Database 类统一管理

**接口**:
```python
class TemplateRegistry:
    def register(self, workflow: WorkflowSpec) -> None
    def match(self, task: dict) -> WorkflowSpec | None
    def get(self, workflow_id: str) -> WorkflowSpec | None
    def list_all(self) -> list[WorkflowSpec]
```

### 5.4 TestCaseStore（测试用例存储）

**职责**:
- 存储测试用例
- 提供测试用例查询接口
- 支持测试执行

**实现**: `openbot/infra/test_case_store.py`

**存储**: 使用 SQLite 持久化（见 7.3 节），通过 Database 类统一管理

**接口**:
```python
class TestCaseStore:
    def add(self, test_case: TestCaseSpec) -> None
    def get_by_capability(self, capability: str) -> list[TestCaseSpec]
    def execute(self, test_case: TestCaseSpec) -> TestResult
```

### 5.5 SessionManager（会话管理）

**职责**:
- 管理用户会话（多用户/多渠道隔离）
- 保存会话历史（用于理解任务）
- 提供 Session 上下文（用于构建系统提示）

**实现**: `tedbot/session/manager.py`（保留 nanobot 实现，新增 Session 上下文管理）

**接口**:
```python
class SessionManager:
    # 保留 nanobot 的核心功能
    def get_or_create(self, key: str) -> Session
    def save(self, session: Session) -> None
    def invalidate(self, key: str) -> None
    def list_sessions(self) -> list[dict]
    
    # 新增：Session 上下文管理
    def get_context_for_task_understanding(self, session: Session) -> dict:
        """
        获取用于理解任务的 Session 上下文
        
        返回：
            {
                "user_history": [...],      # 用户历史对话（最近 N 条）
                "long_term_memory": "...",  # 长期记忆摘要
                "project_context": {...},   # 项目上下文信息
                "user_preferences": {...}   # 用户偏好
            }
        """
        pass
    
    def update_context(self, session: Session, new_info: dict) -> None:
        """更新 Session 上下文（如用户偏好、项目信息等）"""
        pass
```

**Session 上下文优化策略**:
- **滑动窗口**: 只保留最近 N 条消息（如 50 条），超长历史写入日志
- **智能摘要**: 对旧消息进行摘要，保留关键信息
- **索引优化**: 使用索引或向量化提高检索效率
- **压缩存储**: 对历史消息进行压缩，减少存储空间

### 5.6 ContextBuilder（上下文构建）

**职责**:
- 构建系统提示（包含 Session 上下文和执行上下文）
- 组装消息列表（用于 LLM 调用）
- 处理媒体输入（图片等）

**实现**: `tedbot/agent/context.py`（改造 nanobot 实现，支持两层上下文）

**接口**:
```python
class ContextBuilder:
    def __init__(self, workspace: Path, session_manager: SessionManager):
        self.workspace = workspace
        self.session_manager = session_manager
        self.memory = MemoryStore(workspace)
    
    def build_system_prompt(
        self,
        session: Session,
        execution_context: dict,  # 瘦上下文（来自 ContextManager）
        capability_list: list[dict]  # 能力清单（来自 CapabilityRegistry）
    ) -> str:
        """
        构建系统提示（两层上下文）
        
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
        execution_context: dict,
        current_message: str,
        capability_list: list[dict],
        media: list[str] | None = None
    ) -> list[dict]:
        """
        构建完整的消息列表
        
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
    
    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict]:
        """构建用户消息内容（支持图片等媒体）"""
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
```

### 5.7 MemoryStore（长期记忆系统）

**职责**:
- 管理长期记忆（MEMORY.md - 长期事实）
- 管理历史日志（HISTORY.md - 可搜索历史）
- 智能提取关键信息（不是简单合并）

**实现**: `tedbot/agent/memory.py`（保留 nanobot 实现，新增智能提取方法）

**接口**:
```python
class MemoryStore:
    # 保留 nanobot 的核心功能
    def read_long_term(self) -> str
    def write_long_term(self, content: str) -> None
    def append_history(self, entry: str) -> None
    def get_memory_context(self) -> str
    
    # 新增：智能提取（学习 nanobot 内存合并精华，但用更好的手段）
    def extract_key_facts(self, execution_trace: ExecutionTrace) -> dict:
        """
        从执行轨迹中提取关键事实（可以由编排 Agent 调用）
        
        提取内容：
            - 用户偏好
            - 项目信息
            - 重要决策
            - 技术选择
        
        Returns:
            结构化关键事实字典
        """
        pass
    
    def append_execution_summary(self, trace: ExecutionTrace) -> None:
        """
        将执行摘要追加到 HISTORY.md（可搜索）
        
        格式：[时间] 任务类型: 关键步骤摘要
        """
        pass
```

**智能提取策略**（不同于 nanobot 的简单合并）:
- **由编排 Agent 或人工维护**: 不是自动合并，而是智能提取关键信息
- **结构化存储**: 关键事实以结构化方式存储，便于查询
- **可搜索历史**: HISTORY.md 保持可搜索格式，便于 grep

### 5.8 LLM Provider 抽象

**职责**:
- 提供统一的 LLM 调用接口
- 支持多个 LLM Provider（OpenAI、Anthropic、本地模型等）
- 处理 Provider 特定的配置和参数

**实现**: `tedbot/providers/`（完全保留 nanobot 实现）

**接口**:
```python
class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> LLMResponse:
        """调用 LLM"""
        pass
    
    @abstractmethod
    def get_default_model(self) -> str:
        """获取默认模型"""
        pass
```

**支持的 Provider**:
- LiteLLM Provider（支持多个后端）
- 其他 Provider（按需添加）

---

## 六、实施计划

### 6.1 Phase 1: 基础设施搭建（2-3 周）

**目标**: 搭建核心基础设施，支持执行 Agent 基本运行

**任务清单**:

1. **数据结构与 Schema 定义**
   - [x] 实现 `PlanSpec` Schema（✅ 已升级：包含 subtask_goal, success_criteria, retry_policy, execution_mode 等）
   - [x] 实现 `ExecutionTrace` Schema
   - [x] 实现 `CandidateWorkflowSpec` Schema
   - [x] 实现 `AuditReport` Schema
   - [x] 实现 `TestCaseSpec` Schema

2. **ContextManager 实现**
   - [x] 实现瘦上下文管理（4 类信息）
   - [ ] 实现滑动窗口机制（按新规格强化）
   - [ ] 实现超长历史归档（与日志系统联动）

3. **LogService 实现**
   - [x] 实现结构化日志记录
   - [x] 实现日志查询接口
   - [x] 实现日志存储（SQLite，见 7.3 节）

4. **Database 实现（SQLite 持久化）**
   - [x] 实现 Database 类（见 7.3.3 节）
   - [x] 实现表结构初始化与迁移
   - [x] LogService 集成 Database（ExecutionTrace 持久化）
   - [x] TemplateRegistry 集成 Database（WorkflowSpec 持久化）
   - [x] TestCaseStore 集成 Database（TestCaseSpec 持久化）

5. **CapabilityRegistry 实现**
   - [x] 实现能力注册机制
   - [x] 实现能力查询接口
   - [x] 实现能力清单生成（供 LLM 使用）

6. **TemplateRegistry 实现**
   - [x] 实现模板存储
   - [x] 实现模板匹配接口
   - [ ] 实现模板版本管理（版本号/变更历史等）

**验收标准**:
- 所有 Schema 定义完成并通过验证
- ContextManager 可以管理瘦上下文
- LogService 可以记录和查询日志，并持久化到 SQLite
- Database 可正确存储和查询 ExecutionTrace、WorkflowSpec、TestCaseSpec
- CapabilityRegistry 可以注册和查询能力
- TemplateRegistry 可以存储和匹配模板（基于 Database）

---

### 6.2 Phase 2: 执行 Agent 实现（3-4 周）

**目标**: 实现执行 Agent 核心功能，支持「按子任务目标」的局部 React 执行，并完整记录 ExecutionTrace

**任务清单**:

1. **瘦上下文集成（✅ 已集成）**
   - [x] 在 `agent/loop.py` 中集成 ContextManager（已实现子任务级上下文管理）
   - [x] 实现任务规范化解析（抽取目标/约束/输出格式）
   - [x] 实现瘦上下文初始化（`execution_context` 的基础结构）
   - [x] 实现命令处理（在任务规范化之前处理 /new, /help 等命令）

2. **执行循环改造（✅ 已重构为 Plan 驱动）**
   - [x] 改造现有执行循环为 Plan 驱动执行（`_execute_plan` + `_execute_subtask` + `_run_subtask_react_loop`）
   - [x] 实现能力解析与验证（通过 CapabilityRegistry）
   - [x] 实现参数构造（支持 `PlanSpec.steps[].inputs` 和 `inputs_schema` 校验）
   - [x] 实现能力调用（支持 Workflow / Skill / Atomic，通过 CapabilityRegistry）
   - [x] 实现上下文更新（子任务级上下文管理）
   - [x] 实现日志记录（结构化 JSON，写入 LogService/Database）

3. **能力栈集成**
   - [x] 将现有工具注册到 CapabilityRegistry（Atomic 层）
   - [ ] 梳理并注册稳定的 Skill 层能力集合
   - [x] 支持 Workflow 层能力注册（从 TemplateRegistry 加载）
   - [x] 实现能力清单生成（供 LLM 使用）

4. **Plan 支持（✅ 已完成）**
   - [x] 支持读取预先 Plan（来自编排 Agent 的 `PlanSpec`）
   - [x] 支持按子任务顺序驱动执行（按 `PlanSpec.steps` 逐步下发子任务）
   - [x] 实现 Plan 偏离检测和日志记录（按 `PlanSpec` 结构化记录，支持 execution_mode 和 deviation_log_required）
   - [x] 实现 success_criteria 结构化校验（支持 status, required_fields, field_checks）
   - [x] 实现 retry_policy 重试机制（支持 fixed/linear/exponential 退避策略）
   - [x] 实现 timeout_seconds 超时控制
   - [x] 实现并行执行无依赖的子任务
   - [x] 实现子任务目标达成评估（LLM 评估）
   - [x] 实现执行指标收集（执行时间、重试次数等）
   - [x] 实现命令处理功能（/new, /help, /audit, /template, /memory）
   - [ ] （后续）集成 PlanExecutor / SchemaValidator 等更严格执行器

5. **候选 Workflow 抽取**
   - [x] 实现执行轨迹持久化（成功/失败均有 ExecutionTrace）
   - [x] 在审计通过后，由编排 Agent 模式 B 基于 ExecutionTrace 生成候选 Workflow（已在 `ExecutionAgent.process_task` 中接入）
   - [ ] 针对「仅执行 Agent 视角」的轻量 Workflow 骨架抽取（可选增强）

**验收标准**:
- 执行 Agent 可以在瘦上下文约束下运行
- 可以调用 Atomic/Skill/Workflow 三层能力
- 所有执行轨迹被完整记录到日志
- 成功执行可以生成候选 Workflow 骨架

---

### 6.3 Phase 3: 编排 Agent 实现（2-3 周）

**目标**: 实现编排 Agent 四种模式（A/B/C/D）

**任务清单**:

1. **模式 A: 任务拆解 Plan 设计（✅ 已重构）**
   - [x] 实现任务拆解逻辑（`ModeATaskPlan.generate_plan`）
   - [x] 实现 PlanSpec 生成（✅ 已对齐新版 Schema：包含 `subtask_goal`、结构化 `success_criteria`、`retry_policy`、`execution_mode` 等）
   - [x] 集成能力清单（来自 CapabilityRegistry）
   - [x] 移除兼容旧格式代码，严格按新格式生成
   - [ ] 集成失败经验库摘要作为负面样本输入（Mode D 输出接入）

2. **模式 B: 模板抽取（✅ 已实现）**
   - [x] 实现 ExecutionTrace 读取（通过 LogService/Database）
   - [x] 实现步骤过滤和抽象（`mode_b_template_extract.py`，结合审计报告过滤错误/探索性步骤）
   - [x] 实现 CandidateWorkflowSpec 生成
   - [x] 已集成到 `OrchestrationAgent.extract_workflow`
   - [ ] 实现人工审核接口（待审批区 / 明确注册指令）

3. **模式 C: 测试用例生成（✅ 已实现）**
   - [x] 实现测试用例设计逻辑（基础版，`mode_c_test_generation.py`）
   - [x] 实现 TestCaseSpec 生成
   - [x] 集成 TestCaseStore（使用 Database 持久化）
   - [x] 已集成到 `OrchestrationAgent.generate_test_cases`

4. **编排 Agent 主入口（✅ 部分完成）**
   - [x] 实现模式路由（`OrchestrationAgent` 中统一封装 A/B/C）
   - [x] 实现与执行 Agent / 审计 Agent 的交互（在 `ExecutionAgent.process_task` 中，审计后触发 Mode B + 测试）
   - [x] 增加模式 D 入口：从审计失败/高风险结果生成 FailureExperience（✅ 已完成）
     - [x] 创建 `mode_d_failure_experience.py` 实现
     - [x] 创建 `schemas/failure_experience.py` Schema
     - [x] 在 `OrchestrationAgent` 中集成 Mode D
     - [x] 在 `ExecutionAgent` 中触发 Mode D（审计失败/高风险时）
     - [x] 在 Database 中添加失败经验持久化支持

**验收标准**:
- ✅ 模式 A 可以生成有效的 PlanSpec
- ✅ 模式 B 可以从执行日志抽取 Workflow 骨架
- ✅ 模式 C 可以生成测试用例
- ✅ 模式 D 可以从失败执行生成 FailureExperience
- ✅ 四种模式可以独立运行

---

### 6.4 Phase 4: 日志监督 Agent 实现（2 周）

**目标**: 实现日志监督 Agent，支持行为审计

**任务清单**:

1. **审计 Case 构建**
   - [x] 实现 ExecutionTrace 读取（通过 LogService/Database）
   - [x] 实现用户视图读取
   - [x] 实现审计 Case 组装（`AuditCaseBuilder`）

2. **监督 LLM 评估**
   - [x] 实现监督 Prompt 设计（`LLMJudge` system prompt，支持 `intermediate_error` 等）
   - [x] 实现 LLM 评估逻辑
   - [x] 实现结果解析（解析为 judgment dict）

3. **审计报告生成**
   - [x] 实现 AuditReport 生成（`ReportGenerator`）
   - [x] 实现问题证据提取
   - [x] 审计完成后将 AuditReport 持久化到 Database（见 7.3 节）

4. **审计结果处理**
   - [x] 实现与编排 Agent 的交互（模板升级：pass + eligible 时触发 Mode B 抽 Workflow）
   - [x] 实现与编排 Agent 的交互（失败/高风险时触发 Mode D 构建 FailureExperience）
   - [ ] 实现告警和降权机制（如模型降权、能力屏蔽等）

**验收标准**:
- 可以读取执行日志和用户视图
- 可以判定是否撒谎/越权/记录不实
- 可以生成有效的 AuditReport 并持久化到 SQLite
- 审计结果可以触发模板升级流程

---

### 6.5 Phase 5: 测试与优化（2 周）

**目标**: 端到端测试，性能优化，文档完善

**任务清单**:

1. **端到端测试**
   - [ ] 测试执行 Agent 完整流程（含审计与 Workflow 抽取）
   - [ ] 测试编排 Agent A/B/C/D 模式
   - [ ] 测试日志监督 Agent 审计流程
   - [ ] 测试 Agent 间交互（Planner ↔ Execution ↔ Auditor）
   - [x] 测试 Tester Agent（测试用例执行和结果汇总）

2. **性能优化**
   - [ ] 优化上下文管理（滑动窗口效率）
   - [ ] 优化日志存储和查询
   - [ ] 优化能力匹配速度

3. **文档完善**
   - [ ] 完善 API 文档（对齐最新 `PlanSpec` / `AuditReport` / `FailureExperience` 等）
   - [ ] 完善使用示例（展示 Plan → 执行 → 审计 → Workflow/经验 的完整链路）
   - [ ] 完善架构文档（与当前 SPEC 同步演进）

**验收标准**:
- 所有端到端测试通过
- 性能满足要求（上下文管理 < 10ms，日志查询 < 100ms）
- 文档完整可用

---

## 七、Workspace 结构规范

### 7.1 Workspace 目录结构

```
workspace/
├── openbot.db         # SQLite 数据库（执行轨迹、审计报告、模板、测试用例、计划）
├── sessions/          # 会话文件（JSONL 格式）
│   ├── qq_123456.jsonl
│   └── cli_direct.jsonl
├── memory/            # 长期记忆
│   ├── MEMORY.md      # 长期事实（用户偏好、项目信息等）
│   └── HISTORY.md     # 可搜索历史（从 LogService 导出，可选）
├── logs/              # 执行日志（可选，SQLite 为主存储时可为空或作备份）
│   ├── traces/        # ExecutionTrace 文件（JSONL，可选备份）
│   └── audits/        # AuditReport 文件（可选备份）
├── templates/         # Workflow 模板（可选，SQLite 为主存储时可为空）
├── test_cases/        # 测试用例（可选，SQLite 为主存储时可为空）
└── capabilities/     # 能力定义（可选，如果需要文件式定义）
    ├── atomic/
    ├── skill/
    └── workflow/
```

### 7.2 文件存储规范

- **会话文件**: JSONL 格式，每行一个消息对象（保持文件存储，便于阅读）
- **长期记忆**: Markdown 格式，便于阅读和编辑
- **结构化数据**: 使用 SQLite 持久化（见 7.3 节）

### 7.3 SQLite 持久化存储规范

**设计原则**:
- 使用单一 SQLite 数据库文件 `workspace/openbot.db` 存储所有结构化数据
- 复杂嵌套结构（steps、issues 等）以 JSON 字符串存储
- 保持会话、长期记忆为文件存储，便于人工阅读和编辑

**数据库路径**: `workspace/openbot.db`

#### 7.3.1 持久化范围

| 数据类型 | 表名 | 说明 |
|---------|------|------|
| ExecutionTrace | execution_traces | 执行轨迹 |
| AuditReport | audit_reports | 审计报告 |
| WorkflowSpec | workflow_templates | 工作流模板 |
| TestCaseSpec | test_cases | 测试用例 |
| PlanSpec | plans | 计划（编排 Agent 模式 A 输出） |

**保持文件存储**:
- 会话 (Session): `sessions/*.jsonl`
- 长期记忆: `memory/MEMORY.md`, `memory/HISTORY.md`
- 配置: `config.json`

#### 7.3.2 表结构定义

```sql
-- 1. 执行轨迹表
CREATE TABLE execution_traces (
    trace_id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT,  -- 'success' | 'fail'
    final_result TEXT,
    steps_json TEXT NOT NULL,  -- JSON array of ExecutionStepModel
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_traces_started_at ON execution_traces(started_at);
CREATE INDEX idx_traces_status ON execution_traces(status);

-- 2. 审计报告表
CREATE TABLE audit_reports (
    audit_id TEXT PRIMARY KEY,
    execution_trace_id TEXT NOT NULL,
    audited_at TEXT NOT NULL,
    verdict TEXT NOT NULL,  -- 'pass' | 'fail' | 'warning'
    risk_level TEXT NOT NULL,  -- 'low' | 'medium' | 'high'
    issues_json TEXT NOT NULL,  -- JSON array of AuditIssue
    template_candidate_eligible INTEGER NOT NULL DEFAULT 0,  -- BOOLEAN
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (execution_trace_id) REFERENCES execution_traces(trace_id)
);

CREATE INDEX idx_audits_trace_id ON audit_reports(execution_trace_id);
CREATE INDEX idx_audits_verdict ON audit_reports(verdict);
CREATE INDEX idx_audits_audited_at ON audit_reports(audited_at);

-- 3. 工作流模板表
CREATE TABLE workflow_templates (
    workflow_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    source_trace_id TEXT,
    steps_json TEXT NOT NULL,  -- JSON array of WorkflowStepSpec
    created_at TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_workflows_name ON workflow_templates(name);
CREATE INDEX idx_workflows_source_trace ON workflow_templates(source_trace_id);

-- 4. 测试用例表
CREATE TABLE test_cases (
    test_id TEXT PRIMARY KEY,
    capability TEXT NOT NULL,
    type TEXT NOT NULL,  -- 'normal' | 'boundary' | 'error' | 'extreme'
    input_json TEXT NOT NULL,
    expected_output_json TEXT NOT NULL,
    tolerance_json TEXT NOT NULL,  -- ToleranceSpec
    created_at TEXT NOT NULL
);

CREATE INDEX idx_test_cases_capability ON test_cases(capability);
CREATE INDEX idx_test_cases_type ON test_cases(type);

-- 5. 计划表
CREATE TABLE plans (
    plan_id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    steps_json TEXT NOT NULL,  -- JSON array of PlanStep
    created_at TEXT NOT NULL
);

CREATE INDEX idx_plans_created_at ON plans(created_at);
```

#### 7.3.3 基础设施接口

**实现**: `openbot/infra/database.py`

```python
class Database:
    """SQLite 数据库服务，统一管理所有持久化数据"""

    def __init__(self, db_path: Path | None = None) -> None:
        """初始化数据库，若 db_path 为 None 则使用 workspace/openbot.db"""

    def _init_schema(self) -> None:
        """初始化/迁移数据库表结构"""

    # ExecutionTrace
    def save_execution_trace(self, trace: ExecutionTraceModel) -> None
    def get_execution_trace(self, trace_id: str) -> ExecutionTraceModel | None
    def list_execution_traces(self, limit: int = 100, status: str | None = None) -> list[ExecutionTraceModel]

    # AuditReport
    def save_audit_report(self, report: AuditReport) -> None
    def get_audit_report(self, audit_id: str) -> AuditReport | None
    def list_audit_reports(self, trace_id: str | None = None, verdict: str | None = None) -> list[AuditReport]

    # WorkflowSpec
    def save_workflow_template(self, workflow: WorkflowSpec) -> None
    def get_workflow_template(self, workflow_id: str) -> WorkflowSpec | None
    def list_workflow_templates(self) -> list[WorkflowSpec]

    # TestCaseSpec
    def save_test_case(self, test_case: TestCaseSpec) -> None
    def get_test_case(self, test_id: str) -> TestCaseSpec | None
    def list_test_cases(self, capability: str | None = None) -> list[TestCaseSpec]

    # PlanSpec
    def save_plan(self, plan: PlanSpec) -> None
    def get_plan(self, plan_id: str) -> PlanSpec | None
```

#### 7.3.4 组件集成

- **LogService**: 任务结束时将 ExecutionTrace 写入数据库
- **AuditorAgent**: 审计完成后将 AuditReport 写入数据库
- **TemplateRegistry**: 从数据库加载/保存 WorkflowSpec
- **TestCaseStore**: 从数据库加载/保存 TestCaseSpec
- **OrchestrationAgent 模式 A**: 生成的 PlanSpec 可写入数据库（可选）

### 7.4 与 nanobot 的差异

- **移除**: `skills/` 目录（不需要文档式技能）
- **移除**: Bootstrap 文件（AGENTS.md 等，改为配置或代码）
- **新增**: `openbot.db`（SQLite 持久化结构化数据）
- **新增**: `logs/` 目录（执行日志，可选备份）
- **新增**: `templates/` 目录（Workflow 模板，可选备份）
- **新增**: `test_cases/` 目录（测试用例，可选备份）

---

## 八、渠道系统规范

### 8.1 渠道架构

**设计原则**:
- 只保留 QQ 渠道（必须）
- 保留 CLI 渠道（必须，基本交互方式）
- 保留 BaseChannel 接口（便于未来扩展）
- 移除其他渠道（Telegram、Discord 等）

### 8.2 BaseChannel 接口

**实现**: `tedbot/channels/base.py`（完全保留 nanobot 实现）

```python
class BaseChannel(ABC):
    """渠道基类（保留 nanobot 的设计）"""
    name: str = "base"
    
    @abstractmethod
    async def start(self) -> None:
        """启动渠道"""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """停止渠道"""
        pass
    
    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """发送消息"""
        pass
    
    def is_allowed(self, sender_id: str) -> bool:
        """检查发送者是否被允许"""
        pass
```

### 8.3 QQChannel 实现

**实现**: `tedbot/channels/qq.py`（完全保留 nanobot 实现）

- 使用 botpy SDK
- 支持私聊和群聊
- WebSocket 连接，自动重连
- 消息去重（避免重复处理）

### 8.4 CLI 实现

**实现**: `tedbot/cli/commands.py`（完全保留 nanobot 实现）

- 使用 typer 框架
- 支持单次对话和交互式模式
- 直接调用 `AgentLoop.process_direct()`

### 8.5 ChannelManager（简化版）

**实现**: `tedbot/channels/manager.py`（简化 nanobot 实现，只管理 QQ）

```python
class ChannelManager:
    """渠道管理器（简化版，只管理 QQ）"""
    
    def __init__(self, config: Config, bus: MessageBus):
        self.config = config
        self.bus = bus
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        
        self._init_channels()
    
    def _init_channels(self) -> None:
        """初始化渠道（只初始化 QQ）"""
        if self.config.channels.qq.enabled:
            try:
                from tedbot.channels.qq import QQChannel
                self.channels["qq"] = QQChannel(
                    self.config.channels.qq,
                    self.bus
                )
                logger.info("QQ channel enabled")
            except ImportError as e:
                logger.warning(f"QQ channel not available: {e}")
        
        # CLI 不需要在这里初始化，因为它不是异步渠道
        # CLI 通过 commands.py 直接调用 AgentLoop
    
    async def start_all(self) -> None:
        """启动所有渠道"""
        for name, channel in self.channels.items():
            await channel.start()
            logger.info(f"Started channel: {name}")
    
    async def stop_all(self) -> None:
        """停止所有渠道"""
        for name, channel in self.channels.items():
            await channel.stop()
            logger.info(f"Stopped channel: {name}")
    
    async def dispatch_outbound(self) -> None:
        """分发出站消息（只分发给 QQ）"""
        while True:
            try:
                msg = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)
                channel = self.channels.get(msg.channel)
                if channel:
                    await channel.send(msg)
            except asyncio.TimeoutError:
                continue
```

### 8.6 配置简化

**实现**: `tedbot/config/schema.py`

```python
class ChannelsConfig(Base):
    """渠道配置（简化版，只保留 QQ）"""
    qq: QQConfig = Field(default_factory=QQConfig)
    # 移除其他渠道配置（telegram、discord 等）

class Config(Base):
    """主配置"""
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    # ... 其他配置
```

### 8.7 未来扩展

如果需要添加新渠道：
1. 实现 BaseChannel 接口
2. 在 ChannelManager 中注册
3. 无需修改其他代码

---

## 九、项目结构

```
tedbot/
├── tedbot/
│   ├── __init__.py
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── loop.py              # 执行 Agent 主循环
│   │   ├── context.py           # 上下文构建（两层上下文）
│   │   ├── memory.py            # 记忆管理（智能提取）
│   │   ├── planner.py           # 编排 Agent 主入口
│   │   ├── planner/
│   │   │   ├── __init__.py
│   │   │   ├── mode_a_task_plan.py      # 模式 A
│   │   │   ├── mode_b_template_extract.py  # 模式 B
│   │   │   └── mode_c_test_generation.py   # 模式 C
│   │   ├── auditor.py           # 日志监督 Agent 主入口
│   │   ├── auditor/
│   │   │   ├── __init__.py
│   │   │   ├── case_builder.py
│   │   │   ├── llm_judge.py
│   │   │   └── report_generator.py
│   │   ├── capabilities/
│   │   │   ├── __init__.py
│   │   │   ├── base.py          # 能力基类
│   │   │   ├── atomic.py        # Atomic 层
│   │   │   ├── skill.py         # Skill 层
│   │   │   └── registry.py      # 能力注册（保留，兼容）
│   │   └── tools/               # 现有工具（Atomic 层实现）
│   │       ├── __init__.py
│   │       ├── browser.py
│   │       ├── filesystem.py
│   │       ├── shell.py
│   │       └── web.py
│   ├── infra/                   # 基础设施层
│   │   ├── __init__.py
│   │   ├── context_manager.py   # ContextManager（执行上下文）
│   │   ├── database.py          # Database（SQLite 持久化，见 7.3 节）
│   │   ├── log_service.py       # LogService
│   │   ├── capability_registry.py  # CapabilityRegistry（渐进式加载）
│   │   ├── template_registry.py    # TemplateRegistry
│   │   └── test_case_store.py      # TestCaseStore
│   ├── schemas/                 # 数据结构 Schema
│   │   ├── __init__.py
│   │   ├── plan_spec.py
│   │   ├── execution_trace.py
│   │   ├── workflow_spec.py
│   │   ├── audit_report.py
│   │   └── test_case_spec.py
│   ├── workflows/               # Workflow 层
│   │   ├── __init__.py
│   │   ├── workflow.py          # Workflow 基类
│   │   └── recorder.py          # 工作流记录（保留，兼容）
│   ├── channels/                # 通信渠道（简化版）
│   │   ├── __init__.py
│   │   ├── base.py              # BaseChannel 接口
│   │   ├── qq.py                # QQ 渠道（保留）
│   │   └── manager.py           # ChannelManager（简化版）
│   ├── cli/                     # CLI 命令（保留）
│   │   └── commands.py
│   ├── config/                  # 配置管理（保留）
│   ├── providers/               # LLM 提供商（保留）
│   ├── bus/                     # 消息总线（保留）
│   └── session/                 # 会话管理（保留，新增 Session 上下文）
│       └── manager.py
├── tests/                       # 测试
│   ├── test_exec_agent.py
│   ├── test_planner_agent.py
│   ├── test_auditor_agent.py
│   └── test_integration.py
├── docs/                        # 文档
│   ├── architecture.md
│   ├── api.md
│   └── examples.md
├── pyproject.toml
└── README.md
```

---

## 十、验收标准

### 8.1 功能验收

- [ ] 执行 Agent 可以在瘦上下文约束下运行
- [ ] 可以调用 Atomic/Skill/Workflow 三层能力
- [ ] 所有执行轨迹被完整记录到日志
- [ ] 编排 Agent 三种模式可以独立运行
- [ ] 日志监督 Agent 可以审计执行日志
- [ ] 成功执行可以生成候选 Workflow 并升级为正式模板

### 8.2 性能验收

- [ ] 上下文管理操作 < 10ms
- [ ] 日志查询 < 100ms
- [ ] 能力匹配 < 50ms
- [ ] 执行 Agent 单步执行 < 5s（不含 LLM 调用）

### 8.3 质量验收

- [ ] 代码覆盖率 > 80%
- [ ] 所有 Schema 验证通过
- [ ] 所有端到端测试通过
- [ ] 文档完整可用

---

## 十一、风险与应对

### 9.1 技术风险

**风险**: 瘦上下文可能导致 LLM 决策质量下降

**应对**: 
- 设计合理的滑动窗口大小
- 在日志中保留完整上下文，供审计使用
- 通过测试用例验证决策质量

### 9.2 性能风险

**风险**: 日志存储和查询可能成为瓶颈

**应对**:
- 使用高效的存储方案（JSONL 或数据库）
- 实现日志索引
- 考虑日志归档策略

### 9.3 复杂度风险

**风险**: 三个 Agent 的交互可能增加系统复杂度

**应对**:
- 严格定义 Agent 间通信协议（JSON Schema）
- 实现清晰的接口边界
- 充分的单元测试和集成测试

---

## 十二、后续规划

### 10.1 短期（3-6 个月）

- 完善测试用例库
- 优化性能
- 增加更多 Atomic/Skill 能力
- 完善文档和示例

### 10.2 中期（6-12 个月）

- 实现 Workflow 可视化编辑
- 实现自动化测试执行
- 实现审计报告可视化
- 支持多租户

### 10.3 长期（12+ 个月）

- 实现分布式执行
- 实现能力市场
- 实现跨 Agent 协作（如需要）

---

## 附录

### A. 参考文档

- [单 Agent 工程规范](./docs/single_agent_spec.md)
- [完整流程设计图](./docs/flow_diagrams.md)

### B. 术语表

- **执行 Agent**: Runtime Agent，唯一在线执行者
- **编排 Agent**: Planner Agent，负责任务拆解和模板抽取
- **日志监督 Agent**: Auditor Agent，负责行为审计
- **瘦上下文**: 只包含 4 类必要信息的上下文
- **能力栈**: Atomic/Skill/Workflow 三层能力体系
- **ExecutionTrace**: 执行轨迹，结构化日志

### C. 变更日志

- 2026-02-21: 初始版本，完成详细规范设计
- 2026-02-21: 补充 Session 上下文管理、两层上下文构建、Memory 智能提取、能力渐进式加载、Workspace 结构、命令系统、渠道系统等规范
- 2026-02-22: **重大重构完成** - Plan as Specification 范式实现
  - ✅ PlanSpec Schema 升级（subtask_goal, success_criteria, retry_policy, execution_mode 等）
  - ✅ Mode A 规划逻辑重构（严格按新格式，移除兼容代码）
  - ✅ ExecutionAgent 重构为 Plan 驱动执行（按 PlanSpec.steps 逐个执行子任务）
  - ✅ 实现 success_criteria 结构化校验
  - ✅ 实现 retry_policy 重试机制（支持 fixed/linear/exponential）
  - ✅ 实现 timeout_seconds 超时控制
  - ✅ 实现并行执行无依赖的子任务
  - ✅ 实现子任务目标达成评估（LLM 评估）
  - ✅ 实现执行指标收集（执行时间、重试次数等）
  - ✅ 实现命令处理功能（/new, /help, /audit, /template, /memory）
  - ✅ 完善 PlanSpec 数据库保存逻辑（包含 execution_mode 等字段）
  - ✅ Mode B 工作流抽取（已实现并集成到 OrchestrationAgent）
  - ✅ Mode C 测试用例生成（已实现并集成到 OrchestrationAgent）
  - ✅ Mode D 失败经验构建（已完成：创建了 mode_d_failure_experience.py 和 failure_experience.py schema，集成到 OrchestrationAgent 和 ExecutionAgent）
  - ✅ Tester Agent 测试执行（已完成：实现了测试用例执行、结果比较和汇总功能）
- 2026-02-21: 新增 7.3 SQLite 持久化存储规范，定义 Database 类、表结构、持久化范围及组件集成方式