---
layout: post
title: "MCP 集成深度解析：Hermes Agent、OpenCode 与 Claw-Code 的三方对比"
date: 2026-04-29 10:00:00 +0800
excerpt: ""
---

Sign-off-by: 难易

Assisted-by: Hermes:deepseek-v4-flash

MCP（Model Context Protocol）正在成为 AI Agent 生态中的"USB 接口"——一个标准化的协议，让 LLM 应用能够动态发现和调用外部工具。但不同项目对 MCP 的理解和实现方式差异很大。

本文对比三个开源项目——**Hermes Agent**（Python）、**OpenCode**（TypeScript/Effect）和 **Claw-Code**（Rust）——在 MCP 集成上的架构设计、生命周期管理和工具注册策略。

---

## 一、架构概览

三个项目对 MCP 的定位各不相同：

| 维度 | Hermes Agent | OpenCode | Claw-Code |
|------|-------------|----------|-----------|
| 语言 | Python (asyncio) | TypeScript (Effect) | Rust (tokio) |
| 定位 | 通用 Agent 框架 | AI 编程助手 | AI 编程助手 |
| 传输 | stdio, HTTP | stdio, SSE, StreamableHTTP | stdio, SSE, HTTP, WebSocket, ManagedProxy |
| 客户端 SDK | mcp Python 包 | @modelcontextprotocol/sdk | 自实现 JSON-RPC |
| 生命周期 | 内置重连逻辑 | InstanceState 管理 | 11 阶段精细化生命周期 |

最显著的区别：**Claw-Code** 没有使用官方的 MCP SDK，而是完全自实现了 JSON-RPC 协议栈，从零开始构建了整套 MCP 基础设施。**Hermes Agent** 采用最轻量的策略——只有 stdio 和 HTTP 两种传输，自动注册工具。**OpenCode** 则基于官方 SDK 构建，但融入了一套完整的 Effect 函数式架构。

---

## 二、传输层实现：从简单到全面

### Hermes Agent：轻量双传输

Hermes Agent 的 MCP 实现是最简洁的。它只有两种传输模式，配置方式直白：

```yaml
mcp_servers:
  time:
    command: "uvx"
    args: ["mcp-server-time"]
  remote_api:
    url: "https://mcp.example.com/mcp"
    headers:
      Authorization: "Bearer sk-..."
```

底层使用 `mcp` Python 包的 `stdio_client` 和 `streamable_http`。每个服务器作为独立 asyncio Task 运行，失败时自动重连（指数退避，最多 5 次，最长 60s）。

### OpenCode：官方 SDK + 多传输回退

OpenCode 采用了官方 `@modelcontextprotocol/sdk`，支持三种传输类型。连接远程服务器时，会尝试两种传输方式（`StreamableHTTP` 和 `SSE`），按顺序回退：

```typescript
// src/mcp/index.ts - 远程连接策略
const transports: Array<{ name: string; transport: TransportWithAuth }> = [
  {
    name: "StreamableHTTP",
    transport: new StreamableHTTPClientTransport(new URL(mcp.url), { ... }),
  },
  {
    name: "SSE",
    transport: new SSEClientTransport(new URL(mcp.url), { ... }),
  },
]

for (const { name, transport } of transports) {
  const result = yield* connectTransport(transport, connectTimeout).pipe(
    Effect.map((client) => ({ client, transportName: name })),
    Effect.catch((error) => { /* 失败后尝试下一个 */ }),
  )
  if (result) return { client: result.client, status: { status: "connected" } }
}
```

这种"多传输回退"策略很实用——同一个 MCP 服务器可能同时支持 StreamableHTTP 和 SSE，OpenCode 会优先尝试 StreamableHTTP（更高效率），失败后再退回到 SSE。

### Claw-Code：六种传输 + 自实现协议栈

Claw-Code 支持最多样的传输方式：

```rust
// rust/crates/runtime/src/mcp_client.rs
pub enum McpClientTransport {
    Stdio(McpStdioTransport),       // 子进程 stdin/stdout
    Sse(McpRemoteTransport),        // Server-Sent Events
    Http(McpRemoteTransport),       // HTTP 流式传输
    WebSocket(McpRemoteTransport),  // WebSocket 全双工
    Sdk(McpSdkTransport),           // 内置 SDK 扩展
    ManagedProxy(McpManagedProxyTransport),  // Claude.ai 托管代理
}
```

其中最特别的是 `ManagedProxy`——专门为 Claude.ai 托管的 MCP 代理设计，通过 `claude.ai` 域名的 HTTP 请求反向代理到外部服务器。这反映了 Claw-Code 与 Claude 生态的深度绑定。

更关键的是，Claw-Code **没有使用官方 SDK**。它的 JSON-RPC 通信框架是自实现的：

```rust
// rust/crates/runtime/src/mcp_stdio.rs
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct JsonRpcRequest<T = JsonValue> {
    pub jsonrpc: String,
    pub id: JsonRpcId,
    pub method: String,
    pub params: Option<T>,
}
```

帧编码采用"Content-Length: X\r\n\r\n"的 LSP 风格头，通过 tokio 的 `AsyncBufReadExt` 按行读取。这种自实现方式让 Claw-Code 能完全掌控错误处理、超时和自定义扩展，代价是需要自己维护与 MCP 规范版本（`2025-03-26`）的兼容性。

> 源码：[mcp_client.rs](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/runtime/src/mcp_client.rs)

---

## 三、生命周期管理：从无状态到精细化追踪

### Hermes Agent：简洁重连

Hermes Agent 的 MCP 生命周期很简单：启动时连接，失败时重连（指数退避），关闭时优雅断开。没有中间状态管理。

### OpenCode：InstanceState 驱动

OpenCode 使用 Effect 框架的 `InstanceState` 来管理 MCP 连接的生命周期。每个工作目录（project directory）拥有独立的 MCP 实例状态：

```typescript
// src/mcp/index.ts - InstanceState 管理
const state = yield* InstanceState.make<State>(
  Effect.fn("MCP.state")(function* () {
    const s: State = {
      status: {},    // 每台服务器的连接状态
      clients: {},   // 活跃的 MCP 客户端
      defs: {},      // 缓存的工具定义
    }
    // 启动时遍历配置，并行连接
    yield* Effect.forEach(
      Object.entries(config),
      ([key, mcp]) => create(key, mcp),
      { concurrency: "unbounded" },
    )
    // 关闭时清理
    yield* Effect.addFinalizer(() => {
      // SIGTERM 所有子进程
      // 关闭所有客户端
    })
    return s
  }),
)
```

此外，OpenCode 还追踪每个 MCP 服务器的详细状态，支持六种状态值：

```typescript
export const Status = z.discriminatedUnion("status", [
  z.object({ status: z.literal("connected") }),
  z.object({ status: z.literal("disabled") }),
  z.object({ status: z.literal("failed"), error: z.string() }),
  z.object({ status: z.literal("needs_auth") }),
  z.object({ status: z.literal("needs_client_registration"), error: z.string() }),
])
```

### Claw-Code：11 阶段精细化生命周期

Claw-Code 拥有最精细的生命周期管理。它将 MCP 服务器的整个生命周期分为 **11 个阶段**，从配置加载到清理退出，每个阶段都有独立的错误处理和追踪：

```rust
// rust/crates/runtime/src/mcp_lifecycle_hardened.rs
pub enum McpLifecyclePhase {
    ConfigLoad,           // 配置加载
    ServerRegistration,   // 服务器注册
    SpawnConnect,        // 子进程启动/网络连接
    InitializeHandshake, // MCP 初始化握手
    ToolDiscovery,       // 工具发现
    ResourceDiscovery,   // 资源发现
    Ready,               // 就绪
    Invocation,          // 工具调用
    ErrorSurfacing,      // 错误展示
    Shutdown,            // 关闭
    Cleanup,             // 清理
}
```

每个阶段可能产生三种结果：

```rust
pub enum McpPhaseResult {
    Success { phase: McpLifecyclePhase, duration: Duration },
    Failure { phase: McpLifecyclePhase, error: McpErrorSurface },
    Timeout { phase: McpLifecyclePhase, waited: Duration, error: McpErrorSurface },
}
```

`McpErrorSurface` 还标记了错误是否可恢复（`recoverable: bool`），让上层调度器决定是否需要重启服务器。这种"诊段优先"的设计体现了 Rust 在生产环境中的可靠性思维——宁可多记录，不少追踪。

> 源码：[mcp_lifecycle_hardened.rs](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/runtime/src/mcp_lifecycle_hardened.rs)

---

## 四、工具注册与命名策略

三个项目的工具注册策略差异巨大，直接影响了 LLM 使用这些工具的方式。

### Hermes Agent：扁平式注入

Hermes Agent 将 MCP 工具直接注入 Agent 的工具集（toolset），与其他内置工具平级。命名规则为 `mcp_{server}_{tool}`，所有平台（CLI、Discord、Telegram）自动可用。

```yaml
# 配置一个 filesystem server
mcp_servers:
  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
# 工具自动变成: mcp_filesystem_read_file, mcp_filesystem_write_file
```

### OpenCode：动态工具转换

OpenCode 将 MCP 工具转换为 `ai` SDK 的 `Tool` 类型，融入 AI 调用的工具体系中：

```typescript
// src/mcp/index.ts
function convertMcpTool(mcpTool: MCPToolDef, client: MCPClient, timeout?: number): Tool {
  const schema: JSONSchema7 = {
    ...(inputSchema as JSONSchema7),
    type: "object",
    properties: (inputSchema.properties ?? {}) as JSONSchema7["properties"],
    additionalProperties: false,
  }
  return dynamicTool({
    description: mcpTool.description ?? "",
    inputSchema: jsonSchema(schema),
    execute: async (args: unknown) => {
      return client.callTool({ name: mcpTool.name, arguments: (args || {}) as Record<string, unknown> })
    },
  })
}
```

工具名称通过 `sanitize` 函数处理，使用 `{sanitized_server}_{sanitized_tool}` 的命名格式。同时，OpenCode 还提供了**动态工具列表刷新**机制——服务器可以通过 `ToolListChangedNotification` 通知更新工具列表：

```typescript
// src/mcp/index.ts - 工具变更通知
client.setNotificationHandler(ToolListChangedNotificationSchema, async () => {
  const listed = await bridge.promise(defs(name, client, timeout))
  if (!listed) return
  s.defs[name] = listed
  await bridge.promise(bus.publish(ToolsChanged, { server: name }))
})
```

这意味着 MCP 服务器可以在运行时动态增减工具，而无需重启 OpenCode。

### Claw-Code：前缀分离 + 资源集成

Claw-Code 使用 `mcp__{server_name}__{tool_name}` 命名策略，前缀与工具名之间用**双下划线**分隔：

```rust
// rust/crates/runtime/src/mcp.rs
pub fn mcp_tool_prefix(server_name: &str) -> String {
    format!("mcp__{}__", normalize_name_for_mcp(server_name))
}

pub fn mcp_tool_name(server_name: &str, tool_name: &str) -> String {
    format!("{}{}", mcp_tool_prefix(server_name), normalize_name_for_mcp(tool_name))
}
```

同时，Claw-Code 通过 `McpToolRegistry` 维护完整的 MCP 服务状态注册表，不仅追踪工具（`listTools`），还追踪**资源**（`listResources`），支持 `readResource` 和 `listResources` 这两个 MCP 资源模型的原生操作：

```rust
// rust/crates/runtime/src/mcp_tool_bridge.rs
pub struct McpToolRegistry {
    inner: Arc<Mutex<HashMap<String, McpServerState>>>,
    manager: Arc<OnceLock<Arc<Mutex<McpServerManager>>>>,
}
```

注意这里使用了 `OnceLock`——`McpServerManager` 在首次设置后不可更改，避免了运行时竞态条件。

> 源码：[mcp.rs](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/runtime/src/mcp.rs)

---

## 五、OAuth 认证与远程服务器

只有 OpenCode 实现了完整的 MCP OAuth 认证流程（包括 PKCE 和动态客户端注册）。这是三个项目中最复杂的部分。

### OpenCode 的 OAuth 流程

OpenCode 的 `startAuth` → `authenticate` → `finishAuth` 三阶段流程：

1. **startAuth**：创建 `McpOAuthProvider`，使用 PKCE（Proof Key for Code Exchange）生成 code_verifier，启动本地回调服务器监听 `127.0.0.1:19876`，发起认证 URL
2. **Browser Open**：自动打开浏览器让用户完成授权，通过本地回调服务器接收授权码
3. **finishAuth**：使用授权码调用 `transport.finishAuth()` 完成令牌交换，然后重新连接服务器

```typescript
// src/mcp/index.ts - OAuth 令牌交换
const finishAuth = Effect.fn("MCP.finishAuth")(function* (mcpName: string, authorizationCode: string) {
  const transport = pendingOAuthTransports.get(mcpName)
  const result = yield* Effect.tryPromise({
    try: () => transport.finishAuth(authorizationCode).then(() => true as const),
  })
  yield* auth.clearCodeVerifier(mcpName)
  pendingOAuthTransports.delete(mcpName)
  return yield* createAndStore(mcpName, config)  // 重新连接
})
```

OpenCode 还实现了**基于文件系统的令牌存储**——`McpAuth` 服务将刷新令牌持久化到本地文件，支持令牌到期检测和自动刷新。同时支持 **CSRF 保护**——通过 OAuth state 参数验证回调来源。

> 源码：[mcp/index.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/mcp/index.ts)

### Claw-Code 的 OAuth 支持

Claw-Code 在其配置中也定义了 OAuth 支持，包含 `client_id`、`callback_port`、`auth_server_metadata_url` 等字段，但在实现上主要是**配置层面的支持**，用于签名计算和连接参数，没有 OpenCode 那样的完整交互式认证流程。

---

## 六、Hermes Agent 的特色：环境隔离与采样

Hermes Agent 的设计更加精简，但在安全和可扩展性上有独特的设计。

### 环境变量过滤

Hermes Agent 在启动 stdio MCP 服务器子进程时，会**过滤环境变量**——只传递 `PATH`、`HOME`、`LANG` 等安全基线变量，所有凭据（API keys、tokens）默认排除。用户必须显式通过 `env` 配置传递：

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_xxx"
```

### Sampling（服务端发起 LLM 请求）

Hermes Agent 支持 MCP 规范中更进阶的 `sampling/createMessage` 能力——MCP 服务器在执行工具过程中可以**向 Agent 发起 LLM 推理请求**，实现双向交互：

```yaml
mcp_servers:
  my_server:
    command: "npx"
    args: ["-y", "my-mcp-server"]
    sampling:
      enabled: true
      model: "gemini-3-flash"
      max_tokens_cap: 4096
      max_tool_rounds: 5       # 防止无限工具循环
```

这在三个项目中是唯一实现了 MCP 采样功能的，体现了其"通用 Agent 框架"的定位——不仅要调用外部工具，还要作为 MCP 协议的**服务端**响应其他系统的推理请求。

### 凭据脱敏

错误信息中的凭据模式（`ghp_xxx`、`sk-xxx`、`Bearer` tokens 等）会被自动脱敏，防止 LLM 看到明文凭据。

---

## 七、对比总结

| 维度 | Hermes Agent | OpenCode | Claw-Code |
|------|-------------|----------|-----------|
| **MCP SDK** | 官方 Python SDK | 官方 TS SDK | 完全自实现 |
| **传输数量** | 2 (stdio, HTTP) | 3 (stdio, SSE, StreamableHTTP) | **6** (stdio, SSE, HTTP, WS, SDK, ManagedProxy) |
| **生命周期** | 内置重连 | InstanceState + 6 状态 | **11 阶段**精细追踪 |
| **OAuth** | ❌ | ✅ 完整 PKCE 流程 | ⚠️ 配置支持 |
| **Sampling** | ✅ 支持 | ❌ | ❌ |
| **资源模型** | ❌ | ✅ listPrompts/listResources | ✅ listResources |
| **动态工具变更** | ❌ | ✅ 通知机制 | ❌ 需要重新发现 |
| **错误脱敏** | ✅ | ❌ | ❌ |
| **工具命名** | `mcp_{srv}_{tool}` | `{srv}_{tool}` | `mcp__{srv}__{tool}` |

从架构角度看：

- **Hermes Agent** 追求的是"即插即用"——配置最少、安全最好（环境隔离、错误脱敏）、功能最实用（Sampling 支持）。适合作为中心 Agent 框架集成各种 MCP 服务器。

- **OpenCode** 追求的是"协议完整性"——完整的 OAuth 流程、动态工具通知、多传输回退。它对 MCP 规范的支持最全面，适合企业级部署需要高可用 MCP 场景。

- **Claw-Code** 追求的是"全控制与可观测性"——自实现协议栈、11 阶段生命周期、6 种传输、资源模型原生支持。它的设计适合深度定制 MCP 行为和精细故障诊断的场景，尤其适合与 Claude.ai 生态深度整合。

三个项目在 MCP 集成上的不同选择，本质上是它们各自定位的折射：**通用 Agent 框架**、**AI 编程助手的前沿探索者**、**与 Claude 深度绑定的生产级工具**。MCP 作为标准协议的优势也因此体现——同一个协议，不同项目可以在实现深度和功能广度上自由选择。

---

## 参考资料

- [Hermes Agent MCP 配置文档](https://hermes-agent.nousresearch.com/docs/features/mcp)
- [OpenCode MCP 实现](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/mcp/index.ts)
- [Claw-Code MCP 客户端](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/runtime/src/mcp_client.rs)
- [Claw-Code MCP 生命周期](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/runtime/src/mcp_lifecycle_hardened.rs)
- [Claw-Code MCP 工具桥接](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/runtime/src/mcp_tool_bridge.rs)
- [Model Context Protocol 规范](https://spec.modelcontextprotocol.io/)
