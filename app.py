#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Single bot with two panels (V7.1)
- Admin: /start shows [Soroosh] [Portal]
- Customer: /start shows their projects
- Loads portal config + customers from cPanel on startup
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

# ── CRITICAL: patch spluslib SQLite BEFORE any client is created ──
try:
    from spluslib_patch import apply_patches as _sp
    _sp()
except Exception as _e:
    print(f"[app] spluslib_patch not applied: {_e}")


def _load_module(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


TOKEN     = os.environ.get("TG_TOKEN", "").strip()
OWNER_STR = os.environ.get("TG_OWNER_ID", "").strip() or "8389746549"
OWNER     = int(OWNER_STR) if OWNER_STR.isdigit() else 8389746549

if not TOKEN:
    print("[x] TG_TOKEN not set. export TG_TOKEN='your_bot_token'")
    sys.exit(1)

os.environ["TG_TOKEN"] = TOKEN
os.environ["TG_OWNER_ID"] = str(OWNER)

print(f"[app] Soroosh: {SR_PATH}")
print(f"[app] Portal:  {PORTAL_PATH or '(skip)'}")
print(f"[app] owner:   {OWNER}")


# ═══════════════════════════════════════════════════════════
# Load modules FIRST
# ═══════════════════════════════════════════════════════════
soroosh_mod = _load_module("soroosh_bot", SR_PATH)
print("[app] Soroosh module loaded ✓")

portal_mod = None
if PORTAL_PATH:
    try:
        portal_mod = _load_module("portal_bot", PORTAL_PATH)
        print("[app] Portal module loaded ✓")
    except Exception as e:
        print(f"[app] Portal load fail: {e}")


# ═══════════════════════════════════════════════════════════
# Imports
# ═══════════════════════════════════════════════════════════
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    ApplicationHandlerStop,
)
from telegram.request import HTTPXRequest
from diag_monitor import start_monitor


# ═══════════════════════════════════════════════════════════
# Admin menu (main hub)
# ═══════════════════════════════════════════════════════════
async def cmd_start_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id

    # ── Admin ──
    if uid == OWNER:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌀 پنل سروش", callback_data="main:goto_soroosh")],
            [InlineKeyboardButton("🚀 ساخت درگاه", callback_data="main:goto_portal")],
        ])
        try:
            await update.message.reply_text(
                "🎯 <b>منوی اصلی</b>\n\nیکی را انتخاب کن:",
                parse_mode="HTML", reply_markup=kb,
            )
        except Exception as e:
            print(f"[app] admin start reply: {e}")
        raise ApplicationHandlerStop

    # ── Customer ──
    if portal_mod and hasattr(portal_mod, "handle_customer_start"):
        try:
            handled = await portal_mod.handle_customer_start(update, ctx)
            if handled:
                raise ApplicationHandlerStop
        except ApplicationHandlerStop:
            raise
        except Exception as e:
            print(f"[app] customer_start: {type(e).__name__}: {e}")
            import traceback; traceback.print_exc()

    # ── Stranger ──
    try:
        await update.message.reply_text("⛔ دسترسی ندارید.")
    except Exception: pass
    raise ApplicationHandlerStop


async def cb_main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try: await q.answer()
    except Exception: pass

    if q.data == "main:goto_soroosh":
        try:
            await soroosh_mod.show_main()
        except Exception as e:
            print(f"[app] soroosh show_main: {e}")
            try: await q.edit_message_text(f"❌ {e}")
            except Exception: pass

    elif q.data == "main:goto_portal":
        if portal_mod and hasattr(portal_mod, "_show_admin_menu"):
            try:
                await portal_mod._show_admin_menu(q)
            except Exception as e:
                print(f"[app] portal menu: {e}")
                try: await q.edit_message_text(f"❌ {e}")
                except Exception: pass
        elif portal_mod:
            # Fallback if _show_admin_menu missing
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 ساخت درگاه جدید", callback_data="portal:new")],
                [InlineKeyboardButton("📋 پروژه‌های من", callback_data="portal:projects:0")],
                [InlineKeyboardButton("📊 آمار", callback_data="portal:stats:list")],
                [InlineKeyboardButton("⚙️ تنظیمات", callback_data="portal:settings")],
            ])
            try:
                await q.edit_message_text(
                    "🎯 <b>پنل درگاه‌سازی</b>",
                    parse_mode="HTML", reply_markup=kb,
                )
            except Exception as e:
                print(f"[app] portal fallback menu: {e}")

    raise ApplicationHandlerStop


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start_main(update, ctx)


# ═══════════════════════════════════════════════════════════
# Build app
# ═══════════════════════════════════════════════════════════
def build_app():
    req = HTTPXRequest(connection_pool_size=8, connect_timeout=30.0,
                       read_timeout=30.0, write_timeout=30.0, pool_timeout=30.0)

    app = (Application.builder().token(TOKEN)
           .request(req).get_updates_request(req).build())

    # ── Register Soroosh ──
    sr_post = None
    try:
        sr_post = soroosh_mod.setup_application(app, TOKEN, OWNER)
        print("[app] Soroosh handlers registered ✓")
    except Exception as e:
        print(f"[app] Soroosh setup FAIL: {e}")
        import traceback; traceback.print_exc()

    # ── Register Portal ──
    pt_post = None
    if portal_mod:
        try:
            pt_post = portal_mod.setup_application(app)
            print("[app] Portal handlers registered ✓")
        except Exception as e:
            print(f"[app] Portal setup FAIL: {e}")
            import traceback; traceback.print_exc()

    # ── Chain post_init ──
    async def combined_post_init(app):
        # 1) Soroosh post_init (migrations, listeners, PV)
        if sr_post:
            try: await sr_post(app)
            except Exception as e:
                print(f"[app] Soroosh post_init fail: {e}")
                import traceback; traceback.print_exc()

        # 2) Portal: load config + customers from cPanel
        if portal_mod and hasattr(portal_mod, "_load_all_from_cpanel"):
            try:
                await portal_mod._load_all_from_cpanel()
                n_cust = len(getattr(portal_mod, "_customers", {}))
                print(f"[app] Portal loaded from cPanel: {n_cust} customers ✓")
            except Exception as e:
                print(f"[app] Portal cPanel load fail: {e}")
                import traceback; traceback.print_exc()

        # 3) Portal post_init (if any)
        if pt_post:
            try: await pt_post(app)
            except Exception as e:
                print(f"[app] Portal post_init fail: {e}")

        start_monitor(app)

    app.post_init = combined_post_init

    # ── Main menu (group -1 = highest priority) ──
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


# ═══════════════════════════════════════════════════════════
# ASGI mode (PaaS)
# ═══════════════════════════════════════════════════════════
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