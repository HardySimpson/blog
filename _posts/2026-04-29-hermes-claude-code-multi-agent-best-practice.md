---
layout: post
title: "Hermes Agent + Claude Code 多 Agent 协作：CLI Bridge 模式是最佳实践吗？"
category: AI编程
date: 2026-04-29 16:00:00 +0800
excerpt: "在 Hermes Agent 中集成 Claude Code 作为子代理，业界主流的 ACP 协议到底能不能用？调研了 ACP、A2A、MCP、CLI Bridge 四种模式后，结论可能和你想象的不一样。"
---

Sign-off-by: 难易

Assisted-by: Hermes:deepseek-v4-flash [web_search] [delegate_task]

---

当你同时拥有 Hermes Agent 和 Claude Code，最自然的想法就是：让它们协作起来。Hermes 负责编排和系统操作，Claude Code 负责代码生成和审查——听起来合理。

但问题来了：**怎么连？**

市面上流传的说法是"通过 ACP 协议"（Agent Communication Protocol），还有人提 MCP、A2A。我花了一些时间做了调研和实测，这篇文章把结论直接写在前面：

**当前最佳实践不是 ACP，不是 MCP，而是 CLI Bridge 模式——就是 `terminal("claude -p 'task'")` 这种看起来最朴素的方式。**

---

## 一、ACP 为什么不行？

ACP（Agent Communication Protocol）最早由 SingularityNET 提出，设计目标是定义一套标准化的 Agent 间通信协议。听起来很美，但现实中：

- **主流框架无一原生支持**：LangChain、CrewAI、AutoGen、AutoGPT 都没有内置 ACP 支持
- **Claude Code 曾短暂支持后移除**：v1.x 有 `--acp` 参数，v2.x 已经完全移除
- **Hermes 的 `delegate_task` 的 `acp_command` 参数**正是设计来对接 ACP 的子进程[^1]——但这条路在 Claude Code 上走不通

截至 2026 年 4 月，Claude Code v2.1.123 运行 `claude --acp --stdio` 会直接报 `unknown flag: --acp`。

## 二、那其他选项呢？

我调研了三种替代方案，逐一测试：

### MCP（Model Context Protocol）

Anthropic 推出的 MCP 是**工具暴露协议**，让 Agent 能够调用外部工具（数据库、文件系统、API 等）。但它**不是 Agent 间通信协议**——你不能用 MCP 让两个 Agent 互相派活。

### A2A（Agent-to-Agent）

Google 在 2025 年提出的草案，比 ACP 更轻量。但：
- 仍处于草案阶段
- 没有主流框架落地
- Claude Code 不支持

### CLI Bridge（Print Mode）

做法最简单：Hermes 通过 `terminal()` 调用 `claude -p "task"`，Claude Code 执行后返回结果。

```bash
# 实际测试通过的命令
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic \
ANTHROPIC_API_KEY=sk-xxx \
claude --bare -p "Create hello_world.py and run it" \
  --model deepseek-v4-pro \
  --allowedTools "Write,Bash" \
  --max-turns 5
```

**实测结果**：✅ 正常执行，返回结果正确。

| 模式 | 状态 | 上手成本 | 成熟度 |
|------|------|---------|--------|
| ACP | ❌ 不支持 | — | — |
| MCP | ❌ 不适用 | — | — |
| A2A | ⏳ 草案中 | 高 | 低 |
| **CLI Bridge** | ✅ **可用** | **低** | **高** |

## 三、这就是业界最佳实践吗？

搜索了 GitHub、Reddit 和相关社区后发现：**CLI Bridge 是当前业界最广泛使用的多 Agent 集成模式**。这不是"权宜之计"，而是行业共识。

### 为什么 CLI Bridge 反而是最好的？

1. **零依赖**——不需要额外协议栈，不需要启动中间服务器
2. **进程隔离**——子 Agent 崩溃不影响主 Agent
3. **超时可控**——`timeout` 参数直接设，不会出现死等
4. **输出可解析**——stdout 就是结果，失败就是非零退出码
5. **兼容所有 Agent**——不管 Claude Code、OpenCode、Codex，都有 CLI 入口

### 分层架构

实际项目中，我采用的是三层委托架构：

```
┌──────────────────────────────────────┐
│        Hermes Agent (主控层)           │
│  ├─ 任务拆解、结果聚合                  │
│  ├─ 文件操作、系统管理、网络访问         │
│  └─ 记忆持久化、定时任务                 │
├──────────────────────────────────────┤
│    terminal() CLI Bridge (通信层)       │
├──────────────────────────────────────┤
│       子 Agent (执行层)                │
│  ├─ Claude Code → 代码分析/生成/审查    │
│  ├─ OpenCode  → 结构化代码执行          │
│  └─ 自研脚本  → 专项工具                │
└──────────────────────────────────────┘
```

通信通过 CLI 管道加文件系统共享中间结果，实现了解耦的异步协作。

### 实际效果验证

以一次完整的"Hermes → Claude Code → DeepSeek V4 Pro"链路测试为例：

```python
# Hermes 内部调用
terminal(
    "ANTHROPIC_API_KEY=xxx ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic "
    "claude --bare -p 'Create hello_world.py and run it' "
    "--model deepseek-v4-pro --allowedTools Write,Bash --max-turns 3",
    timeout=60
)
```

输出：

```
Hello from Hermes -> Claude Code -> DeepSeek V4 Pro! ACP-style delegation working!
```

链路完整可靠，延迟可控。

## 四、什么时候应该升级？

CLI Bridge 不是万能的。以下几种情况应该考虑升级到更复杂的架构：

| 场景 | 推荐方案 |
|------|---------|
| 需要高频交互（每秒多次调用） | 持久化 stdin/stdout 会话（`claude --print`） |
| 需要子 Agent 间直接对话 | 引入 CrewAI 或 AutoGen 作为编排层 |
| 需要分布式部署 | HTTP/WebSocket 端点暴露（如 OpenCode Server） |
| ACP/A2A 生态成熟 | 切换到标准化协议 |

目前这些场景我都不需要，所以 CLI Bridge 是最优解。

## 五、给未来读者的建议

如果你也在搭多 Agent 系统，我的建议是：

1. **先跑通 CLI Bridge**——10 分钟就能搞定，别在一开始追求完美架构
2. **用持久的 wrapper 脚本**——把环境变量和参数封装好，避免重复
3. **关注 Claude Code 版本更新**——如果未来重新支持 ACP，随时可以切
4. **文件系统是天然的中间件**——子 Agent 写入 /tmp 共享区，主 Agent 读取，简单可靠
5. **不要迷信协议**——ACP 和 A2A 听起来高级，但 CLI Bridge 在绝大多数场景下已经足够

---

## 参考资料

[^1]: [Hermes Agent 文档 — delegate_task](https://hermes-agent.nousresearch.com/docs) — ACP 子代理配置
[^2]: [Claude Code CLI 文档](https://docs.anthropic.com/en/docs/claude-code/overview) — Anthropic 官方 CLI 指南
[^3]: [MCP 协议规范](https://modelcontextprotocol.io) — Anthropic 提出的工具暴露协议
[^4]: [DeepSeek API 文档 — Anthropic 兼容模式](https://api-docs.deepseek.com/) — `/anthropic/v1/messages` 端点说明
[^5]: [Google A2A 草案](https://github.com/google/A2A) — Agent-to-Agent 通信协议（2025）
