#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Minimal safe launcher (V53)
- Does NOTHING at import except patch signal (safe)
- All bots start inside lifespan (uvicorn) or __main__ (python app.py)
- Catches and logs all errors — never crashes the server
"""
import os, sys, threading, asyncio

# ═══════════════════════════════════════════════════════════
# Patch signal.signal for threads (PTB's run_polling calls it from bg thread)
# This is safe — passes through in main thread, no-ops in others
# ═══════════════════════════════════════════════════════════
try:
    import signal
    _MAIN_TID = threading.main_thread().ident
    _orig_signal = signal.signal
    def _safe_signal(sig, handler):
        if threading.current_thread().ident != _MAIN_TID:
            return None
        return _orig_signal(sig, handler)
    signal.signal = _safe_signal
except Exception:
    pass

try:
    import asyncio.unix_events as _ue
    _o = _ue._UnixSelectorEventLoop.add_signal_handler
    def _s(self, sig, cb, *a):
        try: return _o(self, sig, cb, *a)
        except (RuntimeError, ValueError, NotImplementedError, AttributeError):
            return None
    _ue._UnixSelectorEventLoop.add_signal_handler = _s
except Exception:
    pass


# ═══════════════════════════════════════════════════════════
# State
# ═══════════════════════════════════════════════════════════
_started = False
_start_lock = threading.Lock()
_bot_status = {"soroosh": "pending", "portal": "pending"}


# ═══════════════════════════════════════════════════════════
# ASGI app — healthcheck only
# ═══════════════════════════════════════════════════════════
async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        msg = await receive()
        if msg["type"] == "lifespan.startup":
            _start_bots()
            await send({"type": "lifespan.startup.complete"})
        msg = await receive()
        if msg["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
        return

    if scope["type"] == "http":
        path = scope.get("path", "/")
        if path in ("/", "/health"):
            ok = all(v == "ok" for v in _bot_status.values())
            body = (b'{"status":"' + (b"ok" if ok else b"degraded")
                    + b'","bots":'
                    + ('{"soroosh":"' + _bot_status["soroosh"] + '",'
                       '"portal":"' + _bot_status["portal"] + '"}').encode()
                    + b"}")
            await send({
                "type": "http.response.start",
                "status": 200 if ok else 503,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": body})
        else:
            await send({
                "type": "http.response.start", "status": 404,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({"type": "http.response.body", "body": b"not found"})


# ═══════════════════════════════════════════════════════════
# Bot startup — deferred, safe, logged
# ═══════════════════════════════════════════════════════════
def _start_bots():
    global _started
    with _start_lock:
        if _started: return
        _started = True

    from pathlib import Path
    here = Path(__file__).parent.resolve()
    print(f"[launcher] cwd={os.getcwd()} here={here}", flush=True)

    # ── Config ──
    token = os.environ.get("TG_TOKEN", "").strip() or "8386088114:AAGsP7lKVApsI6suH3avJAOpXqxfhoOwBCs"
    owner_str = os.environ.get("TG_OWNER_ID", "").strip() or "8389746549"
    try: owner = int(owner_str)
    except Exception: owner = 8389746549
    os.environ["TG_TOKEN"] = token
    os.environ["TG_OWNER_ID"] = str(owner)

    # ── Soroosh ──
    sr_path = here / "Soroosh_tg_bot.py"
    if not sr_path.is_file():
        print(f"[launcher] ❌ Soroosh not found at {sr_path}", flush=True)
        _bot_status["soroosh"] = "missing"
    else:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("soroosh_bot", str(sr_path))
            mod = importlib.util.module_from_spec(spec)
            sys.modules["soroosh_bot"] = mod
            spec.loader.exec_module(mod)
            print("[launcher] ✅ Soroosh imported OK", flush=True)
            _bot_status["soroosh"] = "ok"

            def _run_sr():
                try:
                    mod.main(token=token, owner_id=owner)
                except Exception as e:
                    import traceback
                    print(f"[soroosh] runtime FAIL: {type(e).__name__}: {e}", flush=True)
                    traceback.print_exc()
                    _bot_status["soroosh"] = "crashed"

            t = threading.Thread(target=_run_sr, daemon=True, name="soroosh-bot")
            t.start()
            print("[launcher] ✅ Soroosh thread started", flush=True)
        except Exception as e:
            import traceback
            print(f"[launcher] ❌ Soroosh import FAIL: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            _bot_status["soroosh"] = "import_fail"

    # ── Portal ──
    portal_path = here / "portal.py"
    if not portal_path.is_file():
        print(f"[launcher] Portal not found — skipping", flush=True)
        _bot_status["portal"] = "missing"
    else:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("portal_bot", str(portal_path))
            mod = importlib.util.module_from_spec(spec)
            sys.modules["portal_bot"] = mod
            spec.loader.exec_module(mod)
            print("[launcher] ✅ Portal imported OK", flush=True)

            if hasattr(mod, "main"):
                def _run_pt():
                    try:
                        mod.main()
                    except Exception as e:
                        import traceback
                        print(f"[portal] runtime FAIL: {type(e).__name__}: {e}", flush=True)
                        traceback.print_exc()
                        _bot_status["portal"] = "crashed"

                t = threading.Thread(target=_run_pt, daemon=True, name="portal-bot")
                t.start()
                print("[launcher] ✅ Portal thread started", flush=True)
                _bot_status["portal"] = "ok"
            else:
                print("[launcher] ❌ Portal has no main()", flush=True)
                _bot_status["portal"] = "no_main"
        except Exception as e:
            import traceback
            print(f"[launcher] ❌ Portal import FAIL: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            _bot_status["portal"] = "import_fail"


# ═══════════════════════════════════════════════════════════
# Direct run (python app.py)
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("[launcher] direct mode", flush=True)
    _start_bots()
    try:
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("[launcher] stopped", flush=True)