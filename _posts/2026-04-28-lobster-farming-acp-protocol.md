---
layout: post
title: "OpenClaw / Hermes 如何与 AI 编程工具打通——ACP 协议实战解析"
category: 龙虾养殖
date: 2026-04-28 14:00:00 +0800
excerpt: "OpenClaw / Hermes 如何通过 ACP 协议与 AI 编程工具打通协作"
---

Sign-off-by: 难易

Assisted-by: Hermes:deepseek-v4-flash

你可能用过 OpenCode、Claude Code 或 Cursor 这类 AI 编程工具。但你想过没有——**你的 Agent 框架（比如 OpenClaw 或 Hermes）是怎么跟这些编程工具打通协作的？**

答案就是 **ACP（Agent Client Protocol）**。

---

## 一、为什么 Agent 框架需要对接编程工具？

先看一个真实场景。假设你在 Hermes Agent 中跟 AI 聊天，突然需要写一段代码。你希望：

1. Hermes 能把这个编程任务派给 OpenCode 或 Claude Code
2. 编程工具执行完后，结果返回给 Hermes
3. Hermes 继续基于结果做下一步决策

这就需要一个**标准化的通信协议**——让不同工具之间能互相调用、传递数据、控制会话。

这就是 ACP 要解决的问题。

---

## 二、ACP 协议是什么？

ACP（Agent Client Protocol）是一个开放的、语言无关的协议，定义了 Agent 之间如何进行标准化通信。

从 OpenCode 的 ACP 实现来看，核心是这几类操作：

```typescript
// packages/opencode/src/acp/agent.ts - ACP 核心操作类型
import {
  type InitializeRequest,      // 初始化连接
  type NewSessionRequest,      // 创建新会话
  type ResumeSessionRequest,   // 恢复已有会话
  type ForkSessionRequest,     // 派生分支会话
  type CancelNotification,     // 取消操作
  type PromptRequest,          // 发送提示词
  type ListSessionsRequest,    // 列出会话
  type LoadSessionRequest,     // 加载会话
} from "@agentclientprotocol/sdk"
```

> 源码：[acp/agent.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/acp/agent.ts)

这些操作覆盖了 Agent 生命周期的所有阶段：创建、执行、中断、恢复、分支。

---

## 三、OpenClaw 是怎么用 ACP 的？

在 OpenClaw 的配置中，可以看到它通过 ACP 把编程任务派发给 OpenCode：

```json
{
  "agents": {
    "list": [
      {
        "id": "coder",
        "name": "Coder",
        "runtime": {
          "type": "acp",              // ← 使用 ACP 协议
          "acp": {
            "agent": "opencode",      // ← 对接 OpenCode
            "backend": "acpx",
            "mode": "persistent",
            "cwd": "/home/claw/.openclaw/workspace/coder"
          }
        }
      }
    ]
  },
  "acp": {
    "enabled": true,
    "dispatch": { "enabled": true },
    "defaultAgent": "opencode",
    "allowedAgents": [
      "claude", "codex", "copilot", "cursor",
      "gemini", "opencode", "qwen", "kimi"
    ]
  }
}
```

这背后的逻辑是：

1. **OpenClaw 作为主 Agent** 负责理解用户意图、制定计划
2. 遇到编程任务时，通过 ACP 协议**派发给 OpenCode 子 Agent**
3. OpenCode 执行代码编写、调试、测试
4. 结果通过 ACP 返回给 OpenClaw
5. OpenClaw 继续后续处理

Session Manager 负责管理这些派发的会话：

```typescript
// packages/opencode/src/acp/session.ts
export class ACPSessionManager {
  private sessions = new Map<string, ACPSessionState>()

  async create(cwd: string, mcpServers: McpServer[], model?: ACPSessionState["model"]) {
    const session = await this.sdk.session.create(
      { directory: cwd },
      { throwOnError: true },
    ).then(x => x.data!)

    const state: ACPSessionState = {
      id: session.id,
      cwd,
      mcpServers,
      createdAt: new Date(),
      model: resolvedModel,
    }
    this.sessions.set(sessionId, state)
    return state
  }
}
```

> 源码：[acp/session.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/acp/session.ts)

---

## 四、Hermes 怎么接入？从 ACP Adapter 说起

Hermes Agent 同样实现了 ACP 集成——通过 **ACP Adapter** 模块。

从 OpenClaw 归档中可以看到 Hermes 的 ACP 适配层结构：

```
.hermes/hermes-agent/acp_adapter/
├── __init__.py
├── __main__.py
├── auth.py         # ACP 认证
├── entry.py        # 入口点
├── events.py       # 事件处理
├── permissions.py  # 权限控制
├── server.py       # ACP 服务器
├── session.py      # 会话管理
└── tools.py        # 工具注册
```

这意味着 Hermes 可以：
- 通过 ACP 接收来自其他 Agent 的任务请求
- 把自己暴露为 ACP Server，供其他工具调用
- 在 Session 层面做细粒度的权限控制

ACP 的 Session State 还支持 MCP Server 挂载，进一步扩展能力：

```typescript
// packages/opencode/src/acp/types.ts
export interface ACPSessionState {
  id: string
  cwd: string
  mcpServers: McpServer[]   // ← 任意 MCP 工具都可以挂进来
  createdAt: Date
  model?: {
    providerID: ProviderID
    modelID: ModelID
  }
}
```

> 源码：[acp/types.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/acp/types.ts)

---

## 五、打通之后的效果

通过 ACP 协议，OpenClaw / Hermes 可以实现：

| 能力 | 说明 |
|------|------|
| **智能派工** | 根据任务类型自动选择合适的编程工具 |
| **会话隔离** | 每个子任务独立会话，互不干扰 |
| **权限控制** | 细粒度控制子 Agent 能做什么 |
| **结果回传** | 子任务完成后结果自动返回主 Agent |
| **热切换** | 可以随时切换后端编程工具而不影响上层逻辑 |

简单来说：**ACP 让不同的 AI Agent 能像微服务一样互相调用。** OpenClaw 是"项目经理"，OpenCode 是"工程师"，Hermes 可以是"接口网关"——各司其职，通过 ACP 协作。

---

## 参考资料

1. [OpenCode ACP 源码：agent.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/acp/agent.ts)
2. [OpenCode ACP 源码：session.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/acp/session.ts)
3. [OpenCode ACP 源码：types.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/acp/types.ts)
4. [ACP 协议规范](https://agentclientprotocol.com)
5. [OpenClaw 快捷键指南 —— ACP 派工模式下的快捷键配置](https://hardysimpson.github.io/blog/2026/04/14/openclaw-keyboard-shortcuts/)
