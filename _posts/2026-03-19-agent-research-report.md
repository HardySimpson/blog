---
layout: post
title: "OpenCode 学习：Agent在人-代码库-LLM对话中的角色调研报告"
date: 2026-03-19 13:00:00 +0800
---

Sign-off-by: 难易
Assisted-by: OpenClaw:minimax/M2.7

*本文档基于 OpenCode 项目的源代码分析编写*

## 一、为什么需要Agent？

### 1.1 核心问题

在没有Agent的情况下，用户直接与LLM交互会面临几个根本性挑战：

1. **LLM无法直接感知代码库状态**：LLM是"无状态"的，它不知道当前项目的结构、文件内容、已执行的命令等
2. **工具执行能力缺失**：LLM本身无法读写文件、运行命令，它只能生成文本
3. **缺乏长期记忆**：每次对话都是独立的，LLM无法记住之前操作过哪些文件
4. **权限控制空白**：无法限制LLM可以访问或修改哪些文件

### 1.2 Agent的桥梁作用

通过分析 [prompt.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/prompt.ts) 的 `loop` 函数可以看出，Agent构建了一个完整的**人-代码库-LLM对话循环**：

```typescript
// prompt.ts 中的核心循环
while (true) {
  // 1. 准备消息（包含用户输入 + 代码库上下文）
  const messages = await prepareMessages()
  
  // 2. 调用LLM获取响应
  const response = await LLM.stream({ messages })
  
  // 3. 执行LLM返回的工具调用
  const result = await processor.process(response)
  
  // 4. 将工具执行结果返回给LLM，继续对话
}
```

> 源码：[session/prompt.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/prompt.ts)

这个循环实现了：

- **上下文管理**：将代码库状态转换为LLM可理解的上下文
- **工具执行**：代表LLM实际执行文件读写、命令运行等操作
- **状态维护**：通过消息历史保持对话连续性
- **结果反馈**：将工具执行结果转换回LLM可理解的形式

### 1.3 分层架构

从 [system.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/system.ts) 可以看到，Agent还负责为不同LLM提供商适配不同的系统提示词：

```typescript
// system.ts - 为不同模型提供不同的系统提示
export function provider(model: Provider.Model) {
  if (model.api.id.includes("gpt-")) return [PROMPT_BEAST]
  if (model.api.id.includes("claude")) return [PROMPT_ANTHROPIC]
  if (model.api.id.includes("gemini-")) return [PROMPT_GEMINI]
  // ...
}
```

> 源码：[session/system.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/system.ts)

这种适配确保了：
- 各模型的能力得到充分发挥
- 遵循各模型的最佳实践
- 适配不同模型的输出格式要求

---

## 二、上下文取舍策略

### 2.1 核心挑战

对于几十万行代码的大型代码库，LLM的上下文窗口（通常128K到1M tokens）远不够容纳全部代码。Agent必须智能地选择"让LLM看到什么"。

### 2.2 OpenCode的上下文管理策略

通过分析 [compaction.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/compaction.ts)，我发现了以下策略：

#### 2.2.1 溢出检测

```typescript
// compaction.ts - 检测是否超过上下文限制
export async function isOverflow(input: { tokens: MessageV2.Assistant["tokens"]; model: Provider.Model }) {
  const context = input.model.limit.context
  const count = input.tokens.total  // 使用的token总数
  const usable = input.model.limit.input - reserved  // 可用输入token
  return count >= usable  // 超过阈值时触发压缩
}
```

> 源码：[session/compaction.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/compaction.ts)

#### 2.2.2 智能裁剪 (Pruning)

```typescript
// compaction.ts - 向后遍历，保留最近40k tokens的上下文
export async function prune(input: { sessionID: SessionID }) {
  // 从最新的消息向前遍历
  // 保留最近2轮的完整对话
  // 对于更早的工具调用输出，如果超过40k tokens则裁剪
}
```

> 源码：[session/compaction.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/compaction.ts)

关键策略：
- **保留最近对话**：最近2轮用户-助手对话保持完整
- **保留总结**：如果某条消息已经有summary（压缩后的摘要），则停止裁剪
- **保护特定工具**：如 `skill` 工具的输出不被裁剪

#### 2.2.3 上下文压缩 (Compaction)

当溢出发生时，Agent会调用专门的 `compaction` agent来生成摘要：

```typescript
// compaction.ts - 生成会话摘要
const defaultPrompt = `Provide a detailed prompt for continuing our conversation above.
Focus on:
- What goal(s) is the user trying to accomplish?
- What important instructions did the user give?
- What notable things were learned?
- What work has been completed?
- Relevant files / directories`
```

> 源码：[session/compaction.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/compaction.ts)

这相当于将长对话"压缩"为一个结构化的摘要，保留关键信息。

### 2.3 上下文选择原则

通过分析代码，Agent选择上下文的优先级是：

1. **用户最新输入**：当前任务的核心需求
2. **最近工具执行结果**：文件修改、命令输出等
3. **项目结构信息**：目录结构、关键配置文件
4. **相关代码片段**：通过检索找到的与任务相关的代码
5. **历史摘要**：经过压缩的历史会话信息

---

## 三、代码生成的保障机制

### 3.1 核心问题

为什么Agent不会"乱写代码"？为什么生成的代码"大致可运行"？这背后有多层保障机制。

### 3.2 多层保障体系

#### 3.2.1 权限控制系统 (PermissionNext)

从 [permission/index.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/permission/index.ts) 和相关代码可以看到，Agent有精细的权限控制：

```typescript
// agent.ts - Agent的默认权限配置
const defaults = PermissionNext.fromConfig({
  "*": "allow",
  doom_loop: "ask",           // 检测无限循环
  external_directory: {
    "*": "ask",                // 外部目录需要询问
  },
  read: {
    "*": "allow",
    "*.env": "ask",            // 敏感文件需要询问
  },
})
```

> 源码：[agent/agent.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/agent/agent.ts)

权限分类：
- **allow**：自动执行
- **ask**：需要用户确认
- **deny**：禁止执行

#### 3.2.2 LSP实时诊断

从 [write.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/write.ts) 可以看到，写入文件后立即进行LSP诊断：

```typescript
// write.ts - 写入后立即诊断
await Filesystem.write(filepath, params.content)
const diagnostics = await LSP.diagnostics()

// 将诊断结果返回给LLM
if (errors.length > 0) {
  output += `\nLSP errors detected in this file, please fix:\n<diagnostics>...`
}
```

> 源码：[tool/write.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/write.ts)

**输入**：
- 无显式输入参数（直接获取当前所有文件的诊断状态）
- 触发条件：文件被修改后，通过 `LSP.touchFile(filepath, true)` 通知LSP服务器该文件已变更

**输出**：
- 返回类型：`Record<string, Diagnostic[]>`
- 结构：键为文件路径，值为诊断信息数组
- 每条诊断信息包含：
  - `severity`: 严重程度（1=ERROR, 2=WARN, 3=INFO, 4=HINT）
  - `message`: 错误/警告消息内容
  - `range`: 错误位置（start/end line和character）

**处理流程**：
1. 文件写入后，调用 `LSP.touchFile()` 通知LSP服务器
2. LSP服务器分析文件，发送 `textDocument/publishDiagnostics` 通知
3. Agent收集所有诊断结果，按文件分组
4. 筛选出ERROR级别的问题（severity === 1）
5. 将诊断结果格式化后追加到工具输出中

**格式化输出示例**：
```
LSP errors detected in this file, please fix:
<diagnostics file="/path/to/file.ts">
ERROR [10:15] Cannot find name 'User' in type definition
ERROR [25:3] Property 'id' is missing in type 'Props'
</diagnostics>
```

这确保了：
- 语法错误被立即发现
- 类型错误在生成时就被捕获
- LLM可以立即修复刚引入的错误

#### 3.2.3 Doom Loop 检测

从 [processor.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/processor.ts) 可以看到防重复机制：

```typescript
// processor.ts - 检测重复的工具调用
const lastThree = parts.slice(-DOOM_LOOP_THRESHOLD)  // 最近3次

if (
  lastThree.length === DOOM_LOOP_THRESHOLD &&
  lastThree.every(p => 
    p.type === "tool" &&
    p.tool === value.toolName &&
    p.state.input === JSON.stringify(value.input)
  )
) {
  // 触发权限询问，防止无限循环
  await PermissionNext.ask({ permission: "doom_loop", ... })
}
```

> 源码：[session/processor.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/processor.ts)

这防止了Agent陷入重复调用同一工具的无限循环。

#### 3.2.4 Snapshot版本跟踪

从 [snapshot/index.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/snapshot/index.ts) 看到：

```typescript
// snapshot.ts - 跟踪文件变更
export async function track() {
  // 每次step开始时记录git snapshot
  const hash = await Process.text(["git", "write-tree"], ...)
  return hash.trim()
}
```

> 源码：[snapshot/index.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/snapshot/index.ts)

每个执行步骤都有快照记录，支持：
- 查看每个步骤修改了哪些文件
- 回滚到任意步骤的状态

#### 3.2.5 Revert回滚机制

从 [revert.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/revert.ts) 看到：

```typescript
// revert.ts - 支持撤销操作
export async function revert(input: RevertInput) {
  // 找到需要回滚的位置
  // 通过git snapshot恢复文件
  // 清理相关的消息历史
}
```

> 源码：[session/revert.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/revert.ts)

用户可以撤销任意步骤的操作，系统会：
- 恢复文件到之前的状态
- 清理对话历史中相关的部分

#### 3.2.6 工具输入验证

从 [tool.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts) 看到：

```typescript
// tool.ts - Zod schema验证
toolInfo.execute = async (args, ctx) => {
  try {
    toolInfo.parameters.parse(args)  // 验证输入
  } catch (error) {
    throw new Error(`Invalid arguments: ${error}`)
  }
  const result = await execute(args, ctx)
}
```

> 源码：[tool/tool.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts)

LLM生成的工具调用参数会经过严格验证，不符合schema的输入会被拒绝并要求重新生成。

### 3.3 保障机制总结

| 机制 | 作用 |
|------|------|
| 权限控制 | 控制能做什么、不能做什么 |
| LSP诊断 | 实时发现语法和类型错误 |
| Doom Loop检测 | 防止无限重复 |
| Snapshot跟踪 | 记录变更历史 |
| Revert回滚 | 允许撤销错误操作 |
| 输入验证 | 确保工具参数正确 |

这形成了一个完整的"安全网"，使得Agent不会乱写代码。

---

## 四、Agent的定位：薄胶水还是厚重workflow？

### 4.1 两种观点的来源

#### "薄胶水"观点
- Agent只是简单地传递消息
- 核心能力由LLM提供
- Agent不做复杂决策

#### "厚重workflow"观点  
- Agent有完整的对话管理
- 有复杂的权限系统
- 有状态维护、错误处理等

### 4.2 答案：两者兼有

通过分析源代码，**OpenCode的Agent既是"薄胶水"又是"厚重workflow"**：

#### "薄"的方面

1. **消息传递**：Agent确实在做用户↔LLM之间的消息传递
2. **工具执行代理**：代表LLM调用文件系统、Shell等工具
3. **轻量级架构**：没有过度复杂的workflow编排

```typescript
// prompt.ts - 核心循环其实很简洁
while (true) {
  const messages = await prepare()
  const stream = await LLM.stream(messages)
  await processor.process(stream)
}
```

#### "厚"的方面

1. **完整的权限系统**：55个文件涉及权限控制
2. **多层次的错误处理**：API错误、重试、优雅降级
3. **状态管理**：消息、会话、快照、revert点
4. **上下文管理**：压缩、裁剪、溢出处理
5. **安全机制**：Doom Loop检测、敏感文件保护

```typescript
// 权限系统复杂度示例 - agent.ts
const defaults = PermissionNext.fromConfig({
  "*": "allow",
  doom_loop: "ask",
  external_directory: { "*": "ask", ... },
  question: "deny",
  plan_enter: "deny",
  read: { "*": "allow", "*.env": "ask", ... },
})
```

### 4.3 设计哲学

OpenCode的Agent设计遵循了一个平衡原则：

> **让简单的事情保持简单，让复杂的事情变得可管理**

- 对于简单任务：Agent是透明的，用户直接与LLM交互
- 对于复杂任务：Agent提供安全网（权限、诊断、回滚）
- 对于超长对话：Agent智能压缩上下文

---

## 附录：源代码链接

### 核心文件

1. **对话循环**：[packages/opencode/src/session/prompt.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/prompt.ts)
   - 用户输入处理
   - 消息循环管理
   - 会话状态维护

2. **消息处理**：[packages/opencode/src/session/message-v2.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/message-v2.ts)
   - 消息类型定义
   - 消息结构

3. **LLM调用**：[packages/opencode/src/session/llm.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/llm.ts)
   - 流式响应处理
   - 系统提示构建

4. **处理器**：[packages/opencode/src/session/processor.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/processor.ts)
   - 工具调用执行
   - Doom Loop检测

5. **系统提示**：[packages/opencode/src/session/system.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/system.ts)
   - 不同模型的提示适配
   - 环境信息注入

### 上下文管理

6. **上下文压缩**：[packages/opencode/src/session/compaction.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/compaction.ts)
   - 溢出检测
   - 智能裁剪
   - 摘要生成

### 安全保障

7. **权限系统**：[packages/opencode/src/permission/index.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/permission/index.ts)
   - 权限规则定义
   - 权限检查

8. **Agent定义**：[packages/opencode/src/agent/agent.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/agent/agent.ts)
   - Agent类型定义
   - 权限配置

9. **快照跟踪**：[packages/opencode/src/snapshot/index.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/snapshot/index.ts)
   - Git快照记录
   - 变更追踪

10. **回滚机制**：[packages/opencode/src/session/revert.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/revert.ts)
    - 操作撤销
    - 状态恢复

### 工具执行

11. **工具框架**：[packages/opencode/src/tool/tool.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts)
    - 工具定义
    - 参数验证

12. **写入工具**：[packages/opencode/src/tool/write.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/write.ts)
    - 文件写入
    - LSP诊断集成

13. **LSP服务**：[packages/opencode/src/lsp/server.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/lsp/server.ts)
    - 语言服务集成
    - 实时诊断
