#!/usr/bin/env python3
"""发布《桩功第一步：接地》到飞天意面公众号"""
import sys, json, subprocess, os, re, time

APPID = "wx6f2600d3acf30196"
APPSECRET = "72f3328bff546478913559b444d05c6b"
TITLE = "桩功第一步：接地"
AUTHOR = "难易"

# === Step 1: Get access_token ===
print("🔑 获取 access_token...")
resp = subprocess.run(["curl", "-s", "--connect-timeout", "10", f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={APPID}&secret={APPSECRET}"], capture_output=True, text=True)
data = json.loads(resp.stdout)
if "access_token" not in data:
    print(f"❌ {data}")
    sys.exit(1)
TOKEN = data["access_token"]
print("   ✅")

# === Step 2: Download blog post from GitHub ===
print("📥 下载文章...")
r = subprocess.run(["curl", "-sL", "--connect-timeout", "10", "--max-time", "15", "-o", "/tmp/wx_article.md",
    "https://ghfast.top/https://raw.githubusercontent.com/HardySimpson/blog/main/_posts/2026-05-21-zhuang-gong-step-one-grounding.md"], capture_output=True, text=True)
if r.returncode != 0:
    print(f"❌ curl exit={r.returncode} stderr={r.stderr}")
    sys.exit(1)
print("   ✅")

# === Step 3: Download cover image ===
print("🖼️  下载封面图...")
r = subprocess.run(["curl", "-sL", "--connect-timeout", "10", "--max-time", "15", "-o", "/tmp/wx_cover.jpg",
    "https://ghfast.top/https://raw.githubusercontent.com/HardySimpson/blog/main/images/tree-roots-grounding-cover.jpg"], capture_output=True, text=True)
if r.returncode != 0:
    print(f"❌ curl exit={r.returncode} stderr={r.stderr}")
    sys.exit(1)
print("   ✅", flush=True)

# === Step 4: Prepare Markdown for WeChat ===
print("🔄 处理 Markdown...")
with open("/tmp/wx_article.md") as f:
    md = f.read()

# Strip Jekyll frontmatter
if md.startswith("---"):
    parts = md.split("---", 2)
    md = parts[2]

# Remove Sign-off and Assisted-by lines (user prefers WeChat without them)
md_lines = md.split("\n")
clean_lines = []
for line in md_lines:
    if line.startswith("Sign-off-by:") or line.startswith("Assisted-by:"):
        continue
    # Skip blank lines that were around signoff
    clean_lines.append(line)
md = "\n".join(clean_lines)

# Remove the separator line (standalone ---)
md = re.sub(r'\n---\n', '\n', md)

# Convert "## 参考资料与原始出处" to bold text (WeChat preference)
md = md.replace('## 参考资料与原始出处', '**参考资料与原始出处**')

# Remove any stray image markdown (will embed cover separately)
md = re.sub(r'!\[.*?\]\(.*?\)', '', md)

# Remove extra blank lines
md = re.sub(r'\n{3,}', '\n\n', md)

# Strip kramdown footnote markers [^n] from body text
md = re.sub(r'\[\^\d+\]', '', md)

# Convert [^n]: definition lines to plain numbered list items
def ref_to_plain(m):
    num = m.group(1)
    text = m.group(2).strip()
    return f"{num}. {text}"

md = re.sub(r'\[\^(\d+)\]:\s*(.*?)(?=\n\[\^\d+\]:|\n\n|\Z)', ref_to_plain, md, flags=re.DOTALL)

md = md.strip()

# Write cleaned markdown
with open("/tmp/wx_article_clean.md", "w") as f:
    f.write(md)

# Convert with pandoc
subprocess.run(["pandoc", "-f", "markdown", "-t", "html", "--wrap=none",
    "-o", "/tmp/wx_article_raw.html", "/tmp/wx_article_clean.md"], check=True)

with open("/tmp/wx_article_raw.html") as f:
    html = f.read()

# Clean HTML for WeChat
html = re.sub(r'<a[^>]*>([^<]*)</a>', r'\1', html)
html = re.sub(r'<section[^>]*class="footnotes[^\"]*"[^>]*>.*?</section>', '', html, flags=re.DOTALL)
html = re.sub(r'<div[^>]*>|</div>', '', html)
html = re.sub(r'<ol[^>]*>|</ol>', '', html)
html = re.sub(r'<li[^>]*>|</li>', '', html)
html = re.sub(r'<sup[^>]*>.*?</sup>', '', html, flags=re.DOTALL)
html = re.sub(r'<hr\s*/?>', '', html)
html = re.sub(r'<p>\s*</p>', '', html)
html = re.sub(r'<thead[^>]*>|</thead>|<tbody[^>]*>|</tbody>', '', html)
html = re.sub(r'<a[^>]*>\s*</a>', '', html)

# Remove empty <p> tags
html = re.sub(r'<p>\s*</p>', '', html)
html = html.strip()

# Add inline styles to headings
html = re.sub(r'<h2[^>]*>', '<h2 style="font-size:1.6em;font-weight:bold;margin:1.2em 0 0.5em;border-left:4px solid #07c160;padding-left:8px">', html)
html = re.sub(r'<h3[^>]*>', '<h3 style="font-size:1.3em;font-weight:bold;margin:1em 0 0.4em">', html)

# === Step 5: Upload body image (cover as top image) ===
print("🖼️  上传正文图片...", flush=True)
resp = subprocess.run(["curl", "-s",
    f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={TOKEN}",
    "-F", "media=@/tmp/wx_cover.jpg"], capture_output=True, text=True)
img_data = json.loads(resp.stdout)
if "url" not in img_data:
    print(f"⚠️  图片上传失败: {img_data}，跳过正文图片")
    cover_img_html = ""
else:
    cover_url = img_data["url"]
    cover_img_html = f'<img data-src="{cover_url}" data-ratio="1.5" data-w="1200" src="{cover_url}" alt="树根深扎大地" style="width:100%;margin-bottom:1em">'
    print(f"   ✅")

html = cover_img_html + html
print("   ✅")

# === Step 6: Upload cover image (as article thumbnail) ===
print("🖼️  上传封面图缩略图...")
resp = subprocess.run(["curl", "-s",
    f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={TOKEN}&type=image",
    "-F", "media=@/tmp/wx_cover.jpg"], capture_output=True, text=True)
data = json.loads(resp.stdout)
if "media_id" not in data:
    print(f"❌ {data}")
    sys.exit(1)
thumb_id = data["media_id"]
print(f"   ✅ media_id: {thumb_id}")

# === Step 7: Create draft ===
print("📋 创建草稿...")
payload = {
    "articles": [{
        "title": TITLE,
        "author": AUTHOR,
        "content": html,
        "thumb_media_id": thumb_id,
        "need_open_comment": 0,
        "only_fans_can_comment": 0
    }]
}
with open("/tmp/wx_draft.json", "w") as f:
    json.dump(payload, f, ensure_ascii=False)

resp = subprocess.run(["curl", "-s",
    f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={TOKEN}",
    "-H", "Content-Type: application/json",
    "-d", "@/tmp/wx_draft.json"], capture_output=True, text=True)
data = json.loads(resp.stdout)
if "media_id" in data and "errcode" not in data:
    draft_id = data["media_id"]
    print(f"   ✅ draft_id: {draft_id}")
    print(f"   📎 预览链接: https://mp.weixin.qq.com/cgi-bin/appmsg?media_id={draft_id}")
elif data.get("errcode", -1) != 0:
    print(f"❌ 草稿创建失败: {data}")
    if data.get("errcode") == 40164:
        print("   → IP 不在白名单，需要加 IP 到微信后台")
    sys.exit(1)

# === Step 8: Try to publish ===
print("🚀 尝试发布...")
payload = {"media_id": draft_id}
with open("/tmp/wx_pub.json", "w") as f:
    json.dump(payload, f)

resp = subprocess.run(["curl", "-s",
    f"https://api.weixin.qq.com/cgi-bin/freepublish/submit?access_token={TOKEN}",
    "-H", "Content-Type: application/json",
    "-d", "@/tmp/wx_pub.json"], capture_output=True, text=True)
data = json.loads(resp.stdout)

if data.get("errcode") == 0:
    pid = data.get("publish_id")
    print(f"   ✅ publish_id: {pid}")
    print("⏳ 等待审核...")
    for i in range(6):
        time.sleep(5)
        resp = subprocess.run(["curl", "-s",
            f"https://api.weixin.qq.com/cgi-bin/freepublish/get?access_token={TOKEN}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps({"publish_id": pid})], capture_output=True, text=True)
        status = json.loads(resp.stdout)
        s = status.get("publish_status", -1)
        if s == 0:
            print("   ✅ 发布成功！")
            aid = status.get("article_id", "")
            if aid:
                print(f"   🔗 https://mp.weixin.qq.com/s/{aid}")
            break
        elif s == 1:
            print(f"   ⏳ 审核中 ({i+1}/6)...")
        else:
            print(f"   ❌ 发布失败: {status}")
            break
else:
    print(f"   ⚠️ 无法自动发布: {data}")
    print(f"   → 请手动从后台发布")
    print(f"   后台: https://mp.weixin.qq.com/cgi-bin/appmsg?media_id={draft_id}")

print("\n✅ 完成！")
