import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import requests
import feedparser
from openai import OpenAI
from datetime import datetime, timedelta
import time
from email.utils import parsedate_to_datetime
import markdown  # 新增：用于把大模型输出的 Markdown 转为 HTML

# ==========================================
# 1. 核心环境配置
# ==========================================
API_KEY = os.environ.get("DEEPSEEK_API_KEY")
if not API_KEY:
    raise ValueError("DEEPSEEK_API_KEY 环境变量为空，请检查 GitHub Secrets")

client = OpenAI(
    api_key=API_KEY,
    base_url="https://api-inference.modelscope.cn/v1"
)

# ==========================================
# 2. 信息源矩阵
# ==========================================
DOMESTIC_FEEDS = [
    # 填你自己的国内技术源，建议单账号RSS
]

INTL_FEEDS = [
    "https://www.anandtech.com/rss/",
    "https://chipsandcheese.com/feed/"
]

REPORT_TITLE = "📚 AI 硬件系统知识精讲"
REPORT_SUBTITLE = "覆盖：PCIe / GPU互联 / 通信库 / GPU芯片 / PCIe Switch / CXL"

# ==========================================
# 3. 邮件发送函数 (升级为 HTML 渲染)
# ==========================================
def send_email(subject, md_content):
    mail_user = os.environ.get("MAIL_USER")
    mail_password = os.environ.get("MAIL_PASSWORD")
    mail_recipient = os.environ.get("MAIL_RECIPIENT")
    mail_server = os.environ.get("MAIL_SERVER", "smtp.qq.com")

    if not all([mail_user, mail_password, mail_recipient]):
        print("错误：邮箱配置不完整。")
        return

    # 将 Markdown 转换为带格式的 HTML，并加上基础 CSS 美化
    html_body = markdown.markdown(md_content)
    styled_html = f"""
    <html>
    <head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1, h2, h3 {{ color: #1a73e8; border-bottom: 1px solid #eee; padding-bottom: 5px; }}
        img {{ max-width: 100%; height: auto; border-radius: 8px; margin: 10px 0; display: block; }}
        blockquote {{ border-left: 4px solid #1a73e8; margin: 0; padding-left: 15px; color: #666; background: #f8f9fa; padding: 10px; }}
        a {{ color: #1a73e8; text-decoration: none; }}
        .card {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 15px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
    </style>
    </head>
    <body>
    {html_body}
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg["From"] = mail_user
    msg["To"] = mail_recipient
    msg["Subject"] = subject
    # ⚠️ 使用 html 格式发送
    msg.attach(MIMEText(styled_html, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(mail_server, 465) as server:
            server.login(mail_user, mail_password)
            server.sendmail(mail_user, mail_recipient, msg.as_string())
        print("✅ 图文邮件发送成功！")
    except Exception as e:
        print(f"❌ 邮件发送失败：{e}")

# ==========================================
# 4. 抓取逻辑
# ==========================================
def fetch_recent_rss(feed_urls, days_limit=7):
    print(f"📡 正在扫描技术源，筛选过去 {days_limit} 天内的深度文章...")
    recent_items = []
    limit_date = datetime.now() - timedelta(days=days_limit)
    
    for url in feed_urls:
        try:
            feed = feedparser.parse(url)
            source_name = feed.feed.title if hasattr(feed.feed, 'title') else "技术专栏"
            
            for entry in feed.entries:
                try:
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        pub_date = datetime(*entry.published_parsed[:6])
                    elif hasattr(entry, 'published'):
                        pub_date = parsedate_to_datetime(entry.published).replace(tzinfo=None)
                    else:
                        continue
                        
                    if pub_date >= limit_date:
                        recent_items.append({
                            "title": entry.title,
                            "url": entry.link,
                            "summary": entry.get("summary", ""),
                            "source": source_name,
                            "pub_date": pub_date
                        })
                except Exception:
                    pass
        except Exception as e:
            print(f"解析 {url} 失败: {e}")
            
    recent_items.sort(key=lambda x: x['pub_date'], reverse=True)
    print(f"✅ 扫描完毕，共发现 {len(recent_items)} 篇待解析文章。")
    return recent_items

# ==========================================
# 5. Jina 穿透抓取正文
# ==========================================
def extract_full_text(url):
    # 使用 Jina AI 获取网页的 Markdown 格式（包含图片语法）
    jina_url = f"https://r.jina.ai/{url}"
    try:
        # 💡 这里加上 header，让 Jina 返回带图片的 Markdown
        headers = {"X-Return-Format": "markdown"}
        response = requests.get(jina_url, headers=headers, timeout=20)
        if response.status_code == 200:
            text = response.text
            if len(text) > 200 and "Access Denied" not in text:
                return text[:6000]
    except Exception:
        pass
    return "抓取正文受限。"

# ==========================================
# 6. 核心 AI 引擎：要求保留图片格式
# ==========================================
def analyze_with_ai(title, content, source_name):
    # 修改 Prompt，明确要求保留 Markdown 图片语法
    prompt = f"""
    你是一位资深的计算机体系结构与底层硬件专家。你的任务是将技术文章转化为系统性的学习笔记。
    请阅读这篇来自【{source_name}】的技术文章：
    【标题】：{title}
    【正文】：{content}
    
    【判定准则】
    如果内容与底层硬件、AI 算力架构、系统通信完全无关（如纯软件应用、社会新闻），请仅回复“无效资讯”。
    如果有价值，请按以下“知识卡片”结构提取知识。

    ⚠️【重要图片要求】
    如果原文中包含有价值的**流程图、芯片架构图、拓扑图**，请务必保留其 Markdown 图片语法 `![描述](图片URL)`，不要删除图片链接。

    【输出结构】
    **【所属门类】**：（必须从以下六个中选一个：PCIe / GPU互联 / 通信库 / GPU芯片 / PCIe Switch / CXL）
    
    **【核心概念】**：这篇文章主要解释了哪些核心概念或技术机制？
    
    **【原理解析】**：用通俗严谨的语言解释原理。（如果原文有架构图，请把图片放在这里，并配上说明）
    
    **【重点笔记】**：提炼 2-3 个最值得记住的关键细节或参数。
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-ai/DeepSeek-V4.1-Flash-1017", 
            messages=[
                {"role": "system", "content": "你是一个擅长将复杂技术拆解为结构化笔记的系统架构师，并能准确保留文档中的 Markdown 图片。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"API调用出错: {e}")
        return "无效资讯"

# ==========================================
# 7. 流水线核心逻辑 (精简额度)
# ==========================================
def process_news_pipeline(news_list, section_title, limit=2):
    report_text = f"## {section_title}\n\n"
    valid_count = 0
    
    for item in news_list:
        if valid_count >= limit:
            break
            
        print(f"🧐 评估文章: {item['title'][:30]}...")
        full_text = extract_full_text(item['url'])
        time.sleep(2) 
        
        analysis = analyze_with_ai(item['title'], full_text, item['source'])
        
        if "无效资讯" not in analysis:
            valid_count += 1
            # 用 html div 包裹一下，让邮件更好看
            report_text += f"<div class='card'>\n\n"
            report_text += f"### [{item['title']}]({item['url']})\n\n"
            report_text += f"{analysis}\n\n"
            report_text += f"</div>\n\n"
            
    if valid_count == 0:
        report_text += "> 🛡️ 本期未抓取到符合要求的系统性深度文章。\n\n"
    return report_text

# ==========================================
# 8. 执行与推送
# ==========================================
if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    raw_domestic = fetch_recent_rss(DOMESTIC_FEEDS, days_limit=3) 
    raw_intl = fetch_recent_rss(INTL_FEEDS, days_limit=3)
    
    final_report = f"# {REPORT_TITLE}\n\n"
    final_report += f"**生成日期**：{today_str}\n\n"
    final_report += f"**知识体系**：{REPORT_SUBTITLE}\n\n---\n\n"
    
    # 💡 严格控制：国内 2 篇，海外 1 篇。每天只消耗 6 个魔粒！
    final_report += process_news_pipeline(raw_domestic, "📌 国内技术深度解析", limit=2)
    final_report += process_news_pipeline(raw_intl, "🌐 海外硬核架构剖析", limit=1)
    
    email_subject = f"【每日技术精读】{today_str} - 底层架构知识"
    send_email(email_subject, final_report)
    print("🎉 每日学习任务执行完毕！")
