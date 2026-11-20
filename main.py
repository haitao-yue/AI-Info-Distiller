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
import json

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
# 2. 超强信息源矩阵
# ==========================================
DOMESTIC_FEEDS = [
    "https://rsshub.app/csdn/blog/sailing_w",
    "https://rsshub.app/csdn/blog/m0_64182150",
    "https://www.infoq.cn/feed",
    "https://rsshub.app/juejin/category/architecture",
    "https://www.ruanyifeng.com/blog/atom.xml"
]

INTL_FEEDS = [
    "https://chipsandcheese.com/feed/",
    "https://semiengineering.com/feed/",
    "https://www.anandtech.com/rss/",
    "https://www.tomshardware.com/feeds/all",
    "https://www.techpowerup.com/rss/news"
]

REPORT_TITLE = "📚 AI 硬件系统知识精讲"
REPORT_SUBTITLE = "覆盖：PCIe / GPU互联 / 通信库 / GPU芯片 / PCIe Switch / CXL"

# ==========================================
# 3. 历史记录读写模块 (防重复核心)
# ==========================================
HISTORY_FILE = "history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_history(new_urls):
    history = load_history()
    history.update(new_urls)
    # 为了不让文件无限膨胀，只保留最近的 1000 条记录
    history_list = list(history)[-1000:] 
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history_list, f, ensure_ascii=False, indent=2)

# ==========================================
# 4. 邮件发送函数
# ==========================================
def send_email(subject, html_content):
    mail_user = os.environ.get("MAIL_USER")
    mail_password = os.environ.get("MAIL_PASSWORD")
    mail_recipient = os.environ.get("MAIL_RECIPIENT")
    mail_server = os.environ.get("MAIL_SERVER", "smtp.qq.com")

    if not all([mail_user, mail_password, mail_recipient]):
        return

    styled_html = f"""
    <html><head><style>
        body {{ font-family: sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; }}
        .container {{ background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        h1, h2 {{ color: #1a73e8; border-bottom: 2px solid #eaeaea; padding-bottom: 10px; }}
        h3 {{ color: #2c3e50; margin-top: 0; }}
        .card {{ background: #ffffff; border: 1px solid #e0e0e0; border-left: 5px solid #1a73e8; border-radius: 6px; padding: 20px; margin-bottom: 25px; }}
        img {{ max-width: 100%; height: auto; border-radius: 6px; margin: 10px 0; }}
        a {{ color: #1a73e8; text-decoration: none; font-weight: bold; }}
        .meta {{ color: #888; font-size: 0.9em; margin-bottom: 15px; }}
    </style></head><body><div class="container">{html_content}</div></body></html>
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
# 5. 抓取逻辑 (去掉了时间限制，直接拉取最新)
# ==========================================
def fetch_unread_rss(feed_urls, history_urls):
    print(f"📡 正在扫描技术源（忽略已发过的文章）...")
    recent_items = []
    
    for url in feed_urls:
        try:
            feed = feedparser.parse(url)
            source_name = feed.feed.title if hasattr(feed.feed, 'title') else "技术专栏"
            
            # 每个源只看最新的 10 篇，防止历史积压太多
            for entry in feed.entries[:10]:
                if entry.link in history_urls:
                    continue # 如果在历史记录里，直接跳过
                
                recent_items.append({
                    "title": entry.title,
                    "url": entry.link,
                    "source": source_name,
                    "pub_date": datetime.now() # 统一给个当前时间用于排序
                })
        except Exception as e:
            print(f"解析 {url} 失败: {e}")
            
    # 为了防止总是优先看某一个源，把所有源打乱
    import random
    random.shuffle(recent_items)
    print(f"✅ 扫描完毕，共发现 {len(recent_items)} 篇从未发过的新文章。")
    return recent_items

# ==========================================
# 6. 穿透抓取正文
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
# 7. AI 知识整理引擎 (大幅放宽判定条件)
# ==========================================
def analyze_with_ai(title, url, content, source_name):
    prompt = f"""
    你是一位资深的计算机体系结构与底层硬件专家。
    请阅读这篇技术文章：
    【标题】：{title}
    【正文】：{content}
    
    【绝对判定准则】
    只要文章涉及以下任何领域（PCIe / GPU / 通信网络 / 芯片架构 / 半导体 / 服务器系统），**哪怕只是沾边或基础概念**，都请**务必输出卡片**。
    只有当文章是纯前端开发、纯后端业务逻辑、社会新闻、娱乐八卦时，才回复“无效资讯”。
    
    【输出格式要求】
    请**直接输出 HTML 代码片段**（不要用 ``` 包裹，直接以 <h3> 开头）。
    <h3>📖 {title}</h3>
    <p class="meta">🔗 原文链接：<a href="{url}" target="_blank">{url}</a></p>
    <p><b>【所属门类】</b>：从（PCIe / GPU互联 / 通信库 / GPU芯片 / PCIe Switch / CXL / 其他硬件）中选一个。</p>
    <p><b>【核心概念】</b>：用一两段话解释文章涉及的核心技术点。</p>
    <p><b>【原理解析】</b>：详细拆解技术原理。若有图，插入 <img src="图片URL">。</p>
    <p><b>【重点笔记】</b>：</p><ul><li>要点1</li><li>要点2</li></ul>
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
# 8. 流水线控制
# ==========================================
def process_news_pipeline(news_list, section_title, limit=2, max_evaluate=10):
    report_text = f"<h2>{section_title}</h2>"
    valid_count = 0
    evaluated_count = 0
    success_urls = [] # 记录今天成功发了哪些链接
    
    for item in news_list:
        if valid_count >= limit or evaluated_count >= max_evaluate:
            break
            
        print(f"🧐 评估文章: {item['title'][:30]}...")
        full_text = extract_full_text(item['url'])
        
        if not full_text:
            print(f"   ⚠️ 丢弃原因: 抓取正文失败")
            continue
            
        evaluated_count += 1 
        time.sleep(1) 
        analysis = analyze_with_ai(item['title'], item['url'], full_text, item['source'])
        
        if "无效资讯" not in analysis and "<h3>" in analysis:
            valid_count += 1
            success_urls.append(item['url']) # 记录成功的URL
            report_text += f"<div class='card'>\n{analysis}\n</div>\n"
            print(f"   ✅ 成功收录！")
        else:
            print(f"   ❌ 丢弃: 纯软件或新闻")
            
    if valid_count == 0:
        report_text += "<div class='card'><p>🛡️ 本期暂无符合门类的文章。</p></div>"
    return report_text, success_urls

# ==========================================
# 9. 执行入口
# ==========================================
if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 加载历史记录
    history_urls = load_history()
    
    # 抓取未读文章 (每个源最多拉10篇，打乱顺序)
    raw_domestic = fetch_unread_rss(DOMESTIC_FEEDS, history_urls) 
    raw_intl = fetch_unread_rss(INTL_FEEDS, history_urls)
    
    final_html = f"<h1>{REPORT_TITLE}</h1>"
    final_html += f"<p><b>生成日期：</b>{today_str}</p><hr>"
    
    # 国内尝试10篇，找2篇；海外尝试5篇，找1篇
    html_dom, success_dom = process_news_pipeline(raw_domestic, "📌 国内技术深度解析", limit=10, max_evaluate=10)
    html_intl, success_intl = process_news_pipeline(raw_intl, "🌐 海外硬核架构剖析", limit=5, max_evaluate=5)
    
    final_html += html_dom
    final_html += html_intl
    
    # 保存今天成功发送的URL到历史文件
    all_success = success_dom + success_intl
    if all_success:
        save_history(all_success)
        print(f"💾 已将 {len(all_success)} 篇文章保存至历史记录。")
    
    email_subject = f"【每日技术精读】{today_str} - 底层架构知识"
    send_email(email_subject, final_html)
    print("🎉 每日学习任务执行完毕！")
