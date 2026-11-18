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
# 1. 核心环境配置 (API 密钥)
# ==========================================
# 📢 [请确认 GitHub Secrets 已配置]：
# DEEPSEEK_API_KEY (填入魔搭的 Token)
# MAIL_USER (你的QQ邮箱)
# MAIL_PASSWORD (QQ邮箱授权码)
# MAIL_RECIPIENT (接收邮箱)
# MAIL_SERVER (smtp.qq.com)

API_KEY = os.environ.get("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    raise ValueError("DEEPSEEK_API_KEY 环境变量为空，请检查 GitHub Secrets 和 daily.yml 的 env 配置")
# ⚠️ 这里已改为魔搭社区的 Base URL
client = OpenAI(
    api_key=API_KEY,
    base_url="https://api-inference.modelscope.cn/v1"
)

# ==========================================
# 2. 信息源矩阵 (RSS 订阅源)
# ==========================================
# 📢 这里填入你在 WeRSS 中获取的公众号聚合链接
DOMESTIC_FEEDS = [
    "http://你的WeRSS公网IP:8001/feed/all.rss" # 请替换为你的真实 WeRSS 链接
]

# 国际源保留了技术类和学术类，为你提供全球视野
INTL_FEEDS = [
    "https://hnrss.org/frontpage",                      
    "https://www.anandtech.com/rss/"
]

# 📢 修改了报告标题
REPORT_TITLE = "🧠 AI硬件每日知识汇总"
REPORT_SUBTITLE = "覆盖：PCIe / GPU互联 / 通信库 / GPU芯片 / PCIe Switch / CXL"

# ==========================================
# 3. 邮件发送函数
# ==========================================
def send_email(subject, content):
    mail_user = os.environ.get("MAIL_USER")
    mail_password = os.environ.get("MAIL_PASSWORD")
    mail_recipient = os.environ.get("MAIL_RECIPIENT")
    mail_server = os.environ.get("MAIL_SERVER", "smtp.qq.com")

    if not all([mail_user, mail_password, mail_recipient]):
        print("错误：邮箱配置不完整，请检查 GitHub Secrets。")
        return

    msg = MIMEMultipart()
    msg["From"] = mail_user
    msg["To"] = mail_recipient
    msg["Subject"] = subject
    # ⚠️ 这里使用 plain 纯文本格式，防止邮件里出现 Markdown 乱码符号
    msg.attach(MIMEText(content, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL(mail_server, 465) as server:
            server.login(mail_user, mail_password)
            server.sendmail(mail_user, mail_recipient, msg.as_string())
        print("✅ 邮件发送成功！")
    except Exception as e:
        print(f"❌ 邮件发送失败：{e}")

# ==========================================
# 4. 抓取近期更新的 RSS 文章 (改为了 1 天)
# ==========================================
def fetch_recent_rss(feed_urls, days_limit=1):
    print(f"📡 正在扫描订阅源，严格筛选过去 {days_limit} 天内的文章...")
    recent_items = []
    limit_date = datetime.now() - timedelta(days=days_limit)
    
    for url in feed_urls:
        try:
            feed = feedparser.parse(url)
            source_name = feed.feed.title if hasattr(feed.feed, 'title') else "精选智库"
            
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
    print(f"✅ 扫描完毕，共发现 {len(recent_items)} 篇 24 小时内的新鲜文章。")
    return recent_items

# ==========================================
# 5. Jina 穿透抓取正文
# ==========================================
def extract_full_text(url):
    jina_url = f"https://r.jina.ai/{url}"
    try:
        response = requests.get(jina_url, timeout=15)
        if response.status_code == 200:
            text = response.text
            if len(text) > 200 and "Access Denied" not in text:
                return text[:3800] 
    except Exception:
        pass
    return "抓取正文受限，请基于标题和摘要进行研判。"

# ==========================================
# 6. 大模型深度剖析 (已改为魔搭模型 + 六大分类)
# ==========================================
def analyze_with_ai(title, content, source_name):
    # ⚠️ 修改了 Prompt，强制 AI 进行门类划分
    prompt = f"""
    你是一位资深的 AI 硬件与底层架构专家。
    请审读这篇来自【{source_name}】的最新资讯：
    【标题】：{title}
    【正文/摘要】：{content}
    
    【判定准则】
    1. 如果该内容与 AI 硬件、底层架构完全无关（如纯消费电子产品、社会新闻），请仅回复“无效资讯”。
    2. 如果有价值，请严格按以下结构输出纯文本简报（不要使用 Markdown 语法，用纯文字排版）：

    【所属门类】：（必须从以下六个中选一个最贴切的：PCIe / GPU互联 / 通信库 / GPU芯片 / PCIe Switch / CXL）
    【核心提要】：用 1-2 句话极简概括这篇资讯的核心事实。
    【深度洞察】：分析该事件背后的底层逻辑、技术难点或行业趋势。
    【行动启发】：给读者提供一个具体的思考角度或学习建议。
    """
    try:
        # ⚠️ 这里替换为魔搭的模型名称
        response = client.chat.completions.create(
            model="deepseek-ai/DeepSeek-V4.1-Flash-1017", 
            messages=[
                {"role": "system", "content": "你是一个专注 AI 硬件与底层架构的顶级知识助理。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"API调用出错: {e}")
        return "无效资讯"

# ==========================================
# 7. 流水线核心逻辑
# ==========================================
def process_news_pipeline(news_list, section_title, limit=None):
    report_text = f"\n========================================\n{section_title}\n========================================\n\n"
    valid_count = 0
    
    for item in news_list:
        if limit is not None and valid_count >= limit:
            print(f"🛑 {section_title} 已达到 {limit} 篇上限，停止分析。")
            break
            
        print(f"🧐 评估文章: {item['title'][:30]}... (发布于 {item['pub_date'].strftime('%m-%d')})")
        full_text = extract_full_text(item['url'])
        time.sleep(1.5) 
        
        analysis = analyze_with_ai(item['title'], full_text, item['source'])
        
        if "无效资讯" not in analysis:
            valid_count += 1
            report_text += f"{valid_count}. {item['title']}\n"
            report_text += f"原文链接：{item['url']}\n"
            report_text += f"{analysis}\n\n----------------------------------------\n\n"
            
    if valid_count == 0:
        report_text += "> 🛡️ 本周期内暂无符合价值研判标准的新鲜动态。\n\n----------------------------------------\n\n"
    return report_text

# ==========================================
# 8. 执行与邮件推送
# ==========================================
if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    raw_domestic = fetch_recent_rss(DOMESTIC_FEEDS)
    raw_intl = fetch_recent_rss(INTL_FEEDS)
    
    final_report = f"{REPORT_TITLE}\n\n"
    final_report += f"生成日期：{today_str}\n"
    final_report += f"订阅说明：{REPORT_SUBTITLE}\n\n"
    
    # 国内最多 10 篇，国际最多 5 篇（因为每天更新，不需要太多，防止邮件太长）
    final_report += process_news_pipeline(raw_domestic, "【国内精选动态】", limit=10)
    final_report += process_news_pipeline(raw_intl, "【海外视野观察】", limit=5)
    
    # 调用发邮件函数
    email_subject = f"【每日汇总】{today_str} - AI硬件系统知识"
    send_email(email_subject, final_report)
    print("🎉 每日汇总任务执行完毕！")
