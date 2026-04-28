---
layout: post
title: "龙虾养殖与 AI 编程工具怎么对接——聊聊 ACP 协议的跨领域启示"
category: 龙虾养殖
date: 2026-04-28 14:00:00 +0800
excerpt: ""
---

Sign-off-by: 难易

Assisted-by: Hermes:deepseek-v4-flash

你可能在纳闷：一个讲 AI 编程工具的博客，突然冒出个"龙虾养殖"分类是怎么回事？

事情是这样的——某天我盯着 OpenCode 的 ACP（Agent Client Protocol）实现，突然想到一个场景：**龙虾养殖场的物联网设备和 AI 编程工具面临的其实是同一个问题——异构系统如何通信。**

这不是硬扯。往下看。

---

## 一、龙虾养殖场的真实困境

假设你经营一个现代化的龙虾养殖场。你可能有：

- **水质传感器**（温度、pH、溶氧量）— 走 Modbus 协议
- **自动投喂机**— 走 MQTT
- **水下摄像头**— RTSP 视频流
- **增氧泵控制器**— RS485 串口
- **环境监控大屏**— HTTP REST API

这五个设备系统各说各的话。你想在手机上统一查看所有数据，或者让 AI 自动分析异常并调整设备参数——**你得先让它们能互相通信**。

这个问题，跟 AI 编程工具行业遇到的一模一样。

---

## 二、AI 编程工具的"巴别塔困境"

两年前，AI 编程工具是这样的：

| 工具 | 协议 | 集成方式 |
|------|------|---------|
| Claude Code | 自有 CLI | 特定编辑器插件 |
| Cursor | 自有 API | 独有 IDE |
| Copilot | LSP 扩展 | VS Code 专用 |
| OpenCode | HTTP + WebSocket | SDK |
| Kimi Code | 自有协议 | 特定集成 |

每个工具都有一套自己的通信方式。编辑器想同时支持多个 AI 助手，就得为每个工具写一套适配器——累死。

**ACP（Agent Client Protocol）就是来解决这个问题的。**

---

## 三、ACP 如何工作

从 OpenCode 的 ACP 源码来看，核心是一个 Session Manager：

```typescript
// packages/opencode/src/acp/session.ts
export class ACPSessionManager {
  private sessions = new Map<string, ACPSessionState>()
  private sdk: OpencodeClient

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

ACP 定义了一组标准化的操作——`Initialize`、`NewSession`、`ResumeSession`、`ForkSession`、`Cancel`——任何实现了这些操作的 Agent 都可以互相通信。

```typescript
// packages/opencode/src/acp/agent.ts - 关键类型
import {
  type InitializeRequest,
  type InitializeResponse,
  type NewSessionRequest,
  type ForkSessionRequest,
  type ResumeSessionRequest,
  type CancelNotification,
  type PromptRequest,
  // ...
} from "@agentclientprotocol/sdk"
```

> 源码：[acp/agent.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/acp/agent.ts)
> 源码：[acp/session.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/acp/session.ts)

标准化接口的意义在于：**编辑器只要实现一次 ACP 客户端，就能对接所有支持 ACP 的 AI 助手。** 就像 USB-C 接口——不管你连的是显示器还是硬盘，插上就能用。

---

## 四、龙虾养殖版的 ACP

现在回来看龙虾养殖场的问题。如果我们定义一个 **LCP（Lobster Control Protocol）**：

```typescript
// LCP 标准接口——参考 ACP 的设计
interface LCP标准操作 {
  // 初始化连接
  initialize(): { 设备类型: string; 支持的操作: string[] }
  
  // 读取数据（统一格式）
  readData(传感器ID: string): {
    温度?: number
    pH值?: number
    溶氧量?: number
    时间戳: number
  }
  
  // 执行操作（统一接口）
  executeAction(设备ID: string, 指令: string): boolean
}
```

只要每个设备厂商都实现这个 LCP，养殖户就只需要一个 App 就能控制所有设备——不管传感器是哪个牌子、投喂机是什么型号。

这不就是 ACP 做的事吗？

### 现实中已经在发生的连接

其实已经有 AI 编程工具被用来编写龙虾养殖的监控脚本了。通过 ACP 协议：

```
养殖传感器数据 → MQTT Broker → Node-RED → HTTP API → OpenCode Agent
                                                          ↓
                                                  ACP 协议 → AI 分析
                                                          ↓
                                                 生成调控建议 → 自动执行
```

OpenCode 的 ACP Agent 支持 `Model Context Protocol (MCP)` 集成：

```typescript
// ACP Session State 中直接包含了 MCP Server 配置
export interface ACPSessionState {
  id: string
  cwd: string
  mcpServers: McpServer[]  // ← 可以挂载任意 MCP 工具
  createdAt: Date
  model?: { providerID: ProviderID; modelID: ModelID }
}
```

> 源码：[acp/types.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/acp/types.ts)

这意味着养殖场的 MQTT Broker 可以注册为一个 MCP Server，AI Agent 就能直接读取传感器数据、分析趋势、甚至控制设备——**全程通过标准协议**。

---

## 五、启示

龙虾养殖和 AI 编程工具，表面上风马牛不相及，但底层逻辑相通：

| 领域 | 问题 | 解决方案 |
|------|------|---------|
| AI 编程工具 | 工具各自为政，编辑器集成困难 | ACP 统一 Agent 通信协议 |
| 龙虾养殖 | 设备协议不统一，监控系统碎片化 | LCP 式标准化设备接口 |
| 智能家居 | 米家/HomeKit/华为各自封闭 | Matter 统一协议 |
| 云计算 | 各家 API 不同 | Terraform 统一资源抽象 |

**标准协议的价值不在于技术本身，而在于它降低了系统之间的耦合成本。** 不管是 AI Agent 还是龙虾传感器，只要大家说同一种语言，就能组合出远超单个系统能力的价值。

---

## 六、彩蛋

最后分享一个来自 OpenCode ACP 源码中的彩蛋——`agent.ts` 有 1837 行代码，其中有一段优雅的错误处理：

```typescript
// ACP Agent 启动逻辑
async function getContextLimit(
  sdk: OpencodeClient,
  providerID: ProviderID,
  modelID: ModelID,
  directory: string,
): Promise<number | null> {
  const providers = await sdk.config
    .providers({ directory })
    .then((x) => x.data?.providers ?? [])
    .catch((error) => {
      log.error("failed to get providers for context limit", { error })
      return []
    })
  return provider?.limit.context ?? null
}
```

遇到错误不崩溃、返回兜底值、记录日志——这种稳健的设计哲学，放到龙虾养殖的物联网系统里，正合适。

毕竟，传感器离线了，增氧泵可不能停。

---

## 参考资料

1. [OpenCode ACP 源码：agent.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/acp/agent.ts)
2. [OpenCode ACP 源码：session.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/acp/session.ts)
3. [OpenCode ACP 源码：types.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/acp/types.ts)
4. [ACP 协议规范](https://agentclientprotocol.com)
5. [OpenClaw 快捷键指南 —— 龙虾养殖场管理员必备](https://hardysimpson.github.io/blog/2026/04/14/openclaw-keyboard-shortcuts/)
