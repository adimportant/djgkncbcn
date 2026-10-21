# =========================================================
# Aadi SMS HUB BOT — FINAL (Copy fixed + All Features)
# =========================================================
import asyncio
import json
import io
import logging
import os
import re
import time
from datetime import datetime
import aiohttp

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile,
)
from dotenv import load_dotenv
import pyotp

try:
    # Current aiogram names this Telegram button type CopyTextButton.
    from aiogram.types import CopyTextButton as CopyText
    HAS_COPY = True
except ImportError:
    try:
        # Compatibility with versions that expose the older name.
        from aiogram.types import CopyText
        HAS_COPY = True
    except ImportError:
        HAS_COPY = False
        CopyText = None

load_dotenv()

# =========================================================
# CONFIG
# =========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
SMS_API_KEY = os.getenv("SMS_API_KEY", "")
API_BASE = "https://api.2oo9.cloud/MXS47FLFX0U/tness/@public/api"

ADMIN_URL = os.getenv("ADMIN_URL", "https://t.me/admin")
OWNER_URL = os.getenv("OWNER_URL", "https://t.me/owner")
OTP_GROUP_URL = os.getenv("OTP_GROUP_URL", "https://t.me/otpgroup")
OTP_GROUP_ID = os.getenv("OTP_GROUP_ID", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "YourBot")
REFER_RATE = float(os.getenv("REFER_RATE", "0.05"))
REFER_REQUIRED_OTPS = int(os.getenv("REFER_REQUIRED_OTPS", "20"))

def _parse_admin_ids():
    raw = os.getenv("ADMIN_IDS", "") or os.getenv("OWNER_ID", "")
    ids = set()
    for part in raw.replace(" ", "").split(","):
        if part.isdigit():
            ids.add(int(part))
    return ids

ADMIN_IDS = _parse_admin_ids()
MAX_BATCH_SIZE = 1

FORCE_CHANNELS = [
    {"id": os.getenv("FORCE_CHANNEL_1_ID", ""),
     "url": os.getenv("FORCE_CHANNEL_1_URL", ""),
     "name": os.getenv("FORCE_CHANNEL_1_NAME", "Channel 1")},
    {"id": os.getenv("FORCE_CHANNEL_2_ID", ""),
     "url": os.getenv("FORCE_CHANNEL_2_URL", ""),
     "name": os.getenv("FORCE_CHANNEL_2_NAME", "Channel 2")},
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# =========================================================
# STORAGE
# =========================================================
active_orders = []
ALL_USERS = set()
RECENT_HITS = []
SENT_OTP_IDS = set()
USERS_DB = {}
SERVICE_HITS = {}
LAST_NUMBER_MSG = {}   # ★ uid -> (chat_id, message_id) - last numbers display

BTN_GET = "📱 GET NUMBERS"
BTN_SEARCH = "🔍 SEARCH NUMBER"
BTN_PROXY = "🌐 PROXY"
BTN_REFER = "🎁 REFER"
BTN_2FA = "🔐 2FA"
BTN_ADMIN = "👑 ADMIN PANEL"
MENU_BUTTONS = {BTN_GET, BTN_SEARCH, BTN_PROXY, BTN_REFER, BTN_2FA, BTN_ADMIN}

class UserFlow(StatesGroup):
    waiting_search_range = State()
    waiting_2fa_key = State()

class AdminFlow(StatesGroup):
    waiting_broadcast = State()
    waiting_limit = State()
    waiting_import_file = State()
    waiting_add_country_service = State()
    waiting_add_country_code = State()
    waiting_add_country_range = State()
    waiting_del_country_service = State()
    waiting_del_country_code = State()

# =========================================================
# SERVICES / COUNTRIES
# =========================================================
SERVICES = {
    "fb_forgot": {"name": "FB FORGET", "label": "FB Forgot",
                  "sid_match": ["facebook", "fb", "fb_forgot", "fb forget"]},
    "instagram": {"name": "INSTAGRAM", "label": "Instagram",
                  "sid_match": ["instagram", "ig"]},
    "whatsapp":  {"name": "WHATSAPP", "label": "WhatsApp",
                  "sid_match": ["whatsapp", "wa"]},
    "telegram":  {"name": "TELEGRAM", "label": "Telegram",
                  "sid_match": ["telegram", "tg"]},
}

COUNTRY_INFO = {
    "GN": {"name": "Guinea", "flag": "🇬🇳"},
    "CM": {"name": "Cameroon", "flag": "🇨🇲"},
    "MG": {"name": "Madagascar", "flag": "🇲🇬"},
    "TG": {"name": "Togo", "flag": "🇹🇬"},
    "AM": {"name": "Armenia", "flag": "🇦🇲"},
}

COUNTRY_CODES = {
    "224": "GN", "237": "CM", "261": "MG", "228": "TG", "374": "AM",
}

SERVICE_COUNTRY_RANGES = {
    "fb_forgot": {
        "GN": {"prefix": "224655", "rid": "224655"},
        "CM": {"prefix": "237626", "rid": "237626"},
        "MG": {"prefix": "261347", "rid": "261347"},
    },
    "instagram": {
        "MG": {"prefix": "261385", "rid": "261385"},
        "TG": {"prefix": "228983", "rid": "228983"},
        "AM": {"prefix": "374559", "rid": "374559"},
    },
    "whatsapp": {
        "GN": {"prefix": "224655", "rid": "224655"},
        "CM": {"prefix": "237626", "rid": "237626"},
        "MG": {"prefix": "261347", "rid": "261347"},
    },
    "telegram": {
        "GN": {"prefix": "224655", "rid": "224655"},
        "CM": {"prefix": "237626", "rid": "237626"},
        "MG": {"prefix": "261347", "rid": "261347"},
    },
}

RANGE_TO_COUNTRY = {}

def rebuild_range_map():
    RANGE_TO_COUNTRY.clear()
    for _svc, _cts in SERVICE_COUNTRY_RANGES.items():
        for _code, _info in _cts.items():
            RANGE_TO_COUNTRY[_info["prefix"]] = _code

rebuild_range_map()

WELCOME_TEXT = """╔═══════════╗
📊 ᴀᴀDɪ ɴᴜᴍʙᴇʀ ʙᴏᴛ
╚═══════════╝
🚀 ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ɴᴜᴍʙᴇʀ & ᴏᴛᴘ ꜱᴇʀᴠɪᴄᴇ
━━━━━━━━━━━━
✅ ᴄʜᴏᴏꜱᴇ ᴀɴ ᴏᴘᴛɪᴏɴ ʙᴇʟᴏᴡ
ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ ᴜꜱɪɴɢ ᴛʜᴇ ʙᴏᴛ.
━━━━━━━━━━━━
💎 ᴘʀᴇᴍɪᴜᴍ ᴏᴛᴘ ꜱᴇʀᴠɪᴄᴇ"""

SERVICE_MENU_TEXT = """📍 <b>Select a service:</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

# =========================================================
# HELPERS
# =========================================================
SMALL_CAPS_MAP = {
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ꜰ', 'g': 'ɢ', 'h': 'ʜ',
    'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ',
    'q': 'ǫ', 'r': 'ʀ', 's': 'ꜱ', 't': 'ᴛ', 'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x',
    'y': 'ʏ', 'z': 'ᴢ',
}

def small_caps(text):
    return "".join(SMALL_CAPS_MAP.get(c.lower(), c) for c in text)

def extract_otp(msg):
    if not msg:
        return None
    clean = re.sub(r"[\s\-\.\:\*]", "", msg)
    m = re.search(r"(\d{4,8})", clean)
    if m:
        return m.group(1)
    m = re.search(r"(\d{4,8})", msg)
    return m.group(1) if m else None

def mask_number(number):
    n = str(number).lstrip("+").replace(" ", "").replace("-", "")
    if len(n) <= 8:
        if len(n) <= 4:
            return n
        return n[:2] + "*" * (len(n) - 4) + n[-2:]
    return n[:4] + "*" * (len(n) - 8) + n[-4:]

def get_country_from_range(range_str):
    if not range_str:
        return None
    clean = str(range_str).replace("XXX", "").replace("xxx", "").strip()
    if not clean:
        return None
    for prefix, code in RANGE_TO_COUNTRY.items():
        if clean.startswith(prefix) or prefix.startswith(clean):
            return code
    return None

def detect_country_from_number(number):
    if not number:
        return None
    n = str(number).lstrip("+").replace(" ", "").replace("-", "")
    for prefix, code in RANGE_TO_COUNTRY.items():
        if n.startswith(prefix):
            return code
    for code_len in (3, 2):
        if len(n) >= code_len:
            prefix = n[:code_len]
            if prefix in COUNTRY_CODES:
                return COUNTRY_CODES[prefix]
    return None

def detect_service_from_otp(msg, number=""):
    msg_l = (msg or "").lower()
    if "facebook" in msg_l or "fb-" in msg_l or "fb code" in msg_l or "fb verification" in msg_l:
        return "fb_forgot"
    if "instagram" in msg_l or "ig code" in msg_l or "ig-" in msg_l:
        return "instagram"
    if "whatsapp" in msg_l or "wa code" in msg_l or "wa-" in msg_l:
        return "whatsapp"
    if "telegram" in msg_l:
        return "telegram"
    n = str(number).lstrip("+")
    for svc_key, cts in SERVICE_COUNTRY_RANGES.items():
        for cty_code, info in cts.items():
            if n.startswith(info["prefix"]):
                return svc_key
    return None

def get_service_from_sid(sid):
    if not sid:
        return None
    sid_l = sid.lower()
    for key, svc in SERVICES.items():
        if sid_l in [s.lower() for s in svc.get("sid_match", [])]:
            return key
    return None

def ensure_user(uid):
    if uid not in USERS_DB:
        USERS_DB[uid] = {"referred_by": None, "referred_users": [],
                         "otp_count": 0, "ref_notified": False}
    return USERS_DB[uid]

def get_refer_stats(uid):
    user = USERS_DB.get(uid, {"referred_users": []})
    referred = user.get("referred_users", [])
    completed = pending = 0
    for rid in referred:
        rc = USERS_DB.get(rid, {}).get("otp_count", 0)
        if rc >= REFER_REQUIRED_OTPS:
            completed += 1
        else:
            pending += 1
    return {"total": len(referred), "completed": completed, "pending": pending}

def get_top_referrers(limit=3):
    scores = [(uid, len(u.get("referred_users", []))) for uid, u in USERS_DB.items()]
    scores = [s for s in scores if s[1] > 0]
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:limit]

# ★ PERFECT COPY BUTTON
def make_btn(text, callback_data=None, url=None, copy_value=None, style=None):
    if url is not None:
        base = {"text": text, "url": url}
        if style:
            try:
                return InlineKeyboardButton(style=style, **base)
            except Exception:
                pass
        return InlineKeyboardButton(**base)
    
    if copy_value is not None:
        if HAS_COPY:
            try:
                return InlineKeyboardButton(text=text, copy_text=CopyText(text=str(copy_value)))
            except Exception as e:
                logging.warning(f"[make_btn] copy_text fail: {e}")
                return InlineKeyboardButton(text=text, callback_data=f"shownum|{copy_value}")
        else:
            return InlineKeyboardButton(text=text, callback_data=f"shownum|{copy_value}")
            
    safe_cb = callback_data or "noop"
    base = {"text": text, "callback_data": safe_cb}
    if style:
        try:
            return InlineKeyboardButton(style=style, **base)
        except Exception:
            pass
    return InlineKeyboardButton(**base)

async def safe_edit(message, text, kb=None):
    try:
        await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        return
    except Exception as e:
        if "not modified" in str(e).lower():
            return
    try:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
        return
    except Exception as e:
        logging.error(f"safe_edit (answer) fail: {e}")
    try:
        await message.answer(text, parse_mode="HTML")
    except Exception:
        pass

def serialize_state():
    users_serial = {str(uid): v for uid, v in USERS_DB.items()}
    hits_serial = {f"{svc}|{cty}": count for (svc, cty), count in SERVICE_HITS.items()}
    return {
        "version": 1,
        "exported_at": datetime.utcnow().isoformat(),
        "users_db": users_serial,
        "service_hits": hits_serial,
        "all_users": sorted(list(ALL_USERS)),
        "active_orders": active_orders,
        "max_batch_size": MAX_BATCH_SIZE,
        "service_country_ranges": SERVICE_COUNTRY_RANGES,
        "country_info": COUNTRY_INFO,
    }

def deserialize_state(data):
    global USERS_DB, SERVICE_HITS, ALL_USERS, active_orders, MAX_BATCH_SIZE, SERVICE_COUNTRY_RANGES, COUNTRY_INFO
    new_users = {}
    for k, v in data.get("users_db", {}).items():
        try:
            uid = int(k)
            if isinstance(v, dict):
                ru = v.get("referred_users", [])
                v["referred_users"] = [int(x) for x in ru if str(x).lstrip("-").isdigit()]
            new_users[uid] = v
        except (ValueError, TypeError):
            continue
    USERS_DB = new_users
    
    new_hits = {}
    for k, v in data.get("service_hits", {}).items():
        if "|" in k:
            svc, cty = k.split("|", 1)
            try:
                new_hits[(svc, cty)] = int(v)
            except (ValueError, TypeError):
                pass
    SERVICE_HITS = new_hits
    
    new_all = set()
    for x in data.get("all_users", []):
        try:
            new_all.add(int(x))
        except (ValueError, TypeError):
            pass
    ALL_USERS = new_all
    active_orders = data.get("active_orders", []) or []
    
    try:
        MAX_BATCH_SIZE = int(data.get("max_batch_size", 1))
    except (ValueError, TypeError):
        MAX_BATCH_SIZE = 1
    
    if isinstance(data.get("service_country_ranges"), dict):
        SERVICE_COUNTRY_RANGES.clear()
        SERVICE_COUNTRY_RANGES.update(data["service_country_ranges"])
    
    if isinstance(data.get("country_info"), dict):
        COUNTRY_INFO.clear()
        COUNTRY_INFO.update(data["country_info"])
    
    rebuild_range_map()

def save_data():
    try:
        data = serialize_state()
        with open("bot_data.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Save data fail: {e}")

def load_data():
    if os.path.exists("bot_data.json"):
        try:
            with open("bot_data.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            deserialize_state(data)
            logging.info("✅ Data loaded from bot_data.json")
        except Exception as e:
            logging.error(f"Load data fail: {e}")

# =========================================================
# KEYBOARDS
# =========================================================
def main_menu_reply_kb(uid=None):
    rows = [
        [KeyboardButton(text=BTN_GET), KeyboardButton(text=BTN_SEARCH)],
        [KeyboardButton(text=BTN_PROXY), KeyboardButton(text=BTN_REFER)],
        [KeyboardButton(text=BTN_2FA)],
    ]
    if uid and is_admin(uid):
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)

def force_join_kb(not_joined):
    rows = []
    for ch in not_joined:
        rows.append([make_btn(f"📢 Join {ch['name']}", url=ch["url"], style="primary")])
    rows.append([make_btn("✅ Verify / Joined", callback_data="verify_join", style="success")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def service_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [make_btn("FB FORGET", callback_data="svc|fb_forgot", style="success"),
         make_btn("INSTAGRAM", callback_data="svc|instagram", style="primary")],
        [make_btn("WHATSAPP", callback_data="svc|whatsapp", style="success")],
        [make_btn("❌ CLOSE", callback_data="main_menu", style="danger")],
    ])

def country_menu_kb(service_key, countries):
    rows = []
    for i in range(0, len(countries), 2):
        row = []
        c1 = countries[i]
        row.append(make_btn(f"{c1['code']}•{c1['hits']}",
                            callback_data=f"cty|{service_key}|{c1['code']}", style="success" if i==0 else "primary"))
        if i + 1 < len(countries):
            c2 = countries[i+1]
            row.append(make_btn(f"{c2['code']}•{c2['hits']}",
                                callback_data=f"cty|{service_key}|{c2['code']}", style="primary"))
        rows.append(row)
    
    rows.append([make_btn("❌ CANCEL", callback_data="get_numbers", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def batch_display_kb(service_key, country_code, numbers, default_flag):
    rows = []
    for n in numbers:
        clean = str(n["number"]).lstrip("+")
        per_cty = n.get("country") or country_code
        flag = COUNTRY_INFO.get(per_cty, {}).get("flag", default_flag) if per_cty else default_flag
        rows.append([make_btn(f"{flag} 📋 {n['number']}", copy_value=clean, style="success")])
            
    rows.append([
        make_btn("🔄 CHANGE NUMBER", callback_data=f"change|{service_key}|{country_code}", style="danger"),
        make_btn("🛡️ OTP GROUP", url=OTP_GROUP_URL, style="primary"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def search_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [make_btn("❌ CANCEL", callback_data="main_menu", style="danger")],
    ])

def batch_search_kb(rid, numbers_meta):
    rows = []
    for n in numbers_meta:
        clean = str(n["number"]).lstrip("+")
        cty = n.get("country", "")
        flag = COUNTRY_INFO.get(cty, {}).get("flag", "🌍") if cty else "🌍"
        rows.append([make_btn(f"{flag} 📋 {n['number']}", copy_value=clean, style="success")])
            
    rows.append([
        make_btn("🔄 CHANGE NUMBER", callback_data=f"chg_search|{rid}", style="danger"),
        make_btn("🛡️ OTP GROUP", url=OTP_GROUP_URL, style="primary"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def proxy_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [make_btn("👤 ADMIN", url=ADMIN_URL, style="primary")],
        [make_btn("❌ CANCEL", callback_data="main_menu", style="danger")],
    ])

def refer_kb(ref_link):
    return InlineKeyboardMarkup(inline_keyboard=[
        [make_btn("📋 COPY LINK", copy_value=ref_link, callback_data=f"shownum|{ref_link}", style="success")],
        [make_btn("❌ CANCEL", callback_data="main_menu", style="danger")],
    ])

def twofa_intro_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [make_btn("🔑 GENERATE 2FA CODE", callback_data="gen_2fa", style="success")],
        [make_btn("❌ CANCEL", callback_data="main_menu", style="danger")],
    ])

def twofa_enter_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [make_btn("❌ CANCEL", callback_data="main_menu", style="danger")],
    ])

def twofa_result_kb(code):
    return InlineKeyboardMarkup(inline_keyboard=[
        [make_btn(f"📋 {code}", copy_value=code, callback_data=f"shownum|{code}", style="success")],
        [make_btn("🔄 NEW CODE", callback_data="gen_2fa", style="primary")],
        [make_btn("🏠 Main Menu", callback_data="main_menu", style="danger")],
    ])

def admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [make_btn("📢 Broadcast Message", callback_data="admin_broadcast", style="success")],
        [make_btn(f"⚙️ Set Batch Size (Current: {MAX_BATCH_SIZE})", callback_data="admin_limit", style="primary")],
        [make_btn("🌍 Add Country", callback_data="admin_add_country", style="success"),
         make_btn("🗑️ Delete Country", callback_data="admin_del_country", style="danger")],
        [make_btn("📊 Bot Stats", callback_data="admin_stats", style="primary")],
        [make_btn("📤 Export Database", callback_data="admin_export", style="success"),
         make_btn("📥 Import Database", callback_data="admin_import", style="primary")],
        [make_btn("❌ Close", callback_data="main_menu", style="danger")],
    ])

def admin_cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [make_btn("❌ Cancel", callback_data="admin_panel", style="danger")],
    ])

# =========================================================
# FORCE JOIN
# =========================================================
async def get_not_joined(user_id):
    not_joined = []
    for ch in FORCE_CHANNELS:
        if not ch["id"]:
            continue
        try:
            member = await bot.get_chat_member(chat_id=ch["id"], user_id=user_id)
            if member.status in ("left", "kicked"):
                not_joined.append(ch)
        except Exception as e:
            logging.warning(f"Force join check failed {ch['id']}: {e}")
    return not_joined

# =========================================================
# API
# =========================================================
async def api_fetch_console():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{API_BASE}/console", timeout=10) as r:
                data = await r.json()
                if data.get("meta", {}).get("code") == 200:
                    return {"status": "success", "hits": data.get("data", {}).get("hits", [])}
                return {"status": "error", "message": data.get("message", "API error")}
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def api_fetch_success_otp():
    try:
        headers = {"mauthapi": SMS_API_KEY}
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{API_BASE}/success-otp", headers=headers, timeout=10) as r:
                data = await r.json()
                if data.get("meta", {}).get("code") == 200:
                    return {"status": "success", "otps": data.get("data", {}).get("otps", [])}
                return {"status": "error", "message": data.get("message", "API error")}
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def api_get_number(service, country="", rid=None, range_prefix=None):
    url = f"{API_BASE}/getnum"
    headers = {"mauthapi": SMS_API_KEY, "Content-Type": "application/json"}
    rids_to_try = []
    if rid:
        rids_to_try.append(str(rid))
    if range_prefix and range_prefix not in rids_to_try:
        rids_to_try.append(range_prefix)
    if range_prefix and range_prefix[:5] not in rids_to_try:
        rids_to_try.append(range_prefix[:5])
    if not rids_to_try:
        return {"status": "error", "message": "No rid provided"}
    last_error = "Unknown error"
    async with aiohttp.ClientSession() as s:
        for rid_try in rids_to_try:
            try:
                async with s.post(url, json={"rid": rid_try}, headers=headers, timeout=10) as r:
                    data = await r.json()
                    meta = data.get("meta") or {}
                    code = meta.get("code")
                    status = meta.get("status")
                    if code == 200 or status == "ok":
                        num = data.get("data") or {}
                        full = num.get("full_number") or num.get("no_plus_number")
                        if full:
                            return {
                                "status": "success", "number": full,
                                "no_plus": num.get("no_plus_number") or str(full).lstrip("+"),
                                "rid_used": rid_try, "order_id": str(rid_try),
                            }
                        last_error = "No number"
                        continue
                    if code == 2946 or status == "not_found":
                        last_error = "Out of stock"
                        continue
                    last_error = f"API {code}: {data.get('message', '')}"
            except Exception as e:
                last_error = str(e)
    return {"status": "error", "message": last_error}

async def fetch_batch(uid, service, country, rid, range_prefix):
    results = []
    for i in range(MAX_BATCH_SIZE):
        try:
            res = await api_get_number(service=service, country=country, rid=rid, range_prefix=range_prefix)
        except Exception as e:
            logging.error(f"fetch_batch #{i} error: {e}")
            break
        if res.get("status") == "success":
            num = res["number"]
            detected_cty = country or detect_country_from_number(num) or ""
            res["detected_country"] = detected_cty
            entry = {
                "uid": uid,
                "order_id": res.get("order_id"),
                "number": num,
                "no_plus": res.get("no_plus"),
                "service": service,
                "country": detected_cty,
                "rid": res.get("rid_used") or rid,
            }
            active_orders.append(entry)
            results.append(res)
        else:
            msg = (res.get("message") or "").lower()
            if "stock" in msg:
                break
        if i < MAX_BATCH_SIZE - 1:
            await asyncio.sleep(0.25)
    return results

def remove_user_orders(uid, service=None, country=None):
    global active_orders
    active_orders[:] = [
        o for o in active_orders
        if not (
            o["uid"] == uid
            and (service is None or o.get("service") == service)
            and (country is None or o.get("country") == country)
        )
    ]

# =========================================================
# OTP MESSAGE  (group mask: ✯𝘼𝘼𝘿𝙄✯)
# =========================================================
def build_otp_message(order, otp_code, mask=False):
    country_code = order.get("country") or get_country_from_range(order.get("rid", "")) or ""
    cty_info = COUNTRY_INFO.get(country_code, {})
    flag = cty_info.get("flag", "🌍")
    cc_small = small_caps(country_code) if country_code else "ꜱᴇᴀʀᴄʜ"

    svc_key = order.get("service", "")
    if svc_key and svc_key in SERVICES:
        svc_label = SERVICES[svc_key]["label"]
    elif svc_key == "search":
        svc_label = "Search"
    else:
        svc_label = "OTP"
    svc_small = small_caps(svc_label)

    raw_number = str(order.get("number", "")).strip()
    no_plus = raw_number.lstrip("+")

    if mask:
        # Group format: 374✯𝘼𝘼𝘿𝙄✯696
        if len(no_plus) >= 6:
            display_num = f"{no_plus[:3]}✯𝘼𝘼𝘿𝙄✯{no_plus[-3:]}"
        else:
            display_num = no_plus
    else:
        # User format: full number with +
        display_num = raw_number if raw_number.startswith("+") else f"+{no_plus}"

    text = (
        f"🔥 <b>100% OTP GUARANTEE</b>\n"
        f"{flag} {cc_small} | 📱 {display_num} | 🗣 {small_caps('English')}\n"
        f"🎯 {svc_small}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    if not HAS_COPY and not mask:
        text += f"\n\nOTP: <code>{otp_code}</code>\n<i>👆 Long-press to copy</i>"

    return text

def build_otp_kb(otp_code):
    kb_rows = [
        [make_btn(f"📋 {otp_code}", copy_value=otp_code, style="success")],
        [
            make_btn("👤 OWNER", url=OWNER_URL, style="primary"),
            make_btn("👥 OTP GROUP", url=OTP_GROUP_URL, style="success"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

# =========================================================
# BACKGROUND
# =========================================================
async def poll_console_hits():
    while True:
        await asyncio.sleep(60)
        try:
            res = await api_fetch_console()
            if res.get("status") == "success":
                now = time.time()
                for hit in res["hits"]:
                    key = (hit.get("range"), hit.get("message"), hit.get("time"))
                    if not any(h.get("_key") == key for h in RECENT_HITS):
                        hit["_key"] = key
                        hit["_fetched_at"] = now
                        RECENT_HITS.append(hit)
                cutoff = now - 3600
                RECENT_HITS[:] = [h for h in RECENT_HITS if h["_fetched_at"] > cutoff]
        except Exception as e:
            logging.warning(f"[console] {e}")

async def poll_otp_for_orders():
    while True:
        await asyncio.sleep(2)
        try:
            res = await api_fetch_success_otp()
            if res.get("status") != "success":
                continue
            for otp in res.get("otps", []):
                otp_id = otp.get("otp_id")
                if not otp_id or otp_id in SENT_OTP_IDS:
                    continue
                number = otp.get("number", "")
                message = otp.get("message", "")
                otp_code = extract_otp(message)
                if not otp_code:
                    SENT_OTP_IDS.add(otp_id)
                    continue

                matched_entry = None
                num_tail = number[-10:] if len(number) >= 10 else number
                for ord_entry in list(active_orders):
                    order_no = (ord_entry.get("no_plus") or "").strip().lstrip("+")
                    if not order_no:
                        order_no = ord_entry.get("number", "").lstrip("+").strip()
                    if not order_no:
                        continue
                    order_tail = order_no[-10:] if len(order_no) >= 10 else order_no
                    if num_tail == order_tail or number.endswith(order_no) or order_no.endswith(number):
                        matched_entry = ord_entry
                        break

                if not matched_entry:
                    logging.info(f"[OTP-POLL] Unmatched {otp_code} ({number})")
                    SENT_OTP_IDS.add(otp_id)
                    if OTP_GROUP_ID:
                        try:
                            fake = {"number": f"+{number}",
                                    "country": detect_country_from_number(number) or ""}
                            await bot.send_message(
                                OTP_GROUP_ID,
                                build_otp_message(fake, otp_code, mask=True),
                                reply_markup=build_otp_kb(otp_code),
                                parse_mode="HTML",
                            )
                        except Exception as e:
                            logging.error(f"[OTP-POLL] Group fail: {e}")
                    continue

                matched_uid = matched_entry["uid"]
                svc_key = matched_entry.get("service", "")
                cty_key = matched_entry.get("country", "")

                if svc_key == "search" or not svc_key:
                    detected = detect_service_from_otp(message, matched_entry["number"])
                    if detected:
                        svc_key = detected
                        matched_entry["service"] = detected

                if not cty_key:
                    cty_key = detect_country_from_number(matched_entry["number"]) or ""
                    matched_entry["country"] = cty_key

                if svc_key and cty_key and svc_key != "search":
                    SERVICE_HITS[(svc_key, cty_key)] = SERVICE_HITS.get((svc_key, cty_key), 0) + 1
                    logging.info(f"[HITS] {svc_key}/{cty_key} → {SERVICE_HITS[(svc_key, cty_key)]}")

                text_user = build_otp_message(matched_entry, otp_code, mask=False)
                kb = build_otp_kb(otp_code)
                try:
                    await bot.send_message(matched_uid, text_user, reply_markup=kb, parse_mode="HTML")
                    logging.info(f"[OTP-POLL] ✅ User {matched_uid}: {otp_code}")
                except Exception as e:
                    logging.error(f"[OTP-POLL] User fail: {e}")

                if OTP_GROUP_ID:
                    try:
                        text_group = build_otp_message(matched_entry, otp_code, mask=True)
                        await bot.send_message(OTP_GROUP_ID, text_group, reply_markup=kb, parse_mode="HTML")
                        logging.info(f"[OTP-POLL] ✅ Group (masked): {otp_code}")
                    except Exception as e:
                        logging.error(f"[OTP-POLL] Group fail: {e}")

                SENT_OTP_IDS.add(otp_id)
                try:
                    active_orders.remove(matched_entry)
                except ValueError:
                    pass

                if matched_uid in USERS_DB:
                    USERS_DB[matched_uid]["otp_count"] = USERS_DB[matched_uid].get("otp_count", 0) + 1
                    referrer_id = USERS_DB[matched_uid].get("referred_by")
                    if (referrer_id
                        and USERS_DB[matched_uid]["otp_count"] >= REFER_REQUIRED_OTPS
                        and not USERS_DB[matched_uid].get("ref_notified")):
                        USERS_DB[matched_uid]["ref_notified"] = True
                        try:
                            await bot.send_message(
                                referrer_id,
                                f"🎉 <b>Referral Completed!</b>\n💰 {REFER_RATE} USDT earned.",
                                parse_mode="HTML")
                        except Exception:
                            pass
            if len(SENT_OTP_IDS) > 5000:
                SENT_OTP_IDS.clear()
        except Exception as e:
            logging.error(f"[OTP-POLL] Fatal: {e}", exc_info=True)

async def broadcast_stats_2h():
    while True:
        await asyncio.sleep(7200)
        try:
            service_groups = {}
            for (svc, cty), count in SERVICE_HITS.items():
                if count > 0 and svc != "search":
                    service_groups.setdefault(svc, []).append((cty, count))

            if not service_groups:
                continue

            blocks = [
                f"📊 {small_caps('Hourly Performance Analysis')}",
                "━━━━━━━━━━━━━━━━━━━━",
            ]

            service_emojis = {
                "fb_forgot": "📱",
                "instagram": "📸",
                "whatsapp": "💬",
                "telegram": "✈️",
            }

            for svc_key in ["fb_forgot", "instagram", "whatsapp", "telegram"]:
                if svc_key not in service_groups:
                    continue
                svc = SERVICES.get(svc_key, {})
                label = svc.get("label", svc_key)
                emoji = service_emojis.get(svc_key, "📱")
                block = [f"{emoji} {small_caps(label)} 🔥"]
                for cty, count in sorted(service_groups[svc_key], key=lambda x: -x[1]):
                    cty_info = COUNTRY_INFO.get(cty, {})
                    flag = cty_info.get("flag", "🌍")
                    name = cty_info.get("name", cty)
                    fire = " 🔥" if count >= 50 else ""
                    block.append(f"{flag} {small_caps(name)} ({small_caps(cty)}) • {count} {small_caps('hits')}{fire}")
                blocks.append("\n".join(block))

            text = "\n\n".join(blocks)

            sent = 0
            for uid in list(ALL_USERS):
                try:
                    await bot.send_message(uid, text, parse_mode="HTML")
                    sent += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    pass
            logging.info(f"[broadcast_2h] Sent to {sent}/{len(ALL_USERS)}")
        except Exception as e:
            logging.warning(f"[broadcast_2h] {e}")

# =========================================================
# /start & /menu
# =========================================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject, state: FSMContext):
    await state.clear()
    ALL_USERS.add(message.from_user.id)
    uid = message.from_user.id
    ensure_user(uid)

    if command.args and command.args.startswith("ref_"):
        try:
            referrer_id = int(command.args[4:])
        except ValueError:
            referrer_id = None
        if referrer_id and referrer_id != uid and USERS_DB[uid].get("referred_by") is None:
            USERS_DB[uid]["referred_by"] = referrer_id
            ensure_user(referrer_id)
            if uid not in USERS_DB[referrer_id]["referred_users"]:
                USERS_DB[referrer_id]["referred_users"].append(uid)
                try:
                    await bot.send_message(referrer_id, "🎉 <b>New Referral!</b>", parse_mode="HTML")
                except Exception:
                    pass

    not_joined = await get_not_joined(uid)
    if not_joined:
        await message.answer(
            "⚠️ <b>Force Join Required</b>\n\n"
            "Bot ka use karne ke liye pehle neeche diye gaye <b>channels join</b> karein.\n"
            "Uske baad <b>✅ Verify / Joined</b> button dabayein.",
            reply_markup=force_join_kb(not_joined),
            parse_mode="HTML",
        )
        return
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_reply_kb(uid))

@dp.message(F.text == "/menu")
async def cmd_menu(message: types.Message, state: FSMContext):
    await state.clear()
    ALL_USERS.add(message.from_user.id)
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_reply_kb(message.from_user.id))

# =========================================================
# REPLY KEYBOARD HANDLERS
# =========================================================
@dp.message(F.text == BTN_GET)
async def on_btn_get_numbers(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    # ★ Delete previous numbers message if exists
    if uid in LAST_NUMBER_MSG:
        chat_id, msg_id = LAST_NUMBER_MSG.pop(uid)
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            pass
    if await get_not_joined(uid):
        await message.answer("Pehle force join complete karein!", reply_markup=main_menu_reply_kb(uid))
        return
    await message.answer(SERVICE_MENU_TEXT, reply_markup=service_menu_kb(), parse_mode="HTML")

@dp.message(F.text == BTN_SEARCH)
async def on_btn_search(message: types.Message, state: FSMContext):
    await state.set_state(UserFlow.waiting_search_range)
    text = ("🔎 <b>SEARCH NUMBER</b>\n\n"
            "Send a range/prefix with at least 4 digits.\n"
            "X / x is optional. Examples: <code>2613</code>, <code>26134xxx</code>, <code>26134XXX</code>.")
    await message.answer(text, reply_markup=search_kb(), parse_mode="HTML")

@dp.message(F.text == BTN_PROXY)
async def on_btn_proxy(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🌐 <b>PROXY</b>\n\n<b>CONTACT ADMIN TO GET PROXY</b>",
        reply_markup=proxy_kb(), parse_mode="HTML",
    )

@dp.message(F.text == BTN_REFER)
async def on_btn_refer(message: types.Message, state: FSMContext):
    global BOT_USERNAME
    await state.clear()
    uid = message.from_user.id
    ensure_user(uid)
    if not BOT_USERNAME or BOT_USERNAME == "YourBot":
        try:
            me = await bot.get_me()
            BOT_USERNAME = me.username or BOT_USERNAME
        except Exception:
            pass
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
    stats = get_refer_stats(uid)
    top = get_top_referrers(3)

    medals = ["🥇", "🥈", "🥉"]
    top_lines = []
    for i, (tid, count) in enumerate(top):
        try:
            u = await bot.get_chat(tid)
            name = f"@{u.username}" if getattr(u, "username", None) else (u.first_name or f"User{tid}")
        except Exception:
            name = f"User{tid}"
        top_lines.append(f"{medals[i]} {name} — {count} lifetime referral(s)")
    if not top_lines:
        top_lines.append("<i>Abhi tak koi referrer nahi.</i>")

    text = ("➖➖➖➖➖➖➖\n« 🎁 REFER & EARN »\n➖➖➖➖➖➖➖\n"
            f"🔗 <b>YOUR LINK:</b>\n<code>{ref_link}</code>\n"
            "➖➖➖➖➖➖➖\n"
            f"👤 <b>TOTAL REFERS:</b> {stats['total']}\n"
            "➖➖➖➖➖➖➖\n"
            f"💸 <b>PER REFER:</b> {REFER_RATE} USDT\n"
            "➖➖➖➖➖➖➖\n\n"
            f"✅ <b>Referral Bonus:</b> {REFER_RATE} USDT\n"
            f"🎯 <b>Requirement:</b> referred user must receive {REFER_REQUIRED_OTPS} successful OTPs\n"
            f"⏳ <b>Pending Referrals:</b> {stats['pending']}\n"
            f"🏆 <b>Completed Referrals:</b> {stats['completed']}\n\n"
            "🏆 <b>TOP 3 LIFETIME REFERRERS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(top_lines) + "\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    await message.answer(text, reply_markup=refer_kb(ref_link), parse_mode="HTML")

@dp.message(F.text == BTN_2FA)
async def on_btn_2fa(message: types.Message, state: FSMContext):
    await state.clear()
    text = ("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "《 🔐 2FA ONLINE 》\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Generate your 2FA security code instantly using your secret key.\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    await message.answer(text, reply_markup=twofa_intro_kb(), parse_mode="HTML")

# =========================================================
# ADMIN PANEL
# =========================================================
@dp.message(F.text == BTN_ADMIN)
async def on_admin_panel(message: types.Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        return
    await message.answer("👑 <b>Welcome Admin!</b>\n\nYahan se aap bot ko control kar sakte hain:",
                         reply_markup=admin_panel_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Not allowed", show_alert=True)
        return
    await safe_edit(callback.message, "👑 <b>Welcome Admin!</b>\n\nYahan se aap bot ko control kar sakte hain:", admin_panel_kb())
    await callback.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Not allowed", show_alert=True)
        return
    await state.set_state(AdminFlow.waiting_broadcast)
    await safe_edit(callback.message,
        "📢 <b>Broadcast Mode</b>\n\nJo message aap bhejenge wo sabhi users ko chala jayega.\n(Text, Photo, Video, Forward sab chalega)\n\n<i>Cancel karne ke liye niche button dabayein.</i>",
        admin_cancel_kb())
    await callback.answer()

@dp.message(AdminFlow.waiting_broadcast)
async def process_admin_broadcast(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    sent = 0
    await message.answer(f"⏳ Broadcasting to {len(ALL_USERS)} users...")
    for uid in list(ALL_USERS):
        try:
            await message.copy_to(chat_id=uid)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await message.answer(f"✅ <b>Broadcast Done!</b>\nSent to {sent}/{len(ALL_USERS)} users.",
                         reply_markup=main_menu_reply_kb(message.from_user.id), parse_mode="HTML")

@dp.callback_query(F.data == "admin_limit")
async def cb_admin_limit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Not allowed", show_alert=True)
        return
    await state.set_state(AdminFlow.waiting_limit)
    await safe_edit(callback.message,
        f"⚙️ <b>Set Batch Size</b>\n\nCurrent: <b>{MAX_BATCH_SIZE}</b> — ek click pr itne numbers allocate honge.\n\nNaya number bhejein (jaise 1, 2, 3):",
        admin_cancel_kb())
    await callback.answer()

@dp.message(AdminFlow.waiting_limit)
async def process_admin_limit(message: types.Message, state: FSMContext):
    global MAX_BATCH_SIZE
    if not is_admin(message.from_user.id):
        return
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Kripya sirf valid number bhejein (jaise 2).")
        return
    val = int(message.text)
    if val < 1 or val > 20:
        await message.answer("❌ 1 se 20 ke beech ka number daalein.")
        return
    MAX_BATCH_SIZE = val
    save_data()
    await state.clear()
    await message.answer(f"✅ Batch size set to <b>{MAX_BATCH_SIZE}</b>.",
                         reply_markup=main_menu_reply_kb(message.from_user.id), parse_mode="HTML")

@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Not allowed", show_alert=True)
        return
    stats_text = (
        "📊 <b>Bot Statistics</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Total Users: <b>{len(ALL_USERS)}</b>\n"
        f"🔗 Active Orders: <b>{len(active_orders)}</b>\n"
        f"🎯 Total OTP Hits: <b>{sum(SERVICE_HITS.values())}</b>\n"
        f"⚙️ Batch Size: <b>{MAX_BATCH_SIZE}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await safe_edit(callback.message, stats_text, admin_panel_kb())
    await callback.answer()

# ★ NEW: Add Country
@dp.callback_query(F.data == "admin_add_country")
async def cb_admin_add_country(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Not allowed", show_alert=True)
        return
    await state.set_state(AdminFlow.waiting_add_country_service)
    
    rows = []
    for svc_key, svc_info in SERVICES.items():
        rows.append([make_btn(svc_info['label'], callback_data=f"addsvc|{svc_key}", style="primary")])
    rows.append([make_btn("❌ Cancel", callback_data="admin_panel", style="danger")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    
    await safe_edit(callback.message, "🌍 <b>Add Country / Range</b>\n\nKis service me add karna hai?", kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("addsvc|"), AdminFlow.waiting_add_country_service)
async def cb_admin_add_country_svc(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    svc_key = callback.data.split("|")[1]
    if svc_key not in SERVICES:
        await callback.answer("Invalid service", show_alert=True)
        return
    await state.update_data(add_svc=svc_key)
    await state.set_state(AdminFlow.waiting_add_country_code)
    await safe_edit(callback.message, 
        f"🌍 <b>Add Country to {SERVICES[svc_key]['label']}</b>\n\n"
        f"Country Code bhejein (jaise <code>GN</code>, <code>TG</code>, ya koi bhi naya jaise <code>FR</code>):\n\n"
        f"<i>Note: Agar country pehle se hai to naya range add ho jayega.</i>",
        admin_cancel_kb())
    await callback.answer()

@dp.message(AdminFlow.waiting_add_country_code)
async def process_add_country_code(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    cty_code = (message.text or "").strip().upper()
    if not cty_code.isalpha() or len(cty_code) < 2 or len(cty_code) > 3:
        await message.answer("❌ Valid Country Code bhejein (2-3 letters, jaise GN, CM).")
        return
    
    await state.update_data(add_cty=cty_code)
    await state.set_state(AdminFlow.waiting_add_country_range)
    
    await message.answer(
        f"🔢 Ab <b>{cty_code}</b> ka <b>Range/Prefix</b> bhejein (bina XXX ke).\n"
        f"Jaise: <code>261385</code> ya <code>228983</code>",
        reply_markup=admin_cancel_kb()
    )

@dp.message(AdminFlow.waiting_add_country_range)
async def process_add_country_range(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    prefix = (message.text or "").strip().replace("X", "").replace("x", "")
    if not prefix.isdigit() or len(prefix) < 3:
        await message.answer("❌ Valid digits bhejein (kam se kam 3 digits).")
        return
    
    data = await state.get_data()
    svc_key = data.get('add_svc')
    cty_code = data.get('add_cty')
    
    if not svc_key or not cty_code:
        await state.clear()
        await message.answer("❌ Session expired. Wapas try karein.")
        return
    
    if svc_key not in SERVICE_COUNTRY_RANGES:
        SERVICE_COUNTRY_RANGES[svc_key] = {}
    
    SERVICE_COUNTRY_RANGES[svc_key][cty_code] = {"prefix": prefix, "rid": prefix}
    
    if cty_code not in COUNTRY_INFO:
        COUNTRY_INFO[cty_code] = {"name": cty_code, "flag": "🌍"}
        
    rebuild_range_map()
    save_data()
    
    await state.clear()
    await message.answer(
        f"✅ <b>Country Added Successfully!</b>\n\n"
        f"Service: <b>{SERVICES[svc_key]['label']}</b>\n"
        f"Country: <b>{cty_code}</b>\n"
        f"Range: <code>{prefix}XXXXXX</code>",
        reply_markup=main_menu_reply_kb(message.from_user.id),
        parse_mode="HTML"
    )

# ★ NEW: Delete Country
@dp.callback_query(F.data == "admin_del_country")
async def cb_admin_del_country(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Not allowed", show_alert=True)
        return
    await state.set_state(AdminFlow.waiting_del_country_service)
    
    rows = []
    for svc_key, svc_info in SERVICES.items():
        rows.append([make_btn(svc_info['label'], callback_data=f"delsvc|{svc_key}", style="primary")])
    rows.append([make_btn("❌ Cancel", callback_data="admin_panel", style="danger")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    
    await safe_edit(callback.message, "🗑️ <b>Delete Country / Range</b>\n\nKis service se delete karna hai?", kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("delsvc|"), AdminFlow.waiting_del_country_service)
async def cb_admin_del_country_svc(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    svc_key = callback.data.split("|")[1]
    await state.update_data(del_svc=svc_key)
    await state.set_state(AdminFlow.waiting_del_country_code)
    
    cts = SERVICE_COUNTRY_RANGES.get(svc_key, {})
    if not cts:
        await safe_edit(callback.message, f"❌ Is service me koi country nahi hai.", admin_cancel_kb())
        return
        
    rows = []
    for cty_code, info in cts.items():
        rows.append([make_btn(f"Delete {cty_code} ({info['prefix']})", callback_data=f"delcty|{cty_code}", style="danger")])
    rows.append([make_btn("❌ Cancel", callback_data="admin_panel", style="danger")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    
    await safe_edit(callback.message, f"🗑️ <b>Delete Country from {SERVICES[svc_key]['label']}</b>\n\nKaunsi country delete karni hai?", kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("delcty|"), AdminFlow.waiting_del_country_code)
async def cb_admin_del_country_code(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    cty_code = callback.data.split("|")[1]
    data = await state.get_data()
    svc_key = data.get('del_svc')
    
    if not svc_key or svc_key not in SERVICE_COUNTRY_RANGES:
        await state.clear()
        await callback.answer("❌ Error", show_alert=True)
        return
        
    if cty_code in SERVICE_COUNTRY_RANGES[svc_key]:
        prefix = SERVICE_COUNTRY_RANGES[svc_key][cty_code]['prefix']
        del SERVICE_COUNTRY_RANGES[svc_key][cty_code]
        
        rebuild_range_map()
        save_data()
                
        await state.clear()
        await safe_edit(
            callback.message,
            f"✅ <b>Deleted!</b>\n\nService: <b>{SERVICES[svc_key]['label']}</b>\nCountry: <b>{cty_code}</b>\nRange: <code>{prefix}</code>",
            admin_panel_kb()
        )
        await callback.answer("Deleted!")
    else:
        await callback.answer("Country not found", show_alert=True)

# ★ NEW: Export / Import
@dp.callback_query(F.data == "admin_export")
async def cb_admin_export(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Not allowed", show_alert=True)
        return
    try:
        data = serialize_state()
        json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        fname = f"aadi_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        await callback.message.answer_document(
            BufferedInputFile(json_bytes, filename=fname),
            caption=(
                f"📤 <b>Database Export</b>\n\n"
                f"👤 Users: <b>{len(USERS_DB)}</b>\n"
                f"🎯 Service Hits: <b>{len(SERVICE_HITS)}</b>\n"
                f"🔗 Active Orders: <b>{len(active_orders)}</b>\n"
                f"⚙️ Batch Size: <b>{MAX_BATCH_SIZE}</b>"
            ),
            parse_mode="HTML",
        )
        await callback.answer("✅ Exported!")
    except Exception as e:
        logging.error(f"Export error: {e}", exc_info=True)
        await callback.answer(f"❌ Export fail: {str(e)[:100]}", show_alert=True)

@dp.callback_query(F.data == "admin_import")
async def cb_admin_import(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Not allowed", show_alert=True)
        return
    await state.set_state(AdminFlow.waiting_import_file)
    await safe_edit(callback.message,
        "📥 <b>Import Database</b>\n\n"
        "JSON backup file document ke roop me bhejein.\n"
        "⚠️ Purana data replace ho jayega.\n\n"
        "<i>Cancel karne ke liye niche dabayein.</i>",
        admin_cancel_kb())
    await callback.answer()

@dp.message(AdminFlow.waiting_import_file, F.document)
async def process_import_file(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    try:
        file_id = message.document.file_id
        file = await bot.get_file(file_id)
        file_data = await bot.download_file(file.file_path)
        raw = file_data.read().decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Invalid JSON structure")
        deserialize_state(data)
        save_data()
        await message.answer(
            f"✅ <b>Import Successful!</b>\n\n"
            f"👤 Users: <b>{len(USERS_DB)}</b>\n"
            f"🎯 Service Hits: <b>{len(SERVICE_HITS)}</b>\n"
            f"🔗 Active Orders: <b>{len(active_orders)}</b>\n"
            f"⚙️ Batch Size: <b>{MAX_BATCH_SIZE}</b>",
            reply_markup=main_menu_reply_kb(message.from_user.id),
            parse_mode="HTML",
        )
        logging.info(f"[IMPORT] Success: {len(USERS_DB)} users, {len(SERVICE_HITS)} hits")
    except Exception as e:
        logging.error(f"Import error: {e}", exc_info=True)
        await message.answer(f"❌ <b>Import Failed</b>\n<i>{str(e)[:200]}</i>",
                             reply_markup=main_menu_reply_kb(message.from_user.id),
                             parse_mode="HTML")

@dp.message(AdminFlow.waiting_import_file)
async def process_import_wrong(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("❌ Kripya JSON backup file bhejein (document format me).")

# =========================================================
# FSM STATES (User)
# =========================================================
@dp.message(UserFlow.waiting_search_range)
async def process_search_range(message: types.Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt in MENU_BUTTONS:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=main_menu_reply_kb(message.from_user.id))
        return
    if not txt or txt.startswith("/"):
        await state.clear()
        return
    rid = txt.lower().replace("x", "").strip()
    if not rid.isdigit() or len(rid) < 4:
        await message.answer(
            "❌ <b>Invalid range!</b>\nAt least 4 digits chahiye.\nExamples: <code>2613</code>, <code>26134xxx</code>",
            reply_markup=search_kb(), parse_mode="HTML",
        )
        return
    await state.clear()
    uid = message.from_user.id
    await message.answer(f"⏳ Allocating {MAX_BATCH_SIZE} number(s) from range <code>{rid}</code>...", parse_mode="HTML")

    results = await fetch_batch(uid, "search", "", rid, None)
    if results:
        numbers_meta = [{"number": r["number"], "country": r.get("detected_country", "")} for r in results]
        
        text_out = (
            f"📱 <b>SEARCH RESULT</b>\n🔢 Range: <code>{rid}</code>\n"
            f"Aadi SMS HUB 🔥\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"                <b>NUMBER{'S' if len(numbers_meta) > 1 else ''}</b>"
        )
        
        if not HAS_COPY:
            nums_str = "\n".join(f"<code>{n['number']}</code>" for n in numbers_meta)
            text_out += f"\n\n{nums_str}\n<i>(Long-press to copy)</i>"
            
        sent = await message.answer(text_out, reply_markup=batch_search_kb(rid, numbers_meta), parse_mode="HTML")
        # ★ Store for deletion on next GET NUMBERS click
        LAST_NUMBER_MSG[uid] = (sent.chat.id, sent.message_id)
    else:
        await message.answer(
            f"❌ <b>Number nahi mila</b>\nRange <code>{rid}</code>",
            reply_markup=search_kb(), parse_mode="HTML",
        )

@dp.callback_query(F.data.startswith("chg_search|"))
async def handle_change_search(callback: CallbackQuery):
    rid = callback.data.split("|", 1)[1]
    uid = callback.from_user.id
    await safe_edit(callback.message, f"🔄 <b>Changing numbers...</b>\nRange: <code>{rid}</code>")
    remove_user_orders(uid, service="search")
    results = await fetch_batch(uid, "search", "", rid, None)
    if results:
        numbers_meta = [{"number": r["number"], "country": r.get("detected_country", "")} for r in results]
        
        text_out = (
            f"📱 <b>SEARCH RESULT</b>\n🔢 Range: <code>{rid}</code>\n"
            f"Aadi SMS HUB 🔥\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"                <b>NUMBER{'S' if len(numbers_meta) > 1 else ''}</b>"
        )
        
        if not HAS_COPY:
            nums_str = "\n".join(f"<code>{n['number']}</code>" for n in numbers_meta)
            text_out += f"\n\n{nums_str}\n<i>(Long-press to copy)</i>"
            
        await safe_edit(callback.message, text_out, batch_search_kb(rid, numbers_meta))
        LAST_NUMBER_MSG[uid] = (callback.message.chat.id, callback.message.message_id)
    else:
        await safe_edit(callback.message, f"❌ <b>Naya number nahi mila</b>\nRange <code>{rid}</code>",
                        search_kb())

@dp.message(UserFlow.waiting_2fa_key)
async def process_2fa_key(message: types.Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt in MENU_BUTTONS:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=main_menu_reply_kb(message.from_user.id))
        return
    if not txt or txt.startswith("/"):
        await state.clear()
        return
    secret = txt.replace(" ", "").upper()
    try:
        code = pyotp.TOTP(secret).now()
    except Exception:
        await message.answer(
            "❌ <b>Invalid 2FA key!</b>\n\nBase32 format (A-Z, 2-7).\nExample: <code>JBSWY3DPEHPK3PXP</code>",
            reply_markup=twofa_enter_kb(), parse_mode="HTML",
        )
        return
    await state.clear()
    text_out = ("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "《 ✅ 2FA CODE GENERATED 》\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    if not HAS_COPY:
        text_out += f"\n\n<code>{code}</code>\n<i>(Long-press to copy)</i>"
        
    await message.answer(text_out, reply_markup=twofa_result_kb(code), parse_mode="HTML")

# =========================================================
# INLINE CALLBACKS
# =========================================================
@dp.callback_query(F.data == "verify_join")
async def verify_join(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if await get_not_joined(callback.from_user.id):
        await callback.answer("❌ Pehle saare channels join karein!", show_alert=True)
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(WELCOME_TEXT, reply_markup=main_menu_reply_kb(callback.from_user.id))
    await callback.answer("✅ Verified!")

@dp.callback_query(F.data == "main_menu")
async def handle_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(WELCOME_TEXT, reply_markup=main_menu_reply_kb(callback.from_user.id))
    await callback.answer()

@dp.callback_query(F.data == "noop")
async def handle_noop(callback: CallbackQuery):
    await callback.answer("✅ Copied!" if HAS_COPY else "Long-press to copy")

@dp.callback_query(F.data.startswith("shownum|"))
async def handle_shownum(callback: CallbackQuery):
    val = callback.data.split("|", 1)[1]
    await callback.answer(f"📋 {val}", show_alert=True)

@dp.callback_query(F.data == "get_numbers")
async def handle_get_numbers(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if await get_not_joined(callback.from_user.id):
        await callback.answer("Pehle force join complete karein!", show_alert=True)
        return
    await safe_edit(callback.message, SERVICE_MENU_TEXT, service_menu_kb())

@dp.callback_query(F.data.startswith("svc|"))
async def handle_service_click(callback: CallbackQuery):
    try:
        service_key = callback.data.split("|", 1)[1]
    except IndexError:
        await callback.answer("Invalid!", show_alert=True)
        return
    svc = SERVICES.get(service_key)
    if not svc:
        await callback.answer("Not found!", show_alert=True)
        return
    countries_map = SERVICE_COUNTRY_RANGES.get(service_key, {})
    if not countries_map:
        await callback.answer("No countries configured!", show_alert=True)
        return
    items = list(countries_map.items())
    items.sort(key=lambda kv: -SERVICE_HITS.get((service_key, kv[0]), 0))
    countries = []
    for code, info in items:
        hits = SERVICE_HITS.get((service_key, code), 0)
        cinfo = COUNTRY_INFO.get(code, {})
        countries.append({"code": code, "name": cinfo.get("name", code),
                          "flag": cinfo.get("flag", ""), "hits": hits})
    ranking_lines = []
    for i, c in enumerate(countries, start=1):
        fire = " 🔥" if i == 1 and c['hits'] > 0 else ""
        ranking_lines.append(f"{i}. {c['flag']} {c['name']} ({c['code']}) • {c['hits']} hits{fire}")
    text = (f"📌 <b>Select a country for {svc['label']}:</b>\n\n"
            f"<b>Countries by hits</b>\n" + "\n".join(ranking_lines) + "\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    await safe_edit(callback.message, text, country_menu_kb(service_key, countries))

@dp.callback_query(F.data.startswith("cty|"))
async def handle_country_click(callback: CallbackQuery):
    try:
        _, service_key, country_code = callback.data.split("|")
    except ValueError:
        await callback.answer("Invalid!", show_alert=True)
        return
    svc = SERVICES.get(service_key, {"label": service_key, "name": service_key})
    ci_info = COUNTRY_INFO.get(country_code, {"name": country_code, "flag": ""})
    ci_range = SERVICE_COUNTRY_RANGES.get(service_key, {}).get(country_code, {})
    rid = ci_range.get("rid")
    prefix = ci_range.get("prefix", "")
    uid = callback.from_user.id
    await safe_edit(callback.message,
        f"📱 <b>{svc['label']}</b>\n"
        f"{ci_info['flag']} {ci_info['name']} ({country_code})\n"
        f"Aadi SMS HUB 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ Allocating {MAX_BATCH_SIZE} number(s) from <code>{prefix}XXXXXX</code>...")
    results = await fetch_batch(uid, service_key, country_code, rid, prefix)
    if results:
        numbers_meta = [{"number": r["number"], "country": r.get("detected_country", country_code)} for r in results]
        
        text = (f"📱 <b>{svc['label']}</b>\n"
                f"{ci_info['flag']} {ci_info['name']} ({country_code})\n"
                f"Aadi SMS HUB 🔥\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"                <b>{svc['name']}</b>")
                
        if not HAS_COPY:
            nums_str = "\n".join(f"<code>{n['number']}</code>" for n in numbers_meta)
            text += f"\n\n{nums_str}\n<i>(Long-press to copy)</i>"
            
        await safe_edit(callback.message, text, batch_display_kb(service_key, country_code, numbers_meta, ci_info['flag']))
        LAST_NUMBER_MSG[uid] = (callback.message.chat.id, callback.message.message_id)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [make_btn("🔄 Retry", callback_data=f"cty|{service_key}|{country_code}", style="success")],
            [make_btn("🔙 Back", callback_data=f"svc|{service_key}", style="primary")],
        ])
        await safe_edit(callback.message,
            f"❌ <b>Number nahi mila</b>\nRange <code>{prefix}XXXXXX</code>", kb)

@dp.callback_query(F.data.startswith("change|"))
async def handle_change_number(callback: CallbackQuery):
    try:
        _, service_key, country_code = callback.data.split("|")
    except ValueError:
        await callback.answer("Invalid!", show_alert=True)
        return
    svc = SERVICES.get(service_key, {"label": service_key, "name": service_key})
    ci_info = COUNTRY_INFO.get(country_code, {"name": country_code, "flag": ""})
    ci_range = SERVICE_COUNTRY_RANGES.get(service_key, {}).get(country_code, {})
    rid = ci_range.get("rid")
    prefix = ci_range.get("prefix", "")
    uid = callback.from_user.id
    await safe_edit(callback.message, f"🔄 <b>Changing numbers...</b>\nRange <code>{prefix}XXXXXX</code>")
    remove_user_orders(uid, service=service_key, country=country_code)
    results = await fetch_batch(uid, service_key, country_code, rid, prefix)
    if results:
        numbers_meta = [{"number": r["number"], "country": r.get("detected_country", country_code)} for r in results]
        
        text = (f"📱 <b>{svc['label']}</b>\n"
                f"{ci_info['flag']} {ci_info['name']} ({country_code})\n"
                f"Aadi SMS HUB 🔥\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"                <b>{svc['name']}</b>")
                
        if not HAS_COPY:
            nums_str = "\n".join(f"<code>{n['number']}</code>" for n in numbers_meta)
            text += f"\n\n{nums_str}\n<i>(Long-press to copy)</i>"
            
        await safe_edit(callback.message, text, batch_display_kb(service_key, country_code, numbers_meta, ci_info['flag']))
        LAST_NUMBER_MSG[uid] = (callback.message.chat.id, callback.message.message_id)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [make_btn("🔄 Retry", callback_data=f"change|{service_key}|{country_code}", style="success")],
            [make_btn("🔙 Back", callback_data=f"cty|{service_key}|{country_code}", style="primary")],
        ])
        await safe_edit(callback.message, f"❌ <b>Naya number nahi mila</b>", kb)

@dp.callback_query(F.data == "gen_2fa")
async def handle_gen_2fa(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserFlow.waiting_2fa_key)
    text = ("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "《 🔑 ENTER 2FA KEY 》\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📝 <b>SEND YOUR 2FA SECRET KEY</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    await safe_edit(callback.message, text, twofa_enter_kb())

# =========================================================
# DEBUG
# =========================================================
@dp.message(F.text.startswith("/testapi"))
async def test_api_command(message: types.Message):
    parts = message.text.split()
    arg = parts[1].upper() if len(parts) > 1 else "GN"
    prefix = None
    if ":" in arg:
        try:
            svc_key, code = arg.split(":", 1)
            if svc_key in SERVICE_COUNTRY_RANGES and code in SERVICE_COUNTRY_RANGES[svc_key]:
                prefix = SERVICE_COUNTRY_RANGES[svc_key][code]["prefix"]
        except Exception:
            pass
    if not prefix:
        for svc_key, cts in SERVICE_COUNTRY_RANGES.items():
            if arg in cts:
                prefix = cts[arg]["prefix"]
                break
    if not prefix:
        await message.answer("❌ Format: <code>/testapi GN</code> ya <code>/testapi instagram:MG</code>", parse_mode="HTML")
        return
    await message.answer(f"🧪 Testing getnum rid=<code>{prefix}</code>...", parse_mode="HTML")
    headers = {"mauthapi": SMS_API_KEY, "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{API_BASE}/getnum", json={"rid": prefix}, headers=headers, timeout=12) as r:
                data = await r.json()
                meta = data.get("meta", {})
                num = (data.get("data") or {}).get("full_number")
                if meta.get("code") == 200 and num:
                    await message.answer(f"✅ Success!\n<code>{num}</code>", parse_mode="HTML")
                else:
                    await message.answer(f"❌ Failed\ncode: {meta.get('code')}\nstatus: {meta.get('status')}\nmsg: {data.get('message')}")
    except Exception as e:
        await message.answer(f"⚠️ Error: <code>{str(e)[:200]}</code>", parse_mode="HTML")

@dp.message(F.text == "/testotp")
async def test_otp_command(message: types.Message):
    res = await api_fetch_success_otp()
    if res.get("status") != "success":
        await message.answer(f"❌ API fail: {res.get('message')}")
        return
    otps = res.get("otps", [])[:5]
    if not otps:
        await message.answer("⚠️ Koi OTP nahi mila.")
        return
    lines = ["📊 <b>Last 5 OTPs:</b>", "━━━━━━━━━━━━"]
    for o in otps:
        num = o.get("number", "")
        msg = o.get("message", "")[:40]
        code = extract_otp(msg) or "??"
        lines.append(f"• <code>{num}</code> → {code}")
    await message.answer("\n".join(lines), parse_mode="HTML")

@dp.message(F.text == "/checkcopy")
async def checkcopy_command(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    import aiogram
    test_val = "TEST_COPY_12345"
    if HAS_COPY:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [make_btn(f"📋 {test_val}", copy_value=test_val, style="success")]
        ])
        await message.answer(
            f"🔧 aiogram: <code>{aiogram.__version__}</code>\n"
            f"🔧 HAS_COPY: <b>True</b>\n\n"
            f"👆 Button tap karein. Agar '{test_val}' copy ho gaya to sab sahi hai.",
            reply_markup=kb, parse_mode="HTML"
        )
    else:
        await message.answer(
            f"🔧 aiogram: <code>{aiogram.__version__}</code>\n"
            f"🔧 HAS_COPY: <b>False</b>\n\n"
            f"❌ Copy feature disabled (aiogram < 3.7.0).\n\n"
            f"Fix: Terminal me chalayein:\n"
            f"<code>pip install -U \"aiogram==3.15.0\"</code>\n"
            f"Fir bot restart karein.",
            parse_mode="HTML"
        )

@dp.message(F.text == "/debug")
async def debug_command(message: types.Message):
    import aiogram
    lines = [
        "🔧 <b>Debug Info</b>",
        "━━━━━━━━━━━━",
        f"aiogram: <code>{aiogram.__version__}</code>",
        f"HAS_COPY: <code>{HAS_COPY}</code>",
        f"MAX_BATCH_SIZE: <code>{MAX_BATCH_SIZE}</code>",
        f"Active Orders: <code>{len(active_orders)}</code>",
        f"Users: <code>{len(USERS_DB)}</code>",
        f"Service Hits groups: <code>{len(SERVICE_HITS)}</code>",
    ]
    await message.answer("\n".join(lines), parse_mode="HTML")

@dp.message(F.text == "/hits")
async def hits_command(message: types.Message):
    if not SERVICE_HITS:
        await message.answer("📊 Abhi tak koi hits nahi.")
        return
    lines = ["📊 <b>Service Hits:</b>", "━━━━━━━━━━━━"]
    for (svc, cty), count in sorted(SERVICE_HITS.items(), key=lambda x: -x[1]):
        svc_l = SERVICES.get(svc, {}).get("label", svc)
        cty_i = COUNTRY_INFO.get(cty, {})
        lines.append(f"• {cty_i.get('flag','')} {cty_i.get('name',cty)} ({cty}) • {svc_l}: <b>{count}</b>")
    await message.answer("\n".join(lines), parse_mode="HTML")

# =========================================================
# STARTUP / MAIN
# =========================================================
async def startup():
    load_data()
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("✅ Webhook deleted")
    except Exception as e:
        logging.warning(f"Webhook delete failed: {e}")
    try:
        me = await bot.get_me()
        global BOT_USERNAME
        BOT_USERNAME = me.username or BOT_USERNAME
        logging.info(f"✅ Bot: @{me.username} ({me.id})")
    except Exception as e:
        logging.error(f"Bot token invalid: {e}")
        return False
        
    import aiogram
    logging.info(f"✅ aiogram version: {aiogram.__version__}")
    logging.info(f"✅ HAS_COPY: {HAS_COPY}")
    
    if not HAS_COPY:
        logging.warning("=" * 60)
        logging.warning("⚠️  COPY FEATURE DISABLED!")
        logging.warning("⚠️  aiogram < 3.7.0 detected.")
        logging.warning("⚠️  Run: pip install -U 'aiogram==3.15.0'")
        logging.warning("⚠️  Then restart bot.")
        logging.warning("=" * 60)
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id,
                    "⚠️ <b>IMPORTANT</b>\n\n"
                    "Copy feature (tap to copy) is DISABLED.\n\n"
                    "Fix: Server pe ye command chalayein:\n"
                    "<code>pip install -U aiogram==3.15.0</code>\n\n"
                    f"Current: <code>aiogram {aiogram.__version__}</code>",
                    parse_mode="HTML")
            except Exception:
                pass
    
    if ADMIN_IDS:
        logging.info(f"✅ Admin IDs: {sorted(ADMIN_IDS)}")
    if OTP_GROUP_ID:
        try:
            chat = await bot.get_chat(OTP_GROUP_ID)
            logging.info(f"✅ OTP Group: {chat.title} ({chat.id})")
        except Exception as e:
            logging.warning(f"⚠️ OTP group check failed: {e}")
    return True

async def main():
    logging.info("Bot starting...")
    ok = await startup()
    if not ok:
        return
    asyncio.create_task(poll_console_hits())
    asyncio.create_task(poll_otp_for_orders())
    asyncio.create_task(broadcast_stats_2h())
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())