"""Rubika + Soroosh + Eitaa Web Panel — v22 (Assistant integrated)"""

import sys, os, io, contextlib, logging

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


# ══════════════════════════════════════════════════════════════
# DATA_DIR
# ══════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════
# FIND BOTS
# ══════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════
# IMPORT BOTS
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


# ══════════════════════════════════════════════════════════════
# SET GLOBALS ON BOTS
# ══════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════
# RUBIKA SHIMS
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
# OWNER FILE
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
# SESSIONS / STATE
# ══════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════
# WebSocket HUB
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


# ══════════════════════════════════════════════════════════════
# STATIC
# ══════════════════════════════════════════════════════════════
STATIC = next((c for c in [HERE / "static", HERE.parent / "static"]
               if c.is_dir() and (c / "login.html").exists()), HERE / "static")


TG_APP: Optional[Application] = None


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════
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
# ASSISTANT — inline
# ══════════════════════════════════════════════════════════════
ASST_DIR = DATA_DIR / "assistant"
ASST_DIR.mkdir(parents=True, exist_ok=True)
ASST_CFG_FILE = ASST_DIR / "config.json"
ASST_SEEN_FILE = ASST_DIR / "seen.json"

ASST_DEFAULT = {
    "enabled": False,
    "group_id": 0,
    "accept_new_accounts": True,
    "max_accounts": 50,
    "apply_rubika": True,
    "apply_soroosh": True,
    "apply_eitaa": False,
    "run_template_id": None,
    "template_duration_hours": 6,
    "retry_after_s": 70,
    "give_up_after_s": 70,
    "notify_owner": True,
}

ASST_PENDING: Dict[str, dict] = {}
ASST_BATCHES: Dict[str, dict] = {}
ASST_USER_CACHE: Dict[str, dict] = {}
ASST_TASKS: Dict[str, asyncio.Task] = {}
ASST_WAITING: Dict[int, dict] = {}
ASST_RUNNING: Dict[str, dict] = {}


def asst_load_cfg():
    if not ASST_CFG_FILE.exists():
        asst_save_cfg(ASST_DEFAULT); return dict(ASST_DEFAULT)
    try:
        with open(ASST_CFG_FILE, encoding="utf-8") as f: d = json.load(f)
        return {**ASST_DEFAULT, **(d if isinstance(d, dict) else {})}
    except Exception: return dict(ASST_DEFAULT)


def asst_save_cfg(c):
    tmp = str(ASST_CFG_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ASST_CFG_FILE)


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
    if "سروش‌پلاس" in t or "سروش پلاس" in t: return "soroosh"
    if "روبیکا" in t or "Rubika" in t: return "rubika"
    return None


def asst_phones(text): return list(dict.fromkeys(_PHONE_RE.findall(text or "")))


def asst_uid(text):
    m = _UID_RE.search(text or "")
    return f"set_{m.group(1)}" if m else None


def asst_code(text):
    t = text or ""
    for pat in (r'کد\s*روبیکا\s*:\s*(\d{4,8})', r'Code\s+(\d{4,8})', r'کد\s*ورود\s*:\s*(\d{4,8})'):
        m = re.search(pat, t)
        if m: return m.group(1)
    return None


def _asst_get_mod(platform):
    return rb if platform == "rubika" else sr if platform == "soroosh" else ei if platform == "eitaa" else None


async def asst_send_rubika(phone): return {"ok": False, "status": "rubika_pending"}
async def asst_verify_rubika(phone, code, h=None): return {"ok": False, "status": "rubika_pending"}


async def asst_send_soroosh(phone):
    if sr is None: return {"ok": False, "status": "not_loaded"}
    try: return await asyncio.to_thread(sr.soroosh_send_code, phone)
    except Exception as e: return {"ok": False, "status": f"{type(e).__name__}: {str(e)[:100]}"}


async def asst_verify_soroosh(phone, code):
    if sr is None: return {"ok": False, "status": "not_loaded"}
    try: return await asyncio.to_thread(sr.soroosh_complete_login, phone, code)
    except Exception as e: return {"ok": False, "status": f"{type(e).__name__}: {str(e)[:100]}"}


async def asst_send_eitaa(phone):
    if ei is None: return {"ok": False, "status": "not_loaded"}
    fn = getattr(ei, "send_code", None) or getattr(ei, "eitaa_send_code", None)
    if not fn: return {"ok": False, "status": "no_api"}
    try:
        r = await asyncio.to_thread(fn, phone) if not asyncio.iscoroutinefunction(fn) else await fn(phone)
        return r if isinstance(r, dict) else {"ok": bool(r), "status": "ok" if r else "fail"}
    except Exception as e: return {"ok": False, "status": f"{type(e).__name__}: {str(e)[:100]}"}


async def asst_verify_eitaa(phone, code):
    if ei is None: return {"ok": False, "status": "not_loaded"}
    fn = getattr(ei, "complete_login", None) or getattr(ei, "eitaa_complete_login", None)
    if not fn: return {"ok": False, "status": "no_api"}
    try:
        r = await asyncio.to_thread(fn, phone, code) if not asyncio.iscoroutinefunction(fn) else await fn(phone, code)
        return r if isinstance(r, dict) else {"ok": bool(r), "status": "ok" if r else "fail"}
    except Exception as e: return {"ok": False, "status": f"{type(e).__name__}: {str(e)[:100]}"}


def asst_trim(platform, max_n):
    mod = _asst_get_mod(platform)
    if mod is None: return
    try:
        accs = mod.list_accounts()
        if len(accs) <= max_n: return
        items = sorted(accs.items(), key=lambda kv: (kv[1].get("created") or 0), reverse=True)
        for aid, _ in items[max_n:]:
            try: mod.remove_account(aid)
            except Exception: pass
        log_print(f"[asst] trim {platform} → {max_n}")
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
    if mod is None: return
    try:
        tpl = mod.get_template(tid)
        if not tpl: return
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
            try:
                await asyncio.wait_for(runner(op, log_print), timeout=1800)
            except asyncio.TimeoutError:
                log_print(f"[asst] {platform}:{aid} timeout 30min")
                try:
                    op2 = mod._get_op(op["id"])
                    if op2:
                        op2["status"] = "cancelled"
                        mod._save_op(op2)
                except Exception: pass
    except asyncio.CancelledError: raise
    except Exception as e:
        log_print(f"[asst-tpl] {platform}:{aid}: {type(e).__name__}: {e}")


async def asst_continuous_template(platform, aid, tid, hours, stop_event):
    key = f"{platform}:{aid}"
    end = time.time() + hours * 3600
    runs = 0
    log_print(f"[asst] {key} start (h={hours})")
    while not stop_event.is_set() and time.time() < end:
        runs += 1
        try: await asst_run_template_once(platform, aid, tid)
        except asyncio.CancelledError: break
        except Exception as e: log_print(f"[asst] {key} run#{runs}: {e}")
        if stop_event.is_set(): break
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30)
            break
        except asyncio.TimeoutError: pass
    log_print(f"[asst] {key} stop (runs={runs})")
    ASST_RUNNING.pop(key, None)


def asst_start_one(platform, aid, tid, hours):
    key = f"{platform}:{aid}"
    info = ASST_RUNNING.get(key)
    if info and info.get("task") and not info["task"].done():
        return False
    ev = asyncio.Event()
    t = asyncio.create_task(asst_continuous_template(platform, aid, tid, hours, ev))
    ASST_RUNNING[key] = {"task": t, "started": time.time(), "hours": hours, "stop": ev}
    return True


async def asst_start_all():
    cfg = asst_load_cfg()
    tid = cfg.get("run_template_id")
    if not tid: return 0
    hours = int(cfg.get("template_duration_hours", 6))
    n = 0
    if rb and cfg.get("apply_rubika"):
        try:
            for aid in rb.list_accounts():
                if asst_start_one("rubika", aid, tid, hours): n += 1
        except Exception: pass
    if sr and cfg.get("apply_soroosh"):
        try:
            for aid in sr.list_accounts():
                if asst_start_one("soroosh", aid, tid, hours): n += 1
        except Exception: pass
    if ei and cfg.get("apply_eitaa"):
        try:
            for aid in ei.list_accounts():
                if asst_start_one("eitaa", aid, tid, hours): n += 1
        except Exception: pass
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


async def asst_restart_all():
    await asst_stop_all()
    await asyncio.sleep(1)
    return await asst_start_all()


def asst_fmt_status(phone, results):
    parts = []
    for plat, label in (("soroosh","سروش"),("rubika","روبیکا"),("eitaa","ایتا")):
        r = results.get(plat) or {}
        st = r.get("status", "")
        if r.get("ok"): st = "✅ وارد شد"
        elif st == "awaiting_code": st = "⏳ در انتظار کد"
        elif st == "retrying": st = "🔄 تلاش مجدد"
        elif st == "giveup": st = "❌ بی‌پاسخ"
        elif "pending" in st: st = "🚧 (بعداً)"
        elif st: st = f"❌ {st[:30]}"
        if st: parts.append(f"{label}: {st}")
    return f"📞 <code>{esc(phone)}</code> — " + (" · ".join(parts) if parts else "—")


def asst_build_reply(bk):
    b = ASST_BATCHES.get(bk) or {}
    src = b.get("source", "?")
    label = {"lebeka":"لبکا","vision":"ویژن"}.get(src, src)
    lines = [f"📋 <b>گزارش ورود</b> — {label}", "━━━━━━━━━━━━━━"]
    for ph in b.get("phones", []):
        lines.append(asst_fmt_status(ph, b.get("results", {}).get(ph, {})))
    lines.append("")
    lines.append(f"🔖 منبع: <b>{label}</b>")
    lines.append(f"🪪 شناسه: <code>{esc(b.get('user_id') or '—')}</code>")
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
    m = await asst_send(chat_id, asst_build_reply(bk))
    if m: batch["msg_id"] = m.message_id

    for ph in phones:
        for plat in ("rubika","soroosh","eitaa"):
            if plat == "rubika" and not cfg.get("apply_rubika"): continue
            if plat == "soroosh" and not cfg.get("apply_soroosh"): continue
            if plat == "eitaa" and not cfg.get("apply_eitaa"): continue
            try:
                r = await (asst_send_rubika(ph) if plat=="rubika"
                           else asst_send_soroosh(ph) if plat=="soroosh"
                           else asst_send_eitaa(ph))
            except Exception as e: r = {"ok": False, "status": str(e)[:80]}
            ok = bool(r.get("ok"))
            ASST_PENDING[f"{ph}|{plat}"] = {
                "batch_key": bk, "phone": ph, "platform": plat,
                "phone_code_hash": r.get("phone_code_hash") or r.get("hash"),
                "sent_at": time.time(), "attempts": 1, "confirmed": False,
                "status": "awaiting_code" if ok else r.get("status","send_failed"),
            }
            batch["results"][ph][plat] = {
                "status": "awaiting_code" if ok else r.get("status","send_failed"), "ok": False}
    if batch["msg_id"]: await asst_edit(bk, batch["msg_id"], chat_id)

    await asst_sleep_or(batch["stop"], cfg.get("retry_after_s", 70))
    if batch.get("done"): return
    for v in list(ASST_PENDING.values()):
        if v["batch_key"] != bk or v["confirmed"]: continue
        ph, plat = v["phone"], v["platform"]
        try:
            r = await (asst_send_rubika(ph) if plat=="rubika"
                       else asst_send_soroosh(ph) if plat=="soroosh"
                       else asst_send_eitaa(ph))
        except Exception as e: r = {"ok": False, "status": str(e)[:80]}
        v["attempts"] += 1; v["sent_at"] = time.time()
        v["status"] = "retrying" if r.get("ok") else r.get("status","retry_failed")
        batch["results"][ph][plat] = {"status": v["status"], "ok": False}
    if batch["msg_id"]: await asst_edit(bk, batch["msg_id"], chat_id)

    await asst_sleep_or(batch["stop"], cfg.get("give_up_after_s", 70))
    if batch.get("done"): return
    for k, v in list(ASST_PENDING.items()):
        if v["batch_key"] != bk or v["confirmed"]: continue
        ph, plat = v["phone"], v["platform"]
        ASST_PENDING.pop(k, None)
        batch["results"][ph][plat] = {"status": "giveup", "ok": False}
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
        log_print(f"[asst-batch] {e}")
        import traceback; traceback.print_exc()
        if bk in ASST_BATCHES: ASST_BATCHES[bk]["done"] = True


async def asst_try_code(platform, code):
    for key, v in list(ASST_PENDING.items()):
        if v["platform"] != platform or v["confirmed"]: continue
        ph, bk = v["phone"], v["batch_key"]
        try:
            r = await (asst_verify_rubika(ph, code, v.get("phone_code_hash")) if platform=="rubika"
                       else asst_verify_soroosh(ph, code) if platform=="soroosh"
                       else asst_verify_eitaa(ph, code))
        except Exception as e: r = {"ok": False, "status": str(e)[:80]}
        if r.get("ok"):
            v["confirmed"] = True
            ASST_PENDING.pop(key, None)
            b = ASST_BATCHES.get(bk)
            if b:
                b["results"][ph][platform] = {"status": "confirmed", "ok": True}
                cfg = asst_load_cfg()
                asst_trim(platform, int(cfg.get("max_accounts", 50)))
                if b.get("msg_id"): await asst_edit(bk, b["msg_id"], b.get("chat_id"))
                tid = cfg.get("run_template_id")
                if tid:
                    mod = _asst_get_mod(platform)
                    if mod:
                        try:
                            for aid, a in mod.list_accounts().items():
                                if a.get("phone") == ph:
                                    hours = int(cfg.get("template_duration_hours", 6))
                                    asst_start_one(platform, aid, tid, hours)
                                    break
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

    if text.strip() == "چخبر":
        if msg.from_user and msg.from_user.id == FORCED_OWNER:
            await asst_stats_to(msg.chat_id, msg.message_id)
        return

    plat = asst_code_source(text)
    if plat:
        code = asst_code(text)
        if code:
            matched = await asst_try_code(plat, code)
            if matched:
                await asst_send(msg.chat_id,
                    f"✅ کد {plat} روی <code>{esc(matched)}</code> تایید شد",
                    reply_to=msg.message_id)
        return

    src = asst_pkg_source(text)
    if not src: return

    if not cfg.get("accept_new_accounts", True):
        await asst_send(msg.chat_id,
            "⏸ ثبت اکانت جدید موقتاً متوقف شده",
            reply_to=msg.message_id)
        return

    phones = asst_phones(text)
    uid = asst_uid(text)
    if not phones: return

    if uid: ASST_USER_CACHE[uid] = {"source": src, "phones": phones, "ts": time.time()}

    if uid and uid in ASST_SEEN:
        await asst_send(msg.chat_id,
            f"⚠️ این شناسه قبلاً ثبت شده: <code>{esc(uid)}</code>\nدوباره بزنم؟",
            reply_markup=asst_dedup_kb(uid),
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
    txt = (f"📊 <b>آمار دستیار</b>\n━━━━━━━━━━━━\n"
           f"📱 روبیکا: <b>{rb_n}</b>\n"
           f"🌀 سروش: <b>{sr_n}</b>\n"
           f"📨 ایتا: <b>{ei_n}</b>\n"
           f"⏳ در انتظار کد: <b>{pend}</b>\n"
           f"⚙️ بچ فعال: <b>{act}</b>\n"
           f"🎬 در حال اجرا: <b>{len(ASST_RUNNING)}</b>\n"
           f"🔖 شناسه‌ها: <b>{len(ASST_SEEN)}</b>")
    await asst_send(chat_id, txt, reply_to=reply_to)


async def asst_show_panel(cid, edit_mid=None):
    cfg = asst_load_cfg()
    rb_n = len(rb.list_accounts()) if rb else 0
    sr_n = len(sr.list_accounts()) if sr else 0
    ei_n = len(ei.list_accounts()) if ei else 0
    tpl_name = "—"
    tid = cfg.get("run_template_id")
    if tid and rb:
        try:
            t = rb.get_template(tid)
            if t: tpl_name = t.get("name", tid)
        except Exception: pass
    on = "🟢" if cfg.get("enabled") else "⚪"
    acc = "🟢" if cfg.get("accept_new_accounts", True) else "🔴"
    txt = (f"🎯 <b>دستیار</b>\n━━━━━━━━━━━━\n\n"
           f"📶 وضعیت: {on}\n"
           f"📥 پذیرش اکانت جدید: {acc}\n"
           f"💬 گروه: <code>{esc(str(cfg.get('group_id') or '—'))}</code>\n"
           f"🔢 حداکثر اکانت: <b>{cfg.get('max_accounts', 50)}</b>\n"
           f"🎬 قالب: <b>{esc(tpl_name)}</b>\n"
           f"⏱ مدت اجرا: <b>{cfg.get('template_duration_hours', 6)} ساعت</b>\n"
           f"🎬 در حال اجرا: <b>{len(ASST_RUNNING)}</b> اکانت\n\n"
           f"📊 روبیکا <b>{rb_n}</b> · سروش <b>{sr_n}</b> · ایتا <b>{ei_n}</b>")
    rows = [
        [B("⏸ توقف پذیرش" if cfg.get("accept_new_accounts", True) else "▶️ شروع پذیرش",
           "asst:toggle_accept"),
         B("خاموش کن" if cfg.get("enabled") else "روشن کن", "asst:toggle")],
        [B("💬 تنظیم گروه", "asst:set_group")],
        [B("🔢 حداکثر", "asst:set_max"), B("🎬 قالب", "asst:set_template")],
        [B(f"⏱ مدت: {cfg.get('template_duration_hours', 6)}h", "asst:set_hours")],
        [B("🔄 شروع مجدد همه", "asst:restart_all"),
         B("🛑 توقف همه", "asst:stop_all")],
        [B("📱 روبیکا " + ("🟢" if cfg.get("apply_rubika") else "⚪"), "asst:tog:rubika"),
         B("🌀 سروش " + ("🟢" if cfg.get("apply_soroosh") else "⚪"), "asst:tog:soroosh"),
         B("📨 ایتا " + ("🟢" if cfg.get("apply_eitaa") else "⚪"), "asst:tog:eitaa")],
        [B("📊 آمار", "asst:stats"), B("🔄 پاک pending", "asst:clear_pending")],
        [B("🏠 بازگشت", "mode:home")],
    ]
    markup = kb_(*rows)
    if edit_mid and TG_APP:
        try:
            await TG_APP.bot.edit_message_text(
                chat_id=cid, message_id=edit_mid, text=txt, reply_markup=markup,
                parse_mode="HTML", disable_web_page_preview=True)
            return
        except Exception as e:
            if "not modified" in str(e).lower(): return
    if TG_APP:
        try:
            m = await TG_APP.bot.send_message(
                chat_id=cid, text=txt, reply_markup=markup,
                parse_mode="HTML", disable_web_page_preview=True)
            for mod in (rb, sr, ei):
                if mod is not None:
                    try: mod.STATE["panel"][cid] = m.message_id
                    except Exception: pass
        except Exception as e: log_print(f"[asst-panel] {e}")


async def asst_route_cb(cid, data):
    cfg = asst_load_cfg()
    if data == "asst:toggle":
        cfg["enabled"] = not cfg.get("enabled"); asst_save_cfg(cfg)
        return await asst_show_panel(cid)
    if data == "asst:toggle_accept":
        cfg["accept_new_accounts"] = not cfg.get("accept_new_accounts", True)
        asst_save_cfg(cfg); return await asst_show_panel(cid)
    if data == "asst:set_group":
        ASST_WAITING[cid] = {"kind": "group"}
        if TG_APP:
            try: await TG_APP.bot.send_message(cid, "💬 شناسه گروه (مثلا <code>-1001234567890</code>):", parse_mode="HTML")
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
            try: await TG_APP.bot.send_message(cid, "⏱ چند ساعت مداوم؟ (1-48):")
            except Exception: pass
        return
    if data == "asst:set_template":
        if rb is None:
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "❌ روبیکا لود نشده")
                except Exception: pass
            return
        try: tpls = rb.list_templates()
        except Exception: tpls = {}
        if not tpls:
            if TG_APP:
                try: await TG_APP.bot.send_message(cid, "قالبی نیست.")
                except Exception: pass
            return
        rows = [[B(f"🎬 {t.get('name','?')[:24]}", f"asst:tpl_pick:{tid}")]
                for tid, t in list(tpls.items())[:12]]
        rows.append([B("❌ بدون قالب", "asst:tpl_pick:none")])
        if TG_APP:
            try: await TG_APP.bot.send_message(cid, "🎬 قالب:", reply_markup=kb_(*rows))
            except Exception: pass
        return
    if data.startswith("asst:tpl_pick:"):
        tid = data.split(":", 3)[3]
        cfg["run_template_id"] = None if tid == "none" else tid
        asst_save_cfg(cfg); return await asst_show_panel(cid)
    if data.startswith("asst:tog:"):
        plat = data.split(":", 3)[3]
        cfg[f"apply_{plat}"] = not cfg.get(f"apply_{plat}", plat in ("rubika","soroosh"))
        asst_save_cfg(cfg); return await asst_show_panel(cid)
    if data == "asst:restart_all":
        n = await asst_restart_all()
        if TG_APP:
            try: await TG_APP.bot.send_message(cid, f"🔄 شروع مجدد {n} اکانت")
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


async def asst_handle_force(q, data):
    parts = data.split(":", 4)
    if len(parts) < 4: return
    mode, uid = parts[2], parts[3]
    cached = ASST_USER_CACHE.get(uid)
    if not cached:
        try: await q.answer("❌ پیام کش نشده — دوباره فوروارد کن", show_alert=True)
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


async def asst_on_startup():
    try:
        cfg = asst_load_cfg()
        if not cfg.get("enabled"): return
        if not cfg.get("run_template_id"): return
        n = await asst_start_all()
        log_print(f"[asst] startup: started {n}")
    except Exception as e: log_print(f"[asst-startup] {e}")


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
    ei_v = getattr(ei, "VERSION", "—") if ei else "—"
    txt = (f"🔖 <b>app.py</b>: v22 (assistant)\n"
           f"📱 <b>روبیکا</b>: {rb_v}\n"
           f"🌀 <b>سروش</b>: {sr_v}\n"
           f"📨 <b>ایتا</b>: {ei_v}\n"
           f"👤 <b>مالک</b>: <code>{FORCED_OWNER}</code>\n"
           f"🌐 <b>Public</b>: {esc(PUBLIC_URL)}\n"
           f"💻 <b>Bind</b>: {HOST}:{PORT}\n"
           f"💾 <b>Data</b>: <code>{DATA_DIR}</code>\n"
           f"🎯 <b>Asst running</b>: {len(ASST_RUNNING)}")
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
        except Exception as e:
            log_print(f"[asst-force] {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()
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
        if rb is None:
            try: await q.edit_message_text("❌ پنل روبیکا لود نشده.", reply_markup=mode_selector_kb())
            except Exception: pass
            raise ApplicationHandlerStop
        try: await rb.show_main()
        except Exception as e:
            log_print(f"[rb.show_main] {type(e).__name__}: {e}")
        raise ApplicationHandlerStop

    if data == "mode:soroosh":
        USER_MODE[cid] = "soroosh"
        if sr is None:
            try: await q.edit_message_text("❌ پنل سروش لود نشده.", reply_markup=mode_selector_kb())
            except Exception: pass
            raise ApplicationHandlerStop
        try: await sr.show_main()
        except Exception as e:
            log_print(f"[sr.show_main] {type(e).__name__}: {e}")
        raise ApplicationHandlerStop

    if data == "mode:eitaa":
        USER_MODE[cid] = "eitaa"
        if ei is None:
            try: await q.edit_message_text("❌ پنل ایتا لود نشده.", reply_markup=mode_selector_kb())
            except Exception: pass
            raise ApplicationHandlerStop
        try: await ei.show_main()
        except Exception as e:
            log_print(f"[ei.show_main] {type(e).__name__}: {e}")
        raise ApplicationHandlerStop

    if data == "mode:assistant":
        USER_MODE[cid] = "assistant"
        try:
            await asst_show_panel(cid, edit_mid=q.message.message_id if q.message else None)
        except Exception as e:
            log_print(f"[asst.show] {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()
        raise ApplicationHandlerStop

    if data.startswith("asst:"):
        try:
            await asst_route_cb(cid, data)
        except Exception as e:
            log_print(f"[asst.route] {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()
        raise ApplicationHandlerStop

    if data in ("menu:home", "mode:home"):
        USER_MODE.pop(cid, None)
        await _render_mode_selector(cid, edit_mid=q.message.message_id)
        raise ApplicationHandlerStop

    mode = USER_MODE.get(cid)
    if mode == "rubika" and rb is not None:
        try: await rb.route_cb(cid, data)
        except Exception as e:
            log_print(f"[rb.route_cb] {type(e).__name__}: {e}")
            try: await TG_APP.bot.send_message(chat_id=cid, text=f"❌ {esc(type(e).__name__)}: {esc(str(e)[:200])}")
            except Exception: pass
        raise ApplicationHandlerStop

    if mode == "soroosh" and sr is not None:
        try: await sr.route_cb(cid, data)
        except Exception as e:
            log_print(f"[sr.route_cb] {type(e).__name__}: {e}")
            try: await TG_APP.bot.send_message(chat_id=cid, text=f"❌ {esc(type(e).__name__)}: {esc(str(e)[:200])}")
            except Exception: pass
        raise ApplicationHandlerStop

    if mode == "eitaa" and ei is not None:
        try: await ei.route_cb(cid, data)
        except Exception as e:
            log_print(f"[ei.route_cb] {type(e).__name__}: {e}")
            try: await TG_APP.bot.send_message(chat_id=cid, text=f"❌ {esc(type(e).__name__)}: {esc(str(e)[:200])}")
            except Exception: pass
        raise ApplicationHandlerStop

    if mode == "assistant":
        try:
            await asst_show_panel(cid, edit_mid=q.message.message_id if q.message else None)
        except Exception as e: log_print(f"[asst-fallback] {e}")
        raise ApplicationHandlerStop

    await _render_mode_selector(cid, edit_mid=q.message.message_id)
    raise ApplicationHandlerStop


# ══════════════════════════════════════════════════════════════
# MESSAGE ROUTER
# ══════════════════════════════════════════════════════════════
async def msg_router(update, context):
    if not authorized(update): return
    cid = update.effective_chat.id

    if cid in ASST_WAITING:
        w = ASST_WAITING.pop(cid)
        try: await asst_handle_wait(cid, w, update.message)
        except Exception as e: log_print(f"[asst-wait] {type(e).__name__}: {e}")
        return

    mode = USER_MODE.get(cid)

    if mode == "assistant":
        try: await update.message.reply_text("🎯 از پنل دستیار استفاده کن\n/menu")
        except Exception: pass
        return

    if mode == "rubika" and rb is not None:
        try: await rb.on_message(update, context)
        except Exception as e:
            log_print(f"[rb.on_message] {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()
        return

    if mode == "soroosh" and sr is not None:
        try: await sr.on_message(update, context)
        except Exception as e:
            log_print(f"[sr.on_message] {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()
        return

    if mode == "eitaa" and ei is not None:
        try: await ei.on_message(update, context)
        except Exception as e:
            log_print(f"[ei.on_message] {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()
        return

    try: await update.message.reply_text("🏠 اول یک پنل انتخاب کن.\n/start یا /menu")
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# POST INIT
# ══════════════════════════════════════════════════════════════
async def on_post_init(app: Application):
    global TG_APP
    TG_APP = app
    for mod in (rb, sr, ei):
        if mod is None: continue
        try: mod.APP = app
        except Exception: pass

    log_print("=" * 60)
    log_print("   🌐 Rubika + Soroosh + Eitaa + Assistant — v22")
    log_print(f"   Owner : {FORCED_OWNER}")
    log_print(f"   Public: {PUBLIC_URL}")
    log_print(f"   Bind  : {HOST}:{PORT}")
    log_print(f"   Data  : {DATA_DIR}")
    log_print(f"   rb bot: {RB_PATH or '—'}")
    log_print(f"   sr bot: {SR_PATH or '—'}")
    log_print(f"   ei bot: {EI_PATH or '—'}")
    log_print("=" * 60)

    try:
        await app.bot.set_my_commands([
            BotCommand("start", "شروع / انتخاب پنل"),
            BotCommand("menu", "منوی انتخاب پنل"),
            BotCommand("version", "نسخه"),
        ])
    except Exception: pass

    if rb is not None:
        try: asyncio.create_task(rb.start_all_listeners()); log_print("[rb] listeners scheduled")
        except Exception as e: log_print(f"[rb listeners] {type(e).__name__}: {e}")
        try: asyncio.create_task(rb.keepalive_loop()); log_print("[rb] keepalive scheduled")
        except Exception as e: log_print(f"[rb keepalive] {type(e).__name__}: {e}")

    if sr is not None:
        try: asyncio.create_task(sr.start_all_listeners()); log_print("[sr] listeners scheduled")
        except Exception as e: log_print(f"[sr listeners] {type(e).__name__}: {e}")
        try: asyncio.create_task(sr.keepalive_loop()); log_print("[sr] keepalive scheduled")
        except Exception as e: log_print(f"[sr keepalive] {type(e).__name__}: {e}")
        try:
            if hasattr(sr, "start_pv_responders"):
                asyncio.create_task(sr.start_pv_responders()); log_print("[sr] pv-responders scheduled")
        except Exception as e: log_print(f"[sr pv] {type(e).__name__}: {e}")

    if ei is not None:
        try:
            if hasattr(ei, "start_all_listeners"):
                asyncio.create_task(ei.start_all_listeners()); log_print("[ei] listeners scheduled")
        except Exception as e: log_print(f"[ei listeners] {type(e).__name__}: {e}")
        try:
            if hasattr(ei, "keepalive_loop"):
                asyncio.create_task(ei.keepalive_loop()); log_print("[ei] keepalive scheduled")
        except Exception as e: log_print(f"[ei keepalive] {type(e).__name__}: {e}")
        try:
            if hasattr(ei, "start_pv_responders"):
                asyncio.create_task(ei.start_pv_responders()); log_print("[ei] pv-responders scheduled")
        except Exception as e: log_print(f"[ei pv] {type(e).__name__}: {e}")

    try: asyncio.create_task(asst_cleanup_loop()); log_print("[asst] cleanup scheduled")
    except Exception as e: log_print(f"[asst cleanup] {type(e).__name__}: {e}")
    try: asyncio.create_task(asst_on_startup()); log_print("[asst] startup scheduled")
    except Exception as e: log_print(f"[asst startup] {type(e).__name__}: {e}")

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

    for mod in (rb, sr, ei):
        if mod is None: continue
        try: mod._loop_ref[0] = loop
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

    try:
        group_filter = tg_filters.ChatType.GROUP | tg_filters.ChatType.SUPERGROUP
        app.add_handler(MessageHandler(
            tg_filters.TEXT & ~tg_filters.COMMAND & group_filter,
            asst_group_handler), group=-2)
    except Exception as e:
        log_print(f"[asst-handler] {type(e).__name__}: {e}")

    app.add_handler(MessageHandler(
        tg_filters.ALL & ~tg_filters.COMMAND, msg_router))
    app.add_error_handler(on_error)

    TG_APP = app
    for mod in (rb, sr, ei):
        if mod is None: continue
        try: mod.APP = app
        except Exception: pass

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
    if _bot_thread is not None and _bot_thread.is_alive(): return False
    _bot_thread = threading.Thread(target=_bot_worker, daemon=True, name="telegram-bot")
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
    log_print("   🌐  Rubika + Soroosh + Eitaa + Assistant — v22")
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
    log_print("-" * 60)
    log_print(f"   🔧 Bind      :  http://{HOST}:{PORT}")
    log_print("")

    yield

    log_print("\n   [shutdown] خاموش کردن...")


# ══════════════════════════════════════════════════════════════
# FastAPI
# ══════════════════════════════════════════════════════════════
app = FastAPI(title="Rubika + Soroosh + Eitaa Panel", lifespan=lifespan)

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


@app.get("/")
async def root(req: Request):
    return RedirectResponse("/dash" if _check_token(_get_token(req)) else "/login", status_code=302)


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


class LoginReq(BaseModel): telegram_id: int
class VerifyReq(BaseModel): telegram_id: int; code: str


@app.post("/api/auth/request")
async def auth_request(req: LoginReq):
    if req.telegram_id != FORCED_OWNER: raise HTTPException(403, "فقط مالک")
    code = gen_code()
    PENDING[req.telegram_id] = {"code": code, "exp": time.time() + 300, "tries": 0}
    try:
        from telegram import Bot as _TGB
        async with _TGB(token=TG_TOKEN) as tg:
            await tg.send_message(
                chat_id=req.telegram_id,
                text=f"🔐 <b>کد ورود پنل</b>\n\n<code>{code}</code>\n\n<i>۵ دقیقه</i>",
                parse_mode="HTML")
    except Exception as e: raise HTTPException(500, f"ارسال نشد: {e}")
    return {"ok": True}


@app.post("/api/auth/verify")
async def auth_verify(req: VerifyReq, response: Response):
    if req.telegram_id != FORCED_OWNER: raise HTTPException(403, "فقط مالک")
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


@app.get("/api/health")
async def api_health():
    return {
        "ok": True, "version": "v22",
        "owner": FORCED_OWNER,
        "rubika_loaded": rb is not None,
        "soroosh_loaded": sr is not None,
        "eitaa_loaded": ei is not None,
        "bot_alive": bool(_bot_thread and _bot_thread.is_alive()),
        "assistant_running": len(ASST_RUNNING),
        "assistant_batches": len(ASST_BATCHES),
        "host": HOST, "port": PORT,
        "public_url": PUBLIC_URL, "railway": IS_RAILWAY,
        "data_dir": str(DATA_DIR),
    }


@app.get("/api/status")
async def api_status(uid: int = Depends(get_uid)):
    rb_accs = len(rb.list_accounts()) if rb else 0
    sr_accs = len(sr.list_accounts()) if sr else 0
    ei_accs = len(ei.list_accounts()) if ei else 0
    return {
        "owner": FORCED_OWNER,
        "bot_alive": bool(_bot_thread and _bot_thread.is_alive()),
        "rubika": {"loaded": rb is not None, "accounts": rb_accs},
        "soroosh": {"loaded": sr is not None, "accounts": sr_accs},
        "eitaa": {"loaded": ei is not None, "accounts": ei_accs},
        "assistant": {
            "enabled": asst_load_cfg().get("enabled"),
            "running": len(ASST_RUNNING),
            "pending": len(ASST_PENDING),
            "batches": len(ASST_BATCHES),
            "seen": len(ASST_SEEN),
        },
        "active_modes": dict(USER_MODE),
        "public_url": PUBLIC_URL,
    }


@app.get("/api/logs")
async def api_logs(uid: int = Depends(get_uid)):
    return {"logs": LOGS[-200:]}


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


if __name__ == "__main__":
    import uvicorn
    log_print("=" * 60)
    log_print("   🌐  Rubika + Soroosh + Eitaa + Assistant — v22")
    log_print(f"   Public: {PUBLIC_URL}")
    log_print(f"   Bind  : {HOST}:{PORT}")
    log_print(f"   Owner : {FORCED_OWNER}")
    log_print(f"   Token : {TG_TOKEN[:15]}...{TG_TOKEN[-6:]}")
    log_print("=" * 60)
    uvicorn.run(
        app, host=HOST, port=PORT, log_level="info",
        proxy_headers=True, forwarded_allow_ips="*",
    )