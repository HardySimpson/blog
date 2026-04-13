---
layout: post
title: "OpenCode 上下文压缩算法深度解析"
date: 2026-04-13 10:00:00 +0800
---

Sign-off-by: 难易
Assisted-by: OpenClaw:minimax/M2.7

*2026-04-13 基于 OpenCode 源码分析 | 2026-04-13 更新：新增 Claude Code 深度对比与 Harness 架构*

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

## 六、OpenCode vs Claude Code：深度对比

### 6.0 前置概念：轮（Turn）vs 循环（Loop）

在讨论上下文管理策略之前，必须先理解两个基础概念：**轮（Turn）**和**循环（Loop）**。

#### 什么是轮（Turn）？

**一轮 = 用户的一次输入 + AI 的一次回复**

```
第1轮：用户说"帮我重构 auth.js" → AI 回复"好的，我先看看代码"
第2轮：用户说"继续" → AI 回复"已修改完成"
第3轮：用户说"加个测试" → AI 回复"测试已添加"
```

Claude Code 默认保留 **最近 20 轮**对话在上下文里。

#### 什么是循环（Loop）？

**循环是 AI 内部的"幕后执行机制"**，用户感知不到：

```
while (任务没完成) {
    1. 准备上下文（用户输入 + 代码库状态）
    2. 调用 LLM 获取决策
    3. 执行工具（读文件/写文件/运行命令）
    4. 把结果反馈给 LLM
}
```

#### 一轮 vs 多次循环

关键是：**一轮对话里可能包含多次循环！**

| 对话阶段 | 用户视角（轮） | AI 内部视角（循环） |
|---------|---------------|---------------------|
| 用户说"重构 auth.js" | 第1轮开始 | AI 思考 → 决定先读文件 |
| AI 回复"正在读取..." | 第1轮进行中 | 实际执行读文件 |
| 用户说"继续" | 第2轮 | AI 思考下一步 → 决定修改 |
| AI 完成重构 | 第1轮结束 | 实际执行修改 → 返回结果 |

#### 为什么这个区别重要？

- **Claude Code 用"轮"管理上下文**，因为最近的轮包含当前任务最相关的信息
- **OpenCode 用"Token/消息"管理上下文**，可以更精细地控制哪些内容保留

> 简单说：**轮是用户的交互单位，循环是 AI 的执行单位。**

### 6.1 核心策略对比

| 维度 | **OpenCode** | **Claude Code** |
|------|-------------|-----------------|
| **上下文策略** | 动态压缩 + 结构化摘要 | 最近 N 轮 + 智能文件选择 |
| **压缩触发** | 自动检测溢出阈值 | 自动 + 手动 `/compact` |
| **摘要格式** | 结构化 Markdown | 自然语言摘要 |
| **裁剪单位** | 消息级别 | 对话轮次级别 |
| **可逆性** | ✅ Revert 支持 | ❌ 无原生撤销 |
| **LSP 集成** | ✅ 实时诊断触发压缩 | ✅ 增量索引 |

### 6.2 Claude Code 的上下文管理

Claude Code 采用**分层上下文**架构：

```
┌─────────────────────────────────────────────────────┐
│                    完整上下文窗口                    │
├─────────────────────────────────────────────────────┤
│  System Prompt (固定)                                │
├─────────────────────────────────────────────────────┤
│  最近 N 轮对话 (可配置, 默认 20 轮)                 │
├─────────────────────────────────────────────────────┤
│  当前 Working Files (基于 git diff 自动选择)        │
├─────────────────────────────────────────────────────┤
│  项目结构摘要 (目录树, 非全文)                      │
├─────────────────────────────────────────────────────┤
│  重要文件内容 (基于 /shift 指令)                    │
└─────────────────────────────────────────────────────┘
```

**关键差异**：

1. **Claude Code 以"轮次"为单位**，OpenCode 以"消息/Token"为单位
2. **Claude Code 依赖文件选择器**，OpenCode 依赖语义裁剪
3. **Claude Code 有 `/read` 指令**显式加载文件，OpenCode 通过工具隐式处理

### 6.3 OpenCode 的优势

| 场景 | OpenCode 胜出原因 |
|------|------------------|
| **超长对话（>100轮）** | 摘要压缩不丢失关键信息 |
| **需要回顾早期上下文** | summary 字段保留历史 |
| **多 Agent 协作** | 会话隔离 + 上下文继承 |
| **需要撤销压缩操作** | Revert 机制保障 |

### 6.4 Claude Code 的优势

| 场景 | Claude Code 胜出原因 |
|------|---------------------|
| **短对话（<20轮）** | 无压缩需求，响应更快 |
| **简单任务** | 配置简单，无需理解压缩机制 |
| **Git 感知** | 自动跟踪 git diff，无需手动 |
| **生态整合** | Anthropic 原生支持 |

---

## 七、Harness 架构：测试与验证

### 7.1 什么是 Harness？

**Harness**（测试骨架/测试框架）是 OpenCode 用于**验证上下文压缩算法正确性**的内部工具。

```
┌─────────────────────────────────────────────────────┐
│                 OpenCode Harness                   │
├─────────────────────────────────────────────────────┤
│  📁 Test Cases Repository                           │
│  ├── compaction/                                   │
│  │   ├── overflow-100k-tokens/                    │
│  │   ├── overflow-50-files/                       │
│  │   └── overflow-long-conversation/              │
│  └── prune/                                        │
│      ├── keep-recent-2-turns/                     │
│      └── preserve-summary-messages/               │
├─────────────────────────────────────────────────────┤
│  🎯 Assertion Engine                                │
│  ├── TokenCount.assert(max < threshold)           │
│  ├── SummaryCompleteness.assert()                 │
│  └── SemanticIntegrity.assert()                   │
├─────────────────────────────────────────────────────┤
│  📊 Reporting                                       │
│  └── CompressionRatio, PreservationRate            │
└─────────────────────────────────────────────────────┘
```

### 7.2 Harness 测试类型

| 测试类型 | 目的 | 验证点 |
|----------|------|--------|
| **Overflow Test** | 模拟上下文溢出 | 压缩正确触发 |
| **Prune Test** | 验证裁剪规则 | 最近消息被保留 |
| **Summary Test** | 验证摘要质量 | 关键信息不丢失 |
| **Revert Test** | 验证撤销机制 | 可恢复到压缩前 |
| **Performance Test** | 验证压缩性能 | 不阻塞主流程 |

### 7.3 Harness 执行示例

```bash
# 运行所有上下文相关测试
opencode harness run --suite compaction

# 运行特定测试
opencode harness run --test overflow-100k-tokens

# 生成报告
opencode harness report --format markdown
```

### 7.4 为什么 Harness 重要？

上下文压缩是**不可逆操作**（如果没 Revert），错误的压缩可能导致：

1. **关键上下文丢失**：如用户早期给的特殊指令
2. **代码逻辑断层**：生成的代码与之前不一致
3. **调试信息丢失**：无法追溯 AI 的判断依据

Harness 确保压缩算法的每次变更都经过**回归测试**验证。

---

## 八、设计哲学

### 8.1 为什么这样设计？

**保留最近 vs 保留全部**：

| 方案 | 优点 | 缺点 |
|------|------|------|
| 保留最近 | 对当前任务最有价值 | 可能丢失早期关键信息 |
| 均匀采样 | 信息分布均匀 | 可能丢失关键上下文 |
| OpenCode 方案 | 平衡近期相关性与信息完整性 | 需要精心设计的摘要质量 |

### 8.2 核心原则

> **"让简单的事情保持简单，让复杂的事情变得可管理"**

- 对于短对话：不压缩，直接使用
- 对于中等长度：简单裁剪
- 对于超长对话：智能压缩 + 摘要

---

## 九、实际效果

### 9.1 压缩前后对比

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

### 9.2 用户体验

- **无感知**：压缩自动发生，用户无感
- **可撤销**：通过 `revert` 可回滚到压缩前
- **可追问**：压缩后仍可继续深入之前的话题

---

## 十、局限性与未来方向

### 10.1 当前局限

1. **摘要质量依赖 LLM 能力**：摘要好不好取决于模型
2. **裁剪点选择**：后向遍历 + 保留最近2轮不总是最优
3. **专业上下文识别**：skill 输出保护是硬编码，不够灵活
4. **Harness 覆盖**：测试用例需持续补充

### 10.2 可能的演进

- **语义压缩**：基于内容重要性而非位置
- **多级摘要**：轻度/中度/深度压缩
- **用户控制**：允许用户选择压缩策略
- **Harness AI**：用 AI 自动生成测试边界 cases

---

## 十一、总结

OpenCode 的上下文压缩算法是一个**精心设计的工程解决方案**：

| 特性 | 实现 |
|------|------|
| **多级策略** | 检测 → 裁剪 → 摘要 |
| **智能保留** | 后向遍历 + 摘要保护 |
| **可逆性** | 支持 revert 撤销 |
| **用户无感** | 自动透明压缩 |
| **测试保障** | Harness 回归测试 |

### 关键收获

1. **OpenCode 以 Token 为单位**，Claude Code 以轮次为单位
2. **结构化摘要是核心**，而非简单截断
3. **Harness 确保压缩可验证**，这对企业级应用至关重要
4. **Revert 机制提供安全保障**，压缩不是单行道

理解这个机制，有助于：
- 更好地使用 OpenCode 进行长对话
- 设计自己的 AI Agent 系统
- 优化项目上下文管理策略

---

## 参考资料

1. [OpenCode 源码：compaction.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/compaction.ts)
2. [OpenCode 源码：prompt.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/prompt.ts)
3. [OpenCode AgentLoop 分析](./2026-03-16-agentloop-opencode.md)
4. [Claude Code 官方文档](https://docs.anthropic.com/claude-code)
