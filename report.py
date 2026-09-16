import os
import sys
import time
import json
import base64
import re
import urllib.parse
from urllib.parse import urljoin
import xml.etree.ElementTree as ET
import hashlib
import urllib3
from datetime import datetime, timezone, timedelta
import requests

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Try importing feedparser safely
try:
    import feedparser
except ImportError:
    feedparser = None
    print("Warning: feedparser is not installed globally.")

# Environment secrets — all loaded from GitHub Secrets (no hardcoded fallbacks)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GH_PAT = os.getenv("GH_PAT")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-3.5-flash"

if not GH_PAT:
    if os.getenv("GITHUB_ACTIONS") == "true":
        print("FATAL: GH_PAT secret not set in GitHub Actions. Exiting.")
        sys.exit(1)
    else:
        print("Warning: GH_PAT not set. Loop chaining and news updates to GitHub will be disabled.")

# ✅ إضافة: فحص BOT_TOKEN وCHAT_ID مبكراً بدل الفشل الصامت لاحقاً
if not BOT_TOKEN or not CHAT_ID:
    print("FATAL: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Exiting.")
    sys.exit(1)

# Configuration paths
STRINGS_PATH = "strings.json"
NEWS_PATH = "news.txt"
offset = 0

# تسجيل وقت بدء التشغيل لتجاهل الرسائل القديمة
_startup_epoch = 0  # سيُحدَّث في __main__

# Tickers definition
PORTFOLIO = ["ETEL", "TMGH", "EFIH", "EGAL", "ADIB", "ORHD", "OCDI", "EFID", "FWRY", "RACC"]
WATCHLIST = [
    "ORAS", "PHDC", "SKPC", "MCQE", "FAITA", "ISPH", "JUFO", "AMOC",
    "MASR", "ORWE", "RMDA", "OLFI", "ARCC", "FAIT", "IFAP", "MTIE",
    "SAUD", "ATQA", "CIRA", "EGAS", "MPCO", "ACGC", "ETRS", "LCSW", "ICFC"
]
ALL_TICKERS = PORTFOLIO + WATCHLIST

# Company websites mapping
COMPANY_WEBSITES = {
    "TMGH": "https://www.tmg-holding.com",
    "FWRY": "https://fawry.com",
    "EGAL": "http://www.egyptalum.com.eg",
    "ETEL": "https://ir.te.eg",
    "EFID": "https://www.edita.com.eg",
    "ADIB": "https://www.adib.eg",
    "ORHD": "https://www.orascomdevelopment.com",
    "EFIH": "https://www.efinanceinvestment.com",
    "OCDI": "https://sodic.com",
    "RACC": "https://rayacc.com",
    "ORAS": "https://orascom.com",
    "PHDC": "https://www.palmhillsdevelopments.com",
    "SKPC": "http://www.sidpec.com",
    "MCQE": "http://www.qenacement.com",
    "FAITA": "https://www.faisalbank.com.eg",
    "FAIT": "https://www.faisalbank.com.eg",
    "ISPH": "https://ibnsina-pharma.com",
    "JUFO": "https://www.juhayna.com",
    "AMOC": "http://www.amoc-eg.com",
    "MASR": "https://madinetmasr.com",
    "ORWE": "https://www.orientalweavers.com",
    "RMDA": "https://www.rameda.com",
    "OLFI": "https://www.obourland.com",
    "ARCC": "https://www.arabiancement.com",
    "IFAP": "http://www.iac-eg.com",
    "MTIE": "http://www.mti-egypt.com",
    "SAUD": "https://www.albaraka.com.eg",
    "ATQA": "http://misrnationalsteel.com",
    "CIRA": "https://cira.com.eg",
    "EGAS": "http://www.egyptgas.com.eg",
    "MPCO": "http://www.manspoultry.com",
    "ACGC": "http://www.acgc-egypt.com",
    "ETRS": "https://www.egytrans.com",
    "LCSW": "https://www.lecico.com",
    "ICFC": "http://www.icf-eg.com"
}

# Arabic stock company names for clear RTL display
COMPANY_NAMES_AR = {
    # المحفظة (Portfolio)
    "ETEL": "المصرية للاتصالات",
    "TMGH": "طلعت مصطفى",
    "EFIH": "إي فاينانس",
    "EGAL": "مصر للألومنيوم",
    "ADIB": "أبوظبي الإسلامي",
    "ORHD": "أوراسكوم للتنمية",
    "OCDI": "سوديك",
    "EFID": "إيديتا",
    "FWRY": "فوري",
    "RACC": "راية مراكز",
    # قائمة المتابعة (Watchlist)
    "ORAS": "أوراسكوم للإنشاء",
    "PHDC": "بالم هيلز",
    "SKPC": "سيدي كرير",
    "MCQE": "أسمنت قنا",
    "FAITA": "فيصل (دولار)",
    "FAIT": "فيصل (جنيه)",
    "ISPH": "ابن سينا",
    "JUFO": "جهينة",
    "AMOC": "أموك",
    "MASR": "مدينة مصر",
    "ORWE": "النساجون",
    "RMDA": "راميدا",
    "OLFI": "عبور لاند",
    "ARCC": "العربية للأسمنت",
    "IFAP": "الدولية للمحاصيل",
    "MTIE": "إم إم جروب",
    "SAUD": "بنك البركة",
    "ATQA": "حديد عتاقة",
    "CIRA": "سيرا للتعليم",
    "EGAS": "غاز مصر",
    "MPCO": "المنصورة للدواجن",
    "ACGC": "العربية للأقطان",
    "ETRS": "إيجيترانس",
    "LCSW": "ليسيكو مصر",
    "ICFC": "الدولية للأسمدة"
}

# Stock keywords for news filtering
STOCK_KEYWORDS = {
    "TMGH": ["طلعت مصطفى", "مجموعة طلعت مصطفى", "TMGH"],
    "ADIB": ["أبوظبي الإسلامي", "أبو ظبي الإسلامي", "مصرف أبوظبي الإسلامي", "ADIB"],
    "EFID": ["إيديتا", "ايديتا", "Edita", "EFID"],
    "RACC": ["راية مراكز", "راية لخدمات الاتصالات", "RACC"],
    "FWRY": ["شركة فوري", "منصة فوري", "فوري لتكنولوجيا", "فوري للمدفوعات", "سهم فوري", "خدمات فوري", "تطبيق فوري", "Fawry", "FWRY", "فوري"],
    "EGAL": ["مصر للألومنيوم", "مصر للالومنيوم", "EGAL"],
    "ETEL": ["المصرية للاتصالات", "المصريه للاتصالات", "شركة وي", "ETEL"],
    "ORHD": ["أوراسكوم للتنمية", "اوراسكوم للتنمية", "ORHD"],
    "EFIH": ["إي فاينانس", "اي فاينانس", "EFIH"],
    "OCDI": ["سوديك", "سودك", "OCDI"],
    "ORAS": ["أوراسكوم كونستراكشون", "اوراسكوم كونستراكشون", "أوراسكوم للإنشاء", "ORAS"],
    "PHDC": ["بالم هيلز", "PHDC"],
    "SKPC": ["سيدي كرير", "سيدبك", "SKPC"],
    "MCQE": ["أسمنت قنا", "اسمنت قنا", "MCQE"],
    "FAITA": ["فيصل الإسلامي", "فيصل الاسلامي", "FAITA"],
    "ISPH": ["ابن سينا فارما", "ابن سينا للأدوية", "ابن سينا", "ISPH"],
    "JUFO": ["جهينة للصناعات", "شركة جهينة", "جهينه", "JUFO"],
    "AMOC": ["أموك", "اموك", "الأسكندرية للزيوت المعدنية", "AMOC"],
    "MASR": ["مدينة مصر للإسكان", "شركة مدينة مصر", "مدينة مصر", "MASR"],
    "ORWE": ["النساجون الشرقيون", "النساجون", "ORWE"],
    "RMDA": ["العاشر من رمضان للأدوية", "راميدا", "RMDA"],
    "OLFI": ["عبور لاند", "عبورلاند", "OLFI"],
    "ARCC": ["العربية للأسمنت", "العربيه للأسمنت", "ARCC"],
    "FAIT": ["بنك فيصل", "FAIT"],
    "IFAP": ["الدولية للمحاصيل", "الدوليه للمحاصيل", "IFAP"],
    "MTIE": ["إم إم جروب", "ام ام جروب", "MTIE"],
    "SAUD": ["بنك البركة", "البركة مصر", "SAUD"],
    "ATQA": ["شركة عتاقة", "مصر الوطنية للصلب", "حديد عتاقة", "عتاقة", "عتاقه", "ATQA"],
    "CIRA": ["القاهرة للاستثمار", "سيرا للتعليم", "سيرا", "CIRA"],
    "EGAS": ["غاز مصر", "EGAS"],
    "MPCO": ["المنصورة للدواجن", "المنصوره للدواجن", "MPCO"],
    "ACGC": ["عربية لحليج الأقطان", "حليج الأقطان", "ACGC"],
    "ETRS": ["إيجيترانس", "ايجيترانس", "المصرية لخدمات النقل", "ETRS"],
    "LCSW": ["ليسيكو مصر", "ليسيكو", "LCSW"],
    "ICFC": ["الدولية للأسمدة", "الدوليه للأسمده", "ICFC"]
}

# ✅ كلمات مستبعدة خاصة بكل سهم لمنع الالتباس اللغوي والمشاهير
NEGATIVE_KEYWORDS = {
    "FWRY": [
        "كفوري", "وائل كفوري", "بشكل فوري", "تحقيق فوري", "إجراء فوري", "تدخل فوري",
        "حظر فوري", "إخلاء فوري", "إفراج فوري", "وقف فوري", "إنهاء فوري", "حل فوري",
        "رد فوري", "علاج فوري", "استجابة فورية", "معالجة فورية", "قرارا فوريا", "تدخلا فوريا",
        "إغلاق فوري", "تنفيذ فوري"
    ],
    "MASR": ["مدينة نصر", "نصر أكتوبر"],
    "SAUD": ["البركة فيكم", "على بركة الله", "حلت البركة"],
    "ISPH": ["مستشفى ابن سينا", "الفيلسوف ابن سينا", "العالم ابن سينا"],
    "JUFO": ["قبيلة جهينة"],
    "RACC": ["رفع راية", "راية بيضاء", "راية الاستسلام", "راية التوحيد"],
    "ETEL": ["ويجز", "ويليام", "تويتر"]
}

# ✅ قائمة استبعاد عامة للأخبار غير الاقتصادية (فنون، مشاهير، حفلات، رياضة، حوادث، جرائم)
GLOBAL_EXCLUDE_KEYWORDS = [
    "مغني", "مطرب", "مطربة", "فنان", "فنانة", "أغنية", "أغاني", "كليب", "ألبوم", 
    "حفل غنائي", "مهرجان سينمائي", "مسلسل", "فيلم", "دراما", "سينما", "ممثلة", "ممثل",
    "كرة قدم", "مباراة", "دوري", "كأس", "منتخب", "الزمالك", "الأهلي", "رياضة", "لاعب", "مدرب",
    "حادث سير", "جريمة", "مقتل", "انتحار", "إصابة شخص", "العثور على جثة", "تصادم قطار", 
    "النيابة العامة تأمر بحبس", "سرقة", "مشاجرة", "مصرع شخص", "سقوط من علو"
]

def safe_round(val, decimals=2):
    if val is None:
        return 0.0
    try:
        if isinstance(val, str):
            val = val.replace(",", "")
        return round(float(val), decimals)
    except (ValueError, TypeError):
        return 0.0

def escape_html(text):
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

DEFAULT_KEYBOARD = {
    "keyboard": [
        [{"text": "💼 محفظتي الاستثمارية"}, {"text": "📊 تقرير الأسعار"}],
        [{"text": "⚡ بيان مفصل RSI"}, {"text": "📌 ملخص حركة اليوم"}],
        [{"text": "⚙️ حالة النظام"}, {"text": "❓ مساعدة والأوامر"}]
    ],
    "resize_keyboard": True,
    "is_persistent": True
}

PORTFOLIO_INLINE_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "💼 محفظتي الاستثمارية (P&L)", "callback_data": "btn_portfolio"},
            {"text": "🔄 تحديث فوري", "callback_data": "btn_report"}
        ],
        [
            {"text": "⚡ بيان مفصل RSI", "callback_data": "btn_rsi"},
            {"text": "📌 ملخص الجلسة", "callback_data": "btn_summary"}
        ],
        [
            {"text": "⚙️ حالة النظام", "callback_data": "btn_status"}
        ]
    ]
}

def setup_telegram_bot_menu():
    """تسجيل قائمة الأوامر الرسمية لتظهر في زر Menu بتطبيق تليجرام تلقائياً."""
    if not BOT_TOKEN:
        return
    commands = [
        {"command": "portfolio", "description": "💼 كشف حساب المحفظة اللحظي والأرباح"},
        {"command": "report", "description": "📊 بث تقرير الأسعار والمؤشرات اللحظي"},
        {"command": "rsi", "description": "⚡ بيان مفصل لمؤشر RSI لجميع الأسهم"},
        {"command": "summary", "description": "📌 ملخص الجلسة والتحليل الفني"},
        {"command": "compare", "description": "⚖️ مقارنة فنية بين سهمين بالذكاء الاصطناعي"},
        {"command": "alert", "description": "🎯 ضبط تنبيه سعري فوري"},
        {"command": "ask", "description": "🧠 استشارة المحلل المالي الذكي"},
        {"command": "status", "description": "⚙️ حالة الخادم وسلسلة الترحيل 24/7"}
    ]
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands", json={"commands": commands}, timeout=10)
    except Exception as e:
        print("Warning setting bot commands menu:", e)

def ensure_rtl(text):
    """فرض اتجاه النص من اليمين لليسار (RTL) بشكل صارم على جميع أسطر رسائل تليجرام."""
    if not text:
        return text
    rlm = "\u200f"
    lines = text.split("\n")
    rtl_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            rtl_lines.append("")
        elif stripped.startswith(rlm):
            rtl_lines.append(line)
        else:
            rtl_lines.append(rlm + line)
    return "\n".join(rtl_lines)

def reply_telegram(text, reply_markup=None):
    """دالة موحدة لإرسال Telegram مع فحص status وإعادة محاولة بدون HTML عند 400، ودعم أزرار التحكم التفاعلية."""
    if not BOT_TOKEN or not CHAT_ID:
        return
    
    # فرض اتجاه النص من اليمين لليسار (RTL) دائماً
    text = ensure_rtl(text)
    
    # تقسيم الرسائل التي تتعدى 3800 حرف تلقائياً لضمان عدم تعطل الإرسال
    if len(text) > 3800:
        lines = text.split("\n")
        chunk = []
        chunk_len = 0
        for line in lines:
            if chunk_len + len(line) + 1 > 3800:
                reply_telegram("\n".join(chunk))
                chunk = [line]
                chunk_len = len(line)
            else:
                chunk.append(line)
                chunk_len += len(line) + 1
        if chunk:
            reply_telegram("\n".join(chunk), reply_markup=reply_markup)
        return

    markup = reply_markup if reply_markup is not None else DEFAULT_KEYBOARD

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": markup
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 400:
            # محاولة الإرسال بدون HTML في حال وجود وسوم مكسورة
            requests.post(url, json={
                "chat_id": CHAT_ID,
                "text": re.sub(r'<[^>]+>', '', text),
                "disable_web_page_preview": True,
                "reply_markup": markup
            }, timeout=15)
        elif r.status_code != 200:
            print(f"Telegram reply error {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print("Error sending telegram message:", e)

def trigger_next_runner():
    print("Dispatching next runner to maintain perpetual cloud loop...")
    url = "https://api.github.com/repos/mahereasybakery-web/egypt-sharia-stock-report/actions/workflows/run_report.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PerpetualRunner"
    }
    payload = {"ref": "main", "inputs": {"force": "false"}}
    for attempt in range(1, 4):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=15)
            print(f"Next runner dispatch attempt {attempt} status: {r.status_code}")
            if r.status_code in [200, 204]:
                return True
        except Exception as e:
            print(f"Attempt {attempt} error dispatching next runner: {e}")
        time.sleep(5)
    return False

def update_github_news(new_content):
    url = "https://api.github.com/repos/mahereasybakery-web/egypt-sharia-stock-report/contents/news.txt"
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "TelegramBot"
    }
    # ✅ إصلاح: GET محاط بـ try/except لتفادي crash عند انقطاع الشبكة
    sha = ""
    try:
        r_get = requests.get(url, headers=headers, timeout=10)
        if r_get.status_code == 200:
            sha = r_get.json().get("sha", "")
    except Exception as e:
        print(f"Warning: Could not fetch SHA for news.txt: {e}")
        
    content_b64 = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
    payload = {
        "message": "Update news.txt via Telegram Bot",
        "content": content_b64
    }
    if sha:
        payload["sha"] = sha
    try:
        r_put = requests.put(url, headers=headers, json=payload, timeout=10)
        return r_put.status_code in [200, 201]
    except Exception as e:
        print(f"Error updating news.txt on GitHub: {e}")
        return False

def get_github_state():
    url = "https://api.github.com/repos/mahereasybakery-web/egypt-sharia-stock-report/contents/state.json"
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "TelegramBot"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            content = base64.b64decode(r.json()["content"]).decode("utf-8")
            return json.loads(content), r.json().get("sha", "")
    except Exception as e:
        print(f"Error loading state.json: {e}")
    return {"sent_links": [], "date": ""}, ""

def update_github_state(state_data, sha):
    url = "https://api.github.com/repos/mahereasybakery-web/egypt-sharia-stock-report/contents/state.json"
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "TelegramBot"
    }
    content_b64 = base64.b64encode(json.dumps(state_data).encode("utf-8")).decode("utf-8")
    payload = {
        "message": "Update state.json",
        "content": content_b64
    }
    if sha:
        payload["sha"] = sha
    try:
        r = requests.put(url, headers=headers, json=payload, timeout=10)
        return r.status_code in [200, 201]
    except Exception as e:
        print(f"Error updating state.json: {e}")
        return False

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
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": question}]
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=60)
            if r.status_code == 200:
                return r.json()["content"][0]["text"]
            else:
                print(f"Claude API returned status {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print("Claude API error:", e)

    # Fallback to Gemini AI (with model fallback to bypass 503/404/429 errors)
    if GEMINI_API_KEY:
        gemini_models = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-flash-latest", "gemini-pro-latest"]
        for model_name in gemini_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
            headers = {"content-type": "application/json"}
            payload = {
                "contents": [{"parts": [{"text": question}]}],
                "generationConfig": {
                    "temperature": 0.3
                }
            }
            for attempt in range(2):
                try:
                    r = requests.post(url, headers=headers, json=payload, timeout=75)
                    if r.status_code == 200:
                        res_json = r.json()
                        candidates = res_json.get("candidates", [])
                        if candidates and "content" in candidates[0] and candidates[0]["content"].get("parts"):
                            return candidates[0]["content"]["parts"][0]["text"]
                        else:
                            print(f"Gemini {model_name} response blocked or empty in ask_ai. Response: {res_json}")
                            break
                    elif r.status_code == 429:
                        print(f"Gemini {model_name} rate limit (429), attempt {attempt+1}. Backing off 5s...")
                        time.sleep(5)
                        continue
                    elif r.status_code == 503:
                        print(f"Gemini {model_name} overloaded (503), attempt {attempt+1}. Backing off 3s...")
                        time.sleep(3)
                        continue
                    else:
                        print(f"Gemini {model_name} ask_ai returned status {r.status_code}")
                        break
                except Exception as e:
                    print(f"Gemini {model_name} ask_ai error: {e}")
                    break
        return "عذراً، خوادم الذكاء الاصطناعي لـ Gemini تواجه ضغطاً حالياً. يرجى المحاولة لاحقاً."
            
    return "يرجى ضبط مفاتيح المطورين (CLAUDE_API_KEY أو GEMINI_API_KEY) لتفعيل محادثات الذكاء الاصطناعي."

def fetch_rss_news():
    feeds = {
        "جريدة البورصة": "https://alborsaanews.com/feed",
        "جريدة المال": "https://almalnews.com/feed/",
        "حابي جرنال": "https://hapijournal.com/feed",
        "إيكونومي بلس": "https://economyplusme.com/feed",
        "إنتربرايز": "https://enterprise.press/ar/feed",
        "أموال الغد": "https://amwalalghad.com/feed",
        "سي إن بي سي عربية": "https://www.cnbcarabia.com/rss",
        "زاوية مصر": "https://www.zawya.com/ar/rss/egypt/",
        "الشروق اقتصاد": "https://www.shorouknews.com/rss/economy",
        "المصري اليوم اقتصاد": "https://www.almasryalyoum.com/rss/sections/2/feed"
    }
    
    # ✅ استعلام أخبار جوجل العام للسوق
    q_market = '"البورصة المصرية" OR "سوق المال" OR "أسهم مصر" OR "EGX30"'
    feeds["أخبار جوجل - البورصة"] = f"https://news.google.com/rss/search?q={urllib.parse.quote(q_market)}&hl=ar&gl=EG&ceid=EG:ar"
    
    # ✅ استعلام أخبار جوجل المخصص لشركات المحفظة والمتابعة الرئيسية
    q_portfolio = '"طلعت مصطفى" OR "سهم فوري" OR "المصرية للاتصالات" OR "إيديتا" OR "أبوظبي الإسلامي" OR "سوديك" OR "إي فاينانس" OR "مصر للألومنيوم"'
    feeds["أخبار جوجل - أسهم المحفظة"] = f"https://news.google.com/rss/search?q={urllib.parse.quote(q_portfolio)}&hl=ar&gl=EG&ceid=EG:ar"
    
    headers = {"User-Agent": "Mozilla/5.0"}
    news_items = []
    
    for source_name, url in feeds.items():
        try:
            r = requests.get(url, headers=headers, timeout=10, verify=False)
            if r.status_code != 200:
                continue
            r.encoding = 'utf-8' # enforce utf-8
                
            if feedparser:
                feed = feedparser.parse(r.content)
                items = feed.entries
            else:
                root = ET.fromstring(r.content)
                items_xml = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry") or [elem for elem in root.iter() if elem.tag.endswith("item") or elem.tag.endswith("entry")]
                items = []
                for item in items_xml:
                    title_elem = next((child for child in item if child.tag.endswith("title")), None)
                    link_elem = next((child for child in item if child.tag.endswith("link")), None)
                    t = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                    l = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                    if not l and link_elem is not None:
                        l = link_elem.attrib.get("href", "").strip()
                    items.append({"title": t, "link": l})

            limit = 40 if "جوجل" in source_name else 25
            for entry in items[:limit]:
                # ✅ فحص تاريخ النشر: نافذة مرنة تشمل آخر 72 ساعة في العطلة وبداية الأسبوع، و36 ساعة في باقي الأيام
                is_recent = True
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        egypt_tz = timezone(timedelta(hours=3))
                        pub_egypt = pub_dt.astimezone(egypt_tz)
                        now_egypt = datetime.now(egypt_tz)
                        # 72 ساعة إذا كان اليوم أحد/جمعة/سبت أو صباح الإثنين، و36 ساعة لباقي الأوقات
                        max_hours = 72 if now_egypt.weekday() in [4, 5, 6] or (now_egypt.weekday() == 0 and now_egypt.hour < 12) else 36
                        age_hours = (now_egypt - pub_egypt).total_seconds() / 3600.0
                        if age_hours > max_hours or age_hours < -2:
                            is_recent = False
                    except Exception:
                        pass
                if not is_recent:
                    continue
                    
                if hasattr(entry, 'title'):
                    title = getattr(entry, 'title', '')
                    link = getattr(entry, 'link', '')
                else:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                if title and link:
                    link = link.replace(" ", "%20")
                    item_source = source_name
                    if "جوجل" in source_name:
                        parts = title.rsplit(" - ", 1)
                        if len(parts) == 2:
                            title = parts[0].strip()
                            item_source = f"{parts[1].strip()} (جوجل)"
                    news_items.append({
                        "title": title.strip(),
                        "link": link,
                        "source": item_source
                    })
        except Exception as e:
            print(f"Error fetching from {source_name}: {e}")
            
    return news_items

def fetch_corporate_websites_news():
    corporate_urls = {
        "FWRY": "https://fawry.com/press-releases/",
        "ETEL": "https://ir.te.eg/ar/news-press-releases/press-releases/",
        "TMGH": "https://www.tmg-holding.com/investor-relations/news-and-announcements/",
        "EFID": "https://www.edita.com.eg/investor-relations/press-releases/",
        "OCDI": "https://sodic.com/investor-relations/disclosures-and-press-releases/",
        "EFIH": "https://www.efinanceinvestment.com/press-releases",
        "ADIB": "https://www.adib.eg/investor-relations/financial-press-releases",
        "ORHD": "https://www.orascomdevelopment.com/investor-relations/press-releases",
        "RACC": "https://rayacc.com/investor-relations/press-releases/"
    }
    
    headers = {"User-Agent": "Mozilla/5.0"}
    results = []
    for ticker, url in corporate_urls.items():
        try:
            r = requests.get(url, headers=headers, timeout=10, verify=False)
            if r.status_code != 200:
                continue
            r.encoding = 'utf-8' # enforce utf-8
            html = r.text
            links = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
            found = 0
            for l_url, l_text in links:
                l_text_clean = re.sub(r'<[^>]+>', '', l_text).strip()
                l_text_clean = re.sub(r'\s+', ' ', l_text_clean)
                
                # ✅ إصلاح: تخطي روابط الأقسام والقوائم الرئيسية لمنع اختطاف التغذية الإخبارية
                parent_url_clean = url.rstrip('/')
                full_link = l_url if l_url.startswith("http") else urljoin(url, l_url)
                full_link_clean = full_link.rstrip('/')
                
                if full_link_clean == parent_url_clean or full_link_clean == parent_url_clean + '/ar' or full_link_clean == parent_url_clean + '/en':
                    continue
                if l_text_clean in [
                    "البيانات الصحفية", "البيانات الصحفيه", "Press Releases", "Press Release",
                    "الأخبار", "الاخبار", "News", "الإفصاحات", "الافصاحات", "Disclosures",
                    "بيانات صحفية", "بيانات صحفيه", "مجلس الإدارة", "مجلس الادارة", "عن الشركة",
                    "عن الشركه", "About Us", "الصفحة الرئيسية", "الرئيسية", "Home"
                ]:
                    continue
                    
                if len(l_text_clean) > 15 and (
                    any(x in l_text_clean for x in ["إفصاح", "بيان", "صحفي", "نتائج", "أرباح", "مجلس", "إدارة", "شراكة", "توقيع", "استحواذ", "تعاون", "افتتاح", "زيادة", "مالية"]) or
                    any(y in l_url.lower() for y in ["press", "release", "news", "disclosure", "pdf"]) or
                    any(z in l_text_clean.lower() for z in ["press", "release", "disclosure", "financial", "result"])
                ):
                    results.append({
                        "tag": f"[{ticker}]",
                        "title": l_text_clean,
                        "link": full_link,
                        "source": "الموقع الرسمي"
                    })
                    found += 1
                    if found >= 2:
                        break
        except Exception as e:
            print(f"Skipping corporate site {ticker}: {e}")
    return results

def decode_unicode_escapes(s):
    """فك تسلسلات Unicode بأمان تام ودون حساسية للأقواس أو علامات الاقتباس."""
    try:
        return re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)
    except Exception:
        return s

def fetch_egx_beta_news():
    url = "https://beta.egx.com.eg/"
    headers = {"User-Agent": "Mozilla/5.0"}
    items = []
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = 'utf-8' # enforce utf-8
        
        # Escaped matches: \"code\":343607,...\"headingArabic\":\"...\"
        escaped_matches = re.finditer(r'\\"code\\"\s*:\s*(\d+),.*?\\"headingArabic\\"\s*:\s*\\"(.*?)\\"', r.text)
        for m in escaped_matches:
            code = m.group(1)
            heading = m.group(2)
            if heading and heading != "null":
                heading = decode_unicode_escapes(heading).replace('\\"', '"').replace('\\\\', '\\')
                items.append({
                    "tag": "[EGX]",
                    "title": heading.strip(),
                    "code": code,
                    "source": "بورصة مصر"
                })
                
        # Unescaped matches: "code":343607,..."headingArabic":"..."
        unescaped_matches = re.finditer(r'"code"\s*:\s*(\d+),.*?"headingArabic"\s*:\s*"(.*?)"', r.text)
        for m in unescaped_matches:
            code = m.group(1)
            heading = m.group(2)
            if heading and heading != "null":
                heading = decode_unicode_escapes(heading).replace('\\"', '"').replace('\\\\', '\\')
                items.append({
                    "tag": "[EGX]",
                    "title": heading.strip(),
                    "code": code,
                    "source": "بورصة مصر"
                })
    except Exception as e:
        print("Error fetching EGX Beta news:", e)
        
    unique = []
    seen = set()
    for item in items:
        uid = f"{item['tag']}_{item['title']}"
        if uid not in seen:
            seen.add(uid)
            item["link"] = "https://beta.egx.com.eg/ar/media-center?tab=disclosure"
            unique.append(item)
    return unique

def normalize_arabic(text):
    """تهيئة النص العربي بتوحيد الألف، والياء/الألف المقصورة، والتاء المربوطة/الهاء لضمان مطابقة الكلمات المكتوبة بطرق مختلفة."""
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"[أإآا]", "ا", text)
    text = re.sub(r"[يى]", "ي", text)
    text = re.sub(r"[ةه]", "ه", text)
    return text

def is_whole_word_match(word, text):
    """مطابقة الكلمات المفتاحية بشكل دقيق مع دعم السوابق العربية المشروعة فقط وتوحيد الحروف لمنع التشابه الخاطئ."""
    if not word or not text:
        return False
    norm_word = normalize_arabic(word.lower())
    norm_text = normalize_arabic(text.lower())
    # ✅ إصلاح: السماح بمسافات متعددة بين الكلمات في العبارة المفتاحية
    escaped_word = re.escape(norm_word).replace(r'\ ', r'\s+')
    # حذف سوابق 'ك' و 'كال' لمنع مطابقة كلمات وأسماء مثل 'كفوري' مع 'فوري' أو 'كاموك' مع 'أموك'
    pattern = r"(?:^|\W)(?:و|ف|ب|ل|لل|ال|وال|فال|بال)?" + escaped_word + r"(?:$|\W)"
    return re.search(pattern, norm_text) is not None

def is_globally_excluded_news(title):
    """فحص الأخبار ضد قائمة الاستبعاد العامة (فنون، مشاهير، حفلات، رياضة، حوادث، جرائم)."""
    if not title:
        return False
    norm_title = normalize_arabic(title.lower())
    for kw in GLOBAL_EXCLUDE_KEYWORDS:
        norm_kw = normalize_arabic(kw.lower())
        if norm_kw in norm_title:
            return True
    return False

def matches_negative_keyword(ticker, title):
    """فحص الأخبار ضد قائمة الاستبعاد الخاصة بالسهم لمنع الالتباس اللغوي والمشاهير."""
    if not title or ticker not in NEGATIVE_KEYWORDS:
        return False
    norm_title = normalize_arabic(title.lower())
    for kw in NEGATIVE_KEYWORDS[ticker]:
        norm_kw = normalize_arabic(kw.lower())
        if norm_kw in norm_title:
            return True
    return False

def get_filtered_market_news(portfolio_list, watchlist_list):
    filtered = []
    seen_links = set()
    
    try:
        corp_news = fetch_corporate_websites_news()
        for item in corp_news:
            link = item["link"]
            if link not in seen_links:
                seen_links.add(link)
                ticker = item["tag"].strip("[]")
                if ticker in portfolio_list or ticker in watchlist_list:
                    filtered.append(item)
    except Exception as e:
        print("Error getting corporate news:", e)
        
    all_news = fetch_rss_news()
    
    # ✅ إصلاح: فلترة وتصنيف أخبار EGX Beta وربطها بالأسهم إذا تطابقت مع STOCK_KEYWORDS
    egx_beta_items = fetch_egx_beta_news()
    for item in egx_beta_items:
        title = item["title"]
        if is_globally_excluded_news(title):
            continue
        if item["link"] not in seen_links:
            seen_links.add(item["link"])
            
            matched_stock = None
            for ticker, keywords in STOCK_KEYWORDS.items():
                if ticker not in portfolio_list and ticker not in watchlist_list:
                    continue
                if matches_negative_keyword(ticker, title):
                    continue
                for kw in keywords:
                    if is_whole_word_match(kw, title):
                        matched_stock = ticker
                        break
                if matched_stock:
                    break
            
            is_market = False
            if not matched_stock:
                for mkw in ["البورصة", "البورصه", "EGX30", "EGX", "سوق المال", "الأسهم المصرية"]:
                    if is_whole_word_match(mkw, title):
                        is_market = True
                        break
            
            if matched_stock or is_market:
                if matched_stock:
                    item["tag"] = f"[{matched_stock}]"
                    item["link"] = f"https://www.mubasher.info/markets/EGX/stocks/{matched_stock}/news"
                else:
                    item["tag"] = "[البورصة]"
                    item["link"] = "https://beta.egx.com.eg/ar/media-center?tab=disclosure"
                filtered.append(item)
    
    for item in all_news:
        title = item["title"]
        link = item["link"]
        source = item["source"]
        if link in seen_links:
            continue
        if is_globally_excluded_news(title):
            continue
            
        matched_stock = None
        for ticker, keywords in STOCK_KEYWORDS.items():
            if ticker not in portfolio_list and ticker not in watchlist_list:
                continue
            if matches_negative_keyword(ticker, title):
                continue
            for kw in keywords:
                if is_whole_word_match(kw, title):
                    matched_stock = ticker
                    break
            if matched_stock:
                break
                
        is_market = False
        if not matched_stock:
            for mkw in ["البورصة", "البورصه", "EGX30", "EGX", "سوق المال", "الأسهم المصرية"]:
                if is_whole_word_match(mkw, title):
                    is_market = True
                    break
                    
        if matched_stock or is_market:
            seen_links.add(link)
            tag = f"[{matched_stock}]" if matched_stock else "[البورصة]"
            filtered.append({
                "tag": tag,
                "title": title,
                "link": link,
                "source": source
            })
    return filtered

def batch_analyze_news_with_gemini(grouped_news, portfolio_list, watchlist_list):
    if not GEMINI_API_KEY:
        print("Gemini API key missing. Skipping AI analysis.")
        return {}
        
    target_tags = []
    for k in portfolio_list + watchlist_list:
        tag = f"[{k}]"
        if tag in grouped_news:
            target_tags.append(tag)
    target_tags = target_tags[:15]  # زيادة الحد من 10 إلى 15 سهماً
    
    if not target_tags:
        return {}
        
    prompt = (
        "أنت خبير مالي ومحلل أسهم ومحكم جودة ومصداقية في البورصة المصرية.\n"
        "مهمتك فحص الأخبار الواردة لكل سهم وتقديم تحليل مالي وتقييم موضوعي مباشر:\n\n"
        "⚠️ قاعدة صارمة جداً (بوابة الاستبعاد الفوري):\n"
        "- إذا كان الخبر المرفق لا يخص إطلاقاً الشركة المساهمة المقيدة في البورصة المصرية ونشاطها المؤسسي (مثل: تشابه أسماء مع مشاهير أو فنانين أو مغنين أو لاعبي كرة، أو استخدام لغوي مجازي كظرف مثل 'بشكل فوري' أو 'حل فوري'، أو أخبار جرائم/حوادث/فن/رياضة لا علاقة لها بالشركة إطلاقاً)، فيجب عليك الرد فوراً بالتنسيق التالي حصراً وبدون أي كلمة أخرى:\n"
        "[اسم السهم]: IRRELEVANT\n\n"
        "إذا كان الخبر متعلقاً بالشركة بالفعل، فقدم تحليلاً بالتنسيق:\n"
        "1. تقييم تأثير الخبر على السهم (إيجابي / سلبي / محايد) وشرح السبب المالي أو التشغيلي المباشر.\n"
        "2. الرؤية الفنية والاتجاه المتوقع مع أهم مستويات الدعم والمقاومة القريبة للسهم.\n"
        "قاعدة هامة: إذا ورد أكثر من خبر عن نفس السهم، قم بتحليلها معاً في تقييم واحد يوضح التأثير المشترك والمتوقع لها مجتمعة على أداء ومستقبل السهم.\n\n"
        "يجب أن تكون الإجابة بالتنسيق التالي لكل سهم (كل سهم في سطر منفصل وبدون أي نصوص برمجية):\n"
        "[اسم السهم]: نص التحليل المالي والتقييم ومستويات الدعم والمقاومة مباشرة.\n"
        "مثال:\n"
        "[FWRY]: التقييم إيجابي. نمو الإيرادات والربحية يدعم استمرار المسار الصاعد، الدعم الحالي 7.80 والمقاومة 8.50 جنيه.\n"
        "[ETEL]: التقييم محايد مائل للإيجابية. استقرار التدفقات النقدية مع ترقب توزيعات الأرباح، الدعم 38.5 والمقاومة 42.0 جنيه.\n\n"
        "الأسهم والأخبار المتاحة:\n"
    )
    
    for tag in target_tags:
        ticker = tag.replace("[", "").replace("]", "")
        prompt += f"--- سهم {ticker} ---\n"
        for item in grouped_news[tag][:3]:
            prompt += f"- {item['title']} (المصدر: {item['source']})\n"
        prompt += "\n"
        
    analyses = {}
    discarded_tags = set()
    # ✅ إصلاح: تجربة عدة نماذج بالتوالي كآلية تراجع (Fallback) لتفادي أخطاء 503/404
    gemini_models = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-flash-latest", "gemini-pro-latest"]
    for model_name in gemini_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2
            }
        }
        success = False
        for attempt in range(2):
            try:
                r = requests.post(url, json=body, headers={"Content-Type": "application/json"}, timeout=60)
                if r.status_code == 200:
                    res_json = r.json()
                    candidates = res_json.get("candidates", [])
                    if not candidates or "content" not in candidates[0] or not candidates[0]["content"].get("parts"):
                        print(f"Gemini {model_name} response blocked or empty. Response: {res_json}")
                        break
                    raw_text = candidates[0]["content"]["parts"][0]["text"].strip()
                    matches = re.finditer(r'\[([A-Z0-9]+)\][^\w]*((?:(?!\[[A-Z0-9]+\]).)*)', raw_text, re.DOTALL)
                    for m in matches:
                        clean = m.group(1).upper()
                        analysis = m.group(2).strip()
                        if analysis:
                            upper_an = analysis.upper()
                            if "IRRELEVANT" in upper_an or "لا علاقة" in analysis or "غير متعلق" in analysis or "لا يمت" in analysis or "تشابه اسماء" in analysis:
                                print(f"⚠️ AI Discard Gate: Discarding irrelevant news for [{clean}]: {analysis}")
                                discarded_tags.add(f"[{clean}]")
                            else:
                                analysis_esc = escape_html(analysis)
                                analyses[f"[{clean}]"] = f"🧠 <b>تحليل AI لسهم {clean}:</b> {analysis_esc}"
                    print(f"Gemini AI Analysis successfully generated using {model_name} for:", list(analyses.keys()))
                    if discarded_tags:
                        print("AI Discarded irrelevant tags:", list(discarded_tags))
                    success = True
                    break
                elif r.status_code == 429:
                    print(f"Gemini {model_name} news analysis rate limit (429), attempt {attempt+1}. Backing off 4s...")
                    time.sleep(4)
                    continue
                elif r.status_code == 503:
                    print(f"Gemini {model_name} overloaded (503), attempt {attempt+1}. Backing off 3s...")
                    time.sleep(3)
                    continue
                else:
                    print(f"Gemini {model_name} returned status {r.status_code}: {r.text[:300]}")
                    break
            except Exception as e:
                print(f"Error in Gemini {model_name} batch AI news analysis: {e}")
                break
        if success:
            break
            
    # ✅ حذف الأسهم غير المتعلقة كلياً من قائمة الأخبار المجمعة حتى لا ترسل لتليجرام
    for d_tag in discarded_tags:
        if d_tag in grouped_news:
            del grouped_news[d_tag]
            
    return analyses

def generate_market_ai_pulse(parsed_stocks, egx30, egx33, egx70ewi, sorted_port, sorted_watch):
    """توليد تحليل فني وسوقي لحظي مستقل عبر الذكاء الاصطناعي لتقديم رؤية استراتيجية واضحة للمستثمر حتى في غياب الأخبار الصحفية."""
    if not GEMINI_API_KEY and not CLAUDE_API_KEY:
        return ""
        
    try:
        # اختيار أبرز الأسهم: أهم 3 أسهم من المحفظة + أعلى سهمين حركةً وتغيراً في السوق
        key_stocks = sorted_port[:3]
        movers = [s for s in (sorted_port + sorted_watch) if s not in key_stocks]
        movers.sort(key=lambda x: abs(parsed_stocks.get(x, {}).get("chgPct", 0)), reverse=True)
        selected_tickers = key_stocks + movers[:2]
        
        stock_details = []
        for t in selected_tickers:
            d = parsed_stocks.get(t, {})
            chg = d.get('chgPct', 0)
            chg_str = f"+{chg}%" if chg > 0 else f"{chg}%"
            stock_details.append(f"• {t}: السعر {d.get('close', 0)} ج.م (التغير {chg_str}) | المؤشرات الفنية: {d.get('rec', 'محايد')}")
            
        prompt = (
            "أنت كبير استراتيجيي التداول والمحلل المالي الأول للبورصة المصرية.\n"
            "بناءً على شاشة الأسعار اللحظية التالية لجلسة اليوم:\n"
            f"- مؤشر EGX30: {egx30.get('close')} ({egx30.get('chgPct')}%), مؤشر الشريعة EGX33: {egx33.get('close')} ({egx33.get('chgPct')}%), مؤشر السبعيني EGX70: {egx70ewi.get('close')} ({egx70ewi.get('chgPct')}%)\n"
            f"- أبرز أسهم المحفظة والأسهم الأكثر حركة اليوم:\n" + "\n".join(stock_details) + "\n\n"
            "المطلوب: تقديم تقرير تحليلي مكثف وواضح للمستثمر في 3 فقرات مركزة بالتنسيق التالي حصراً وبدون مقدمات:\n"
            "⚡ <b>نبض الجلسة والسيولة:</b> قراءة موجزة لاتجاه السيولة وسلوك المؤشرات العامة.\n"
            "🎯 <b>نظرة فنية على الأسهم النشطة:</b> تحليل فني مباشر لأبرز سهمين (مستويات الدعم والمقاومة اللحظية، وتوصية فنية محددة).\n"
            "💡 <b>بوصلة المستثمر:</b> نصيحة استراتيجية واضحة للتعامل مع بقية الجلسة أو الجلسة القادمة.\n\n"
            "تنبيه: اكتب النص بأسلوب اقتصادي فخم ومباشر بدون مقدمات وبدون أي كود برمجي أو وسوم غير <b>."
        )
        
        if GEMINI_API_KEY:
            gemini_models = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-flash-latest", "gemini-pro-latest"]
            for model_name in gemini_models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
                body = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.25
                    }
                }
                for attempt in range(2):
                    try:
                        r = requests.post(url, json=body, headers={"Content-Type": "application/json"}, timeout=35)
                        if r.status_code == 200:
                            res_json = r.json()
                            candidates = res_json.get("candidates", [])
                            if candidates and "content" in candidates[0] and candidates[0]["content"].get("parts"):
                                raw_text = candidates[0]["content"]["parts"][0]["text"].strip()
                                return f"🧠 <b>تحليل الذكاء الاصطناعي لنبض الجلسة:</b>\n\n{raw_text}"
                        elif r.status_code in [429, 503]:
                            time.sleep(2)
                            continue
                        else:
                            break
                    except Exception as e:
                        print(f"Error calling Gemini {model_name} for market pulse: {e}")
                        break
    except Exception as e:
        print("Error in generate_market_ai_pulse:", e)
    return ""

def send_telegram_photo(photo_path, caption=""):
    """إرسال صورة شارت فني إلى تليجرام مع شرح."""
    if not BOT_TOKEN or not CHAT_ID or not os.path.exists(photo_path):
        return
    if caption:
        caption = ensure_rtl(caption)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        with open(photo_path, "rb") as f:
            files = {"photo": f}
            data = {"chat_id": CHAT_ID, "caption": caption[:1024], "parse_mode": "HTML"}
            requests.post(url, data=data, files=files, timeout=30)
    except Exception as e:
        print("Error sending telegram photo:", e)

def generate_market_chart(indices, parsed_stocks):
    """توليد رسم بياني يومي أنيق للأداء الفني والزخم (Dark Mode)."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np
        
        plt.style.use('dark_background')
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5), dpi=120)
        fig.patch.set_facecolor('#121212')
        ax1.set_facecolor('#1e1e1e')
        ax2.set_facecolor('#1e1e1e')
        
        # 1. Bar chart of Core Portfolio Stocks changes
        stocks = ["TMGH", "FWRY", "ETEL", "EFID", "ADIB", "EGAL", "OCDI", "EFIH"]
        filtered_stocks = [s for s in stocks if s in parsed_stocks]
        if not filtered_stocks:
            filtered_stocks = list(parsed_stocks.keys())[:6]
        chgs = [parsed_stocks[s].get("chgPct", 0.0) for s in filtered_stocks]
        colors = ['#00E676' if c > 0 else ('#FF5252' if c < 0 else '#888888') for c in chgs]
        
        y_pos = np.arange(len(filtered_stocks))
        ax1.barh(y_pos, chgs, color=colors, height=0.55)
        ax1.set_yticks(y_pos)
        ax1.set_yticklabels(filtered_stocks, fontsize=10, fontweight='bold', color='#FFFFFF')
        ax1.axvline(0, color='#888888', linestyle='--', linewidth=0.8)
        ax1.set_title('تغيرات أسهم المحفظة (%)', fontsize=11, fontweight='bold', color='#FFD700', pad=10)
        for i, v in enumerate(chgs):
            ax1.text(v + (0.1 if v >= 0 else -0.45), i, f"{v:+.1f}%", va='center', fontsize=9, fontweight='bold', color='#FFFFFF')
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        
        # 2. RSI Gauge
        rsis = [parsed_stocks[s].get("rsi", 50.0) or 50.0 for s in filtered_stocks]
        rsi_colors = ['#FF5252' if r >= 70 else ('#00E676' if r <= 30 else '#29B6F6') for r in rsis]
        ax2.barh(y_pos, rsis, color=rsi_colors, height=0.55)
        ax2.set_yticks(y_pos)
        ax2.set_yticklabels(filtered_stocks, fontsize=10, fontweight='bold', color='#FFFFFF')
        ax2.axvline(70, color='#FF5252', linestyle=':', linewidth=1.2, label='Overbought (70)')
        ax2.axvline(30, color='#00E676', linestyle=':', linewidth=1.2, label='Oversold (30)')
        ax2.set_xlim(0, 100)
        ax2.set_title('مؤشر الزخم الفني RSI (14)', fontsize=11, fontweight='bold', color='#00E5FF', pad=10)
        for i, v in enumerate(rsis):
            ax2.text(v + 1.5, i, f"{v:.1f}", va='center', fontsize=9, fontweight='bold', color='#FFFFFF')
        ax2.legend(loc='lower right', fontsize=8, facecolor='#2a2a2a', edgecolor='none')
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        
        plt.tight_layout()
        out_path = "market_summary_chart.png"
        plt.savefig(out_path, facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close()
        return out_path
    except Exception as e:
        print("Error generating market chart:", e)
        return None

def scan_insider_and_block_trades(all_news, egx_beta_items):
    """رصد صفقات الداخليين (أعضاء مجلس الإدارة، المجموعات المرتبطة، أسهم الخزينة) والصفقات الكبرى."""
    insider_keywords = [
        "مجلس ادارة", "مجلس اداره", "اعضاء مجلس", "المجموعات المرتبطة", "المجموعه المرتبطه",
        "كبار المساهمين", "اسهم خزينة", "اسهم خزينه", "صفقة ذات حجم كبير", "صفقة كودية", "نقل ملكية",
        "تعاملات الداخليين"
    ]
    alerts = []
    seen = set()
    for it in (egx_beta_items + all_news):
        t = it.get("title", "")
        if not t or t in seen:
            continue
        norm_t = normalize_arabic(t.lower())
        for kw in insider_keywords:
            if kw in norm_t:
                seen.add(t)
                alerts.append(it)
                break
    return alerts

def format_insider_alerts(alerts):
    if not alerts:
        return ""
    block = "🚨 <b>رادار كبار المساهمين والصفقات الكبرى (Insider Deals):</b>\n"
    for al in alerts[:4]:
        title_esc = escape_html(al["title"])
        source_esc = escape_html(al.get("source", "إفصاح رسمي"))
        link_esc = escape_html(al.get("link", "#"))
        block += f"• {title_esc} ({source_esc}) <a href='{link_esc}'>[التفاصيل]</a>\n"
    return block

def scan_dividends_and_actions(all_news, egx_beta_items):
    """رصد إعلانات التوزيعات النقدية وتواريخ نهاية الحق والجمعيات العمومية."""
    div_keywords = [
        "كوبون نقدي", "توزيع نقدي", "توزيع ارباح", "نهاية الحق", "تاريخ الصرف",
        "جمعية عامة عادية", "تجزئة القيمة الاسمية", "اسهم مجانية"
    ]
    actions = []
    seen = set()
    for it in (egx_beta_items + all_news):
        t = it.get("title", "")
        if not t or t in seen:
            continue
        norm_t = normalize_arabic(t.lower())
        for kw in div_keywords:
            if kw in norm_t:
                seen.add(t)
                actions.append(it)
                break
    return actions

def format_dividends_alerts(actions):
    if not actions:
        return ""
    block = "💰 <b>رادار التوزيعات النقدية وقرارات الشركات (Corporate Actions):</b>\n"
    for ac in actions[:4]:
        title_esc = escape_html(ac["title"])
        source_esc = escape_html(ac.get("source", "إفصاح رسمي"))
        link_esc = escape_html(ac.get("link", "#"))
        block += f"• {title_esc} ({source_esc}) <a href='{link_esc}'>[التفاصيل]</a>\n"
    return block

def calculate_portfolio_pnl(holdings, parsed_stocks):
    """حساب الأرباح والخسائر اللحظية بدقة متناهية 0.00 ج.م."""
    if not holdings:
        return None
    total_cost = 0.0
    total_val = 0.0
    details = []
    
    for ticker, data in holdings.items():
        qty = float(data.get("qty", 0))
        buy_p = float(data.get("buy_price", 0))
        if qty <= 0 or buy_p <= 0:
            continue
        curr_p = float(parsed_stocks.get(ticker, {}).get("close", buy_p))
        cost = qty * buy_p
        val = qty * curr_p
        pnl = val - cost
        pnl_pct = (pnl / cost) * 100.0 if cost > 0 else 0.0
        
        total_cost += cost
        total_val += val
        
        details.append({
            "ticker": ticker,
            "qty": qty,
            "buy_p": buy_p,
            "curr_p": curr_p,
            "cost": cost,
            "val": val,
            "pnl": pnl,
            "pnl_pct": pnl_pct
        })
        
    total_pnl = total_val - total_cost
    total_pnl_pct = (total_pnl / total_cost) * 100.0 if total_cost > 0 else 0.0
    
    return {
        "details": details,
        "total_cost": total_cost,
        "total_val": total_val,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct
    }

def format_portfolio_pnl_message(pnl_data):
    if not pnl_data or not pnl_data["details"]:
        return (
            "💼 <b>المحفظة الذكية الرقمية:</b>\n"
            "لم يتم تسجيل أي أسهم بعد.\n"
            "يمكنك تسجيل حيازاتك بسهولة بالأمر:\n"
            "<code>/set_holding [السهم] [الكمية] [سعر_الشراء]</code>\n"
            "مثال:\n"
            "<code>/set_holding FWRY 2000 18.50</code>"
        )
    
    # فرز الأسهم دائماً من الأعلى ربحاً إلى الأقل ربحاً (أو الأقل خسارة)
    sorted_details = sorted(pnl_data["details"], key=lambda x: x["pnl_pct"], reverse=True)
    
    msg = "💼 <b>كشف حساب المحفظة الاستثمارية اللحظي (P&L):</b>\n"
    msg += "<i>(مرتبة تنازلياً من الأعلى ربحاً إلى الأقل)</i>\n\n"
    for d in sorted_details:
        dir_e = "🟢" if d["pnl"] >= 0 else "🔴"
        sign = "+" if d["pnl"] >= 0 else ""
        ticker_name = COMPANY_NAMES_AR.get(d['ticker'], d['ticker'])
        msg += f"{dir_e} <b>{ticker_name} ({d['ticker']})</b> - عدد {int(d['qty']):,} سهم:\n"
        msg += f"  • سعر الشراء: {d['buy_p']:.2f} ج.م | السعر اللحظي: <b>{d['curr_p']:.2f} ج.م</b>\n"
        msg += f"  • صافي العائد: <b>{sign}{d['pnl']:,.2f} ج.م</b> ({sign}{d['pnl_pct']:.2f}%)\n\n"
        
    tot_e = "🟢" if pnl_data["total_pnl"] >= 0 else "🔴"
    tot_sign = "+" if pnl_data["total_pnl"] >= 0 else ""
    msg += "━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📊 <b>إجمالي القيمة السوقية:</b> {pnl_data['total_val']:,.2f} ج.م\n"
    msg += f"💵 <b>إجمالي التكلفة:</b> {pnl_data['total_cost']:,.2f} ج.م\n"
    msg += f"{tot_e} <b>صافي الربح/الخسارة:</b> <b>{tot_sign}{pnl_data['total_pnl']:,.2f} ج.م</b> ({tot_sign}{pnl_data['total_pnl_pct']:.2f}%)\n"
    return msg

def check_and_trigger_user_alerts(parsed_stocks, state_data, state_sha):
    """فحص تنبيهات الأسعار المخصصة للمستخدم وإرسال إشعار فوري عند تحققها."""
    alerts = state_data.get("alerts", [])
    if not alerts:
        return
    remaining_alerts = []
    triggered_any = False
    for a in alerts:
        ticker = a.get("ticker", "").upper()
        cond = a.get("cond", "")
        price = float(a.get("price", 0))
        curr = parsed_stocks.get(ticker, {}).get("close")
        if curr is not None and curr > 0:
            if (cond == ">" and curr >= price) or (cond == "<" and curr <= price):
                alert_msg = (
                    f"🎯 <b>تنبيه سعري متحقق!</b>\n"
                    f"سهم <b>{ticker}</b> وصل إلى <b>{curr:.2f} ج.م</b> "
                    f"(الشرط المحدد: {cond} {price:.2f} ج.م).\n"
                    f"📊 التغير اليومي: {parsed_stocks[ticker].get('chgPct', 0)}%"
                )
                reply_telegram(alert_msg)
                triggered_any = True
                continue
        remaining_alerts.append(a)
    if triggered_any:
        state_data["alerts"] = remaining_alerts
        update_github_state(state_data, state_sha)

def fetch_all_data_tv(tickers, strings):
    parsed = {}
    indices = {
        "EGX30": {"close": 0.0, "open": 0.0, "chgPct": 0.0},
        "EGX70EWI": {"close": 0.0, "open": 0.0, "chgPct": 0.0},
        "EGX100EWI": {"close": 0.0, "open": 0.0, "chgPct": 0.0}
    }
    url = "https://scanner.tradingview.com/egypt/scan"
    tv_tickers = [f"EGX:{t}" for t in tickers] + ["EGX:EGX30", "EGX:EGX70EWI", "EGX:EGX100EWI"]
    payload = {
        "symbols": {"tickers": tv_tickers},
        "columns": [
            "close", "open", "change", "Recommend.All",
            "RSI", "volume", "average_volume_10d_calc", "SMA20", "SMA50", "Value.Traded"
        ]
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        r.raise_for_status()  # رفع استثناء عند أي خطأ HTTP (4xx, 5xx)
        data = r.json()
        for item in data.get("data", []):
            sym = item["s"].replace("EGX:", "")
            c = safe_round(item["d"][0])
            o = safe_round(item["d"][1])
            change_val = item["d"][2]   # نسبة التغيير اليومي من TradingView
            rec_val = item["d"][3]
            
            # المؤشرات الفنية المتقدمة
            rsi_val = safe_round(item["d"][4], 1) if len(item["d"]) > 4 and item["d"][4] is not None else None
            vol_val = safe_round(item["d"][5], 0) if len(item["d"]) > 5 and item["d"][5] is not None else 0
            avg_vol = safe_round(item["d"][6], 0) if len(item["d"]) > 6 and item["d"][6] is not None else 0
            sma20_val = safe_round(item["d"][7], 2) if len(item["d"]) > 7 and item["d"][7] is not None else None
            sma50_val = safe_round(item["d"][8], 2) if len(item["d"]) > 8 and item["d"][8] is not None else None
            val_traded = safe_round(item["d"][9], 0) if len(item["d"]) > 9 and item["d"][9] is not None else 0
            
            vol_spike = bool(avg_vol > 5000 and vol_val >= (avg_vol * 1.8))
            rsi_tag = ""
            if rsi_val is not None:
                if rsi_val >= 70:
                    rsi_tag = "⚠️ تشبع شرائي"
                elif rsi_val <= 30:
                    rsi_tag = "💎 تشبع بيعي"
            
            # استخدام change مباشرة
            chg = safe_round(change_val)
            
            rec_str = ""
            if rec_val is not None:
                if rec_val >= 0.5: rec_str = strings.get('strong_buy', 'شراء قوي')
                elif rec_val >= 0.1: rec_str = strings.get('buy', 'شراء')
                elif rec_val <= -0.5: rec_str = strings.get('strong_sell', 'بيع قوي')
                elif rec_val <= -0.1: rec_str = strings.get('sell', 'بيع')
                else: rec_str = "محايد"
            if sym in indices:
                indices[sym] = {"close": c, "open": o, "chgPct": chg, "volume": vol_val, "val_traded": val_traded}
            else:
                parsed[sym] = {
                    "close": c, "open": o, "chgPct": chg, "rec": rec_str,
                    "rsi": rsi_val, "volume": vol_val, "avg_vol": avg_vol,
                    "sma20": sma20_val, "sma50": sma50_val, "val_traded": val_traded,
                    "vol_spike": vol_spike, "rsi_tag": rsi_tag
                }
    except Exception as e:
        print("Error fetching TV prices:", e)
        reply_telegram(f"⚠️ <b>تنبيه:</b> فشل الاتصال بخادم TradingView لجلب الأسعار.\n<code>{str(e)[:200]}</code>")
        for t in tickers:
            parsed[t] = {"close": 0.0, "open": 0.0, "chgPct": 0.0, "rec": ""}
    return parsed, indices

def fetch_forex_gold():
    usdegp = {"close": 0.0, "chgPct": 0.0, "open": 0.0}
    xauusd = {"close": 0.0, "chgPct": 0.0, "open": 0.0}
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        r_fx = requests.post("https://scanner.tradingview.com/forex/scan", json={
            "symbols": {"tickers": ["FX_IDC:USDEGP"]},
            "columns": ["close", "open", "change"]
        }, headers=headers, timeout=10)
        r_fx.raise_for_status()
        r_fx = r_fx.json()
        for item in r_fx.get("data", []):
            c = safe_round(item["d"][0])
            o = safe_round(item["d"][1])
            chg_val = item["d"][2]
            chg = safe_round(chg_val)
            usdegp = {"close": c, "chgPct": chg, "open": o}
    except Exception as e:
        print("Error fetching FX:", e)
        
    try:
        r_gold = requests.post("https://scanner.tradingview.com/cfd/scan", json={
            "symbols": {"tickers": ["TVC:GOLD"]},
            "columns": ["close", "open", "change"]
        }, headers=headers, timeout=10)
        r_gold.raise_for_status()
        r_gold = r_gold.json()
        for item in r_gold.get("data", []):
            c = safe_round(item["d"][0])
            o = safe_round(item["d"][1])
            chg_val = item["d"][2]
            chg = safe_round(chg_val)
            xauusd = {"close": c, "chgPct": chg, "open": o}
    except Exception as e:
        print("Error fetching Gold:", e)
        
    return usdegp, xauusd

def fetch_egx33_shariah():
    """Fetch EGX33 Shariah index from TradingView symbol page (not available in Scanner API)."""
    shariah = {"close": 0.0, "open": 0.0, "chgPct": 0.0}
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get("https://www.tradingview.com/symbols/EGX-SHARIAH/", headers=headers, timeout=15)
        text = r.text
        
        close_m = re.search(r'"close"\s*:\s*"?([\d.,]+)"?', text)
        open_m = re.search(r'"open"\s*:\s*"?([\d.,]+)"?', text)
        
        if close_m and open_m:
            c = safe_round(close_m.group(1))
            o = safe_round(open_m.group(1))
            chg = round(((c - o) / o) * 100, 2) if o > 0 else 0.0
            shariah = {"close": c, "open": o, "chgPct": chg}
            print(f"EGX33 Shariah fetched: close={c}, open={o}, chg={chg}%")
        else:
            # ✅ إصلاح: إزالة التنبيه المتكرر لـ Telegram لتجنب إزعاج المستخدم كل 15 دقيقة
            print("EGX33 Shariah: Could not parse price data from TradingView page. (Scraping fail)")
    except Exception as e:
        print(f"Error fetching EGX33 Shariah: {e}")
    return shariah

def send_report(force=False):
    print(f"[{datetime.now()}] Generating and sending report...")
    if not os.path.exists(STRINGS_PATH):
        # ✅ إصلاح: إرسال تنبيه Telegram بدلاً من الخروج الصامت
        reply_telegram("⚠️ <b>خطأ حرجي:</b> ملف strings.json غير موجود في المستودع! لن يُرسَل أي تقرير.")
        print("Strings file missing.")
        return
        
    with open(STRINGS_PATH, "r", encoding="utf-8") as f:
        s = json.load(f)
        
    # Get Prices, Indices & FX/Gold
    parsed_stocks, indices = fetch_all_data_tv(ALL_TICKERS, s)
    egx30 = indices.get("EGX30", {"close": 0.0, "open": 0.0, "chgPct": 0.0})
    egx70ewi = indices.get("EGX70EWI", {"close": 0.0, "open": 0.0, "chgPct": 0.0})
    egx100ewi = indices.get("EGX100EWI", {"close": 0.0, "open": 0.0, "chgPct": 0.0})
    egx33 = fetch_egx33_shariah()
    usdegp, xauusd = fetch_forex_gold()
    
    # Sort lists
    sorted_port = sorted([k for k in PORTFOLIO if k in parsed_stocks], key=lambda x: parsed_stocks[x]["chgPct"], reverse=True)
    # ترشيح الأسهم في قائمة المراقبة بحيث لا تظهر الأسهم المستثمر بها (المحفظة) مرتين
    sorted_watch = sorted([k for k in WATCHLIST if k in parsed_stocks and k not in PORTFOLIO], key=lambda x: parsed_stocks[x]["chgPct"], reverse=True)
    
    # Process and group News (both Live and Manual)
    news_blocks = []
    live_news = []
    manual_news = []
    
    # 1. Fetch live news from corporate sites and RSS feeds
    try:
        live_news = get_filtered_market_news(PORTFOLIO, WATCHLIST)
    except Exception as e:
        print("Error fetching live news:", e)
        
    # 2. Load manual news and classify under stock tags to group them with live news
    if os.path.exists(NEWS_PATH):
        try:
            with open(NEWS_PATH, "r", encoding="utf-8") as nf:
                content = nf.read().strip()
                if content:
                    for block in content.split("\n\n"):
                        lines = block.strip().split("\n")
                        if lines and lines[0].strip():
                            title = lines[0].strip()
                            # ✅ إصلاح: توليد رابط وهمي فريد وثابت للأخبار اليدوية التي لا تحتوي على رابط لمنع ضياعها في الفلترة
                            fallback_hash = hashlib.md5(title.encode('utf-8')).hexdigest()[:10]
                            link = lines[1].strip() if len(lines) >= 2 else f"manual://{fallback_hash}"
                            
                            # Match manual news to stock keywords
                            matched_stock = None
                            for ticker, keywords in STOCK_KEYWORDS.items():
                                for kw in keywords:
                                    if is_whole_word_match(kw, title):
                                        matched_stock = ticker
                                        break
                                if matched_stock:
                                    break
                                    
                            tag = f"[{matched_stock}]" if matched_stock else "[عام]"
                            live_news.append({
                                "tag": tag,
                                "title": title,
                                "link": link,
                                "source": "تحديث خاص"
                            })
        except Exception as e:
            print("Error loading manual news:", e)
            
    # 3. Group and analyze news blocks
    try:
        grouped = {}
        unique_live_news = []
        seen_titles = set()
        
        # ✅ إصلاح: منع تكرار الأخبار التي أُرسلت في تقارير سابقة لنفس اليوم (حتى عبر الـ Runners المختلفة)
        state_data, state_sha = get_github_state()
        egypt_tz_local = timezone(timedelta(hours=3))
        today_str = datetime.now(egypt_tz_local).strftime("%Y-%m-%d")
        
        # تصفير الأخبار إذا بدأ يوم جديد
        if state_data.get("date") != today_str:
            state_data = {"sent_links": [], "date": today_str, "summary_sent": False}
            
        sent_links = set(state_data.get("sent_links", []))
        
        for item in live_news:
            if item["title"] not in seen_titles:
                seen_titles.add(item["title"])
                unique_live_news.append(item)
                grouped.setdefault(item["tag"], []).append(item)
                
        def priority(t):
            ticker = t.replace("[", "").replace("]", "")
            if ticker in PORTFOLIO: return 0
            if ticker in WATCHLIST: return 1
            return 2
            
        sorted_tags = sorted(grouped.keys(), key=lambda t: (priority(t), t))
        
        # Analyze ONLY new items via AI
        ai_analyses = {}
        if grouped:
            ai_analyses = batch_analyze_news_with_gemini(grouped, PORTFOLIO, WATCHLIST)
        
        # ✅ تصفية التاجات المستبعدة بواسطة بوابة الذكاء الاصطناعي (AI Discard Gate)
        sorted_tags = [t for t in sorted_tags if t in grouped]
        
        for tag in sorted_tags:
            items_in_tag = grouped[tag]
            block = f"{s['rlm']}🔥 <b>{tag}</b>:\n"
            for item in items_in_tag[:3]:
                # ✅ إصلاح: ترميز العنوان والمصدر والرابط لمنع أخطاء التنسيق في تليجرام عند وجود رموز مثل & أو <
                title_esc = escape_html(item["title"])
                source_esc = escape_html(item["source"])
                link_esc = escape_html(item["link"])
                block += f"{s['rlm']}• {title_esc} ({source_esc}) <a href='{link_esc}'>[رابط مباشر]</a>\n"
                sent_links.add(item["link"])
            if tag in ai_analyses:
                block += f"{s['rlm']}{ai_analyses[tag]}\n"
            news_blocks.append(block.strip())
            
        # تحديث حالة الروابط المرسلة على GitHub
        if unique_live_news:
            state_data["sent_links"] = list(sent_links)
            update_github_state(state_data, state_sha)
            
    except Exception as e:
        print("Error grouping and analyzing news:", e)

    news_chunks = []
    current = []
    length = 0
    for block in news_blocks:
        b_len = len(block) + 2
        if length + b_len > 3800:  # زيادة الحد من 3500 إلى 3800 (Telegram يدعم 4096)
            if current:
                news_chunks.append("\n\n".join(current))
            current = [block]
            length = b_len
        else:
            current.append(block)
            length += b_len
    if current:
        news_chunks.append("\n\n".join(current))
        
    # Time Calculations (Egypt Cairo Timezone UTC+3)
    egypt_tz = timezone(timedelta(hours=3))
    now = datetime.now(egypt_tz)
    today = now.strftime("%Y/%m/%d")
    # ✅ إصلاح: لا نعتمد على %p (يختلف بحسب locale الـ server)
    hour_12 = now.hour % 12 or 12
    minute = now.strftime("%M")
    period = s["am"] if now.hour < 12 else s["pm"]
    time_display = f"{hour_12:02d}:{minute} {period}"
    
    total_minutes = now.hour * 60 + now.minute
    status_text = ""
    port_header = s.get('portfolio_title', 'أسهم مستثمر بها')
    watch_header = s.get('watchlist_title', 'أسهم شرعية أخرى للمتابعة')
    
    # Calculate last trading close date and time
    last_close_date = None
    last_close_time = "02:30 مساءً"
    weekday = now.weekday()
    
    if weekday in [4, 5]: # Friday, Saturday (Weekend)
        days_to_subtract = 1 if weekday == 4 else 2
        last_close_date = (now - timedelta(days=days_to_subtract)).strftime("%Y/%m/%d")
        status_text = f"🛑 <b>البورصة متوقفة حالياً (عطلة نهاية الأسبوع)</b>\n📊 <b>الأسعار أدناه هي إغلاق آخر جلسة عمل (جلسة {last_close_date}) الساعة {last_close_time}.</b>\n\n"
        port_header = f"📊 {port_header} (إغلاق جلسة {last_close_date})"
        watch_header = f"📊 {watch_header} (إغلاق جلسة {last_close_date})"
    elif total_minutes < 8 * 60 + 45: # Before market opens today (trading day)
        days_to_subtract = 3 if weekday == 6 else 1 # If Sunday, last was Thursday, else yesterday
        last_close_date = (now - timedelta(days=days_to_subtract)).strftime("%Y/%m/%d")
        status_text = f"⚠️ <b>السوق لم يفتح بعد (يفتح 08:45 صباحاً)</b>\n📊 <b>الأسعار أدناه هي إغلاق آخر جلسة عمل (جلسة {last_close_date}) الساعة {last_close_time}.</b>\n\n"
        port_header = f"📊 {port_header} (إغلاق جلسة {last_close_date})"
        watch_header = f"📊 {watch_header} (إغلاق جلسة {last_close_date})"
    elif total_minutes >= 14 * 60 + 30: # After market closed today (trading day)
        last_close_date = today
        status_text = f"🔒 <b>انتهت جلسة تداول اليوم (إغلاق 02:30 مساءً)</b>\n📈 <b>الأسعار أدناه هي أسعار الإغلاق النهائية لليوم (جلسة {last_close_date}).</b>\n\n"
        port_header = f"📈 {port_header} (إغلاق جلسة اليوم {last_close_date})"
        watch_header = f"📈 {watch_header} (إغلاق جلسة اليوم {last_close_date})"
    else:
        status_text = ""
        port_header = f"💼 {port_header} (حركة لحظية)"
        watch_header = f"📋 {watch_header} (حركة لحظية)"
        
    msg_portfolio = f"{s['rlm']}<b>{s['report_title']}</b>\n"
    msg_portfolio += f"{s['rlm']}<b>{s['date']}: {today} | {time_display}</b>\n"
    msg_portfolio += f"{s['rlm']}{s['line']}\n"
    if status_text:
        msg_portfolio += f"{s['rlm']}{status_text}"
    else:
        msg_portfolio += "\n"
        
    msg_portfolio += f"{s['rlm']}<b>{port_header}:</b>\n"
    for k in sorted_port:
        item = parsed_stocks[k]
        val = item["chgPct"]
        chg_str = f"+{val}%" if val > 0 else (f"{val}%" if val < 0 else "0.0%")
        dir_emoji = s["e_green"] if val > 0 else (s["e_red"] if val < 0 else s["e_white"])
        ticker_link = COMPANY_WEBSITES.get(k, "#")
        ticker_html = f"<a href='{ticker_link}'>{k}</a>" if ticker_link != "#" else k
        name_ar = COMPANY_NAMES_AR.get(k, k)
        rec_part = f" | {item['rec']}" if item.get("rec") else ""
        msg_portfolio += f"{s['rlm']}{dir_emoji} {name_ar}({ticker_html}): {item['open']} {s['e_arrow']} {item['close']} ({chg_str}){rec_part}\n"
        
    msg_watchlist = f"{s['rlm']}<b>{watch_header}:</b>\n"
    for k in sorted_watch:
        item = parsed_stocks[k]
        val = item["chgPct"]
        chg_str = f"+{val}%" if val > 0 else (f"{val}%" if val < 0 else "0.0%")
        dir_emoji = s["e_green"] if val > 0 else (s["e_red"] if val < 0 else s["e_white"])
        ticker_link = COMPANY_WEBSITES.get(k, "#")
        ticker_html = f"<a href='{ticker_link}'>{k}</a>" if ticker_link != "#" else k
        name_ar = COMPANY_NAMES_AR.get(k, k)
        rec_part = f" | {item['rec']}" if item.get("rec") else ""
        msg_watchlist += f"{s['rlm']}{dir_emoji} {name_ar}({ticker_html}): {item['open']} {s['e_arrow']} {item['close']} ({chg_str}){rec_part}\n"
    
    # === Build Indices & Currencies Section (separate message) ===
    def fmt_chg(val):
        if val > 0: return f"+{val}%"
        elif val < 0: return f"{val}%"
        return "0.0%"
    
    def dir_e(val):
        if val > 0: return s["e_green"]
        elif val < 0: return s["e_red"]
        return s["e_white"]
    
    msg_indices = f"{s['rlm']}<b>📊 المؤشرات:</b>\n"
    msg_indices += f"{s['rlm']}{dir_e(egx30['chgPct'])} <b>EGX30</b>:{s['rlm']} {egx30['open']} {s['e_arrow']} <b>{egx30['close']}</b> ({fmt_chg(egx30['chgPct'])})\n"
    msg_indices += f"{s['rlm']}{dir_e(egx33['chgPct'])} <b>EGX33 الشريعة</b>:{s['rlm']} {egx33['open']} {s['e_arrow']} <b>{egx33['close']}</b> ({fmt_chg(egx33['chgPct'])})\n"
    msg_indices += f"{s['rlm']}{dir_e(egx70ewi['chgPct'])} <b>EGX70 EWI</b>:{s['rlm']} {egx70ewi['open']} {s['e_arrow']} <b>{egx70ewi['close']}</b> ({fmt_chg(egx70ewi['chgPct'])})\n"
    msg_indices += f"{s['rlm']}{dir_e(egx100ewi['chgPct'])} <b>EGX100 EWI</b>:{s['rlm']} {egx100ewi['open']} {s['e_arrow']} <b>{egx100ewi['close']}</b> ({fmt_chg(egx100ewi['chgPct'])})\n"
    msg_indices += f"\n{s['rlm']}<b>💱 العملات والمعادن:</b>\n"
    msg_indices += f"{s['rlm']}{dir_e(usdegp['chgPct'])} <b>USD/EGP</b>:{s['rlm']} {usdegp['open']} {s['e_arrow']} <b>{usdegp['close']}</b> ({fmt_chg(usdegp['chgPct'])})\n"
    msg_indices += f"{s['rlm']}{dir_e(xauusd['chgPct'])} <b>{s['gold']}</b>:{s['rlm']} {xauusd['open']} {s['e_arrow']} <b>{xauusd['close']}</b>$ ({fmt_chg(xauusd['chgPct'])})\n"
    
    # ✅ إصلاح: استخدام دالة reply_telegram الموحدة والمؤمنة مع إرفاق أزرار التحكم اللحظية
    reply_telegram(msg_portfolio, reply_markup=PORTFOLIO_INLINE_KEYBOARD)
    reply_telegram(msg_watchlist)
    reply_telegram(msg_indices)
    
    # ✅ إضافة: إرسال النبض الفني والسوقي للذكاء الاصطناعي (AI Market Pulse) بشكل آمن
    try:
        ai_market_pulse = generate_market_ai_pulse(parsed_stocks, egx30, egx33, egx70ewi, sorted_port, sorted_watch)
        if ai_market_pulse:
            reply_telegram(ai_market_pulse)
    except Exception as e:
        print("Error sending AI market pulse:", e)
        
    # ✅ إضافة: رادار كبار المساهمين والصفقات الكبرى بشكل آمن
    try:
        insider_alerts = scan_insider_and_block_trades(live_news, [])
        insider_msg = format_insider_alerts(insider_alerts)
        if insider_msg:
            reply_telegram(insider_msg)
    except Exception as e:
        print("Error sending insider alerts:", e)
        
    # ✅ إضافة: فحص تنبيهات الأسعار المخصصة للمستخدم
    try:
        check_and_trigger_user_alerts(parsed_stocks, state_data, state_sha)
    except Exception as e:
        print("Error checking user alerts:", e)
        
    try:
        if news_chunks:
            for i, chunk in enumerate(news_chunks):
                if i == 0:
                    chunk = f"{s['rlm']}<b>{s['e_rocket']} {s['latest_news_developments']}:</b>\n" + chunk
                reply_telegram(chunk)
    except Exception as e:
        print("Error sending news chunks:", e)
            
    # ✅ إضافة: مسح الأخبار اليدوية القديمة تلقائياً من الملف على GitHub بعد إرسالها بنجاح لمنع تكرار إرسالها غداً
    if os.path.exists(NEWS_PATH):
        try:
            with open(NEWS_PATH, "r", encoding="utf-8") as f:
                has_content = bool(f.read().strip())
            if has_content:
                with open(NEWS_PATH, "w", encoding="utf-8") as f:
                    f.write("")
                update_github_news("")
                print("Manual news cleared automatically after sending report.")
        except Exception as e:
            print("Error clearing manual news:", e)

def get_session_context(dt=None):
    if dt is None:
        dt = datetime.now(timezone(timedelta(hours=3)))
    weekday = dt.weekday()
    # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
    if weekday == 3:  # Thursday (End of trading week in Egypt)
        return {
            "day_name": "الخميس",
            "is_thursday": True,
            "next_session_title": "خريطة الجلسة القادمة (الأحد - افتتاح الأسبوع)",
            "next_session_name": "الجلسة القادمة (الأحد - افتتاح الأسبوع)",
            "closing_title": "ملخص حركة اليوم وخريطة الجلسة القادمة (الأحد - افتتاح الأسبوع)",
            "closing_greeting": "🔒 <b>تم إغلاق تداولات الأسبوع بنجاح. نلقاكم يوم الأحد القادم بإذن الله مع افتتاح أسبوع تداول جديد.</b>",
            "prompt_day_context": (
                "تنبيه جوهري بالغ الأهمية: اليوم هو الخميس (ختام تداولات الأسبوع في البورصة المصرية)، "
                "وغداً الجمعة والسبت عطلة نهاية الأسبوع الرسمية (السوق مغلق). "
                "يُحظر تماماً ذكر عبارة 'جلسة الغد' أو 'توقعات الغد' أو الإشارة إلى أن غداً يوم تداول! "
                "بدلاً من ذلك، اكتب عن 'الجلسة القادمة (الأحد - افتتاح الأسبوع الجديد)' وقدّم تقييماً ختامياً للأسبوع وتطلعات افتتاح الأسبوع القادم يوم الأحد."
            ),
            "projection_header": "5. 🔮 <b>سيناريو وتوقعات الجلسة القادمة (الأحد - افتتاح الأسبوع):</b>",
            "rule_projection_header": "🔮 رؤية وخريطة افتتاح الأسبوع القادم (جلسة الأحد):"
        }
    elif weekday == 6:  # Sunday
        return {
            "day_name": "الأحد",
            "is_thursday": False,
            "next_session_title": "توقعات جلسة الغد (الإثنين)",
            "next_session_name": "جلسة الغد (الإثنين)",
            "closing_title": "ملخص حركة اليوم وتوقعات جلسة الغد (الإثنين)",
            "closing_greeting": "🔒 <b>تم إرسال تقرير الإقفال لجلسة اليوم. نلقاكم غداً (الإثنين) بإذن الله.</b>",
            "prompt_day_context": "الجلسة القادمة هي جلسة الغد (الإثنين).",
            "projection_header": "5. 🔮 <b>سيناريو وتوقعات جلسة الغد (الإثنين):</b>",
            "rule_projection_header": "🔮 رؤية وتوقعات جلسة الغد (الإثنين):"
        }
    elif weekday == 0:  # Monday
        return {
            "day_name": "الإثنين",
            "is_thursday": False,
            "next_session_title": "توقعات جلسة الغد (الثلاثاء)",
            "next_session_name": "جلسة الغد (الثلاثاء)",
            "closing_title": "ملخص حركة اليوم وتوقعات جلسة الغد (الثلاثاء)",
            "closing_greeting": "🔒 <b>تم إرسال تقرير الإقفال لجلسة اليوم. نلقاكم غداً (الثلاثاء) بإذن الله.</b>",
            "prompt_day_context": "الجلسة القادمة هي جلسة الغد (الثلاثاء).",
            "projection_header": "5. 🔮 <b>سيناريو وتوقعات جلسة الغد (الثلاثاء):</b>",
            "rule_projection_header": "🔮 رؤية وتوقعات جلسة الغد (الثلاثاء):"
        }
    elif weekday == 1:  # Tuesday
        return {
            "day_name": "الثلاثاء",
            "is_thursday": False,
            "next_session_title": "توقعات جلسة الغد (الأربعاء)",
            "next_session_name": "جلسة الغد (الأربعاء)",
            "closing_title": "ملخص حركة اليوم وتوقعات جلسة الغد (الأربعاء)",
            "closing_greeting": "🔒 <b>تم إرسال تقرير الإقفال لجلسة اليوم. نلقاكم غداً (الأربعاء) بإذن الله.</b>",
            "prompt_day_context": "الجلسة القادمة هي جلسة الغد (الأربعاء).",
            "projection_header": "5. 🔮 <b>سيناريو وتوقعات جلسة الغد (الأربعاء):</b>",
            "rule_projection_header": "🔮 رؤية وتوقعات جلسة الغد (الأربعاء):"
        }
    elif weekday == 2:  # Wednesday
        return {
            "day_name": "الأربعاء",
            "is_thursday": False,
            "next_session_title": "توقعات جلسة الغد (الخميس - ختام الأسبوع)",
            "next_session_name": "جلسة الغد (الخميس - ختام الأسبوع)",
            "closing_title": "ملخص حركة اليوم وتوقعات جلسة الغد (الخميس - ختام الأسبوع)",
            "closing_greeting": "🔒 <b>تم إرسال تقرير الإقفال لجلسة اليوم. نلقاكم غداً (الخميس) بإذن الله.</b>",
            "prompt_day_context": "الجلسة القادمة هي جلسة الغد (الخميس - ختام تداولات الأسبوع).",
            "projection_header": "5. 🔮 <b>سيناريو وتوقعات جلسة الغد (الخميس - ختام الأسبوع):</b>",
            "rule_projection_header": "🔮 رؤية وتوقعات جلسة الغد (الخميس - ختام الأسبوع):"
        }
    else:  # Weekend (Friday=4, Saturday=5)
        return {
            "day_name": "الجمعة" if weekday == 4 else "السبت",
            "is_thursday": False,
            "next_session_title": "توقعات جلسة الأحد القادمة",
            "next_session_name": "جلسة الأحد القادمة",
            "closing_title": "ملخص جلسة البورصة وتوقعات جلسة الأحد",
            "closing_greeting": "🔒 <b>البورصة في عطلة نهاية الأسبوع. نلقاكم يوم الأحد القادم بإذن الله.</b>",
            "prompt_day_context": "البورصة في عطلة نهاية الأسبوع، والجلسة القادمة هي جلسة الأحد القادم.",
            "projection_header": "5. 🔮 <b>سيناريو وتوقعات جلسة الأحد القادمة:</b>",
            "rule_projection_header": "🔮 رؤية وتوقعات جلسة الأحد القادمة:"
        }

def generate_daily_summary_ai(stocks_data, indices_data, fx_gold_data, grouped_news, strings, ctx=None):
    if ctx is None:
        ctx = get_session_context()
        
    # Construct details of today's market movements
    market_details = "--- أداء أسهم المحفظة الأساسية ---\n"
    for ticker in PORTFOLIO:
        if ticker in stocks_data:
            info = stocks_data[ticker]
            market_details += f"- سهم {ticker}: الافتتاح: {info['open']}، الإغلاق: {info['close']}، التغير: {info['chgPct']:+.2f}%\n"
            
    market_details += "\n--- أبرز أسهم قائمة المتابعة الشريعية ---\n"
    for ticker in WATCHLIST:
        if ticker in stocks_data and ticker not in PORTFOLIO:
            info = stocks_data[ticker]
            if abs(info['chgPct']) >= 0.5:
                market_details += f"- سهم {ticker}: الافتتاح: {info['open']}، الإغلاق: {info['close']}، التغير: {info['chgPct']:+.2f}%\n"
        
    market_details += "\n--- أداء المؤشرات والعملات اليوم ---\n"
    for idx, info in indices_data.items():
        market_details += f"- مؤشر {idx}: الافتتاح: {info['open']}، الإغلاق: {info['close']}، التغير: {info['chgPct']:+.2f}%\n"
    for key, info in fx_gold_data.items():
        market_details += f"- {key}: الافتتاح: {info['open']}، الإغلاق: {info['close']}، التغير: {info['chgPct']:+.2f}%\n"
        
    market_details += "\n--- أخبار وإفصاحات الشركات اليوم ---\n"
    for tag, items in grouped_news.items():
        market_details += f"=== {tag} ===\n"
        for item in items:
            market_details += f"- {item['title']} (المصدر: {item['source']})\n"
            
    prompt = (
        f"أنت كبير المحللين الماليين واستراتيجي التداول في البورصة المصرية.\n"
        f"مهمتك هي إعداد تقرير '{ctx['closing_title']}' لجلسة البورصة بعد الإغلاق، ليكون تقريراً تحليلياً متكاملاً وواضحاً وشاملاً للمستثمر.\n"
        f"{ctx['prompt_day_context']}\n\n"
        "التقرير يجب أن يكون باللغة العربية الفصحى وبتنسيق HTML أنيق للإرسال على تليجرام، ويحتوي على الأقسام التالية:\n\n"
        "1. 📝 <b>قراءة عامة للجلسة وسلوك السيولة:</b> تحليل دقيق لطبيعة الجلسة اليوم (هل كانت تجميع أم جني أرباح أم شراء مؤسسي، وما اتجاه السيولة العام).\n"
        "2. 📊 <b>حركة المؤشرات الرئيسية والعملات:</b> تحليل أداء مؤشر الشريعة EGX33 ومؤشر EGX30 وحركة الدولار والذهب، وتأثير ذلك على السوق.\n"
        "3. 💼 <b>تحليل مفصل لأسهم المحفظة الأساسية:</b> (أهم قسم في التقرير) قدم تحليلاً فاحصاً ومفصلاً لأسهم المحفظة وخاصة الأسهم النشطة اليوم (مثل TMGH, ADIB, ETEL, FWRY... إلخ):\n"
        "   - ما الذي حدث للسهم ولماذا تحرك بهذا الشكل (ربطاً بالأخبار أو حركة السيولة وجني الأرباح)؟\n"
        "   - مستويات الدعم والمقاومة الفنية الحالية.\n"
        f"   - التوصية والرؤية الفنية لـ {ctx['next_session_name']} (احتفاظ / جني أرباح / تجميع).\n"
        "4. 🚀 <b>أبرز الفرص والأسهم النشطة بالسوق:</b> رصد سريع للأسهم الرابحة وأسباب صعودها وأبرز الأسهم المتراجعة.\n"
        f"{ctx['projection_header']} سيناريو حركة المؤشرات، ومستويات الدعم والمقاومة الحرجة للمؤشر العام.\n\n"
        "شروط التنسيق والجودة:\n"
        "- اكتب بلغة مالية واضحة، سهلة الفهم، شارحة ومباشرة.\n"
        "- استخدم وسوم HTML المسموحة في تليجرام فقط للتنسيق (مثل <b>, <i>, <code>, <u>).\n"
        "- لا تستخدم علامات الماركداون (مثل ** أو `) إطلاقاً، اعتمد بالكامل على وسوم HTML.\n"
        "- اجعل التقرير غنياً بالمعلومات والتحليل المعمق المفيد عملياً للمستثمر.\n\n"
        f"بيانات السوق والأخبار المتاحة لجلسة اليوم:\n{market_details}"
    )
    return ask_ai(prompt)

def generate_rule_based_daily_summary(stocks_data, indices_data, fx_gold_data, grouped_news, strings, ctx=None):
    if ctx is None:
        ctx = get_session_context()
        
    res = "<b>📝 ملخص أداء جلسة اليوم وأهم التحركات:</b>\n"
    
    # 1. Indices & Currencies
    res += "\n<b>📊 المؤشرات والعملات:</b>\n"
    for k, v in indices_data.items():
        chg_icon = "🟢" if v["chgPct"] > 0 else ("🔴" if v["chgPct"] < 0 else "⚪")
        res += f"{chg_icon} <b>{k}:</b> إغلاق {v['close']} ({v['chgPct']:+.2f}%)\n"
    for k, v in fx_gold_data.items():
        chg_icon = "🟢" if v["chgPct"] > 0 else ("🔴" if v["chgPct"] < 0 else "⚪")
        res += f"{chg_icon} <b>{k}:</b> {v['close']} ({v['chgPct']:+.2f}%)\n"
        
    # 2. Portfolio Performance & Technical Stance (مرتبة تنازلياً من الأعلى ربحاً إلى الأقل)
    res += "\n<b>💼 أداء وتحليل أسهم المحفظة الأساسية:</b>\n"
    sorted_portfolio_stocks = sorted(
        [t for t in PORTFOLIO if t in stocks_data],
        key=lambda t: stocks_data[t].get("chgPct", 0),
        reverse=True
    )
    for t in sorted_portfolio_stocks:
        info = stocks_data[t]
        chg = info["chgPct"]
        if chg > 1.0:
            stance = "زخم صاعد واختراق مستويات مقاومة"
        elif chg > 0.0:
            stance = "أداء إيجابي متماسك بدعم قوى شرائية"
        elif chg == 0.0:
            stance = "حركة عرضية متوازنة بانتظار سيولة جديدة"
        elif chg > -1.0:
            stance = "تصحيح طفيف وطبيعي ضمن النطاق العرضي"
        else:
            stance = "جني أرباح وتراجع، مع ترقب مناطق الدعم للارتداد"
        icon = "🟢" if chg > 0 else ("🔴" if chg < 0 else "⚪")
        name_ar = COMPANY_NAMES_AR.get(t, t)
        res += f"{icon} <b>{name_ar} ({t}):</b> {info['close']} ج (<b>{chg:+.2f}%</b>) — {stance}\n"

    # 3. Top Movers in Market
    gainers = []
    losers = []
    for ticker, info in stocks_data.items():
        if info["chgPct"] > 0.3:
            gainers.append((ticker, info["close"], info["chgPct"]))
        elif info["chgPct"] < -0.3:
            losers.append((ticker, info["close"], info["chgPct"]))
            
    gainers.sort(key=lambda x: x[2], reverse=True)
    losers.sort(key=lambda x: x[2])
    
    if gainers:
        res += "\n<b>🚀 أبرز الأسهم الصاعدة اليوم (الأعلى ربحاً):</b>\n"
        for t, c, chg in gainers[:5]:
            name_ar = COMPANY_NAMES_AR.get(t, t)
            res += f"• <b>{name_ar} ({t}):</b> {c} جنيه (🟢 <b>{chg:+.2f}%</b>)\n"
            
    if losers:
        res += "\n<b>🔻 أبرز الأسهم المتراجعة (جني أرباح/تصحيح):</b>\n"
        for t, c, chg in losers[:5]:
            name_ar = COMPANY_NAMES_AR.get(t, t)
            res += f"• <b>{name_ar} ({t}):</b> {c} جنيه (🔴 <b>{chg:+.2f}%</b>)\n"
            
    # 3. Key News
    if grouped_news:
        res += "\n<b>📰 أهم إفصاحات وأخبار الشركات اليوم:</b>\n"
        count = 0
        for tag, items in grouped_news.items():
            if count >= 6:
                break
            for item in items[:2]:
                res += f"• <b>{tag}</b>: {item['title']}\n"
                count += 1
                if count >= 6:
                    break
                    
    # 4. Market Projection
    egx30_chg = indices_data.get("EGX30", {}).get("chgPct", 0)
    res += f"\n<b>{ctx['rule_projection_header']}</b>\n"
    if egx30_chg > 0.5:
        res += "استمرار الزخم الشرائي والسيولة المؤسسية يدعم مواصلة الصعود واختبار مستويات مقاومة جديدة مع الحفاظ على الحذر عند القمم السعرية."
    elif egx30_chg < -0.5:
        res += "حركة تصحيحية وجني أرباح صحي لتخفيف المؤشرات، يُتوقع ظهور قوى شرائية ارتدادية عند مستويات الدعم الرئيسية للأسهم القيادية."
    else:
        res += "حركة عرضية متوازنة بين قوى الشراء وجني الأرباح، مع ترقب مستويات سيولة جديدة لتحديد اتجاه كسر المسار العرضي."
        
    return res

def send_daily_summary():
    ctx = get_session_context()
    print(f"[{datetime.now()}] Generating and sending daily summary report ({ctx['closing_title']})...")
    if not os.path.exists(STRINGS_PATH):
        reply_telegram("⚠️ <b>خطأ حرجي:</b> ملف strings.json غير موجود في المستودع!")
        return False
        
    with open(STRINGS_PATH, "r", encoding="utf-8") as f:
        s = json.load(f)
        
    parsed_stocks, indices = fetch_all_data_tv(ALL_TICKERS, s)
    egx30 = indices.get("EGX30", {"close": 0.0, "open": 0.0, "chgPct": 0.0})
    egx70ewi = indices.get("EGX70EWI", {"close": 0.0, "open": 0.0, "chgPct": 0.0})
    egx100ewi = indices.get("EGX100EWI", {"close": 0.0, "open": 0.0, "chgPct": 0.0})
    egx33 = fetch_egx33_shariah()
    usdegp, xauusd = fetch_forex_gold()
    
    live_news = []
    try:
        live_news = get_filtered_market_news(PORTFOLIO, WATCHLIST)
    except Exception as e:
        print("Error fetching live news for daily summary:", e)
        
    grouped = {}
    seen_titles = set()
    for item in live_news:
        if item["title"] not in seen_titles:
            seen_titles.add(item["title"])
            grouped.setdefault(item["tag"], []).append(item)
            
    stocks_data = parsed_stocks
    indices_data = {
        "EGX30": egx30,
        "EGX33 الشريعة": egx33,
        "EGX70 EWI": egx70ewi,
        "EGX100 EWI": egx100ewi
    }
    fx_gold_data = {
        "USD/EGP": usdegp,
        "GOLD": xauusd
    }
    
    reply_telegram(f"🔄 جاري إعداد ملخص حركة اليوم والتحليل الختامي و{ctx['next_session_title']}...")
    summary_text = generate_daily_summary_ai(stocks_data, indices_data, fx_gold_data, grouped, s, ctx)
    
    # Fallback to rule-based summary if AI failed or returned error string
    if not summary_text or "عذراً" in summary_text or len(summary_text.strip()) < 50:
        print("AI summary empty or failed. Generating rich rule-based financial summary fallback...")
        summary_text = generate_rule_based_daily_summary(stocks_data, indices_data, fx_gold_data, grouped, s, ctx)
        
    header = f"📌 <b>{ctx['closing_title']} {datetime.now(timezone(timedelta(hours=3))).strftime('%Y/%m/%d')}</b>\n\n"
    reply_telegram(header + summary_text)
    
    # ✅ إضافة: رادار التوزيعات النقدية وقرارات الشركات
    div_actions = scan_dividends_and_actions(live_news, [])
    div_msg = format_dividends_alerts(div_actions)
    if div_msg:
        reply_telegram(div_msg)
        
    # ✅ إضافة: توليد وإرسال الشارت الفني البصري
    chart_file = generate_market_chart(indices_data, stocks_data)
    if chart_file and os.path.exists(chart_file):
        send_telegram_photo(chart_file, caption=f"📊 <b>شارت الأداء الفني ومؤشر الزخم RSI لجلسة {datetime.now(timezone(timedelta(hours=3))).strftime('%Y/%m/%d')}</b>")
        
    # ✅ إضافة: كشف حساب المحفظة الاستثمارية P&L اللحظي
    try:
        state_data, _ = get_github_state()
        user_holdings = state_data.get("holdings", {})
        if user_holdings:
            pnl_data = calculate_portfolio_pnl(user_holdings, stocks_data)
            if pnl_data and pnl_data.get("details"):
                pnl_msg = format_portfolio_pnl_message(pnl_data)
                reply_telegram(pnl_msg)
    except Exception as e:
        print("Error sending daily portfolio summary:", e)
        
    return True

def send_detailed_rsi_report():
    """توليد وبث بيان مفصل ورادار متقدم لمؤشر القوة النسبية (RSI 14) لجميع الأسهم الشرعية."""
    print(f"[{datetime.now()}] Generating detailed RSI report...")
    s = {}
    if os.path.exists(STRINGS_PATH):
        with open(STRINGS_PATH, "r", encoding="utf-8") as f:
            s = json.load(f)
            
    parsed_stocks, _ = fetch_all_data_tv(ALL_TICKERS, s)
    
    stock_rsi_list = []
    for ticker in ALL_TICKERS:
        if ticker in parsed_stocks:
            info = parsed_stocks[ticker]
            rsi_val = info.get("rsi")
            if rsi_val is not None:
                name_ar = COMPANY_NAMES_AR.get(ticker, ticker)
                stock_rsi_list.append({
                    "ticker": ticker,
                    "name": name_ar,
                    "rsi": rsi_val,
                    "close": info.get("close", 0.0),
                    "chg": info.get("chgPct", 0.0),
                    "rec": info.get("rec", "")
                })
                
    if not stock_rsi_list:
        reply_telegram("⚠️ تعذر جلب بيانات مؤشر RSI حالياً من الخادم.")
        return False
        
    stock_rsi_list.sort(key=lambda x: x["rsi"], reverse=True)
    
    now = datetime.now(timezone(timedelta(hours=3)))
    today_str = now.strftime("%Y/%m/%d")
    hour_12 = now.hour % 12 or 12
    minute = now.strftime("%M")
    period = "صباحاً" if now.hour < 12 else "مساءً"
    time_str = f"{hour_12:02d}:{minute} {period}"
    
    overbought = [x for x in stock_rsi_list if x["rsi"] >= 70]
    bullish = [x for x in stock_rsi_list if 55 <= x["rsi"] < 70]
    neutral = [x for x in stock_rsi_list if 40 <= x["rsi"] < 55]
    oversold = [x for x in stock_rsi_list if x["rsi"] < 40]
    
    msg = f"⚡ <b>البيان المفصل ورادار مؤشر القوة النسبية RSI (14)</b>\n"
    msg += f"📅 <b>التاريخ:</b> {today_str} | {time_str}\n"
    msg += f"📊 <b>إجمالي الأسهم المفحوصة:</b> {len(stock_rsi_list)} سهماً شرعياً\n"
    msg += "━━━━━━━━━━━━━━━━━━━\n\n"
    
    msg += "<b>📌 توزيع السيولة وقوة الزخم:</b>\n"
    msg += f"• ⚠️ <b>تشبع شرائي (RSI ≥ 70):</b> {len(overbought)} أسهم (قمم سعرية)\n"
    msg += f"• 🟢 <b>زخم صاعد إيجابي (RSI 55-69):</b> {len(bullish)} أسهم\n"
    msg += f"• 🟡 <b>نطاق عرضي وتجميع (RSI 40-54):</b> {len(neutral)} أسهم\n"
    msg += f"• 💎 <b>تشبع بيعي/قيعان (RSI &lt; 40):</b> {len(oversold)} أسهم\n\n"
    msg += "━━━━━━━━━━━━━━━━━━━\n\n"
    
    if overbought:
        msg += "⚠️ <b>منطقة التشبع الشرائي (RSI ≥ 70) - [حذر من الشراء عند القمة]:</b>\n"
        for item in overbought:
            sign = "+" if item["chg"] > 0 else ""
            msg += f"• <b>{item['name']}({item['ticker']}):</b> <code>RSI {item['rsi']:.1f}</code> | {item['close']} ج ({sign}{item['chg']}%) | {item['rec']}\n"
        msg += "\n"
        
    if bullish:
        msg += "🟢 <b>منطقة الزخم الصاعد الإيجابي (RSI 55 - 69.9):</b>\n"
        for item in bullish:
            sign = "+" if item["chg"] > 0 else ""
            msg += f"• <b>{item['name']}({item['ticker']}):</b> <code>RSI {item['rsi']:.1f}</code> | {item['close']} ج ({sign}{item['chg']}%) | {item['rec']}\n"
        msg += "\n"
        
    if neutral:
        msg += "🟡 <b>منطقة التجميع والنطاق العرضي (RSI 40 - 54.9):</b>\n"
        for item in neutral:
            sign = "+" if item["chg"] > 0 else ""
            msg += f"• <b>{item['name']}({item['ticker']}):</b> <code>RSI {item['rsi']:.1f}</code> | {item['close']} ج ({sign}{item['chg']}%) | {item['rec']}\n"
        msg += "\n"
        
    if oversold:
        msg += "💎 <b>منطقة التشبع البيعي والقيعان (RSI &lt; 40) - [فرص ارتداد]:</b>\n"
        for item in oversold:
            sign = "+" if item["chg"] > 0 else ""
            msg += f"• <b>{item['name']}({item['ticker']}):</b> <code>RSI {item['rsi']:.1f}</code> | {item['close']} ج ({sign}{item['chg']}%) | {item['rec']}\n"
        msg += "\n"
        
    msg += "━━━━━━━━━━━━━━━━━━━\n"
    msg += "💡 <b>خلاصة فنية:</b> الأسهم ذات RSI أعلى من 70 هي الأكثر عرضة لجني الأرباح وتهدئة المؤشرات، بينما الأسهم قرب 30 تشير لتشبع بيعي مفرط واقتراب مناطق الارتداد."
    
    reply_telegram(msg, reply_markup=PORTFOLIO_INLINE_KEYBOARD)
    return True

def handle_telegram_command(text):
    text_clean = text.strip()
    text_lower = text_clean.lower()
    if text_lower.startswith("/start") or text_lower.startswith("/help") or "مساعدة" in text_clean or "مساعده" in text_clean or "أوامر" in text_clean:
        help_msg = (
            "<b>🤖 أهلاً بك في منصة تداول أسهم الشريعة المؤسسية!</b>\n\n"
            "إليك الأزرار الذكية المتاحة للضغط المباشر:\n"
            "💼 <b>[💼 محفظتي الاستثمارية]</b> أو <code>/portfolio</code> : كشف حساب أرباح/خسائر محفظتك اللحظي (P&L).\n"
            "📊 <b>[📊 تقرير الأسعار]</b> أو <code>/report</code> : بث فوري لأحدث الأسعار والمؤشرات الفنية.\n"
            "⚡ <b>[⚡ بيان مفصل RSI]</b> أو <code>/rsi</code> : رادار مؤشر القوة النسبية RSI والتشبعات لجميع الأسهم.\n"
            "📌 <b>[📌 ملخص حركة اليوم]</b> أو <code>/summary</code> : ملخص الجلسة والتحليل الفني وتوقعات الغد.\n"
            "⚙️ <b>[⚙️ حالة النظام]</b> أو <code>/status</code> : التحقق من اتصال البوت وسلسلة الترحيل 24/7.\n"
            "➕ <code>/set_holding [السهم] [الكمية] [سعر_الشراء]</code> : لتعديل أو تسجيل أسهم محفظتك.\n"
            "⚖️ <code>/compare [سهم1] [سهم2]</code> : مقارنة فنية واستثمارية مباشرة بالذكاء الاصطناعي.\n"
            "🎯 <code>/alert [السهم] [> أو <] [السعر]</code> : ضبط تنبيه سعري فوري.\n"
            "🧠 <code>/ask [سؤالك]</code> : استشارة المحلل المالي الذكي (Claude/Gemini)."
        )
        reply_telegram(help_msg, reply_markup=DEFAULT_KEYBOARD)
        
    elif text_lower.startswith("/portfolio") or "محفظت" in text_clean or "محفظه" in text_clean:
        try:
            state_data, _ = get_github_state()
            holdings = state_data.get("holdings", {})
            s = {}
            if os.path.exists(STRINGS_PATH):
                with open(STRINGS_PATH, "r", encoding="utf-8") as f:
                    s = json.load(f)
            parsed_stocks, _ = fetch_all_data_tv(ALL_TICKERS, s)
            pnl_data = calculate_portfolio_pnl(holdings, parsed_stocks)
            reply_telegram(format_portfolio_pnl_message(pnl_data), reply_markup=PORTFOLIO_INLINE_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ حدث خطأ أثناء حساب المحفظة: {e}")
            
    elif text_lower.startswith("/report") or "تقرير الأسعار" in text_clean or "تقرير الاسعار" in text_clean or "تحديث فوري" in text_clean:
        reply_telegram("🔄 جاري تحديث بيانات السوق وبث التقرير اللحظي فوراً...")
        send_report(force=True)
        
    elif text_lower.startswith("/rsi") or "rsi" in text_lower or "بيان مفصل" in text_clean:
        reply_telegram("🔄 جاري إعداد البيان المفصل لمؤشر RSI لجميع الأسهم...")
        send_detailed_rsi_report()
        
    elif text_lower.startswith("/summary") or "ملخص" in text_clean:
        reply_telegram("🔄 جاري إعداد ملخص حركة اليوم والتحليل الفني...")
        send_daily_summary()
            
    elif text_lower.startswith("/set_holding") or text_lower.startswith("/حيازة"):
        parts = text.split()
        if len(parts) < 4:
            reply_telegram("⚠️ التنسيق المطلوب:\n<code>/set_holding [السهم] [الكمية] [سعر_الشراء]</code>\nمثال:\n<code>/set_holding FWRY 2000 18.50</code>")
            return
        ticker = parts[1].upper().replace("[", "").replace("]", "")
        try:
            qty = float(parts[2].replace(",", ""))
            buy_price = float(parts[3].replace(",", ""))
            state_data, state_sha = get_github_state()
            if "holdings" not in state_data:
                state_data["holdings"] = {}
            state_data["holdings"][ticker] = {"qty": qty, "buy_price": buy_price}
            if update_github_state(state_data, state_sha):
                reply_telegram(f"✅ <b>تم تحديث المحفظة بنجاح:</b>\nتم تسجيل حيازة <b>{ticker}</b>: {qty:,.0f} سهم بسعر {buy_price:.2f} ج.م.\nيمكنك الآن الضغط على زر <b>[💼 محفظتي الاستثمارية]</b> لعرض الأرباح اللحظية.")
            else:
                reply_telegram("❌ فشل حفظ بيانات المحفظة على الخادم. يرجى المحاولة لاحقاً.")
        except ValueError:
            reply_telegram("⚠️ الكمية وسعر الشراء يجب أن تكون أرقاماً صحيحة.")
            
    elif text_lower.startswith("/compare") or text_lower.startswith("/مقارنة") or text_lower.startswith("/مقارنه"):
        parts = text.split()
        if len(parts) < 3:
            reply_telegram("⚠️ التنسيق المطلوب:\n<code>/compare [سهم1] [سهم2]</code>\nمثال:\n<code>/compare TMGH ETEL</code>")
            return
        t1 = parts[1].upper().replace("[", "").replace("]", "")
        t2 = parts[2].upper().replace("[", "").replace("]", "")
        reply_telegram(f"🔄 جاري المقارنة بين سهمي <b>{t1}</b> و <b>{t2}</b> عبر الذكاء الاصطناعي...")
        try:
            parsed_stocks, _ = fetch_all_data_tv([t1, t2], {})
            d1 = parsed_stocks.get(t1, {})
            d2 = parsed_stocks.get(t2, {})
            c_prompt = (
                f"أنت خبير مالي ومحلل أسهم في البورصة المصرية.\n"
                f"قارن تحليلياً واستثمارياً بين سهم {t1} وسهم {t2} بناءً على المؤشرات الفنية والأسعار:\n"
                f"- سهم {t1}: السعر {d1.get('close')} ج.م (التغير {d1.get('chgPct')}%) | RSI: {d1.get('rsi')} | التوصية: {d1.get('rec')}\n"
                f"- سهم {t2}: السعر {d2.get('close')} ج.م (التغير {d2.get('chgPct')}%) | RSI: {d2.get('rsi')} | التوصية: {d2.get('rec')}\n\n"
                f"المطلوب: مقارنة سريعة من 3 نقاط:\n"
                f"1. المقارنة الفنية والزخم.\n"
                f"2. مستويات الدعم والمقاومة لكل سهم.\n"
                f"3. الرأي النهائي أيهما يحمل فرصة أفضل وأقل مخاطرة حالياً للمستثمر."
            )
            comparison_res = ask_ai(c_prompt)
            reply_telegram(f"⚖️ <b>مقارنة استثمارية بين {t1} و {t2}:</b>\n\n{comparison_res}")
        except Exception as e:
            reply_telegram(f"⚠️ خطأ أثناء إجراء المقارنة: {e}")
            
    elif text_lower.startswith("/alert") or text_lower.startswith("/تنبيه"):
        parts = text.split()
        if len(parts) < 4 or parts[2] not in [">", "<", ">=", "<="]:
            reply_telegram("⚠️ التنسيق المطلوب:\n<code>/alert [السهم] [> أو <] [السعر]</code>\nمثال:\n<code>/alert FWRY > 20.00</code>")
            return
        ticker = parts[1].upper().replace("[", "").replace("]", "")
        cond = parts[2]
        try:
            price = float(parts[3].replace(",", ""))
            state_data, state_sha = get_github_state()
            if "alerts" not in state_data:
                state_data["alerts"] = []
            state_data["alerts"].append({"ticker": ticker, "cond": cond, "price": price})
            if update_github_state(state_data, state_sha):
                reply_telegram(f"🎯 <b>تم تفعيل التنبيه السعري:</b>\nسيصلك إشعار فوري عند وصول <b>{ticker}</b> إلى <b>{cond} {price:.2f} ج.م</b>.")
            else:
                reply_telegram("❌ فشل تسجيل التنبيه على الخادم.")
        except ValueError:
            reply_telegram("⚠️ السعر يجب أن يكون رقماً صحيحاً.")
        
    elif text_lower.startswith("/add_news"):
        news_content = text[len("/add_news"):].strip()
        if not news_content:
            reply_telegram("⚠️ يرجى كتابة نص الخبر بعد الأمر. مثال:\n<code>/add_news خبر جديد هنا</code>")
            return
            
        local_content = ""
        if os.path.exists(NEWS_PATH):
            with open(NEWS_PATH, "r", encoding="utf-8") as nf:
                local_content = nf.read().strip()
                
        updated_content = news_content if not local_content else f"{local_content}\n\n{news_content}"
        
        with open(NEWS_PATH, "w", encoding="utf-8") as nf:
            nf.write(updated_content)
            
        if update_github_news(updated_content):
            reply_telegram("✅ تمت إضافة الخبر وتحديث الملف على GitHub بنجاح!")
        else:
            reply_telegram("❌ فشل تحديث الخبر على GitHub. يرجى التحقق من الاتصال.")
            
    elif text_lower.startswith("/clear_news") or text_lower.startswith("/مسح"):
        if os.path.exists(NEWS_PATH):
            with open(NEWS_PATH, "w", encoding="utf-8") as nf:
                nf.write("")
            if update_github_news(""):
                reply_telegram("✅ تم مسح جميع الأخبار اليدوية بنجاح!")
            else:
                reply_telegram("❌ تم مسح الأخبار محلياً لكن فشل التحديث على GitHub.")
        else:
            reply_telegram("⚠️ لا توجد أخبار يدوية محفوظة حالياً لتتم إزالتها.")
            
    elif text_lower.startswith("/ask") or text_lower.startswith("/اسأل"):
        question = text[len("/ask"):].strip() if text_lower.startswith("/ask") else text[len("/اسأل"):].strip()
        if not question:
            reply_telegram("⚠️ يرجى كتابة السؤال بعد الأمر. مثال:\n<code>/ask ما توقعاتك لسهم طلعت مصطفى؟</code>")
            return
        reply_telegram("🔄 جاري التفكير والتحليل...")
        reply_telegram(ask_ai(question))
        
    elif text_lower.startswith("/status") or "حالة النظام" in text_clean or "حاله النظام" in text_clean or "حالة" in text_clean or "حاله" in text_clean:
        import time
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        status_msg = (
            "🟢 <b>حالة البوت: متصل ويعمل بنجاح (24/7 Cloud Relay)</b>\n"
            f"🕒 <b>وقت الخادم (UTC):</b> {current_time}\n"
            f"🧠 <b>المحرك الذكي:</b> {GEMINI_MODEL}\n"
            "⚙️ <b>العملية:</b> قيد المراقبة المستمرة، وسلسلة الترحيل السحابي نشطة."
        )
        reply_telegram(status_msg, reply_markup=DEFAULT_KEYBOARD)
        
    else:
        reply_telegram("🔄 جاري معالجة سؤالك واستشارة الذكاء الاصطناعي...")
        reply_telegram(ask_ai(text))

def poll_telegram_messages():
    global offset
    if not BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"offset": offset, "timeout": 8}  # ✅ رُفع من 5 إلى 8 ثوانٍ
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            updates = r.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                
                # 1. معالجة نقرات الأزرار المدمجة التفاعلية (Inline Keyboard Buttons)
                if "callback_query" in update:
                    cb = update["callback_query"]
                    cb_id = cb.get("id")
                    chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                    if chat_id == CHAT_ID:
                        cb_data = cb.get("data", "")
                        try:
                            requests.post(
                                f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
                                json={"callback_query_id": cb_id},
                                timeout=5
                            )
                        except Exception:
                            pass
                            
                        if cb_data == "btn_portfolio":
                            handle_telegram_command("/portfolio")
                        elif cb_data == "btn_report":
                            handle_telegram_command("/report")
                        elif cb_data == "btn_rsi":
                            handle_telegram_command("/rsi")
                        elif cb_data == "btn_summary":
                            handle_telegram_command("/summary")
                        elif cb_data == "btn_status":
                            handle_telegram_command("/status")
                    continue
                
                # 2. معالجة الرسائل النصية ونقرات الأزرار السفلية الثابتة (Reply Keyboard)
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if chat_id != CHAT_ID:
                    continue
                # ✅ إصلاح: تجاهل الرسائل الأقدم من وقت بدء التشغيل
                msg_date = msg.get("date", 0)
                if msg_date < _startup_epoch:
                    continue
                text = msg.get("text", "").strip()
                if text:
                    handle_telegram_command(text)
    except Exception as e:
        print("Polling error:", e)

def get_next_market_open(now):
    # Target time is 08:45 AM
    candidate = now.replace(hour=8, minute=45, second=0, microsecond=0)
    # If today is already past 08:45 AM or today is weekend, advance to tomorrow
    if now >= candidate or now.weekday() in [4, 5]:
        candidate += timedelta(days=1)
        candidate = candidate.replace(hour=8, minute=45, second=0, microsecond=0)
    
    # Keep advancing day until candidate falls on a trading day (Sunday=6, Mon=0, Tue=1, Wed=2, Thu=3)
    # Weekend in Egypt: Friday=4, Saturday=5
    while candidate.weekday() in [4, 5]:
        candidate += timedelta(days=1)
        
    return candidate

def enter_perpetual_sleep_and_relay():
    egypt_tz = timezone(timedelta(hours=3))
    now = datetime.now(egypt_tz)
    target = get_next_market_open(now)
    total_seconds = (target - now).total_seconds()
    
    print(f"[{now.strftime('%H:%M:%S')}] Entering Perpetual 24/7 Cloud Relay. Next market session at {target.strftime('%Y-%m-%d %H:%M:%S')} ({total_seconds/3600:.2f} hours remaining).")
    
    # GitHub Actions max job execution time is 6 hours (21,600s). Safe chunk is 5 hours (18,000s).
    SAFE_CHUNK_SECONDS = 5 * 3600
    
    if total_seconds > SAFE_CHUNK_SECONDS:
        sleep_duration = SAFE_CHUNK_SECONDS
        will_chain = True
    else:
        sleep_duration = max(10, total_seconds)
        will_chain = False
        
    print(f"[{now.strftime('%H:%M:%S')}] Relay Chunk: Sleeping for {sleep_duration/3600:.2f} hours (active Telegram polling enabled)...")
    
    start_time = time.time()
    while (time.time() - start_time) < sleep_duration:
        poll_telegram_messages()
        time.sleep(5)
        
    now_after = datetime.now(egypt_tz)
    if will_chain:
        print(f"[{now_after.strftime('%H:%M:%S')}] 5-hour relay chunk complete. Dispatching next runner to maintain perpetual relay...")
        trigger_next_runner()
        sys.exit(0)
    else:
        print(f"[{now_after.strftime('%H:%M:%S')}] Market opening reached ({now_after.strftime('%H:%M:%S')}). Perpetual relay handoff to market session!")
        return

def wait_for_market_open():
    egypt_tz = timezone(timedelta(hours=3))
    now = datetime.now(egypt_tz)
    target_time = now.replace(hour=8, minute=45, second=0, microsecond=0)
    
    if now < target_time:
        seconds_to_wait = (target_time - now).total_seconds()
        print(f"[{now.strftime('%H:%M:%S')}] Early Wake active. Waiting {seconds_to_wait:.1f} seconds until market open (08:45 AM)...")
        start_time = time.time()
        while (time.time() - start_time) < seconds_to_wait:
            poll_telegram_messages()
            time.sleep(5)
        print(f"[{datetime.now(egypt_tz).strftime('%H:%M:%S')}] Market open! Starting run.")

def sleep_until_next_15min_mark():
    egypt_tz = timezone(timedelta(hours=3))
    now = datetime.now(egypt_tz)
    minute = now.minute
    second = now.second
    microsecond = now.microsecond
    
    next_minute = ((minute // 15) + 1) * 15
    if next_minute == 60:
        seconds_to_wait = (60 - minute) * 60 - second
    else:
        seconds_to_wait = (next_minute - minute) * 60 - second
        
    seconds_to_wait -= (microsecond / 1000000.0)
    if seconds_to_wait <= 0:
        seconds_to_wait = 900
        
    print(f"[{now.strftime('%H:%M:%S')}] Waiting {seconds_to_wait:.1f} seconds until next clock mark...")
    start_time = time.time()
    while (time.time() - start_time) < seconds_to_wait:
        poll_telegram_messages()
        time.sleep(5)

if __name__ == "__main__":
    egypt_tz = timezone(timedelta(hours=3))
    now = datetime.now(egypt_tz)
    today_str = now.strftime("%Y-%m-%d")
    # ✅ تسجيل وقت البدء لتجاهل رسائل Telegram القديمة مع هامش أمان 5 دقائق لتلافي فجوة الانتقال بين الـ runners
    _startup_epoch = int(time.time()) - 300
    
    # ✅ إعداد وتحديث قائمة الأزرار والأوامر الرسمية في تطبيق تليجرام تلقائياً
    setup_telegram_bot_menu()
    
    force_run = os.environ.get("FORCE_RUN", "false").lower() == "true"
    
    # 1. Check weekday: Weekend in Egypt is Friday/Saturday (4, 5)
    if now.weekday() in [4, 5] and not force_run:
        print(f"[{now.strftime('%H:%M:%S')}] Weekend (Friday/Saturday). Market closed. Entering Perpetual 24/7 Cloud Relay.")
        enter_perpetual_sleep_and_relay()
        sys.exit(0)
        
    # 2. Check time of day: If 3:00 PM (15:00) or later, all trading and closing reports for today are finished!
    if (now.hour * 60 + now.minute >= 15 * 60) and not force_run:
        print(f"[{now.strftime('%H:%M:%S')}] Past 03:00 PM Cairo time. All sessions and reports completed for today ({today_str}). Entering Perpetual 24/7 Cloud Relay.")
        enter_perpetual_sleep_and_relay()
        sys.exit(0)
        
    # 3. Check state: If today's daily summary has already been sent, today's trading work is finished!
    if not force_run:
        try:
            state_data, _ = get_github_state()
            if state_data.get("date") == today_str and state_data.get("summary_sent", False):
                print(f"[{now.strftime('%H:%M:%S')}] Daily closing summary was already sent today ({today_str}). Entering Perpetual 24/7 Cloud Relay.")
                enter_perpetual_sleep_and_relay()
                sys.exit(0)
        except Exception as e:
            print(f"Warning checking initial state: {e}")
        
    if force_run:
        print(f"[{now.strftime('%H:%M:%S')}] FORCE_RUN enabled. Processing commands and sending immediate report.")
        # ✅ إصلاح: قراءة رسائل التليجرام أولاً لمعالجة أوامر مثل /status قبل إنهاء التشغيل القسري
        poll_telegram_messages()
        time.sleep(2)
        send_report(force=True)
        
        # إذا تم التشغيل القسري بعد إغلاق السوق (بعد 14:30)، نرسل الملخص الختامي أيضاً
        if now.hour * 60 + now.minute >= 14 * 60 + 30:
            print("Past 2:30 PM, sending daily summary during force run...")
            success = send_daily_summary()
            if success:
                state_data, state_sha = get_github_state()
                state_data["date"] = today_str
                state_data["summary_sent"] = True
                update_github_state(state_data, state_sha)
        
        # ✅ إصلاح: أوقف runner بعد 14:30 وعلى مدار أيام الأسبوع أو عطلة نهاية الأسبوع
        if now.weekday() not in [4, 5] and now.hour * 60 + now.minute < 14 * 60 + 30:
            print(f"[{now.strftime('%H:%M:%S')}] Market open. Scheduling next runner.")
            trigger_next_runner()
        else:
            print(f"[{now.strftime('%H:%M:%S')}] Near/past market close or weekend. Entering Perpetual 24/7 Cloud Relay.")
            enter_perpetual_sleep_and_relay()
        sys.exit(0)
        
    wait_for_market_open()
    
    import sys
    TOTAL_CYCLES = 24
    for i in range(TOTAL_CYCLES):
        loop_now = datetime.now(egypt_tz)
        print(f"=== Loop Cycle {i+1}/{TOTAL_CYCLES} | Time: {loop_now.strftime('%H:%M:%S')} ===")
        current_time_minutes = loop_now.hour * 60 + loop_now.minute
        
        try:
            # إذا انتهت جلسة التداول (بعد 14:30 / 02:30 ظهراً):
            if current_time_minutes > 14 * 60 + 30:
                print(f"[{loop_now.strftime('%H:%M:%S')}] Past 2:30 PM (market closed). Handling session close & summary.")
                
                # التحقق أولاً: إذا كان التقرير الختامي قد أُرسل اليوم بالفعل، ننتقل للترحيل الليلي
                state_data, state_sha = get_github_state()
                if state_data.get("date") == today_str and state_data.get("summary_sent", False):
                    print(f"[{loop_now.strftime('%H:%M:%S')}] Daily summary already sent today. Transitioning to Perpetual 24/7 Cloud Relay.")
                    enter_perpetual_sleep_and_relay()
                    sys.exit(0)
                
                # إرسال تقرير الإقفال لأسعار الجلسة
                send_report()
                
                ctx = get_session_context(loop_now)
                reply_telegram(ctx["closing_greeting"])
                
                # الانتظار حتى الساعة 3:00 مساءً لإرسال التقرير التحليلي الإضافي (الملخص الختامي)
                now_egypt = datetime.now(egypt_tz)
                target_summary_time = now_egypt.replace(hour=15, minute=0, second=0, microsecond=0)
                if now_egypt < target_summary_time:
                    seconds_to_wait = (target_summary_time - now_egypt).total_seconds()
                    print(f"[{now_egypt.strftime('%H:%M:%S')}] Waiting {seconds_to_wait:.1f} seconds until 3:00 PM for Daily Summary...")
                    start_time = time.time()
                    while (time.time() - start_time) < seconds_to_wait:
                        poll_telegram_messages()
                        time.sleep(5)
                
                success = send_daily_summary()
                if success:
                    state_data, state_sha = get_github_state()
                    state_data["date"] = today_str
                    state_data["summary_sent"] = True
                    update_github_state(state_data, state_sha)
                
                print(f"[{datetime.now(egypt_tz).strftime('%H:%M:%S')}] Daily summary sent. Transitioning to Perpetual 24/7 Cloud Relay...")
                enter_perpetual_sleep_and_relay()
                sys.exit(0)
                
            # خلال ساعات الجلسة (من 08:45 صباحاً حتى 14:30 ظهراً)
            if 8 * 60 + 45 <= current_time_minutes <= 14 * 60 + 30:
                send_report()
            else:
                print(f"[{loop_now.strftime('%H:%M:%S')}] Outside active market hours, skipping report.")
                
        except Exception as cycle_err:
            import traceback
            print(f"⚠️ Error during cycle {i+1}: {cycle_err}")
            traceback.print_exc()
            # استمرار البوت في العمل دون إنهاء العملية والانتقال للدورة القادمة
            time.sleep(10)
            
        if i == TOTAL_CYCLES - 1:
            # إطلاق المشغل الجديد فقط إذا كان السوق لا يزال مفتوحاً (قبل 14:30)
            if loop_now.hour * 60 + loop_now.minute < 14 * 60 + 30:
                print(f"[{loop_now.strftime('%H:%M:%S')}] Market still active. Dispatching next runner to continue intraday session.")
                trigger_next_runner()
                sys.exit(0)
            else:
                print(f"[{loop_now.strftime('%H:%M:%S')}] Time is 2:30 PM or later. Transitioning to Perpetual 24/7 Cloud Relay.")
                enter_perpetual_sleep_and_relay()
                sys.exit(0)
                
        if i < TOTAL_CYCLES - 1:
            try:
                sleep_until_next_15min_mark()
            except Exception as sleep_err:
                print(f"Error in sleep_until_next_15min_mark: {sleep_err}")
                time.sleep(60)
