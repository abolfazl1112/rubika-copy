#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Launcher + ASGI wrapper for Soroosh bot (V50.1)
- `python app.py`     → run bot in polling mode (foreground)
- `uvicorn app:app`   → ASGI healthcheck + bot in bg thread (single-process only)

Multi-worker safety:
    Uses a cross-process file lock so only ONE uvicorn worker starts the bot.
    Safe with --workers N (recommended: --workers 1, but N won't break it).

Healthcheck:
    GET /        → 200 ok  (bot running)   / 503 degraded (bot down)
    GET /health  → same
    GET /<other> → 404
"""
import os, sys, threading
from pathlib import Path

HERE = Path(__file__).parent.resolve()

# ── Locate Soroosh ──────────────────────────────────────────
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
    print("[x] Soroosh_tg_bot.py not found")
    sys.exit(1)

# ── Config ──────────────────────────────────────────────────
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

# ── Bot state ───────────────────────────────────────────────
_BOT_THREAD = None
_BOT_FAILED = threading.Event()       # set if bot crashed — healthcheck reads it
_BOT_LOCK   = threading.Lock()         # serialise start_bot() calls in this process
_LOCK_FH    = None                     # cross-process file lock handle


# ── Lazy Soroosh import ────────────────────────────────────
def _load_soroosh():
    """Only the process that actually runs the bot pays import cost."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("soroosh_bot", str(SR_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["soroosh_bot"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Cross-process lock (multi-worker safe) ──────────────────
def _acquire_bot_lock():
    """Return True if this process now owns the bot lock."""
    global _LOCK_FH
    import tempfile
    lock_path = os.path.join(tempfile.gettempdir(), "soroosh_bot.lock")
    try:
        try:
            import fcntl
            fh = open(lock_path, "w")
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            # Windows fallback
            import msvcrt
            fh = open(lock_path, "w")
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        fh.write(str(os.getpid()))
        fh.flush()
        _LOCK_FH = fh   # keep open — closing releases the lock
        return True
    except (BlockingIOError, OSError, IOError):
        return False


# ── Bot runner ──────────────────────────────────────────────
def _run_bot():
    try:
        soroosh = _load_soroosh()
        print("[launcher] Soroosh imported ✓")
    except Exception as e:
        print(f"[launcher] import FAIL: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        _BOT_FAILED.set()
        return
    try:
        soroosh.main(token=TOKEN, owner_id=OWNER)
    except KeyboardInterrupt:
        print("[launcher] bot stopped")
    except Exception as e:
        print(f"[launcher] bot error: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        _BOT_FAILED.set()


def start_bot():
    """Start bot thread. Returns True if this process owns the bot."""
    global _BOT_THREAD
    with _BOT_LOCK:
        if _BOT_THREAD and _BOT_THREAD.is_alive():
            return True
        if _BOT_FAILED.is_set():
            return False
        if not _acquire_bot_lock():
            print("[launcher] bot already running in another worker — skipping")
            return False
        _BOT_THREAD = threading.Thread(target=_run_bot, daemon=True, name="soroosh-bot")
        _BOT_THREAD.start()
        print("[launcher] bot thread started")
        return True


def _bot_alive():
    return bool(_BOT_THREAD and _BOT_THREAD.is_alive() and not _BOT_FAILED.is_set())


# ── ASGI app ────────────────────────────────────────────────
async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        msg = await receive()
        if msg["type"] == "lifespan.startup":
            start_bot()
            await send({"type": "lifespan.startup.complete"})
        msg = await receive()
        if msg["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
        return

    if scope["type"] == "http":
        path = scope.get("path", "/")
        if path in ("/", "/health"):
            ok = _bot_alive()
            body = (b'{"status":"ok","bot":"running"}' if ok
                    else b'{"status":"degraded","bot":"down"}')
            await send({
                "type": "http.response.start",
                "status": 200 if ok else 503,
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


# ── Direct run ──────────────────────────────────────────────
if __name__ == "__main__":
    print("[launcher] running bot directly...")
    _run_bot()