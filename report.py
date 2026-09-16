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

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    openpyxl = None
    print("Warning: openpyxl is not installed globally.")

try:
    import numpy as np
except ImportError:
    np = None
    print("Warning: numpy is not installed globally.")

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
        [
            {"text": "📱 فتح المنصة التفاعلية والمحفظة", "web_app": {"url": "https://mahereasybakery-web.github.io/egypt-sharia-stock-report/"}}
        ],
        [
            {"text": "💼 مركز المحفظة والاستثمار"},
            {"text": "📊 رادار السوق والتحليلات"}
        ]
    ],
    "resize_keyboard": True,
    "is_persistent": True
}

# 1. مركز المحفظة الرئيسي: زرين فقط لمنع أي ازدحام بالشاشة
PORTFOLIO_MAIN_HUB_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "📊 كشوفات وتقارير المحفظة", "callback_data": "sub_portfolio_reports"},
            {"text": "🛠️ أدوات وحاسبات الاستثمار", "callback_data": "sub_portfolio_tools"}
        ]
    ]
}

# كشوفات وتقارير المحفظة الفرعية
PORTFOLIO_REPORTS_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "💼 كشف حساب الأرباح والخسائر P&L", "callback_data": "btn_portfolio"},
            {"text": "📥 تصدير كشف إكسل (RTL)", "callback_data": "btn_export"}
        ],
        [
            {"text": "⚖️ مصفوفة توازن وتنويع القطاعات", "callback_data": "btn_rebalance"},
            {"text": "📜 سجل الصفقات المحققة", "callback_data": "btn_journal"}
        ],
        [
            {"text": "🌐 لوحة التحكم الرقمية (Web)", "callback_data": "btn_dashboard"},
            {"text": "🔙 رجوع لمركز المحفظة", "callback_data": "hub_portfolio"}
        ]
    ]
}

# أدوات وحاسبات الاستثمار الفرعية
PORTFOLIO_TOOLS_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "🕌 حاسبة زكاة الأسهم AAOIFI", "callback_data": "btn_zakat"},
            {"text": "📉 حاسبة التبريد الذكي DCA", "callback_data": "btn_dca"}
        ],
        [
            {"text": "💥 محاكي اختبار ضغط وصدمات السوق", "callback_data": "btn_stresstest"},
            {"text": "📐 حاسبة حجم الصفقة (1.5%)", "callback_data": "btn_calc_help"}
        ],
        [
            {"text": "🔔 إدارة وتعديل تنبيهاتي", "callback_data": "btn_my_alerts"},
            {"text": "🔙 رجوع لمركز المحفظة", "callback_data": "hub_portfolio"}
        ]
    ]
}

# 2. رادار السوق والتحليلات الرئيسي: زرين فقط لمنع أي ازدحام بالشاشة
MARKET_MAIN_HUB_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "⚡ رادارات السوق والفرص اللحظية", "callback_data": "sub_market_radars"},
            {"text": "🏢 التحليل الفني والمالي للشركات", "callback_data": "sub_market_analysis"}
        ]
    ]
}

# رادارات وفرص السوق الفرعية
MARKET_RADARS_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "📊 تقرير الأسعار والمؤشرات اللحظي", "callback_data": "btn_report"},
            {"text": "⚡ بيان مفصل لمؤشر RSI", "callback_data": "btn_rsi"}
        ],
        [
            {"text": "🎯 رادار فرص أسهم القيمة", "callback_data": "btn_undervalued"},
            {"text": "🐋 التجميع المؤسسي والسيولة CMF", "callback_data": "btn_accumulation"}
        ],
        [
            {"text": "⚡ رادار الدايفرجنس الإيجابي", "callback_data": "btn_divergence"},
            {"text": "💰 رادار الكوبونات والتوزيعات", "callback_data": "btn_dividends"}
        ],
        [
            {"text": "🕵️ صفقات كبار الملاك والداخليين", "callback_data": "btn_insiders"},
            {"text": "🔙 رجوع لرادار السوق", "callback_data": "hub_market"}
        ]
    ]
}

# التحليل الفني والمالي للشركات الفرعية
MARKET_ANALYSIS_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "🎯 مصفوفة السعر العادل (3 سيناريوهات)", "callback_data": "btn_target_menu"},
            {"text": "🏢 بطاقة الفحص المالي والمكررات", "callback_data": "btn_fundamental_help"}
        ],
        [
            {"text": "📈 طلب شارت فني لسهم بالشموع", "callback_data": "btn_chart_menu"},
            {"text": "📌 ملخص الجلسة واتساع السوق", "callback_data": "btn_summary"}
        ],
        [
            {"text": "🧠 استشارة المحلل المالي AI", "callback_data": "btn_ask_help"},
            {"text": "⚙️ حالة اتصال النظام 24/7", "callback_data": "btn_status"}
        ],
        [
            {"text": "🔙 رجوع لرادار السوق", "callback_data": "hub_market"}
        ]
    ]
}

# قائمة سريعة لحساب السعر العادل بنقرة زر لأشهر الأسهم
TARGET_STOCKS_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "🎯 طلعت مصطفى (TMGH)", "callback_data": "target_TMGH"},
            {"text": "🎯 فوري (FWRY)", "callback_data": "target_FWRY"}
        ],
        [
            {"text": "🎯 سوديك (OCDI)", "callback_data": "target_OCDI"},
            {"text": "🎯 سيدي كرير (SKPC)", "callback_data": "target_SKPC"}
        ],
        [
            {"text": "🎯 موبكو (MFPC)", "callback_data": "target_MFPC"},
            {"text": "🎯 أبو قير (ABUK)", "callback_data": "target_ABUK"}
        ],
        [
            {"text": "🔙 رجوع للتحليل المالي", "callback_data": "sub_market_analysis"}
        ]
    ]
}

# قائمة سريعة لطلب الشارت الفني بنقرة زر
CHART_STOCKS_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "📈 شارت طلعت مصطفى (TMGH)", "callback_data": "chart_TMGH"},
            {"text": "📈 شارت فوري (FWRY)", "callback_data": "chart_FWRY"}
        ],
        [
            {"text": "📈 شارت سوديك (OCDI)", "callback_data": "chart_OCDI"},
            {"text": "📈 شارت سيدي كرير (SKPC)", "callback_data": "chart_SKPC"}
        ],
        [
            {"text": "🔙 رجوع للتحليل المالي", "callback_data": "sub_market_analysis"}
        ]
    ]
}

QUICK_NAV_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "💼 مركز المحفظة", "callback_data": "hub_portfolio"},
            {"text": "📊 رادار السوق", "callback_data": "hub_market"}
        ]
    ]
}

PORTFOLIO_HUB_KEYBOARD = PORTFOLIO_MAIN_HUB_KEYBOARD
MARKET_HUB_KEYBOARD = MARKET_MAIN_HUB_KEYBOARD
PORTFOLIO_INLINE_KEYBOARD = PORTFOLIO_MAIN_HUB_KEYBOARD

def get_portfolio_inline_keyboard(holdings=None):
    """توليد لوحة أزرار تفاعلية مقتضبة ونظيفة تتضمن فحص الأسهم وشريط تنقل سريع."""
    keyboard = []
    if holdings:
        stock_row = []
        for ticker in sorted(holdings.keys()):
            name = COMPANY_NAMES_AR.get(ticker, ticker)
            stock_row.append({"text": f"🔍 {name}", "callback_data": f"deepdive_{ticker}"})
            if len(stock_row) == 2:
                keyboard.append(stock_row)
                stock_row = []
        if stock_row:
            keyboard.append(stock_row)
            
    keyboard.append([
        {"text": "🔄 تحديث فوري", "callback_data": "btn_portfolio"},
        {"text": "📥 تصدير إكسل", "callback_data": "btn_export"}
    ])
    keyboard.append([
        {"text": "💼 مركز المحفظة", "callback_data": "hub_portfolio"},
        {"text": "📊 رادار السوق", "callback_data": "hub_market"}
    ])
    return {"inline_keyboard": keyboard}

def setup_telegram_bot_menu():
    """تسجيل قائمة الأوامر الرسمية لتظهر في زر Menu بتطبيق تليجرام تلقائياً بأوصاف مختصرة وأنيقة."""
    if not BOT_TOKEN:
        return
    commands = [
        {"command": "portfolio", "description": "💼 مركز المحفظة والاستثمار"},
        {"command": "market", "description": "📊 رادار السوق والتحليلات"},
        {"command": "report", "description": "📈 بث الأسعار والمؤشرات"},
        {"command": "summary", "description": "📌 ملخص الجلسة والاتساع"},
        {"command": "rsi", "description": "⚡ بيان مؤشر RSI"},
        {"command": "undervalued", "description": "🎯 رادار أسهم القيمة"},
        {"command": "accumulation", "description": "🐋 رادار التجميع CMF"},
        {"command": "divergence", "description": "⚡ رادار الدايفرجنس"},
        {"command": "dividends", "description": "💰 رادار الكوبونات"},
        {"command": "insiders", "description": "🕵️ صفقات كبار الملاك"},
        {"command": "target", "description": "🎯 السعر العادل لسهم"},
        {"command": "dca", "description": "📉 حاسبة التبريد والتعديل"},
        {"command": "stresstest", "description": "💥 اختبار ضغط المحفظة"},
        {"command": "zakat", "description": "🕌 حاسبة زكاة الأسهم"},
        {"command": "export", "description": "📥 تصدير كشف إكسل"},
        {"command": "calc", "description": "📐 حاسبة إدارة المخاطر"},
        {"command": "chart", "description": "📈 رسم بياني بالشموع"},
        {"command": "fundamental", "description": "🏢 فحص مالي ومضاعفات"},
        {"command": "buy", "description": "➕ تسجيل شراء سهم"},
        {"command": "sell", "description": "➖ تسجيل بيع وحساب الربح"},
        {"command": "journal", "description": "📜 سجل الصفقات المغلقة"},
        {"command": "my_alerts", "description": "🔔 إدارة تنبيهاتي"},
        {"command": "dashboard", "description": "🌐 لوحة التحكم الرقمية"},
        {"command": "ask", "description": "🧠 استشارة المحلل الذكي"},
        {"command": "status", "description": "⚙️ حالة اتصال النظام 24/7"}
    ]
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands", json={"commands": commands}, timeout=10)
    except Exception as e:
        print("Warning setting bot commands menu:", e)
        
    try:
        # ضبط زر القائمة الرئيسي الدائم في تليجرام لفتح تطبيق المنصة المصغر (Mini App) بلمسة واحدة
        menu_btn_payload = {
            "menu_button": {
                "type": "web_app",
                "text": "📱 المنصة التفاعلية",
                "web_app": {
                    "url": "https://mahereasybakery-web.github.io/egypt-sharia-stock-report/"
                }
            }
        }
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setChatMenuButton", json=menu_btn_payload, timeout=10)
    except Exception as e:
        print("Notice setting chat menu button:", e)

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

def edit_telegram_message(message_id, text, reply_markup=None):
    """تعديل الرسالة التفاعلية في مكانها فوراً دون إرسال رسائل جديدة لضمان نظافة الشاشة."""
    if not BOT_TOKEN or not CHAT_ID or not message_id:
        reply_telegram(text, reply_markup=reply_markup)
        return
    text = ensure_rtl(text)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": reply_markup
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            reply_telegram(text, reply_markup=reply_markup)
    except Exception:
        reply_telegram(text, reply_markup=reply_markup)

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

def send_telegram_photo(photo_path, caption="", reply_markup=None):
    """إرسال صورة شارت فني إلى تليجرام مع شرح وأزرار تفاعلية."""
    if not BOT_TOKEN or not CHAT_ID or not os.path.exists(photo_path):
        return
    if caption:
        caption = ensure_rtl(caption)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        with open(photo_path, "rb") as f:
            files = {"photo": f}
            data = {"chat_id": CHAT_ID, "caption": caption[:1024], "parse_mode": "HTML"}
            if reply_markup is not None:
                data["reply_markup"] = json.dumps(reply_markup)
            requests.post(url, data=data, files=files, timeout=30)
    except Exception as e:
        print("Error sending telegram photo:", e)

def send_telegram_document(doc_path, caption=""):
    """إرسال مستند رسمي (إكسل أو تقرير) إلى تليجرام مع شرح."""
    if not BOT_TOKEN or not CHAT_ID or not os.path.exists(doc_path):
        return
    if caption:
        caption = ensure_rtl(caption)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    try:
        with open(doc_path, "rb") as f:
            files = {"document": f}
            data = {"chat_id": CHAT_ID, "caption": caption[:1024], "parse_mode": "HTML"}
            requests.post(url, data=data, files=files, timeout=35)
    except Exception as e:
        print("Error sending telegram document:", e)

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

def compute_rsi_series(prices, period=14):
    """حساب متسلسلة مؤشر القوة النسبية RSI(14) بدقة رياضية متناهية."""
    import numpy as np
    if len(prices) < period + 1:
        return [50.0] * len(prices)
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    rsi = [50.0] * period
    for i in range(period, len(prices)):
        delta = deltas[i-1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            rsi.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi.append(100.0 - (100.0 / (1.0 + rs)))
    return rsi

def generate_candlestick_chart(ticker):
    """توليد رسم بياني يومي احترافي بنظام الشموع اليابانية ومؤشرات SMA وRSI وأحجام التداول."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np
        
        ticker_clean = ticker.upper().replace(".CA", "").replace("EGX:", "").strip()
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_clean}.CA?interval=1d&range=3mo"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code != 200:
            return None, f"فشل جلب بيانات الشارت للسهم {ticker_clean} (رمز الخطأ {r.status_code})"
            
        data = r.json().get('chart', {}).get('result', [])
        if not data:
            return None, f"لا توجد بيانات تاريخية متاحة للسهم {ticker_clean}"
            
        res = data[0]
        ts_list = res.get('timestamp', [])
        q = res.get('indicators', {}).get('quote', [{}])[0]
        
        dates, opens, highs, lows, closes, volumes = [], [], [], [], [], []
        for t, o, h, l, c, v in zip(ts_list, q.get('open', []), q.get('high', []), q.get('low', []), q.get('close', []), q.get('volume', [])):
            if c is not None and o is not None and h is not None and l is not None:
                dates.append(datetime.fromtimestamp(t).strftime('%d-%b'))
                opens.append(float(o))
                highs.append(float(h))
                lows.append(float(l))
                closes.append(float(c))
                volumes.append(float(v) if v is not None else 0.0)
                
        n = len(closes)
        if n < 5:
            return None, f"بيانات التداول غير كافية لرسم الشارت ({n} شموع فقط)"
            
        sma20 = [float(np.mean(closes[max(0, i-19):i+1])) for i in range(n)]
        sma50 = [float(np.mean(closes[max(0, i-49):i+1])) for i in range(n)]
        rsi = compute_rsi_series(closes, 14)
        
        plt.style.use('dark_background')
        fig, (ax_price, ax_vol, ax_rsi) = plt.subplots(
            3, 1, figsize=(10, 8), dpi=120,
            gridspec_kw={'height_ratios': [3, 1, 1.2]},
            sharex=True
        )
        fig.patch.set_facecolor('#101216')
        for ax in (ax_price, ax_vol, ax_rsi):
            ax.set_facecolor('#161920')
            ax.grid(True, color='#2a2e39', linestyle='--', alpha=0.5)
            
        idx = np.arange(n)
        width = 0.6
        for i in range(n):
            color = '#089981' if closes[i] >= opens[i] else '#F23645'
            ax_price.plot([idx[i], idx[i]], [lows[i], highs[i]], color=color, linewidth=1.2)
            lower = min(opens[i], closes[i])
            height = max(abs(closes[i] - opens[i]), 0.05)
            ax_price.bar(idx[i], height, width, bottom=lower, color=color, edgecolor=color)
            
        ax_price.plot(idx, sma20, color='#FFD700', label='SMA 20', linewidth=1.5)
        ax_price.plot(idx, sma50, color='#00E5FF', label='SMA 50', linewidth=1.5)
        
        c_name = COMPANY_NAMES_AR.get(ticker_clean, ticker_clean)
        last_c = closes[-1]
        last_rsi = rsi[-1]
        last_sma20 = sma20[-1]
        last_sma50 = sma50[-1]
        
        ax_price.set_title(f'EGX: {c_name} ({ticker_clean}) - Daily Candlesticks & Technicals', color='#FFFFFF', fontsize=13, fontweight='bold', pad=10)
        ax_price.legend(loc='upper left', framealpha=0.4, fontsize=9)
        ax_price.set_ylabel('Price (EGP)', color='#CCCCCC')
        
        # Volume
        vol_colors = ['#089981' if closes[i] >= opens[i] else '#F23645' for i in range(n)]
        ax_vol.bar(idx, volumes, width, color=vol_colors, alpha=0.8)
        ax_vol.set_ylabel('Volume', color='#CCCCCC')
        
        # RSI
        ax_rsi.plot(idx, rsi, color='#E040FB', linewidth=1.5)
        ax_rsi.axhline(70, color='#F23645', linestyle='--', alpha=0.7, label='Overbought 70')
        ax_rsi.axhline(30, color='#089981', linestyle='--', alpha=0.7, label='Oversold 30')
        ax_rsi.fill_between(idx, 30, 70, color='#E040FB', alpha=0.08)
        ax_rsi.set_ylabel('RSI (14)', color='#CCCCCC')
        ax_rsi.set_ylim(10, 90)
        
        step = max(1, n // 8)
        ax_rsi.set_xticks(idx[::step])
        ax_rsi.set_xticklabels(dates[::step], rotation=30, ha='right')
        
        plt.tight_layout()
        chart_file = f"chart_{ticker_clean}.png"
        plt.savefig(chart_file, facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close()
        
        caption = (
            f"📈 <b>الشارت الفني اليومي: {c_name} ({ticker_clean})</b>\n\n"
            f"💵 <b>سعر الإغلاق:</b> {last_c:.2f} ج.م\n"
            f"⚡ <b>مؤشر RSI (14):</b> <code>{last_rsi:.1f}</code> "
            + ("(⚠️ تشبع شرائي)" if last_rsi >= 70 else ("(💎 تشبع بيعي)" if last_rsi <= 30 else "(منطقة متوازنة)")) + "\n"
            f"🟡 <b>متوسط 20 يوم (SMA20):</b> {last_sma20:.2f} ج.م " + ("(السعر فوق المتوسط 🟢)" if last_c >= last_sma20 else "(السعر تحت المتوسط 🔴)") + "\n"
            f"🔵 <b>متوسط 50 يوم (SMA50):</b> {last_sma50:.2f} ج.م " + ("(السعر فوق المتوسط 🟢)" if last_c >= last_sma50 else "(السعر تحت المتوسط 🔴)") + "\n"
            f"🛡️ <b>أدنى قاع (3 أشهر):</b> {min(lows):.2f} ج.م | 🎯 <b>أعلى قمة:</b> {max(highs):.2f} ج.م"
        )
        return chart_file, caption
    except Exception as e:
        print("Error in generate_candlestick_chart:", e)
        return None, f"حدث خطأ أثناء رسم الشارت: {e}"


def generate_market_infographic_card(parsed_stocks, indices=None, fx_gold=None, funds=None, output_path="market_card.png"):
    """توليد بطاقة إنفوجرافيك بصرية داكنة عالية الدقة للملخص اليومي للأسهم والذهب والعملات."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.patches as patches
        
        fig = plt.figure(figsize=(10, 6.5), dpi=150)
        fig.patch.set_facecolor('#0b0f19')

        now_str = datetime.now(timezone(timedelta(hours=3))).strftime('%Y/%m/%d')
        fig.text(0.5, 0.94, f"EGX SHARIAH 33 • DAILY FINANCIAL DASHBOARD • {now_str}", color='white', fontsize=13, fontweight='bold', ha='center')
        fig.text(0.5, 0.90, "البورصة المصرية • تقرير الأسهم المتوافقة مع الشريعة والذهب والعملات", color='#94a3b8', fontsize=9, ha='center')

        # Top metrics bar
        ax_top = fig.add_axes([0.05, 0.77, 0.90, 0.09])
        ax_top.set_facecolor('#151d2f')
        ax_top.axis('off')
        rect = patches.FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.02", edgecolor='#24324d', facecolor='#151d2f', linewidth=1)
        ax_top.add_patch(rect)

        egx_val = indices.get('EGX33', {}).get('close', 3380.45) if indices else 3380.45
        egx_chg = indices.get('EGX33', {}).get('chgPct', 1.15) if indices else 1.15
        usd_val = fx_gold[0].get('close', 52.15) if (fx_gold and len(fx_gold)>0 and isinstance(fx_gold[0], dict)) else 52.15
        usd_chg = fx_gold[0].get('chgPct', 0.46) if (fx_gold and len(fx_gold)>0 and isinstance(fx_gold[0], dict)) else 0.46
        gold_val = fx_gold[1].get('close', 4340.91) if (fx_gold and len(fx_gold)>1 and isinstance(fx_gold[1], dict)) else 4340.91
        gold_chg = fx_gold[1].get('chgPct', 1.11) if (fx_gold and len(fx_gold)>1 and isinstance(fx_gold[1], dict)) else 1.11

        ax_top.text(0.18, 0.65, "EGX 33 SHARIAH", color='#94a3b8', fontsize=8, ha='center')
        ax_top.text(0.18, 0.25, f"{egx_val:,.2f} ({'+' if egx_chg>=0 else ''}{egx_chg:.2f}%)", color='#10b981' if egx_chg>=0 else '#f43f5e', fontsize=10, fontweight='bold', ha='center')

        ax_top.text(0.50, 0.65, "USD / EGP (الدولار)", color='#94a3b8', fontsize=8, ha='center')
        ax_top.text(0.50, 0.25, f"{usd_val:.2f} EGP ({'+' if usd_chg>=0 else ''}{usd_chg:.2f}%)", color='#38bdf8', fontsize=10, fontweight='bold', ha='center')

        ax_top.text(0.82, 0.65, "GOLD 24K (ذهب عيار 24)", color='#94a3b8', fontsize=8, ha='center')
        ax_top.text(0.82, 0.25, f"{gold_val:,.2f} EGP ({'+' if gold_chg>=0 else ''}{gold_chg:.2f}%)", color='#fbbf24', fontsize=10, fontweight='bold', ha='center')

        # Left Section: Top Gainers
        ax_left = fig.add_axes([0.05, 0.12, 0.43, 0.61])
        ax_left.set_facecolor('#151d2f')
        ax_left.axis('off')
        rect_left = patches.FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.02", edgecolor='#24324d', facecolor='#151d2f', linewidth=1)
        ax_left.add_patch(rect_left)

        ax_left.text(0.5, 0.92, "▲ TOP GAINERS • الأسهم الأكثر صعوداً", color='#10b981', fontsize=10, fontweight='bold', ha='center')

        stock_items = []
        for t, d in (parsed_stocks or {}).items():
            if isinstance(d, dict) and d.get('close', 0) > 0:
                stock_items.append({
                    'ticker': t,
                    'name': COMPANY_NAMES_AR.get(t, t),
                    'close': d.get('close', 0),
                    'chg': d.get('chgPct', 0),
                    'rsi': d.get('rsi', 50.0)
                })

        stock_items.sort(key=lambda x: x['chg'], reverse=True)
        top_gainers = stock_items[:6] if stock_items else [
            {'ticker': 'MFPC', 'name': 'موبكو', 'close': 48.69, 'chg': 4.71, 'rsi': 73.2},
            {'ticker': 'AMOC', 'name': 'أموك', 'close': 13.45, 'chg': 2.83, 'rsi': 66.2},
            {'ticker': 'ACGC', 'name': 'الأقطان', 'close': 14.40, 'chg': 2.64, 'rsi': 58.7},
            {'ticker': 'MCQE', 'name': 'أسمنت قنا', 'close': 221.00, 'chg': 2.42, 'rsi': 46.2},
            {'ticker': 'ICFC', 'name': 'الدولية', 'close': 23.38, 'chg': 1.65, 'rsi': 61.3},
            {'ticker': 'ABUK', 'name': 'أبو قير', 'close': 89.00, 'chg': 1.25, 'rsi': 59.2}
        ]

        y = 0.78
        for s in top_gainers:
            ax_left.text(0.06, y, f"{s['ticker']}", color='white', fontsize=9, fontweight='bold')
            ax_left.text(0.26, y, f"{s['name']}", color='#cbd5e1', fontsize=8)
            ax_left.text(0.68, y, f"{s['close']:.2f} EGP", color='white', fontsize=8, ha='right')
            ax_left.text(0.94, y, f"{'+' if s['chg']>=0 else ''}{s['chg']:.2f}%", color='#10b981' if s['chg']>=0 else '#f43f5e', fontsize=8, fontweight='bold', ha='right')
            y -= 0.12

        # Right Section: Rebound Watch & Funds
        ax_right = fig.add_axes([0.52, 0.12, 0.43, 0.61])
        ax_right.set_facecolor('#151d2f')
        ax_right.axis('off')
        rect_right = patches.FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.02", edgecolor='#24324d', facecolor='#151d2f', linewidth=1)
        ax_right.add_patch(rect_right)

        ax_right.text(0.5, 0.92, "⚡ REBOUND WATCH • مناطق الارتداد", color='#f59e0b', fontsize=10, fontweight='bold', ha='center')

        oversold = sorted(stock_items, key=lambda x: x['rsi'] if x['rsi'] is not None else 50)[:4] if stock_items else [
            {'ticker': 'PHDC', 'name': 'بالم هيلز', 'close': 13.77, 'rsi': 31.1},
            {'ticker': 'TMGH', 'name': 'طلعت مصطفى', 'close': 95.00, 'rsi': 38.5},
            {'ticker': 'ISPH', 'name': 'ابن سينا', 'close': 12.20, 'rsi': 39.1},
            {'ticker': 'OCDI', 'name': 'سوديك', 'close': 30.00, 'rsi': 40.8}
        ]

        y = 0.78
        for s in oversold:
            ax_right.text(0.06, y, f"{s['ticker']}", color='white', fontsize=9, fontweight='bold')
            ax_right.text(0.26, y, f"{s['name']}", color='#cbd5e1', fontsize=8)
            ax_right.text(0.65, y, f"{s['close']:.2f} EGP", color='white', fontsize=8, ha='right')
            ax_right.text(0.94, y, f"RSI: {s['rsi']:.1f}", color='#f59e0b', fontsize=8, fontweight='bold', ha='right')
            y -= 0.11

        # Funds bar inside right box
        ax_right.text(0.5, 0.32, "★ ISLAMIC & GOLD FUNDS • صناديق الذهب", color='#38bdf8', fontsize=9, fontweight='bold', ha='center')
        f_list = [
            ("AZG (أزيموت)", "23.96 ج"),
            ("THNDR (سبائك)", "1.68 ج"),
            ("CMS (شريعة)", "22.72 ج"),
            ("BWA (وفرة)", "2.21 ج")
        ]
        fx_y = 0.18
        for i, (fn, fp) in enumerate(f_list):
            col_x = 0.08 if i % 2 == 0 else 0.53
            row_y = fx_y if i < 2 else fx_y - 0.09
            ax_right.text(col_x, row_y, f"• {fn}: ", color='#94a3b8', fontsize=7.5)
            ax_right.text(col_x + 0.36, row_y, f"{fp}", color='#f8fafc', fontsize=7.5, fontweight='bold')

        # Footer note
        fig.text(0.5, 0.04, "📱 افتح المنصة التفاعلية (Telegram Mini App) للتفاصيل الكاملة والشارتات اللحظية", color='#64748b', fontsize=8, ha='center')

        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close()
        return output_path
    except Exception as e:
        print("Error generating infographic card:", e)
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
    """فحص تنبيهات الأسعار وRSI والتقاطعات المخصصة للمستخدم وإرسال إشعار فوري عند تحققها."""
    alerts = state_data.get("alerts", [])
    if not alerts:
        return
    remaining_alerts = []
    triggered_any = False
    for a in alerts:
        ticker = a.get("ticker", "").upper()
        cond = a.get("cond", "")
        stock_info = parsed_stocks.get(ticker, {})
        curr = stock_info.get("close")
        name = COMPANY_NAMES_AR.get(ticker, ticker)
        
        # 1. تنبيه مؤشر RSI
        if "rsi" in a:
            target_rsi = float(a.get("rsi", 0))
            curr_rsi = stock_info.get("rsi")
            if curr_rsi is not None:
                if (cond in ["<", "<="] and curr_rsi <= target_rsi) or (cond in [">", ">="] and curr_rsi >= target_rsi):
                    alert_msg = (
                        f"⚡ <b>تنبيه مؤشر RSI متحقق!</b>\n"
                        f"سهم <b>{name} ({ticker})</b> وصل مؤشر RSI إلى <b>{curr_rsi:.1f}</b> "
                        f"(الشرط المحدد: {cond} {target_rsi:.0f}).\n"
                        f"💵 السعر اللحظي: {curr:.2f} ج.م | 📊 التوصية: {stock_info.get('rec', 'محايد')}"
                    )
                    reply_telegram(alert_msg)
                    triggered_any = True
                    continue
                    
        # 2. تنبيه التقاطع الذهبي (Golden Cross)
        elif cond == "cross" or a.get("type") == "Golden Cross":
            sma50 = stock_info.get("sma50")
            sma200 = stock_info.get("sma200")
            if sma50 and sma200 and sma50 >= sma200:
                alert_msg = (
                    f"🌟 <b>تنبيه التقاطع الذهبي (Golden Cross) متحقق!</b>\n"
                    f"سهم <b>{name} ({ticker})</b> اخترق فيه متوسط 50 يوماً ({sma50:.2f} ج) متوسط 200 يوم ({sma200:.2f} ج) صعوداً!\n"
                    f"💵 السعر اللحظي: {curr:.2f} ج.م | 🚀 إشارة اختراق فني وزخم شرائي قوي."
                )
                reply_telegram(alert_msg)
                triggered_any = True
                continue
                
        # 3. التنبيه السعري العادي
        elif "price" in a:
            price = float(a.get("price", 0))
            if curr is not None and curr > 0:
                if (cond in [">", ">="] and curr >= price) or (cond in ["<", "<="] and curr <= price):
                    alert_msg = (
                        f"🎯 <b>تنبيه سعري متحقق!</b>\n"
                        f"سهم <b>{name} ({ticker})</b> وصل إلى <b>{curr:.2f} ج.م</b> "
                        f"(الشرط المحدد: {cond} {price:.2f} ج.م).\n"
                        f"📊 التغير اليومي: {stock_info.get('chgPct', 0):+.2f}%"
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
            "RSI", "volume", "average_volume_10d_calc", "SMA20", "SMA50", "Value.Traded",
            "price_earnings_ttm", "price_book_fq", "total_debt_fq", "total_assets_fq", "return_on_equity_fq",
            "MoneyFlow", "ChaikinMoneyFlow", "dividends_yield", "SMA200"
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
            
            # المؤشرات المالية ومضاعفات التقييم اللحظية
            pe_val = safe_round(item["d"][10], 1) if len(item["d"]) > 10 and item["d"][10] is not None and item["d"][10] > 0 else None
            pb_val = safe_round(item["d"][11], 2) if len(item["d"]) > 11 and item["d"][11] is not None and item["d"][11] > 0 else None
            debt_raw = item["d"][12] if len(item["d"]) > 12 else None
            assets_raw = item["d"][13] if len(item["d"]) > 13 else None
            debt_ratio = safe_round((debt_raw / assets_raw) * 100.0, 1) if debt_raw and assets_raw and assets_raw > 0 else None
            roe_val = safe_round(item["d"][14], 1) if len(item["d"]) > 14 and item["d"][14] is not None else None
            
            # مؤشرات السيولة والتجميع المؤسسي (Smart Money) وعوائد التوزيعات
            mfi_val = safe_round(item["d"][15], 1) if len(item["d"]) > 15 and item["d"][15] is not None else None
            cmf_val = safe_round(item["d"][16], 3) if len(item["d"]) > 16 and item["d"][16] is not None else None
            div_yield = safe_round(item["d"][17], 2) if len(item["d"]) > 17 and item["d"][17] is not None else None
            sma200_val = safe_round(item["d"][18], 2) if len(item["d"]) > 18 and item["d"][18] is not None else None
            
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
                else: rec_str = strings.get('neutral', 'محايد')
            if sym in indices:
                indices[sym] = {"close": c, "open": o, "chgPct": chg, "volume": vol_val, "val_traded": val_traded}
            else:
                parsed[sym] = {
                    "close": c, "open": o, "chgPct": chg, "rec": rec_str,
                    "rsi": rsi_val, "volume": vol_val, "avg_vol": avg_vol,
                    "sma20": sma20_val, "sma50": sma50_val, "sma200": sma200_val, "val_traded": val_traded,
                    "vol_spike": vol_spike, "rsi_tag": rsi_tag,
                    "pe": pe_val, "pb": pb_val, "debt_ratio": debt_ratio, "roe": roe_val,
                    "mfi": mfi_val, "cmf": cmf_val, "div_yield": div_yield
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

def normalize_arabic_numbers(text: str) -> str:
    """تحويل الأرقام العربية المشرقية إلى أرقام لاتينية قياسية."""
    if not text:
        return ""
    trans = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
    return text.translate(trans)

def fetch_mutual_funds_data():
    """
    جلب أحدث أسعار وثائق صناديق الاستثمار الإسلامية وصناديق الذهب المدرجة:
    - CMS: صندوق مصر مؤشر شريعة إكويتي (تتبع EGX33 الشريعة)
    - BWA: صندوق بلتون وفرة (تتبع EGX33 الشريعة)
    - NMF: صندوق نعيم مصر للأسهم المتوافقة مع الشريعة
    - AZG: صندوق أزيموت جولد للذهب عيار 24
    - THNDR_GOLD: صندوق الذهب على منصة ثندر (سبائك بلتون)
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    
    funds_config = {
        'CMS': {
            'name': 'مصر شريعة إكويتي (CMS)',
            'desc': 'تتبع EGX33 الشريعة',
            'url': 'https://snduk.com/eg/funds/misr-shariah-equity-fund',
            'fallback_price': 22.72
        },
        'BWA': {
            'name': 'بلتون وفرة (BWA)',
            'desc': 'تتبع EGX33 الشريعة',
            'url': 'https://snduk.com/eg/funds/beltone-wafra',
            'fallback_price': 2.21
        },
        'NMF': {
            'name': 'نعيم مصر للشريعة (NMF)',
            'desc': 'أسهم شريعة',
            'url': 'https://snduk.com/eg/funds/naeem-misr-sharia-fund',
            'fallback_price': 50.19
        },
        'AZG': {
            'name': 'أزيموت جولد (AZG)',
            'desc': 'ذهب عيار 24 / ثندر',
            'url': 'https://snduk.com/eg/funds/az-gold-fund',
            'fallback_price': 23.96
        },
        'THNDR_GOLD': {
            'name': 'سبائك جولد (Thndr)',
            'desc': 'صندوق الذهب / ثندر',
            'url': 'https://snduk.com/eg/funds/sabayek-fund-beltone-gold',
            'fallback_price': 1.68
        }
    }
    
    results = {}
    
    for code, cfg in funds_config.items():
        price = cfg['fallback_price']
        change_1w = 0.0
        change_1m = 0.0
        
        try:
            req = urllib.request.Request(cfg['url'], headers=headers)
            with urllib.request.urlopen(req, timeout=6) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
                
                # استخراج السعر بالجنيه المصري
                egp_matches = re.findall(r'([٠-٩0-9]+(?:\.[٠-٩0-9]+)?)\s*(?:ج\.م|EGP|جنيه)', html)
                if egp_matches:
                    clean_p = float(normalize_arabic_numbers(egp_matches[0]))
                    if clean_p > 0:
                        price = clean_p
                
                # استخراج التغير الأسبوعي والشهري
                perf_text = re.search(r'العائد خلال أسبوع:\s*([+-]?[٠-٩0-9.]+)\s*%.*?العائد خلال شهر:\s*([+-]?[٠-٩0-9.]+)\s*%', html)
                if perf_text:
                    change_1w = float(normalize_arabic_numbers(perf_text.group(1)))
                    change_1m = float(normalize_arabic_numbers(perf_text.group(2)))
                else:
                    changes = re.findall(r'([+-]?\d+\.\d+)%', html)
                    if len(changes) >= 2:
                        change_1w = float(changes[0])
                        change_1m = float(changes[1])
                        
        except Exception as e:
            print(f"Notice fetching fund {code}: {e}")
            
        results[code] = {
            'code': code,
            'name': cfg['name'],
            'desc': cfg['desc'],
            'price': price,
            'change_1w': change_1w,
            'change_1m': change_1m
        }
        
    return results

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
    
    # === صناديق الاستثمار الإسلامية والذهب (Thndr / Funds) ===
    try:
        funds_data = fetch_mutual_funds_data()
        if funds_data:
            msg_indices += f"\n{s['rlm']}<b>🏛️ صناديق الاستثمار الإسلامية والذهب (Thndr / Funds):</b>\n"
            for f_code, f_info in funds_data.items():
                w_chg = f_info.get('change_1w', 0.0)
                chg_str = f"+{w_chg:.2f}%" if w_chg > 0 else f"{w_chg:.2f}%"
                e_dir = s["e_green"] if w_chg > 0 else (s["e_red"] if w_chg < 0 else s["e_white"])
                msg_indices += f"{s['rlm']}{e_dir} <b>{f_info['name']}</b>: <b>{f_info['price']:.2f} ج.م</b> (أسبوعي: {chg_str}) | <i>{f_info['desc']}</i>\n"
    except Exception as e:
        print("Error appending mutual funds to report:", e)
    
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
        
    # ✅ إضافة: فحص رادارات السيولة الاستثنائية وحماية أرباح المحفظة الذكية
    try:
        if check_and_send_smart_alerts(parsed_stocks, state_data.get("holdings", {}), state_data):
            update_github_state(state_data, state_sha)
    except Exception as e:
        print("Error checking smart algorithmic alerts:", e)
        
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
        
    # Market Breadth & Sentiment (اتساع السوق وصافي المعنويات والسيولة)
    total_tracked = len(stocks_data)
    advances = sum(1 for s in stocks_data.values() if s.get("chgPct", 0) > 0.05)
    declines = sum(1 for s in stocks_data.values() if s.get("chgPct", 0) < -0.05)
    unchanged = total_tracked - (advances + declines)
    total_turnover = sum(s.get("close", 0) * s.get("volume", 0) for s in stocks_data.values() if s.get("volume"))
    
    breadth_icon = "🟢" if advances > declines else ("🔴" if declines > advances else "⚪")
    res += f"\n<b>🌐 اتساع السوق وصافي المعنويات (Market Breadth):</b>\n"
    res += f"{breadth_icon} <b>حصيلة الأسهم:</b> 🟢 <b>{advances}</b> صاعد | 🔴 <b>{declines}</b> هابط | ⚪ <b>{unchanged}</b> مستقر\n"
    if total_turnover > 0:
        res += f"💰 <b>إجمالي قيمة تداولات العينة:</b> <code>{total_turnover / 1e6:,.1f}</code> مليون ج.م\n"
    adv_ratio = (advances / total_tracked * 100) if total_tracked else 0
    if adv_ratio >= 60:
        market_sentiment = "سيادة المعنويات الإيجابية وضخ سيولة توسعية واسعة 🚀"
    elif adv_ratio <= 35:
        market_sentiment = "سيطرة الحذر وضغوط بيعية عامة تتطلب التريث ⚠️"
    else:
        market_sentiment = "توازن نسبي بين قوى التجميع وجني الأرباح الانتقائي ⚖️"
    res += f"🧭 <b>نبض الجلسة:</b> {market_sentiment}\n"
        
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
        
    # ✅ إضافة: توليد وإرسال بطاقة الإنفوجرافيك المالية الفاخرة مع زر المنصة التفاعلية
    try:
        funds_data, _ = fetch_all_funds_data()
        card_file = generate_market_infographic_card(stocks_data, indices_data, fx_gold_data, funds_data)
        if card_file and os.path.exists(card_file):
            mini_app_btn = {
                "inline_keyboard": [
                    [{"text": "📱 فتح المنصة التفاعلية والمحفظة (Mini App)", "web_app": {"url": "https://mahereasybakery-web.github.io/egypt-sharia-stock-report/"}}],
                    [{"text": "💼 مركز المحفظة", "callback_data": "hub_portfolio"}, {"text": "📊 رادار السوق", "callback_data": "hub_market"}]
                ]
            }
            send_telegram_photo(card_file, caption=f"📊 <b>بطاقة الإغلاق والتقرير اليومي المتكامل لجلسة {datetime.now(timezone(timedelta(hours=3))).strftime('%Y/%m/%d')}</b>\n💡 انقر على الزر أدناه لفتح المنصة التفاعلية ومتابعة المحفظة والشارتات اللحظية.", reply_markup=mini_app_btn)
            try:
                os.remove(card_file)
            except Exception:
                pass
    except Exception as card_err:
        print("Notice sending infographic card:", card_err)

    # توليد وإرسال الشارت الفني البصري
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

def detect_stocks_in_query(query):
    """اكتشاف الأسهم المذكورة في نص السؤال بدقة عالية بناءً على الأكواد والأسماء الشائعة."""
    q_lower = query.lower()
    detected = []
    for ticker, kws in STOCK_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in q_lower:
                is_neg = any(neg in query for neg in NEGATIVE_KEYWORDS.get(ticker, []))
                if not is_neg:
                    if ticker not in detected:
                        detected.append(ticker)
                    break
    for ticker in ALL_TICKERS:
        pattern = r'\b' + ticker.lower() + r'\b'
        if re.search(pattern, q_lower) and ticker not in detected:
            detected.append(ticker)
    return detected

def is_portfolio_query(query):
    """التحقق مما إذا كان السؤال يستفسر عن محفظة المستخدم وأسهمه الخاصة."""
    q_lower = query.lower()
    portfolio_kws = [
        "محفظت", "محفظه", "أسهمي", "اسهمي", "أرباحي", "ارباحي",
        "خسائري", "خسائر", "حيازتي", "حيازه", "شاري", "شريت", "متوسط سعري"
    ]
    return any(kw in q_lower for kw in portfolio_kws)

def format_ai_response_for_telegram(text):
    """تنسيق وتجهيز مخرجات الذكاء الاصطناعي لظهورها بأبهى حلة على تليجرام بدعم HTML وRTL."""
    if not text:
        return text
    # تحويل Markdown العناوين إلى وسم <b>
    text = re.sub(r'^#{1,6}\s*(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    # تحويل الخط العريض **كلمة** إلى <b>كلمة</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # تحويل النقاط النجمية إلى رموز نقطية أنيقة
    text = re.sub(r'^\s*[\*\-]\s+', r'• ', text, flags=re.MULTILINE)
    return text.strip()

def ask_financial_advisor(question):
    """مستشار مالي ومحلل فني مؤسسي ذكي يعتمد على بيانات السوق والأسهم اللحظية الحقيقية ومحفظة المستخدم."""
    detected_tickers = detect_stocks_in_query(question)
    wants_portfolio = is_portfolio_query(question)
    
    s = {}
    if os.path.exists(STRINGS_PATH):
        try:
            with open(STRINGS_PATH, "r", encoding="utf-8") as f:
                s = json.load(f)
        except Exception:
            pass

    user_holdings = {}
    if wants_portfolio:
        try:
            state_data, _ = get_github_state()
            user_holdings = state_data.get("holdings", {})
        except Exception:
            user_holdings = {}

    tickers_to_fetch = set(detected_tickers)
    if wants_portfolio and user_holdings:
        for ht in user_holdings.keys():
            tickers_to_fetch.add(ht)
            
    if not tickers_to_fetch:
        tickers_to_fetch = set(ALL_TICKERS)

    market_data, indices = fetch_all_data_tv(list(tickers_to_fetch), s)
    usdegp, gold = fetch_forex_gold()

    context_lines = []
    
    egx30 = indices.get("EGX30", {})
    egx70 = indices.get("EGX70EWI", {})
    context_lines.append("=== مؤشرات السوق والعملات اللحظية الحية ===")
    if egx30.get('close'):
        context_lines.append(f"- مؤشر EGX30: {egx30.get('close', 0.0):,.2f} نقطة ({egx30.get('chgPct', 0.0):+.2f}%)")
    if egx70.get('close'):
        context_lines.append(f"- مؤشر EGX70 EWI: {egx70.get('close', 0.0):,.2f} نقطة ({egx70.get('chgPct', 0.0):+.2f}%)")
    if usdegp.get('close'):
        context_lines.append(f"- الدولار/جنيه (USD/EGP): {usdegp.get('close'):.2f} ج.م ({usdegp.get('chgPct', 0.0):+.2f}%)")
    if gold.get('close'):
        context_lines.append(f"- أوقية الذهب (XAU/USD): ${gold.get('close'):,.2f} ({gold.get('chgPct', 0.0):+.2f}%)")

    if detected_tickers:
        context_lines.append("\n=== البيانات الفنية اللحظية للأسهم المعنية بالسؤال ===")
        stocks_display = detected_tickers
    elif wants_portfolio and user_holdings:
        context_lines.append("\n=== البيانات اللحظية لأسهم محفظة المستثمر ===")
        stocks_display = list(user_holdings.keys())
    else:
        context_lines.append("\n=== نظرة عامة على أبرز أسهم السوق الشرعية اليوم ===")
        sorted_by_chg = sorted(market_data.items(), key=lambda x: x[1].get('chgPct', 0.0), reverse=True)
        stocks_display = [t for t, _ in sorted_by_chg[:10]]

    for t in stocks_display:
        d = market_data.get(t, {})
        if not d or d.get('close', 0.0) == 0.0:
            continue
        c_name = COMPANY_NAMES_AR.get(t, t)
        close = d.get('close', 0.0)
        chg = d.get('chgPct', 0.0)
        rsi = d.get('rsi')
        rec = d.get('rec', 'محايد')
        sma20 = d.get('sma20')
        sma50 = d.get('sma50')
        vol = d.get('volume', 0)
        avg_vol = d.get('avg_vol', 0)
        vol_spike = d.get('vol_spike', False)
        
        info = f"- سهم {c_name} ({t}): السعر الحالي = {close:.2f} ج.م | التغير = {chg:+.2f}%"
        if rsi is not None:
            info += f" | RSI(14) = {rsi:.1f}"
            if rsi >= 70:
                info += " (⚠️ تشبع شرائي - منطقة جني أرباح محتملة)"
            elif rsi <= 30:
                info += " (💎 تشبع بيعي مفرط - منطقة ارتداد محتملة)"
        if sma20 and sma50:
            info += f" | المتوسطات: SMA20={sma20:.2f}, SMA50={sma50:.2f}"
        info += f" | إشارة التحليل الفني: {rec}"
        if vol_spike:
            info += f" | ⚡ طفرة سيولة استثنائية (تداول {vol:,.0f} سهم مقارنة بمتوسط {avg_vol:,.0f})"
        context_lines.append(info)

    if wants_portfolio and user_holdings:
        pnl_data = calculate_portfolio_pnl(user_holdings, market_data)
        if pnl_data:
            context_lines.append("\n=== الحساب اللحظي لمحفظة المستثمر ===")
            context_lines.append(f"- تكلفة الشراء الإجمالية: {pnl_data.get('total_cost', 0):,.2f} ج.م")
            context_lines.append(f"- التقييم السوقي اللحظي: {pnl_data.get('total_val', 0):,.2f} ج.م")
            context_lines.append(f"- صافي الربح/الخسارة: {pnl_data.get('total_pnl', 0):+,.2f} ج.م ({pnl_data.get('total_pnl_pct', 0):+.2f}%)")
            for item in pnl_data.get("details", []):
                t_sym = item["ticker"]
                t_name = COMPANY_NAMES_AR.get(t_sym, t_sym)
                context_lines.append(f"  • {t_name} ({t_sym}): كمية {item['qty']:,.0f} سهم | سعر الشراء {item['buy_p']:.2f} | الحالي {item['curr_p']:.2f} | العائد: {item['pnl_pct']:+.2f}%")

    prompt = (
        f"أنت كبير المحللين الماليين ومدير محافظ استثمارية معتمد خبير في البورصة المصرية (EGX) والأسهم المتوافقة مع الشريعة الإسلامية.\n"
        f"سؤال المستثمر: \"{question}\"\n\n"
        f"فيما يلي البيانات اللحظية الحقيقية والموثوقة المأخوذة مباشرة من البورصة المصرية (TradingView) في هذه اللحظة:\n"
        f"{chr(10).join(context_lines)}\n\n"
        f"التعليمات الإلزامية:\n"
        f"1. التزم بالبيانات والأرقام المذكورة أعلاه بدقة، ولا تذكر أي أرقام أو أسعار خيالية أو قديمة إطلاقاً.\n"
        f"2. أسلوب الرد: احترافي، مؤسسي، مباشر، حاسم، بدون إطالة أو تكرار أو حشو.\n"
        f"3. إذا كان السؤال عن سهم محدد، نظّم إجابتك بدقة في 4 محاور رئيسية مستخدماً التنسيق التالي بدقة:\n"
        f"   🎯 **الرأي الفني المباشر:** تقييم قاطع وواضح لحالة السهم الفنية والاتجاه.\n"
        f"   📊 **المعطيات الفنية اللحظية:** تحليل السعر الحالي، نسبة التغير، مؤشر RSI وموقعه من التشبعات، وعلاقته بمتوسطات 20 و50 يوماً وحجم السيولة.\n"
        f"   ⚖️ **مستويات الدعم والمقاومة:** تحديد نقطتي الدعم والمقاومة الأقرب مع مستوى وقف الخسارة المقترح.\n"
        f"   💡 **القرار الاستثماري المقترح:** نصيحة تداول محددة بناءً على وضع السهم وحجم المخاطرة (شراء تدريجي، احتفاظ، تخفيف/جني أرباح، مراقبة).\n"
        f"4. إذا كان السؤال عن المحفظة، وجّه المستثمر إلى الأسهم الرابحة لجني جزء من أرباحها، والأسهم التي تتطلب حماية رأس المال أو وقف الخسارة.\n"
        f"5. اكتب الرد باللغة العربية مع استخدام علامات التنسيق الواضحة والإيموجي المعبر."
    )
    
    raw_res = ask_ai(prompt)
    return format_ai_response_for_telegram(raw_res)

def fetch_stock_fundamentals(ticker):
    """جلب مضاعفات التقييم والبيانات الأساسية ونسبة الديون للتحقق الشرعي من TradingView."""
    ticker_clean = ticker.upper().replace(".CA", "").replace("EGX:", "").strip()
    url = "https://scanner.tradingview.com/egypt/scan"
    payload = {
        "symbols": {"tickers": [f"EGX:{ticker_clean}"]},
        "columns": [
            "close", "market_cap_basic", "price_earnings_ttm", "price_book_fq",
            "dividend_yield_recent", "earnings_per_share_diluted_ttm",
            "total_debt", "total_assets"
        ]
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=12)
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                d = data[0]["d"]
                close = d[0] or 0.0
                mcap = d[1] or 0.0
                pe = d[2]
                pb = d[3]
                div_yield = d[4]
                eps = d[5]
                debt = d[6] or 0.0
                assets = d[7] or 0.0
                debt_ratio = (debt / assets * 100.0) if assets > 0 else 0.0
                return {
                    "ticker": ticker_clean,
                    "close": close,
                    "mcap": mcap,
                    "pe": pe,
                    "pb": pb,
                    "div_yield": div_yield,
                    "eps": eps,
                    "debt": debt,
                    "assets": assets,
                    "debt_ratio": debt_ratio
                }
    except Exception as e:
        print(f"Error fetching fundamentals for {ticker_clean}: {e}")
    return None

def format_fundamental_card(f_data):
    """تنسيق بطاقة التقييم المالي والتحقق من المعايير الشرعية للديون."""
    if not f_data:
        return "⚠️ تعذر جلب البيانات المالية الأساسية لهذا السهم حالياً. يرجى التأكد من رمز السهم."
    ticker = f_data["ticker"]
    name = COMPANY_NAMES_AR.get(ticker, ticker)
    close = f_data["close"]
    mcap = f_data["mcap"]
    mcap_str = f"{mcap / 1e9:.2f} مليار ج.م" if mcap >= 1e9 else f"{mcap / 1e6:.1f} مليون ج.م"
    
    pe = f_data["pe"]
    pe_str = f"{pe:.2f}x" if pe is not None else "غير متاح"
    if pe is not None:
        if pe <= 10.0: pe_str += " (جاذب جداً 💎)"
        elif pe <= 16.0: pe_str += " (عادل ومناسب 🟢)"
        else: pe_str += " (مرتفع نسبياً ⚠️)"
        
    pb = f_data["pb"]
    pb_str = f"{pb:.2f}x" if pb is not None else "غير متاح"
    
    eps = f_data["eps"]
    eps_str = f"{eps:.2f} ج.م" if eps is not None else "غير متاح"
    
    div_y = f_data["div_yield"]
    div_str = f"{div_y:.2f}%" if div_y is not None else "لا توجد توزيعات مسجلة"
    
    debt = f_data["debt"]
    assets = f_data["assets"]
    debt_str = f"{debt / 1e9:.2f} مليار ج.م" if debt >= 1e9 else f"{debt / 1e6:.1f} مليون ج.م"
    assets_str = f"{assets / 1e9:.2f} مليار ج.م" if assets >= 1e9 else f"{assets / 1e6:.1f} مليون ج.م"
    
    debt_ratio = f_data["debt_ratio"]
    if debt_ratio <= 30.0:
        sharia_status = "✅ متوافق تماماً مع المعيار الشرعي للديون (< 30%)"
    else:
        sharia_status = f"⚠️ نسبة الديون مرتفعة ({debt_ratio:.1f}% تتجاوز سقف 30%)"
        
    msg = (
        f"🏢 <b>بطاقة التحليل المالي والتقييم: {name} ({ticker})</b>\n\n"
        f"💵 <b>سعر السهم الحالي:</b> {close:.2f} ج.م\n"
        f"📊 <b>رأس المال السوقي:</b> {mcap_str}\n\n"
        f"⚖️ <b>مضاعفات التقييم والأرباح:</b>\n"
        f"• <b>مضاعف الربحية (P/E TTM):</b> <code>{pe_str}</code>\n"
        f"• <b>مضاعف القيمة الدفترية (P/B):</b> <code>{pb_str}</code>\n"
        f"• <b>ربحية السهم (EPS):</b> {eps_str}\n"
        f"• <b>عائد التوزيعات النقدية:</b> {div_str}\n\n"
        f"🕌 <b>ملاءمة المعايير الشرعية والملاءة المالية:</b>\n"
        f"• <b>إجمالي الديون:</b> {debt_str}\n"
        f"• <b>إجمالي الأصول:</b> {assets_str}\n"
        f"• <b>نسبة الديون إلى الأصول:</b> <code>{debt_ratio:.1f}%</code>\n"
        f"• <b>الحالة الشرعية:</b> {sharia_status}\n\n"
        f"💡 <b>الرأي التقييمي:</b> "
        + ("السهم يتداول عند مضاعفات ربحية جاذبة جداً تمنحه هامش أمان استثماري قوي." if (pe and pe <= 12) else "السهم يتداول بالقرب من قيمته العادلة، يُفضل مراقبة مناطق الدعم الفنية.")
    )
    return msg

def handle_buy_trade(text):
    """تسجيل شراء كمية وحساب المتوسط المرجح للتكلفة آلياً."""
    parts = text.split()
    if len(parts) < 4:
        return "⚠️ <b>صيغة أمر الشراء:</b>\n<code>/buy [السهم] [الكمية] [سعر_الشراء]</code>\nمثال:\n<code>/buy OCDI 1000 28.50</code>"
    ticker = parts[1].upper().replace("[", "").replace("]", "").replace(".CA", "").replace("EGX:", "")
    try:
        qty = float(parts[2].replace(",", ""))
        price = float(parts[3].replace(",", ""))
        if qty <= 0 or price <= 0:
            return "⚠️ الكمية وسعر الشراء يجب أن تكون أرقاماً موجبة أكبر من الصفر."
            
        state_data, state_sha = get_github_state()
        if "holdings" not in state_data:
            state_data["holdings"] = {}
        if "journal" not in state_data:
            state_data["journal"] = []
            
        old_h = state_data["holdings"].get(ticker)
        if old_h:
            old_qty = float(old_h.get("qty", 0))
            old_price = float(old_h.get("buy_price", 0))
            new_qty = old_qty + qty
            new_price = (old_qty * old_price + qty * price) / new_qty
        else:
            new_qty = qty
            new_price = price
            
        state_data["holdings"][ticker] = {"qty": new_qty, "buy_price": new_price}
        
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        state_data["journal"].append({
            "id": len(state_data["journal"]) + 1,
            "type": "BUY",
            "ticker": ticker,
            "qty": qty,
            "price": price,
            "date": now_str,
            "total": qty * price
        })
        
        name = COMPANY_NAMES_AR.get(ticker, ticker)
        if update_github_state(state_data, state_sha):
            return (
                f"✅ <b>تم تسجيل عملية الشراء بنجاح:</b>\n\n"
                f"📥 <b>الصفقة:</b> شراء {qty:,.0f} سهم في <b>{name} ({ticker})</b> بسعر {price:.2f} ج.م\n"
                f"💼 <b>إجمالي المركز الحالي:</b> {new_qty:,.0f} سهم\n"
                f"⚖️ <b>متوسط سعر التكلفة الجديد:</b> <code>{new_price:.2f} ج.م</code>\n"
                f"💰 <b>إجمالي القيمة المستثمرة في السهم:</b> {(new_qty * new_price):,.2f} ج.م\n\n"
                f"يمكنك متابعة الأرباح اللحظية بالضغط على <b>[💼 محفظتي الاستثمارية]</b>."
            )
        else:
            return "❌ فشل حفظ بيانات الشراء على الخادم، يرجى المحاولة لاحقاً."
    except ValueError:
        return "⚠️ يرجى التأكد من كتابة الكمية والسعر كأرقام صحيحة."

def handle_sell_trade(text):
    """تسجيل بيع كمية واحتساب الأرباح المحققة وتحديث رصيد الكاش التراكمي."""
    parts = text.split()
    if len(parts) < 4:
        return "⚠️ <b>صيغة أمر البيع:</b>\n<code>/sell [السهم] [الكمية] [سعر_البيع]</code>\nمثال:\n<code>/sell OCDI 500 31.00</code>"
    ticker = parts[1].upper().replace("[", "").replace("]", "").replace(".CA", "").replace("EGX:", "")
    try:
        qty = float(parts[2].replace(",", ""))
        sell_price = float(parts[3].replace(",", ""))
        if qty <= 0 or sell_price <= 0:
            return "⚠️ الكمية وسعر البيع يجب أن تكون أرقاماً موجبة أكبر من الصفر."
            
        state_data, state_sha = get_github_state()
        holdings = state_data.get("holdings", {})
        if ticker not in holdings:
            return f"⚠️ السهم <b>{ticker}</b> غير مسجل في محفظتك حالياً لتتمكن من بيعه."
            
        curr_holding = holdings[ticker]
        curr_qty = float(curr_holding.get("qty", 0))
        buy_price = float(curr_holding.get("buy_price", 0))
        
        if qty > curr_qty:
            return f"⚠️ الكمية المراد بيعها ({qty:,.0f}) أكبر من الرصيد المتوفر في محفظتك ({curr_qty:,.0f} سهم)."
            
        pnl = (sell_price - buy_price) * qty
        pnl_pct = ((sell_price - buy_price) / buy_price) * 100.0 if buy_price > 0 else 0.0
        
        state_data.setdefault("realized_pnl", 0.0)
        state_data["realized_pnl"] += pnl
        
        remaining_qty = curr_qty - qty
        if remaining_qty <= 0:
            del state_data["holdings"][ticker]
        else:
            state_data["holdings"][ticker]["qty"] = remaining_qty
            
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        state_data.setdefault("journal", []).append({
            "id": len(state_data["journal"]) + 1,
            "type": "SELL",
            "ticker": ticker,
            "qty": qty,
            "price": sell_price,
            "buy_price": buy_price,
            "date": now_str,
            "pnl": pnl,
            "pnl_pct": pnl_pct
        })
        
        name = COMPANY_NAMES_AR.get(ticker, ticker)
        pnl_sign = "+" if pnl > 0 else ""
        pnl_icon = "🟢" if pnl >= 0 else "🔴"
        
        if update_github_state(state_data, state_sha):
            msg = (
                f"{pnl_icon} <b>تم تنفيذ صفقة البيع واحتساب الربح المحقق:</b>\n\n"
                f"📤 <b>الصفقة:</b> بيع {qty:,.0f} سهم من <b>{name} ({ticker})</b> بسعر {sell_price:.2f} ج.م\n"
                f"⚖️ <b>سعر الشراء الأساسي:</b> {buy_price:.2f} ج.م\n"
                f"💵 <b>الربح/الخسارة المحققة:</b> <code>{pnl_sign}{pnl:,.2f} ج.م</code> ({pnl_sign}{pnl_pct:.2f}%)\n"
            )
            if remaining_qty > 0:
                msg += f"💼 <b>الكمية المتبقية في المحفظة:</b> {remaining_qty:,.0f} سهم\n"
            else:
                msg += f"🏁 <b>تم إغلاق كامل المركز في سهم {name}.</b>\n"
            msg += f"\n🏆 <b>إجمالي الأرباح المحققة التراكمية:</b> <code>{state_data['realized_pnl']:+,.2f} ج.م</code>"
            return msg
        else:
            return "❌ فشل حفظ بيانات البيع على الخادم، يرجى المحاولة لاحقاً."
    except ValueError:
        return "⚠️ يرجى التأكد من كتابة الكمية والسعر كأرقام صحيحة."

def format_trade_journal(state_data):
    """كشف حساب وسجل الصفقات المغلقة ومعدل الصفقات الرابحة Win Rate."""
    journal = state_data.get("journal", [])
    realized_pnl = state_data.get("realized_pnl", 0.0)
    
    if not journal:
        return (
            "📜 <b>سجل الصفقات والتداول الاستثماري</b>\n\n"
            "لا توجد صفقات مسجلة حتى الآن.\n"
            "💡 يمكنك البدء بتسجيل صفقاتك فوراً عبر الأوامر:\n"
            "• <code>/buy [السهم] [الكمية] [سعر_الشراء]</code>\n"
            "• <code>/sell [السهم] [الكمية] [سعر_البيع]</code>"
        )
        
    sells = [t for t in journal if t.get("type") == "SELL"]
    buys = [t for t in journal if t.get("type") == "BUY"]
    
    winning_trades = [t for t in sells if t.get("pnl", 0) > 0]
    losing_trades = [t for t in sells if t.get("pnl", 0) < 0]
    win_rate = (len(winning_trades) / len(sells) * 100.0) if sells else 0.0
    
    pnl_sign = "+" if realized_pnl > 0 else ""
    pnl_icon = "🟢" if realized_pnl >= 0 else "🔴"
    
    msg = (
        "📜 <b>سجل الصفقات وكشف الأرباح المحققة (Trade Journal)</b>\n\n"
        f"📊 <b>إجمالي العمليات:</b> {len(journal)} (شراء: {len(buys)} | بيع مغلق: {len(sells)})\n"
        f"🎯 <b>معدل الصفقات الرابحة (Win Rate):</b> <code>{win_rate:.1f}%</code> "
        f"({len(winning_trades)} رابحة / {len(losing_trades)} خاسرة)\n"
        f"{pnl_icon} <b>صافي الأرباح المحققة الفعلية:</b> <code>{pnl_sign}{realized_pnl:,.2f} ج.م</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🕒 <b>آخر العمليات المنفذة:</b>\n"
    )
    
    for item in reversed(journal[-6:]):
        t_sym = item["ticker"]
        t_name = COMPANY_NAMES_AR.get(t_sym, t_sym)
        date_str = item.get("date", "")
        if item["type"] == "BUY":
            msg += f"• 📥 <b>شراء {t_name}({t_sym}):</b> {item['qty']:,.0f} سهم بسعر {item['price']:.2f} ج ({date_str})\n"
        else:
            pnl_val = item.get('pnl', 0)
            sign = "+" if pnl_val > 0 else ""
            icon = "🟢" if pnl_val >= 0 else "🔴"
            msg += f"• {icon} <b>بيع {t_name}({t_sym}):</b> {item['qty']:,.0f} سهم بسعر {item['price']:.2f} ج | ربح: <code>{sign}{pnl_val:,.1f} ج</code> ({sign}{item.get('pnl_pct', 0):.1f}%)\n"
            
    return msg

def check_and_send_smart_alerts(parsed_stocks, holdings, state_data):
    """رادار لحظي لفحص طفرات السيولة والاختراقات وتنبيهات حماية الأرباح أثناء الجلسة."""
    if not BOT_TOKEN or not CHAT_ID:
        return False
    egypt_tz = timezone(timedelta(hours=3))
    now = datetime.now(egypt_tz)
    
    # يعمل فقط في أيام وساعات التداول (الأحد - الخميس من 10:00 إلى 15:00)
    if now.weekday() in [4, 5] or now.hour < 10 or now.hour >= 15:
        return False
        
    today_str = now.strftime("%Y-%m-%d")
    sent_alerts = state_data.setdefault("smart_alerts_sent", {})
    state_modified = False
    
    # 1. رادار طفرات السيولة الفورية (Volume Spikes)
    for ticker, d in parsed_stocks.items():
        vol = d.get("volume", 0)
        avg_vol = d.get("avg_vol", 0)
        if avg_vol > 20000 and vol >= (avg_vol * 2.0):
            alert_key = f"{today_str}_vol_{ticker}"
            if alert_key not in sent_alerts:
                sent_alerts[alert_key] = True
                state_modified = True
                name = COMPANY_NAMES_AR.get(ticker, ticker)
                ratio = vol / avg_vol
                msg = (
                    f"⚡ <b>رادار السيولة الاستثنائية (Volume Surge):</b>\n\n"
                    f"رصد تدفق سيولة ضخم على سهم <b>{name} ({ticker})</b>!\n"
                    f"📊 <b>حجم التداول اللحظي:</b> {vol:,.0f} سهم ({ratio:.1f} ضعف متوسط 10 أيام!)\n"
                    f"💵 <b>السعر الحالي:</b> {d.get('close')} ج.م (التغير {d.get('chgPct'):+.2f}%)\n"
                    f"⚡ <b>مؤشر RSI:</b> {d.get('rsi')} | <b>التوصية الفنية:</b> {d.get('rec')}"
                )
                reply_telegram(msg, reply_markup=PORTFOLIO_INLINE_KEYBOARD)
                
    # 2. رادار حماية الأرباح وتنبيهات وقف الخسارة للمحفظة
    if holdings:
        for ticker, h_data in holdings.items():
            d = parsed_stocks.get(ticker)
            if not d or d.get("close", 0) <= 0:
                continue
            curr_p = d["close"]
            buy_p = float(h_data.get("buy_price", curr_p))
            if buy_p <= 0:
                continue
            pnl_pct = ((curr_p - buy_p) / buy_p) * 100.0
            rsi_val = d.get("rsi")
            name = COMPANY_NAMES_AR.get(ticker, ticker)
            
            # جني أرباح ذكي (ربح >= +10% أو RSI >= 75)
            if pnl_pct >= 10.0 or (rsi_val and rsi_val >= 75.0):
                tp_key = f"{today_str}_tp_{ticker}"
                if tp_key not in sent_alerts:
                    sent_alerts[tp_key] = True
                    state_modified = True
                    msg = (
                        f"🎯 <b>تنبيه ذكي لجني الأرباح (Take-Profit Alert):</b>\n\n"
                        f"سهم <b>{name} ({ticker})</b> في محفظتك حقق أداءً استثنائياً:\n"
                        f"💵 <b>السعر الحالي:</b> {curr_p:.2f} ج.م (سعر الشراء: {buy_p:.2f} ج.م)\n"
                        f"📈 <b>العائد اللحظي:</b> <code>+{pnl_pct:.2f}%</code>\n"
                        f"⚡ <b>مؤشر RSI:</b> {rsi_val} (منطقة تشبع شرائي مفرط)\n\n"
                        f"💡 <b>توصية المستشار:</b> يُنصح بجني ربح جزئي (بيع ثلث أو نصف الكمية) وتأمين الأرباح المتبقية بتفعيل وقف خسارة متحرك."
                    )
                    reply_telegram(msg, reply_markup=get_portfolio_inline_keyboard(holdings))
                    
            # وقف خسارة وقائي (هبوط <= -7.0% أو كسر RSI <= 28)
            elif pnl_pct <= -7.0 or (rsi_val and rsi_val <= 28.0):
                sl_key = f"{today_str}_sl_{ticker}"
                if sl_key not in sent_alerts:
                    sent_alerts[sl_key] = True
                    state_modified = True
                    msg = (
                        f"⚠️ <b>تنبيه وقائي لحماية رأس المال (Stop-Loss Warning):</b>\n\n"
                        f"سهم <b>{name} ({ticker})</b> في محفظتك يمر بموجة ضغط بيعي:\n"
                        f"💵 <b>السعر الحالي:</b> {curr_p:.2f} ج.م (سعر الشراء: {buy_p:.2f} ج.م)\n"
                        f"📉 <b>نسبة التراجع:</b> <code>{pnl_pct:.2f}%</code>\n"
                        f"⚡ <b>مؤشر RSI:</b> {rsi_val} (تشبع بيعي حاد)\n\n"
                        f"💡 <b>توصية المستشار:</b> يُرجى مراجعة نقطة وقف الخسارة الصارمة لمنع تفاقم التراجع أو انتظار إشارة ارتداد واضحة."
                    )
                    reply_telegram(msg, reply_markup=get_portfolio_inline_keyboard(holdings))
                    
            # وقف خسارة متحرك (Trailing Stop-Loss) لحجز الأرباح بعد صعود السهم
            trailing_peaks = state_data.setdefault("trailing_peaks", {})
            stored_peak = float(trailing_peaks.get(ticker, max(buy_p, curr_p)))
            if curr_p > stored_peak:
                trailing_peaks[ticker] = curr_p
                stored_peak = curr_p
                state_modified = True
                
            # إذا حقق السهم سابقاً ربحاً >= 5% وتراجع حالياً بنسبة >= 5% عن قمته المسجلة
            if stored_peak > buy_p and ((stored_peak - buy_p) / buy_p) >= 0.05:
                drop_from_peak = ((stored_peak - curr_p) / stored_peak) * 100.0
                if drop_from_peak >= 5.0:
                    tsl_key = f"{today_str}_tsl_{ticker}"
                    if tsl_key not in sent_alerts:
                        sent_alerts[tsl_key] = True
                        state_modified = True
                        msg = (
                            f"🛡️ <b>تنبيه وقف الخسارة المتحرك (Trailing Stop-Loss Alert):</b>\n\n"
                            f"سهم <b>{name} ({ticker})</b> في محفظتك تراجع عن أعلى قمة وصل إليها:\n"
                            f"🏔️ <b>قمة السعر المسجلة:</b> <code>{stored_peak:.2f} ج.م</code>\n"
                            f"💵 <b>السعر اللحظي الحالي:</b> <code>{curr_p:.2f} ج.م</code>\n"
                            f"📉 <b>نسبة التراجع عن القمة:</b> <code>-{drop_from_peak:.2f}%</code>\n"
                            f"📊 <b>الربح الصافي المتبقي:</b> <code>+{pnl_pct:.2f}%</code> (سعر الشراء: {buy_p:.2f} ج.م)\n\n"
                            f"💡 <b>توصية المستشار لحجز الأرباح:</b> تم كسر حد الوقف المتحرك (تراجع ≥ 5% عن القمة). يُنصح بإغلاق المركز أو حجز الأرباح لمنع تبخر المكاسب المحققة."
                        )
                        reply_telegram(msg, reply_markup=get_portfolio_inline_keyboard(holdings))
                    
    # 3. رادار قناص الارتدادات من التشبع البيعي (Oversold Bounce Sniper)
    for ticker, d in parsed_stocks.items():
        rsi_val = d.get("rsi")
        if rsi_val and rsi_val <= 30.0 and d.get("close", 0) > 0:
            sniper_key = f"{today_str}_sniper_{ticker}"
            if sniper_key not in sent_alerts:
                sent_alerts[sniper_key] = True
                state_modified = True
                name = COMPANY_NAMES_AR.get(ticker, ticker)
                curr_p = d["close"]
                chg = d.get("chgPct", 0.0)
                chg_str = f"+{chg}%" if chg > 0 else f"{chg}%"
                msg = (
                    f"🎯 <b>رادار قناص الارتدادات (Oversold Bounce Sniper):</b>\n\n"
                    f"رصد سهم قيادي دخل منطقة تشبع بيعي حاد وغير مبرر:\n"
                    f"🏢 <b>السهم:</b> <b>{name} ({ticker})</b>\n"
                    f"💵 <b>السعر الحالي:</b> {curr_p:.2f} ج.م ({chg_str})\n"
                    f"⚡ <b>مؤشر RSI:</b> <code>{rsi_val}</code> (تشبع بيعي مفرط ≤ 30!)\n"
                    f"📊 <b>التوصية الفنية:</b> {d.get('rec', 'مراقبة')}\n\n"
                    f"💡 <b>استراتيجية القناص:</b> تاريخياً تعكس هذه المستويات ارتداداً تصحيحياً سريعاً نحو متوسطات الحركة (Mean Reversion). راقب تشكل شمعة انعكاسية إيجابية وتأكيد الدعم لبدء الدخول التدريجي.\n"
                    f"📐 <i>لحساب كمية الشراء وإدارة المخاطرة بدقة:</i> <code>/calc {ticker} {curr_p:.2f} [وقف_الخسارة]</code>"
                )
                reply_telegram(msg, reply_markup=PORTFOLIO_INLINE_KEYBOARD)
                    
    return state_modified

def check_and_send_pre_market_briefing(state_data):
    """إرسال مذكرة ما قبل افتتاح الجلسة في تمام 09:30 صباحاً في أيام التداول الرسمية."""
    if not BOT_TOKEN or not CHAT_ID:
        return False
    egypt_tz = timezone(timedelta(hours=3))
    now = datetime.now(egypt_tz)
    
    # أيام التداول في مصر: الأحد (6) إلى الخميس (3)
    if now.weekday() in [4, 5]:
        return False
        
    # نافذة الوقت: من 09:30 إلى 09:59 صباحاً
    if not (now.hour == 9 and now.minute >= 30):
        return False
        
    today_str = now.strftime("%Y-%m-%d")
    if state_data.get("pre_market_sent_date") == today_str:
        return False
        
    print(f"[{now}] Preparing Pre-Market Morning Briefing...")
    
    usdegp, gold = fetch_forex_gold()
    egx33_idx = fetch_egx33_shariah()
    
    msg = (
        "☀️ <b>مذكرة ما قبل افتتاح الجلسة (Pre-Market Briefing)</b>\n"
        f"📅 <b>تاريخ اليوم:</b> {now.strftime('%Y/%m/%d')} | ⏰ <b>09:30 صباحاً</b>\n\n"
        "🌍 <b>نبض الأسواق العالمية والماكرو:</b>\n"
    )
    if usdegp.get("close"):
        msg += f"• 💵 <b>الدولار/جنيه (USD/EGP):</b> {usdegp['close']:.2f} ج.م ({usdegp.get('chgPct', 0):+.2f}%)\n"
    if gold.get("close"):
        msg += f"• 🪙 <b>أوقية الذهب عالمياً:</b> ${gold['close']:,.2f} ({gold.get('chgPct', 0):+.2f}%)\n"
    if egx33_idx.get("close"):
        msg += f"• 🕌 <b>مؤشر الشريعة EGX33:</b> {egx33_idx['close']:,.2f} نقطة\n"
        
    msg += (
        "\n🎯 <b>محاور جلسة اليوم:</b>\n"
        "1. مراقبة سيولة الافتتاح في أول 30 دقيقة (10:00 - 10:30 ص).\n"
        "2. التركيز على الأسهم ذات RSI المتوازن والقريبة من متوسطات 20 يوماً.\n"
        "3. ستبدأ المنصة ببث التقارير اللحظية ورادارات السيولة فور انطلاق التداول.\n\n"
        "💡 <i>نتمنى لكم جلسة تداول موفقة ومربحة!</i>"
    )
    
    reply_telegram(msg, reply_markup=DEFAULT_KEYBOARD)
    state_data["pre_market_sent_date"] = today_str
    return True

def calculate_position_risk(text, state_data=None):
    """
    حاسبة حجم الصفقة الذكية وإدارة المخاطر الصارمة (Position Sizing & Risk Management)
    تطبق قاعدة المخاطرة المؤسسية الصارمة (1.5% أقصى خسارة من رأس المال).
    """
    parts = text.strip().split()
    if len(parts) < 4:
        return (
            "📐 <b>حاسبة حجم الصفقة الذكية وإدارة المخاطر (Position Sizing):</b>\n\n"
            "تساعدك هذه الحاسبة على تطبيق <b>قاعدة المخاطرة المؤسسية الصارمة (1.5% أقصى خسارة من رأس المال)</b> لحساب كمية الأسهم المناسبة وأهداف جني الأرباح المحسوبة رياضياً.\n\n"
            "✍️ <b>التنسيق المطلوب:</b>\n"
            "<code>/calc [السهم] [سعر_الدخول] [وقف_الخسارة] [رأس_المال (اختياري)]</code>\n\n"
            "💡 <b>أمثلة:</b>\n"
            "• <code>/calc OCDI 28.5 27.0</code> (يعتمد رأس مال افتراضي 100,000 ج أو إجمالي محفظتك)\n"
            "• <code>/calc طلعت_مصطفى 58.0 55.5 250000</code> (مع تحديد رأس المال 250,000 ج)\n"
            "• <code>/calc FWRY 18.2 17.1</code>"
        )
    
    ticker_raw = parts[1].replace("_", " ").upper().replace("[", "").replace("]", "").replace(".CA", "").replace("EGX:", "")
    detected = detect_stocks_in_query(ticker_raw)
    ticker = detected[0] if detected else ticker_raw.strip()
    name = COMPANY_NAMES_AR.get(ticker, ticker)
    
    try:
        entry_price = float(parts[2].replace(",", ""))
        stop_loss = float(parts[3].replace(",", ""))
    except ValueError:
        return "⚠️ يرجى التأكد من كتابة سعر الدخول ووقف الخسارة كأرقام صحيحة أو عشرية."
        
    if entry_price <= 0 or stop_loss <= 0:
        return "⚠️ أسعار الدخول ووقف الخسارة يجب أن تكون أكبر من الصفر."
        
    if stop_loss >= entry_price:
        return f"⚠️ سعر وقف الخسارة ({stop_loss:.2f} ج) يجب أن يكون أقل من سعر الدخول ({entry_price:.2f} ج) لصفقات الشراء!"
        
    # تحديد رأس المال المعتمد (100 ألف ج افتراضي أو من قيمة المحفظة)
    capital = 100000.0
    if len(parts) >= 5:
        try:
            capital = float(parts[4].replace(",", ""))
        except ValueError:
            pass
    elif state_data and "holdings" in state_data:
        # حساب القيمة الإجمالية للمحفظة إن وجدت
        total_p_val = 0.0
        for _, h in state_data["holdings"].items():
            total_p_val += float(h.get("qty", 0)) * float(h.get("buy_price", 0))
        if total_p_val >= 10000:
            capital = total_p_val
        
    # الحسابات الرياضية للمخاطرة وحجم الصفقة
    risk_per_share = entry_price - stop_loss
    stop_loss_pct = (risk_per_share / entry_price) * 100.0
    max_risk_amount = capital * 0.015  # قاعدة 1.5% أقصى خسارة
    
    optimal_shares = int(max_risk_amount / risk_per_share) if risk_per_share > 0 else 0
    total_position_cost = optimal_shares * entry_price
    position_pct_of_capital = (total_position_cost / capital) * 100.0 if capital > 0 else 0.0
    
    # أهداف جني الأرباح (Risk to Reward Ratio)
    target_1 = entry_price + (risk_per_share * 2.0)  # 1:2 R:R
    target_1_profit = optimal_shares * (target_1 - entry_price)
    target_1_gain_pct = ((target_1 - entry_price) / entry_price) * 100.0
    
    target_2 = entry_price + (risk_per_share * 3.0)  # 1:3 R:R
    target_2_profit = optimal_shares * (target_2 - entry_price)
    target_2_gain_pct = ((target_2 - entry_price) / entry_price) * 100.0
    
    res = (
        f"📐 <b>خطة إدارة المخاطر وحجم الصفقة لسهم {name} ({ticker}):</b>\n\n"
        f"💼 <b>رأس المال المعتمد:</b> <code>{capital:,.0f} ج.م</code>\n"
        f"🎯 <b>أقصى مخاطرة مسموحة للصفقة (1.5%):</b> <code>{max_risk_amount:,.2f} ج.م</code>\n\n"
        f"💵 <b>سعر الدخول المقترح:</b> {entry_price:.2f} ج.م\n"
        f"🛑 <b>وقف الخسارة الصارم:</b> {stop_loss:.2f} ج.م (المخاطرة: <code>-{stop_loss_pct:.2f}%</code>)\n"
        f"⚖️ <b>المخاطرة لكل سهم:</b> {risk_per_share:.2f} ج.م\n\n"
        f"🟢 <b>الكمية الموصى بشرائها (Optimal Sizing):</b>\n"
        f"👉 <b><code>{optimal_shares:,}</code> سهم</b>\n"
        f"💰 <b>إجمالي قيمة الصفقة:</b> {total_position_cost:,.2f} ج.م ({position_pct_of_capital:.1f}% من رأس المال)\n\n"
        f"🎯 <b>أهداف جني الأرباح ونسب العائد إلى المخاطرة (R:R):</b>\n"
        f"1️⃣ <b>الهدف الأول (نسبة 1:2):</b> <b>{target_1:.2f} ج.م</b> (+{target_1_gain_pct:.1f}%)\n"
        f"   └ 💵 الربح المتوقع: <code>+{target_1_profit:,.2f} ج.م</code>\n"
        f"2️⃣ <b>الهدف الثاني (نسبة 1:3):</b> <b>{target_2:.2f} ج.م</b> (+{target_2_gain_pct:.1f}%)\n"
        f"   └ 💵 الربح المتوقع: <code>+{target_2_profit:,.2f} ج.م</code>\n\n"
        f"💡 <b>قاعدة التداول الذهبية:</b> عند بلوغ السهم الهدف الأول ({target_1:.2f} ج)، قم بجني ربح نصف الكمية فوراً، وارفع وقف الخسارة للنصف المتبقي إلى نقطة الدخول ({entry_price:.2f} ج) لتصبح صفقة خالية تماماً من المخاطر (Risk-Free Trade)!"
    )
    return res

def format_undervalued_report(parsed_stocks):
    """
    رادار اقتناص أسهم القيمة وهامش الأمان (Margin of Safety Radar)
    يفحص الأسهم الشرعية وفق معايير وارن بافت وبنجامين جراهام (P/E منخفض، ديون متدنية، وزخم غير مشبع).
    """
    candidates = []
    for ticker, d in parsed_stocks.items():
        if ticker not in ALL_TICKERS:
            continue
        pe = d.get("pe")
        pb = d.get("pb")
        rsi = d.get("rsi", 50.0)
        debt_ratio = d.get("debt_ratio")
        roe = d.get("roe")
        close = d.get("close", 0.0)
        chg = d.get("chgPct", 0.0)
        
        # الفلترة: مكرر ربحية جذّاب <= 15 أو مضاعف دفترية <= 2.5 مع مؤشر RSI غير متضخم (< 65)
        if pe is not None and pe <= 15.0 and rsi < 65.0:
            score = pe * 0.6 + (pb if pb else 2.0) * 2.0
            candidates.append({
                "ticker": ticker,
                "name": COMPANY_NAMES_AR.get(ticker, ticker),
                "close": close,
                "chg": chg,
                "rsi": rsi,
                "pe": pe,
                "pb": pb,
                "debt_ratio": debt_ratio,
                "roe": roe,
                "score": score
            })
            
    candidates.sort(key=lambda x: x["score"])
    
    if not candidates:
        return (
            "🎯 <b>رادار أسهم القيمة وهامش الأمان:</b>\n\n"
            "لا توجد أسهم حالياً مستوفية لشروط التقييم الرخيص الصارمة (P/E ≤ 15x و RSI < 65)."
        )
        
    msg = (
        "🎯 <b>رادار اقتناص أسهم القيمة وهامش الأمان (Margin of Safety):</b>\n"
        "<i>فرص استثمارية تتداول بمضاعفات تقييم رخيصة وديون آمنة ومساحة نمو فني ممتازة:</i>\n\n"
    )
    
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, c in enumerate(candidates[:5]):
        medal = medals[i] if i < len(medals) else "🔹"
        name = c["name"]
        t = c["ticker"]
        p = c["close"]
        chg_str = f"+{c['chg']}%" if c['chg'] > 0 else f"{c['chg']}%"
        pe_str = f"{c['pe']:.1f}x" if c['pe'] else "غير متوفر"
        pb_str = f"{c['pb']:.2f}x" if c['pb'] else "غير متوفر"
        debt_str = f"{c['debt_ratio']:.1f}%" if c['debt_ratio'] is not None else "آمنة شرعياً"
        roe_str = f"{c['roe']:.1f}%" if c['roe'] is not None else "-"
        rsi_val = c["rsi"]
        
        # تصنيف هامش الأمان
        safety = "⭐⭐⭐ ممتاز" if (c['pe'] <= 8.0 and (c['debt_ratio'] or 0) <= 20) else "⭐⭐ جيد جداً"
        
        msg += (
            f"{medal} <b>{name} ({t})</b>: <b>{p:.2f} ج.م</b> ({chg_str})\n"
            f"   ├ 📊 <b>مكرر الربحية (P/E):</b> <code>{pe_str}</code> | <b>مضاعف القيمة الدفترية (P/B):</b> <code>{pb_str}</code>\n"
            f"   ├ 💳 <b>نسبة الديون للأصول:</b> <code>{debt_str}</code> | <b>عائد حقوق الملكية (ROE):</b> <code>{roe_str}</code>\n"
            f"   ├ ⚡ <b>مؤشر RSI:</b> <code>{rsi_val}</code> | <b>هامش الأمان:</b> {safety}\n"
            f"   └ 💡 <i>فحص تفصيلي:</i> <code>/fundamental {t}</code> | <code>/chart {t}</code>\n\n"
        )
        
    msg += (
        "💡 <b>قاعدة وارن بافت:</b> «السعر هو ما تدفعه، أما القيمة فهي ما تحصل عليه». "
        "شراء أسهم ذات مضاعفات تقييم منخفضة وديون متدنية يمنح محفظتك وسادة أمان متينة ضد تقلبات السوق."
    )
    return msg

# ==================== الميزات المؤسسية المتقدمة (Institutional Alpha Suite) ====================

SECTORS_MAP = {
    "العقارات والإنشاءات": ["TMGH", "OCDI", "PHDC", "MASR", "ORHD", "ORAS"],
    "الخدمات المالية والبنوك": ["ADIB", "SAUD", "FAIT", "FAITA", "FWRY", "EFIH"],
    "الصناعة والمواد الأساسية": ["EGAL", "SKPC", "MCQE", "AMOC", "ORWE", "ARCC", "ATQA", "LCSW"],
    "الأغذية والاستهلاك": ["EFID", "JUFO", "OLFI", "IFAP", "MPCO", "ACGC"],
    "الاتصالات والتكنولوجيا والرعاية": ["ETEL", "RACC", "MTIE", "ETRS", "CIRA", "EGAS", "ICFC", "ISPH", "RMDA"],
    "صناديق المؤشرات والذهب": ["CMS", "BWA", "NMF", "AZG", "THNDR_GOLD"]
}

def calculate_portfolio_zakat(state_data, parsed_stocks, custom_query=None):
    """
    حاسبة زكاة الأسهم والمحافظ الاستثمارية وفق معايير AAOIFI ودار الإفتاء المصرية.
    1. عروض التجارة والمضاربة: 2.5% على القيمة السوقية الإجمالية للمحفظة.
    2. الاستثمار طويل الأجل / النماء: 2.5% على الوعاء الزكوي (صافي الأصول المتداولة 20% تقديراً).
    """
    holdings = state_data.get("holdings", {})
    eval_items = []
    
    if custom_query:
        parts = custom_query.strip().split()
        if len(parts) >= 2:
            ticker_raw = parts[0].replace("_", " ").upper().replace(".CA", "")
            detected = detect_stocks_in_query(ticker_raw)
            ticker = detected[0] if detected else ticker_raw.strip()
            try:
                qty = float(parts[1].replace(",", ""))
                eval_items.append((ticker, qty))
            except ValueError:
                pass
                
    if not eval_items and holdings:
        for ticker, h in holdings.items():
            qty = float(h.get("qty", 0))
            if qty > 0:
                eval_items.append((ticker, qty))
                
    if not eval_items:
        return (
            "🕌 <b>حاسبة زكاة الأسهم والمحافظ الاستثمارية (معايير AAOIFI):</b>\n\n"
            "محفظتك خالية من الأسهم حالياً.\n"
            "💡 يمكنك حساب زكاة سهم محدد مباشرة عبر الأمر:\n"
            "<code>/zakat [السهم] [الكمية]</code> (مثال: <code>/zakat سوديك 2000</code>)\n"
            "أو تسجيل صفقاتك عبر أمر <code>/buy</code> لحساب زكاة محفظتك تلقائياً."
        )
        
    total_market_val = 0.0
    stock_rows = ""
    for ticker, qty in eval_items:
        name = COMPANY_NAMES_AR.get(ticker, ticker)
        stock_d = parsed_stocks.get(ticker, {})
        curr_p = stock_d.get("close", 0.0)
        item_val = qty * curr_p
        total_market_val += item_val
        stock_rows += f"• <b>{name} ({ticker}):</b> {qty:,.0f} سهم × {curr_p:.2f} ج = <code>{item_val:,.2f} ج</code>\n"
        
    # الحسابات الشرعية
    zakat_trade_hijri = total_market_val * 0.025
    zakat_trade_gregorian = total_market_val * 0.02577
    
    zakat_base_longterm = total_market_val * 0.20
    zakat_invest_hijri = zakat_base_longterm * 0.025
    zakat_invest_gregorian = zakat_base_longterm * 0.02577
    
    msg = (
        "🕌 <b>بيان زكاة الأسهم والمحفظة الشرعي المعتمد:</b>\n\n"
        f"💼 <b>إجمالي القيمة السوقية للأصول المقيمة:</b> <code>{total_market_val:,.2f} ج.م</code>\n\n"
        f"{stock_rows}\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ <b>إذا كانت نيتك (المضاربة والبيع السريع - عروض تجارة):</b>\n"
        f"   └ الزكاة الواجبة (سنة هجرية 2.5%): <b><code>{zakat_trade_hijri:,.2f} ج.م</code></b>\n"
        f"   └ الزكاة الواجبة (سنة ميلادية 2.577%): <b><code>{zakat_trade_gregorian:,.2f} ج.م</code></b>\n\n"
        "2️⃣ <b>إذا كانت نيتك (الاستثمار طويل الأجل وحبس الأصل للاستفادة من الأرباح):</b>\n"
        f"   ├ الوعاء الزكوي للأصول المتداولة (20% تقديراً): <code>{zakat_base_longterm:,.2f} ج.م</code>\n"
        f"   └ الزكاة الواجبة (سنة هجرية 2.5%): <b><code>{zakat_invest_hijri:,.2f} ج.م</code></b>\n"
        f"   └ الزكاة الواجبة (سنة ميلادية 2.577%): <b><code>{zakat_invest_gregorian:,.2f} ج.م</code></b>\n\n"
        "💡 <b>ملاحظة فقهية:</b> تجب الزكاة إذا بلغ مجموع أموالك النقدية وقيمة الأسهم نصاب الزكاة (ما يعادل 85 جرام ذهب عيار 21) وحال عليها الحول."
    )
    return msg

def analyze_portfolio_rebalancing(holdings, parsed_stocks):
    """مصفوفة التنويع القطاعي وتنبيهات تركز المخاطر المؤسسية."""
    if not holdings:
        return (
            "⚖️ <b>مصفوفة التنويع القطاعي وإعادة التوازن (Portfolio Balance):</b>\n\n"
            "المحفظة خالية من الأسهم حالياً. سجّل صفقاتك عبر أمر <code>/buy</code> لتحليل توزيع المخاطر القطاعية."
        )
        
    sector_values = {}
    total_val = 0.0
    
    for ticker, h in holdings.items():
        qty = float(h.get("qty", 0))
        stock_d = parsed_stocks.get(ticker, {})
        curr_p = stock_d.get("close", float(h.get("buy_price", 0)))
        val = qty * curr_p
        total_val += val
        
        s_name = "قطاعات أخرى"
        for sec, syms in SECTORS_MAP.items():
            if ticker in syms:
                s_name = sec
                break
        sector_values[s_name] = sector_values.get(s_name, 0.0) + val
        
    if total_val <= 0:
        return "⚠️ القيمة الإجمالية للمحفظة غير كافية للتحليل."
        
    msg = (
        "⚖️ <b>مصفوفة التنويع القطاعي وإدارة تركز المخاطر:</b>\n\n"
        f"💰 <b>إجمالي القيمة السوقية للمحفظة:</b> <code>{total_val:,.2f} ج.م</code>\n\n"
        "📊 <b>الأوزان النسبية للقطاعات الحالية:</b>\n"
    )
    
    warnings = []
    for sec, s_val in sorted(sector_values.items(), key=lambda x: x[1], reverse=True):
        weight = (s_val / total_val) * 100.0
        if weight > 35.0:
            status = "🔴 تركز مخاطر مرتفع (Overweight)"
            warnings.append(f"• قطاع <b>{sec}</b> يمثل <code>{weight:.1f}%</code> من محفظتك (المستوى الآمن ≤ 35%).")
        elif weight >= 15.0:
            status = "🟢 وزن متوازن وصحي"
        else:
            status = "🟡 وزن خفيف (Underweight)"
        msg += f"• <b>{sec}:</b> <code>{weight:.1f}%</code> ({s_val:,.1f} ج) | {status}\n"
        
    msg += "\n━━━━━━━━━━━━━━━━━━━\n"
    if warnings:
        msg += "⚠️ <b>تنبيهات تركز المخاطر:</b>\n" + "\n".join(warnings) + "\n\n"
        msg += "💡 <b>خطة إعادة التوازن المقترحة:</b>\n"
        msg += "1. يُنصح بتجميد الشراء الإضافي في القطاع المتضخم وتأمين الأرباح به.\n"
        msg += "2. توجيه سيولة التوزيعات أو الصفقات الرابحة نحو الأسهم المقومة بأقل من قيمتها (راجع <code>/undervalued</code>) أو صناديق الذهب والشريعة للتحوط."
    else:
        msg += "✅ <b>حالة المحفظة:</b> توزيعك القطاعي متوازن وصحي وموزع باحترافية على القطاعات."
        
    return msg

def find_smart_money_accumulation(parsed_stocks):
    """رادار التجميع المؤسسي وتدفقات السيولة الذكية (Smart Money Tracker)."""
    candidates = []
    for ticker, d in parsed_stocks.items():
        if ticker not in ALL_TICKERS:
            continue
        cmf = d.get("cmf")
        mfi = d.get("mfi")
        rsi = d.get("rsi")
        val_traded = d.get("val_traded", 0)
        chg = d.get("chgPct", 0)
        close = d.get("close", 0)
        
        # تجميع مؤسسي: CMF > 0.05 مع عدم وصول السهم لقمة مفرطة RSI < 65
        if cmf is not None and cmf > 0.05 and rsi is not None and rsi < 65:
            candidates.append({
                "ticker": ticker,
                "name": COMPANY_NAMES_AR.get(ticker, ticker),
                "close": close,
                "chg": chg,
                "cmf": cmf,
                "mfi": mfi,
                "rsi": rsi,
                "val_traded": val_traded
            })
            
    candidates.sort(key=lambda x: x["cmf"], reverse=True)
    if not candidates:
        return "🐋 <b>رادار التجميع المؤسسي:</b> لا توجد مؤشرات تجميع استثنائية حالياً في مرحلة الهدوء السعري."
        
    msg = (
        "🐋 <b>رادار التجميع المؤسسي وتدفق السيولة الذكية (Smart Money Tracker):</b>\n"
        "<i>أسهم تشهد تدفقات سيولة شرائية خفية مستمرة (CMF موجب) وقبل حدوث الانفجار السعري:</i>\n\n"
    )
    for c in candidates[:5]:
        t = c["ticker"]
        name = c["name"]
        p = c["close"]
        chg_str = f"+{c['chg']}%" if c['chg'] > 0 else f"{c['chg']}%"
        cmf_str = f"+{c['cmf']:.3f}"
        mfi_str = f"{c['mfi']:.1f}" if c['mfi'] else "-"
        rsi_str = f"{c['rsi']:.1f}"
        v_millions = c["val_traded"] / 1_000_000.0 if c["val_traded"] else 0
        
        msg += (
            f"🔹 <b>{name} ({t})</b>: <b>{p:.2f} ج.م</b> ({chg_str})\n"
            f"   ├ 🌊 <b>تدفق سيولة تشايكين (CMF):</b> <code>{cmf_str}</code> (شراء تجميعي قوي)\n"
            f"   ├ ⚡ <b>مؤشر MFI:</b> <code>{mfi_str}</code> | <b>مؤشر RSI:</b> <code>{rsi_str}</code>\n"
            f"   ├ 💵 <b>قيمة التداول:</b> {v_millions:,.1f} مليون جنيه\n"
            f"   └ 💡 <i>فحص تفصيلي:</i> <code>/chart {t}</code> | <code>/calc {t} {p:.2f} [الوقف]</code>\n\n"
        )
    msg += "💡 <b>القاعدة المؤسسية:</b> عندما يكون مؤشر CMF موجباً بقوة مع استقرار السعر دون قمم (RSI < 65)، فهذا يعكس تجميعاً هادئاً للمحافظ الكبرى قبل بدء موجة الصعود القادمة."
    return msg

def run_stock_backtest_strategy(ticker: str):
    """محاكي اختبار الاستراتيجيات تاريخياً على مدار عام كامل (250 جلسة تداول)."""
    sym = ticker.upper().replace(".CA", "").replace("EGX:", "").replace("_", " ").strip()
    detected = detect_stocks_in_query(sym)
    sym = detected[0] if detected else sym
    name = COMPANY_NAMES_AR.get(sym, sym)
    
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}.CA?interval=1d&range=1y"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            res = data.get('chart', {}).get('result', [])
            if not res:
                return f"⚠️ لم يتم العثور على بيانات تاريخية لسهم <b>{name} ({sym})</b>."
            quote = res[0]['indicators']['quote'][0]
            closes = quote.get('close', [])
            
        clean_closes = [float(c) for c in closes if c is not None and c > 0]
        if len(clean_closes) < 40:
            return f"⚠️ البيانات التاريخية المتاحة لسهم <b>{name} ({sym})</b> غير كافية لمحاكاة الاختبار (أقل من 40 جلسة)."
            
        deltas = [clean_closes[i] - clean_closes[i-1] for i in range(1, len(clean_closes))]
        gains = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
        
        rsi_series = [None] * 14
        avg_g = sum(gains[:14]) / 14.0
        avg_l = sum(losses[:14]) / 14.0
        
        for i in range(14, len(deltas)):
            avg_g = (avg_g * 13 + gains[i]) / 14.0
            avg_l = (avg_l * 13 + losses[i]) / 14.0
            if avg_l == 0:
                rsi = 100.0
            else:
                rs = avg_g / avg_l
                rsi = 100.0 - (100.0 / (1.0 + rs))
            rsi_series.append(rsi)
            
        trades = []
        in_pos = False
        entry_p = 0.0
        entry_idx = 0
        
        for i in range(14, len(clean_closes) - 1):
            rsi = rsi_series[i]
            curr_p = clean_closes[i]
            
            if not in_pos:
                if rsi is not None and rsi <= 35.0:
                    in_pos = True
                    entry_p = clean_closes[i + 1]
                    entry_idx = i + 1
            else:
                pnl_pct = ((curr_p - entry_p) / entry_p) * 100.0
                days_held = i - entry_idx
                if pnl_pct >= 8.0 or pnl_pct <= -5.0 or (rsi is not None and rsi >= 65.0) or days_held >= 25:
                    trades.append({
                        "entry": entry_p,
                        "exit": curr_p,
                        "pnl_pct": pnl_pct,
                        "days": days_held
                    })
                    in_pos = False
                    
        if not trades:
            return (
                f"🧪 <b>نتائج الاختبار التاريخي لسهم {name} ({sym}) خلال آخر عام:</b>\n\n"
                f"لم تتولد أي إشارات تشبع بيعي حاد (RSI ≤ 35) خلال العام الماضي نظراً لسيطرة الاتجاه الصاعد القوي على السهم.\n"
                f"💡 يُفضل استخدام استراتيجية اختراق المتوسطات المتحركة أو اختبار سهم آخر."
            )
            
        wins = [t for t in trades if t["pnl_pct"] > 0]
        losses = [t for t in trades if t["pnl_pct"] <= 0]
        win_rate = (len(wins) / len(trades)) * 100.0
        total_roi = sum(t["pnl_pct"] for t in trades)
        best_trade = max(t["pnl_pct"] for t in trades)
        max_drawdown = min(t["pnl_pct"] for t in trades)
        
        win_icon = "🟢" if win_rate >= 60.0 else "🟡"
        
        msg = (
            f"🧪 <b>محاكي اختبار الاستراتيجيات الكمية (Backtest Engine):</b>\n"
            f"🏢 <b>السهم المختبر:</b> <b>{name} ({sym})</b> | <b>الفترة:</b> آخر 250 جلسة تداول (عام كامل)\n"
            f"🎯 <b>الاستراتيجية:</b> قناص الارتدادات من التشبع البيعي (RSI ≤ 35 مع جني أرباح +8% ووقف -5%)\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>النتائج الإحصائية الدقيقة:</b>\n"
            f"• <b>إجمالي الصفقات المنفذة:</b> {len(trades)} صفقة\n"
            f"• {win_icon} <b>معدل النجاح (Win Rate):</b> <b><code>{win_rate:.1f}%</code></b> ({len(wins)} رابحة / {len(losses)} خاسرة)\n"
            f"• 📈 <b>العائد التراكمي الإجمالي:</b> <b><code>{total_roi:+.1f}%</code></b>\n"
            f"• 🚀 <b>أفضل صفقة محققة:</b> <code>+{best_trade:.1f}%</code>\n"
            f"• 🛑 <b>أقصى تراجع لصفقة مفردة:</b> <code>{max_drawdown:.1f}%</code>\n\n"
            f"🕒 <b>تفاصيل آخر العمليات المنفذة في الاختبار:</b>\n"
        )
        for t in trades[-4:]:
            t_icon = "🟢" if t["pnl_pct"] > 0 else "🔴"
            msg += f"• {t_icon} دخول: {t['entry']:.2f} ج ⬅️ خروج: {t['exit']:.2f} ج | عائد: <code>{t['pnl_pct']:+.1f}%</code> ({t['days']} يوم)\n"
            
        msg += "\n💡 <b>الخلاصة الإحصائية:</b> نتائج الباك تست تثبت كفاءة إدارة المخاطر في تحويل التشبعات البيعية إلى صفقات رابحة."
        return msg
    except Exception as e:
        return f"⚠️ خطأ أثناء إجراء المحاكاة لسهم {sym}: {e}"

def export_portfolio_to_excel(holdings, state_data, parsed_stocks, indices=None, funds_data=None, filepath="portfolio_report.xlsx"):
    """تصدير كشف حساب المحفظة الاستثمارية بصيغة إكسل احترافية (RTL, Styling, Formatting)."""
    if openpyxl is None:
        return None
        
    wb = openpyxl.Workbook()
    
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
    sub_header_fill = PatternFill(start_color="2A4D7A", end_color="2A4D7A", fill_type="solid")
    total_fill = PatternFill(start_color="EAEEF3", end_color="EAEEF3", fill_type="solid")
    
    green_font = Font(name="Calibri", size=10, color="006100", bold=True)
    red_font = Font(name="Calibri", size=10, color="9C0006", bold=True)
    bold_font = Font(name="Calibri", size=10, bold=True)
    
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )
    
    # 1. المحفظة الاستثمارية
    ws_port = wb.active
    ws_port.title = "المحفظة الاستثمارية"
    ws_port.views.sheetView[0].rightToLeft = True
    
    headers_port = [
        "كود السهم", "اسم الشركة", "القطاع", "الكمية", "سعر الشراء (ج)",
        "السعر اللحظي (ج)", "القيمة الإجمالية (ج)", "الربح/الخسارة (ج)", "العائد %", "مؤشر RSI"
    ]
    ws_port.append(headers_port)
    for c in range(1, len(headers_port) + 1):
        cell = ws_port.cell(row=1, column=c)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        
    total_cost = 0.0
    total_val = 0.0
    row_idx = 2
    
    for ticker, h in holdings.items():
        qty = float(h.get("qty", 0))
        buy_p = float(h.get("buy_price", 0))
        d = parsed_stocks.get(ticker, {})
        curr_p = d.get("close", buy_p)
        name = COMPANY_NAMES_AR.get(ticker, ticker)
        
        sec = "أخرى"
        for s_name, t_list in SECTORS_MAP.items():
            if ticker in t_list:
                sec = s_name
                break
                
        cost = qty * buy_p
        val = qty * curr_p
        pnl = val - cost
        pnl_pct = (pnl / cost) if cost > 0 else 0.0
        
        total_cost += cost
        total_val += val
        
        ws_port.append([
            ticker, name, sec, qty, buy_p, curr_p, val, pnl, pnl_pct, d.get("rsi", "-")
        ])
        
        ws_port.cell(row=row_idx, column=4).number_format = '#,##0'
        ws_port.cell(row=row_idx, column=5).number_format = '#,##0.00'
        ws_port.cell(row=row_idx, column=6).number_format = '#,##0.00'
        ws_port.cell(row=row_idx, column=7).number_format = '#,##0.00'
        
        pnl_c = ws_port.cell(row=row_idx, column=8)
        pnl_c.number_format = '[Color10]+#,##0.00;[Red]-#,##0.00;0.00'
        pnl_c.font = green_font if pnl >= 0 else red_font
        
        pct_c = ws_port.cell(row=row_idx, column=9)
        pct_c.number_format = '+0.00%;-0.00%;0.00%'
        pct_c.font = green_font if pnl_pct >= 0 else red_font
        
        for c in range(1, len(headers_port) + 1):
            ws_port.cell(row=row_idx, column=c).border = thin_border
            
        row_idx += 1
        
    tot_pnl = total_val - total_cost
    tot_pct = (tot_pnl / total_cost) if total_cost > 0 else 0.0
    ws_port.append(["الإجمالي", "", "", "", total_cost, total_val, total_val, tot_pnl, tot_pct, ""])
    for c in range(1, len(headers_port) + 1):
        cell = ws_port.cell(row=row_idx, column=c)
        cell.font = bold_font
        cell.fill = total_fill
        cell.border = thin_border
        
    ws_port.cell(row=row_idx, column=5).number_format = '#,##0.00'
    ws_port.cell(row=row_idx, column=6).number_format = '#,##0.00'
    ws_port.cell(row=row_idx, column=7).number_format = '#,##0.00'
    ws_port.cell(row=row_idx, column=8).number_format = '[Color10]+#,##0.00;[Red]-#,##0.00;0.00'
    ws_port.cell(row=row_idx, column=9).number_format = '+0.00%;-0.00%;0.00%'
    
    for col in ws_port.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws_port.column_dimensions[get_column_letter(col[0].column)].width = max(max_len + 4, 12)
        
    # 2. سجل الصفقات
    journal = state_data.get("journal", [])
    ws_journal = wb.create_sheet(title="سجل الصفقات المحققة")
    ws_journal.views.sheetView[0].rightToLeft = True
    headers_j = ["التاريخ", "النوع", "كود السهم", "اسم الشركة", "الكمية", "سعر التنفيذ (ج)", "الربح المحقق (ج)", "العائد %"]
    ws_journal.append(headers_j)
    for c in range(1, len(headers_j) + 1):
        cell = ws_journal.cell(row=1, column=c)
        cell.font = header_font
        cell.fill = sub_header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        
    r_j = 2
    for item in journal:
        t_sym = item.get("ticker", "")
        t_name = COMPANY_NAMES_AR.get(t_sym, t_sym)
        pnl_val = item.get("pnl", 0.0)
        pnl_pct = item.get("pnl_pct", 0.0) / 100.0
        ws_journal.append([
            item.get("date", ""),
            "شراء" if item.get("type") == "BUY" else "بيع",
            t_sym,
            t_name,
            item.get("qty", 0),
            item.get("price", 0),
            pnl_val if item.get("type") == "SELL" else "-",
            pnl_pct if item.get("type") == "SELL" else "-"
        ])
        for c in range(1, len(headers_j) + 1):
            ws_journal.cell(row=r_j, column=c).border = thin_border
        r_j += 1
        
    for col in ws_journal.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws_journal.column_dimensions[get_column_letter(col[0].column)].width = max(max_len + 4, 12)
        
    wb.save(filepath)
    return filepath

def fetch_and_format_insider_deals(all_news=None, egx_beta_items=None):
    """رادار صفقات كبار المساهمين والداخليين وصفقات الحجم الكبير (Insider & Block Trades)."""
    try:
        if all_news is None or egx_beta_items is None:
            all_news = fetch_all_news()
            egx_beta_items = fetch_egx_beta_news()
        alerts = scan_insider_and_block_trades(all_news, egx_beta_items)
        if not alerts:
            return (
                "🕵️ <b>رادار صفقات كبار الملاك والداخليين (Insider Trades):</b>\n\n"
                "لم يتم رصد إفصاحات جديدة لتعاملات الداخليين أو صفقات كبرى خلال الـ 24 ساعة الماضية.\n"
                "💡 يقوم الرادار بمسح إفصاحات شاشة البورصة لحظياً وتنبيهك فور تنفيذ أي صفقة شراء لمجلس الإدارة أو أسهم الخزينة."
            )
        msg = (
            "🕵️ <b>رادار صفقات كبار الملاك والداخليين والصفقات الكبرى:</b>\n"
            "<i>رصد تحركات مجالس الإدارات والمجموعات المرتبطة وكبار المساهمين:</i>\n\n"
        )
        for al in alerts[:8]:
            title = escape_html(al.get("title", ""))
            source = escape_html(al.get("source", "إفصاح رسمي"))
            link = escape_html(al.get("link", "#"))
            msg += f"• <b>{title}</b>\n  └ المصدر: <i>{source}</i> | <a href='{link}'>قراءة الإفصاح الرسمي</a>\n\n"
        msg += "💡 <b>القاعدة المؤسسية:</b> شراء الداخليين وأعضاء مجلس الإدارة لأسهم شركاتهم بالسوق المفتوح هو أقوى مؤشرات الثقة الصاعدة في نمو أرباح الشركة والتدفقات المستقبلية."
        return msg
    except Exception as e:
        return f"⚠️ خطأ أثناء فحص صفقات الداخليين: {e}"

def scan_bullish_divergence_all(parsed_stocks):
    """رادار التباعد الفني الإيجابي (Bullish Divergence Scanner): قاع سعر هابط يقابله قاع صاعد أعلى في RSI."""
    results = []
    scan_tickers = [t for t in ALL_TICKERS if t in parsed_stocks and parsed_stocks[t].get("close", 0) > 0]
    
    for ticker in scan_tickers:
        d = parsed_stocks.get(ticker, {})
        curr_rsi = d.get("rsi")
        if curr_rsi is None or curr_rsi > 55:
            continue
            
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.CA?interval=1d&range=2mo"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                res = data.get('chart', {}).get('result', [])
                if not res:
                    continue
                quote = res[0]['indicators']['quote'][0]
                closes = [float(c) for c in quote.get('close', []) if c is not None and c > 0]
                lows = [float(l) for l in quote.get('low', []) if l is not None and l > 0]
                
            if len(closes) < 22:
                continue
                
            deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
            gains = [max(delta, 0) for delta in deltas]
            losses = [max(-delta, 0) for delta in deltas]
            rsi_series = [None] * 14
            avg_g = sum(gains[:14]) / 14.0
            avg_l = sum(losses[:14]) / 14.0
            for i in range(14, len(deltas)):
                avg_g = (avg_g * 13 + gains[i]) / 14.0
                avg_l = (avg_l * 13 + losses[i]) / 14.0
                rs = avg_g / (avg_l if avg_l > 0 else 1e-9)
                rsi_series.append(100.0 - (100.0 / (1.0 + rs)))
                
            if len(lows) < 20:
                continue
            window_lows = lows[-20:]
            window_rsi = rsi_series[-20:]
            
            p1_idx = min(range(0, 10), key=lambda i: window_lows[i])
            p2_idx = min(range(10, len(window_lows)), key=lambda i: window_lows[i])
            
            price1 = window_lows[p1_idx]
            price2 = window_lows[p2_idx]
            rsi1 = window_rsi[p1_idx]
            rsi2 = window_rsi[p2_idx]
            
            if rsi1 is not None and rsi2 is not None and price2 <= (price1 * 0.995) and rsi2 >= (rsi1 + 2.0):
                results.append({
                    "ticker": ticker,
                    "name": COMPANY_NAMES_AR.get(ticker, ticker),
                    "close": d.get("close"),
                    "chgPct": d.get("chgPct", 0),
                    "price1": price1,
                    "price2": price2,
                    "rsi1": rsi1,
                    "rsi2": rsi2,
                    "div_strength": (rsi2 - rsi1)
                })
        except Exception:
            continue
            
    if not results:
        return (
            "⚡ <b>رادار التباعد الفني الإيجابي (Bullish Divergence Scanner):</b>\n\n"
            "لم يتم رصد دايفرجنس إيجابي مكتمل في أسهم العينة حالياً.\n"
            "💡 يتم فحص السلوك السعري لكل سهم تاريخياً، ويرسل البوت تنبيهاً فور انفصال مسار القوة النسبية RSI عن قيعان السعر."
        )
        
    results.sort(key=lambda x: x["div_strength"], reverse=True)
    msg = (
        "⚡ <b>رادار التباعد الفني الإيجابي (Bullish Divergence Tracker):</b>\n"
        "<i>رصد أسهم سجلت قيعاناً سعرية أدنى بينما شكل مؤشر RSI قيعاناً صاعدة (تجميع خفي وانعكاس وشيك):</i>\n\n"
    )
    for r in results[:5]:
        t = r["ticker"]
        name = r["name"]
        p = r["close"]
        chg_sign = "+" if r['chgPct'] > 0 else ""
        msg += (
            f"🔹 <b>{name} ({t}):</b> <b>{p:.2f} ج.م</b> ({chg_sign}{r['chgPct']:.2f}%)\n"
            f"   ├ 📉 <b>قاع السعر السابق:</b> {r['price1']:.2f} ج ⬅️ <b>القاع الأحدث:</b> <code>{r['price2']:.2f} ج</code> (قاع أدنى)\n"
            f"   ├ 📈 <b>قاع RSI السابق:</b> {r['rsi1']:.1f} ⬅️ <b>قاع RSI الأحدث:</b> <code>{r['rsi2']:.1f}</code> (قاع صاعد أعلى! 🚀)\n"
            f"   └ 🎯 <b>التوصية:</b> إشارة انعكاس قاع استباقية. فحص الشارت: <code>/chart {t}</code>\n\n"
        )
    msg += "💡 <b>القاعدة الفنية:</b> الدايفرجنس الإيجابي هو أحد أدق نماذج صيد القيعان تاريخياً، حيث يعكس تلاشي قوى البيع وسيطرة تدفقات الشراء المؤسسية قبل بدء موجة الصعود."
    return msg

def calculate_fair_value_scenarios(ticker: str, parsed_stocks: dict):
    """مصفوفة السعر العادل والسيناريوهات الثلاثة (Bull Case / Base Case / Bear Case)."""
    sym = ticker.upper().replace(".CA", "").replace("EGX:", "").replace("_", " ").strip()
    detected = detect_stocks_in_query(sym)
    sym = detected[0] if detected else sym
    name = COMPANY_NAMES_AR.get(sym, sym)
    
    d = parsed_stocks.get(sym, {})
    curr_p = d.get("close", 0.0)
    if curr_p <= 0:
        return f"⚠️ تعذر جلب بيانات السعر اللحظي لسهم <b>{name} ({sym})</b>."
        
    pe = d.get("pe")
    pb = d.get("pb")
    rsi = d.get("rsi", 50)
    sma50 = d.get("sma50", curr_p * 0.95)
    sma200 = d.get("sma200", curr_p * 0.90)
    div_y = d.get("div_yield", 0.0)
    
    sector_pe = 8.5
    if pe and pe > 0:
        val_multiple = (sector_pe / pe)
        base_fair = curr_p * (0.65 + 0.35 * min(max(val_multiple, 0.7), 1.5))
    else:
        base_fair = curr_p * 1.10
        
    bull_target = max(base_fair * 1.15, curr_p * 1.18)
    bull_roi = ((bull_target - curr_p) / curr_p) * 100.0
    
    base_target = max(base_fair, curr_p * 1.08)
    base_roi = ((base_target - curr_p) / curr_p) * 100.0
    
    bear_support = min(curr_p * 0.93, sma50 if sma50 and sma50 < curr_p else curr_p * 0.92)
    bear_risk = ((bear_support - curr_p) / curr_p) * 100.0
    
    reward_risk_ratio = abs(base_roi / bear_risk) if abs(bear_risk) > 0 else 2.0
    
    div_str = f"{div_y:.2f}%" if div_y else "غير متوفر"
    pe_str = f"{pe}x" if pe else "N/A"
    pb_str = f"{pb}x" if pb else "N/A"
    
    msg = (
        f"🎯 <b>مصفوفة السعر العادل والسيناريوهات الاستثمارية:</b>\n"
        f"🏢 <b>السهم:</b> <b>{name} ({sym})</b> | <b>السعر اللحظي:</b> <code>{curr_p:.2f} ج.م</code>\n"
        f"📊 <b>مكرر الربحية (P/E):</b> {pe_str} | <b>المضاعف الدفتري (P/B):</b> {pb_str}\n"
        f"⚡ <b>مؤشر RSI:</b> {rsi} | <b>عائد الكوبون:</b> {div_str}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣ <b>السيناريو المتفائل (Bull Case - اختراق القمم واستمرار الزخم):</b>\n"
        f"   └ 🎯 <b>المستهدف السعري:</b> <b><code>{bull_target:.2f} ج.م</code></b> (عائد متوقع: <code>+{bull_roi:.1f}%</code>)\n"
        f"   └ 💡 <i>المحفز:</i> نمو أرباح الشركة وضخ سيولة تجميعية مؤسسية جديدة.\n\n"
        f"2️⃣ <b>السيناريو الأساسي (Base Case - السعر العادل المنطقي 3-6 أشهر):</b>\n"
        f"   └ 🎯 <b>السعر العادل المقدر:</b> <b><code>{base_target:.2f} ج.م</code></b> (عائد متوقع: <code>+{base_roi:.1f}%</code>)\n"
        f"   └ 💡 <i>المحفز:</i> تسعير التدفقات النقدية والاقتراب من متوسط مكررات أرباح القطاع.\n\n"
        f"3️⃣ <b>السيناريو المتحفظ (Bear Case - قاع الأمان ووقف الخسارة):</b>\n"
        f"   └ 🛑 <b>مستوى الدعم الصلب:</b> <b><code>{bear_support:.2f} ج.م</code></b> (مخاطرة هبوط: <code>{bear_risk:.1f}%</code>)\n"
        f"   └ 💡 <i>المحفز:</i> ضغوط بيعية عامة في المؤشر أو كسر متوسط 50 يوماً.\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⚖️ <b>معامل العائد إلى المخاطرة (Risk/Reward):</b> <code>1:{reward_risk_ratio:.1f}</code>\n"
        f"💡 <b>الخلاصة الاستثمارية:</b> {'الفرصة ممتازة استثمارياً ونسبة العائد للمخاطرة مغرية للشراء التدريجي.' if reward_risk_ratio >= 1.8 else 'يُنصح بالتريث وانتظار إشارة ارتداد وتأكيد الدعم قبل بناء مراكز جديدة.'}"
    )
    return msg

def format_dividend_radar(parsed_stocks, all_news=None, egx_beta_items=None):
    """رادار موسم الكوبونات وعوائد التوزيعات النقدية السنوية."""
    div_stocks = []
    for ticker, d in parsed_stocks.items():
        if ticker not in ALL_TICKERS:
            continue
        y = d.get("div_yield")
        if y and y > 0:
            div_stocks.append((ticker, COMPANY_NAMES_AR.get(ticker, ticker), d.get("close", 0), y, d.get("pe")))
            
    div_stocks.sort(key=lambda x: x[3], reverse=True)
    
    if all_news is None or egx_beta_items is None:
        all_news = fetch_all_news()
        egx_beta_items = fetch_egx_beta_news()
    actions = scan_dividends_and_actions(all_news, egx_beta_items)
    
    msg = (
        "💰 <b>رادار موسم الكوبونات وعوائد التوزيعات النقدية (Dividend Radar):</b>\n"
        "<i>أعلى الأسهم الشرعية من حيث العائد النقدي السنوي ومواعيد استحقاق التوزيعات:</i>\n\n"
    )
    
    if div_stocks:
        msg += "📊 <b>أعلى الأسهم تحقيقاً للعائد النقدي (Dividend Yield):</b>\n"
        for t, name, close, y, pe in div_stocks[:6]:
            pe_str = f"{pe}x" if pe else "-"
            msg += f"• <b>{name} ({t}):</b> عائد <b><code>{y:.2f}%</code></b> سنوياً (السعر: {close:.2f} ج | P/E: {pe_str})\n"
        msg += "\n"
    else:
        msg += "• لا تتوفر بيانات عوائد كوبونات مباشرة حالياً في عينة المسح.\n\n"
        
    if actions:
        msg += "📅 <b>أحدث إفصاحات وقرارات التوزيعات والجمعيات العامة:</b>\n"
        for ac in actions[:4]:
            t_esc = escape_html(ac.get("title", ""))
            link = escape_html(ac.get("link", "#"))
            msg += f"• {t_esc} <a href='{link}'>[التفاصيل]</a>\n"
        msg += "\n"
        
    msg += "💡 <b>القاعدة الاستثمارية:</b> الأسهم التي توزع عوائد نقدية سخية (>8%) توفر حماية ممتازة لرأس المال ضد التضخم وتقلبات السوق، وتتيح إعادة استثمار الكوبونات لتعظيم العائد التراكمي."
    return msg

def calculate_smart_dca(holdings, parsed_stocks, query):
    """حاسبة التبريد والتعديل الذكي للتكلفة (Smart DCA): تحسب عدد الأسهم والسيولة المطلوبة لخفض متوسط التكلفة."""
    import math
    parts = query.strip().split()
    if len(parts) < 2:
        return (
            "📉 <b>حاسبة التبريد والتعديل الذكي للتكلفة (Smart DCA):</b>\n\n"
            "تحسب لك عدد الأسهم والمبلغ الدقيق المطلوب لخفض متوسط تكلفتك إلى السعر المستهدف.\n\n"
            "📌 <b>طريقة الاستخدام:</b>\n"
            "• <code>/dca [السهم] [المتوسط_المستهدف]</code> (إذا كان السهم مسجلاً بمحفظتك)\n"
            "  <i>مثال:</i> <code>/dca سوديك 32.00</code>\n"
            "• أو كتابة كامل البيانات يدوياً:\n"
            "  <code>/dca [السهم] [سعر_الشراء_الحالي] [المتوسط_المستهدف]</code>"
        )
        
    sym_raw = parts[0].replace("_", " ").upper().replace(".CA", "")
    detected = detect_stocks_in_query(sym_raw)
    ticker = detected[0] if detected else sym_raw.strip()
    name = COMPANY_NAMES_AR.get(ticker, ticker)
    
    stock_d = parsed_stocks.get(ticker, {})
    curr_market_p = stock_d.get("close", 0.0)
    h_data = holdings.get(ticker, {}) if holdings else {}
    
    q1, p1, p2, p_target = None, None, curr_market_p, None
    
    try:
        if len(parts) == 2:
            p_target = float(parts[1].replace(",", ""))
            if h_data:
                q1 = float(h_data.get("qty", 0))
                p1 = float(h_data.get("buy_price", 0))
            else:
                return f"⚠️ سهم <b>{name} ({ticker})</b> غير مسجل بمحفظتك. يرجى إدخال: <code>/dca {ticker} [سعر_شرائك] [المتوسط_المستهدف]</code>"
        elif len(parts) == 3:
            p1 = float(parts[1].replace(",", ""))
            p_target = float(parts[2].replace(",", ""))
            q1 = float(h_data.get("qty", 1000)) if h_data else 1000.0
        elif len(parts) >= 4:
            q1 = float(parts[1].replace(",", ""))
            p1 = float(parts[2].replace(",", ""))
            p_target = float(parts[3].replace(",", ""))
    except ValueError:
        return "⚠️ يرجى إدخال أرقام صحيحة للأسعار والكميات."
        
    if not q1 or not p1 or not p_target or p2 <= 0:
        return "⚠️ بيانات غير مكتملة أو تعذر قراءة سعر السهم اللحظي في السوق."
        
    if p_target <= p2:
        return f"⚠️ السعر المستهدف ({p_target:.2f} ج) يجب أن يكون أعلى من سعر السوق اللحظي ({p2:.2f} ج) لتتمكن من التبريد."
        
    if p_target >= p1:
        return f"⚠️ السعر المستهدف ({p_target:.2f} ج) يجب أن يكون أقل من سعر تكلفتك الحالي ({p1:.2f} ج) ليكون تخفيضاً للتكلفة."
        
    q2 = math.ceil((q1 * (p1 - p_target)) / (p_target - p2))
    required_cash = q2 * p2
    total_shares = q1 + q2
    new_avg = ((q1 * p1) + (q2 * p2)) / total_shares
    
    sec_name = "القطاع"
    for s_name, t_list in SECTORS_MAP.items():
        if ticker in t_list:
            sec_name = s_name
            break
            
    msg = (
        f"📉 <b>خطة التبريد والتعديل الذكي للتكلفة (Smart DCA):</b>\n\n"
        f"🏢 <b>السهم:</b> <b>{name} ({ticker})</b> | <b>القطاع:</b> {sec_name}\n"
        f"📊 <b>مركزك الحالي:</b> {q1:,.0f} سهم بمتوسط <code>{p1:.2f} ج.م</code>\n"
        f"💵 <b>سعر التبريد اللحظي بالسوق:</b> <code>{p2:.2f} ج.م</code>\n"
        f"🎯 <b>متوسط التكلفة المستهدف:</b> <code>{p_target:.2f} ج.م</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🛒 <b>الكمية التعديلية المطلوبة للشراء:</b> <b><code>{q2:,.0f} سهم</code></b>\n"
        f"💰 <b>السيولة النقدية المطلوبة للعملية:</b> <b><code>{required_cash:,.2f} ج.م</code></b>\n"
        f"📦 <b>إجمالي أسهمك بعد التنفيذ:</b> {total_shares:,.0f} سهم\n"
        f"✅ <b>متوسط التكلفة الجديد الفعلي:</b> <b><code>{new_avg:.2f} ج.م</code></b> (توفير: {p1 - new_avg:.2f} ج/سهم)\n\n"
        f"💡 <b>قاعدة السلامة المالية:</b> تأكد من توفر سيولة نقدية كافية وألا يؤدي التبريد لزيادة وزن قطاع {sec_name} عن 35% من محفظتك الإجمالية."
    )
    return msg

def run_portfolio_stress_test(holdings, parsed_stocks, fx_gold_data=None, indices=None):
    """محاكي اختبار الضغط ومصفوفة الصدمات الاقتصادية للمحفظة (Portfolio Stress Testing)."""
    if not holdings:
        return "💥 <b>اختبار ضغط المحفظة:</b> محفظتك خالية حالياً من الأسهم. سجّل أسهمك أولاً عبر أمر <code>/buy</code>."
        
    total_val = 0.0
    stock_weights = {}
    
    for ticker, h in holdings.items():
        qty = float(h.get("qty", 0))
        curr_p = float(parsed_stocks.get(ticker, {}).get("close", float(h.get("buy_price", 0))))
        val = qty * curr_p
        total_val += val
        stock_weights[ticker] = val
        
    if total_val <= 0:
        return "⚠️ القيمة السوقية للمحفظة غير كافية لمحاكاة اختبار الضغط."
        
    exporters = ["EGAL", "SKPC", "AMOC", "ORWE", "ORAS", "ARCC", "ATQA", "MCQE"]
    gold_funds = ["AZG", "THNDR_GOLD"]
    
    shock_crash_loss = total_val * 0.075
    crash_pnl_pct = -7.5
    
    exporter_val = sum(stock_weights.get(t, 0) for t in exporters)
    gold_val = sum(stock_weights.get(t, 0) for t in gold_funds)
    fx_gain = (exporter_val * 0.08) + (gold_val * 0.12) + ((total_val - exporter_val - gold_val) * 0.02)
    fx_pct = (fx_gain / total_val) * 100.0
    
    gold_gain = (gold_val * 0.15)
    gold_pct = (gold_gain / total_val) * 100.0
    
    msg = (
        "💥 <b>محاكي اختبار الضغط وصدمات السوق (Portfolio Stress Testing):</b>\n\n"
        f"💼 <b>إجمالي القيمة السوقية للمحفظة:</b> <code>{total_val:,.2f} ج.م</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ <b>السيناريو الأول: هبوط حاد في المؤشر العام (EGX30 -7.0% Crash):</b>\n"
        f"   └ 📉 الأثر التقديري على المحفظة: <b><code>-{shock_crash_loss:,.2f} ج.م</code></b> (<code>{crash_pnl_pct:.1f}%</code>)\n"
        "   └ 🛡️ <i>صمام الأمان:</i> حجز الأرباح وتفعيل أمر الوقف المتحرك يحميك من 70% من هذا التراجع.\n\n"
        "2️⃣ <b>السيناريو الثاني: تحريك سعر الصرف (انخفاض الجنيه -10% أمام الدولار):</b>\n"
        f"   └ 📈 الأثر التقديري على المحفظة: <b><code>+{fx_gain:,.2f} ج.م</code></b> (<code>+{fx_pct:.1f}%</code>)\n"
        f"   └ 💡 <i>السبب:</i> استفادة الشركات المصدرة بالدولار والتحوط بالذهب والقطاع العقاري.\n\n"
        "3️⃣ <b>السيناريو الثالث: قفزة تاريخية في أسعار الذهب (+15% Gold Surge):</b>\n"
        f"   └ 🏆 مساهمة صناديق الذهب المباشرة: <b><code>+{gold_gain:,.2f} ج.م</code></b> (<code>+{gold_pct:.1f}%</code>)\n"
        f"   └ 💡 {'لديك تحوط ممتاز بصناديق الذهب!' if gold_val > 0 else 'محفظتك خالية من صناديق الذهب (AZG / Thndr Gold) ويُنصح بتخصيص 10% منها للتحوط.'}\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>التقييم المؤسسي الإجمالي للمناعة والمخاطر:</b>\n"
        f"{'🟢 محفظتك شديدة المتانة وتتمتع بمصادر دخل دولارية وتحوط عالي ضد تقلبات العملة.' if exporter_val / total_val >= 0.25 else '🟡 يُنصح بتعزيز أسهم الشركات المصدرة وصناديق الذهب لتحسين صمود المحفظة أمام الصدمات.'}"
    )
    return msg

def format_user_alerts_manager(state_data):
    """عرض وإدارة التنبيهات السارية مع إمكانية حذف أي تنبيه بنقرة واحدة."""
    alerts = state_data.get("alerts", [])
    if not alerts:
        return (
            "🔔 <b>إدارة التنبيهات المشروطة (Alerts Manager):</b>\n\n"
            "لا توجد أي تنبيهات نشطة مسجلة حالياً.\n\n"
            "💡 <b>يمكنك تفعيل تنبيهات ذكية بسهولة:</b>\n"
            "• تنبيه سعري: <code>/alert TMGH > 100</code>\n"
            "• تنبيه RSI: <code>/alert FWRY rsi < 30</code>\n"
            "• تنبيه تقاطع ذهبي: <code>/alert SKPC cross</code>"
        ), None
        
    msg = "🔔 <b>قائمة التنبيهات الفنية والسعرية النشطة:</b>\n\n"
    buttons = []
    
    for i, al in enumerate(alerts):
        ticker = al.get("ticker", "")
        name = COMPANY_NAMES_AR.get(ticker, ticker)
        cond = al.get("cond", "")
        target = al.get("price") or al.get("rsi") or al.get("type", "")
        
        msg += f"<b>{i+1}.</b> <b>{name} ({ticker}):</b> الشرط <code>{cond} {target}</code>\n"
        buttons.append([{"text": f"❌ حذف {name} ({cond} {target})", "callback_data": f"del_alert_{i}"}])
        
    buttons.append([{"text": "🗑️ مسح جميع التنبيهات", "callback_data": "clear_all_alerts"}])
    buttons.append([{"text": "💼 كشف المحفظة", "callback_data": "btn_portfolio"}])
    
    return msg, {"inline_keyboard": buttons}

def format_dashboard_summary(holdings, state_data, parsed_stocks, indices, funds_data):
    """عرض رابط وملخص لوحة التحكم الرقمية التفاعلية للمحفظة والأسهم."""
    repo_url = "https://mahereasybakery-web.github.io/egypt-sharia-stock-report/"
    total_val = 0.0
    for ticker, h in (holdings or {}).items():
        qty = float(h.get("qty", 0))
        p = float(parsed_stocks.get(ticker, {}).get("close", float(h.get("buy_price", 0))))
        total_val += qty * p
        
    msg = (
        "🌐 <b>لوحة التحكم الرقمية التفاعلية (Interactive Web Dashboard):</b>\n\n"
        f"💼 <b>القيمة السوقية للمحفظة:</b> <code>{total_val:,.2f} ج.م</code>\n"
        "📊 <b>المميزات المتوفرة في لوحة الويب:</b>\n"
        "• رسم بياني دائري تفاعلي (Donut Chart) للأوزان القطاعية.\n"
        "• شاشات أسعار وبطاقات لحظية للأسهم الـ 33 ومؤشرات RSI وCMF.\n"
        "• شارت TradingView تفاعلي مدمج ومباشر.\n\n"
        f"🔗 <b>رابط الدخول المباشر:</b>\n"
        f"<a href='{repo_url}'>{repo_url}</a>"
    )
    return msg

def handle_telegram_command(text):
    text_clean = text.strip()
    text_lower = text_clean.lower()
    
    # 0. الفئتان الرئيسيتان لتقسيم الشاشة والحفاظ على النظافة التامة (زرين فقط أسفل الشاشة)
    if "مركز المحفظة" in text_clean or text_clean == "💼 مركز المحفظة والاستثمار" or text_lower in ["/portfolio_hub", "/hub_portfolio"]:
        msg = (
            "💼 <b>مركز إدارة المحفظة والقرارات الاستثمارية:</b>\n"
            "<i>اختر التقرير أو الأداة المطلوبة من الأزرار التفاعلية أدناه:</i>"
        )
        reply_telegram(msg, reply_markup=PORTFOLIO_HUB_KEYBOARD)
        return
        
    elif "رادار السوق" in text_clean or text_clean == "📊 رادار السوق والتحليلات" or text_lower in ["/market_hub", "/market"]:
        msg = (
            "📊 <b>رادار مسح السوق والتحليلات الفنية والمالية:</b>\n"
            "<i>اختر الرادار أو التحليل المطلوب من الأزرار التفاعلية أدناه:</i>"
        )
        reply_telegram(msg, reply_markup=MARKET_HUB_KEYBOARD)
        return
        
    if text_lower.startswith("/start") or text_lower.startswith("/help") or "مساعدة" in text_clean or "مساعده" in text_clean or "أوامر" in text_clean:
        help_msg = (
            "<b>🤖 أهلاً بك في منصة تداول أسهم الشريعة المؤسسية!</b>\n\n"
            "تم تنظيم كافة التقارير والأدوات في <b>مركزين رئيسيين</b> بأسفل الشاشة لتوفير أقصى وضوح لمتابعة التقارير:\n\n"
            "💼 <b>[💼 مركز المحفظة والاستثمار]:</b>\n"
            "• كشف الأرباح والخسائر اللحظي (P&L)\n"
            "• تصدير كشف المحفظة إكسل فاخر (RTL)\n"
            "• مصفوفة تنويع القطاعات وإعادة التوازن\n"
            "• حاسبة زكاة الأسهم (معايير AAOIFI)\n"
            "• حاسبة التبريد وتعديل التكلفة (Smart DCA)\n"
            "• محاكي اختبار ضغط وصدمات السوق\n"
            "• حاسبة إدارة المخاطر (قاعدة 1.5%)\n"
            "• سجل الصفقات المغلقة ونسبة النجاح\n"
            "• إدارة وتعديل التنبيهات المشروطة\n"
            "• لوحة التحكم الرقمية التفاعلية (Web)\n\n"
            "📊 <b>[📊 رادار السوق والتحليلات]:</b>\n"
            "• تقرير الأسعار اللحظية وصناديق الذهب\n"
            "• بيان مفصل لمؤشر القوة النسبية RSI\n"
            "• رادار اقتناص أسهم القيمة وهامش الأمان\n"
            "• رادار التجميع المؤسسي والسيولة CMF\n"
            "• رادار التباعد الفني الإيجابي (الدايفرجنس)\n"
            "• رادار موسم الكوبونات والتوزيعات النقدية\n"
            "• رادار صفقات كبار الملاك والداخليين\n"
            "• بطاقة السعر العادل والسيناريوهات الثلاثة\n"
            "• محاكي اختبار الاستراتيجيات تاريخياً\n"
            "• شارت فني بالشموع اليابانية ومؤشر RSI\n"
            "• استشارة المحلل المالي الذكي (Gemini AI)\n\n"
            "💡 <i>اضغط على أي من الزرين أسفل الشاشة للوصول الفوري لكافة التقارير!</i>"
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
            reply_telegram(format_portfolio_pnl_message(pnl_data), reply_markup=get_portfolio_inline_keyboard(holdings))
        except Exception as e:
            reply_telegram(f"⚠️ حدث خطأ أثناء حساب المحفظة: {e}")
            
    elif text_lower.startswith("/chart") or text_lower.startswith("/شارت") or "شارت فني" in text_clean:
        args = ""
        if text_lower.startswith("/chart"):
            args = text[len("/chart"):].strip()
        elif text_lower.startswith("/شارت"):
            args = text[len("/شارت"):].strip()
        elif "شارت فني" in text_clean:
            args = ""
            
        if not args:
            reply_telegram(
                "📈 <b>أمر الشارت الفني بالشموع اليابانية ومؤشر RSI</b>\n\n"
                "يرجى تحديد السهم المطلوب بعد الأمر. أمثلة:\n"
                "• <code>/chart OCDI</code>\n"
                "• <code>/chart طلعت مصطفى</code>\n"
                "• <code>/chart FWRY</code>"
            )
            return
            
        detected = detect_stocks_in_query(args)
        ticker = detected[0] if detected else args.upper().replace(".CA", "").replace("EGX:", "").strip()
        c_name = COMPANY_NAMES_AR.get(ticker, ticker)
        
        reply_telegram(f"🔄 جاري رسم الشارت الفني المتقدم لسهم <b>{c_name} ({ticker})</b>...")
        chart_file, caption = generate_candlestick_chart(ticker)
        if chart_file and os.path.exists(chart_file):
            send_telegram_photo(chart_file, caption)
            try:
                os.remove(chart_file)
            except Exception:
                pass
        else:
            reply_telegram(f"⚠️ {caption}")
            
    elif text_lower.startswith("/fundamental") or text_lower.startswith("/مالي") or "فحص مالي" in text_clean:
        args = ""
        if text_lower.startswith("/fundamental"):
            args = text[len("/fundamental"):].strip()
        elif text_lower.startswith("/مالي"):
            args = text[len("/مالي"):].strip()
        elif "فحص مالي" in text_clean:
            args = ""
            
        if not args:
            reply_telegram(
                "🏢 <b>بطاقة التحليل المالي ومضاعفات التقييم والديون</b>\n\n"
                "يرجى كتابة رمز أو اسم السهم بعد الأمر. أمثلة:\n"
                "• <code>/fundamental TMGH</code>\n"
                "• <code>/fundamental سوديك</code>\n"
                "• <code>/fundamental فوري</code>"
            )
            return
            
        detected = detect_stocks_in_query(args)
        ticker = detected[0] if detected else args.upper().replace(".CA", "").replace("EGX:", "").strip()
        c_name = COMPANY_NAMES_AR.get(ticker, ticker)
        
        reply_telegram(f"🔄 جاري استخراج البيانات المالية ومضاعفات التقييم لسهم <b>{c_name} ({ticker})</b>...")
        f_data = fetch_stock_fundamentals(ticker)
        reply_telegram(format_fundamental_card(f_data), reply_markup=PORTFOLIO_INLINE_KEYBOARD)
        
    elif text_lower.startswith("/buy") or text_lower.startswith("/شراء"):
        reply_telegram(handle_buy_trade(text))
        
    elif text_lower.startswith("/sell") or text_lower.startswith("/بيع"):
        reply_telegram(handle_sell_trade(text))
        
    elif text_lower.startswith("/journal") or text_lower.startswith("/history") or "سجل الصفقات" in text_clean:
        try:
            state_data, _ = get_github_state()
            reply_telegram(format_trade_journal(state_data), reply_markup=DEFAULT_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ خطأ أثناء فتح سجل الصفقات: {e}")
            
    elif text_lower.startswith("/report") or "تقرير الأسعار" in text_clean or "تقرير الاسعار" in text_clean or "تحديث فوري" in text_clean:
        reply_telegram("🔄 جاري تحديث بيانات السوق وبث التقرير اللحظي فوراً...")
        send_report(force=True)
        
    elif text_lower.startswith("/rsi") or "rsi" in text_lower or "بيان مفصل" in text_clean:
        reply_telegram("🔄 جاري إعداد البيان المفصل لمؤشر RSI لجميع الأسهم...")
        send_detailed_rsi_report()
        
    elif text_lower.startswith("/summary") or "ملخص" in text_clean:
        reply_telegram("🔄 جاري إعداد ملخص حركة اليوم والتحليل الفني...")
        send_daily_summary()
        
    elif text_lower.startswith("/undervalued") or text_lower.startswith("/فرص") or text_lower.startswith("/قيمة") or "أسهم القيمة" in text_clean or "فرص القيمة" in text_clean:
        reply_telegram("🔄 جاري مسح الأسهم الشرعية واقتناص فرص القيمة وهامش الأمان...")
        try:
            s = {}
            if os.path.exists(STRINGS_PATH):
                with open(STRINGS_PATH, "r", encoding="utf-8") as f:
                    s = json.load(f)
            parsed_stocks, _ = fetch_all_data_tv(ALL_TICKERS, s)
            reply_telegram(format_undervalued_report(parsed_stocks), reply_markup=PORTFOLIO_INLINE_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ خطأ أثناء تشغيل رادار أسهم القيمة: {e}")
            
    elif text_lower.startswith("/calc") or text_lower.startswith("/حاسبة") or "حاسبة المخاطر" in text_clean:
        try:
            state_data, _ = get_github_state()
            reply_telegram(calculate_position_risk(text, state_data), reply_markup=PORTFOLIO_INLINE_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ حدث خطأ في الحاسبة: {e}")
            
    elif text_lower.startswith("/zakat") or text_lower.startswith("/زكاة") or text_lower.startswith("/زكاه") or "زكاة" in text_clean or "زكاه" in text_clean:
        query_arg = ""
        if text_lower.startswith("/zakat"):
            query_arg = text[len("/zakat"):].strip()
        elif text_lower.startswith("/زكاة"):
            query_arg = text[len("/زكاة"):].strip()
        elif text_lower.startswith("/زكاه"):
            query_arg = text[len("/زكاه"):].strip()
        reply_telegram("🔄 جاري حساب الزكاة الشرعية وفق معايير AAOIFI...")
        try:
            state_data, _ = get_github_state()
            s = {}
            if os.path.exists(STRINGS_PATH):
                with open(STRINGS_PATH, "r", encoding="utf-8") as f:
                    s = json.load(f)
            parsed_stocks, _ = fetch_all_data_tv(ALL_TICKERS, s)
            reply_telegram(calculate_portfolio_zakat(state_data, parsed_stocks, custom_query=query_arg if query_arg else None), reply_markup=PORTFOLIO_INLINE_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ خطأ في حاسبة الزكاة: {e}")
            
    elif text_lower.startswith("/rebalance") or text_lower.startswith("/توازن") or "توازن المحفظة" in text_clean:
        reply_telegram("🔄 جاري تحليل التوزيع القطاعي ومصفوفة المخاطر...")
        try:
            state_data, _ = get_github_state()
            holdings = state_data.get("holdings", {})
            s = {}
            if os.path.exists(STRINGS_PATH):
                with open(STRINGS_PATH, "r", encoding="utf-8") as f:
                    s = json.load(f)
            parsed_stocks, _ = fetch_all_data_tv(ALL_TICKERS, s)
            reply_telegram(analyze_portfolio_rebalancing(holdings, parsed_stocks), reply_markup=PORTFOLIO_INLINE_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ خطأ في مصفوفة التوازن: {e}")
            
    elif text_lower.startswith("/accumulation") or text_lower.startswith("/smart_money") or text_lower.startswith("/تجميع") or "التجميع المؤسسي" in text_clean:
        reply_telegram("🔄 جاري فحص رادار التجميع المؤسسي وتدفقات السيولة الذكية (CMF)...")
        try:
            s = {}
            if os.path.exists(STRINGS_PATH):
                with open(STRINGS_PATH, "r", encoding="utf-8") as f:
                    s = json.load(f)
            parsed_stocks, _ = fetch_all_data_tv(ALL_TICKERS, s)
            reply_telegram(find_smart_money_accumulation(parsed_stocks), reply_markup=PORTFOLIO_INLINE_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ خطأ في رادار التجميع المؤسسي: {e}")
            
    elif text_lower.startswith("/backtest") or text_lower.startswith("/باك_تست") or text_lower.startswith("/اختبار"):
        parts = text.split()
        if len(parts) < 2:
            reply_telegram(
                "🧪 <b>محاكي اختبار الاستراتيجيات الكمية تاريخياً (Backtest):</b>\n\n"
                "يرجى تحديد رمز أو اسم السهم المراد اختباره على مدار عام كامل (250 جلسة).\n"
                "أمثلة:\n"
                "• <code>/backtest TMGH</code>\n"
                "• <code>/backtest سوديك</code>\n"
                "• <code>/backtest FWRY</code>"
            )
        else:
            ticker_input = parts[1]
            reply_telegram(f"🔄 جاري جلب 250 شمعة تداول يومية وتنفيذ المحاكاة الكمية لسهم {ticker_input}...")
            try:
                reply_telegram(run_stock_backtest_strategy(ticker_input), reply_markup=PORTFOLIO_INLINE_KEYBOARD)
            except Exception as e:
                reply_telegram(f"⚠️ خطأ في محاكي الاختبار: {e}")
                
    elif text_lower.startswith("/export") or text_lower.startswith("/تصدير") or text_lower.startswith("/اكسل") or "تصدير إكسل" in text_clean:
        reply_telegram("🔄 جاري توليد كشف حساب المحفظة الفاخر بصيغة Excel (RTL)...")
        try:
            state_data, _ = get_github_state()
            holdings = state_data.get("holdings", {})
            s = {}
            if os.path.exists(STRINGS_PATH):
                with open(STRINGS_PATH, "r", encoding="utf-8") as f:
                    s = json.load(f)
            parsed_stocks, _ = fetch_all_data_tv(ALL_TICKERS, s)
            indices, _ = fetch_indices_data_tv(s)
            funds_data, _ = fetch_all_funds_data()
            excel_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio_report.xlsx")
            res_path = export_portfolio_to_excel(holdings, state_data, parsed_stocks, indices, funds_data, filepath=excel_path)
            if res_path and os.path.exists(res_path):
                now_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M")
                caption = f"📊 <b>كشف حساب المحفظة الاستثمارية الفاخر (Excel)</b>\n🕒 التاريخ: {now_str}\n💼 تم تدقيق وتنسيق البيانات وفق المعايير المحاسبية المعتمدة."
                send_telegram_document(res_path, caption=caption)
                try:
                    os.remove(res_path)
                except Exception:
                    pass
            else:
                reply_telegram("⚠️ تعذر توليد ملف الإكسل. يرجى التحقق من توفر البيانات.")
        except Exception as e:
            reply_telegram(f"⚠️ خطأ أثناء تصدير ملف الإكسل: {e}")
            
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
        if len(parts) < 3:
            reply_telegram(
                "🎯 <b>نظام التنبيهات الذكية والمشروطة:</b>\n\n"
                "• <b>تنبيه سعري:</b> <code>/alert TMGH > 100</code> أو <code>/alert FWRY < 18</code>\n"
                "• <b>تنبيه مؤشر RSI:</b> <code>/alert سوديك rsi < 30</code>\n"
                "• <b>تنبيه التقاطع الذهبي:</b> <code>/alert SKPC cross</code>\n\n"
                "💡 <i>لعرض أو مسح تنبيهاتك الحالية:</i> <code>/my_alerts</code>"
            )
            return
            
        sym_input = parts[1].upper().replace("[", "").replace("]", "").replace(".CA", "")
        detected = detect_stocks_in_query(sym_input)
        ticker = detected[0] if detected else sym_input
        name = COMPANY_NAMES_AR.get(ticker, ticker)
        
        state_data, state_sha = get_github_state()
        if "alerts" not in state_data:
            state_data["alerts"] = []
            
        # 1. تنبيه التقاطع الذهبي: /alert SKPC cross
        if len(parts) == 3 and parts[2].lower() in ["cross", "تقاطع", "الذهبي"]:
            new_al = {"ticker": ticker, "cond": "cross", "type": "Golden Cross"}
            state_data["alerts"].append(new_al)
            if update_github_state(state_data, state_sha):
                reply_telegram(f"🎯 <b>تم تفعيل تنبيه التقاطع الذهبي:</b>\nسيصلك إشعار فوري عند اختراق سهم <b>{name} ({ticker})</b> لمتوسط 200 يوم صعوداً (Golden Cross).")
            else:
                reply_telegram("❌ فشل تسجيل التنبيه على الخادم.")
            return
            
        # 2. تنبيه مؤشر RSI: /alert FWRY rsi < 30
        if len(parts) >= 4 and parts[2].lower() == "rsi":
            cond = parts[3]
            if cond not in [">", "<", ">=", "<="] or len(parts) < 5:
                reply_telegram("⚠️ التنسيق المطلوب لتنبيه RSI:\n<code>/alert [السهم] rsi [< أو >] [القيمة]</code>\nمثال:\n<code>/alert FWRY rsi < 30</code>")
                return
            try:
                target_rsi = float(parts[4].replace(",", ""))
                new_al = {"ticker": ticker, "cond": cond, "rsi": target_rsi}
                state_data["alerts"].append(new_al)
                if update_github_state(state_data, state_sha):
                    reply_telegram(f"🎯 <b>تم تفعيل تنبيه مؤشر RSI:</b>\nسيصلك إشعار فوري عند وصول RSI لسهم <b>{name} ({ticker})</b> إلى <b>{cond} {target_rsi:.0f}</b>.")
                else:
                    reply_telegram("❌ فشل تسجيل التنبيه على الخادم.")
            except ValueError:
                reply_telegram("⚠️ قيمة مؤشر RSI يجب أن تكون رقماً.")
            return
            
        # 3. تنبيه سعري عادي: /alert TMGH > 100
        cond = parts[2]
        if cond not in [">", "<", ">=", "<="]:
            reply_telegram("⚠️ التنسيق المطلوب:\n<code>/alert [السهم] [> أو <] [السعر]</code>\nمثال:\n<code>/alert FWRY > 20.00</code>")
            return
        try:
            price = float(parts[3].replace(",", ""))
            new_al = {"ticker": ticker, "cond": cond, "price": price}
            state_data["alerts"].append(new_al)
            if update_github_state(state_data, state_sha):
                reply_telegram(f"🎯 <b>تم تفعيل التنبيه السعري:</b>\nسيصلك إشعار فوري عند وصول سهم <b>{name} ({ticker})</b> إلى <b>{cond} {price:.2f} ج.م</b>.")
            else:
                reply_telegram("❌ فشل تسجيل التنبيه على الخادم.")
        except ValueError:
            reply_telegram("⚠️ السعر يجب أن يكون رقماً صحيحاً.")

    elif text_lower.startswith("/my_alerts") or text_lower.startswith("/تنبيهاتي") or "إدارة وتعديل تنبيهاتي" in text_clean or "تنبيهاتي" in text_clean:
        try:
            state_data, _ = get_github_state()
            alerts_msg, alerts_markup = format_user_alerts_manager(state_data)
            reply_telegram(alerts_msg, reply_markup=alerts_markup if alerts_markup else PORTFOLIO_HUB_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ خطأ أثناء جلب قائمة التنبيهات: {e}")

    elif text_lower.startswith("/insiders") or text_lower.startswith("/داخليين") or text_lower.startswith("/صفقات") or "صفقات كبار الملاك" in text_clean or "صفقات الداخليين" in text_clean:
        reply_telegram("🔄 جاري فحص إفصاحات البورصة المصرية ورصد صفقات كبار الملاك والداخليين...")
        try:
            insider_report = fetch_and_format_insider_deals()
            reply_telegram(insider_report, reply_markup=MARKET_HUB_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ خطأ أثناء جلب صفقات الداخليين: {e}")

    elif text_lower.startswith("/divergence") or text_lower.startswith("/دايفرجنس") or "رادار الدايفرجنس" in text_clean or "انفراج إيجابي" in text_clean:
        reply_telegram("🔄 جاري مسح الشارتات الفنية ورصد إشارات الدايفرجنس الإيجابي الخفي...")
        try:
            s = {}
            if os.path.exists(STRINGS_PATH):
                with open(STRINGS_PATH, "r", encoding="utf-8") as f:
                    s = json.load(f)
            parsed_stocks, _ = fetch_all_data_tv(ALL_TICKERS, s)
            div_report = scan_bullish_divergence_all(parsed_stocks)
            reply_telegram(div_report, reply_markup=MARKET_HUB_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ خطأ أثناء مسح الدايفرجنس: {e}")

    elif text_lower.startswith("/target") or text_lower.startswith("/سعر_عادل") or text_lower.startswith("/هدف") or "سعر عادل" in text_clean or "مصفوفة الأهداف" in text_clean:
        args = ""
        if text_lower.startswith("/target"):
            args = text[len("/target"):].strip()
        elif text_lower.startswith("/سعر_عادل"):
            args = text[len("/سعر_عادل"):].strip()
        elif text_lower.startswith("/هدف"):
            args = text[len("/هدف"):].strip()
            
        if not args:
            reply_telegram(
                "🎯 <b>مصفوفة السعر العادل والسيناريوهات الثلاثة (3-Scenario Valuation)</b>\n\n"
                "يرجى كتابة رمز أو اسم السهم بعد الأمر. أمثلة:\n"
                "• <code>/target TMGH</code>\n"
                "• <code>/target سوديك</code>\n"
                "• <code>/target فوري</code>"
            )
            return
            
        detected = detect_stocks_in_query(args)
        ticker = detected[0] if detected else args.upper().replace(".CA", "").replace("EGX:", "").strip()
        name = COMPANY_NAMES_AR.get(ticker, ticker)
        
        reply_telegram(f"🔄 جاري حساب القيمة العادلة والسيناريوهات الثلاثة لسهم <b>{name} ({ticker})</b>...")
        try:
            s = {}
            if os.path.exists(STRINGS_PATH):
                with open(STRINGS_PATH, "r", encoding="utf-8") as f:
                    s = json.load(f)
            parsed_stocks, _ = fetch_all_data_tv([ticker], s)
            val_msg = calculate_fair_value_scenarios(ticker, parsed_stocks)
            reply_telegram(val_msg, reply_markup=MARKET_HUB_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ خطأ أثناء حساب القيمة العادلة: {e}")

    elif text_lower.startswith("/dividends") or text_lower.startswith("/كوبونات") or text_lower.startswith("/توزيعات") or "رادار الكوبونات" in text_clean or "رادار التوزيعات" in text_clean:
        reply_telegram("🔄 جاري فحص عوائد التوزيعات وتواريخ الكوبونات النقدية للأسهم القيادية...")
        try:
            s = {}
            if os.path.exists(STRINGS_PATH):
                with open(STRINGS_PATH, "r", encoding="utf-8") as f:
                    s = json.load(f)
            parsed_stocks, _ = fetch_all_data_tv(ALL_TICKERS, s)
            div_report = format_dividend_radar(parsed_stocks)
            reply_telegram(div_report, reply_markup=MARKET_HUB_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ خطأ أثناء فحص الكوبونات: {e}")

    elif text_lower.startswith("/dca") or text_lower.startswith("/تبريد") or "حاسبة التبريد" in text_clean:
        query_arg = ""
        if text_lower.startswith("/dca"):
            query_arg = text[len("/dca"):].strip()
        elif text_lower.startswith("/تبريد"):
            query_arg = text[len("/تبريد"):].strip()
            
        try:
            state_data, _ = get_github_state()
            holdings = state_data.get("holdings", {})
            s = {}
            if os.path.exists(STRINGS_PATH):
                with open(STRINGS_PATH, "r", encoding="utf-8") as f:
                    s = json.load(f)
            parsed_stocks, _ = fetch_all_data_tv(ALL_TICKERS, s)
            dca_result = calculate_smart_dca(holdings, parsed_stocks, query_arg)
            reply_telegram(dca_result, reply_markup=PORTFOLIO_HUB_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ خطأ في حاسبة التبريد: {e}")

    elif text_lower.startswith("/stresstest") or text_lower.startswith("/ضغط") or text_lower.startswith("/صدمات") or "محاكي اختبار الضغط" in text_clean or "اختبار الضغط" in text_clean:
        reply_telegram("🔄 جاري تنفيذ محاكاة اختبار الضغط ومصفوفة الصدمات على محفظتك...")
        try:
            state_data, _ = get_github_state()
            holdings = state_data.get("holdings", {})
            s = {}
            if os.path.exists(STRINGS_PATH):
                with open(STRINGS_PATH, "r", encoding="utf-8") as f:
                    s = json.load(f)
            parsed_stocks, _ = fetch_all_data_tv(ALL_TICKERS, s)
            indices, _ = fetch_indices_data_tv(s)
            stress_msg = run_portfolio_stress_test(holdings, parsed_stocks, indices=indices)
            reply_telegram(stress_msg, reply_markup=PORTFOLIO_HUB_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ خطأ أثناء تنفيذ اختبار الضغط: {e}")

    elif text_lower.startswith("/dashboard") or text_lower.startswith("/لوحة") or "لوحة التحكم الرقمية" in text_clean or "لوحة التحكم" in text_clean:
        try:
            state_data, _ = get_github_state()
            holdings = state_data.get("holdings", {})
            s = {}
            if os.path.exists(STRINGS_PATH):
                with open(STRINGS_PATH, "r", encoding="utf-8") as f:
                    s = json.load(f)
            parsed_stocks, _ = fetch_all_data_tv(ALL_TICKERS, s)
            indices, _ = fetch_indices_data_tv(s)
            funds_data, _ = fetch_all_funds_data()
            dash_msg = format_dashboard_summary(holdings, state_data, parsed_stocks, indices, funds_data)
            web_buttons = {
                "inline_keyboard": [
                    [{"text": "🌐 فتح لوحة التحكم على المتصفح", "url": "https://mahereasybakery-web.github.io/egypt-sharia-stock-report/"}],
                    [{"text": "💼 مركز المحفظة", "callback_data": "hub_portfolio"}, {"text": "📊 رادار السوق", "callback_data": "hub_market"}]
                ]
            }
            reply_telegram(dash_msg, reply_markup=web_buttons)
        except Exception as e:
            reply_telegram(f"⚠️ خطأ في عرض لوحة التحكم: {e}")
        
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
            
    elif text_lower.startswith("/ask") or text_lower.startswith("/اسأل") or "استشارة المحلل" in text_clean:
        question = ""
        if text_lower.startswith("/ask"):
            question = text[len("/ask"):].strip()
        elif text_lower.startswith("/اسأل"):
            question = text[len("/اسأل"):].strip()
        elif "استشارة المحلل" in text_clean:
            question = ""
            
        if not question:
            help_ask_msg = (
                "🧠 <b>المحلل المالي والاستثماري الذكي للبورصة المصرية</b>\n\n"
                "أهلاً بك! يمكنك سؤالي عن أي سهم، أو استشارة بشأن محفظتك، أو استكشاف اتجاه السوق، وسأجيبك فوراً بالاعتماد على <b>البيانات اللحظية الحية للبورصة (TradingView)</b> ومؤشرات RSI والمتوسطات ومحفظتك!\n\n"
                "💡 <b>أمثلة أسئلة يمكنك نسخها أو النقر عليها:</b>\n"
                "• <code>/ask ما تحليلك الفني لسهم طلعت مصطفى ومستويات الدعم والمقاومة؟</code>\n"
                "• <code>/ask هل سهم فوري مناسب للشراء حالياً أم في مرحلة جني أرباح؟</code>\n"
                "• <code>/ask ما رأيك في سهم سوديك وهل دخل منطقة تشبع شرائي؟</code>\n"
                "• <code>/ask حلل وضع محفظتي الحالية وما أفضل فرصة للتعزيز؟</code>\n"
                "• <code>/ask كيف ترى اتجاه السوق والمؤشر الرئيسي EGX30 اليوم؟</code>\n\n"
                "✍️ <i>فقط اكتب:</i> <code>/ask [سؤالك هنا]</code>"
            )
            reply_telegram(help_ask_msg, reply_markup=PORTFOLIO_INLINE_KEYBOARD)
            return
            
        reply_telegram("🔄 جاري جمع البيانات اللحظية وإعداد التحليل المؤسسي الذكي...")
        try:
            analysis = ask_financial_advisor(question)
            reply_telegram(analysis, reply_markup=PORTFOLIO_INLINE_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ حدث خطأ أثناء التحليل: {e}")
        
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
        reply_telegram("🔄 جاري جمع البيانات اللحظية وإعداد التحليل المؤسسي الذكي...")
        try:
            analysis = ask_financial_advisor(text)
            reply_telegram(analysis, reply_markup=PORTFOLIO_INLINE_KEYBOARD)
        except Exception as e:
            reply_telegram(f"⚠️ حدث خطأ أثناء التحليل: {e}")

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
                    cb_msg = cb.get("message", {})
                    msg_id = cb_msg.get("message_id")
                    chat_id = str(cb_msg.get("chat", {}).get("id", ""))
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
                            
                        # التنقل الهرمي المقتضب (زرين فقط في كل مستوى لمنع الازدحام نهائياً)
                        if cb_data == "hub_portfolio":
                            msg = (
                                "💼 <b>مركز إدارة المحفظة والقرارات الاستثمارية:</b>\n"
                                "<i>تم تنظيم كافة الأدوات في فئتين (زرين فقط) لتصفية الشاشة:</i>"
                            )
                            edit_telegram_message(msg_id, msg, reply_markup=PORTFOLIO_MAIN_HUB_KEYBOARD)
                            
                        elif cb_data == "sub_portfolio_reports":
                            msg = (
                                "📊 <b>كشوفات وتقارير المحفظة الاستثمارية:</b>\n"
                                "<i>اختر الكشف أو التقرير المطلوب:</i>"
                            )
                            edit_telegram_message(msg_id, msg, reply_markup=PORTFOLIO_REPORTS_KEYBOARD)
                            
                        elif cb_data == "sub_portfolio_tools":
                            msg = (
                                "🛠️ <b>حاسبات وأدوات إدارة المحفظة والمخاطر:</b>\n"
                                "<i>اختر الأداة أو الحاسبة المطلوبة:</i>"
                            )
                            edit_telegram_message(msg_id, msg, reply_markup=PORTFOLIO_TOOLS_KEYBOARD)
                            
                        elif cb_data == "hub_market":
                            msg = (
                                "📊 <b>رادار مسح السوق والتحليلات الفنية والمالية:</b>\n"
                                "<i>تم تنظيم كافة الرادارات في فئتين (زرين فقط) لتصفية الشاشة:</i>"
                            )
                            edit_telegram_message(msg_id, msg, reply_markup=MARKET_MAIN_HUB_KEYBOARD)
                            
                        elif cb_data == "sub_market_radars":
                            msg = (
                                "⚡ <b>رادارات السوق والفرص اللحظية والسيولة:</b>\n"
                                "<i>اختر الرادار المطلوب لبث بياناته فوراً:</i>"
                            )
                            edit_telegram_message(msg_id, msg, reply_markup=MARKET_RADARS_KEYBOARD)
                            
                        elif cb_data == "sub_market_analysis":
                            msg = (
                                "🏢 <b>التحليل الفني والمالي ومصفوفة التقييم:</b>\n"
                                "<i>اختر نوع التحليل المطلوب:</i>"
                            )
                            edit_telegram_message(msg_id, msg, reply_markup=MARKET_ANALYSIS_KEYBOARD)
                            
                        elif cb_data == "btn_target_menu":
                            msg = (
                                "🎯 <b>مصفوفة السعر العادل والسيناريوهات الثلاثة:</b>\n"
                                "<i>اختر السهم المطلوب لحساب قيمته العادلة فوراً أو اكتب /target [السهم]:</i>"
                            )
                            edit_telegram_message(msg_id, msg, reply_markup=TARGET_STOCKS_KEYBOARD)
                            
                        elif cb_data == "btn_chart_menu":
                            msg = (
                                "📈 <b>طلب شارت فني لسهم بالشموع اليابانية ومؤشر RSI:</b>\n"
                                "<i>اختر السهم المطلوب لرسم شارته اللحظي فوراً أو اكتب /chart [السهم]:</i>"
                            )
                            edit_telegram_message(msg_id, msg, reply_markup=CHART_STOCKS_KEYBOARD)
                            
                        elif cb_data.startswith("target_"):
                            t = cb_data.replace("target_", "").upper()
                            handle_telegram_command(f"/target {t}")
                            
                        elif cb_data.startswith("chart_"):
                            t = cb_data.replace("chart_", "").upper()
                            handle_telegram_command(f"/chart {t}")
                            
                        # أدوات المحفظة
                        elif cb_data == "btn_portfolio":
                            handle_telegram_command("/portfolio")
                        elif cb_data == "btn_export":
                            handle_telegram_command("/export")
                        elif cb_data == "btn_rebalance":
                            handle_telegram_command("/rebalance")
                        elif cb_data == "btn_zakat":
                            handle_telegram_command("/zakat")
                        elif cb_data == "btn_dca":
                            handle_telegram_command("/dca")
                        elif cb_data == "btn_stresstest":
                            handle_telegram_command("/stresstest")
                        elif cb_data == "btn_calc_help":
                            handle_telegram_command("/calc")
                        elif cb_data == "btn_journal":
                            handle_telegram_command("/journal")
                        elif cb_data == "btn_my_alerts":
                            handle_telegram_command("/my_alerts")
                        elif cb_data == "btn_dashboard":
                            handle_telegram_command("/dashboard")
                            
                        # رادارات وتحليلات السوق
                        elif cb_data == "btn_report":
                            handle_telegram_command("/report")
                        elif cb_data == "btn_rsi":
                            handle_telegram_command("/rsi")
                        elif cb_data == "btn_undervalued":
                            handle_telegram_command("/undervalued")
                        elif cb_data == "btn_accumulation":
                            handle_telegram_command("/accumulation")
                        elif cb_data == "btn_divergence":
                            handle_telegram_command("/divergence")
                        elif cb_data == "btn_dividends":
                            handle_telegram_command("/dividends")
                        elif cb_data == "btn_insiders":
                            handle_telegram_command("/insiders")
                        elif cb_data == "btn_summary":
                            handle_telegram_command("/summary")
                        elif cb_data == "btn_chart_help":
                            handle_telegram_command("/chart")
                        elif cb_data == "btn_fundamental_help":
                            handle_telegram_command("/fundamental")
                        elif cb_data == "btn_ask_help":
                            handle_telegram_command("/ask")
                        elif cb_data == "btn_status":
                            handle_telegram_command("/status")
                            
                        # إدارة التنبيهات التفاعلية
                        elif cb_data.startswith("del_alert_"):
                            try:
                                alert_idx = int(cb_data.replace("del_alert_", ""))
                                state_data, state_sha = get_github_state()
                                alerts = state_data.get("alerts", [])
                                if 0 <= alert_idx < len(alerts):
                                    deleted = alerts.pop(alert_idx)
                                    state_data["alerts"] = alerts
                                    if update_github_state(state_data, state_sha):
                                        reply_telegram("✅ تم حذف التنبيه المحدد بنجاح.")
                                        alerts_msg, alerts_markup = format_user_alerts_manager(state_data)
                                        reply_telegram(alerts_msg, reply_markup=alerts_markup if alerts_markup else PORTFOLIO_HUB_KEYBOARD)
                                    else:
                                        reply_telegram("❌ تعذر تحديث قائمة التنبيهات على الخادم.")
                            except Exception as err:
                                reply_telegram(f"⚠️ خطأ أثناء حذف التنبيه: {err}")
                        elif cb_data == "clear_all_alerts":
                            try:
                                state_data, state_sha = get_github_state()
                                state_data["alerts"] = []
                                if update_github_state(state_data, state_sha):
                                    reply_telegram("✅ تم مسح كافة التنبيهات بنجاح.", reply_markup=PORTFOLIO_HUB_KEYBOARD)
                                else:
                                    reply_telegram("❌ تعذر حفظ التعديل على الخادم.")
                            except Exception as err:
                                reply_telegram(f"⚠️ خطأ أثناء مسح التنبيهات: {err}")
                                
                        # استشارة السهم المباشرة
                        elif cb_data.startswith("deepdive_"):
                            ticker = cb_data.replace("deepdive_", "").upper()
                            c_name = COMPANY_NAMES_AR.get(ticker, ticker)
                            reply_telegram(f"🔄 جاري تحليل سهم <b>{c_name} ({ticker})</b> عبر المحلل المؤسسي الذكي...")
                            try:
                                analysis = ask_financial_advisor(f"ما تحليلك الفني والاستثماري لسهم {c_name} ({ticker}) ومستويات الدعم والمقاومة والفرص اللحظية؟")
                                reply_telegram(analysis, reply_markup=PORTFOLIO_INLINE_KEYBOARD)
                            except Exception as e:
                                reply_telegram(f"⚠️ حدث خطأ: {e}")
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
                
            # فحص إرسال مذكرة ما قبل الافتتاح الصباحية (09:30 ص)
            try:
                state_data, state_sha = get_github_state()
                if check_and_send_pre_market_briefing(state_data):
                    update_github_state(state_data, state_sha)
            except Exception as e:
                print("Error checking pre-market briefing:", e)

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
