#!/usr/bin/env python3
"""发布《诺特定理与内家拳》到飞天意面公众号"""
import sys, json, subprocess, os, re, time, base64

APPID = "wx6f2600d3acf30196"
APPSECRET = "72f3328bff546478913559b444d05c6b"
TITLE = "诺特定理与内家拳：为什么对称性就是守恒"
AUTHOR = "难易"

# === Step 1: Get access_token ===
print("🔑 获取 access_token...")
resp = subprocess.run(["curl", "-s", f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={APPID}&secret={APPSECRET}"], capture_output=True, text=True)
data = json.loads(resp.stdout)
if "access_token" not in data:
    print(f"❌ {data}")
    sys.exit(1)
TOKEN = data["access_token"]
print("   ✅")

# === Step 2: Download blog post from GitHub ===
print("📥 下载文章...")
subprocess.run(["curl", "-sL", "-o", "/tmp/wx_article.md",
    "https://raw.githubusercontent.com/HardySimpson/blog/main/_posts/2026-05-10-noether-theorem-internal-martial-arts.md"], check=True)
print("   ✅")

# === Step 3: Download cover image ===
print("🖼️  下载封面图...")
subprocess.run(["curl", "-sL", "-o", "/tmp/wx_cover.jpg",
    "https://raw.githubusercontent.com/HardySimpson/blog/main/images/noether-tai-chi-cover.jpg"], check=True)
print("   ✅")

# === Step 4: Prepare Markdown for WeChat ===
print("🔄 处理 Markdown...")
with open("/tmp/wx_article.md") as f:
    md = f.read()

# Strip Jekyll frontmatter
if md.startswith("---"):
    parts = md.split("---", 2)
    md = parts[2]

# Extract sign-off and move to end
signoff_lines = []
body_lines = []
in_signoff = False
for line in md.split("\n"):
    if line.startswith("Sign-off-by:") or line.startswith("Assisted-by:"):
        signoff_lines.append(line)
        in_signoff = True
    elif in_signoff and line.strip() == "":
        signoff_lines.append(line)
    elif in_signoff and line.strip() == "---":
        signoff_lines.append(line)
        in_signoff = False
    else:
        if not in_signoff:  # Only add body lines after sign-off section
            body_lines.append(line)

# Rebuild: body + signoff at end
md = "\n".join(body_lines) + "\n\n" + "\n".join(signoff_lines)

# Cover image: move right after the separator, before first heading
# Remove any stray image from body (it will be embedded separately)
md = re.sub(r'!\[.*?\]\(.*?\)', '', md)

# Remove extra blank lines after signoff ---
md = re.sub(r'\n{3,}', '\n\n', md)
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
# Remove pandoc footnote backlinks
html = re.sub(r'<a[^>]*>\u2191</a>', '', html)

# Remove div/ol/li/sup tags
html = re.sub(r'<div[^>]*>|</div>', '', html)
html = re.sub(r'<ol[^>]*>|</ol>', '', html)
html = re.sub(r'<li[^>]*>|</li>', '', html)
html = re.sub(r'<sup[^>]*>.*?</sup>', '', html, flags=re.DOTALL)
html = re.sub(r'<hr\s*/?>', '', html)
html = re.sub(r'<p>\s*</p>', '', html)
html = re.sub(r'<table[^>]*>', '', html)
html = re.sub(r'</table>', '', html)
html = re.sub(r'<thead[^>]*>', '', html)
html = re.sub(r'</thead>', '', html)
html = re.sub(r'<tbody[^>]*>', '', html)
html = re.sub(r'</tbody>', '', html)
html = re.sub(r'<tr[^>]*>', '', html)
html = re.sub(r'</tr>', '', html)
html = re.sub(r'<td[^>]*>', '', html)
html = re.sub(r'</td>', '', html)
html = re.sub(r'<th[^>]*>', '', html)
html = re.sub(r'</th>', '', html)

# Keep <a> tags for WeChat links (don't strip them entirely)
# Only strip backlinks (↑), keep readable links
html = re.sub(r'<a[^>]*>\s*</a>', '', html)

# Replace $$...$$ inline math with plain text
html = re.sub(r'\$\$.*?\$\$', '', html, flags=re.DOTALL)
html = re.sub(r'\$[^$]+\$', '', html)

# Remove empty <p> tags
html = re.sub(r'<p>\s*</p>', '', html)
html = html.strip()

# === Step 4b: Add inline styles to headings ===
# WeChat strips CSS classes but respects inline style
html = re.sub(r'<h2>', '<h2 style="font-size:1.5em;font-weight:bold;margin:1.2em 0 0.6em">', html)
html = re.sub(r'<h3>', '<h3 style="font-size:1.25em;font-weight:bold;margin:1em 0 0.5em">', html)

# === Step 4c: Insert cover image at the top of body ===
# WeChat body images must be uploaded via uploadimg API
print("🖼️  上传正文图片...")
resp = subprocess.run(["curl", "-s",
    f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={TOKEN}",
    "-F", "media=@/tmp/wx_cover.jpg"], capture_output=True, text=True)
img_data = json.loads(resp.stdout)
if "url" not in img_data:
    print(f"⚠️  图片上传失败: {img_data}，跳过正文图片")
    cover_img_html = ""
else:
    cover_url = img_data["url"]
    cover_img_html = f'<img data-src="{cover_url}" data-ratio="0.5625" data-w="1280" src="{cover_url}" alt="内家运动三定律与现代物理学范式示意" style="width:100%;margin-bottom:1em">'
    print(f"   ✅")

html = cover_img_html + html

print("   ✅")

# === Step 5: Upload cover image (as article thumbnail) ===
print("🖼️  上传封面图...")
resp = subprocess.run(["curl", "-s",
    f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={TOKEN}&type=image",
    "-F", "media=@/tmp/wx_cover.jpg"], capture_output=True, text=True)
data = json.loads(resp.stdout)
if "media_id" not in data:
    print(f"❌ {data}")
    sys.exit(1)
thumb_id = data["media_id"]
print(f"   ✅ media_id: {thumb_id}")

# === Step 6: Create draft ===
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

# === Step 7: Try to publish (may fail for unverified accounts) ===
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
