#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Soroosh launcher
پشتیبانی از هر دو حالت:
  1) python3 app.py
  2) uvicorn app:app    ← fake ASGI + soroosh در background
"""
import os, sys, importlib.util, threading, asyncio
from pathlib import Path

HERE = Path(__file__).parent.resolve()

os.environ.setdefault("TG_TOKEN", "8921325744:AAFXRJVzWotsUiZ9yslVpc7NevS2c-8DNnQ")
os.environ.setdefault("TG_OWNER_ID", "8389746549")

SR_PATH = HERE / "Soroosh_tg_bot.py"
if not SR_PATH.exists():
    print(f"❌ پیدا نشد: {SR_PATH}")
    sys.exit(1)

print("=" * 60)
print(f"   🌀 loading {SR_PATH.name}")
print("=" * 60)

spec = importlib.util.spec_from_file_location("soroosh_bot", str(SR_PATH))
sr = importlib.util.module_from_spec(spec)
sys.modules["soroosh_bot"] = sr

try:
    spec.loader.exec_module(sr)
except Exception as e:
    print(f"❌ import fail: {type(e).__name__}: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

if not hasattr(sr, "main"):
    print("❌ Soroosh_tg_bot.py تابع main() نداره")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# Fake ASGI app — برای uvicorn app:app سازگاری
# Soroosh رو در background thread اجرا می‌کنه
# ═══════════════════════════════════════════════════════════════
_bot_thread = None
_bot_started = False

def _start_bot_once():
    global _bot_thread, _bot_started
    if _bot_started and _bot_thread and _bot_thread.is_alive():
        return
    _bot_started = True
    print("[app] starting soroosh main() in background thread")
    _bot_thread = threading.Thread(target=sr.main, daemon=True, name="soroosh-main")
    _bot_thread.start()


async def app(scope, receive, send):
    """Minimal ASGI app — فقط lifespan + health check."""
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                _start_bot_once()
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
        return

    if scope["type"] == "http":
        body = b'{"ok":true,"service":"soroosh"}'
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})
        return

    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1000})
        return


# ═══════════════════════════════════════════════════════════════
# حالت اجرای مستقیم: python3 app.py
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        sr.main()
    except KeyboardInterrupt:
        print("\n[!] stopped")
    except Exception as e:
        print(f"[!] fatal: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()