# openbot 架构文档

## 概述

openbot 是一个基于**单 Agent 规范**的 AI 助手系统，核心设计理念：

- **轻量、可托管、稳定、低幻觉、可审计**
- **把确定性交给流程，把不确定性交给 AI**
- **能固化成流程的，绝不交给 AI 即兴发挥**
- **AI 只做人类无法提前写死的决策**

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      openbot 系统架构                          │
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
│  │  ContextManager | LogService | TemplateRegistry      │   │
│  │  CapabilityRegistry | TestCaseStore                  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## 核心组件

### 1. 执行 Agent (ExecutionAgent)

**位置**: `openbot/agent/loop.py`

**职责**:
- 唯一在线执行者，负责实际调用工具、记录日志、返回结果
- 在瘦上下文约束下进行 React 模式决策
- 所有能力调用必须经过 CapabilityRegistry 验证
- 所有行为必须记录到 LogService

**核心流程**:
1. 任务接收与初始化
2. React 模式执行循环
3. 任务结束处理

### 2. 编排 Agent (OrchestrationAgent)

**位置**: `openbot/agent/planner/planner.py`

**职责**:
- 任务拆解 Plan 设计（模式 A）
- 从成功执行日志抽象 Workflow（模式 B）
- 为能力/Workflow 生成测试用例（模式 C）

### 3. 审计 Agent (AuditorAgent)

**位置**: `openbot/agent/auditor/auditor.py`

**职责**:
- 审计执行日志，判定是否撒谎、伪造成功、越权等
- 为模板升级提供判断依据

### 4. 能力栈 (CapabilityRegistry)

**位置**: `openbot/infra/capability_registry.py`

**三层能力栈**:
- **Atomic 层**: 最底层的原子能力（工具）
- **Skill 层**: 组合能力或远程 MCP 能力
- **Workflow 层**: 成熟可复用的工作流模板

### 5. 基础设施

- **ContextManager**: 瘦执行上下文管理
- **LogService**: ExecutionTrace 记录
- **TemplateRegistry**: Workflow 模板库
- **TestCaseStore**: 测试用例存储
- **SessionManager**: 会话管理
- **MemoryStore**: 长期记忆系统

## 数据流

### 执行流程

```
用户任务
  ↓
执行 Agent (任务规范化)
  ↓
ContextManager (初始化瘦上下文)
  ↓
React 循环:
  - LLM 决策
  - 能力解析与验证
  - 能力执行
  - 上下文更新
  - 日志记录
  ↓
任务完成
  ↓
LogService (保存 ExecutionTrace)
  ↓
审计 Agent (可选)
  ↓
编排 Agent 模式 B (可选，提取 Workflow)
```

### 审计流程

```
ExecutionTrace
  ↓
审计 Agent (构建审计 Case)
  ↓
监督 LLM 评估
  ↓
生成 AuditReport
  ↓
如果通过且可升级 → 编排 Agent 模式 B
```

## 设计原则

1. **单执行 Agent**: 唯一在线执行者，所有工具调用都经过它
2. **瘦上下文 + 完整日志**: 上下文只存必要信息，完整行为记录在日志中
3. **三层能力栈**: Atomic/Skill/Workflow，LLM 只能调度已有能力
4. **Workflow 作为高阶工具**: 优先使用，但可偏离，需记录原因
5. **职责分离**: 编排负责设计，执行负责运行，审计负责监督
6. **结构化协议**: 所有 Agent 间通信使用严格 JSON Schema
7. **可审计可追溯**: 所有决策和调用都有日志，支持事后审计

## 性能要求

根据 SPEC.md 的验收标准：

- 上下文管理操作 < 10ms
- 日志查询 < 100ms
- 能力匹配 < 50ms
- 执行 Agent 单步执行 < 5s（不含 LLM 调用）

## 扩展性

系统设计支持：

- 添加新的 Atomic 工具（通过 ToolRegistry 自动发现）
- 添加新的 Skill 能力（组合现有工具）
- 添加新的 Workflow 模板（从成功执行中提取）
- 添加新的通信渠道（实现 BaseChannel 接口）

## 参考

详细设计规范见 `SPEC.md`。
