#!/usr/bin/env python3
"""发布《你的身体对称吗》到飞天意面公众号"""
import sys, json, subprocess, os, re, time

APPID = "wx6f2600d3acf30196"
APPSECRET = "72f3328bff546478913559b444d05c6b"
TITLE = "你的身体对称吗——外三合、丹田与空间结构对称「内家运动三定律」系列之三"
AUTHOR = "难易"
MD_PATH = "/home/hermes/projects/blog/_posts/2026-05-14-spatial-symmetry-angular-momentum.md"
COVER_PATH = "/home/hermes/projects/blog/images/noether-tai-chi-cover.jpg"

# === Step 1: Get access_token ===
print("🔑 获取 access_token...")
resp = subprocess.run(["curl", "-s", "--connect-timeout", "10",
    f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={APPID}&secret={APPSECRET}"],
    capture_output=True, text=True)
data = json.loads(resp.stdout)
if "access_token" not in data:
    print(f"❌ {data}")
    sys.exit(1)
TOKEN = data["access_token"]
print("   ✅")

# === Step 2: Read and clean Markdown ===
print("🔄 处理 Markdown...")
with open(MD_PATH) as f:
    md = f.read()

# Strip frontmatter
if md.startswith("---"):
    parts = md.split("---", 2)
    md = parts[2]

# Extract sign-off lines and move to end
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
        if not in_signoff:
            body_lines.append(line)

md = "\n".join(body_lines) + "\n\n" + "\n".join(signoff_lines)

# Remove body image (will be embedded separately)
md = re.sub(r'!\[.*?\]\(.*?\)', '', md)

# Strip LaTeX math
md = re.sub(r'\$\$.*?\$\$', '', md, flags=re.DOTALL)
md = re.sub(r'\$[^$\n]+\$', '', md)

# Strip kramdown footnote markers [^n] from body
md = re.sub(r'\[\^\d+\]', '', md)

# Convert [^n]: reference lines to plain numbered list items
def ref_to_plain(m):
    num = m.group(1)
    text = m.group(2).strip()
    return f"{num}. {text}"
md = re.sub(r'\[\^(\d+)\]:\s*(.*?)(?=\n\[\^\d+\]:|\n\n|\Z)', ref_to_plain, md, flags=re.DOTALL)

# Replace ## 参考资料 with **参考资料** (avoid h2 rendering issue)
md = md.replace('## 参考资料', '**参考资料**')

md = md.strip()

with open("/tmp/wx_article_clean.md", "w") as f:
    f.write(md)

# Convert with pandoc
r = subprocess.run(["pandoc", "-f", "markdown", "-t", "html", "--wrap=none",
    "-o", "/tmp/wx_article_raw.html", "/tmp/wx_article_clean.md"],
    capture_output=True, text=True)
if r.returncode != 0:
    print(f"❌ pandoc failed: {r.stderr}")
    sys.exit(1)

with open("/tmp/wx_article_raw.html") as f:
    html = f.read()

# === Step 3: Clean HTML for WeChat ===
print("🧹 清洗 HTML...")
html = re.sub(r'<a[^>]*>([^<]*)</a>', r'\1', html)
html = re.sub(r'<section[^>]*class="footnotes[^"]*"[^>]*>.*?</section>', '', html, flags=re.DOTALL)
html = re.sub(r'<div[^>]*>|</div>', '', html)
html = re.sub(r'<ol[^>]*>|</ol>', '', html)
html = re.sub(r'<li[^>]*>|</li>', '', html)
html = re.sub(r'<sup[^>]*>.*?</sup>', '', html, flags=re.DOTALL)
html = re.sub(r'<hr\s*/?>', '', html)
html = re.sub(r'<p>\s*</p>', '', html)
html = re.sub(r'<thead[^>]*>|</thead>|<tbody[^>]*>|</tbody>', '', html)
html = re.sub(r'<a[^>]*>\s*</a>', '', html)

# Strip LaTeX math remnants
html = re.sub(r'\$\$.*?\$\$', '', html, flags=re.DOTALL)
html = re.sub(r'\$[^$]+\$', '', html)

# Heading inline styles (h2=1.5em, h3=1.25em — from previous successful post)
html = re.sub(r'<h2[^>]*>', '<h2 style="font-size:1.5em;font-weight:bold;margin:1em 0 0.4em;border-left:4px solid #07c160;padding-left:8px">', html)
html = re.sub(r'<h3[^>]*>', '<h3 style="font-size:1.25em;font-weight:bold;margin:0.8em 0 0.3em">', html)

# Table styles
html = re.sub(r'<table[^>]*>', '<table style="width:100%;border-collapse:collapse;margin:1em 0;font-size:0.95em">', html)
html = re.sub(r'<th[^>]*>', '<th style="background-color:#f2f2f2;border:1px solid #d9d9d9;padding:10px 12px;text-align:center;font-weight:bold">', html)
html = re.sub(r'<td[^>]*>', '<td style="border:1px solid #d9d9d9;padding:10px 12px">', html)

# === Step 4: Upload cover image for body embedding ===
print("🖼️  上传正文图片...")
resp = subprocess.run(["curl", "-s",
    f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={TOKEN}",
    "-F", f"media=@{COVER_PATH}"], capture_output=True, text=True)
img_data = json.loads(resp.stdout)
if "url" not in img_data:
    print(f"⚠️  图片上传失败: {img_data}，跳过正文图片")
    cover_img_html = ""
else:
    cover_url = img_data["url"]
    cover_img_html = f'<img data-src="{cover_url}" src="{cover_url}" style="width:100%;margin-bottom:1em">'
    print(f"   ✅")

# Insert cover image at top of body
html = cover_img_html + html

# Sign-off at the end
signoff_html = '''<hr style="margin:30px 0 15px"/>
<p style="color:#999;font-size:0.85em">Sign-off-by: 难易</p>
<p style="color:#999;font-size:0.85em">Assisted-by: Hermes:minimax-m2.7</p>'''
html = html.rstrip() + '\n' + signoff_html

html = html.strip()
print("   ✅")

# === Step 5: Upload thumbnail ===
print("🖼️  上传封面缩略图...")
resp = subprocess.run(["curl", "-s",
    f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={TOKEN}&type=image",
    "-F", f"media=@{COVER_PATH}"], capture_output=True, text=True)
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
        "digest": "内家拳外三合：手与足合、肘与膝合、肩与胯合。为什么古典拳论用合而不是对齐？第二定律从空间对称性给出了物理答案。",
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
    print(f"   📎 预览: https://mp.weixin.qq.com/cgi-bin/appmsg?media_id={draft_id}")
elif data.get("errcode", -1) != 0:
    print(f"❌ 草稿创建失败: {data}")
    sys.exit(1)

# === Step 7: Try publish ===
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

print("\n✅ 完成！")
