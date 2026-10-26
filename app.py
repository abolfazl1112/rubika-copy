#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — v26 · Soroosh-only Assistant + Real SMS Force + Accurate SMS Stats

Assistant:
  • Only Soroosh (login + template execution)
  • Rubika and Eitaa removed from assistant (their own panels still work)
  • Real SMS force: if initial send goes to App, retry with force_sms=True
  • Accurate SMS stats: per-phone send_type breakdown, sorted by status
  • Vision: skip "request sent" notifications — only process "number received" result template
"""

import sys, os, io, contextlib, logging, queue, unicodedata
import json, time, secrets, asyncio, importlib.util, threading, re, shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

REAL_STDOUT = sys.stdout
REAL_STDERR = sys.stderr

def log_print(msg=""):
    try: print(msg, file=REAL_STDOUT, flush=True)
    except Exception: pass

logging.basicConfig(level=logging.CRITICAL, stream=io.StringIO())
for _name in ("", "uvicorn", "uvicorn.error", "uvicorn.access",
              "httpx", "httpcore", "telegram", "telegram.ext",
              "urllib3", "aiohttp", "asyncio", "fastapi",
              "multipart", "rubpy", "splusthon", "eitaa_cli", "eitaa",
              "requests", "web", "rubika_bot", "soroosh_bot", "eitaa_bot"):
    _lg = logging.getLogger(_name)
    _lg.setLevel(logging.CRITICAL); _lg.propagate = False
    _lg.handlers = [logging.NullHandler()]

try:
    import asyncio.unix_events as _ue
    _orig_add_signal = _ue._UnixSelectorEventLoop.add_signal_handler
    def _safe_add_signal(self, sig, callback, *args):
        try: return _orig_add_signal(self, sig, callback, *args)
        except (RuntimeError, ValueError, NotImplementedError, AttributeError): return None
    _ue._UnixSelectorEventLoop.add_signal_handler = _safe_add_signal
except Exception: pass

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ApplicationHandlerStop,
                          filters as tg_filters)
from telegram.request import HTTPXRequest

HERE = Path(__file__).parent.resolve()

# ═══════════════ CONFIG ═══════════════
TG_TOKEN = os.environ.get("TG_TOKEN", "").strip()
try: FORCED_OWNER = int(os.environ.get("TG_OWNER_ID", "").strip() or "8389746549")
except Exception: FORCED_OWNER = 8389746549

HOST = os.environ.get("PANEL_HOST", "0.0.0.0").strip()
PORT = int(os.environ.get("PORT", "8080"))

PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")
if not PUBLIC_URL:
    if os.environ.get("RAILWAY_ENVIRONMENT"):
        PUBLIC_URL = "https://rubika-production.up.railway.app"
    else:
        PUBLIC_URL = f"http://127.0.0.1:{PORT}"

def _panel_data_dir() -> Path:
    candidates = []
    e = os.environ.get("DATA_DIR", "").strip()
    if e: candidates.append(e)
    e = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if e: candidates.append(e)
    if os.environ.get("RAILWAY_ENVIRONMENT"):
        candidates.extend(["/data", "/app/data"])
    local = HERE / "data"
    try: local.mkdir(exist_ok=True); candidates.append(str(local))
    except Exception: pass
    for c in candidates:
        try:
            p = Path(c)
            if p.is_dir() and os.access(p, os.W_OK): return p.resolve()
        except Exception: pass
    return HERE

DATA_DIR = _panel_data_dir()
LOG_FILE = DATA_DIR / "bot_runtime.log"
os.environ["DATA_DIR"] = str(DATA_DIR)

RB_FILENAME = "rubika_tg_bot.py"
SR_FILENAME = "Soroosh_tg_bot.py"
EI_FILENAME = "Eitaa_tg_bot.py"

def _find_bot(filename):
    env = os.environ.get("RUBIKA_BOT_DIR")
    if env:
        p = Path(env).expanduser().resolve() / filename
        if p.is_file(): return p.parent, p
    for c in [HERE / filename, HERE.parent / filename,
              Path("/app") / filename, Path("/home/container") / filename]:
        try:
            if c.is_file(): return c.parent.resolve(), c.resolve()
        except Exception: pass
    for base in (Path.cwd(), HERE):
        for parent in [base] + list(base.parents):
            c = parent / filename
            try:
                if c.is_file(): return c.parent.resolve(), c.resolve()
            except Exception: pass
    return None, None

RB_DIR, RB_PATH = _find_bot(RB_FILENAME)
SR_DIR, SR_PATH = _find_bot(SR_FILENAME)
EI_DIR, EI_PATH = _find_bot(EI_FILENAME)

os.environ["TG_TOKEN"] = TG_TOKEN
os.environ["TG_OWNER_ID"] = str(FORCED_OWNER)

# ═══════════════ LOAD MODULES ═══════════════
rb = None
if RB_PATH:
    _buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(_buf), contextlib.redirect_stderr(_buf):
            spec = importlib.util.spec_from_file_location("rubika_bot", str(RB_PATH))
            rb = importlib.util.module_from_spec(spec)
            sys.modules["rubika_bot"] = rb
            spec.loader.exec_module(rb)
    except Exception as e:
        log_print(f"❌ import {RB_FILENAME}: {type(e).__name__}: {e}")
        rb = None

sr = None
if SR_PATH:
    _buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(_buf), contextlib.redirect_stderr(_buf):
            spec = importlib.util.spec_from_file_location("soroosh_bot", str(SR_PATH))
            sr = importlib.util.module_from_spec(spec)
            sys.modules["soroosh_bot"] = sr
            spec.loader.exec_module(sr)
    except Exception as e:
        log_print(f"❌ import {SR_FILENAME}: {type(e).__name__}: {e}")
        sr = None

ei = None
if EI_PATH:
    _buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(_buf), contextlib.redirect_stderr(_buf):
            spec = importlib.util.spec_from_file_location("eitaa_bot", str(EI_PATH))
            ei = importlib.util.module_from_spec(spec)
            sys.modules["eitaa_bot"] = ei
            spec.loader.exec_module(ei)
    except Exception as e:
        log_print(f"❌ import {EI_FILENAME}: {type(e).__name__}: {e}")
        ei = None

if rb is None and sr is None and ei is None:
    log_print("❌ هیچ رباتی import نشد."); sys.exit(1)

if sr is None:
    log_print("❌ دستیار فقط با سروش کار می‌کند — Soroosh_tg_bot.py لود نشد.")
    sys.exit(1)

for _mod in (rb, sr, ei):
    if _mod is None: continue
    try: _mod.FORCED_OWNER = FORCED_OWNER
    except Exception: pass
    try: _mod.TG_TOKEN = TG_TOKEN
    except Exception: pass
    try: _mod.STATE["owner"] = FORCED_OWNER
    except Exception: pass
    if not hasattr(_mod, "_loop_ref"):
        try: _mod._loop_ref = [None]
        except Exception: pass

# ═══════════════ Soroosh send_code type patch ═══════════════
if sr is not None and hasattr(sr, "SoroushClient"):
    try:
        _SR_CLS = sr.SoroushClient
        # V35_FINAL — send_code_request is on the INSTANCE, not the class.
        # Silently skip the class-level patch (spluslib attaches it dynamically).
        if not hasattr(_SR_CLS, "send_code_request"):
            _SR_CLS._type_patched_v25 = True
            print("[+] patch-sr-type: instance-level method, skipping")
        elif not getattr(_SR_CLS, "_type_patched_v25", False):
            _orig_req = _SR_CLS.send_code_request
            async def _patched_req(self, *a, **kw):
                r = await _orig_req(self, *a, **kw)
                try:
                    t = getattr(r, "type", None)
                    tname = type(t).__name__ if t else ""
                    mp = {
                        "SentCodeTypeApp": "برنامه", "SentCodeTypeSms": "sms",
                        "SentCodeTypeCall": "تماس", "SentCodeTypeFlashCall": "تماس",
                        "SentCodeTypeMissedCall": "تماس", "SentCodeTypeEmailCode": "email",
                        "SentCodeTypeFirebaseSms": "firebase",
                        "SentCodeTypeFragmentSms": "fragment",
                    }
                    self._code_type_name = mp.get(tname, "unknown")
                except Exception:
                    self._code_type_name = "unknown"
                return r
            _SR_CLS.send_code_request = _patched_req
            _SR_CLS._type_patched_v25 = True
            log_print("[+] patched SoroushClient.send_code_request")
    except Exception as e:
        log_print(f"[patch-sr-type] {e}")

# ═══════════════ WEB SESSIONS ═══════════════
SESS_FILE = str(DATA_DIR / "web_sessions.json")
SESSIONS: Dict[str, Dict[str, Any]] = {}
if os.path.exists(SESS_FILE):
    try: SESSIONS = json.load(open(SESS_FILE, encoding="utf-8"))
    except Exception: SESSIONS = {}

LOGS: List[dict] = []
MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None
USER_MODE: Dict[int, str] = {}

def wlog(msg):
    entry = {"text": str(msg)[:600], "ts": time.time()}
    LOGS.append(entry)
    if len(LOGS) > 500: LOGS.pop(0)
    try:
        if MAIN_LOOP and MAIN_LOOP.is_running():
            asyncio.run_coroutine_threadsafe(
                HUB.broadcast({"type": "log", "text": entry["text"], "ts": entry["ts"]}),
                MAIN_LOOP)
    except Exception: pass

for _mod in (rb, sr, ei):
    if _mod is None: continue
    try: _mod.log_cb = wlog
    except Exception: pass

STATIC = next((c for c in [HERE / "static", HERE.parent / "static"]
               if c.is_dir() and (c / "login.html").exists()), HERE / "static")

TG_APP: Optional[Application] = None

def esc(s):
    return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def B(label, data): return InlineKeyboardButton(label, callback_data=data)
def kb_(*rows): return InlineKeyboardMarkup([list(r) for r in rows if r])

class Conn:
    def __init__(self, ws, uid):
        self.ws = ws; self.uid = uid
        self.q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.alive = True; self.writer = None
    def push(self, msg) -> bool:
        if not self.alive: return False
        try: self.q.put_nowait(msg); return True
        except asyncio.QueueFull: self.alive = False; return False
    async def _write(self):
        try:
            while True:
                msg = await self.q.get()
                if isinstance(msg, str): await self.ws.send_text(msg)
                else: await self.ws.send_json(msg)
        except asyncio.CancelledError: raise
        except Exception: pass
        finally: self.alive = False

class Hub:
    def __init__(self): self.conns: set = set()
    async def connect(self, ws, uid):
        await ws.accept()
        c = Conn(ws, uid); c.writer = asyncio.create_task(c._write())
        self.conns.add(c); return c
    def disconnect(self, c):
        c.alive = False; self.conns.discard(c)
        if c.writer: c.writer.cancel()
    async def broadcast(self, msg, uid=None):
        for c in list(self.conns):
            if uid and c.uid != uid: continue
            if not c.push(msg): self.disconnect(c)

HUB = Hub()

def authorized(update):
    try: return update.effective_chat.id == FORCED_OWNER
    except Exception: return False

def _eta(sec):
    sec = int(sec)
    if sec < 60: return f"{sec}s"
    if sec < 3600: return f"{sec // 60}m"
    return f"{sec // 3600}h {(sec % 3600) // 60}m"

def mode_selector_kb():
    rows = []
    if rb is not None: rows.append([B("📱  پنل روبیکا", "mode:rubika")])
    if sr is not None: rows.append([B("🌀  پنل سروش",  "mode:soroosh")])
    if ei is not None: rows.append([B("📨  پنل ایتا",  "mode:eitaa")])
    rows.append([B("🎯  دستیار", "mode:assistant")])
    return kb_(*rows)

async def _render_mode_selector(cid: int, edit_mid: Optional[int] = None) -> Optional[int]:
    lines = ["🏠 <b>پنل مدیریت</b>", "━━━━━━━━━━━━", "", "یک پنل رو انتخاب کن:", ""]
    if rb is not None: lines.append("📱 <b>روبیکا</b> — ارسال، جوینر، کانال، لیسنر")
    if sr is not None: lines.append("🌀 <b>سروش</b> — ارسال، جوینر، پاسخ خودکار")
    if ei is not None: lines.append("📨 <b>ایتا</b> — ارسال، جوینر، پاسخ خودکار")
    lines.append("🎯 <b>دستیار</b> — ورود انبوه + اجرای مداوم قالب (سروش)")
    txt = "\n".join(lines) + "\n"
    if edit_mid:
        try:
            await TG_APP.bot.edit_message_text(
                chat_id=cid, message_id=edit_mid, text=txt,
                reply_markup=mode_selector_kb(), parse_mode="HTML",
                disable_web_page_preview=True)
            return edit_mid
        except Exception: pass
    try:
        m = await TG_APP.bot.send_message(
            chat_id=cid, text=txt, reply_markup=mode_selector_kb(),
            parse_mode="HTML", disable_web_page_preview=True)
        return m.message_id
    except Exception as e:
        log_print(f"[mode-selector] {type(e).__name__}: {e}")
        return None

# ══════════════════════════════════════════════════════════════
# ASSISTANT — v26 (Soroosh-only · real SMS force · accurate stats · vision explicit)
# ══════════════════════════════════════════════════════════════
ASST_DIR = DATA_DIR / "assistant"
ASST_DIR.mkdir(parents=True, exist_ok=True)
ASST_CFG_FILE = ASST_DIR / "config.json"
ASST_SEEN_FILE = ASST_DIR / "seen.json"
ASST_RUNNING_FILE = ASST_DIR / "running.json"
ASST_HISTORY_FILE = ASST_DIR / "sms_history.json"

ASST_DEFAULT = {
    "enabled": False, "group_id": 0, "accept_new_accounts": True,
    "wipe_accounts_on_startup": True,
    "auto_start_on_boot": False,
    "max_accounts": 50,
    "run_template_id_soroosh": None,
    "template_duration_hours": 6,
    "retry_after_s": 60, "give_up_after_s": 180,
    "notify_owner": True,
    "force_sms": True,
    "force_sms_max_retries": 1,
    "force_sms_delay_s": 10,
}

ASST_PENDING: Dict[str, dict] = {}
ASST_BATCHES: Dict[str, dict] = {}
ASST_BATCH_ERRORS: Dict[str, List[str]] = {}
ASST_USER_CACHE: Dict[str, dict] = {}
ASST_TASKS: Dict[str, asyncio.Task] = {}
ASST_WAITING: Dict[int, dict] = {}
ASST_RUNNING: Dict[str, dict] = {}
ASST_UID_PHONES: Dict[str, set] = {}

def asst_load_cfg():
    if not ASST_CFG_FILE.exists():
        asst_save_cfg(ASST_DEFAULT)
        return dict(ASST_DEFAULT)
    try:
        with open(ASST_CFG_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict): return dict(ASST_DEFAULT)
        merged = {**ASST_DEFAULT, **d}
        if int(merged.get("give_up_after_s", 0)) < 120: merged["give_up_after_s"] = 180
        if int(merged.get("retry_after_s", 0)) < 45: merged["retry_after_s"] = 60
        return merged
    except Exception: return dict(ASST_DEFAULT)

def asst_save_cfg(c):
    tmp = str(ASST_CFG_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ASST_CFG_FILE)

def asst_save_running_state():
    data = {}
    for key, info in ASST_RUNNING.items():
        data[key] = {
            "platform": info.get("platform", ""),
            "aid": info.get("aid", ""), "tid": info.get("tid", ""),
            "started": info.get("started", 0), "hours": info.get("hours", 6),
            "runs": info.get("runs", 0),
        }
    try:
        tmp = str(ASST_RUNNING_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ASST_RUNNING_FILE)
    except Exception as e:
        log_print(f"[asst-running-save] {e}")

def asst_load_running_state():
    if not ASST_RUNNING_FILE.exists(): return {}
    try:
        with open(ASST_RUNNING_FILE, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception: return {}

def asst_load_seen():
    try:
        if ASST_SEEN_FILE.exists():
            with open(ASST_SEEN_FILE, encoding="utf-8") as f: d = json.load(f)
            if isinstance(d, dict): return set(d.get("ids", []))
    except Exception: pass
    return set()

def asst_save_seen(ids):
    tmp = str(ASST_SEEN_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"ids": sorted(ids)}, f, ensure_ascii=False)
    os.replace(tmp, ASST_SEEN_FILE)

ASST_SEEN = asst_load_seen()

# ── SMS history (persistent across restarts) ──
def _load_sms_history():
    try:
        if ASST_HISTORY_FILE.exists():
            with open(ASST_HISTORY_FILE, encoding="utf-8") as f:
                d = json.load(f)
                return d if isinstance(d, list) else []
    except Exception: pass
    return []

def _save_sms_history(history):
    try:
        if len(history) > 2000:
            history = history[-2000:]
        tmp = str(ASST_HISTORY_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False)
        os.replace(tmp, ASST_HISTORY_FILE)
    except Exception: pass

ASST_SMS_HISTORY: List[dict] = _load_sms_history()

def _record_sms_event(phone, uid, send_type, force_attempted, force_success, status, error=None):
    ASST_SMS_HISTORY.append({
        "phone": phone, "uid": uid,
        "send_type": send_type,
        "force_attempted": force_attempted,
        "force_success": force_success,
        "status": status,
        "error": str(error)[:200] if error else None,
        "ts": int(time.time()),
    })
    _save_sms_history(ASST_SMS_HISTORY)

# ── Text normalization ──
_V25_INVIS = re.compile(r'[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff\ufe0e\ufe0f\u20e3]')
_V25_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_V25_UID_TOKEN = re.compile(r'/?set_[a-f0-9]{8,}', re.I)
_V25_UID = re.compile(r'set_([a-f0-9]{8,})', re.I)
_V25_PHONE = re.compile(
    r'(?<![0-9A-Za-z])(?:(?:\+|00)?98[\s\-.()]*0?|0)[\s\-.()]*9(?:[\s\-.()]*\d){9}(?!\d)')

V25_SEEN_FILE = ASST_DIR / "phones_seen.json"
V25_TTL = 6 * 3600

def _v25_load_seen():
    try:
        with open(V25_SEEN_FILE, encoding="utf-8") as f: d = json.load(f)
        now = time.time()
        return {k: float(v) for k, v in d.items() if now - float(v) < V25_TTL}
    except Exception: return {}

V25_SEEN_PH: Dict[str, float] = _v25_load_seen()

def _v25_save_seen():
    try:
        now = time.time()
        for k in [k for k, v in V25_SEEN_PH.items() if now - v > V25_TTL]:
            V25_SEEN_PH.pop(k, None)
        tmp = str(V25_SEEN_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(V25_SEEN_PH, f)
        os.replace(tmp, V25_SEEN_FILE)
    except Exception as e:
        log_print(f"[v25-seen-save] {e}")

def v25_full_text(msg):
    base = msg.text or msg.caption or ""
    ents = (msg.entities if msg.text else msg.caption_entities) or []
    extra = []
    for e in ents:
        try:
            if str(e.type) in ("text_link", "MessageEntityType.TEXT_LINK") and e.url:
                extra.append(e.url)
        except Exception: pass
    return base + ("\n" + "\n".join(extra) if extra else "")

def v25_norm(text):
    t = unicodedata.normalize("NFKC", text or "")
    t = _V25_INVIS.sub("", t)
    return t.translate(_V25_DIGITS)

def v25_phones(text):
    t = _V25_UID_TOKEN.sub(" ", text or "")
    out = []
    for m in _V25_PHONE.finditer(t):
        d = re.sub(r'\D', '', m.group(0))
        if d.startswith("00"): d = d[2:]
        if d.startswith("98") and len(d) > 10: d = d[2:]
        if d.startswith("0") and len(d) > 10: d = d[1:]
        if len(d) == 10 and d[0] == "9": out.append("0" + d)
    return list(dict.fromkeys(out))

def v25_uid(text):
    m = _V25_UID.search(text or "")
    return f"set_{m.group(1).lower()}" if m else None

# ── Vision template detection ──
def v25_vision_is_request_sent(text):
    """Initial 'request has been sent' notification — no numbers yet, must be ignored.
    Example:
        ⏲ ʀᴇQᴜᴇꜱᴛ ʜᴀꜱ ʙᴇᴇɴ ❲ - ❳
        ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ꜱᴇɴᴛ, ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ ꜰᴏʀ ʀᴇꜱᴘᴏɴꜱᴇ
        🤖 ʀᴇQᴜᴇꜱᴛ : #ꜰɪɴᴅ_ɴᴜᴍʙᴇʀ •
        📱 ᴀɴᴅʀᴏɪᴅɪᴅ : /set_xxx •
        📡 ᴘᴜꜱʜ ᴛʏᴘᴇ : ᴛᴏᴋᴇɴ •
        › ᴠɪꜱɪᴏɴ
    """
    if not text: return False
    markers = [
        "ʀᴇQᴜᴇꜱᴛ ʜᴀꜱ ʙᴇᴇɴ", "request has been",
        "ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ꜱᴇɴᴛ", "successfully sent",
        "ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ ꜰᴏʀ ʀᴇꜱᴘᴏɴꜱᴇ", "please wait for response",
        "ᴘᴜꜱʜ ᴛʏᴘᴇ", "push type",
        "ᴀɴᴅʀᴏɪᴅɪᴅ", "androidid",
    ]
    for m in markers:
        if m in text: return True
        if m.lower() in text.lower(): return True
    return False

def v25_vision_is_number_received(text):
    """Result template 'number received successfully' — real numbers present.
    Example:
        📞 #ɴᴜᴍʙᴇʀ ʀᴇᴄᴇɪᴠᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ
        ├─ 📶 Irancell
        │ └─ 09022955697
        │ └─ 09338145495
        ...
        🪪 ᴜꜱᴇʀ: /set_xxx
        › ᴠɪꜱɪᴏɴ
    """
    if not text: return False
    markers = [
        "ɴᴜᴍʙᴇʀ ʀᴇᴄᴇɪᴠᴇᴅ", "number received",
        "ʀᴇᴄᴇɪᴠᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ", "received successfully",
    ]
    for m in markers:
        if m in text: return True
        if m.lower() in text.lower(): return True
    return False

def v25_source(text, phones, uid):
    low = (text or "").lower()
    if "target #phones" in low or "lebeka team" in low or "@thelebeka" in low:
        return "lebeka"

    # Vision: EXPLICIT separation of the two templates.
    # 1) Result template "number received successfully" → process (only if numbers exist)
    if v25_vision_is_number_received(text):
        return "vision" if phones else None

    # 2) Notification template "request has been sent" → ignore explicitly
    if v25_vision_is_request_sent(text):
        return None

    # 3) Fallback: vision signature + at least one phone
    for sig in ("› ᴠɪꜱɪᴏɴ", "› vision", "› ʋɪꜱɪᴏɴ"):
        if sig in text and phones:
            return "vision"

    if uid and phones:
        return "vision"
    return None

# ── Send type labels ──
def _send_type_label(t: str) -> str:
    return {
        "sms": "🟢 SMS",
        "برنامه": "🟡 App",
        "app": "🟡 App",
        "تماس": "🔵 Call",
        "call": "🔵 Call",
        "email": "📧 Email",
        "firebase": "🔥 FB",
        "unknown": "⚪ ?",
        "": "⚪ ?",
    }.get(str(t), f"⚪ {t}")

# ── Code detection (Soroosh only) ──
def asst_code_source(text):
    t = text or ""
    t_clean = re.sub(r'[\s\u200c\u200d\ufeff]+', '', t)
    if "سروشپلاس" in t_clean: return "soroosh"
    if "soroosh" in t_clean.lower(): return "soroosh"
    if "سروش" in t_clean: return "soroosh"
    return None

def asst_code(text):
    t = text or ""
    t_norm = t.replace("：", ":")
    persian = "۰۱۲۳۴۵۶۷۸۹"; arabic = "٠١٢٣٤٥٦٧٨٩"
    trans = str.maketrans(persian + arabic, "01234567890123456789")
    t_norm = t_norm.translate(trans)

    pats = [
        r'کد\s*ورود\s*:\s*(\d{4,8})(?!\d)',
        r'کد\s*سروش\s*:\s*(\d{4,8})(?!\d)',
        r'Code\s*:\s*(\d{4,8})(?!\d)',
        r'Code\s+(\d{4,8})(?!\d)',
        r'کد\s*:\s*(\d{4,8})(?!\d)',
    ]
    for t_test in (t, t_norm):
        for pat in pats:
            m = re.search(pat, t_test)
            if m: return m.group(1)

    t_clean = re.sub(r'[\s\u200c\u200d]+', '', t_norm)
    fallback = [
        r'کدورود:(\d{4,8})(?!\d)', r'کدسروش:(\d{4,8})(?!\d)',
        r'Code:(\d{4,8})(?!\d)', r'Code(\d{4,8})(?!\d)',
        r'کد:(\d{4,8})(?!\d)',
    ]
    for pat in fallback:
        m = re.search(pat, t_clean)
        if m: return m.group(1)
    return None

def _threaded_runner(coro_fn, *args):
    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try: return loop.run_until_complete(coro_fn(*args))
        finally:
            try: loop.close()
            except Exception: pass
    return _runner

def _asst_extract_send_type(phone):
    if sr is None: return "unknown"
    try:
        norm = re.sub(r"[^\d]", "", phone or "")
        if norm.startswith("00"): norm = norm[2:]
        if norm.startswith("0"): norm = norm[1:]
        if not norm.startswith("98"): norm = "98" + norm
        for p in (phone, norm):
            e = getattr(sr, "_LOGIN_TMP", {}).get(p)
            if e:
                c = e.get("cli")
                if c: return getattr(c, "_code_type_name", "unknown") or "unknown"
    except Exception: pass
    return "unknown"

# ── REAL SMS FORCE ──
async def _force_sms_soroosh(phone, max_retries=1, delay_s=10):
    """Real attempt to force SMS when initial send went to App/Call.
    Returns {"success": bool, "new_type": str, "attempts": [...], "reason": str?}"""
    if sr is None:
        return {"success": False, "reason": "sr_not_loaded", "attempts": []}

    norm = re.sub(r"[^\d]", "", phone or "")
    if norm.startswith("00"): norm = norm[2:]
    if norm.startswith("0"): norm = norm[1:]
    if not norm.startswith("98"): norm = "98" + norm

    entry = None
    for p in (phone, norm):
        if hasattr(sr, "_LOGIN_TMP") and p in sr._LOGIN_TMP:
            entry = sr._LOGIN_TMP[p]; break
    if not entry:
        return {"success": False, "reason": "no_pending_login", "attempts": []}

    cli = entry.get("cli")
    if cli is None:
        return {"success": False, "reason": "no_client", "attempts": []}

    variant = entry.get("variant") or f"+{norm}"
    attempts = []

    for i in range(max_retries):
        if i > 0 and delay_s > 0:
            await asyncio.sleep(delay_s)
        try:
            r = cli.send_code_request(variant, force_sms=True)
            if asyncio.iscoroutine(r): r = await r
            new_type = getattr(cli, "_code_type_name", "unknown") or "unknown"
            h = getattr(r, "phone_code_hash", None)
            if h is None and isinstance(r, dict): h = r.get("phone_code_hash")
            attempts.append({"attempt": i+1, "new_type": new_type, "got_hash": bool(h)})
            if new_type == "sms":
                if h: entry["hash"] = h
                sr._LOGIN_TMP[norm] = entry
                try: sr._LOGIN_TMP[phone] = entry
                except Exception: pass
                return {"success": True, "new_type": "sms",
                        "phone_code_hash": h, "attempts": attempts}
        except Exception as e:
            err_s = f"{type(e).__name__}: {str(e)[:80]}"
            attempts.append({"attempt": i+1, "error": err_s})
            err_up = err_s.upper()
            if "FLOOD" in err_up or "TOO_MANY" in err_up:
                m = re.search(r"(\d+)", err_s)
                wait = min(int(m.group(1)) if m else 15, 45)
                await asyncio.sleep(wait)

    final_type = getattr(cli, "_code_type_name", "unknown") or "unknown"
    return {"success": False, "new_type": final_type,
            "reason": f"still_{final_type}", "attempts": attempts}

# ── Send code ──
async def asst_send_soroosh(phone):
    if sr is None: return {"ok": False, "status": "not_loaded",
                           "send_type": "unknown", "send_type_label": "⚪ ?"}

    norm = re.sub(r"[^\d]", "", phone or "")
    if norm.startswith("00"): norm = norm[2:]
    if norm.startswith("0"): norm = norm[1:]
    if not norm.startswith("98"): norm = "98" + norm

    # If already pending, return current state
    if hasattr(sr, "_LOGIN_TMP"):
        for p in (phone, norm):
            if p in sr._LOGIN_TMP:
                st = _asst_extract_send_type(phone)
                return {
                    "ok": True, "status": "awaiting_code",
                    "phone_code_hash": sr._LOGIN_TMP[p].get("hash"),
                    "send_type": st, "send_type_label": _send_type_label(st),
                    "reused": True, "force_attempted": False,
                }

    # Fresh send
    try:
        r = await asyncio.wait_for(
            asyncio.to_thread(_threaded_runner(sr.soroosh_send_code, phone)), timeout=95)
        if not isinstance(r, dict):
            return {"ok": False, "status": "bad_type",
                    "send_type": "unknown", "send_type_label": "⚪ ?"}

        if not r.get("ok"):
            return {"ok": False, "status": r.get("status", "send_failed"),
                    "send_type": "unknown", "send_type_label": "⚪ ?",
                    "force_attempted": False}

        initial_type = _asst_extract_send_type(phone)

        # REAL SMS FORCE — try if App / unknown
        force_attempted = False
        force_success = False
        force_details = None

        cfg = asst_load_cfg()
        if cfg.get("force_sms", True) and initial_type in ("برنامه", "app", "unknown", ""):
            force_attempted = True
            force_details = await _force_sms_soroosh(
                phone,
                max_retries=int(cfg.get("force_sms_max_retries", 1)),
                delay_s=int(cfg.get("force_sms_delay_s", 10)),
            )
            if force_details.get("success"):
                initial_type = "sms"
                force_success = True
                log_print(f"[v25-sms] {phone}: FORCED to SMS ✓")
            else:
                log_print(f"[v25-sms] {phone}: force failed ({force_details.get('reason')})")

        return {
            "ok": True, "status": "awaiting_code",
            "phone_code_hash": r.get("phone_code_hash"),
            "send_type": initial_type,
            "send_type_label": _send_type_label(initial_type),
            "force_attempted": force_attempted,
            "force_success": force_success,
            "force_details": force_details,
        }
    except asyncio.TimeoutError:
        return {"ok": False, "status": "timeout_95s",
                "send_type": "unknown", "send_type_label": "⚪ ?",
                "force_attempted": False}
    except Exception as e:
        return {"ok": False, "status": f"{type(e).__name__}: {str(e)[:100]}",
                "send_type": "unknown", "send_type_label": "⚪ ?",
                "force_attempted": False}

async def asst_verify_soroosh(phone, code):
    if sr is None: return {"ok": False, "status": "not_loaded"}
    try:
        r = await asyncio.wait_for(
            asyncio.to_thread(_threaded_runner(sr.soroosh_complete_login, phone, code)),
            timeout=125)
        if not isinstance(r, dict):
            return {"ok": False, "status": f"bad_type:{type(r).__name__}"}
        return r
    except asyncio.TimeoutError:
        return {"ok": False, "status": "timeout_125s"}
    except Exception as e:
        return {"ok": False, "status": f"{type(e).__name__}: {str(e)[:100]}"}

def asst_trim(max_n):
    if sr is None: return
    try:
        accs = sr.list_accounts()
        if len(accs) <= max_n: return
        items = sorted(accs.items(), key=lambda kv: (kv[1].get("created") or 0), reverse=True)
        removed = 0
        for aid, _ in items[max_n:]:
            key = f"soroosh:{aid}"
            info = ASST_RUNNING.get(key)
            if info:
                ev = info.get("stop")
                if ev:
                    try: ev.set()
                    except Exception: pass
                t = info.get("task")
                if t and not t.done():
                    try: t.cancel()
                    except Exception: pass
                ASST_RUNNING.pop(key, None)
            try: sr.remove_account(aid); removed += 1
            except Exception: pass
        log_print(f"[asst] trim soroosh → {max_n} (removed {removed})")
        asst_save_running_state()
    except Exception as e: log_print(f"[asst-trim] {e}")

def asst_cleanup_ops():
    if sr is None: return
    try:
        ops = sr._load_ops()
        cutoff = time.time() - 3600
        kept = [o for o in ops if not (o.get("_asst") and o.get("created", 0) < cutoff)]
        if len(kept) != len(ops):
            sr._save_ops(kept)
            log_print(f"[asst-cleanup] {len(ops) - len(kept)} ops removed")
    except Exception: pass

async def asst_run_template_once(aid, tid):
    if sr is None: return None
    try:
        tpl = sr.get_template(tid)
        if not tpl: return None
        op = {"id": f"asst_{secrets.token_hex(5)}", "created": int(time.time()),
              "type": "autotar", "accounts": [aid], "template_id": tid,
              "status": "running", "_asst": True,
              "progress": {"joined":0,"failed":0,"total":0,"pending":0,"in_progress":0,
                           "phase":"asst-loop","sent":0,"already":0,"tried":0,"wave":0,
                           "left":0,"round":0,"skipped_seen":0,"skipped_banned":0,"rejected":0},
              "errors": []}
        try: sr._save_op(op)
        except Exception: pass
        runner = getattr(sr, "run_auto_tar", None)
        if runner:
            try: await asyncio.wait_for(runner(op, log_print), timeout=1800)
            except asyncio.TimeoutError:
                log_print(f"[asst] soroosh:{aid} timeout 30min")
        return op["id"]
    except asyncio.CancelledError: raise
    except Exception as e:
        log_print(f"[asst-tpl] soroosh:{aid}: {type(e).__name__}: {e}")
        return None

async def asst_continuous_template(aid, tid, hours, stop_event):
    key = f"soroosh:{aid}"
    end = time.time() + hours * 3600
    runs = 0
    if sr is None:
        ASST_RUNNING.pop(key, None); asst_save_running_state(); return
    log_print(f"[asst] {key} start (h={hours}, tid={tid})")
    while not stop_event.is_set() and time.time() < end:
        try:
            accounts = sr.list_accounts()
            if aid not in accounts:
                log_print(f"[asst] {key} STOP: account gone"); break
        except Exception: pass
        try:
            tpl = sr.get_template(tid)
            if not tpl:
                log_print(f"[asst] {key} STOP: template gone"); break
        except Exception: pass
        runs += 1
        info = ASST_RUNNING.get(key)
        if info: info["runs"] = runs
        try:
            op_id = await asst_run_template_once(aid, tid)
            info2 = ASST_RUNNING.get(key)
            if info2: info2["current_op_id"] = op_id
        except asyncio.CancelledError: break
        except Exception as e:
            log_print(f"[asst] {key} run#{runs} ERROR: {e}")
            info3 = ASST_RUNNING.get(key)
            if info3: info3["last_error"] = str(e)[:200]
        if stop_event.is_set(): break
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30)
            break
        except asyncio.TimeoutError: pass
    log_print(f"[asst] {key} stop (runs={runs})")
    ASST_RUNNING.pop(key, None)
    asst_save_running_state()

def asst_start_one(aid, tid, hours):
    key = f"soroosh:{aid}"
    info = ASST_RUNNING.get(key)
    if info and info.get("task") and not info["task"].done(): return False
    ev = asyncio.Event()
    t = asyncio.create_task(asst_continuous_template(aid, tid, hours, ev))
    ASST_RUNNING[key] = {
        "task": t, "started": time.time(), "hours": hours, "stop": ev,
        "runs": 0, "platform": "soroosh", "aid": aid, "tid": tid,
        "current_op_id": None, "last_error": None,
    }
    asst_save_running_state()
    return True

async def asst_start_all():
    cfg = asst_load_cfg()
    hours = int(cfg.get("template_duration_hours", 6))
    n = 0
    tid = cfg.get("run_template_id_soroosh")
    if not tid:
        log_print("[asst-start] soroosh: NO TEMPLATE ⚠️"); return 0
    if sr is None: return 0
    try:
        accounts = sr.list_accounts()
        log_print(f"[asst-start] soroosh: {len(accounts)} accounts, tid={tid}")
        for aid in accounts:
            if asst_start_one(aid, tid, hours): n += 1
    except Exception as e:
        log_print(f"[asst-start] soroosh ERROR: {type(e).__name__}: {e}")
    return n

async def asst_stop_all():
    for key, info in list(ASST_RUNNING.items()):
        ev = info.get("stop")
        if ev:
            try: ev.set()
            except Exception: pass
        t = info.get("task")
        if t and not t.done():
            try: t.cancel()
            except Exception: pass
    ASST_RUNNING.clear()
    asst_save_running_state()

async def asst_restart_all():
    await asst_stop_all()
    await asyncio.sleep(1)
    return await asst_start_all()

# ── Batch reply — CLEAR send-type info ──
def asst_build_reply(bk):
    b = ASST_BATCHES.get(bk) or {}
    src = b.get("source", "?")
    label = {"lebeka":"لبکا","vision":"ویژن"}.get(src, src)
    phones = b.get("phones", [])
    results = b.get("results", {})

    def _line(ph):
        v = results.get(ph) or {}
        status = v.get("status", "")
        send_type = v.get("send_type", "unknown")
        fa = v.get("force_attempted", False)
        fs = v.get("force_success", False)
        ok = v.get("ok", False)

        if ok or status == "confirmed": icon = "✅"
        elif status == "giveup": icon = "❌"
        elif status == "retrying": icon = "🔄"
        elif status == "awaiting_code": icon = "⏳"
        else: icon = "⚪"

        st = _send_type_label(send_type)
        fm = ""
        if fa:
            fm = " 🔄✓" if fs else " 🔄✗"

        return f"{icon} <code>{esc(ph)}</code> — {st}{fm}"

    lines = [f"📋 <b>گزارش ورود سروش</b> — {label}", "━"*30, ""]
    if not phones:
        lines.append("<i>خالی</i>")
    for ph in phones:
        lines.append(_line(ph))
    lines.append("")
    lines.append(f"🪪 شناسه: <code>{esc(b.get('user_id') or '—')}</code>")

    errs = ASST_BATCH_ERRORS.get(bk, [])
    if errs:
        lines.append(f"\n⚠️ <b>خطاها ({len(errs)}):</b>")
        for e in errs[-3:]:
            lines.append(f"<code>• {esc(e[:80])}</code>")
    return "\n".join(lines)

async def asst_send(chat_id, text, reply_markup=None, reply_to=None):
    if TG_APP is None: return None
    try:
        kw = {"chat_id": chat_id, "text": text[:4000],
              "parse_mode": "HTML", "disable_web_page_preview": True}
        if reply_markup: kw["reply_markup"] = reply_markup
        if reply_to: kw["reply_to_message_id"] = reply_to
        return await TG_APP.bot.send_message(**kw)
    except Exception as e: log_print(f"[asst-send] {e}"); return None

async def asst_edit(bk, msg_id, chat_id):
    if TG_APP is None or not msg_id: return
    try:
        await TG_APP.bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id, text=asst_build_reply(bk)[:4000],
            parse_mode="HTML", disable_web_page_preview=True)
    except Exception: pass

async def asst_sleep_or(ev, sec):
    try: await asyncio.wait_for(ev.wait(), timeout=sec)
    except asyncio.TimeoutError: pass

async def asst_run_batch(bk, chat_id, source, phones, user_id):
    cfg = asst_load_cfg()
    batch = {"source": source, "phones": phones, "user_id": user_id,
             "chat_id": chat_id, "started": time.time(),
             "results": {ph: {} for ph in phones},
             "done": False, "stop": asyncio.Event(), "msg_id": None}
    ASST_BATCHES[bk] = batch
    ASST_BATCH_ERRORS[bk] = []

    m = await asst_send(chat_id, asst_build_reply(bk))
    if m: batch["msg_id"] = m.message_id

    # Phase 1: initial send for each phone
    for ph in phones:
        try: r = await asst_send_soroosh(ph)
        except Exception as e: r = {"ok": False, "status": str(e)[:80],
                                    "send_type": "unknown", "force_attempted": False}

        ok = bool(r.get("ok"))
        if not ok:
            ASST_BATCH_ERRORS[bk].append(f"soroosh {ph}: {r.get('status','?')[:60]}")
            log_print(f"[asst] soroosh:{ph} FAILED — {r.get('status')}")

        ASST_PENDING[f"{ph}|soroosh"] = {
            "batch_key": bk, "phone": ph, "platform": "soroosh",
            "phone_code_hash": r.get("phone_code_hash") or r.get("hash"),
            "sent_at": time.time(), "attempts": 1, "confirmed": False,
            "status": "awaiting_code" if ok else r.get("status", "send_failed"),
            "send_type": r.get("send_type", "unknown"),
            "force_attempted": r.get("force_attempted", False),
            "force_success": r.get("force_success", False),
        }
        batch["results"][ph] = {
            "status": ASST_PENDING[f"{ph}|soroosh"]["status"],
            "ok": False,
            "send_type": r.get("send_type", "unknown"),
            "send_type_label": r.get("send_type_label", _send_type_label("unknown")),
            "force_attempted": r.get("force_attempted", False),
            "force_success": r.get("force_success", False),
            "sent_at": time.time(),
        }
        _record_sms_event(
            ph, user_id, r.get("send_type", "unknown"),
            r.get("force_attempted", False), r.get("force_success", False),
            batch["results"][ph]["status"],
        )

    if batch["msg_id"]: await asst_edit(bk, batch["msg_id"], chat_id)

    # Phase 2: wait then retry force_sms for App-only phones
    await asst_sleep_or(batch["stop"], cfg.get("retry_after_s", 60))
    if batch.get("done"): return

    for key, v in list(ASST_PENDING.items()):
        if v["batch_key"] != bk or v["confirmed"]: continue
        ph = v["phone"]
        send_type = v.get("send_type", "unknown")
        force_attempted = v.get("force_attempted", False)

        # If initial send was App and we haven't force-attempted yet, try now
        if (send_type in ("برنامه", "app", "unknown") and not force_attempted
                and cfg.get("force_sms", True)):
            log_print(f"[v25-sms] {ph}: retry force_sms (phase 2)")
            fr = await _force_sms_soroosh(
                ph,
                max_retries=int(cfg.get("force_sms_max_retries", 1)),
                delay_s=int(cfg.get("force_sms_delay_s", 10)),
            )
            v["force_attempted"] = True
            if fr.get("success"):
                v["send_type"] = "sms"
                v["force_success"] = True
                if fr.get("phone_code_hash"): v["phone_code_hash"] = fr["phone_code_hash"]
                batch["results"][ph]["send_type"] = "sms"
                batch["results"][ph]["force_attempted"] = True
                batch["results"][ph]["force_success"] = True
                log_print(f"[v25-sms] {ph}: forced to SMS ✓ (phase 2)")
            else:
                v["force_success"] = False
                batch["results"][ph]["force_attempted"] = True
                batch["results"][ph]["force_success"] = False
                log_print(f"[v25-sms] {ph}: force failed ({fr.get('reason')})")

    if batch["msg_id"]: await asst_edit(bk, batch["msg_id"], chat_id)

    # Phase 3: giveup (entries STAY in PENDING for late code)
    await asst_sleep_or(batch["stop"], cfg.get("give_up_after_s", 180))
    if batch.get("done"): return

    for k, v in list(ASST_PENDING.items()):
        if v["batch_key"] != bk or v["confirmed"]: continue
        ph = v["phone"]
        v["status"] = "giveup"
        batch["results"][ph]["status"] = "giveup"
        log_print(f"[asst] soroosh:{ph} giveup")

    batch["done"] = True
    if batch["msg_id"]: await asst_edit(bk, batch["msg_id"], chat_id)
    if cfg.get("notify_owner") and TG_APP:
        try:
            ok_n = sum(1 for ph in phones for v in [batch["results"].get(ph, {})] if v.get("ok"))
            src_l = {"lebeka":"لبکا","vision":"ویژن"}.get(source, source)
            await TG_APP.bot.send_message(chat_id=FORCED_OWNER,
                text=f"✅ بچ تموم شد\n📞 {len(phones)} · ✅ {ok_n} موفق\n🔖 {src_l}")
        except Exception: pass

async def asst_safe_batch(bk, *args):
    try: await asst_run_batch(bk, *args)
    except asyncio.CancelledError:
        if bk in ASST_BATCHES: ASST_BATCHES[bk]["done"] = True
        raise
    except Exception as e:
        log_print(f"[asst-batch] FATAL: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        if bk not in ASST_BATCH_ERRORS: ASST_BATCH_ERRORS[bk] = []
        ASST_BATCH_ERRORS[bk].append(f"FATAL: {type(e).__name__}: {str(e)[:200]}")
        if bk in ASST_BATCHES:
            ASST_BATCHES[bk]["done"] = True
            if ASST_BATCHES[bk].get("msg_id"):
                await asst_edit(bk, ASST_BATCHES[bk]["msg_id"], ASST_BATCHES[bk].get("chat_id"))

async def asst_try_code(code):
    for key, v in list(ASST_PENDING.items()):
        if v["platform"] != "soroosh" or v["confirmed"]: continue
        ph, bk = v["phone"], v["batch_key"]
        try: r = await asst_verify_soroosh(ph, code)
        except Exception as e: r = {"ok": False, "status": str(e)[:80]}

        if r.get("ok"):
            v["confirmed"] = True; ASST_PENDING.pop(key, None)
            b = ASST_BATCHES.get(bk); cfg = asst_load_cfg()
            if b:
                b["results"][ph]["status"] = "confirmed"
                b["results"][ph]["ok"] = True
                asst_trim(int(cfg.get("max_accounts", 50)))
                if b.get("msg_id"): await asst_edit(bk, b["msg_id"], b.get("chat_id"))

            tid = cfg.get("run_template_id_soroosh")
            if tid and sr:
                try:
                    for aid, a in sr.list_accounts().items():
                        if a.get("phone") == ph:
                            hours = int(cfg.get("template_duration_hours", 6))
                            asst_start_one(aid, tid, hours)
                            break
                except Exception: pass
            cid_notify = (b.get("chat_id") if b else None) or FORCED_OWNER
            if not tid and TG_APP:
                try: await TG_APP.bot.send_message(chat_id=cid_notify,
                    text=f"⚠️ اکانت سروش وارد شد (<code>{esc(ph)}</code>)\n\n❌ قالب انتخاب نشده!",
                    parse_mode="HTML")
                except Exception: pass
            return ph
        else:
            if TG_APP:
                err_msg = str(r.get("status") or r.get("error") or "unknown")
                try:
                    await TG_APP.bot.send_message(chat_id=FORCED_OWNER,
                        text=f"❌ <b>خطای ورود سروش</b>\n📞 <code>{esc(ph)}</code>\n🔑 <code>{esc(code)}</code>\n⚠️ <code>{esc(err_msg[:200])}</code>",
                        parse_mode="HTML")
                except Exception: pass
    return None

def asst_dedup_kb(uid):
    return kb_(
        [B("🔁 ورود مجدد سروش", f"asst:force:soroosh:{uid}")],
        [B("❌ لغو", "noop")],
    )

async def asst_group_handler(update, context):
    msg = update.message or update.edited_message
    if msg is None: return
    is_edit = update.edited_message is not None
    try:
        if msg.chat.type not in ("group", "supergroup"): return
    except Exception: return
    cfg = asst_load_cfg()
    if not cfg.get("enabled"): return
    gid = int(cfg.get("group_id") or 0)
    if gid and msg.chat_id != gid: return

    raw = v25_full_text(msg)
    if not raw.strip(): return
    text = v25_norm(raw)
    log_print(f"[asst-group] edit={is_edit} chat={msg.chat_id} msg={msg.message_id} len={len(text)}")
    is_owner = bool(msg.from_user and msg.from_user.id == FORCED_OWNER)

    if text.strip() == "چخبر":
        if is_owner: await asst_stats_to(msg.chat_id, msg.message_id)
        return

    # Code detection (Soroosh only)
    plat = asst_code_source(text)
    if plat == "soroosh":
        code = asst_code(text)
        if code:
            matched = await asst_try_code(code)
            if matched:
                await asst_send(msg.chat_id,
                    f"✅ کد سروش روی <code>{esc(matched)}</code> تایید شد",
                    reply_to=msg.message_id)
            elif not is_edit:
                await asst_send(msg.chat_id,
                    f"⚠️ کد سروش دریافت شد ولی شماره‌ای در انتظار نبود\nکد: <code>{esc(code)}</code>",
                    reply_to=msg.message_id)
        return

    # Phone package detection
    phones = v25_phones(text)
    uid = v25_uid(text)
    if not phones:
        # Explicit log for vision "request sent" notifications so they don't confuse debugging
        if v25_vision_is_request_sent(text) and not v25_vision_is_number_received(text):
            log_print(f"[v26-vision] skip 'request sent' notification (msg {msg.message_id}, edit={is_edit})")
        return
    src = v25_source(text, phones, uid)
    if not src:
        log_print(f"[asst-group] phones={phones} ولی منبع نامشخص → رد شد")
        return
    if not cfg.get("accept_new_accounts", True):
        if not is_edit:
            await asst_send(msg.chat_id, "⏸ ثبت اکانت جدید موقتاً متوقف شده",
                            reply_to=msg.message_id)
        return

    ukey = uid or f"m{msg.message_id}"
    ASST_USER_CACHE[ukey] = {"source": src, "phones": phones, "ts": time.time()}

    now = time.time()
    new_phones = [p for p in phones if now - V25_SEEN_PH.get(p, 0) > V25_TTL]
    if not new_phones:
        if not is_edit:
            if is_owner:
                await asst_send(msg.chat_id,
                    f"⚠️ این شماره‌ها قبلاً ثبت شده: <code>{esc(ukey)}</code>\nدوباره بزنم؟",
                    reply_markup=asst_dedup_kb(ukey), reply_to=msg.message_id)
            else:
                await asst_send(msg.chat_id, "ℹ️ همه شماره‌ها قبلاً پردازش شدند",
                                reply_to=msg.message_id)
        return

    for p in new_phones: V25_SEEN_PH[p] = now
    _v25_save_seen()
    if uid:
        ASST_UID_PHONES.setdefault(uid, set()).update(new_phones)
        ASST_SEEN.add(uid); asst_save_seen(ASST_SEEN)
    log_print(f"[asst-group] phones={new_phones} uid={uid} src={src}")
    bk = "b_" + secrets.token_hex(4)
    ASST_TASKS[bk] = asyncio.create_task(
        asst_safe_batch(bk, msg.chat_id, src, new_phones, uid))

async def asst_stats_to(chat_id, reply_to=None):
    sr_n = len(sr.list_accounts()) if sr else 0
    pend = len([k for k in ASST_PENDING if not ASST_PENDING[k].get("confirmed")])
    act = len([k for k in ASST_BATCHES if not ASST_BATCHES[k].get("done")])
    total_errors = sum(len(e) for e in ASST_BATCH_ERRORS.values())
    txt = (f"📊 <b>آمار دستیار</b>\n━━━━━━━━━━━━\n"
           f"🌀 سروش: <b>{sr_n}</b>\n"
           f"⏳ در انتظار کد: <b>{pend}</b>\n"
           f"⚙️ بچ فعال: <b>{act}</b>\n"
           f"🎬 در حال اجرا: <b>{len(ASST_RUNNING)}</b>\n"
           f"⚠️ خطاهای بچ: <b>{total_errors}</b>\n"
           f"🔖 شناسه‌ها: <b>{len(ASST_SEEN)}</b>")
    await asst_send(chat_id, txt, reply_to=reply_to)

# ═══════════════ PANELS ═══════════════
async def v25_show_main(cid, edit_mid=None):
    cfg = asst_load_cfg()
    sr_n = len(sr.list_accounts()) if sr else 0
    on = "🟢" if cfg.get("enabled") else "⚪"
    acc = "🟢" if cfg.get("accept_new_accounts", True) else "🔴"
    running = len(ASST_RUNNING)
    pend = len([k for k in ASST_PENDING if not ASST_PENDING[k].get("confirmed")])
    force_on = "🟢" if cfg.get("force_sms", True) else "⚪"
    txt = (f"🎯 <b>دستیار — سروش</b>\n━━━━━━━━━━━━━━━\n\n"
           f"📶 وضعیت: {on}   ·   📥 پذیرش: {acc}\n"
           f"🔄 تلاش SMS: {force_on}\n"
           f"🎬 در حال اجرا: <b>{running}</b>   ·   ⏳ در انتظار کد: <b>{pend}</b>\n\n"
           f"<b>📊 اکانت‌ها:</b>\n🌀 سروش: <b>{sr_n}</b>")
    rows = [
        [B(f"📊 داشبورد ({running})", "asst:dash")],
        [B("🚀 عملیات گروهی", "asst:bulk")],
        [B("🎬 قالب سروش", "asst:set_tpl:soroosh"), B("⚙️ تنظیمات", "asst:menu:settings")],
        [B("📈 آمار و لاگ‌ها", "asst:menu:stats")],
        [B("📨 آمار پیامک", "asst:stats:sms")],
        [B("خاموش کن" if cfg.get("enabled") else "روشن کن", "asst:toggle")],
        [B("🏠 بازگشت", "mode:home")],
    ]
    markup = kb_(*rows)
    if edit_mid and TG_APP:
        try:
            await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt,
                                               reply_markup=markup, parse_mode="HTML",
                                               disable_web_page_preview=True)
            return
        except Exception as e:
            if "not modified" in str(e).lower(): return
    if TG_APP:
        try:
            m = await TG_APP.bot.send_message(cid, txt, reply_markup=markup,
                                              parse_mode="HTML", disable_web_page_preview=True)
            for mod in (rb, sr, ei):
                if mod is not None:
                    try: mod.STATE["panel"][cid] = m.message_id
                    except Exception: pass
        except Exception: pass

async def v25_show_dashboard(cid, edit_mid=None):
    total = len(ASST_RUNNING)
    txt = f"📊 <b>داشبورد زنده</b> — {total} اکانت\n━━━━━━━━━━━━━━━\n\n"
    if total == 0:
        txt += "<i>هیچ اکانتی در حال اجرا نیست</i>"
    else:
        txt += "🌀 <b>سروش</b>:\n"
        accs_data = {}
        try:
            if sr: accs_data = sr.list_accounts() or {}
        except Exception: pass
        for key, info in list(ASST_RUNNING.items())[:6]:
            aid = info.get("aid") or key.split(":", 1)[1]
            name = (accs_data.get(aid) or {}).get("name", aid[:10])[:18]
            runs = info.get("runs", 0)
            elapsed = int(time.time() - info.get("started", 0)) if info.get("started") else 0
            txt += f"  • <b>{esc(name)}</b> — دور {runs} — {_eta(elapsed)}\n"
        if total > 6: txt += f"  <i>+{total-6} دیگر</i>\n"
    rows = [[B(f"🌀 جزئیات سروش ({total})", "asst:dash:plat:soroosh")]] if total else []
    rows.append([B("🔄 بروزرسانی", "asst:dash")])
    rows.append([B("« بازگشت", "asst:refresh")])
    markup = kb_(*rows)
    if edit_mid and TG_APP:
        try:
            await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt[:4000],
                                               reply_markup=markup, parse_mode="HTML",
                                               disable_web_page_preview=True)
            return
        except Exception as e:
            if "not modified" in str(e).lower(): return
    if TG_APP:
        try:
            await TG_APP.bot.send_message(cid, txt[:4000], reply_markup=markup,
                                          parse_mode="HTML", disable_web_page_preview=True)
        except Exception: pass

async def v25_show_dash_platform(cid, edit_mid=None):
    accs_data = {}
    try:
        if sr: accs_data = sr.list_accounts() or {}
    except Exception: pass
    running_keys = [k for k in ASST_RUNNING.keys() if k.startswith("soroosh:")]
    txt = f"🌀 <b>سروش — اجراهای فعال</b>\n━━━━━━━━━━━━━━━\n\n"
    if not running_keys:
        txt += "<i>هیچ اکانتی در حال اجرا نیست</i>"
    rows = []
    for key in running_keys:
        info = ASST_RUNNING.get(key) or {}
        aid = info.get("aid") or key.split(":", 1)[1]
        acc = accs_data.get(aid) or {}
        name = (acc.get("name") or aid)[:22]
        runs = info.get("runs", 0)
        txt += f"👤 <b>{esc(name)}</b> — دور {runs}\n"
        rows.append([B(f"👤 {esc(name[:22])} (دور {runs})", f"asst:acc:soroosh:{aid}")])
    rows.append([B("« بازگشت", "asst:dash")])
    markup = kb_(*rows)
    if edit_mid and TG_APP:
        try:
            await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt[:4000],
                                               reply_markup=markup, parse_mode="HTML",
                                               disable_web_page_preview=True)
            return
        except Exception as e:
            if "not modified" in str(e).lower(): return
    if TG_APP:
        try:
            await TG_APP.bot.send_message(cid, txt[:4000], reply_markup=markup,
                                          parse_mode="HTML", disable_web_page_preview=True)
        except Exception: pass

def _v25_bar(pct, n=14):
    pct = max(0, min(100, int(pct)))
    fill = int(pct * n / 100)
    return "█" * fill + "░" * (n - fill) + f" {pct}%"

def v25_phase_section(phase_str):
    if not phase_str: return None
    ph = str(phase_str); ph_low = ph.lower()
    if "کانال" in ph or "ph_create" in ph_low or "channel" in ph_low: return "channel"
    if "پروفایل" in ph or "ph_update_prof" in ph_low or "profile" in ph_low: return "profile"
    if "pv" in ph_low: return "pv"
    if "استخراج" in ph or "جوین" in ph or "موج" in ph or "join" in ph_low: return "joiner"
    if "ارسال" in ph or "ph_sending" in ph_low or "send" in ph_low: return "sender"
    if "ترک" in ph or "ph_leaving" in ph_low or "leave" in ph_low: return "lefter"
    if "پایان" in ph or "ph_done" in ph_low: return "done"
    return None

def v25_build_account_detail(aid, info, tpl, op):
    accs = {}
    try:
        if sr: accs = sr.list_accounts() or {}
    except Exception: pass
    acc = accs.get(aid) or {}
    name = acc.get("name") or aid[:12]
    phone = acc.get("phone") or "—"
    prog = (op.get("progress") if op else {}) or {}
    phase = prog.get("phase", "")
    runs = info.get("runs", 0)
    elapsed = int(time.time() - info.get("started", 0)) if info.get("started") else 0
    hours = info.get("hours", 6)
    lines = [
        f"🌀 <b>{esc(name[:24])}</b>",
        f"📞 <code>{esc(phone)}</code>",
        f"🔁 دور {runs} · ⏱ {_eta(elapsed)} / {hours}h",
        "━━━━━━━━━━━━━━━",
    ]
    if not tpl:
        lines.append("⚠️ قالب حذف شده یا پیدا نشد")
        return "\n".join(lines)

    num = tpl.get("num_id", "?")
    tname = tpl.get("name", "?")[:24]
    lines.append(f"🎬 قالب #{num} — <b>{esc(tname)}</b>")
    lines.append("")

    cur_sec = v25_phase_section(phase)
    section_order = ["channel", "profile", "pv", "joiner", "sender", "lefter"]

    def _sec_done(target):
        if cur_sec == "done": return True
        try: return section_order.index(cur_sec or "") > section_order.index(target)
        except Exception: return False

    def _sec_active(target): return cur_sec == target

    tpl_ch = tpl.get("channel") or {}
    if tpl_ch.get("title"):
        lines.append("📢 <b>کانال</b>")
        ch_done = _sec_done("channel"); ch_active = _sec_active("channel")
        if ch_active: lines.append("  ⏳ در حال ساخت...")
        elif ch_done: lines.append("  ✅ ساخته شد")
        else: lines.append("  ⏳ در انتظار")
        chans = acc.get("channels") or []
        for c in chans:
            if c.get("title"):
                lines.append(f"  📝 {esc(str(c.get('title'))[:20])}")
                if c.get("username"): lines.append(f"  🔤 @{esc(c['username'])}")
                if c.get("join_link"): lines.append("  🔗 ✅")
                break
        if tpl_ch.get("initial_messages"):
            status = "✅" if ch_done else ("⏳" if ch_active else "—")
            lines.append(f"  📨 پیام‌های اولیه: {status} ({len(tpl_ch['initial_messages'])})")
        if tpl_ch.get("photo_file"):
            status = "✅" if ch_done else ("⏳" if ch_active else "—")
            lines.append(f"  🖼 عکس: {status}")
        lines.append("")

    tpl_pr = tpl.get("profile") or {}
    if tpl_pr.get("first_name") or tpl_pr.get("last_name") or tpl_pr.get("bio") or tpl_pr.get("photo_file"):
        lines.append("👤 <b>پروفایل</b>")
        pr_done = _sec_done("profile"); pr_active = _sec_active("profile")
        st = "✅" if pr_done else ("⏳" if pr_active else "—")
        if tpl_pr.get("first_name"): lines.append(f"  نام: {st}")
        if tpl_pr.get("last_name"): lines.append(f"  فامیل: {st}")
        if tpl_pr.get("bio"): lines.append(f"  بیو: {st}")
        if tpl_pr.get("photo_file"): lines.append(f"  عکس: {st}")
        if tpl_pr.get("username"): lines.append(f"  یوزرنیم: {st}")
        lines.append("")

    tpl_pv = tpl.get("pv") or {}
    if tpl_pv.get("enabled") and tpl_pv.get("items"):
        lines.append("💬 <b>PV</b>")
        pv_done = _sec_done("pv"); pv_active = _sec_active("pv")
        st = "✅" if (pv_done or pv_active) else "—"
        lines.append(f"  فعال: {st}")
        lines.append(f"  پیام‌ها: {len(tpl_pv['items'])}")
        lines.append("")

    tpl_jn = tpl.get("joiner") or {}
    max_join = int(tpl_jn.get("max_join", 0) or 0)
    if max_join > 0:
        lines.append("🤝 <b>جوینر</b>")
        j = prog.get("joined", 0); f = prog.get("failed", 0); alr = prog.get("already", 0)
        pct = int((j / max_join * 100) if max_join else 0)
        lines.append(f"  🎯 سقف: {max_join}")
        lines.append(f"  ✓ {j} · ♻️ {alr} · ✗ {f}")
        lines.append(f"  <code>{_v25_bar(pct)}</code>")
        if prog.get("wave"): lines.append(f"  🌊 موج: {prog['wave']}")
        lines.append("")

    tpl_sn = tpl.get("sender") or {}
    if tpl_sn.get("text") or tpl_sn.get("attach_file"):
        lines.append("📤 <b>ارسال</b>")
        pv_s = prog.get("pv_sent", 0); pv_f = prog.get("pv_failed", 0)
        grp_s = prog.get("grp_sent", 0); grp_f = prog.get("grp_failed", 0)
        total_s = pv_s + grp_s; total_f = pv_f + grp_f
        all_t = total_s + total_f
        pct = int((total_s / all_t * 100) if all_t else 0)
        if pv_s or pv_f: lines.append(f"  💬 PV: ✓{pv_s} ✗{pv_f}")
        if grp_s or grp_f: lines.append(f"  👥 GRP: ✓{grp_s} ✗{grp_f}")
        if not (pv_s or pv_f or grp_s or grp_f):
            lines.append(f"  ⏳ در انتظار")
        else:
            lines.append(f"  <code>{_v25_bar(pct)}</code>")
        lines.append("")

    if phase:
        lines.append(f"📍 <i>{esc(str(phase)[:70])}</i>")

    err = info.get("last_error")
    if err: lines.append(f"⚠️ <code>{esc(err[:100])}</code>")

    return "\n".join(lines)

async def v25_show_account_detail(cid, aid, edit_mid=None):
    info = ASST_RUNNING.get(f"soroosh:{aid}")
    if not info:
        if TG_APP:
            try: await TG_APP.bot.send_message(cid, "⚠️ اکانت در حال اجرا نیست")
            except Exception: pass
        return
    tpl = None
    try:
        if sr and info.get("tid"): tpl = sr.get_template(info["tid"])
    except Exception: pass
    op = None
    try:
        if sr and info.get("current_op_id"): op = sr._get_op(info["current_op_id"])
    except Exception: pass
    txt = v25_build_account_detail(aid, info, tpl, op)
    rows = [
        [B("🔄 بروزرسانی", f"asst:acc:soroosh:{aid}")],
        [B("🛑 توقف این اکانت", f"asst:acc_stop:soroosh:{aid}")],
        [B("« بازگشت", "asst:dash:plat:soroosh")],
    ]
    markup = kb_(*rows)
    if edit_mid and TG_APP:
        try:
            await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt[:4000],
                                               reply_markup=markup, parse_mode="HTML",
                                               disable_web_page_preview=True)
            return
        except Exception as e:
            if "not modified" in str(e).lower(): return
    if TG_APP:
        try:
            await TG_APP.bot.send_message(cid, txt[:4000], reply_markup=markup,
                                          parse_mode="HTML", disable_web_page_preview=True)
        except Exception: pass

async def v25_show_bulk_ops(cid, edit_mid=None):
    sr_n = len(sr.list_accounts()) if sr else 0
    txt = ("🚀 <b>عملیات گروهی</b>\n━━━━━━━━━━━━━━━\n\n"
           "<i>عملیات روی همه اکانت‌های سروش با تنظیمات قالب فعال</i>\n\n")
    if sr_n: txt += f"🌀 سروش: <b>{sr_n}</b> اکانت\n"
    rows = []
    if sr_n:
        rows.append([B(f"🌀 سروش ({sr_n})", "asst:bulk:menu:soroosh")])
    rows.append([B("« بازگشت", "asst:refresh")])
    markup = kb_(*rows)
    if edit_mid and TG_APP:
        try:
            await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt[:4000],
                                               reply_markup=markup, parse_mode="HTML",
                                               disable_web_page_preview=True)
            return
        except Exception as e:
            if "not modified" in str(e).lower(): return
    if TG_APP:
        try:
            await TG_APP.bot.send_message(cid, txt[:4000], reply_markup=markup,
                                          parse_mode="HTML", disable_web_page_preview=True)
        except Exception: pass

async def v25_show_bulk_platform(cid, edit_mid=None):
    n_accs = 0; tpl = None
    try:
        if sr: n_accs = len(sr.list_accounts())
    except Exception: pass
    cfg = asst_load_cfg()
    tid = cfg.get("run_template_id_soroosh")
    if tid and sr:
        try: tpl = sr.get_template(tid)
        except Exception: pass
    txt = f"🌀 <b>سروش — عملیات گروهی</b>\n━━━━━━━━━━━━━━━\n\n"
    txt += f"👥 تعداد: <b>{n_accs}</b>\n"
    if tpl:
        txt += f"🎬 قالب: <b>#{tpl.get('num_id','?')} {esc(tpl.get('name','?')[:20])}</b>\n"
    else:
        txt += "⚠️ هیچ قالبی انتخاب نشده\n"
    rows = [
        [B("🤝 جوین همه", "asst:bulk:join:soroosh")],
        [B("📤 ارسال همه", "asst:bulk:send:soroosh")],
        [B("🚪 ترک همه", "asst:bulk:leave:soroosh")],
        [B("« بازگشت", "asst:bulk")],
    ]
    markup = kb_(*rows)
    if edit_mid and TG_APP:
        try:
            await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt[:4000],
                                               reply_markup=markup, parse_mode="HTML",
                                               disable_web_page_preview=True)
            return
        except Exception as e:
            if "not modified" in str(e).lower(): return
    if TG_APP:
        try:
            await TG_APP.bot.send_message(cid, txt[:4000], reply_markup=markup,
                                          parse_mode="HTML", disable_web_page_preview=True)
        except Exception: pass

async def v25_run_bulk_op(cid, op_type):
    if sr is None:
        if TG_APP:
            try: await TG_APP.bot.send_message(cid, "❌ سروش لود نشده")
            except Exception: pass
        return
    cfg = asst_load_cfg()
    tid = cfg.get("run_template_id_soroosh")
    if not tid:
        if TG_APP:
            try: await TG_APP.bot.send_message(cid, "❌ اول یک قالب انتخاب کن")
            except Exception: pass
        return
    tpl = None
    try: tpl = sr.get_template(tid)
    except Exception: pass
    if not tpl:
        if TG_APP:
            try: await TG_APP.bot.send_message(cid, "❌ قالب پیدا نشد")
            except Exception: pass
        return
    try: accounts = list(sr.list_accounts().keys())
    except Exception: accounts = []
    if not accounts:
        if TG_APP:
            try: await TG_APP.bot.send_message(cid, "❌ هیچ اکانتی نیست")
            except Exception: pass
        return
    oid_prefix = {"join":"jl","send":"sd","leave":"lf"}.get(op_type, "op")
    op = {
        "id": f"{oid_prefix}_" + secrets.token_hex(5),
        "created": int(time.time()),
        "type": {"join":"joinlef","send":"send","leave":"lefter"}.get(op_type, "send"),
        "accounts": accounts, "status": "running", "_asst": True,
        "progress": {"joined":0,"failed":0,"total":0,"pending":0,"in_progress":0,
                     "phase":"bulk-start","sent":0,"already":0,"tried":0,"wave":0,
                     "left":0,"round":0,"skipped_seen":0,"skipped_banned":0,"rejected":0,
                     "extracted":0,"lds_done":0,"pv_sent":0,"pv_failed":0,
                     "grp_sent":0,"grp_failed":0},
        "errors": [],
    }
    try:
        if op_type == "join":
            jn = tpl.get("joiner") or {}
            op["max_join"] = int(jn.get("max_join", 0) or 0)
            op["groups_only"] = bool(jn.get("groups_only", True))
            op["join_delay"] = {"ultra":0.3,"fast":1.0,"normal":3.0,"slow":8.0}.get(jn.get("speed","fast"),1.0)
            op["wave_size"] = 50; op["extract_limit"] = 300
            op["link_donies"] = list(sr.load_link_donies())
            runner = getattr(sr, "run_joiner_lefter", None)
        elif op_type == "send":
            snd = tpl.get("sender") or {}
            op["payload"] = {"text": snd.get("text") or "سلام"}
            op["target"] = snd.get("target", "both")
            op["max"] = int(snd.get("max_send", 0) or 0)
            op["delay"] = float(snd.get("delay", 1.5))
            op["groups_only"] = bool((tpl.get("joiner") or {}).get("groups_only", True))
            op["attach_file"] = snd.get("attach_file") or ""
            op["infinite_loop"] = False; op["loop_delay"] = 3.0
            op["rescan_targets"] = True
            runner = getattr(sr, "run_sender", None)
        elif op_type == "leave":
            lf = tpl.get("lefter") or {}
            op["leave_mode"] = lf.get("leave_mode") or "all"
            op["delay"] = 0.8
            runner = getattr(sr, "run_lefter", None)
        else: return
        if not runner:
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, f"❌ runner برای {op_type} نیست")
                except Exception: pass
            return
        try: sr._save_op(op)
        except Exception: pass
        asyncio.create_task(runner(op, log_print))
        if TG_APP:
            try:
                await TG_APP.bot.send_message(
                    cid, f"✅ عملیات {op_type} روی {len(accounts)} اکانت سروش شروع شد\n🪪 <code>{op['id']}</code>",
                    parse_mode="HTML")
            except Exception: pass
    except Exception as e:
        log_print(f"[bulk-op] {op_type}: {type(e).__name__}: {e}")
        if TG_APP:
            try: await TG_APP.bot.send_message(cid, f"❌ {type(e).__name__}: {str(e)[:200]}")
            except Exception: pass

# ═══════════════ SMS STATS — ACCURATE + SORTED ═══════════════
async def v25_show_sms_stats(cid, page=0, edit_mid=None):
    """Accurate per-phone SMS stats — sorted by status, then time."""

    # Collect entries from current session batches + persistent history
    entries = []

    # Current session
    for bk, b in ASST_BATCHES.items():
        for ph in b.get("phones", []):
            v = b.get("results", {}).get(ph, {})
            entries.append({
                "phone": ph,
                "uid": b.get("user_id"),
                "send_type": v.get("send_type", "unknown"),
                "force_attempted": v.get("force_attempted", False),
                "force_success": v.get("force_success", False),
                "status": v.get("status", "unknown"),
                "ok": v.get("ok", False),
                "ts": int(v.get("sent_at", b.get("started", 0))),
                "session": True,
            })

    # Historical
    seen_phones = {(e["phone"], e["ts"]) for e in entries}
    for h in ASST_SMS_HISTORY[-300:]:
        key = (h.get("phone"), h.get("ts"))
        if key in seen_phones: continue
        entries.append({
            "phone": h.get("phone"),
            "uid": h.get("uid"),
            "send_type": h.get("send_type", "unknown"),
            "force_attempted": h.get("force_attempted", False),
            "force_success": h.get("force_success", False),
            "status": h.get("status", "unknown"),
            "ok": h.get("status") == "confirmed",
            "ts": h.get("ts", 0),
            "session": False,
        })

    # Sort: awaiting first (needs attention), then confirmed, then giveup; each by most recent
    def _sort_key(e):
        order = {
            "awaiting_code": 0, "retrying": 1,
            "confirmed": 2,
            "giveup": 3, "failed": 4,
        }
        return (order.get(e["status"], 5), -e["ts"])
    entries.sort(key=_sort_key)

    # Aggregate
    total = len(entries)
    sms_count = sum(1 for e in entries if e["send_type"] == "sms")
    app_count = sum(1 for e in entries if e["send_type"] in ("برنامه", "app"))
    call_count = sum(1 for e in entries if e["send_type"] in ("تماس", "call"))
    email_count = sum(1 for e in entries if e["send_type"] == "email")
    unknown_count = total - sms_count - app_count - call_count - email_count

    confirmed = sum(1 for e in entries if e["ok"] or e["status"] == "confirmed")
    awaiting = sum(1 for e in entries if e["status"] == "awaiting_code")
    retrying = sum(1 for e in entries if e["status"] == "retrying")
    giveup = sum(1 for e in entries if e["status"] == "giveup")
    failed = sum(1 for e in entries if e["status"] == "failed")

    force_att = sum(1 for e in entries if e["force_attempted"])
    force_ok = sum(1 for e in entries if e["force_success"])

    def _pct(n): return int(100 * n / total) if total else 0

    txt = f"📨 <b>آمار پیامک</b>\n{'━'*30}\n\n"

    txt += f"<b>📊 کل ارسال‌ها:</b> <b>{total}</b>\n"
    if total:
        txt += f"🟢 SMS: <b>{sms_count}</b> ({_pct(sms_count)}%)\n"
        txt += f"🟡 App: <b>{app_count}</b> ({_pct(app_count)}%)\n"
        if call_count: txt += f"🔵 Call: <b>{call_count}</b> ({_pct(call_count)}%)\n"
        if email_count: txt += f"📧 Email: <b>{email_count}</b>\n"
        if unknown_count: txt += f"⚪ Unknown: <b>{unknown_count}</b>\n"

    txt += f"\n<b>📈 وضعیت ورود:</b>\n"
    txt += f"✅ تایید شده: <b>{confirmed}</b>\n"
    if awaiting: txt += f"⏳ در انتظار کد: <b>{awaiting}</b>\n"
    if retrying: txt += f"🔄 در حال تلاش: <b>{retrying}</b>\n"
    if giveup: txt += f"❌ بی‌پاسخ: <b>{giveup}</b>\n"
    if failed: txt += f"⚠️ خطا: <b>{failed}</b>\n"

    if force_att:
        txt += f"\n<b>🔄 تلاش SMS:</b>\n"
        txt += f"کل: <b>{force_att}</b> · موفق: <b>{force_ok}</b>"
        if force_att:
            txt += f" ({int(100 * force_ok / force_att)}%)"
        txt += "\n"

    # Per-phone list
    PER = 15
    pages = max(1, -(-total // PER))
    page = max(0, min(page, pages - 1))
    chunk = entries[page * PER:(page + 1) * PER]

    if chunk:
        txt += f"\n<b>📋 لیست ({page+1}/{pages}):</b>\n\n"
        for e in chunk:
            st_label = _send_type_label(e["send_type"])
            st = e["status"]
            if e["ok"] or st == "confirmed": icon = "✅"
            elif st == "awaiting_code": icon = "⏳"
            elif st == "retrying": icon = "🔄"
            elif st == "giveup": icon = "❌"
            elif st == "failed": icon = "⚠️"
            else: icon = "⚪"

            force_mark = ""
            if e["force_attempted"]:
                force_mark = " 🔄✓" if e["force_success"] else " 🔄✗"

            ago = _eta(time.time() - e["ts"]) if e["ts"] else "—"
            uid_short = ""
            if e.get("uid"):
                uid_short = f" · <code>{esc(str(e['uid'])[:16])}</code>"

            txt += f"{icon} <code>{esc(e['phone'])}</code> — {st_label}{force_mark}\n"
            txt += f"   <i>{ago}</i>{uid_short}\n"
    else:
        txt += f"\n<i>هیچ ارسالی ثبت نشده</i>"

    rows = []
    if pages > 1:
        pr = []
        if page > 0: pr.append(B("◀️", f"asst:stats:sms:{page-1}"))
        pr.append(B(f"{page+1}/{pages}", "noop"))
        if page < pages - 1: pr.append(B("▶️", f"asst:stats:sms:{page+1}"))
        rows.append(pr)
    rows.append([B("🔄 بروزرسانی", f"asst:stats:sms:{page}"),
                 B("🗑 پاک کردن", "asst:stats:clear")])
    rows.append([B("« بازگشت", "asst:menu:stats")])
    markup = kb_(*rows)

    if edit_mid and TG_APP:
        try:
            await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt[:4000],
                                               reply_markup=markup, parse_mode="HTML",
                                               disable_web_page_preview=True)
            return
        except Exception as e:
            if "not modified" in str(e).lower(): return
    if TG_APP:
        try:
            await TG_APP.bot.send_message(cid, txt[:4000], reply_markup=markup,
                                          parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e: log_print(f"[stats-sms] {e}")

async def v25_show_menu_settings(cid, edit_mid=None):
    cfg = asst_load_cfg()
    force_on = "🟢" if cfg.get("force_sms", True) else "⚪"
    txt = (f"⚙️ <b>تنظیمات</b>\n━━━━━━━━━━━━━━━\n\n"
           f"💬 گروه: <code>{esc(str(cfg.get('group_id') or '—'))}</code>\n"
           f"🔢 حداکثر: <b>{cfg.get('max_accounts', 50)}</b>\n"
           f"⏱ مدت: <b>{cfg.get('template_duration_hours', 6)}h</b>\n"
           f"🔄 تلاش SMS: {force_on}\n"
           f"   تلاش‌ها: <b>{cfg.get('force_sms_max_retries', 1)}</b>\n"
           f"   تاخیر: <b>{cfg.get('force_sms_delay_s', 10)}s</b>")
    rows = [
        [B("💬 گروه", "asst:set_group"), B("🔢 حداکثر", "asst:set_max")],
        [B(f"⏱ {cfg.get('template_duration_hours', 6)}h", "asst:set_hours")],
        [B(f"🔄 تلاش SMS: {'🟢' if cfg.get('force_sms', True) else '⚪'}", "asst:toggle_force_sms")],
        [B(f"🔁 تلاش‌ها: {cfg.get('force_sms_max_retries', 1)}", "asst:set_force_retries"),
         B(f"⏱ تاخیر: {cfg.get('force_sms_delay_s', 10)}s", "asst:set_force_delay")],
        [B("⏸ توقف پذیرش" if cfg.get("accept_new_accounts", True) else "▶️ شروع پذیرش", "asst:toggle_accept")],
        [B("« بازگشت", "asst:refresh")],
    ]
    markup = kb_(*rows)
    if edit_mid and TG_APP:
        try: await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt,
                                                reply_markup=markup, parse_mode="HTML",
                                                disable_web_page_preview=True); return
        except Exception: pass
    if TG_APP:
        try: await TG_APP.bot.send_message(cid, txt, reply_markup=markup,
                                           parse_mode="HTML", disable_web_page_preview=True)
        except Exception: pass

async def v25_show_menu_templates(cid, edit_mid=None):
    cfg = asst_load_cfg()
    tid = cfg.get("run_template_id_soroosh")
    tpl_name = "—"
    if tid and sr:
        try:
            t = sr.get_template(tid)
            if t: tpl_name = f"#{t.get('num_id','?')} {t.get('name','?')[:16]}"
        except Exception: pass
    txt = (f"🎬 <b>قالب سروش</b>\n━━━━━━━━━━━━━━━\n\n"
           f"🌀 قالب: <b>{esc(tpl_name)}</b>\n\n"
           f"🎯 در حال اجرا: <b>{len(ASST_RUNNING)}</b>")
    rows = [
        [B("🌀 انتخاب قالب سروش", "asst:set_tpl:soroosh")],
        [B("🔄 شروع مجدد", "asst:restart_all"), B("🛑 توقف", "asst:stop_all")],
        [B("« بازگشت", "asst:refresh")],
    ]
    markup = kb_(*rows)
    if edit_mid and TG_APP:
        try: await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt,
                                                reply_markup=markup, parse_mode="HTML",
                                                disable_web_page_preview=True); return
        except Exception: pass
    if TG_APP:
        try: await TG_APP.bot.send_message(cid, txt, reply_markup=markup,
                                           parse_mode="HTML", disable_web_page_preview=True)
        except Exception: pass

async def v25_show_menu_stats(cid, edit_mid=None):
    pend = len([k for k in ASST_PENDING if not ASST_PENDING[k].get("confirmed")])
    errs = sum(len(e) for e in ASST_BATCH_ERRORS.values())
    act = len([k for k in ASST_BATCHES if not ASST_BATCHES[k].get("done")])
    txt = (f"📊 <b>آمار و لاگ‌ها</b>\n━━━━━━━━━━━━━━━\n\n"
           f"⏳ در انتظار کد: <b>{pend}</b>\n"
           f"⚙️ بچ فعال: <b>{act}</b>\n"
           f"🎬 در حال اجرا: <b>{len(ASST_RUNNING)}</b>\n"
           f"⚠️ خطاها: <b>{errs}</b>\n"
           f"🔖 شناسه‌ها: <b>{len(ASST_SEEN)}</b>")
    rows = [
        [B("📨 آمار پیامک (دقیق)", "asst:stats:sms")],
        [B("📋 لاگ‌ها", "asst:logs"), B("🔄 پاک pending", "asst:clear_pending")],
        [B("« بازگشت", "asst:refresh")],
    ]
    markup = kb_(*rows)
    if edit_mid and TG_APP:
        try: await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt,
                                                reply_markup=markup, parse_mode="HTML",
                                                disable_web_page_preview=True); return
        except Exception: pass
    if TG_APP:
        try: await TG_APP.bot.send_message(cid, txt, reply_markup=markup,
                                           parse_mode="HTML", disable_web_page_preview=True)
        except Exception: pass

async def asst_show_panel(cid, edit_mid=None):
    return await v25_show_main(cid, edit_mid)

async def asst_show_logs(cid, page=0):
    logs = list(LOGS[-100:])
    for bk, errs in ASST_BATCH_ERRORS.items():
        for e in errs[-10:]:
            logs.append({"text": f"[batch {bk[-4:]}] {e}", "ts": time.time()})
    logs.sort(key=lambda x: x.get("ts", 0)); logs = logs[-100:]
    PER = 15; pages = max(1, -(-len(logs) // PER)); page = max(0, min(page, pages - 1))
    chunk = logs[page * PER:(page + 1) * PER]
    txt = f"📋 <b>لاگ‌های دستیار</b> — {len(logs)} خط آخر\n━━━━━━━━━━━━━\n\n"
    if not chunk: txt += "<i>خالی</i>"
    for lg in chunk:
        t = time.strftime("%H:%M:%S", time.localtime(lg.get("ts", 0)))
        line = str(lg.get("text", ""))[:150]
        txt += f"<code>{t}</code> {esc(line)}\n"
    nav_btns = []
    if pages > 1:
        pr = []
        if page > 0: pr.append(B("◀️", f"asst:logs:{page-1}"))
        pr.append(B(f"{page+1}/{pages}", "noop"))
        if page < pages - 1: pr.append(B("▶️", f"asst:logs:{page+1}"))
        nav_btns.append(pr)
    nav_btns.append([B("🔄 بروزرسانی", f"asst:logs:{page}"), B("« بازگشت", "asst:refresh")])
    if TG_APP:
        try:
            await TG_APP.bot.send_message(cid, txt[:4000], reply_markup=kb_(*nav_btns),
                                          parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e: log_print(f"[asst-logs] {e}")

async def asst_route_cb(cid, data):
    try:
        cfg = asst_load_cfg()

        if data == "asst:menu:settings": return await v25_show_menu_settings(cid)
        if data == "asst:menu:templates": return await v25_show_menu_templates(cid)
        if data == "asst:menu:stats": return await v25_show_menu_stats(cid)
        if data == "asst:refresh": return await v25_show_main(cid)
        if data == "asst:dash": return await v25_show_dashboard(cid)
        if data.startswith("asst:dash:plat:"):
            return await v25_show_dash_platform(cid)
        if data == "asst:bulk": return await v25_show_bulk_ops(cid)
        if data.startswith("asst:bulk:menu:"):
            return await v25_show_bulk_platform(cid)
        if data.startswith("asst:bulk:"):
            parts = data.split(":")
            if len(parts) >= 4:
                op_type = parts[2]
                return await v25_run_bulk_op(cid, op_type)

        if data.startswith("asst:acc_stop:"):
            parts = data.split(":")
            if len(parts) >= 4:
                aid = parts[3]
                key = f"soroosh:{aid}"
                info = ASST_RUNNING.get(key)
                if info:
                    ev = info.get("stop")
                    if ev:
                        try: ev.set()
                        except Exception: pass
                    t = info.get("task")
                    if t and not t.done():
                        try: t.cancel()
                        except Exception: pass
                    ASST_RUNNING.pop(key, None)
                    asst_save_running_state()
                    if TG_APP:
                        try: await TG_APP.bot.send_message(cid, f"🛑 متوقف شد: {aid[:12]}")
                        except Exception: pass
                return await v25_show_dash_platform(cid)
        if data.startswith("asst:acc:"):
            parts = data.split(":")
            if len(parts) >= 4:
                aid = parts[3]
                return await v25_show_account_detail(cid, aid)

        if data.startswith("asst:stats:sms"):
            parts = data.split(":")
            pg = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            return await v25_show_sms_stats(cid, pg)
        if data == "asst:stats:clear":
            ASST_SMS_HISTORY.clear(); _save_sms_history(ASST_SMS_HISTORY)
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "🗑 آمار پاک شد")
                except Exception: pass
            return await v25_show_sms_stats(cid, 0)

        if data == "asst:toggle":
            cfg["enabled"] = not cfg.get("enabled"); asst_save_cfg(cfg)
            return await v25_show_main(cid)
        if data == "asst:toggle_accept":
            cfg["accept_new_accounts"] = not cfg.get("accept_new_accounts", True)
            asst_save_cfg(cfg); return await v25_show_main(cid)
        if data == "asst:toggle_force_sms":
            cfg["force_sms"] = not cfg.get("force_sms", True)
            asst_save_cfg(cfg); return await v25_show_menu_settings(cid)
        if data == "asst:set_force_retries":
            ASST_WAITING[cid] = {"kind": "force_retries"}
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "🔁 تعداد تلاش (1-5):")
                except Exception: pass
            return
        if data == "asst:set_force_delay":
            ASST_WAITING[cid] = {"kind": "force_delay"}
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "⏱ تاخیر بین تلاش‌ها (ثانیه):")
                except Exception: pass
            return
        if data == "asst:set_group":
            ASST_WAITING[cid] = {"kind": "group"}
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "💬 شناسه گروه:")
                except Exception: pass
            return
        if data == "asst:set_max":
            ASST_WAITING[cid] = {"kind": "max"}
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "🔢 حداکثر اکانت (1-50):")
                except Exception: pass
            return
        if data == "asst:set_hours":
            ASST_WAITING[cid] = {"kind": "hours"}
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "⏱ چند ساعت؟ (1-48):")
                except Exception: pass
            return

        if data == "asst:logs": await asst_show_logs(cid, 0); return
        if data.startswith("asst:logs:"):
            try: page = int(data.split(":", 2)[2])
            except Exception: page = 0
            await asst_show_logs(cid, page); return

        if data.startswith("asst:set_tpl:"):
            if sr is None:
                if TG_APP:
                    try: await TG_APP.bot.send_message(cid, "❌ سروش لود نشده")
                    except Exception: pass
                return
            try: tpls = sr.list_templates()
            except Exception: tpls = {}
            if not tpls:
                if TG_APP:
                    try: await TG_APP.bot.send_message(cid, "قالبی برای سروش نیست.")
                    except Exception: pass
                return
            rows = []
            for tid, t in list(tpls.items())[:12]:
                num = t.get("num_id", "?"); name = t.get("name", "?")[:24]
                rows.append([B(f"#{num} 🎯 {name}", f"asst:tpl_pick:soroosh:{tid}")])
            rows.append([B("❌ بدون قالب", "asst:tpl_pick:soroosh:none")])
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "🎬 قالب سروش:", reply_markup=kb_(*rows))
                except Exception: pass
            return
        if data.startswith("asst:tpl_pick:"):
            parts = data.split(":", 3)
            if len(parts) < 4: return
            tid = parts[3]
            cfg["run_template_id_soroosh"] = None if tid == "none" else tid
            asst_save_cfg(cfg)
            started = 0
            if cfg.get("enabled") and tid != "none":
                if sr:
                    hours = int(cfg.get("template_duration_hours", 6))
                    try:
                        for aid in sr.list_accounts():
                            if asst_start_one(aid, tid, hours): started += 1
                    except Exception as e: log_print(f"[asst-tpl-pick] {e}")
            if TG_APP and tid != "none":
                try:
                    await TG_APP.bot.send_message(cid,
                        f"✅ قالب سروش ذخیره · 🎬 {started} اکانت استارت شد",
                        parse_mode="HTML")
                except Exception: pass
            return await v25_show_main(cid)

        if data == "asst:restart_all":
            n = await asst_restart_all()
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, f"🔄 شروع {n} اکانت")
                except Exception: pass
            return await v25_show_main(cid)
        if data == "asst:stop_all":
            await asst_stop_all()
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "🛑 همه متوقف شد")
                except Exception: pass
            return await v25_show_main(cid)
        if data == "asst:stats": await asst_stats_to(cid); return
        if data == "asst:clear_pending":
            ASST_PENDING.clear(); ASST_BATCH_ERRORS.clear()
            for b in ASST_BATCHES.values():
                b["done"] = True
                ev = b.get("stop")
                if ev:
                    try: ev.set()
                    except Exception: pass
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "🔄 پاک شد")
                except Exception: pass
            return await v25_show_main(cid)
    except Exception as e:
        log_print(f"[asst-route] FATAL: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        if TG_APP:
            try:
                await TG_APP.bot.send_message(cid,
                    f"❌ {type(e).__name__}: {str(e)[:200]}", parse_mode="HTML")
            except Exception: pass

async def asst_handle_force(q, data):
    parts = data.split(":", 4)
    if len(parts) < 4: return
    uid = parts[3]
    cached = ASST_USER_CACHE.get(uid)
    if not cached:
        try: await q.answer("❌ پیام کش نشده", show_alert=True)
        except Exception: pass
        return
    try: await q.answer("⏳ شروع...")
    except Exception: pass
    chat_id = q.message.chat_id if q.message else 0
    bk = "b_" + secrets.token_hex(4)
    ASST_TASKS[bk] = asyncio.create_task(
        asst_safe_batch(bk, chat_id, cached["source"], cached["phones"], uid))

async def asst_handle_wait(cid, w, msg):
    cfg = asst_load_cfg()
    text = (msg.text or "").strip()
    kind = w.get("kind")
    if kind == "group":
        try: gid = int(text)
        except Exception:
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "❌ عدد معتبر نیست")
                except Exception: pass
            return
        cfg["group_id"] = gid; asst_save_cfg(cfg)
        if TG_APP:
            try: await TG_APP.bot.send_message(cid, f"✅ گروه: <code>{gid}</code>", parse_mode="HTML")
            except Exception: pass
        await v25_show_main(cid)
    elif kind == "max":
        try: v = max(1, min(50, int(text)))
        except Exception:
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "❌ عدد 1-50")
                except Exception: pass
            return
        cfg["max_accounts"] = v; asst_save_cfg(cfg)
        if TG_APP:
            try: await TG_APP.bot.send_message(cid, f"✅ {v}")
            except Exception: pass
        await v25_show_main(cid)
    elif kind == "hours":
        try: h = max(1, min(48, int(text)))
        except Exception:
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "❌ عدد 1-48")
                except Exception: pass
            return
        cfg["template_duration_hours"] = h; asst_save_cfg(cfg)
        if TG_APP:
            try: await TG_APP.bot.send_message(cid, f"✅ {h} ساعت")
            except Exception: pass
        await v25_show_main(cid)
    elif kind == "force_retries":
        try: v = max(1, min(5, int(text)))
        except Exception:
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "❌ عدد 1-5")
                except Exception: pass
            return
        cfg["force_sms_max_retries"] = v; asst_save_cfg(cfg)
        if TG_APP:
            try: await TG_APP.bot.send_message(cid, f"✅ {v} تلاش")
            except Exception: pass
        await v25_show_menu_settings(cid)
    elif kind == "force_delay":
        try: v = max(5, min(60, int(text)))
        except Exception:
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "❌ عدد 5-60")
                except Exception: pass
            return
        cfg["force_sms_delay_s"] = v; asst_save_cfg(cfg)
        if TG_APP:
            try: await TG_APP.bot.send_message(cid, f"✅ {v} ثانیه")
            except Exception: pass
        await v25_show_menu_settings(cid)

async def asst_cleanup_loop():
    while True:
        await asyncio.sleep(300)
        try: asst_cleanup_ops()
        except Exception: pass
        try:
            now = time.time()
            for k, v in list(ASST_PENDING.items()):
                if now - v.get("sent_at", now) > 900:
                    ASST_PENDING.pop(k, None)
                    log_print(f"[asst] cleanup old pending: {k}")
        except Exception: pass

def _wipe_accounts_and_sessions():
    """V35_FINAL — wipe accounts.json + sessions + ops on startup"""
    if sr is None:
        return {"error": "sr_not_loaded"}
    deleted = {"accounts": False, "sessions": 0, "pending": 0, "ops": False}
    try:
        if os.path.exists(sr.ACC_FILE):
            os.remove(sr.ACC_FILE)
            deleted["accounts"] = True
    except Exception as e:
        log_print(f"[v35-wipe] accounts: {e}")
    try:
        sd = sr._get_sessions_dir()
        if os.path.isdir(sd):
            for fn in os.listdir(sd):
                full = os.path.join(sd, fn)
                if fn.startswith("spluslib_") and ".session" in fn:
                    try: os.remove(full); deleted["sessions"] += 1
                    except Exception: pass
                elif fn.startswith("_pending_"):
                    try: os.remove(full); deleted["pending"] += 1
                    except Exception: pass
    except Exception as e:
        log_print(f"[v35-wipe] sessions: {e}")
    try:
        sr._save_ops([])
        deleted["ops"] = True
    except Exception: pass
    try:
        ASST_RUNNING.clear()
        ASST_PENDING.clear()
        ASST_BATCHES.clear()
        ASST_TASKS.clear()
        ASST_USER_CACHE.clear()
        for _k in list(ASST_BATCH_ERRORS.keys()):
            ASST_BATCH_ERRORS.pop(_k, None)
    except Exception: pass
    return deleted


async def asst_on_startup():
    try:
        cfg = asst_load_cfg()
        log_print(f"[asst] startup: enabled={cfg.get('enabled')}")
        log_print(f"[asst]   tpl_soroosh={cfg.get('run_template_id_soroosh')}")
        log_print(f"[asst]   force_sms={cfg.get('force_sms')}")
        
        # V35_FINAL — wipe accounts on startup (default ON)
        if cfg.get("wipe_accounts_on_startup", True):
            try:
                _w = _wipe_accounts_and_sessions()
                log_print(f"[v35] WIPED: {_w}")
            except Exception as _we:
                log_print(f"[v35] wipe fail: {_we}")
        
        # V35_FINAL — no auto-start on boot
        if not cfg.get("auto_start_on_boot", False):
            log_print("[v35] auto-start DISABLED — start manually from panel")
            return
        if not cfg.get("enabled"): return
        n = await asst_start_all()
        log_print(f"[asst] startup: started {n}")
        saved = asst_load_running_state()
        for key, info in saved.items():
            cur = ASST_RUNNING.get(key)
            if cur and isinstance(info, dict):
                try:
                    cur["runs"] = int(info.get("runs", 0))
                    cur["started"] = float(info.get("started", cur["started"]))
                except Exception: pass
        asst_save_running_state()
    except Exception as e:
        log_print(f"[asst-startup] FAILED: {type(e).__name__}: {e}")

# ═══════════════ COMMANDS ═══════════════
async def cmd_start(update, context):
    cid = update.effective_chat.id
    if cid != FORCED_OWNER:
        try: await update.message.reply_text("⛔ خصوصی است.")
        except Exception: pass
        return
    USER_MODE.pop(cid, None)
    for mod in (rb, sr, ei):
        if mod is None: continue
        try: mod.STATE["panel"].pop(cid, None)
        except Exception: pass
    mid = await _render_mode_selector(cid)
    if mid:
        for mod in (rb, sr, ei):
            if mod is None: continue
            try: mod.STATE["panel"][cid] = mid
            except Exception: pass

async def cmd_menu(update, context):
    if not authorized(update): return
    await cmd_start(update, context)

async def cmd_version(update, context):
    if not authorized(update): return
    sr_v = getattr(sr, "VERSION", "—") if sr else "—"
    rb_v = getattr(rb, "VERSION", "—") if rb else "—"
    ei_v = getattr(ei, "VERSION", "—") if ei else "—"
    txt = (f"🔖 <b>app.py</b>: v26\n"
           f"🌀 <b>سروش</b>: {sr_v}\n"
           f"📱 <b>روبیکا</b>: {rb_v}\n"
           f"📨 <b>ایتا</b>: {ei_v}\n"
           f"👤 <b>مالک</b>: <code>{FORCED_OWNER}</code>\n"
           f"🎬 <b>در حال اجرا</b>: {len(ASST_RUNNING)}")
    await update.message.reply_text(txt, parse_mode="HTML")

async def cb_router(update, context):
    q = update.callback_query
    if q is None: return
    data = q.data or ""
    cid = update.effective_chat.id if update.effective_chat else 0
    fuid = q.from_user.id if q.from_user else None
    if data.startswith("asst:force:"):
        if fuid != FORCED_OWNER:
            try: await q.answer("تو پسر کی ای؟", show_alert=True)
            except Exception: pass
            raise ApplicationHandlerStop
        try: await q.answer("⏳")
        except Exception: pass
        try: await asst_handle_force(q, data)
        except Exception as e: log_print(f"[asst-force] {e}")
        raise ApplicationHandlerStop
    if data == "noop":
        try: await q.answer()
        except Exception: pass
        raise ApplicationHandlerStop
    if not authorized(update):
        try: await q.answer("تو پسر کی ای؟", show_alert=True)
        except Exception: pass
        raise ApplicationHandlerStop
    try: await q.answer()
    except Exception: pass
    if q.message:
        for mod in (rb, sr, ei):
            if mod is None: continue
            try: mod.STATE["panel"][cid] = q.message.message_id
            except Exception: pass
    if data == "mode:rubika":
        USER_MODE[cid] = "rubika"
        if rb is None: raise ApplicationHandlerStop
        try: await rb.show_main()
        except Exception as e: log_print(f"[rb.show_main] {e}")
        raise ApplicationHandlerStop
    if data == "mode:soroosh":
        USER_MODE[cid] = "soroosh"
        if sr is None: raise ApplicationHandlerStop
        try: await sr.show_main()
        except Exception as e: log_print(f"[sr.show_main] {e}")
        raise ApplicationHandlerStop
    if data == "mode:eitaa":
        USER_MODE[cid] = "eitaa"
        if ei is None: raise ApplicationHandlerStop
        try: await ei.show_main()
        except Exception as e: log_print(f"[ei.show_main] {e}")
        raise ApplicationHandlerStop
    if data == "mode:assistant":
        USER_MODE[cid] = "assistant"
        try: await asst_show_panel(cid, edit_mid=q.message.message_id if q.message else None)
        except Exception as e: log_print(f"[asst.show] {e}")
        raise ApplicationHandlerStop
    if data.startswith("asst:"):
        try: await asst_route_cb(cid, data)
        except Exception as e:
            log_print(f"[asst.route] {e}")
            import traceback; traceback.print_exc()
        raise ApplicationHandlerStop
    if data in ("menu:home", "mode:home"):
        USER_MODE.pop(cid, None)
        await _render_mode_selector(cid, edit_mid=q.message.message_id)
        raise ApplicationHandlerStop
    mode = USER_MODE.get(cid)
    if mode == "rubika" and rb is not None:
        try: await rb.route_cb(cid, data)
        except Exception as e: log_print(f"[rb.route_cb] {e}")
        raise ApplicationHandlerStop
    if mode == "soroosh" and sr is not None:
        try: await sr.route_cb(cid, data)
        except Exception as e: log_print(f"[sr.route_cb] {e}")
        raise ApplicationHandlerStop
    if mode == "eitaa" and ei is not None:
        try: await ei.route_cb(cid, data)
        except Exception as e: log_print(f"[ei.route_cb] {e}")
        raise ApplicationHandlerStop
    if mode == "assistant":
        try: await asst_show_panel(cid, edit_mid=q.message.message_id if q.message else None)
        except Exception as e: log_print(f"[asst-fallback] {e}")
        raise ApplicationHandlerStop
    await _render_mode_selector(cid, edit_mid=q.message.message_id)
    raise ApplicationHandlerStop

async def msg_router(update, context):
    if not authorized(update): return
    cid = update.effective_chat.id
    if cid in ASST_WAITING:
        w = ASST_WAITING.pop(cid); msg = update.message or update.edited_message
        try: await asst_handle_wait(cid, w, msg)
        except Exception as e: log_print(f"[asst-wait] {e}")
        return
    mode = USER_MODE.get(cid)
    if mode == "assistant":
        try:
            msg = update.message or update.edited_message
            await msg.reply_text("🎯 از پنل دستیار استفاده کن\n/menu")
        except Exception: pass
        return
    if mode == "rubika" and rb is not None:
        try: await rb.on_message(update, context)
        except Exception as e: log_print(f"[rb.on_message] {e}")
        return
    if mode == "soroosh" and sr is not None:
        try: await sr.on_message(update, context)
        except Exception as e: log_print(f"[sr.on_message] {e}")
        return
    if mode == "eitaa" and ei is not None:
        try: await ei.on_message(update, context)
        except Exception as e: log_print(f"[ei.on_message] {e}")
        return
    try:
        msg = update.message or update.edited_message
        await msg.reply_text("🏠 اول یک پنل انتخاب کن.\n/start یا /menu")
    except Exception: pass

async def on_post_init(app: Application):
    global TG_APP
    TG_APP = app
    for mod in (rb, sr, ei):
        if mod is None: continue
        try: mod.APP = app
        except Exception: pass
    log_print("=" * 60)
    log_print("   🌐 Soroosh Panel + Assistant — v26")
    log_print(f"   rb: {RB_PATH or '—'}")
    log_print(f"   sr: {SR_PATH or '—'}")
    log_print(f"   ei: {EI_PATH or '—'}")
    log_print("=" * 60)
    try:
        await app.bot.set_my_commands([
            BotCommand("start", "شروع"),
            BotCommand("menu", "منو"),
            BotCommand("version", "نسخه"),
        ])
    except Exception: pass
    for mod in (rb, sr, ei):
        if mod is None: continue
        try: asyncio.create_task(mod.start_all_listeners())
        except Exception: pass
        try: asyncio.create_task(mod.keepalive_loop())
        except Exception: pass
        if hasattr(mod, "start_pv_responders"):
            try: asyncio.create_task(mod.start_pv_responders())
            except Exception: pass
    try: asyncio.create_task(asst_cleanup_loop())
    except Exception: pass
    try: asyncio.create_task(asst_on_startup())
    except Exception: pass
    log_print("   ✅ listeners + pv + keepalive + asst scheduled")

async def on_error(update, context):
    log_print(f"[!] {type(context.error).__name__}: {context.error}")

_bot_thread: Optional[threading.Thread] = None

def _bot_worker():
    global TG_APP
    log_print("   ربات: ⏳ polling...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for mod in (rb, sr, ei):
        if mod is None: continue
        try: mod._loop_ref[0] = loop
        except Exception: pass
    req = HTTPXRequest(connection_pool_size=8, connect_timeout=30.0,
                       read_timeout=30.0, write_timeout=30.0, pool_timeout=30.0)
    app = (Application.builder().token(TG_TOKEN).request(req)
           .get_updates_request(req).post_init(on_post_init).build())
    app.add_handler(CallbackQueryHandler(cb_router), group=-1)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("version", cmd_version))
    try:
        group_filter = tg_filters.ChatType.GROUP | tg_filters.ChatType.SUPERGROUP
        app.add_handler(MessageHandler(
            (tg_filters.TEXT | tg_filters.CAPTION) & group_filter,
            asst_group_handler), group=-2)
    except Exception as e: log_print(f"[asst-handler] {e}")
    app.add_handler(MessageHandler(tg_filters.ALL & ~tg_filters.COMMAND, msg_router))
    app.add_error_handler(on_error)
    TG_APP = app
    for mod in (rb, sr, ei):
        if mod is None: continue
        try: mod.APP = app
        except Exception: pass
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES, poll_interval=2.0, timeout=30.0)
    except BaseException as e:
        log_print(f"   ربات: ❌ {type(e).__name__}: {e}")
    finally:
        log_print("   ربات: 🔴 DOWN")

def start_bot_thread() -> bool:
    global _bot_thread
    if _bot_thread is not None and _bot_thread.is_alive(): return False
    _bot_thread = threading.Thread(target=_bot_worker, daemon=True, name="telegram-bot")
    _bot_thread.start(); return True

@asynccontextmanager
async def lifespan(_app=None):
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()
    log_print("=" * 60)
    log_print("   🌐 Soroosh Panel + Assistant — v26")
    log_print("=" * 60)
    start_bot_thread()
    await asyncio.sleep(2.0)
    yield
    log_print("\n   [shutdown]")




# APP_V34_NO_WEB
if __name__ == "__main__":
    import asyncio
    log_print("=" * 60)
    log_print("   🌀 Soroosh Panel + Assistant")
    log_print("=" * 60)
    async def _run_forever():
        async with lifespan(None):
            while True:
                await asyncio.sleep(3600)
    try:
        asyncio.run(_run_forever())
    except KeyboardInterrupt:
        print("\n[!] stopped")
    except Exception as e:
        print(f"[!] fatal: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
