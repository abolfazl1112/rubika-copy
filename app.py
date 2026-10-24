"""Rubika + Soroosh + Eitaa Web Panel — v22.9 (all fixes · Code 220908 · pending normalize · no re-send)"""

import sys, os, io, contextlib, logging, queue

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
        except (RuntimeError, ValueError, NotImplementedError, AttributeError):
            return None
    _ue._UnixSelectorEventLoop.add_signal_handler = _safe_add_signal
except Exception: pass


import json, time, secrets, asyncio, importlib.util, tempfile, threading, runpy, re, shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import (FastAPI, Response, HTTPException, WebSocket, WebSocketDisconnect,
                     UploadFile, File, Depends, Query, Request, Form)
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand)
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ApplicationHandlerStop,
                          filters as tg_filters)
from telegram.request import HTTPXRequest

HERE = Path(__file__).parent.resolve()


# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════
TG_TOKEN = os.environ.get("TG_TOKEN", "").strip() or "8386088114:AAGwPae4COCTKR99or_hBe9t2VCT4gFYkMQ"
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

IS_RAILWAY = bool(os.environ.get("RAILWAY_ENVIRONMENT") or
                  os.environ.get("RAILWAY_STATIC_URL") or
                  os.environ.get("RAILWAY_PROJECT_ID"))
IS_HTTPS = PUBLIC_URL.startswith("https://")


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
        log_print(f"⚠️  import {SR_FILENAME}: {type(e).__name__}: {e}")
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
        log_print(f"⚠️  import {EI_FILENAME}: {type(e).__name__}: {e}")
        ei = None


if rb is None and sr is None and ei is None:
    log_print("❌ هیچ رباتی import نشد."); sys.exit(1)


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


if rb is not None:
    if not hasattr(rb, "update_account_field"):
        def _shim_update_account_field(aid, key, value):
            accounts = rb.list_accounts()
            if aid in accounts:
                accounts[aid][key] = value
                rb.save_accounts(accounts)
        rb.update_account_field = _shim_update_account_field

    if not hasattr(rb, "send_text"):
        async def _shim_send_text(cli, target, text):
            return await rb.send_text_only(cli, target, text)
        rb.send_text = _shim_send_text

    if not hasattr(rb, "rubika_get_my_profile"):
        async def _shim_get_profile(cli):
            out = {"first_name": "", "last_name": "", "bio": "",
                   "username": "", "phone": "", "user_guid": ""}
            try:
                me = await cli.get_me()
                u = getattr(me, "user", me)
                for k in ("first_name", "last_name", "bio", "username",
                          "phone", "user_guid"):
                    v = getattr(u, k, None)
                    if v is not None: out[k] = v
            except Exception as e:
                out["error"] = str(e)[:200]
            return out
        rb.rubika_get_my_profile = _shim_get_profile


OWNER_FILE = DATA_DIR / "tg_owner.json"


def _ensure_owner_file():
    try:
        tmp = str(OWNER_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"owner": FORCED_OWNER}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(OWNER_FILE))
    except Exception as e:
        log_print(f"[panel] owner file: {type(e).__name__}: {e}")


_ensure_owner_file()


SESS_FILE = str(DATA_DIR / "web_sessions.json")
PENDING: Dict[int, Dict[str, Any]] = {}
SESSIONS: Dict[str, Dict[str, Any]] = {}
if os.path.exists(SESS_FILE):
    try: SESSIONS = json.load(open(SESS_FILE, encoding="utf-8"))
    except Exception: SESSIONS = {}
LOGS: List[dict] = []
MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None
USER_MODE: Dict[int, str] = {}


def save_sessions():
    with open(SESS_FILE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(SESSIONS, f, ensure_ascii=False, indent=2)
    os.replace(SESS_FILE + ".tmp", SESS_FILE)


def gen_code(): return str(secrets.randbelow(900000) + 100000)


def _eta(sec):
    sec = int(sec)
    if sec < 60: return f"{sec}s"
    if sec < 3600: return f"{sec // 60}m"
    return f"{sec // 3600}h {(sec % 3600) // 60}m"


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


def authorized(update):
    try: return update.effective_chat.id == FORCED_OWNER
    except Exception: return False


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
    lines.append("🎯 <b>دستیار</b> — ورود انبوه + اجرای مداوم قالب")
    txt = "\n".join(lines) + "\n"
    if edit_mid:
        try:
            await TG_APP.bot.edit_message_text(
                chat_id=cid, message_id=edit_mid, text=txt,
                reply_markup=mode_selector_kb(),
                parse_mode="HTML", disable_web_page_preview=True)
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
# ASSISTANT — v22.9
# ══════════════════════════════════════════════════════════════
ASST_DIR = DATA_DIR / "assistant"
ASST_DIR.mkdir(parents=True, exist_ok=True)
ASST_CFG_FILE = ASST_DIR / "config.json"
ASST_SEEN_FILE = ASST_DIR / "seen.json"
ASST_RUNNING_FILE = ASST_DIR / "running.json"

ASST_DEFAULT = {
    "enabled": False, "group_id": 0, "accept_new_accounts": True,
    "max_accounts": 50,
    "apply_rubika": True, "apply_soroosh": True, "apply_eitaa": False,
    "run_template_id_rubika": None,
    "run_template_id_soroosh": None,
    "run_template_id_eitaa": None,
    "template_duration_hours": 6,
    "retry_after_s": 60, "give_up_after_s": 180,
    "notify_owner": True,
}

ASST_PENDING: Dict[str, dict] = {}
ASST_BATCHES: Dict[str, dict] = {}
ASST_BATCH_ERRORS: Dict[str, List[str]] = {}
ASST_USER_CACHE: Dict[str, dict] = {}
ASST_TASKS: Dict[str, asyncio.Task] = {}
ASST_WAITING: Dict[int, dict] = {}
ASST_RUNNING: Dict[str, dict] = {}

_rubika_active_phone = [None]


def asst_load_cfg():
    if not ASST_CFG_FILE.exists():
        asst_save_cfg(ASST_DEFAULT)
        return dict(ASST_DEFAULT)
    try:
        with open(ASST_CFG_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return dict(ASST_DEFAULT)
        merged = {**ASST_DEFAULT, **d}
        if int(merged.get("give_up_after_s", 0)) < 120:
            merged["give_up_after_s"] = 180
        if int(merged.get("retry_after_s", 0)) < 45:
            merged["retry_after_s"] = 60
        return merged
    except Exception:
        return dict(ASST_DEFAULT)


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
            "aid": info.get("aid", ""),
            "tid": info.get("tid", ""),
            "started": info.get("started", 0),
            "hours": info.get("hours", 6),
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

_PHONE_RE = re.compile(r'\b0\d{10}\b')
_UID_RE = re.compile(r'/set_([a-f0-9]{8,})')


def asst_pkg_source(text):
    t = text or ""
    if "Target #Phones" in t or "Lebeka Team" in t or "@TheLeBeKa" in t: return "lebeka"
    if "› ᴠɪꜱɪᴏɴ" in t or "ʀᴇᴄᴇɪᴠᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ" in t: return "vision"
    return None


def asst_code_source(text):
    t = text or ""
    t_clean = re.sub(r'[\s\u200c\u200d\ufeff]+', '', t)
    if "سروشپلاس" in t_clean: return "soroosh"
    if "soroosh" in t_clean.lower(): return "soroosh"
    if "روبیکا" in t_clean: return "rubika"
    if "rubika" in t_clean.lower(): return "rubika"
    if "سروش" in t_clean: return "soroosh"
    if "روبیکا" in t_clean: return "rubika"
    return None


def asst_phones(text): return list(dict.fromkeys(_PHONE_RE.findall(text or "")))


def asst_uid(text):
    m = _UID_RE.search(text or "")
    return f"set_{m.group(1)}" if m else None


def asst_code(text):
    t = text or ""
    t_norm = t.replace("：", ":")
    persian = "۰۱۲۳۴۵۶۷۸۹"
    arabic  = "٠١٢٣٤٥٦٧٨٩"
    trans = str.maketrans(persian + arabic, "01234567890123456789")
    t_norm = t_norm.translate(trans)

    pats = [
        r'کد\s*ورود\s*:\s*(\d{4,8})',
        r'کد\s*روبیکا\s*:\s*(\d{4,8})',
        r'Code\s*:\s*(\d{4,8})',
        r'Code\s+(\d{4,8})',
        r'کد\s*:\s*(\d{4,8})',
    ]
    for t_test in (t, t_norm):
        for pat in pats:
            m = re.search(pat, t_test)
            if m:
                log_print(f"[asst-code] MATCH {pat[:22]!r} → {m.group(1)}")
                return m.group(1)

    t_clean = re.sub(r'[\s\u200c\u200d]+', '', t_norm)
    fallback = [
        r'کدورود:(\d{4,8})', r'کدروبیکا:(\d{4,8})',
        r'Code:(\d{4,8})', r'Code(\d{4,8})',
        r'کد:(\d{4,8})',
    ]
    for pat in fallback:
        m = re.search(pat, t_clean)
        if m:
            log_print(f"[asst-code] MATCH-FALLBACK {pat[:22]!r} → {m.group(1)}")
            return m.group(1)

    log_print(f"[asst-code] NO MATCH in: {t[:100]!r}")
    return None


def _asst_get_mod(platform):
    return rb if platform == "rubika" else sr if platform == "soroosh" else ei if platform == "eitaa" else None


def _threaded_runner(coro_fn, *args):
    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro_fn(*args))
        finally:
            try: loop.close()
            except Exception: pass
    return _runner


# ═══════════════ RUBIKA ═══════════════
async def asst_send_rubika(phone):
    if rb is None: return {"ok": False, "status": "not_loaded"}
    if not hasattr(rb, "login_via_rubpy"):
        return {"ok": False, "status": "no_login_fn"}
    pending = getattr(rb, "_pending_login", {})
    if phone in pending:
        log_print(f"[asst-rubika] already pending: {phone}")
        return {"ok": True, "status": "awaiting_code"}
    if _rubika_active_phone[0]:
        if _rubika_active_phone[0] in pending:
            return {"ok": False, "status": f"busy:{_rubika_active_phone[0][:4]}"}
        else:
            _rubika_active_phone[0] = None
    _rubika_active_phone[0] = phone
    try:
        await rb.login_via_rubpy(phone, phone)
        for _ in range(8):
            await asyncio.sleep(1)
            if phone in getattr(rb, "_pending_login", {}):
                log_print(f"[asst-rubika] SENT code for {phone}")
                return {"ok": True, "status": "awaiting_code"}
        _rubika_active_phone[0] = None
        log_print(f"[asst-rubika] send_code timeout for {phone}")
        return {"ok": False, "status": "send_timeout"}
    except Exception as e:
        _rubika_active_phone[0] = None
        log_print(f"[asst-rubika] send exception {phone}: {e}")
        return {"ok": False, "status": f"{type(e).__name__}: {str(e)[:80]}"}


async def asst_verify_rubika(phone, code, h=None):
    if rb is None: return {"ok": False, "status": "not_loaded"}
    pending = getattr(rb, "_pending_login", {})
    if phone not in pending:
        return {"ok": False, "status": "no_pending"}
    entry = pending[phone]
    q = entry.get("q")
    if not q:
        return {"ok": False, "status": "no_queue"}
    accounts_before = set()
    try: accounts_before = set(rb.list_accounts().keys())
    except Exception: pass
    try:
        q.put(code)
        log_print(f"[asst-rubika-verify] pushed code {code} to {phone}")
    except Exception as e:
        return {"ok": False, "status": f"queue_err: {str(e)[:40]}"}
    for _ in range(120):
        await asyncio.sleep(1)
        if phone not in getattr(rb, "_pending_login", {}):
            break
    _rubika_active_phone[0] = None
    try:
        accounts = rb.list_accounts()
        for aid, a in accounts.items():
            if a.get("phone") == phone and aid not in accounts_before:
                log_print(f"[asst-rubika-verify] ✓ {phone} → {aid}")
                return {"ok": True, "aid": aid, "name": a.get("name", phone)}
    except Exception: pass
    if phone in getattr(rb, "_pending_login", {}):
        return {"ok": False, "status": "wrong_code_retry"}
    log_print(f"[asst-rubika-verify] ✗ {phone} failed")
    return {"ok": False, "status": "wrong_code"}


# ═══════════════ SOROOSH ═══════════════
async def asst_send_soroosh(phone):
    if sr is None: return {"ok": False, "status": "not_loaded"}
    try:
        norm = re.sub(r"[^\d]", "", phone or "")
        if norm.startswith("00"): norm = norm[2:]
        if norm.startswith("0"): norm = norm[1:]
        if not norm.startswith("98"): norm = "98" + norm
    except Exception:
        norm = phone
    if hasattr(sr, "_LOGIN_TMP"):
        for p in (phone, norm):
            if p in sr._LOGIN_TMP:
                log_print(f"[asst-soroosh] already pending: {phone} (key={p})")
                return {"ok": True, "status": "awaiting_code",
                        "phone_code_hash": sr._LOGIN_TMP[p].get("hash")}
    try:
        r = await asyncio.wait_for(
            asyncio.to_thread(_threaded_runner(sr.soroosh_send_code, phone)),
            timeout=95
        )
        if not isinstance(r, dict):
            return {"ok": False, "status": f"bad_type:{type(r).__name__}"}
        if r.get("ok"):
            log_print(f"[asst-soroosh] SENT code for {phone}")
        return r
    except asyncio.TimeoutError:
        return {"ok": False, "status": "timeout_95s"}
    except Exception as e:
        return {"ok": False, "status": f"{type(e).__name__}: {str(e)[:100]}"}


async def asst_verify_soroosh(phone, code):
    if sr is None: return {"ok": False, "status": "not_loaded"}
    try:
        r = await asyncio.wait_for(
            asyncio.to_thread(_threaded_runner(sr.soroosh_complete_login, phone, code)),
            timeout=125
        )
        if not isinstance(r, dict):
            return {"ok": False, "status": f"bad_type:{type(r).__name__}"}
        return r
    except asyncio.TimeoutError:
        return {"ok": False, "status": "timeout_125s"}
    except Exception as e:
        return {"ok": False, "status": f"{type(e).__name__}: {str(e)[:100]}"}


async def asst_send_eitaa(phone):
    if ei is None: return {"ok": False, "status": "not_loaded"}
    fn = getattr(ei, "send_code", None) or getattr(ei, "eitaa_send_code", None)
    if not fn: return {"ok": False, "status": "no_api"}
    try:
        if asyncio.iscoroutinefunction(fn):
            r = await asyncio.wait_for(fn(phone), timeout=95)
        else:
            r = await asyncio.wait_for(asyncio.to_thread(fn, phone), timeout=95)
        return r if isinstance(r, dict) else {"ok": bool(r), "status": "ok" if r else "fail"}
    except asyncio.TimeoutError:
        return {"ok": False, "status": "timeout_95s"}
    except Exception as e: return {"ok": False, "status": f"{type(e).__name__}: {str(e)[:100]}"}


async def asst_verify_eitaa(phone, code):
    if ei is None: return {"ok": False, "status": "not_loaded"}
    fn = getattr(ei, "complete_login", None) or getattr(ei, "eitaa_complete_login", None)
    if not fn: return {"ok": False, "status": "no_api"}
    try:
        if asyncio.iscoroutinefunction(fn):
            r = await asyncio.wait_for(fn(phone, code), timeout=125)
        else:
            r = await asyncio.wait_for(asyncio.to_thread(fn, phone, code), timeout=125)
        return r if isinstance(r, dict) else {"ok": bool(r), "status": "ok" if r else "fail"}
    except asyncio.TimeoutError:
        return {"ok": False, "status": "timeout_125s"}
    except Exception as e: return {"ok": False, "status": f"{type(e).__name__}: {str(e)[:100]}"}


def asst_trim(platform, max_n):
    mod = _asst_get_mod(platform)
    if mod is None: return
    try:
        accs = mod.list_accounts()
        if len(accs) <= max_n: return
        items = sorted(accs.items(), key=lambda kv: (kv[1].get("created") or 0), reverse=True)
        removed = 0
        for aid, _ in items[max_n:]:
            key = f"{platform}:{aid}"
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
            try:
                mod.remove_account(aid); removed += 1
            except Exception: pass
        log_print(f"[asst] trim {platform} → {max_n} (removed {removed})")
        asst_save_running_state()
    except Exception as e: log_print(f"[asst-trim] {e}")


def asst_cleanup_ops():
    for mod in (rb, sr, ei):
        if mod is None or not hasattr(mod, "_load_ops"): continue
        try:
            ops = mod._load_ops()
            cutoff = time.time() - 3600
            kept = [o for o in ops if not (o.get("_asst") and o.get("created", 0) < cutoff)]
            if len(kept) != len(ops):
                mod._save_ops(kept)
                log_print(f"[asst-cleanup] {len(ops) - len(kept)} ops removed")
        except Exception: pass


async def asst_run_template_once(platform, aid, tid):
    mod = _asst_get_mod(platform)
    if mod is None: return None
    try:
        tpl = mod.get_template(tid)
        if not tpl: return None
        op = {"id": f"asst_{secrets.token_hex(5)}", "created": int(time.time()),
              "type": "autotar", "accounts": [aid], "template_id": tid,
              "status": "running", "_asst": True,
              "progress": {"joined":0,"failed":0,"total":0,"pending":0,"in_progress":0,
                           "phase":"asst-loop","sent":0,"already":0,"tried":0,"wave":0,
                           "left":0,"round":0,"skipped_seen":0,"skipped_banned":0,"rejected":0},
              "errors": []}
        try: mod._save_op(op)
        except Exception: pass
        runner = getattr(mod, "run_auto_tar", None)
        if runner:
            try: await asyncio.wait_for(runner(op, log_print), timeout=1800)
            except asyncio.TimeoutError:
                log_print(f"[asst] {platform}:{aid} timeout 30min")
        return op["id"]
    except asyncio.CancelledError: raise
    except Exception as e:
        log_print(f"[asst-tpl] {platform}:{aid}: {type(e).__name__}: {e}")
        return None


async def asst_continuous_template(platform, aid, tid, hours, stop_event):
    key = f"{platform}:{aid}"
    end = time.time() + hours * 3600
    runs = 0
    mod = _asst_get_mod(platform)
    if mod is None:
        ASST_RUNNING.pop(key, None); asst_save_running_state(); return
    log_print(f"[asst] {key} start (h={hours}, tid={tid})")
    while not stop_event.is_set() and time.time() < end:
        try:
            accounts = mod.list_accounts()
            if aid not in accounts:
                log_print(f"[asst] {key} STOP: account gone"); break
        except Exception: pass
        try:
            tpl = mod.get_template(tid)
            if not tpl:
                log_print(f"[asst] {key} STOP: template gone"); break
        except Exception: pass
        runs += 1
        info = ASST_RUNNING.get(key)
        if info: info["runs"] = runs
        try:
            op_id = await asst_run_template_once(platform, aid, tid)
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


def asst_start_one(platform, aid, tid, hours):
    key = f"{platform}:{aid}"
    info = ASST_RUNNING.get(key)
    if info and info.get("task") and not info["task"].done():
        return False
    ev = asyncio.Event()
    t = asyncio.create_task(asst_continuous_template(platform, aid, tid, hours, ev))
    ASST_RUNNING[key] = {
        "task": t, "started": time.time(), "hours": hours, "stop": ev,
        "runs": 0, "platform": platform, "aid": aid, "tid": tid,
        "current_op_id": None, "last_error": None,
    }
    asst_save_running_state()
    return True


async def asst_start_all():
    cfg = asst_load_cfg()
    hours = int(cfg.get("template_duration_hours", 6))
    n = 0
    for platform in ("rubika", "soroosh", "eitaa"):
        if not cfg.get(f"apply_{platform}"): continue
        tid = cfg.get(f"run_template_id_{platform}")
        if not tid:
            log_print(f"[asst-start] {platform}: NO TEMPLATE ⚠️"); continue
        mod = _asst_get_mod(platform)
        if mod is None: continue
        try:
            accounts = mod.list_accounts()
            log_print(f"[asst-start] {platform}: {len(accounts)} accounts, tid={tid}")
            for aid in accounts:
                if asst_start_one(platform, aid, tid, hours):
                    n += 1
        except Exception as e:
            log_print(f"[asst-start] {platform} ERROR: {type(e).__name__}: {e}")
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


def _asst_status_str(r):
    if not r: return "—"
    st = r.get("status", "")
    if r.get("ok"): return "✅ وارد شد"
    if st == "awaiting_code": return "⏳ در انتظار کد"
    if st == "retrying": return "🔄 تلاش مجدد"
    if st == "giveup": return "❌ بی‌پاسخ"
    if st.startswith("busy"): return f"⏸ مشغول ({st[5:9]})"
    if "pending" in st.lower(): return "🚧 (بعداً)"
    if "timeout" in st.lower(): return "⏰ تایم‌اوت"
    if st: return f"❌ {st[:40]}"
    return "—"


def asst_build_reply(bk):
    b = ASST_BATCHES.get(bk) or {}
    src = b.get("source", "?")
    label = {"lebeka":"لبکا","vision":"ویژن"}.get(src, src)
    cfg = asst_load_cfg()
    phones = b.get("phones", [])
    results = b.get("results", {})
    lines = [f"📋 <b>گزارش ورود</b> — {label}", "━━━━━━━━━━━━━━", ""]
    lines.append("📱 <b>روبیکا:</b>")
    if cfg.get("apply_rubika"):
        for ph in phones:
            r = (results.get(ph) or {}).get("rubika") or {}
            lines.append(f"📞 <code>{esc(ph)}</code> — {_asst_status_str(r)}")
    else:
        lines.append("<i>غیرفعال</i>")
    lines.append("")
    lines.append("🌀 <b>سروش:</b>")
    if cfg.get("apply_soroosh"):
        for ph in phones:
            r = (results.get(ph) or {}).get("soroosh") or {}
            lines.append(f"📞 <code>{esc(ph)}</code> — {_asst_status_str(r)}")
    else:
        lines.append("<i>غیرفعال</i>")
    if cfg.get("apply_eitaa"):
        lines.append("")
        lines.append("📨 <b>ایتا:</b>")
        for ph in phones:
            r = (results.get(ph) or {}).get("eitaa") or {}
            lines.append(f"📞 <code>{esc(ph)}</code> — {_asst_status_str(r)}")
    lines.append("")
    lines.append(f"🔖 منبع: <b>{label}</b>")
    lines.append(f"🪪 شناسه: <code>{esc(b.get('user_id') or '—')}</code>")
    errs = ASST_BATCH_ERRORS.get(bk, [])
    if errs:
        lines.append(f"\n⚠️ <b>خطاها ({len(errs)}):</b>")
        for e in errs[-5:]:
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

    # ── Phase 1: initial send
    for ph in phones:
        if cfg.get("apply_rubika"):
            try: r = await asst_send_rubika(ph)
            except Exception as e: r = {"ok": False, "status": str(e)[:80]}
            if not isinstance(r, dict): r = {"ok": False, "status": "bad_type"}
            ok = bool(r.get("ok"))
            if not ok:
                ASST_BATCH_ERRORS[bk].append(f"rubika {ph}: {r.get('status','?')[:60]}")
                log_print(f"[asst] rubika:{ph} FAILED — {r.get('status')}")
            ASST_PENDING[f"{ph}|rubika"] = {
                "batch_key": bk, "phone": ph, "platform": "rubika",
                "phone_code_hash": r.get("phone_code_hash") or r.get("hash"),
                "sent_at": time.time(), "attempts": 1, "confirmed": False,
                "status": "awaiting_code" if ok else r.get("status","send_failed"),
            }
            batch["results"][ph]["rubika"] = {"status": ASST_PENDING[f"{ph}|rubika"]["status"], "ok": False}

        if cfg.get("apply_soroosh"):
            try: r = await asst_send_soroosh(ph)
            except Exception as e: r = {"ok": False, "status": str(e)[:80]}
            if not isinstance(r, dict): r = {"ok": False, "status": "bad_type"}
            ok = bool(r.get("ok"))
            if not ok:
                ASST_BATCH_ERRORS[bk].append(f"soroosh {ph}: {r.get('status','?')[:60]}")
                log_print(f"[asst] soroosh:{ph} FAILED — {r.get('status')}")
            ASST_PENDING[f"{ph}|soroosh"] = {
                "batch_key": bk, "phone": ph, "platform": "soroosh",
                "phone_code_hash": r.get("phone_code_hash") or r.get("hash"),
                "sent_at": time.time(), "attempts": 1, "confirmed": False,
                "status": "awaiting_code" if ok else r.get("status","send_failed"),
            }
            batch["results"][ph]["soroosh"] = {"status": ASST_PENDING[f"{ph}|soroosh"]["status"], "ok": False}

        if cfg.get("apply_eitaa"):
            try: r = await asst_send_eitaa(ph)
            except Exception as e: r = {"ok": False, "status": str(e)[:80]}
            if not isinstance(r, dict): r = {"ok": False, "status": "bad_type"}
            ok = bool(r.get("ok"))
            ASST_PENDING[f"{ph}|eitaa"] = {
                "batch_key": bk, "phone": ph, "platform": "eitaa",
                "phone_code_hash": r.get("phone_code_hash") or r.get("hash"),
                "sent_at": time.time(), "attempts": 1, "confirmed": False,
                "status": "awaiting_code" if ok else r.get("status","send_failed"),
            }
            batch["results"][ph]["eitaa"] = {"status": ASST_PENDING[f"{ph}|eitaa"]["status"], "ok": False}

    if batch["msg_id"]: await asst_edit(bk, batch["msg_id"], chat_id)

    # ── Phase 2: retry (never re-send if awaiting_code)
    await asst_sleep_or(batch["stop"], cfg.get("retry_after_s", 60))
    if batch.get("done"): return
    for v in list(ASST_PENDING.values()):
        if v["batch_key"] != bk or v["confirmed"]: continue
        ph, plat = v["phone"], v["platform"]
        current = v.get("status", "")
        if current == "awaiting_code":
            v["sent_at"] = time.time()
            v["status"] = "retrying"
            batch["results"][ph][plat] = {"status": "retrying", "ok": False}
            log_print(f"[asst] {plat}:{ph} still awaiting — NOT re-sending")
        else:
            try:
                r = await (asst_send_rubika(ph) if plat=="rubika"
                           else asst_send_soroosh(ph) if plat=="soroosh"
                           else asst_send_eitaa(ph))
                if not isinstance(r, dict): r = {"ok": False, "status": "bad_type"}
            except Exception as e: r = {"ok": False, "status": str(e)[:80]}
            v["attempts"] += 1; v["sent_at"] = time.time()
            v["status"] = "awaiting_code" if r.get("ok") else r.get("status","retry_failed")
            batch["results"][ph][plat] = {"status": v["status"], "ok": False}
            log_print(f"[asst] {plat}:{ph} retry → {v['status']}")

    if batch["msg_id"]: await asst_edit(bk, batch["msg_id"], chat_id)

    # ── Phase 3: giveup (entries STAY in PENDING)
    await asst_sleep_or(batch["stop"], cfg.get("give_up_after_s", 180))
    if batch.get("done"): return
    for k, v in list(ASST_PENDING.items()):
        if v["batch_key"] != bk or v["confirmed"]: continue
        ph, plat = v["phone"], v["platform"]
        v["status"] = "giveup"
        batch["results"][ph][plat] = {"status": "giveup", "ok": False}
        log_print(f"[asst] {plat}:{ph} giveup — PENDING kept for late code")
    batch["done"] = True
    if batch["msg_id"]: await asst_edit(bk, batch["msg_id"], chat_id)
    if cfg.get("notify_owner") and TG_APP:
        try:
            ok_n = sum(1 for ph in phones for v in batch["results"].get(ph, {}).values() if v.get("ok"))
            src = {"lebeka":"لبکا","vision":"ویژن"}.get(source, source)
            await TG_APP.bot.send_message(chat_id=FORCED_OWNER,
                text=f"✅ بچ تموم شد\n📞 {len(phones)} · ✅ {ok_n} موفق\n🔖 {src}")
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


async def asst_try_code(platform, code):
    for key, v in list(ASST_PENDING.items()):
        if v["platform"] != platform or v["confirmed"]: continue
        ph, bk = v["phone"], v["batch_key"]
        try:
            r = await (asst_verify_rubika(ph, code, v.get("phone_code_hash")) if platform=="rubika"
                       else asst_verify_soroosh(ph, code) if platform=="soroosh"
                       else asst_verify_eitaa(ph, code))
        except Exception as e:
            r = {"ok": False, "status": str(e)[:80]}
            log_print(f"[asst-try] {platform}:{ph} EXC: {e}")
        log_print(f"[asst-try] {platform}:{ph} ok={r.get('ok')} status={str(r.get('status',''))[:50]}")
        if r.get("ok"):
            v["confirmed"] = True
            ASST_PENDING.pop(key, None)
            b = ASST_BATCHES.get(bk)
            cfg = asst_load_cfg()
            if b:
                b["results"][ph][platform] = {"status": "confirmed", "ok": True}
                asst_trim(platform, int(cfg.get("max_accounts", 50)))
                if b.get("msg_id"): await asst_edit(bk, b["msg_id"], b.get("chat_id"))
            tid = cfg.get(f"run_template_id_{platform}")
            mod = _asst_get_mod(platform)
            if tid and mod:
                try:
                    for aid, a in mod.list_accounts().items():
                        if a.get("phone") == ph:
                            hours = int(cfg.get("template_duration_hours", 6))
                            if asst_start_one(platform, aid, tid, hours):
                                log_print(f"[asst] AUTO-START {platform}:{aid}")
                            break
                except Exception: e = None
            cid_notify = (b.get("chat_id") if b else None) or FORCED_OWNER
            if not tid:
                try:
                    await TG_APP.bot.send_message(
                        chat_id=cid_notify,
                        text=(f"⚠️ اکانت <b>{platform}</b> وارد شد (<code>{esc(ph)}</code>)\n\n"
                              f"❌ ولی هیچ <b>قالبی</b> برای {platform} انتخاب نشده!\n"
                              f"👉 از پنل دستیار → «قالب {platform}» انتخاب کن"),
                        parse_mode="HTML")
                except Exception: pass
            return ph
    return None


def asst_dedup_kb(uid):
    return kb_(
        [B("🌀 ورود سروش",    f"asst:force:soroosh:{uid}")],
        [B("📱 ورود روبیکا",   f"asst:force:rubika:{uid}")],
        [B("🔁 ورود مجدد همه", f"asst:force:all:{uid}")],
    )


async def asst_group_handler(update, context):
    msg = update.message
    if msg is None or not msg.text: return
    try:
        if msg.chat.type not in ("group", "supergroup"): return
    except Exception: return
    cfg = asst_load_cfg()
    if not cfg.get("enabled"): return
    gid = int(cfg.get("group_id") or 0)
    if gid and msg.chat_id != gid: return
    text = msg.text
    log_print(f"[asst-group] chat={msg.chat_id} len={len(text)}")
    is_owner = (msg.from_user and msg.from_user.id == FORCED_OWNER)

    if text.strip() == "چخبر":
        if is_owner: await asst_stats_to(msg.chat_id, msg.message_id)
        return

    plat = asst_code_source(text)
    if plat:
        code = asst_code(text)
        log_print(f"[asst-code] plat={plat} code={code}")
        if code:
            matched = await asst_try_code(plat, code)
            if matched:
                await asst_send(msg.chat_id,
                    f"✅ کد {plat} روی <code>{esc(matched)}</code> تایید شد",
                    reply_to=msg.message_id)
            else:
                await asst_send(msg.chat_id,
                    f"⚠️ کد {plat} دریافت شد ولی هیچ شماره‌ای در انتظار نبود\nکد: <code>{esc(code)}</code>",
                    reply_to=msg.message_id)
        return

    src = asst_pkg_source(text)
    if not src: return
    if not cfg.get("accept_new_accounts", True):
        await asst_send(msg.chat_id, "⏸ ثبت اکانت جدید موقتاً متوقف شده", reply_to=msg.message_id)
        return
    phones = asst_phones(text)
    uid = asst_uid(text)
    if not phones: return
    if uid: ASST_USER_CACHE[uid] = {"source": src, "phones": phones, "ts": time.time()}
    if uid and uid in ASST_SEEN:
        if is_owner:
            await asst_send(msg.chat_id,
                f"⚠️ این شناسه قبلاً ثبت شده: <code>{esc(uid)}</code>\nدوباره بزنم؟",
                reply_markup=asst_dedup_kb(uid), reply_to=msg.message_id)
        else:
            await asst_send(msg.chat_id,
                f"ℹ️ این شناسه قبلاً پردازش شده — فقط مالک می‌تونه دوباره اجرا کنه",
                reply_to=msg.message_id)
        return
    if uid: ASST_SEEN.add(uid); asst_save_seen(ASST_SEEN)
    bk = "b_" + secrets.token_hex(4)
    ASST_TASKS[bk] = asyncio.create_task(asst_safe_batch(bk, msg.chat_id, src, phones, uid))


async def asst_stats_to(chat_id, reply_to=None):
    rb_n = len(rb.list_accounts()) if rb else 0
    sr_n = len(sr.list_accounts()) if sr else 0
    ei_n = len(ei.list_accounts()) if ei else 0
    pend = len([k for k in ASST_PENDING if not ASST_PENDING[k].get("confirmed")])
    act = len([k for k in ASST_BATCHES if not ASST_BATCHES[k].get("done")])
    total_errors = sum(len(e) for e in ASST_BATCH_ERRORS.values())
    txt = (f"📊 <b>آمار دستیار</b>\n━━━━━━━━━━━━\n"
           f"📱 روبیکا: <b>{rb_n}</b>\n"
           f"🌀 سروش: <b>{sr_n}</b>\n"
           f"📨 ایتا: <b>{ei_n}</b>\n"
           f"⏳ در انتظار کد: <b>{pend}</b>\n"
           f"⚙️ بچ فعال: <b>{act}</b>\n"
           f"🎬 در حال اجرا: <b>{len(ASST_RUNNING)}</b>\n"
           f"⚠️ خطاهای بچ: <b>{total_errors}</b>\n"
           f"🔖 شناسه‌ها: <b>{len(ASST_SEEN)}</b>")
    await asst_send(chat_id, txt, reply_to=reply_to)


async def asst_show_running(cid, edit_mid=None):
    total = len(ASST_RUNNING)
    txt = f"🎬 <b>در حال اجرا</b> — {total} اکانت\n━━━━━━━━━━━━\n\n"
    by_plat = {"rubika": [], "soroosh": [], "eitaa": []}
    for key, info in ASST_RUNNING.items():
        plat = info.get("platform") or key.split(":", 1)[0]
        if plat in by_plat: by_plat[plat].append((key, info))
    for plat, label, icon in [("rubika","روبیکا","📱"),("soroosh","سروش","🌀"),("eitaa","ایتا","📨")]:
        accounts = by_plat[plat]
        txt += f"{icon} <b>{label}</b> ({len(accounts)}):\n"
        if not accounts:
            txt += "<i>— خالی</i>\n\n"; continue
        mod = _asst_get_mod(plat)
        accs_data = {}
        try:
            if mod: accs_data = mod.list_accounts() or {}
        except Exception: pass
        for key, info in accounts[:8]:
            aid = info.get("aid") or key.split(":", 1)[1]
            name = (accs_data.get(aid) or {}).get("name", aid[:10])
            runs = info.get("runs", 0)
            elapsed = int(time.time() - info.get("started", 0)) if info.get("started") else 0
            hours = info.get("hours", 6)
            txt += f"• <b>{esc(name[:18])}</b> — دور {runs} — {_eta(elapsed)}/{hours}h\n"
        txt += "\n"
    rows = []
    for plat, label, icon in [("rubika","روبیکا","📱"),("soroosh","سروش","🌀"),("eitaa","ایتا","📨")]:
        if by_plat[plat]:
            rows.append([B(f"{icon} جزئیات {label} ({len(by_plat[plat])})", f"asst:running:{plat}")])
    rows.append([B("🔄 بروزرسانی", "asst:running_all"), B("🛑 توقف همه", "asst:stop_all")])
    rows.append([B("« بازگشت", "asst:refresh")])
    if edit_mid and TG_APP:
        try:
            await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt[:4000],
                                               reply_markup=kb_(*rows), parse_mode="HTML",
                                               disable_web_page_preview=True)
            return
        except Exception as e:
            if "not modified" in str(e).lower(): return
    if TG_APP:
        try:
            await TG_APP.bot.send_message(cid, txt[:4000], reply_markup=kb_(*rows),
                                          parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e: log_print(f"[asst-running] {e}")


async def asst_show_running_platform(cid, platform, edit_mid=None):
    if platform not in ("rubika", "soroosh", "eitaa"):
        return await asst_show_running(cid, edit_mid)
    mod = _asst_get_mod(platform)
    accs_data = {}
    try:
        if mod: accs_data = mod.list_accounts() or {}
    except Exception: pass
    label = {"rubika":"روبیکا","soroosh":"سروش","eitaa":"ایتا"}[platform]
    icon = {"rubika":"📱","soroosh":"🌀","eitaa":"📨"}[platform]
    running_keys = [k for k in ASST_RUNNING.keys() if k.startswith(f"{platform}:")]
    txt = f"{icon} <b>{label} — جزئیات اجرا</b>\n━━━━━━━━━━━━\n\n"
    if not running_keys:
        txt += "<i>هیچ اکانتی در حال اجرا نیست</i>"
    else:
        for key in running_keys:
            info = ASST_RUNNING.get(key) or {}
            aid = info.get("aid") or key.split(":", 1)[1]
            acc = accs_data.get(aid) or {}
            name = acc.get("name") or aid[:12]
            phone = acc.get("phone") or "—"
            runs = info.get("runs", 0)
            elapsed = int(time.time() - info.get("started", 0)) if info.get("started") else 0
            hours = info.get("hours", 6)
            txt += f"👤 <b>{esc(name[:24])}</b>\n"
            txt += f"📞 <code>{esc(phone)}</code>\n"
            txt += f"🔁 دور {runs} · ⏱ {_eta(elapsed)} / {hours}h\n\n"
            tid = info.get("tid")
            tpl = None
            if tid and mod:
                try: tpl = mod.get_template(tid)
                except Exception: pass
            if not tpl:
                txt += "<i>⚠️ قالب حذف شده یا پیدا نشد</i>\n\n"
            else:
                op = None
                op_id = info.get("current_op_id")
                if op_id and mod:
                    try: op = mod._get_op(op_id)
                    except Exception: op = None
                prog = (op.get("progress") if op else {}) or {}
                num = tpl.get("num_id", "?")
                tname = tpl.get("name", "?")[:24]
                txt += f"🎬 <b>قالب #{num} — {esc(tname)}</b>\n"
                j = prog.get("joined", 0); f = prog.get("failed", 0)
                pv_s = prog.get("pv_sent", 0); pv_f = prog.get("pv_failed", 0)
                grp_s = prog.get("grp_sent", 0); grp_f = prog.get("grp_failed", 0)
                if j or f: txt += f"🤝 ✓{j} ✗{f}\n"
                if pv_s or pv_f: txt += f"💬 PV ✓{pv_s} ✗{pv_f}\n"
                if grp_s or grp_f: txt += f"📤 GRP ✓{grp_s} ✗{grp_f}\n"
                ph = prog.get("phase", "")
                if ph: txt += f"📍 <i>{esc(str(ph)[:70])}</i>\n"
                txt += "\n"
            err = info.get("last_error")
            if err:
                txt += f"⚠️ <code>{esc(err[:80])}</code>\n\n"
            txt += "━━━━━━━━━━━━\n\n"
    rows = [
        [B("🔄 بروزرسانی", f"asst:running:{platform}")],
        [B("« بازگشت", "asst:running_all")],
    ]
    if edit_mid and TG_APP:
        try:
            await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt[:4000],
                                               reply_markup=kb_(*rows), parse_mode="HTML",
                                               disable_web_page_preview=True)
            return
        except Exception: pass
    if TG_APP:
        try:
            await TG_APP.bot.send_message(cid, txt[:4000], reply_markup=kb_(*rows),
                                          parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e: log_print(f"[asst-running-plat] {e}")


async def asst_show_panel(cid, edit_mid=None):
    try:
        cfg = asst_load_cfg()
        rb_n = len(rb.list_accounts()) if rb else 0
        sr_n = len(sr.list_accounts()) if sr else 0
        ei_n = len(ei.list_accounts()) if ei else 0

        def _tpl_name(platform):
            tid = cfg.get(f"run_template_id_{platform}")
            if not tid: return "—"
            mod = _asst_get_mod(platform)
            if not mod: return tid
            try:
                t = mod.get_template(tid)
                if t: return f"#{t.get('num_id','?')} {t.get('name','?')[:18]}"
            except Exception: pass
            return tid

        on = "🟢" if cfg.get("enabled") else "⚪"
        acc = "🟢" if cfg.get("accept_new_accounts", True) else "🔴"
        running_count = len(ASST_RUNNING)
        warnings = []
        for plat, lbl in [("rubika","روبیکا"),("soroosh","سروش"),("eitaa","ایتا")]:
            if cfg.get(f"apply_{plat}") and not cfg.get(f"run_template_id_{plat}"):
                warnings.append(f"⚠️ قالب {lbl} انتخاب نشده")
        txt = (f"🎯 <b>دستیار</b>\n━━━━━━━━━━━━\n\n"
               f"📶 وضعیت: {on}\n"
               f"📥 پذیرش اکانت جدید: {acc}\n"
               f"💬 گروه: <code>{esc(str(cfg.get('group_id') or '—'))}</code>\n"
               f"🔢 حداکثر اکانت: <b>{cfg.get('max_accounts', 50)}</b>\n"
               f"⏱ مدت اجرا: <b>{cfg.get('template_duration_hours', 6)} ساعت</b>\n"
               f"🎬 در حال اجرا: <b>{running_count}</b> اکانت\n\n"
               f"<b>قالب‌ها:</b>\n"
               f"📱 روبیکا: <b>{esc(_tpl_name('rubika'))}</b>\n"
               f"🌀 سروش: <b>{esc(_tpl_name('soroosh'))}</b>\n"
               f"📨 ایتا: <b>{esc(_tpl_name('eitaa'))}</b>\n\n"
               f"📊 روبیکا <b>{rb_n}</b> · سروش <b>{sr_n}</b> · ایتا <b>{ei_n}</b>")
        if warnings:
            txt += "\n\n" + "\n".join(warnings)
        rows = [
            [B("⏸ توقف پذیرش" if cfg.get("accept_new_accounts", True) else "▶️ شروع پذیرش",
               "asst:toggle_accept"),
             B("خاموش کن" if cfg.get("enabled") else "روشن کن", "asst:toggle")],
            [B(f"🎬 در حال اجرا ({running_count})", "asst:running_all")],
            [B("💬 تنظیم گروه", "asst:set_group")],
            [B("🔢 حداکثر", "asst:set_max"),
             B(f"⏱ مدت: {cfg.get('template_duration_hours', 6)}h", "asst:set_hours")],
            [B("📱 قالب روبیکا", "asst:set_tpl:rubika"),
             B("🌀 قالب سروش", "asst:set_tpl:soroosh"),
             B("📨 قالب ایتا", "asst:set_tpl:eitaa")],
            [B("🔄 شروع مجدد همه", "asst:restart_all"),
             B("🛑 توقف همه", "asst:stop_all")],
            [B("📱 روبیکا " + ("🟢" if cfg.get("apply_rubika") else "⚪"), "asst:tog:rubika"),
             B("🌀 سروش " + ("🟢" if cfg.get("apply_soroosh") else "⚪"), "asst:tog:soroosh"),
             B("📨 ایتا " + ("🟢" if cfg.get("apply_eitaa") else "⚪"), "asst:tog:eitaa")],
            [B("📊 آمار", "asst:stats"), B("📋 لاگ‌ها", "asst:logs"),
             B("🔄 پاک pending", "asst:clear_pending")],
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
            except Exception as e: log_print(f"[asst-panel] {e}")
    except Exception as e:
        log_print(f"[asst-show] FATAL: {type(e).__name__}: {e}")


async def asst_show_logs(cid, page=0):
    logs = list(LOGS[-100:])
    for bk, errs in ASST_BATCH_ERRORS.items():
        for e in errs[-10:]:
            logs.append({"text": f"[batch {bk[-4:]}] {e}", "ts": time.time()})
    logs.sort(key=lambda x: x.get("ts", 0))
    logs = logs[-100:]
    PER = 15
    pages = max(1, -(-len(logs) // PER))
    page = max(0, min(page, pages - 1))
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
        if data == "asst:refresh": return await asst_show_panel(cid)
        if data == "asst:running_all": return await asst_show_running(cid)
        if data.startswith("asst:running:"):
            plat = data.split(":", 2)[2]
            return await asst_show_running_platform(cid, plat)
        if data == "asst:toggle":
            cfg["enabled"] = not cfg.get("enabled"); asst_save_cfg(cfg)
            return await asst_show_panel(cid)
        if data == "asst:toggle_accept":
            cfg["accept_new_accounts"] = not cfg.get("accept_new_accounts", True)
            asst_save_cfg(cfg); return await asst_show_panel(cid)
        if data == "asst:set_group":
            ASST_WAITING[cid] = {"kind": "group"}
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "💬 شناسه گروه:", parse_mode="HTML")
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
            platform = data.split(":", 2)[2]
            if platform not in ("rubika","soroosh","eitaa"): return
            mod = _asst_get_mod(platform)
            if mod is None:
                if TG_APP:
                    try: await TG_APP.bot.send_message(cid, f"❌ پلتفرم {platform} لود نشده")
                    except Exception: pass
                return
            try: tpls = mod.list_templates()
            except Exception: tpls = {}
            if not tpls:
                if TG_APP:
                    try: await TG_APP.bot.send_message(cid, f"قالبی برای {platform} نیست.")
                    except Exception: pass
                return
            rows = []
            for tid, t in list(tpls.items())[:12]:
                num = t.get("num_id", "?")
                name = t.get("name", "?")[:24]
                rows.append([B(f"#{num} 🎯 {name}", f"asst:tpl_pick:{platform}:{tid}")])
            rows.append([B("❌ بدون قالب", f"asst:tpl_pick:{platform}:none")])
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, f"🎬 قالب {platform}:", reply_markup=kb_(*rows))
                except Exception: pass
            return
        if data.startswith("asst:tpl_pick:"):
            parts = data.split(":", 3)
            if len(parts) < 4: return
            platform = parts[2]; tid = parts[3]
            cfg[f"run_template_id_{platform}"] = None if tid == "none" else tid
            asst_save_cfg(cfg)
            started = 0
            if cfg.get("enabled") and cfg.get(f"apply_{platform}") and tid != "none":
                mod = _asst_get_mod(platform)
                if mod:
                    hours = int(cfg.get("template_duration_hours", 6))
                    try:
                        for aid in mod.list_accounts():
                            if asst_start_one(platform, aid, tid, hours): started += 1
                    except Exception as e: log_print(f"[asst-tpl-pick] {e}")
            if TG_APP and tid != "none":
                try:
                    await TG_APP.bot.send_message(
                        cid, f"✅ قالب {platform} ذخیره · 🎬 {started} اکانت استارت شد",
                        parse_mode="HTML")
                except Exception: pass
            return await asst_show_panel(cid)
        if data.startswith("asst:tog:"):
            plat = data.split(":", 2)[2]
            cfg[f"apply_{plat}"] = not cfg.get(f"apply_{plat}", plat in ("rubika","soroosh"))
            asst_save_cfg(cfg); return await asst_show_panel(cid)
        if data == "asst:restart_all":
            n = await asst_restart_all()
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, f"🔄 شروع {n} اکانت")
                except Exception: pass
            return await asst_show_panel(cid)
        if data == "asst:stop_all":
            await asst_stop_all()
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "🛑 همه متوقف شد")
                except Exception: pass
            return await asst_show_panel(cid)
        if data == "asst:stats": await asst_stats_to(cid); return
        if data == "asst:clear_pending":
            ASST_PENDING.clear()
            ASST_BATCH_ERRORS.clear()
            for b in ASST_BATCHES.values():
                b["done"] = True
                ev = b.get("stop")
                if ev:
                    try: ev.set()
                    except Exception: pass
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "🔄 پاک شد")
                except Exception: pass
            return await asst_show_panel(cid)
    except Exception as e:
        log_print(f"[asst-route] FATAL: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        if TG_APP:
            try:
                await TG_APP.bot.send_message(cid, f"❌ {type(e).__name__}: {str(e)[:200]}", parse_mode="HTML")
            except Exception: pass


async def asst_handle_force(q, data):
    parts = data.split(":", 4)
    if len(parts) < 4: return
    mode, uid = parts[2], parts[3]
    cached = ASST_USER_CACHE.get(uid)
    if not cached:
        try: await q.answer("❌ پیام کش نشده", show_alert=True)
        except Exception: pass
        return
    cfg = asst_load_cfg()
    if mode == "rubika":
        cfg["apply_rubika"]=True; cfg["apply_soroosh"]=False; cfg["apply_eitaa"]=False
    elif mode == "soroosh":
        cfg["apply_rubika"]=False; cfg["apply_soroosh"]=True; cfg["apply_eitaa"]=False
    asst_save_cfg(cfg)
    try: await q.answer("⏳ شروع...")
    except Exception: pass
    chat_id = q.message.chat_id if q.message else 0
    bk = "b_" + secrets.token_hex(4)
    ASST_TASKS[bk] = asyncio.create_task(asst_safe_batch(bk, chat_id, cached["source"], cached["phones"], uid))


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
        await asst_show_panel(cid)
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
        await asst_show_panel(cid)
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
        await asst_show_panel(cid)


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


async def asst_on_startup():
    try:
        cfg = asst_load_cfg()
        log_print(f"[asst] startup: enabled={cfg.get('enabled')}")
        for p in ("rubika","soroosh","eitaa"):
            log_print(f"[asst]   apply_{p}={cfg.get(f'apply_{p}')} tpl={cfg.get(f'run_template_id_{p}')}")
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


# ══════════════════════════════════════════════════════════════
# COMMANDS
# ══════════════════════════════════════════════════════════════
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
    rb_v = getattr(rb, "VERSION", "—") if rb else "—"
    sr_v = getattr(sr, "VERSION", "—") if sr else "—"
    txt = (f"🔖 <b>app.py</b>: v22.9\n"
           f"📱 <b>روبیکا</b>: {rb_v}\n"
           f"🌀 <b>سروش</b>: {sr_v}\n"
           f"👤 <b>مالک</b>: <code>{FORCED_OWNER}</code>\n"
           f"🎬 <b>در حال اجرا</b>: {len(ASST_RUNNING)}")
    await update.message.reply_text(txt, parse_mode="HTML")


# ══════════════════════════════════════════════════════════════
# CALLBACK ROUTER
# ══════════════════════════════════════════════════════════════
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
        w = ASST_WAITING.pop(cid)
        try: await asst_handle_wait(cid, w, update.message)
        except Exception as e: log_print(f"[asst-wait] {e}")
        return
    mode = USER_MODE.get(cid)
    if mode == "assistant":
        try: await update.message.reply_text("🎯 از پنل دستیار استفاده کن\n/menu")
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
    try: await update.message.reply_text("🏠 اول یک پنل انتخاب کن.\n/start یا /menu")
    except Exception: pass


async def on_post_init(app: Application):
    global TG_APP
    TG_APP = app
    for mod in (rb, sr, ei):
        if mod is None: continue
        try: mod.APP = app
        except Exception: pass
    log_print("=" * 60)
    log_print("   🌐 Rubika + Soroosh + Eitaa + Assistant — v22.9")
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
            tg_filters.TEXT & ~tg_filters.COMMAND & group_filter,
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
async def lifespan(_app: FastAPI):
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()
    log_print("=" * 60)
    log_print("   🌐  Rubika + Soroosh + Eitaa + Assistant — v22.9")
    log_print("=" * 60)
    start_bot_thread()
    await asyncio.sleep(2.0)
    yield
    log_print("\n   [shutdown]")


app = FastAPI(title="Rubika + Soroosh + Eitaa Panel", lifespan=lifespan)

if STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/api/health")
async def api_health():
    return {
        "ok": True, "version": "v22.9",
        "owner": FORCED_OWNER,
        "rubika_loaded": rb is not None,
        "soroosh_loaded": sr is not None,
        "eitaa_loaded": ei is not None,
        "bot_alive": bool(_bot_thread and _bot_thread.is_alive()),
        "assistant_running": len(ASST_RUNNING),
        "assistant_pending": len(ASST_PENDING),
    }


if __name__ == "__main__":
    import uvicorn
    log_print("=" * 60)
    log_print("   🌐  v22.9")
    log_print(f"   Public: {PUBLIC_URL}")
    log_print(f"   Bind  : {HOST}:{PORT}")
    log_print("=" * 60)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info",
                proxy_headers=True, forwarded_allow_ips="*")