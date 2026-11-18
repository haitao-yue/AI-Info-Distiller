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
# 2. 信息源矩阵：替换为高质量技术知识源
# ==========================================
# 📢 [用户自定义区]：请将这里替换为你收集的优质公众号/专栏 RSS 链接！
# 建议：不要放新闻号，放“修芯验证”、“AI系统”这种写深度长文的账号。
DOMESTIC_FEEDS = [
    # 示例：你的 WeRSS 公众号聚合源
    # "http://你的公网IP:8001/feed/all.rss" 
    
    # 示例：CSDN 优质专栏的 RSS (需要你去找对应的 RSS 生成器)
    # "https://rsshub.app/csdn/blog/你的博主ID"
]

# 📢 [用户自定义区]：海外深度技术源（这里保留了极客深度博客，去掉了快速新闻源）
INTL_FEEDS = [
    "https://www.anandtech.com/rss/",                 # AnandTech (深度硬件评测)
    "https://chipsandcheese.com/feed/"                # Chips and Cheese (极其硬核的芯片架构分析)
]

REPORT_TITLE = "📚 AI 硬件系统知识精讲"
REPORT_SUBTITLE = "覆盖：PCIe / GPU互联 / 通信库 / GPU芯片 / PCIe Switch / CXL"

# ==========================================
# 3. 邮件发送函数 (保持不变)
# ==========================================
def send_email(subject, content):
    mail_user = os.environ.get("MAIL_USER")
    mail_password = os.environ.get("MAIL_PASSWORD")
    mail_recipient = os.environ.get("MAIL_RECIPIENT")
    mail_server = os.environ.get("MAIL_SERVER", "smtp.qq.com")

    if not all([mail_user, mail_password, mail_recipient]):
        print("错误：邮箱配置不完整。")
        return

    msg = MIMEMultipart()
    msg["From"] = mail_user
    msg["To"] = mail_recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(content, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL(mail_server, 465) as server:
            server.login(mail_user, mail_password)
            server.sendmail(mail_user, mail_recipient, msg.as_string())
        print("✅ 邮件发送成功！")
    except Exception as e:
        print(f"❌ 邮件发送失败：{e}")

# ==========================================
# 4. 抓取逻辑：放宽时间限制，重点抓取长文
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
                        # 💡 过滤掉极短的新闻，只保留长文（如果是 RSS 提供 summary 的话）
                        summary = entry.get("summary", "")
                        # 如果摘要字数太少，可能只是一条新闻，直接跳过（可选策略）
                        # if len(summary) < 100: continue 
                        
                        recent_items.append({
                            "title": entry.title,
                            "url": entry.link,
                            "summary": summary,
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
    jina_url = f"https://r.jina.ai/{url}"
    try:
        response = requests.get(jina_url, timeout=20)
        if response.status_code == 200:
            text = response.text
            if len(text) > 200 and "Access Denied" not in text:
                return text[:6000] # 增加读取字数上限，保证长文能被读到
    except Exception:
        pass
    return "抓取正文受限。"

# ==========================================
# 6. 核心 AI 引擎：改为“知识整理专家”
# ==========================================
def analyze_with_ai(title, content, source_name):
    # ⚠️ 彻底重写了 Prompt，强制 AI 按教材的逻辑去拆解知识点
    prompt = f"""
    你是一位资深的计算机体系结构与底层硬件专家。你的任务不是播报新闻，而是将技术文章转化为系统性的学习笔记。
    请阅读这篇来自【{source_name}】的技术文章：
    【标题】：{title}
    【正文】：{content}
    
    【判定准则】
    如果内容与底层硬件、AI 算力架构、系统通信完全无关（如纯软件应用、社会新闻），请仅回复“无效资讯”。
    如果有价值，请按以下“知识卡片”结构，提取该文章的硬核知识：

    【所属门类】：（必须从以下六个中选一个：PCIe / GPU互联 / 通信库 / GPU芯片 / PCIe Switch / CXL）
    【核心概念】：这篇文章主要解释了哪些核心概念或技术机制？（如 TLP、LTSSM、NVLink 拓扑等）
    【原理解析】：用通俗但严谨的语言，解释这些技术是如何工作的？（如果涉及流程或架构，请一步步拆解说明）
    【重点笔记】：提炼文章中 2-3 个最值得记住的关键细节、参数或架构设计考量。
    """
    try:
        response = client.chat.completions.create(
            model="deepseek-ai/DeepSeek-V4.1-Flash-1017", 
            messages=[
                {"role": "system", "content": "你是一个擅长将复杂技术拆解为结构化笔记的系统架构师。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"API调用出错: {e}")
        return "无效资讯"

# ==========================================
# 7. 流水线核心逻辑
# ==========================================
def process_news_pipeline(news_list, section_title, limit=3):
    report_text = f"\n========================================\n{section_title}\n========================================\n\n"
    valid_count = 0
    
    for item in news_list:
        if valid_count >= limit:
            print(f"🛑 {section_title} 已达到 {limit} 篇上限，停止分析。")
            break
            
        print(f"🧐 评估文章: {item['title'][:30]}...")
        full_text = extract_full_text(item['url'])
        time.sleep(2) # 防止请求过快
        
        analysis = analyze_with_ai(item['title'], full_text, item['source'])
        
        if "无效资讯" not in analysis:
            valid_count += 1
            report_text += f"📖 《{item['title']}》\n"
            report_text += f"🔗 原文链接：{item['url']}\n"
            report_text += f"{analysis}\n\n----------------------------------------\n\n"
            
    if valid_count == 0:
        report_text += "> 🛡️ 本期未抓取到符合要求的系统性深度文章。\n\n"
    return report_text

# ==========================================
# 8. 执行与推送
# ==========================================
if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 建议把 days_limit 设长一点，因为高质量技术长文更新没那么频繁
    raw_domestic = fetch_recent_rss(DOMESTIC_FEEDS, days_limit=3) 
    raw_intl = fetch_recent_rss(INTL_FEEDS, days_limit=3)
    
    final_report = f"{REPORT_TITLE}\n\n"
    final_report += f"生成日期：{today_str}\n"
    final_report += f"知识体系：{REPORT_SUBTITLE}\n\n"
    
    # 💡 每天精读的篇数：国内 2 篇，国际 1 篇（每天读 3 篇深度长文，足够了）
    final_report += process_news_pipeline(raw_domestic, "【国内技术深度解析】", limit=2)
    final_report += process_news_pipeline(raw_intl, "【海外硬核架构剖析】", limit=1)
    
    email_subject = f"【每日技术精读】{today_str} - 底层架构知识"
    send_email(email_subject, final_report)
    print("🎉 每日学习任务执行完毕！")
