---
layout: post
title: "ACP 协议解析：OpenCode 的 Agent 通信标准实现"
date: 2026-03-20 15:00:00 +0800
---

# ACP 协议解析：OpenCode 的 Agent 通信标准实现

*2026-03-20 更新：补充 ACP 协议技术细节与 OpenCode 实现分析*

---

## 一、背景：为什么需要 ACP？

在 AI 代码助手蓬勃发展的今天，开发者面临一个关键问题：**不同的 AI 编程工具各自为政，无法互通**。

- Cursor 有自己的 API
- Claude Code 有自己的协议
- GitHub Copilot 又是另一套
- OpenCode、Kimi Code、Qwen Code...

这导致了几个核心问题：

1. **厂商锁定（Vendor Lock-in）**：用户一旦习惯某个工具，就很难迁移
2. **集成成本高**：编辑器/IDE 需要为每个 AI 助手单独适配
3. **生态割裂**：好的 AI 能力无法在不同工具间共享

就像当年编程语言需要 LSP（Language Server Protocol）来统一 IDE 与编程语言的交互一样，**AI 代码助手也需要一个统一协议来规范客户端与 AI Agent 之间的通信**。

这就是 **ACP（Agent Client Protocol）** 诞生的背景。

---

## 二、ACP 协议概述

### 2.1 什么是 ACP？

**ACP（Agent Client Protocol）** 是一个开放标准，定义了代码编辑器/IDE（客户端）与 AI 编程 Agent（服务端）之间的通信规范。

它由 **JetBrains** 和 **Zed** 团队联合开发，目标是：

> "让任何兼容 ACP 的编辑器可以使用任何兼容 ACP 的 AI Agent"

类似于 LSP（Language Server Protocol）的工作方式，但专门针对 AI 编程场景。

### 2.2 ACP vs MCP

很多人会混淆 ACP 和 **MCP（Model Context Protocol）**：

| 协议 | 全称 | 定位 | 制定方 |
|------|------|------|--------|
| **ACP** | Agent Client Protocol | 编辑器 ↔ AI Agent 的通信协议 | JetBrains + Zed |
| **MCP** | Model Context Protocol | AI Agent ↔ 工具/数据源的上下文协议 | Anthropic |

简单说：
- **ACP** = 编辑器和 AI Agent 之间"说什么"
- **MCP** = AI Agent 和外部工具之间"怎么连接"

两者是互补关系，ACP 复用 MCP 的 JSON 类型定义。

---

## 三、ACP 协议技术细节

### 3.1 通信架构

```
┌─────────────────┐         ACP          ┌─────────────────┐
│                 │  ←─── JSON-RPC ───→  │                 │
│   IDE/Editor    │                      │   AI Agent      │
│   (Client)      │  • 请求/响应         │   (Server)      │
│                 │  • 通知               │                 │
│  - Zed          │  • 流式事件           │  - OpenCode     │
│  - JetBrains    │                      │  - Claude Code  │
│  - VS Code      │                      │  - Gemini CLI   │
│  - Neovim       │                      │  - Cursor       │
└─────────────────┘                      └─────────────────┘
```

### 3.2 传输层

ACP 支持两种传输模式：

| 模式 | 用途 | 格式 |
|------|------|------|
| **本地模式（Local）** | Agent 作为编辑器子进程运行 | stdio + ndjson（换行分隔 JSON） |
| **远程模式（Remote）** | Agent 运行在云端或远程服务器 | HTTP/WebSocket（远程支持持续演进中） |

### 3.3 消息格式

基于 **JSON-RPC 2.0** 标准：

```json
// 请求示例
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "agent.complete",
  "params": {
    "prompt": "实现用户登录功能",
    "context": {
      "files": ["/src/auth/login.ts"],
      "language": "typescript"
    }
  }
}

// 响应示例
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": "已为您创建 login.ts，包含...",
    "changes": [
      { "file": "/src/auth/login.ts", "type": "create" }
    ]
  }
}

// 流式事件示例
{
  "jsonrpc": "2.0",
  "method": "agent.thinking",
  "params": {
    "content": "正在分析代码结构..."
  }
}
```

### 3.4 核心能力

ACP 协议定义了以下核心能力：

| 能力 | 说明 |
|------|------|
| **聊天交互** | 发送提示词、接收 AI 回复 |
| **文件操作** | 读取、写入、编辑文件 |
| **终端执行** | 运行 Shell 命令 |
| **工具调用** | 执行自定义工具 |
| ** MCP 服务器** | 连接外部工具服务 |
| **项目规则** | 加载 AGENTS.md 等项目配置 |
| **代码格式化** | 集成 linter/formatter |
| **权限管理** | 控制 AI 可执行的操作 |
| **会话管理** | 持久化对话上下文 |

---

## 四、OpenCode 的 ACP 实现

### 4.1 OpenCode ACP 架构

OpenCode 全面支持 ACP 协议，提供与 CLI/TUI 模式**功能完全对等**的 ACP 服务：

```
┌──────────────────┐
│                  │
│  OpenCode ACP    │  ←─── opencode acp ───→  编辑器
│  Server         │
│                  │
│  ┌────────────┐  │
│  │ Built-in   │  │  文件操作、终端、工具
│  │ Tools      │  │
│  ├────────────┤  │
│  │ MCP        │  │  Supabase、Playwright 等
│  │ Servers    │  │
│  ├────────────┤  │
│  │ Agents     │  │  plan/build/explore
│  ├────────────┤  │
│  │ Formatters │  │  ruff、biome 等
│  ├────────────┤  │
│  │ Permissions│  │  权限控制
│  └────────────┘  │
└──────────────────┘
```

### 4.2 启动 ACP 模式

```bash
# 基本启动
opencode acp

# 指定模型
opencode acp -m anthropic/claude-sonnet-4

# 带环境变量
OPENCODE_API_KEY=xxx opencode acp
```

### 4.3 编辑器配置

#### Zed 编辑器

在 `~/.config/zed/settings.json` 中配置：

```json
{
  "agent_servers": {
    "OpenCode": {
      "command": "opencode",
      "args": ["acp"]
    }
  }
}
```

#### JetBrains IDE

在项目或用户目录的 `acp.json` 中配置：

```json
{
  "agent_servers": {
    "OpenCode": {
      "command": "/path/to/opencode",
      "args": ["acp"]
    }
  }
}
```

#### Neovim (Avante.nvim)

```lua
{
  acp_providers = {
    ["opencode"] = { command = "opencode", args = { "acp" } }
  }
}
```

#### Neovim (CodeCompanion.nvim)

```lua
{
  adapter = {
    name = "opencode",
    model = "claude-sonnet-4"
  }
}
```

### 4.4 OpenCode ACP 功能覆盖

| 功能 | ACP 支持 | CLI/TUI 支持 |
|------|:--------:|:------------:|
| 内置工具（文件/终端） | ✅ | ✅ |
| 自定义工具/Slash 命令 | ✅ | ✅ |
| MCP 服务器 | ✅ | ✅ |
| 项目规则（AGENTS.md） | ✅ | ✅ |
| 格式化/Linter | ✅ | ✅ |
| 多 Agents（plan/build/explore） | ✅ | ✅ |
| 权限管理 | ✅ | ✅ |
| 会话管理 | ✅ | ✅ |

**结论**：OpenCode 的 ACP 模式提供了与原生模式完全一致的能力。

---

## 五、ACP 生态系统

### 5.1 支持 ACP 的编辑器

| 编辑器 | 支持程度 |
|--------|----------|
| **Zed** | 原生支持 |
| **JetBrains IDEs** | 原生支持（IntelliJ、PyCharm 等） |
| **VS Code** | 通过扩展支持 |
| **Neovim** | Avante.nvim、CodeCompanion.nvim |

### 5.2 支持 ACP 的 AI Agent

| Agent | 状态 |
|-------|------|
| **OpenCode** | ✅ 完全支持 |
| **Claude Code** | ✅ 支持 |
| **Gemini CLI** | ✅ 支持 |
| **GitHub Copilot** | 🔜 开发中 |
| **Cursor** | 🔜 开发中 |
| **Kimi Code** | ✅ 支持 |
| **Qwen Code** | ✅ 支持 |
| **Kiro CLI** | ✅ 支持 |

### 5.3 相关资源

| 资源 | 链接 |
|------|------|
| 官方文档 | [agentclientprotocol.com](https://agentclientprotocol.com/) |
| OpenCode ACP | [opencode.ai/docs/acp](https://opencode.ai/docs/acp) |
| JetBrains ACP | [jetbrains.com/acp](https://www.jetbrains.com/acp) |
| GitHub (A2A/A2A) | [github.com/i-am-bee/acp](https://github.com/i-am-bee/acp) |

---

## 六、ACP 的意义与未来

### 6.1 行业影响

1. **打破垄断**：用户不再被某个编辑器和 AI 助手绑定
2. **降低集成成本**：一次开发，到处运行
3. **促进竞争**：好的 AI 能力可以通过 ACP 被所有编辑器使用
4. **生态共建**：编辑器和 AI 开发者可以专注自身优势

### 6.2 演进方向

根据 JetBrains 和 Zed 的规划：

- **远程 Agent 支持**：通过 HTTP/WebSocket 支持云端 Agent
- **多 Agent 协作**：一个编辑器同时连接多个 Agent
- **A2A 协议**：Agent-to-Agent 通信（已捐赠给 Linux Foundation）

### 6.3 对 OpenCode 的意义

对于 OpenCode：

- **扩大用户群**：通过 ACP 进入 Zed、JetBrains 用户群体
- **生态融入**：成为 ACP 生态系统的一等公民
- **竞争力提升**：与其他商业方案平等竞争

---

## 七、总结

ACP 协议代表了 AI 编程工具走向标准化的重要一步。通过定义清晰的客户端-服务端通信规范，它正在解决 AI 编程领域的生态碎片化问题。

OpenCode 作为 ACP 的积极推动者和完全兼容的实现者，为用户提供了：
- ✅ 功能完整的 ACP 服务
- ✅ 与 CLI/TUI 完全对等的能力
- ✅ 无缝衔接主流编辑器的体验

对于开发者而言，ACP 意味着：**选择你喜欢的编辑器，使用你信任的 AI Agent**。

---

## 参考资料

1. [Agent Client Protocol 官方文档](https://agentclientprotocol.com/get-started/introduction)
2. [JetBrains ACP](https://www.jetbrains.com/acp)
3. [OpenCode ACP 文档](https://opencode.ai/docs/acp)
4. [Zed Editor](https://zed.dev)
5. [Linux Foundation A2A/A2A](https://github.com/i-am-bee/acp)
