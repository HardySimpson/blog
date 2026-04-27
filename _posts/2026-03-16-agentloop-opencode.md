---
layout: post
title: "OpenCode 学习：AgentLoop 核心代码模块拆解"
date: 2026-03-16 10:00:00 +0800
---

Sign-off-by: 难易
Assisted-by: OpenClaw:minimax/M2.7

## 一、为什么要研究 AgentLoop？

对于当前比较火的 Agent 编程来说，底层的逻辑其实相当直接：**不断把问题提给 LLM 大模型，获取答案，并调用工具执行**。

核心代码可能就几百行，但充分把大模型的能力发挥出来，用于支撑所有业务场景。

## 二、AgentLoop 核心循环

OpenCode 的核心 AgentLoop 代码位于 `session/prompt.ts`。

### 2.1 主循环伪代码

```typescript
// session/prompt.ts - 核心循环
async function agentLoop(sessionID, resume_existing) {
  // 1. 初始化或恢复会话
  const abort = resume_existing ? resume(sessionID) : start(sessionID)
  
  // 2. 主循环
  while (true) {
    // 2.1 获取消息
    const msgs = await MessageV2.stream(sessionID)
    
    // 2.2 识别任务（子任务/压缩任务）
    const tasks = identifyTasks(msgs)
    
    // 2.3 处理任务
    if (tasks.subtask) { /* 执行子任务 */ continue }
    if (tasks.compaction) { /* 执行压缩 */ continue }
    
    // 2.4 正常处理：调用 LLM
    const result = await processor.process({
      user: lastUser,
      agent,
      system,  // 系统提示
      messages: MessageV2.toModelMessages(msgs, model),
      tools,
      model
    })
    
    if (result === "stop") break
    if (result === "compact") { /* 触发压缩 */ }
  }
  
  // 3. 清理并返回
  SessionCompaction.prune({ sessionID })
  return lastAssistantMessage
}
```

### 2.2 关键模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 会话管理 | `session/session.ts` | 会话创建、恢复、状态管理 |
| 消息处理 | `session/message-v2.ts` | 消息流、版本管理 |
| 循环入口 | `session/prompt.ts` | AgentLoop 主循环 |
| 处理器 | `session/processor.ts` | LLM 调用、工具执行 |
| 压缩 | `session/compaction.ts` | 上下文溢出处理 |

## 三、消息处理与任务识别

### 3.1 消息结构

```typescript
interface MessageV2 {
  id: string
  role: "user" | "assistant" | "system"
  parts: Part[]
  info: {
    agent?: string
    model?: string
    tokens?: number
    summary?: string
  }
}
```

### 3.2 任务类型

```typescript
type Task = 
  | { type: "subtask", model: ModelIdentifier }
  | { type: "compaction", auto: boolean, overflow: boolean }
```

## 四、源码参考

### 核心文件

1. **[session/prompt.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/prompt.ts)** - AgentLoop 主循环
2. **[session/message-v2.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/message-v2.ts)** - 消息类型定义
3. **[session/processor.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/processor.ts)** - 消息处理器
4. **[session/compaction.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/compaction.ts)** - 上下文压缩
5. **[session/session.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/session.ts)** - 会话管理

### 相关文件

6. **[agent/agent.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/agent/agent.ts)** - Agent 定义
7. **[tool/tool.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts)** - 工具框架
8. **[snapshot/index.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/snapshot/index.ts)** - 变更快照

## 五、核心技术特点

1. **异步处理**：使用 async/await 处理异步操作
2. **状态管理**：通过 state() 函数维护会话状态
3. **资源清理**：使用 defer() 确保会话结束时清理资源
4. **任务分离**：子任务和压缩任务独立处理
5. **流式处理**：支持消息流式输出

## 六、总结

AgentLoop 是 OpenCode 的核心，理解它的结构有助于：
- 理解 AI Agent 的基本工作原理
- 排查会话相关问题
- 基于 OpenCode 构建自己的 Agent 系统

</div>

<!-- series: OpenCode 学习系列 -->
<div class="series-nav">
    <span class="series-label">系列：OpenCode 学习系列</span>
    <div class="series-links">
        <a href="/2026/03/16/agent-workflow-explanation/" class="nav prev">← OpenCode 学习：Agent工作流程通俗解释</a> &nbsp;|&nbsp; <a href="/2026/03/19/agent-research-report/" class="nav next">OpenCode 学习：Agent在人-代码库-LLM对话中的角色调研报告 →</a>
    </div>
</div>

---

## 七、参考资料

1. [OpenCode 源码：session/prompt.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/prompt.ts)
2. [OpenCode 源码：session/message-v2.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/message-v2.ts)
3. [OpenCode 源码：session/processor.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/processor.ts)
4. [OpenCode 源码：session/compaction.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/compaction.ts)
5. [OpenCode 源码：session/session.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/session.ts)
6. [OpenCode 源码：agent/agent.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/agent/agent.ts)
7. [OpenCode 源码：tool/tool.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts)
8. [OpenCode 源码：snapshot/index.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/snapshot/index.ts)
