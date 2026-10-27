#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Launcher
پنل اصلی: روبیکا / سروش / Tools (شامل دستیار)
"""
import sys, os, io, contextlib, logging
import json, time, asyncio, importlib.util, threading
from pathlib import Path
from typing import Optional, Dict, Any, List

REAL_OUT = sys.stdout


def log_print(msg=""):
    try: print(msg, file=REAL_OUT, flush=True)
    except Exception: pass


logging.basicConfig(level=logging.CRITICAL, stream=io.StringIO())
for _n in ("", "uvicorn", "httpx", "httpcore", "telegram", "telegram.ext",
           "urllib3", "aiohttp", "asyncio", "requests", "web", "splusthon", "rubpy"):
    _lg = logging.getLogger(_n)
    _lg.setLevel(logging.CRITICAL); _lg.propagate = False
    _lg.handlers = [logging.NullHandler()]

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ApplicationHandlerStop,
                          filters as tg_filters)
from telegram.request import HTTPXRequest

HERE = Path(__file__).parent.resolve()

# ── Config ──
TG_TOKEN = os.environ.get("TG_TOKEN", "").strip() or "8921325744:AAFXRJVzWotsUiZ9yslVpc7NevS2c-8DNnQ"
try: FORCED_OWNER = int(os.environ.get("TG_OWNER_ID", "").strip() or "8389746549")
except Exception: FORCED_OWNER = 8389746549

os.environ["TG_TOKEN"] = TG_TOKEN
os.environ["TG_OWNER_ID"] = str(FORCED_OWNER)

# ── Find modules ──
def _find(filename):
    for c in [HERE / filename, HERE.parent / filename,
              Path("/app") / filename, Path("/home/container") / filename]:
        try:
            if c.is_file(): return c.resolve()
        except Exception: pass
    for base in (Path.cwd(), HERE):
        for p in [base] + list(base.parents):
            c = p / filename
            try:
                if c.is_file(): return c.resolve()
            except Exception: pass
    return None

RB_PATH = _find("rubika_tg_bot.py")
SR_PATH = _find("Soroosh_tg_bot.py")
EI_PATH = _find("Eitaa_tg_bot.py")
AS_PATH = _find("assistant_tg_bot.py")


def _load(name, path):
    if not path: return None
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            spec = importlib.util.spec_from_file_location(name, str(path))
            m = importlib.util.module_from_spec(spec)
            sys.modules[name] = m
            spec.loader.exec_module(m)
        return m
    except Exception as e:
        log_print(f"❌ import {name}: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        return None


log_print("=" * 60)
log_print("   🌀 Loading modules...")
rb = _load("rubika_bot", RB_PATH)
sr = _load("soroosh_bot", SR_PATH)
ei = _load("eitaa_bot", EI_PATH)
asst = _load("assistant_bot", AS_PATH)

log_print(f"   rb: {'✓' if rb else '—'}")
log_print(f"   sr: {'✓' if sr else '—'}")
log_print(f"   ei: {'✓' if ei else '—'}")
log_print(f"   asst: {'✓' if asst else '—'}")
log_print("=" * 60)

if rb is None and sr is None and ei is None and asst is None:
    log_print("❌ هیچ ماژولی لود نشد"); sys.exit(1)


# ── Shared UI helpers ──
def esc(s):
    import html
    return html.escape(str(s if s is not None else ""))


def B(label, data): return InlineKeyboardButton(label, callback_data=data)
def kb_(*rows): return InlineKeyboardMarkup([list(r) for r in rows if r])
def grid(btns, cols=2): return [btns[i:i+cols] for i in range(0, len(btns), cols)]


def authorized(update):
    try: return update.effective_chat.id == FORCED_OWNER
    except Exception: return False


USER_MODE: Dict[int, str] = {}
TG_APP: Optional[Application] = None


# ── Menus ──
def main_menu_kb():
    rows = []
    if rb is not None: rows.append([B("📱 پنل روبیکا", "mode:rubika")])
    if sr is not None: rows.append([B("🌀 پنل سروش", "mode:soroosh")])
    if ei is not None: rows.append([B("📨 پنل ایتا", "mode:eitaa")])
    rows.append([B("🛠 Tools", "mode:tools")])
    return kb_(*rows)


def tools_menu_kb():
    rows = []
    if asst is not None: rows.append([B("🎯 دستیار", "mode:assistant")])
    rows.append([B("🏠 بازگشت", "menu:home")])
    return kb_(*rows)


async def _render_main(cid, edit_mid=None):
    lines = ["🏠 <b>پنل مدیریت</b>", "━━━━━━━━━━━━", ""]
    if rb: lines.append("📱 <b>روبیکا</b> — ارسال، جوینر، کانال")
    if sr: lines.append("🌀 <b>سروش</b> — ارسال، جوینر، قالب")
    if ei: lines.append("📨 <b>ایتا</b> — ارسال، جوینر")
    if asst: lines.append("🛠 <b>Tools</b> — دستیار + ابزارها")
    lines.append("")
    lines.append("یک پنل انتخاب کن:")
    txt = "\n".join(lines)
    if edit_mid and TG_APP:
        try:
            await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt,
                                               reply_markup=main_menu_kb(), parse_mode="HTML",
                                               disable_web_page_preview=True)
            return edit_mid
        except Exception as e:
            if "not modified" in str(e).lower(): return edit_mid
    if TG_APP:
        try:
            m = await TG_APP.bot.send_message(cid, txt, reply_markup=main_menu_kb(),
                                              parse_mode="HTML", disable_web_page_preview=True)
            return m.message_id
        except Exception: pass
    return None


async def _render_tools(cid, edit_mid=None):
    txt = ("🛠 <b>Tools</b>\n━━━━━━━━━━━━\n\n"
           "ابزارها و دستیار:")
    if edit_mid and TG_APP:
        try:
            await TG_APP.bot.edit_message_text(chat_id=cid, message_id=edit_mid, text=txt,
                                               reply_markup=tools_menu_kb(), parse_mode="HTML",
                                               disable_web_page_preview=True)
            return edit_mid
        except Exception as e:
            if "not modified" in str(e).lower(): return edit_mid
    if TG_APP:
        try:
            m = await TG_APP.bot.send_message(cid, txt, reply_markup=tools_menu_kb(),
                                              parse_mode="HTML", disable_web_page_preview=True)
            return m.message_id
        except Exception: pass
    return None


# ── Routers ──
async def cmd_start(update, context):
    cid = update.effective_chat.id
    if cid != FORCED_OWNER:
        try: await update.message.reply_text("⛔ خصوصی است.")
        except Exception: pass
        return
    USER_MODE.pop(cid, None)
    # clear panel message id in all modules
    for mod in (rb, sr, ei, asst):
        if mod is None: continue
        try: mod.STATE["panel"].pop(cid, None)
        except Exception: pass
    mid = await _render_main(cid)
    if mid:
        for mod in (rb, sr, ei, asst):
            if mod is None: continue
            try: mod.STATE["panel"][cid] = mid
            except Exception: pass


async def cmd_menu(update, context):
    if not authorized(update): return
    await cmd_start(update, context)


async def cmd_version(update, context):
    if not authorized(update): return
    lines = ["🔖 <b>Versions</b>", ""]
    if rb: lines.append(f"📱 rubika: {getattr(rb,'VERSION','—')}")
    if sr: lines.append(f"🌀 soroosh: {getattr(sr,'VERSION','—')}")
    if ei: lines.append(f"📨 eitaa: {getattr(ei,'VERSION','—')}")
    if asst: lines.append(f"🎯 assistant: {getattr(asst,'VERSION','—')}")
    lines.append(f"\n👤 <code>{FORCED_OWNER}</code>")
    try:
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception: pass


async def cb_router(update, context):
    q = update.callback_query
    if q is None: return
    data = q.data or ""
    cid = update.effective_chat.id if update.effective_chat else 0

    # special force button (owner check inside)
    if data.startswith("asst:force:"):
        if q.from_user and q.from_user.id != FORCED_OWNER:
            try: await q.answer("⛔", show_alert=True)
            except Exception: pass
            raise ApplicationHandlerStop
        try: await q.answer("⏳")
        except Exception: pass
        if asst:
            try: await asst.route_cb(cid, data)  # forwards to force
            except Exception: pass
        raise ApplicationHandlerStop

    if data == "noop":
        try: await q.answer()
        except Exception: pass
        raise ApplicationHandlerStop

    if not authorized(update):
        try: await q.answer("⛔ خصوصی", show_alert=True)
        except Exception: pass
        raise ApplicationHandlerStop

    try: await q.answer()
    except Exception: pass

    # update panel ID in all modules
    if q.message:
        for mod in (rb, sr, ei, asst):
            if mod is None: continue
            try: mod.STATE["panel"][cid] = q.message.message_id
            except Exception: pass
        # also update app.py's own panel tracking
        _APP_PANEL[cid] = q.message.message_id

    edit_mid = q.message.message_id if q.message else None

    # main router
    if data in ("menu:home", "mode:home"):
        USER_MODE.pop(cid, None)
        await _render_main(cid, edit_mid=edit_mid)
        raise ApplicationHandlerStop

    if data == "mode:tools":
        USER_MODE[cid] = "tools"
        await _render_tools(cid, edit_mid=edit_mid)
        raise ApplicationHandlerStop

    if data == "mode:assistant":
        USER_MODE[cid] = "assistant"
        if asst:
            try: await asst.show_main(cid, edit_mid=edit_mid)
            except Exception as e: log_print(f"[asst.show] {e}")
        raise ApplicationHandlerStop

    if data == "mode:rubika":
        USER_MODE[cid] = "rubika"
        if rb:
            try: await rb.show_main()
            except Exception as e: log_print(f"[rb] {e}")
        raise ApplicationHandlerStop

    if data == "mode:soroosh":
        USER_MODE[cid] = "soroosh"
        if sr:
            try: await sr.show_main()
            except Exception as e: log_print(f"[sr] {e}")
        raise ApplicationHandlerStop

    if data == "mode:eitaa":
        USER_MODE[cid] = "eitaa"
        if ei:
            try: await ei.show_main()
            except Exception as e: log_print(f"[ei] {e}")
        raise ApplicationHandlerStop

    # assistant prefixed callbacks
    if data.startswith("asst:") and asst:
        try: await asst.route_cb(cid, data)
        except Exception as e:
            log_print(f"[asst.route] {e}")
            import traceback; traceback.print_exc()
        raise ApplicationHandlerStop

    # else: route by USER_MODE
    mode = USER_MODE.get(cid)
    if mode == "rubika" and rb:
        try: await rb.route_cb(cid, data)
        except Exception as e: log_print(f"[rb.cb] {e}")
        raise ApplicationHandlerStop
    if mode == "soroosh" and sr:
        try: await sr.route_cb(cid, data)
        except Exception as e: log_print(f"[sr.cb] {e}")
        raise ApplicationHandlerStop
    if mode == "eitaa" and ei:
        try: await ei.route_cb(cid, data)
        except Exception as e: log_print(f"[ei.cb] {e}")
        raise ApplicationHandlerStop
    if mode == "assistant" and asst:
        try: await asst.route_cb(cid, data)
        except Exception as e: log_print(f"[asst.cb] {e}")
        raise ApplicationHandlerStop

    # fallback
    await _render_main(cid, edit_mid=edit_mid)
    raise ApplicationHandlerStop


async def msg_router(update, context):
    if not authorized(update): return
    cid = update.effective_chat.id

    # assistant waiting input
    if asst and cid in getattr(asst, "ASST_WAITING", {}):
        try: await asst.on_private_message(update, context)
        except Exception as e: log_print(f"[asst.msg] {e}")
        return

    mode = USER_MODE.get(cid)
    if mode == "rubika" and rb:
        try: await rb.on_message(update, context)
        except Exception as e: log_print(f"[rb.msg] {e}")
        return
    if mode == "soroosh" and sr:
        try: await sr.on_message(update, context)
        except Exception as e: log_print(f"[sr.msg] {e}")
        return
    if mode == "eitaa" and ei:
        try: await ei.on_message(update, context)
        except Exception as e: log_print(f"[ei.msg] {e}")
        return
    if mode == "assistant" and asst:
        try: await asst.on_private_message(update, context)
        except Exception as e: log_print(f"[asst.msg] {e}")
        return

    try:
        await update.message.reply_text("🏠 اول یک پنل انتخاب کن.\n/menu")
    except Exception: pass


async def on_error(update, context):
    log_print(f"[!] {type(context.error).__name__}: {context.error}")


# ── Post init ──
_APP_PANEL: Dict[int, int] = {}


async def on_post_init(app: Application):
    global TG_APP
    TG_APP = app

    # attach app to all modules
    for mod in (rb, sr, ei):
        if mod is None: continue
        try: mod.APP = app
        except Exception: pass
        try: mod.STATE["owner"] = FORCED_OWNER
        except Exception: pass
    if asst:
        try: asst.APP = app
        except Exception: pass
        try: asst.TG_APP = app
        except Exception: pass
        try: asst.sr = sr
        except Exception: pass
        try: asst.STATE["owner"] = FORCED_OWNER
        except Exception: pass

    log_print("=" * 60)
    log_print("   🌐 Bot started")
    log_print("=" * 60)

    try:
        await app.bot.set_my_commands([
            BotCommand("start", "شروع"),
            BotCommand("menu", "منو"),
            BotCommand("version", "نسخه"),
        ])
    except Exception: pass

    # 1. Wipe FIRST (if assistant)
    if asst:
        try:
            await asst.asst_on_startup()
            log_print("[startup] assistant ready")
        except Exception as e:
            log_print(f"[startup] asst: {e}")

    # 2. Start listeners
    for mod in (rb, sr, ei):
        if mod is None: continue
        try: asyncio.create_task(mod.start_all_listeners())
        except Exception: pass
        try: asyncio.create_task(mod.keepalive_loop())
        except Exception: pass
        if hasattr(mod, "start_pv_responders"):
            try: asyncio.create_task(mod.start_pv_responders())
            except Exception: pass

    # 3. Assistant cleanup
    if asst:
        try: asyncio.create_task(asst.asst_cleanup_loop())
        except Exception: pass

    log_print("   ✅ all modules started")


# ── Bot worker ──
_bot_thread: Optional[threading.Thread] = None


def _bot_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for mod in (rb, sr, ei, asst):
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

    # group filter for assistant (SMS/AutoTar watcher)
    if asst:
        try:
            gf = tg_filters.ChatType.GROUP | tg_filters.ChatType.SUPERGROUP
            app.add_handler(MessageHandler(
                (tg_filters.TEXT | tg_filters.CAPTION) & gf,
                asst.on_group_message), group=-2)
        except Exception as e:
            log_print(f"[group handler] {e}")

    app.add_handler(MessageHandler(tg_filters.ALL & ~tg_filters.COMMAND, msg_router))
    app.add_error_handler(on_error)

    log_print("   ربات: ⏳ polling...")
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES,
                        poll_interval=2.0, timeout=30.0)
    except BaseException as e:
        log_print(f"   ربات: ❌ {type(e).__name__}: {e}")


def main():
    global _bot_thread
    log_print("=" * 60)
    log_print("   🌐 Launcher v1.0")
    log_print(f"   owner: {FORCED_OWNER}")
    log_print("=" * 60)
    _bot_thread = threading.Thread(target=_bot_worker, daemon=True, name="bot")
    _bot_thread.start()
    try:
        while _bot_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        log_print("\n[!] stopped")


if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\n[!] قطع")
    except Exception as e:
        print(f"[!] fatal: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()