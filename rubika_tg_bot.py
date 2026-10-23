# Rubika_tg_bot.py — v2.3.1 (fixed login hang · remove send_code_request hook · logging)
import os, sys, json, asyncio, time, re, threading, secrets, random, hashlib, glob, mimetypes
import logging, traceback, builtins, queue
import html as _html
from typing import Optional, Dict, Any, List, Set, Tuple

VERSION = "Rubika v2.3.1"


def _detect_data_dir():
    env = os.environ.get("DATA_DIR", "").strip()
    if env and os.path.isdir(env) and os.access(env, os.W_OK): return env
    rv = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if rv and os.path.isdir(rv) and os.access(rv, os.W_OK): return rv
    if os.environ.get("RAILWAY_ENVIRONMENT"):
        for c in ["/data", "/app/data"]:
            if os.path.isdir(c) and os.access(c, os.W_OK): return c
    return os.path.dirname(os.path.abspath(__file__))


DATA_DIR = _detect_data_dir()
RUBIKA_DIR = os.path.join(DATA_DIR, "rubika")
os.makedirs(RUBIKA_DIR, exist_ok=True)
LOG_FILE = os.path.join(RUBIKA_DIR, "rubika.log")
UPLOADS_DIR = os.path.join(RUBIKA_DIR, "uploads")
LANG_FILE = os.path.join(RUBIKA_DIR, "lang.json")
SESSIONS_DIR = os.path.join(RUBIKA_DIR, "sessions")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(SESSIONS_DIR, exist_ok=True)

logging.basicConfig(level=logging.CRITICAL, stream=open(os.devnull, "w"))
for _n in ("urllib3", "requests", "httpx", "httpcore",
           "telegram.ext.Updater", "telegram.request", "rubpy", "asyncio"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)
    logging.getLogger(_n).propagate = False

print(f"[+] VERSION: {VERSION}")
print(f"[+] DATA_DIR: {DATA_DIR}")

TG_TOKEN = os.environ.get("TG_TOKEN", "").strip()
try: FORCED_OWNER = int(os.environ.get("TG_OWNER_ID", "8389746549"))
except Exception: FORCED_OWNER = 8389746549
print(f"[+] OWNER: {FORCED_OWNER}")
if not TG_TOKEN:
    print("[!] TG_TOKEN not set — export TG_TOKEN='<token>'")

try:
    import asyncio.unix_events as _ue
    _orig_add_signal = _ue._UnixSelectorEventLoop.add_signal_handler
    def _safe_add_signal(self, sig, callback, *args):
        try: return _orig_add_signal(self, sig, callback, *args)
        except Exception: return None
    _ue._UnixSelectorEventLoop.add_signal_handler = _safe_add_signal
except Exception: pass

_flog = logging.getLogger("rubika_file"); _flog.setLevel(logging.DEBUG); _flog.propagate = False
try:
    _fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _flog.addHandler(_fh)
except Exception: pass

def flog(msg, level="info"):
    try: print(f"[rubika] {msg}", flush=True)
    except Exception: pass
    try: getattr(_flog, level)(msg)
    except Exception: pass

try:
    from rubpy import Client as RubikaClient
    RUBIKA_OK = True
except ImportError as _e:
    print(f"[x] rubpy not installed: {_e}"); RUBIKA_OK = False

# ═══════════════ I18N + STYLE ═══════════════
_LANG_CACHE = {"v": None}
def _get_lang():
    if _LANG_CACHE["v"]: return _LANG_CACHE["v"]
    try:
        if os.path.exists(LANG_FILE):
            with open(LANG_FILE, encoding="utf-8") as f:
                _LANG_CACHE["v"] = json.load(f).get("v", "fa")
        else: _LANG_CACHE["v"] = "fa"
    except Exception: _LANG_CACHE["v"] = "fa"
    return _LANG_CACHE["v"]
def _set_lang(v):
    _LANG_CACHE["v"] = v
    try:
        with open(LANG_FILE, "w", encoding="utf-8") as f:
            json.dump({"v": v}, f, ensure_ascii=False)
    except Exception: pass
def is_en(): return _get_lang() == "en"

_SC = str.maketrans({
    'a':'ᴀ','b':'ʙ','c':'ᴄ','d':'ᴅ','e':'ᴇ','f':'ꜰ','g':'ɢ','h':'ʜ','i':'ɪ',
    'j':'ᴊ','k':'ᴋ','l':'ʟ','m':'ᴍ','n':'ɴ','o':'ᴏ','p':'ᴘ','q':'ǫ','r':'ʀ',
    's':'ꜱ','t':'ᴛ','u':'ᴜ','v':'ᴠ','w':'ᴡ','x':'x','y':'ʏ','z':'ᴢ',
    'A':'ᴀ','B':'ʙ','C':'ᴄ','D':'ᴅ','E':'ᴇ','F':'ꜰ','G':'ɢ','H':'ʜ','I':'ɪ',
    'J':'ᴊ','K':'ᴋ','L':'ʟ','M':'ᴍ','N':'ɴ','O':'ᴏ','P':'ᴘ','Q':'ǫ','R':'ʀ',
    'S':'ꜱ','T':'ᴛ','U':'ᴜ','V':'ᴠ','W':'ᴡ','X':'x','Y':'ʏ','Z':'ᴢ',
})
def SC(s): return str(s).translate(_SC) if is_en() else str(s)
TICK = "⤳"
def _line(): return "━" * 32

_TR = {
"panel": {"fa": "پنل", "en": "panel"},
"accounts_n": {"fa": "اکانت‌ها", "en": "accounts"},
"pv_enabled": {"fa": "PV فعال", "en": "pv enabled"},
"running_ops": {"fa": "در حال اجرا", "en": "running ops"},
"idle": {"fa": "بیکار", "en": "idle"},
"listener": {"fa": "لیسنر", "en": "listener"},
"data_dir": {"fa": "مسیر داده", "en": "data dir"},
"send": {"fa": "ارسال", "en": "send"},
"joiner": {"fa": "جوینر", "en": "joiner"},
"lefter": {"fa": "لفتر", "en": "lefter"},
"templates": {"fa": "قالب‌ها", "en": "templates"},
"pv": {"fa": "پیوی", "en": "pv"},
"stats": {"fa": "آمار", "en": "stats"},
"errors": {"fa": "خطاها", "en": "errors"},
"cache": {"fa": "کش", "en": "cache"},
"linkdonies": {"fa": "لینک‌دونی", "en": "linkdonies"},
"settings": {"fa": "تنظیمات", "en": "settings"},
"back_to_panel": {"fa": "بازگشت به پنل", "en": "back to panel"},
"back": {"fa": "بازگشت", "en": "back"},
"cancel": {"fa": "لغو", "en": "cancel"},
"next": {"fa": "بعدی »", "en": "next »"},
"prev": {"fa": "« قبلی", "en": "« prev"},
"yes": {"fa": "بله", "en": "yes"},
"no": {"fa": "خیر", "en": "no"},
"confirm": {"fa": "تایید", "en": "confirm"},
"start": {"fa": "شروع", "en": "start"},
"stop": {"fa": "توقف", "en": "stop"},
"add": {"fa": "افزودن", "en": "add"},
"delete": {"fa": "حذف", "en": "delete"},
"clear": {"fa": "پاک", "en": "clear"},
"toggle_on": {"fa": "روشن کن", "en": "turn on"},
"toggle_off": {"fa": "خاموش کن", "en": "turn off"},
"on": {"fa": "روشن", "en": "on"},
"off": {"fa": "خاموش", "en": "off"},
"all": {"fa": "همه", "en": "all"},
"empty": {"fa": "خالی", "en": "empty"},
"loading": {"fa": "در حال بارگذاری...", "en": "loading..."},
"not_found": {"fa": "پیدا نشد.", "en": "not found."},
"select_account": {"fa": "یک اکانت انتخاب کن", "en": "select an account"},
"pv_auto": {"fa": "پاسخ خودکار پیوی", "en": "auto-reply pv"},
"pv_status": {"fa": "وضعیت", "en": "status"},
"pv_active": {"fa": "فعال", "en": "on"},
"pv_inactive": {"fa": "خاموش", "en": "off"},
"pv_poller": {"fa": "پولر", "en": "poller"},
"pv_max": {"fa": "سقف/کاربر", "en": "max/user"},
"pv_delay": {"fa": "تایمر", "en": "delay"},
"pv_notify": {"fa": "اعلان", "en": "notify"},
"pv_poll": {"fa": "هر چند ثانیه", "en": "poll"},
"pv_items": {"fa": "پیام‌ها", "en": "items"},
"pv_custom": {"fa": "سفارشی", "en": "custom"},
"pv_add_text": {"fa": "افزودن متن", "en": "+ text"},
"pv_add_file": {"fa": "افزودن فایل", "en": "+ file"},
"pv_add_delay": {"fa": "افزودن تاخیر", "en": "+ delay"},
"pv_list": {"fa": "لیست پیام‌ها", "en": "items"},
"pv_report": {"fa": "گزارش", "en": "report"},
"pv_reset_counter": {"fa": "ریست شمارنده", "en": "reset counter"},
"pv_reset_custom": {"fa": "حذف سفارشی", "en": "reset custom"},
"pv_restart": {"fa": "ری‌استارت", "en": "restart"},
"pv_delay_q": {"fa": "تایمر (0=آنی):", "en": "delay (0=instant):"},
"pv_poll_q": {"fa": "هر چند ثانیه؟ (حداقل 2):", "en": "poll seconds (>=2):"},
"pv_text_q": {"fa": "متن:", "en": "text:"},
"pv_file_q": {"fa": "پیام/عکس/فایل:", "en": "send msg/photo/file:"},
"pv_delaysec_q": {"fa": "ثانیه:", "en": "seconds:"},
"pv_report_title": {"fa": "گزارش پیوی", "en": "pv report"},
"pv_total": {"fa": "کل", "en": "total"},
"pv_page": {"fa": "صفحه", "en": "page"},
"pv_no_accounts": {"fa": "هیچ اکانتی نداری.", "en": "no accounts yet."},
"accounts_title": {"fa": "اکانت‌ها", "en": "accounts"},
"add_account": {"fa": "افزودن اکانت", "en": "add account"},
"bulk_login": {"fa": "ورود انبوه", "en": "bulk login"},
"alias": {"fa": "اسم مستعار", "en": "alias"},
"refresh_profile": {"fa": "به‌روزرسانی پروفایل", "en": "refresh profile"},
"real_name": {"fa": "نام واقعی", "en": "real name"},
"username": {"fa": "نام کاربری", "en": "username"},
"user_id": {"fa": "شناسه عددی", "en": "user id"},
"guid": {"fa": "شناسه", "en": "guid"},
"avatar": {"fa": "عکس پروفایل", "en": "avatar"},
"phone": {"fa": "شماره", "en": "phone"},
"groups": {"fa": "گروه‌ها", "en": "groups"},
"pvs": {"fa": "پیوی", "en": "pvs"},
"channels_created": {"fa": "کانال ساخته", "en": "channels created"},
"listener_status": {"fa": "لیسنر", "en": "listener"},
"delete_account": {"fa": "حذف اکانت", "en": "delete account"},
"refresh_stats": {"fa": "بروزرسانی آمار", "en": "refresh stats"},
"auto_tar": {"fa": "اتو تار", "en": "auto-tar"},
"add_account_q": {"fa": "🔑 <b>ورود اکانت</b>\n━━━━━━━━━━━━━━━\n\nلطفاً شماره را وارد کنید:\n\nمثال: <code>989121234567</code>", "en": "🔑 <b>Account login</b>\n━━━━━━━━━━━━━━━\n\nPlease enter the phone number:\n\nExample: <code>989121234567</code>"},
"invalid_phone": {"fa": "شماره نامعتبر:", "en": "invalid phone:"},
"acc_delete_q": {"fa": "حذف <b>{n}</b>؟", "en": "delete <b>{n}</b>?"},
"prof_first_q": {"fa": "نام:", "en": "first name:"},
"prof_last_q": {"fa": "فامیل:", "en": "last name:"},
"prof_bio_q": {"fa": "بیو:", "en": "bio:"},
"prof_user_q": {"fa": "یوزرنیم:", "en": "username:"},
"prof_photo_menu": {"fa": "عکس پروفایل", "en": "profile photo"},
"prof_set_photo": {"fa": "تنظیم عکس جدید", "en": "set new photo"},
"prof_del_photo": {"fa": "حذف عکس‌ها", "en": "delete photos"},
"prof_send_photo": {"fa": "عکس رو بفرست:", "en": "send photo:"},
"prof_no_photo": {"fa": "عکس نبود:", "en": "no photo:"},
"prof_deleting": {"fa": "در حال حذف...", "en": "deleting..."},
"prof_uploading": {"fa": "در حال آپلود...", "en": "uploading..."},
"ch_photo_menu": {"fa": "عکس کانال", "en": "channel photo"},
"ch_new_type": {"fa": "نوع کانال:", "en": "channel type:"},
"ch_new_name_q": {"fa": "اسم کانال:", "en": "channel name:"},
"ch_new_user_q": {"fa": "یوزرنیم:", "en": "username:"},
"ch_creating": {"fa": "در حال ساخت...", "en": "creating..."},
"ch_created": {"fa": "ساخته شد", "en": "created"},
"ch_no_channels": {"fa": "هنوز کانالی نساختی.", "en": "no channels yet."},
"ch_send_q": {"fa": "متن:", "en": "text:"},
"ch_file_q": {"fa": "فایل:", "en": "file:"},
"ch_caption_q": {"fa": "کپشن:", "en": "caption:"},
"ch_link_fetch": {"fa": "در حال دریافت...", "en": "fetching..."},
"ch_link_q": {"fa": "لینک:", "en": "link:"},
"ch_profile_edit_title": {"fa": "اسم:", "en": "title:"},
"ch_profile_edit_desc": {"fa": "توضیح:", "en": "description:"},
"ch_profile_edit_user": {"fa": "یوزرنیم:", "en": "username:"},
"ch_delete_q": {"fa": "حذف کانال؟", "en": "delete channel?"},
"listener_restart_all": {"fa": "ری‌استارت همه", "en": "restart all"},
"ld_auto_join": {"fa": "جوین خودکار", "en": "auto-join"},
"ld_progress_per_acc": {"fa": "پیشرفت برای هر اکانت جداست", "en": "progress per account"},
"ld_add_q": {"fa": "لینک:", "en": "link:"},
"ld_reset_prog": {"fa": "بازنشانی پیشرفت همه", "en": "reset all progress"},
"ld_reset_list": {"fa": "بازنشانی لیست", "en": "reset list"},
"ld_add": {"fa": "افزودن", "en": "+ add"},
"op_joiner": {"fa": "جوینر", "en": "joiner"},
"op_lefter": {"fa": "لفتر", "en": "lefter"},
"op_autotar": {"fa": "اتو تار", "en": "auto-tar"},
"op_send": {"fa": "ارسال", "en": "send"},
"op_running": {"fa": "در حال اجرا", "en": "running"},
"op_paused": {"fa": "متوقف", "en": "paused"},
"op_queued": {"fa": "در صف", "en": "queued"},
"op_done": {"fa": "تکمیل", "en": "done"},
"op_failed": {"fa": "خطا", "en": "failed"},
"op_cancelled": {"fa": "لغو شده", "en": "cancelled"},
"op_empty": {"fa": "خالی", "en": "empty"},
"op_draft": {"fa": "پیش‌نویس", "en": "draft"},
"op_joined": {"fa": "جوین", "en": "joined"},
"op_sent": {"fa": "ارسال", "en": "sent"},
"op_left": {"fa": "ترک", "en": "left"},
"op_failed_c": {"fa": "خطا", "en": "failed"},
"op_tried": {"fa": "تلاش", "en": "tried"},
"op_wave": {"fa": "موج", "en": "wave"},
"op_round": {"fa": "دور", "en": "round"},
"op_phase": {"fa": "مرحله", "en": "phase"},
"op_limit": {"fa": "سقف", "en": "limit"},
"op_already": {"fa": "قبا عضو", "en": "already"},
"op_blocked": {"fa": "بلاک", "en": "blocked"},
"op_skipped_seen": {"fa": "دیده‌شده", "en": "seen"},
"op_skipped_banned": {"fa": "بلاک‌شده", "en": "banned"},
"op_rejected": {"fa": "غیرفعال", "en": "inactive"},
"stats_title": {"fa": "آمار", "en": "stats"},
"stats_done": {"fa": "موفق", "en": "done"},
"stats_failed": {"fa": "ناموفق", "en": "failed"},
"stats_errors": {"fa": "خطاها", "en": "errors"},
"stats_running": {"fa": "در حال اجرا", "en": "running now"},
"errors_none": {"fa": "خالی", "en": "empty"},
"send_step1": {"fa": "اکانت(ها)", "en": "accounts"},
"send_step2": {"fa": "متن را بفرست", "en": "send the message text"},
"send_step3": {"fa": "مقصد؟", "en": "select target"},
"send_step4": {"fa": "حداکثر؟", "en": "max messages"},
"send_target_pv": {"fa": "پیوی", "en": "pv only"},
"send_target_gr": {"fa": "گروه‌ها", "en": "groups only"},
"send_target_both": {"fa": "هر دو", "en": "both"},
"send_grp_only": {"fa": "فقط گروه‌های واقعی", "en": "real groups only"},
"send_infinite": {"fa": "لوپ بی‌نهایت", "en": "infinite loop"},
"send_loop_delay": {"fa": "بین دورها", "en": "loop delay"},
"send_rescan": {"fa": "اسکن مجدد در هر دور", "en": "rescan each round"},
"send_edit": {"fa": "تاخیر ویرایش", "en": "edit delay"},
"send_random": {"fa": "تصادفی", "en": "random"},
"send_ph_list": {"fa": "لیست", "en": "list"},
"send_multi": {"fa": "چند مرحله‌ای", "en": "multi-step edit"},
"send_attach": {"fa": "پیوست فایل", "en": "attach file"},
"send_auto_left": {"fa": "ترک خودکار", "en": "auto leave"},
"send_attach_q": {"fa": "فایل:", "en": "send file:"},
"send_loop_q": {"fa": "ثانیه بین دورها:", "en": "seconds between loops:"},
"send_edit_q": {"fa": "ثانیه:", "en": "seconds:"},
"send_ph_q": {"fa": "متن جانشین:", "en": "placeholder text:"},
"send_max_q": {"fa": "عدد (0=بی‌نهایت):", "en": "number (0=∞):"},
"send_unlimited": {"fa": "بی‌نهایت", "en": "unlimited"},
"send_custom": {"fa": "دلخواه", "en": "custom"},
"jl_title": {"fa": "جوینر", "en": "joiner"},
"jl_select": {"fa": "کدام اکانت؟", "en": "select accounts"},
"jl_selected": {"fa": "انتخاب‌شده", "en": "selected"},
"jl_speed": {"fa": "سرعت", "en": "speed"},
"jl_grp_only": {"fa": "فقط گروه‌ها", "en": "groups only"},
"jl_max": {"fa": "سقف", "en": "max join"},
"jl_speed_ultra": {"fa": "فوق‌سریع", "en": "ultra"},
"jl_speed_fast": {"fa": "سریع", "en": "fast"},
"jl_speed_normal": {"fa": "عادی", "en": "normal"},
"jl_speed_safe": {"fa": "امن", "en": "safe"},
"jl_ld": {"fa": "لینک‌دونی", "en": "linkdonies"},
"jl_max_q": {"fa": "عدد:", "en": "number:"},
"jl_no_account": {"fa": "اول اکانت اضافه کن.", "en": "add an account first."},
"lf_title": {"fa": "لفتر", "en": "lefter"},
"lf_mode": {"fa": "حالت ترک", "en": "leave mode"},
"lf_mode_all": {"fa": "همه گروه‌ها و کانال‌ها", "en": "all chats"},
"lf_mode_groups": {"fa": "فقط گروه‌ها", "en": "groups only"},
"lf_mode_channels": {"fa": "فقط کانال‌ها", "en": "channels only"},
"lf_mode_closed": {"fa": "فقط گروه‌های بسته", "en": "closed groups"},
"lf_delay": {"fa": "تاخیر", "en": "delay"},
"at_title": {"fa": "قالب‌ها", "en": "templates"},
"at_desc": {"fa": "قالب = ست کامل از تنظیمات", "en": "template = full config set"},
"at_new": {"fa": "ساخت قالب", "en": "+ new template"},
"at_channel": {"fa": "کانال", "en": "channel"},
"at_profile": {"fa": "پروفایل", "en": "profile"},
"at_joiner": {"fa": "جوین", "en": "joiner"},
"at_sender": {"fa": "ارسال", "en": "sender"},
"at_pv": {"fa": "پیوی", "en": "pv"},
"at_lefter": {"fa": "ترک", "en": "lefter"},
"at_rename": {"fa": "تغییر نام", "en": "rename"},
"at_run": {"fa": "اجرا روی اکانت", "en": "run on accounts"},
"at_delete": {"fa": "حذف", "en": "delete"},
"at_mode_only": {"fa": "فقط ارسال", "en": "send only"},
"at_mode_js": {"fa": "جوین + ارسال", "en": "join + send"},
"at_mode_jsl": {"fa": "جوین + ارسال + ترک", "en": "join + send + leave"},
"at_apply_acc": {"fa": "اعمال روی اکانت‌ها", "en": "apply to accounts"},
"at_run_title": {"fa": "اجرای قالب", "en": "run template"},
"at_rename_q": {"fa": "نام:", "en": "name:"},
"at_delete_q": {"fa": "حذف <b>{n}</b>؟", "en": "delete <b>{n}</b>?"},
"cfg_title": {"fa": "تنظیمات", "en": "settings"},
"cfg_lang": {"fa": "زبان", "en": "language"},
"cfg_lang_fa": {"fa": "فارسی", "en": "persian"},
"cfg_lang_en": {"fa": "انگلیسی", "en": "english"},
"cfg_join_delay": {"fa": "تاخیر جوین", "en": "join delay"},
"cfg_wave_size": {"fa": "اندازه موج", "en": "wave size"},
"cfg_extract": {"fa": "سقف استخراج", "en": "extract limit"},
"cfg_wait": {"fa": "انتظار لینک", "en": "wait for links"},
"cfg_auto_join": {"fa": "جوین خودکار لینک‌دونی", "en": "auto-join linkdoni"},
"cfg_listener": {"fa": "لیسنر", "en": "listener"},
"cfg_value_q": {"fa": "مقدار جدید برای {k}:", "en": "new value for {k}:"},
"cfg_invalid": {"fa": "عدد نامعتبر", "en": "invalid number"},
"mode": {"fa": "حالت", "en": "mode"},
"max": {"fa": "سقف", "en": "max"},
"text": {"fa": "متن", "en": "text"},
"target": {"fa": "مقصد", "en": "target"},
"delay": {"fa": "تاخیر", "en": "delay"},
"file": {"fa": "فایل", "en": "file"},
"vars": {"fa": "متغیرها", "en": "vars"},
"debug": {"fa": "عیب‌یابی", "en": "debug"},
"link_sent": {"fa": "لینک", "en": "link"},
"failed": {"fa": "ناموفق", "en": "failed"},
"ph_start": {"fa": "شروع", "en": "start"},
"ph_connect": {"fa": "اتصال", "en": "connecting"},
"ph_connected": {"fa": "متصل شد: {n}", "en": "connected: {n}"},
"ph_connect_fail": {"fa": "اتصال ناموفق: {n}", "en": "connect failed: {n}"},
"ph_auto_join": {"fa": "جوین خودکار {i}/{t}", "en": "auto-join {i}/{t}"},
"ph_extract": {"fa": "موج {n}: استخراج", "en": "wave {n}: extracting"},
"ph_deep": {"fa": "موج {n}: اسکن عمیق", "en": "wave {n}: deep scan"},
"ph_wait": {"fa": "انتظار {s}ث ({i}/{t})", "en": "wait {s}s ({i}/{t})"},
"ph_links": {"fa": "موج {n}: {c} لینک", "en": "wave {n}: {c} links"},
"ph_wave_done": {"fa": "موج {n} تمام", "en": "wave {n} done"},
"ph_no_links": {"fa": "لینک جدیدی نیامد", "en": "no new links"},
"ph_limit": {"fa": "به سقف رسید", "en": "limit reached"},
"ph_collecting": {"fa": "جمع‌آوری مخاطبین", "en": "collecting targets"},
"ph_sending": {"fa": "ارسال به {n}", "en": "sending to {n}"},
"ph_loop": {"fa": "دور {n}", "en": "loop {n}"},
"ph_send_final": {"fa": "ارسال نهایی", "en": "final send"},
"ph_update_prof": {"fa": "بروزرسانی پروفایل", "en": "updating profile"},
"ph_create_ch": {"fa": "ساخت کانال: {n}", "en": "creating channel: {n}"},
"ph_leaving": {"fa": "ترک کردن ({m})", "en": "leaving ({m})"},
"ph_no_targets": {"fa": "مخاطبی نیست", "en": "no targets"},
"ph_nothing": {"fa": "چیزی نیست", "en": "nothing"},
"ph_done": {"fa": "پایان", "en": "done"},
"ph_cancelled": {"fa": "لغو شد", "en": "cancelled"},
"ph_error": {"fa": "خطا: {n}", "en": "error: {n}"},
"ph_progress": {"fa": "پیشرفت {a}/{b}", "en": "progress {a}/{b}"},
"ph_acc_suspend": {"fa": "اکانت {n} معلق شده", "en": "account {n} suspended"},
"ph_reply_ok": {"fa": "پاسخ موفق به {u}", "en": "reply ok: {u}"},
"ph_reply_fail": {"fa": "پاسخ ناموفق به {u}: {e}", "en": "reply failed: {u}: {e}"},
"public": {"fa": "عمومی", "en": "public"},
"private": {"fa": "خصوصی", "en": "private"},
"type": {"fa": "نوع", "en": "type"},
"link": {"fa": "لینک", "en": "link"},
"get_link": {"fa": "دریافت لینک", "en": "get link"},
"set_link": {"fa": "ثبت لینک", "en": "set link"},
"ch_send_text": {"fa": "متن", "en": "text"},
"ch_send_photo": {"fa": "عکس", "en": "photo"},
"ch_send_video": {"fa": "ویدیو", "en": "video"},
"ch_send_file": {"fa": "فایل", "en": "file"},
"seen": {"fa": "دیده‌شده", "en": "seen"},
"banned": {"fa": "بلاک‌شده", "en": "banned"},
"channels": {"fa": "کانال‌ها", "en": "channels"},
"my_channels": {"fa": "کانال‌های من", "en": "my channels"},
"create_channel": {"fa": "ساخت کانال جدید", "en": "create new channel"},
"channel_title": {"fa": "عنوان", "en": "title"},
"about": {"fa": "درباره", "en": "about"},
"name": {"fa": "نام", "en": "name"},
"last_name": {"fa": "فامیل", "en": "last name"},
"bio": {"fa": "بیو", "en": "bio"},
"photo": {"fa": "عکس", "en": "photo"},
"profile": {"fa": "پروفایل", "en": "profile"},
"ld_progress": {"fa": "پیشرفت لینک‌دونی", "en": "linkdoni progress"},
"clear_seen": {"fa": "پاک دیده‌شده", "en": "clear seen"},
"clear_banned": {"fa": "پاک بلاک‌شده", "en": "clear banned"},
"clear_both": {"fa": "پاک هر دو", "en": "clear both"},
"reset_ld": {"fa": "ریست پیشرفت", "en": "reset ld progress"},
"wipe_all": {"fa": "پاک کردن همه", "en": "wipe all"},
}

def T(k, **kw):
    e = _TR.get(k)
    if not e: return str(k)
    lang = _get_lang()
    s = e.get(lang) or e.get("en") or str(k)
    for a, b in kw.items(): s = s.replace("{" + a + "}", str(b))
    return s

# ═══════════════ HELPERS ═══════════════
def _load(path, default):
    if not os.path.exists(path):
        return dict(default) if isinstance(default, dict) else default
    try:
        with open(path, encoding="utf-8") as f: d = json.load(f)
        if isinstance(default, dict) and isinstance(d, dict): return {**default, **d}
        return d
    except Exception: return dict(default) if isinstance(default, dict) else default

def _save(path, data):
    try: os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    except Exception: pass
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(path + ".tmp", path)

def _fmt_error(e):
    if e is None: return "—"
    if hasattr(e, "message"): return str(e.message)[:300]
    return str(e)[:300]

def _is_rate_limit(ex):
    return any(k in str(ex).upper() for k in ("TOO_MANY", "RATE_LIMIT", "FLOOD", "TOO_REQUESTS"))

def _is_perm_error(ex):
    msg = str(ex).upper()
    return any(k in msg for k in ("FORBIDDEN", "BANNED", "KICKED", "BLOCKED", "SUSPENDED"))

def _is_auth_dead(ex):
    s = str(ex).upper()
    return any(k in s for k in ("AUTH_DEAD", "NO_SESSION", "SESSION_REVOKED",
                                "AUTH_KEY_UNREGISTERED", "INVALID_AUTH"))

def normalize_phone(raw: str) -> str:
    if not raw: return ""
    s = re.sub(r"[^\d]", "", str(raw))
    if not s: return ""
    if s.startswith("00"): s = s[2:]
    if s.startswith("0"): s = s[1:]
    if not s.startswith("98"): s = "98" + s
    if len(s) < 11 or len(s) > 13: raise ValueError(f"invalid: {raw}")
    return s

def _hash_of(link):
    if not link: return ""
    s = link.strip().lower()
    if s.startswith("@"): return "u:" + s[1:]
    m = re.search(r"/joing/([A-Za-z0-9_\-]+)", s)
    if m: return "j:" + m.group(1)
    m = re.search(r"rubika\.ir/([A-Za-z0-9_\-]+)", s)
    if m: return "r:" + m.group(1)
    return "x:" + s[:60]

def _extract_links_from_text(txt):
    out = []
    if not txt: return out
    for m in re.finditer(r'(?:https?://)?rubika\.ir/joing/([A-Za-z0-9_\-]+)', txt, re.I):
        out.append(f"https://rubika.ir/joing/{m.group(1)}")
    for m in re.finditer(r'(?:https?://)?rubika\.ir/([A-Za-z][A-Za-z0-9_\-]{4,40})', txt, re.I):
        u = m.group(1)
        if u.lower() in ("joing", "joinchat"): continue
        out.append("@" + u)
    for m in re.finditer(r'(?<![A-Za-z0-9_@])@([A-Za-z][A-Za-z0-9_]{4,40})', txt):
        out.append("@" + m.group(1))
    seen = set(); res = []
    for lk in out:
        if lk in seen: continue
        seen.add(lk); res.append(lk)
    return res

def _extract_msg_texts(m):
    parts = []
    for field in ("text", "caption", "file_name", "title", "description"):
        v = _extract_field(m, field)
        if isinstance(v, str) and v: parts.append(v)
    fi = _extract_field(m, "file_inline")
    if fi is not None:
        for field in ("file_name", "title", "description", "remote_url"):
            v = _extract_field(fi, field)
            if isinstance(v, str) and v: parts.append(v)
    return " ".join(parts)

def _substitute(pattern, ctx):
    if not pattern: return ""
    s = str(pattern)
    for k, v in ctx.items(): s = s.replace("{" + k + "}", str(v))
    return s

def _build_ctx():
    return {"n": int(time.time()) % 100000,
            "rnd": str(random.randint(100000, 999999)),
            "date": time.strftime("%Y%m%d"),
            "time": time.strftime("%H%M%S")}

def _detect_kind_from_path(path):
    ext = os.path.splitext(path)[1].lower()
    mime, _ = mimetypes.guess_type(path)
    mime = (mime or "").lower()
    if ext in (".jpg",".jpeg",".png",".webp",".bmp",".heic",".heif") or mime.startswith("image/"):
        return "Image"
    if ext in (".mp4",".mov",".avi",".mkv",".webm",".flv",".3gp",".m4v") or mime.startswith("video/"):
        return "Video"
    if ext in (".mp3",".m4a",".wav",".flac",".aac",".opus") or mime.startswith("audio/"):
        if ext in (".ogg",".oga",".opus"): return "Voice"
        return "Music"
    return "File"

def _extract_link_from_response(r):
    if r is None: return None
    if isinstance(r, dict):
        for k in ("join_link", "link", "url", "invite_link", "invite", "joinLink"):
            v = r.get(k)
            if isinstance(v, str) and v.startswith("http"): return v
        for k in ("data", "result", "chat", "response", "channel", "invite"):
            nested = r.get(k)
            if isinstance(nested, (dict, list)):
                link = _extract_link_from_response(nested)
                if link: return link
    if isinstance(r, list):
        for item in r:
            link = _extract_link_from_response(item)
            if link: return link
    try:
        s = str(r)
        m = re.search(r'https?://[^\s"\'<>]+', s)
        if m: return m.group(0)
    except Exception: pass
    return None

# ═══════════════ PATHS ═══════════════
ACC_FILE = os.path.join(RUBIKA_DIR, "accounts.json")
CFG_FILE = os.path.join(RUBIKA_DIR, "config.json")
ERRORS_FILE = os.path.join(RUBIKA_DIR, "errors.json")
OPS_FILE = os.path.join(RUBIKA_DIR, "ops.json")
TEMPLATES_FILE = os.path.join(RUBIKA_DIR, "templates.json")
SEEN_FILE = os.path.join(RUBIKA_DIR, "seen_links.json")
BANNED_FILE = os.path.join(RUBIKA_DIR, "banned_groups.json")
LDPROG_FILE = os.path.join(RUBIKA_DIR, "linkdoni_progress.json")
PV_ITEMS_FILE = os.path.join(RUBIKA_DIR, "pv_items.json")
PV_REPORT_FILE = os.path.join(RUBIKA_DIR, "pv_report.json")
PV_COUNTS_FILE = os.path.join(RUBIKA_DIR, "pv_counts.json")
PV_WM_FILE = os.path.join(RUBIKA_DIR, "pv_wm.json")
PV_ACCOUNT_FILE = os.path.join(RUBIKA_DIR, "pv_per_account.json")
LINK_DONIES_FILE = os.path.join(RUBIKA_DIR, "linkdonies.json")

_SEEN_CACHE = {}; _BANNED_CACHE = {}; _LDPROG_CACHE = {}
_PV_WM = None; _PV_WM_DIRTY = False

def _load_seen(aid):
    if not aid: return set()
    if aid in _SEEN_CACHE: return _SEEN_CACHE[aid]
    all_d = _load(SEEN_FILE, {})
    if not isinstance(all_d, dict): all_d = {}
    acc = all_d.get(aid) or {}
    _SEEN_CACHE[aid] = set(acc.keys()); return _SEEN_CACHE[aid]
def _mark_seen(aid, h):
    if not aid or not h: return
    seen = _load_seen(aid)
    if h in seen: return
    seen.add(h)
    try:
        all_d = _load(SEEN_FILE, {})
        if not isinstance(all_d, dict): all_d = {}
        acc = all_d.setdefault(aid, {}); acc[h] = 1
        if len(acc) > 50000:
            all_d[aid] = dict(list(acc.items())[-40000:])
            _SEEN_CACHE[aid] = set(all_d[aid].keys())
        _save(SEEN_FILE, all_d)
    except Exception: pass
def _is_seen(aid, h): return bool(aid and h and h in _load_seen(aid))
def _clear_seen(aid=None):
    if aid:
        _SEEN_CACHE.pop(aid, None)
        try:
            all_d = _load(SEEN_FILE, {})
            if isinstance(all_d, dict): all_d.pop(aid, None); _save(SEEN_FILE, all_d)
        except Exception: pass
    else:
        _SEEN_CACHE.clear()
        try: _save(SEEN_FILE, {})
        except Exception: pass
def _seen_count(aid): return len(_load_seen(aid))

def _load_banned(aid):
    if not aid: return {}
    if aid in _BANNED_CACHE: return _BANNED_CACHE[aid]
    all_d = _load(BANNED_FILE, {})
    if not isinstance(all_d, dict): all_d = {}
    acc = all_d.get(aid) or {}
    if not isinstance(acc, dict): acc = {}
    _BANNED_CACHE[aid] = acc; return acc
def _mark_banned(aid, h, reason=""):
    if not aid or not h: return
    try:
        all_d = _load(BANNED_FILE, {})
        if not isinstance(all_d, dict): all_d = {}
        acc = all_d.setdefault(aid, {})
        acc[h] = {"reason": str(reason)[:120], "ts": int(time.time())}
        _BANNED_CACHE[aid] = acc; _save(BANNED_FILE, all_d)
    except Exception: pass
def _is_banned(aid, h): return bool(aid and h and h in _load_banned(aid))
def _clear_banned(aid=None):
    if aid:
        _BANNED_CACHE.pop(aid, None)
        try:
            all_d = _load(BANNED_FILE, {})
            if isinstance(all_d, dict): all_d.pop(aid, None); _save(BANNED_FILE, all_d)
        except Exception: pass
    else:
        _BANNED_CACHE.clear()
        try: _save(BANNED_FILE, {})
        except Exception: pass
def _banned_count(aid): return len(_load_banned(aid))

def _load_ldprog(aid):
    if not aid: return {}
    if aid in _LDPROG_CACHE: return _LDPROG_CACHE[aid]
    all_d = _load(LDPROG_FILE, {})
    if not isinstance(all_d, dict): all_d = {}
    acc = all_d.get(aid) or {}
    if not isinstance(acc, dict): acc = {}
    _LDPROG_CACHE[aid] = acc; return acc
def _get_ld_last(aid, url):
    try: return int(_load_ldprog(aid).get(url, 0))
    except Exception: return 0
def _set_ld_last(aid, url, max_id):
    if not aid or not url: return
    try:
        all_d = _load(LDPROG_FILE, {})
        if not isinstance(all_d, dict): all_d = {}
        acc = all_d.setdefault(aid, {})
        old = int(acc.get(url, 0))
        if int(max_id) > old:
            acc[url] = int(max_id); _LDPROG_CACHE[aid] = acc; _save(LDPROG_FILE, all_d)
    except Exception: pass
def _reset_ld_progress(aid=None):
    if aid:
        _LDPROG_CACHE.pop(aid, None)
        try:
            all_d = _load(LDPROG_FILE, {})
            if isinstance(all_d, dict): all_d.pop(aid, None); _save(LDPROG_FILE, all_d)
        except Exception: pass
    else:
        _LDPROG_CACHE.clear()
        try: _save(LDPROG_FILE, {})
        except Exception: pass

def _pv_count(aid, uid):
    d = _load(PV_COUNTS_FILE, {}); return int((d.get(aid) or {}).get(str(uid), 0))
def _pv_count_add(aid, uid, delta):
    d = _load(PV_COUNTS_FILE, {}); acc = d.setdefault(aid, {})
    acc[str(uid)] = max(0, int(acc.get(str(uid), 0)) + delta); _save(PV_COUNTS_FILE, d)
def _pv_limit_reached(aid, uid, cfg):
    mx = int(cfg.get("max_replies", 1) or 0)
    return mx > 0 and _pv_count(aid, uid) >= mx
def _wm_load():
    global _PV_WM
    if _PV_WM is None:
        d = _load(PV_WM_FILE, {}); _PV_WM = d if isinstance(d, dict) else {}
    return _PV_WM
def _wm_get(aid, uid):
    try: return int((_wm_load().get(aid) or {}).get(str(uid), 0))
    except Exception: return 0
def _wm_set(aid, uid, mid):
    global _PV_WM_DIRTY
    w = _wm_load().setdefault(aid, {})
    if int(mid) > int(w.get(str(uid), 0)):
        w[str(uid)] = int(mid); _PV_WM_DIRTY = True
def _wm_flush():
    global _PV_WM_DIRTY
    if _PV_WM_DIRTY:
        try: _save(PV_WM_FILE, _wm_load())
        except Exception: pass
        _PV_WM_DIRTY = False

DEFAULT_PV_ITEMS = {
    "enabled": False, "delay_seconds": 0, "reply_once": True, "max_replies": 1,
    "notify": True, "notify_on_receive": True, "notify_on_reply": True,
    "poll_seconds": 3, "items": [{"kind": "text", "text": "سلام 👋"}]
}
def _load_pv_items():
    d = _load(PV_ITEMS_FILE, DEFAULT_PV_ITEMS)
    if not isinstance(d, dict): return dict(DEFAULT_PV_ITEMS)
    for k, v in DEFAULT_PV_ITEMS.items():
        if k not in d: d[k] = v
    return d
def _load_pv_account(aid):
    base = _load_pv_items()
    if not aid: return base
    per = _load(PV_ACCOUNT_FILE, {})
    if not isinstance(per, dict): per = {}
    acc_cfg = per.get(aid) or {}
    if not isinstance(acc_cfg, dict): acc_cfg = {}
    merged = {**base, **acc_cfg}
    if not isinstance(merged.get("items"), list) or not merged.get("items"):
        merged["items"] = base.get("items") or []
    return merged
def _save_pv_account(aid, cfg):
    if not aid: return
    per = _load(PV_ACCOUNT_FILE, {})
    if not isinstance(per, dict): per = {}
    per[aid] = {k: cfg.get(k) for k in ("enabled","delay_seconds","reply_once",
        "max_replies","notify","notify_on_receive","notify_on_reply","poll_seconds","items")}
    _save(PV_ACCOUNT_FILE, per)
def _has_pv_account(aid):
    per = _load(PV_ACCOUNT_FILE, {})
    return isinstance(per, dict) and aid in per
def _delete_pv_account(aid):
    per = _load(PV_ACCOUNT_FILE, {})
    if isinstance(per, dict): per.pop(aid, None); _save(PV_ACCOUNT_FILE, per)
def _load_pv_report():
    d = _load(PV_REPORT_FILE, {}); return d if isinstance(d, dict) else {}
def _save_pv_report(d): _save(PV_REPORT_FILE, d)
def _record_pv_visit(aid, uid, info=None):
    rep = _load_pv_report(); acc = rep.setdefault(aid, {})
    uid = str(uid); now = int(time.time())
    if uid in acc:
        acc[uid]["last_seen"] = now
        acc[uid]["count"] = acc[uid].get("count", 1) + 1
        if info:
            for k, v in info.items():
                if v is not None: acc[uid][k] = v
    else:
        e = {"first_seen": now, "last_seen": now, "count": 1,
             "replied": False, "reply_ok": False, "error": None, "blocked": False}
        if info: e.update({k: v for k, v in info.items() if v is not None})
        acc[uid] = e
    _save_pv_report(rep)
def _record_pv_reply(aid, uid, ok, err=None):
    rep = _load_pv_report(); acc = rep.setdefault(aid, {}); uid = str(uid)
    if uid not in acc:
        acc[uid] = {"first_seen": int(time.time()), "last_seen": int(time.time()),
                    "count": 1, "replied": False, "reply_ok": False}
    acc[uid]["replied"] = True; acc[uid]["replied_at"] = int(time.time())
    acc[uid]["reply_ok"] = bool(ok)
    if err:
        acc[uid]["error"] = str(err)[:200]
        acc[uid]["blocked"] = "FORBIDDEN" in str(err).upper()
    else: acc[uid]["error"] = None; acc[uid]["blocked"] = False
    _save_pv_report(rep)

DEFAULT_LINK_DONIES = ["@Padeshahe15", "@linkdony_rubikas"]
def load_link_donies():
    d = _load(LINK_DONIES_FILE, None)
    if not isinstance(d, list) or not d:
        _save(LINK_DONIES_FILE, DEFAULT_LINK_DONIES); return list(DEFAULT_LINK_DONIES)
    return d
def save_link_donies(lst): _save(LINK_DONIES_FILE, lst)
def add_link_doni(url):
    url = url.strip()
    if not url: return False
    lst = load_link_donies()
    if url in lst: return False
    lst.append(url); save_link_donies(lst); return True
def remove_link_doni(idx):
    lst = load_link_donies()
    if idx < 0 or idx >= len(lst): return False
    lst.pop(idx); save_link_donies(lst); return True

DEFAULT_CFG = {
    "listener": 1, "auto_join_linkdoni": 1,
    "wave_size": 50, "extract_limit": 300, "join_delay": 0.5,
    "deep_scan_pages": 30, "deep_scan_page_size": 25,
    "wait_for_links_sec": 90, "max_wait_rounds": 20,
}

def _load_errors():
    d = _load(ERRORS_FILE, []); return d if isinstance(d, list) else []
def add_error(source, error, target=None, account=None):
    err_up = str(error).upper()
    if "CHANNEL_PRIVATE" in err_up: return
    errs = _load_errors()
    errs.append({"time": int(time.time()), "source": str(source)[:40], "error": str(error)[:300],
                 "target": (str(target)[:120] if target is not None else None),
                 "account": (str(account)[:60] if account is not None else None)})
    if len(errs) > 500: errs = errs[-500:]
    try: _save(ERRORS_FILE, errs)
    except Exception: pass
def clear_errors():
    try: _save(ERRORS_FILE, [])
    except Exception: pass

def list_accounts(): return _load(ACC_FILE, {})
def save_accounts(a): _save(ACC_FILE, a)
def get_account(aid): return list_accounts().get(aid)

def add_account(aid, phone, name, session_name=None, user_guid=None, alias=None, profile=None):
    accounts = list_accounts()
    accounts[aid] = {"phone": phone, "name": name, "user_guid": user_guid,
                     "alias": alias or "", "profile": profile or {},
                     "session_name": session_name or os.path.join(SESSIONS_DIR, aid),
                     "created": int(time.time()), "channels": []}
    save_accounts(accounts); return accounts[aid]

def update_account(aid, **kw):
    accounts = list_accounts()
    if aid in accounts:
        accounts[aid].update(kw); save_accounts(accounts)

def remove_account(aid):
    accounts = list_accounts(); accounts.pop(aid, None); save_accounts(accounts)
    _STATS_CACHE.pop(aid, None)
    try: _delete_pv_account(aid)
    except Exception: pass
    try: _clear_seen(aid); _clear_banned(aid); _reset_ld_progress(aid)
    except Exception: pass
    base = os.path.join(SESSIONS_DIR, aid)
    for ext in (".rp", ".session", ".json"):
        p = base + ext
        if os.path.exists(p):
            try: os.remove(p)
            except Exception: pass
def get_stored_channels(aid):
    a = get_account(aid); return list(a.get("channels") or []) if a else []
def add_channel_to_storage(aid, ch_data):
    accounts = list_accounts()
    if aid not in accounts: return
    chans = accounts[aid].setdefault("channels", [])
    guid = ch_data.get("guid")
    if guid:
        for c in chans:
            if c.get("guid") == guid: c.update(ch_data); save_accounts(accounts); return
    chans.append(ch_data); save_accounts(accounts)
def remove_channel_from_storage(aid, idx):
    accounts = list_accounts()
    if aid not in accounts: return None
    chans = accounts[aid].get("channels") or []
    if idx < 0 or idx >= len(chans): return None
    removed = chans.pop(idx); accounts[aid]["channels"] = chans
    save_accounts(accounts); return removed
def update_channel_field(aid, idx, key, value):
    accounts = list_accounts()
    if aid not in accounts: return
    chans = accounts[aid].get("channels") or []
    if 0 <= idx < len(chans): chans[idx][key] = value; save_accounts(accounts)

_STATS_CACHE = {}
_STATS_CACHE_TTL = 300

# ═══════════════ OPS ═══════════════
def _load_ops():
    d = _load(OPS_FILE, []); return d if isinstance(d, list) else []
def _save_ops(ops): _save(OPS_FILE, ops)
def _get_op(oid):
    for o in _load_ops():
        if o.get("id") == oid: return o
    return None
def _save_op(op):
    ops = _load_ops()
    for i, o in enumerate(ops):
        if o.get("id") == op["id"]: ops[i] = op; break
    else: ops.append(op)
    _save_ops(ops)

def _get_op_lock(oid):
    key = "oplock_" + oid
    if key not in STATE: STATE[key] = asyncio.Lock()
    return STATE[key]

def _op_stats(op):
    p = op.get("progress") or {}
    t = op.get("type")
    if t in ("joinlef","lefter"):
        return {"done": p.get("joined", 0), "failed": p.get("failed", 0), "pending": 0,
                "in_progress": 1 if op.get("status") == "running" else 0,
                "total": op.get("max_join", 0) or (p.get("joined", 0) + p.get("failed", 0)),
                "already": p.get("already", 0), "sent": p.get("sent", 0),
                "left": p.get("left", 0), "wave": p.get("wave", 0),
                "tried": p.get("tried", 0),
                "skipped_seen": p.get("skipped_seen", 0),
                "skipped_banned": p.get("skipped_banned", 0),
                "rejected": p.get("rejected", 0), "round": p.get("round", 0),
                "extracted": p.get("extracted", 0), "lds_done": p.get("lds_done", 0)}
    if t == "autotar":
        return {"done": p.get("joined", 0), "failed": p.get("failed", 0),
                "pending": p.get("pending", 0), "in_progress": 1 if op.get("status") == "running" else 0,
                "total": p.get("total", 0), "already": p.get("already", 0),
                "sent": p.get("sent", 0), "left": p.get("left", 0),
                "wave": p.get("wave", 0), "tried": p.get("tried", 0),
                "skipped_seen": p.get("skipped_seen", 0),
                "skipped_banned": p.get("skipped_banned", 0),
                "rejected": p.get("rejected", 0), "round": p.get("round", 0),
                "extracted": p.get("extracted", 0), "lds_done": p.get("lds_done", 0)}
    return {"done": p.get("sent", 0), "failed": p.get("failed", 0),
            "pending": p.get("pending", 0), "in_progress": p.get("in_progress", 0),
            "total": p.get("total", 0), "blocked": p.get("blocked", 0),
            "round": p.get("round", 0)}

def _op_effective_status(op):
    st = op.get("status", "draft")
    if op.get("type") in ("joinlef","lefter","autotar"):
        if st in ("done","failed","cancelled","paused"): return st
        return "running"
    return st

def _op_short_title(op, n=32):
    t = op.get("type")
    if t == "joinlef": return f"{T('op_joiner')} ({op.get('max_join', 0)})"
    if t == "lefter": return f"{T('op_lefter')} ({op.get('leave_mode', '?')})"
    if t == "autotar":
        tpl = get_template(op.get("template_id"))
        return f"{T('op_autotar')}: {short(tpl.get('name', '?'), 20)}" if tpl else T("op_autotar")
    p = op.get("payload") or {}
    if p.get("text"): return f"{T('op_send')} «{p.get('text')[:n]}»"
    return T("op_send")

def _op_status_label(st):
    return T("op_" + st) if ("op_" + st) in _TR else st

def _op_progress_bar(op):
    s = _op_stats(op); done = s["done"] + s["failed"]; tot = s["total"] or 0
    if tot == 0: return "▱" * 16 + " 0%", 0
    pct = int(done * 100 / tot); fill = int(done * 16 / tot)
    if fill > 16: fill = 16
    return "▰" * fill + "▱" * (16 - fill) + f" {pct}%", pct

# ═══════════════ TEMPLATES ═══════════════
def list_templates():
    d = _load(TEMPLATES_FILE, {}); return d if isinstance(d, dict) else {}
def save_templates(t): _save(TEMPLATES_FILE, t)
def get_template(tid): return list_templates().get(tid)
def add_template(tpl):
    ts = list_templates(); ts[tpl["id"]] = tpl; save_templates(ts)
def delete_template(tid):
    ts = list_templates(); ts.pop(tid, None); save_templates(ts)
def update_template(tid, section, field, value):
    ts = list_templates(); t = ts.get(tid)
    if not t: return
    if section == "meta": t[field] = value
    elif section == "sender_edit": t.setdefault("sender", {})[field] = value
    elif section == "pv": t.setdefault("pv", {})[field] = value
    else: t.setdefault(section, {})[field] = value
    save_templates(ts)
def new_template(name="قالب جدید"):
    return {
        "id": "tp_" + secrets.token_hex(4), "name": name, "created": int(time.time()),
        "channel": {"type":"private","title":"","username":"","about":"","photo_file":""},
        "profile": {"first_name":"","last_name":"","username":"","bio":"","photo_file":""},
        "joiner": {"max_join":0,"speed":"fast","groups_only":True},
        "sender": {"text":"","target":"groups","mode":"send_only",
            "max_send":0,"delay":1.5,
            "edit_delay_enabled":False,"edit_delay_seconds":3.0,
            "edit_delay_random":False,"edit_delay_min":2.0,"edit_delay_max":6.0,
            "placeholder_text":"سلام","placeholder_random":False,
            "placeholder_list":"سلام,درود,hi,salam",
            "multi_step_edit":False,"multi_step_middle":"Hi",
            "send_to_existing":True,
            "attach_file":"","attach_caption":"",
            "infinite_loop":False,"loop_delay":3.0,"rescan_targets":True},
        "pv": {"enabled":False,"delay_seconds":0,"reply_once":True,"max_replies":1,
               "notify":True,"notify_on_receive":True,"notify_on_reply":True,
               "poll_seconds":3,"items":[{"kind":"text","text":"سلام 👋"}],
               "apply_to_accounts":True},
        "lefter": {"leave_mode":"closed"},
    }

JL_SPEEDS = [("ultra", "jl_speed_ultra", 0.3),
             ("fast",  "jl_speed_fast",  1.0),
             ("normal","jl_speed_normal",3.0),
             ("slow",  "jl_speed_safe",  8.0)]

# ═══════════════ RUBIKA PLATFORM ═══════════════
def _extract_field(obj, *names, default=None):
    if obj is None: return default
    if isinstance(obj, dict):
        for n in names:
            if n in obj and obj[n] is not None: return obj[n]
        return default
    for n in names:
        try:
            v = getattr(obj, n, None)
            if v is not None: return v
        except Exception: pass
    if hasattr(obj, "model_dump"):
        try:
            d = obj.model_dump()
            if isinstance(d, dict):
                for n in names:
                    if n in d and d[n] is not None: return d[n]
        except Exception: pass
    _dict_fn = getattr(obj, "dict", None)
    if callable(_dict_fn):
        try:
            d = _dict_fn()
            if isinstance(d, dict):
                for n in names:
                    if n in d and d[n] is not None: return d[n]
        except Exception: pass
    if hasattr(obj, "to_dict"):
        try:
            d = obj.to_dict()
            if isinstance(d, dict):
                for n in names:
                    if n in d and d[n] is not None: return d[n]
        except Exception: pass
    try:
        d = obj.__dict__
        for n in names:
            if n in d and d[n] is not None: return d[n]
    except Exception: pass
    return default

def _chat_info(chat):
    if chat is None: return None
    abs_obj = _extract_field(chat, "abs_object", "absObject")
    src = abs_obj if abs_obj is not None else chat
    guid = (_extract_field(src, "object_guid", "objectGuid", "chat_guid", "guid", "id") or
            _extract_field(chat, "object_guid", "guid", "id"))
    if not guid: return None
    is_group = _extract_field(src, "is_group", "isGroup")
    is_channel = _extract_field(src, "is_channel", "isChannel")
    is_private = _extract_field(src, "is_private", "isPrivate", "is_user", "isUser")
    if is_group is True: typ = "Group"
    elif is_channel is True: typ = "Channel"
    elif is_private is True: typ = "User"
    else:
        t = _extract_field(src, "type")
        if t in ("Group", "Channel", "User"): typ = t
        elif isinstance(guid, str) and guid.startswith("g"): typ = "Group"
        elif isinstance(guid, str) and guid.startswith("c"): typ = "Channel"
        elif isinstance(guid, str) and guid.startswith("u"): typ = "User"
        else: typ = "Unknown"
    title = (_extract_field(src, "title", "first_name", "firstName", "name", "display_name") or
             _extract_field(chat, "title", "first_name", "name") or "")
    username = _extract_field(src, "username") or ""
    last_msg = (_extract_field(src, "last_message", "lastMessage") or
                _extract_field(chat, "last_message", "lastMessage"))
    return {"guid": str(guid), "type": typ, "title": str(title),
            "username": str(username), "last_message": last_msg}

_ACCOUNT_LOCKS = {}
_ACCOUNT_LOCKS_GUARD = threading.Lock()
def _get_account_lock(aid):
    if not aid: return None
    with _ACCOUNT_LOCKS_GUARD:
        if aid not in _ACCOUNT_LOCKS:
            _ACCOUNT_LOCKS[aid] = asyncio.Lock()
        return _ACCOUNT_LOCKS[aid]

class SafeRubikaClient(RubikaClient if RUBIKA_OK else object):
    def __init__(self, *args, **kwargs):
        self._aid = kwargs.pop("_aid", None)
        self._lock = _get_account_lock(self._aid) if self._aid else None
        name = kwargs.get("name") or (args[0] if args else "")
        if not name:
            name = os.path.join(SESSIONS_DIR, f"session_{self._aid or secrets.token_hex(4)}")
            if args: args = (name,) + args[1:]
            else: kwargs["name"] = name
        super().__init__(*args, **kwargs)
    async def __aenter__(self):
        if self._lock:
            try:
                await asyncio.wait_for(self._lock.acquire(), timeout=8)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._lock = None
        try:
            await self.start(); return self
        except Exception:
            if self._lock:
                try: self._lock.release()
                except Exception: pass
            raise
    async def start(self, phone_number=None):
        try:
            await super().start(phone_number=phone_number)
        except Exception as e:
            raise RuntimeError(f"NO_SESSION: {e}") from e
        try:
            me = await self.get_me()
            self.guid = _extract_field(me, "user_guid")
            if not self.guid:
                u = _extract_field(me, "user")
                self.guid = _extract_field(u, "user_guid") if u is not None else None
        except Exception as e:
            raise RuntimeError(f"NO_SESSION: get_me failed — {e}")
    async def __aexit__(self, *args, **kwargs):
        try: return await super().__aexit__(*args, **kwargs)
        finally:
            if self._lock:
                try: self._lock.release()
                except Exception: pass

def _filter_kwargs(fn, kw):
    import inspect
    try:
        sig = inspect.signature(fn)
    except Exception:
        return kw
    for p in sig.parameters.values():
        if p.kind == inspect.Parameter.VAR_KEYWORD: return kw
    valid = set(sig.parameters.keys())
    return {k: v for k, v in kw.items() if k in valid}

async def _try_methods(client, method_names, kw_variants):
    errors = []
    for name in method_names:
        fn = getattr(client, name, None)
        if not fn: continue
        for base in kw_variants:
            kw = _filter_kwargs(fn, base)
            if base and not kw:
                continue
            try:
                r = fn(**kw)
                if asyncio.iscoroutine(r): r = await r
                return True, f"{name}({list(kw.keys())})", r
            except Exception as e:
                errors.append(f"{name}: {_fmt_error(e)}")
    return False, " | ".join(errors[:4]) or "no method", None

# ═══════════════ RUBIKA OPERATIONS ═══════════════
async def rb_send_text(client, target, text):
    errors = []
    for mname in ("send_message", "sendMessage"):
        fn = getattr(client, mname, None)
        if not fn: continue
        for kw in ({"object_guid": target, "text": text},
                   {"chat_id": target, "text": text},
                   {"object_guid": target, "message": text}):
            try:
                kw2 = _filter_kwargs(fn, kw)
                if not kw2: continue
                r = fn(**kw2)
                if asyncio.iscoroutine(r): r = await r
                status = _extract_field(r, "status")
                if status and str(status).upper() not in ("OK", ""):
                    errors.append(f"{mname}: {status}"); continue
                return True, r
            except Exception as e:
                err = _fmt_error(e)
                if "INVALID_AUTH" in err.upper():
                    return False, "AUTH_DEAD: session expired or invalid — please re-login"
                errors.append(err)
    return False, " | ".join(errors[-3:]) or "no_method"

async def rb_send_file(client, target, file_path, caption="", kind="File"):
    if not os.path.exists(file_path): return False, "file_not_found"
    if not kind or kind == "File":
        kind = _detect_kind_from_path(file_path)
    cap = (caption or "").strip() or None
    errors = []
    method_map = {"Image": ("send_photo", "photo"), "Video": ("send_video", "video"),
                  "Music": ("send_music", "music"), "Voice": ("send_voice", "voice"),
                  "File": ("send_document", "document")}
    fallbacks = {"Image": ["send_photo", "send_image", "send_file", "send_document"],
                 "Video": ["send_video", "send_file", "send_document"],
                 "Music": ["send_music", "send_audio", "send_file"],
                 "Voice": ["send_voice", "send_audio", "send_file"],
                 "File": ["send_document", "send_file"]}
    for method_name in fallbacks.get(kind, ["send_document"]):
        fn = getattr(client, method_name, None)
        if not fn: continue
        primary = method_map.get(kind, ("", "file"))[0] == method_name
        file_param = method_map.get(kind, ("", "file"))[1] if primary else "file"
        kw = {"object_guid": target, file_param: file_path}
        if cap: kw["caption"] = cap
        for k in (kw, {k2: v for k2, v in kw.items() if k2 != "caption"}):
            try:
                kw2 = _filter_kwargs(fn, k)
                if not kw2: continue
                r = fn(**kw2)
                if asyncio.iscoroutine(r): r = await r
                status = _extract_field(r, "status") if r else None
                if not status or str(status).upper() == "OK":
                    return True, f"{method_name}_ok"
                errors.append(f"{method_name}: {status}")
            except TypeError: continue
            except Exception as e:
                err = str(e)[:100]; errors.append(f"{method_name}: {err}")
                if "TOO_REQUESTS" in err.upper() or "FLOOD" in err.upper():
                    return False, "RATE_LIMIT"
    return False, " | ".join(errors[-3:]) or "all_failed"

async def rb_leave_chat(client, guid):
    try:
        r = client.leave_chat(guid)
        if asyncio.iscoroutine(r): r = await r
        return True, None
    except Exception as e:
        err = _fmt_error(e)
        if "NOT_PARTICIPANT" in err.upper(): return True, "already_left"
        return False, err

async def rb_get_chats(client):
    try:
        r = client.get_chats()
        if asyncio.iscoroutine(r): r = await r
    except Exception as e:
        flog(f"[get_chats] error: {_fmt_error(e)}")
        return []
    chats = _extract_field(r, "chats")
    if isinstance(chats, list): return chats
    data = _extract_field(r, "data")
    if data is not None:
        chats = _extract_field(data, "chats")
        if isinstance(chats, list): return chats
    return []

async def rb_get_messages(client, guid, limit=25, max_id=None):
    if max_id is None or max_id == "": max_id = "0"
    mid_str = str(max_id)
    attempts = [
        lambda: client.get_messages(guid, limit=limit, middle_message_id=mid_str),
        lambda: client.get_messages(guid, limit=limit, max_id=mid_str),
        lambda: client.get_messages_interval(guid, mid_str),
        lambda: client.get_messages_interval(guid, middle_message_id=mid_str),
        lambda: client.get_messages(guid, mid_str, limit),
        lambda: client.get_messages(object_guid=guid, limit=limit, middle_message_id=mid_str),
    ]
    for fn in attempts:
        try:
            r = fn()
            if asyncio.iscoroutine(r): r = await r
            msgs = _extract_field(r, "messages")
            if isinstance(msgs, list) and msgs: return msgs
        except Exception: continue
    return []

async def rb_verify_member(client, guid):
    try:
        for c in await rb_get_chats(client):
            ci = _chat_info(c)
            if ci and ci["guid"] == guid:
                return True
    except Exception: pass
    return False

async def rb_resolve(client, ident):
    ident = (ident or "").strip()
    if not ident: return None
    if "/joing/" in ident:
        h = ident.rstrip("/").split("/")[-1]
        for mname in ("group_preview_by_join_link", "channel_preview_by_join_link"):
            fn = getattr(client, mname, None)
            if not fn: continue
            try:
                r = fn(h)
                if asyncio.iscoroutine(r): r = await r
                g = _extract_field(r, "object_guid", "group_guid", "channel_guid", "guid")
                if g: return g
                d = _extract_field(r, "data")
                if d is not None:
                    g = _extract_field(d, "object_guid", "group_guid", "channel_guid", "guid")
                    if g: return g
            except Exception: pass
        return None
    uname = ident.lstrip("@").split("/")[-1]
    for mname in ("get_channel_info", "getChannelInfo",
                  "get_group_info", "getGroupInfo",
                  "get_info", "getInfo"):
        fn = getattr(client, mname, None)
        if not fn: continue
        try:
            r = fn(username=uname)
            if asyncio.iscoroutine(r): r = await r
            for k in ("object_guid", "group_guid", "channel_guid", "guid"):
                g = _extract_field(r, k)
                if g: return g
            d = _extract_field(r, "data")
            if d is not None:
                for k in ("object_guid", "group_guid", "channel_guid", "guid"):
                    g = _extract_field(d, k)
                    if g: return g
        except Exception: pass
    try:
        for c in await rb_get_chats(client):
            ci = _chat_info(c)
            if ci and ci["username"].lower() == uname.lower():
                return ci["guid"]
    except Exception: pass
    return None

async def rb_is_group(client, ident):
    ident = (ident or "").strip()
    if not ident: return True
    if "/joing/" in ident:
        h = ident.rstrip("/").split("/")[-1]
        fn = getattr(client, "group_preview_by_join_link", None)
        if fn:
            try:
                r = fn(h)
                if asyncio.iscoroutine(r): r = await r
                status = _extract_field(r, "status")
                if status and str(status).upper() not in ("OK", ""): return True
                if _extract_field(r, "object_guid", "group_guid", "guid"): return True
                d = _extract_field(r, "data")
                if d is not None and _extract_field(d, "group") is not None: return True
                return True
            except Exception: return True
        return True
    if ident.startswith("@"):
        uname = ident[1:]
        for mname in ("get_group_info", "getGroupInfo"):
            fn = getattr(client, mname, None)
            if not fn: continue
            try:
                r = fn(username=uname)
                if asyncio.iscoroutine(r): r = await r
                d = _extract_field(r, "data") or r
                if _extract_field(d, "group") is not None: return True
            except Exception: pass
        return True
    return True

def _join_status_tag(r):
    if r is None: return True, "joined", None
    status = _extract_field(r, "status")
    status_det = _extract_field(r, "status_det") or ""
    msg = _extract_field(r, "client_show_message") or ""
    full = f"{status or ''} {status_det} {msg}".upper()
    if not status or str(status).upper() == "OK":
        return True, "joined", None
    if any(k in full for k in ("ALREADY", "MEMBER", "عضو هست", "JOINED_BEFORE")):
        return True, "already", None
    return False, "failed", f"{status}: {str(status_det or msg)[:150]}"

async def rb_join(client, ident, guid=None):
    s = (ident or "").strip()
    if not s: return False, "empty", "failed"
    errors = []
    def _already(e):
        em = _fmt_error(e).upper()
        return any(k in em for k in ("ALREADY", "MEMBER", "عضو"))

    if "rubika.ir" in s:
        fn = getattr(client, "join_group_by_link", None)
        if fn:
            try:
                r = fn(link=s)
                if asyncio.iscoroutine(r): r = await r
                ok, tag, err = _join_status_tag(r)
                if ok: return True, None, tag
                if any(k in str(err or "").upper() for k in ("ALREADY","MEMBER")):
                    return True, None, "already"
                errors.append(f"jbl: {err}")
            except Exception as e:
                if _already(e): return True, None, "already"
                errors.append(f"jbl: {str(e)[:80]}")

    fn2 = getattr(client, "join_chat", None)
    if fn2:
        for kw in ({"guid_or_link": s}, {"link": s}):
            try:
                r = fn2(**kw)
                if asyncio.iscoroutine(r): r = await r
                ok, tag, err = _join_status_tag(r)
                if ok: return True, None, tag
                errors.append(f"join_chat: {err}")
                break
            except TypeError: continue
            except Exception as e:
                if _already(e): return True, None, "already"
                errors.append(f"join_chat: {str(e)[:80]}")
                break
        else:
            try:
                r = fn2(s)
                if asyncio.iscoroutine(r): r = await r
                ok, tag, err = _join_status_tag(r)
                if ok: return True, None, tag
                errors.append(f"join_chat(pos): {err}")
            except Exception as e:
                if _already(e): return True, None, "already"
                errors.append(f"join_chat(pos): {str(e)[:80]}")

    if guid:
        fn3 = getattr(client, "join_group", None)
        if fn3:
            try:
                r = fn3(guid=guid)
                if asyncio.iscoroutine(r): r = await r
                ok, tag, err = _join_status_tag(r)
                if ok: return True, None, tag
                errors.append(f"join_group: {err}")
            except Exception as e:
                if _already(e): return True, None, "already"
                errors.append(f"join_group: {str(e)[:80]}")

    if any("TOO_REQUESTS" in str(e).upper() for e in errors):
        return False, "TOO_REQUESTS", "ratelimit"
    return False, " | ".join(errors[-3:]) if errors else "no_join_method", "failed"

async def rb_join_by_link(client, link):
    ok, err, tag = await rb_join(client, link, guid=None)
    if ok: return True, None, tag
    return False, err, "failed"

async def rb_join_by_username(client, username):
    ok, err, tag = await rb_join(client, "@" + username.lstrip("@"), guid=None)
    if ok: return True, None, tag
    return False, err, "failed"

async def rb_resolve_username(client, username):
    g = await rb_resolve(client, "@" + username.lstrip("@"))
    return (g, "ok") if g else (None, "not_found")

async def rb_create_channel(client, title, description=""):
    errors = []
    for mname in ("add_channel", "addChannel", "create_channel",
                  "createChannel", "new_channel", "newChannel"):
        fn = getattr(client, mname, None)
        if not fn: continue
        for kw in ({"title": title, "description": description or None},
                   {"title": title},
                   {"name": title, "description": description or None}):
            try:
                kw2 = _filter_kwargs(fn, {k: v for k, v in kw.items() if v is not None})
                if not kw2: continue
                r = fn(**kw2)
                if asyncio.iscoroutine(r): r = await r
                status = _extract_field(r, "status")
                if status and str(status).upper() not in ("OK", ""):
                    errors.append(f"{mname}: {status}"); continue
                for k in ("channel_guid", "object_guid", "chat_guid", "guid"):
                    v = _extract_field(r, k)
                    if v: return True, v, None
                data = _extract_field(r, "data")
                if data is not None:
                    for k in ("channel_guid", "object_guid", "chat_guid", "guid"):
                        v = _extract_field(data, k)
                        if v: return True, v, None
                return True, None, "no_guid"
            except TypeError: continue
            except Exception as e:
                errors.append(f"{mname}: {_fmt_error(e)}")
    return False, None, " | ".join(errors[-2:]) or "no_method"

async def rb_create_join_link(client, guid, attempts=3):
    last_err = None
    for attempt in range(attempts):
        for method_name in ("create_join_link", "createJoinLink",
                            "add_join_link", "addJoinLink", "get_join_link"):
            fn = getattr(client, method_name, None)
            if not fn: continue
            for kw in [{"object_guid": guid}, {"channel_guid": guid},
                       {"chat_id": guid}, {"guid": guid}]:
                try:
                    kw2 = _filter_kwargs(fn, kw)
                    if not kw2 and kw: continue
                    r = fn(**kw2)
                    if asyncio.iscoroutine(r): r = await r
                    link = _extract_link_from_response(r)
                    if link: return True, link
                    last_err = f"{method_name}: no link"
                except TypeError: continue
                except Exception as e: last_err = f"{method_name}: {str(e)[:80]}"
        if attempt < attempts - 1: await asyncio.sleep(1.5 + attempt)
    return False, last_err or "no_link_method_worked"

async def rb_set_channel_username(client, guid, uname):
    uname = (uname or "").lstrip("@").strip()
    if not uname: return False, "empty_username"
    errors = []
    fn = getattr(client, "update_channel_username", None)
    if fn:
        for kw in [{"channel_guid": guid, "username": uname},
                   {"object_guid": guid, "username": uname}]:
            try:
                kw2 = _filter_kwargs(fn, kw)
                if not kw2 and kw: continue
                r = fn(**kw2)
                if asyncio.iscoroutine(r): r = await r
                status = _extract_field(r, "status") if r else None
                if not status or str(status).upper() == "OK":
                    return True, "update_channel_username"
                errors.append(f"ucu: {status}")
            except TypeError: continue
            except Exception as e: errors.append(f"ucu: {str(e)[:60]}")
    return False, " | ".join(errors[:3]) or "no_method_worked"

async def rb_edit_channel(client, guid, **kwargs):
    ok, info, r = await _try_methods(client,
        ("edit_channel_info", "editChannelInfo", "edit_group_info", "editGroupInfo"),
        [{"channel_guid": guid, **kwargs}, {"object_guid": guid, **kwargs}])
    return ok, info

async def rb_upload_avatar(client, guid, image_path):
    if not os.path.exists(image_path): return False, "file_not_found"
    for mname in ("upload_avatar", "uploadAvatar", "set_avatar"):
        fn = getattr(client, mname, None)
        if not fn: continue
        try:
            r = fn(guid, image_path)
            if asyncio.iscoroutine(r): r = await r
            return True, "ok"
        except Exception:
            continue
    return False, "no_avatar_method"

async def rb_remove_channel(client, guid):
    ok, info, r = await _try_methods(client,
        ("remove_channel", "removeChannel", "delete_channel"),
        [{"channel_guid": guid}, {"object_guid": guid}])
    return ok, info

async def rb_update_profile(client, first_name=None, last_name=None, bio=None):
    kw = {}
    if first_name is not None: kw["first_name"] = first_name
    if last_name is not None: kw["last_name"] = last_name
    if bio is not None: kw["bio"] = bio
    if not kw: return False, "empty"
    ok, info, r = await _try_methods(client,
        ("update_profile", "updateProfile", "set_profile"), [kw])
    return ok, info

async def rb_update_username(client, username):
    uname = username.lstrip("@")
    ok, info, r = await _try_methods(client,
        ("update_username", "set_username", "updateUsername"),
        [{"username": uname}, {"username": "@" + uname}])
    return ok, info

async def rb_collect_targets(client, target, own_guids=None, groups_only=False):
    chats = await rb_get_chats(client)
    own_guids = own_guids or set()
    out = []
    try: me = await client.get_me()
    except Exception: me = None
    my_guid = _extract_field(me, "user_guid") if me is not None else None
    if not my_guid and me is not None:
        u = _extract_field(me, "user")
        my_guid = _extract_field(u, "user_guid") if u is not None else None
    for c in chats:
        ci = _chat_info(c)
        if not ci: continue
        if ci["guid"] == my_guid or ci["guid"] in own_guids: continue
        if ci["type"] == "User" and target in ("pv", "both"):
            out.append({"type": "pv", "target": ci["guid"], "name": ci["title"]})
        elif ci["type"] in ("Group", "Channel") and target in ("groups", "both"):
            if groups_only and ci["type"] == "Channel":
                ct = _extract_field(c, "channel_type", "channelType")
                if ct in ("Private", "Public"): continue
            out.append({"type": "groups", "target": ci["guid"], "name": ci["title"]})
    return out

async def rb_get_channel_info(client, guid):
    ok, info, r = await _try_methods(client,
        ("get_channel_info", "getChannelInfo", "get_info", "getInfo"),
        [{"channel_guid": guid}, {"object_guid": guid}])
    if ok and r is not None:
        d = {}
        for k in ("title", "username", "description", "members", "join_link", "object_guid", "channel_guid"):
            v = _extract_field(r, k)
            if v is not None: d[k] = v
        return d, None
    return {}, info

async def rb_get_account_stats(aid, force=False):
    now = time.time()
    c = _STATS_CACHE.get(aid)
    if c and not force and (now - c["ts"]) < _STATS_CACHE_TTL: return c["data"]
    acc = get_account(aid)
    if not acc: return {"groups":0,"pvs":0,"channels":0,"bots":0,"total":0,"error":"no account"}
    stats = {"groups":0,"pvs":0,"channels":0,"bots":0,"total":0}
    try:
        cli = SafeRubikaClient(name=acc.get("session_name"), _aid=aid)
        async with cli as bot:
            for c in await rb_get_chats(bot):
                ci = _chat_info(c)
                if not ci: continue
                if ci["type"] == "User": stats["pvs"] += 1
                elif ci["type"] == "Group": stats["groups"] += 1
                elif ci["type"] == "Channel": stats["channels"] += 1
                stats["total"] += 1
    except Exception:
        pass
    _STATS_CACHE[aid] = {"ts": now, "data": stats}; return stats

async def rb_refresh_profile(aid):
    acc = get_account(aid)
    if not acc: return False, "no account"
    try:
        cli = SafeRubikaClient(name=acc.get("session_name"), _aid=aid)
        async with cli as bot:
            me = await bot.get_me()
            u = _extract_field(me, "user") or me
            first = _extract_field(u, "first_name") or ""
            last = _extract_field(u, "last_name") or ""
            uname = _extract_field(u, "username") or ""
            bio = _extract_field(u, "bio") or ""
            guid = _extract_field(u, "user_guid") or ""
            uid = _extract_field(u, "user_id") or ""
            profile = {"first_name": first, "last_name": last, "username": uname,
                       "bio": bio, "user_guid": guid, "user_id": uid, "updated": int(time.time())}
            update_account(aid, profile=profile,
                          name=f"{first} {last}".strip() or acc.get("name"),
                          user_guid=guid)
            return True, profile
    except Exception as e:
        return False, _fmt_error(e)

# ═══════════════ LOGIN UI HELPERS ═══════════════
def _detect_send_type_from_prompt(prompt):
    p = str(prompt).lower()
    if any(k in p for k in ("sms", "پیامک", "پیام کوتاه")): return "sms"
    if any(k in p for k in ("call", "voice", "تماس", "صوتی")): return "call"
    if any(k in p for k in ("internal", "rubika", "rubpy", "app", "اپلیکیشن", "درون")): return "rubika"
    return "rubika"

def _send_type_label(st):
    return {
        "sms": "پیامک 📱",
        "call": "تماس تلفنی 📞",
        "rubika": "درون‌برنامه‌ای 💬",
    }.get(st, "درون‌برنامه‌ای 💬")

async def _login_panel_sending(phone):
    text = (
        f"\n🔑 <b>ورود به حساب</b>\n"
        f"{_line()}\n\n"
        f"یک کد به شماره زیر ارسال می‌شود:\n"
        f"<code>{esc(phone)}</code>\n\n"
        f"⏳ صبر کنید کد برسد...\n\n"
        f"👇 سپس کد را همین‌جا بفرست:"
    )
    await panel(text, kb_([B(f"« {T('cancel')}", "conv:cancel")]), page_tag="login_code")

async def _login_panel_code_sent(phone, send_type):
    label = _send_type_label(send_type)
    text = (
        f"\n✅ <b>کد ارسال شد</b>\n"
        f"{_line()}\n\n"
        f"کد به شماره:\n"
        f"<code>{esc(phone)}</code>\n"
        f"از طریق <b>{label}</b> ارسال شد.\n\n"
        f"👇 لطفاً کد را همین‌جا بفرست:"
    )
    await panel(text, kb_([B(f"« {T('cancel')}", "conv:cancel")]), page_tag="login_code")

# ═══════════════ LOGIN — behavior same as v2.1 + UI hooks + logging ═══════════════
_pending_login = {}
async def login_via_rubpy(admin_id, phone):
    loop = asyncio.get_running_loop()
    q = queue.Queue()
    _pending_login[admin_id] = {"q": q, "phone": phone}
    _stage = {"code_sent": False, "send_type": "rubika"}

    def fake_input(prompt=""):
        msg = str(prompt).strip() or "کد ورود:"
        flog(f"[login] fake_input fired: {msg[:60]!r}")
        try:
            if not _stage["code_sent"]:
                _stage["code_sent"] = True
                st = _detect_send_type_from_prompt(msg)
                flog(f"[login] send_type: {st}")
                asyncio.run_coroutine_threadsafe(
                    _login_panel_code_sent(phone, st), loop)
            else:
                asyncio.run_coroutine_threadsafe(tg_send(f"📨 {msg}"), loop)
        except Exception as e:
            flog(f"[login] fake_input schedule err: {e}", "error")
        flog("[login] waiting for user code...")
        try:
            code = q.get(timeout=300)
            flog(f"[login] got code len={len(str(code))}")
            return code
        except queue.Empty:
            flog("[login] TIMEOUT waiting for code", "error")
            raise RuntimeError("timeout waiting for code")

    aid = "acc_" + secrets.token_hex(4)
    sess_path = os.path.join(SESSIONS_DIR, aid)

    def worker():
        old = builtins.input
        builtins.input = fake_input
        try:
            async def run():
                c = RubikaClient(name=sess_path)
                await c.start(phone_number=phone)
                me = await c.get_me()
                try: await c.disconnect()
                except Exception: pass
                return me
            return asyncio.run(run())
        finally:
            builtins.input = old

    async def job():
        try:
            me = await asyncio.to_thread(worker)
            name = _extract_field(me, "first_name")
            if not name:
                u = _extract_field(me, "user")
                name = _extract_field(u, "first_name") if u is not None else None
            name = name or phone
            guid = _extract_field(me, "user_guid")
            if not guid:
                u = _extract_field(me, "user")
                guid = _extract_field(u, "user_guid") if u is not None else None
            add_account(aid, phone, name, sess_path, guid)
            await tg_send(f"✅ وارد شد: {esc(name)}\n🆔 <code>{aid}</code>")
            try: await show_accounts()
            except Exception: pass
        except Exception as e:
            flog(f"[login] job error: {type(e).__name__}: {e}", "error")
            for ext in (".rp", ".session", ".json"):
                p = sess_path + ext
                if os.path.exists(p):
                    try: os.remove(p)
                    except Exception: pass
            await tg_send(f"❌ لاگین ناموفق: {esc(str(e)[:200])}")
            try: await show_accounts()
            except Exception: pass
        finally:
            _pending_login.pop(admin_id, None)
    asyncio.create_task(job())

# ═══════════════ BULK LOGIN ═══════════════
_bulk_state = {}

async def bulk_login_start(cid, phones):
    if not phones: return
    state = {"phones": [], "states": {}, "active": True, "current_idx": 0}
    _bulk_state[cid] = state
    for raw in phones:
        try:
            phone = normalize_phone(raw)
            if phone not in state["phones"]: state["phones"].append(phone)
            state["states"][phone] = {"status": "pending"}
        except Exception:
            state["states"][raw] = {"status": "invalid", "error": "شماره نامعتبر"}
            if raw not in state["phones"]: state["phones"].append(raw)
    await tg_send(f"⏳ شروع {len(state['phones'])} شماره (ترتیبی)...")
    asyncio.create_task(_bulk_process_next(cid))
    await show_bulk_login_menu(cid)

async def _bulk_process_next(cid):
    state = _bulk_state.get(cid)
    if not state: return
    if state.get("cancelled"): return await bulk_finish(cid)
    while state["current_idx"] < len(state["phones"]):
        phone = state["phones"][state["current_idx"]]
        st = state["states"].get(phone, {})
        if st.get("status") == "pending": break
        state["current_idx"] += 1
    if state["current_idx"] >= len(state["phones"]):
        return await bulk_finish(cid)
    phone = state["phones"][state["current_idx"]]
    st = state["states"][phone]
    st["status"] = "running"
    aid = "acc_" + secrets.token_hex(4)
    sess_path = os.path.join(SESSIONS_DIR, aid)
    st["aid"] = aid
    loop = asyncio.get_running_loop()
    q = queue.Queue()
    st["q"] = q
    st["step"] = "login"
    await show_bulk_login_menu(cid)
    flog(f"[bulk] start {phone}, qid={id(q)}")

    def fake_input(prompt=""):
        msg = str(prompt).strip() or "کد را بفرست:"
        try:
            asyncio.run_coroutine_threadsafe(
                tg_send(f"📨 کد برای <code>{esc(phone)}</code>:\n{esc(msg)}",
                        markup=kb_([B(f"« {T('cancel')}", "conv:cancel")])),
                loop)
        except Exception as e:
            flog(f"[bulk] send schedule FAILED: {e}", "error")
        try:
            return q.get(timeout=300)
        except queue.Empty:
            raise RuntimeError("timeout waiting for code")

    def worker():
        old = builtins.input
        builtins.input = fake_input
        try:
            async def run():
                c = RubikaClient(name=sess_path)
                await c.start(phone_number=phone)
                me = await c.get_me()
                try: await c.disconnect()
                except Exception: pass
                return me
            return asyncio.run(run())
        finally:
            builtins.input = old

    try:
        me = await asyncio.to_thread(worker)
        u = _extract_field(me, "user") or me
        name = _extract_field(u, "first_name") or phone
        guid = _extract_field(u, "user_guid")
        add_account(aid, phone, name, sess_path, guid)
        st["status"] = "ok"
        await tg_send(f"✅ {phone}: {esc(name)}")
        try: await rb_refresh_profile(aid)
        except Exception: pass
    except Exception as e:
        st["status"] = "error"; st["error"] = str(e)[:100]
        await tg_send(f"❌ {phone}: {esc(str(e)[:150])}")
        for f in glob.glob(sess_path + "*"):
            try: os.remove(f)
            except Exception: pass
    st.pop("q", None); st.pop("step", None)
    state["current_idx"] += 1
    await show_bulk_login_menu(cid)
    await asyncio.sleep(2)
    await _bulk_process_next(cid)

async def bulk_finish(cid):
    state = _bulk_state.pop(cid, None)
    if not state: return await show_accounts()
    for phone, st in state.get("states", {}).items():
        q = st.get("q")
        if q:
            try: q.put("")
            except Exception: pass
    ok_n = sum(1 for s in state.get("states", {}).values() if s.get("status") == "ok")
    await tg_send(f"🏁 پایان — ✅ {ok_n} از {len(state.get('phones', []))}")
    await show_accounts()

async def show_bulk_login_menu(cid):
    state = _bulk_state.get(cid)
    if not state: return await show_accounts()
    rows = []
    for idx, phone in enumerate(state["phones"]):
        st = state["states"].get(phone, {})
        status = st.get("status", "pending")
        if st.get("step") == "login": icon = "📨"
        else: icon = {"ok": "✅", "running": "⏳", "pending": "⏸",
                      "timeout": "⏱", "error": "❌", "invalid": "❌"}.get(status, "⏳")
        rows.append([B(f"{icon} {phone}", f"bulk:enter:{idx}")])
    rows.append([B("🏁 اتمام عملیات", "bulk:finish")])
    rows.append([B("⬅️ بازگشت", "menu:acc")])
    ok_n = sum(1 for s in state["states"].values() if s.get("status") == "ok")
    wait_code_n = sum(1 for s in state["states"].values() if s.get("step") == "login")
    pending_n = sum(1 for s in state["states"].values() if s.get("status") == "pending")
    fail_n = sum(1 for s in state["states"].values() if s.get("status") in ("error","timeout","invalid"))
    cur_idx = state.get("current_idx", 0)
    txt = (head("📨", "bulk_login") +
           f"📊 کل: <b>{len(state['phones'])}</b>\n"
           f"✅ وارد: <b>{ok_n}</b>\n"
           f"📨 منتظر کد: <b>{wait_code_n}</b>\n"
           f"⏸ در نوبت: <b>{pending_n}</b>\n"
           f"❌ ناموفق: <b>{fail_n}</b>\n"
           f"📍 شماره {cur_idx+1}/{len(state['phones'])}\n\n"
           f"<i>کد را همین‌جا بفرست (نه روی دکمه)</i>")
    await panel(txt, kb_(*rows), page_tag="bulk_login")

# ═══════════════ TELEGRAM UI ═══════════════
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, filters as tg_filters)
from telegram.request import HTTPXRequest

PAGE_SIZE = 6
STATE = {"owner": None, "panel": {}, "conv": {},
         "listener_stops": {}, "op_panel": {}, "listener_new_count": 0}
_loop_ref = [None]
APP = None
_TMP_EDIT = {}
_PAGE_STATE = {}
_PANEL_SIG = {}
_OP_LAST = {}
LISTENER_TASKS = {}
PV_LISTENER_TASKS = {}
_PV_STOP_EVENTS = {}
_PV_REPLY_TASKS = {}
JL_JOBS = {}
OP_TASKS = {}
OP_LIVE = {}

def esc(s): return _html.escape(str(s if s is not None else ""))
def short(s, n=40):
    s = str(s or "").replace("\n", " ")
    return s if len(s) <= n else s[:n-1] + "…"

def _style_for(data):
    d = str(data or "").lower()
    if ":delok" in d: return "success"
    if d.endswith(":go") or "run_go" in d or ":run_acc" in d: return "success"
    if d.startswith("acc:add") or d.startswith("chnew:start") or d.startswith("at:new"): return "success"
    if ":add_text" in d or ":add_saved" in d or ":add_delay" in d: return "success"
    if ":restart" in d or ":refresh" in d: return "success"
    if any(k in d for k in (":accnext", ":maxnext", ":tgtnext", ":composenext", ":confirm", ":delok")): return "success"
    if d.endswith(":del") or ":del:" in d or d.startswith("ld:del:"): return "danger"
    if "cancel" in d: return "danger"
    if d.startswith("op:stop:"): return "danger"
    if d == "err:clear": return "danger"
    if "clear_all" in d or "wipe" in d: return "danger"
    if ":clear_seen" in d or ":clear_banned" in d: return "danger"
    if ":reset_ld" in d or ":reset_prog" in d or d.startswith("ld:reset:"): return "danger"
    if "reset_to_global" in d: return "danger"
    if d and d != "noop": return "primary"
    return None

def B(label, data, style=None):
    if style is None:
        try: style = _style_for(data)
        except Exception: style = None
    try:
        if style:
            try: return InlineKeyboardButton(label, callback_data=data, style=style)
            except TypeError:
                try: return InlineKeyboardButton(label, callback_data=data, api_kwargs={"style": style})
                except Exception: return InlineKeyboardButton(label, callback_data=data)
        return InlineKeyboardButton(label, callback_data=data)
    except Exception:
        return InlineKeyboardButton(label, callback_data=data)

def SEL(active, label): return ("[✓] " if active else "[ ] ") + label
def kb_(*rows): return InlineKeyboardMarkup([list(r) for r in rows if r])
def grid(btns, cols=2): return [btns[i:i+cols] for i in range(0, len(btns), cols)]
def nav(back=None, home=True):
    row = []
    if back: row.append(B(f"« {T('back')}", back))
    if home: row.append(B(T("back_to_panel"), "menu:main"))
    return row
def head(icon, key, sub=None):
    t = T(key) if key in _TR else str(key)
    if is_en(): t = SC(t)
    s = f"{{{icon}}} {t}"
    if sub is not None: s += f"  ({sub})"
    return "\n" + s + "\n" + _line() + "\n\n"
def mrow(emoji, key, value):
    k = T(key) if key in _TR else str(key)
    if is_en(): k = SC(k)
    return f"{emoji}{TICK}{k} : {value}"
def dots(cur, total): return "".join("●" if i <= cur else "○" for i in range(1, total+1)) + f"  {cur}/{total}"
def _bar(pct, n=14):
    fill = max(0, min(n, round(pct * n / 100)))
    return "█" * fill + "░" * (n - fill)
def _eta(sec):
    sec = int(sec)
    if sec < 60: return f"{sec}ث"
    if sec < 3600: return f"{sec // 60}د"
    return f"{sec // 3600}س {(sec % 3600) // 60}د"

def authorized(update):
    try: return update.effective_chat.id == FORCED_OWNER
    except Exception: return False

def _sig(text, kb):
    try: k = json.dumps(kb.to_dict(), sort_keys=True) if kb else ""
    except Exception: k = repr(kb)
    return hashlib.md5((text + "|" + k).encode()).hexdigest()

async def panel(text, kb=None, page_tag=None):
    cid = STATE.get("owner")
    if not cid or APP is None: return
    if page_tag: _set_page(cid, page_tag)
    text = str(text)[:4000]
    sig = _sig(text, kb)
    mid = STATE["panel"].get(cid)
    if mid:
        if _PANEL_SIG.get(cid) == (mid, sig): return
        try:
            await APP.bot.edit_message_text(chat_id=cid, message_id=mid, text=text, reply_markup=kb,
                                            parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            _PANEL_SIG[cid] = (mid, sig); return
        except BadRequest as e:
            if "not modified" in str(e).lower(): _PANEL_SIG[cid] = (mid, sig); return
        except RetryAfter: return
        except Exception: pass
    for attempt in range(3):
        try:
            m = await APP.bot.send_message(chat_id=cid, text=text, reply_markup=kb,
                                           parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            STATE["panel"][cid] = m.message_id
            _PANEL_SIG[cid] = (m.message_id, sig); return
        except RetryAfter as e: await asyncio.sleep(float(e.retry_after) + 0.5)
        except Exception: await asyncio.sleep(1.5 * (attempt + 1))

async def _autodel(mid, delay=4.0):
    await asyncio.sleep(delay)
    try: await APP.bot.delete_message(chat_id=STATE["owner"], message_id=mid)
    except Exception: pass

async def tg_send(text, markup=None, parse_mode=None):
    if not STATE.get("owner") or APP is None: return False
    text = str(text)[:4000]
    ephemeral = (markup is None and len(text) <= 40)
    for attempt in range(3):
        try:
            m = await APP.bot.send_message(chat_id=STATE["owner"], text=text, reply_markup=markup,
                                           parse_mode=parse_mode or "HTML", disable_web_page_preview=True)
            if ephemeral: asyncio.create_task(_autodel(m.message_id))
            return True
        except RetryAfter as e: await asyncio.sleep(float(e.retry_after) + 0.5)
        except Exception as e:
            if "parse entities" in str(e) and parse_mode: parse_mode = None; continue
            await asyncio.sleep(1.5 * (attempt + 1))
    return False

async def ask(text, note=None):
    body = (f"⚠️ {esc(note)}\n\n" if note else "") + text
    await panel(body, kb_([B(f"« {T('cancel')}", "conv:cancel")]), page_tag="ask")

def log_cb(msg):
    try:
        loop = _loop_ref[0]
        if loop: loop.create_task(tg_send(str(msg)))
    except Exception: pass

def get_conv(cid):
    c = STATE["conv"].get(cid)
    if not c: c = STATE["conv"][cid] = {}
    return c
def clear_conv(cid): STATE["conv"].pop(cid, None)

def _extract_media(msg):
    if msg is None: return None
    for attr in ("photo","video","animation","document","audio","voice","sticker"):
        try:
            v = getattr(msg, attr, None)
            if v:
                if isinstance(v, (list, tuple)) and v: return v[-1]
                return v
        except Exception: continue
    return None

async def _download_tg_file(media_obj, aid, prefix):
    if APP is None: raise RuntimeError("APP not ready")
    if media_obj is None: raise RuntimeError("no_media")
    file_id = getattr(media_obj, "file_id", None)
    if not file_id: raise RuntimeError("no_file_id")
    f = await APP.bot.get_file(file_id)
    ext = os.path.splitext(getattr(f, "file_path", "") or "")[1] or ".bin"
    fname = f"{prefix}_{aid}_{int(time.time())}_{secrets.token_hex(3)}{ext}"
    full = os.path.join(UPLOADS_DIR, fname)
    try: await f.download_to_drive(full)
    except AttributeError:
        data = await f.download_as_bytearray()
        with open(full, "wb") as fp: fp.write(bytes(data))
    if not os.path.exists(full) or os.path.getsize(full) == 0: raise RuntimeError("empty_file")
    return full

def _set_page(cid, tag):
    try: _PAGE_STATE[int(cid)] = str(tag)
    except Exception: pass
def _is_page(cid, tag):
    try: return _PAGE_STATE.get(int(cid)) == tag
    except Exception: return False

# ═══════════════ PANELS ═══════════════
async def show_main():
    accounts = list_accounts()
    running = [o for o in _load_ops() if _op_effective_status(o) == "running"]
    pv_enabled = sum(1 for aid in accounts if _load_pv_account(aid).get("enabled"))
    txt = head("🌀", "panel", VERSION)
    txt += mrow("👤", "accounts_n", len(accounts)) + "\n"
    txt += mrow("💬", "pv_enabled", pv_enabled) + "\n"
    txt += mrow("📊", "running_ops", (len(running) if running else T("idle"))) + "\n"
    txt += mrow("👂", "listener", sum(1 for t in LISTENER_TASKS.values() if not t.done())) + "\n"
    txt += mrow("💾", "data_dir", f"<code>{esc(DATA_DIR)}</code>")
    rows = []
    if running: rows.append([B(f"{T('running_ops')} ({len(running)})", f"op:view:{running[0]['id']}")])
    rows += [
        [B(T("send"), "send:start"), B(T("joiner"), "jl:start")],
        [B(T("lefter"), "lf:start"), B(T("templates"), "at:menu")],
        [B(T("accounts_n"), "menu:acc"), B(T("pv"), "menu:pv")],
        [B(T("stats"), "menu:stats"), B(T("errors"), "menu:errors"), B(T("cache"), "menu:cache")],
        [B(T("listener"), "menu:listen"), B(T("linkdonies"), "ld:list:jl:back_to_settings")],
        [B(T("settings"), "menu:cfg")],
    ]
    await panel(txt, kb_(*rows), page_tag="main")

async def show_cache_menu():
    accounts = list_accounts()
    txt = head("🗂", "cache") + T("select_account") + "\n\n"
    rows = []
    for aid, a in accounts.items():
        sn = _seen_count(aid); bn = _banned_count(aid); ln = len(_load_ldprog(aid))
        rows.append([B(f"{short(a.get('name','?'), 14)} · {T('seen')} {sn} · {T('banned')} {bn} · {ln}", f"cache:acc:{aid}")])
    if not accounts: txt += T("empty")
    rows.append([B(T("wipe_all"), "cache:clear_all_accounts")])
    rows.append(nav())
    await panel(txt, kb_(*rows), page_tag="cache")

async def show_cache_account(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="cache")
    sn = _seen_count(aid); bn = _banned_count(aid); ln = len(_load_ldprog(aid))
    txt = head("🗂", f"{T('cache')} · {a.get('name','?')}")
    txt += mrow("🔍", "seen", sn) + "\n"
    txt += mrow("🚫", "banned", bn) + "\n"
    txt += mrow("📡", "ld_progress", ln)
    rows = [
        [B(T("clear_seen"), f"cache:acc:{aid}:clear_seen"), B(T("clear_banned"), f"cache:acc:{aid}:clear_banned")],
        [B(T("clear_both"), f"cache:acc:{aid}:clear_all"), B(T("reset_ld"), f"cache:acc:{aid}:reset_ld")],
        [B(T("refresh_profile"), f"acc:refresh_one:{aid}")],
        nav("menu:cache"),
    ]
    await panel(txt, kb_(*rows), page_tag=f"cache:{aid}")

async def show_pv_menu():
    accounts = list_accounts()
    txt = head("💬", "pv_auto") + T("select_account") + "\n\n"
    if not accounts:
        txt += T("pv_no_accounts")
        return await panel(txt, kb_([B(T("add_account"), "acc:add")], nav()), page_tag="pv_menu")
    rows = []
    for aid, a in accounts.items():
        cfg = _load_pv_account(aid)
        en = f"[{T('pv_active') if cfg.get('enabled') else T('pv_inactive')}] "
        items_n = len(cfg.get("items") or [])
        rows.append([B(f"{en}{short(a.get('name','?'), 20)} · {items_n}", f"pv:acc:{aid}")])
    rows.append(nav())
    await panel(txt, kb_(*rows), page_tag="pv_menu")

async def show_pv_account_menu(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="pv_menu")
    cfg = _load_pv_account(aid)
    en = bool(cfg.get("enabled")); mx = int(cfg.get("max_replies", 1) or 0)
    items = cfg.get("items") or []; notify_on = bool(cfg.get("notify", True))
    poll_sec = int(cfg.get("poll_seconds", 3)); delay_sec = int(cfg.get("delay_seconds", 0))
    pv_task = PV_LISTENER_TASKS.get(aid); poller_on = bool(pv_task and not pv_task.done())
    has_custom = _has_pv_account(aid)
    txt = head("💬", f"{T('pv')} · {a.get('name','?')}")
    txt += mrow("📶", "pv_status", (T("pv_active") if en else T("pv_inactive"))) + "\n"
    txt += mrow("🔄", "pv_poller", (T("on") if poller_on else T("off"))) + "\n"
    txt += mrow("👥", "pv_max", (mx if mx else "∞")) + "\n"
    txt += mrow("⏱", "pv_delay", f"{delay_sec}s") + "\n"
    txt += mrow("🔔", "pv_notify", (T("on") if notify_on else T("off"))) + "\n"
    txt += mrow("🔄", "pv_poll", f"{poll_sec}s") + "\n"
    txt += mrow("📨", "pv_items", len(items))
    if has_custom: txt += f"  ({T('pv_custom')})"
    txt += "\n\n"
    for i, it in enumerate(items, 1):
        k = it.get("kind", "text")
        if k == "text": txt += f"{i}. 💬 <code>{esc(short(it.get('text',''), 40))}</code>\n"
        elif k == "file": txt += f"{i}. 📁 <code>{esc(os.path.basename(it.get('file_path','?')))}</code>\n"
        elif k == "delay": txt += f"{i}. ⏸ {it.get('seconds', 3)}s\n"
    rows = [
        [B(T("toggle_off") if en else T("toggle_on"), f"pv:acc:{aid}:toggle")],
        [B(f"{T('pv_max')}: {mx if mx else '∞'}", f"pv:acc:{aid}:cycle_max"), B(T("pv_delay"), f"pv:acc:{aid}:set_delay")],
        [B(T("pv_add_text"), f"pv:acc:{aid}:add_text"), B(T("pv_add_file"), f"pv:acc:{aid}:add_saved"), B(T("pv_add_delay"), f"pv:acc:{aid}:add_delay")],
        [B(T("pv_list"), f"pv:acc:{aid}:list"), B(T("pv_report"), f"pv:acc:{aid}:report:0")],
        [B(f"{T('pv_notify')}: {'✓' if notify_on else '✗'}", f"pv:acc:{aid}:toggle_notify"), B(f"{T('pv_poll')} {poll_sec}s", f"pv:acc:{aid}:set_poll")],
        [B(T("pv_reset_counter"), f"pv:acc:{aid}:clear_replies"), B(T("pv_reset_custom"), f"pv:acc:{aid}:reset_to_global")],
        [B(T("pv_restart"), f"pv:acc:{aid}:restart")],
        nav("menu:pv"),
    ]
    await panel(txt, kb_(*rows), page_tag=f"pv_acc:{aid}")

async def show_pv_account_list(aid):
    cfg = _load_pv_account(aid); items = cfg.get("items") or []
    a = get_account(aid)
    txt = head("📋", f"{T('pv_list')} · {a.get('name','?') if a else aid}")
    for i, it in enumerate(items, 1):
        k = it.get("kind", "text")
        if k == "text": txt += f"\n{i}. 💬 <code>{esc(short(it.get('text',''), 60))}</code>"
        elif k == "file": txt += f"\n{i}. 📁 <code>{esc(os.path.basename(it.get('file_path','?')))}</code>"
        elif k == "delay": txt += f"\n{i}. ⏸ {it.get('seconds',3)}s"
    rows = [[B(f"{T('delete')} {i+1}", f"pv:acc:{aid}:del:{i}")] for i in range(len(items))]
    rows.append([B(f"« {T('back')}", f"pv:acc:{aid}")])
    await panel(txt, kb_(*rows), page_tag=f"pv_list:{aid}")

async def show_pv_account_report(aid, page=0):
    rep = _load_pv_report(); users = rep.get(aid) or {}
    rows_data = []
    for uid, data in users.items():
        rows_data.append({"uid": uid, "first_name": data.get("first_name") or "",
                          "count": data.get("count", 1), "replied": data.get("replied", False),
                          "reply_ok": data.get("reply_ok", False), "blocked": data.get("blocked", False),
                          "error": data.get("error"), "last_seen": data.get("last_seen", 0)})
    rows_data.sort(key=lambda x: x["last_seen"], reverse=True)
    PER = 8; pages = max(1, -(-len(rows_data) // PER)); page = max(0, min(page, pages - 1))
    chunk = rows_data[page * PER:(page + 1) * PER]
    a = get_account(aid)
    txt = head("📊", f"{T('pv_report')} · {a.get('name','?') if a else aid}")
    txt += f"👥 {T('pv_total')}: <b>{len(rows_data)}</b>   ·   📄 {T('pv_page')} {page+1}/{pages}\n\n"
    for r in chunk:
        name = r["first_name"] or "?"
        st = "✅" if r["replied"] and r["reply_ok"] else ("❌" if r["replied"] else "⏳")
        if r["blocked"]: st += " 🚫"
        ago = int(time.time() - r["last_seen"])
        txt += f"{st} <b>{esc(short(name, 20))}</b> · 📨×{r['count']} · <i>{_eta(ago)}</i>\n"
        if r.get("error"): txt += f"   <code>{esc(short(r['error'], 50))}</code>\n"
    nav_btns = []
    if pages > 1:
        pr = []
        if page > 0: pr.append(B(T("prev"), f"pv:acc:{aid}:report:{page-1}"))
        pr.append(B(f"{page+1}/{pages}", "noop"))
        if page < pages - 1: pr.append(B(T("next"), f"pv:acc:{aid}:report:{page+1}"))
        nav_btns.append(pr)
    nav_btns.append([B(f"« {T('back')}", f"pv:acc:{aid}")])
    await panel(txt, kb_(*nav_btns), page_tag=f"pv_rep:{aid}:{page}")

# ═══════════════ ACCOUNTS VIEW ═══════════════
def _accounts_view(page):
    accounts = list_accounts(); items = list(accounts.items())
    pages = max(1, -(-len(items) // PAGE_SIZE)); page = max(0, min(page, pages - 1))
    chunk = items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = []
    for aid, a in chunk:
        cfg = _load_pv_account(aid); pv_icon = "🟢" if cfg.get("enabled") else "⚪"
        st = _STATS_CACHE.get(aid, {}).get("data") or {}
        alias = a.get("alias") or a.get("name") or "?"
        rows.append([B(f"📱 {short(alias, 14)} · {pv_icon} · 👥{st.get('groups','…')}", f"acc:view:{aid}")])
    if pages > 1:
        pr = []
        if page > 0: pr.append(B("◀️", f"acc:page:{page - 1}"))
        pr.append(B(f"{page + 1}/{pages}", "noop"))
        if page < pages - 1: pr.append(B("▶️", f"acc:page:{page + 1}"))
        rows.append(pr)
    rows.append([B(f"➕ {T('add_account')}", "acc:add")])
    rows.append([B(f"📨 {T('bulk_login')}", "acc:bulk")])
    rows.append([B(f"🔄 {T('refresh_profile')}", "acc:refresh")])
    rows.append(nav())
    txt = head("📱", "accounts_n", len(accounts))
    return txt, kb_(*rows), f"acc_list:{page}", chunk

async def show_accounts(page=0):
    txt, kb, tag, chunk = _accounts_view(page)
    await panel(txt, kb, page_tag=tag)
    if chunk:
        stale = any(aid not in _STATS_CACHE or (time.time() - _STATS_CACHE[aid].get("ts", 0)) > 120 for aid, _ in chunk)
        if stale: asyncio.create_task(_bg_fetch_stats(page, tag))

async def _bg_fetch_stats(page, tag):
    try:
        _, _, _, chunk = _accounts_view(page)
        async def one(aid):
            try: await asyncio.wait_for(rb_get_account_stats(aid), timeout=25)
            except Exception: pass
        await asyncio.gather(*[one(aid) for aid, _ in chunk])
        cid = STATE.get("owner")
        if not cid or not _is_page(cid, tag): return
        txt, kb, tag2, _ = _accounts_view(page)
        await panel(txt, kb, page_tag=tag2)
    except Exception: pass

async def show_account_detail(aid):
    tag = f"acc:{aid}"; a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    t = LISTENER_TASKS.get(aid); on = bool(t and not t.done())
    pvt = PV_LISTENER_TASKS.get(aid); pvon = bool(pvt and not pvt.done())
    pvc = _load_pv_account(aid)
    st = _STATS_CACHE.get(aid, {}).get("data") or {}
    g = lambda k: st.get(k, "…")
    alias = a.get("alias") or "—"
    real_name = a.get("name") or "—"
    username = a.get("username") or (a.get("profile") or {}).get("username") or "—"
    user_id = a.get("user_id") or (a.get("profile") or {}).get("user_id") or "—"
    guid = a.get("user_guid") or (a.get("profile") or {}).get("user_guid") or "—"
    avatar = (a.get("profile") or {}).get("avatar") or ""

    txt = head("📱", alias if alias != "—" else real_name)
    txt += mrow("📞", "phone", f"<code>{esc(a.get('phone', '—'))}</code>") + "\n"
    txt += mrow("👤", "real_name", f"<b>{esc(real_name)}</b>") + "\n"
    txt += mrow("🏷", "alias", f"<b>{esc(alias)}</b>") + "\n"
    txt += mrow("🔤", "username", f"<code>{esc(username)}</code>") + "\n"
    txt += mrow("🆔", "guid", f"<code>{esc(guid)}</code>") + "\n"
    txt += mrow("🔢", "user_id", f"<code>{esc(user_id)}</code>") + "\n"
    if avatar:
        txt += mrow("🖼", "avatar", f'<a href="{esc(avatar)}">📷</a>') + "\n"
    txt += f"\n{_line()}\n"
    txt += mrow("👥", "groups", f"<b>{g('groups')}</b>") + "  ·  "
    txt += mrow("💬", "pvs", f"<b>{g('pvs')}</b>") + "  ·  "
    txt += mrow("📢", "channels", f"<b>{g('channels')}</b>") + "\n"
    txt += mrow("✨", "channels_created", f"<b>{len(get_stored_channels(aid))}</b>") + "\n"
    txt += mrow("👂", "listener", '🟢' if on else '⚪') + "  ·  "
    txt += mrow("💬", "pv", '🟢' if pvon else '⚪')
    if pvc.get("enabled"): txt += f" ({len(pvc.get('items') or [])})"
    txt += f"\n{mrow('🔍', 'seen', f'<b>{_seen_count(aid)}</b>')}  ·  {mrow('🚫', 'banned', f'<b>{_banned_count(aid)}</b>')}"

    rows = grid([
        B("🔄 " + T("refresh_profile"), f"acc:refresh_profile:{aid}"),
        B("✏️ " + T("alias"), f"acc:set_alias:{aid}"),
        B(T("auto_tar"), f"acc:at:{aid}"), B(T("channels"), f"ch:menu:{aid}"),
        B(T("profile"), f"prof:menu:{aid}"),
        B((T("toggle_off") if on else T("toggle_on")) + " " + T("listener"), f"listen:toggle:{aid}"),
        B(T("pv"), f"pv:acc:{aid}"), B(T("photo"), f"accphoto:menu:{aid}"),
        B(T("lefter"), f"acc:lf:{aid}"), B(T("cache"), f"cache:acc:{aid}"),
    ])
    rows.append([B(f"🗑 {T('delete_account')}", f"acc:del:{aid}")])
    rows.append(nav("menu:acc"))
    await panel(txt, kb_(*rows), page_tag=tag)
    if (time.time() - (st.get("ts") or 0)) > 120:
        asyncio.create_task(_bg_refresh_one(aid, tag))

async def _bg_refresh_one(aid, tag):
    try:
        await asyncio.wait_for(rb_get_account_stats(aid, force=True), timeout=30)
        cid = STATE.get("owner")
        if not cid or not _is_page(cid, tag): return
        await show_account_detail(aid)
    except Exception: pass

async def show_profile_menu(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    rows = grid([
        B(T("name"), f"prof:set:first:{aid}"), B(T("last_name"), f"prof:set:last:{aid}"),
        B(T("bio"), f"prof:set:about:{aid}"), B(T("username"), f"prof:set:username:{aid}"),
        B(T("photo"), f"accphoto:menu:{aid}"),
    ])
    rows.append(nav(f"acc:view:{aid}"))
    await panel(head("📝", "profile", a.get("name", "?")) + f"📞 <code>{esc(a.get('phone', '—'))}</code>",
                kb_(*rows), page_tag=f"prof:{aid}")

async def show_acc_photo_menu(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    rows = [[B(T("prof_set_photo"), f"accphoto:set:{aid}")], [B(T("prof_del_photo"), f"accphoto:del:{aid}")], nav(f"acc:view:{aid}")]
    await panel(head("🖼", "prof_photo_menu", a.get("name", "?")), kb_(*rows), page_tag=f"accphoto:{aid}")

async def show_ch_photo_menu(aid, idx):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    chs = get_stored_channels(aid)
    if idx < 0 or idx >= len(chs): return await show_ch_list(aid)
    ch = chs[idx]
    rows = [[B(T("prof_set_photo"), f"chphoto:set:{aid}:{idx}")], [B(T("prof_del_photo"), f"chphoto:del:{aid}:{idx}")], nav(f"ch:view:{aid}:{idx}")]
    await panel(head("🖼", "ch_photo_menu", ch.get("title", "?")), kb_(*rows), page_tag=f"chphoto:{aid}:{idx}")

def _ch_link(ch):
    un = (ch.get("username") or "").lstrip("@")
    return ch.get("join_link") or (f"https://rubika.ir/{un}" if un else "")

async def show_ch_menu(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    n = len(get_stored_channels(aid))
    txt = head("📢", "channels", a.get("name", "?")) + f"✨ {T('channels_created')}: <b>{n}</b>"
    rows = [[B(f"📋 {T('my_channels')} ({n})", f"chlist:show:{aid}:0")], [B(T("create_channel"), f"chnew:start:{aid}")], nav(f"acc:view:{aid}")]
    await panel(txt, kb_(*rows), page_tag=f"ch_menu:{aid}")

async def show_ch_list(aid, page=0):
    channels = get_stored_channels(aid); per = 6
    pages = max(1, -(-len(channels) // per)); page = max(0, min(page, pages - 1))
    rows = []
    for idx, ch in list(enumerate(channels))[page * per:(page + 1) * per]:
        icon = "🌐" if (ch.get("type") == "public" or ch.get("username")) else "🔒"
        lbl = f"{icon} {short(ch.get('title', '?'), 24)}"
        if ch.get("username"): lbl += f" · @{ch['username']}"
        rows.append([B(lbl, f"ch:view:{aid}:{idx}")])
    if pages > 1:
        pr = []
        if page > 0: pr.append(B("◀️", f"chlist:show:{aid}:{page - 1}"))
        pr.append(B(f"{page + 1}/{pages}", "noop"))
        if page < pages - 1: pr.append(B("▶️", f"chlist:show:{aid}:{page + 1}"))
        rows.append(pr)
    rows.append([B(T("create_channel"), f"chnew:start:{aid}")])
    rows.append(nav(f"ch:menu:{aid}"))
    txt = head("📋", "my_channels", len(channels))
    txt += T("ch_no_channels") if not channels else ""
    await panel(txt, kb_(*rows), page_tag=f"chlist:{aid}:{page}")

async def show_channel_view(aid, idx):
    if not get_account(aid): return await panel(T("not_found"), kb_(nav()), page_tag="main")
    channels = get_stored_channels(aid)
    if idx < 0 or idx >= len(channels): return await show_ch_list(aid)
    ch = channels[idx]
    un = ch.get("username") or ""; is_pub = ch.get("type") == "public" or bool(un)
    link = _ch_link(ch)
    txt = head("📢", ch.get("title") or "?")
    txt += mrow("🔖", "type", (T("public") if is_pub else T("private"))) + "\n"
    if un: txt += mrow("🔤", "username", f"@{esc(un)}") + "\n"
    txt += mrow("🔗", "link", (f"<code>{esc(link)}</code>" if link else "—"))
    rows = [
        [B("💬 " + T("ch_send_text"), f"chsend:text:{aid}:{idx}"), B("🖼 " + T("ch_send_photo"), f"chsend:photo:{aid}:{idx}")],
        [B("🎬 " + T("ch_send_video"), f"chsend:video:{aid}:{idx}"), B("📄 " + T("ch_send_file"), f"chsend:file:{aid}:{idx}")],
        [B("📝 " + T("profile"), f"chprof:show:{aid}:{idx}"), B("🖼 " + T("photo"), f"chphoto:menu:{aid}:{idx}")],
        [B("🔗 " + T("get_link"), f"ch:getlink:{aid}:{idx}"), B("✍️ " + T("set_link"), f"ch:setlink:{aid}:{idx}")],
        [B("🔍 " + T("debug"), f"ch:diag:{aid}:{idx}"), B("🗑 " + T("delete"), f"ch:del:{aid}:{idx}")],
        nav(f"chlist:show:{aid}:0"),
    ]
    await panel(txt, kb_(*rows), page_tag=f"chview:{aid}:{idx}")

def _ch_profile_view(aid, idx, ch, info, err=None, loading=False):
    title = info.get("title") or ch.get("title") or "?"
    un = info.get("username") or ch.get("username") or ""
    desc = info.get("description") or ch.get("description") or ""
    members = info.get("members")
    link = ch.get("join_link") or info.get("join_link") or (f"https://rubika.ir/{un}" if un else "")
    txt = head("📝", title) + (T("public") if un else T("private")) + "\n\n"
    if un: txt += f"🔤 @{esc(un)}\n"
    txt += f"🔗 <code>{esc(link)}</code>\n" if link else "🔗 —\n"
    txt += "📖 " + (esc(desc[:200]) if desc else "—") + "\n"
    if members is not None: txt += f"👥 <b>{members}</b>\n"
    if loading: txt += "\n⏳ ..."
    elif err: txt += f"\n⚠️ <i>{esc(str(err)[:150])}</i>"
    rows = [
        [B("✏️ " + T("name"), f"chprof:edit:title:{aid}:{idx}"), B("📖 " + T("about"), f"chprof:edit:desc:{aid}:{idx}")],
        [B("🔤 " + T("username"), f"chprof:edit:user:{aid}:{idx}")],
        [B(T("get_link"), f"ch:getlink:{aid}:{idx}"), B(T("set_link"), f"ch:setlink:{aid}:{idx}")],
        [B("🔄", f"chprof:show:{aid}:{idx}"), B(T("delete"), f"ch:del:{aid}:{idx}")],
        nav(f"ch:view:{aid}:{idx}"),
    ]
    return txt, kb_(*rows)

async def show_ch_profile(aid, idx):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    channels = get_stored_channels(aid)
    if idx < 0 or idx >= len(channels): return await show_ch_list(aid)
    ch = channels[idx]; tag = f"chprof:{aid}:{idx}"
    txt, kb = _ch_profile_view(aid, idx, ch, dict(ch), loading=True)
    await panel(txt, kb, page_tag=tag)
    info = dict(ch); err = None
    try:
        cli = SafeRubikaClient(name=a.get("session_name"), _aid=aid)
        async with cli as bot:
            info2, err2 = await rb_get_channel_info(bot, ch.get("guid"))
            if info2: info = info2
            if err2: err = err2
    except Exception as e:
        err = f"{type(e).__name__}: {_fmt_error(e)}"
    cid = STATE.get("owner")
    if not cid or not _is_page(cid, tag): return
    txt, kb = _ch_profile_view(aid, idx, ch, info, err=err)
    await panel(txt, kb, page_tag=tag)

async def show_ch_new_type(aid, title):
    await panel(head("🏗", "create_channel") + f"📝 <b>{esc(title)}</b>\n\n{T('ch_new_type')}",
                kb_([B(T("public"), f"chnew:pub:{aid}"), B(T("private"), f"chnew:priv:{aid}")],
                    [B(f"« {T('cancel')}", f"ch:menu:{aid}")]), page_tag=f"chnew_type:{aid}")

async def show_listen_menu():
    accounts = list_accounts()
    txt = head("👂", "listener"); btns = []
    for aid, a in accounts.items():
        t = LISTENER_TASKS.get(aid); run = t is not None and not t.done()
        btns.append(B(f"{'🟢' if run else '⚪'} {short(a.get('name', '?'), 14)}", f"listen:toggle:{aid}"))
    rows = grid(btns)
    rows.append([B(T("listener_restart_all"), "listen:restart")])
    rows.append(nav())
    await panel(txt, kb_(*rows), page_tag="listen")

async def show_linkdonies(back_to="jl:back_to_settings"):
    lst = load_link_donies()
    auto = int(_load(CFG_FILE, DEFAULT_CFG).get("auto_join_linkdoni", 1))
    txt = head("📡", "linkdonies", len(lst))
    txt += f"🔁 {T('ld_auto_join')}: <b>{'🟢' if auto else '🔴'}</b>\n"
    txt += f"<i>{T('ld_progress_per_acc')}</i>\n\n"
    for i, url in enumerate(lst): txt += f"{i + 1}. <code>{esc(url)}</code>\n"
    rows = grid([B(f"🗑 {i + 1}. {short(u.split('/')[-1], 12)}", f"ld:del:{i}:{back_to}") for i, u in enumerate(lst)])
    rows.append([B(T("ld_add"), f"ld:add:{back_to}"), B(T("toggle_off") if auto else T("toggle_on"), f"ld:toggle_autojoin:{back_to}")])
    rows.append([B(T("ld_reset_prog"), f"ld:reset_prog:{back_to}")])
    rows.append([B(T("ld_reset_list"), f"ld:reset:{back_to}")])
    rows.append(nav(back_to, home=False))
    await panel(txt, kb_(*rows), page_tag="linkdonies")

def _op_view(op):
    oid = op["id"]; t = op.get("type")
    st = _op_effective_status(op); s = _op_stats(op); p = op.get("progress") or {}
    tot = s["total"] or 0; proc = s["done"] + s["failed"]
    pct = min(100, int(proc * 100 / tot)) if tot else 0
    icon = {"joinlef": "🤝", "lefter": "🚪", "autotar": "🎯", "send": "📤"}.get(t, "⚙️")
    label = {"joinlef": "op_joiner", "lefter": "op_lefter", "autotar": "op_autotar", "send": "op_send"}.get(t, "?")
    txt = head(icon, label, oid[-6:])
    txt += f"<b>{_op_status_label(st)}</b>\n"
    txt += f"<code>{_bar(pct)} {pct}%</code>\n\n"
    if t in ("joinlef", "autotar"):
        txt += f"🤝 {T('op_joined')}: <b>{s['done']}</b>   ✗ {T('op_failed_c')}: <b>{s['failed']}</b>"
        if op.get("max_join"): txt += f"   🎯 <b>{op['max_join']}</b>"
        if s.get("already"): txt += f"\n♻️ {T('op_already')}: <b>{s['already']}</b>"
        if s.get("sent"): txt += f"\n📤 {T('op_sent')}: <b>{s['sent']}</b>"
        if s.get("left"): txt += f"\n🚪 {T('op_left')}: <b>{s['left']}</b>"
        if s.get("tried"): txt += f"\n🔗 {T('op_tried')}: <b>{s['tried']}</b>"
        if s.get("extracted"): txt += f"\n📥 استخراج: <b>{s['extracted']}</b> لینک"
        if s.get("skipped_seen"): txt += f"\n🔍 {T('op_skipped_seen')}: <b>{s['skipped_seen']}</b>"
        if s.get("skipped_banned"): txt += f"\n🚫 {T('op_skipped_banned')}: <b>{s['skipped_banned']}</b>"
        if s.get("rejected"): txt += f"\n🟡 {T('op_rejected')}: <b>{s['rejected']}</b>"
        if s.get("wave"): txt += f"\n🌊 {T('op_wave')}: <b>{s['wave']}</b>"
        if s.get("round"): txt += f"   ·   🔁 {T('op_round')}: <b>{s['round']}</b>"
    elif t == "lefter":
        txt += f"🚪 {T('op_left')}: <b>{s['done']}</b>   ✗ {T('op_failed_c')}: <b>{s['failed']}</b>"
    else:
        txt += f"✓ {T('op_sent')}: <b>{s['done']}</b>   ✗ {T('op_failed_c')}: <b>{s['failed']}</b>   ⏳ {s['pending']}"
        if s.get("blocked"): txt += f"\n🚫 {T('op_blocked')}: {s['blocked']}"
        if s.get("round"): txt += f"   ·   🔁 {T('op_round')}: {s['round']}"
    txt += f"\n\n📍 <i>{esc(p.get('phase', '—'))}</i>"
    rows = []
    if st == "running": rows.append([B(T("stop"), f"op:stop:{oid}")])
    rows.append([B(f"« {T('stats')}", "menu:stats"), B(T("back_to_panel"), "menu:main")])
    return txt, kb_(*rows)

async def _refresh_op_panel(op_id, force=False):
    try:
        op = _get_op(op_id); cid = STATE.get("owner")
        if not op or not cid: return
        if not force:
            if STATE.get("op_panel", {}).get(cid) != op_id: return
            if not _is_page(cid, f"op:{op_id}"): return
            if _op_effective_status(op) == "running":
                now = time.time()
                if now - _OP_LAST.get(op_id, 0) < 1.5: return
                _OP_LAST[op_id] = now
        txt, kb = _op_view(op)
        await panel(txt, kb, page_tag=f"op:{op_id}")
    except Exception: pass

async def _live_for_op(oid):
    while True:
        try:
            op2 = _get_op(oid)
            if not op2 or _op_effective_status(op2) != "running": return
            cid = STATE.get("owner")
            if not cid or not _is_page(cid, f"op:{oid}"): return
            await _refresh_op_panel(oid)
        except asyncio.CancelledError: raise
        except Exception: pass
        await asyncio.sleep(1.5)

def _ensure_live_for(oid):
    t = OP_LIVE.get(oid)
    if t and not t.done(): return t
    t = asyncio.create_task(_live_for_op(oid))
    OP_LIVE[oid] = t
    return t

async def show_op_detail(oid):
    op = _get_op(oid)
    if not op: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    cid = STATE.get("owner")
    if cid: STATE.setdefault("op_panel", {})[cid] = oid
    txt, kb = _op_view(op)
    await panel(txt, kb, page_tag=f"op:{oid}")
    if _op_effective_status(op) == "running":
        _ensure_live_for(oid)

async def show_stats():
    ops = _load_ops(); ops.sort(key=lambda o: o.get("created", 0), reverse=True)
    errs = _load_errors()
    done = sum(_op_stats(o)["done"] for o in ops)
    failed = sum(_op_stats(o)["failed"] for o in ops)
    running = [o for o in ops if _op_effective_status(o) == "running"]
    txt = head("📊", "stats_title")
    txt += f"✅ <b>{done}</b>   ❌ <b>{failed}</b>   ⚠️ <b>{len(errs)}</b>\n"
    if running:
        txt += f"\n<b>🟢 {T('stats_running')}</b>\n"
        for o in running[:3]:
            s = _op_stats(o)
            txt += f"• {esc(_op_short_title(o, 22))}  ✅{s['done']} ❌{s['failed']}\n"
    rows = []
    for o in ops[:8]:
        s = _op_stats(o); prog = f"{s['done']}/{s['total']}" if s["total"] else "—"
        rows.append([B(f"{short(_op_short_title(o, 20), 22)} · {prog}", f"op:view:{o['id']}")])
    rows.append([B(T("errors"), "menu:errors"), B(T("back_to_panel"), "menu:main")])
    await panel(txt, kb_(*rows), page_tag="stats")

async def show_errors(page=0):
    errors = list(reversed(_load_errors()))
    if not errors: return await panel(head("⚠️", "errors") + T("errors_none"), kb_(nav()), page_tag="errors")
    PER = 4; pages = max(1, -(-len(errors) // PER)); page = max(0, min(page, pages - 1))
    txt = head("⚠️", "errors", len(errors))
    for e in errors[page * PER:(page + 1) * PER]:
        t = time.strftime("%m/%d %H:%M", time.localtime(e.get("time", 0)))
        txt += f"\n🕐 <code>{esc(t)}</code> · <b>{esc(e.get('source', '?'))}</b>\n<code>{esc(str(e.get('error', ''))[:220])}</code>\n"
    rows = []
    if pages > 1:
        pr = []
        if page > 0: pr.append(B(T("prev"), f"err:page:{page - 1}"))
        pr.append(B(f"{page + 1}/{pages}", "noop"))
        if page < pages - 1: pr.append(B(T("next"), f"err:page:{page + 1}"))
        rows.append(pr)
    rows.append([B(T("clear"), "err:clear"), B(T("back_to_panel"), "menu:main")])
    await panel(txt, kb_(*rows), page_tag=f"errors:{page}")

async def show_cfg():
    cfg = _load(CFG_FILE, DEFAULT_CFG); lang = _get_lang()
    txt = head("⚙️", "cfg_title")
    txt += mrow("🌐", "cfg_lang", (T("cfg_lang_fa") if lang == "fa" else T("cfg_lang_en"))) + "\n"
    txt += mrow("⏱", "cfg_join_delay", cfg.get("join_delay", DEFAULT_CFG["join_delay"])) + "\n"
    txt += mrow("🌊", "cfg_wave_size", cfg.get("wave_size", DEFAULT_CFG["wave_size"])) + "\n"
    txt += mrow("📦", "cfg_extract", cfg.get("extract_limit", DEFAULT_CFG["extract_limit"])) + "\n"
    txt += mrow("⏸", "cfg_wait", cfg.get("wait_for_links_sec", DEFAULT_CFG["wait_for_links_sec"])) + "\n"
    auto = int(cfg.get("auto_join_linkdoni", 1)); lst = int(cfg.get("listener", 1))
    txt += mrow("🔁", "cfg_auto_join", (T("on") if auto else T("off"))) + "\n"
    txt += mrow("👂", "cfg_listener", (T("on") if lst else T("off")))
    lang_btn = f"🌐 {T('cfg_lang')}: {'🇮🇷 ' + T('cfg_lang_fa') if lang=='fa' else '🇬🇧 ' + T('cfg_lang_en')}"
    rows = [
        [B(lang_btn, "cfg:lang")],
        [B(T("cfg_join_delay"), "cfg:set:join_delay"), B(T("cfg_wave_size"), "cfg:set:wave_size")],
        [B(T("cfg_extract"), "cfg:set:extract_limit"), B(T("cfg_wait"), "cfg:set:wait_for_links_sec")],
        [B(T("toggle_off") if auto else T("toggle_on"), "cfg:toggle_autojoin")],
        [B(T("toggle_off") if lst else T("toggle_on"), "cfg:toggle_listener")],
        nav(),
    ]
    await panel(txt, kb_(*rows), page_tag="cfg")

# ═══════════════ SEND WIZARD ═══════════════
def _send_conv(cid):
    c = get_conv(cid)
    if "send" not in c:
        c["send"] = {"step": "accounts", "accounts": [], "payload": None,
                     "target": "both", "max": 0, "auto_left": False,
                     "edit_delay_enabled": False, "edit_delay_seconds": 3.0,
                     "edit_delay_random": False, "edit_delay_min": 2.0, "edit_delay_max": 6.0,
                     "placeholder_text": "سلام", "placeholder_random": False,
                     "placeholder_list": "سلام,درود",
                     "multi_step_edit": False, "multi_step_middle": "Hi",
                     "attach_file": "", "groups_only": True,
                     "infinite_loop": False, "loop_delay": 3.0, "rescan_targets": True}
    return c["send"]

def _send_summary(s):
    accs = s.get("accounts") or []; all_a = list_accounts()
    if "all" in accs: al = f"{T('all')} ({len(all_a)})"
    elif not accs: al = "—"
    else:
        names = [get_account(i).get("name", "?") for i in accs[:2] if get_account(i)]
        al = "، ".join(names) + (f" +{len(accs) - 2}" if len(accs) > 2 else "")
    p = s.get("payload")
    tgt = {"pv": T("send_target_pv"), "groups": T("send_target_gr"), "both": T("send_target_both")}.get(s.get("target", "both"), "?")
    mx = s.get("max", 0) or 0
    ed = "🟢" if s.get("edit_delay_enabled") else "⚪"
    af = "🟢" if s.get("attach_file") else "⚪"
    inf = "🔁" if s.get("infinite_loop") else "⚪"
    return (f"\n👤 {esc(al)}\n✉️ " + (f"«{esc(short(p.get('text'), 30))}»" if p else "—") +
            f"\n🎯 {esc(tgt)}   ·   🔢 {mx if mx else '∞'}\n🎭 {T('send_edit')}: {ed}   ·   📎: {af}   ·   {T('send_infinite')}: {inf}")

async def send_step_accounts(cid, s):
    accounts = list_accounts()
    if not accounts: return await panel(T("jl_no_account"), kb_([B(f"➕ {T('add_account')}", "acc:add")], nav()), page_tag="send:1")
    sel = set(s.get("accounts") or []); all_sel = "all" in sel
    btns = [B(SEL((all_sel or aid in sel), short(a.get('name', '?'), 14)), f"send:acc:{aid}") for aid, a in accounts.items()]
    rows = grid(btns)
    rows.append([B(T("all") if not all_sel else T("cancel"), "send:accall"), B(T("next"), "send:accnext")])
    rows.append([B(f"« {T('cancel')}", "send:cancel")])
    await panel(head("📤", "send", dots(1, 4)) + T("send_step1") + _send_summary(s), kb_(*rows), page_tag="send:1")

async def send_step_compose(cid, s):
    txt = head("📤", "send", dots(2, 4)) + T("send_step2") + _send_summary(s)
    rows = []
    if s.get("payload"): rows.append([B(T("send_custom"), "send:recompose"), B(T("next"), "send:composenext")])
    rows.append([B(f"« {T('back')}", "send:prev"), B(T("cancel"), "send:cancel")])
    await panel(txt, kb_(*rows), page_tag="send:2")

async def send_step_target(cid, s):
    t = s.get("target", "both")
    mk = lambda k, l: B(SEL(t == k, l), f"send:tgt:{k}")
    ed_on = bool(s.get("edit_delay_enabled", False)); ed_sec = s.get("edit_delay_seconds", 3.0)
    grp_only = bool(s.get("groups_only", True)); inf_on = bool(s.get("infinite_loop", False))
    ld = s.get("loop_delay", 3.0); rs = bool(s.get("rescan_targets", True))
    af = s.get("attach_file") or ""
    rows = [[mk("pv", T("send_target_pv")), mk("groups", T("send_target_gr")), mk("both", T("send_target_both"))],
            [B(SEL(grp_only, T("send_grp_only")), "send:toggle_groups_only")],
            [B(SEL(inf_on, T("send_infinite")), "send:toggle_infinite")],
            [B(f"⏱ {T('send_loop_delay')}: {ld}s", "send:loop_delay")],
            [B(SEL(rs, T("send_rescan")), "send:toggle_rescan")],
            [B(SEL(ed_on, T("send_edit")), "send:toggle_edit")],
            [B(f"⏱ {ed_sec}s", "send:edit_sec"), B(T("send_random"), "send:toggle_edit_rand")],
            [B(f"💬 {esc(short(s.get('placeholder_text', 'سلام'), 10))}", "send:edit_ph"), B(T("send_ph_list"), "send:toggle_ph_rand")],
            [B(SEL(s.get("multi_step_edit"), T("send_multi")), "send:toggle_multi")],
            [B(f"📎 {T('send_attach')}: {esc(short(os.path.basename(af), 15) if af else '—')}", "send:attach")],
            [B(SEL(s.get("auto_left"), T("send_auto_left")), "send:toggle_auto_left")],
            [B(T("next"), "send:tgtnext")],
            [B(f"« {T('back')}", "send:prev"), B(T("cancel"), "send:cancel")]]
    await panel(head("📤", "send", dots(3, 4)) + T("send_step3") + _send_summary(s), kb_(*rows), page_tag="send:3")

async def send_step_max(cid, s):
    mx = s.get("max", 0)
    mk = lambda n: B(SEL(mx == n, str(n)), f"send:max:{n}")
    rows = [[mk(50), mk(100), mk(500)], [mk(1000), mk(2000), mk(5000)],
            [B(SEL(mx == 0, T("send_unlimited")), "send:max:0"), B(T("send_custom"), "send:max:custom")],
            [B(T("confirm"), "send:maxnext")],
            [B(f"« {T('back')}", "send:prev"), B(T("cancel"), "send:cancel")]]
    await panel(head("📤", "send", dots(4, 4)) + T("send_step4") + _send_summary(s), kb_(*rows), page_tag="send:4")

async def send_step_confirm(cid, s):
    accounts = list_accounts(); sel = s.get("accounts") or []
    if "all" in sel: sel = list(accounts.keys())
    if not sel: s["step"] = "accounts"; return await panel(T("empty"), kb_(nav()), page_tag="send:1")
    if not s.get("payload"): s["step"] = "compose"; return await panel(T("empty"), kb_(nav()), page_tag="send:2")
    extra = ""
    if s.get("infinite_loop"): extra = f"\n🔁 <b>{T('send_infinite')}</b>  ·  ⏱ {s.get('loop_delay', 3)}s"
    await panel(head("📤", "confirm") + _send_summary(s) + extra,
                kb_([B(T("start"), "send:go")],
                    [B(T("send_custom"), "send:back_edit"), B(T("cancel"), "send:cancel")]), page_tag="send:confirm")

async def show_send_step(cid):
    s = _send_conv(cid); step = s["step"]
    if step == "accounts": await send_step_accounts(cid, s)
    elif step == "compose": await send_step_compose(cid, s)
    elif step == "target": await send_step_target(cid, s)
    elif step == "max": await send_step_max(cid, s)
    elif step == "confirm": await send_step_confirm(cid, s)

# ═══════════════ JOINER UI ═══════════════
def _jl_conv(cid):
    c = get_conv(cid)
    if "jl" not in c:
        c["jl"] = {"step": "account", "accounts": [], "max_join": 0, "speed": "fast", "groups_only": True}
    return c["jl"]

async def jl_step_account(cid, s):
    accounts = list_accounts()
    if not accounts: return await panel(T("jl_no_account"), kb_([B(f"➕ {T('add_account')}", "acc:add")], nav()), page_tag="jl:1")
    sel = set(s.get("accounts") or [])
    rows = grid([B(SEL(aid in sel, short(a.get('name', '?'), 14)), f"jl:acc:{aid}") for aid, a in accounts.items()])
    rows.append([B(T("next"), "jl:next")]); rows.append([B(T("back_to_panel"), "menu:main")])
    await panel(head("🤝", "joiner", dots(1, 3)) + f"{T('jl_select')}  <b>{len(sel)}</b>", kb_(*rows), page_tag="jl:1")

async def jl_step_settings(cid, s):
    speed = s.get("speed", "fast"); lds = load_link_donies()
    lbl = next((T(l) for k, l, _ in JL_SPEEDS if k == speed), "—")
    grp = T("on") if s.get("groups_only", True) else T("off")
    txt = head("🤝", "joiner", dots(2, 3)) + mrow("🚀", "jl_speed", lbl) + "\n" + mrow("📡", "jl_ld", len(lds)) + "\n" + mrow("👥", "jl_grp_only", grp)
    rows = grid([B(SEL(speed == k, T(l)), f"jl:speed:{k}") for k, l, _ in JL_SPEEDS])
    rows.append([B(f"📡 {T('jl_ld')} ({len(lds)})", "jl:linkdonies")])
    rows.append([B(SEL(s.get("groups_only", True), T("jl_grp_only")), "jl:toggle_groups_only")])
    rows.append([B(T("next"), "jl:next")]); rows.append(nav("jl:back"))
    await panel(txt, kb_(*rows), page_tag="jl:2")

async def jl_step_max(cid, s):
    mx = s.get("max_join", 0)
    mk = lambda n: B(SEL(mx == n, str(n)), f"jl:max:{n}")
    txt = head("🤝", "joiner", dots(3, 3)) + f"{T('jl_max')}: <b>{mx if mx else '∞'}</b>"
    rows = [[mk(50), mk(100), mk(200)], [mk(500), mk(1000), mk(2000)], [B(T("send_custom"), "jl:max:custom")]]
    if mx: rows.append([B(T("start"), "jl:go")])
    rows.append(nav("jl:back"))
    await panel(txt, kb_(*rows), page_tag="jl:3")

async def show_jl_step(cid):
    s = _jl_conv(cid)
    if s["step"] == "account": await jl_step_account(cid, s)
    if s["step"] == "settings": await jl_step_settings(cid, s)
    if s["step"] == "max": await jl_step_max(cid, s)

# ═══════════════ LEFTER UI ═══════════════
def _lf_conv(cid):
    c = get_conv(cid)
    if "lf" not in c: c["lf"] = {"step": "account", "accounts": [], "mode": "all", "delay": 0.8}
    return c["lf"]
def _lf_modes(): return [("all", "lf_mode_all"), ("groups", "lf_mode_groups"), ("channels", "lf_mode_channels"), ("closed", "lf_mode_closed")]

async def lf_step_account(cid, s):
    accounts = list_accounts()
    if not accounts: return await panel(T("jl_no_account"), kb_([B(f"➕ {T('add_account')}", "acc:add")], nav()), page_tag="lf:1")
    sel = set(s.get("accounts") or [])
    rows = grid([B(SEL(aid in sel, short(a.get('name', '?'), 14)), f"lf:acc:{aid}") for aid, a in accounts.items()])
    rows.append([B(T("next"), "lf:next")]); rows.append([B(T("back_to_panel"), "menu:main")])
    await panel(head("🚪", "lefter", dots(1, 3)) + f"{T('jl_select')}  <b>{len(sel)}</b>", kb_(*rows), page_tag="lf:1")

async def lf_step_mode(cid, s):
    mode = s.get("mode", "all")
    btns = [B(SEL(mode == k, T(l)), f"lf:mode:{k}") for k, l in _lf_modes()]
    rows = [[b] for b in btns]; rows.append([B(T("next"), "lf:next")]); rows.append(nav("lf:back"))
    await panel(head("🚪", "lefter", dots(2, 3)) + T("lf_mode"), kb_(*rows), page_tag="lf:2")

async def lf_step_delay(cid, s):
    d = s.get("delay", 0.8)
    mk = lambda n, l: B(SEL(abs(d - n) < 0.01, l), f"lf:delay:{n}")
    txt = head("🚪", "lefter", dots(3, 3)) + f"{T('lf_delay')}: <b>{d}s</b>"
    rows = [[mk(0.3, "🚀 0.3s"), mk(0.8, "⚡ 0.8s"), mk(1.5, "🐢 1.5s")], [mk(3.0, "🛡 3s")], [B(T("start"), "lf:go")], nav("lf:back")]
    await panel(txt, kb_(*rows), page_tag="lf:3")

async def show_lf_step(cid):
    s = _lf_conv(cid)
    if s["step"] == "account": await lf_step_account(cid, s)
    if s["step"] == "mode": await lf_step_mode(cid, s)
    if s["step"] == "delay": await lf_step_delay(cid, s)

# ═══════════════ TEMPLATES UI ═══════════════
async def show_at_menu():
    tpls = list_templates()
    txt = head("🎯", "at_title", len(tpls)) + f"<i>{T('at_desc')}</i>"
    rows = []
    for tid, t in list(tpls.items())[:8]:
        parts = []
        if t.get("channel", {}).get("title"): parts.append("🌐" if t.get("channel", {}).get("type") == "public" else "🔒")
        if t.get("profile", {}).get("first_name") or t.get("profile", {}).get("bio"): parts.append("📝")
        if int(t.get("joiner", {}).get("max_join", 0) or 0) > 0: parts.append("🤝")
        if t.get("sender", {}).get("text"): parts.append("📤")
        if t.get("pv", {}).get("items"): parts.append("💬")
        if t.get("lefter", {}).get("leave_mode"): parts.append("🚪")
        badge = " ".join(parts) or "∅"
        rows.append([B(f"🎯 {short(t.get('name', '?'), 16)}  ·  {badge}", f"at:{tid}:view")])
    rows.append([B(f"➕ {T('at_new')}", "at:new")]); rows.append(nav())
    await panel(txt, kb_(*rows), page_tag="at:menu")

async def show_at_view(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    ch = t.get("channel", {}); pr = t.get("profile", {}); jn = t.get("joiner", {}); sn = t.get("sender", {}); lf = t.get("lefter", {}); pv = t.get("pv", {})
    def bd(d, k): return "🟢" if d.get(k) else "⚪"
    def bdn(d, k): return "🟢" if int(d.get(k, 0) or 0) > 0 else "⚪"
    txt = head("🎯", t.get("name", "?"))
    txt += f"🏗 {T('at_channel')}: {bd(ch, 'title')}"
    if ch.get("title"): txt += f" <i>{esc(short(ch['title'], 20))}</i>"
    txt += f"\n📝 {T('at_profile')}: {bd(pr, 'first_name') or bd(pr, 'bio') or bd(pr, 'username')}"
    txt += f"\n🤝 {T('at_joiner')}: {bdn(jn, 'max_join')}"
    if int(jn.get('max_join', 0) or 0) > 0: txt += f" <i>({jn['max_join']})</i>"
    txt += f"\n📤 {T('at_sender')}: {bd(sn, 'text')}"
    txt += f"\n💬 {T('at_pv')}: {'🟢' if pv.get('enabled') else '⚪'}  ·  {len(pv.get('items') or [])}"
    txt += f"\n🚪 {T('at_lefter')}: 🟢 <i>{lf.get('leave_mode', '?')}</i>"
    rows = grid([B(T("at_channel"), f"at:{tid}:ch"), B(T("at_profile"), f"at:{tid}:pr"), B(T("at_joiner"), f"at:{tid}:jn"), B(T("at_sender"), f"at:{tid}:sn"), B(T("at_pv"), f"at:{tid}:pv"), B(T("at_lefter"), f"at:{tid}:lf"), B(T("at_rename"), f"at:{tid}:rename")])
    rows.append([B(T("at_run"), f"at:{tid}:run")]); rows.append([B(T("at_delete"), f"at:{tid}:del"), B(T("back_to_panel"), "menu:main")])
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:view")

async def show_at_channel(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    c = t.get("channel", {}); is_pub = c.get("type", "private") == "public"
    txt = head("🏗", "at_channel", t.get("name", "?"))
    txt += mrow("🔖", "type", (T("public") if is_pub else T("private"))) + "\n"
    txt += mrow("📝", "channel_title", c.get("title") or "—") + "\n"
    if is_pub: txt += mrow("🔤", "username", c.get("username") or "—") + "\n"
    txt += mrow("📖", "about", short(c.get("about", ""), 40) or "—") + "\n"
    txt += mrow("🖼", "photo", os.path.basename(c.get("photo_file", "")) or "—") + "\n"
    txt += f"\n<b>{T('vars')}</b>: <code>{{n}} {{rnd}} {{date}}</code>"
    rows = [[B(SEL(is_pub, T("public")), f"at:{tid}:chtype:public"), B(SEL(not is_pub, T("private")), f"at:{tid}:chtype:private")], [B(T("channel_title"), f"at:{tid}:chset:title")]]
    if is_pub: rows.append([B(T("username"), f"at:{tid}:chset:username")])
    rows.append([B(T("about"), f"at:{tid}:chset:about")]); rows.append([B(T("photo"), f"at:{tid}:chset:photo_file")]); rows.append(nav(f"at:{tid}:view"))
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:ch")

async def show_at_profile(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    p = t.get("profile", {})
    txt = head("📝", "at_profile", t.get("name", "?"))
    txt += mrow("👤", "name", p.get("first_name") or "—") + "\n"
    txt += mrow("👤", "last_name", p.get("last_name") or "—") + "\n"
    txt += mrow("🔤", "username", p.get("username") or "—") + "\n"
    txt += mrow("📖", "bio", short(p.get("bio", ""), 60) or "—") + "\n"
    txt += mrow("🖼", "photo", os.path.basename(p.get("photo_file", "")) or "—")
    rows = [[B(T("name"), f"at:{tid}:prset:first_name"), B(T("last_name"), f"at:{tid}:prset:last_name")], [B(T("username"), f"at:{tid}:prset:username"), B(T("bio"), f"at:{tid}:prset:bio")], [B(T("photo"), f"at:{tid}:prset:photo_file")], nav(f"at:{tid}:view")]
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:pr")

async def show_at_joiner(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    j = t.get("joiner", {}); spd = j.get("speed"); spd_lbl = next((T(l) for k, l, _ in JL_SPEEDS if k == spd), spd)
    txt = head("🤝", "at_joiner", t.get("name", "?"))
    txt += mrow("🎯", "jl_max", j.get("max_join", 0)) + "\n" + mrow("🚀", "jl_speed", spd_lbl) + "\n" + mrow("👥", "jl_grp_only", ("🟢" if j.get("groups_only", True) else "⚪"))
    rows = [[B(T("jl_max"), f"at:{tid}:jnset:max_join")]]
    rows += grid([B(SEL(spd == k, T(l)), f"at:{tid}:jnspeed:{k}") for k, l, _ in JL_SPEEDS])
    rows.append([B(SEL(j.get("groups_only", True), T("jl_grp_only")), f"at:{tid}:jntoggle_groups_only")]); rows.append(nav(f"at:{tid}:view"))
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:jn")

async def show_at_sender(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    s = t.get("sender", {})
    mode_labels = {"send_only": T("at_mode_only"), "join_send": T("at_mode_js"), "join_send_leave": T("at_mode_jsl")}
    ed_on = bool(s.get("edit_delay_enabled", False)); ed_sec = s.get("edit_delay_seconds", 3.0); ed_rand = bool(s.get("edit_delay_random", False))
    ph = s.get("placeholder_text", "سلام"); ph_rand = bool(s.get("placeholder_random", False)); ms_on = bool(s.get("multi_step_edit", False))
    af = s.get("attach_file") or ""; inf_on = bool(s.get("infinite_loop", False)); ld = s.get("loop_delay", 3.0); rs = bool(s.get("rescan_targets", True))
    txt = head("📤", "at_sender", t.get("name", "?"))
    txt += mrow("✉️", "text", short(s.get("text", ""), 50) or "—") + "\n"
    txt += mrow("🎯", "target", s.get("target", "?")) + "\n"
    txt += mrow("🔁", "mode", mode_labels.get(s.get("mode"), s.get("mode"))) + "\n"
    txt += mrow("🔢", "max", s.get("max_send", 0) or "∞") + "\n"
    txt += mrow("⏱", "delay", f"{s.get('delay', 1.5)}s") + "\n"
    txt += mrow("🎭", "send_edit", ("🟢" if ed_on else "⚪"))
    if ed_on: txt += f" 🎲" if ed_rand else f" {ed_sec}s"; txt += f"\n💬 <code>{esc(ph)}</code>"
    txt += f"\n🔁 {T('send_infinite')}: {'🟢' if inf_on else '⚪'}"
    if inf_on: txt += f"  ⏱ {ld}s"; txt += f"\n🔄 {T('send_rescan')}: {'🟢' if rs else '⚪'}"
    txt += f"\n📎 <code>{esc(os.path.basename(af) if af else '—')}</code>"
    rows = [
        [B(T("text"), f"at:{tid}:snset:text")],
        [B(T("target"), f"at:{tid}:snset:target"), B(T("max"), f"at:{tid}:snset:max_send")],
        [B(T("delay"), f"at:{tid}:snset:delay"), B(T("mode"), f"at:{tid}:snmode")],
        [B(SEL(inf_on, T("send_infinite")), f"at:{tid}:sntoggle_loop"), B(f"⏱ {ld}s", f"at:{tid}:snset_loop_delay")],
        [B(SEL(rs, T("send_rescan")), f"at:{tid}:sntoggle_rescan")],
        [B(SEL(ed_on, T("send_edit")), f"at:{tid}:snedit:toggle")],
        [B(f"⏱ {ed_sec}s", f"at:{tid}:snedit:sec"), B(f"💬 PH", f"at:{tid}:snedit:ph")],
        [B(SEL(ph_rand, T("send_ph_list")), f"at:{tid}:snedit:ph_rand"), B(SEL(ms_on, T("send_multi")), f"at:{tid}:snedit:multi_toggle")],
        [B(f"📎 {esc(os.path.basename(af) if af else T('add'))}", f"at:{tid}:snedit:file")],
        nav(f"at:{tid}:view"),
    ]
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:sn")

async def show_at_sender_mode(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    cur = t["sender"].get("mode", "send_only")
    opts = [("send_only", T("at_mode_only")), ("join_send", T("at_mode_js")), ("join_send_leave", T("at_mode_jsl"))]
    txt = head("🔁", "mode") + f"<b>{cur}</b>"
    rows = grid([B(SEL(cur == k, l), f"at:{tid}:snmode_set:{k}") for k, l in opts])
    rows.append(nav(f"at:{tid}:sn"))
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:snmode")

async def show_at_pv(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    pv = t.get("pv", {}); en = bool(pv.get("enabled")); mx = int(pv.get("max_replies", 1) or 0)
    items = pv.get("items") or []; apply_acc = bool(pv.get("apply_to_accounts", True))
    txt = head("💬", "at_pv", t.get("name", "?"))
    txt += mrow("📶", "pv_status", (T("pv_active") if en else T("pv_inactive"))) + "\n"
    txt += mrow("👥", "pv_max", (mx if mx else "∞")) + "\n"
    txt += mrow("⏱", "pv_delay", f"{pv.get('delay_seconds', 0)}s") + "\n"
    txt += mrow("🔄", "at_apply_acc", ("🟢" if apply_acc else "⚪")) + "\n"
    txt += mrow("📨", "pv_items", len(items)) + "\n\n"
    for i, it in enumerate(items, 1):
        k = it.get("kind", "text")
        if k == "text": txt += f"{i}. 💬 <code>{esc(short(it.get('text', ''), 40))}</code>\n"
        elif k == "file": txt += f"{i}. 📁 <code>{esc(os.path.basename(it.get('file_path', '?')))}</code>\n"
        elif k == "delay": txt += f"{i}. ⏸ {it.get('seconds', 3)}s\n"
    rows = [
        [B(T("toggle_off") if en else T("toggle_on"), f"at:{tid}:pv:toggle")],
        [B(f"{T('pv_max')}: {mx if mx else '∞'}", f"at:{tid}:pv:cycle_max"), B(T("pv_delay"), f"at:{tid}:pv:set_delay")],
        [B(T("pv_add_text"), f"at:{tid}:pv:add_text"), B(T("pv_add_file"), f"at:{tid}:pv:add_saved"), B(T("pv_add_delay"), f"at:{tid}:pv:add_delay")],
        [B(SEL(apply_acc, T("at_apply_acc")), f"at:{tid}:pv:toggle_apply")],
        [B(T("pv_list"), f"at:{tid}:pv:list")],
        nav(f"at:{tid}:view"),
    ]
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:pv")

async def show_at_pv_list(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    items = (t.get("pv") or {}).get("items") or []
    txt = head("📋", "pv_list", len(items))
    for i, it in enumerate(items, 1):
        k = it.get("kind", "text")
        if k == "text": txt += f"\n{i}. 💬 <code>{esc(short(it.get('text', ''), 60))}</code>"
        elif k == "file": txt += f"\n{i}. 📁 <code>{esc(os.path.basename(it.get('file_path', '?')))}</code>"
        elif k == "delay": txt += f"\n{i}. ⏸ {it.get('seconds', 3)}s"
    rows = [[B(f"{T('delete')} {i+1}", f"at:{tid}:pv:del:{i}")] for i in range(len(items))]
    rows.append([B(f"« {T('back')}", f"at:{tid}:pv")])
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:pv_list")

async def show_at_lefter(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    l = t.get("lefter", {})
    txt = head("🚪", "at_lefter", t.get("name", "?")) + f"🎯 {T('lf_mode')}: <b>{l.get('leave_mode', '?')}</b>"
    rows = []
    for k, lbl in _lf_modes(): rows.append([B(SEL(l.get("leave_mode") == k, T(lbl)), f"at:{tid}:lfset:{k}")])
    rows.append(nav(f"at:{tid}:view"))
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:lf")

async def show_at_run(tid, page=0):
    t = get_template(tid)
    if not t: return await show_at_menu()
    accounts = list_accounts(); items = list(accounts.items()); per = 6
    pages = max(1, -(-len(items) // per)); page = max(0, min(page, pages - 1)); chunk = items[page * per:(page + 1) * per]
    cid = STATE.get("owner"); conv = get_conv(cid) if cid else {}
    selected = set((conv.get("at_run") or {}).get("accounts") or [])
    rows = []
    for aid, a in chunk: rows.append([B(SEL(aid in selected, short(a.get('name', '?'), 20)), f"at:{tid}:run_acc:{aid}")])
    if pages > 1:
        pr = []
        if page > 0: pr.append(B(T("prev"), f"at:{tid}:run:{page - 1}"))
        pr.append(B(f"{page + 1}/{pages}", "noop"))
        if page < pages - 1: pr.append(B(T("next"), f"at:{tid}:run:{page + 1}"))
        rows.append(pr)
    rows.append([B(T("start"), f"at:{tid}:run_go")]); rows.append(nav(f"at:{tid}:view"))
    txt = head("🎯", "at_run_title", t.get("name", "?")) + f"{T('jl_selected')}: <b>{len(selected)}</b>"
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:run:{page}")

async def show_acc_at_menu(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    tpls = list_templates(); txt = head("🎯", "auto_tar", a.get("name", "?"))
    if not tpls: return await panel(txt + "\n\n" + T("empty"), kb_([B(f"➕ {T('at_new')}", "at:new"), B(T("back_to_panel"), "menu:main")]), page_tag=f"acc:at:{aid}")
    rows = [[B(f"🎯 {short(t.get('name', '?'), 22)}", f"acc:at:run:{aid}:{tid}")] for tid, t in list(tpls.items())[:10]]
    rows.append(nav(f"acc:view:{aid}"))
    await panel(txt, kb_(*rows), page_tag=f"acc:at:{aid}")

async def show_acc_lf(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    txt = head("🚪", "lefter", a.get("name", "?"))
    rows = [[B(T(lbl), f"acc:lf:go:{aid}:{k}")] for k, lbl in _lf_modes()]
    rows.append(nav(f"acc:view:{aid}"))
    await panel(txt, kb_(*rows), page_tag=f"acc:lf:{aid}")

# ═══════════════ MESSAGE HANDLER ═══════════════
async def _on_message_impl(update, context):
    if not authorized(update): return
    msg = update.message
    if msg is None: return
    cid = update.effective_chat.id
    conv = STATE["conv"].get(cid) or {}
    text = (msg.text or "").strip()

    if "acc" in conv and conv["acc"].get("step") == "login_pending":
        q = _pending_login.get(cid, {}).get("q")
        if q:
            try: q.put(text)
            except Exception: pass
        return

    if cid in _bulk_state:
        state = _bulk_state[cid]
        idx = state.get("current_idx", -1)
        if 0 <= idx < len(state["phones"]):
            phone = state["phones"][idx]
            st = state["states"].get(phone, {})
            if st.get("step") == "login":
                q = st.get("q")
                if q:
                    try: q.put(text)
                    except Exception: pass
                return

    if conv.get("bulk_wait"):
        conv.pop("bulk_wait")
        phones = [line.strip() for line in text.splitlines() if line.strip()]
        if not phones: return await ask("هیچ شماره‌ای یافت نشد. دوباره:")
        asyncio.create_task(bulk_login_start(cid, phones))
        return await panel("⏳ در حال ارسال کدها...", page_tag="bulk_wait")

    if conv.get("alias_edit"):
        aid = conv.pop("alias_edit")
        update_account(aid, alias=text[:50])
        await tg_send("✅ اسم مستعار ذخیره شد")
        return await show_account_detail(aid)

    if conv.get("chsend_text"):
        info = conv.pop("chsend_text"); aid = info["aid"]; idx = info["idx"]
        await panel("⏳ ارسال...", page_tag=f"chview:{aid}:{idx}")
        a = get_account(aid); chs = get_stored_channels(aid)
        if not a or idx >= len(chs): return await panel(T("not_found"), kb_(nav()), page_tag="main")
        ch = chs[idx]; ok = False; msg_r = ""
        try:
            cli = SafeRubikaClient(name=a.get("session_name"), _aid=aid)
            async with cli as bot:
                ok, msg_r = await rb_send_text(bot, ch.get("guid"), text)
        except Exception as e: msg_r = _fmt_error(e)
        if ok:
            return await panel(head("✅", "send") + f"💬 <code>{esc(text[:100])}</code>",
                               kb_([B(f"« {T('back')}", f"ch:view:{aid}:{idx}")]), page_tag=f"chview:{aid}:{idx}")
        return await panel(f"❌ <code>{esc(str(msg_r)[:400])}</code>",
                           kb_([B(f"« {T('back')}", f"ch:view:{aid}:{idx}")]), page_tag=f"chview:{aid}:{idx}")

    if conv.get("chsend_media"):
        info = conv["chsend_media"]; aid = info["aid"]; idx = info["idx"]
        force_kind = info.get("force_kind")
        media = _extract_media(msg)
        if not media: return await ask("عکس/ویدیو/فایل بفرست:")
        await panel("⏳ آپلود...", page_tag=f"chview:{aid}:{idx}")
        try: fpath = await _download_tg_file(media, aid, "chsend")
        except Exception as e: return await ask(f"❌ دانلود: {str(e)[:100]}")
        actual = _detect_kind_from_path(fpath)
        kind = actual if actual in ("Image","Video","Music","Voice") else (force_kind or "File")
        cap = text.strip() or ""
        conv.pop("chsend_media", None)
        a = get_account(aid); chs = get_stored_channels(aid)
        if not a or idx >= len(chs): return await panel(T("not_found"), kb_(nav()), page_tag="main")
        ch = chs[idx]; ok = False; msg_r = ""
        try:
            cli = SafeRubikaClient(name=a.get("session_name"), _aid=aid)
            async with cli as bot:
                ok, msg_r = await rb_send_file(bot, ch.get("guid"), fpath, cap, kind)
        except Exception as e: msg_r = _fmt_error(e)
        if ok:
            label = {"Image":"🖼 عکس","Video":"🎬 ویدیو","Music":"🎵 موزیک",
                     "Voice":"🎙 ویس","File":"📄 فایل"}.get(kind,"📄 فایل")
            body = head("✅", "send") + f"{label} ارسال شد"
            if cap: body += f"\n💬 <code>{esc(cap[:100])}</code>"
            return await panel(body, kb_([B(f"« {T('back')}", f"ch:view:{aid}:{idx}")]),
                               page_tag=f"chview:{aid}:{idx}")
        return await panel(f"❌ <code>{esc(str(msg_r)[:400])}</code>",
                           kb_([B(f"« {T('back')}", f"ch:view:{aid}:{idx}")]), page_tag=f"chview:{aid}:{idx}")

    if conv.get("pv_acc_wait"):
        w = conv.pop("pv_acc_wait"); aid = w.get("aid"); kind = w.get("kind")
        cfg = _load_pv_account(aid); items = cfg.get("items") or []
        if kind == "delay":
            try: cfg["delay_seconds"] = max(0, int(re.sub(r"[^\d]", "", text) or "0"))
            except Exception: cfg["delay_seconds"] = 0
        elif kind == "poll":
            try: cfg["poll_seconds"] = max(2, int(re.sub(r"[^\d]", "", text) or "3"))
            except Exception: cfg["poll_seconds"] = 3
        elif kind == "add_text":
            items.append({"kind": "text", "text": text}); cfg["items"] = items
        elif kind == "add_delay_sec":
            try: sec = max(0, int(re.sub(r"[^\d]", "", text) or "3"))
            except Exception: sec = 3
            items.append({"kind": "delay", "seconds": sec}); cfg["items"] = items
        _save_pv_account(aid, cfg)
        await tg_send("✅")
        return await show_pv_account_menu(aid)

    if conv.get("pv_acc_save_msg"):
        w = conv.pop("pv_acc_save_msg"); aid = w.get("aid")
        media = _extract_media(msg); caption = text or ""
        if not media and not caption: return await ask("پیام یا فایل بفرست:")
        local_path = None
        if media:
            try: local_path = await _download_tg_file(media, "pv", "pvitem")
            except Exception: pass
        cfg = _load_pv_account(aid); items = cfg.get("items") or []
        if local_path: items.append({"kind": "file", "file_path": local_path, "caption": caption})
        else: items.append({"kind": "text", "text": caption})
        cfg["items"] = items; _save_pv_account(aid, cfg)
        await tg_send("✅")
        return await show_pv_account_menu(aid)

    if conv.get("pv_tpl_wait"):
        w = conv.pop("pv_tpl_wait"); tid = w.get("tid"); kind = w.get("kind")
        t = get_template(tid)
        if not t: return await show_at_menu()
        pv = t.setdefault("pv", {}); items = pv.get("items") or []
        if kind == "delay":
            try: pv["delay_seconds"] = max(0, int(re.sub(r"[^\d]", "", text) or "0"))
            except Exception: pv["delay_seconds"] = 0
            update_template(tid, "pv", "delay_seconds", pv["delay_seconds"])
        elif kind == "add_text":
            items.append({"kind": "text", "text": text}); update_template(tid, "pv", "items", items)
        elif kind == "add_delay_sec":
            try: sec = max(0, int(re.sub(r"[^\d]", "", text) or "3"))
            except Exception: sec = 3
            items.append({"kind": "delay", "seconds": sec}); update_template(tid, "pv", "items", items)
        await tg_send("✅")
        return await show_at_pv(tid)

    if conv.get("pv_tpl_save_msg"):
        w = conv.pop("pv_tpl_save_msg"); tid = w.get("tid")
        t = get_template(tid)
        if not t: return await show_at_menu()
        media = _extract_media(msg); caption = text or ""
        if not media and not caption: return await ask("پیام یا فایل بفرست:")
        local_path = None
        if media:
            try: local_path = await _download_tg_file(media, "pvtpl", "pvtpl")
            except Exception: pass
        pv = t.setdefault("pv", {}); items = pv.get("items") or []
        if local_path: items.append({"kind": "file", "file_path": local_path, "caption": caption})
        else: items.append({"kind": "text", "text": caption})
        update_template(tid, "pv", "items", items)
        await tg_send("✅")
        return await show_at_pv(tid)

    if conv.get("accphoto_upload"):
        info = conv.pop("accphoto_upload"); aid = info["aid"]
        media = _extract_media(msg)
        if not media: return await ask(T("prof_no_photo"))
        try: fpath = await _download_tg_file(media, aid, "accphoto")
        except Exception as e: return await ask(f"❌ {str(e)[:100]}")
        a = get_account(aid)
        if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
        await panel(f"⏳ {T('prof_uploading')}", page_tag=f"accphoto:{aid}")
        ok = False; msg_r = ""
        try:
            cli = SafeRubikaClient(name=a.get("session_name"), _aid=aid)
            async with cli as bot:
                me = await bot.get_me()
                my_guid = _extract_field(me, "user_guid")
                if not my_guid:
                    u = _extract_field(me, "user")
                    my_guid = _extract_field(u, "user_guid") if u is not None else None
                ok, msg_r = await rb_upload_avatar(bot, my_guid, fpath)
        except Exception as e:
            msg_r = _fmt_error(e)
        await tg_send("✅" if ok else f"❌ {msg_r[:150]}")
        return await show_acc_photo_menu(aid)

    if conv.get("chphoto_upload"):
        info = conv.pop("chphoto_upload"); aid = info["aid"]; idx = info["idx"]
        media = _extract_media(msg)
        if not media: return await ask(T("prof_no_photo"))
        try: fpath = await _download_tg_file(media, aid, "chphoto")
        except Exception as e: return await ask(f"❌ {str(e)[:100]}")
        a = get_account(aid); chs = get_stored_channels(aid)
        if not a or idx >= len(chs): return await panel(T("not_found"), kb_(nav()), page_tag="main")
        ch = chs[idx]
        await panel(f"⏳ {T('prof_uploading')}", page_tag=f"chphoto:{aid}:{idx}")
        ok = False; msg_r = ""
        try:
            cli = SafeRubikaClient(name=a.get("session_name"), _aid=aid)
            async with cli as bot:
                ok, msg_r = await rb_upload_avatar(bot, ch.get("guid"), fpath)
        except Exception as e:
            msg_r = _fmt_error(e)
        await tg_send("✅" if ok else f"❌ {msg_r[:150]}")
        return await show_ch_photo_menu(aid, idx)

    if conv.get("chfile_upload") and conv["chfile_upload"].get("step") == "wait_file":
        info = conv["chfile_upload"]; aid = info["aid"]; idx = info["idx"]
        media = _extract_media(msg); fpath = None
        if media:
            try: fpath = await _download_tg_file(media, aid, "chfile")
            except Exception as e: return await ask(f"❌ {str(e)[:100]}")
        elif text and os.path.exists(text.strip()): fpath = text.strip()
        if not fpath: return await ask(T("ch_file_q"))
        info["file_path"] = fpath; info["step"] = "wait_caption"; conv["chfile_upload"] = info
        return await ask(T("ch_caption_q"))

    if conv.get("chfile_upload") and conv["chfile_upload"].get("step") == "wait_caption":
        info = conv.pop("chfile_upload"); aid = info["aid"]; idx = info["idx"]
        fpath = info.get("file_path"); caption = text.strip()
        a = get_account(aid); chs = get_stored_channels(aid)
        if not a or idx >= len(chs): return await panel(T("not_found"), kb_(nav()), page_tag="main")
        ch = chs[idx]
        await panel(f"⏳ {T('loading')}", page_tag=f"chview:{aid}:{idx}")
        ok = False; msg_r = ""
        try:
            cli = SafeRubikaClient(name=a.get("session_name"), _aid=aid)
            async with cli as bot:
                kind = _detect_kind_from_path(fpath)
                ok, msg_r = await rb_send_file(bot, ch.get("guid"), fpath, caption, kind)
        except Exception as e:
            msg_r = _fmt_error(e)
        await tg_send("✅" if ok else f"❌ {msg_r[:150]}")
        return await show_channel_view(aid, idx)

    if conv.get("at_field_photo"):
        info = conv.pop("at_field_photo"); tid = info["tid"]; section = info["section"]; field = info["field"]
        media = _extract_media(msg)
        if not media: return await ask(T("prof_no_photo"))
        try: fpath = await _download_tg_file(media, "tpl", "tplfile")
        except Exception as e: return await ask(f"❌ {str(e)[:100]}")
        update_template(tid, section, field, fpath)
        await tg_send("✅")
        if section == "channel": return await show_at_channel(tid)
        if section == "profile": return await show_at_profile(tid)
        if section == "sender": return await show_at_sender(tid)
        return await show_at_view(tid)

    if cid in _TMP_EDIT:
        info = _TMP_EDIT.pop(cid)
        if info["kind"] == "at_field":
            tid = info["tid"]; section = info["section"]; field = info["field"]; value = text
            if field in ("max_join", "max_send"):
                try: value = int(re.sub(r"[^\d]", "", text) or "0")
                except Exception: value = 0
            elif field == "delay":
                try: value = float(re.sub(r"[^\d\.]", "", text) or "1.5")
                except Exception: value = 1.5
            elif field == "edit_delay_seconds":
                try: value = max(0.0, float(re.sub(r"[^\d\.]", "", text) or "3.0"))
                except Exception: value = 3.0
            elif field == "loop_delay":
                try: value = max(0.5, float(re.sub(r"[^\d\.]", "", text) or "3.0"))
                except Exception: value = 3.0
            update_template(tid, section, field, value)
            await tg_send("✅")
            if section == "meta": return await show_at_view(tid)
            if section == "channel": return await show_at_channel(tid)
            if section == "profile": return await show_at_profile(tid)
            if section == "joiner": return await show_at_joiner(tid)
            if section == "sender": return await show_at_sender(tid)
            if section == "lefter": return await show_at_lefter(tid)

    if conv.get("send_edit_wait"):
        kind = conv.pop("send_edit_wait"); s = _send_conv(cid)
        if kind == "sec":
            try: s["edit_delay_seconds"] = max(0.0, float(re.sub(r"[^\d\.]", "", text) or "3.0"))
            except Exception: s["edit_delay_seconds"] = 3.0
        elif kind == "ph": s["placeholder_text"] = text or "سلام"
        elif kind == "loop_delay":
            try: s["loop_delay"] = max(0.5, float(re.sub(r"[^\d\.]", "", text) or "3.0"))
            except Exception: s["loop_delay"] = 3.0
        return await show_send_step(cid)

    if conv.get("send_file_upload"):
        conv.pop("send_file_upload"); s = _send_conv(cid); media = _extract_media(msg)
        if media:
            try: fpath = await _download_tg_file(media, "send", "sendfile"); s["attach_file"] = fpath
            except Exception as e: return await ask(f"❌ {str(e)[:100]}")
        elif text and os.path.exists(text.strip()): s["attach_file"] = text.strip()
        else: return await ask(T("send_attach_q"))
        await tg_send("✅")
        return await show_send_step(cid)

    if conv.get("cfg_wait"):
        key = conv.pop("cfg_wait"); cfg = _load(CFG_FILE, DEFAULT_CFG)
        try:
            v = text.strip(); cfg[key] = float(v) if "." in v else int(v); _save(CFG_FILE, cfg); await tg_send("✅")
        except Exception: await tg_send(T("cfg_invalid"))
        return await show_cfg()

    if conv.get("ld_wait") == "url":
        back = conv.pop("ld_back", "jl:back_to_settings"); url = text.strip()
        if url.startswith("rubika.ir"): url = "https://" + url
        if add_link_doni(url): await tg_send("✅")
        else: await tg_send("ℹ️")
        return await show_linkdonies(back)

    if conv.get("setlink"):
        info = conv.pop("setlink"); aid = info["aid"]; idx = info["idx"]; url = text.strip()
        if not url: return await ask(T("ch_link_q"))
        if not url.startswith("http"): url = "https://" + url
        update_channel_field(aid, idx, "join_link", url); await tg_send("✅")
        return await show_channel_view(aid, idx)

    if conv.get("chsend") and conv["chsend"].get("step") == "compose":
        info = conv.pop("chsend"); aid = info["aid"]; idx = info["idx"]
        await panel(f"⏳ {T('loading')}", page_tag=f"chview:{aid}:{idx}")
        a = get_account(aid); chs = get_stored_channels(aid)
        if not a or idx >= len(chs): return await panel(T("not_found"), kb_(nav()), page_tag="main")
        ch = chs[idx]; ok = False; msg_r = ""
        try:
            cli = SafeRubikaClient(name=a.get("session_name"), _aid=aid)
            async with cli as bot:
                ok, msg_r = await rb_send_text(bot, ch.get("guid"), text)
        except Exception as e:
            msg_r = _fmt_error(e)
        if ok:
            return await panel(head("✅", "send") + f"💬 <code>{esc(text[:100])}</code>", kb_([B(f"« {T('back')}", f"ch:view:{aid}:{idx}")]), page_tag=f"chview:{aid}:{idx}")
        return await panel(f"❌ <code>{esc(str(msg_r)[:400])}</code>", kb_([B(f"« {T('back')}", f"ch:view:{aid}:{idx}")]), page_tag=f"chview:{aid}:{idx}")

    if conv.get("chnew"):
        info = conv["chnew"]; step = info.get("step"); aid = info.get("aid")
        a = get_account(aid)
        if not a:
            conv.pop("chnew", None)
            return await panel(T("not_found"), kb_(nav()), page_tag="main")
        if step == "title":
            title = text.strip()
            if not title: return await ask(T("ch_new_name_q"))
            info["title"] = title[:60]; info["step"] = "type"; conv["chnew"] = info
            return await show_ch_new_type(aid, title)
        if step == "username":
            title = info.get("title"); uname = text.lstrip("@").strip()
            if not uname: return await ask(T("ch_new_user_q"))
            conv.pop("chnew", None)
            await panel(f"⏳ {T('ch_creating')} <b>{esc(title)}</b>", page_tag="chnew_run")
            ok = False; msg_r = ""; ch_guid = None; uname_ok = False
            try:
                cli = SafeRubikaClient(name=a.get("session_name"), _aid=aid)
                async with cli as bot:
                    ok, ch_guid, msg_r = await rb_create_channel(bot, title)
                    if ok and ch_guid:
                        await asyncio.sleep(2)
                        uname_ok, umsg = await rb_set_channel_username(bot, ch_guid, uname)
                        if not uname_ok: msg_r = f"username: {umsg}"
            except Exception as e: msg_r = _fmt_error(e)
            if ok and ch_guid:
                add_channel_to_storage(aid, {"title": title, "guid": ch_guid, "type": "public",
                    "username": uname if uname_ok else "", "created": int(time.time())})
                if uname_ok:
                    body = head("✅", "ch_created") + f"📝 {esc(title)}\n🔗 @{esc(uname)}"
                else:
                    body = (head("⚠️", "ch_created") + f"📝 {esc(title)}\n"
                            f"یوزرنیم تنظیم نشد: <code>{esc(str(msg_r)[:200])}</code>")
                return await panel(body,
                                   kb_([B(f"⚙️ {T('my_channels')}", f"chlist:show:{aid}:0")],
                                       [B(f"« {T('back')}", f"ch:menu:{aid}")]), page_tag=f"ch_menu:{aid}")
            return await panel(f"❌ <code>{esc(str(msg_r)[:300])}</code>",
                               kb_([B(f"« {T('back')}", f"ch:menu:{aid}")]), page_tag=f"ch_menu:{aid}")

    if conv.get("chprof_edit"):
        info = conv.pop("chprof_edit"); aid = info["aid"]; idx = info["idx"]; field = info["field"]
        a = get_account(aid); chs = get_stored_channels(aid)
        if not a or idx >= len(chs): return await panel(T("not_found"), kb_(nav()), page_tag="main")
        ch = chs[idx]; guid = ch.get("guid")
        await panel(f"⏳ {T('loading')}", page_tag=f"chprof:{aid}:{idx}")
        ok = False; msg_r = ""
        try:
            cli = SafeRubikaClient(name=a.get("session_name"), _aid=aid)
            async with cli as bot:
                if field == "title":
                    ok, msg_r = await rb_edit_channel(bot, guid, title=text[:60])
                    if ok: update_channel_field(aid, idx, "title", text[:60])
                elif field == "desc":
                    ok, msg_r = await rb_edit_channel(bot, guid, description=text)
                    if ok: update_channel_field(aid, idx, "description", text)
                elif field == "user":
                    uname = text.lstrip("@").strip()
                    ok, msg_r = await rb_set_channel_username(bot, guid, uname)
                    if ok:
                        update_channel_field(aid, idx, "username", uname)
                        update_channel_field(aid, idx, "type", "public")
        except Exception as e:
            msg_r = _fmt_error(e)
        await tg_send("✅" if ok else f"❌ {msg_r[:150]}")
        return await show_ch_profile(aid, idx)

    if conv.get("prof_field"):
        info = conv.pop("prof_field"); field = info["field"]; aid = info["aid"]
        a = get_account(aid)
        if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
        await panel(f"⏳ {T('loading')}", page_tag=f"prof:{aid}")
        ok = False; msg_r = ""
        try:
            cli = SafeRubikaClient(name=a.get("session_name"), _aid=aid)
            async with cli as bot:
                if field in ("first", "last", "about"):
                    kw = {}
                    if field == "first": kw["first_name"] = text
                    elif field == "last": kw["last_name"] = text
                    elif field == "about": kw["bio"] = text
                    ok, msg_r = await rb_update_profile(bot, **kw)
                elif field == "username": ok, msg_r = await rb_update_username(bot, text)
        except Exception as e:
            msg_r = _fmt_error(e)
        if ok: return await panel(head("✅", "profile") + f"<code>{esc(str(msg_r)[:200])}</code>", kb_([B(f"« {T('back')}", f"prof:menu:{aid}")]), page_tag=f"prof:{aid}")
        return await panel(f"❌ <code>{esc(str(msg_r)[:300])}</code>", kb_([B(f"« {T('back')}", f"prof:menu:{aid}")]), page_tag=f"prof:{aid}")

    if "jl_wait" in conv:
        conv.pop("jl_wait"); jl = get_conv(cid).get("jl") or {}
        try: jl["max_join"] = max(1, int(re.sub(r"[^\d]", "", text)))
        except Exception: return await ask(T("jl_max_q"))
        get_conv(cid)["jl"] = jl; return await jl_step_max(cid, jl)

    if "send_wait" in conv:
        conv.pop("send_wait"); s = _send_conv(cid)
        try: s["max"] = max(0, int(re.sub(r"[^\d]", "", text)))
        except Exception: return await ask(T("send_max_q"))
        return await show_send_step(cid)

    if "send" in conv:
        s = conv["send"]
        if s.get("step") == "compose":
            if not text: return await ask(T("send_step2"))
            s["payload"] = {"text": text}; s["step"] = "target"
            return await show_send_step(cid)

    if "acc" in conv:
        a = conv["acc"]; step = a.get("step")
        if step == "phone":
            try: ph = normalize_phone(text)
            except Exception as e: return await ask(T("invalid_phone"), note=str(e)[:150])
            a["phone"] = ph
            a["step"] = "login_pending"
            await _login_panel_sending(ph)
            asyncio.create_task(login_via_rubpy(cid, ph))
            return

_on_message_orig = _on_message_impl
async def on_message(update, context):
    cid = None; had_conv = False; pv_keep = False
    try:
        cid = update.effective_chat.id
        had_conv = bool(STATE["conv"].get(cid)) or (cid in _TMP_EDIT)
        c = STATE["conv"].get(cid) or {}
        c_acc = c.get("acc") or {}
        if (c.get("pv_save_msg") or c.get("pv_acc_save_msg") or c.get("pv_tpl_save_msg")
            or c.get("chsend_media") or c.get("chsend_text") or c.get("chfile_upload")
            or c.get("accphoto_upload") or c.get("chphoto_upload")
            or c_acc.get("step") == "login_pending"
            or cid in _pending_login or cid in _bulk_state):
            pv_keep = True
    except Exception: pass
    await _on_message_orig(update, context)
    try:
        if had_conv and authorized(update) and update.message and not pv_keep:
            await update.message.delete()
    except Exception: pass

# ═══════════════ CALLBACK ROUTER ═══════════════
async def route_cb(cid, data):
    p = data.split(":"); h = p[0]

    if h == "bulk":
        sub = p[1] if len(p) > 1 else ""
        if sub == "enter" and len(p) >= 3:
            idx = int(p[2])
            st = _bulk_state.get(cid)
            if not st: return await show_accounts()
            phone = st["phones"][idx]
            stt = st["states"].get(phone, {})
            if stt.get("step") == "login":
                await tg_send(f"📨 {phone}: کد را همین‌جا بفرست")
            elif stt.get("status") == "ok":
                await tg_send(f"✅ {phone} وارد شده")
            elif stt.get("status") == "pending":
                await tg_send(f"⏸ {phone} در نوبت است")
            else:
                err = stt.get("error", stt.get("status", "?"))
                await tg_send(f"⏳ {phone}: {esc(err[:150])}")
            return
        if sub == "finish":
            state = _bulk_state.get(cid)
            if state: state["cancelled"] = True
            return await bulk_finish(cid)

    if h not in ("op", "noop"): STATE.setdefault("op_panel", {}).pop(cid, None)
    if data == "conv:cancel": clear_conv(cid); _TMP_EDIT.pop(cid, None); return await show_main()
    if data == "menu:main": clear_conv(cid); _TMP_EDIT.pop(cid, None); return await show_main()
    if data == "menu:acc": return await show_accounts()
    if data == "menu:stats": return await show_stats()
    if data == "menu:errors": return await show_errors()
    if data == "menu:listen": return await show_listen_menu()
    if data == "menu:cache": return await show_cache_menu()
    if data == "menu:pv": return await show_pv_menu()
    if data == "menu:cfg": return await show_cfg()

    if data == "cfg:lang":
        cur = _get_lang(); new = "en" if cur == "fa" else "fa"; _set_lang(new)
        await tg_send(("🌐 " + T("cfg_lang_en")) if new == "en" else ("🌐 " + T("cfg_lang_fa")))
        return await show_main()

    if h == "cache":
        sub = p[1] if len(p) > 1 else ""
        if sub == "acc" and len(p) >= 3:
            aid = p[2]; act = p[3] if len(p) > 3 else ""
            if not act: return await show_cache_account(aid)
            if act == "clear_seen": _clear_seen(aid); await tg_send("🗑"); return await show_cache_account(aid)
            if act == "clear_banned": _clear_banned(aid); await tg_send("🗑"); return await show_cache_account(aid)
            if act == "clear_all": _clear_seen(aid); _clear_banned(aid); await tg_send("🗑"); return await show_cache_account(aid)
            if act == "reset_ld": _reset_ld_progress(aid); await tg_send("🔄"); return await show_cache_account(aid)
        if sub == "clear_all_accounts": _clear_seen(); _clear_banned(); _reset_ld_progress(); await tg_send("🗑"); return await show_cache_menu()

    if h == "pv":
        sub = p[1] if len(p) > 1 else ""
        if sub == "acc" and len(p) >= 3:
            aid = p[2]; act = p[3] if len(p) > 3 else ""
            if not act: return await show_pv_account_menu(aid)
            cfg = _load_pv_account(aid)
            if act == "toggle":
                cfg["enabled"] = not bool(cfg.get("enabled")); _save_pv_account(aid, cfg)
                if cfg["enabled"]:
                    existing = PV_LISTENER_TASKS.get(aid)
                    if not existing or existing.done():
                        acc = get_account(aid)
                        if acc:
                            stop = asyncio.Event(); _PV_STOP_EVENTS[aid] = stop
                            t = asyncio.create_task(pv_poller_worker(aid, acc, stop)); PV_LISTENER_TASKS[aid] = t
                else: _stop_pv_for_account(aid)
                return await show_pv_account_menu(aid)
            if act == "cycle_max":
                seq = [1, 2, 3, 5, 0]; cur = int(cfg.get("max_replies", 1) or 0)
                cfg["max_replies"] = seq[(seq.index(cur) + 1) % len(seq)] if cur in seq else 1
                _save_pv_account(aid, cfg); return await show_pv_account_menu(aid)
            if act == "set_delay": get_conv(cid)["pv_acc_wait"] = {"aid": aid, "kind": "delay"}; return await ask(T("pv_delay_q"))
            if act == "set_poll": get_conv(cid)["pv_acc_wait"] = {"aid": aid, "kind": "poll"}; return await ask(T("pv_poll_q"))
            if act == "toggle_notify": cfg["notify"] = not bool(cfg.get("notify", True)); _save_pv_account(aid, cfg); return await show_pv_account_menu(aid)
            if act == "add_text": get_conv(cid)["pv_acc_wait"] = {"aid": aid, "kind": "add_text"}; return await ask(T("pv_text_q"))
            if act == "add_saved": get_conv(cid)["pv_acc_save_msg"] = {"aid": aid}; return await ask(T("pv_file_q"))
            if act == "add_delay": get_conv(cid)["pv_acc_wait"] = {"aid": aid, "kind": "add_delay_sec"}; return await ask(T("pv_delaysec_q"))
            if act == "list": return await show_pv_account_list(aid)
            if act == "del" and len(p) >= 5:
                try: i = int(p[4])
                except Exception: return await show_pv_account_list(aid)
                items = cfg.get("items") or []
                if 0 <= i < len(items): items.pop(i)
                cfg["items"] = items; _save_pv_account(aid, cfg); await tg_send("🗑"); return await show_pv_account_list(aid)
            if act == "clear_replies":
                d = _load(PV_COUNTS_FILE, {}); d.pop(aid, None); _save(PV_COUNTS_FILE, d)
                w = _wm_load(); w.pop(aid, None); _wm_flush(); await tg_send("🧹"); return await show_pv_account_menu(aid)
            if act == "reset_to_global": _delete_pv_account(aid); await tg_send("♻️"); return await show_pv_account_menu(aid)
            if act == "restart":
                _stop_pv_for_account(aid); await asyncio.sleep(0.5)
                cfg2 = _load_pv_account(aid)
                if cfg2.get("enabled"):
                    acc = get_account(aid)
                    if acc:
                        stop = asyncio.Event(); _PV_STOP_EVENTS[aid] = stop
                        t = asyncio.create_task(pv_poller_worker(aid, acc, stop)); PV_LISTENER_TASKS[aid] = t
                await tg_send("🔄"); return await show_pv_account_menu(aid)
            if act == "report":
                try: pg = int(p[4]) if len(p) > 4 else 0
                except Exception: pg = 0
                return await show_pv_account_report(aid, pg)

    if h == "acc":
        if len(p) >= 5 and p[1] == "at" and p[2] == "run":
            aid = p[3]; tid = p[4]
            op = {"id": "at_" + secrets.token_hex(5), "created": int(time.time()), "type": "autotar", "accounts": [aid], "template_id": tid, "status": "running",
                  "progress": {"joined":0,"failed":0,"total":0,"pending":0,"in_progress":0,"phase":T("ph_start"),"sent":0,"already":0,"tried":0,"wave":0,"left":0,"round":0,"skipped_seen":0,"skipped_banned":0,"rejected":0}, "errors": []}
            _save_op(op); OP_TASKS[op["id"]] = asyncio.create_task(run_auto_tar(op, log_cb)); return await show_op_detail(op["id"])
        if len(p) >= 3 and p[1] == "at": return await show_acc_at_menu(p[2])
        sub = p[1] if len(p) > 1 else ""
        if sub == "bulk":
            get_conv(cid).pop("acc", None)
            get_conv(cid)["bulk_wait"] = True
            await ask("📞 شماره‌ها را خط به خط وارد کنید:\n<i>هر خط یک شماره</i>")
            return
        if sub == "page": return await show_accounts(int(p[2]))
        if sub == "refresh":
            for aid in list(_STATS_CACHE.keys()): _STATS_CACHE.pop(aid, None)
            await tg_send(f"🔄 {T('refresh_profile')}"); return await show_accounts()
        if sub == "refresh_one" and len(p) >= 3:
            _STATS_CACHE.pop(p[2], None); await tg_send(f"🔄 {T('refresh_profile')}")
            try: await asyncio.wait_for(rb_refresh_profile(p[2]), timeout=20)
            except Exception: pass
            return await show_account_detail(p[2])
        if sub == "refresh_profile" and len(p) >= 3:
            aid = p[2]
            await tg_send("⏳ در حال به‌روزرسانی پروفایل...")
            ok, res = await rb_refresh_profile(aid)
            await tg_send("✅ پروفایل به‌روز شد" if ok else f"❌ {res}")
            return await show_account_detail(aid)
        if sub == "set_alias" and len(p) >= 3:
            aid = p[2]
            get_conv(cid)["alias_edit"] = aid
            await ask("🏷 اسم مستعار جدید را وارد کنید:")
            return
        if sub == "add":
            get_conv(cid).pop("bulk_wait", None)
            get_conv(cid)["acc"] = {"step": "phone"}
            return await ask(T("add_account_q"))
        if sub == "view": return await show_account_detail(p[2])
        if sub == "del":
            a = get_account(p[2])
            if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
            return await panel(T("acc_delete_q", n=esc(a.get('name','?'))), kb_([B(T("yes"), f"acc:delok:{p[2]}"), B(T("no"), f"acc:view:{p[2]}")]), page_tag=f"acc_del:{p[2]}")
        if sub == "delok":
            _stop_listener_for(p[2])
            try: _stop_pv_for_account(p[2])
            except Exception: pass
            remove_account(p[2]); await tg_send("🗑"); return await show_accounts()
        if sub == "lf" and len(p) >= 5 and p[3] == "go":
            aid = p[2]; mode = p[4]
            op = {"id": "lf_" + secrets.token_hex(5), "created": int(time.time()), "type": "lefter", "accounts": [aid], "leave_mode": mode, "delay": 0.8, "status": "running", "progress": {"joined":0,"failed":0,"total":0,"phase":T("ph_start")}, "errors": []}
            _save_op(op); OP_TASKS[op["id"]] = asyncio.create_task(run_lefter(op, log_cb)); return await show_op_detail(op["id"])
        if sub == "lf" and len(p) >= 3: return await show_acc_lf(p[2])

    if h == "accphoto":
        sub = p[1] if len(p) > 1 else ""
        if sub == "menu" and len(p) >= 3: return await show_acc_photo_menu(p[2])
        if sub == "set" and len(p) >= 3: get_conv(cid)["accphoto_upload"] = {"aid": p[2]}; return await ask(T("prof_send_photo"))
        if sub == "del" and len(p) >= 3:
            aid = p[2]; a = get_account(aid)
            if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
            await panel(f"⏳ {T('prof_deleting')}", page_tag=f"accphoto:{aid}")
            ok = False; msg_r = ""
            try:
                cli = SafeRubikaClient(name=a.get("session_name"), _aid=aid)
                async with cli as bot:
                    fn = getattr(bot, "delete_profile_photos", None)
                    if fn:
                        r = fn()
                        if asyncio.iscoroutine(r): await r
                        ok = True
                    else: msg_r = "not_supported"
            except Exception as e: msg_r = _fmt_error(e)
            await tg_send("✅" if ok else f"❌ {msg_r[:150]}"); return await show_acc_photo_menu(aid)

    if h == "chphoto":
        sub = p[1] if len(p) > 1 else ""
        if sub == "menu" and len(p) >= 4: return await show_ch_photo_menu(p[2], int(p[3]))
        if sub == "set" and len(p) >= 4: get_conv(cid)["chphoto_upload"] = {"aid": p[2], "idx": int(p[3])}; return await ask(T("prof_send_photo"))
        if sub == "del" and len(p) >= 4:
            await tg_send("ℹ️ not_supported"); return await show_ch_photo_menu(p[2], int(p[3]))

    if h == "chfile":
        sub = p[1] if len(p) > 1 else ""
        if sub == "start" and len(p) >= 4: get_conv(cid)["chfile_upload"] = {"aid": p[2], "idx": int(p[3]), "step": "wait_file"}; return await ask(T("ch_file_q"))

    if h == "jl":
        c = get_conv(cid); s = c.get("jl") or {"step": "account", "accounts": [], "max_join": 0, "speed": "fast", "groups_only": True}; c["jl"] = s
        sub = p[1] if len(p) > 1 else ""
        if sub == "start": c["jl"] = {"step": "account", "accounts": [], "max_join": 0, "speed": "fast", "groups_only": True}; return await jl_step_account(cid, c["jl"])
        if sub == "acc" and len(p) >= 3:
            aid = p[2]; sel = s.setdefault("accounts", [])
            if aid in sel: sel.remove(aid)
            else: sel.append(aid)
            return await jl_step_account(cid, s)
        if sub == "speed" and len(p) >= 3: s["speed"] = p[2]; return await jl_step_settings(cid, s)
        if sub == "toggle_groups_only": s["groups_only"] = not s.get("groups_only", True); return await jl_step_settings(cid, s)
        if sub == "max" and len(p) >= 3:
            v = p[2]
            if v == "custom": get_conv(cid)["jl_wait"] = "max"; return await ask(T("jl_max_q"))
            try: s["max_join"] = int(v)
            except Exception: pass
            return await jl_step_max(cid, s)
        if sub == "next":
            if s["step"] == "account":
                if not s.get("accounts"): return await panel(T("empty"), kb_([B(f"« {T('back')}", "jl:back")]), page_tag="jl:1")
                s["step"] = "settings"; return await jl_step_settings(cid, s)
            elif s["step"] == "settings": s["step"] = "max"; return await jl_step_max(cid, s)
        if sub == "back":
            if s["step"] == "settings": s["step"] = "account"
            elif s["step"] == "max": s["step"] = "settings"
            return await show_jl_step(cid)
        if sub == "linkdonies": return await show_linkdonies("jl:back_to_settings")
        if sub == "back_to_settings": s["step"] = "settings"; return await jl_step_settings(cid, s)
        if sub == "cancel": c.pop("jl", None); return await show_main()
        if sub == "go":
            if not s.get("max_join"): return await panel(T("empty"), kb_([B(f"« {T('back')}", "jl:back")]), page_tag="jl:3")
            if not s.get("accounts"): return await panel(T("empty"), kb_([B(f"« {T('back')}", "jl:back")]), page_tag="jl:1")
            speed_map = {"ultra": 0.3, "fast": 1.0, "normal": 3.0, "slow": 8.0}; spd = s.get("speed", "fast"); cfg = _load(CFG_FILE, DEFAULT_CFG)
            op = {"id": "jl_" + secrets.token_hex(5), "created": int(time.time()), "type": "joinlef", "accounts": s.get("accounts") or [], "max_join": s.get("max_join", 0), "status": "running", "speed": spd, "join_delay": speed_map.get(spd, 1.0), "groups_only": bool(s.get("groups_only", True)), "wave_size": int(cfg.get("wave_size", 50)), "extract_limit": int(cfg.get("extract_limit", 300)), "link_donies": list(load_link_donies()),
                  "progress": {"joined":0,"failed":0,"total":0,"phase":T("ph_start"),"skipped_seen":0,"skipped_banned":0,"rejected":0,"already":0,"sent":0,"wave":0,"tried":0,"left":0,"round":0,"extracted":0,"lds_done":0}, "errors": []}
            _save_op(op); c.pop("jl", None)
            JL_JOBS[op["id"]] = asyncio.create_task(run_joiner_lefter(op, log_cb))
            OP_TASKS[op["id"]] = JL_JOBS[op["id"]]
            return await show_op_detail(op["id"])

    if h == "lf":
        c = get_conv(cid); s = c.get("lf") or {"step": "account", "accounts": [], "mode": "all", "delay": 0.8}; c["lf"] = s
        sub = p[1] if len(p) > 1 else ""
        if sub == "start": c["lf"] = {"step": "account", "accounts": [], "mode": "all", "delay": 0.8}; return await lf_step_account(cid, c["lf"])
        if sub == "acc" and len(p) >= 3:
            aid = p[2]; sel = s.setdefault("accounts", [])
            if aid in sel: sel.remove(aid)
            else: sel.append(aid)
            return await lf_step_account(cid, s)
        if sub == "mode" and len(p) >= 3: s["mode"] = p[2]; return await lf_step_mode(cid, s)
        if sub == "delay" and len(p) >= 3:
            try: s["delay"] = float(p[2])
            except Exception: s["delay"] = 0.8
            return await lf_step_delay(cid, s)
        if sub == "next":
            if s["step"] == "account":
                if not s.get("accounts"): return await panel(T("empty"), kb_([B(f"« {T('back')}", "lf:back")]), page_tag="lf:1")
                s["step"] = "mode"; return await lf_step_mode(cid, s)
            elif s["step"] == "mode": s["step"] = "delay"; return await lf_step_delay(cid, s)
        if sub == "back":
            if s["step"] == "mode": s["step"] = "account"
            elif s["step"] == "delay": s["step"] = "mode"
            return await show_lf_step(cid)
        if sub == "cancel": c.pop("lf", None); return await show_main()
        if sub == "go":
            if not s.get("accounts"): return await panel(T("empty"), kb_([B(f"« {T('back')}", "lf:back")]), page_tag="lf:1")
            op = {"id": "lf_" + secrets.token_hex(5), "created": int(time.time()), "type": "lefter", "accounts": s.get("accounts") or [], "leave_mode": s.get("mode", "all"), "delay": s.get("delay", 0.8), "status": "running", "progress": {"joined":0,"failed":0,"total":0,"phase":T("ph_start")}, "errors": []}
            _save_op(op); c.pop("lf", None)
            OP_TASKS[op["id"]] = asyncio.create_task(run_lefter(op, log_cb))
            return await show_op_detail(op["id"])

    if h == "at":
        if data == "at:menu": return await show_at_menu()
        if data == "at:new":
            tpl = new_template("قالب " + secrets.token_hex(2)); add_template(tpl); return await show_at_view(tpl["id"])
        if len(p) >= 3 and p[1].startswith("tp_"):
            tid = p[1]; act = p[2]
            if act == "view": return await show_at_view(tid)
            if act == "del":
                t = get_template(tid)
                if not t: return await show_at_menu()
                return await panel(T("at_delete_q", n=esc(t.get('name','?'))), kb_([B(T("yes"), f"at:{tid}:delok"), B(T("no"), f"at:{tid}:view")]), page_tag=f"at:{tid}:view")
            if act == "delok": delete_template(tid); await tg_send("🗑"); return await show_at_menu()
            if act == "rename": _TMP_EDIT[cid] = {"kind": "at_field", "tid": tid, "section": "meta", "field": "name"}; return await ask(T("at_rename_q"))
            if act == "ch": return await show_at_channel(tid)
            if act == "pr": return await show_at_profile(tid)
            if act == "jn": return await show_at_joiner(tid)
            if act == "sn": return await show_at_sender(tid)
            if act == "pv": return await show_at_pv(tid)
            if act == "lf": return await show_at_lefter(tid)
            if act == "snmode": return await show_at_sender_mode(tid)
            if act == "chtype" and len(p) >= 4: update_template(tid, "channel", "type", p[3]); return await show_at_channel(tid)
            if act == "chset" and len(p) >= 4:
                field = p[3]
                if field == "photo_file": get_conv(cid)["at_field_photo"] = {"tid": tid, "section": "channel", "field": "photo_file"}; return await ask(T("ch_photo_menu"))
                _TMP_EDIT[cid] = {"kind": "at_field", "tid": tid, "section": "channel", "field": field}
                prompts = {"title": T("channel_title"), "username": T("username"), "about": T("about")}
                return await ask(prompts.get(field, "مقدار:"))
            if act == "prset" and len(p) >= 4:
                field = p[3]
                if field == "photo_file": get_conv(cid)["at_field_photo"] = {"tid": tid, "section": "profile", "field": "photo_file"}; return await ask(T("prof_photo_menu"))
                _TMP_EDIT[cid] = {"kind": "at_field", "tid": tid, "section": "profile", "field": field}
                prompts = {"first_name": T("prof_first_q"), "last_name": T("prof_last_q"), "username": T("prof_user_q"), "bio": T("prof_bio_q")}
                return await ask(prompts.get(field, "مقدار:"))
            if act == "jnset" and len(p) >= 4: _TMP_EDIT[cid] = {"kind": "at_field", "tid": tid, "section": "joiner", "field": p[3]}; return await ask(T("jl_max"))
            if act == "jnspeed" and len(p) >= 4: update_template(tid, "joiner", "speed", p[3]); return await show_at_joiner(tid)
            if act == "jntoggle_groups_only":
                t = get_template(tid)
                if t: update_template(tid, "joiner", "groups_only", not bool(t.get("joiner", {}).get("groups_only", True)))
                return await show_at_joiner(tid)
            if act == "snset" and len(p) >= 4:
                field = p[3]; _TMP_EDIT[cid] = {"kind": "at_field", "tid": tid, "section": "sender", "field": field}
                prompts = {"text": T("text"), "target": T("target"), "max_send": T("max"), "delay": T("delay")}
                return await ask(prompts.get(field, "مقدار:"))
            if act == "snmode_set" and len(p) >= 4: update_template(tid, "sender", "mode", p[3]); return await show_at_sender(tid)
            if act == "sntoggle_loop":
                t = get_template(tid)
                if t:
                    snd = t.setdefault("sender", {}); snd["infinite_loop"] = not bool(snd.get("infinite_loop", False))
                    ts = list_templates(); ts[tid] = t; save_templates(ts)
                return await show_at_sender(tid)
            if act == "sntoggle_rescan":
                t = get_template(tid)
                if t:
                    snd = t.setdefault("sender", {}); snd["rescan_targets"] = not bool(snd.get("rescan_targets", True))
                    ts = list_templates(); ts[tid] = t; save_templates(ts)
                return await show_at_sender(tid)
            if act == "snset_loop_delay": _TMP_EDIT[cid] = {"kind": "at_field", "tid": tid, "section": "sender", "field": "loop_delay"}; return await ask(T("send_loop_q"))
            if act == "snedit" and len(p) >= 4:
                sub_act = p[3]; ts = list_templates(); t2 = ts.get(tid)
                if sub_act in ("toggle", "ph_rand", "multi_toggle"):
                    if t2:
                        snd2 = t2.setdefault("sender", {})
                        if sub_act == "toggle": snd2["edit_delay_enabled"] = not bool(snd2.get("edit_delay_enabled", False))
                        elif sub_act == "ph_rand": snd2["placeholder_random"] = not bool(snd2.get("placeholder_random", False))
                        elif sub_act == "multi_toggle": snd2["multi_step_edit"] = not bool(snd2.get("multi_step_edit", False))
                        save_templates(ts)
                    return await show_at_sender(tid)
                if sub_act == "sec": _TMP_EDIT[cid] = {"kind": "at_field", "tid": tid, "section": "sender_edit", "field": "edit_delay_seconds"}; return await ask(T("send_edit_q"))
                if sub_act == "ph": _TMP_EDIT[cid] = {"kind": "at_field", "tid": tid, "section": "sender_edit", "field": "placeholder_text"}; return await ask(T("send_ph_q"))
                if sub_act == "file": get_conv(cid)["at_field_photo"] = {"tid": tid, "section": "sender_edit", "field": "attach_file"}; return await ask(T("send_attach_q"))
            if act == "pv" and len(p) >= 4:
                sub_act = p[3]; t2 = get_template(tid)
                if not t2: return await show_at_menu()
                pv2 = t2.setdefault("pv", {}); items = pv2.get("items") or []
                if sub_act == "toggle": pv2["enabled"] = not bool(pv2.get("enabled", False)); update_template(tid, "pv", "enabled", pv2["enabled"]); return await show_at_pv(tid)
                if sub_act == "cycle_max":
                    seq = [1, 2, 3, 5, 0]; cur = int(pv2.get("max_replies", 1) or 0); nv = seq[(seq.index(cur) + 1) % len(seq)] if cur in seq else 1
                    update_template(tid, "pv", "max_replies", nv); return await show_at_pv(tid)
                if sub_act == "set_delay": get_conv(cid)["pv_tpl_wait"] = {"tid": tid, "kind": "delay"}; return await ask(T("pv_delay_q"))
                if sub_act == "toggle_apply": update_template(tid, "pv", "apply_to_accounts", not bool(pv2.get("apply_to_accounts", True))); return await show_at_pv(tid)
                if sub_act == "add_text": get_conv(cid)["pv_tpl_wait"] = {"tid": tid, "kind": "add_text"}; return await ask(T("pv_text_q"))
                if sub_act == "add_saved": get_conv(cid)["pv_tpl_save_msg"] = {"tid": tid}; return await ask(T("pv_file_q"))
                if sub_act == "add_delay": get_conv(cid)["pv_tpl_wait"] = {"tid": tid, "kind": "add_delay_sec"}; return await ask(T("pv_delaysec_q"))
                if sub_act == "list": return await show_at_pv_list(tid)
                if sub_act == "del" and len(p) >= 5:
                    try: i = int(p[4])
                    except Exception: return await show_at_pv_list(tid)
                    if 0 <= i < len(items): items.pop(i)
                    update_template(tid, "pv", "items", items); await tg_send("🗑"); return await show_at_pv_list(tid)
            if act == "lfset" and len(p) >= 4: update_template(tid, "lefter", "leave_mode", p[3]); return await show_at_lefter(tid)
            if act == "run": return await show_at_run(tid)
            if act == "run_acc" and len(p) >= 4:
                aid = p[3]; c = get_conv(cid); ar = c.setdefault("at_run", {"template_id": tid, "accounts": []}); sel = ar.setdefault("accounts", [])
                if aid in sel: sel.remove(aid)
                else: sel.append(aid)
                return await show_at_run(tid)
            if act == "run_go":
                c = get_conv(cid); ar = c.get("at_run") or {}; sel = ar.get("accounts") or []
                if not sel: return await panel(T("empty"), kb_(nav(f"at:{tid}:view")), page_tag=f"at:{tid}:run:0")
                op = {"id": "at_" + secrets.token_hex(5), "created": int(time.time()), "type": "autotar", "accounts": sel, "template_id": tid, "status": "running",
                      "progress": {"joined":0,"failed":0,"total":0,"pending":0,"in_progress":0,"phase":T("ph_start"),"sent":0,"already":0,"tried":0,"wave":0,"left":0,"round":0,"skipped_seen":0,"skipped_banned":0,"rejected":0}, "errors": []}
                _save_op(op); c.pop("at_run", None)
                OP_TASKS[op["id"]] = asyncio.create_task(run_auto_tar(op, log_cb))
                return await show_op_detail(op["id"])
            if len(p) == 3 and p[2].isdigit(): return await show_at_run(tid, int(p[2]))

    if h == "ch":
        sub = p[1] if len(p) > 1 else ""
        if sub == "menu": return await show_ch_menu(p[2])
        if sub == "view" and len(p) >= 4: return await show_channel_view(p[2], int(p[3]))
        if sub == "getlink" and len(p) >= 4:
            aid = p[2]; idx = int(p[3]); a = get_account(aid); chs = get_stored_channels(aid)
            if not a or idx >= len(chs): return await panel(T("not_found"), kb_(nav()), page_tag="main")
            await panel(f"⏳ {T('ch_link_fetch')}", page_tag=f"chview:{aid}:{idx}")
            ok = False; res = ""
            try:
                cli = SafeRubikaClient(name=a.get("session_name"), _aid=aid)
                async with cli as bot: ok, res = await rb_create_join_link(bot, chs[idx].get("guid"))
                if ok: update_channel_field(aid, idx, "join_link", res)
            except Exception as e: res = _fmt_error(e)
            if ok: return await panel(head("🔗", "link_sent") + f"\n\n<code>{esc(res)}</code>", kb_([B(f"🔄 {T('get_link')}", f"ch:getlink:{aid}:{idx}")], [B(f"✍️ {T('set_link')}", f"ch:setlink:{aid}:{idx}")], [B(f"« {T('back')}", f"ch:view:{aid}:{idx}")]), page_tag=f"chview:{aid}:{idx}")
            return await panel(f"❌ {esc(str(res)[:400])}", kb_([B(f"✍️ {T('set_link')}", f"ch:setlink:{aid}:{idx}")], [B(f"« {T('back')}", f"ch:view:{aid}:{idx}")]), page_tag=f"chview:{aid}:{idx}")
        if sub == "setlink" and len(p) >= 4: get_conv(cid)["setlink"] = {"aid": p[2], "idx": int(p[3])}; return await ask(T("ch_link_q"))
        if sub == "diag" and len(p) >= 4:
            aid = p[2]; idx = int(p[3]); chs = get_stored_channels(aid)
            if idx >= len(chs): return await show_ch_list(aid)
            dump = "=== STORED ===\n" + "\n".join(f"  {k} = {repr(v)[:100]}" for k, v in chs[idx].items())
            return await panel(head("🔍", "debug") + f"\n<pre>{esc(dump[:3500])}</pre>", kb_([B(f"« {T('back')}", f"ch:view:{aid}:{idx}")]), page_tag=f"chview:{aid}:{idx}")
        if sub == "del" and len(p) >= 4:
            aid = p[2]; idx = int(p[3]); channels = get_stored_channels(aid)
            if idx >= len(channels): return await show_ch_list(aid)
            return await panel(T("ch_delete_q"), kb_([B(T("yes"), f"ch:delok:{aid}:{idx}"), B(T("no"), f"ch:view:{aid}:{idx}")]), page_tag=f"chview:{aid}:{idx}")
        if sub == "delok" and len(p) >= 4:
            aid = p[2]; idx = int(p[3]); a = get_account(aid); chs = get_stored_channels(aid)
            if a and idx < len(chs):
                try:
                    cli = SafeRubikaClient(name=a.get("session_name"), _aid=aid)
                    async with cli as bot: await rb_remove_channel(bot, chs[idx].get("guid"))
                except Exception: pass
            remove_channel_from_storage(aid, idx); await tg_send("🗑"); return await show_ch_list(aid)

    if h == "chlist":
        sub = p[1] if len(p) > 1 else ""
        if sub == "show": return await show_ch_list(p[2], int(p[3]) if len(p) > 3 else 0)

    if h == "chsend":
        sub = p[1] if len(p) > 1 else ""
        if sub == "start" and len(p) >= 4: get_conv(cid)["chsend"] = {"aid": p[2], "idx": int(p[3]), "step": "compose"}; return await ask(T("ch_send_q"))
        if sub == "text" and len(p) >= 4: get_conv(cid)["chsend_text"] = {"aid": p[2], "idx": int(p[3])}; return await ask("💬 متن پیام:")
        if sub == "photo" and len(p) >= 4: get_conv(cid)["chsend_media"] = {"aid": p[2], "idx": int(p[3]), "force_kind": "Image"}; return await ask("🖼 عکس بفرست:")
        if sub == "video" and len(p) >= 4: get_conv(cid)["chsend_media"] = {"aid": p[2], "idx": int(p[3]), "force_kind": "Video"}; return await ask("🎬 ویدیو بفرست:")
        if sub == "file" and len(p) >= 4: get_conv(cid)["chsend_media"] = {"aid": p[2], "idx": int(p[3]), "force_kind": None}; return await ask("📄 فایل بفرست (با کپشن اختیاری):")

    if h == "chnew":
        sub = p[1] if len(p) > 1 else ""
        if sub == "start": get_conv(cid)["chnew"] = {"aid": p[2], "step": "title"}; return await ask(T("ch_new_name_q"))
        if sub == "pub":
            aid = p[2]; info = get_conv(cid).get("chnew") or {}; title = info.get("title")
            if not title: return await panel(T("not_found"), kb_(nav(f"ch:menu:{aid}")), page_tag=f"ch_menu:{aid}")
            get_conv(cid)["chnew"] = {"aid": aid, "step": "username", "title": title}; return await ask(T("ch_new_user_q"))
        if sub == "priv":
            aid = p[2]; info = get_conv(cid).get("chnew") or {}; title = info.get("title")
            if not title: return await panel(T("not_found"), kb_(nav(f"ch:menu:{aid}")), page_tag=f"ch_menu:{aid}")
            get_conv(cid).pop("chnew", None); a = get_account(aid)
            if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
            await panel(f"⏳ {T('ch_creating')}", page_tag="chnew_run")
            ok = False; msg_r = ""; ch_guid = None; join_link = ""
            try:
                cli = SafeRubikaClient(name=a.get("session_name"), _aid=aid)
                async with cli as bot:
                    ok, ch_guid, msg_r = await rb_create_channel(bot, title)
                    if ok and ch_guid:
                        await asyncio.sleep(1.5)
                        ok_link, link_res = await rb_create_join_link(bot, ch_guid)
                        if ok_link: join_link = link_res
                        else: msg_r = f"link: {link_res}"
            except Exception as e: msg_r = _fmt_error(e)
            if ok and ch_guid:
                add_channel_to_storage(aid, {"title": title, "guid": ch_guid, "type": "private", "join_link": join_link, "created": int(time.time())})
                body = head("✅", "ch_created") + f"📝 {esc(title)}\n"
                if join_link: body += f"🔗 <code>{esc(join_link)}</code>"
                else: body += f"⚠️ لینک خودکار ساخته نشد"
                return await panel(body, kb_([B(f"⚙️ {T('my_channels')}", f"chlist:show:{aid}:0")], [B(f"« {T('back')}", f"ch:menu:{aid}")]), page_tag=f"ch_menu:{aid}")
            return await panel(f"❌ <code>{esc(str(msg_r)[:300])}</code>", kb_([B(f"« {T('back')}", f"ch:menu:{aid}")]), page_tag=f"ch_menu:{aid}")

    if h == "chprof":
        sub = p[1] if len(p) > 1 else ""
        if sub == "show" and len(p) >= 4: return await show_ch_profile(p[2], int(p[3]))
        if sub == "edit" and len(p) >= 5:
            field = p[2]; aid = p[3]; idx = int(p[4])
            get_conv(cid)["chprof_edit"] = {"aid": aid, "idx": idx, "field": field}
            prompts = {"title": "👤 اسم جدید:", "desc": "📖 توضیح جدید:", "user": "🔤 یوزرنیم جدید (بدون @):"}
            return await ask(prompts.get(field, "مقدار جدید:"))

    if h == "prof":
        sub = p[1] if len(p) > 1 else ""
        if sub == "menu": return await show_profile_menu(p[2])
        if sub == "set":
            field = p[2]; aid = p[3]; get_conv(cid)["prof_field"] = {"field": field, "aid": aid}
            prompts = {"first": T("prof_first_q"), "last": T("prof_last_q"), "about": T("prof_bio_q"), "username": T("prof_user_q")}
            return await ask(prompts.get(field, "مقدار:"))

    if h == "ld":
        sub = p[1] if len(p) > 1 else ""; back = p[3] if len(p) > 3 else (p[2] if len(p) > 2 else "jl:back_to_settings")
        if sub == "list": return await show_linkdonies(back)
        if sub == "add": get_conv(cid)["ld_wait"] = "url"; get_conv(cid)["ld_back"] = back; return await ask(T("ld_add_q"))
        if sub == "del" and len(p) >= 3: remove_link_doni(int(p[2])); await tg_send("🗑"); return await show_linkdonies(back)
        if sub == "reset": save_link_donies(list(DEFAULT_LINK_DONIES)); await tg_send("🔄"); return await show_linkdonies(back)
        if sub == "reset_prog": _reset_ld_progress(); await tg_send("🔄"); return await show_linkdonies(back)
        if sub == "toggle_autojoin":
            cfg = _load(CFG_FILE, DEFAULT_CFG); cfg["auto_join_linkdoni"] = 0 if int(cfg.get("auto_join_linkdoni", 1)) else 1; _save(CFG_FILE, cfg); return await show_linkdonies(back)

    if h == "err":
        sub = p[1] if len(p) > 1 else ""
        if sub == "page": return await show_errors(int(p[2]))
        if sub == "clear": clear_errors(); await tg_send("🗑"); return await show_errors()

    if h == "listen":
        sub = p[1] if len(p) > 1 else ""
        if sub == "restart": await restart_all_listeners(); await tg_send("🔄"); return await show_listen_menu()
        if sub == "toggle" and len(p) >= 3:
            aid = p[2]; t = LISTENER_TASKS.get(aid)
            if t and not t.done(): _stop_listener_for(aid); await tg_send("⚪")
            else: await start_all_listeners(); await tg_send("🟢")
            await asyncio.sleep(0.3); return await show_listen_menu()

    if h == "op":
        sub = p[1] if len(p) > 1 else ""; oid = p[2] if len(p) > 2 else None
        if sub == "view" and oid: return await show_op_detail(oid)
        if sub == "stop" and oid:
            op = _get_op(oid)
            if op:
                st = STATE.get("cancel_" + oid)
                if st: st.set()
                t = OP_TASKS.get(oid) or JL_JOBS.get(oid)
                if t and not t.done(): t.cancel()
                op["status"] = "cancelled"; op["finished_at"] = int(time.time()); _save_op(op)
            return await show_op_detail(oid)

    if h == "send":
        s = _send_conv(cid); sub = p[1] if len(p) > 1 else ""
        if sub == "start": s["step"] = "accounts"; s["accounts"] = s.get("accounts") or []; return await show_send_step(cid)
        if sub == "acc" and len(p) >= 3:
            aid = p[2]; sel = s.setdefault("accounts", [])
            if "all" in sel: sel.remove("all")
            if aid in sel: sel.remove(aid)
            else: sel.append(aid)
            return await show_send_step(cid)
        if sub == "accall": s["accounts"] = [] if "all" in (s.get("accounts") or []) else ["all"]; return await show_send_step(cid)
        if sub == "accnext":
            if not s.get("accounts"): return await show_send_step(cid)
            s["step"] = "compose"; return await show_send_step(cid)
        if sub == "recompose": s["step"] = "compose"; s["payload"] = None; return await show_send_step(cid)
        if sub == "composenext":
            if not s.get("payload"): return await show_send_step(cid)
            s["step"] = "target"; return await show_send_step(cid)
        if sub == "tgt" and len(p) >= 3: s["target"] = p[2]; return await show_send_step(cid)
        if sub == "toggle_auto_left": s["auto_left"] = not s.get("auto_left", False); return await show_send_step(cid)
        if sub == "toggle_groups_only": s["groups_only"] = not s.get("groups_only", True); return await show_send_step(cid)
        if sub == "toggle_infinite": s["infinite_loop"] = not s.get("infinite_loop", False); return await show_send_step(cid)
        if sub == "toggle_rescan": s["rescan_targets"] = not s.get("rescan_targets", True); return await show_send_step(cid)
        if sub == "loop_delay": get_conv(cid)["send_edit_wait"] = "loop_delay"; return await ask(T("send_loop_q"))
        if sub == "toggle_edit": s["edit_delay_enabled"] = not s.get("edit_delay_enabled", False); return await show_send_step(cid)
        if sub == "edit_sec": get_conv(cid)["send_edit_wait"] = "sec"; return await ask(T("send_edit_q"))
        if sub == "edit_ph": get_conv(cid)["send_edit_wait"] = "ph"; return await ask(T("send_ph_q"))
        if sub == "toggle_edit_rand": s["edit_delay_random"] = not s.get("edit_delay_random", False); return await show_send_step(cid)
        if sub == "toggle_ph_rand": s["placeholder_random"] = not s.get("placeholder_random", False); return await show_send_step(cid)
        if sub == "toggle_multi": s["multi_step_edit"] = not s.get("multi_step_edit", False); return await show_send_step(cid)
        if sub == "attach": get_conv(cid)["send_file_upload"] = True; return await ask(T("send_attach_q"))
        if sub == "tgtnext": s["step"] = "max"; return await show_send_step(cid)
        if sub == "max" and len(p) >= 3:
            v = p[2]
            if v == "custom": get_conv(cid)["send_wait"] = "max"; return await ask(T("send_max_q"))
            try: s["max"] = int(v)
            except Exception: pass
            return await show_send_step(cid)
        if sub == "maxnext": s["step"] = "confirm"; return await show_send_step(cid)
        if sub == "back": s["step"] = "accounts"; return await show_send_step(cid)
        if sub == "prev":
            order = ["accounts", "compose", "target", "max", "confirm"]; i = order.index(s.get("step", "accounts")); s["step"] = order[max(0, i-1)]
            return await show_send_step(cid)
        if sub == "back_edit": s["step"] = "accounts"; return await show_send_step(cid)
        if sub == "cancel": clear_conv(cid); return await show_main()
        if sub == "go":
            accounts = list_accounts(); sel = s.get("accounts") or []
            if "all" in sel: sel = list(accounts.keys())
            op = {"id": "sd_" + secrets.token_hex(5), "created": int(time.time()), "type": "send", "accounts": sel, "target": s.get("target", "both"), "max": s.get("max", 0) or 0, "payload": s.get("payload") or {"text": "سلام"}, "delay": 1.5, "auto_left": bool(s.get("auto_left", False)), "status": "running", "groups_only": bool(s.get("groups_only", True)), "attach_file": s.get("attach_file", ""), "infinite_loop": bool(s.get("infinite_loop", False)), "loop_delay": float(s.get("loop_delay", 3.0)), "rescan_targets": bool(s.get("rescan_targets", True)), "edit_delay_enabled": bool(s.get("edit_delay_enabled", False)), "edit_delay_seconds": float(s.get("edit_delay_seconds", 3.0)), "edit_delay_random": bool(s.get("edit_delay_random", False)), "edit_delay_min": float(s.get("edit_delay_min", 2.0)), "edit_delay_max": float(s.get("edit_delay_max", 6.0)), "placeholder_text": s.get("placeholder_text", "سلام"), "placeholder_random": bool(s.get("placeholder_random", False)), "placeholder_list": s.get("placeholder_list", ""), "multi_step_edit": bool(s.get("multi_step_edit", False)), "multi_step_middle": s.get("multi_step_middle", "Hi"), "progress": {"sent":0,"failed":0,"total":0,"pending":0,"in_progress":0,"phase":T("ph_start"),"blocked":0,"round":0}, "errors": []}
            _save_op(op); clear_conv(cid)
            OP_TASKS[op["id"]] = asyncio.create_task(run_sender(op, log_cb))
            return await show_op_detail(op["id"])

    if h == "cfg":
        sub = p[1] if len(p) > 1 else ""
        if sub == "set" and len(p) >= 3: get_conv(cid)["cfg_wait"] = p[2]; return await ask(T("cfg_value_q", k=p[2]))
        if sub == "toggle_autojoin":
            cfg = _load(CFG_FILE, DEFAULT_CFG); cfg["auto_join_linkdoni"] = 0 if int(cfg.get("auto_join_linkdoni", 1)) else 1; _save(CFG_FILE, cfg); return await show_cfg()
        if sub == "toggle_listener":
            cfg = _load(CFG_FILE, DEFAULT_CFG); cfg["listener"] = 0 if int(cfg.get("listener", 1)) else 1; _save(CFG_FILE, cfg); return await show_cfg()

# ═══════════════ SERVICES ═══════════════
async def _extract_from_linkdoni(aid, cli, url, limit=300):
    url = (url or "").strip()
    if not url: return []
    guid = await rb_resolve(cli, url)
    if not guid:
        flog(f"[extract] {url}: resolve failed")
        return []
    if not await rb_verify_member(cli, guid):
        ok, err, tag = await rb_join(cli, url, guid=guid)
        if not ok:
            flog(f"[extract] {url}: join failed — {str(err)[:120]}")
        await asyncio.sleep(2)
        if not await rb_verify_member(cli, guid):
            await asyncio.sleep(2)
    cfg = _load(CFG_FILE, DEFAULT_CFG)
    page_size = min(int(cfg.get("deep_scan_page_size", 25)), 25)
    max_pages = (limit // page_size) + 30
    cursor = "0"; seen_ids = set(); scanned = 0; pages = 0; raw_links = []
    while pages < max_pages and scanned < limit:
        pages += 1
        batch = await rb_get_messages(cli, guid, limit=page_size, max_id=cursor)
        if not batch:
            if pages > 1 and cursor != "0":
                try:
                    cint = int(cursor)
                    for off in (1, page_size // 2, page_size, page_size * 2):
                        alt = str(max(0, cint - off))
                        retry = await rb_get_messages(cli, guid, limit=page_size, max_id=alt)
                        if retry:
                            batch = retry; break
                except Exception: pass
            if not batch: break
        new_msgs = [m for m in batch if str(_extract_field(m, "message_id", "id")) not in seen_ids]
        for m in new_msgs: seen_ids.add(str(_extract_field(m, "message_id", "id")))
        if not new_msgs:
            try:
                cint = int(cursor)
                for off in (1, page_size // 2, page_size, page_size * 2, page_size * 3):
                    alt = str(max(0, cint - off))
                    retry = await rb_get_messages(cli, guid, limit=page_size, max_id=alt)
                    retry_new = [m for m in retry if str(_extract_field(m, "message_id", "id")) not in seen_ids]
                    if retry_new:
                        batch = retry; new_msgs = retry_new
                        for m in new_msgs: seen_ids.add(str(_extract_field(m, "message_id", "id")))
                        break
            except Exception: pass
            if not new_msgs: break
        scanned += len(new_msgs)
        for m in new_msgs:
            combined = _extract_msg_texts(m)
            if combined:
                raw_links.extend(_extract_links_from_text(combined))
        ids = []
        for m in batch:
            try:
                i = int(_extract_field(m, "message_id", "id") or 0)
                if i: ids.append(i)
            except (ValueError, TypeError): pass
        if not ids: break
        min_id = min(ids)
        if min_id <= 1: break
        if len(batch) < page_size: break
        cursor = str(min_id - 1)
        await asyncio.sleep(0.3)
    seen = set(); uniq = []
    for lk in raw_links:
        h = _hash_of(lk)
        if h in seen: continue
        seen.add(h); uniq.append(lk)
    flog(f"[extract] {url}: {scanned} msg → {len(uniq)} links")
    return uniq

async def _auto_join_one_linkdoni(cli, url):
    url = (url or "").strip()
    if not url: return None
    guid = await rb_resolve(cli, url)
    if not guid: return None
    if await rb_verify_member(cli, guid): return guid
    ok, err, tag = await rb_join(cli, url, guid=guid)
    if ok: await asyncio.sleep(1.5)
    else: flog(f"[auto-join] {url}: {str(err)[:120]}")
    return guid

async def _op_phase(oid, phase):
    lock = _get_op_lock(oid)
    async with lock:
        op2 = _get_op(oid)
        if op2:
            op2["progress"]["phase"] = phase
            _save_op(op2)
    await _refresh_op_panel(oid)

async def _op_progress(oid, **kw):
    lock = _get_op_lock(oid)
    async with lock:
        op2 = _get_op(oid)
        if op2:
            op2["progress"].update(kw)
            _save_op(op2)

# ═══════════════ SENDER ═══════════════
async def run_sender(op, log):
    accounts = list_accounts(); sel = op.get("accounts") or []
    if "all" in sel: sel = list(accounts.keys())
    oid = op["id"]; lock = _get_op_lock(oid)
    op["progress"] = {"sent":0,"failed":0,"total":0,"pending":0,"in_progress":0,
                      "phase":T("ph_start"),"blocked":0,"round":0}
    op["status"] = "running"; op["errors"] = []; _save_op(op)
    stop = asyncio.Event(); STATE["cancel_" + oid] = stop
    async def worker_one(aid):
        acc = accounts.get(aid)
        if not acc: return
        name = acc.get("name") or aid; sent = failed = blocked = 0
        delay = float(op.get("delay", 1.5))
        payload = op.get("payload") or {"text": "سلام"}; text = payload.get("text") or "سلام"
        attach_file = op.get("attach_file") or ""
        infinite_loop = bool(op.get("infinite_loop", False))
        loop_delay = float(op.get("loop_delay", 3.0)); rescan = bool(op.get("rescan_targets", True))
        target = op.get("target", "both"); groups_only = bool(op.get("groups_only", True))
        max_send = int(op.get("max", 0) or 0)
        try:
            await _op_phase(oid, T("ph_connect"))
            cli = SafeRubikaClient(name=acc.get("session_name"), _aid=aid)
            async with cli as bot:
                await bot.get_me()
                await _op_phase(oid, T("ph_collecting"))
                own_guids = {c.get("guid") for c in get_stored_channels(aid) if c.get("guid")}
                targets = []; loop_round = 0
                while not stop.is_set():
                    loop_round += 1
                    if not targets or rescan:
                        targets = await rb_collect_targets(bot, target, own_guids, groups_only)
                        if max_send and len(targets) > max_send: targets = targets[:max_send]
                    if not targets:
                        if infinite_loop:
                            await _op_phase(oid, T("ph_no_targets")); await asyncio.sleep(5); continue
                        await _op_phase(oid, T("ph_no_targets")); return
                    await _op_phase(oid, T("ph_sending", n=len(targets)))
                    await _op_progress(oid, total=len(targets), pending=len(targets),
                                       round=loop_round if infinite_loop else 0)
                    for i, t in enumerate(targets, 1):
                        if stop.is_set(): break
                        guid = t["target"]; ok = False; err = None
                        try:
                            if attach_file and os.path.exists(attach_file):
                                kind = _detect_kind_from_path(attach_file)
                                ok, err = await rb_send_file(bot, guid, attach_file, text, kind)
                            else:
                                ok, err = await rb_send_text(bot, guid, text)
                        except Exception as e:
                            ok, err = False, _fmt_error(e)
                        if ok: sent += 1
                        else:
                            if "BLOCKED" in str(err).upper(): blocked += 1
                            else:
                                failed += 1; add_error("send", err or "fail", t.get("name"), name)
                        await _op_progress(oid, sent=sent, failed=failed, blocked=blocked,
                                           pending=max(0, len(targets) - i))
                        await asyncio.sleep(delay)
                    if stop.is_set() or not infinite_loop: break
                    await asyncio.sleep(loop_delay)
        except asyncio.CancelledError: raise
        except Exception as e:
            add_error("sender", _fmt_error(e), None, name)
    async def _runner():
        try:
            tasks = [asyncio.create_task(worker_one(a)) for a in sel if a in accounts]
            if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            async with lock:
                op2 = _get_op(oid)
                if op2 and op2.get("status") not in ("cancelled", "done"):
                    op2["status"] = "done"; op2["finished_at"] = int(time.time()); _save_op(op2)
            cid = STATE.get("owner")
            if cid and _is_page(cid, f"op:{oid}"):
                await _refresh_op_panel(oid, force=True)
            OP_TASKS.pop(oid, None)
    OP_TASKS[oid] = asyncio.create_task(_runner())
    _ensure_live_for(oid)

# ═══════════════ LEFTER ═══════════════
async def run_lefter(op, log):
    accounts = list_accounts(); sel = op.get("accounts") or []
    if "all" in sel: sel = list(accounts.keys())
    oid = op["id"]; lock = _get_op_lock(oid)
    op["progress"] = {"joined":0,"failed":0,"total":0,"phase":T("ph_start")}
    op["status"] = "running"; op["errors"] = []; _save_op(op)
    mode = op.get("leave_mode", "all"); delay = float(op.get("delay", 0.8))
    stop = asyncio.Event(); STATE["cancel_" + oid] = stop
    async def worker_one(aid):
        acc = accounts.get(aid)
        if not acc: return
        name = acc.get("name") or aid; left = failed = 0
        try:
            await _op_phase(oid, T("ph_connect"))
            cli = SafeRubikaClient(name=acc.get("session_name"), _aid=aid)
            async with cli as bot:
                me = await bot.get_me()
                my_guid = _extract_field(me, "user_guid")
                if not my_guid:
                    u = _extract_field(me, "user")
                    my_guid = _extract_field(u, "user_guid") if u is not None else None
                await _op_phase(oid, T("ph_collecting"))
                chats = await rb_get_chats(bot)
                targets = []
                for c in chats:
                    ci = _chat_info(c)
                    if not ci: continue
                    if ci["guid"] == my_guid: continue
                    typ = ci["type"]
                    if typ == "User": continue
                    if mode == "groups" and typ != "Group": continue
                    if mode == "channels" and typ != "Channel": continue
                    if mode == "closed" and typ != "Group": continue
                    targets.append({"guid": ci["guid"], "name": ci["title"]})
                await _op_progress(oid, total=len(targets))
                if not targets: await _op_phase(oid, T("ph_nothing")); return
                for i, t in enumerate(targets, 1):
                    if stop.is_set(): await _op_phase(oid, T("ph_cancelled")); return
                    ok, err = await rb_leave_chat(bot, t["guid"])
                    if ok: left += 1
                    else: failed += 1; add_error("lefter", err or "?", t["name"], name)
                    await _op_progress(oid, joined=left, failed=failed,
                                       phase=T("ph_progress", a=left, b=len(targets)))
                    if delay > 0: await asyncio.sleep(delay)
                await _op_phase(oid, f"✓ {left} · ✗ {failed}")
        except asyncio.CancelledError: raise
        except Exception as e:
            add_error("lefter", _fmt_error(e), None, name)
    async def _runner():
        try:
            tasks = [asyncio.create_task(worker_one(a)) for a in sel if a in accounts]
            if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            async with lock:
                op2 = _get_op(oid)
                if op2 and op2.get("status") not in ("cancelled", "done"):
                    op2["status"] = "done"; op2["finished_at"] = int(time.time()); _save_op(op2)
            cid = STATE.get("owner")
            if cid and _is_page(cid, f"op:{oid}"):
                await _refresh_op_panel(oid, force=True)
            OP_TASKS.pop(oid, None)
    OP_TASKS[oid] = asyncio.create_task(_runner())
    _ensure_live_for(oid)

# ═══════════════ JOINER ═══════════════
async def run_joiner_lefter(op, log):
    accounts = list_accounts(); sel = op.get("accounts") or []
    if "all" in sel: sel = list(accounts.keys())
    oid = op["id"]; lock = _get_op_lock(oid)
    op["progress"] = {"joined":0,"failed":0,"total":0,"phase":T("ph_start"),
                      "skipped_seen":0,"skipped_banned":0,"rejected":0,
                      "already":0,"sent":0,"wave":0,"tried":0,"left":0,"round":0,
                      "extracted":0,"lds_done":0}
    op["status"] = "running"; op["errors"] = []; _save_op(op)
    max_join = int(op.get("max_join", 0) or 0)
    join_delay = float(op.get("join_delay", 1.0))
    groups_only = bool(op.get("groups_only", True))
    wave_size = int(op.get("wave_size") or 50)
    extract_limit = int(op.get("extract_limit") or 300)
    lds = op.get("link_donies") or list(load_link_donies())
    stop = asyncio.Event(); STATE["cancel_" + oid] = stop

    async def worker_one(aid):
        acc = accounts.get(aid)
        if not acc: return
        name = acc.get("name") or aid
        joined = failed = skipped_seen = skipped_banned = already = 0
        wave_num = 0; wait_round = 0
        cfg = _load(CFG_FILE, DEFAULT_CFG)
        wait_seconds = int(cfg.get("wait_for_links_sec", 90))
        max_wait_rounds = int(cfg.get("max_wait_rounds", 20))
        try:
            await _op_phase(oid, T("ph_connect"))
            cli = SafeRubikaClient(name=acc.get("session_name"), _aid=aid)
            async with cli as bot:
                await bot.get_me()
                total_lds = len(lds)
                for i, url in enumerate(lds, 1):
                    if stop.is_set(): return
                    await _op_phase(oid, f"جوین لینک‌دونی {i}/{total_lds}: {url}")
                    try: await _auto_join_one_linkdoni(bot, url)
                    except Exception: pass
                    await asyncio.sleep(0.5)

                while True:
                    if stop.is_set(): await _op_phase(oid, T("ph_cancelled")); return
                    if max_join and joined >= max_join:
                        await _op_phase(oid, T("ph_limit")); return
                    wave_num += 1
                    await _op_phase(oid, f"موج {wave_num}: استخراج موازی از {total_lds} لینک‌دونی...")
                    await _op_progress(oid, wave=wave_num, extracted=0, lds_done=0)

                    sem = asyncio.Semaphore(3)
                    lds_done_count = [0]
                    extracted_count = [0]

                    async def extract_one(url):
                        async with sem:
                            try:
                                found = await _extract_from_linkdoni(aid, bot, url, limit=extract_limit)
                                lds_done_count[0] += 1
                                extracted_count[0] += len(found)
                                async with lock:
                                    op2 = _get_op(oid)
                                    if op2:
                                        op2["progress"]["lds_done"] = lds_done_count[0]
                                        op2["progress"]["extracted"] = extracted_count[0]
                                        _save_op(op2)
                                await _refresh_op_panel(oid)
                                return found
                            except Exception as e:
                                add_error("extract", _fmt_error(e), url, aid)
                                lds_done_count[0] += 1
                                return []

                    try:
                        results = await asyncio.gather(
                            *[asyncio.create_task(extract_one(u)) for u in lds],
                            return_exceptions=True)
                    except Exception:
                        results = []

                    all_links = []
                    for r in results:
                        if isinstance(r, list): all_links.extend(r)

                    seen_set = set(); deduped = []
                    for lk in all_links:
                        h = _hash_of(lk)
                        if not h: continue
                        if h in seen_set: continue
                        if _is_seen(aid, h): skipped_seen += 1; continue
                        if _is_banned(aid, h): skipped_banned += 1; continue
                        seen_set.add(h); deduped.append(lk)
                    all_links = deduped

                    await _op_progress(oid, extracted=len(all_links),
                                       skipped_seen=skipped_seen,
                                       skipped_banned=skipped_banned)

                    if not all_links:
                        wait_round += 1
                        if wait_round > max_wait_rounds:
                            await _op_phase(oid, T("ph_no_links")); return
                        await _op_phase(oid, f"موج {wave_num}: بدون لینک — انتظار {wait_seconds}ث ({wait_round}/{max_wait_rounds})")
                        for _ in range(wait_seconds):
                            if stop.is_set(): return
                            await asyncio.sleep(1)
                        continue
                    wait_round = 0

                    total_batches = (len(all_links) + wave_size - 1) // wave_size
                    for batch_i in range(total_batches):
                        if stop.is_set(): return
                        if max_join and joined >= max_join: break
                        batch = all_links[batch_i * wave_size:(batch_i + 1) * wave_size]
                        await _op_phase(oid, f"موج {wave_num} ({batch_i+1}/{total_batches}): جوین {len(batch)} لینک")

                        sem2 = asyncio.Semaphore(2)

                        async def join_one(lk):
                            nonlocal joined, failed, already
                            async with sem2:
                                if max_join and joined >= max_join: return
                                if stop.is_set(): return
                                h = _hash_of(lk)
                                if _is_seen(aid, h) or _is_banned(aid, h): return

                                if groups_only:
                                    try:
                                        is_grp = await rb_is_group(bot, lk)
                                        if not is_grp:
                                            _mark_seen(aid, h)
                                            return
                                    except Exception:
                                        pass

                                base_delay = max(3.0, join_delay)

                                ok = False; err = "?"; tag = "failed"
                                try:
                                    ok, err, tag = await rb_join(bot, lk, guid=None)

                                    if not ok and "TOO_REQUESTS" in str(err).upper():
                                        flog(f"[join] Rate limited on {lk}. Waiting 60s and retrying once...")
                                        await asyncio.sleep(60)
                                        ok, err, tag = await rb_join(bot, lk, guid=None)

                                except Exception as e:
                                    ok, err, tag = False, _fmt_error(e), "failed"

                                if ok:
                                    _mark_seen(aid, h)
                                    if tag == "already":
                                        already += 1
                                    else:
                                        joined += 1
                                else:
                                    failed += 1
                                    add_error("join", err, lk, name)
                                    eu = str(err).upper()
                                    if "BANNED" in eu or "KICKED" in eu or "BLOCKED" in eu:
                                        _mark_banned(aid, h, err[:80])

                                await _op_progress(oid, joined=joined, failed=failed, already=already)
                                if base_delay > 0: await asyncio.sleep(base_delay)

                        await asyncio.gather(
                            *[asyncio.create_task(join_one(lk)) for lk in batch],
                            return_exceptions=True)
                        await _refresh_op_panel(oid)
                        await asyncio.sleep(1)
        except asyncio.CancelledError: raise
        except Exception as e:
            add_error("joiner", _fmt_error(e), None, name)

    async def _runner():
        try:
            tasks = [asyncio.create_task(worker_one(a)) for a in sel if a in accounts]
            if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            async with lock:
                op2 = _get_op(oid)
                if op2 and op2.get("status") not in ("cancelled", "done"):
                    op2["status"] = "done"; op2["finished_at"] = int(time.time()); _save_op(op2)
            cid = STATE.get("owner")
            if cid and _is_page(cid, f"op:{oid}"):
                await _refresh_op_panel(oid, force=True)
            OP_TASKS.pop(oid, None)
    OP_TASKS[oid] = asyncio.create_task(_runner())
    _ensure_live_for(oid)

# ═══════════════ AUTO-TAR ═══════════════
async def run_auto_tar(op, log):
    accounts = list_accounts(); sel = op.get("accounts") or []
    if "all" in sel: sel = list(accounts.keys())
    tpl = get_template(op.get("template_id"))
    if not tpl: op["status"] = "failed"; _save_op(op); return
    op["progress"] = {"joined":0,"failed":0,"total":0,"pending":0,"in_progress":0,
                      "phase":T("ph_start"),"sent":0,"already":0,"tried":0,"wave":0,
                      "left":0,"round":0,"skipped_seen":0,"skipped_banned":0,"rejected":0,
                      "extracted":0,"lds_done":0}
    op["status"] = "running"; op["errors"] = []; _save_op(op)
    ctx = _build_ctx(); oid = op["id"]; lock = _get_op_lock(oid)
    stop = asyncio.Event(); STATE["cancel_" + oid] = stop
    async def worker_one(aid):
        acc = accounts.get(aid)
        if not acc: return
        name = acc.get("name") or aid
        try:
            await _op_phase(oid, T("ph_connect"))
            cli = SafeRubikaClient(name=acc.get("session_name"), _aid=aid)
            async with cli as bot:
                me = await bot.get_me()
                my_guid = _extract_field(me, "user_guid")
                if not my_guid:
                    u = _extract_field(me, "user")
                    my_guid = _extract_field(u, "user_guid") if u is not None else None
                pv = tpl.get("pv") or {}
                if pv.get("apply_to_accounts") and pv.get("items"):
                    cur = _load_pv_account(aid)
                    cur.update({"enabled": bool(pv.get("enabled", cur.get("enabled"))),
                                "delay_seconds": int(pv.get("delay_seconds", cur.get("delay_seconds"))),
                                "max_replies": int(pv.get("max_replies", cur.get("max_replies"))),
                                "items": list(pv.get("items") or [])})
                    _save_pv_account(aid, cur)
                ch = tpl.get("channel") or {}
                if ch.get("title"):
                    title = _substitute(ch["title"], ctx)[:60]
                    desc = _substitute(ch.get("description", ""), ctx)
                    await _op_phase(oid, T("ph_create_ch", n=title))
                    ok, guid, err = await rb_create_channel(bot, title, desc)
                    if ok and guid:
                        add_channel_to_storage(aid, {"title": title, "guid": guid, "type": ch.get("type", "private"), "username": ch.get("username") or "", "created": int(time.time())})
                        if ch.get("photo_file") and os.path.exists(ch["photo_file"]):
                            await rb_upload_avatar(bot, guid, ch["photo_file"])
                    else:
                        add_error("autotar-channel", err, title, name)
                p = tpl.get("profile") or {}
                if p.get("first_name") or p.get("last_name") or p.get("bio"):
                    await _op_phase(oid, T("ph_update_prof"))
                    await rb_update_profile(bot,
                        first_name=_substitute(p.get("first_name", ""), ctx) or None,
                        last_name=_substitute(p.get("last_name", ""), ctx) or None,
                        bio=_substitute(p.get("bio", ""), ctx) or None)
                if p.get("username"): await rb_update_username(bot, _substitute(p["username"], ctx))
                j = tpl.get("joiner") or {}; snd = tpl.get("sender") or {}
                mode = snd.get("mode", "send_only")
                sender_text = _substitute(snd.get("text", ""), ctx) if snd.get("text") else ""
                send_during_join = (mode in ("join_send","join_send_leave")) and bool(sender_text)
                send_to_existing = bool(snd.get("send_to_existing", True))
                attach_file = snd.get("attach_file") or ""
                groups_only = bool(j.get("groups_only", True)); max_join = int(j.get("max_join", 0) or 0)
                join_delay = {"ultra":0.3,"fast":1.0,"normal":3.0,"slow":8.0}.get(j.get("speed","fast"), 1.0)
                joined_count = sent_count = left_count = 0; failed_count = 0
                if max_join > 0:
                    lds = list(load_link_donies()); wave_num = 0
                    for i, url in enumerate(lds, 1):
                        if stop.is_set(): return
                        await _op_phase(oid, f"جوین لینک‌دونی {i}/{len(lds)}: {url}")
                        try: await _auto_join_one_linkdoni(bot, url)
                        except Exception: pass
                        await asyncio.sleep(0.5)
                    while joined_count < max_join and wave_num < 100:
                        if stop.is_set(): return
                        wave_num += 1
                        await _op_progress(oid, wave=wave_num)
                        new_links = []
                        for url in lds:
                            try: found = await _extract_from_linkdoni(aid, bot, url, limit=300)
                            except Exception: found = []
                            for lk in found:
                                h = _hash_of(lk)
                                if not h or _is_seen(aid, h) or _is_banned(aid, h): continue
                                if lk in new_links: continue
                                new_links.append(lk)
                                if len(new_links) >= 50: break
                            if len(new_links) >= 50: break
                        if not new_links: await asyncio.sleep(20); continue
                        for lk in new_links:
                            if joined_count >= max_join: break
                            h = _hash_of(lk)
                            if _is_seen(aid, h) or _is_banned(aid, h): continue
                            if groups_only:
                                try:
                                    is_grp = await rb_is_group(bot, lk)
                                    if not is_grp: _mark_seen(aid, h); continue
                                except Exception: pass
                            try:
                                ok, err, tag = await rb_join(bot, lk, guid=None)
                            except Exception:
                                ok, err, tag = False, "fail", "failed"
                            if not ok:
                                failed_count += 1; _mark_seen(aid, h)
                                await _op_progress(oid, failed=failed_count); continue
                            _mark_seen(aid, h)
                            if tag == "already": pass
                            else: joined_count += 1
                            await _op_progress(oid, joined=joined_count)
                            if send_during_join and sender_text:
                                try:
                                    await asyncio.sleep(0.4)
                                    g = await rb_resolve(bot, lk)
                                    if g:
                                        if attach_file and os.path.exists(attach_file):
                                            kind = _detect_kind_from_path(attach_file)
                                            await rb_send_file(bot, g, attach_file, sender_text, kind)
                                        else:
                                            await rb_send_text(bot, g, sender_text)
                                        sent_count += 1
                                        await _op_progress(oid, sent=sent_count)
                                        if mode == "join_send_leave":
                                            lok, _ = await rb_leave_chat(bot, g)
                                            if lok:
                                                left_count += 1
                                                await _op_progress(oid, left=left_count)
                                except Exception: pass
                            if join_delay > 0: await asyncio.sleep(join_delay)
                if sender_text or attach_file:
                    if send_to_existing or not send_during_join:
                        target = snd.get("target", "groups"); max_send = int(snd.get("max_send", 0) or 0); delay = float(snd.get("delay", 1.5))
                        await _op_phase(oid, T("ph_send_final"))
                        chats = await rb_get_chats(bot)
                        own = {c.get("guid") for c in get_stored_channels(aid) if c.get("guid")}
                        targets = []
                        for c in chats:
                            ci = _chat_info(c)
                            if not ci: continue
                            if ci["guid"] == my_guid or ci["guid"] in own: continue
                            if target in ("pv","both") and ci["type"] == "User": targets.append(ci["guid"])
                            elif target in ("groups","both") and ci["type"] in ("Group","Channel"): targets.append(ci["guid"])
                        if max_send and len(targets) > max_send: targets = targets[:max_send]
                        for g in targets:
                            if stop.is_set(): return
                            try:
                                if attach_file and os.path.exists(attach_file):
                                    kind = _detect_kind_from_path(attach_file)
                                    await rb_send_file(bot, g, attach_file, sender_text, kind)
                                else:
                                    await rb_send_text(bot, g, sender_text)
                                sent_count += 1
                                await _op_progress(oid, sent=sent_count)
                            except Exception as e:
                                failed_count += 1; add_error("autotar-send", _fmt_error(e), g, name)
                            if delay > 0: await asyncio.sleep(delay)
                lf = tpl.get("lefter") or {}
                if lf.get("leave_mode") and lf["leave_mode"] != "off":
                    ml = lf["leave_mode"]
                    await _op_phase(oid, T("ph_leaving", m=ml))
                    chats = await rb_get_chats(bot)
                    own = {c.get("guid") for c in get_stored_channels(aid) if c.get("guid")}
                    for c in chats:
                        if stop.is_set(): return
                        ci = _chat_info(c)
                        if not ci or ci["guid"] in own: continue
                        typ = ci["type"]
                        if typ == "User": continue
                        if ml == "groups" and typ != "Group": continue
                        if ml == "channels" and typ != "Channel": continue
                        if ml == "closed" and typ != "Group": continue
                        lok, _ = await rb_leave_chat(bot, ci["guid"])
                        if lok:
                            left_count += 1
                            await _op_progress(oid, left=left_count)
                        await asyncio.sleep(0.6)
                await _op_phase(oid, T("ph_done"))
        except asyncio.CancelledError: raise
        except Exception as e:
            add_error("autotar", _fmt_error(e), None, name)
    async def _runner():
        try:
            tasks = [asyncio.create_task(worker_one(a)) for a in sel if a in accounts]
            if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            async with lock:
                op2 = _get_op(oid)
                if op2 and op2.get("status") not in ("cancelled", "done"):
                    op2["status"] = "done"; op2["finished_at"] = int(time.time()); _save_op(op2)
            cid = STATE.get("owner")
            if cid and _is_page(cid, f"op:{oid}"):
                await _refresh_op_panel(oid, force=True)
            OP_TASKS.pop(oid, None)
    OP_TASKS[oid] = asyncio.create_task(_runner())
    _ensure_live_for(oid)

# ═══════════════ LISTENER / PV / KEEPALIVE ═══════════════
LISTENER_SEEN = {}; LISTENER_SEEN_LOCK = threading.Lock(); LISTENER_MAX_SEEN = 8000

async def pv_listener(aid, acc, stop_event):
    name = acc.get("name") or aid; sess = acc.get("session_name"); seeded = False
    while not stop_event.is_set():
        cli = None
        try:
            cli = SafeRubikaClient(name=sess, _aid=aid)
            async with cli as bot:
                me = await bot.get_me()
                my_guid = _extract_field(me, "user_guid")
                if not my_guid:
                    u = _extract_field(me, "user")
                    my_guid = _extract_field(u, "user_guid") if u is not None else None
                while not stop_event.is_set():
                    cfg = _load(CFG_FILE, DEFAULT_CFG)
                    if not int(cfg.get("listener", 1)):
                        await asyncio.sleep(15); continue
                    try:
                        chats = await rb_get_chats(bot)
                        for c in chats:
                            ci = _chat_info(c)
                            if not ci or ci["type"] != "User" or ci["guid"] == my_guid: continue
                            last = ci.get("last_message")
                            if not last: continue
                            mid = _extract_field(last, "message_id", "id")
                            if not mid: continue
                            key = f"{aid}:{ci['guid']}:{mid}"
                            with LISTENER_SEEN_LOCK:
                                if key in LISTENER_SEEN: continue
                                LISTENER_SEEN[key] = time.time()
                                if len(LISTENER_SEEN) > LISTENER_MAX_SEEN:
                                    oldest = sorted(LISTENER_SEEN.items(), key=lambda x: x[1])[:1500]
                                    for k, _ in oldest: LISTENER_SEEN.pop(k, None)
                            if seeded and not _extract_field(last, "is_mine", "isMine"):
                                txt = _extract_field(last, "text") or ""
                                if txt:
                                    STATE["listener_new_count"] = STATE.get("listener_new_count", 0) + 1
                                    await tg_send(f"📥 پیام جدید در {esc(name)}\n💬 <code>{esc(txt[:300])}</code>")
                        if not seeded: seeded = True
                    except asyncio.CancelledError: raise
                    except Exception: pass
                    await asyncio.sleep(15)
        except asyncio.CancelledError: raise
        except RuntimeError as e:
            if _is_auth_dead(e) or "NO_SESSION" in str(e): return
            await asyncio.sleep(60)
        except Exception:
            await asyncio.sleep(60)
        finally:
            if cli:
                try: await cli.__aexit__(None, None, None)
                except Exception: pass
        await asyncio.sleep(60)

async def start_all_listeners():
    for aid, acc in list_accounts().items():
        if aid in LISTENER_TASKS and not LISTENER_TASKS[aid].done(): continue
        stop = asyncio.Event(); STATE.setdefault("listener_stops", {})[aid] = stop
        t = asyncio.create_task(pv_listener(aid, acc, stop)); LISTENER_TASKS[aid] = t

def _stop_listener_for(aid):
    loop = _loop_ref[0]
    if loop is None: return
    def _go():
        st = STATE.setdefault("listener_stops", {}).get(aid)
        if st: st.set()
        t = LISTENER_TASKS.pop(aid, None)
        if t and not t.done(): t.cancel()
    try: loop.call_soon_threadsafe(_go)
    except Exception: pass

async def restart_all_listeners():
    for aid, st in list(STATE.get("listener_stops", {}).items()):
        try: st.set()
        except Exception: pass
    for aid, t in list(LISTENER_TASKS.items()):
        if not t.done(): t.cancel()
    LISTENER_TASKS.clear(); STATE["listener_stops"] = {}; LISTENER_SEEN.clear()
    await asyncio.sleep(1); await start_all_listeners()

async def _sleep_or_stop(ev, sec):
    try: await asyncio.wait_for(ev.wait(), timeout=sec)
    except asyncio.TimeoutError: pass

async def _pv_send_reply(aid, sender_guid, cfg, stop_event, sender_info):
    cli = None; send_ok = True; send_err = None
    try:
        for _ in range(int(cfg.get("delay_seconds", 0))):
            if stop_event.is_set(): return
            await asyncio.sleep(1)
        acc = get_account(aid)
        if not acc: return
        cli = SafeRubikaClient(name=acc.get("session_name"), _aid=aid)
        await cli.__aenter__()
        for item in cfg.get("items") or []:
            if stop_event.is_set(): break
            kind = item.get("kind", "text")
            try:
                if kind == "text" and item.get("text"):
                    ok, err = await rb_send_text(cli, sender_guid, item["text"])
                    if not ok: send_ok = False; send_err = err
                elif kind == "file":
                    fp = item.get("file_path")
                    if fp and os.path.exists(fp):
                        k = _detect_kind_from_path(fp)
                        ok, err = await rb_send_file(cli, sender_guid, fp, item.get("caption") or "", k)
                        if not ok: send_ok = False; send_err = err
                elif kind == "delay": await asyncio.sleep(int(item.get("seconds", 3)))
                await asyncio.sleep(random.uniform(0.8, 1.8))
            except Exception as e: send_ok = False; send_err = _fmt_error(e)
    except Exception as e: send_ok = False; send_err = _fmt_error(e)
    finally:
        if cli:
            try: await cli.__aexit__(None, None, None)
            except Exception: pass
        _record_pv_reply(aid, sender_guid, ok=send_ok, err=send_err)
        u = sender_info.get("first_name") or sender_info.get("username") or sender_guid
        if send_ok: await tg_send(f"✅ {T('ph_reply_ok', u=esc(u))}")
        else: await tg_send(f"❌ {T('ph_reply_fail', u=esc(u), e=esc(send_err or '?'))}")

async def _pv_handle_new_msg(aid, sender_guid, sender_info, msg, stop_event):
    cfg = _load_pv_account(aid)
    if not cfg.get("enabled"): return
    uid = str(sender_guid); _record_pv_visit(aid, uid, sender_info)
    if _pv_limit_reached(aid, uid, cfg): return
    key = f"{aid}:{uid}"; ex = _PV_REPLY_TASKS.get(key)
    if ex and not ex.done(): return
    _pv_count_add(aid, uid, +1)
    if cfg.get("notify", True) and cfg.get("notify_on_receive", True):
        u = sender_info.get("first_name") or sender_info.get("username") or uid
        mt = _extract_field(msg, "text") or "📎"
        await tg_send(f"🔔 <b>{esc(u)}</b>: <code>{esc(mt[:120])}</code>")
    task = asyncio.create_task(_pv_send_reply(aid, sender_guid, cfg, stop_event, sender_info))
    _PV_REPLY_TASKS[key] = task

async def pv_poller_worker(aid, acc, stop_event):
    global _PV_WM_DIRTY
    name = acc.get("name") or aid; sess = acc.get("session_name"); cli = None; my_guid = None
    flog(f"[pv] {name}: poller started")
    try:
        while not stop_event.is_set():
            cfg = _load_pv_account(aid); poll = max(3, int(cfg.get("poll_seconds", 3)))
            if not cfg.get("enabled"): await _sleep_or_stop(stop_event, poll); continue
            try:
                if cli is None:
                    cli = SafeRubikaClient(name=sess, _aid=aid); await cli.__aenter__()
                    me = await cli.get_me()
                    my_guid = _extract_field(me, "user_guid")
                    if not my_guid:
                        u = _extract_field(me, "user")
                        my_guid = _extract_field(u, "user_guid") if u is not None else None
                chats = await rb_get_chats(cli)
                first = not (_wm_load().get(aid) or {}).get("_init")
                for c in chats:
                    ci = _chat_info(c)
                    if not ci or ci["type"] != "User" or ci["guid"] == my_guid: continue
                    last = ci.get("last_message")
                    if not last: continue
                    try: mid = int(_extract_field(last, "message_id", "id") or 0)
                    except Exception: mid = 0
                    if not mid or mid <= _wm_get(aid, ci["guid"]): continue
                    _wm_set(aid, ci["guid"], mid)
                    if first or _extract_field(last, "is_mine", "isMine"): continue
                    info = {"first_name": ci["title"] or "", "last_name": "",
                            "username": ci["username"] or ""}
                    try: await _pv_handle_new_msg(aid, ci["guid"], info, {"text": _extract_field(last, "text") or ""}, stop_event)
                    except Exception as he: flog(f"[pv] handle: {he}", "warning")
                if first: _wm_load().setdefault(aid, {})["_init"] = 1; _PV_WM_DIRTY = True
                _wm_flush()
            except asyncio.CancelledError: raise
            except Exception as e:
                flog(f"[pv] {name}: {type(e).__name__}", "warning")
                if cli:
                    try: await cli.__aexit__(None, None, None)
                    except Exception: pass
                    cli = None
                await _sleep_or_stop(stop_event, 8); continue
            await _sleep_or_stop(stop_event, poll)
    finally:
        _wm_flush()
        if cli:
            try: await cli.__aexit__(None, None, None)
            except Exception: pass
        flog(f"[pv] {name}: poller stopped")

async def start_pv_responders():
    for aid, acc in list_accounts().items():
        cfg = _load_pv_account(aid)
        if not cfg.get("enabled"): continue
        existing = PV_LISTENER_TASKS.get(aid)
        if existing and not existing.done(): continue
        stop = asyncio.Event(); _PV_STOP_EVENTS[aid] = stop
        t = asyncio.create_task(pv_poller_worker(aid, acc, stop)); PV_LISTENER_TASKS[aid] = t

def _stop_pv_for_account(aid):
    st = _PV_STOP_EVENTS.pop(aid, None)
    if st:
        try: st.set()
        except Exception: pass
    t = PV_LISTENER_TASKS.pop(aid, None)
    if t and not t.done(): t.cancel()

KEEPALIVE_SECONDS = 15 * 60; PV_HEALTH_SECONDS = 5 * 60
async def keepalive_loop():
    flog("[keepalive] started"); await asyncio.sleep(60); pv_check = 0
    while True:
        try:
            for aid, acc in list_accounts().items():
                try:
                    cli = SafeRubikaClient(name=acc.get("session_name"), _aid=aid)
                    async with cli as bot: await bot.get_me()
                except Exception: pass
                await asyncio.sleep(random.uniform(3, 6))
            pv_check += 1
            if pv_check * KEEPALIVE_SECONDS >= PV_HEALTH_SECONDS:
                pv_check = 0
                dead = [aid for aid, t in list(PV_LISTENER_TASKS.items()) if t is None or t.done()]
                for aid in dead:
                    PV_LISTENER_TASKS.pop(aid, None); st = _PV_STOP_EVENTS.pop(aid, None)
                    if st:
                        try: st.set()
                        except Exception: pass
                if dead: await start_pv_responders()
            await asyncio.sleep(KEEPALIVE_SECONDS)
        except asyncio.CancelledError: raise
        except Exception: await asyncio.sleep(60)

# ═══════════════ BOOT ═══════════════
async def _post_init(app):
    try:
        await app.bot.set_my_commands([BotCommand("start", "شروع"), BotCommand("menu", "منو")])
    except Exception: pass
    try: _loop_ref[0] = asyncio.get_running_loop()
    except Exception: pass
    try:
        await start_all_listeners(); await start_pv_responders(); asyncio.create_task(keepalive_loop())
    except Exception as e: flog(f"[post_init] {type(e).__name__}: {e}")

async def _on_error(update, context):
    flog(f"[!] {type(context.error).__name__}: {context.error}", "error")

async def cmd_start(update, context):
    cid = update.effective_chat.id
    if cid != FORCED_OWNER: return
    STATE["panel"].pop(cid, None); STATE.setdefault("op_panel", {}).pop(cid, None); _TMP_EDIT.pop(cid, None)
    await show_main()

async def cmd_menu(update, context):
    if not authorized(update): return
    await cmd_start(update, context)

async def on_callback(update, context):
    q = update.callback_query
    if q is None: return
    try: await q.answer()
    except Exception: pass
    if not authorized(update): return
    cid = update.effective_chat.id
    if q.message: STATE["panel"][cid] = q.message.message_id
    data = q.data or ""
    if data == "noop": return
    try: await route_cb(cid, data)
    except Exception as e:
        flog(f"[callback] {data}: {traceback.format_exc()}", "error")
        await tg_send(f"❌ {type(e).__name__}: {str(e)[:200]}")

def main(token=None, owner_id=None):
    global APP, TG_TOKEN, FORCED_OWNER
    if token:
        TG_TOKEN = token
    else:
        TG_TOKEN = os.environ.get("TG_TOKEN", "").strip()
    if not TG_TOKEN or ":" not in TG_TOKEN:
        print("[x] TG_TOKEN not set. export TG_TOKEN='<bot_token>' first.")
        return
    if owner_id:
        FORCED_OWNER = int(owner_id)
    else:
        try: FORCED_OWNER = int(os.environ.get("TG_OWNER_ID", "8389746549"))
        except Exception: FORCED_OWNER = 8389746549
    STATE["owner"] = FORCED_OWNER
    flog(f"[+] VERSION: {VERSION}"); flog(f"[+] DATA_DIR: {DATA_DIR}")
    req = HTTPXRequest(connection_pool_size=8, connect_timeout=30.0, read_timeout=30.0, write_timeout=30.0, pool_timeout=30.0)
    APP = (Application.builder().token(TG_TOKEN).request(req).get_updates_request(req).post_init(_post_init).build())
    APP.add_handler(CommandHandler("start", cmd_start))
    APP.add_handler(CommandHandler("menu", cmd_menu))
    APP.add_handler(CallbackQueryHandler(on_callback))
    APP.add_handler(MessageHandler(tg_filters.ALL & ~tg_filters.COMMAND, on_message))
    APP.add_error_handler(_on_error)
    flog("[+] polling...")
    APP.run_polling(allowed_updates=Update.ALL_TYPES, poll_interval=2.0, timeout=30.0)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\n[!] قطع")