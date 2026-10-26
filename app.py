#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Minimal launcher: فقط Soroosh_tg_bot.py رو import و اجرا می‌کنه.
نه FastAPI، نه assistant، نه هیچ چیز دیگه.
"""
import os, sys, importlib.util
from pathlib import Path

HERE = Path(__file__).parent.resolve()

# env defaults
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

if __name__ == "__main__":
    try:
        sr.main()
    except KeyboardInterrupt:
        print("\n[!] stopped")
    except Exception as e:
        print(f"[!] fatal: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()