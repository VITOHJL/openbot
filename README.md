# openbot

## ⚠️ 重要说明：当前版本（PlanSpec+React）的经验教训

**本分支（PlanSpec+React）是一个实验性版本，展示了多 Agent 设计的复杂性。**

### 设计问题总结

1. **多 Agent 设计过于复杂**：虽然设计严谨，但多个 Agent 之间相互牵制，导致系统过于复杂。并非从零生成项目，导致不断拆东墙补西墙。

2. **过度依赖 JSON 控制稳定性**：通过 PlanSpec 等 JSON Schema 来控制执行稳定性，但因为 LLM 生成 JSON 的不稳定性，反而导致多次返工。简单任务的耗时和 token 消耗都大幅增长。

3. **核心问题**：
   - 多 Agent 协作的复杂性超过了收益
   - JSON Schema 验证虽然严谨，但 LLM 生成的不稳定性导致频繁失败
   - 简单任务变得复杂，执行效率下降

### 经验教训

**我们应该做更简单直接的 Agent 系统，但在初期想好后期的拓展性。**

这个版本作为经验积累保留，但**不建议在生产环境使用**。后续版本将采用更简单直接的设计。

---

## 项目简介

一个基于 **多 Agent 协作架构** 的 AI 助手系统，采用 PlanSpec 驱动的执行模式。

### 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                    多 Agent 协作架构                          │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  执行Agent   │    │  编排Agent   │    │  审计Agent   │  │
│  │ (Execution)  │    │ (Planner)    │    │  (Auditor)   │  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘  │
│         │                   │                    │          │
│         └───────────────────┼────────────────────┘          │
│                             │                               │
│  ┌──────────────┐           │                               │
│  │  测试Agent   │           │                               │
│  │  (Tester)    │           │                               │
│  └──────────────┘           │                               │
│                             │                               │
│  ┌──────────────────────────┼──────────────────────────┐   │
│  │        能力栈 (CapabilityRegistry)                   │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ Workflow │  │ Skill/   │  │ Atomic   │          │   │
│  │  │   层     │  │  MCP层   │  │   层     │          │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Agent 职责

1. **编排 Agent (OrchestrationAgent/Planner)**
   - **Mode A**: 任务拆解 Plan 设计 - 将用户任务拆解为 PlanSpec
   - **Mode B**: 模板抽取 - 从成功执行轨迹抽象 Workflow
   - **Mode C**: 测试用例生成 - 为能力/Workflow 生成测试用例
   - **Mode D**: 失败经验构建 - 从失败执行轨迹构建失败经验
   - 包含 Session 上下文，用于理解任务意图

2. **执行 Agent (ExecutionAgent)**
   - 唯一在线执行者，所有工具调用都经由它
   - 按 PlanSpec 执行子任务，每个子任务内部使用 React 模式
   - 不包含 Session 上下文，只按 Plan 执行
   - 支持 success_criteria 验证和 LLM 目标评估

3. **审计 Agent (AuditorAgent)**
   - 监督执行轨迹，判定是否存在撒谎、越权等问题
   - 生成 AuditReport，包含 verdict、risk_level、issues
   - 支持迭代修正识别（中间错误但已修正的情况）

4. **测试 Agent (TesterAgent)**
   - 执行测试用例，验证能力/Workflow 的正确性
   - 支持 TestCaseSpec 的多种测试类型

### 核心特性

- **PlanSpec 驱动执行**：通过 JSON Schema 定义执行计划，确保结构化执行
- **三层能力栈**：Atomic / Skill / Workflow，支持渐进式能力注册
- **瘦执行上下文 + 完整 ExecutionTrace 日志**：上下文精简，日志完整
- **两层上下文管理**：
  - Session 上下文：用于理解任务（Planner 使用）
  - 执行上下文：用于执行任务（Execution Agent 使用）
- **可审计可追溯**：所有决策和调用都有日志，支持事后审计

详细设计规范见仓库根目录的 `SPEC.md`。该项目的目标是在实践中验证并迭代这套规范。

## 当前状态

### ✅ 已完成

1. **数据结构与 Schema 定义**
   - ✅ PlanSpec（执行计划规范）
   - ✅ ExecutionTrace（执行轨迹）
   - ✅ WorkflowSpec（工作流规范）
   - ✅ AuditReport（审计报告）
   - ✅ TestCaseSpec（测试用例规范）
   - ✅ FailureExperience（失败经验）

2. **基础设施实现**
   - ✅ ContextManager（瘦执行上下文管理）
   - ✅ LogService（ExecutionTrace 记录）
   - ✅ CapabilityRegistry（能力注册，支持渐进式加载）
   - ✅ TemplateRegistry（Workflow 模板库）
   - ✅ TestCaseStore（测试用例存储）
   - ✅ SessionManager（会话管理，含 Session 上下文接口）
   - ✅ MemoryStore（长期记忆系统）
   - ✅ Database（SQLite 持久化）

3. **Agent 实现**
   - ✅ **ExecutionAgent**：执行 Agent 核心循环
     - PlanSpec 驱动的子任务执行
     - React 模式内部循环
     - success_criteria 验证
     - LLM 目标评估
   - ✅ **OrchestrationAgent/Planner**：编排 Agent
     - ✅ Mode A: 任务拆解 Plan 设计
     - ✅ Mode B: 模板抽取
     - ✅ Mode C: 测试用例生成
     - ✅ Mode D: 失败经验构建
   - ✅ **AuditorAgent**：审计 Agent
     - 执行轨迹审计
     - 撒谎/越权检测
     - 迭代修正识别
   - ✅ **TesterAgent**：测试 Agent
     - 测试用例执行
     - 结果验证

4. **上下文管理**
   - ✅ ContextBuilder（两层上下文构建）
     - Session 上下文（Planner 使用，用于理解任务）
     - 执行上下文（Execution Agent 使用，用于执行任务）
   - ✅ 上下文隔离：Execution Agent 不包含 Session 历史

5. **工具与能力**
   - ✅ Atomic 层工具（filesystem, shell, echo 等）
   - ✅ 工具注册与执行机制
   - ✅ 能力调用验证

6. **CLI 命令**
   - ✅ `openbot agent -m "message"` - 单次对话
   - ✅ `openbot agent` - 交互式模式
   - ✅ `openbot config` - 查看/初始化配置

7. **配置系统**
   - ✅ 配置文件管理（`~/.openbot/config.json`）
   - ✅ 多 Provider 支持（OpenRouter, Anthropic, OpenAI 等）
   - ✅ 环境变量覆盖
   - ✅ Provider Registry 自动匹配

### 📋 待完成

- Skill/Workflow 层能力扩展
- QQ 渠道集成
- 更多测试用例类型支持
- 性能优化（减少 token 消耗）

## 快速开始

### 安装

```bash
cd openbot
pip install -e .
```

### 配置

openbot 使用配置文件来管理设置。首次运行时会自动创建默认配置。

#### 方式 1: 使用配置文件（推荐）

运行配置命令查看或初始化配置：

```bash
openbot config
```

配置文件位置：`~/.openbot/config.json`

你可以直接编辑配置文件，或使用环境变量覆盖：

```bash
# 环境变量格式：OPENBOT__<SECTION>__<SUBSECTION>__<KEY>
export OPENBOT__PROVIDERS__OPENROUTER__API_KEY="your-api-key"
export OPENBOT__PROVIDERS__ANTHROPIC__API_KEY="your-anthropic-key"
export OPENBOT__AGENTS__DEFAULTS__MODEL="anthropic/claude-opus-4-5"
export OPENBOT__AGENTS__DEFAULTS__WORKSPACE="~/.openbot/workspace"
```

#### 方式 2: 直接编辑配置文件

编辑 `~/.openbot/config.json`：

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.openbot/workspace",
      "model": "anthropic/claude-opus-4-5",
      "maxTokens": 8192,
      "temperature": 0.7,
      "maxToolIterations": 20
    }
  },
  "providers": {
    "openrouter": {
      "apiKey": "your-openrouter-api-key",
      "apiBase": null
    },
    "anthropic": {
      "apiKey": "your-anthropic-api-key",
      "apiBase": null
    }
  },
  "channels": {
    "qq": {
      "enabled": false,
      "appId": "",
      "secret": ""
    }
  }
}
```

#### 支持的 Provider

- `openrouter` - OpenRouter 网关（支持多种模型）
- `anthropic` - Anthropic Claude
- `openai` - OpenAI GPT
- `deepseek` - DeepSeek
- `gemini` - Google Gemini
- `dashscope` - 阿里云通义千问
- `moonshot` - Moonshot (Kimi)
- `minimax` - MiniMax
- `groq` - Groq
- `vllm` - vLLM 本地部署
- `custom` - 自定义 OpenAI 兼容端点

### 使用

```bash
# 单次对话
openbot agent -m "Hello, openbot!"

# 交互式模式
openbot agent
```

## 项目结构

```
openbot/
├── openbot/
│   ├── agent/              # Agent 核心
│   │   ├── loop.py         # ExecutionAgent（执行 Agent）
│   │   ├── context.py      # ContextBuilder（上下文构建）
│   │   ├── memory.py       # MemoryStore（长期记忆）
│   │   ├── tester.py      # TesterAgent（测试 Agent）
│   │   ├── planner/        # OrchestrationAgent（编排 Agent）
│   │   │   ├── planner.py  # 主入口
│   │   │   ├── mode_a_task_plan.py          # Mode A: 任务拆解
│   │   │   ├── mode_b_template_extract.py   # Mode B: 模板抽取
│   │   │   ├── mode_c_test_generation.py    # Mode C: 测试生成
│   │   │   └── mode_d_failure_experience.py # Mode D: 失败经验
│   │   ├── auditor/        # AuditorAgent（审计 Agent）
│   │   │   ├── auditor.py  # 主入口
│   │   │   ├── case_builder.py    # 审计 Case 构建
│   │   │   ├── llm_judge.py       # LLM 评估
│   │   │   └── report_generator.py # 报告生成
│   │   └── tools/          # Atomic 工具
│   │       ├── base.py     # 工具基类
│   │       ├── filesystem.py
│   │       ├── shell.py
│   │       └── registry.py
│   ├── infra/              # 基础设施
│   │   ├── context_manager.py    # 执行上下文管理
│   │   ├── log_service.py        # 执行轨迹记录
│   │   ├── capability_registry.py # 能力注册
│   │   ├── template_registry.py  # 模板库
│   │   ├── test_case_store.py    # 测试用例存储
│   │   └── database.py           # 数据库持久化
│   ├── schemas/            # 数据结构 Schema
│   │   ├── plan_spec.py           # PlanSpec
│   │   ├── execution_trace.py     # ExecutionTrace
│   │   ├── workflow_spec.py       # WorkflowSpec
│   │   ├── audit_report.py        # AuditReport
│   │   ├── test_case_spec.py      # TestCaseSpec
│   │   └── failure_experience.py  # FailureExperience
│   ├── providers/          # LLM Provider
│   ├── bus/               # 消息总线
│   ├── session/           # 会话管理
│   └── cli/               # CLI 命令
└── SPEC.md                # 详细设计规范
```

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 代码检查
ruff check .
```

