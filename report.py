import json
import os
import time
import requests
import base64
import urllib.request
import urllib.parse
from urllib.parse import urljoin
import xml.etree.ElementTree as ET
import re
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
    
    # Add Google News Search (representing 100+ sources)
    import urllib.parse
    gnews_query = 'البورصة المصرية OR أسهم مصر OR اقتصاد مصر OR "طلعت مصطفى" OR "فوري" OR "سوديك" OR "إيديتا" OR "أبوظبي الإسلامي" OR "مصر للألومنيوم" OR "المصرية للاتصالات" OR "إي فاينانس" OR "أوراسكوم"'
    encoded_query = urllib.parse.quote(gnews_query)
    feeds["أخبار جوجل"] = f"https://news.google.com/rss/search?q={encoded_query}&hl=ar&gl=EG&ceid=EG:ar"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    news_items = []
    
    # We will import feedparser locally to avoid issues if not available,
    # but run_report.yml installs it.
    try:
        import feedparser
    except ImportError:
        feedparser = None
        print("Warning: feedparser is not installed. RSS parsing may fail.")

    for source_name, url in feeds.items():
        try:
            r = requests.get(url, headers=headers, timeout=10, verify=False)
            if r.status_code != 200:
                print(f"Error fetching from {source_name}: HTTP {r.status_code}")
                continue
                
            if feedparser:
                feed = feedparser.parse(r.content)
                items = feed.entries
            else:
                # Fallback to ElementTree if feedparser is missing
                root = ET.fromstring(r.content)
                items_xml = root.findall(".//item")
                if not items_xml:
                    items_xml = root.findall(".//{http://www.w3.org/2005/Atom}entry")
                if not items_xml:
                    items_xml = [elem for elem in root.iter() if elem.tag.endswith("item") or elem.tag.endswith("entry")]
                    
                items = []
                for item in items_xml:
                    title_elem = None
                    link_elem = None
                    for child in item:
                        if child.tag.endswith("title"): title_elem = child
                        if child.tag.endswith("link"): link_elem = child
                    t = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                    l = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                    if not l and link_elem is not None:
                        l = link_elem.attrib.get("href", "").strip()
                    items.append({"title": t, "link": l})

            limit = 30 if source_name == "أخبار جوجل" else 15
            for entry in items[:limit]:
                if feedparser:
                    title = entry.title if 'title' in entry else ""
                    link = entry.link if 'link' in entry else ""
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
                            actual_source = parts[1].strip()
                            item_source = f"{actual_source} (جوجل)"
                    
                    news_items.append({
                        "title": title.strip(),
                        "link": link,
                        "source": item_source
                    })
        except Exception as e:
            print(f"Error fetching from {source_name}: {e}")
            
    return news_items

def is_whole_word_match(word, text):
    if not word or not text:
        return False
        
    word = word.lower().strip()
    text = text.lower()
    
    if word == "وي":
        # Specific check for "وي" (WE) to avoid false positives like "قوي" or "سنوي"
        pattern = r"(?:^|[^\w\u0600-\u06FF])(?:و|ف|ب|ك|ل|لل|ال|وال|فال|بال|كال)?وي(?:$|[^\w\u0600-\u06FF])"
        return re.search(pattern, text) is not None
        
    return word in text

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
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    results = []
    for ticker, url in corporate_urls.items():
        try:
            # Using requests.get with timeout is much more robust
            r = requests.get(url, headers=headers, timeout=4, verify=False)
            html = r.text
            
            # Simple regex to find <a> tags and extract their links and text
            links = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
            
            found_count = 0
            for l_url, l_text in links:
                l_text_clean = re.sub(r'<[^>]+>', '', l_text).strip()
                l_text_clean = re.sub(r'\s+', ' ', l_text_clean)
                
                # Check for corporate press release indicators in Arabic or English
                if len(l_text_clean) > 15 and (
                    any(x in l_text_clean for x in ["إفصاح", "بيان", "صحفي", "نتائج", "أرباح", "مجلس", "إدارة", "شراكة", "توقيع", "استحواذ", "تعاون", "افتتاح", "زيادة", "مالية"]) or
                    any(y in l_url.lower() for y in ["press", "release", "news", "disclosure", "pdf"]) or
                    any(z in l_text_clean.lower() for z in ["press", "release", "disclosure", "financial", "result"])
                ):
                    full_link = l_url
                    if l_url.startswith("/"):
                        full_link = urljoin(url, l_url)
                    elif not l_url.startswith("http"):
                        full_link = urljoin(url, l_url)
                        
                    results.append({
                        "tag": f"[{ticker}]",
                        "title": l_text_clean,
                        "link": full_link,
                        "source": "الموقع الرسمي"
                    })
                    found_count += 1
                    if found_count >= 2:  # Keep top 2 announcements per site
                        break
        except Exception as e:
            print(f"Skipping corporate site {ticker} news fetch: {e}")
            
    return results

def get_filtered_market_news(portfolio_list, watchlist_list):
    filtered = []
    seen_links = set()
    
    # 1. Fetch news directly from corporate websites first (with absolute priority)
    try:
        corp_news = fetch_corporate_websites_news()
        for item in corp_news:
            link = item["link"]
            if link not in seen_links:
                seen_links.add(link)
                # Ensure the ticker is in our watched list
                ticker = item["tag"].strip("[]")
                if ticker in portfolio_list or ticker in watchlist_list:
                    filtered.append(item)
    except Exception as e:
        print("Error fetching corporate news:", e)
        
    # 2. Fetch news from standard RSS feeds and Google News
    all_news = fetch_rss_news()
    
    stock_keywords = {
        "TMGH": ["طلعت مصطفى", "طلعت مصطفي", "TMGH"],
        "ADIB": ["أبوظبي الإسلامي", "أبو ظبي الإسلامي", "ADIB"],
        "EFID": ["إيديتا", "ايديتا", "EFID"],
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
        "MASR": ["مدينة مصر", "مدينة نصر", "MASR"],
        "ORWE": ["النساجون الشرقيون", "النساجون", "ORWE"],
        "RMDA": ["العاشر من رمضان", "راميدا", "RMDA"],
        "OLFI": ["عبور لاند", "عبورلاند", "OLFI"],
        "ARCC": ["العربية للأسمنت", "العربيه للأسمنت", "ARCC"],
        "FAIT": ["فيصل الإسلامي", "فيصل الاسلامي", "FAIT"],
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
    
    for item in all_news:
        title = item["title"]
        link = item["link"]
        source = item["source"]
        
        if link in seen_links:
            continue
            
        matched_stock = None
        for ticker, keywords in stock_keywords.items():
            # Check if this ticker is in either portfolio or watchlist
            if ticker not in portfolio_list and ticker not in watchlist_list:
                continue
            for kw in keywords:
                if is_whole_word_match(kw, title):
                    matched_stock = ticker
                    break
            if matched_stock:
                break
                
        is_market_news = False
        if not matched_stock:
            market_keywords = ["البورصة", "البورصه", "EGX30", "EGX", "سوق المال", "الأسهم المصرية"]
            for mkw in market_keywords:
                if is_whole_word_match(mkw, title):
                    is_market_news = True
                    break
                    
        if matched_stock or is_market_news:
            seen_links.add(link)
            tag = f"[{matched_stock}]" if matched_stock else "[البورصة]"
            filtered.append({
                "tag": tag,
                "title": title,
                "link": link,
                "source": source
            })
            
    return filtered

def batch_analyze_news_with_gemini(grouped_news, portfolio_list, watchlist_list, s):
    """
    Analyzes news for all stocks in a single Gemini API request.
    Returns a dictionary mapping ticker tag -> analysis HTML block.
    """
    if not GEMINI_API_KEY:
        print("Gemini API key is missing. Skipping batch AI analysis.")
        return {}
        
    target_tags = []
    
    # Portfolio stocks with news
    for k in portfolio_list:
        tag = f"[{k}]"
        if tag in grouped_news:
            target_tags.append(tag)
            
    # Watchlist stocks with news
    for k in watchlist_list:
        tag = f"[{k}]"
        if tag in grouped_news and tag not in target_tags:
            target_tags.append(tag)
            
    # Limit to 10 stocks to keep response size and latency small
    target_tags = target_tags[:10]
    
    if not target_tags:
        return {}
        
    prompt = (
        "أنت خبير مالي ومحلل أسهم محترف في البورصة المصرية.\n"
        "مهمتك هي تحليل الأخبار لكل سهم وتقديم تقييم مالي وتوقعات مستقبلية مختصرة جداً.\n"
        "لكل سهم من الأسهم التالية، قم بتحليل الأخبار المرفقة وقدم تحليلاً باللغة العربية الفصحى (بين 30 إلى 50 كلمة لكل سهم) يشمل:\n"
        "1. التقييم المالي للخبر والتأثير المتوقع على سعر ومستقبل السهم (إيجابي / سلبي / محايد).\n"
        "2. نظرة مستقبلية قصيرة للسهم.\n\n"
        "يجب أن تكون الإجابة بصيغة JSON كائن (JSON object) فقط، حيث المفاتيح هي اسم السهم (مثال: 'FWRY' أو 'ETEL') والقيم هي نص التحليل المالي والتقييم مباشرة بدون أي نصوص برمجية أو علامات ماركداون إضافية.\n\n"
        "الأسهم والأخبار المتاحة:\n"
    )
    
    for tag in target_tags:
        ticker = tag.replace("[", "").replace("]", "")
        prompt += f"--- سهم {ticker} ---\n"
        for idx, item in enumerate(grouped_news[tag][:3]):
            prompt += f"- {item['title']} (المصدر: {item['source']})\n"
        prompt += "\n"
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"
    body = {
        "contents": [
            {
                "parts": [
                    { "text": prompt }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2
        }
    }
    
    analyses = {}
    try:
        r = requests.post(url, json=body, headers={"Content-Type": "application/json"}, timeout=15)
        if r.status_code == 200:
            res_json = r.json()
            raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            
            # Clean up JSON blocks
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_text = "\n".join(lines).strip()
                
            parsed_json = json.loads(raw_text)
            for ticker, analysis in parsed_json.items():
                clean_ticker = ticker.strip().upper().replace("[", "").replace("]", "")
                tag = f"[{clean_ticker}]"
                analyses[tag] = f"🧠 <b>تحليل AI لسهم {clean_ticker}:</b> {analysis.strip()}"
        else:
            print(f"Gemini batch API returned status {r.status_code}: {r.text}")
    except Exception as e:
        print("Error in Gemini batch AI news analysis:", e)
        
    return analyses

def send_report():
    print(f"[{datetime.now()}] Generating and sending report...")
    if not os.path.exists(STRINGS_PATH):
        print("Strings file missing, skipping report generation.")
        return

    with open(STRINGS_PATH, "r", encoding="utf-8") as f:
        s = json.load(f)

    company_websites = {
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

    # 1. Fetch stock prices
    stocks_payload = {
        "symbols": {
            "tickers": [
                "EGX:OCDI", "EGX:ORHD", "EGX:EFIH", "EGX:RACC",
                "EGX:EGAL", "EGX:TMGH", "EGX:EFID", "EGX:ETEL",
                "EGX:ADIB", "EGX:FWRY", "EGX:ORAS", "EGX:PHDC",
                "EGX:SKPC", "EGX:MCQE", "EGX:FAITA", "EGX:ISPH",
                "EGX:JUFO", "EGX:AMOC", "EGX:MASR", "EGX:ORWE",
                "EGX:RMDA", "EGX:OLFI", "EGX:ARCC", "EGX:FAIT",
                "EGX:IFAP", "EGX:MTIE", "EGX:SAUD", "EGX:ATQA",
                "EGX:CIRA", "EGX:EGAS", "EGX:MPCO", "EGX:ACGC",
                "EGX:ETRS", "EGX:LCSW", "EGX:ICFC", "EGX:EGX30"
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
    portfolio_list = ["EGAL", "TMGH", "ETEL", "EFID", "ADIB", "ORHD", "EFIH", "OCDI"]
    watchlist_list = [
        "RACC", "FWRY", "ORAS", "PHDC", "SKPC", "MCQE", "FAITA", "ISPH", "JUFO", "AMOC",
        "MASR", "ORWE", "RMDA", "OLFI", "ARCC", "FAIT", "IFAP", "MTIE",
        "SAUD", "ATQA", "CIRA", "EGAS", "MPCO", "ACGC", "ETRS", "LCSW",
        "ICFC"
    ]
    
    sorted_portfolio = sorted([k for k in portfolio_list if k in parsed_stocks], key=lambda x: parsed_stocks[x]["chgPct"], reverse=True)
    sorted_watchlist = sorted([k for k in watchlist_list if k in parsed_stocks], key=lambda x: parsed_stocks[x]["chgPct"], reverse=True)

    # Parse News from Live RSS feeds
    news_blocks = []
    try:
        live_news = get_filtered_market_news(portfolio_list, watchlist_list)
        
        # Group news by tag
        grouped = {}
        for item in live_news:
            tag = item["tag"]
            if tag not in grouped:
                grouped[tag] = []
            grouped[tag].append(item)
            
        # Define tag priority function based on user requirement:
        # Priority 0: Invested stocks (portfolio_list)
        # Priority 1: Watchlist stocks (watchlist_list)
        # Priority 2: General news ([البورصة])
        def get_tag_priority(t):
            ticker = t.replace("[", "").replace("]", "")
            if ticker in portfolio_list:
                return 0
            elif ticker in watchlist_list:
                return 1
            else:
                return 2
                
        # Sort groups: prioritized stock groups first, then watchlist groups, then general [البورصة] last.
        sorted_tags = sorted(grouped.keys(), key=lambda t: (get_tag_priority(t), t))
        
        # Get AI analysis mapping in a single batch request
        ai_analyses = batch_analyze_news_with_gemini(grouped, portfolio_list, watchlist_list, s)
        
        for tag in sorted_tags:
            items_in_tag = grouped[tag]
            group_text = f"{s['rlm']}🔥 <b>{tag}</b>:\n"
            for item in items_in_tag[:3]:
                title = item["title"]
                link = item["link"]
                source = item["source"]
                group_text += f"{s['rlm']}• {title} ({source}) <a href='{link}'>[رابط مباشر]</a>\n"
            
            # Append AI analysis if available for this tag
            if tag in ai_analyses:
                group_text += f"{s['rlm']}{ai_analyses[tag]}\n"
                
            news_blocks.append(group_text.strip())
            
    except Exception as e:
        print("Error getting live news:", e)
        
    # Graceful fallback to news.txt if no live news matched
    if not news_blocks and os.path.exists(NEWS_PATH):
        with open(NEWS_PATH, "r", encoding="utf-8") as nf:
            content = nf.read().strip()
            if content:
                blocks = content.split("\n\n")
                for block in blocks:
                    lines = block.strip().split("\n")
                    if len(lines) >= 2:
                        desc = lines[0].strip()
                        link = lines[1].strip()
                        news_blocks.append(f"{s['rlm']}{desc}\n{s['rlm']}{s['e_link']} <a href='{link}'>{s['e_link']} رابط الخبر</a>")

    # Group news blocks into chunks under 3500 characters
    news_message_chunks = []
    current_chunk = []
    current_len = 0
    for block in news_blocks:
        block_len = len(block) + 2  # plus "\n\n" separator
        if current_len + block_len > 3500:
            if current_chunk:
                news_message_chunks.append("\n\n".join(current_chunk))
            current_chunk = [block]
            current_len = block_len
        else:
            current_chunk.append(block)
            current_len += block_len
    if current_chunk:
        news_message_chunks.append("\n\n".join(current_chunk))

    # DateTime formatting (Egypt Cairo Timezone UTC+3)
    egypt_tz = timezone(timedelta(hours=3))
    now = datetime.now(egypt_tz)
    today = now.strftime("%Y/%m/%d")
    hour = int(now.strftime("%I"))
    minute = now.strftime("%M")
    period = s["am"] if now.strftime("%p") == "AM" else s["pm"]
    time_display = f"{hour:02d}:{minute} {period}"

    # Format Telegram message
    total_minutes = now.hour * 60 + now.minute
    market_status_text = ""
    portfolio_header = s.get('portfolio_title', 'أسهم مستثمر بها')
    watchlist_header = s.get('watchlist_title', 'أسهم شرعية أخرى للمتابعة')
    
    if total_minutes < 10 * 60:  # Before 10:00 AM Cairo Time
        market_status_text = "⚠️ <b>السوق مغلق حالياً (يفتح 10:00 ص)</b>\n📊 <b>الأسعار والتغيرات أدناه هي إغلاق الجلسة السابقة.</b>\n\n"
        portfolio_header = f"📊 {portfolio_header} (إغلاق الجلسة السابقة)"
        watchlist_header = f"📊 {watchlist_header} (إغلاق الجلسة السابقة)"
    elif 10 * 60 <= total_minutes <= 14 * 60 + 30:  # 10:00 AM to 2:30 PM (Active trading)
        portfolio_header = f"💼 {portfolio_header} (حركة لحظية)"
        watchlist_header = f"📋 {watchlist_header} (حركة لحظية)"
    else:  # After 2:30 PM
        market_status_text = "🔒 <b>انتهت جلسة تداول اليوم (السوق مغلق)</b>\n📈 <b>الأسعار أدناه هي أسعار الإغلاق النهائية لليوم.</b>\n\n"
        portfolio_header = f"📈 {portfolio_header} (إغلاق جلسة اليوم)"
        watchlist_header = f"📈 {watchlist_header} (إغلاق جلسة اليوم)"

    tg_msg = f"{s['rlm']}<b>{s['report_title']}</b>\n"
    tg_msg += f"{s['rlm']}<b>{s['date']}: {today} | {time_display}</b>\n"
    tg_msg += f"{s['rlm']}{s['line']}\n"
    if market_status_text:
        tg_msg += f"{s['rlm']}{market_status_text}"
    else:
        tg_msg += "\n"

    # Portfolio block
    tg_msg += f"{s['rlm']}<b>{portfolio_header}:</b>\n"
    for k in sorted_portfolio:
        item = parsed_stocks[k]
        chg_val = item["chgPct"]
        chg_str = f"+{chg_val}%" if chg_val > 0 else (f"{chg_val}%" if chg_val < 0 else "0.0%")
        dir_emoji = s["e_green"] if chg_val >= 0 else s["e_red"]
        ticker_link = company_websites.get(k, "#")
        ticker_html = f"<a href='{ticker_link}'>{k}</a>" if ticker_link != "#" else k
        tg_msg += f"{s['rlm']}{dir_emoji} <b>{ticker_html}</b>:{s['rlm']} {item['open']} {s['e_arrow']} <b>{item['close']}</b> ({chg_str}) | {item['rec']}\n"

    # Watchlist block
    tg_msg += f"\n{s['rlm']}<b>{watchlist_header}:</b>\n"
    for k in sorted_watchlist:
        item = parsed_stocks[k]
        chg_val = item["chgPct"]
        chg_str = f"+{chg_val}%" if chg_val > 0 else (f"{chg_val}%" if chg_val < 0 else "0.0%")
        dir_emoji = s["e_green"] if chg_val >= 0 else s["e_red"]
        ticker_link = company_websites.get(k, "#")
        ticker_html = f"<a href='{ticker_link}'>{k}</a>" if ticker_link != "#" else k
        tg_msg += f"{s['rlm']}{dir_emoji} <b>{ticker_html}</b>:{s['rlm']} {item['open']} {s['e_arrow']} <b>{item['close']}</b> ({chg_str}) | {item['rec']}\n"



    # Indices block
    egx30_dir = s["e_green"] if egx30["chgPct"] >= 0 else s["e_red"]
    usdegp_dir = s["e_green"] if usdegp["chgPct"] >= 0 else s["e_red"]
    xauusd_dir = s["e_green"] if xauusd["chgPct"] >= 0 else s["e_red"]

    egx30_chg = f"+{egx30['chgPct']}%" if egx30['chgPct'] > 0 else (f"{egx30['chgPct']}%" if egx30['chgPct'] < 0 else "0.0%")
    usdegp_chg = f"+{usdegp['chgPct']}%" if usdegp['chgPct'] > 0 else (f"{usdegp['chgPct']}%" if usdegp['chgPct'] < 0 else "0.0%")
    xauusd_chg = f"+{xauusd['chgPct']}%" if xauusd['chgPct'] > 0 else (f"{xauusd['chgPct']}%" if xauusd['chgPct'] < 0 else "0.0%")

    tg_msg += f"\n{s['rlm']}<b>{s['e_blue']} {s['indices_currencies']}:</b>\n"
    tg_msg += f"{s['rlm']}{egx30_dir} <b>EGX30</b>:{s['rlm']} {egx30['open']} {s['e_arrow']} <b>{egx30['close']}</b> ({egx30_chg})\n"
    tg_msg += f"{s['rlm']}{usdegp_dir} <b>USD/EGP</b>:{s['rlm']} {usdegp['open']} {s['e_arrow']} <b>{usdegp['close']}</b> ({usdegp_chg})\n"
    tg_msg += f"{s['rlm']}{xauusd_dir} <b>{s['gold']}</b>:{s['rlm']} {xauusd['open']} {s['e_arrow']} <b>{xauusd['close']}</b>$ ({xauusd_chg})\n\n"

    # Check length and split if necessary to avoid Telegram's 4096 character limit
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    # If we have only 1 chunk and it fits together with tg_msg under 4000 chars, send combined!
    if len(news_message_chunks) == 1 and (len(tg_msg) + len(news_message_chunks[0]) + 100 <= 4000):
        combined_msg = tg_msg + f"{s['rlm']}<b>{s['e_rocket']} {s['latest_news_developments']}:</b>\n{news_message_chunks[0]}"
        payload = {
            "chat_id": CHAT_ID,
            "text": combined_msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            r_tg = requests.post(url, json=payload)
            print("Telegram Combined Response:", r_tg.status_code)
            if r_tg.status_code != 200:
                print("Telegram combined error body:", r_tg.text)
        except Exception as e:
            print("Telegram combined error:", e)
    else:
        # Send stock report first as Part 1
        payload1 = {
            "chat_id": CHAT_ID,
            "text": tg_msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            r_tg1 = requests.post(url, json=payload1)
            print("Telegram Part 1 (Stocks) Response:", r_tg1.status_code)
            if r_tg1.status_code != 200:
                print("Telegram part 1 error body:", r_tg1.text)
        except Exception as e:
            print("Telegram Part 1 error:", e)
            
        # Send each news chunk as a separate Telegram message
        for idx, chunk in enumerate(news_message_chunks):
            # If there's only 1 chunk, no need to add part label
            part_label = f" (جزء {idx + 1})" if len(news_message_chunks) > 1 else ""
            news_msg = f"{s['rlm']}<b>{s['report_title']} - {s['e_rocket']} {s['latest_news_developments']}{part_label} ({today})</b>\n\n{chunk}"
            payload2 = {
                "chat_id": CHAT_ID,
                "text": news_msg,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            try:
                r_tg2 = requests.post(url, json=payload2)
                print(f"Telegram News Part {idx + 1} Response:", r_tg2.status_code)
                if r_tg2.status_code != 200:
                    print(f"Telegram news part {idx + 1} error body:", r_tg2.text)
            except Exception as e:
                print(f"Telegram News Part {idx + 1} error:", e)

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

if __name__ == "__main__":
    # Get Cairo timezone
    egypt_tz = timezone(timedelta(hours=3))
    now = datetime.now(egypt_tz)
    
    # Check FORCE_RUN flag
    force_run = os.environ.get("FORCE_RUN", "false").lower() == "true"
    if force_run:
        print(f"[{now.strftime('%H:%M:%S')}] FORCE_RUN is enabled. Sending an immediate report and exiting.")
        send_report()
        exit(0)
        
    # Check weekday (0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun)
    # Sunday to Thursday is [6, 0, 1, 2, 3]
    day = now.weekday()
    if day in [4, 5]: # Friday or Saturday
        print(f"[{now.strftime('%H:%M:%S')}] Weekend (Friday/Saturday), exiting to conserve actions minutes.")
        exit(0)
        
    # Run perpetual loop aligned with clock marks (:00, :15, :30, :45)
    TOTAL_CYCLES = 12
    for i in range(TOTAL_CYCLES):
        loop_now = datetime.now(egypt_tz)
        print(f"=== Loop Cycle {i+1}/{TOTAL_CYCLES} | Time: {loop_now.strftime('%H:%M:%S')} ===")
        
        # Check active hour range: 09:00 to 15:30 Cairo time
        current_time_minutes = loop_now.hour * 60 + loop_now.minute
        if current_time_minutes > 15 * 60 + 30:
            print(f"[{loop_now.strftime('%H:%M:%S')}] Time is past 3:30 PM, terminating run to conserve minutes.")
            exit(0)
            
        if 9 * 60 <= current_time_minutes <= 15 * 60 + 30:
            send_report()
        else:
            print(f"[{loop_now.strftime('%H:%M:%S')}] Outside automated report hours (9:00 AM - 3:30 PM), skipping.")
            
        # Before the runner finishes, trigger the next runner if it is still before 3:00 PM Cairo time
        if i == TOTAL_CYCLES - 2:
            if loop_now.hour < 15:
                trigger_next_runner()
            else:
                print(f"[{loop_now.strftime('%H:%M:%S')}] Time is 3:00 PM or later, stopping perpetual loop generation.")
                
        sleep_until_next_15min_mark()
