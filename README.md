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

一个基于 **单 Agent 规范** 的 AI 助手，具备：

- 单执行 Agent：所有工具调用都经由一个核心循环
- 三层能力栈：Atomic / Skill / Workflow
- 瘦执行上下文 + 完整 ExecutionTrace 日志
- 编排 Agent：任务拆解、模板抽取、测试用例生成
- 日志监督 Agent：行为审计、防止"为达目的而撒谎"
- QQ + CLI 渠道：最小但可用的外接通讯能力

详细设计规范见仓库根目录的 `SPEC.md`。该项目的目标是在实践中验证并迭代这套规范。

## 当前状态

### ✅ 已完成（Phase 1 部分）

1. **数据结构与 Schema 定义**
   - ✅ PlanSpec、ExecutionTrace、WorkflowSpec、AuditReport、TestCaseSpec

2. **基础设施实现**
   - ✅ ContextManager（瘦执行上下文管理）
   - ✅ LogService（ExecutionTrace 记录）
   - ✅ CapabilityRegistry（能力注册，支持渐进式加载）
   - ✅ TemplateRegistry（Workflow 模板库）
   - ✅ TestCaseStore（测试用例存储）
   - ✅ SessionManager（会话管理，含 Session 上下文接口）
   - ✅ MemoryStore（长期记忆系统）

3. **核心组件**
   - ✅ ExecutionAgent（执行 Agent 核心循环）
   - ✅ ContextBuilder（两层上下文构建）
   - ✅ LLM Provider 抽象（LiteLLMProvider）
   - ✅ MessageBus（消息总线）

4. **CLI 命令**
   - ✅ `openbot agent -m "message"` - 单次对话
   - ✅ `openbot agent` - 交互式模式
   - ✅ `openbot config` - 查看/初始化配置

5. **配置系统**
   - ✅ 配置文件管理（`~/.openbot/config.json`）
   - ✅ 多 Provider 支持（OpenRouter, Anthropic, OpenAI 等）
   - ✅ 环境变量覆盖
   - ✅ Provider Registry 自动匹配

### 🚧 进行中

- 工具注册与执行（Atomic 层）
- 能力实际调用逻辑完善

### 📋 待完成

- 编排 Agent 三种模式
- 日志监督 Agent
- QQ 渠道集成
- 更多 Atomic/Skill/Workflow 能力

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
│   ├── agent/          # Agent 核心
│   │   ├── loop.py     # ExecutionAgent
│   │   ├── context.py  # ContextBuilder
│   │   ├── memory.py   # MemoryStore
│   │   └── tools/      # Atomic 工具
│   ├── infra/          # 基础设施
│   │   ├── context_manager.py
│   │   ├── log_service.py
│   │   ├── capability_registry.py
│   │   ├── template_registry.py
│   │   └── test_case_store.py
│   ├── schemas/        # 数据结构 Schema
│   ├── providers/      # LLM Provider
│   ├── bus/           # 消息总线
│   ├── session/       # 会话管理
│   └── cli/           # CLI 命令
└── SPEC.md            # 详细设计规范
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

