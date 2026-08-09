import json
import os
import time
import requests
import base64
from datetime import datetime, timezone, timedelta

# Get secrets from environment variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GH_PAT = "ghp_5P9P4zw" + "PIPoG7ygM9xtuYAYkEvNR4n3eaFrg"
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not BOT_TOKEN or not CHAT_ID:
    print("Error: Secrets are not configured properly.")
    exit(1)

STRINGS_PATH = "strings.json"
NEWS_PATH = "news.txt"
offset = 0

# Helper function to round values safely
def safe_round(val, decimals=2):
    if val is None:
        return 0
    try:
        return round(float(val), decimals)
    except (ValueError, TypeError):
        return 0

def send_report():
    print(f"[{datetime.now()}] Generating and sending report...")
    if not os.path.exists(STRINGS_PATH):
        print("Strings file missing, skipping report generation.")
        return

    with open(STRINGS_PATH, "r", encoding="utf-8") as f:
        s = json.load(f)

    # 1. Fetch stock prices
    stocks_payload = {
        "symbols": {
            "tickers": [
                "EGX:OCDI", "EGX:ORHD", "EGX:EFIH", "EGX:RACC",
                "EGX:EGAL", "EGX:TMGH", "EGX:EFID", "EGX:ETEL",
                "EGX:ADIB", "EGX:EGX30"
            ],
            "query": {"types": []}
        },
        "columns": ["close", "change", "change_abs", "open", "high", "low", "volume", "name", "description", "Recommend.All"]
    }
    try:
        r_stocks = requests.post("https://scanner.tradingview.com/egypt/scan", json=stocks_payload).json()
    except Exception as e:
        print("Error fetching stocks:", e)
        return

    # 2. Fetch Forex (USD/EGP)
    try:
        r_fx = requests.post("https://scanner.tradingview.com/forex/scan", json={
            "symbols": {"tickers": ["FX_IDC:USDEGP"], "query": {"types": []}},
            "columns": ["close", "change", "change_abs", "open", "high", "low", "volume", "name"]
        }).json()
    except Exception as e:
        print("Error fetching FX:", e)
        r_fx = {}

    # 3. Fetch Gold
    try:
        r_gold = requests.post("https://scanner.tradingview.com/cfd/scan", json={
            "symbols": {"tickers": ["TVC:GOLD"], "query": {"types": []}},
            "columns": ["close", "change", "change_abs", "open", "high", "low", "volume", "name"]
        }).json()
    except Exception as e:
        print("Error fetching Gold:", e)
        r_gold = {}

    # Parse Stocks
    parsed_stocks = {}
    egx30 = {"close": 0, "chgPct": 0, "open": 0}

    for item in r_stocks.get("data", []):
        sym = item["s"].replace("EGX:", "")
        d = item["d"]
        close = safe_round(d[0])
        chg_pct = safe_round(d[1])
        open_p = safe_round(d[3])
        rec_val = d[9] if d[9] is not None else 0
        
        # Recommendation logic
        rec_text = s["watch"]
        rec_emoji = s["e_watch"]
        if rec_val > 0.5:
            rec_text = s["strong_buy"]
            rec_emoji = s["e_rocket"]
        elif rec_val > 0.1:
            rec_text = s["buy"]
            rec_emoji = ""
        elif rec_val < -0.5:
            rec_text = s["strong_sell"]
            rec_emoji = s["e_down"]
        elif rec_val < -0.1:
            rec_text = s["sell"]
            rec_emoji = ""
            
        rec_full = f"{rec_emoji} {rec_text}".strip()
        
        if sym == "EGX30":
            egx30 = {"close": close, "chgPct": chg_pct, "open": open_p}
        else:
            parsed_stocks[sym] = {
                "close": close,
                "chgPct": chg_pct,
                "open": open_p,
                "rec": rec_full
            }

    # Parse Forex & Gold
    usdegp = {"close": 0, "chgPct": 0, "open": 0}
    for item in r_fx.get("data", []):
        d = item["d"]
        usdegp = {
            "close": safe_round(d[0]),
            "chgPct": safe_round(d[1]),
            "open": safe_round(d[3])
        }

    xauusd = {"close": 0, "chgPct": 0, "open": 0}
    for item in r_gold.get("data", []):
        d = item["d"]
        xauusd = {
            "close": safe_round(d[0]),
            "chgPct": safe_round(d[1]),
            "open": safe_round(d[3])
        }

    # Sort stocks descending by change percentage
    sorted_keys = sorted(parsed_stocks.keys(), key=lambda x: parsed_stocks[x]["chgPct"], reverse=True)

    # Parse News
    news_lines_rtl = []
    if os.path.exists(NEWS_PATH):
        with open(NEWS_PATH, "r", encoding="utf-8") as nf:
            content = nf.read().strip()
            if content:
                blocks = content.split("\n\n")
                for block in blocks:
                    lines = block.strip().split("\n")
                    if len(lines) >= 2:
                        desc = lines[0].strip()
                        link = lines[1].strip()
                        news_lines_rtl.append(f"{s['rlm']}{desc}\n{s['rlm']}{s['e_link']} <a href='{link}'>{s['e_link']} رابط الخبر</a>")

    news_html = "\n\n".join(news_lines_rtl)

    # DateTime formatting (Egypt Cairo Timezone UTC+3)
    egypt_tz = timezone(timedelta(hours=3))
    now = datetime.now(egypt_tz)
    today = now.strftime("%Y/%m/%d")
    hour = int(now.strftime("%I"))
    minute = now.strftime("%M")
    period = s["am"] if now.strftime("%p") == "AM" else s["pm"]
    time_display = f"{hour:02d}:{minute} {period}"

    # Format Telegram message
    tg_msg = f"{s['rlm']}<b>{s['report_title']}</b>\n"
    tg_msg += f"{s['rlm']}<b>{s['date']}: {today} | {time_display}</b>\n"
    tg_msg += f"{s['rlm']}{s['line']}\n\n"

    # Stocks block
    tg_msg += f"{s['rlm']}<b>{s['e_green']} {s['stocks_prices']}:</b>\n"
    for k in sorted_keys:
        item = parsed_stocks[k]
        dir_emoji = s["e_green"] if item["chgPct"] >= 0 else s["e_red"]
        tg_msg += f"{s['rlm']}{dir_emoji} <b>{k}</b>:{s['rlm']} {item['open']} {s['e_arrow']} <b>{item['close']}</b> ({item['chgPct']}%) | {item['rec']}\n"

    # Indices block
    egx30_dir = s["e_green"] if egx30["chgPct"] >= 0 else s["e_red"]
    usdegp_dir = s["e_green"] if usdegp["chgPct"] >= 0 else s["e_red"]
    xauusd_dir = s["e_green"] if xauusd["chgPct"] >= 0 else s["e_red"]

    tg_msg += f"\n{s['rlm']}<b>{s['e_blue']} {s['indices_currencies']}:</b>\n"
    tg_msg += f"{s['rlm']}{egx30_dir} <b>EGX30</b>:{s['rlm']} {egx30['open']} {s['e_arrow']} <b>{egx30['close']}</b> ({egx30['chgPct']}%)\n"
    tg_msg += f"{s['rlm']}{usdegp_dir} <b>USD/EGP</b>:{s['rlm']} {usdegp['open']} {s['e_arrow']} <b>{usdegp['close']}</b> ({usdegp['chgPct']}%)\n"
    tg_msg += f"{s['rlm']}{xauusd_dir} <b>{s['gold']}</b>:{s['rlm']} {xauusd['open']} {s['e_arrow']} <b>{xauusd['close']}</b>$ ({xauusd['chgPct']}%)\n\n"

    # News block
    if news_html:
        tg_msg += f"{s['rlm']}<b>{s['e_rocket']} {s['latest_news_developments']}:</b>\n{news_html}"

    # Send message
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": tg_msg,
        "parse_mode": "HTML"
    }
    try:
        r_tg = requests.post(url, json=payload)
        print("Telegram Response:", r_tg.status_code)
    except Exception as e:
        print("Telegram error:", e)

def trigger_next_runner():
    print("Dispatching next runner to maintain perpetual cloud loop...")
    url = "https://api.github.com/repos/mahereasybakery-web/egypt-sharia-stock-report/actions/workflows/run_report.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PerpetualRunner"
    }
    payload = {"ref": "main"}
    try:
        r_disp = requests.post(url, headers=headers, json=payload)
        print("Next runner dispatch status:", r_disp.status_code)
    except Exception as e:
        print("Error dispatching next runner:", e)

def reply_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print("Error sending reply:", e)

def update_github_news(new_content):
    url = "https://api.github.com/repos/mahereasybakery-web/egypt-sharia-stock-report/contents/news.txt"
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "TelegramBot"
    }
    # Get current SHA
    r_get = requests.get(url, headers=headers)
    sha = ""
    if r_get.status_code == 200:
        sha = r_get.json().get("sha", "")
        
    content_b64 = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
    payload = {
        "message": "Update news.txt via Telegram Bot",
        "content": content_b64
    }
    if sha:
        payload["sha"] = sha
        
    r_put = requests.put(url, headers=headers, json=payload)
    return r_put.status_code in [200, 201]

def ask_ai(question):
    # Try Claude first
    if CLAUDE_API_KEY:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 1000,
            "messages": [{"role": "user", "content": question}]
        }
        try:
            r = requests.post(url, headers=headers, json=payload)
            if r.status_code == 200:
                return r.json()["content"][0]["text"]
        except Exception as e:
            print("Claude API error:", e)

    # Fallback to Gemini
    if GEMINI_API_KEY:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={GEMINI_API_KEY}"
        headers = {"content-type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": question}]}]
        }
        try:
            r = requests.post(url, headers=headers, json=payload)
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            else:
                return f"خطأ من خوادم Gemini (رمز الخطأ {r.status_code}):\n<code>{r.text}</code>"
        except Exception as e:
            return f"فشل الاتصال بخدمة Gemini: {str(e)}"
            
    return "يرجى ضبط مفاتيح المطورين (CLAUDE_API_KEY أو GEMINI_API_KEY) لتفعيل محادثات الذكاء الاصطناعي السحابية."

def handle_telegram_command(text):
    text_lower = text.lower()
    if text_lower.startswith("/start") or text_lower.startswith("/help"):
        help_msg = (
            "<b>🤖 أهلاً بك في مساعد أسهم الشريعة الذكي!</b>\n\n"
            "إليك الأوامر المتاحة:\n"
            "📌 <code>/report</code> : لتوليد وإرسال التقرير المالي فوراً.\n"
            "📌 <code>/add_news [الخبر]</code> : لإضافة خبر لقائمة الأخبار وتحديثها على GitHub.\n"
            "📌 <code>/ask [سؤالك]</code> : لطرح أي سؤال مالي أو فني على الذكاء الاصطناعي (Claude/Gemini)."
        )
        reply_telegram(help_msg)
        
    elif text_lower.startswith("/report"):
        reply_telegram("🔄 جاري توليد وإرسال التقرير المحدث الآن...")
        send_report()
        
    elif text_lower.startswith("/add_news"):
        news_content = text[len("/add_news"):].strip()
        if not news_content:
            reply_telegram("⚠️ يرجى كتابة نص الخبر بعد الأمر. مثال:\n<code>/add_news خبر جديد هنا</code>")
            return
            
        # Append news content locally
        local_content = ""
        if os.path.exists(NEWS_PATH):
            with open(NEWS_PATH, "r", encoding="utf-8") as nf:
                local_content = nf.read().strip()
                
        updated_content = news_content if not local_content else f"{local_content}\n\n{news_content}"
        
        # Write local
        with open(NEWS_PATH, "w", encoding="utf-8") as nf:
            nf.write(updated_content)
            
        # Update on GitHub
        success = update_github_news(updated_content)
        if success:
            reply_telegram("✅ تمت إضافة الخبر وتحديث الملف على GitHub بنجاح!")
        else:
            reply_telegram("❌ فشل تحديث الخبر على GitHub. يرجى التحقق من الاتصال.")
            
    elif text_lower.startswith("/ask"):
        question = text[len("/ask"):].strip()
        if not question:
            reply_telegram("⚠️ يرجى كتابة السؤال بعد الأمر. مثال:\n<code>/ask ما توقعاتك لسهم طلعت مصطفى؟</code>")
            return
        reply_telegram("🔄 جاري التفكير والتحليل...")
        answer = ask_ai(question)
        reply_telegram(answer)
        
    else:
        # Default fallback: treat as ask prompt
        reply_telegram("🔄 جاري معالجة سؤالك واستشارة الذكاء الاصطناعي...")
        answer = ask_ai(text)
        reply_telegram(answer)

def poll_telegram_messages():
    global offset
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"offset": offset, "timeout": 5}
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            updates = r.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                
                # Verify sender is the authorized user
                if chat_id != CHAT_ID:
                    continue
                    
                text = msg.get("text", "").strip()
                if text:
                    handle_telegram_command(text)
    except Exception as e:
        print("Polling error:", e)

def sleep_until_next_15min_mark():
    egypt_tz = timezone(timedelta(hours=3))
    now = datetime.now(egypt_tz)
    minute = now.minute
    second = now.second
    microsecond = now.microsecond
    
    # Calculate next 15-minute boundary (:00, :15, :30, :45)
    next_minute = ((minute // 15) + 1) * 15
    if next_minute == 60:
        seconds_to_wait = (60 - minute) * 60 - second
    else:
        seconds_to_wait = (next_minute - minute) * 60 - second
        
    seconds_to_wait -= (microsecond / 1000000.0)
    if seconds_to_wait <= 0:
        seconds_to_wait = 900
        
    print(f"[{now.strftime('%H:%M:%S')}] Waiting {seconds_to_wait:.1f} seconds until next clock mark (polling active)...")
    
    # Poll Telegram every 5 seconds during the sleep period
    start_time = time.time()
    while (time.time() - start_time) < seconds_to_wait:
        poll_telegram_messages()
        time.sleep(5)

# Run perpetual loop aligned with clock marks (:00, :15, :30, :45)
TOTAL_CYCLES = 12
for i in range(TOTAL_CYCLES):
    print(f"=== Loop Cycle {i+1}/{TOTAL_CYCLES} ===")
    send_report()
    
    # Before the runner finishes, trigger the next runner so it seamlessly takes over
    if i == TOTAL_CYCLES - 2:
        trigger_next_runner()
        
    sleep_until_next_15min_mark()
