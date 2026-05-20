---
layout: post
title: "Agent 会话生命周期管理：Claw-Code（Rust）与 OpenCode（TypeScript）的对比分析"
category: AI编程
date: 2026-04-28 10:00:00 +0800
excerpt: "Claw-Code（Rust）与 OpenCode（TypeScript）在 Agent 会话生命周期管理上的设计差异对比"
---

Sign-off-by: 难易

Assisted-by: Hermes:deepseek-v4-flash

AI Coding Agent 的核心是"循环调用 LLM + 工具执行"，而支撑这个循环的基础设施之一是**会话（Session）管理系统**。Agent 需要记住对话历史、追踪工具调用的结果、支持回退操作、在崩溃后恢复状态——这些都依赖一个健壮的会话生命周期管理。

本文对比两个开源 Agent 框架——**Claw-Code**（Rust）和 **OpenCode**（TypeScript）——在会话管理上的设计差异。

---

## 一、存储层：文件系统 vs 数据库

### Claw-Code：基于 workspace 指纹的文件系统

Claw-Code 的会话存储核心是 `SessionStore`，位于 `session_control.rs`：

```rust
// rust/crates/runtime/src/session_control.rs
pub struct SessionStore {
    sessions_root: PathBuf,
    workspace_root: PathBuf,
}

impl SessionStore {
    pub fn from_cwd(cwd: impl AsRef<Path>) -> Result<Self, SessionControlError> {
        let canonical_cwd = fs::canonicalize(cwd)
            .unwrap_or_else(|_| cwd.to_path_buf());
        let sessions_root = canonical_cwd
            .join(".claw")
            .join("sessions")
            .join(workspace_fingerprint(&canonical_cwd));
        fs::create_dir_all(&sessions_root)?;
        Ok(Self { sessions_root, workspace_root: canonical_cwd })
    }
}
```

设计亮点：

- **Workspace 指纹隔离**：`workspace_fingerprint` 从工作目录的规范化路径计算稳定哈希，确保并行 `opencode serve` 实例不会碰撞
- **符号链接归一化**：通过 `fs::canonicalize` 解决 `/tmp` 与 `/private/tmp`（macOS）等不同路径表示产生的哈希不一致问题（ticket #151）
- **双构造器**：`from_cwd` 自动推导存储路径，`from_data_dir` 支持显式 `--data-dir` 参数

> 源码：[session_control.rs](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/runtime/src/session_control.rs)

### OpenCode：Zod Schema + Effect 数据库层

OpenCode 的会话存储走的是一条更"TypeScript 生态"的路线——Zod 运行时校验 + Effect 副作用管理：

```typescript
// session/session.ts - Schema 定义
export const Info = z.object({
  sessionID: SessionID.zod,
  title: z.string(),
  createdAt: z.number(),
  updatedAt: z.number(),
  projectSlug: z.string().optional(),
  fork: ForkInfo.zod.optional(),
  revert: RevertInfo.zod.optional(),
  archivedAt: z.number().optional(),
})

export interface Interface {
  readonly create: (input: CreateInput) => Effect.Effect<Info>
  readonly get: (input: GetInput) => Effect.Effect<Info>
  readonly fork: (input: ForkInput) => Effect.Effect<Info>
  readonly messages: (input: MessagesInput) => Effect.Effect<MessageV2.Info[]>
}
```

Service 通过 `Context.Tag` 注册，由 `Layer` 组合注入——这比 Rust 的 `impl` trait 模式更灵活，但也意味着类型错误可能被延迟到运行时。

> 源码：[session.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/session.ts)

### 对比

| 维度 | Claw-Code (Rust) | OpenCode (TypeScript) |
|------|-----------------|----------------------|
| 底层存储 | 文件系统 (`~/.claw/sessions/`) | SQLite (via Storage Service) |
| 序列化 | 自定义 Session struct + serde | Zod schema + SQL rows |
| 隔离粒度 | workspace 哈希命名空间 | 数据库 session 表 + projectSlug |
| 路径安全 | 编译时检查 | 运行时 Zod 校验 |

---

## 二、会话分支：Fork 机制对比

### Claw-Code：原生分支支持

Claw-Code 的 `fork_session` 是一个一等公民操作，生成完整的 `ForkedManagedSession`，包含父会话引用和分支名：

```rust
pub fn fork_session(
    &self,
    session: &Session,
    branch_name: Option<String>,
) -> Result<ForkedManagedSession, SessionControlError> {
    let parent_session_id = session.session_id.clone();
    let forked = session
        .fork(branch_name)
        .with_workspace_root(self.workspace_root.clone());
    let handle = self.create_handle(&forked.session_id);
    let forked = forked.with_persistence_path(handle.path.clone());
    forked.save_to_path(&handle.path)?;
    Ok(ForkedManagedSession {
        parent_session_id,
        handle,
        session: forked,
        branch_name,
    })
}
```

每个 Forked 会话都可追溯回父会话（`parent_session_id`），与 Git 分支的语义一致。

### OpenCode：Revert 模式

OpenCode 没有直接的 fork 概念，而是通过 **revert（回退）** 实现类似效果：

```typescript
export const ForkInput = z.object({
  sessionID: SessionID.zod,
  messageID: MessageID.zod.optional(),
})

export interface Interface {
  readonly revert: (input: RevertInput) => Effect.Effect<Session.Info>
  readonly unrevert: (input: { sessionID: SessionID }) => Effect.Effect<Session.Info>
}
```

Revert 不是复制整个会话，而是记录一个"回退点"（snapshot），回退时丢弃后面的消息，但保留快照以便 `unrevert` 恢复。

---

## 三、错误处理与宿命

### Claw-Code：枚举式错误分类

```rust
pub enum SessionControlError {
    Io(std::io::Error),
    Serde(serde_json::Error),
    Format(String),
    WorkspaceMismatch {
        expected: PathBuf,
        actual: PathBuf,
    },
    SessionNotFound(String),
    PathTraversal,
}
```

Rust 枚举的优势在于**穷尽匹配**——所有可能的错误场景都在类型系统中明确。新增错误处理分支时，编译器会强制检查所有 match 表达式是否完备。

### OpenCode：Effect 的 Cause 系统

OpenCode 使用 Effect 的 `Cause` 错误模型，配合 `retry.ts` 的指数退避：

```typescript
export const RETRY_INITIAL_DELAY = 2000
export const RETRY_BACKOFF_FACTOR = 2
export const RETRY_MAX_DELAY = 2_147_483_647

export function delay(attempt: number, error?: MessageV2.APIError) {
  // 优先使用服务器返回的 retry-after 头
  if (error) {
    const headers = error.data.responseHeaders
    if (headers?.["retry-after-ms"]) {
      return cap(Number.parseFloat(headers["retry-after-ms"]))
    }
  }
  // 否则按指数退避
  return cap(RETRY_INITIAL_DELAY * Math.pow(RETRY_BACKOFF_FACTOR, attempt - 1))
}
```

同时通过 `SessionRunState` 管理并发安全：

```typescript
export interface Interface {
  readonly assertNotBusy: (sessionID: SessionID) => Effect.Effect<void>
  readonly cancel: (sessionID: SessionID) => Effect.Effect<void>
  readonly ensureRunning: (...) => Effect.Effect<MessageV2.WithParts>
}
```

`assertNotBusy` 在 revert 操作前调用，防止并发修改导致状态不一致。

---

## 四、会话摘要与元数据

### Claw-Code：ManagedSessionSummary

```rust
pub struct ManagedSessionSummary {
    pub id: String,
    pub path: PathBuf,
    pub updated_at_ms: u64,
    pub modified_epoch_millis: u128,
    pub message_count: usize,
    pub parent_session_id: Option<String>,
    pub branch_name: Option<String>,
}
```

排序策略：先按更新时间降序，同时间按修改时间降序，最后按 ID 排序：

```rust
fn sort_managed_sessions(sessions: &mut [ManagedSessionSummary]) {
    sessions.sort_by(|left, right| {
        right.updated_at_ms.cmp(&left.updated_at_ms)
            .then_with(|| right.modified_epoch_millis.cmp(&left.modified_epoch_millis))
            .then_with(|| right.id.cmp(&left.id))
    });
}
```

### OpenCode：Summary Service

OpenCode 通过独立的 `SessionSummary` Service 计算差异摘要，回退时会记录 `session_diff`：

```typescript
const diffs = yield* summary.computeDiff({ messages: range })
yield* storage.write(["session_diff", input.sessionID], diffs)
yield* bus.publish(Session.Event.Diff, { sessionID: input.sessionID, diff: diffs })
```

事件总线 (`Bus.Service`) 将变更推送给 UI 层，TUI 无需轮询即可实时反映状态。

---

## 五、设计哲学差异

深入看两套代码后，能感受到不同的设计哲学：

| 维度 | Claw-Code (Rust) | OpenCode (TypeScript) |
|------|-----------------|----------------------|
| **核心抽象** | 文件 + 结构体 | Service + Effect |
| **隔离性** | 编译器强制 + 工作区间隔离 | 运行时校验 + 锁机制 |
| **状态持久化** | session::Session → serde → 磁盘 | Zod schema → SQL row |
| **并发安全** | 文件锁 / 操作系统保证 | Runner + assertNotBusy |
| **分支模型** | 一等公民（Git 式 fork） | revert/snapshot 模式 |
| **错误分类** | enum 穷尽匹配 | Cause + retry 策略 |
| **监控集成** | Telemetry crate | Event Bus + Bus.Publish |

Rust 的选择体现了**编译期安全**的追求——类型的组合确保错误场景在编译时就被覆盖齐全。TypeScript + Effect 的选择则强调**运行时弹性**——复杂的 retry 策略、动态的 snapshot 管理、事件驱动的 UI 更新，这些在动态系统中更容易表达。

没有谁绝对优于谁。Claw-Code 更适合需要确定性、高性能、低资源占用的场景；OpenCode 则更适合需要快速迭代、丰富 UI 交互、灵活错误恢复的开发者工具。

---

## 参考资料

1. [Claw-Code 源码：session_control.rs](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/runtime/src/session_control.rs)
2. [OpenCode 源码：session.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/session.ts)
3. [OpenCode 源码：run-state.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/run-state.ts)
4. [OpenCode 源码：retry.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/retry.ts)
5. [OpenCode 源码：revert.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/revert.ts)
