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
GEMINI_MODEL = "gemini-2.5-flash"

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
PORTFOLIO = ["EGAL", "TMGH", "ETEL", "EFID", "ADIB", "ORHD", "EFIH", "OCDI"]
WATCHLIST = [
    "RACC", "FWRY", "ORAS", "PHDC", "SKPC", "MCQE", "FAITA", "ISPH", "JUFO", "AMOC",
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

# Stock keywords for news filtering
STOCK_KEYWORDS = {
    "TMGH": ["طلعت مصطفى", "TMGH"],
    "ADIB": ["أبوظبي الإسلامي", "أبو ظبي الإسلامي", "ADIB"],
    "EFID": ["إيديتا", "ايديتا", "Edita", "EFID"],
    "RACC": ["راية مراكز", "راية لخدمات", "RACC"],
    "FWRY": ["فوري", "FWRY"],
    "EGAL": ["مصر للألومنيوم", "مصر للالومنيوم", "EGAL"],
    "ETEL": ["المصرية للاتصالات", "المصريه للاتصالات", "وي", "ETEL"],
    "ORHD": ["أوراسكوم للتنمية", "اوراسكوم للتنمية", "ORHD"],
    "EFIH": ["إي فاينانس", "اي فاينانس", "EFIH"],
    "OCDI": ["سوديك", "سودك", "OCDI"],
    "ORAS": ["أوراسكوم كونستراكشون", "اوراسكوم كونستراكشون", "أوراسكوم للإنشاء", "ORAS"],
    "PHDC": ["بالم هيلز", "PHDC"],
    "SKPC": ["سيدي كرير", "سيدبك", "SKPC"],
    "MCQE": ["أسمنت قنا", "اسمنت قنا", "MCQE"],
    "FAITA": ["فيصل الإسلامي", "فيصل الاسلامي", "FAITA"],
    "ISPH": ["ابن سينا", "ISPH"],
    "JUFO": ["جهينة", "جهينه", "JUFO"],
    "AMOC": ["أموك", "اموك", "الأسكندرية للزيوت المعدنية", "AMOC"],
    "MASR": ["مدينة مصر", "ماديناتي", "MASR"],  # حذف 'مدينة نصر' لتجنب false positives
    "ORWE": ["النساجون الشرقيون", "النساجون", "ORWE"],
    "RMDA": ["العاشر من رمضان", "راميدا", "RMDA"],
    "OLFI": ["عبور لاند", "عبورلاند", "OLFI"],
    "ARCC": ["العربية للأسمنت", "العربيه للأسمنت", "ARCC"],
    "FAIT": ["بنك فيصل", "FAIT"],
    "IFAP": ["الدولية للمحاصيل", "الدوليه للمحاصيل", "IFAP"],
    "MTIE": ["إم إم جروب", "ام ام جروب", "MTIE"],
    "SAUD": ["البركة", "بنك البركة", "SAUD"],
    "ATQA": ["عتاقة", "عتاقه", "مصر الوطنية للصلب", "ATQA"],
    "CIRA": ["القاهرة للاستثمار", "سيرا", "CIRA"],
    "EGAS": ["غاز مصر", "EGAS"],
    "MPCO": ["المنصورة للدواجن", "المنصوره للدواجن", "MPCO"],
    "ACGC": ["عربية لحليج الأقطان", "حليج الأقطان", "ACGC"],
    "ETRS": ["إيجيترانس", "ايجيترانس", "المصرية لخدمات النقل", "ETRS"],
    "LCSW": ["ليسيكو", "LCSW"],
    "ICFC": ["الدولية للأسمدة", "الدوليه للأسمده", "ICFC"]
}

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

def reply_telegram(text):
    """دالة موحدة لإرسال Telegram مع فحص status وإعادة محاولة بدون HTML عند 400، ودعم تقسيم الرسائل الطويلة."""
    if not BOT_TOKEN or not CHAT_ID:
        return
    
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
            reply_telegram("\n".join(chunk))
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 400:
            # محاولة الإرسال بدون HTML في حال وجود وسوم مكسورة
            requests.post(url, json={
                "chat_id": CHAT_ID,
                "text": re.sub(r'<[^>]+>', '', text),
                "disable_web_page_preview": True
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
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        print("Next runner dispatch status:", r.status_code)
    except Exception as e:
        print("Error dispatching next runner:", e)

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
            "max_tokens": 1000,
            "messages": [{"role": "user", "content": question}]
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                return r.json()["content"][0]["text"]
        except Exception as e:
            print("Claude API error:", e)

    # Fallback to Gemini AI (with model fallback to bypass 503/404 errors)
    if GEMINI_API_KEY:
        for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
            headers = {"content-type": "application/json"}
            payload = {
                "contents": [{"parts": [{"text": question}]}]
            }
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=30)
                if r.status_code == 200:
                    res_json = r.json()
                    candidates = res_json.get("candidates", [])
                    if candidates and "content" in candidates[0] and candidates[0]["content"].get("parts"):
                        return candidates[0]["content"]["parts"][0]["text"]
                    else:
                        print(f"Gemini {model_name} response blocked or empty in ask_ai. Response: {res_json}")
                        continue
                else:
                    print(f"Gemini {model_name} ask_ai returned status {r.status_code}")
            except Exception as e:
                print(f"Gemini {model_name} ask_ai error: {e}")
        return "عذراً، خوادم الذكاء الاصطناعي لـ Gemini تواجه ضغطاً حالياً. يرجى المحاولة لاحقاً."
            
    return "يرجى ضبط مفاتيح المطورين (CLAUDE_API_KEY أو GEMINI_API_KEY) لتفعيل محادثات الذكاء الاصطناعي."

def fetch_rss_news():
    feeds = {
        "جريدة البورصة": "https://alborsaanews.com/feed",
        "حبي جرنال": "https://hapijournal.com/feed",
        "إيكونومي بلس": "https://economyplusme.com/feed",
        "إنتربرايز": "https://enterprise.press/ar/feed",
        "اليوم السابع": "https://www.youm7.com/rss/SectionRSS?SectionID=9",
        "أموال الغد": "https://amwalalghad.com/feed",
        "جريدة الشروق": "https://www.shorouknews.com/rss/economy",
        "سي إن بي سي عربية": "https://www.cnbcarabia.com/rss",
        "الوطن": "https://www.elwatannews.com/home/rss/economy",
        "المصري اليوم": "https://www.almasryalyoum.com/rss/sections/2/feed",
        "صدى البلد": "https://www.elbalad.news/rss.aspx?id=12",
        "بوابة فيتو": "https://www.vetogate.com/rss.aspx?id=4"
    }
    
    gnews_query = 'البورصة المصرية OR أسهم مصر OR اقتصاد مصر OR "طلعت مصطفى" OR "فوري" OR "سوديك" OR "إيديتا" OR "أبوظبي الإسلامي" OR "مصر للألومنيوم" OR "المصرية للاتصالات" OR "إي فاينانس" OR "أوراسكوم"'
    encoded_query = urllib.parse.quote(gnews_query)
    feeds["أخبار جوجل"] = f"https://news.google.com/rss/search?q={encoded_query}&hl=ar&gl=EG&ceid=EG:ar"
    
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

            limit = 30 if source_name == "أخبار جوجل" else 15
            for entry in items[:limit]:
                # ✅ إصلاح: فحص نوع entry بدل الاعتماد على وجود feedparser فقط
                if hasattr(entry, 'title'):
                    title = getattr(entry, 'title', '')
                    link = getattr(entry, 'link', '')
                else:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                if title and link:
                    link = link.replace(" ", "%20")
                    item_source = source_name
                    if source_name == "أخبار جوجل":
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
        objects = re.findall(r'\\"headingArabic\\":\\"(.*?)\\".*?\\"contentArabic\\":\\"(.*?)\\"', r.text)
        objects_unescaped = re.findall(r'"headingArabic":"(.*?)".*?"contentArabic":"(.*?)"', r.text)
        for heading, content in objects + objects_unescaped:
            if heading and heading != "null":
                # ✅ إصلاح: فك Unicode escapes بأمان تام وحذف backslashes الزائدة
                heading = decode_unicode_escapes(heading).replace('\\"', '"').replace('\\\\', '\\')
                items.append({
                    "tag": "[EGX]",
                    "title": heading.strip(),
                    "link": "https://beta.egx.com.eg/",
                    "source": "بورصة مصر (Beta)"
                })
    except Exception as e:
        print("Error fetching EGX Beta news:", e)
        
    unique = []
    seen = set()
    for item in items:
        uid = f"{item['tag']}_{item['title']}"
        if uid not in seen:
            seen.add(uid)
            # ✅ إصلاح: توليد رابط فريد وهمي ومستقر لمنع خوارزمية الفلترة من حذف الأخبار المتعددة بسبب تطابق الرابط، ولمنع التكرار عبر الـ runners
            stable_hash = hashlib.md5(uid.encode("utf-8")).hexdigest()[:10]
            item["link"] = f"https://beta.egx.com.eg/?news={stable_hash}"
            unique.append(item)
    return unique

def is_whole_word_match(word, text):
    """مطابقة الكلمات المفتاحية بشكل دقيق مع دعم السوابق العربية وتجنب التداخلات مثل (فوري vs فورية)."""
    if not word or not text:
        return False
    word = word.lower().strip()
    text = text.lower()
    # ✅ إصلاح: السماح بمسافات متعددة بين الكلمات في العبارة المفتاحية
    escaped_word = re.escape(word).replace(r'\ ', r'\s+')
    pattern = r"(?:^|\W)(?:و|ف|ب|ك|ل|لل|ال|وال|فال|بال|كال)?" + escaped_word + r"(?:$|\W)"
    return re.search(pattern, text) is not None

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
        if item["link"] not in seen_links:
            seen_links.add(item["link"])
            
            matched_stock = None
            for ticker, keywords in STOCK_KEYWORDS.items():
                if ticker not in portfolio_list and ticker not in watchlist_list:
                    continue
                for kw in keywords:
                    if is_whole_word_match(kw, item["title"]):
                        matched_stock = ticker
                        break
                if matched_stock:
                    break
            
            is_market = False
            if not matched_stock:
                for mkw in ["البورصة", "البورصه", "EGX30", "EGX", "سوق المال", "الأسهم المصرية"]:
                    if is_whole_word_match(mkw, item["title"]):
                        is_market = True
                        break
            
            if matched_stock or is_market:
                if matched_stock:
                    item["tag"] = f"[{matched_stock}]"
                else:
                    item["tag"] = "[البورصة]"
                filtered.append(item)
    
    for item in all_news:
        title = item["title"]
        link = item["link"]
        source = item["source"]
        if link in seen_links:
            continue
            
        matched_stock = None
        for ticker, keywords in STOCK_KEYWORDS.items():
            if ticker not in portfolio_list and ticker not in watchlist_list:
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
        "أنت خبير مالي ومحلل أسهم محترف في البورصة المصرية.\n"
        "مهمتك هي تحليل الأخبار لكل سهم وتقديم تقييم مالي وتوقعات مستقبلية مختصرة جداً.\n"
        "لكل سهم من الأسهم التالية، قم بتحليل الأخبار المرفقة وقدم تحليلاً باللغة العربية الفصحى (بين 30 إلى 50 كلمة لكل سهم) يشمل:\n"
        "1. التقييم المالي للخبر والتأثير المتوقع على سعر ومستقبل السهم (إيجابي / سلبي / محايد).\n"
        "2. نظرة مستقبلية قصيرة للسهم.\n"
        "قاعدة هامة: التحليل يجب أن يكون نقدي ودقيق جداً، وموضوعي يعكس الواقع بحيادية تامة.\n\n"
        "يجب أن تكون الإجابة بالتنسيق التالي لكل سهم (كل سهم في سطر منفصل وبدون أي نصوص برمجية أو علامات ماركداون إضافية):\n"
        "[اسم السهم]: نص التحليل المالي والتقييم مباشرة.\n"
        "مثال:\n"
        "[FWRY]: التقييم إيجابي. من المتوقع نمو السعر بسبب زيادة الأرباح.\n"
        "[ETEL]: التقييم محايد. استقرار في الأداء المالي مع نظرة مستقبلية مستقرة.\n\n"
        "الأسهم والأخبار المتاحة:\n"
    )
    
    for tag in target_tags:
        ticker = tag.replace("[", "").replace("]", "")
        prompt += f"--- سهم {ticker} ---\n"
        for item in grouped_news[tag][:3]:
            prompt += f"- {item['title']} (المصدر: {item['source']})\n"
        prompt += "\n"
        
    analyses = {}
    # ✅ إصلاح: تجربة عدة نماذج بالتوالي كآلية تراجع (Fallback) لتفادي أخطاء 503/404
    for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2
            }
        }
        try:
            r = requests.post(url, json=body, headers={"Content-Type": "application/json"}, timeout=45)
            if r.status_code == 200:
                res_json = r.json()
                candidates = res_json.get("candidates", [])
                if not candidates or "content" not in candidates[0] or not candidates[0]["content"].get("parts"):
                    print(f"Gemini {model_name} response blocked or empty. Response: {res_json}")
                    continue
                raw_text = candidates[0]["content"]["parts"][0]["text"].strip()
                # ✅ إصلاح: استخدام re.finditer بدلاً من splitlines لدعم التحليلات متعددة الأسطر (Multi-line)
                matches = re.finditer(r'\[([A-Z0-9]+)\][^\w]*((?:(?!\[[A-Z0-9]+\]).)*)', raw_text, re.DOTALL)
                for m in matches:
                    clean = m.group(1).upper()
                    analysis = m.group(2).strip()
                    if analysis:
                        # ✅ إصلاح: ترميز النص قبل وضعه في وسوم HTML لمنع فشل الإرسال
                        analysis_esc = escape_html(analysis)
                        analyses[f"[{clean}]"] = f"🧠 <b>تحليل AI لسهم {clean}:</b> {analysis_esc}"
                print(f"Gemini AI Analysis successfully generated using {model_name} for:", list(analyses.keys()))
                break
            else:
                print(f"Gemini {model_name} returned status {r.status_code}: {r.text[:300]}")
        except Exception as e:
            print(f"Error in Gemini {model_name} batch AI news analysis: {e}")
            
    return analyses

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
        "columns": ["close", "open", "change", "Recommend.All"]
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
            
            # استخدام change مباشرة
            chg = safe_round(change_val)
            
            rec_str = ""
            if rec_val is not None:
                if rec_val >= 0.5: rec_str = f"🚀 {strings['strong_buy']}"
                elif rec_val >= 0.1: rec_str = f"📈 {strings['buy']}"
                elif rec_val <= -0.5: rec_str = f"📉 {strings['strong_sell']}"
                elif rec_val <= -0.1: rec_str = f"🔻 {strings['sell']}"
                else: rec_str = "⏸️ محايد"
            if sym in indices:
                indices[sym] = {"close": c, "open": o, "chgPct": chg}
            else:
                parsed[sym] = {"close": c, "open": o, "chgPct": chg, "rec": rec_str}
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
            state_data = {"sent_links": [], "date": today_str}
            
        sent_links = set(state_data.get("sent_links", []))
        
        for item in live_news:
            if item["title"] not in seen_titles and (force or item["link"] not in sent_links):
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
        
        for tag in sorted_tags:
            items_in_tag = grouped[tag]
            block = f"{s['rlm']}🔥 <b>{tag}</b>:\n"
            for item in items_in_tag[:3]:
                # ✅ إصلاح: ترميز العنوان والمصدر لمنع أخطاء التنسيق في تليجرام عند وجود رموز مثل & أو <
                title_esc = escape_html(item["title"])
                source_esc = escape_html(item["source"])
                block += f"{s['rlm']}• {title_esc} ({source_esc}) <a href='{item['link']}'>[رابط مباشر]</a>\n"
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
    
    if total_minutes < 8 * 60 + 45:
        status_text = "⚠️ <b>السوق لم يفتح بعد (يفتح 08:45 ص)</b>\n📊 <b>الأسعار والتغيرات أدناه هي إغلاق الجلسة السابقة.</b>\n\n"
        port_header = f"📊 {port_header} (إغلاق الجلسة السابقة)"
        watch_header = f"📊 {watch_header} (إغلاق الجلسة السابقة)"
    elif 8 * 60 + 45 <= total_minutes <= 14 * 60 + 30:  # ✅ إصلاح: السوق يُغلق 14:30
        port_header = f"💼 {port_header} (حركة لحظية)"
        watch_header = f"📋 {watch_header} (حركة لحظية)"
    else:
        status_text = "🔒 <b>انتهت جلسة تداول اليوم (إغلاق 14:30)</b>\n📈 <b>الأسعار أدناه هي أسعار الإغلاق النهائية لليوم.</b>\n\n"
        port_header = f"📈 {port_header} (إغلاق جلسة اليوم)"
        watch_header = f"📈 {watch_header} (إغلاق جلسة اليوم)"
        
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
        msg_portfolio += f"{s['rlm']}{dir_emoji} <b>{ticker_html}</b>:{s['rlm']} {item['open']} {s['e_arrow']} <b>{item['close']}</b> ({chg_str}) | {item['rec']}\n"
        
    msg_watchlist = f"{s['rlm']}<b>{watch_header}:</b>\n"
    for k in sorted_watch:
        item = parsed_stocks[k]
        val = item["chgPct"]
        chg_str = f"+{val}%" if val > 0 else (f"{val}%" if val < 0 else "0.0%")
        dir_emoji = s["e_green"] if val > 0 else (s["e_red"] if val < 0 else s["e_white"])
        ticker_link = COMPANY_WEBSITES.get(k, "#")
        ticker_html = f"<a href='{ticker_link}'>{k}</a>" if ticker_link != "#" else k
        msg_watchlist += f"{s['rlm']}{dir_emoji} <b>{ticker_html}</b>:{s['rlm']} {item['open']} {s['e_arrow']} <b>{item['close']}</b> ({chg_str}) | {item['rec']}\n"
    
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
    
    # ✅ إصلاح: استخدام دالة reply_telegram الموحدة والمؤمنة ضد الطول الزائد والمشاكل البرمجية
    reply_telegram(msg_portfolio)
    reply_telegram(msg_watchlist)
    reply_telegram(msg_indices)
        
    if news_chunks:
        for i, chunk in enumerate(news_chunks):
            if i == 0:
                chunk = f"{s['rlm']}<b>{s['e_rocket']} {s['latest_news_developments']}:</b>\n" + chunk
            reply_telegram(chunk)

def handle_telegram_command(text):
    text_lower = text.lower()
    if text_lower.startswith("/start") or text_lower.startswith("/help"):
        help_msg = (
            "<b>🤖 أهلاً بك في مساعد أسهم الشريعة الذكي!</b>\n\n"
            "إليك الأوامر المتاحة:\n"
            "📌 <code>/report</code> : لتوليد وإرسال التقرير المالي فوراً.\n"
            "📌 <code>/add_news [الخبر]</code> : لإضافة خبر لقائمة الأخبار وتحديثها على GitHub.\n"
            "📌 <code>/clear_news</code> : لمسح جميع الأخبار اليدوية القديمة.\n"
            "📌 <code>/ask [سؤالك]</code> : لطرح أي سؤال مالي أو فني على الذكاء الاصطناعي (Claude/Gemini).\n"
            "📌 <code>/status</code> : حالة البوت الحالية."
        )
        reply_telegram(help_msg)
        
    elif text_lower.startswith("/report"):
        reply_telegram("🔄 جاري توليد وإرسال التقرير المحدث الآن...")
        send_report(force=True)
        
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
            
    elif text_lower.startswith("/clear_news"):
        if os.path.exists(NEWS_PATH):
            with open(NEWS_PATH, "w", encoding="utf-8") as nf:
                nf.write("")
            if update_github_news(""):
                reply_telegram("✅ تم مسح جميع الأخبار اليدوية بنجاح!")
            else:
                reply_telegram("❌ تم مسح الأخبار محلياً لكن فشل التحديث على GitHub.")
        else:
            reply_telegram("⚠️ لا توجد أخبار يدوية محفوظة حالياً لتتم إزالتها.")
            
    elif text_lower.startswith("/ask"):
        question = text[len("/ask"):].strip()
        if not question:
            reply_telegram("⚠️ يرجى كتابة السؤال بعد الأمر. مثال:\n<code>/ask ما توقعاتك لسهم طلعت مصطفى؟</code>")
            return
        reply_telegram("🔄 جاري التفكير والتحليل...")
        reply_telegram(ask_ai(question))
        
    elif text_lower.startswith("/status"):
        import time
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        status_msg = (
            "🟢 <b>حالة البوت: متصل ويعمل بنجاح</b>\n"
            f"🕒 <b>وقت الخادم (UTC):</b> {current_time}\n"
            f"🧠 <b>المحرك الذكي:</b> {GEMINI_MODEL}\n"
            "⚙️ <b>العملية:</b> قيد المراقبة المستمرة لأخبار السوق."
        )
        reply_telegram(status_msg)
        
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
    # ✅ تسجيل وقت البدء لتجاهل رسائل Telegram القديمة مع هامش أمان 5 دقائق لتلافي فجوة الانتقال بين الـ runners
    _startup_epoch = int(time.time()) - 300
    
    # Check weekday (Egypt stock market runs Sunday to Thursday)
    # Python weekday(): 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
    if now.weekday() in [4, 5]:
        print(f"[{now.strftime('%H:%M:%S')}] Weekend (Friday/Saturday). Exiting.")
        sys.exit(0)
        
    force_run = os.environ.get("FORCE_RUN", "false").lower() == "true"
    if force_run:
        print(f"[{now.strftime('%H:%M:%S')}] FORCE_RUN enabled. Sending immediate report.")
        send_report(force=True)
        
        # ✅ إصلاح: أوقف runner قبل 14:45 فقط (وليس حتى 15:30)
        if now.hour * 60 + now.minute < 14 * 60 + 45:
            print(f"[{now.strftime('%H:%M:%S')}] Market open. Scheduling next runner.")
            trigger_next_runner()
        else:
            print(f"[{now.strftime('%H:%M:%S')}] Near/past market close. Not chaining next runner.")
        sys.exit(0)
        
    wait_for_market_open()
    
    import sys
    TOTAL_CYCLES = 15
    try:
        for i in range(TOTAL_CYCLES):
            loop_now = datetime.now(egypt_tz)
            print(f"=== Loop Cycle {i+1}/{TOTAL_CYCLES} | Time: {loop_now.strftime('%H:%M:%S')} ===")
            
            current_time_minutes = loop_now.hour * 60 + loop_now.minute
            # ✅ إصلاح: مزامنة حد الخروج مع حد الإرسال (14:30 وليس 15:30)
            if current_time_minutes > 14 * 60 + 30:
                print(f"[{loop_now.strftime('%H:%M:%S')}] Past 2:30 PM (market closed). Sending final closing report.")
                send_report()
                reply_telegram("🔒 <b>تم إرسال تقرير الإقفال النهائي لجلسة اليوم. نراكم غداً بإذن الله.</b>")
                sys.exit(0)
                
            # ✅ إصلاح: البورصة تُغلق 14:30 وليس 15:30
            if 8 * 60 + 45 <= current_time_minutes <= 14 * 60 + 30:
                send_report()
            else:
                print(f"[{loop_now.strftime('%H:%M:%S')}] Outside market hours, skipping report.")
                
            if i == TOTAL_CYCLES - 1:
                # ✅ إصلاح: إطلاق المشغل الجديد في نهاية الدورة الأخيرة فقط لمنع تشغيل نسختين في وقت واحد وتكرار الرسائل
                if loop_now.hour * 60 + loop_now.minute < 15 * 60:
                    trigger_next_runner()
                else:
                    print(f"[{loop_now.strftime('%H:%M:%S')}] Time is 3:00 PM or later. Stopping chain.")
                    
            if i < TOTAL_CYCLES - 1:
                sleep_until_next_15min_mark()
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        short_error = error_details[-500:] if len(error_details) > 500 else error_details
        error_msg = f"⚠️ <b>تنبيه من الخادم:</b>\nحدث خطأ برمجي أدى لتوقف البوت:\n<pre>{short_error}</pre>"
        reply_telegram(error_msg)
        print(f"CRITICAL ERROR: {e}")
        sys.exit(1)
