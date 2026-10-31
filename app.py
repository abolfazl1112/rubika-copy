#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Single bot with two panels (V53)
/start shows: [Soroosh panel] [Portal]
"""
import os, sys, threading
from pathlib import Path

HERE = Path(__file__).parent.resolve()


def _find(name):
    for c in [HERE / name, Path("/app") / name, Path.cwd() / name]:
        try:
            if c.is_file(): return c.resolve()
        except Exception: pass
    return None


SR_PATH     = _find("Soroosh_tg_bot.py")
PORTAL_PATH = _find("portal.py")

if SR_PATH is None:
    print("[x] Soroosh not found"); sys.exit(1)


def _load_module(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


TOKEN     = os.environ.get("TG_TOKEN", "").strip() or "8386088114:AAGsP7lKVApsI6suH3avJAOpXqxfhoOwBCs"
OWNER_STR = os.environ.get("TG_OWNER_ID", "").strip() or "8389746549"
OWNER     = int(OWNER_STR) if OWNER_STR.isdigit() else 8389746549

os.environ["TG_TOKEN"] = TOKEN
os.environ["TG_OWNER_ID"] = str(OWNER)

print(f"[app] Soroosh: {SR_PATH}")
print(f"[app] Portal:  {PORTAL_PATH or '(skip)'}")
print(f"[app] owner:   {OWNER}")


# ── Load modules FIRST ──
soroosh_mod = _load_module("soroosh_bot", SR_PATH)
print("[app] Soroosh module loaded ✓")

portal_mod = None
if PORTAL_PATH:
    try:
        portal_mod = _load_module("portal_bot", PORTAL_PATH)
        print("[app] Portal module loaded ✓")
    except Exception as e:
        print(f"[app] Portal load fail: {e}")


# ── Build merged Application ──
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    ApplicationHandlerStop,
)
from telegram.request import HTTPXRequest


async def cmd_start_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != OWNER:
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌀 پنل سروش", callback_data="main:goto_soroosh")],
        [InlineKeyboardButton("🚀 ساخت درگاه", callback_data="main:goto_portal")],
    ])
    await update.message.reply_text(
        "🎯 <b>منوی اصلی</b>\n\n"
        "یکی را انتخاب کن:",
        parse_mode="HTML", reply_markup=kb,
    )
    raise ApplicationHandlerStop


async def cb_main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "main:goto_soroosh":
        try:
            await soroosh_mod.show_main()
        except Exception as e:
            await q.edit_message_text(f"❌ {e}")
    elif q.data == "main:goto_portal":
        if portal_mod:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 ساخت درگاه جدید", callback_data="portal:new")],
                [InlineKeyboardButton("📋 پروژه‌های من", callback_data="portal:projects:0")],
                [InlineKeyboardButton("📊 آمار", callback_data="portal:stats:list")],
                [InlineKeyboardButton("⚙️ تنظیمات", callback_data="portal:settings")],
            ])
            await q.edit_message_text(
                "🎯 <b>پنل درگاه‌سازی</b>",
                parse_mode="HTML", reply_markup=kb,
            )
    raise ApplicationHandlerStop


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start_main(update, ctx)


def build_app():
    req = HTTPXRequest(connection_pool_size=8, connect_timeout=30.0,
                       read_timeout=30.0, write_timeout=30.0, pool_timeout=30.0)

    # Build without post_init first, we'll chain manually
    app = (Application.builder().token(TOKEN)
           .request(req).get_updates_request(req).build())

    # Register Soroosh handlers (returns post_init)
    sr_post = soroosh_mod.setup_application(app, TOKEN, OWNER)
    print("[app] Soroosh handlers registered ✓")

    # Register Portal handlers
    pt_post = None
    if portal_mod:
        pt_post = portal_mod.setup_application(app)
        print("[app] Portal handlers registered ✓")

    # Chain post_init
    async def combined_post_init(app):
        if sr_post:
            try: await sr_post(app)
            except Exception as e:
                print(f"[app] Soroosh post_init fail: {e}")
                import traceback; traceback.print_exc()
        if pt_post:
            try: await pt_post(app)
            except Exception as e:
                print(f"[app] Portal post_init fail: {e}")

    app.post_init = combined_post_init

    # Main menu handlers (group -1 = highest priority)
    app.add_handler(CommandHandler("start", cmd_start_main), group=-1)
    app.add_handler(CommandHandler("menu",  cmd_menu),       group=-1)
    app.add_handler(CallbackQueryHandler(cb_main_menu, pattern="^main:"), group=-1)

    return app


def _run():
    try:
        app = build_app()
        print("[app] ✅ Built merged Application")
        print("[app] Starting polling...")
        app.run_polling(allowed_updates=Update.ALL_TYPES,
                        poll_interval=2.0, timeout=30.0)
    except Exception as e:
        import traceback
        print(f"[app] FATAL: {type(e).__name__}: {e}")
        traceback.print_exc()


# ── ASGI mode ──
_started = False
_start_lock = threading.Lock()
_main_thread = None


def _ensure_started():
    global _started, _main_thread
    with _start_lock:
        if _started: return
        _started = True
        _main_thread = threading.Thread(target=_run, daemon=True, name="main-bot")
        _main_thread.start()


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        msg = await receive()
        if msg["type"] == "lifespan.startup":
            _ensure_started()
            await send({"type": "lifespan.startup.complete"})
        msg = await receive()
        if msg["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
        return
    if scope["type"] == "http":
        path = scope.get("path", "/")
        if path in ("/", "/health"):
            ok = _main_thread and _main_thread.is_alive()
            body = (b'{"status":"' + (b"ok" if ok else b"degraded") + b'"}')
            await send({"type": "http.response.start",
                        "status": 200 if ok else 503,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
        else:
            await send({"type": "http.response.start", "status": 404,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"not found"})


if __name__ == "__main__":
    print("[app] direct mode")
    _run()