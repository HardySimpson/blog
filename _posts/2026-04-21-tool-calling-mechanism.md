---
layout: post
title: "Claude Code vs OpenCode 工具调用机制深度对比"
date: 2026-04-21 09:24:00 +0800
---

Sign-off-by: 难易

Assisted-by: OpenClaw:minimax/M2.7

*2026-04-21 基于 Claude Code (claw-code) 和 OpenCode 源码分析*

---

## 一、引言：为什么工具调用是 AI 编程 Agent 的核心

工具调用（Tool Calling）是 AI 编程 Agent 与外部世界交互的桥梁。它决定了：

1. **如何定义**一个工具（参数 schema、描述、执行逻辑）
2. **如何注册**工具到系统（builtin vs custom vs plugin）
3. **如何执行**工具调用（参数验证、权限检查、结果处理）
4. **如何路由**工具调用到对应的处理器

本文从源码出发，深度对比 Claude Code 和 OpenCode 在工具调用机制上的设计差异。

---

## 二、OpenCode：TypeScript + Effect 的函数式架构

### 2.1 核心接口：Tool.Def

OpenCode 的工具定义统一在 `Tool.Def` 接口中：

```typescript
// tool/tool.ts - 核心工具接口
export interface Def<Parameters extends z.ZodType = z.ZodType, M extends Metadata = Metadata> {
  id: string
  description: string
  parameters: Parameters
  execute(args: z.infer<Parameters>, ctx: Context): Effect.Effect<ExecuteResult<M>>
  formatValidationError?(error: z.ZodError): string
}
```

每个工具都有：
- **id**: 唯一标识符
- **description**: 描述（会发送给 LLM）
- **parameters**: Zod schema，定义参数格式
- **execute**: 执行函数，返回 `Effect.Effect<ExecuteResult<M>>`

### 2.2 工具定义工厂：Tool.define

OpenCode 使用 `Tool.define()` 工厂函数创建工具：

```typescript
// tool/tool.ts
export function define<Parameters extends z.ZodType, Result extends Metadata, R, ID extends string = string>(
  id: ID,
  init: Effect.Effect<Init<Parameters, Result>, never, R>,
): Effect.Effect<Info<Parameters, Result>, never, R | Truncate.Service | Agent.Service> & { id: ID }
```

`Tool.define()` 返回一个 `Effect`，这意味着：
- 工具初始化是**延迟的**（lazy）
- 可以在初始化时**依赖其他服务**（通过 Effect 的上下文）
- 初始化逻辑可以**异步执行**

### 2.3 执行中间件：Truncation + Error Handling

最精妙的设计在于 `wrap()` 函数，它为每个工具的 `execute` 函数包裹了中间件：

```typescript
// tool/tool.ts - 执行中间件包装
function wrap<Parameters extends z.ZodType, Result extends Metadata>(
  id: string,
  init: Init<Parameters, Result>,
  truncate: Truncate.Interface,
  agents: Agent.Interface,
) {
  return () =>
    Effect.gen(function* () {
      const toolInfo = typeof init === "function" ? { ...(yield* init()) } : { ...init }
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
          // 自动 truncation
          if (result.metadata.truncated !== undefined) {
            return result
          }
          const agent = yield* agents.get(ctx.agent)
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
        }).pipe(Effect.orDie, Effect.withSpan("Tool.execute", { attributes: attrs }))
      }
      return toolInfo
    })
}
```

这个设计实现了三个关键功能：

1. **Zod 参数验证**：调用 `parameters.parse(args)` 验证参数，无效时返回友好错误
2. **自动输出截断**：如果工具返回的 `output` 过长，自动截断并写入文件
3. **OpenTelemetry Tracing**：每个工具执行都有 span 追踪

### 2.4 工具注册表：ToolRegistry Service

OpenCode 的工具通过 `ToolRegistry` 服务集中管理：

```typescript
// tool/schema.ts - ToolRegistry 接口
export interface Interface {
  readonly ids: () => Effect.Effect<string[]>
  readonly all: () => Effect.Effect<Tool.Def[]>
  readonly named: () => Effect.Effect<{ task: TaskDef; read: ReadDef }>
  readonly tools: (model: { providerID: ProviderID; modelID: ModelID; agent: Agent.Info }) => Effect.Effect<Tool.Def[]>
}
```

工具来源分三层：

```typescript
// tool/schema.ts - 工具来源
const state = yield* InstanceState.make<State>(function* (ctx) {
  const custom: Tool.Def[] = []

  // 1. Custom tools from filesystem directories
  const dirs = yield* config.directories()
  const matches = dirs.flatMap((dir) =>
    Glob.scanSync("{tool,tools}/*.{js,ts}", { cwd: dir, absolute: true, dot: true, symlink: true }),
  )
  for (const match of matches) {
    const mod = yield* Effect.promise(() => import(...))
    for (const [id, def] of Object.entries<ToolDefinition>(mod)) {
      custom.push(fromPlugin(id, def))
    }
  }

  // 2. Plugins
  const plugins = yield* plugin.list()
  for (const p of plugins) {
    for (const [id, def] of Object.entries(p.tool ?? {})) {
      custom.push(fromPlugin(id, def))
    }
  }

  // 3. Builtin tools
  const builtin = [
    tool.invalid,
    tool.bash,
    tool.read,
    tool.glob,
    tool.grep,
    tool.edit,
    tool.write,
    tool.task,
    tool.fetch,
    tool.todo,
    tool.search,
    tool.code,
    tool.skill,
    tool.patch,
    tool.question,
    ...(Flag.OPENCODE_EXPERIMENTAL_LSP_TOOL ? [tool.lsp] : []),
  ]

  return { custom, builtin, task: tool.task, read: tool.read }
})
```

### 2.5 权限检查：Permission System

工具执行前需要通过权限检查：

```typescript
// tool/edit.ts - 权限请求示例
yield* ctx.ask({
  permission: "edit",
  patterns: [path.relative(Instance.worktree, filePath)],
  always: ["*"],
  metadata: { filepath: filePath, diff },
})
```

`ctx.ask()` 会暂停执行，等待用户授权。这是一个**协作式权限模型**：

- 工具声明自己需要的权限（`edit`、`bash`、`external_directory` 等）
- 用户预先配置规则集（ruleset）
- 首次使用时询问，之后按规则自动处理

### 2.6 模型特定的工具选择

OpenCode 能根据模型动态选择工具：

```typescript
// tool/schema.ts - 模型相关工具过滤
const tools: Interface["tools"] = Effect.fn("ToolRegistry.tools")(function* (input) {
  const filtered = (yield* all()).filter((tool) => {
    // CodeSearch 和 WebSearch 只对 OpenCode provider 或启用了 EXA 的情况开放
    if (tool.id === CodeSearchTool.id || tool.id === WebSearchTool.id) {
      return input.providerID === ProviderID.opencode || Flag.OPENCODE_ENABLE_EXA
    }

    // GPT 模型使用 ApplyPatchTool，否则用 EditTool
    const usePatch =
      input.modelID.includes("gpt-") && !input.modelID.includes("oss") && !input.modelID.includes("gpt-4")
    if (tool.id === ApplyPatchTool.id) return usePatch
    if (tool.id === EditTool.id || tool.id === WriteTool.id) return !usePatch

    return true
  })
  return filtered
})
```

这个设计非常精妙：**同一个 Edit 操作，根据模型不同选择不同的实现**。GPT 模型用 `ApplyPatchTool`（基于 unified diff），其他模型用 `EditTool`（基于 oldString/newString）。

---

## 三、Claude Code：Python + 快照镜像的架构

### 3.1 工具快照机制

Claude Code 的 Python 代码库是一个**镜像实现**，真实源码在 TypeScript 中被归档。其核心是 `tools_snapshot.json`：

```python
# src/tools.py
SNAPSHOT_PATH = Path(__file__).resolve().parent / 'reference_data' / 'tools_snapshot.json'

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

每个工具条目包含：
- **name**: 工具名称
- **responsibility**: 职责描述
- **source_hint**: 原始 TypeScript 文件路径
- **status**: 'mirrored' 表示已镜像

### 3.2 工具注册与过滤

```python
# src/tools.py
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

注意这里返回的是 `PortingModule`，只是**元数据**（名称、描述、来源），不是实际执行逻辑。

### 3.3 ToolPool 组装

```python
# src/tool_pool.py
@dataclass(frozen=True)
class ToolPool:
    tools: tuple[PortingModule, ...]
    simple_mode: bool
    include_mcp: bool

def assemble_tool_pool(
    simple_mode: bool = False,
    include_mcp: bool = True,
    permission_context: ToolPermissionContext | None = None,
) -> ToolPool:
    return ToolPool(
        tools=get_tools(simple_mode=simple_mode, include_mcp=include_mcp, permission_context=permission_context),
        simple_mode=simple_mode,
        include_mcp=include_mcp,
    )
```

`ToolPool` 类似于 OpenCode 的 `ToolRegistry`，但它只是**静态元数据的集合**，没有真正的执行逻辑。

### 3.4 权限上下文

```python
# src/permissions.py - 工具权限过滤
def filter_tools_by_permission_context(
    tools: tuple[PortingModule, ...],
    permission_context: ToolPermissionContext | None = None,
) -> tuple[PortingModule, ...]:
    if permission_context is None:
        return tools
    return tuple(module for module in tools if not permission_context.blocks(module.name))
```

Claude Code 也有权限系统，但它是**基于排除列表**的（`blocks()`），而不是 OpenCode 的协作式询问模型。

---

## 四、核心架构差异对比

### 4.1 执行模型

| 维度 | OpenCode | Claude Code |
|------|----------|-------------|
| 语言 | TypeScript + Effect | Python (镜像自 TypeScript) |
| 工具定义 | `Tool.Def` 接口 + `Effect.Effect` | `PortingModule` 快照数据 |
| 执行方式 | 真正的函数执行 | 快照元数据（实际执行在 TypeScript） |
| 参数验证 | Zod schema + 运行时验证 | 快照中的元数据 |
| 错误处理 | Effect.try + 友好错误消息 | N/A（镜像层） |
| 输出截断 | 自动 truncation 中间件 | N/A |

### 4.2 工具来源

OpenCode 的工具来源更丰富：

```
OpenCode 工具来源:
├── Builtin tools (edit, read, bash, glob, grep, etc.)
├── Custom tools (从 {tool,tools}/ 目录加载)
└── Plugin tools (从 Plugin 系统加载)

Claude Code 工具来源:
└── tools_snapshot.json (所有工具的静态元数据)
```

### 4.3 权限模型

**OpenCode**：协作式询问
```typescript
yield* ctx.ask({
  permission: "edit",
  patterns: [...],
  always: ["*"],
  metadata: {...},
})
```

**Claude Code**：基于排除列表
```python
permission_context.blocks(module.name)
```

### 4.4 模型适配

OpenCode 在 `ToolRegistry.tools()` 中实现了**模型特定的工具选择**：

```typescript
// GPT 模型用 ApplyPatchTool，其他用 EditTool
const usePatch = input.modelID.includes("gpt-") && !input.modelID.includes("oss") && !input.modelID.includes("gpt-4")
```

Claude Code 的 Python 层没有这个能力，因为它只是镜像层。

---

## 五、Edit 工具：最复杂的案例

### 5.1 OpenCode 的 EditTool 实现

OpenCode 的 `EditTool` 是最复杂的工具之一，它实现了**9种字符串替换策略**：

```typescript
// tool/edit.ts - 替换策略链
for (const replacer of [
  SimpleReplacer,           // 精确匹配
  LineTrimmedReplacer,      // 去除首尾空白后匹配
  BlockAnchorReplacer,      // 首尾行作为锚点，模糊匹配中间内容
  WhitespaceNormalizedReplacer,  // 空白符归一化
  IndentationFlexibleReplacer,    // 缩进灵活匹配
  EscapeNormalizedReplacer,       // 转义符归一化
  TrimmedBoundaryReplacer,        // 边界 trim 匹配
  ContextAwareReplacer,           // 上下文感知
  MultiOccurrenceReplacer,        // 多重匹配
]) {
  for (const search of replacer(content, oldString)) {
    // 找到匹配，执行替换
  }
}
```

`BlockAnchorReplacer` 特别有意思：当 `oldString` 首尾行能匹配但中间内容有差异时，使用 **Levenshtein 距离** 计算相似度：

```typescript
// tool/edit.ts - Levenshtein 距离计算
function levenshtein(a: string, b: string): number {
  const matrix = Array.from({ length: a.length + 1 }, (_, i) =>
    Array.from({ length: b.length + 1 }, (_, j) => (i === 0 ? j : j === 0 ? i : 0)),
  )
  // ...
}
```

当相似度超过阈值（单候选 0.0，多候选 0.3）时，接受匹配。

### 5.2 文件锁机制

EditTool 还实现了**文件级别的锁**，防止并发编辑：

```typescript
// tool/edit.ts - 文件锁
const locks = new Map<string, Semaphore.Semaphore>()

function lock(filePath: string) {
  const resolvedFilePath = AppFileSystem.resolve(filePath)
  const hit = locks.get(resolvedFilePath)
  if (hit) return hit
  const next = Semaphore.makeUnsafe(1)
  locks.set(resolvedFilePath, next)
  return next
}

// 使用
yield* lock(filePath).withPermits(1)(
  Effect.gen(function* () {
    // 执行编辑操作
  })
)
```

### 5.3 Claude Code 的 EditTool

Claude Code 的 EditTool 在 Python 层只有元数据，实际逻辑在 TypeScript 归档层：

```json
{
  "name": "EditTool",
  "source_hint": "tools/EditTool/EditTool.tsx",
  "responsibility": "Tool module mirrored from archived TypeScript path tools/EditTool/EditTool.tsx"
}
```

---

## 六、总结：两种哲学

### OpenCode 的哲学：一切皆 Effect

OpenCode 将工具调用完全函数式化：

1. **工具是数据**：工具定义是 `Tool.Def` 类型
2. **执行是 Effect**：每个工具执行返回 `Effect.Effect`
3. **中间件是组合**：通过 `wrap()` 函数组合验证、截断、追踪
4. **依赖注入**：通过 Effect Context 注入所需服务

这个设计的优势：
- **可测试性**：Effect 可以被 mock 和组合
- **可观测性**：内置 span 追踪
- **可扩展性**：Plugin 系统和 filesystem 目录加载
- **模型适配**：同一操作不同实现

### Claude Code 的哲学：镜像 + 快照

Claude Code 的 Python 实现是 TypeScript 代码库的镜像：

1. **源码在 TypeScript**：Python 只是类型标注的镜像
2. **工具是快照**：`tools_snapshot.json` 是静态元数据
3. **执行在别处**：实际执行逻辑在归档的 TypeScript 中

这个设计的优势：
- **一致性**：Python 和 TypeScript 保持同步
- **文档化**：快照包含 source_hint，便于追溯
- **Porting 友好**：清晰的镜像关系

---

## 七、参考资料

1. [OpenCode 源码：tool/tool.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts)
2. [OpenCode 源码：tool/schema.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/schema.ts)
3. [OpenCode 源码：tool/edit.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/edit.ts)
4. [OpenCode 源码：tool/bash.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/bash.ts)
5. [OpenCode 源码：session/llm.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/llm.ts)
6. [Claude Code 源码：tools.py](https://github.com/claude-code/claude-code/blob/main/src/tools.py)
7. [Claude Code 源码：tool_pool.py](https://github.com/claude-code/claude-code/blob/main/src/tool_pool.py)
8. [Claude Code 源码：tools_snapshot.json](https://github.com/claude-code/claude-code/blob/main/src/reference_data/tools_snapshot.json)
