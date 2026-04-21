---
layout: post
title: "AI Coding Agent 的技能扩展：Skills vs MCP 深度对比"
date: 2026-04-21 09:30:00 +0800
---

Sign-off-by: 难易

Assisted-by: OpenClaw:minimax/M2.7

---

当一个 AI Coding Agent 需要扩展能力时，有两条主要路径：**Skills**（技能系统）和 **MCP**（Model Context Protocol）。OpenCode 和 Claw-code（Claude Code 的开源重写）各自选择了不同的架构。本文深入分析两者的取舍。

## 什么是 Skills

Skills 是一种**本地优先**的扩展机制。Agent 在启动时扫描预定义目录，加载 `SKILL.md` 文件，解析其中的描述和使用规则。

```markdown
# SKILL.md 示例
name: blog-writer
description: "用于创建、编辑、维护技术博客..."
```

Skills 的特点：
- **文件驱动**：一个 `.md` 文件就是一个技能
- **本地发现**：通过目录扫描（`skills/**/SKILL.md`）自动发现
- **轻量**：无需服务进程，直接读取元数据

## 什么是 MCP

MCP（Model Context Protocol）是一种**网络优先**的扩展协议。由 Anthropic 提出，旨在让 Agent 与外部工具通过标准协议通信。

MCP 的核心组件：
- **MCP Server**：独立运行的 HTTP 服务，提供工具清单和调用接口
- **OAuth 认证**：支持安全的第三方授权
- **动态发现**：Agent 通过协议协商获取可用工具

## OpenCode 的选择：Skills + MCP 双轨并行

OpenCode（anomalyco/opencode）采用了**双轨并行**策略，同时支持 Skills 和 MCP。

### Skills 系统架构

```
skill/
├── discovery.ts    # 技能发现服务
├── index.ts        # 技能注册与加载
└── skill.ts        # 技能定义与执行
```

**关键设计**：

```typescript
// skill/discovery.ts - 技能发现
const EXTERNAL_SKILL_PATTERN = ".claude/skills/**/SKILL.md"
const OPENCODE_SKILL_PATTERN = "{skill,skills}/**/SKILL.md"
```

**发现机制**：
- 扫描多个目录：`~/.claude/skills/`、`./.agents/`、项目内 `skills/`
- 支持 Git URL 远程拉取技能
- Zod Schema 验证技能格式

### MCP 系统架构

```
mcp/
├── auth.ts              # MCP 认证
├── oauth-callback.ts    # OAuth 回调处理
├── oauth-provider.ts    # OAuth Provider 实现
└── index.ts             # MCP 核心
```

**OpenCode 的 MCP 实现特点**：
- 完整的 OAuth 2.0 流程支持
- 支持第三方 MCP Server 的动态接入
- 通过 `effect` 框架管理并发和依赖注入

### 工具系统

OpenCode 将内置能力拆分为独立工具：

```
tool/
├── bash.ts          # Shell 命令执行
├── read.ts          # 文件读取
├── write.ts         # 文件写入
├── edit.ts          # 代码编辑
├── grep.ts          # 文本搜索
├── glob.ts          # 文件模式匹配
├── lsp.ts           # Language Server Protocol
├── mcp-exa.ts       # MCP 外部搜索集成
├── webfetch.ts      # 网页获取
└── websearch.ts     # 搜索引擎
```

**设计思路**：工具职责单一，通过组合完成复杂任务。

## Claw-code 的选择：Plugins 体系

Claw-code（ultraworkers/claw-code）采用了基于 **Plugins** 的扩展体系。

### Plugins 架构

```
rust/crates/plugins/
├── lib.rs           # 插件核心
└── hooks.rs         # 钩子系统
```

**核心设计**：

```rust
// 插件类型定义
pub enum PluginKind {
    Builtin,    // 内置插件
    Bundled,    // 捆绑插件
    External,   // 外部插件
}
```

**插件目录结构**：
```
.claude-plugin/
├── plugin.json      # 插件清单
└── ...             # 插件代码
```

### 插件与 Skills 的区别

| 维度 | Claw-code Plugins | OpenCode Skills |
|------|------------------|----------------|
| 格式 | JSON + Rust WASM | Markdown + TypeScript |
| 执行 | WASM 沙箱隔离 | 直接加载执行 |
| 分发 | .claude-plugin 目录 | 任意目录扫描 |
| 扩展性 | 编译时决定 | 运行时发现 |

### Claw-code 的 ACP 协议

Claw-code 实现了 **ACP（Agent Client Protocol）**，一种 agent 间通信协议：

- 端到端加密通信
- 支持多 agent 协作
- 独立的会话管理

## 核心取舍对比

### OpenCode：开放生态，技能即文档

**优势**：
- SKILL.md 文件本身即文档，可读性强
- 支持任意目录，无需特殊安装
- MCP 协议标准化，接入门槛低

**劣势**：
- 技能质量参差不齐，缺乏强校验
- 无运行时隔离，恶意技能风险
- Skills 分散管理，依赖约定而非强制

**适用场景**：社区贡献型生态、需要快速实验的团队

### Claw-code：安全优先，插件即应用

**优势**：
- WASM 沙箱提供运行时隔离
- Plugins 体系更接近传统软件分发
- 内置 marketplace 机制更规范

**劣势**：
- 开发者体验稍重，需要编译/WASM
- Skills 相比更封闭
- 生态建设成本更高

**适用场景**：企业级应用、安全要求高的场景

## 架构决策矩阵

| 维度 | OpenCode | Claw-code |
|------|----------|-----------|
| 扩展协议 | MCP (官方) + 自有 Skill | ACP (自研) + Plugin |
| 技能格式 | SKILL.md (Markdown) | plugin.json + WASM |
| 工具发现 | 目录扫描 + MCP 协议 | 插件清单 + 内置 |
| 安全模型 | 依赖 MCP OAuth | WASM 沙箱 |
| 生态策略 | 开放、去中心化 | 规范、受控 |
| 技术栈 | TypeScript/Bun | Rust |
| 内置工具数 | 20+ 独立工具 | Rust crates 内聚 |

## 我的判断

**OpenCode** 更适合快速迭代、社区驱动的项目。技能就是文档，降低了贡献门槛；MCP 协议让工具接入标准化。

**Claw-code** 更适合企业场景。Plugins 的 WASM 隔离提供了更强的安全保障；ACP 协议让多 agent 协作更可控。

两者代表了两个方向：**OpenCode 押注开放生态**，**Claw-code 押注安全规范**。没有绝对优劣，只有场景匹配。

---

## 参考资料

1. [OpenCode 源码：skill 系统](https://github.com/anomalyco/opencode/tree/main/packages/opencode/src/skill)
2. [OpenCode 源码：mcp 系统](https://github.com/anomalyco/opencode/tree/main/packages/opencode/src/mcp)
3. [OpenCode 源码：tool 系统](https://github.com/anomalyco/opencode/tree/main/packages/opencode/src/tool)
4. [Claw-code 源码：plugins](https://github.com/ultraworkers/claw-code/tree/main/rust/crates/plugins)
5. [Claw-code 源码：ACP 协议](https://github.com/ultraworkers/claw-code/tree/main/rust/crates)
