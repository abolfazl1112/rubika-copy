#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Launcher (V52 final)
- Soroosh in main thread (panel always opens)
- Portal in background (uses its own hardcoded token)
- Assistant only if ASST_TOKEN is set AND differs from TG_TOKEN

Run:     python app.py
ASGI:    uvicorn app:app --workers 1
"""
import os, sys, threading, signal
from pathlib import Path

HERE = Path(__file__).parent.resolve()

# ═══════════════════════════════════════════════════════════
# Signal patch — required for run_polling() in threads
# ═══════════════════════════════════════════════════════════
_MAIN_TID = threading.main_thread().ident
_orig_signal = signal.signal
def _safe_signal(sig, handler):
    if threading.current_thread().ident != _MAIN_TID:
        return None
    return _orig_signal(sig, handler)
signal.signal = _safe_signal

try:
    import asyncio.unix_events as _ue
    _o = _ue._UnixSelectorEventLoop.add_signal_handler
    def _s(self, sig, cb, *a):
        try: return _o(self, sig, cb, *a)
        except (RuntimeError, ValueError, NotImplementedError, AttributeError):
            return None
    _ue._UnixSelectorEventLoop.add_signal_handler = _s
except Exception: pass

print("[launcher] signal handlers patched")


def _find(name):
    for c in [HERE / name, HERE.parent / name,
              Path("/app") / name, Path.cwd() / name]:
        try:
            if c.is_file(): return c.resolve()
        except Exception: pass
    return None


SR_PATH     = _find("Soroosh_tg_bot.py")
ASST_PATH   = _find("assistant_tg_bot.py")
PORTAL_PATH = _find("portal.py")

if SR_PATH is None:
    print("[x] Soroosh_tg_bot.py not found"); sys.exit(1)

# ── Tokens ───────────────────────────────────────────────
TOKEN     = os.environ.get("TG_TOKEN", "").strip() or "8386088114:AAGsP7lKVApsI6suH3avJAOpXqxfhoOwBCs"
OWNER_STR = os.environ.get("TG_OWNER_ID", "").strip() or "8389746549"
OWNER     = int(OWNER_STR) if OWNER_STR.isdigit() else 8389746549

ASST_TOKEN = os.environ.get("ASST_TOKEN", "").strip()
ASST_OWNER_STR = os.environ.get("ASST_OWNER_ID", "").strip() or str(OWNER)
ASST_OWNER = int(ASST_OWNER_STR) if ASST_OWNER_STR.isdigit() else OWNER

# Validate: Assistant token MUST differ from Soroosh token
RUN_ASSISTANT = bool(ASST_TOKEN and ASST_TOKEN != TOKEN)
if ASST_TOKEN and ASST_TOKEN == TOKEN:
    print("[launcher] WARNING: ASST_TOKEN == TG_TOKEN → Assistant DISABLED (would cause Conflict)")

os.environ["TG_TOKEN"] = TOKEN
os.environ["TG_OWNER_ID"] = str(OWNER)

print(f"[launcher] Soroosh:   {SR_PATH}")
print(f"[launcher] Portal:    {PORTAL_PATH or '(skip)'}")
print(f"[launcher] Assistant: {ASST_PATH if RUN_ASSISTANT else '(skip - no separate token)'}")
print(f"[launcher] owner:     {OWNER}")

# ═══════════════════════════════════════════════════════════
# Bot state
# ═══════════════════════════════════════════════════════════
_bots = {
    "soroosh":   {"thread": None, "failed": threading.Event(), "lock": threading.Lock(), "fh": None},
    "assistant": {"thread": None, "failed": threading.Event(), "lock": threading.Lock(), "fh": None},
    "portal":    {"thread": None, "failed": threading.Event(), "lock": threading.Lock(), "fh": None},
}


def _acquire_lock(name):
    import tempfile
    p = os.path.join(tempfile.gettempdir(), f"{name}_bot.lock")
    try:
        try:
            import fcntl
            fh = open(p, "w"); fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            import msvcrt
            fh = open(p, "w"); msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        fh.write(str(os.getpid())); fh.flush()
        _bots[name]["fh"] = fh
        return True
    except (BlockingIOError, OSError, IOError):
        return False


# ═══════════════════════════════════════════════════════════
# Soroosh
# ═══════════════════════════════════════════════════════════
def _run_soroosh():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("soroosh_bot", str(SR_PATH))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["soroosh_bot"] = mod
        spec.loader.exec_module(mod)
        print("[launcher] Soroosh loaded ✓")
    except Exception as e:
        print(f"[launcher] Soroosh import FAIL: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        _bots["soroosh"]["failed"].set(); return
    try:
        mod.main(token=TOKEN, owner_id=OWNER)
    except KeyboardInterrupt:
        print("[launcher] Soroosh stopped")
    except Exception as e:
        print(f"[launcher] Soroosh error: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        _bots["soroosh"]["failed"].set()


# ═══════════════════════════════════════════════════════════
# Assistant (only if separate token)
# ═══════════════════════════════════════════════════════════
def _run_assistant():
    if ASST_PATH is None or not RUN_ASSISTANT: return
    try:
        import importlib.util
        # load soroosh first (assistant needs it)
        sspec = importlib.util.spec_from_file_location("soroosh_bot", str(SR_PATH))
        sr = importlib.util.module_from_spec(sspec)
        sys.modules["soroosh_bot"] = sr
        sspec.loader.exec_module(sr)

        aspec = importlib.util.spec_from_file_location("assistant_bot", str(ASST_PATH))
        amod = importlib.util.module_from_spec(aspec)
        sys.modules["assistant_bot"] = amod
        aspec.loader.exec_module(amod)

        amod.sr = sr
        print("[launcher] Assistant loaded ✓")
        _run_assistant_loop(amod)
    except Exception as e:
        print(f"[launcher] Assistant import FAIL: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        _bots["assistant"]["failed"].set()


def _run_assistant_loop(amod):
    try:
        from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                                  MessageHandler, filters as tg_filters)
        from telegram.request import HTTPXRequest
        from telegram import Update
        import asyncio

        amod.TG_TOKEN = ASST_TOKEN
        amod.FORCED_OWNER = ASST_OWNER
        amod.STATE["owner"] = ASST_OWNER

        async def _post_init(app):
            amod.TG_APP = app; amod.APP = app
            amod._loop_ref[0] = asyncio.get_running_loop()
            try: await amod.asst_on_startup()
            except Exception as e: print(f"[launcher] asst startup: {e}")
            try: asyncio.create_task(amod.asst_cleanup_loop())
            except Exception: pass

        async def _on_start(update, context):
            if not amod.authorized(update): return
            await amod.show_main(update.effective_chat.id)

        async def _on_callback(update, context):
            q = update.callback_query
            if q is None: return
            try: await q.answer()
            except Exception: pass
            if not amod.authorized(update): return
            cid = update.effective_chat.id
            if q.message: amod.STATE["panel"][cid] = q.message.message_id
            if q.data == "noop": return
            try: await amod.route_cb(cid, q.data or "")
            except Exception as e:
                import traceback; traceback.print_exc()
                await amod.tg_send(f"❌ {type(e).__name__}: {str(e)[:200]}")

        async def _on_group(update, context):
            try: await amod.on_group_message(update, context)
            except Exception as e: print(f"[asst-group] {e}")

        async def _on_private(update, context):
            try: await amod.on_private_message(update, context)
            except Exception as e: print(f"[asst-private] {e}")

        req = HTTPXRequest(connection_pool_size=8, connect_timeout=30.0,
                           read_timeout=30.0, write_timeout=30.0, pool_timeout=30.0)
        app = (Application.builder().token(ASST_TOKEN).request(req)
               .get_updates_request(req).post_init(_post_init).build())
        app.add_handler(CommandHandler("start", _on_start))
        app.add_handler(CallbackQueryHandler(_on_callback))
        app.add_handler(MessageHandler(tg_filters.ChatType.GROUPS & tg_filters.ALL, _on_group))
        app.add_handler(MessageHandler(tg_filters.ChatType.PRIVATE & tg_filters.ALL, _on_private))

        print("[launcher] Assistant polling...")
        app.run_polling(allowed_updates=Update.ALL_TYPES, poll_interval=2.0, timeout=30.0)
    except Exception as e:
        print(f"[launcher] Assistant runtime FAIL: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        _bots["assistant"]["failed"].set()


# ═══════════════════════════════════════════════════════════
# Portal (its own hardcoded token in portal.py)
# ═══════════════════════════════════════════════════════════
def _run_portal():
    if PORTAL_PATH is None: return
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("portal_bot", str(PORTAL_PATH))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["portal_bot"] = mod
        spec.loader.exec_module(mod)
        print("[launcher] Portal loaded ✓")
    except Exception as e:
        print(f"[launcher] Portal import FAIL: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        _bots["portal"]["failed"].set(); return
    try:
        if not hasattr(mod, "main"):
            print("[launcher] Portal has no main()")
            _bots["portal"]["failed"].set(); return
        mod.main()
    except KeyboardInterrupt:
        print("[launcher] Portal stopped")
    except Exception as e:
        print(f"[launcher] Portal error: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        _bots["portal"]["failed"].set()


# ═══════════════════════════════════════════════════════════
# Dispatcher
# ═══════════════════════════════════════════════════════════
_RUNNERS = {
    "soroosh":   (_run_soroosh,    True),
    "assistant": (_run_assistant,  ASST_PATH is not None and RUN_ASSISTANT),
    "portal":    (_run_portal,     PORTAL_PATH is not None),
}


def start_bot(name):
    info = _bots[name]; fn, should = _RUNNERS[name]
    if not should: return False
    with info["lock"]:
        if info["thread"] and info["thread"].is_alive(): return True
        if info["failed"].is_set(): return False
        if not _acquire_lock(name):
            print(f"[launcher] {name} already running elsewhere"); return False
        info["thread"] = threading.Thread(target=fn, daemon=True, name=f"{name}-bot")
        info["thread"].start()
        print(f"[launcher] {name} thread started"); return True


def _bot_alive(name):
    info = _bots[name]
    return bool(info["thread"] and info["thread"].is_alive() and not info["failed"].is_set())


def _all_alive():
    return all(_bot_alive(n) for n in _RUNNERS if _RUNNERS[n][1])


# ═══════════════════════════════════════════════════════════
# ASGI (for PaaS healthcheck)
# ═══════════════════════════════════════════════════════════
async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        msg = await receive()
        if msg["type"] == "lifespan.startup":
            # background for portal + assistant
            for n in ("portal", "assistant"):
                if _RUNNERS[n][1]: start_bot(n)
            # Soroosh ALSO in background in ASGI mode
            start_bot("soroosh")
            await send({"type": "lifespan.startup.complete"})
        msg = await receive()
        if msg["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
        return
    if scope["type"] == "http":
        path = scope.get("path", "/")
        if path in ("/", "/health"):
            ok = _all_alive()
            parts = []
            for n in ("soroosh", "assistant", "portal"):
                if not _RUNNERS[n][1]: continue
                parts.append(f'"{n}":"{"ok" if _bot_alive(n) else "down"}"')
            body = ('{"status":"' + ("ok" if ok else "degraded") + '",'
                    + ",".join(parts) + "}").encode()
            await send({"type": "http.response.start",
                        "status": 200 if ok else 503,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
        else:
            await send({"type": "http.response.start", "status": 404,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"not found"})


# ═══════════════════════════════════════════════════════════
# Direct run
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("[launcher] direct mode")
    # background bots first
    for n in ("portal", "assistant"):
        if _RUNNERS[n][1]: start_bot(n)
    # Soroosh in MAIN thread — guarantees panel opens
    print("[launcher] starting Soroosh in main thread...")
    _run_soroosh()#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Launcher (V52 final)
- Soroosh in main thread (panel always opens)
- Portal in background (uses its own hardcoded token)
- Assistant only if ASST_TOKEN is set AND differs from TG_TOKEN

Run:     python app.py
ASGI:    uvicorn app:app --workers 1
"""
import os, sys, threading, signal
from pathlib import Path

HERE = Path(__file__).parent.resolve()

# ═══════════════════════════════════════════════════════════
# Signal patch — required for run_polling() in threads
# ═══════════════════════════════════════════════════════════
_MAIN_TID = threading.main_thread().ident
_orig_signal = signal.signal
def _safe_signal(sig, handler):
    if threading.current_thread().ident != _MAIN_TID:
        return None
    return _orig_signal(sig, handler)
signal.signal = _safe_signal

try:
    import asyncio.unix_events as _ue
    _o = _ue._UnixSelectorEventLoop.add_signal_handler
    def _s(self, sig, cb, *a):
        try: return _o(self, sig, cb, *a)
        except (RuntimeError, ValueError, NotImplementedError, AttributeError):
            return None
    _ue._UnixSelectorEventLoop.add_signal_handler = _s
except Exception: pass

print("[launcher] signal handlers patched")


def _find(name):
    for c in [HERE / name, HERE.parent / name,
              Path("/app") / name, Path.cwd() / name]:
        try:
            if c.is_file(): return c.resolve()
        except Exception: pass
    return None


SR_PATH     = _find("Soroosh_tg_bot.py")
ASST_PATH   = _find("assistant_tg_bot.py")
PORTAL_PATH = _find("portal.py")

if SR_PATH is None:
    print("[x] Soroosh_tg_bot.py not found"); sys.exit(1)

# ── Tokens ───────────────────────────────────────────────
TOKEN     = os.environ.get("TG_TOKEN", "").strip() or "8386088114:AAGsP7lKVApsI6suH3avJAOpXqxfhoOwBCs"
OWNER_STR = os.environ.get("TG_OWNER_ID", "").strip() or "8389746549"
OWNER     = int(OWNER_STR) if OWNER_STR.isdigit() else 8389746549

ASST_TOKEN = os.environ.get("ASST_TOKEN", "").strip()
ASST_OWNER_STR = os.environ.get("ASST_OWNER_ID", "").strip() or str(OWNER)
ASST_OWNER = int(ASST_OWNER_STR) if ASST_OWNER_STR.isdigit() else OWNER

# Validate: Assistant token MUST differ from Soroosh token
RUN_ASSISTANT = bool(ASST_TOKEN and ASST_TOKEN != TOKEN)
if ASST_TOKEN and ASST_TOKEN == TOKEN:
    print("[launcher] WARNING: ASST_TOKEN == TG_TOKEN → Assistant DISABLED (would cause Conflict)")

os.environ["TG_TOKEN"] = TOKEN
os.environ["TG_OWNER_ID"] = str(OWNER)

print(f"[launcher] Soroosh:   {SR_PATH}")
print(f"[launcher] Portal:    {PORTAL_PATH or '(skip)'}")
print(f"[launcher] Assistant: {ASST_PATH if RUN_ASSISTANT else '(skip - no separate token)'}")
print(f"[launcher] owner:     {OWNER}")

# ═══════════════════════════════════════════════════════════
# Bot state
# ═══════════════════════════════════════════════════════════
_bots = {
    "soroosh":   {"thread": None, "failed": threading.Event(), "lock": threading.Lock(), "fh": None},
    "assistant": {"thread": None, "failed": threading.Event(), "lock": threading.Lock(), "fh": None},
    "portal":    {"thread": None, "failed": threading.Event(), "lock": threading.Lock(), "fh": None},
}


def _acquire_lock(name):
    import tempfile
    p = os.path.join(tempfile.gettempdir(), f"{name}_bot.lock")
    try:
        try:
            import fcntl
            fh = open(p, "w"); fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            import msvcrt
            fh = open(p, "w"); msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        fh.write(str(os.getpid())); fh.flush()
        _bots[name]["fh"] = fh
        return True
    except (BlockingIOError, OSError, IOError):
        return False


# ═══════════════════════════════════════════════════════════
# Soroosh
# ═══════════════════════════════════════════════════════════
def _run_soroosh():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("soroosh_bot", str(SR_PATH))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["soroosh_bot"] = mod
        spec.loader.exec_module(mod)
        print("[launcher] Soroosh loaded ✓")
    except Exception as e:
        print(f"[launcher] Soroosh import FAIL: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        _bots["soroosh"]["failed"].set(); return
    try:
        mod.main(token=TOKEN, owner_id=OWNER)
    except KeyboardInterrupt:
        print("[launcher] Soroosh stopped")
    except Exception as e:
        print(f"[launcher] Soroosh error: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        _bots["soroosh"]["failed"].set()


# ═══════════════════════════════════════════════════════════
# Assistant (only if separate token)
# ═══════════════════════════════════════════════════════════
def _run_assistant():
    if ASST_PATH is None or not RUN_ASSISTANT: return
    try:
        import importlib.util
        # load soroosh first (assistant needs it)
        sspec = importlib.util.spec_from_file_location("soroosh_bot", str(SR_PATH))
        sr = importlib.util.module_from_spec(sspec)
        sys.modules["soroosh_bot"] = sr
        sspec.loader.exec_module(sr)

        aspec = importlib.util.spec_from_file_location("assistant_bot", str(ASST_PATH))
        amod = importlib.util.module_from_spec(aspec)
        sys.modules["assistant_bot"] = amod
        aspec.loader.exec_module(amod)

        amod.sr = sr
        print("[launcher] Assistant loaded ✓")
        _run_assistant_loop(amod)
    except Exception as e:
        print(f"[launcher] Assistant import FAIL: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        _bots["assistant"]["failed"].set()


def _run_assistant_loop(amod):
    try:
        from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                                  MessageHandler, filters as tg_filters)
        from telegram.request import HTTPXRequest
        from telegram import Update
        import asyncio

        amod.TG_TOKEN = ASST_TOKEN
        amod.FORCED_OWNER = ASST_OWNER
        amod.STATE["owner"] = ASST_OWNER

        async def _post_init(app):
            amod.TG_APP = app; amod.APP = app
            amod._loop_ref[0] = asyncio.get_running_loop()
            try: await amod.asst_on_startup()
            except Exception as e: print(f"[launcher] asst startup: {e}")
            try: asyncio.create_task(amod.asst_cleanup_loop())
            except Exception: pass

        async def _on_start(update, context):
            if not amod.authorized(update): return
            await amod.show_main(update.effective_chat.id)

        async def _on_callback(update, context):
            q = update.callback_query
            if q is None: return
            try: await q.answer()
            except Exception: pass
            if not amod.authorized(update): return
            cid = update.effective_chat.id
            if q.message: amod.STATE["panel"][cid] = q.message.message_id
            if q.data == "noop": return
            try: await amod.route_cb(cid, q.data or "")
            except Exception as e:
                import traceback; traceback.print_exc()
                await amod.tg_send(f"❌ {type(e).__name__}: {str(e)[:200]}")

        async def _on_group(update, context):
            try: await amod.on_group_message(update, context)
            except Exception as e: print(f"[asst-group] {e}")

        async def _on_private(update, context):
            try: await amod.on_private_message(update, context)
            except Exception as e: print(f"[asst-private] {e}")

        req = HTTPXRequest(connection_pool_size=8, connect_timeout=30.0,
                           read_timeout=30.0, write_timeout=30.0, pool_timeout=30.0)
        app = (Application.builder().token(ASST_TOKEN).request(req)
               .get_updates_request(req).post_init(_post_init).build())
        app.add_handler(CommandHandler("start", _on_start))
        app.add_handler(CallbackQueryHandler(_on_callback))
        app.add_handler(MessageHandler(tg_filters.ChatType.GROUPS & tg_filters.ALL, _on_group))
        app.add_handler(MessageHandler(tg_filters.ChatType.PRIVATE & tg_filters.ALL, _on_private))

        print("[launcher] Assistant polling...")
        app.run_polling(allowed_updates=Update.ALL_TYPES, poll_interval=2.0, timeout=30.0)
    except Exception as e:
        print(f"[launcher] Assistant runtime FAIL: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        _bots["assistant"]["failed"].set()


# ═══════════════════════════════════════════════════════════
# Portal (its own hardcoded token in portal.py)
# ═══════════════════════════════════════════════════════════
def _run_portal():
    if PORTAL_PATH is None: return
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("portal_bot", str(PORTAL_PATH))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["portal_bot"] = mod
        spec.loader.exec_module(mod)
        print("[launcher] Portal loaded ✓")
    except Exception as e:
        print(f"[launcher] Portal import FAIL: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        _bots["portal"]["failed"].set(); return
    try:
        if not hasattr(mod, "main"):
            print("[launcher] Portal has no main()")
            _bots["portal"]["failed"].set(); return
        mod.main()
    except KeyboardInterrupt:
        print("[launcher] Portal stopped")
    except Exception as e:
        print(f"[launcher] Portal error: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        _bots["portal"]["failed"].set()


# ═══════════════════════════════════════════════════════════
# Dispatcher
# ═══════════════════════════════════════════════════════════
_RUNNERS = {
    "soroosh":   (_run_soroosh,    True),
    "assistant": (_run_assistant,  ASST_PATH is not None and RUN_ASSISTANT),
    "portal":    (_run_portal,     PORTAL_PATH is not None),
}


def start_bot(name):
    info = _bots[name]; fn, should = _RUNNERS[name]
    if not should: return False
    with info["lock"]:
        if info["thread"] and info["thread"].is_alive(): return True
        if info["failed"].is_set(): return False
        if not _acquire_lock(name):
            print(f"[launcher] {name} already running elsewhere"); return False
        info["thread"] = threading.Thread(target=fn, daemon=True, name=f"{name}-bot")
        info["thread"].start()
        print(f"[launcher] {name} thread started"); return True


def _bot_alive(name):
    info = _bots[name]
    return bool(info["thread"] and info["thread"].is_alive() and not info["failed"].is_set())


def _all_alive():
    return all(_bot_alive(n) for n in _RUNNERS if _RUNNERS[n][1])


# ═══════════════════════════════════════════════════════════
# ASGI (for PaaS healthcheck)
# ═══════════════════════════════════════════════════════════
async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        msg = await receive()
        if msg["type"] == "lifespan.startup":
            # background for portal + assistant
            for n in ("portal", "assistant"):
                if _RUNNERS[n][1]: start_bot(n)
            # Soroosh ALSO in background in ASGI mode
            start_bot("soroosh")
            await send({"type": "lifespan.startup.complete"})
        msg = await receive()
        if msg["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
        return
    if scope["type"] == "http":
        path = scope.get("path", "/")
        if path in ("/", "/health"):
            ok = _all_alive()
            parts = []
            for n in ("soroosh", "assistant", "portal"):
                if not _RUNNERS[n][1]: continue
                parts.append(f'"{n}":"{"ok" if _bot_alive(n) else "down"}"')
            body = ('{"status":"' + ("ok" if ok else "degraded") + '",'
                    + ",".join(parts) + "}").encode()
            await send({"type": "http.response.start",
                        "status": 200 if ok else 503,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
        else:
            await send({"type": "http.response.start", "status": 404,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"not found"})


# ═══════════════════════════════════════════════════════════
# Direct run
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("[launcher] direct mode")
    # background bots first
    for n in ("portal", "assistant"):
        if _RUNNERS[n][1]: start_bot(n)
    # Soroosh in MAIN thread — guarantees panel opens
    print("[launcher] starting Soroosh in main thread...")
    _run_soroosh()()