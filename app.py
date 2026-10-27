#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Launcher + ASGI wrapper برای Soroosh bot
- `python app.py` → ربات رو اجرا می‌کنه (polling)
- `uvicorn app:app` → ASGI خالی + ربات در thread (برای healthcheck سرور)
"""
import os, sys, threading, time, asyncio
from pathlib import Path

HERE = Path(__file__).parent.resolve()

# ── پیدا کردن Soroosh ──
def _find_soroosh():
    for c in [HERE / "Soroosh_tg_bot.py",
              HERE.parent / "Soroosh_tg_bot.py",
              Path("/app/Soroosh_tg_bot.py"),
              Path.cwd() / "Soroosh_tg_bot.py"]:
        try:
            if c.is_file(): return c.resolve()
        except Exception: pass
    return None

SR_PATH = _find_soroosh()
if SR_PATH is None:
    print("[x] Soroosh_tg_bot.py پیدا نشد")
    sys.exit(1)

# ── توکن ──
TOKEN = os.environ.get("TG_TOKEN", "").strip() or "8386088114:AAGsP7lKVApsI6suH3avJAOpXqxfhoOwBCs"
OWNER_STR = os.environ.get("TG_OWNER_ID", "").strip() or "8389746549"
try:
    OWNER = int(OWNER_STR)
except Exception:
    OWNER = 8389746549

os.environ["TG_TOKEN"] = TOKEN
os.environ["TG_OWNER_ID"] = str(OWNER)

print(f"[launcher] Soroosh: {SR_PATH}")
print(f"[launcher] owner: {OWNER}")

# ── ایمپورت Soroosh ──
import importlib.util
try:
    spec = importlib.util.spec_from_file_location("soroosh_bot", str(SR_PATH))
    soroosh = importlib.util.module_from_spec(spec)
    sys.modules["soroosh_bot"] = soroosh
    spec.loader.exec_module(soroosh)
    print("[launcher] Soroosh imported ✓")
except Exception as e:
    print(f"[launcher] import FAIL: {type(e).__name__}: {e}")
    import traceback; traceback.print_exc()
    soroosh = None

# ── Bot runner (thread) ──
_BOT_STARTED = False
_BOT_THREAD = None


def _run_bot():
    """اجرای ربات در thread جدا"""
    global _BOT_STARTED
    if soroosh is None:
        print("[launcher] Soroosh not loaded")
        return
    try:
        _BOT_STARTED = True
        soroosh.main(token=TOKEN, owner_id=OWNER)
    except KeyboardInterrupt:
        print("[launcher] bot stopped")
    except Exception as e:
        print(f"[launcher] bot error: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()


def start_bot():
    global _BOT_THREAD
    if _BOT_THREAD and _BOT_THREAD.is_alive():
        return
    _BOT_THREAD = threading.Thread(target=_run_bot, daemon=True, name="soroosh-bot")
    _BOT_THREAD.start()
    print("[launcher] bot thread started")


# ── ASGI (برای healthcheck) ──
async def app(scope, receive, send):
    """ASGI app ساده — فقط برای healthcheck"""
    if scope["type"] == "lifespan":
        # startup
        start_bot()
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif msg["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    elif scope["type"] == "http":
        path = scope.get("path", "/")
        body = b'{"status":"ok","bot":"soroosh"}'
        if path == "/" or path == "/health":
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": body})
        else:
            await send({
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({"type": "http.response.body", "body": b"not found"})


# ── Main ──
def _detect_mode():
    """تشخیص اینکه با uvicorn اجرا شده یا مستقیم"""
    # اگه uvicorn هست، argv شامل uvicorn هست
    argv = " ".join(sys.argv).lower()
    if "uvicorn" in argv or "gunicorn" in argv:
        return "asgi"
    # اگه __main__ هست، مستقیم
    return "direct"


if __name__ == "__main__":
    mode = _detect_mode()
    print(f"[launcher] mode: {mode}")

    if mode == "direct":
        # حالت مستقیم: ربات رو در thread اصلی اجرا کن
        print("[launcher] running bot directly...")
        _run_bot()
    else:
        # حالت ASGI: ربات از طریق lifespan شروع می‌شه
        print("[launcher] ASGI mode — bot starts via lifespan")
        # keep-alive loop
        try:
            while True:
                time.sleep(10)
                if _BOT_THREAD and not _BOT_THREAD.is_alive():
                    print("[launcher] bot died, restarting...")
                    start_bot()
        except KeyboardInterrupt:
            print("[launcher] stopped")