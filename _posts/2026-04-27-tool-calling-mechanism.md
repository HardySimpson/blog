---
layout: post
title: "Claude Code vs OpenCode 工具调用机制对比分析"
date: 2026-04-27 08:00:00 +0800
---

Sign-off-by: 难易

Assisted-by: 4090龙虾:minimax/M2.7

---

## 引言

Claude Code 和 OpenCode 是当前最具代表性的两个 AI 代码助手项目。两者都实现了复杂的工具调用（Tool Calling）机制，但在架构设计上走了截然不同的路线。

本文从**工具定义、注册机制、执行流程、权限控制**四个维度，深入对比两者的实现差异。

---

## 一、工具定义：从快照到 Effect

### Claude Code：镜像快照模式

Claude Code 的工具系统采用**快照镜像（Mirrored Tools）**模式。核心源码位于 [`src/tools.py`](https://github.com/anomalyco/claude-code/blob/main/src/tools.py)：

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

PORTED_TOOLS = load_tool_snapshot()
```

工具定义存储在 `reference_data/tools_snapshot.json` 中，Python 层只是对 TypeScript 源码的工具镜像。定义本身是静态的 JSON 数据，描述工具的**名称、来源、职责**。

### OpenCode：Effect 驱动的函数式定义

OpenCode 采用 **Effect TypeScript** 框架，工具以函数式风格定义。核心接口在 [`src/tool/tool.ts`](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts)：

```typescript
export interface Def<Parameters extends z.ZodType = z.ZodType, M extends Metadata = Metadata> {
  id: string
  description: string
  parameters: Parameters
  execute(args: z.infer<Parameters>, ctx: Context): Effect.Effect<ExecuteResult<M>>
  formatValidationError?(error: z.ZodError): string
}

export function define<Parameters extends z.ZodType, Result extends Metadata, R>(
  id: ID,
  init: Effect.Effect<Init<Parameters, Result>, never, R>,
): Effect.Effect<Info<Parameters, Result>, never, R | Truncate.Service | Agent.Service> & { id: ID }
```

每个工具都是一个完整的 Effect，包含参数校验、执行逻辑、元数据。每个工具通过 `Tool.define('name', Effect.gen(...))` 注册，执行时返回 `Effect.Effect<ExecuteResult>`。

**对比：**

| 维度 | Claude Code | OpenCode |
|------|-------------|----------|
| 定义格式 | 静态 JSON 快照 | 动态 Effect 函数 |
| 参数校验 | 外部处理 | 内置 Zod schema |
| 执行模型 | Python 函数调用 | 函数式 Effect |
| 工具数量 | 镜像自 TypeScript | 原生 TypeScript 实现 |

---

## 二、注册机制：泳池组装 vs 分层服务

### Claude Code：工具池组装

Claude Code 通过 [`src/tool_pool.py`](https://github.com/anomalyco/claude-code/blob/main/src/tool_pool.py) 组装工具池：

```python
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

工具池是一个简单的数据结构，通过 `get_tools()` 筛选可用的工具。`simple_mode` 只保留 `BashTool`、`FileReadTool`、`FileEditTool` 三个核心工具。

### OpenCode：分层依赖注入服务

OpenCode 的工具注册在 [`src/tool/registry.ts`](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/registry.ts)，实现为 Context.Service 依赖注入服务：

```typescript
export class Service extends Context.Service<Service, Interface>()("@opencode/ToolRegistry") {}

export const layer: Layer.Layer<Service, never, ...> = Layer.effect(
  Service,
  Effect.gen(function* () {
    const state = yield* InstanceState.make<State>(
      Effect.fn("ToolRegistry.state")(function* (ctx) {
        const custom: Tool.Def[] = []
        // 从插件加载自定义工具
        for (const p of plugins) {
          for (const [id, def] of Object.entries(p.tool ?? {})) {
            custom.push(fromPlugin(id, def))
          }
        }
        // ... 内置工具
        return { custom, builtin: [...] }
      })
    )
    return Service.of({ ids, all, named, tools })
  })
)
```

支持三种工具来源：
1. **内置工具**：Bash、Read、Edit、Write、Glob、Grep、Task、WebFetch 等
2. **自定义工具**：从 `{tool,tools}/*.{js,ts}` 目录扫描加载
3. **插件工具**：通过 Plugin API 注册

---

## 三、执行流程：路由匹配 vs 上下文分发

### Claude Code：路由 + 执行注册表

Claude Code 的工具执行通过 [`src/runtime.py`](https://github.com/anomalyco/claude-code/blob/main/src/runtime.py) 的 `PortRuntime` 类：

```python
def route_prompt(self, prompt: str, limit: int = 5) -> list[RoutedMatch]:
    tokens = {token.lower() for token in prompt.replace('/', ' ').replace('-', ' ').split() if token}
    by_kind = {
        'command': self._collect_matches(tokens, PORTED_COMMANDS, 'command'),
        'tool': self._collect_matches(tokens, PORTED_TOOLS, 'tool'),
    }
    # 按 token 匹配选择最佳工具/命令
```

执行时通过 `execution_registry.py` 查找工具实现：

```python
matched_tools=tuple(match.name for match in matches if match.kind == 'tool'),
# ...
tool_execs = tuple(
    registry.tool(match.name).execute(prompt)
    for match in matches if match.kind == 'tool' and registry.tool(match.name)
)
```

本质是 **token 级别的字符串匹配** + **注册表查找**。

### OpenCode：流式处理 + 状态机

OpenCode 的工具执行在 [`src/session/processor.ts`](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/processor.ts) 中实现为状态机：

```typescript
interface Handle {
  readonly message: MessageV2.Assistant
  readonly updateToolCall: (toolCallID: string, update: (part: MessageV2.ToolPart) => MessageV2.ToolPart) => Effect.Effect<MessageV2.ToolPart | undefined>
  readonly completeToolCall: (toolCallID: string, output: {...}) => Effect.Effect<void>
  readonly process: (streamInput: LLM.StreamInput) => Effect.Effect<Result>
}
```

`SessionProcessor` 管理完整的工具调用生命周期：
1. 接收 LLM 流事件
2. 解析 `tool_call` 块
3. 通过 `updateToolCall` 更新执行状态
4. 通过 `completeToolCall` 返回结果
5. 支持流式增量更新

---

## 四、权限控制：上下文过滤 vs 评估引擎

### Claude Code：工具级别权限上下文

```python
def filter_tools_by_permission_context(
    tools: tuple[PortingModule, ...],
    permission_context: ToolPermissionContext | None = None,
) -> tuple[PortingModule, ...]:
    if permission_context is None:
        return tools
    return tuple(module for module in tools if not permission_context.blocks(module.name))
```

简单的黑名单模式，基于工具名称阻止访问。

### OpenCode：细粒度权限评估

OpenCode 的权限系统在 [`src/permission/`](https://github.com/anomalyco/opencode/tree/dev/packages/opencode/src/permission) 中：

```typescript
const describeTask = Effect.fn("ToolRegistry.describeTask")(function* (agent: Agent.Info) {
  const items = (yield* agents.list()).filter((item) => item.mode !== "primary")
  const filtered = items.filter(
    (item) => Permission.evaluate("task", item.name, agent.permission).action !== "deny",
  )
  // ...
})
```

每个工具执行时都经过 `Permission.evaluate()` 检查，支持基于 agent 类型的动态权限配置。

---

## 五、特殊机制：模型适配

OpenCode 有一个值得注意的设计：**根据模型选择不同的编辑工具**。

```typescript
const tools: Interface["tools"] = Effect.fn("ToolRegistry.tools")(function* (input) {
  const filtered = (yield* all()).filter((tool) => {
    // CodeSearch 和 WebSearch 仅限 OpenCode provider
    if (tool.id === CodeSearchTool.id || tool.id === WebSearchTool.id) {
      return input.providerID === ProviderID.opencode || Flag.OPENCODE_ENABLE_EXA
    }

    const usePatch = input.modelID.includes("gpt-") && !input.modelID.includes("oss") && !input.modelID.includes("gpt-4")
    if (tool.id === ApplyPatchTool.id) return usePatch
    if (tool.id === EditTool.id || tool.id === WriteTool.id) return !usePatch

    return true
  })
  return yield* Effect.forEach(filtered, ...)
})
```

- **GPT 系列（非 o4）**：使用 `ApplyPatchTool`（结构化 patch 应用）
- **其他模型**：使用 `EditTool` + `WriteTool`（直接文件编辑）

这种设计根据 LLM 的能力特点动态切换工具集，是非常务实的工程选择。

---

## 结论

| 维度 | Claude Code | OpenCode |
|------|-------------|----------|
| 设计哲学 | 镜像 + 简单 | 原生 + 可扩展 |
| 工具定义 | 静态 JSON | 动态 Effect |
| 注册机制 | 泳池组装 | 依赖注入服务 |
| 执行模型 | 同步路由匹配 | 异步流式状态机 |
| 权限控制 | 黑名单过滤 | 评估引擎 |
| 模型适配 | 未体现 | ApplyPatch vs EditTool |

Claude Code 的工具系统更简洁，适合快速移植；OpenCode 的工具系统更灵活，支持插件、热加载、模型适配。两者代表了 AI 代码助手工具系统的两种设计方向。

<!-- series: 工具调用机制对比系列 -->
<div class="series-nav">
    <span class="series-label">系列：工具调用机制对比系列</span>
    <div class="series-links">
        <a href="/2026/04/22/tool-calling-mechanism/" class="nav prev">← 工具调用机制对比：Claude Code vs OpenCode</a>
    </div>
</div>

---

## 参考资料

1. [Claude Code tools.py](https://github.com/anomalyco/claude-code/blob/main/src/tools.py)
2. [Claude Code tool_pool.py](https://github.com/anomalyco/claude-code/blob/main/src/tool_pool.py)
3. [Claude Code runtime.py](https://github.com/anomalyco/claude-code/blob/main/src/runtime.py)
4. [OpenCode tool.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/tool.ts)
5. [OpenCode registry.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/registry.ts)
6. [OpenCode processor.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/processor.ts)
7. [OpenCode apply_patch.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/apply_patch.ts)
