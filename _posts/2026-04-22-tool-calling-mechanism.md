---
layout: post
title: "工具调用机制对比：Claude Code vs OpenCode"
category: AI-Agent
date: 2026-04-22 08:00:00 +0800
---

Sign-off-by: 难易

Assisted-by: OpenClaw:minimax/M2.7

---

## 背景

Claude Code 和 OpenCode 是当前最具代表性的两个 AI Coding Agent 实现。本文从**工具调用机制（Tool Calling）**角度进行深度对比，解析两者在工具抽象、执行模型、权限控制上的设计差异。

---

## 1. 工具定义：声明式 vs 过程式

### Claude Code：镜像快照模式

Claude Code 采用**快照镜像（Mirrored Tools）**策略：

```python
# tools.py - 核心逻辑
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

所有工具定义存储在 `reference_data/tools_snapshot.json` 中，通过 `PortingModule` 数据类声明元数据（name、responsibility、source_hint）。工具本身是"只读镜像"，执行逻辑由被镜像的原始实现处理。

### OpenCode：Effect 系统驱动

OpenCode 使用 **Effect** 编程范式定义工具：

```typescript
// tool.ts - 核心类型定义
export function define<Parameters extends z.ZodType, Result extends Metadata, R, ID extends string = string>(
  id: ID,
  init: Effect.Effect<Init<Parameters, Result>, never, R>,
): Effect.Effect<Info<Parameters, Result>, never, R | Truncate.Service | Agent.Service> & { id: ID }
```

每个工具通过 `Tool.define(id, init)` 声明，返回 `Effect.Effect<Info>`。执行时经过：
1. **参数校验**（Zod schema）
2. **执行业务逻辑**
3. **输出截断**（Truncate.Service）
4. **OpenTelemetry Span** 埋点

> 源码：[opencode/tool.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts)

---

## 2. 工具注册：集中式 vs 分层式

### Claude Code：权限过滤 + MCP 扩展

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

工具列表静态生成，通过 `permission_context` 动态过滤。逻辑简单清晰，但扩展点在于 MCP 插件集成。

### OpenCode：三层插件架构

```typescript
// registry.ts - 三层注册
const state = yield* InstanceState.make(
  Effect.fn("ToolRegistry.state")(function* (ctx) {
    const custom: Tool.Def[] = []

    // Layer 1: 自定义工具目录 {tool,tools}/*.ts
    const matches = dirs.flatMap((dir) =>
      Glob.scanSync("{tool,tools}/*.{js,ts}", { cwd: dir, absolute: true }),
    )
    for (const match of matches) {
      const mod = yield* Effect.promise(() => import(process.platform === "win32" ? match : pathToFileURL(match).href))
      for (const [id, def] of Object.entries<ToolDefinition>(mod)) {
        custom.push(fromPlugin(id, def))
      }
    }

    // Layer 2: 插件工具
    const plugins = yield* plugin.list()
    for (const p of plugins) {
      for (const [id, def] of Object.entries(p.tool ?? {})) {
        custom.push(fromPlugin(id, def))
      }
    }

    // Layer 3: 内置工具
    const tool = yield* Effect.all({
      invalid: Tool.init(invalid),
      bash: Tool.init(bash),
      read: Tool.init(read),
      // ...
    })
  }),
)
```

**三层架构**：
1. **自定义目录**：`{tool,tools}/*.ts` 文件扫描
2. **插件系统**：从 Plugin.Service 获取工具定义
3. **内置工具**：通过 Effect.all 并行初始化

> 源码：[opencode/registry.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/registry.ts)

---

## 3. 执行模型：同步代理 vs Effect 异步

### Claude Code：函数代理

```python
def execute_tool(name: str, payload: str = '') -> ToolExecution:
    module = get_tool(name)
    if module is None:
        return ToolExecution(name=name, source_hint='', payload=payload, handled=False, message=f'Unknown mirrored tool: {name}')
    action = f"Mirrored tool '{module.name}' from {module.source_hint} would handle payload {payload!r}."
    return ToolExecution(name=module.name, source_hint=module.source_hint, payload=payload, handled=True, message=action)
```

执行是**同步函数调用**，payload 以字符串传递，函数签名固定 `execute_tool(name, payload)`。

### OpenCode：Effect Context 链路

```typescript
// bash.ts - 异步流式执行
const result = yield* Effect.runPromise(
  ChildProcess.spawn({
    command,
    workingDirectory: workingDirectory,
    environment: envVars,
    stdin: input,
    timeout: timeoutValue,
    signal: ctx.abort,
  }).pipe(Stream.run.flatMap(() => Stream.empty)),
)
```

执行基于 **Effect**（类似 Haskell 的 IO Monad），支持：
- **流式输出**：通过 `Effect/unstable/Stream` 实现
- **AbortSignal 传播**：与请求生命周期绑定
- **并发控制**：`Effect.forEach(..., { concurrency: "unbounded" })`

---

## 4. 权限控制：上下文过滤 vs 声明式评估

### Claude Code

```python
def filter_tools_by_permission_context(tools: tuple[PortingModule, ...], permission_context: ToolPermissionContext | None = None) -> tuple[PortingModule, ...]:
    if permission_context is None:
        return tools
    return tuple(module for module in tools if not permission_context.blocks(module.name))
```

基于 `ToolPermissionContext.blocks(module.name)` 判断，返回布尔值。逻辑轻量但粒度粗。

### OpenCode

```typescript
// permission/evaluation.ts
export function evaluate(
  tool: string,
  action: string,
  permission: Permission,
): { action: "allow" | "deny" | "ask"; context: Permission.Context | undefined }
```

权限评估返回 `{ action, context }`，支持**运行时上下文**（如当前工作目录、文件路径）。结合 `Permission.evaluate("task", item.name, agent.permission)` 用于任务过滤。

---

## 5. 输出截断：独立服务 vs 内嵌逻辑

### Claude Code

工具执行后输出截断逻辑**未在此模块中直接体现**，可能在上层 Message 处理中。

### OpenCode：Truncate.Service

```typescript
// truncate.ts
export const truncate = (output: string, opts: TruncateOptions, agent: Agent.Info) => {
  const { maxLength, flag } = getLimits(agent.model.id)
  if (output.length <= maxLength) return { content: output, truncated: false }
  return {
    content: output.slice(0, maxLength - flag.length) + flag,
    truncated: true,
    outputPath: writeTruncated(output, opts),
  }
}
```

截断作为独立 Service，通过 `Agent.Info.model.id` 动态判断模型上下文窗口，支持：
- **按模型限制**：不同模型有不同的 maxLength
- **写入文件**：超长输出写入本地文件，返回路径引用

> 源码：[opencode/truncate.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/truncate.ts)

---

## 核心结论

| 维度 | Claude Code | OpenCode |
|------|-------------|----------|
| **定义方式** | JSON 快照镜像 | Effect 声明式 |
| **插件扩展** | MCP 过滤 | 三层架构（目录+插件+内置） |
| **执行模型** | 同步函数调用 | Effect 异步流 |
| **权限控制** | 布尔过滤 | 上下文感知评估 |
| **截断机制** | 未在本模块体现 | 独立 Service |
| **并发管理** | 未明确 | Effect 并发控制 |

**设计哲学差异**：
- **Claude Code** 追求简单、稳定，工具定义以"快照"方式静态化，执行逻辑与声明分离，适合稳定场景
- **OpenCode** 追求灵活、可扩展，Effect 系统提供强类型+声明式+可组合性，适合需要深度定制的 Agent 场景

</div>

</div>

<!-- series: OpenCode 学习系列 -->
<div class="series-nav">
    <span class="series-label">系列：OpenCode 学习系列</span>
    <div class="series-links">
        <a href="/2026/04/21/cli-pipe-model-implementation/" class="nav prev">← CLI 管道模型在 AI Agent 中的落地：Skills 与 Tools 的对接机制</a> &nbsp;|&nbsp; <a href="/2026/04/28/tool-calling-mechanism/" class="nav next">Claude Code vs OpenCode：工具调用机制深度对比 →</a>
    </div>
</div>

---

## 参考资料

1. [Claude Code 源码：tools.py](https://github.com/anthrop/claude-code/blob/main/src/tools.py)
2. [OpenCode 源码：tool.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts)
3. [OpenCode 源码：registry.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/registry.ts)
4. [OpenCode 源码：bash.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/bash.ts)
5. [OpenCode 源码：truncate.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/truncate.ts)
