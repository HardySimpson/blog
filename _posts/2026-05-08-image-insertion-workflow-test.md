---
layout: post
title: "博客配图管线测试：从 Telegram 图片到 GitHub Pages"
category: 工程
date: 2026-05-08 05:15:00 +0800
excerpt: "测试 Hermes Agent 博客撰写技能中图片管线的端到端流程——Telegram 接收图片 → 缓存 → 复制到博客仓库 → 文章引用 → git push → GitHub Pages 渲染。验证全链路能否一次跑通。"
---

Sign-off-by: 难易

Assisted-by: Hermes:deepseek-v4-pro

![测试配图](https://hardysimpson.github.io/blog/images/test-image-insert.jpg)

## 管线流程

本次测试覆盖以下步骤：

1. **图片接收** — 用户通过 Telegram 发送图片，Hermes Gateway 自动缓存到 `~/.hermes/image_cache/`
2. **图片分析** — Vision Provider 分析图片内容（本次因 MiniMax CN 账号无 vision 模型跳过）
3. **图片复制** — 将缓存图片拷贝到博客仓库 `images/` 目录
4. **文章撰写** — 生成 Frontmatter + Sign-off + 正文 + 图片引用的 Markdown
5. **Git Push** — 通过 SSH（port 443 绕过代理）推送到 GitHub
6. **Pages 渲染** — Jekyll 自动构建，约 30–90 秒后可访问

## 配图格式要求

- 图片文件名与文章 slug 对应：`{slug}.jpg`
- 引用路径使用绝对 URL：`https://hardysimpson.github.io/blog/images/{slug}.jpg`
- 图片随文章一起 `git add` 和 push
- Pages 构建有一定延迟，先验证 raw GitHub URL 确认文件已推送

## 校验

推送后验证：

```bash
# 确认原始文件存在
curl -sL -o /dev/null -w "%{http_code}" \
  "https://github.com/HardySimpson/blog/blob/main/_posts/2026-05-08-image-insertion-workflow-test.md"

# 确认图片文件存在
curl -sL -o /dev/null -w "%{http_code}" \
  "https://raw.githubusercontent.com/HardySimpson/blog/main/images/test-image-insert.jpg"

# 确认 Pages 渲染
curl -sL -o /dev/null -w "%{http_code}" \
  "https://hardysimpson.github.io/blog/2026/05/08/image-insertion-workflow-test/"
```
