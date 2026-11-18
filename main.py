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
import re

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
# 2. 超强信息源矩阵 (无需任何公网IP)
# ==========================================
# 📢 国内优质技术源 (直接可用的公开 RSS)
DOMESTIC_FEEDS = [
    # 王齐 (Sailing_W) 的 CSDN 博客：国内讲 PCIe 体系结构最经典的作者
    "https://rsshub.app/csdn/blog/sailing_w",
    
    # 你之前找的 CSDN 博主 (AI Agent 与底层硬件)
    "https://rsshub.app/csdn/blog/m0_64182150",
    
    # InfoQ 中文：涵盖大量架构、底层技术的深度好文
    "https://www.infoq.cn/feed",
    
    # 掘金的架构分类
    "https://rsshub.app/juejin/category/architecture",
    
    # 阮一峰博客 (作为全栈技术视野保底)
    "https://www.ruanyifeng.com/blog/atom.xml"
]

# 📢 海外硬核技术源 (直接可用的公开 RSS)
INTL_FEEDS = [
    # Chips and Cheese：硬核微架构分析，包含大量 GPU 缓存、内存子系统的微基准测试
    "https://chipsandcheese.com/feed/",
    
    # Semiconductor Engineering：半导体工程，涵盖先进封装、CXL、互联技术
    "https://semiengineering.com/feed/",
    
    # AnandTech：老牌硬件评测，深度解析 PCIe/CXL 标准演进与服务器架构
    "https://www.anandtech.com/rss/",
    
    # Tom's Hardware：全球知名硬件网站，服务器、GPU 架构新闻
    "https://www.tomshardware.com/feeds/all",
    
    # TechPowerUp：硬件评测与技术新闻
    "https://www.techpowerup.com/rss/news"
]

REPORT_TITLE = "📚 AI 硬件系统知识精讲"
REPORT_SUBTITLE = "覆盖：PCIe / GPU互联 / 通信库 / GPU芯片 / PCIe Switch / CXL"

# ==========================================
# 3. 邮件发送函数
# ==========================================
def send_email(subject, html_content):
    mail_user = os.environ.get("MAIL_USER")
    mail_password = os.environ.get("MAIL_PASSWORD")
    mail_recipient = os.environ.get("MAIL_RECIPIENT")
    mail_server = os.environ.get("MAIL_SERVER", "smtp.qq.com")

    if not all([mail_user, mail_password, mail_recipient]):
        print("错误：邮箱配置不完整。")
        return

    styled_html = f"""
    <html>
    <head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; }}
        .container {{ background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        h1, h2 {{ color: #1a73e8; border-bottom: 2px solid #eaeaea; padding-bottom: 10px; margin-top: 0; }}
        h3 {{ color: #2c3e50; margin-top: 0; }}
        .card {{ background: #ffffff; border: 1px solid #e0e0e0; border-left: 5px solid #1a73e8; border-radius: 6px; padding: 20px; margin-bottom: 25px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
        img {{ max-width: 100%; height: auto; border-radius: 6px; margin: 10px 0; display: block; border: 1px solid #eee; }}
        a {{ color: #1a73e8; text-decoration: none; font-weight: bold; }}
        a:hover {{ text-decoration: underline; }}
        .meta {{ color: #888; font-size: 0.9em; margin-bottom: 15px; }}
        ul {{ padding-left: 20px; }}
        li {{ margin-bottom: 8px; }}
    </style>
    </head>
    <body>
        <div class="container">
            {html_content}
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg["From"] = mail_user
    msg["To"] = mail_recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(styled_html, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(mail_server, 465) as server:
            server.login(mail_user, mail_password)
            server.sendmail(mail_user, mail_recipient, msg.as_string())
        print("✅ 邮件发送成功！")
    except Exception as e:
        print(f"❌ 邮件发送失败：{e}")

# ==========================================
# 4. 抓取逻辑
# ==========================================
def fetch_recent_rss(feed_urls, days_limit=7):
    print(f"📡 正在扫描技术源...")
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
# 5. 穿透抓取正文
# ==========================================
def extract_full_text(url):
    jina_url = f"https://r.jina.ai/{url}"
    try:
        headers = {"X-Return-Format": "markdown"}
        response = requests.get(jina_url, headers=headers, timeout=20)
        if response.status_code == 200:
            text = response.text
            if len(text) > 200 and "Access Denied" not in text:
                return text[:6000]
    except Exception:
        pass
    return ""

# ==========================================
# 6. AI 知识整理引擎
# ==========================================
def analyze_with_ai(title, url, content, source_name):
    prompt = f"""
    你是一位资深的计算机体系结构与底层硬件专家。
    请阅读这篇技术文章：
    【标题】：{title}
    【正文】：{content}
    
    【绝对判定准则】
    只要文章涉及以下任何领域（PCIe / GPU互联 / 通信库 / GPU芯片 / PCIe Switch / CXL / 半导体架构 / 芯片封装），请务必输出卡片。
    如果文章是纯软件应用开发（如前端、Java）、新闻八卦、社会资讯，请直接回复“无效资讯”。

    【输出格式要求】
    请**直接输出 HTML 代码片段**（不要用 ``` 包裹，直接以 <h3> 开头）。
    必须严格按以下 HTML 结构输出：
    <h3>📖 {title}</h3>
    <p class="meta">🔗 原文链接：<a href="{url}" target="_blank">{url}</a></p>
    
    <p><b>【所属门类】</b>：从（PCIe / GPU互联 / 通信库 / GPU芯片 / PCIe Switch / CXL）中选一个。</p>
    
    <p><b>【核心概念】</b>：用一两段话解释文章涉及的核心技术点。</p>
    
    <p><b>【原理解析】</b>：详细拆解技术原理。
    ⚠️ 若原文有架构图/流程图，请在合适的位置插入 HTML 图片标签：<img src="图片URL" alt="架构图"> (请从原文中提取真实的图片 URL，若无图片则不要输出 img 标签)</p>
    
    <p><b>【重点笔记】</b>：列出 2-3 个核心知识点。</p>
    <ul>
        <li>要点1</li>
        <li>要点2</li>
    </ul>
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-ai/DeepSeek-V4.1-Flash-1017", 
            messages=[
                {"role": "system", "content": "你是一个严谨的底层硬件架构师，只输出纯净的 HTML 技术笔记。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        raw_result = response.choices[0].message.content.strip()
        clean_html = re.sub(r'^```(html)?\s*', '', raw_result)
        clean_html = re.sub(r'\s*```$', '', clean_html)
        return clean_html.strip()
    except Exception as e:
        print(f"   ❌ API调用出错: {e}")
        return "无效资讯"

# ==========================================
# 7. 流水线控制
# ==========================================
def process_news_pipeline(news_list, section_title, limit=2):
    report_text = f"<h2>{section_title}</h2>"
    valid_count = 0
    
    for item in news_list:
        if valid_count >= limit:
            break
            
        print(f"🧐 评估文章: {item['title'][:30]}...")
        full_text = extract_full_text(item['url'])
        
        if not full_text:
            print(f"   ⚠️ 丢弃原因: 抓取正文失败或正文太短")
            continue
            
        time.sleep(2) 
        analysis = analyze_with_ai(item['title'], item['url'], full_text, item['source'])
        
        if "无效资讯" not in analysis and "<h3>" in analysis:
            valid_count += 1
            report_text += f"<div class='card'>\n{analysis}\n</div>\n"
            print(f"   ✅ 成功收录！")
        else:
            print(f"   ❌ 丢弃原因: AI判定不符合门类")
            
    if valid_count == 0:
        report_text += "<div class='card'><p>🛡️ 本期暂无符合底层硬件门类的深度文章。</p></div>"
    return report_text

# ==========================================
# 8. 执行入口
# ==========================================
if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    raw_domestic = fetch_recent_rss(DOMESTIC_FEEDS, days_limit=7) 
    raw_intl = fetch_recent_rss(INTL_FEEDS, days_limit=7)
    
    final_html = f"<h1>{REPORT_TITLE}</h1>"
    final_html += f"<p><b>生成日期：</b>{today_str}</p>"
    final_html += f"<p><b>知识体系：</b>{REPORT_SUBTITLE}</p><hr>"
    
    # 国内找 2 篇，海外找 1 篇
    final_html += process_news_pipeline(raw_domestic, "📌 国内技术深度解析", limit=1)
    #final_html += process_news_pipeline(raw_intl, "🌐 海外硬核架构剖析", limit=1)
    
    email_subject = f"【每日技术精读】{today_str} - 底层架构知识"
    send_email(email_subject, final_html)
    print("🎉 每日学习任务执行完毕！")
