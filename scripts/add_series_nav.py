#!/usr/bin/env python3
"""Add prev/next navigation links to blog series."""
import re
from pathlib import Path

BLOG_DIR = Path("/home/claw/.openclaw/workspace/coder/blog/_posts")

# 定义系列（按时间顺序排列）
SERIES = {
    "opencode-learning": {
        "name": "OpenCode 学习系列",
        "posts": [
            "2026-03-16-agent-workflow-explanation",
            "2026-03-16-agentloop-opencode",
            "2026-03-19-agent-research-report",
            "2026-03-19-opencode-separated-configuration",
            "2026-03-19-opencode-windows-desktop-log",
            "2026-03-20-acp-protocol-opencode-implementation",
            "2026-04-13-opencode-context-compaction-algorithm",
            "2026-04-21-effect-framework-vs-harness",
            "2026-04-21-cli-pipe-model-implementation",
            "2026-04-22-tool-calling-mechanism",
            "2026-04-27-tool-calling-mechanism",
        ],
    },
    "openclaw-series": {
        "name": "OpenClaw 系列",
        "posts": [
            "2026-04-14-openclaw-binding-peer-channel-agent",
            "2026-04-14-openclaw-keyboard-shortcuts",
        ],
    },
    "ebook-knowledge": {
        "name": "电子书知识库系列",
        "posts": [
            "2026-04-23-ebook-library-architecture",
            "2026-04-23-ebook-library-for-humans-and-ai",
            "2026-04-23-personal-book-knowledge-base-ai-era",
        ],
    },
    "knowledge-ai": {
        "name": "AI 时代知识管理系列",
        "posts": [
            "2026-04-24-knowledge-ai-era",
            "2026-04-24-historical-critiques",
        ],
    },
}


def slug_to_url(slug: str) -> str:
    """Convert slug to GitHub Pages URL."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)", slug)
    if m:
        date, title = m.groups()
        parts = date.split("-")
        return f"/{parts[0]}/{parts[1]}/{parts[2]}/{title}/"
    return f"/{slug}/"


def get_post_title(slug: str) -> str:
    """Get post title from file."""
    path = BLOG_DIR / f"{slug}.md"
    if not path.exists():
        return slug
    content = path.read_text()
    m = re.search(r'^title:\s*"([^"]+)"', content, re.MULTILINE)
    return m.group(1) if m else slug


def add_nav_to_post(slug: str, prev_slug: str | None, next_slug: str | None, series_name: str) -> None:
    """Add prev/next navigation to a post."""
    path = BLOG_DIR / f"{slug}.md"
    if not path.exists():
        print(f"  SKIP: {slug}.md not found")
        return

    content = path.read_text()

    # Build navigation HTML
    nav_parts = []
    if prev_slug:
        prev_title = get_post_title(prev_slug)
        prev_url = slug_to_url(prev_slug)
        nav_parts.append(
            f'<a href="{prev_url}" class="nav prev">← {prev_title}</a>'
        )
    if next_slug:
        next_title = get_post_title(next_slug)
        next_url = slug_to_url(next_slug)
        nav_parts.append(
            f'<a href="{next_url}" class="nav next">{next_title} →</a>'
        )

    if not nav_parts:
        return

    nav_html = f"""
<!-- series: {series_name} -->
<div class="series-nav">
    <span class="series-label">系列：{series_name}</span>
    <div class="series-links">
        {" &nbsp;|&nbsp; ".join(nav_parts)}
    </div>
</div>
"""

    # 检查是否已有导航
    if '<!-- series:' in content and 'class="series-nav"' in content:
        print(f"  SKIP: {slug}.md already has navigation")
        return

    # 插入到参考资料之前（最后一个 --- 分隔符之后）
    last_delim = content.rfind("\n---\n")
    if last_delim == -1:
        print(f"  SKIP: {slug}.md has no --- delimiter")
        return

    content = content[:last_delim] + nav_html + content[last_delim:]
    path.write_text(content)
    print(f"  ADDED: {slug}.md")


def main():
    print("Adding series navigation links...\n")

    for series_id, series in SERIES.items():
        print(f"Processing series: {series['name']}")
        posts = series["posts"]
        for i, slug in enumerate(posts):
            prev_slug = posts[i - 1] if i > 0 else None
            next_slug = posts[i + 1] if i < len(posts) - 1 else None
            add_nav_to_post(slug, prev_slug, next_slug, series["name"])
        print()

    print("Done!")


if __name__ == "__main__":
    main()
