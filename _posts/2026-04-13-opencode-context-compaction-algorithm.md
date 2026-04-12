---
layout: post
title: "OpenCode 上下文压缩算法深度解析"
date: 2026-04-13 10:00:00 +0800
---

Sign-off-by: 难易
Assisted-by: OpenClaw:minimax/M2.7

# OpenCode 上下文压缩算法深度解析

*2026-04-13 基于 OpenCode 源码分析*

---

## 一、核心问题：上下文溢出

### 1.1 LLM 的 token 限制

现代 LLM 有严格的上下文窗口限制：

| 模型 | 上下文窗口 | 实际可用（含预留）|
|------|-----------|-----------------|
| GPT-4o | 128K tokens | ~120K |
| Claude 3.5 | 200K tokens | ~180K |
| Gemini 1.5 | 1M tokens | ~900K |

对于动辄几十万行的代码库，这个限制远远不够。

### 1.2 OpenCode 的溢出检测

```typescript
// compaction.ts - 核心检测逻辑
export async function isOverflow(input: {
  tokens: MessageV2.Assistant["tokens"]
  model: Provider.Model
}) {
  const context = input.model.limit.context      // 模型上下文限制
  const count = input.tokens.total               // 已使用的 token 总数
  const usable = input.model.limit.input - reserved  // 实际可用 token
  
  return count >= usable  // 超过阈值时触发压缩
}
```

**触发条件**：
- 已使用 token 数 ≥ 实际可用 token 数
- 预留 `reserved` 通常为 2000-4000 tokens，用于容纳系统响应

---

## 二、压缩策略：智能裁剪

### 2.1 裁剪原则

OpenCode 采用**后向遍历、保留最近**的策略：

```
┌─────────────────────────────────────────────────────┐
│ 消息历史                                           │
├─────────────────────────────────────────────────────┤
│ [最旧] ████████░░░░░░░░░░░░░░░░░░░░░ [最新]      │
│        ↓                                           │
│        ═══════ 超过 40K tokens 的部分被裁剪       │
│                                                     │
│ 保留最近 2 轮完整对话 + 最新用户输入              │
└─────────────────────────────────────────────────────┘
```

### 2.2 裁剪规则详解

```typescript
// 裁剪优先级（从高到低）
1. 用户最新输入（当前任务核心）
2. 最近 2 轮完整对话（保持上下文连贯性）
3. 已压缩过的摘要（summary 字段）
4. 工具调用结果（文件修改、命令输出）
5. 更早的历史消息
```

**关键保护机制**：
- 有 `summary` 的消息停止裁剪（已提炼过关键信息）
- `skill` 工具的输出不被裁剪（重要上下文）
- 系统消息和系统提示词永远保留

---

## 三、Compaction 流程：生成摘要

### 3.1 什么时候触发 Compaction？

不是每次溢出都触发 compaction。OpenCode 的判断逻辑：

| 条件 | 动作 |
|------|------|
| 仅溢出，无其他问题 | 简单裁剪（prune） |
| 溢出 + 对话过长 | 触发 compaction 生成摘要 |
| 用户主动请求 | `/compact` 命令 |

### 3.2 Compaction Prompt

当需要生成摘要时，OpenCode 调用专门的 compaction agent：

```typescript
const defaultPrompt = `Provide a detailed prompt for continuing our conversation above.
Focus on:
- What goal(s) is the user trying to accomplish?
- What important instructions did the user give?
- What notable things were learned?
- What work has been completed?
- Relevant files / directories`
```

这个 prompt 引导 LLM 生成**结构化的会话摘要**，而非简单截断。

### 3.3 摘要内容结构

生成的摘要包含：

```
## 任务目标
用户正在尝试完成...

## 重要指令
- 指令1
- 指令2

## 关键发现
- 发现了什么
- 学习了什么是重要的

## 已完成工作
1. 步骤1
2. 步骤2

## 相关文件/目录
- /path/to/file1
- /path/to/dir2
```

---

## 四、技术实现细节

### 4.1 消息结构

```typescript
interface MessageV2 {
  id: string
  role: "user" | "assistant" | "system"
  parts: Part[]
  info: {
    agent?: string
    model?: string
    tokens?: number
    summary?: string  // 压缩后的摘要
  }
}
```

### 4.2 Token 计算

```typescript
// token 计算考虑因素
interface TokenCount {
  prompt_tokens: number      // 输入 token
  completion_tokens: number   // 输出 token  
  total: number              // 总计
  reserved: number           // 预留空间
}
```

### 4.3 压缩执行流程

```
1. 检测溢出 → isOverflow() 返回 true
2. 识别压缩点 → 找到合适的裁剪位置
3. 后向遍历 → 从最新消息向前遍历
4. 决定保留/裁剪 → 基于规则判断
5. 生成摘要 → compaction agent 处理
6. 替换消息 → 原始消息 → 摘要消息
7. 继续对话 → 使用压缩后的上下文
```

---

## 五、源码关键文件

| 文件 | 职责 |
|------|------|
| `session/compaction.ts` | 核心压缩算法：溢出检测、裁剪、摘要生成 |
| `session/prompt.ts` | 调用 compaction 的入口 |
| `session/message-v2.ts` | 消息类型定义 |
| `session/revert.ts` | 支持撤销压缩操作 |

---

## 六、设计哲学

### 6.1 为什么这样设计？

**保留最近 vs 保留全部**：

| 方案 | 优点 | 缺点 |
|------|------|------|
| 保留最近 | 对当前任务最有价值 | 可能丢失早期关键信息 |
| 均匀采样 | 信息分布均匀 | 可能丢失关键上下文 |
| OpenCode 方案 | 平衡近期相关性与信息完整性 | 需要精心设计的摘要质量 |

### 6.2 核心原则

> **"让简单的事情保持简单，让复杂的事情变得可管理"**

- 对于短对话：不压缩，直接使用
- 对于中等长度：简单裁剪
- 对于超长对话：智能压缩 + 摘要

---

## 七、与其他系统的对比

| 系统 | 上下文策略 |
|------|-----------|
| **OpenCode** | 动态压缩 + 摘要生成 |
| **Claude Code** | 最近 N 轮 + 重要文件 |
| **Cursor** | 相似上下文检索 |
| **Copilot** | 混合：项目感知 + 语义检索 |

---

## 八、实际效果

### 8.1 压缩前后对比

```
压缩前：
- 100K tokens 历史消息
- 包含 50 个文件修改
- 30 轮对话

压缩后：
- 15K tokens 摘要
- 保留核心任务、关键发现、文件列表
- 可继续对话而不丢失关键上下文
```

### 8.2 用户体验

- **无感知**：压缩自动发生，用户无感
- **可撤销**：通过 `revert` 可回滚到压缩前
- **可追问**：压缩后仍可继续深入之前的话题

---

## 九、局限性与未来方向

### 9.1 当前局限

1. **摘要质量依赖 LLM 能力**：摘要好不好取决于模型
2. **裁剪点选择**：后向遍历 + 保留最近2轮不总是最优
3. **专业上下文识别**：skill 输出保护是硬编码，不够灵活

### 9.2 可能的演进

- **语义压缩**：基于内容重要性而非位置
- **多级摘要**：轻度/中度/深度压缩
- **用户控制**：允许用户选择压缩策略

---

## 十、总结

OpenCode 的上下文压缩算法是一个**精心设计的工程解决方案**：

1. **多级策略**：检测 → 裁剪 → 摘要
2. **智能保留**：后向遍历 + 摘要保护
3. **可逆性**：支持 revert 撤销
4. **用户无感**：自动透明压缩

理解这个机制，有助于：
- 更好地使用 OpenCode 进行长对话
- 设计自己的 AI Agent 系统
- 优化项目上下文管理策略

---

## 参考资料

1. [OpenCode 源码：compaction.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/compaction.ts)
2. [OpenCode 源码：prompt.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/prompt.ts)
3. [OpenCode AgentLoop 分析](./2026-03-16-agentloop-opencode.md)
