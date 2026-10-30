#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V52 Patch for Soroosh_tg_bot.py
Fixes:
  1. Session release hang (delete account + template run)
  2. Joiner false positive (counts unverified joins as successful)
  3. Stricter join verification
"""
import sys, os, shutil, time

TARGET = "Soroosh_tg_bot.py"
for a in sys.argv[1:]:
    if not a.startswith("--"): TARGET = a; break
DRY = "--dry-run" in sys.argv

if not os.path.exists(TARGET):
    print(f"[x] not found: {TARGET}"); sys.exit(1)

with open(TARGET, "r", encoding="utf-8") as f:
    src = f.read()
orig = len(src)
applied, failed = [], []

def rep(name, old, new):
    global src
    if old not in src:
        failed.append(name); return
    src = src.replace(old, new, 1)
    applied.append(name)

# ══════════════════════════════════════════════════════════
# FIX 1 — Session release: timeout disconnect (prevents hang)
# ══════════════════════════════════════════════════════════

rep("release_timeout",
'''    async def _do_release(self, aid):
        w = self._clients.pop(aid, None)
        self._loops.pop(aid, None)
        if w:
            try: await w.disconnect()
            except Exception: pass''',
'''    async def _do_release(self, aid):
        w = self._clients.pop(aid, None)
        self._loops.pop(aid, None)
        if w:
            # V52: timeout disconnect — was hanging on stuck client
            try:
                await asyncio.wait_for(w.disconnect(), timeout=6)
            except asyncio.TimeoutError:
                flog(f"[v52-sm] {aid}: disconnect timeout 6s — force closing", "warning")
                try:
                    tele = getattr(w, "_telethon", None)
                    if tele is not None:
                        try: await asyncio.wait_for(tele.disconnect(), timeout=2)
                        except Exception: pass
                        try:
                            sess = getattr(tele, "session", None)
                            if sess is not None and hasattr(sess, "close"):
                                sess.close()
                        except Exception: pass
                except Exception: pass
            except Exception: pass''')

# ── also guard release() lock acquisition with timeout ──
rep("release_lock_timeout",
'''    async def release(self, aid):
        lock = self._aid_lock(aid)
        if lock is not None:
            async with lock:
                await self._do_release(aid)
        else:
            await self._do_release(aid)''',
'''    async def release(self, aid):
        # V52: bounded lock wait (was hanging up to 45s on stuck _do_get)
        lock = self._aid_lock(aid)
        if lock is not None:
            try:
                await asyncio.wait_for(lock.acquire(), timeout=10)
                try:
                    await self._do_release(aid)
                finally:
                    try: lock.release()
                    except Exception: pass
            except asyncio.TimeoutError:
                flog(f"[v52-sm] {aid}: release lock timeout 10s — forcing", "warning")
                w = self._clients.pop(aid, None)
                self._loops.pop(aid, None)
                if w:
                    try: await asyncio.wait_for(w.disconnect(), timeout=3)
                    except Exception: pass
        else:
            await self._do_release(aid)''')

# ══════════════════════════════════════════════════════════
# FIX 2 — Joiner: unverified ≠ joined (false positive fix)
# ══════════════════════════════════════════════════════════

rep("unverified_is_fail",
'''        if ent_new is None:
            return True, None, ("already" if tag == "already" else "unverified")''',
'''        if ent_new is None:
            # V52: was returning True here → false positive joins
            return False, None, ("already" if tag == "already" else "unverified")''')

# ── strengthen entity check ──
rep("strict_entity_check",
'''        # 4. Check broadcast channel
        if _is_broadcast_channel(ent_new):''',
'''        # V52: strict flags check before counting
        try:
            if getattr(ent_new, "left", False):
                return False, ent_new, "left_flag"
            if getattr(ent_new, "kicked", False):
                return False, ent_new, "kicked_flag"
            if getattr(ent_new, "deactivated", False):
                return False, ent_new, "deactivated"
        except Exception: pass
        # 4. Check broadcast channel
        if _is_broadcast_channel(ent_new):''')

# ══════════════════════════════════════════════════════════
# FIX 3 — _try_join invite: try harder to resolve entity
# ══════════════════════════════════════════════════════════

rep("invite_resolve_harder",
'''            if entity is not None and _is_broadcast_channel(entity):
                try: await _lefter_leave_one(cli, {"entity": entity, "kind": "channel"})
                except Exception: pass
                return False, "is_broadcast_channel", "channel", entity
            return True, None, "invite", entity''',
'''            # V52: if entity is None, try harder to resolve
            if entity is None and CheckChatInviteRequest is not None:
                try:
                    info = cli(CheckChatInviteRequest(h))
                    if asyncio.iscoroutine(info): info = await info
                    entity = getattr(info, "chat", None)
                except Exception: pass
            if entity is None:
                try:
                    entity = await cli.get_entity(h)
                except Exception: pass
            if entity is not None and _is_broadcast_channel(entity):
                try: await _lefter_leave_one(cli, {"entity": entity, "kind": "channel"})
                except Exception: pass
                return False, "is_broadcast_channel", "channel", entity
            # V52: return tag="invite"; _v46 will verify and NOT count unverified
            return True, None, "invite", entity''')

# ══════════════════════════════════════════════════════════
# FIX 4 — Auto-tar: log what really happened on join
# ══════════════════════════════════════════════════════════

rep("join_log_reason",
'''                            elif _why.startswith("closed"):
                                S["rejected"] = int(S.get("rejected", 0)) + 1
                                flog(f"[v46-join] 🚫 closed skip: {lk[:40]} ({_why})")
                            else:
                                S["failed"] = int(S.get("failed", 0)) + 1''',
'''                            elif _why.startswith("closed"):
                                S["rejected"] = int(S.get("rejected", 0)) + 1
                                flog(f"[v46-join] 🚫 closed skip: {lk[:40]} ({_why})")
                            else:
                                S["failed"] = int(S.get("failed", 0)) + 1
                                # V52: log WHY it failed (unverified / left_flag / timeout / ...)
                                flog(f"[v52-join] ✗ {lk[:40]} — {_why}")''')

# ══════════════════════════════════════════════════════════
# POST CHECK + WRITE
# ══════════════════════════════════════════════════════════

print("=" * 60)
print(f"V52 PATCH — {TARGET}")
print("=" * 60)
print(f"\n✅ Applied: {len(applied)}")
for a in applied: print(f"   ✓ {a}")
if failed:
    print(f"\n⚠️  Failed: {len(failed)}")
    for f in failed: print(f"   ✗ {f}")

try:
    compile(src, TARGET, "exec")
    print("\n✅ syntax OK")
except SyntaxError as e:
    print(f"\n❌ SYNTAX ERROR L{e.lineno}: {e.msg}")
    sys.exit(1)

print(f"\n📊 {orig:,} → {len(src):,} bytes ({len(src)-orig:+d})")

if DRY:
    print("\n🔍 dry-run — not written"); sys.exit(0)

bk = f"{TARGET}.bak.{int(time.time())}"
shutil.copy2(TARGET, bk)
with open(TARGET, "w", encoding="utf-8") as f:
    f.write(src)
print(f"\n💾 backup: {bk}")
print(f"✅ written: {TARGET}")