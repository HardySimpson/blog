---
layout: post
title: "AI Agent 编程范式：为什么 CLI 思维正在回归"
date: 2026-04-21 09:54:00 +0800
---

Sign-off-by: 难易

Assisted-by: OpenClaw:minimax/M2.7

---

AI Coding Agent 的扩展机制目前主要三条路：Skills（技能系统）、MCP（Model Context Protocol）、ACP（Agent Client Protocol）。但如果我们跳出"工具调用"这个思维定式，回归到**CLI 管道模型**，会发现一条被低估的路径。

## 为什么 CLI 思维在 AI 时代反而更重要了

传统的 CLI（命令行界面）有以下特征：
- **stdin/stdout/stderr** 标准化流接口
- **管道（Pipe）** 连接进程
- **文本流** 作为通用数据格式
- **进程隔离** 每个命令独立运行

这些特征在 AI Agent 场景下有独特的价值。

## 核心优势一：绕过 Context Token 限制

这是最关键的一点。

当前所有 AI 模型都有 Context 长度限制。Claude 3.5 支持 200K tokens，GPT-4o 支持 128K tokens，看起来很大。但当处理真实代码库时，这个限制很快就会被击穿：

- 一个中大型项目的代码总量轻松超过 1M tokens
- 大型日志文件往往有数百 MB
- CI 构建输出、测试覆盖率报告都可能很大

**传统工具调用的问题**：

```typescript
// 常见的工具调用方式
const result = await agent.callTool("grep", {
  pattern: "TODO",
  files: "**/*.ts"  // 需要把文件内容加载进 context
})
// 如果文件很大？token 爆了
```

**CLI 管道思维的核心**：数据不需要进入 AI 的 Context。数据通过管道流到专门的处理程序，结果以结构化文本输出。

```
# grep 的管道模型
find . -name "*.ts" | xargs grep "TODO" | head -100
#                        ↑ grep 处理文件
#        ↑ find 输出文件列表（不是内容）
#                                              ↑ head 限制结果量
# AI 只处理最终的结构化结果，不需要看到整个文件
```

**在 Agent 中的等价实现**：

```
用户问：有哪些文件包含 TODO？
Agent 执行：
  1. 启动 grep process（独立进程，不占用 context）
  2. grep 通过管道返回文件路径和行号
  3. 只有结构化结果进入 AI 决策流程
  4. 完整文件内容从不进入 context
```

这样做的好处：**无论代码库有多大，AI 处理的始终只是它需要的摘要信息**。

## 核心优势二：流式处理与背压

管道天然支持流式处理。数据以行为单位流动，不需要等待"完整输入"。

```
tail -f /var/log/app.log | grep ERROR | awk '{print $1, $2, $5}'
#                ↑ 实时流          ↑ 过滤        ↑ 格式化
# 每行数据处理完立即输出，不等整个日志结束
```

在 AI Agent 场景：
- **长任务实时反馈**：代码生成任务可以边生成边展示
- **背压控制**：如果下游处理慢，上游自动降速
- **内存效率**：不需要把所有数据加载到内存

传统工具调用的缺陷：Agent 生成一个 5000 行的文件，必须等待完整生成后才能看到结果。管道模型下：生成一行返回一行。

## 核心优势三：可组合性与 Unix 哲学

Unix 设计哲学：**每个程序只做一件事，做好它，用文本流连接**。

```
ls -la | grep ".md" | wc -l
# 列出文件 | 过滤 md | 计数
# 三个独立程序组合完成复杂任务
```

这正是 AI Agent 工具系统需要的：

| 传统工具设计 | CLI 管道思维 |
|------------|------------|
| 一个工具做多件事 | 单一职责工具 |
| 返回完整结果 | 返回流式文本 |
| 强耦合 | 松耦合 |
| 难以测试单个步骤 | 每步可独立验证 |

OpenCode 的工具设计已经体现了这一点：

```typescript
// OpenCode 的工具分工
tool/
├── bash.ts      # 只做一件事：执行 shell
├── read.ts      # 只做一件事：读文件
├── write.ts     # 只做一件事：写文件
├── grep.ts      # 只做一件事：文本搜索
├── glob.ts      # 只做一件事：模式匹配
```

每个工具都通过 stdin/stdout 交互，可以被管道连接。

## 核心优势四：进程隔离与安全

CLI 模型的另一个被低估的优势：**天然的沙箱隔离**。

```
# 每个管道组件运行在独立进程
# 一个崩溃不影响其他
# 资源限制可精确控制（ulimit, cgroup）
```

对比 MCP Server：
- MCP Server 是常驻进程，需要单独管理生命周期
- CLI 工具是按需启动的进程，天然支持超时和资源限制

对比 Skills：
- Skill 代码在 Agent 运行时上下文中执行
- CLI 工具在独立进程中执行，隔离更彻底

## 实践案例：OpenCode 的管道实现

OpenCode 的工具系统实际上已经在用管道思维：

```typescript
// tool/bash.ts - 启动一个进程执行命令
// 输出通过 stdout 返回给调用者
// Agent 拿到的是纯文本结果，不关心命令如何执行
```

```typescript
// tool/grep.ts - 搜索结果通过 stdout 返回
// grep 执行在独立进程
// Agent 只收到匹配行的文本列表
```

OpenCode 的 MCP 支持也是管道思维的体现：
- MCP Server 返回的工具描述是**元数据**，不是执行结果
- 真正执行时，数据流仍然通过协议传输

## 未来展望：Agent 编程范式的新方向

跳出 Skills、MCP、ACP，当前还有哪些值得关注的范式？

### 1. CSP（Communicating Sequential Processes）

Go 语言的并发模型。基于 channel 的消息传递，进程间通过通道通信。

```
// CSP 思维
ch := make(chan string)
go func() {
    result := processLargeFile("data.csv")
    ch <- result  // 只传递结果引用，不传数据本身
}()
```

**在 Agent 场景的价值**：每个 tool 是独立的 goroutine，通过 channel 传递任务和结果。天然支持并发，不会阻塞。

代表项目：Go-based AI agents（如 go-opencode 方向）

### 2. Actor Model（参与者模型）

每个 Actor 是独立的计算单元，通过消息传递交互，拥有私有状态。

```
Actor Mailbox
    ↓ 异步消息
  Actor → 状态变更 → 发送响应
```

**在 Agent 场景的价值**：每个工具是一个 Actor，状态隔离，支持容错。

代表项目：Erlang/Elixir BEAM 上的 AI 运行时

### 3. Event-Driven + Pub/Sub

事件驱动的工具发现和调用。

```
Event Bus
    ↓ 发布
Agent 发布 "需要文件内容" 事件
    ↓ 订阅
文件系统 Actor 响应事件
```

**在 Agent 场景的价值**：工具不需要显式调用，通过事件总线解耦。

代表项目：VSCode 扩展系统

### 4. Wasm Component Model（WebAssembly 组件模型）

Wasm 正在演进为"可移植的二进制接口"，组件之间通过接口类型系统交互。

```
Component A (Wasm)
    ↓ exports/imports
Component B (Wasm)
```

**在 Agent 场景的价值**：工具是 Wasm Component，跨语言、跨运行时、强隔离。

代表项目：BytecodeAlliance/wasmtime

### 5. Vector Similarity + Tool Retrieval（向量相似度工具发现）

不依赖固定清单，而是通过语义检索动态发现工具。

```
用户 query → Embedding → 向量数据库检索 → top-k 工具 → 调用
```

**在 Agent 场景的价值**：Agent 可以从大量工具中"即时发现"当前需要的，不需要预先知道所有工具。

代表项目：LangChain Tool Retrieval, GPTs Action 动态发现

### 6. LSP-inspired Tool Protocol（LSP 风格工具协议）

参考 Language Server Protocol 的设计：工具定义和工具执行分离。

```
Tool Definition Protocol（工具定义协议）
    ↓ 工具声明自己的能力
    ↓ 支持 Completions, Diagnostics, ...
Tool Execution Protocol（工具执行协议）
    ↓ 标准化请求/响应格式
```

**在 Agent 场景的价值**：统一的工具接口，任何工具只要实现 LSP-style 接口就能接入。

### 7. Formal Planning Language（形式化规划语言）

用 PDDL（Planning Domain Definition Language）或类似的形式化语言描述任务，让 Agent 生成可验证的执行计划。

```
Domain: file-editing
Actions:
  - read_file(path) → content
  - write_file(path, content)
  - edit_file(path, pattern, replacement)
Goal: produce_diff(original, modified)
```

**在 Agent 场景的价值**：任务规划从"模糊生成"变为"形式化推理"，可验证、可回溯。

## 范式对比矩阵

| 范式 | 核心抽象 | 工具发现 | 数据流 | 适用场景 |
|------|---------|---------|--------|---------|
| CLI/Pipe | 进程 + 流 | 静态清单 | push/stream | 文本处理、过滤、转换 |
| Skills | 文档 + 描述 | 目录扫描 | request/response | 轻量扩展、社区贡献 |
| MCP | HTTP + JSON-RPC | 协议协商 | request/response | 标准化服务接入 |
| ACP | 会话 + 加密 | 端点发现 | 消息传递 | 多 Agent 协作 |
| CSP | Channel + Goroutine | 类型系统 | 同步/异步 | 并发任务处理 |
| Actor | Mailbox + 状态 | 名称注册 | 异步消息 | 分布式 Agent |
| Wasm Component | Interface + Impl | 接口发现 | 强类型调用 | 安全沙箱、跨语言 |
| Vector Retrieval | Embedding + ANN | 语义搜索 | request/response | 超大规模工具集 |

## 我的判断

**CLI 管道思维被严重低估**。当前 Skills/MCP/ACP 都过度关注"工具是什么"，而忽略了"数据如何流动"。管道模型提供了一个更符合 Unix 哲学的答案：**让数据流动起来，而不是全部加载到有限 Context 中**。

**未来的 Agent 编程**可能是多范式融合：
- **工具定义层**：Skills 或 MCP（描述工具是什么）
- **工具发现层**：Vector Retrieval（如何找到需要的工具）
- **执行层**：CLI 管道 + 进程隔离（如何高效安全地执行）
- **协作层**：ACP 或 Actor Model（Agent 之间如何通信）

单一范式不够用，**组合才是终态**。

---

## 参考资料

1. [OpenCode 源码：tool 系统](https://github.com/anomalyco/opencode/tree/main/packages/opencode/src/tool)
2. [Unix Philosophy - Doug McIlroy](https://en.wikipedia.org/wiki/Unix_philosophy)
3. [CSP - Communicating Sequential Processes (Hoare)](https://en.wikipedia.org/wiki/Communicating_sequential_processes)
4. [WebAssembly Component Model](https://component-model.bytecodealliance.org/)
5. [Language Server Protocol](https://microsoft.github.io/language-server-protocol/)
6. [PDDL - Planning Domain Definition Language](https://en.wikipedia.org/wiki/Planning_Domain_Definition_Language)
