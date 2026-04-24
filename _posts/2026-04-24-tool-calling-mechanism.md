---
layout: post
title: "Claude Code 与 OpenCode 工具调用机制对比分析"
date: 2026-04-24 08:00:00 +0800
---

Sign-off-by: 难易

Assisted-by: OpenClaw:minimax/M2.7

## 引言

工具调用（Tool Calling）是 AI Coding Agent 的核心能力。本文从源码层面深入对比 Claude Code（Python 移植版）与 OpenCode（原生 TypeScript）的工具调用机制，剖析两者在架构设计上的根本差异。

## 1. 架构哲学对比

### Claude Code：镜像快照模式

Claude Code 源码中，`tools.py` 采用**镜像快照模式**：

```python
# tools.py - 从 JSON 快照加载工具元数据
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

> 源码：[tools.py](https://github.com/anomalyco/claude-code/blob/main/src/tools.py)

工具定义存储在 `reference_data/tools_snapshot.json` 中，执行时返回"将要处理"的描述信息，并非真正执行：

```python
def execute_tool(name: str, payload: str = '') -> ToolExecution:
    module = get_tool(name)
    if module is None:
        return ToolExecution(name=name, ..., handled=False, ...)
    action = f"Mirrored tool '{module.name}' from {module.source_hint} would handle payload {payload!r}."
    return ToolExecution(name=module.name, ..., handled=True, message=action)
```

这是因为 Claude Code 当前是**移植项目**，尚未实现真正的工具执行逻辑。

### OpenCode：Effect 函数式模式

OpenCode 采用 **Effect** 函数式编程范式定义工具：

```typescript
// tool.ts - 工具定义核心
export function define<Parameters extends z.ZodType, Result extends Metadata, R, ID extends string = string>(
  id: ID,
  init: Effect.Effect<Init<Parameters, Result>, never, R>,
): Effect.Effect<Info<Parameters, Result>, never, R | Truncate.Service | Agent.Service> & { id: ID }
```

每个工具返回 `Effect.Effect<ExecuteResult>`，天然支持异步、错误处理和并发控制。

## 2. 工具注册机制

### OpenCode 的注册表

OpenCode 通过 `registry.ts` 集中注册所有内置工具：

```typescript
const tool = yield* Effect.all({
  invalid: Tool.init(invalid),
  bash: Tool.init(bash),
  read: Tool.init(read),
  glob: Tool.init(globtool),
  grep: Tool.init(greptool),
  edit: Tool.init(edit),
  write: Tool.init(writetool),
  task: Tool.init(task),
  fetch: Tool.init(webfetch),
  todo: Tool.init(todo),
  search: Tool.init(websearch),
  code: Tool.init(codesearch),
  skill: Tool.init(skilltool),
  patch: Tool.init(patchtool),
  question: Tool.init(question),
  lsp: Tool.init(lsptool),
  plan: Tool.init(plan),
})
```

> 源码：[registry.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/registry.ts)

### 动态工具加载

OpenCode 支持从文件系统动态加载自定义工具：

```typescript
const matches = dirs.flatMap((dir) =>
  Glob.scanSync("{tool,tools}/*.{js,ts}", { cwd: dir, absolute: true, dot: true, symlink: true }),
)
for (const match of matches) {
  const namespace = path.basename(match, path.extname(match))
  const mod = yield* Effect.promise(() => import(...))
  for (const [id, def] of Object.entries<ToolDefinition>(mod)) {
    custom.push(fromPlugin(id, def))
  }
}
```

还支持插件扩展：

```typescript
const plugins = yield* plugin.list()
for (const p of plugins) {
  for (const [id, def] of Object.entries(p.tool ?? {})) {
    custom.push(fromPlugin(id, def))
  }
}
```

## 3. Bash 工具：复杂度对比

### Claude Code：占位符

Claude Code 的 Bash 工具尚未实现，执行返回镜像信息。

### OpenCode：完整的命令执行引擎

OpenCode 的 `bash.ts` 实现了完整的命令解析和执行：

```typescript
// 使用 web-tree-sitter 解析 Bash/PowerShell 命令
const parser = lazy(async () => {
  const { Parser } = await import("web-tree-sitter")
  const { default: bashWasm } = await import("tree-sitter-bash/tree-sitter-bash.wasm" as string, ...)
  const { default: psWasm } = await import("tree-sitter-powershell/tree-sitter-powershell.wasm" as string, ...)
  const bash = new Parser()
  bash.setLanguage(bashLanguage)
  const ps = new Parser()
  ps.setLanguage(psLanguage)
  return { bash, ps }
})
```

关键功能：
- **tree-sitter 语法解析**：精准识别命令参数、文件操作
- **路径扫描**：自动检测危险的文件操作（rm, cp, mv 等）
- **权限询问**：需要外部目录访问时自动向用户请求权限
- **输出截断**：大输出自动写入临时文件
- **超时控制**：支持用户自定义超时

```typescript
const exit = yield* Effect.raceAll([
  handle.exitCode.pipe(Effect.map((code) => ({ kind: "exit" as const, code }))),
  abort.pipe(Effect.map(() => ({ kind: "abort" as const, code: null }))),
  timeout.pipe(Effect.map(() => ({ kind: "timeout" as const, code: null }))),
])
```

> 源码：[bash.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/bash.ts)

## 4. 工具过滤与条件加载

OpenCode 根据模型动态过滤工具：

```typescript
const tools: Interface["tools"] = Effect.fn("ToolRegistry.tools")(function* (input) {
  const filtered = (yield* all()).filter((tool) => {
    // CodeSearchTool 和 WebSearchTool 仅对特定 provider 启用
    if (tool.id === CodeSearchTool.id || tool.id === WebSearchTool.id) {
      return input.providerID === ProviderID.opencode || Flag.OPENCODE_ENABLE_EXA
    }
    // GPT 模型使用 ApplyPatchTool，非 GPT 使用 EditTool+WriteTool
    const usePatch = input.modelID.includes("gpt-") && !input.modelID.includes("oss") && !input.modelID.includes("gpt-4")
    if (tool.id === ApplyPatchTool.id) return usePatch
    if (tool.id === EditTool.id || tool.id === WriteTool.id) return !usePatch
    return true
  })
})
```

这体现了 OpenCode 对**多模型支持**的深度适配。

## 5. 错误处理与验证

### OpenCode 的参数验证

```typescript
toolInfo.execute = (args, ctx) => {
  return Effect.gen(function* () {
    yield* Effect.try({
      try: () => toolInfo.parameters.parse(args),
      catch: (error) => {
        if (error instanceof z.ZodError && toolInfo.formatValidationError) {
          return new Error(toolInfo.formatValidationError(error), { cause: error })
        }
        return new Error(`The ${id} tool was called with invalid arguments: ${error}.`, { cause: error })
      },
    })
    const result = yield* execute(args, ctx)
    // ...
  }).pipe(Effect.orDie, Effect.withSpan("Tool.execute", { attributes: attrs }))
}
```

使用 Zod 进行运行时参数校验，错误信息可自定义格式化。

## 6. 核心结论

| 维度 | Claude Code (Python) | OpenCode (TypeScript/Effect) |
|------|---------------------|------------------------------|
| **架构** | 镜像快照，尚未执行 | Effect 函数式，完全可执行 |
| **工具来源** | JSON 元数据 | 内置 + 文件系统 + 插件 |
| **Bash 支持** | 无（占位） | 完整 tree-sitter 解析 |
| **权限控制** | 基础过滤 | 动态询问 + 模式匹配 |
| **模型适配** | 静态列表 | 按模型 ID 动态过滤 |
| **错误处理** | 基本返回 | Zod 验证 + Effect 错误传播 |

**本质差异**：Claude Code 是移植项目，采用"记录-回放"思路先把 API 表面定义好；OpenCode 是原生实现，每个工具都是完整的 Effect 函数，强调可组合性和可测试性。

对于想要深入理解 AI Coding Agent 工具调用设计的开发者，OpenCode 的 `registry.ts` + `tool.ts` + `bash.ts` 是一份绝佳的参考教材。

## 参考资料

1. [OpenCode 源码：tool/tool.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts)
2. [OpenCode 源码：tool/registry.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/registry.ts)
3. [OpenCode 源码：tool/bash.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/bash.ts)
4. [Claude Code 源码：tools.py](https://github.com/anomalyco/claude-code/blob/main/src/tools.py)
5. [Claude Code 源码：runtime.py](https://github.com/anomalyco/claude-code/blob/main/src/runtime.py)
