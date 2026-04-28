---
layout: post
title: "CLI 管道模型在 AI Agent 中的落地：Skills 与 Tools 的对接机制"
date: 2026-04-21 10:04:00 +0800
---

Sign-off-by: 难易

Assisted-by: OpenClaw:minimax/M2.7

---

上一篇文章讲了 CLI 思维的价值。但一个关键问题没有回答：**CLI 管道模型在 AI Agent 中到底是怎么落地的？Skills 和 Tools 扮演什么角色？它们如何对接？**

本文深入 OpenCode 源码，拆解实际的实现机制。

## 整体架构：三层分离

OpenCode 的工具系统分为三层：

```
┌─────────────────────────────────────────┐
│           Agent 调度层                  │
│   （理解任务 → 决定调用哪些工具 → 组合结果）  │
├─────────────────────────────────────────┤
│         Tool 执行层（工具注册表）         │
│  BashTool / GrepTool / ReadTool / SkillTool  │
├─────────────────────────────────────────┤
│         进程执行层（CLI 管道）            │
│   child_process / shell / stdin/stdout   │
└─────────────────────────────────────────┘
```

**Skills 并不直接执行命令**。Skills 是**描述层**，Tools 是**执行层**。两者通过 Agent 的调度层解耦。

## 第一层：Tool Registry —— 工具的注册与发现

OpenCode 的所有工具通过 `registry.ts` 集中注册：

```typescript
// tool/registry.ts
import { BashTool } from "./bash"
import { GrepTool } from "./grep"
import { ReadTool } from "./read"
import { SkillTool } from "./skill"
import { GlobTool } from "./glob"
// ... 更多工具

export const tools = [
  BashTool,
  GrepTool,
  ReadTool,
  WriteTool,
  GlobTool,
  EditTool,
  SkillTool,
  // ...
]
```

**关键设计**：每个工具都是 `Tool.define(name, factory)` 的产物，返回 `ToolDefinition`。注册表持有这些定义，Agent 在运行时查询可用工具列表。

```typescript
// 工具定义的通用接口
export const Tool.define = (name: string, factory: () => ToolFactory) => {
  return {
    name,
    description: "...",      // 供 Agent 理解用途
    parameters: z.object({})  // 参数 Schema
    execute: (params, ctx) => Effect  // 实际执行逻辑
  }
}
```

## 第二层：Skill Tool —— 技能如何被发现和加载

Skill 系统负责**发现**和**加载**技能，但不负责执行。

```typescript
// tool/skill.ts
export const SkillTool = Tool.define("skill", () => {
  return {
    description: DESCRIPTION,
    parameters: Parameters,  // { name: string }
    execute: (params, ctx) =>
      Effect.gen(function* () {
        // 1. 从 Skill Service 获取技能信息
        const info = yield* skill.get(params.name)
        
        // 2. 请求用户授权（ask 机制）
        yield* ctx.ask({ permission: "skill", patterns: [params.name] })
        
        // 3. 扫描技能目录，返回文件列表
        const files = yield* rg.files({ cwd: dir }).pipe(
          Stream.take(limit),
          Stream.runCollect
        )
        
        // 4. 返回技能内容给 Agent
        return {
          output: [
            `<skill_content name="${info.name}">`,
            info.content.trim(),  // SKILL.md 的全文
            `Base directory: ${base}`,
            "<skill_files>",
            files,
            "</skill_files>",
            "</skill_content>"
          ].join("\n")
        }
      })
  }
})
```

**Skill Tool 的输出不是执行结果，而是技能的定义和上下文**。Agent 拿到这些信息后，再决定如何调用 Tools。

## 第三层：Bash Tool —— 真正的 CLI 管道执行

Bash Tool 是 OpenCode 中**最核心的执行器**。它启动独立进程，通过 stdin/stdout 与 AI Context 隔离。

```typescript
// tool/bash.ts
export const BashTool = Tool.define("bash", () => {
  return {
    parameters: Parameters,  // { command, timeout, workdir, description }
    execute: (params, ctx) =>
      Effect.gen(function* () {
        // 1. 解析命令（tree-sitter 解析 shell 语法）
        const root = yield* parse(params.command, ps)
        
        // 2. 扫描命令涉及的文件路径（安全审计）
        const scan = yield* collect(root, cwd, ps, shell)
        
        // 3. 请求权限
        yield* ask(ctx, scan)
        
        // 4. 启动子进程执行命令
        const handle = yield* spawner.spawn(
          cmd(shell, name, params.command, cwd, env)
        )
        
        // 5. 流式处理输出（不等待完整结果）
        yield* Effect.forkScoped(
          Stream.runForEach(Stream.decodeText(handle.all), (chunk) => {
            // 每 chunk 都实时推送给 Context
            return ctx.metadata({ metadata: { output: chunk } })
          })
        )
        
        // 6. 返回最终结果（可能被截断）
        return { output, metadata: { exit: code } }
      })
  }
})
```

**关键机制**：

1. **`handle.all` 是流式的**：`Stream.decodeText(handle.all)` 将进程输出作为流处理，每产生一行就推送给 Agent
2. **`ctx.metadata` 实时反馈**：即使命令还在执行，Agent 也能看到中间输出
3. **超时和中止支持**：`ctx.abort` 信号可以强制终止进程

## 管道是如何组装的

**案例：Agent 需要搜索包含 "TODO" 的文件列表**

**Agent 的思维链**：

```
用户问：哪些文件包含 TODO？
1. 我需要用 grep 搜索 "TODO"
2. grep 输出是文件路径 + 行号
3. 我只需要文件路径，不需要文件内容
4. 可以用 grep + cut 管道只取路径
```

**Agent 生成的命令**：

```
grep -rn "TODO" . --include="*.ts" | cut -d: -f1 | sort -u
```

**Bash Tool 的执行**：

```
┌─────────────────────────────────────────┐
│  进程：grep -rn "TODO" . --include="*.ts"  │
│  stdout: "src/a.ts:10:TODO: fix bug"   │
│          "src/b.ts:5:TODO: refactor"    │
└──────────────────┬──────────────────────┘
                   ↓管道
┌─────────────────────────────────────────┐
│  进程：cut -d: -f1                      │
│  输入：stdout of grep                   │
│  输出："src/a.ts"                       │
│        "src/b.ts"                       │
└──────────────────┬──────────────────────┘
                   ↓管道
┌─────────────────────────────────────────┐
│  进程：sort -u                          │
│  输入：stdout of cut                    │
│  输出："src/a.ts"                       │
│        "src/b.ts"                       │
└─────────────────────────────────────────┘
```

**最终进入 AI Context 的只有**：

```
src/a.ts
src/b.ts
```

**完整文件内容从未进入 Context**。

## Skills 如何引导 Agent 使用管道

Skill 的价值在于**告诉 Agent 这个场景下应该用什么管道**。

```markdown
# blog-writer skill (SKILL.md)
name: blog-writer
description: "博客写作技能。用于创建、编辑、维护技术博客..."

## 使用规范

### 发布流程
1. 提交文章到 _posts/ 目录
2. 创建新分支
3. push 后检查 GitHub Actions 状态

### 常用命令
git add _posts/YYYY-MM-DD-*.md && git commit -m "..."
git push origin blog/daily-YYYY-MM-DD-*
```

**Agent 读取 Skill 后**，它的上下文里就有了这个"最佳实践"。当用户说"帮我发布博客"时：

```
Agent:
  1. 调用 SkillTool("blog-writer") → 获取发布流程
  2. 按流程生成 git 命令
  3. 调用 BashTool 执行 git 命令
  4. 调用 BashTool("gh pr create ...") 创建 PR
```

Skill 不是工具，是**指导 Agent 行为的 prompt 片段**。

## 对接机制的核心：Effect 框架

OpenCode 用 `effect` 框架（一个 TypeScript 响应式库）统一管理工具的执行。

```typescript
// 工具调用的响应式链条
const result = yield* skill.get(name)         // 获取技能
  .pipe(Effect.flatMap(info => ...))            // 处理技能内容
  .pipe(Effect.map(output => ...))              // 格式化输出
```

**Effect 的优势**：

1. **声明式**：描述"做什么"而不是"怎么做"
2. **可组合**：`flatMap`、`map`、`zip` 可以组合工具
3. **并发友好**：`Effect.forkScoped` 可以并行执行多个工具
4. **错误处理统一**：所有工具错误通过 `Effect.orDie` 统一捕获

## Skills MCP 双轨的实际分工

OpenCode 的 MCP 和 Skills 不是竞争关系，是不同层次的扩展：

| 维度 | Skills | MCP |
|------|--------|-----|
| 层级 | 描述层（prompt 片段） | 协议层（工具调用协议） |
| 触发 | Agent 主动加载 | Agent 被动发现 |
| 数据格式 | SKILL.md 文本 | JSON-RPC 请求/响应 |
| 执行 | 通过 BashTool 调用 CLI | MCP Server 独立执行 |
| 用途 | 指导 Agent 行为模式 | 扩展 Agent 可调用的工具 |

**MCP Server 本质上是一个长期的 CLI 进程**，通过协议接收命令、返回结果。Skills 描述的是"在什么场景下调用什么工具、用什么参数"。

## 为什么这样的架构是合理的

**分离关注点**：

```
Skills（人写） → 告诉 Agent 什么时候用什么工具
Tool Registry → 定义有哪些工具可用
Bash Tool → 具体怎么执行命令
Process Layer → 命令如何与系统交互
```

**好处**：

1. **Skills 可以是纯 Markdown**，不需要编程知识就能写
2. **Tools 是标准化的**，不管 Bash、Grep、Read，实现接口一致
3. **Agent 调度层不需要关心底层细节**，只管组合
4. **进程隔离保证安全**，任何工具崩溃不影响 Agent

## 局限性与改进方向

**当前局限**：

1. **管道是 Agent 生成的字符串**，依赖 Agent 理解 shell 语法
2. **流式输出受限于 token 推送速度**，大量输出时仍有 Context 压力
3. **Tools 之间无状态共享**，需要通过文件系统中转

**可能的改进**：

1. **声明式管道**：Skills 描述管道而不是单独命令，Agent 只负责填参数
2. **流式结果索引**：输出不直接进 Context，而是写入临时文件，只传引用
3. **Tool 间通信协议**：让 Tools 可以直接交换数据，不需要都经过 Agent

</div>

</div>

<!-- series: OpenCode 学习系列 -->
<div class="series-nav">
    <span class="series-label">系列：OpenCode 学习系列</span>
    <div class="series-links">
        <a href="/2026/04/21/effect-framework-vs-harness/" class="nav prev">← Effect 框架 vs Harness：两种不同的 Agent 编程范式</a> &nbsp;|&nbsp; <a href="/2026/04/22/tool-calling-mechanism/" class="nav next">工具调用机制对比：Claude Code vs OpenCode →</a>
    </div>
</div>

---

## 参考资料

1. [OpenCode 源码：tool/registry.ts](https://github.com/anomalyco/opencode/tree/main/packages/opencode/src/tool)
2. [OpenCode 源码：tool/bash.ts](https://github.com/anomalyco/opencode/blob/main/packages/opencode/src/tool/bash.ts)
3. [OpenCode 源码：tool/skill.ts](https://github.com/anomalyco/opencode/blob/main/packages/opencode/src/tool/skill.ts)
4. [Effect Framework](https://effect.website/)
5. [OpenCode 源码：skill/discovery.ts](https://github.com/anomalyco/opencode/blob/main/packages/opencode/src/skill/discovery.ts)
