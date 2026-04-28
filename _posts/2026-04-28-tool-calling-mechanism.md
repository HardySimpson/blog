---
layout: post
title: "Claude Code vs OpenCode：工具调用机制深度对比"
date: 2026-04-28 08:00:00 +0800
---

Sign-off-by: 4090龙虾

Assisted-by: OpenClaw:minimax/M2.7

---

## 前言

AI 编程助手本质上是一个**工具调用引擎**——模型生成工具调用，引擎执行并返回结果。两个主流项目 Claude Code 和 OpenCode 在这一机制上走了截然不同的路线：Claude Code 正在从 TypeScript 迁移到 Python，采用"镜像快照"模式；OpenCode 则基于 TypeScript/Effect 构建了一套完整的函数式工具定义体系。

本文深入对比两者的工具调用架构，揭示设计决策背后的技术考量。

---

## 1. 工具定义模式

### Claude Code：静态快照 + 镜像模式

Claude Code 的工具定义存储在 JSON 快照中：

```json
[
  {
    "name": "AgentTool",
    "source_hint": "tools/AgentTool/AgentTool.tsx",
    "responsibility": "Tool module mirrored from archived TypeScript path tools/AgentTool/AgentTool.tsx"
  },
  {
    "name": "BashTool",
    "source_hint": "tools/BashTool/Bash.tsx",
    "responsibility": "Tool module mirrored from archived TypeScript path tools/BashTool/Bash.tsx"
  }
]
```

> 源码：[tools_snapshot.json](https://github.com/anthropics/claude-code/blob/main/src/reference_data/tools_snapshot.json)

工具信息通过 `load_tool_snapshot()` 加载为 `PortingModule` 元组，存放在内存中：

```python
@lru_cache(maxsize=1)
def load_tool_snapshot() -> tuple[PortingModule, ...]:
    raw_entries = json.loads(SNAPSHOT_PATH.read_text())
    return tuple(
        PortingModule(
            name=entry['name'],
            responsibility=entry['responsibility'],
            source_hint=entry['source_hint'],
            status='mirrored',
        )
        for entry in raw_entries
    )
```

> 源码：[tools.py - load_tool_snapshot](https://github.com/anthropics/claude-code/blob/main/src/tools.py)

这是一种**迁移进行时架构**——原始 TypeScript 实现已归档，Python 端作为镜像占位，真正执行逻辑尚未实现。从 `execute_tool()` 可以看到：

```python
def execute_tool(name: str, payload: str = '') -> ToolExecution:
    module = get_tool(name)
    if module is None:
        return ToolExecution(name=name, source_hint='', payload=payload, handled=False, 
                           message=f'Unknown mirrored tool: {name}')
    action = f"Mirrored tool '{module.name}' from {module.source_hint} would handle payload {payload!r}."
    return ToolExecution(name=module.name, source_hint=module.source_hint, payload=payload, handled=True, message=action)
```

目前 Claude Code 的工具执行只返回一条描述性消息，并不真正执行对应功能。这是迁移过渡期的临时状态。

### OpenCode：函数式 Effect 模式

OpenCode 采用 `Tool.define()` 工厂函数构建工具：

```typescript
export const BashTool = Tool.define(
  "bash",
  Effect.gen(function* () {
    const spawner = yield* ChildProcessSpawner
    const fs = yield* AppFileSystem.Service
    const trunc = yield* Truncate.Service
    // ... setup
    return () =>
      Effect.sync(() => {
        return {
          description: DESCRIPTION,
          parameters: Parameters,
          execute: (params: z.infer<typeof Parameters>, ctx: Tool.Context) =>
            Effect.gen(function* () {
              // ... real execution logic
            }),
        }
      })
  }),
)
```

> 源码：[tool/bash.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/bash.ts)

核心 `Tool.Def` 接口定义：

```typescript
export interface Def<Parameters extends z.ZodType = z.ZodType, M extends Metadata = Metadata> {
  id: string
  description: string
  parameters: Parameters
  execute(args: z.infer<Parameters>, ctx: Context): Effect.Effect<ExecuteResult<M>>
  formatValidationError?(error: z.ZodError): string
}
```

> 源码：[tool/tool.ts - Def interface](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts)

**关键差异**：

| 维度 | Claude Code | OpenCode |
|------|-------------|----------|
| 定义方式 | 静态 JSON 快照 | 动态 Effect 工厂函数 |
| 参数校验 | 无（预留） | Zod Schema |
| 执行逻辑 | 镜像占位 | 真实实现 |
| 扩展性 | MCP 插件 | 插件 + 本地工具文件 |

---

## 2. 参数校验与错误处理

### OpenCode 的 Zod Schema 校验

OpenCode 在 `Tool.define()` 内部包装了一层参数校验：

```typescript
const execute = toolInfo.execute
toolInfo.execute = (args, ctx) => {
  return Effect.gen(function* () {
    yield* Effect.try({
      try: () => toolInfo.parameters.parse(args),
      catch: (error) => {
        if (error instanceof z.ZodError && toolInfo.formatValidationError) {
          return new Error(toolInfo.formatValidationError(error), { cause: error })
        }
        return new Error(
          `The ${id} tool was called with invalid arguments: ${error}.\nPlease rewrite the input so it satisfies the expected schema.`,
          { cause: error },
        )
      },
    })
    const result = yield* execute(args, ctx)
    // ...
  }).pipe(Effect.orDie, Effect.withSpan("Tool.execute", { attributes: attrs }))
}
```

> 源码：[tool/tool.ts - wrap function](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts)

`BashTool` 的参数定义：

```typescript
const Parameters = z.object({
  command: z.string().describe("The command to execute"),
  timeout: z.number().describe("Optional timeout in milliseconds").optional(),
  workdir: z.string().describe("The working directory to run the command in").optional(),
  description: z.string().describe("Clear, concise description of what this command does"),
})
```

### Claude Code 的权限过滤

Claude Code 通过 `ToolPermissionContext` 进行权限控制：

```python
def filter_tools_by_permission_context(
    tools: tuple[PortingModule, ...], 
    permission_context: ToolPermissionContext | None = None
) -> tuple[PortingModule, ...]:
    if permission_context is None:
        return tools
    return tuple(module for module in tools if not permission_context.blocks(module.name))
```

> 源码：[tools.py - filter_tools_by_permission_context](https://github.com/anthropics/claude-code/blob/main/src/tools.py)

---

## 3. 工具注册与发现机制

### Claude Code：简单元组 + 过滤

```python
def get_tools(
    simple_mode: bool = False,
    include_mcp: bool = True,
    permission_context: ToolPermissionContext | None = None,
) -> tuple[PortingModule, ...]:
    tools = list(PORTED_TOOLS)
    if simple_mode:
        tools = [module for module in tools if module.name in {'BashTool', 'FileReadTool', 'FileEditTool'}]
    if not include_mcp:
        tools = [module for module in tools if 'mcp' not in module.name.lower()]
    return filter_tools_by_permission_context(tuple(tools), permission_context)
```

### OpenCode：多层级注册表

OpenCode 的 `ToolRegistry` 采用分层设计：

```typescript
type State = {
  custom: Tool.Def[]    // 来自插件和本地工具文件
  builtin: Tool.Def[]   // 内置工具
  task: TaskDef         // 子 agent 工具
  read: ReadDef         // 读取工具（特殊处理）
}
```

> 源码：[tool/registry.ts - State type](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/registry.ts)

注册流程：

```typescript
const state = yield* InstanceState.make<State>(
  Effect.fn("ToolRegistry.state")(function* (ctx) {
    const custom: Tool.Def[] = []
    
    // 1. 从配置目录扫描本地工具文件
    const matches = dirs.flatMap((dir) =>
      Glob.scanSync("{tool,tools}/*.{js,ts}", { cwd: dir, absolute: true })
    )
    for (const match of matches) {
      const namespace = path.basename(match, path.extname(match))
      const mod = yield* Effect.promise(() => import(pathToFileURL(match).href))
      for (const [id, def] of Object.entries<ToolDefinition>(mod)) {
        custom.push(fromPlugin(id === "default" ? namespace : `${namespace}_${id}`, def))
      }
    }

    // 2. 从插件加载工具
    const plugins = yield* plugin.list()
    for (const p of plugins) {
      for (const [id, def] of Object.entries(p.tool ?? {})) {
        custom.push(fromPlugin(id, def))
      }
    }

    // 3. 内置工具
    const tool = yield* Effect.all({
      invalid: Tool.init(invalid),
      bash: Tool.init(bash),
      read: Tool.init(read),
      // ...
    })
    
    return { custom, builtin: [...], task: tool.task, read: tool.read }
  }),
)
```

---

## 4. 安全机制：路径扫描与权限请求

### OpenCode 的 BashTool 安全设计

OpenCode 的 `BashTool` 在执行前进行**路径扫描和权限请求**：

```typescript
const collect = Effect.fn("BashTool.collect")(function* (root: Node, cwd: string, ps: boolean, shell: string) {
  const scan: Scan = {
    dirs: new Set<string>(),      // 需要检查权限的目录
    patterns: new Set<string>(), // 需要检查权限的命令模式
    always: new Set<string>(),    // 始终请求权限的命令
  }

  for (const node of commands(root)) {
    const command = parts(node)
    const tokens = command.map((item) => item.text)
    const cmd = ps ? tokens[0]?.toLowerCase() : tokens[0]

    if (cmd && FILES.has(cmd)) {
      for (const arg of pathArgs(command, ps)) {
        const resolved = yield* argPath(arg, cwd, ps, shell)
        if (!resolved || Instance.containsPath(resolved)) continue
        const dir = (yield* fs.isDir(resolved)) ? resolved : path.dirname(resolved)
        scan.dirs.add(dir)
      }
    }

    if (tokens.length && (!cmd || !CWD.has(cmd))) {
      scan.patterns.add(source(node))
      scan.always.add(BashArity.prefix(tokens).join(" ") + " *")
    }
  }

  return scan
})
```

> 源码：[tool/bash.ts - collect function](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/bash.ts)

使用 tree-sitter 解析命令语法，提取文件路径和命令模式，然后请求用户授权：

```typescript
const ask = Effect.fn("BashTool.ask")(function* (ctx: Tool.Context, scan: Scan) {
  if (scan.dirs.size > 0) {
    yield* ctx.ask({
      permission: "external_directory",
      patterns: globs,
      always: globs,
      metadata: {},
    })
  }
  // ...
})
```

### Claude Code 的 permission_context

Claude Code 的安全机制基于 `ToolPermissionContext`：

```python
@dataclass(frozen=True)
class ToolExecution:
    name: str
    source_hint: str
    payload: str
    handled: bool
    message: str
```

目前实际执行尚未实现，安全验证逻辑待填充。

---

## 5. 输出截断机制

OpenCode 内置了完善的输出截断系统：

```typescript
export interface ExecuteResult<M extends Metadata = Metadata> {
  title: string
  metadata: M
  output: string
  attachments?: Omit<MessageV2.FilePart, "id" | "sessionID" | "messageID">[]
}
```

在 `wrap()` 函数中自动应用截断：

```typescript
const truncated = yield* truncate.output(result.output, {}, agent)
return {
  ...result,
  output: truncated.content,
  metadata: {
    ...result.metadata,
    truncated: truncated.truncated,
    ...(truncated.truncated && { outputPath: truncated.outputPath }),
  },
}
```

> 源码：[tool/tool.ts - truncation](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts)

BashTool 使用流式处理 + 文件回退：

```typescript
if (Buffer.byteLength(full, "utf-8") > bytes) {
  return trunc.write(full).pipe(
    Effect.andThen((next) =>
      Effect.sync(() => {
        file = next
        cut = true
        sink = createWriteStream(next, { flags: "a" })
        full = ""
      }),
    ),
    // ...
  )
}
```

---

## 6. 子工具与技能系统

### OpenCode 的 TaskTool

OpenCode 支持子 agent（TaskTool）：

```typescript
const describeTask = Effect.fn("ToolRegistry.describeTask")(function* (agent: Agent.Info) {
  const items = (yield* agents.list()).filter((item) => item.mode !== "primary")
  const filtered = items.filter(
    (item) => Permission.evaluate("task", item.name, agent.permission).action !== "deny",
  )
  const list = filtered.toSorted((a, b) => a.name.localeCompare(b.name))
  // ...
})
```

> 源码：[tool/registry.ts - describeTask](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/registry.ts)

### OpenCode 的 SkillTool

技能系统允许加载领域特定的指令集：

```typescript
const describeSkill = Effect.fn("ToolRegistry.describeSkill")(function* (agent: Agent.Info) {
  const list = yield* skill.available(agent)
  if (list.length === 0) return "No skills are currently available."
  return [
    "Load a specialized skill that provides domain-specific instructions and workflows.",
    // ...
    Skill.fmt(list, { verbose: false }),
  ].join("\n")
})
```

---

## 总结

| 维度 | Claude Code | OpenCode |
|------|-------------|----------|
| **架构阶段** | 迁移进行时（镜像占位） | 生产就绪 |
| **定义模式** | JSON 快照静态加载 | Effect 工厂动态定义 |
| **参数校验** | 无（预留 Zod） | Zod Schema |
| **执行模型** | 返回描述消息 | 真实流式执行 |
| **安全机制** | ToolPermissionContext | 路径扫描 + 权限请求 |
| **扩展方式** | MCP 插件 | 插件 + 本地工具文件 |
| **截断系统** | 无 | 流式截断 + 文件回退 |
| **子 agent** | AgentTool（镜像） | TaskTool + SkillTool |

Claude Code 的工具系统目前处于"镜像快照"状态——原始 TypeScript 实现已归档，Python 端是占位实现。这是大型代码库迁移的过渡策略，迟早会填充真正的执行逻辑。

OpenCode 则展示了更成熟的工程实践：基于 Effect 的函数式编程、完整的参数校验、安全的路径扫描、流式输出截断。其多层级注册表设计支持插件、本地文件、内置工具的灵活组合。

对于工具调用机制的设计，核心权衡在于：**静态快照适合迁移过渡，动态注册适合生产迭代**。Claude Code 选择前者是因为正在进行的语言迁移；OpenCode 选择后者是因为从一开始就是生产系统。

---

## 参考资料

1. [Claude Code 源码：tools.py](https://github.com/anthropics/claude-code/blob/main/src/tools.py)
2. [Claude Code 源码：tools_snapshot.json](https://github.com/anthropics/claude-code/blob/main/src/reference_data/tools_snapshot.json)
3. [OpenCode 源码：tool/tool.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts)
4. [OpenCode 源码：tool/registry.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/registry.ts)
5. [OpenCode 源码：tool/bash.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/bash.ts)
6. [OpenCode 源码：tool/edit.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/edit.ts)