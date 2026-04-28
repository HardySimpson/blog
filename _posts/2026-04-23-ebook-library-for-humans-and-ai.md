---
layout: post
title: "如何构建对人类和 AI 都友好的电子书库"
category: 电子书
date: 2026-04-23 06:15:00 +0800
---

Sign-off-by: 钟成

Assisted-by: OpenClaw:minimax/M2.7

# 如何构建对人类和 AI 都友好的个人电子书库

> 一站式方案：从 1848 本书库到随时随地阅读

---

## 背景

个人电子书库是个老话题，但随着 LLM 和 AI Agent 的爆发，一个新需求正在浮现：

**你的书库，能不能让 AI 也读懂？**

AI 要帮你回答"这本书讲了什么"、总结要点、跨书关联知识，首先需要的是**结构化的元数据**——书名、作者、出版社、出版年、简介、分类标签。

本文记录了我构建这套电子书库的完整经验，适合想在家里搭一套"可 AI 访问的个人图书馆"的朋友。

---

## 核心目标

- ✅ **人**：手机/电脑随时阅读，格式不挑（EPUB/PDF/TXT）
- ✅ **AI**：结构化元数据，可编程查询，可让 LLM 作为知识库
- ✅ **维护成本低**：增量更新自动化

---

## 技术方案

### 架构一览

```
用户手机
  │
  ▼
teachoice.net/books/          ← 域名入口
  │
  ▼
Nginx（反向代理）
  │
  ├─ /books/  → Calibre-Web（书库管理 + OPDS 阅读协议）
  └─ /api/    → 其他服务
       │
       ▼
   Calibre 数据库（SQLite）
```

### 为什么选 Calibre-Web

Calibre 是电子书管理的事实标准，但桌面版太重。**Calibre-Web** 提供了轻量化的 Web 界面，同时原生支持 **OPDS 协议**——这是让手机阅读 App 连接书库的关键。

对比其他方案：

| 方案 | OPDS | 跨平台 | AI 友好 | 部署难度 |
|------|------|--------|---------|----------|
| Calibre 桌面版 | ❌ | ❌ | 中 | 简单 |
| **Calibre-Web** | ✅ | ✅ | ✅ | 简单 |
| Kouko（Node.js） | ✅ | ✅ | 中 | 简单 |
| Self-hosted Goodreads | ✅ | ✅ | 低 | 复杂 |

---

## 部署细节

### 1. Docker 部署 Calibre-Web

```yaml
services:
  calibre-web:
    image: linuxserver/calibre-web:latest
    container_name: calibre-web
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Asia/Shanghai
    volumes:
      - /home/claw/calibre-library:/books
      - ./app.db:/config/app.db
    restart: unless-stopped
```

关键点：**书库路径映射到容器内 `/books`**，这是 Calibre-Web 默认的配置路径。

### 2. Nginx 子路径路由

书库通过 `/books/` 路径暴露，不需要额外的域名或端口：

```nginx
location /books/ {
    proxy_pass http://calibre-web:8083/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    # 关闭 proxy_buffering，避免大文件下载卡死
    proxy_buffering off;
}
```

### 3. OPDS 协议接入

OPDS 是让阅读 App 连接书库的桥梁。地址就是：

```
https://your-domain.com/books/opds/
```

支持 OPDS 的免费阅读 App（Android）：

- **FBReader** — 老牌轻量，完全免费
- **Foliate** — 开源，界面现代
- **Librera Reader** — 功能丰富，免费无广告

---

## 对 AI 友好的关键：元数据

这是本文最重要的部分。

### 问题

书库有 **1848 本书**，但相当一部分元数据是错的：

- 书名 = 作者名（如《三体X》显示作者也是"三体X"）
- 拼音文件名无法识别（如 `28820016 77..83.pdf`）
- 作者字段为 `Unknown`

### 解决：双源 API 自动修复

同时调用两个数据源：

1. **豆瓣**（`book.douban.com/j/subject_suggest`）— 中文书籍主力
2. **Open Library**（`openlibrary.org/search.json`）— 英文书籍

```python
def search_douban(title):
    url = f"https://book.douban.com/j/subject_suggest?q={quote(title[:40])}"
    resp = urlopen(Request(url, headers=H))
    return json.loads(resp.read().decode())

def search_openlibrary(title):
    url = f"https://openlibrary.org/search.json?q={quote(title)}&limit=3"
    resp = urlopen(Request(url))
    return json.loads(resp.read().decode())["docs"]
```

### 关键教训

**书库的元数据质量比选择什么软件更重要。**

AI 能否读懂你的书库，取决于元数据是否干净：

```json
# AI 友好的元数据示例
{
    "title": "三体",
    "author": "刘慈欣",
    "publisher": "重庆出版社",
    "year": 2008,
    "isbn": "9787229006536",
    "tags": ["科幻", "硬科幻", "三体三部曲"]
}

# AI 不友好的元数据
{
    "title": "28820016 77..83",
    "author": "Unknown",
    "publisher": "",
    "year": null,
    "tags": []
}
```

**建议**：建立书库之初就用 Calibre 桌面版认真整理元数据，后期成本会低很多。

---

## 全文检索：让 AI 能回答具体问题

Calibre-Web 自带基础搜索，但更高级的知识库需求，可以配合 **语义搜索**：

```
用户问题
   ↓
Embedding 模型（对问题向量化）
   ↓
向量数据库（匹配相关段落）
   ↓
LLM（结合上下文生成答案）
   ↓
回答
```

具体实现可以用：
- **MaxKB**（开源，支持 RAG）
- **AnythingLLM**（桌面端，简单易用）
- **Dify**（自部署，需要一定技术背景）

---

## 持续维护

### 增量更新

新书入库后，元数据需要同步。最简方案：

1. 用 Calibre 桌面版整理新书元数据
2. 保存后 Calibre-Web 自动读取
3. OPDS 书库实时更新

### OPDS 不支持上传

OPDS 是只读协议。上传新书的方式：

- **网页端上传**：Calibre-Web 界面手动添加
- **NAS 共享**：通过 SMB 协议直接在文件夹里拖书
- **Calibre 桌面版**：批量导入，效率最高

---

## 效果

部署完成后：

- 手机 App（FBReader / Librera）直接连接书库，随时阅读
- 任何设备浏览器访问 `teachoice.net/books/` 即可浏览
- AI 助手可以接入 OPDS 书库做知识库（OPDS 输出标准 Atom XML）
- 书库完全私有，不依赖任何第三方云服务

---

## 常见问题

**Q: 为什么不用微信读书/多看阅读？**

A: 那些是平台，书不归你。本地书库才是你的资产。

**Q: 没有公网 IP 怎么从外面访问？**

A: 可以用 Cloudflare Tunnel / frp 内网穿透，不暴露公网 IP 更安全。

**Q: 元数据整理太麻烦怎么办？**

A: 优先整理高频阅读的书，其他的先用 Douban/OL 插件自动匹配，慢慢来。

</div>

<!-- series: 电子书知识库系列 -->
<div class="series-nav">
    <span class="series-label">系列：电子书知识库系列</span>
    <div class="series-links">
        <a href="/2026/04/23/ebook-library-architecture/" class="nav prev">← 自托管电子书库的技术架构：Calibre-Web 部署实战</a> &nbsp;|&nbsp; <a href="/2026/04/23/personal-book-knowledge-base-ai-era/" class="nav next">个人书籍知识库——生命的细胞膜 →</a>
    </div>
</div>

---

*有问题或建议？欢迎交流。*
