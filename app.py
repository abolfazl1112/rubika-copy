"""Rubika + Soroosh Web Panel — v20 (Railway production + TG_TOKEN env only)"""

# ══════════════════════════════════════════════════════════════
# ۰) قاپ زدن stdout/stderr واقعی
# ══════════════════════════════════════════════════════════════
import sys, os, io, contextlib, logging

REAL_STDOUT = sys.stdout
REAL_STDERR = sys.stderr


def log_print(msg=""):
    try: print(msg, file=REAL_STDOUT, flush=True)
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# ۱) خفه کردن لاگرها
# ══════════════════════════════════════════════════════════════
logging.basicConfig(level=logging.CRITICAL, stream=io.StringIO())
for _name in ("", "uvicorn", "uvicorn.error", "uvicorn.access",
              "httpx", "httpcore", "telegram", "telegram.ext",
              "urllib3", "aiohttp", "asyncio", "fastapi",
              "multipart", "rubpy", "splusthon", "requests", "web",
              "rubika_bot", "soroosh_bot"):
    _lg = logging.getLogger(_name)
    _lg.setLevel(logging.CRITICAL)
    _lg.propagate = False
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

HERE = Path(__file__).parent.resolve()


# ══════════════════════════════════════════════════════════════
# ★★★  توکن‌ها و owner — فقط از ENV  ★★★
# ══════════════════════════════════════════════════════════════
TG_TOKEN = os.environ.get("TG_TOKEN", "").strip()
if not TG_TOKEN or ":" not in TG_TOKEN:
    log_print("❌  TG_TOKEN در متغیرهای محیطی ست نشده.")
    log_print("    در Railway: Variables → TG_TOKEN = <bot_token>")
    sys.exit(1)

try:
    FORCED_OWNER = int(os.environ.get("TG_OWNER_ID", "").strip() or "8389746549")
except Exception:
    FORCED_OWNER = 8389746549


# ══════════════════════════════════════════════════════════════
# HOST / PORT / PUBLIC_URL — برای Railway
# ══════════════════════════════════════════════════════════════
# روی Railway باید روی 0.0.0.0 گوش بده
HOST = os.environ.get("PANEL_HOST", "0.0.0.0").strip()
PORT = int(os.environ.get("PORT", "8080"))

# URL عمومی که تو لاگ‌ها و لینک‌ها نمایش داده می‌شه
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://rubika-production.up.railway.app").strip().rstrip("/")

# آیا پشت پروکسی (Railway) هستیم؟
IS_RAILWAY = bool(os.environ.get("RAILWAY_ENVIRONMENT") or
                  os.environ.get("RAILWAY_STATIC_URL") or
                  os.environ.get("RAILWAY_PROJECT_ID"))
IS_HTTPS = PUBLIC_URL.startswith("https://")


# ══════════════════════════════════════════════════════════════
# ۲) DATA_DIR
# ══════════════════════════════════════════════════════════════
def _panel_data_dir() -> Path:
    candidates = []
    e = os.environ.get("DATA_DIR", "").strip()
    if e: candidates.append(e)
    e = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if e: candidates.append(e)
    if os.environ.get("RAILWAY_ENVIRONMENT"):
        candidates.extend(["/data", "/app/data"])
    for c in candidates:
        try:
            p = Path(c)
            if p.is_dir() and os.access(p, os.W_OK):
                return p.resolve()
        except Exception: pass
    return HERE


DATA_DIR = _panel_data_dir()
LOG_FILE = DATA_DIR / "bot_runtime.log"
os.environ["DATA_DIR"] = str(DATA_DIR)


# ══════════════════════════════════════════════════════════════
# ۳) پیدا کردن ربات‌ها
# ══════════════════════════════════════════════════════════════
RB_FILENAME = "rubika_tg_bot.py"
SR_FILENAME = "Soroosh_tg_bot.py"


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


# ══════════════════════════════════════════════════════════════
# ۴) ENV pass-through
# ══════════════════════════════════════════════════════════════
os.environ["TG_TOKEN"] = TG_TOKEN
os.environ["TG_OWNER_ID"] = str(FORCED_OWNER)


# ══════════════════════════════════════════════════════════════
# ۵) import ربات روبیکا
# ══════════════════════════════════════════════════════════════
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
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n===== rubika import @ {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            f.write(_buf.getvalue())
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# ۶) import ربات سروش
# ══════════════════════════════════════════════════════════════
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
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n===== soroosh import @ {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            f.write(_buf.getvalue())
    except Exception: pass


if rb is None and sr is None:
    log_print("❌ هیچ رباتی import نشد."); sys.exit(1)


# ══════════════════════════════════════════════════════════════
# ۷) SET GLOBALS روی هر دو
# ══════════════════════════════════════════════════════════════
if rb is not None:
    rb.FORCED_OWNER = FORCED_OWNER
    rb.TG_TOKEN = TG_TOKEN
    try: rb.STATE["owner"] = FORCED_OWNER
    except Exception: pass
    if not hasattr(rb, "_loop_ref"):
        rb._loop_ref = [None]


if sr is not None:
    sr.FORCED_OWNER = FORCED_OWNER
    sr.TG_TOKEN = TG_TOKEN
    try: sr.STATE["owner"] = FORCED_OWNER
    except Exception: pass
    if not hasattr(sr, "_loop_ref"):
        sr._loop_ref = [None]


# ══════════════════════════════════════════════════════════════
# ۸) RUBIKA — compatibility shims
# ══════════════════════════════════════════════════════════════
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

    if not hasattr(rb, "get_live_channels"):
        async def _shim_live_channels(cli):
            try:
                chats = await rb.get_all_chats_raw(cli)
                return [c for c in chats if (c.get("type") or "") == "Channel"]
            except Exception: return []
        rb.get_live_channels = _shim_live_channels

    if not hasattr(rb, "joiner"):
        async def _shim_joiner(cli, channels, max_count, log_cb):
            joined = 0
            for ch in channels:
                try:
                    ok, _r, _t = await rb._try_join_single(cli, ch)
                    if ok:
                        joined += 1
                        try: log_cb(f"✅ join {str(ch)[:30]}")
                        except Exception: pass
                    if max_count and joined >= max_count: break
                except Exception: continue
            return joined
        rb.joiner = _shim_joiner


# ══════════════════════════════════════════════════════════════
# ۹) OWNER FILE
# ══════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════
# ۱۰) SESSIONS / STATE
# ══════════════════════════════════════════════════════════════
SESS_FILE = str(DATA_DIR / "web_sessions.json")
PENDING: Dict[int, Dict[str, Any]] = {}
SESSIONS: Dict[str, Dict[str, Any]] = {}
if os.path.exists(SESS_FILE):
    try: SESSIONS = json.load(open(SESS_FILE, encoding="utf-8"))
    except: SESSIONS = {}
LOGS: List[dict] = []
MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None
USER_MODE: Dict[int, str] = {}


def save_sessions():
    with open(SESS_FILE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(SESSIONS, f, ensure_ascii=False, indent=2)
    os.replace(SESS_FILE + ".tmp", SESS_FILE)


def gen_code():
    return str(secrets.randbelow(900000) + 100000)


# ══════════════════════════════════════════════════════════════
# ۱۱) WebSocket hub
# ══════════════════════════════════════════════════════════════
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
        c = Conn(ws, uid)
        c.writer = asyncio.create_task(c._write())
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


if rb is not None:
    try: rb.log_cb = wlog
    except Exception: pass
if sr is not None:
    try: sr.log_cb = wlog
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# ۱۲) STATIC
# ══════════════════════════════════════════════════════════════
STATIC = next((c for c in [HERE / "static", HERE.parent / "static"]
               if c.is_dir() and (c / "login.html").exists()), HERE / "static")


# ══════════════════════════════════════════════════════════════
# ۱۳) TELEGRAM Application — یک ربات واحد
# ══════════════════════════════════════════════════════════════
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                     BotCommand)
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ApplicationHandlerStop,
                          filters as tg_filters)
from telegram.request import HTTPXRequest

TG_APP: Optional[Application] = None


def esc(s):
    return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def B(label, data): return InlineKeyboardButton(label, callback_data=data)
def kb_(*rows): return InlineKeyboardMarkup([list(r) for r in rows if r])


def authorized(update):
    try: return update.effective_chat.id == FORCED_OWNER
    except Exception: return False


def mode_selector_kb():
    return kb_(
        [B("📱  پنل روبیکا", "mode:rubika")],
        [B("🌀  پنل سروش",  "mode:soroosh")],
    )


async def _render_mode_selector(cid: int, edit_mid: Optional[int] = None) -> Optional[int]:
    txt = (
        "🏠 <b>پنل مدیریت</b>\n"
        "━━━━━━━━━━━━\n\n"
        "یک پنل رو انتخاب کن:\n\n"
        "📱 <b>روبیکا</b> — ارسال، جوینر، کانال، لیسنر\n"
        "🌀 <b>سروش</b> — ارسال، جوینر، پاسخ خودکار\n"
    )
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
# /start  /menu  /version
# ══════════════════════════════════════════════════════════════
async def cmd_start(update, context):
    cid = update.effective_chat.id
    if cid != FORCED_OWNER:
        try: await update.message.reply_text("⛔ خصوصی است.")
        except Exception: pass
        return
    USER_MODE.pop(cid, None)
    if rb is not None:
        try: rb.STATE["panel"].pop(cid, None)
        except Exception: pass
    if sr is not None:
        try: sr.STATE["panel"].pop(cid, None)
        except Exception: pass
    mid = await _render_mode_selector(cid)
    if mid:
        if rb is not None:
            try: rb.STATE["panel"][cid] = mid
            except Exception: pass
        if sr is not None:
            try: sr.STATE["panel"][cid] = mid
            except Exception: pass


async def cmd_menu(update, context):
    if not authorized(update): return
    await cmd_start(update, context)


async def cmd_version(update, context):
    if not authorized(update): return
    rb_v = getattr(rb, "VERSION", "—") if rb else "—"
    sr_v = getattr(sr, "VERSION", "—") if sr else "—"
    txt = (f"🔖 <b>app.py</b>: v20\n"
           f"📱 <b>روبیکا</b>: {rb_v}\n"
           f"🌀 <b>سروش</b>: {sr_v}\n"
           f"👤 <b>مالک</b>: <code>{FORCED_OWNER}</code>\n"
           f"🌐 <b>Public</b>: {esc(PUBLIC_URL)}\n"
           f"💻 <b>Bind</b>: {HOST}:{PORT}\n"
           f"💾 <b>Data</b>: <code>{DATA_DIR}</code>")
    await update.message.reply_text(txt, parse_mode="HTML")


# ══════════════════════════════════════════════════════════════
# CALLBACK ROUTER
# ══════════════════════════════════════════════════════════════
async def cb_router(update, context):
    q = update.callback_query
    if q is None: return
    try: await q.answer()
    except Exception: pass
    if not authorized(update):
        raise ApplicationHandlerStop

    cid = update.effective_chat.id
    data = q.data or ""

    if data == "noop":
        raise ApplicationHandlerStop

    if q.message:
        if rb is not None:
            try: rb.STATE["panel"][cid] = q.message.message_id
            except Exception: pass
        if sr is not None:
            try: sr.STATE["panel"][cid] = q.message.message_id
            except Exception: pass

    # ─── انتخاب پنل ───
    if data == "mode:rubika":
        USER_MODE[cid] = "rubika"
        if rb is None:
            try:
                await q.edit_message_text("❌ پنل روبیکا لود نشده.",
                                           reply_markup=mode_selector_kb())
            except Exception: pass
            raise ApplicationHandlerStop
        try:
            await rb.show_main()
        except Exception as e:
            log_print(f"[rb.show_main] {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()
        raise ApplicationHandlerStop

    if data == "mode:soroosh":
        USER_MODE[cid] = "soroosh"
        if sr is None:
            try:
                await q.edit_message_text("❌ پنل سروش لود نشده.",
                                           reply_markup=mode_selector_kb())
            except Exception: pass
            raise ApplicationHandlerStop
        try:
            await sr.show_main()
        except Exception as e:
            log_print(f"[sr.show_main] {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()
        raise ApplicationHandlerStop

    # ─── بازگشت به انتخاب پنل ───
    if data in ("menu:home", "mode:home"):
        USER_MODE.pop(cid, None)
        await _render_mode_selector(cid, edit_mid=q.message.message_id)
        raise ApplicationHandlerStop

    # ─── dispatch ───
    mode = USER_MODE.get(cid)
    if mode == "rubika" and rb is not None:
        try:
            await rb.route_cb(cid, data)
        except Exception as e:
            log_print(f"[rb.route_cb] {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()
            try:
                await TG_APP.bot.send_message(
                    chat_id=cid,
                    text=f"❌ {esc(type(e).__name__)}: {esc(str(e)[:200])}")
            except Exception: pass
        raise ApplicationHandlerStop

    if mode == "soroosh" and sr is not None:
        try:
            await sr.route_cb(cid, data)
        except Exception as e:
            log_print(f"[sr.route_cb] {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()
            try:
                await TG_APP.bot.send_message(
                    chat_id=cid,
                    text=f"❌ {esc(type(e).__name__)}: {esc(str(e)[:200])}")
            except Exception: pass
        raise ApplicationHandlerStop

    await _render_mode_selector(cid, edit_mid=q.message.message_id)
    raise ApplicationHandlerStop


# ══════════════════════════════════════════════════════════════
# MESSAGE ROUTER
# ══════════════════════════════════════════════════════════════
async def msg_router(update, context):
    if not authorized(update): return
    cid = update.effective_chat.id
    mode = USER_MODE.get(cid)

    if mode == "rubika" and rb is not None:
        try:
            await rb.on_message(update, context)
        except Exception as e:
            log_print(f"[rb.on_message] {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()
        return

    if mode == "soroosh" and sr is not None:
        try:
            await sr.on_message(update, context)
        except Exception as e:
            log_print(f"[sr.on_message] {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()
        return

    try:
        await update.message.reply_text("🏠 اول یک پنل انتخاب کن.\n/start یا /menu")
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# POST INIT
# ══════════════════════════════════════════════════════════════
async def on_post_init(app: Application):
    global TG_APP
    TG_APP = app
    if rb is not None: rb.APP = app
    if sr is not None: sr.APP = app

    log_print("=" * 60)
    log_print("   🌐 Rubika + Soroosh — Unified Bot (Railway)")
    log_print(f"   Owner : {FORCED_OWNER}")
    log_print(f"   Public: {PUBLIC_URL}")
    log_print(f"   Bind  : {HOST}:{PORT}")
    log_print(f"   Data  : {DATA_DIR}")
    log_print(f"   rb bot: {RB_PATH or '—'}")
    log_print(f"   sr bot: {SR_PATH or '—'}")
    log_print("=" * 60)

    try:
        await app.bot.set_my_commands([
            BotCommand("start", "شروع / انتخاب پنل"),
            BotCommand("menu", "منوی انتخاب پنل"),
            BotCommand("version", "نسخه"),
        ])
    except Exception: pass

    if rb is not None:
        try:
            asyncio.create_task(rb.start_all_listeners())
            log_print("[rb] listeners scheduled")
        except Exception as e:
            log_print(f"[rb listeners] {type(e).__name__}: {e}")
        try:
            asyncio.create_task(rb.keepalive_loop())
            log_print("[rb] keepalive scheduled")
        except Exception as e:
            log_print(f"[rb keepalive] {type(e).__name__}: {e}")

    if sr is not None:
        try:
            asyncio.create_task(sr.start_all_listeners())
            log_print("[sr] listeners scheduled")
        except Exception as e:
            log_print(f"[sr listeners] {type(e).__name__}: {e}")
        try:
            asyncio.create_task(sr.keepalive_loop())
            log_print("[sr] keepalive scheduled")
        except Exception as e:
            log_print(f"[sr keepalive] {type(e).__name__}: {e}")
        # ★ PV responder
        try:
            if hasattr(sr, "start_pv_responders"):
                asyncio.create_task(sr.start_pv_responders())
                log_print("[sr] pv-responders scheduled")
        except Exception as e:
            log_print(f"[sr pv] {type(e).__name__}: {e}")

    log_print("   ✅ همه listenerها و keepaliveها فعال شدن")


async def on_error(update, context):
    log_print(f"[!] {type(context.error).__name__}: {context.error}")


# ══════════════════════════════════════════════════════════════
# BOT THREAD
# ══════════════════════════════════════════════════════════════
_bot_thread: Optional[threading.Thread] = None


def _bot_worker():
    global TG_APP
    log_print("   ربات تلگرام: ⏳ در حال راه‌اندازی polling...")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    if rb is not None:
        try: rb._loop_ref[0] = loop
        except Exception: pass
    if sr is not None:
        try: sr._loop_ref[0] = loop
        except Exception: pass

    req = HTTPXRequest(connection_pool_size=8, connect_timeout=30.0,
                       read_timeout=30.0, write_timeout=30.0, pool_timeout=30.0)
    app = (Application.builder()
           .token(TG_TOKEN)
           .request(req)
           .get_updates_request(req)
           .post_init(on_post_init)
           .build())

    app.add_handler(CallbackQueryHandler(cb_router), group=-1)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("version", cmd_version))
    app.add_handler(MessageHandler(
        tg_filters.ALL & ~tg_filters.COMMAND, msg_router))
    app.add_error_handler(on_error)

    TG_APP = app
    if rb is not None: rb.APP = app
    if sr is not None: sr.APP = app

    try:
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            poll_interval=2.0,
            timeout=30.0,
        )
    except SystemExit:
        log_print("   ربات تلگرام: SystemExit")
    except BaseException as e:
        log_print(f"   ربات تلگرام: ❌ {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
    finally:
        log_print("   ربات تلگرام: 🔴 DOWN")


def start_bot_thread() -> bool:
    global _bot_thread
    if _bot_thread is not None and _bot_thread.is_alive():
        return False
    _bot_thread = threading.Thread(target=_bot_worker, daemon=True,
                                    name="telegram-bot")
    _bot_thread.start()
    return True


# ══════════════════════════════════════════════════════════════
# LIFESPAN
# ══════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(_app: FastAPI):
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()

    log_print("=" * 60)
    log_print("   🌐  Rubika + Soroosh Web Panel — v20")
    log_print("=" * 60)

    start_bot_thread()
    await asyncio.sleep(2.0)

    if _bot_thread and _bot_thread.is_alive():
        log_print("   ربات تلگرام: 🟢 UP     polling فعال")
    else:
        log_print("   ربات تلگرام: ⚠️  بالا نیومد")

    log_print("-" * 60)
    log_print(f"   ✅ Public URL:  {PUBLIC_URL}")
    log_print(f"      Login    :  {PUBLIC_URL}/login")
    log_print(f"      Dash     :  {PUBLIC_URL}/dash")
    log_print(f"      Health   :  {PUBLIC_URL}/api/health")
    log_print(f"      Status   :  {PUBLIC_URL}/api/status")
    log_print("-" * 60)
    log_print(f"   🔧 Bind      :  http://{HOST}:{PORT}")
    log_print("")

    yield

    log_print("\n   [shutdown] خاموش کردن...")


# ══════════════════════════════════════════════════════════════
# FastAPI
# ══════════════════════════════════════════════════════════════
app = FastAPI(title="Rubika + Soroosh Panel", lifespan=lifespan)

if STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


import traceback as _tb_global


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception):
    tb = _tb_global.format_exc()
    log_print(f"\n❌ [500] {request.method} {request.url.path}")
    log_print(f"   {type(exc).__name__}: {str(exc)[:300]}")
    log_print(tb)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n===== 500 @ {request.method} {request.url.path} =====\n")
            f.write(f"{type(exc).__name__}: {exc}\n")
            f.write(tb)
    except Exception: pass
    return JSONResponse(status_code=500, content={
        "error": type(exc).__name__,
        "message": str(exc)[:500],
        "path": str(request.url.path),
    })


# ══════════════════════════════════════════════════════════════
# AUTH HELPERS
# ══════════════════════════════════════════════════════════════
def _get_token(request: Request) -> Optional[str]:
    tok = request.cookies.get("session")
    if tok: return tok
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        tok = auth[7:].strip()
        if tok: return tok
    return request.query_params.get("token")


def _check_token(tok):
    if not tok or tok not in SESSIONS: return None
    s = SESSIONS[tok]
    if time.time() > s["exp"]:
        SESSIONS.pop(tok, None); save_sessions(); return None
    return s


async def get_uid(request: Request) -> int:
    s = _check_token(_get_token(request))
    if not s: raise HTTPException(401, "unauth")
    return s["uid"]


def _page(n): return FileResponse(str(STATIC / n))


def _require(req, page):
    if not _check_token(_get_token(req)):
        return RedirectResponse("/login", status_code=302)
    return _page(page)


# ══════════════════════════════════════════════════════════════
# HTML Pages
# ══════════════════════════════════════════════════════════════
@app.get("/")
async def root(req: Request):
    return RedirectResponse("/dash" if _check_token(_get_token(req)) else "/login",
                            status_code=302)


@app.get("/login")
async def p_login(): return _page("login.html")

@app.get("/dash")
async def p_dash(request: Request): return _require(request, "dash.html")

@app.get("/accounts")
async def p_accs(request: Request): return _require(request, "accounts.html")

@app.get("/chats")
async def p_chats(request: Request): return _require(request, "chats.html")

@app.get("/chat/{aid}/{guid}")
async def p_chat_detail(request: Request, aid: str, guid: str):
    if not _check_token(_get_token(request)):
        return RedirectResponse("/login", status_code=302)
    return _page("chat.html")

@app.get("/send")
async def p_send(request: Request): return _require(request, "send.html")

@app.get("/channels")
async def p_chan(request: Request): return _require(request, "channels.html")

@app.get("/extract")
async def p_extr(request: Request): return _require(request, "extract.html")

@app.get("/reports")
async def p_rep(request: Request): return _require(request, "reports.html")

@app.get("/settings/{aid}")
async def p_settings_acc(request: Request, aid: str):
    if not _check_token(_get_token(request)):
        return RedirectResponse("/login", status_code=302)
    return _page("settings.html")

@app.get("/settings")
async def p_set(request: Request): return _require(request, "settings.html")

@app.get("/logs")
async def p_logs(request: Request): return _require(request, "logs.html")


# ══════════════════════════════════════════════════════════════
# AUTH API
# ══════════════════════════════════════════════════════════════
class LoginReq(BaseModel): telegram_id: int
class VerifyReq(BaseModel): telegram_id: int; code: str


@app.post("/api/auth/request")
async def auth_request(req: LoginReq):
    if req.telegram_id != FORCED_OWNER:
        raise HTTPException(403, "فقط مالک")
    code = gen_code()
    PENDING[req.telegram_id] = {"code": code, "exp": time.time() + 300, "tries": 0}
    try:
        from telegram import Bot as _TGB
        async with _TGB(token=TG_TOKEN) as tg:
            await tg.send_message(
                chat_id=req.telegram_id,
                text=f"🔐 <b>کد ورود پنل</b>\n\n<code>{code}</code>\n\n<i>۵ دقیقه</i>",
                parse_mode="HTML")
    except Exception as e:
        raise HTTPException(500, f"ارسال نشد: {e}")
    return {"ok": True}


@app.post("/api/auth/verify")
async def auth_verify(req: VerifyReq, response: Response):
    if req.telegram_id != FORCED_OWNER:
        raise HTTPException(403, "فقط مالک")
    p = PENDING.get(req.telegram_id)
    if not p: raise HTTPException(400, "اول کد بگیر")
    if time.time() > p["exp"]:
        PENDING.pop(req.telegram_id, None); raise HTTPException(400, "منقضی")
    if p["code"] != req.code.strip():
        p["tries"] += 1
        if p["tries"] >= 5: PENDING.pop(req.telegram_id, None)
        raise HTTPException(400, f"کد اشتباه ({p['tries']}/5)")
    PENDING.pop(req.telegram_id, None)
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {"uid": req.telegram_id, "exp": time.time() + 7 * 86400}
    save_sessions()
    # ★ روی HTTPS (Railway) کوکی secure می‌ذاریم
    response.set_cookie("session", token, httponly=True, samesite="lax",
                        secure=IS_HTTPS, path="/", max_age=7 * 86400)
    return {"ok": True, "token": token}


@app.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response):
    tok = _get_token(request)
    if tok:
        SESSIONS.pop(tok, None); save_sessions()
    response.delete_cookie("session", path="/")
    return {"ok": True}


@app.get("/api/me")
async def me(uid: int = Depends(get_uid)):
    return {"telegram_id": uid}


# ══════════════════════════════════════════════════════════════
# HEALTH / STATUS
# ══════════════════════════════════════════════════════════════
@app.get("/api/health")
async def api_health():
    return {
        "ok": True,
        "version": "v20",
        "owner": FORCED_OWNER,
        "rubika_loaded": rb is not None,
        "soroosh_loaded": sr is not None,
        "bot_alive": bool(_bot_thread and _bot_thread.is_alive()),
        "host": HOST,
        "port": PORT,
        "public_url": PUBLIC_URL,
        "railway": IS_RAILWAY,
        "data_dir": str(DATA_DIR),
    }


@app.get("/api/status")
async def api_status(uid: int = Depends(get_uid)):
    rb_accs = 0; sr_accs = 0
    try: rb_accs = len(rb.list_accounts()) if rb else 0
    except Exception: pass
    try: sr_accs = len(sr.list_accounts()) if sr else 0
    except Exception: pass
    return {
        "owner": FORCED_OWNER,
        "bot_alive": bool(_bot_thread and _bot_thread.is_alive()),
        "rubika": {"loaded": rb is not None, "accounts": rb_accs},
        "soroosh": {"loaded": sr is not None, "accounts": sr_accs},
        "active_modes": dict(USER_MODE),
        "public_url": PUBLIC_URL,
    }


@app.get("/api/logs")
async def api_logs(uid: int = Depends(get_uid)):
    return {"logs": LOGS[-200:]}


# ══════════════════════════════════════════════════════════════
# WEBSOCKET
# ══════════════════════════════════════════════════════════════
@app.websocket("/ws")
async def ws_ep(ws: WebSocket, token: str = Query("")):
    s = _check_token(token) or _check_token(ws.cookies.get("session"))
    if not s:
        await ws.close(code=1008); return
    uid = s["uid"]
    conn = await HUB.connect(ws, uid)
    conn.push({"type": "hello", "uid": uid})
    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=55)
            except asyncio.TimeoutError:
                break
            if raw == "ping":
                conn.push("pong"); continue
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        HUB.disconnect(conn)
        try: await ws.close()
        except Exception: pass


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    log_print("=" * 60)
    log_print("   🌐  Rubika + Soroosh — Unified (Railway)")
    log_print(f"   Public: {PUBLIC_URL}")
    log_print(f"   Bind  : {HOST}:{PORT}")
    log_print(f"   Owner : {FORCED_OWNER}")
    log_print("=" * 60)
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
        proxy_headers=True,               # ★ برای Railway (پشت پروکسی)
        forwarded_allow_ips="*",          # ★ اجازه X-Forwarded-* از پروکسی Railway
    )