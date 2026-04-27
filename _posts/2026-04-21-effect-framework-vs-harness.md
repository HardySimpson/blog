---
layout: post
title: "Effect 框架 vs Harness：两种不同的 Agent 编程范式"
date: 2026-04-21 10:41:00 +0800
---

Sign-off-by: 难易

Assisted-by: OpenClaw:minimax/M2.7

---

在 AI Coding Agent 的开发中，有两个经常被混淆的概念：**Effect 框架**和 **Harness**。它们解决的是不同层次的问题，代表了两种不同的架构思维。

OpenCode 用 Effect 框架构建整个工具系统。Claw-code 用 Harness 机制实现与 Claude Code 的兼容。两者看似不相关，实际上代表了"**如何构建**"和"**如何对接**"两种根本不同的关注点。

## Effect 框架：组合式计算的核心

Effect 是一个 TypeScript 函数式响应式编程库，核心解决两个问题：**如何描述计算**，以及**如何执行副作用**。

### 什么是副作用

程序设计中的"纯函数"不依赖外部状态，不产生可观察的副作用。但真实的工具调用必然涉及副作用：

- 读取文件（I/O 副作用）
- 执行 Shell 命令（系统调用副作用）
- 发起 HTTP 请求（网络副作用）
- 读取环境变量（环境副作用）

Effect 的思路是：**用类型系统描述副作用，让编译器帮助管理它们**。

### Effect 的核心语法

```typescript
// 1. Effect.fn - 声明式函数
const parse = Effect.fn("BashTool.parse")(function* (command: string, ps: boolean) {
  const tree = yield* Effect.promise(() => parser().then((p) => p[ps ? 'ps' : 'bash'].parse(command)))
  return tree.rootNode
})

// 2. Effect.gen - 生成器语法（类似 async/await）
const run = Effect.fn("BashTool.run")(function* (input, ctx) {
  const handle = yield* spawner.spawn(cmd(...))  // yield* = 等待 Effect
  const exit = yield* handle.exitCode            // 组合多个 Effect
  return { output, metadata: { exit } }
})

// 3. Effect.Service - 依赖注入层
export class SkillService extends Context.Service<SkillService>()("@opencode/Skill") {
  readonly get: (name: string) => Effect.Effect<Info | undefined>
  readonly all: () => Effect.Effect<Info[]>
  readonly available: (agent?: Agent.Info) => Effect.Effect<Info[]>
}
```

### Effect 的优势：组合性

Effect 最大的价值是**可组合**：

```typescript
// 链式组合
const result = yield* skill.get(name)
  .pipe(Effect.flatMap(info => loadContent(info)))
  .pipe(Effect.map(content => parse(content)))
  .pipe(Effect.mapError(err => handleError(err)))

// 并行执行
const [a, b, c] = yield* Effect.all([
  Effect.promise(() => fetchA()),
  Effect.promise(() => fetchB()),
  Effect.promise(() => fetchC()),
])

// 条件执行
const data = yield* (shouldFetch ? fetchData() : Effect.succeedcachedData))
```

每个 `yield*` 都是在"等待"一个 Effect 完成。Effect 的执行器负责处理：
- 异步调度
- 错误传播
- 取消信号
- 重试逻辑

### Effect 的错误处理

传统 try/catch 的问题：错误类型无法静态检查，容易遗漏。

```typescript
// Effect 的类型化错误处理
const program = Effect.gen(function* () {
  const file = yield* Effect.tryPromise({
    try: () => readFile("data.json"),
    catch: (error) => new FileReadError(error.message)  // 错误类型明确
  })
  
  const parsed = yield* Effect.try({
    try: () => JSON.parse(file),
    catch: (error) => new ParseError(error.message)  // 错误类型明确
  })
  
  return parsed
})

// 统一在顶层处理所有可能的错误
Effect.runPromise(program).catch(console.error)
```

### Effect 与 OpenCode 的工具系统

OpenCode 将每个工具都建模为 Effect：

```typescript
// tool/bash.ts
export const BashTool = Tool.define("bash", Effect.gen(function* () {
  return {
    description: DESCRIPTION,
    parameters: Parameters,
    execute: (params, ctx) =>
      Effect.gen(function* () {
        // 解析命令
        const root = yield* parse(params.command, ps)
        
        // 收集文件扫描结果
        const scan = yield* collect(root, cwd, ps, shell)
        
        // 请求权限
        yield* ask(ctx, scan)
        
        // 执行命令，流式处理输出
        const handle = yield* spawner.spawn(cmd(...))
        yield* Effect.forkScoped(
          Stream.runForEach(Stream.decodeText(handle.all), (chunk) => 
            ctx.metadata({ metadata: { output: chunk } })
          )
        )
        
        return yield* run({ shell, name, command: params.command, ... })
      }).pipe(Effect.orDie)  // 错误统一处理
  }
}))
```

**Effect 在这里扮演的角色**：让工具的执行变成可描述、可组合、可错误处理的数据流。

## Harness：对接外部系统的桥梁

Harness（测试 harness / 兼容 harness）解决的是完全不同的问题：**我的系统如何与另一个系统共存**？

### 测试 Harness 的经典定义

在软件测试领域，Harness 是"包围被测系统的脚手架"：

```
┌─────────────────────────────────────┐
│           Test Harness              │
│                                     │
│  ┌───────────────────────────────┐  │
│  │     System Under Test        │  │
│  └───────────────────────────────┘  │
│                                     │
│  stub / mock / driver / harness    │
└─────────────────────────────────────┘
```

Harness 提供：
- **Stubs**：模拟外部依赖的返回值
- **Mocks**：验证被测系统对外部的调用
- **Drivers**：驱动被测系统执行特定场景

### Claw-code 的 Compat Harness

Claw-code 的 `compat-harness` 干的是同样的事——但不是测试场景，而是**兼容场景**。

```rust
// compat-harness/src/lib.rs
pub fn extract_manifest(paths: &UpstreamPaths) -> ExtractedManifest {
    let commands_source = fs::read_to_string(paths.commands_path())?;
    let tools_source = fs::read_to_string(paths.tools_path())?;
    let cli_source = fs::read_to_string(paths.cli_path())?;

    Ok(ExtractedManifest {
        commands: extract_commands(&commands_source),
        tools: extract_tools(&tools_source),
        bootstrap: extract_bootstrap_plan(&cli_source),
    })
}
```

**Harness 在这里的作用**：从 Claude Code 的 TypeScript 源码中**提取清单**——有哪些命令、有哪些工具、启动流程是什么——然后用这些信息指导 Claw-code 的行为。

### Harness 的工作原理

```
Claude Code 源码（TypeScript）
         ↓
   compat-harness 解析
         ↓
  提取 CommandRegistry, ToolRegistry
         ↓
  Claw-code 的 Rust 运行时
         ↓
  生成与 Claude Code 兼容的行为
```

具体来说：

**1. 命令提取**（从 TypeScript 源码解析）

```rust
pub fn extract_commands(source: &str) -> CommandRegistry {
    let mut entries = Vec::new();
    
    // 检测 import 语句
    for raw_line in source.lines() {
        let line = raw_line.trim();
        
        // import { addDir } from "./commands/add_dir"
        if line.starts_with("import ") && line.contains("./commands/") {
            entries.push(CommandManifestEntry {
                name: imported,
                source: CommandSource::Builtin,
            })
        }
        
        // export const INTERNAL_ONLY_COMMANDS = [...]
        if line.starts_with("export const INTERNAL_ONLY_COMMANDS = [") {
            in_internal_block = true;
        }
    }
    
    dedupe_commands(entries)
}
```

**2. 工具提取**（从 TypeScript 源码解析）

```rust
pub fn extract_tools(source: &str) -> ToolRegistry {
    let mut entries = Vec::new();
    
    for raw_line in source.lines() {
        let line = raw_line.trim();
        
        // import { BashTool } from "./tools/bash"
        if line.starts_with("import ") && line.contains("./tools/") {
            for imported in imported_symbols(line) {
                if imported.ends_with("Tool") {
                    entries.push(ToolManifestEntry {
                        name: imported,
                        source: ToolSource::Base,
                    })
                }
            }
        }
    }
    
    dedupe_tools(entries)
}
```

**3. 启动阶段提取**（从 CLI 源码解析）

```rust
pub fn extract_bootstrap_plan(source: &str) -> BootstrapPlan {
    let mut phases = vec![BootstrapPhase::CliEntry];
    
    // 检测 fast-path 条件
    if source.contains("--version") {
        phases.push(BootstrapPhase::FastPathVersion);
    }
    if source.contains("--dump-system-prompt") {
        phases.push(BootstrapPhase::SystemPromptFastPath);
    }
    if source.contains("args[0] === 'daemon'") {
        phases.push(BootstrapPhase::DaemonFastPath);
    }
    // ...
    
    phases.push(BootstrapPhase::MainRuntime);
    BootstrapPlan::from_phases(phases)
}
```

### Harness 的本质

Harness 不是实现逻辑，而是**翻译层**。它的输入是外部系统的结构信息（源码、配置、协议），输出是本系统可以理解和使用的数据结构。

**关键区别**：

| 维度 | Effect | Harness |
|------|--------|---------|
| 关注点 | 如何构建程序 | 如何对接外部 |
| 输入 | 业务逻辑描述 | 外部系统的结构 |
| 输出 | 可执行程序 | 兼容层/适配器 |
| 思维模型 | 组合式函数编程 | 解析-转换-适配 |
| 代表框架 | Effect | compat-harness |

## 两者如何协作

在实际的 Agent 项目中，Effect 和 Harness 通常共存：

```
┌─────────────────────────────────────────────────┐
│              Claw-code 架构                     │
├─────────────────────────────────────────────────┤
│                                                 │
│  Effect Framework（构建工具）                    │
│  ├── ToolRegistry 定义工具                      │
│  ├── Plugin System 扩展                         │
│  └── ACP 协议实现                               │
│                                                 │
│  Harness（兼容外部）                            │
│  ├── compat-harness 解析 Claude Code 源码      │
│  └── MockParity 测试验证兼容性                  │
│                                                 │
└─────────────────────────────────────────────────┘
```

```
┌─────────────────────────────────────────────────┐
│              OpenCode 架构                      │
├─────────────────────────────────────────────────┤
│                                                 │
│  Effect Framework（核心引擎）                    │
│  ├── Tool.Service + Effect 组合                │
│  ├── Skill.Service + Effect 发现                │
│  ├── MCP + Effect.HTTP 通信                    │
│  └── Bus + Effect.Stream 事件流                │
│                                                 │
│  （没有显式的 Harness 层）                      │
│  但可以通过 MCP 协议对接外部系统                 │
│                                                 │
└─────────────────────────────────────────────────┘
```

## 什么时候用什么

**选择 Effect 框架**：
- 需要组合多个异步操作
- 错误处理需要类型安全
- 需要依赖注入和服务层
- 工具之间有复杂的依赖关系

**选择 Harness**：
- 需要兼容另一个系统
- 需要从外部源码/配置中提取结构
- 需要验证与上游的行为一致性
- 测试场景需要 Mock/Stub

**两者结合**：
- 用 Effect 构建核心功能
- 用 Harness 确保与外部系统兼容
- 这是企业级 Agent 的常见模式

## 我的判断

Effect 框架是**内功**——如何组织代码、如何处理副作用、如何让系统健壮。

Harness 是**外功**——如何与外部世界对话、如何保持兼容性、如何在生态中生存。

**没有优劣之分，只有层次之别。**

真正的成熟系统，两者都需要。OpenCode 用 Effect 构建了强大的内功，但缺乏显式的 Harness 层去与 Claude Code 对接。Claw-code 用 Harness 解决了兼容问题，但核心实现（Rust）目前还缺少 Effect 这样的组合式框架。

<!-- series: 工具调用机制对比系列 -->
<div class="series-nav">
    <span class="series-label">系列：工具调用机制对比系列</span>
    <div class="series-links">
        <a href="/2026/04/21/cli-pipe-model-implementation/" class="nav next">CLI 管道模型在 AI Agent 中的落地：Skills 与 Tools 的对接机制 →</a>
    </div>
</div>

---

## 参考资料

1. [Effect Framework 官网](https://effect.website/)
2. [OpenCode Effect 使用示例](https://github.com/anomalyco/opencode/tree/main/packages/opencode/src)
3. [Claw-code Compat Harness 源码](https://github.com/ultraworkers/claw-code/tree/main/rust/crates/compat-harness)
4. [Test Harness - Wikipedia](https://en.wikipedia.org/wiki/Test_harness)
5. [Effect - GitHub](https://github.com/Effect-TS/Effect)
