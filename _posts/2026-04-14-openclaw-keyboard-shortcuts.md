---
layout: post
title: "OpenClaw 常用快捷键指南"
date: 2026-04-14 06:20:00 +0800
---

Sign-off-by: 难易

Assisted-by: OpenClaw:minimax/M2.7

# OpenClaw 常用快捷键指南

OpenClaw 是一个 AI 编程助手平台，支持多种交互方式。本文整理了最常用的快捷键和命令，帮助你提高效率。

## TUI 快捷键

TUI（Terminal UI）是 OpenClaw 的终端界面，通过 `openclaw tui` 启动。

### 消息发送与中断

| 快捷键 | 功能 |
|--------|------|
| **Enter** | 发送消息 |
| **Esc** | 中止当前运行 |
| **Ctrl+C** | 清空输入框（按两次退出） |
| **Ctrl+D** | 退出 TUI |

### 切换选择器

| 快捷键 | 功能 |
|--------|------|
| **Ctrl+L** | 模型选择器 |
| **Ctrl+G** | Agent 选择器 |
| **Ctrl+P** | 会话选择器 |

### 界面显示控制

| 快捷键 | 功能 |
|--------|------|
| **Ctrl+O** | 切换工具输出展开/折叠 |
| **Ctrl+T** | 切换思考过程可见性（重新加载历史） |

## 斜杠命令（Slash Commands）

在 TUI 或 WebChat 中输入 `/` 开头的命令。

### 核心命令

| 命令 | 功能 |
|------|------|
| `/help` | 显示帮助 |
| `/status` | 显示状态诊断 |
| `/agents` | 列出所有 Agent |
| `/models` | 列出可用模型 |
| `/sessions` | 列出当前会话 |

### 会话控制

| 命令 | 功能 |
|------|------|
| `/session <key>` | 切换到指定会话 |
| `/new` 或 `/reset` | 重置会话 |
| `/abort` | 中止当前运行 |
| `/settings` | 打开设置面板 |
| `/exit` | 退出 |

### 模型与响应控制

| 命令 | 功能 |
|------|------|
| `/model <provider/model>` | 切换模型 |
| `/think <off\|minimal\|low\|medium\|high>` | 设置思考深度 |
| `/fast <on\|off>` | 快速模式 |
| `/reasoning <on\|off\|stream>` | 推理模式 |
| `/verbose <on\|full\|off>` | 详细输出模式 |
| `/usage <off\|tokens\|full>` | 用量显示模式 |

### 权限与交付

| 命令 | 功能 |
|------|------|
| `/elevated <on\|off\|ask\|full>` | 提升权限模式 |
| `/deliver <on\|off>` | 消息交付开关 |
| `/activation <mention\|always>` | 激活模式 |

### 调试命令

| 命令 | 功能 |
|------|------|
| `/debug show` | 显示调试配置 |
| `/debug set <key>=<value>` | 设置调试项 |
| `/debug reset` | 重置调试配置 |

## 本地 Shell 命令

在 TUI 中，可以执行本地命令：

| 命令 | 功能 |
|------|------|
| `!<command>` | 执行本地 Shell 命令 |
| `!` | 发送普通消息（单个感叹号） |

**注意**：
- 首次执行会提示授权
- 命令在 TUI 工作目录的新 shell 中运行
- 环境变量 `OPENCLAW_SHELL=tui-local` 会自动注入

## 配置文件修改

| 命令 | 功能 |
|------|------|
| `/config get <key>` | 获取配置项 |
| `/config set <key> <value>` | 设置配置项 |
| `/config list` | 列出所有配置 |

## 常用组合场景

### 场景 1：切换到另一个 Agent

```
Ctrl+G → 选择 Agent → Enter
```

### 场景 2：查看当前 Token 用量

```
/usage tokens
```

### 场景 3：中止无响应的任务

```
Esc
```

### 场景 4：快速重置会话

```
/new
```

### 场景 5：本地执行命令

```
!ls -la
```

## 参考资料

1. [OpenClaw TUI 文档](https://docs.openclaw.ai/web/tui)
2. [OpenClaw CLI 参考](https://docs.openclaw.ai/cli)
3. [Slash Commands](https://docs.openclaw.ai/tools/slash-commands)
