# Jekyll 博客

这是一个基于 Jekyll 的 GitHub Pages 博客项目。

## 项目结构

```
blog/
├── _includes/          # 可重用的模板片段
│   ├── head.html      # HTML head 部分
│   ├── header.html    # 网站头部
│   └── footer.html    # 网站底部
├── _layouts/          # 页面布局模板
│   ├── default.html   # 默认布局
│   ├── post.html      # 文章布局
│   └── page.html      # 页面布局
├── _posts/            # 博客文章
│   └── 2026-03-16-welcome-to-jekyll.md
├── assets/            # 静态资源
│   └── main.scss      # 主样式文件
├── _config.yml        # 站点配置
├── _sass/             # SASS 样式文件
│   └── main.scss
├── about.md           # 关于页面
├── feed.xml           # RSS 订阅
├── index.html         # 首页
└── Gemfile            # Ruby 依赖
```

## 使用方法

### 本地预览

1. 安装 Ruby 和 Bundler
2. 运行以下命令：

```bash
bundle install
bundle exec jekyll serve
```

3. 打开浏览器访问 `http://localhost:4000`

### 部署到 GitHub Pages

1. 将项目推送到 GitHub 仓库
2. 在仓库设置中启用 GitHub Pages
3. 选择 `main` 分支作为源

## 配置说明

编辑 `_config.yml` 文件来配置你的网站：

- `title`: 网站标题
- `description`: 网站描述
- `theme`: 使用的主题
- `plugins`: 启用的插件

## 添加新文章

在 `_posts` 目录下创建新文件，文件名格式为：

```
YYYY-MM-DD-title.md
```

文件头部需要添加 Front Matter：

```markdown
---
layout: post
title: "文章标题"
date: 2026-03-16
categories: 分类
---

文章内容...
```

## 许可证

MIT License