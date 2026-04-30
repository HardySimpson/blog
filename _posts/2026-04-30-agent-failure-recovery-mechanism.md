---
layout: post
title: "AI Agent 的故障恢复机制：Claw-Code 的 Recovery Recipes 与 OpenCode 的 Effect Retry 对比"
category: AI编程
date: 2026-04-30 10:00:00 +0800
excerpt: "AI Coding Agent 在运行中不可避免会遇到各种故障——Provider 超时、MCP 握手失败、Prompt 投递错误、编译失败。本文深入分析 Claw-Code（Rust）和 OpenCode（TypeScript）在故障恢复上的两种不同哲学：声明式配方 vs 命令式重试。"
---

Sign-off-by: 难易

Assisted-by: Hermes:deepseek-v4-flash

AI Coding Agent 的核心是 LLM + 工具循环执行，但这个循环随时可能被打断——Provider 返回 503、MCP 服务器握手失败、Git 分支过时导致编译错误、Prompt 投递到错误的 channel。Agent 能不能优雅地处理这些故障，决定了它是\"可靠的助手\"还是\"一碰就碎的玩具\"。

本文深入两个开源 Agent 框架——**Claw-Code**（Rust）和 **OpenCode**（TypeScript）——的源代码，分析它们在故障恢复机制上的设计差异。

---

## 一、Claw-Code：声明式 Recovery Recipes

Claw-Code 的恢复机制是我在开源 Agent 框架中见过最**系统化**的。它不是零散地写一堆 try-catch，而是用一套 **Recovery Recipe（恢复配方）系统**来声明式地描述故障处理。

### 1.1 故障场景枚举

核心代码在 `recovery_recipes.rs`，首先定义 7 种已知故障场景：

```rust
// rust/crates/runtime/src/recovery_recipes.rs:16-26
pub enum FailureScenario {
    TrustPromptUnresolved,    // 信任提示未解决
    PromptMisdelivery,        // Prompt 投递错误
    StaleBranch,              // Git 分支过时
    CompileRedCrossCrate,     // 编译交叉 crate
    McpHandshakeFailure,      // MCP 握手失败
    PartialPluginStartup,     // 插件部分启动失败
    ProviderFailure,          // LLM Provider 故障
}
```

> 源码：[recovery_recipes.rs](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/runtime/src/recovery_recipes.rs)

### 1.2 恢复配方定义

每个场景都有对应的**恢复步骤序列**，精确描述做什么：

```rust
// rust/crates/runtime/src/recovery_recipes.rs:179-229
pub fn recipe_for(scenario: &FailureScenario) -> RecoveryRecipe {
    match scenario {
        FailureScenario::PromptMisdelivery => RecoveryRecipe {
            steps: vec![RecoveryStep::RedirectPromptToAgent],
            max_attempts: 1,
            escalation_policy: EscalationPolicy::AlertHuman,
        },
        FailureScenario::StaleBranch => RecoveryRecipe {
            steps: vec![RecoveryStep::RebaseBranch, RecoveryStep::CleanBuild],
            max_attempts: 1,
            escalation_policy: EscalationPolicy::AlertHuman,
        },
        FailureScenario::ProviderFailure => RecoveryRecipe {
            steps: vec![RecoveryStep::RestartWorker],
            max_attempts: 1,
            escalation_policy: EscalationPolicy::AlertHuman,
        },
        // ... 其他场景
    }
}
```

设计亮点：

- **max_attempts: 1 的设计隐含了一个原则**：自动恢复只尝试一次，不行就上报给人类。这避免了 Agent 陷入无限重试的死循环
- **EscalationPolicy** 有三个级别：`AlertHuman`（通知用户）、`LogAndContinue`（记日志继续）、`Abort`（终止）——给不同严重程度的故障分出优先级
- **步骤序列可组合**：`StaleBranch` 需要先 rebase 再 build，两步之间是顺序依赖

### 1.3 Worker 重启状态机

当 Provider 故障或 Prompt 投递错误发生时，恢复配方的最终手段通常是 `RestartWorker`。这是通过 Worker 状态机实现的：

```rust
// rust/crates/runtime/src/worker_boot.rs:569-590
pub fn restart(&self, worker_id: &str) -> Result<Worker, String> {
    let worker = inner.workers.get_mut(worker_id)?;
    worker.status = WorkerStatus::Spawning;
    worker.trust_gate_cleared = false;
    worker.last_prompt = None;
    worker.replay_prompt = None;
    worker.last_error = None;
    worker.prompt_delivery_attempts = 0;
    worker.prompt_in_flight = false;
    push_event(worker, WorkerEventKind::Restarted, ...);
    Ok(worker.clone())
}
```

> 源码：[worker_boot.rs](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/runtime/src/worker_boot.rs)

重启不是简单地杀掉重开——它会**保留 `replay_prompt` 字段**用于 prompt 重放。也就是说，如果此前有一次 Prompt 投递失败，Worker 在重启后会通过 `replay_prompt` 自动重试这条消息。Prompt 重放机制位于同一个文件的第 421-437 行：

```rust
if worker.auto_recover_prompt_misdelivery && is_misdelivery {
    worker.replay_prompt = Some(last_prompt.clone());
    worker.status = WorkerStatus::ReadyForPrompt;
}
```

### 1.4 Provider Fallback 链

API 调用层面，Claw-Code 提供了静态配置的 Provider 回退链：

```rust
// rust/crates/runtime/src/config.rs:70-77
/// Ordered chain of fallback model identifiers used when the primary
/// provider returns a retryable failure (429/500/503/etc.).
pub struct ProviderFallbackConfig {
    primary: Option<String>,
    fallbacks: Vec<String>, // 严格顺序，依次尝试
}
```

结合底层 Anthropic provider 的带抖动指数退避：

```rust
// rust/crates/api/src/providers/anthropic.rs:401-464
fn send_with_retry(&self, request, max_retries, initial_backoff, max_backoff) {
    for attempt in 0..=max_retries {
        match self.send(request).await {
            Ok(response) => return Ok(response),
            Err(e) if e.is_retryable() => {
                let backoff = calculate_backoff(attempt, initial_backoff, max_backoff);
                sleep(backoff + jitter()).await; // 加随机抖动
                continue;
            }
            Err(e) => return Err(e), // 不可重试，立刻返回
        }
    }
}
```

> 源码：[config.rs](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/runtime/src/config.rs)

**多层恢复栈**：API 层（指数退避重试）→ Provider 层（回退链）→ Worker 层（重启+prompt 重放）→ Recovery 层（配方+升级策略）。每层解决不同粒度的故障，彼此独立。

---

## 二、OpenCode：Effect 驱动的命令式恢复

OpenCode 选择了完全不同的路线——依赖 TypeScript Effect 库的 `Effect.retry` 能力，配合 Git 快照系统实现文件级的回滚。

### 2.1 核心 Retry 策略

最底层的重试逻辑在 `session/retry.ts`：

```typescript
// packages/opencode/src/session/retry.ts:12-15
export const RETRY_INITIAL_DELAY = 2000
export const RETRY_BACKOFF_FACTOR = 2
export const RETRY_MAX_DELAY_NO_HEADERS = 30_000
```

```typescript
// packages/opencode/src/session/retry.ts:21-52
export function delay(attempt: number, error?: MessageV2.APIError) {
  if (error) {
    const headers = error.data.responseHeaders
    if (headers) {
      // 优先服务器 retry-after 头
      const retryAfterMs = headers["retry-after-ms"]
      if (retryAfterMs) return cap(Number.parseFloat(retryAfterMs))
      // 支持 HTTP-date 格式
      const retryAfter = headers["retry-after"]
      if (retryAfter) { /* 解析秒或日期 */ }
    }
  }
  // 否则指数退避
  return cap(RETRY_INITIAL_DELAY * Math.pow(RETRY_BACKOFF_FACTOR, attempt - 1))
}
```

> 源码：[retry.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/retry.ts)

相比 Claw-Code 的纯指数退避，OpenCode 多了一个细节：**优先尊重服务端返回的 `retry-after` 头部**。如果 Provider 说"30 秒后再试"，就严格等 30 秒，而不是按自己的算法来决定。这更符合 HTTP 语义，也避免了与 Provider 限流策略的冲突。

### 2.2 重试目标判断

```typescript
// packages/opencode/src/session/retry.ts:54-60
export function retryable(error: Err) {
  // 上下文溢出错误不重试（因为只会继续溢出）
  if (MessageV2.ContextOverflowError.isInstance(error)) return undefined
  if (MessageV2.APIError.isInstance(error)) {
    // 5xx 必须重试，即便 SDK 没标记
    if (!error.data.isRetryable && !(status >= 500)) return undefined
    if (error.data.responseBody?.includes("FreeUsageLimitError"))
      return GO_UPSELL_MESSAGE
  }
}
```

这里有个反直觉但非常实用的设计决定：**上下文溢出（ContextOverflowError）直接跳过重试**——因为 LLM 再次请求只会继续增加上下文长度，问题不会自动解决。而 5xx 错误则相反，**即使 Provider SDK 没有标记为可重试，也强制重试**，因为 5xx 通常是临时性服务器错误。

### 2.3 Session Processor 的 Effect.retry 封装

重试策略实际作用于 Session Processor 中的 LLM 流式调用：

```typescript
// packages/opencode/src/session/processor.ts:568-579
yield* Effect.retry(
  Effect.catchCauseIf(
    stream,
    (cause) => !Cause.isInterruptedOnly(cause) // 用户取消不重试
  ),
  SessionRetry.policy(opts) // 用自定义策略调度
)
```

这里用 `Effect.catchCauseIf` 做了一个重要的过滤——**用户主动中断（Ctrl+C）不会触发重试**。重试只在服务器错误、限流等场景下生效。

### 2.4 Git 快照：文件级回滚

当 Agent 的编辑操作导致不可逆的结果，OpenCode 用 Git 快照系统来做文件级的恢复：

```typescript
// packages/opencode/src/snapshot/index.ts:351-375
const restore = Effect.fnUntraced(function* (snapshot: string) {
  return yield* locked(
    Effect.gen(function* () {
      const result = yield* git([...core, ...args(["read-tree", snapshot])], { cwd: state.worktree })
      if (result.code === 0) {
        const checkout = yield* git([...core, ...args(["checkout-index", "-a", "-f"])], { cwd: state.worktree })
      }
    })
  )
})
```

> 源码：[snapshot/index.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/snapshot/index.ts)

### 2.5 Session Revert：操作级回退

结合快照，OpenCode 的 `SessionRevert` 实现了粒度为单条消息的回退：

```typescript
// packages/opencode/src/session/revert.ts:41-90
const revert = Effect.fn("SessionRevert.revert")(function* (input: RevertInput) {
  yield* state.assertNotBusy(input.sessionID)        // 并发安全

  rev.snapshot = session.revert?.snapshot ??
    (yield* snap.track())    // 先记录当前快照

  if (session.revert?.snapshot)
    yield* snap.restore(session.revert.snapshot)     // 恢复到之前的快照
  yield* snap.revert(patches)                         // 撤销差异

  // 计算变更摘要，推送事件
  const diffs = yield* summary.computeDiff({ messages: range })
  yield* bus.publish(Session.Event.Diff, { sessionID, diff: diffs })
})
```

> 源码：[revert.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/revert.ts)

设计亮点：

- **多层回退**：`track()` 保存当前状态 → `restore()` 恢复到之前快照 → `revert()` 回滚单个 patch——每层应对不同粒度的恢复需求
- **事件驱动 UI 更新**：恢复操作完成后通过 `Bus.publish` 通知 TUI 更新，无需轮询
- **`assertNotBusy` 并发锁**：确保在 revert 操作中不会有其他并发操作修改状态

### 2.6 Workspace Session 恢复

对于更严重的故障——工作区完全不可用，OpenCode 在 control plane 层提供了 session 恢复：

```typescript
// packages/opencode/src/control-plane/workspace.ts:145-296
// 分批回放 session 事件到目标 workspace
// 从数据库读取 session 的所有事件（按 seq 排序）
// 分成 size=10 的批次，逐批通过 SyncEvent.replayAll()
// 或 HTTP POST 到 /sync/replay（远程 workspace）
export function sessionRestore(input: SessionRestoreInput) {
  // 分批回放，每批次完成后发出进度事件
}
```

---

## 三、设计哲学的核心差异

### 3.1 恢复策略对比表

| 维度 | Claw-Code (Rust) | OpenCode (TypeScript) |
|------|-----------------|----------------------|
| **恢复模型** | 声明式 Recipe（配方） | 命令式 Retry + Snapshot |
| **故障分类** | 7 种枚举场景，精确映射 | 按 HTTP 错误码 + 字符串模式 |
| **重试策略** | 指数退避 + 随机抖动 | 优先 retry-after 头，再指数退避 |
| **恢复粒度** | Worker 级（整个 Agent 重启） | 消息级（单条 revert）+ 文件级（Git snapshot） |
| **工具恢复** | 无逐工具重试 | 编辑工具内置模糊匹配回退 |
| **Provider 容错** | Fallback 链（配置多个模型） | 仅重试同一模型 |
| **死循环防护** | max_attempts: 1，然后升级 | DOOM_LOOP_THRESHOLD=3 |
| **状态追踪** | Worker 状态机 | SessionStatus 三态 (idle/busy/retry) |
| **升级机制** | EscalationPolicy 三层 | 无（最终失败返回 error） |
| **MCP 容错** | 重试握手 + 错误表面 recoverable 标志 | 多传输方式尝试（StreamableHTTP → SSE） |

### 3.2 两种哲学

Claw-Code 的 Recovery Recipes 是**编译时确定性**的体现。在 Rust 中，故障场景是枚举类型，恢复步骤也是枚举类型，`recipe_for()` 是一个纯函数——给定故障场景，返回固定的恢复序列。编译器可以穷尽检查是否所有场景都有对应配方。

```rust
// 编译器保证所有 FailureScenario 都有配方
match scenario {
    TrustPromptUnresolved => ...,
    PromptMisdelivery => ...,
    StaleBranch => ...,
    CompileRedCrossCrate => ...,
    McpHandshakeFailure => ...,
    PartialPluginStartup => ...,
    ProviderFailure => ...,
    // 新增场景时编译器会警告缺少的分支
}
```

OpenCode 则走的是**运行时弹性**路线。Effect.retry 配合 `retryable()` 函数在运行时动态判断是否需要重试、重试多久。Snapshot + Revert 系统用 Git 做文件层的冗余恢复，TUI 提供删除/恢复 dialog 让用户手动选择恢复方案。

这两种哲学的核心区别在于：

1. **Claw-Code 认为故障是可以预测和分类的**——所以需要精确枚举、一一映射，失败就升级
2. **OpenCode 认为故障是不可完全预测的**——所以需要多层弹性（API 重试 → 快照回滚 → workspace 恢复），以及人工介入的 UI

### 3.3 实际影响

Claw-Code 的方式在**确定性环境**中更优秀——比如 CI/CD、服务端部署，故障模式相对固定，可以提前写好配方。一旦遇到未知故障，`EscalationPolicy::AlertHuman` 是最安全的做法。

OpenCode 的方式在**交互式环境**中更灵活——比如开发者桌面工具，用户可以手动决定是否恢复、恢复到哪一步。Git 快照的存在意味着任何时候都可以 revert，不需要预先定义故障类型。

---

## 四、各自的盲区

### Claw-Code 的盲区

- 没有通用的逐工具重试机制。如果 `Bash` 工具的执行因为竞争条件失败，不会自动重试——需要触发 Worker 级重启
- `max_attempts: 1` 在某些 transient 故障下过于保守。若 Provider 恰好有 3 秒的抖动窗口，1 次自动重试可能不够

### OpenCode 的盲区

- 没有 Provider 回退链。同一模型重试仍然失败后，不会自动切换到备用模型（如 Anthropic → OpenAI），用户需要手动切换
- 高层故障（如 workspace 损坏）的恢复路径完全依赖用户手动操作，没有自动升级机制

---

## 五、总结

Claw-Code 的 Recovery Recipes 和 OpenCode 的 Effect Retry + Snapshot 代表了 Rust 和 TypeScript 在故障恢复上的不同设计美学。

Claw-Code 选择**在编译时穷尽所有可能性**——用类型系统确保每个故障都有处理方案。代价是灵活性受限：面对未预见的故障，只能升级给用户。

OpenCode 选择**在运行时保持弹性**——对未知错误无限重试（受限于 DOOM_LOOP_THRESHOLD），同时用 Git 快照保住文件层的可回滚能力。代价是某些场景下可能重试过度或给用户太多选择。

如果让我选：生产环境、后台 Agent → **Claw-Code 的 Recovery Recipes**。交互式、开发者桌面工具 → **OpenCode 的 Effect Retry + Snapshot**。

但最理想的情况可能是两者的结合——声明式配方定义当做什么，运行时的弹性做怎么重试，快照系统保底。这大概是 Agent 框架在"稳健"和"灵活"之间的最佳平衡点。

---

## 参考资料

1. [Claw-Code 源码：recovery_recipes.rs](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/runtime/src/recovery_recipes.rs) — 恢复配方系统
2. [Claw-Code 源码：worker_boot.rs](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/runtime/src/worker_boot.rs) — Worker 状态机与重启
3. [Claw-Code 源码：config.rs](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/runtime/src/config.rs) — Provider fallback 配置
4. [Claw-Code 源码：anthropic.rs](https://github.com/ultraworkers/claw-code/blob/main/rust/crates/api/src/providers/anthropic.rs) — API 层重试
5. [OpenCode 源码：retry.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/retry.ts) — 重试策略
6. [OpenCode 源码：processor.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/processor.ts) — Session 处理器 Effect.retry
7. [OpenCode 源码：snapshot/index.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/snapshot/index.ts) — Git 快照恢复
8. [OpenCode 源码：revert.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/revert.ts) — 会话回退
