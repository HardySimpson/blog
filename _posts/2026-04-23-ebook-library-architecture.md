---
layout: post
title: "自托管电子书库的技术架构：Calibre-Web 部署实战"
date: 2026-04-23 06:50:00 +0800
---

Sign-off-by: 钟成

Assisted-by: OpenClaw:minimax/M2.7

# 自托管电子书库的技术架构：Calibre-Web 部署实战

> 如何用 Docker + Nginx 搭一套支持 OPDS 的私有电子书库，并让 AI 助手能够理解和检索

---

## 背景问题

做个人知识管理的人大多遇到过这个困境：

- 书存在百度网盘，下载限速
- 书存在微信读书，账号随时被封
- 书存在 Calibre 桌面版，换设备就同步不了

更根本的问题是：**书库对 AI 不友好**。LLM 要回答"这本书讲了什么"，首先需要结构化的元数据——书名、作者、出版社、年份、简介。而大多数书库只有一个乱糟糟的文件夹。

我的方案：**自托管 Calibre-Web + OPDS + 结构化元数据**，让书库同时对人类和 AI 友好。

---

## 整体架构

```
手机 App（FBReader / Librera）
        │
        │ HTTPS
        ▼
   Nginx 反向代理
        │
        ├─ /books/   ──▶ Calibre-Web :8083
        │
        └─ /api/     ──▶ 其他服务（如果有）

        │
        ▼
   Calibre-Web 容器
        │
        ▼
   metadata.db（书库元数据，1848本书，6.4GB）
```

架构选型逻辑：

| 组件 | 选型 | 原因 |
|------|------|------|
| 书库管理 | Calibre-Web | Calibre 是事实标准，Web 化最成熟 |
| 部署方式 | Docker Compose | 一键启动，跨平台 |
| 手机阅读 | OPDS 协议 | 开放标准，主流 App 都支持 |
| 反向代理 | 复用现有 Nginx | 复用基础设施，不引入新端口 |

---

## 关键技术决策

### 1. OPDS 协议：手机阅读的核心

OPDS（Open Publication Distribution System）是电子书领域的开放协议，支持浏览、搜索、下载。它的核心优势：

```
# OPDS Feed 示例（Atom XML）
<feed>
  <entry>
    <title>三体</title>
    <author><name>刘慈欣</name></author>
    <link href="/opds/books/1.epub" type="application/epub+zip"/>
    <content>人类首次与外星文明的接触...</content>
  </entry>
</feed>
```

相比直接文件共享（SMB/NAS），OPDS 提供**完整的元数据**——App 里直接显示封面、作者、简介，不需要人工整理文件名。

支持的免费 App：

- **FBReader**（Android / iOS）— 老牌轻量，完全免费
- **Librera Reader**（Android）— 无广告，功能强
- **Foliate**（Linux / Android）— 开源，界面现代

### 2. Nginx 路径路由：复用现有基础设施

不单独给书库分配端口，通过 URL 路径区分：

```nginx
location /books/ {
    proxy_pass http://calibre-web:8083/;
    proxy_buffering off;  # 关键：关闭 buffer，避免大文件下载挂起
}

# Calibre-Web 内部重定向依赖根路径透传
location / {
    proxy_pass http://calibre-web:8083/;
}
```

**为什么要透传 `/` 而不是 404？**

Calibre-Web 内部有很多重定向逻辑（如 setup wizard、登录后的跳转），如果只代理 `/books/`，这些路径会 404。全部透传到 Calibre-Web，让它自己处理路由。

### 3. 两个数据库的关系：metadata.db vs app.db

这是最容易踩坑的地方。

```
metadata.db          →  Calibre 桌面版使用的数据库
app.db              →  Calibre-Web 运行时使用的数据库（SQLite）
```

Calibre-Web 首次启动时，从 `metadata.db` 导入元数据到 `app.db`，之后**不再自动同步**。

解决方案：Calibre-Web 提供"重新扫描书库"功能，手动触发增量同步。

```yaml
# docker-compose.yml 中的关键配置
volumes:
  - /path/to/library:/books:ro    # 书库只读挂载
  - calibre-web-config:/config     # app.db 持久化
```

### 4. 元数据整理：双源 API 自动修复

书库元数据质量直接影响 AI 的理解能力。我写了一个自动修复脚本，同时调用两个数据源：

```python
# 豆瓣 API（中文书籍主力）
def search_douban(title):
    url = f"https://book.douban.com/j/subject_suggest?q={quote(title)}"
    ...

# Open Library API（英文书籍）
def search_openlibrary(title):
    url = f"https://openlibrary.org/search.json?q={quote(title)}"
    ...
```

从文件内容提取书名的流程：

```python
# TXT 文件：直接读前200字
text = open(path).read(200)

# EPUB/ZIP 文件：解压后解析 HTML
with zipfile.ZipFile(path) as z:
    html = z.read("content.html")
    text = strip_tags(html)

# PDF（有文本层的）：pdftotext 提取
subprocess.run(["pdftotext", "-layout", path, "-"])
```

---

## Docker Compose 部署

```yaml
services:
  calibre-web:
    image: linuxserver/calibre-web:latest
    volumes:
      - /home/user/calibre-library:/books:ro
      - calibre-config:/config
    environment:
      - PUID=1001
      - PGID=1002

volumes:
  calibre-config:
    driver: local
```

就这么简单。Nginx 配置好路由，服务就起来了。

---

## 遇到的问题和解决

### 问题 1：登录 POST 请求挂死

排查了很久，发现是 Nginx 的 `proxy_buffering off` 缺失。OPDS 的 POST 登录请求在某些情况下会被 Nginx buffer 住，导致超时。

**解决**：在 `/books/` 和 `/` 的 location 段都加上 `proxy_buffering off;`

### 问题 2：frp 穿透后 HTTP 80 端口 502

Nginx 只监听了 443，frpc 连 80 端口时 connection refused。

**解决**：新增 `listen 80; return 301 https://$host$request_uri;`，让 80 端口重定向到 443。

### 问题 3：书名乱码的书无法识别

书库里有一批文件名是编号的 PDF（如 `28820016 77..83.pdf`），从文件名完全无法判断是哪本书。

**思路**：读取文件内容，提取前几百字，用这些文字作为搜索关键词去豆瓣查询。PDF 需要调用 `pdftotext`，EPUB/ZIP 直接解压读 HTML。

---

## 对 AI 友好的本质

AI 能否理解你的书库，取决于元数据是否干净：

```json
// AI 友好的元数据
{
    "title": "三体",
    "author": "刘慈欣",
    "publisher": "重庆出版社",
    "year": 2008,
    "isbn": "9787229006536"
}

// AI 不友好的元数据
{
    "title": "28820016 77..83",
    "author": "Unknown"
}
```

元数据整理是书库建设中最重要但最容易被忽略的工作。**建立书库的第一天就要认真整理**，等到书多了再返工，成本会非常高。

---

## 下一步

1. **全文检索**：让 AI 能够回答具体问题，而不是只知道书名作者。这需要把书库接入 RAG 系统（如 MaxKB / AnythingLLM）
2. **元数据持续维护**：新书入库自动补全元数据
3. **OCR 处理**：对扫描版 PDF 进行文字识别，纳入自动修复流程

</div>

<!-- series: 电子书知识库系列 -->
<div class="series-nav">
    <span class="series-label">系列：电子书知识库系列</span>
    <div class="series-links">
        <a href="/2026/04/23/ebook-library-for-humans-and-ai/" class="nav next">如何构建对人类和 AI 都友好的电子书库 →</a>
    </div>
</div>

---

## 附录：项目地址

项目已开源，包含完整的 Docker Compose 配置和元数据修复脚本：

```
github.com/HardySimpson/calibre-reader
```

包含：
- `docker-compose.yml` — 一键部署
- `nginx/proxy.conf` — Nginx 配置
- `scripts/metadata-fix*.py` — 元数据自动修复脚本
- `docs/DEPLOY.md` — 详细部署文档
