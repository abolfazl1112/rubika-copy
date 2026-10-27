# V48_ASST_APPLIED
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assistant_tg_bot.py — دستیار مستقل
قابل ران شدن به تنهایی یا توسط app.py
"""
import os, sys, json, io, asyncio, time, re, secrets, random, threading, shutil, unicodedata
import logging, traceback
from pathlib import Path
from typing import Optional, Dict, Any, List

VERSION = "Assistant v1.0"

# ══════════════════════════════════════════════════════════════
# Globals (set by app.py or standalone)
# ══════════════════════════════════════════════════════════════
sr = None                          # Soroosh module — set by app.py
TG_APP = None                      # Telegram Application
APP = None                         # alias
FORCED_OWNER = None
TG_TOKEN = ""
log_cb = None

STATE = {"owner": None, "panel": {}, "conv": {},
         "op_panel": {}, "listener_new_count": 0}
_loop_ref = [None]
LOGS: List[dict] = []
MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None
_TMP_EDIT = {}


def log_print(msg=""):
    try: print(msg, flush=True)
    except Exception: pass


def esc(s):
    import html as _h
    return _h.escape(str(s if s is not None else ""))


def short(s, n=40):
    s = str(s or "").replace("\n", " ")
    return s if len(s) <= n else s[:n-1] + "…"


def _eta(sec):
    sec = int(sec)
    if sec < 60: return f"{sec}ث"
    if sec < 3600: return f"{sec // 60}د"
    return f"{sec // 3600}س {(sec % 3600) // 60}د"


# ══════════════════════════════════════════════════════════════
# Paths
# ══════════════════════════════════════════════════════════════
def _asst_data_dir() -> Path:
    for cand in [os.environ.get("DATA_DIR", "").strip(),
                 os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip(),
                 "/data", "/app/data",
                 str(Path(__file__).parent / "data")]:
        if not cand: continue
        try:
            p = Path(cand)
            p.mkdir(parents=True, exist_ok=True)
            if p.is_dir() and os.access(p, os.W_OK): return p
        except Exception: pass
    return Path(__file__).parent


ASST_DIR = _asst_data_dir() / "assistant"
ASST_DIR.mkdir(parents=True, exist_ok=True)
ASST_CFG_FILE = ASST_DIR / "config.json"
ASST_SEEN_FILE = ASST_DIR / "seen.json"
ASST_HISTORY_FILE = ASST_DIR / "sms_history.json"

ASST_DEFAULT = {
    "enabled": False, "group_id": 0, "accept_new_accounts": True,
    "wipe_accounts_on_startup": True, "auto_start_on_boot": False,
    "max_accounts": 50, "run_template_id_soroosh": None,
    "template_duration_hours": 6, "retry_after_s": 60, "give_up_after_s": 180,
    "notify_owner": True, "force_sms": True,
    "force_sms_max_retries": 1, "force_sms_delay_s": 10,
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
        with open(ASST_CFG_FILE, encoding="utf-8") as f: d = json.load(f)
        if not isinstance(d, dict): return dict(ASST_DEFAULT)
        m = {**ASST_DEFAULT, **d}
        if int(m.get("give_up_after_s", 0)) < 120: m["give_up_after_s"] = 180
        if int(m.get("retry_after_s", 0)) < 45: m["retry_after_s"] = 60
        return m
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
        if len(history) > 2000: history = history[-2000:]
        tmp = str(ASST_HISTORY_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False)
        os.replace(tmp, ASST_HISTORY_FILE)
    except Exception: pass


ASST_SMS_HISTORY: List[dict] = _load_sms_history()


def _record_sms_event(phone, uid, send_type, fa, fs, status, error=None):
    ASST_SMS_HISTORY.append({
        "phone": phone, "uid": uid, "send_type": send_type,
        "force_attempted": fa, "force_success": fs, "status": status,
        "error": str(error)[:200] if error else None, "ts": int(time.time()),
    })
    _save_sms_history(ASST_SMS_HISTORY)


# ══════════════════════════════════════════════════════════════
# Text normalization
# ══════════════════════════════════════════════════════════════
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
        with open(tmp, "w", encoding="utf-8") as f: json.dump(V25_SEEN_PH, f)
        os.replace(tmp, V25_SEEN_FILE)
    except Exception: pass


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


def v25_vision_is_request_sent(text):
    if not text: return False
    marks = ["ʀᴇQᴜᴇꜱᴛ ʜᴀꜱ ʙᴇᴇɴ", "request has been",
             "ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ꜱᴇɴᴛ", "successfully sent",
             "ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ ꜰᴏʀ ʀᴇꜱᴘᴏɴꜱᴇ", "please wait for response",
             "ᴘᴜꜱʜ ᴛʏᴘᴇ", "push type", "ᴀɴᴅʀᴏɪᴅɪᴅ", "androidid"]
    for m in marks:
        if m in text or m.lower() in text.lower(): return True
    return False


def v25_vision_is_number_received(text):
    if not text: return False
    marks = ["ɴᴜᴍʙᴇʀ ʀᴇᴄᴇɪᴠᴇᴅ", "number received",
             "ʀᴇᴄᴇɪᴠᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ", "received successfully"]
    for m in marks:
        if m in text or m.lower() in text.lower(): return True
    return False


def v25_source(text, phones, uid):
    low = (text or "").lower()
    if "target #phones" in low or "lebeka team" in low or "@thelebeka" in low:
        return "lebeka"
    if v25_vision_is_number_received(text):
        return "vision" if phones else None
    if v25_vision_is_request_sent(text):
        return None
    for sig in ("› ᴠɪꜱɪᴏɴ", "› vision", "› ʋɪꜱɪᴏɴ"):
        if sig in text and phones: return "vision"
    if uid and phones: return "vision"
    return None


def _send_type_label(t):
    return {"sms": "🟢 SMS", "برنامه": "🟡 App", "app": "🟡 App",
            "تماس": "🔵 Call", "call": "🔵 Call", "email": "📧 Email",
            "firebase": "🔥 FB", "unknown": "⚪ ?", "": "⚪ ?"}.get(str(t), f"⚪ {t}")


def asst_code_source(text):
    t = text or ""
    t_clean = re.sub(r'[\s\u200c\u200d\ufeff]+', '', t)
    if "سروشپلاس" in t_clean or "soroosh" in t_clean.lower() or "سروش" in t_clean:
        return "soroosh"
    return None


def asst_code(text):
    t = text or ""
    t_norm = t.replace("：", ":")
    persian = "۰۱۲۳۴۵۶۷۸۹"; arabic = "٠١٢٣٤٥٦٧٨٩"
    t_norm = t_norm.translate(str.maketrans(persian + arabic, "01234567890123456789"))
    pats = [r'کد\s*ورود\s*:\s*(\d{4,8})(?!\d)', r'کد\s*سروش\s*:\s*(\d{4,8})(?!\d)',
            r'Code\s*:\s*(\d{4,8})(?!\d)', r'Code\s+(\d{4,8})(?!\d)',
            r'کد\s*:\s*(\d{4,8})(?!\d)']
    for t_test in (t, t_norm):
        for pat in pats:
            m = re.search(pat, t_test)
            if m: return m.group(1)
    t_clean = re.sub(r'[\s\u200c\u200d]+', '', t_norm)
    for pat in [r'کدورود:(\d{4,8})(?!\d)', r'کدسروش:(\d{4,8})(?!\d)',
                r'Code:(\d{4,8})(?!\d)', r'Code(\d{4,8})(?!\d)', r'کد:(\d{4,8})(?!\d)']:
        m = re.search(pat, t_clean)
        if m: return m.group(1)
    return None


def _threaded_runner(coro_fn, *args):
    def _r():
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        try: return loop.run_until_complete(coro_fn(*args))
        finally:
            try: loop.close()
            except Exception: pass
    return _r


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
                # V48: read V47 sent_type from entry
                st = e.get("sent_type")
                if st: return st
                c = e.get("cli")
                if c:
                    st2 = getattr(c, "_code_type_name", None)
                    if st2: return st2
    except Exception: pass
    return "unknown"


# ══════════════════════════════════════════════════════════════
# SMS force / send / verify
# ══════════════════════════════════════════════════════════════
async def _force_sms_soroosh(phone, max_retries=1, delay_s=10):
    if sr is None: return {"success": False, "reason": "sr_not_loaded", "attempts": []}
    norm = re.sub(r"[^\d]", "", phone or "")
    if norm.startswith("00"): norm = norm[2:]
    if norm.startswith("0"): norm = norm[1:]
    if not norm.startswith("98"): norm = "98" + norm
    entry = None
    for p in (phone, norm):
        if hasattr(sr, "_LOGIN_TMP") and p in sr._LOGIN_TMP:
            entry = sr._LOGIN_TMP[p]; break
    if not entry: return {"success": False, "reason": "no_pending_login", "attempts": []}
    cli = entry.get("cli")
    if cli is None: return {"success": False, "reason": "no_client", "attempts": []}
    variant = entry.get("variant") or f"+{norm}"
    attempts = []
    for i in range(max_retries):
        if i > 0 and delay_s > 0: await asyncio.sleep(delay_s)
        try:
            try:
                r = cli.send_code_request(variant, force_sms=True)
            except TypeError:
                r = cli.send_code_request(variant)
            if asyncio.iscoroutine(r): r = await r
            # V48: detect new type from response
            new_type = "unknown"
            try:
                if hasattr(sr, "_v47_detect_sent_type"):
                    new_type = sr._v47_detect_sent_type(r)
                else:
                    t = getattr(r, "type", None)
                    if t is not None:
                        tn = type(t).__name__.lower()
                        if "sms" in tn: new_type = "sms"
                        elif "flashcall" in tn: new_type = "flashcall"
                        elif "call" in tn: new_type = "call"
                        elif "app" in tn: new_type = "app"
            except Exception: pass
            # Update sent_type in entry regardless of outcome
            entry["sent_type"] = new_type
            try:
                sr._LOGIN_TMP[norm] = entry
                sr._LOGIN_TMP[phone] = entry
            except Exception: pass
            h = getattr(r, "phone_code_hash", None)
            if h is None and isinstance(r, dict): h = r.get("phone_code_hash")
            attempts.append({"attempt": i+1, "new_type": new_type, "got_hash": bool(h)})
            if new_type == "sms":
                if h: entry["hash"] = h
                sr._LOGIN_TMP[norm] = entry
                try: sr._LOGIN_TMP[phone] = entry
                except Exception: pass
                return {"success": True, "new_type": "sms", "phone_code_hash": h, "attempts": attempts}
        except Exception as e:
            err_s = f"{type(e).__name__}: {str(e)[:80]}"
            attempts.append({"attempt": i+1, "error": err_s})
            if "FLOOD" in err_s.upper() or "TOO_MANY" in err_s.upper():
                m = re.search(r"(\d+)", err_s)
                await asyncio.sleep(min(int(m.group(1)) if m else 15, 45))
    final = getattr(cli, "_code_type_name", "unknown") or "unknown"
    return {"success": False, "new_type": final, "reason": f"still_{final}", "attempts": attempts}


async def asst_send_soroosh(phone):
    if sr is None: return {"ok": False, "status": "not_loaded", "send_type": "unknown"}
    norm = re.sub(r"[^\d]", "", phone or "")
    if norm.startswith("00"): norm = norm[2:]
    if norm.startswith("0"): norm = norm[1:]
    if not norm.startswith("98"): norm = "98" + norm
    if hasattr(sr, "_LOGIN_TMP"):
        for p in (phone, norm):
            if p in sr._LOGIN_TMP:
                st = _asst_extract_send_type(phone)
                return {"ok": True, "status": "awaiting_code",
                        "phone_code_hash": sr._LOGIN_TMP[p].get("hash"),
                        "send_type": st, "send_type_label": _send_type_label(st),
                        "reused": True, "force_attempted": False}
    try:
        r = await asyncio.wait_for(
            asyncio.to_thread(_threaded_runner(sr.soroosh_send_code, phone)), timeout=95)
        if not isinstance(r, dict):
            return {"ok": False, "status": "bad_type", "send_type": "unknown"}
        if not r.get("ok"):
            return {"ok": False, "status": r.get("status", "send_failed"),
                    "send_type": "unknown", "force_attempted": False}
        initial = _asst_extract_send_type(phone)
        fa = False; fs = False; fd = None
        cfg = asst_load_cfg()
        if cfg.get("force_sms", True) and initial in ("برنامه", "app", "unknown", ""):
            fa = True
            fd = await _force_sms_soroosh(phone,
                max_retries=int(cfg.get("force_sms_max_retries", 1)),
                delay_s=int(cfg.get("force_sms_delay_s", 10)))
            if fd.get("success"):
                initial = "sms"; fs = True
        return {"ok": True, "status": "awaiting_code",
                "phone_code_hash": r.get("phone_code_hash"),
                "send_type": initial, "send_type_label": _send_type_label(initial),
                "force_attempted": fa, "force_success": fs, "force_details": fd}
    except asyncio.TimeoutError:
        return {"ok": False, "status": "timeout_95s", "send_type": "unknown", "force_attempted": False}
    except Exception as e:
        return {"ok": False, "status": f"{type(e).__name__}: {str(e)[:100]}",
                "send_type": "unknown", "force_attempted": False}


async def asst_verify_soroosh(phone, code):
    if sr is None: return {"ok": False, "status": "not_loaded"}
    try:
        r = await asyncio.wait_for(
            asyncio.to_thread(_threaded_runner(sr.soroosh_complete_login, phone, code)), timeout=125)
        return r if isinstance(r, dict) else {"ok": False, "status": "bad_type"}
    except asyncio.TimeoutError: return {"ok": False, "status": "timeout_125s"}
    except Exception as e: return {"ok": False, "status": f"{type(e).__name__}: {str(e)[:100]}"}


# ══════════════════════════════════════════════════════════════
# Template runner
# ══════════════════════════════════════════════════════════════
def asst_trim(max_n):
    if sr is None: return
    try:
        accs = sr.list_accounts()
        if len(accs) <= max_n: return
        items = sorted(accs.items(), key=lambda kv: (kv[1].get("created") or 0), reverse=True)
        for aid, _ in items[max_n:]:
            key = f"soroosh:{aid}"
            info = ASST_RUNNING.pop(key, None)
            if info:
                ev = info.get("stop")
                if ev:
                    try: ev.set()
                    except Exception: pass
                t = info.get("task")
                if t and not t.done():
                    try: t.cancel()
                    except Exception: pass
            try: sr.remove_account(aid)
            except Exception: pass
        asst_save_running_state()
    except Exception as e: log_print(f"[asst-trim] {e}")


def asst_save_running_state():
    data = {}
    for key, info in ASST_RUNNING.items():
        data[key] = {"platform": info.get("platform",""), "aid": info.get("aid",""),
                     "tid": info.get("tid",""), "started": info.get("started",0),
                     "hours": info.get("hours",6), "runs": info.get("runs",0)}
    try:
        tmp = str(ASST_DIR / "running.json") + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, ASST_DIR / "running.json")
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
            except asyncio.TimeoutError: pass
        return op["id"]
    except asyncio.CancelledError: raise
    except Exception: return None


async def asst_continuous_template(aid, tid, hours, stop_event):
    key = f"soroosh:{aid}"
    end = time.time() + hours * 3600
    runs = 0
    if sr is None:
        ASST_RUNNING.pop(key, None); asst_save_running_state(); return
    while not stop_event.is_set() and time.time() < end:
        try:
            if aid not in sr.list_accounts():
                break
        except Exception: pass
        try:
            if not sr.get_template(tid): break
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
            info3 = ASST_RUNNING.get(key)
            if info3: info3["last_error"] = str(e)[:200]
        if stop_event.is_set(): break
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30); break
        except asyncio.TimeoutError: pass
    ASST_RUNNING.pop(key, None)
    asst_save_running_state()


def asst_start_one(aid, tid, hours):
    key = f"soroosh:{aid}"
    info = ASST_RUNNING.get(key)
    if info and info.get("task") and not info["task"].done(): return False
    ev = asyncio.Event()
    t = asyncio.create_task(asst_continuous_template(aid, tid, hours, ev))
    ASST_RUNNING[key] = {"task": t, "started": time.time(), "hours": hours, "stop": ev,
                         "runs": 0, "platform": "soroosh", "aid": aid, "tid": tid,
                         "current_op_id": None, "last_error": None}
    asst_save_running_state()
    return True


async def asst_start_all():
    cfg = asst_load_cfg()
    hours = int(cfg.get("template_duration_hours", 6))
    tid = cfg.get("run_template_id_soroosh")
    if not tid or sr is None: return 0
    n = 0
    try:
        for aid in sr.list_accounts():
            if asst_start_one(aid, tid, hours): n += 1
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
    asst_save_running_state()


async def asst_restart_all():
    await asst_stop_all()
    await asyncio.sleep(1)
    return await asst_start_all()


# ══════════════════════════════════════════════════════════════
# Batch
# ══════════════════════════════════════════════════════════════
def asst_build_reply(bk):
    b = ASST_BATCHES.get(bk) or {}
    src = b.get("source", "?")
    label = {"lebeka":"لبکا","vision":"ویژن"}.get(src, src)
    phones = b.get("phones", [])
    results = b.get("results", {})
    lines = [f"📋 <b>گزارش ورود سروش</b> — {label}", "━"*30, ""]
    for ph in phones:
        v = results.get(ph) or {}
        status = v.get("status", "")
        st = _send_type_label(v.get("send_type", "unknown"))
        fm = ""
        if v.get("force_attempted"):
            fm = " 🔄✓" if v.get("force_success") else " 🔄✗"
        icon = {"confirmed":"✅","giveup":"❌","retrying":"🔄","awaiting_code":"⏳"}.get(status, "⚪")
        lines.append(f"{icon} <code>{esc(ph)}</code> — {st}{fm}")
    if not phones: lines.append("<i>خالی</i>")
    lines.append("")
    lines.append(f"🪪 شناسه: <code>{esc(b.get('user_id') or '—')}</code>")
    errs = ASST_BATCH_ERRORS.get(bk, [])
    if errs:
        lines.append(f"\n⚠️ <b>خطاها ({len(errs)}):</b>")
        for e in errs[-3:]: lines.append(f"<code>• {esc(e[:80])}</code>")
    return "\n".join(lines)


async def asst_send(chat_id, text, reply_markup=None, reply_to=None):
    if TG_APP is None: return None
    try:
        kw = {"chat_id": chat_id, "text": text[:4000],
              "parse_mode": "HTML", "disable_web_page_preview": True}
        if reply_markup: kw["reply_markup"] = reply_markup
        if reply_to: kw["reply_to_message_id"] = reply_to
        return await TG_APP.bot.send_message(**kw)
    except Exception: return None


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

    # V48: send to ALL phones in parallel (10 at a time)
    _v48_sem = asyncio.Semaphore(10)
    async def _v48_send_one(ph):
        async with _v48_sem:
            try: return ph, await asst_send_soroosh(ph)
            except Exception as e:
                return ph, {"ok": False, "status": str(e)[:80],
                            "send_type": "unknown", "force_attempted": False}

    _v48_results = await asyncio.gather(
        *[_v48_send_one(ph) for ph in phones], return_exceptions=False)

    for ph, r in _v48_results:
        ok = bool(r.get("ok"))
        if not ok:
            ASST_BATCH_ERRORS[bk].append(f"{ph}: {r.get('status','?')[:60]}")
        ASST_PENDING[f"{ph}|soroosh"] = {
            "batch_key": bk, "phone": ph, "platform": "soroosh",
            "phone_code_hash": r.get("phone_code_hash") or r.get("hash"),
            "sent_at": time.time(), "attempts": 1, "confirmed": False,
            "status": "awaiting_code" if ok else r.get("status", "send_failed"),
            "send_type": r.get("send_type", "unknown"),
            "force_attempted": r.get("force_attempted", False),
            "force_success": r.get("force_success", False)}
        batch["results"][ph] = {
            "status": ASST_PENDING[f"{ph}|soroosh"]["status"], "ok": False,
            "send_type": r.get("send_type", "unknown"),
            "force_attempted": r.get("force_attempted", False),
            "force_success": r.get("force_success", False), "sent_at": time.time()}
        _record_sms_event(ph, user_id, r.get("send_type","unknown"),
                          r.get("force_attempted",False), r.get("force_success",False),
                          batch["results"][ph]["status"])

    if batch["msg_id"]: await asst_edit(bk, batch["msg_id"], chat_id)

    await asst_sleep_or(batch["stop"], cfg.get("retry_after_s", 60))
    if batch.get("done"): return

    for v in list(ASST_PENDING.values()):
        if v["batch_key"] != bk or v["confirmed"]: continue
        ph = v["phone"]
        if v.get("send_type","unknown") in ("برنامه","app","unknown") and \
           not v.get("force_attempted") and cfg.get("force_sms", True):
            fr = await _force_sms_soroosh(ph,
                max_retries=int(cfg.get("force_sms_max_retries",1)),
                delay_s=int(cfg.get("force_sms_delay_s",10)))
            v["force_attempted"] = True
            if fr.get("success"):
                v["send_type"] = "sms"; v["force_success"] = True
                if fr.get("phone_code_hash"): v["phone_code_hash"] = fr["phone_code_hash"]
                batch["results"][ph].update({"send_type":"sms","force_attempted":True,"force_success":True})
            else:
                v["force_success"] = False
                batch["results"][ph].update({"force_attempted":True,"force_success":False})

    if batch["msg_id"]: await asst_edit(bk, batch["msg_id"], chat_id)

    await asst_sleep_or(batch["stop"], cfg.get("give_up_after_s", 180))
    if batch.get("done"): return

    for v in list(ASST_PENDING.values()):
        if v["batch_key"] != bk or v["confirmed"]: continue
        v["status"] = "giveup"
        batch["results"][v["phone"]]["status"] = "giveup"

    batch["done"] = True
    if batch["msg_id"]: await asst_edit(bk, batch["msg_id"], chat_id)


async def asst_safe_batch(bk, *args):
    try: await asst_run_batch(bk, *args)
    except asyncio.CancelledError:
        if bk in ASST_BATCHES: ASST_BATCHES[bk]["done"] = True
        raise
    except Exception as e:
        log_print(f"[asst-batch] FATAL: {type(e).__name__}: {e}")
        if bk not in ASST_BATCH_ERRORS: ASST_BATCH_ERRORS[bk] = []
        ASST_BATCH_ERRORS[bk].append(f"FATAL: {type(e).__name__}: {str(e)[:200]}")
        if bk in ASST_BATCHES:
            ASST_BATCHES[bk]["done"] = True


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
                            asst_start_one(aid, tid, int(cfg.get("template_duration_hours", 6)))
                            break
                except Exception: pass
            return ph
        else:
            if TG_APP:
                err_msg = str(r.get("status") or "unknown")
                try:
                    await TG_APP.bot.send_message(chat_id=FORCED_OWNER,
                        text=f"❌ خطای ورود سروش\n📞 <code>{esc(ph)}</code>\n🔑 <code>{esc(code)}</code>\n⚠️ <code>{esc(err_msg[:200])}</code>",
                        parse_mode="HTML")
                except Exception: pass
    return None


def asst_dedup_kb(uid):
    return kb_([B("🔁 ورود مجدد", f"asst:force:soroosh:{uid}")], [B("❌ لغو", "noop")])


# ══════════════════════════════════════════════════════════════
# Telegram UI helpers
# ══════════════════════════════════════════════════════════════
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter
from telegram.ext import ApplicationHandlerStop


def B(label, data):
    return InlineKeyboardButton(label, callback_data=data)


def kb_(*rows): return InlineKeyboardMarkup([list(r) for r in rows if r])


def grid(btns, cols=2): return [btns[i:i+cols] for i in range(0, len(btns), cols)]


def nav(back="mode:tools", home=True):
    row = []
    if back: row.append(B("« بازگشت", back))
    if home: row.append(B("🏠 منوی اصلی", "menu:home"))
    return row


_PANEL_SIG = {}
_PAGE_STATE = {}


def _sig(text, kb):
    import hashlib
    try: k = json.dumps(kb.to_dict(), sort_keys=True) if kb else ""
    except Exception: k = repr(kb)
    return hashlib.md5((text + "|" + k).encode()).hexdigest()


def _set_page(cid, tag):
    try: _PAGE_STATE[int(cid)] = str(tag)
    except Exception: pass


def _is_page(cid, tag):
    try: return _PAGE_STATE.get(int(cid)) == tag
    except Exception: return False


async def panel(text, kb=None, page_tag=None):
    cid = STATE.get("owner")
    if not cid or TG_APP is None: return
    if page_tag: _set_page(cid, page_tag)
    text = str(text)[:4000]
    sig = _sig(text, kb)
    mid = STATE["panel"].get(cid)
    if mid:
        if _PANEL_SIG.get(cid) == (mid, sig): return
        try:
            await TG_APP.bot.edit_message_text(chat_id=cid, message_id=mid, text=text,
                                               reply_markup=kb, parse_mode=ParseMode.HTML,
                                               disable_web_page_preview=True)
            _PANEL_SIG[cid] = (mid, sig); return
        except BadRequest as e:
            if "not modified" in str(e).lower():
                _PANEL_SIG[cid] = (mid, sig); return
        except RetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 0.5)
            try:
                await TG_APP.bot.edit_message_text(chat_id=cid, message_id=mid, text=text,
                                                   reply_markup=kb, parse_mode=ParseMode.HTML)
                _PANEL_SIG[cid] = (mid, sig); return
            except Exception: pass
        except Exception: pass
    for _ in range(3):
        try:
            m = await TG_APP.bot.send_message(chat_id=cid, text=text, reply_markup=kb,
                                              parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            STATE["panel"][cid] = m.message_id
            _PANEL_SIG[cid] = (m.message_id, sig); return
        except RetryAfter as e: await asyncio.sleep(float(e.retry_after) + 0.5)
        except Exception: await asyncio.sleep(1.5)


async def tg_send(text, markup=None):
    if not STATE.get("owner") or TG_APP is None: return False
    for _ in range(3):
        try:
            await TG_APP.bot.send_message(chat_id=STATE["owner"], text=str(text)[:4000],
                                          reply_markup=markup, parse_mode="HTML",
                                          disable_web_page_preview=True)
            return True
        except RetryAfter as e: await asyncio.sleep(float(e.retry_after) + 0.5)
        except Exception: await asyncio.sleep(1.5)
    return False


async def ask(text):
    await panel(text, kb_([B("« لغو", "asst:refresh")]), page_tag="ask")


def get_conv(cid):
    c = STATE["conv"].get(cid)
    if not c: c = STATE["conv"][cid] = {}
    return c


def clear_conv(cid): STATE["conv"].pop(cid, None)


def authorized(update):
    try: return update.effective_chat.id == FORCED_OWNER
    except Exception: return False


def _bar(pct, n=14):
    pct = max(0, min(100, int(pct)))
    return "█" * int(pct * n / 100) + "░" * (n - int(pct * n / 100))


def _v25_bar(pct, n=14):
    return _bar(pct, n) + f" {max(0,min(100,int(pct)))}%"


# ══════════════════════════════════════════════════════════════
# Panels
# ══════════════════════════════════════════════════════════════
async def v25_show_main(cid, edit_mid=None):
    if edit_mid is None: edit_mid = STATE["panel"].get(cid)
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
           f"<b>📊 اکانت‌ها:</b> 🌀 سروش: <b>{sr_n}</b>")
    rows = [
        [B(f"📊 داشبورد ({running})", "asst:dash")],
        [B("🚀 عملیات گروهی", "asst:bulk")],
        [B("🎬 قالب سروش", "asst:set_tpl:soroosh"), B("⚙️ تنظیمات", "asst:menu:settings")],
        [B("📈 آمار و لاگ‌ها", "asst:menu:stats")],
        [B("📨 آمار پیامک", "asst:stats:sms")],
        [B("خاموش کن" if cfg.get("enabled") else "روشن کن", "asst:toggle")],
        [B("🏠 بازگشت به Tools", "mode:tools")],
    ]
    markup = kb_(*rows)
    if edit_mid and TG_APP:
        try:
            await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt,
                                               reply_markup=markup, parse_mode="HTML",
                                               disable_web_page_preview=True)
            STATE["panel"][cid] = edit_mid; return
        except Exception as e:
            if "not modified" in str(e).lower(): return
    if TG_APP:
        try:
            m = await TG_APP.bot.send_message(cid, txt, reply_markup=markup,
                                              parse_mode="HTML", disable_web_page_preview=True)
            STATE["panel"][cid] = m.message_id
        except Exception: pass


async def v25_show_dashboard(cid, edit_mid=None):
    total = len(ASST_RUNNING)
    txt = f"📊 <b>داشبورد زنده</b> — {total} اکانت\n━━━━━━━━━━━━━━━\n\n"
    if total == 0: txt += "<i>هیچ اکانتی در حال اجرا نیست</i>"
    else:
        txt += "🌀 <b>سروش</b>:\n"
        accs = {}
        try:
            if sr: accs = sr.list_accounts() or {}
        except Exception: pass
        for key, info in list(ASST_RUNNING.items())[:6]:
            aid = info.get("aid") or key.split(":",1)[1]
            name = (accs.get(aid) or {}).get("name", aid[:10])[:18]
            txt += f"  • <b>{esc(name)}</b> — دور {info.get('runs',0)} — {_eta(int(time.time()-info.get('started',0)) if info.get('started') else 0)}\n"
        if total > 6: txt += f"  <i>+{total-6} دیگر</i>\n"
    rows = [[B(f"🌀 جزئیات ({total})", "asst:dash:plat:soroosh")]] if total else []
    rows.append([B("🔄 بروزرسانی", "asst:dash")])
    rows.append([B("« بازگشت", "asst:refresh")])
    await _do_edit_or_send(cid, txt, kb_(*rows), edit_mid, "dash")


async def _do_edit_or_send(cid, txt, markup, edit_mid, tag):
    if edit_mid and TG_APP:
        try:
            await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid,
                                               text=txt[:4000], reply_markup=markup,
                                               parse_mode="HTML", disable_web_page_preview=True)
            STATE["panel"][cid] = edit_mid; return
        except Exception as e:
            if "not modified" in str(e).lower(): return
    if TG_APP:
        try:
            m = await TG_APP.bot.send_message(cid, txt[:4000], reply_markup=markup,
                                              parse_mode="HTML", disable_web_page_preview=True)
            STATE["panel"][cid] = m.message_id
        except Exception: pass


async def v25_show_dash_platform(cid, edit_mid=None):
    accs = {}
    try:
        if sr: accs = sr.list_accounts() or {}
    except Exception: pass
    keys = [k for k in ASST_RUNNING if k.startswith("soroosh:")]
    txt = f"🌀 <b>سروش — اجراهای فعال</b>\n━━━━━━━━━━━━━━━\n\n"
    if not keys: txt += "<i>هیچ اکانتی</i>"
    rows = []
    for key in keys:
        info = ASST_RUNNING.get(key) or {}
        aid = info.get("aid") or key.split(":",1)[1]
        name = (accs.get(aid) or {}).get("name", aid)[:22]
        txt += f"👤 <b>{esc(name)}</b> — دور {info.get('runs',0)}\n"
        rows.append([B(f"👤 {esc(name[:22])}", f"asst:acc:soroosh:{aid}")])
    rows.append([B("« بازگشت", "asst:dash")])
    await _do_edit_or_send(cid, txt, kb_(*rows), edit_mid, "dash_plat")


async def v25_show_account_detail(cid, aid, edit_mid=None):
    info = ASST_RUNNING.get(f"soroosh:{aid}")
    if not info:
        return await tg_send("⚠️ اکانت در حال اجرا نیست")
    accs = {}
    try:
        if sr: accs = sr.list_accounts() or {}
    except Exception: pass
    acc = accs.get(aid) or {}
    name = acc.get("name") or aid[:12]
    phone = acc.get("phone") or "—"
    tpl = None
    try:
        if sr and info.get("tid"): tpl = sr.get_template(info["tid"])
    except Exception: pass
    op = None
    try:
        if sr and info.get("current_op_id"): op = sr._get_op(info["current_op_id"])
    except Exception: pass
    prog = (op.get("progress") if op else {}) or {}
    txt = (f"🌀 <b>{esc(name[:24])}</b>\n📞 <code>{esc(phone)}</code>\n"
           f"🔁 دور {info.get('runs',0)} · ⏱ {_eta(int(time.time()-info.get('started',0)) if info.get('started') else 0)} / {info.get('hours',6)}h\n"
           "━━━━━━━━━━━━━━━\n")
    if tpl:
        txt += f"🎬 قالب #{tpl.get('num_id','?')} — <b>{esc(tpl.get('name','?')[:24])}</b>\n"
    # sections
    sx = prog.get("sections") or {}
    if sx:
        txt += "\n<b>📊 جزئیات:</b>"
        for k, label, icon in [
            ("channel", "کانال", "🏗"),
            ("profile", "پروفایل", "👤"),
            ("joiner", "جوین", "🤝"),
            ("sender", "ارسال", "📤"),
            ("pv", "PV", "💬"),
        ]:
            s = sx.get(k) or {}
            if not s: continue
            st = s.get("status", "")
            ic = {"created":"✅","done":"✅","live":"🟢","running":"🟢",
                  "failed":"❌","stopped":"⏹","creating":"⏳"}.get(st, "⚪")
            txt += f"\n{icon} {label}: {ic}"
            if s.get("link"): txt += f" <code>{esc(s['link'][:30])}</code>"
            if s.get("joined"): txt += f" ✓{s['joined']}"
            if s.get("failed"): txt += f" ✗{s['failed']}"
    if prog.get("phase"): txt += f"\n\n📍 <i>{esc(str(prog['phase'])[:70])}</i>"
    if info.get("last_error"): txt += f"\n⚠️ <code>{esc(info['last_error'][:100])}</code>"
    rows = [
        [B("🔄 بروزرسانی", f"asst:acc:soroosh:{aid}")],
        [B("🛑 توقف", f"asst:acc_stop:soroosh:{aid}")],
        [B("« بازگشت", "asst:dash:plat:soroosh")],
    ]
    await _do_edit_or_send(cid, txt, kb_(*rows), edit_mid, f"acc:{aid}")


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
         B(f"⏱ {cfg.get('force_sms_delay_s', 10)}s", "asst:set_force_delay")],
        [B("⏸ توقف پذیرش" if cfg.get("accept_new_accounts", True) else "▶️ شروع پذیرش", "asst:toggle_accept")],
        [B("« بازگشت", "asst:refresh")],
    ]
    await _do_edit_or_send(cid, txt, kb_(*rows), edit_mid, "settings")


async def v25_show_menu_templates(cid, edit_mid=None):
    cfg = asst_load_cfg()
    tid = cfg.get("run_template_id_soroosh")
    tpl_name = "—"
    if tid and sr:
        try:
            t = sr.get_template(tid)
            if t: tpl_name = f"#{t.get('num_id','?')} {t.get('name','?')[:16]}"
        except Exception: pass
    txt = f"🎬 <b>قالب سروش</b>\n━━━━━━━━━━━━━━━\n\n🌀 قالب: <b>{esc(tpl_name)}</b>\n\n🎯 در حال اجرا: <b>{len(ASST_RUNNING)}</b>"
    rows = [
        [B("🌀 انتخاب قالب سروش", "asst:set_tpl:soroosh")],
        [B("🔄 شروع مجدد", "asst:restart_all"), B("🛑 توقف", "asst:stop_all")],
        [B("« بازگشت", "asst:refresh")],
    ]
    await _do_edit_or_send(cid, txt, kb_(*rows), edit_mid, "templates")


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
        [B("📨 آمار پیامک", "asst:stats:sms")],
        [B("📋 لاگ‌ها", "asst:logs"), B("🔄 پاک pending", "asst:clear_pending")],
        [B("« بازگشت", "asst:refresh")],
    ]
    await _do_edit_or_send(cid, txt, kb_(*rows), edit_mid, "stats")


async def v25_show_sms_stats(cid, page=0, edit_mid=None):
    entries = []
    for bk, b in ASST_BATCHES.items():
        for ph in b.get("phones", []):
            v = b.get("results", {}).get(ph, {})
            entries.append({"phone": ph, "uid": b.get("user_id"),
                "send_type": v.get("send_type","unknown"),
                "force_attempted": v.get("force_attempted",False),
                "force_success": v.get("force_success",False),
                "status": v.get("status","unknown"),
                "ok": v.get("ok",False),
                "ts": int(v.get("sent_at", b.get("started",0)))})
    for h in ASST_SMS_HISTORY[-300:]:
        entries.append({"phone": h.get("phone"), "uid": h.get("uid"),
            "send_type": h.get("send_type","unknown"),
            "force_attempted": h.get("force_attempted",False),
            "force_success": h.get("force_success",False),
            "status": h.get("status","unknown"),
            "ok": h.get("status")=="confirmed", "ts": h.get("ts",0)})
    def _sort(e):
        return ({"awaiting_code":0,"retrying":1,"confirmed":2,"giveup":3,"failed":4}.get(e["status"],5), -e["ts"])
    entries.sort(key=_sort)
    total = len(entries)
    sms_c = sum(1 for e in entries if e["send_type"]=="sms")
    app_c = sum(1 for e in entries if e["send_type"] in ("برنامه","app"))
    conf = sum(1 for e in entries if e["ok"] or e["status"]=="confirmed")
    aw = sum(1 for e in entries if e["status"]=="awaiting_code")
    gu = sum(1 for e in entries if e["status"]=="giveup")
    def pct(n): return int(100*n/total) if total else 0
    txt = f"📨 <b>آمار پیامک</b>\n{'━'*30}\n\n"
    txt += f"📊 کل: <b>{total}</b>\n"
    if total:
        txt += f"🟢 SMS: <b>{sms_c}</b> ({pct(sms_c)}%)\n"
        txt += f"🟡 App: <b>{app_c}</b> ({pct(app_c)}%)\n"
    txt += f"\n✅ تایید: <b>{conf}</b>\n"
    if aw: txt += f"⏳ در انتظار: <b>{aw}</b>\n"
    if gu: txt += f"❌ بی‌پاسخ: <b>{gu}</b>\n"
    PER = 15; pages = max(1, -(-total // PER)); page = max(0, min(page, pages-1))
    chunk = entries[page*PER:(page+1)*PER]
    if chunk:
        txt += f"\n<b>📋 لیست ({page+1}/{pages}):</b>\n\n"
        for e in chunk:
            st = e["status"]
            icon = {"confirmed":"✅","giveup":"❌","retrying":"🔄","awaiting_code":"⏳"}.get(st,"⚪")
            fm = ""
            if e["force_attempted"]: fm = " 🔄✓" if e["force_success"] else " 🔄✗"
            txt += f"{icon} <code>{esc(e['phone'])}</code> — {_send_type_label(e['send_type'])}{fm}\n"
    rows = []
    if pages > 1:
        pr = []
        if page > 0: pr.append(B("◀️", f"asst:stats:sms:{page-1}"))
        pr.append(B(f"{page+1}/{pages}", "noop"))
        if page < pages-1: pr.append(B("▶️", f"asst:stats:sms:{page+1}"))
        rows.append(pr)
    rows.append([B("🔄", f"asst:stats:sms:{page}"), B("🗑 پاک", "asst:stats:clear")])
    rows.append([B("« بازگشت", "asst:menu:stats")])
    await _do_edit_or_send(cid, txt, kb_(*rows), edit_mid, "sms_stats")


async def asst_show_logs(cid, page=0):
    logs = list(LOGS[-100:])
    for bk, errs in ASST_BATCH_ERRORS.items():
        for e in errs[-10:]:
            logs.append({"text": f"[batch {bk[-4:]}] {e}", "ts": time.time()})
    logs.sort(key=lambda x: x.get("ts",0))
    PER = 15; pages = max(1, -(-len(logs)//PER)); page = max(0, min(page, pages-1))
    chunk = logs[page*PER:(page+1)*PER]
    txt = f"📋 <b>لاگ‌ها</b> — {len(logs)}\n━━━━━━━━━━━━━\n\n"
    for lg in chunk:
        t = time.strftime("%H:%M:%S", time.localtime(lg.get("ts",0)))
        txt += f"<code>{t}</code> {esc(str(lg.get('text',''))[:150])}\n"
    rows = [[B("🔄", f"asst:logs:{page}"), B("« بازگشت", "asst:refresh")]]
    if TG_APP:
        try:
            await TG_APP.bot.send_message(cid, txt[:4000], reply_markup=kb_(*rows),
                                          parse_mode="HTML", disable_web_page_preview=True)
        except Exception: pass


async def asst_stats_to(chat_id, reply_to=None):
    sr_n = len(sr.list_accounts()) if sr else 0
    pend = len([k for k in ASST_PENDING if not ASST_PENDING[k].get("confirmed")])
    txt = (f"📊 آمار دستیار\n🌀 سروش: {sr_n}\n⏳ در انتظار: {pend}\n"
           f"🎬 در حال اجرا: {len(ASST_RUNNING)}")
    await asst_send(chat_id, txt, reply_to=reply_to)


# ══════════════════════════════════════════════════════════════
# Route callbacks
# ══════════════════════════════════════════════════════════════
async def asst_route_cb(cid, data):
    try:
        cfg = asst_load_cfg()

        if data == "asst:refresh": return await v25_show_main(cid)
        if data == "asst:menu:settings": return await v25_show_menu_settings(cid)
        if data == "asst:menu:templates": return await v25_show_menu_templates(cid)
        if data == "asst:menu:stats": return await v25_show_menu_stats(cid)
        if data == "asst:dash": return await v25_show_dashboard(cid)
        if data.startswith("asst:dash:plat:"): return await v25_show_dash_platform(cid)

        if data.startswith("asst:acc_stop:"):
            p = data.split(":")
            if len(p) >= 4:
                aid = p[3]; key = f"soroosh:{aid}"
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
                return await v25_show_dash_platform(cid)
        if data.startswith("asst:acc:"):
            p = data.split(":")
            if len(p) >= 4: return await v25_show_account_detail(cid, p[3])

        if data.startswith("asst:stats:sms"):
            p = data.split(":")
            pg = int(p[3]) if len(p) > 3 and p[3].isdigit() else 0
            return await v25_show_sms_stats(cid, pg)
        if data == "asst:stats:clear":
            ASST_SMS_HISTORY.clear(); _save_sms_history(ASST_SMS_HISTORY)
            return await v25_show_sms_stats(cid, 0)

        if data == "asst:toggle":
            cfg["enabled"] = not cfg.get("enabled"); asst_save_cfg(cfg)
            return await v25_show_main(cid)
        if data == "asst:toggle_accept":
            cfg["accept_new_accounts"] = not cfg.get("accept_new_accounts", True)
            asst_save_cfg(cfg); return await v25_show_main(cid)
        if data == "asst:toggle_force_sms":
            cfg["force_sms"] = not cfg.get("force_sms", True); asst_save_cfg(cfg)
            return await v25_show_menu_settings(cid)
        if data == "asst:set_force_retries":
            ASST_WAITING[cid] = {"kind": "force_retries"}
            return await tg_send("🔁 تعداد تلاش (1-5):")
        if data == "asst:set_force_delay":
            ASST_WAITING[cid] = {"kind": "force_delay"}
            return await tg_send("⏱ تاخیر (ثانیه):")
        if data == "asst:set_group":
            ASST_WAITING[cid] = {"kind": "group"}
            return await tg_send("💬 شناسه گروه:")
        if data == "asst:set_max":
            ASST_WAITING[cid] = {"kind": "max"}
            return await tg_send("🔢 حداکثر (1-50):")
        if data == "asst:set_hours":
            ASST_WAITING[cid] = {"kind": "hours"}
            return await tg_send("⏱ چند ساعت؟ (1-48):")

        if data == "asst:logs": return await asst_show_logs(cid, 0)
        if data.startswith("asst:logs:"):
            try: page = int(data.split(":",2)[2])
            except Exception: page = 0
            return await asst_show_logs(cid, page)

        if data.startswith("asst:set_tpl:"):
            if sr is None: return await tg_send("❌ سروش لود نشده")
            try: tpls = sr.list_templates()
            except Exception: tpls = {}
            if not tpls: return await tg_send("قالبی نیست")
            rows = []
            for tid, t in list(tpls.items())[:12]:
                num = t.get("num_id","?"); name = t.get("name","?")[:24]
                rows.append([B(f"#{num} 🎯 {name}", f"asst:tpl_pick:soroosh:{tid}")])
            rows.append([B("❌ بدون قالب", "asst:tpl_pick:soroosh:none")])
            return await tg_send("🎬 قالب سروش:", kb_(*rows))
        if data.startswith("asst:tpl_pick:"):
            p = data.split(":",3)
            if len(p) < 4: return
            tid = p[3]
            cfg["run_template_id_soroosh"] = None if tid == "none" else tid
            asst_save_cfg(cfg)
            started = 0
            if cfg.get("enabled") and tid != "none" and sr:
                hours = int(cfg.get("template_duration_hours", 6))
                try:
                    for aid in sr.list_accounts():
                        if asst_start_one(aid, tid, hours): started += 1
                except Exception: pass
            if tid != "none":
                await tg_send(f"✅ قالب ذخیره · {started} اکانت استارت شد")
            return await v25_show_main(cid)

        if data == "asst:restart_all":
            n = await asst_restart_all()
            await tg_send(f"🔄 شروع {n} اکانت"); return await v25_show_main(cid)
        if data == "asst:stop_all":
            await asst_stop_all(); await tg_send("🛑 همه متوقف شد")
            return await v25_show_main(cid)
        if data == "asst:clear_pending":
            ASST_PENDING.clear(); ASST_BATCH_ERRORS.clear()
            for b in ASST_BATCHES.values():
                b["done"] = True
                ev = b.get("stop")
                if ev:
                    try: ev.set()
                    except Exception: pass
            await tg_send("🔄 پاک شد"); return await v25_show_main(cid)
        if data == "asst:bulk": return await tg_send("🚀 عملیات گروهی بزودی")
    except Exception as e:
        log_print(f"[asst-route] {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()


async def asst_handle_force(q, data):
    p = data.split(":",4)
    if len(p) < 4: return
    uid = p[3]
    cached = ASST_USER_CACHE.get(uid)
    if not cached:
        try: await q.answer("❌ کش نشده", show_alert=True)
        except Exception: pass
        return
    chat_id = q.message.chat_id if q.message else 0
    bk = "b_" + secrets.token_hex(4)
    ASST_TASKS[bk] = asyncio.create_task(
        asst_safe_batch(bk, chat_id, cached["source"], cached["phones"], uid))


async def asst_handle_wait(cid, w, msg):
    cfg = asst_load_cfg()
    text = (msg.text or "").strip()
    kind = w.get("kind")
    if kind == "group":
        try: cfg["group_id"] = int(text); asst_save_cfg(cfg)
        except Exception: return await tg_send("❌ عدد نامعتبر")
        return await v25_show_main(cid)
    if kind == "max":
        try: cfg["max_accounts"] = max(1, min(50, int(text))); asst_save_cfg(cfg)
        except Exception: return await tg_send("❌ عدد 1-50")
        return await v25_show_main(cid)
    if kind == "hours":
        try: cfg["template_duration_hours"] = max(1, min(48, int(text))); asst_save_cfg(cfg)
        except Exception: return await tg_send("❌ عدد 1-48")
        return await v25_show_main(cid)
    if kind == "force_retries":
        try: cfg["force_sms_max_retries"] = max(1, min(5, int(text))); asst_save_cfg(cfg)
        except Exception: return await tg_send("❌ عدد 1-5")
        return await v25_show_menu_settings(cid)
    if kind == "force_delay":
        try: cfg["force_sms_delay_s"] = max(5, min(60, int(text))); asst_save_cfg(cfg)
        except Exception: return await tg_send("❌ عدد 5-60")
        return await v25_show_menu_settings(cid)


# ══════════════════════════════════════════════════════════════
# Group handler — catches SMS/phone/UID in configured group
# ══════════════════════════════════════════════════════════════
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

    is_owner = bool(msg.from_user and msg.from_user.id == FORCED_OWNER)
    if text.strip() == "چخبر":
        if is_owner: await asst_stats_to(msg.chat_id, msg.message_id)
        return

    if asst_code_source(text):
        code = asst_code(text)
        if code:
            matched = await asst_try_code(code)
            if matched and not is_edit:
                await asst_send(msg.chat_id,
                    f"✅ کد روی <code>{esc(matched)}</code> تایید شد",
                    reply_to=msg.message_id)
        return

    phones = v25_phones(text)
    uid = v25_uid(text)
    if not phones: return
    src = v25_source(text, phones, uid)
    if not src: return
    if not cfg.get("accept_new_accounts", True): return

    ukey = uid or f"m{msg.message_id}"
    ASST_USER_CACHE[ukey] = {"source": src, "phones": phones, "ts": time.time()}
    now = time.time()
    new_phones = [p for p in phones if now - V25_SEEN_PH.get(p, 0) > V25_TTL]
    if not new_phones: return
    for p in new_phones: V25_SEEN_PH[p] = now
    _v25_save_seen()
    if uid:
        ASST_UID_PHONES.setdefault(uid, set()).update(new_phones)
        ASST_SEEN.add(uid); asst_save_seen(ASST_SEEN)
    bk = "b_" + secrets.token_hex(4)
    ASST_TASKS[bk] = asyncio.create_task(
        asst_safe_batch(bk, msg.chat_id, src, new_phones, uid))


# ══════════════════════════════════════════════════════════════
# Message handler (text in private chat)
# ══════════════════════════════════════════════════════════════
async def on_message(update, context):
    if not authorized(update): return
    cid = update.effective_chat.id
    if cid in ASST_WAITING:
        w = ASST_WAITING.pop(cid)
        msg = update.message or update.edited_message
        try: await asst_handle_wait(cid, w, msg)
        except Exception: pass
        return
    try:
        msg = update.message or update.edited_message
        if msg: await msg.reply_text("🎯 از پنل دستیار استفاده کن")
    except Exception: pass


# ══════════════════════════════════════════════════════════════
# Startup
# ══════════════════════════════════════════════════════════════
def _wipe_accounts_and_sessions():
    if sr is None: return {"error": "sr_not_loaded"}
    deleted = {"accounts": False, "sessions": 0, "pending": 0, "ops": False}
    try:
        if os.path.exists(sr.ACC_FILE): os.remove(sr.ACC_FILE); deleted["accounts"] = True
    except Exception: pass
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
    except Exception: pass
    try:
        sr._save_ops([]); deleted["ops"] = True
    except Exception: pass
    try:
        ASST_RUNNING.clear(); ASST_PENDING.clear()
        ASST_BATCHES.clear(); ASST_TASKS.clear(); ASST_USER_CACHE.clear()
    except Exception: pass
    return deleted


async def asst_on_startup():
    try:
        cfg = asst_load_cfg()
        log_print(f"[asst] startup enabled={cfg.get('enabled')} tpl={cfg.get('run_template_id_soroosh')}")
        if cfg.get("wipe_accounts_on_startup", True):
            try:
                w = _wipe_accounts_and_sessions()
                log_print(f"[asst] WIPED: {w}")
            except Exception as e:
                log_print(f"[asst] wipe fail: {e}")
        if not cfg.get("auto_start_on_boot", False):
            log_print("[asst] auto-start DISABLED (start manually)")
            return
        if not cfg.get("enabled"): return
        n = await asst_start_all()
        log_print(f"[asst] started {n} accounts")
    except Exception as e:
        log_print(f"[asst-startup] {type(e).__name__}: {e}")


async def asst_cleanup_loop():
    while True:
        await asyncio.sleep(300)
        try:
            now = time.time()
            for k, v in list(ASST_PENDING.items()):
                if now - v.get("sent_at", now) > 900:
                    ASST_PENDING.pop(k, None)
        except Exception: pass


# ══════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════
async def show_main(cid, edit_mid=None):
    return await v25_show_main(cid, edit_mid)


async def route_cb(cid, data):
    return await asst_route_cb(cid, data)


async def on_group_message(update, context):
    return await asst_group_handler(update, context)


async def on_private_message(update, context):
    return await on_message(update, context)