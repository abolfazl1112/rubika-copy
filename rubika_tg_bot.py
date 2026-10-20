# rubika_tg_bot.py — v76 (Soroosh-style UI · real rubpy API · fast joiner/lefter)
import os, sys, ssl, json, socket, asyncio, time, glob, re, threading, secrets, random, hashlib
import logging, traceback, html as _html, concurrent.futures
from typing import Optional, Dict, Any, List, Set, Tuple
VERSION = "Rubika v76"

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
SOROOSH_DIR = os.path.join(DATA_DIR, "rubika"); os.makedirs(SOROOSH_DIR, exist_ok=True)
LOG_FILE = os.path.join(SOROOSH_DIR, "rubika.log")
UPLOADS_DIR = os.path.join(SOROOSH_DIR, "uploads"); os.makedirs(UPLOADS_DIR, exist_ok=True)
LANG_FILE = os.path.join(SOROOSH_DIR, "lang.json")
SESSIONS_DIR = os.path.join(SOROOSH_DIR, "sessions"); os.makedirs(SESSIONS_DIR, exist_ok=True)

logging.basicConfig(level=logging.CRITICAL, stream=open(os.devnull, "w"))
for _n in ("urllib3","urllib3.connectionpool","requests","httpx","httpcore",
           "telegram.ext.Updater","telegram.request","rubpy","asyncio"):
    logging.getLogger(_n).setLevel(logging.CRITICAL); logging.getLogger(_n).propagate = False
print(f"[+] {VERSION}"); print(f"[+] DATA_DIR: {DATA_DIR}")

try: FORCED_OWNER = int(os.environ.get("TG_OWNER_ID", "8389746549"))
except Exception: FORCED_OWNER = 8389746549
print(f"[+] OWNER: {FORCED_OWNER}")

try:
    import asyncio.unix_events as _ue
    _orig_add_signal = _ue._UnixSelectorEventLoop.add_signal_handler
    def _safe_add_signal(self, sig, callback, *args):
        try: return _orig_add_signal(self, sig, callback, *args)
        except (RuntimeError, ValueError, NotImplementedError, AttributeError): return None
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

# ═══════════════ RUPPY IMPORT ═══════════════
try:
    import rubpy
    from rubpy import Client as _RClient
except ImportError as _e:
    print(f"[x] rubpy not installed: {_e}"); sys.exit(1)

# ═══════════════ I18N + STYLE ═══════════════
_LANG_CACHE = {"v": None}
def _get_lang():
    if _LANG_CACHE["v"]: return _LANG_CACHE["v"]
    try:
        if os.path.exists(LANG_FILE):
            _LANG_CACHE["v"] = json.load(open(LANG_FILE, encoding="utf-8")).get("v", "fa")
        else: _LANG_CACHE["v"] = "fa"
    except Exception: _LANG_CACHE["v"] = "fa"
    return _LANG_CACHE["v"]
def _set_lang(v):
    _LANG_CACHE["v"] = v
    try: json.dump({"v": v}, open(LANG_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception: pass
def is_en(): return _get_lang() == "en"
_SC = str.maketrans({'a':'ᴀ','b':'ʙ','c':'ᴄ','d':'ᴅ','e':'ᴇ','f':'ꜰ','g':'ɢ','h':'ʜ','i':'ɪ','j':'ᴊ','k':'ᴋ','l':'ʟ','m':'ᴍ','n':'ɴ','o':'ᴏ','p':'ᴘ','q':'ǫ','r':'ʀ','s':'ꜱ','t':'ᴛ','u':'ᴜ','v':'ᴠ','w':'ᴡ','x':'x','y':'ʏ','z':'ᴢ','A':'ᴀ','B':'ʙ','C':'ᴄ','D':'ᴅ','E':'ᴇ','F':'ꜰ','G':'ɢ','H':'ʜ','I':'ɪ','J':'ᴊ','K':'ᴋ','L':'ʟ','M':'ᴍ','N':'ɴ','O':'ᴏ','P':'ᴘ','Q':'ǫ','R':'ʀ','S':'ꜱ','T':'ᴛ','U':'ᴜ','V':'ᴠ','W':'ᴡ','X':'x','Y':'ʏ','Z':'ᴢ'})
def SC(s): return str(s).translate(_SC) if is_en() else str(s)
TICK = "⤳"
def _line(): return "━" * 32

_TR = {
"panel":{"fa":"پنل","en":"panel"},"accounts_n":{"fa":"اکانت‌ها","en":"accounts"},
"pv_enabled":{"fa":"PV فعال","en":"pv enabled"},"running_ops":{"fa":"در حال اجرا","en":"running ops"},
"idle":{"fa":"بیکار","en":"idle"},"listener":{"fa":"لیسنر","en":"listener"},
"data_dir":{"fa":"مسیر داده","en":"data dir"},"send":{"fa":"ارسال","en":"send"},
"joiner":{"fa":"جوینر","en":"joiner"},"lefter":{"fa":"لفتر","en":"lefter"},
"templates":{"fa":"قالب‌ها","en":"templates"},"pv":{"fa":"پیوی","en":"pv"},
"stats":{"fa":"آمار","en":"stats"},"errors":{"fa":"خطاها","en":"errors"},
"cache":{"fa":"کش","en":"cache"},"linkdonies":{"fa":"لینک‌دونی","en":"linkdonies"},
"settings":{"fa":"تنظیمات","en":"settings"},"back_to_panel":{"fa":"بازگشت به پنل","en":"back to panel"},
"back":{"fa":"بازگشت","en":"back"},"cancel":{"fa":"لغو","en":"cancel"},
"next":{"fa":"بعدی »","en":"next »"},"prev":{"fa":"« قبلی","en":"« prev"},
"yes":{"fa":"بله","en":"yes"},"no":{"fa":"خیر","en":"no"},"confirm":{"fa":"تایید","en":"confirm"},
"start":{"fa":"شروع","en":"start"},"stop":{"fa":"توقف","en":"stop"},
"add":{"fa":"افزودن","en":"add"},"delete":{"fa":"حذف","en":"delete"},
"clear":{"fa":"پاک","en":"clear"},"toggle_on":{"fa":"روشن کن","en":"turn on"},
"toggle_off":{"fa":"خاموش کن","en":"turn off"},"on":{"fa":"روشن","en":"on"},"off":{"fa":"خاموش","en":"off"},
"all":{"fa":"همه","en":"all"},"none":{"fa":"خالی","en":"none"},"loading":{"fa":"در حال بارگذاری...","en":"loading..."},
"saved":{"fa":"ذخیره شد","en":"saved"},"deleted":{"fa":"حذف شد","en":"deleted"},
"cleared":{"fa":"پاک شد","en":"cleared"},"restarted":{"fa":"ری‌استارت شد","en":"restarted"},
"not_found":{"fa":"پیدا نشد.","en":"not found."},"empty":{"fa":"خالی","en":"empty"},
"enter":{"fa":"بفرست","en":"send"},"phone":{"fa":"شماره","en":"phone"},"id":{"fa":"شناسه","en":"id"},
"name":{"fa":"نام","en":"name"},"last_name":{"fa":"فامیل","en":"last name"},
"username":{"fa":"یوزرنیم","en":"username"},"bio":{"fa":"بیو","en":"bio"},
"about":{"fa":"درباره","en":"about"},"photo":{"fa":"عکس","en":"photo"},
"profile":{"fa":"پروفایل","en":"profile"},"channels":{"fa":"کانال‌ها","en":"channels"},
"my_channels":{"fa":"کانال‌های من","en":"my channels"},"create_channel":{"fa":"ساخت کانال جدید","en":"create new channel"},
"channel_title":{"fa":"عنوان","en":"title"},"description":{"fa":"توضیحات","en":"description"},
"public":{"fa":"عمومی","en":"public"},"private":{"fa":"خصوصی","en":"private"},
"type":{"fa":"نوع","en":"type"},"link":{"fa":"لینک","en":"link"},
"get_link":{"fa":"دریافت لینک","en":"get link"},"set_link":{"fa":"ثبت لینک","en":"set link"},
"seen":{"fa":"دیده‌شده","en":"seen"},"banned":{"fa":"بلاک‌شده","en":"banned"},
"ld_progress":{"fa":"پیشرفت لینک‌دونی","en":"linkdoni progress"},
"clear_seen":{"fa":"پاک دیده‌شده","en":"clear seen"},"clear_banned":{"fa":"پاک بلاک‌شده","en":"clear banned"},
"clear_both":{"fa":"پاک هر دو","en":"clear both"},"reset_ld":{"fa":"ریست پیشرفت","en":"reset ld progress"},
"wipe_all":{"fa":"پاک کردن همه اکانت‌ها","en":"wipe all accounts"},
"select_account":{"fa":"یک اکانت انتخاب کن","en":"select an account"},
"pv_auto":{"fa":"پاسخ خودکار پیوی","en":"auto-reply pv"},"pv_status":{"fa":"وضعیت","en":"status"},
"pv_active":{"fa":"فعال","en":"on"},"pv_inactive":{"fa":"خاموش","en":"off"},
"pv_poller":{"fa":"پولر","en":"poller"},"pv_max":{"fa":"سقف/کاربر","en":"max/user"},
"pv_delay":{"fa":"تایمر","en":"delay"},"pv_notify":{"fa":"اعلان","en":"notify"},
"pv_poll":{"fa":"هر چند ثانیه","en":"poll"},"pv_items":{"fa":"پیام‌ها","en":"items"},
"pv_custom":{"fa":"سفارشی","en":"custom"},"pv_add_text":{"fa":"افزودن متن","en":"+ text"},
"pv_add_file":{"fa":"افزودن فایل","en":"+ file"},"pv_add_delay":{"fa":"افزودن تاخیر","en":"+ delay"},
"pv_list":{"fa":"لیست پیام‌ها","en":"items"},"pv_report":{"fa":"گزارش","en":"report"},
"pv_reset_counter":{"fa":"ریست شمارنده","en":"reset counter"},"pv_reset_custom":{"fa":"حذف سفارشی","en":"reset custom"},
"pv_restart":{"fa":"ری‌استارت","en":"restart"},"pv_delay_q":{"fa":"تایمر (0=آنی):","en":"delay (0=instant):"},
"pv_poll_q":{"fa":"هر چند ثانیه؟ (حداقل 2):","en":"poll seconds (>=2):"},
"pv_text_q":{"fa":"متن:","en":"text:"},"pv_file_q":{"fa":"پیام/عکس/فایل:","en":"send msg/photo/file:"},
"pv_delaysec_q":{"fa":"ثانیه:","en":"seconds:"},"pv_report_title":{"fa":"گزارش پیوی","en":"pv report"},
"pv_total":{"fa":"کل","en":"total"},"pv_page":{"fa":"صفحه","en":"page"},
"pv_no_accounts":{"fa":"هیچ اکانتی نداری.","en":"no accounts yet."},
"add_account":{"fa":"افزودن اکانت","en":"add account"},"groups":{"fa":"گروه‌ها","en":"groups"},
"pvs":{"fa":"پیوی","en":"pvs"},"bots":{"fa":"ربات‌ها","en":"bots"},
"channels_created":{"fa":"کانال ساخته","en":"channels created"},
"listener_status":{"fa":"لیسنر","en":"listener"},"delete_account":{"fa":"حذف اکانت","en":"delete account"},
"refresh_stats":{"fa":"بروزرسانی آمار","en":"refresh stats"},"refresh_all":{"fa":"بروزرسانی همه","en":"refresh all"},
"auto_tar":{"fa":"اتو تار","en":"auto-tar"},"add_account_q":{"fa":"شماره:\nمثال: <code>989121234567</code>","en":"phone number:"},
"invalid_phone":{"fa":"شماره نامعتبر:","en":"invalid phone:"},"acc_delete_q":{"fa":"حذف <b>{n}</b>؟","en":"delete <b>{n}</b>?"},
"prof_first_q":{"fa":"نام:","en":"first name:"},"prof_last_q":{"fa":"فامیل:","en":"last name:"},
"prof_bio_q":{"fa":"بیو:","en":"bio:"},"prof_user_q":{"fa":"یوزرنیم:","en":"username:"},
"prof_photo_menu":{"fa":"عکس پروفایل","en":"profile photo"},"prof_set_photo":{"fa":"تنظیم عکس جدید","en":"set new photo"},
"prof_del_photo":{"fa":"حذف عکس‌ها","en":"delete photos"},"prof_send_photo":{"fa":"عکس رو بفرست:","en":"send photo:"},
"prof_no_photo":{"fa":"عکس نبود:","en":"no photo:"},"prof_deleting":{"fa":"در حال حذف...","en":"deleting..."},
"prof_uploading":{"fa":"در حال آپلود...","en":"uploading..."},"ch_photo_menu":{"fa":"عکس کانال","en":"channel photo"},
"ch_new_type":{"fa":"نوع کانال:","en":"channel type:"},"ch_new_name_q":{"fa":"اسم کانال:","en":"channel name:"},
"ch_new_user_q":{"fa":"یوزرنیم:","en":"username:"},"ch_creating":{"fa":"در حال ساخت...","en":"creating..."},
"ch_created":{"fa":"ساخته شد","en":"created"},"ch_no_channels":{"fa":"هنوز کانالی نساختی.","en":"no channels yet."},
"ch_created_list":{"fa":"کانال‌هایی که ساخت","en":"channels you created"},"ch_send_q":{"fa":"متن:","en":"text:"},
"ch_file_q":{"fa":"فایل:","en":"file:"},"ch_caption_q":{"fa":"کپشن:","en":"caption:"},
"ch_link_fetch":{"fa":"در حال دریافت...","en":"fetching..."},"ch_link_q":{"fa":"لینک:","en":"link:"},
"ch_delete_q":{"fa":"حذف کانال؟","en":"delete channel?"},"listener_on":{"fa":"روشن","en":"on"},
"listener_off":{"fa":"خاموش","en":"off"},"listener_restart_all":{"fa":"ری‌استارت همه","en":"restart all"},
"listener_cfg":{"fa":"تنظیمات","en":"cfg"},"ld_auto_join":{"fa":"جوین خودکار","en":"auto-join"},
"ld_progress_per_acc":{"fa":"پیشرفت برای هر اکانت جداست","en":"progress per account"},
"ld_add_q":{"fa":"لینک:","en":"link:"},"ld_reset_prog":{"fa":"بازنشانی پیشرفت همه","en":"reset all progress"},
"ld_reset_list":{"fa":"بازنشانی لیست","en":"reset list"},"ld_add":{"fa":"افزودن","en":"+ add"},
"op_joiner":{"fa":"جوینر","en":"joiner"},"op_lefter":{"fa":"لفتر","en":"lefter"},
"op_autotar":{"fa":"اتو تار","en":"auto-tar"},"op_send":{"fa":"ارسال","en":"send"},
"op_running":{"fa":"در حال اجرا","en":"running"},"op_paused":{"fa":"متوقف","en":"paused"},
"op_queued":{"fa":"در صف","en":"queued"},"op_done":{"fa":"تکمیل","en":"done"},
"op_failed":{"fa":"خطا","en":"failed"},"op_cancelled":{"fa":"لغو شده","en":"cancelled"},
"op_empty":{"fa":"خالی","en":"empty"},"op_draft":{"fa":"پیش‌نویس","en":"draft"},
"op_joined":{"fa":"جوین","en":"joined"},"op_sent":{"fa":"ارسال","en":"sent"},
"op_left":{"fa":"ترک","en":"left"},"op_failed_c":{"fa":"خطا","en":"failed"},
"op_tried":{"fa":"تلاش","en":"tried"},"op_wave":{"fa":"موج","en":"wave"},
"op_round":{"fa":"دور","en":"round"},"op_phase":{"fa":"مرحله","en":"phase"},
"op_limit":{"fa":"سقف","en":"limit"},"op_already":{"fa":"قبلا عضو","en":"already"},
"op_blocked":{"fa":"بلاک","en":"blocked"},"op_skipped_seen":{"fa":"دیده‌شده","en":"seen"},
"op_skipped_banned":{"fa":"بلاک‌شده","en":"banned"},"op_rejected":{"fa":"غیرفعال","en":"inactive"},
"stats_title":{"fa":"آمار","en":"stats"},"stats_done":{"fa":"موفق","en":"done"},
"stats_failed":{"fa":"ناموفق","en":"failed"},"stats_errors":{"fa":"خطاها","en":"errors"},
"stats_running":{"fa":"در حال اجرا","en":"running now"},"errors_none":{"fa":"خالی","en":"empty"},
"send_step1":{"fa":"اکانت(ها)","en":"accounts"},"send_step2":{"fa":"متن را بفرست","en":"send the message text"},
"send_step3":{"fa":"مقصد؟","en":"select target"},"send_step4":{"fa":"حداکثر؟","en":"max messages"},
"send_target_pv":{"fa":"پیوی","en":"pv only"},"send_target_gr":{"fa":"گروه‌ها","en":"groups only"},
"send_target_both":{"fa":"هر دو","en":"both"},"send_grp_only":{"fa":"فقط گروه‌های واقعی","en":"real groups only"},
"send_infinite":{"fa":"لوپ بی‌نهایت","en":"infinite loop"},"send_loop_delay":{"fa":"بین دورها","en":"loop delay"},
"send_rescan":{"fa":"اسکن مجدد در هر دور","en":"rescan each round"},"send_edit":{"fa":"تاخیر ویرایش","en":"edit delay"},
"send_random":{"fa":"تصادفی","en":"random"},"send_ph_list":{"fa":"لیست","en":"list"},
"send_multi":{"fa":"چند مرحله‌ای","en":"multi-step edit"},"send_attach":{"fa":"پیوست فایل","en":"attach file"},
"send_auto_left":{"fa":"ترک خودکار","en":"auto leave"},"send_attach_q":{"fa":"فایل:","en":"send file:"},
"send_loop_q":{"fa":"ثانیه بین دورها:","en":"seconds between loops:"},"send_edit_q":{"fa":"ثانیه:","en":"seconds:"},
"send_ph_q":{"fa":"متن جانشین:","en":"placeholder text:"},"send_max_q":{"fa":"عدد (0=بی‌نهایت):","en":"number (0=∞):"},
"send_unlimited":{"fa":"بی‌نهایت","en":"unlimited"},"send_custom":{"fa":"دلخواه","en":"custom"},
"jl_title":{"fa":"جوینر","en":"joiner"},"jl_select":{"fa":"کدام اکانت؟","en":"select accounts"},
"jl_selected":{"fa":"انتخاب‌شده","en":"selected"},"jl_speed":{"fa":"سرعت","en":"speed"},
"jl_grp_only":{"fa":"فقط گروه‌ها","en":"groups only"},"jl_max":{"fa":"سقف","en":"max join"},
"jl_speed_ultra":{"fa":"فوق‌سریع","en":"ultra"},"jl_speed_fast":{"fa":"سریع","en":"fast"},
"jl_speed_normal":{"fa":"عادی","en":"normal"},"jl_speed_safe":{"fa":"امن","en":"safe"},
"jl_ld":{"fa":"لینک‌دونی","en":"linkdonies"},"jl_max_q":{"fa":"عدد:","en":"number:"},
"jl_no_account":{"fa":"اول اکانت اضافه کن.","en":"add an account first."},
"lf_title":{"fa":"لفتر","en":"lefter"},"lf_mode":{"fa":"حالت ترک","en":"leave mode"},
"lf_mode_all":{"fa":"همه گروه‌ها و کانال‌ها","en":"all chats"},"lf_mode_groups":{"fa":"فقط گروه‌ها","en":"groups only"},
"lf_mode_channels":{"fa":"فقط کانال‌ها","en":"channels only"},"lf_mode_closed":{"fa":"فقط گروه‌های بسته","en":"closed groups"},
"lf_delay":{"fa":"تاخیر","en":"delay"},"at_title":{"fa":"قالب‌ها","en":"templates"},
"at_desc":{"fa":"قالب = ست کامل از تنظیمات","en":"template = full config set"},"at_new":{"fa":"ساخت قالب","en":"+ new template"},
"at_channel":{"fa":"کانال","en":"channel"},"at_profile":{"fa":"پروفایل","en":"profile"},
"at_joiner":{"fa":"جوین","en":"joiner"},"at_sender":{"fa":"ارسال","en":"sender"},
"at_pv":{"fa":"پیوی","en":"pv"},"at_lefter":{"fa":"ترک","en":"lefter"},
"at_rename":{"fa":"تغییر نام","en":"rename"},"at_run":{"fa":"اجرا روی اکانت","en":"run on accounts"},
"at_delete":{"fa":"حذف","en":"delete"},"at_mode_only":{"fa":"فقط ارسال","en":"send only"},
"at_mode_js":{"fa":"جوین + ارسال","en":"join + send"},"at_mode_jsl":{"fa":"جوین + ارسال + ترک","en":"join + send + leave"},
"at_apply_acc":{"fa":"اعمال روی اکانت‌ها","en":"apply to accounts"},"at_run_title":{"fa":"اجرای قالب","en":"run template"},
"at_rename_q":{"fa":"نام:","en":"name:"},"at_delete_q":{"fa":"حذف <b>{n}</b>؟","en":"delete <b>{n}</b>?"},
"cfg_title":{"fa":"تنظیمات","en":"settings"},"cfg_lang":{"fa":"زبان","en":"language"},
"cfg_lang_fa":{"fa":"فارسی","en":"persian"},"cfg_lang_en":{"fa":"انگلیسی","en":"english"},
"cfg_join_delay":{"fa":"تاخیر جوین","en":"join delay"},"cfg_wave_size":{"fa":"اندازه موج","en":"wave size"},
"cfg_extract":{"fa":"سقف استخراج","en":"extract limit"},"cfg_wait":{"fa":"انتظار لینک","en":"wait for links"},
"cfg_auto_join":{"fa":"جوین خودکار لینک‌دونی","en":"auto-join linkdoni"},"cfg_listener":{"fa":"لیسنر","en":"listener"},
"cfg_value_q":{"fa":"مقدار جدید برای {k}:","en":"new value for {k}:"},"cfg_invalid":{"fa":"عدد نامعتبر","en":"invalid number"},
"mode":{"fa":"حالت","en":"mode"},"max":{"fa":"سقف","en":"max"},"text":{"fa":"متن","en":"text"},
"target":{"fa":"مقصد","en":"target"},"delay":{"fa":"تاخیر","en":"delay"},"file":{"fa":"فایل","en":"file"},
"vars":{"fa":"متغیرها","en":"vars"},"chat":{"fa":"چت","en":"chat"},
"sender":{"fa":"فرستنده","en":"sender"},"from":{"fa":"از","en":"from"},
"debug":{"fa":"عیب‌یابی","en":"debug"},"link_sent":{"fa":"لینک","en":"link"},"failed":{"fa":"ناموفق","en":"failed"},
"ph_start":{"fa":"شروع","en":"start"},"ph_connect":{"fa":"اتصال","en":"connecting"},
"ph_connected":{"fa":"متصل شد: {n}","en":"connected: {n}"},"ph_connect_fail":{"fa":"اتصال ناموفق: {n}","en":"connect failed: {n}"},
"ph_auto_join":{"fa":"جوین خودکار {i}/{t}","en":"auto-join {i}/{t}"},
"ph_extract":{"fa":"موج {n}: استخراج","en":"wave {n}: extracting"},
"ph_deep":{"fa":"موج {n}: اسکن عمیق","en":"wave {n}: deep scan"},
"ph_wait":{"fa":"انتظار {s}ث ({i}/{t})","en":"wait {s}s ({i}/{t})"},
"ph_links":{"fa":"موج {n}: {c} لینک","en":"wave {n}: {c} links"},
"ph_wave_done":{"fa":"موج {n} تمام","en":"wave {n} done"},"ph_no_links":{"fa":"لینک جدیدی نیامد","en":"no new links"},
"ph_limit":{"fa":"به سقف رسید","en":"limit reached"},"ph_collecting":{"fa":"جمع‌آوری مخاطبین","en":"collecting targets"},
"ph_sending":{"fa":"ارسال به {n}","en":"sending to {n}"},"ph_loop":{"fa":"دور {n}","en":"loop {n}"},
"ph_send_final":{"fa":"ارسال نهایی","en":"final send"},"ph_update_prof":{"fa":"بروزرسانی پروفایل","en":"updating profile"},
"ph_create_ch":{"fa":"ساخت کانال: {n}","en":"creating channel: {n}"},
"ph_leaving":{"fa":"ترک کردن ({m})","en":"leaving ({m})"},"ph_no_targets":{"fa":"مخاطبی نیست","en":"no targets"},
"ph_nothing":{"fa":"چیزی نیست","en":"nothing"},"ph_done":{"fa":"پایان","en":"done"},
"ph_cancelled":{"fa":"لغو شد","en":"cancelled"},"ph_error":{"fa":"خطا: {n}","en":"error: {n}"},
"ph_progress":{"fa":"پیشرفت {a}/{b}","en":"progress {a}/{b}"},
"ph_broadcast_skip":{"fa":"کانال عمومی رد شد","en":"broadcast channel skipped"},
"ph_acc_suspend":{"fa":"اکانت {n} معلق شده","en":"account {n} suspended"},
"ph_reply_ok":{"fa":"پاسخ موفق به {u}","en":"reply ok: {u}"},
"ph_reply_fail":{"fa":"پاسخ ناموفق به {u}: {e}","en":"reply failed: {u}: {e}"},
"ph_new_message":{"fa":"پیام جدید برای {n}","en":"new message for {n}"},
"ph_waves_end":{"fa":"موج‌ها تمام شد","en":"waves done"},
}
def T(k, **kw):
    e = _TR.get(k)
    if not e: return str(k)
    lang = _get_lang(); s = e.get(lang) or e.get("en") or str(k)
    for a, b in kw.items(): s = s.replace("{"+a+"}", str(b))
    return s

# ═══════════════ HELPERS ═══════════════
def _load(path, default):
    if not os.path.exists(path): return dict(default) if isinstance(default, dict) else default
    try:
        with open(path, encoding="utf-8") as f: d = json.load(f)
        if isinstance(default, dict) and isinstance(d, dict): return {**default, **d}
        return d
    except Exception: return dict(default) if isinstance(default, dict) else default
def _save(path, data):
    try: os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    except Exception: pass
    with open(path + ".tmp", "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(path + ".tmp", path)
def _fmt_error(e):
    if e is None: return "—"
    if isinstance(e, dict):
        return str(e.get("client_show_message") or e.get("status_det") or e.get("status") or e)[:300]
    return str(e)[:300]
def _is_rate_limit(ex):
    return any(k in str(ex).upper() for k in ("TOO_REQUESTS","RATE_LIMIT","FLOOD","TOO_MANY","استفاده بیش از حد","بیش از حد مجاز"))
def _is_auth_dead(ex): return "AUTH_DEAD" in str(ex) or "NO_SESSION" in str(ex) or "NOT_REGISTERED" in str(ex)

def normalize_phone(raw):
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
    m = re.search(r"/(?:joing|join|joinchat)/([A-Za-z0-9_\-]+)", s)
    if m: return "j:" + m.group(1)
    m = re.search(r"(?:rubika\.ir|ble\.rip)/([A-Za-z0-9_\-]+)", s)
    if m: return "u:" + m.group(1)
    return "x:" + s[:60]

# ═══════════════ PATHS ═══════════════
ACC_FILE = os.path.join(SOROOSH_DIR, "accounts.json")
CFG_FILE = os.path.join(SOROOSH_DIR, "config.json")
ERRORS_FILE = os.path.join(SOROOSH_DIR, "errors.json")
OPS_FILE = os.path.join(SOROOSH_DIR, "ops.json")
TEMPLATES_FILE = os.path.join(SOROOSH_DIR, "templates.json")
SEEN_FILE = os.path.join(SOROOSH_DIR, "seen_links.json")
BANNED_FILE = os.path.join(SOROOSH_DIR, "banned_groups.json")
LDPROG_FILE = os.path.join(SOROOSH_DIR, "linkdoni_progress.json")
PV_ITEMS_FILE = os.path.join(SOROOSH_DIR, "pv_items.json")
PV_REPORT_FILE = os.path.join(SOROOSH_DIR, "pv_report.json")
PV_COUNTS_FILE = os.path.join(SOROOSH_DIR, "pv_counts.json")
PV_WM_FILE = os.path.join(SOROOSH_DIR, "pv_wm.json")
PV_ACCOUNT_FILE = os.path.join(SOROOSH_DIR, "pv_per_account.json")
LINK_DONIES_FILE = os.path.join(SOROOSH_DIR, "linkdonies.json")

_SEEN_CACHE: Dict[str, Set[str]] = {}
_BANNED_CACHE: Dict[str, Dict[str, Any]] = {}
_LDPROG_CACHE: Dict[str, Dict[str, int]] = {}
_PV_WM: Optional[Dict[str, Dict[str, int]]] = None
_PV_WM_DIRTY = False

def _load_seen(aid):
    if not aid: return set()
    if aid in _SEEN_CACHE: return _SEEN_CACHE[aid]
    all_d = _load(SEEN_FILE, {}) or {}
    acc = all_d.get(aid) or {}
    _SEEN_CACHE[aid] = set(acc.keys()); return _SEEN_CACHE[aid]
def _mark_seen(aid, h):
    if not aid or not h: return
    seen = _load_seen(aid)
    if h in seen: return
    seen.add(h)
    try:
        all_d = _load(SEEN_FILE, {}) or {}
        acc = all_d.setdefault(aid, {}); acc[h] = 1
        if len(acc) > 50000:
            all_d[aid] = dict(list(acc.items())[-40000:]); _SEEN_CACHE[aid] = set(all_d[aid].keys())
        _save(SEEN_FILE, all_d)
    except Exception: pass
def _is_seen(aid, h): return bool(aid and h and h in _load_seen(aid))
def _clear_seen(aid=None):
    if aid:
        _SEEN_CACHE.pop(aid, None)
        try:
            all_d = _load(SEEN_FILE, {}) or {}; all_d.pop(aid, None); _save(SEEN_FILE, all_d)
        except Exception: pass
    else:
        _SEEN_CACHE.clear()
        try: _save(SEEN_FILE, {})
        except Exception: pass
def _seen_count(aid): return len(_load_seen(aid))

def _load_banned(aid):
    if not aid: return {}
    if aid in _BANNED_CACHE: return _BANNED_CACHE[aid]
    all_d = _load(BANNED_FILE, {}) or {}
    acc = all_d.get(aid) or {}
    if not isinstance(acc, dict): acc = {}
    _BANNED_CACHE[aid] = acc; return acc
def _mark_banned(aid, h, reason=""):
    if not aid or not h: return
    try:
        all_d = _load(BANNED_FILE, {}) or {}
        acc = all_d.setdefault(aid, {})
        acc[h] = {"reason": str(reason)[:120], "ts": int(time.time())}
        _BANNED_CACHE[aid] = acc; _save(BANNED_FILE, all_d)
    except Exception: pass
def _is_banned(aid, h): return bool(aid and h and h in _load_banned(aid))
def _clear_banned(aid=None):
    if aid:
        _BANNED_CACHE.pop(aid, None)
        try:
            all_d = _load(BANNED_FILE, {}) or {}; all_d.pop(aid, None); _save(BANNED_FILE, all_d)
        except Exception: pass
    else:
        _BANNED_CACHE.clear()
        try: _save(BANNED_FILE, {})
        except Exception: pass
def _banned_count(aid): return len(_load_banned(aid))

def _load_ldprog(aid):
    if not aid: return {}
    if aid in _LDPROG_CACHE: return _LDPROG_CACHE[aid]
    all_d = _load(LDPROG_FILE, {}) or {}
    acc = all_d.get(aid) or {}
    if not isinstance(acc, dict): acc = {}
    _LDPROG_CACHE[aid] = acc; return acc
def _get_ld_last(aid, url):
    try: return int(_load_ldprog(aid).get(url, 0))
    except Exception: return 0
def _set_ld_last(aid, url, max_id):
    if not aid or not url: return
    try:
        all_d = _load(LDPROG_FILE, {}) or {}
        acc = all_d.setdefault(aid, {})
        old = int(acc.get(url, 0))
        if int(max_id) > old:
            acc[url] = int(max_id); _LDPROG_CACHE[aid] = acc; _save(LDPROG_FILE, all_d)
    except Exception: pass
def _reset_ld_progress(aid=None):
    if aid:
        _LDPROG_CACHE.pop(aid, None)
        try:
            all_d = _load(LDPROG_FILE, {}) or {}; all_d.pop(aid, None); _save(LDPROG_FILE, all_d)
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

DEFAULT_PV_ITEMS = {"enabled":False,"delay_seconds":0,"reply_once":True,"max_replies":1,
    "notify":True,"notify_on_receive":True,"notify_on_reply":True,"poll_seconds":3,
    "items":[{"kind":"text","text":"سلام 👋"}]}
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
    per[aid] = {k: cfg.get(k) for k in ("enabled","delay_seconds","reply_once","max_replies",
        "notify","notify_on_receive","notify_on_reply","poll_seconds","items")}
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
        acc[uid]["last_seen"] = now; acc[uid]["count"] = acc[uid].get("count", 1) + 1
        if info:
            for k, v in info.items():
                if v is not None: acc[uid][k] = v
    else:
        e = {"first_seen":now,"last_seen":now,"count":1,"replied":False,"reply_ok":False,"error":None,"blocked":False}
        if info: e.update({k: v for k, v in info.items() if v is not None})
        acc[uid] = e
    _save_pv_report(rep)
def _record_pv_reply(aid, uid, ok, err=None):
    rep = _load_pv_report(); acc = rep.setdefault(aid, {}); uid = str(uid)
    if uid not in acc:
        acc[uid] = {"first_seen":int(time.time()),"last_seen":int(time.time()),"count":1,"replied":False,"reply_ok":False}
    acc[uid]["replied"] = True; acc[uid]["replied_at"] = int(time.time())
    acc[uid]["reply_ok"] = bool(ok)
    if err:
        acc[uid]["error"] = str(err)[:200]; acc[uid]["blocked"] = "FORBIDDEN" in str(err).upper()
    else: acc[uid]["error"] = None; acc[uid]["blocked"] = False
    _save_pv_report(rep)

DEFAULT_LINK_DONIES = ["@linkdony_rubikas","@lovo_lovoo0","@CBkJCCFE1IZHOEMRXTHDONBZMQLEJJGK"]
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

DEFAULT_CFG = {"listener":1,"auto_join_linkdoni":1,"wave_size":50,"extract_limit":300,
    "join_delay":0.5,"deep_scan_pages":30,"deep_scan_page_size":100,
    "wait_for_links_sec":90,"max_wait_rounds":20}

def _load_errors():
    d = _load(ERRORS_FILE, []); return d if isinstance(d, list) else []
def add_error(source, error, target=None, account=None):
    err_up = str(error).upper()
    if "CHANNELPRIVATEERROR" in err_up or "CHANNEL_PRIVATE" in err_up: return
    if "REQUEST WAS UNSUCCESSFUL" in err_up: return
    errs = _load_errors()
    errs.append({"time":int(time.time()),"source":str(source)[:40],"error":str(error)[:300],
        "target":(str(target)[:120] if target is not None else None),
        "account":(str(account)[:60] if account is not None else None)})
    if len(errs) > 500: errs = errs[-500:]
    try: _save(ERRORS_FILE, errs)
    except Exception: pass
def clear_errors():
    try: _save(ERRORS_FILE, [])
    except Exception: pass

def list_accounts(): return _load(ACC_FILE, {})
def save_accounts(a): _save(ACC_FILE, a)
def get_account(aid): return list_accounts().get(aid)
def add_account(aid, phone, name, session_string, user_id=None):
    """دقیقاً مثل سروش: session_string در accounts.json ذخیره میشه."""
    accounts = list_accounts()
    accounts[aid] = {"phone": phone, "name": name, "session_string": session_string,
                     "user_id": user_id, "created": int(time.time()), "channels": []}
    save_accounts(accounts); return accounts[aid]

def remove_account(aid):
    accounts = list_accounts(); a = accounts.pop(aid, None); save_accounts(accounts)
    _STATS_CACHE.pop(aid, None)
    if a:
        sess = a.get("session_string") or a.get("session_name") or os.path.join(SESSIONS_DIR, aid)
        for f in glob.glob(sess + "*"):
            try: os.remove(f)
            except Exception: pass
    try: _delete_pv_account(aid)
    except Exception: pass
    try: _clear_seen(aid); _clear_banned(aid); _reset_ld_progress(aid)
    except Exception: pass

def _get_sess_path(aid):
    """helper — مسیر سشن (سبک سروش)."""
    acc = get_account(aid) or {}
    return acc.get("session_string") or _get_sess_path(aid)


def get_stored_channels(aid):
    a = get_account(aid); return list(a.get("channels") or []) if a else []
def get_own_channel_ids(aid):
    out = set()
    for ch in get_stored_channels(aid):
        for k in ("id","raw_id","guid"):
            cid = ch.get(k)
            if cid is not None:
                try: out.add(str(cid))
                except Exception: pass
    return out
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
    if aid in accounts and 0 <= idx < len(accounts[aid].get("channels", [])):
        accounts[aid]["channels"][idx][key] = value; save_accounts(accounts)

_STATS_CACHE = {}; _STATS_CACHE_TTL = 300

# ═══════════════ RUBPY CLIENT WRAPPER ═══════════════
_ACCOUNT_LOCKS = {}; _ACCOUNT_LOCKS_GUARD = threading.Lock()
def _get_account_lock(aid):
    if not aid: return None
    with _ACCOUNT_LOCKS_GUARD:
        if aid not in _ACCOUNT_LOCKS: _ACCOUNT_LOCKS[aid] = asyncio.Lock()
        return _ACCOUNT_LOCKS[aid]

class SafeClient:
    def __init__(self, aid, session_path, name=None, use_lock=True):
        self.aid = aid; self.session_path = session_path; self.name = name or aid
        self._client = None
        self._lock = _get_account_lock(aid) if use_lock else None
        self._locked = False
    async def __aenter__(self):
        if self._lock:
            try: await asyncio.wait_for(self._lock.acquire(), timeout=10); self._locked = True
            except (asyncio.TimeoutError, asyncio.CancelledError): self._locked = False
        try:
            await self._connect(); return self
        except BaseException:
            if self._locked:
                try: self._lock.release()
                except Exception: pass
                self._locked = False
            raise
    async def __aexit__(self, *args, **kwargs):
        try: await self._disconnect()
        finally:
            if self._locked:
                try: self._lock.release()
                except Exception: pass
                self._locked = False
    async def _connect(self):
        if self._client is not None: return
        cli = _RClient(name=self.session_path)
        try: await cli.start()
        except Exception as e: raise RuntimeError(f"NO_SESSION: {e}")
        self._client = cli
    async def _disconnect(self):
        if self._client is not None:
            try: await self._client.disconnect()
            except Exception: pass
            self._client = None
    def __getattr__(self, name):
        if name.startswith("_"): raise AttributeError(name)
        if self._client is None: raise AttributeError(f"not connected: {name}")
        return getattr(self._client, name)

async def _connect_with_retry(aid, session_path=None, name=None, tries=3, per_timeout=35):
    if session_path is None:
        session_path = _get_sess_path(aid)
    last_err = None
    for i in range(tries):
        cli = None
        try:
            cli = SafeClient(aid, session_path, name=name, use_lock=False)
            await asyncio.wait_for(cli.__aenter__(), timeout=per_timeout)
            return cli, None
        except asyncio.TimeoutError:
            last_err = f"Timeout #{i+1}/{tries}"
            try:
                if cli: await cli._disconnect()
            except Exception: pass
            await asyncio.sleep(2 + i)
        except asyncio.CancelledError:
            try:
                if cli: await cli._disconnect()
            except Exception: pass
            raise
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:120]}"
            try:
                if cli: await cli._disconnect()
            except Exception: pass
            await asyncio.sleep(2 + i)
    return None, last_err


# ═══════════════ RUBPY HELPERS (with exact API) ═══════════════
def _to_dict(o):
    if o is None: return {}
    if isinstance(o, dict): return o
    if hasattr(o, "to_dict"):
        try: return o.to_dict()
        except Exception: pass
    d = {}
    for k in dir(o):
        if k.startswith("_"): continue
        try:
            v = getattr(o, k)
            if not callable(v): d[k] = v
        except Exception: continue
    return d

def _chats_from_update(upd) -> List[Dict[str, Any]]:
    """Normalize get_chats() update into list of dicts."""
    d = _to_dict(upd)
    out = []
    chats = d.get("chats") or (d.get("data") or {}).get("chats") or []
    if not isinstance(chats, list): chats = []
    for c in chats:
        c = c if isinstance(c, dict) else _to_dict(c)
        abs_obj = c.get("abs_object") or c.get("absObject") or c
        guid = abs_obj.get("object_guid") or abs_obj.get("objectGuid") or c.get("object_guid")
        ctype = abs_obj.get("type") or c.get("type") or ""
        title = abs_obj.get("first_name") or abs_obj.get("title") or abs_obj.get("name") or c.get("title") or ""
        uname = abs_obj.get("username") or ""
        if not guid: continue
        out.append({"guid":guid,"type":ctype,"title":title,"username":uname,
            "is_blocked":bool(abs_obj.get("is_blocked")),"raw":c})
    return out

def _messages_from_update(upd) -> List[Dict[str, Any]]:
    d = _to_dict(upd)
    msgs = d.get("messages") or (d.get("data") or {}).get("messages") or []
    if not isinstance(msgs, list): msgs = []
    out = []
    for m in msgs:
        m = m if isinstance(m, dict) else _to_dict(m)
        out.append({"id":str(m.get("message_id") or m.get("messageId") or m.get("id") or ""),
            "text":m.get("text") or "","sender":str(m.get("sender_id") or m.get("author_object_guid") or ""),
            "is_mine":bool(m.get("is_mine")),"time":str(m.get("time") or m.get("date") or ""),
            "type":m.get("type") or "Text"})
    return out

def _extract_guid_from_update(upd):
    if upd is None: return None
    d = _to_dict(upd)
    for path in (("chat",), ("channel",), ("group",), ("data","chat"), ("data","channel")):
        cur = d
        ok = True
        for p in path:
            if isinstance(cur, dict) and p in cur: cur = cur[p]
            else: ok = False; break
        if ok and isinstance(cur, dict):
            g = cur.get("object_guid") or cur.get("channel_guid") or cur.get("group_guid")
            if isinstance(g, str) and g: return g
    for k in ("object_guid","channel_guid","group_guid","chat_guid"):
        if k in d and isinstance(d[k], str): return d[k]
    return None

# ─── The REAL rubpy join/leave operations ───
async def _try_join(bot, link):
    """
    Uses rubpy's REAL methods:
      - join_group(link)           for group hash links
      - join_channel_by_link(link) for channel invite links
      - join_channel_action(guid,'Join') for channel by guid
    Returns (ok:bool, guid_or_err, tag:str, entity_guid_for_post:str|None)
    """
    link = (link or "").strip()
    if not link: return False, "empty-link", "join-failed", None
    is_hash = "/joing/" in link or "/join/" in link or "/joinchat/" in link
    is_user = link.startswith("@") or (not is_hash and "/" not in link)
    # 1) Hash link: try join_group first, then join_channel_by_link
    if is_hash:
        try:
            r = await bot.join_group(link)
            return True, None, "join_group", None
        except Exception as e:
            err = _fmt_error(e)
            if "ALREADY" in err.upper() or "MEMBER" in err.upper():
                return True, None, "already", None
            if _is_rate_limit(e): raise
            # try channel version
            try:
                r = await bot.join_channel_by_link(link)
                return True, None, "join_channel_by_link", None
            except Exception as e2:
                err2 = _fmt_error(e2)
                if "ALREADY" in err2.upper() or "MEMBER" in err2.upper():
                    return True, None, "already", None
                return False, err2 or err, "join-failed", None
    # 2) Username (@xxx) or plain: try join_channel_by_link
    if is_user:
        uname = link.lstrip("@")
        # rubpy join_channel_by_link accepts hash, but for public usernames we need guid
        # Try: strip to /username hash via getLinkFromAppUrl
        try:
            app_url = f"https://rubika.ir/{uname}"
            r = await bot.get_link_from_app_url(app_url)
            d = _to_dict(r)
            guid = (d.get("channel",{}) or {}).get("channel_guid") if isinstance(d.get("channel"),dict) else None
            if not guid: guid = d.get("channel_guid") or d.get("group_guid") or d.get("object_guid")
            if guid:
                try:
                    await bot.join_channel_action(channel_guid=guid, action="Join")
                    return True, guid, "join_channel_action", guid
                except Exception as e:
                    err = _fmt_error(e)
                    if "ALREADY" in err.upper(): return True, guid, "already", guid
                    return False, err, "join-failed", guid
        except Exception: pass
        # fallback: try as channel link
        try:
            await bot.join_channel_by_link(uname)
            return True, None, "join_channel_by_link", None
        except Exception as e:
            err = _fmt_error(e)
            if "ALREADY" in err.upper(): return True, None, "already", None
            return False, err, "join-failed", None
    return False, "unknown-link-format", "join-failed", None

async def _try_leave_one(bot, target):
    """
    Uses rubpy's REAL methods:
      - leave_group(group_guid)  for groups (g...)
      - join_channel_action(channel_guid, 'Remove') for channels (c...)
    """
    guid = target.get("guid") or target.get("id"); kind = target.get("kind")
    if not guid: return False, "no-guid"
    g = str(guid)
    try:
        if g.startswith("c") or kind == "channel":
            await bot.join_channel_action(channel_guid=g, action="Remove")
            return True, None
        elif g.startswith("g") or kind == "group":
            await bot.leave_group(group_guid=g)
            return True, None
        else:
            # try both
            try:
                await bot.join_channel_action(channel_guid=g, action="Remove"); return True, None
            except Exception:
                await bot.leave_group(group_guid=g); return True, None
    except Exception as e:
        msg = str(e).upper()
        if "NOT_MEMBER" in msg or "NOT_PARTICIPANT" in msg: return True, "already_left"
        return False, _fmt_error(e)

async def _get_all_chats(bot) -> List[Dict[str, Any]]:
    try:
        upd = await bot.get_chats()
        return _chats_from_update(upd)
    except Exception as e:
        flog(f"[get_chats] {type(e).__name__}: {e}", "warning")
        return []

def _is_true_group(c):
    t = (c.get("type") or "").strip()
    if t != "Group": return False
    return True
def _is_true_channel(c):
    return (c.get("type") or "").strip() == "Channel"

async def _collect_targets_for_send(bot, target, exclude_ids=None, groups_only=False):
    exclude_ids = exclude_ids or set()
    out = []
    chats = await _get_all_chats(bot)
    try:
        me = await bot.get_me(); my_guid = _to_dict(me).get("user",{}).get("user_guid") or _to_dict(me).get("user_guid")
    except Exception: my_guid = None
    for c in chats:
        try:
            guid = c.get("guid")
            if not guid: continue
            if guid in exclude_ids: continue
            t = (c.get("type") or "").strip()
            if t == "User" and target in ("pv","both"):
                if my_guid and guid == my_guid: continue
                out.append({"type":"pv","target":guid,"entity":guid,"name":c.get("title") or "دوست"})
            elif t == "Group" and target in ("groups","both"):
                out.append({"type":"group","target":guid,"entity":guid,"name":c.get("title") or guid[:15]})
            elif t == "Channel" and target == "channels":
                out.append({"type":"channel","target":guid,"entity":guid,"name":c.get("title") or guid[:15]})
        except Exception: continue
    return out

def _extract_links_from_text(txt):
    out = []
    if not txt: return out
    for m in re.finditer(r'(?:https?://)?(?:rubika\.ir|ble\.rip)/(?:joing|join|joinchat)/([A-Za-z0-9_\-]{10,})', txt, re.I):
        out.append(f"https://rubika.ir/joing/{m.group(1)}")
    for m in re.finditer(r'(?<![A-Za-z0-9_@])@([A-Za-z][A-Za-z0-9_]{4,40})', txt):
        out.append("@" + m.group(1))
    seen = set(); res = []
    for lk in out:
        k = _hash_of(lk)
        if k and k not in seen: seen.add(k); res.append(lk)
    return res

async def _extract_from_linkdoni(aid, bot, url, limit=300, log=None, deep_scan=False):
    links = []
    try:
        # join the linkdoni first
        ok, _, _, _ = await _try_join(bot, url)
        # resolve guid
        guid = None
        if url.startswith("@") or "/" not in url:
            un = url.lstrip("@")
            try:
                r = await bot.get_link_from_app_url(f"https://rubika.ir/{un}")
                d = _to_dict(r)
                ch = d.get("channel") or {}
                if isinstance(ch, dict): guid = ch.get("channel_guid")
                if not guid: guid = d.get("channel_guid") or d.get("object_guid")
            except Exception: pass
        else:
            # hash link → after join, get_chats to find the new one
            try:
                chats = await _get_all_chats(bot)
                # pick most recently joined - heuristic: match hash
                h = _hash_of(url)
                for c in chats:
                    if h in str(c): guid = c["guid"]; break
                if not guid and chats: guid = chats[-1]["guid"]  # last is usually newest
            except Exception: pass
        if not guid: return links
        last_max = _get_ld_last(aid, url)
        max_pages = int(_load(CFG_FILE, DEFAULT_CFG).get("deep_scan_pages", 30)) if deep_scan else 3
        page_size = int(_load(CFG_FILE, DEFAULT_CFG).get("deep_scan_page_size", 100)) if deep_scan else 100
        offset = last_max if last_max else 0
        seen = set()
        for page in range(max_pages):
            try:
                msgs_upd = await bot.get_messages(object_guid=guid, max_id=str(offset) if offset else "0",
                                                    limit=str(page_size), sort="FromMax")
            except Exception: break
            msgs = _messages_from_update(msgs_upd)
            if not msgs: break
            max_seen = offset
            for m in msgs:
                try:
                    mid = int(m["id"]) if m["id"] else 0
                    if mid > max_seen: max_seen = mid
                    if mid in seen: continue
                    seen.add(mid)
                except Exception: pass
                if m.get("text"): links.extend(_extract_links_from_text(m["text"]))
            if max_seen > offset: offset = max_seen
            if len(msgs) < page_size: break
            await asyncio.sleep(0.15)
        if offset > last_max: _set_ld_last(aid, url, offset)
    except Exception as e:
        if log: log(f"extract warn: {_fmt_error(e)[:80]}")
    return links

# ═══════════════ LOGIN ═══════════════
_LOGIN_TMP = {}
_rubika_loop = None; _rubika_loop_thread = None; _rubika_loop_lock = threading.Lock()
def _run_rubika_loop():
    global _rubika_loop
    _rubika_loop = asyncio.new_event_loop(); asyncio.set_event_loop(_rubika_loop); _rubika_loop.run_forever()
def ensure_rubika_loop():
    global _rubika_loop_thread
    with _rubika_loop_lock:
        if _rubika_loop_thread is None or not _rubika_loop_thread.is_alive():
            _rubika_loop_thread = threading.Thread(target=_run_rubika_loop, daemon=True, name="rubika-loop")
            _rubika_loop_thread.start(); time.sleep(0.5)

async def _do_full_login(phone, code, admin_id):
    """interactive login — دقیقاً مثل سروش."""
    aid = "acc_" + secrets.token_hex(4)
    sess_path = os.path.join(SESSIONS_DIR, aid)
    loop = asyncio.get_running_loop()
    input_queue = queue.Queue()
    pending_inputs[admin_id] = {"step":"login","q":input_queue,"aid":aid,"sess_path":sess_path}
    def fake_input(prompt=""):
        msg = str(prompt).strip() or "مقدار بعدی رو بفرست:"
        asyncio.run_coroutine_threadsafe(tg_send(f"📨 {msg}", parse_mode="HTML"), loop)
        try: return input_queue.get(timeout=300)
        except Exception as e: raise RuntimeError(f"input timeout: {e}")
    input_queue.put(code)
    def worker():
        import builtins as _b
        old_in = _b.input
        _b.input = fake_input
        try:
            async def run():
                c = _RClient(name=sess_path)
                await c.start(phone_number=phone)
                me = await c.get_me()
                try: await c.disconnect()
                except Exception: pass
                return me
            return asyncio.run(run())
        finally:
            _b.input = old_in
    try:
        me = await asyncio.to_thread(worker)
        d = _to_dict(me); u = d.get("user") or {}
        name = (f"{u.get('first_name','') or ''} {u.get('last_name','') or ''}").strip() or phone
        guid = u.get("user_guid") or u.get("guid")
        add_account(aid, phone, name, sess_path, guid)
        pending_inputs.pop(admin_id, None)
        flog(f"[login] OK {aid} -> {sess_path}.rp")
        return {"ok": True, "aid": aid, "name": name}
    except Exception as e:
        for f in glob.glob(sess_path + "*"):
            try: os.remove(f)
            except Exception: pass
        pending_inputs.pop(admin_id, None)
        flog(f"[login] FAIL: {e}", "error")
        return {"ok": False, "status": str(e)[:300]}


# ═══════════════ LEFTER ═══════════════
async def _lefter_collect(bot, mode="all", exclude_ids=None):
    exclude_ids = exclude_ids or set()
    out = []
    chats = await _get_all_chats(bot)
    for c in chats:
        try:
            guid = c.get("guid"); t = (c.get("type") or "").strip()
            if not guid: continue
            if guid in exclude_ids: continue
            kind = None
            if t == "Group": kind = "group"
            elif t == "Channel": kind = "channel"
            else: continue
            if mode == "groups" and kind != "group": continue
            if mode == "channels" and kind != "channel": continue
            out.append({"guid":guid,"id":guid,"name":c.get("title") or guid[:15],"kind":kind})
        except Exception: continue
    return out

async def _lefter_worker(aid, acc, op_id, mode, delay, log):
    name = acc.get("name") or acc.get("phone") or aid
    op = _get_op(op_id)
    if not op: return
    lock = _get_op_lock(op_id); left = 0; failed = 0
    async def _set_phase(phase):
        async with lock:
            op2 = _get_op(op_id)
            if op2: op2["progress"]["phase"] = phase; _save_op(op2)
        await _refresh_op_panel(op_id)
    async def _finish(phase):
        async with lock:
            op2 = _get_op(op_id)
            if op2:
                op2["progress"]["phase"] = phase
                if op2.get("status") == "running": op2["status"] = "done"; op2["finished_at"] = int(time.time())
                _save_op(op2)
        await _refresh_op_panel(op_id)
    cli = None
    try:
        await _set_phase(T("ph_connect"))
        cli, err = await _connect_with_retry(aid, _get_sess_path(aid), name=name, tries=3)
        if cli is None: await _finish(T("ph_connect_fail", n=err)); return
        await _set_phase(T("ph_collecting"))
        own_ids = get_own_channel_ids(aid)
        targets = await _lefter_collect(cli, mode, exclude_ids=own_ids)
        if not targets: await _finish(T("ph_nothing")); return
        async with lock:
            op2 = _get_op(op_id)
            if op2: op2["progress"]["total"] = len(targets); _save_op(op2)
        for t in targets:
            async with lock:
                op2 = _get_op(op_id)
                if not op2 or op2.get("status") == "cancelled": await _finish(T("ph_cancelled")); return
            try:
                ok, err2 = await asyncio.wait_for(_try_leave_one(cli, t), timeout=30)
                if ok: left += 1
                else: failed += 1; add_error("lefter", err2, t.get("name"), name)
            except Exception as e:
                failed += 1; add_error("lefter", _fmt_error(e), t.get("name"), name)
            async with lock:
                op2 = _get_op(op_id)
                if op2:
                    op2["progress"]["joined"] = left; op2["progress"]["failed"] = failed
                    op2["progress"]["phase"] = T("ph_progress", a=left, b=len(targets)); _save_op(op2)
            if delay > 0: await asyncio.sleep(delay)
        await _finish(f"✓ {left} · ✗ {failed}")
    except asyncio.CancelledError: await _finish(T("ph_cancelled")); raise
    except Exception as e:
        flog(f"[lefter] FATAL: {traceback.format_exc()}", "error")
        await _finish(T("ph_error", n=type(e).__name__))
    finally:
        if cli:
            try: await cli._disconnect()
            except Exception: pass

async def run_lefter(op, log):
    accounts = list_accounts(); sel = op.get("accounts") or []
    if "all" in sel: sel = list(accounts.keys())
    op["progress"] = {"joined":0,"failed":0,"total":0,"phase":T("ph_start")}
    op["status"] = "running"; op["errors"] = []; _save_op(op)
    tasks = []
    for aid in sel:
        a = accounts.get(aid)
        if not a: continue
        tasks.append(asyncio.create_task(_lefter_worker(aid, a, op["id"],
                     op.get("leave_mode","all"), float(op.get("delay",0.5)), log)))
    if tasks: await asyncio.gather(*tasks, return_exceptions=True)
    op2 = _get_op(op["id"])
    if op2 and op2.get("status") not in ("cancelled","done"):
        op2["status"] = "done"; op2["finished_at"] = int(time.time()); _save_op(op2)

# ═══════════════ JOINER ═══════════════
JL_SPEEDS = [("ultra","jl_speed_ultra",0.2),("fast","jl_speed_fast",0.6),
             ("normal","jl_speed_normal",1.5),("slow","jl_speed_safe",4.0)]
JL_JOBS = {}

async def _joiner_worker(aid, acc, op_id, join_delay, max_join, auto_msg, log):
    name = acc.get("name") or acc.get("phone") or aid
    op = _get_op(op_id)
    if not op: return
    link_donies = op.get("link_donies") or list(load_link_donies())
    wave_size = int(op.get("wave_size") or 50); extract_limit = int(op.get("extract_limit") or 300)
    lock = _get_op_lock(op_id)
    joined = 0; failed = 0; wave_num = 0
    skipped_seen = 0; skipped_banned = 0; rejected_inactive = 0; skipped_channel = 0
    cli = None
    cfg = _load(CFG_FILE, DEFAULT_CFG)
    wait_seconds = int(cfg.get("wait_for_links_sec", 90))
    max_wait_rounds = int(cfg.get("max_wait_rounds", 20))
    async def _set_phase(phase):
        async with lock:
            op2 = _get_op(op_id)
            if op2: op2["progress"]["phase"] = phase; _save_op(op2)
        await _refresh_op_panel(op_id)
    async def _finish(phase):
        async with lock:
            op2 = _get_op(op_id)
            if op2:
                op2["progress"]["phase"] = phase
                if op2.get("status") == "running": op2["status"] = "done"; op2["finished_at"] = int(time.time())
                _save_op(op2)
        await _refresh_op_panel(op_id)
    try:
        await _set_phase(T("ph_connect"))
        cli, err = await _connect_with_retry(aid, _get_sess_path(aid), name=name, tries=3)
        if cli is None: await _finish(T("ph_connect_fail", n=err)); return
        try:
            me = await asyncio.wait_for(cli.get_me(), timeout=25)
            me_d = _to_dict(me); un = (me_d.get("user") or {}).get("first_name") or aid
            await _set_phase(T("ph_connected", n=un))
        except Exception as e:
            await _finish(T("ph_error", n=type(e).__name__)); return
        # auto-join linkdoni
        auto_join = int(cfg.get("auto_join_linkdoni", 1))
        if auto_join:
            for i, url in enumerate(link_donies, 1):
                async with lock:
                    op2 = _get_op(op_id)
                    if not op2 or op2.get("status") == "cancelled": await _finish(T("ph_cancelled")); return
                await _set_phase(T("ph_auto_join", i=i, t=len(link_donies)))
                try: await asyncio.wait_for(_try_join(cli, url), timeout=20)
                except Exception: pass
        deep_done = False; wait_round = 0
        while True:
            async with lock:
                op2 = _get_op(op_id)
                if not op2 or op2.get("status") == "cancelled": await _finish(T("ph_cancelled")); return
            if max_join and joined >= max_join: await _finish(T("ph_limit")); return
            wave_num += 1
            await _set_phase(T("ph_extract", n=wave_num))
            # extract in parallel
            tasks = [asyncio.create_task(_extract_from_linkdoni(aid, cli, u, limit=extract_limit, log=log, deep_scan=False)) for u in link_donies]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            new_links = []
            for r in results:
                if isinstance(r, list):
                    for lk in r:
                        h = _hash_of(lk)
                        if not h: continue
                        if _is_seen(aid, h): skipped_seen += 1; continue
                        if _is_banned(aid, h): skipped_banned += 1; continue
                        if lk in new_links: continue
                        new_links.append(lk)
                        if len(new_links) >= wave_size: break
                if len(new_links) >= wave_size: break
            if not new_links and not deep_done:
                deep_done = True
                await _set_phase(T("ph_deep", n=wave_num))
                tasks2 = [asyncio.create_task(_extract_from_linkdoni(aid, cli, u, limit=300, log=log, deep_scan=True)) for u in link_donies]
                results2 = await asyncio.gather(*tasks2, return_exceptions=True)
                for r in results2:
                    if isinstance(r, list):
                        for lk in r:
                            h = _hash_of(lk)
                            if not h: continue
                            if _is_seen(aid, h): skipped_seen += 1; continue
                            if _is_banned(aid, h): skipped_banned += 1; continue
                            if lk in new_links: continue
                            new_links.append(lk)
                            if len(new_links) >= wave_size: break
                    if len(new_links) >= wave_size: break
            if not new_links:
                wait_round += 1
                if wait_round > max_wait_rounds: await _finish(T("ph_no_links")); return
                await _set_phase(T("ph_wait", s=wait_seconds, i=wait_round, t=max_wait_rounds))
                for _ in range(wait_seconds):
                    async with lock:
                        op2 = _get_op(op_id)
                        if not op2 or op2.get("status") == "cancelled": await _finish(T("ph_cancelled")); return
                    await asyncio.sleep(1)
                wave_num -= 1; deep_done = False; continue
            else: wait_round = 0
            await _set_phase(T("ph_links", n=wave_num, c=len(new_links)))
            async with lock:
                op2 = _get_op(op_id)
                if op2: op2["progress"]["total"] = op2["progress"].get("total", 0) + len(new_links); _save_op(op2)
            sem = asyncio.Semaphore(12)
            async def join_one(lk):
                nonlocal joined, failed, rejected_inactive, skipped_channel
                async with sem:
                    if max_join and joined >= max_join: return
                    async with lock:
                        op2 = _get_op(op_id)
                        if not op2 or op2.get("status") == "cancelled": return
                    h = _hash_of(lk)
                    if _is_seen(aid, h) or _is_banned(aid, h): return
                    try:
                        ok, res, tag, ent_new = await asyncio.wait_for(_try_join(cli, lk), timeout=25)
                        if ok:
                            _mark_seen(aid, h)
                            if tag == "already":
                                pass
                            joined += 1
                            if auto_msg and ent_new:
                                try: await cli.send_message(object_guid=ent_new, text=auto_msg)
                                except Exception: pass
                        else:
                            failed += 1; add_error("join", res, lk, name)
                            if res and ("BANNED" in str(res).upper() or "KICKED" in str(res).upper()):
                                _mark_banned(aid, h, str(res)[:80])
                            _mark_seen(aid, h)
                    except Exception as e:
                        failed += 1; add_error("join", _fmt_error(e), lk, name)
                        try: _mark_seen(aid, h)
                        except Exception: pass
                    async with lock:
                        op2 = _get_op(op_id)
                        if op2:
                            op2["progress"]["joined"] = joined; op2["progress"]["failed"] = failed
                            op2["progress"]["skipped_seen"] = skipped_seen
                            op2["progress"]["skipped_banned"] = skipped_banned
                            op2["progress"]["rejected"] = rejected_inactive
                            _save_op(op2)
                    if join_delay > 0: await asyncio.sleep(join_delay)
            await asyncio.gather(*[asyncio.create_task(join_one(lk)) for lk in new_links], return_exceptions=True)
            await _set_phase(T("ph_wave_done", n=wave_num))
    except asyncio.CancelledError: await _finish(T("ph_cancelled")); raise
    except Exception as e:
        flog(f"[joiner] FATAL: {traceback.format_exc()}", "error")
        await _finish(T("ph_error", n=type(e).__name__))
    finally:
        if cli:
            try: await cli._disconnect()
            except Exception: pass

async def run_joiner_lefter(op, log):
    accounts = list_accounts(); sel = op.get("accounts") or []
    if "all" in sel: sel = list(accounts.keys())
    op["progress"] = {"joined":0,"failed":0,"total":0,"phase":T("ph_start"),
        "skipped_seen":0,"skipped_banned":0,"rejected":0,"already":0,"sent":0,"wave":0,"tried":0,"left":0,"round":0}
    op["status"] = "running"; op["errors"] = []; _save_op(op)
    tasks = []
    for aid in sel:
        a = accounts.get(aid)
        if not a: continue
        tasks.append(asyncio.create_task(_joiner_worker(aid, a, op["id"],
            float(op.get("join_delay", 0.5)), op.get("max_join", 0) or 0,
            (op.get("auto_msg") or "").strip(), log)))
    if tasks: await asyncio.gather(*tasks, return_exceptions=True)
    op2 = _get_op(op["id"])
    if op2 and op2.get("status") not in ("cancelled","done"):
        op2["status"] = "done"; op2["finished_at"] = int(time.time()); _save_op(op2)
    JL_JOBS.pop(op["id"], None)

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
    p = op.get("progress") or {}; t = op.get("type")
    if t in ("joinlef","lefter"):
        return {"done":p.get("joined",0),"failed":p.get("failed",0),"pending":0,
            "in_progress":1 if op.get("status") == "running" else 0,
            "total":op.get("max_join",0) or (p.get("joined",0) + p.get("failed",0)),
            "already":p.get("already",0),"sent":p.get("sent",0),"left":p.get("left",0),
            "wave":p.get("wave",0),"tried":p.get("tried",0),
            "skipped_seen":p.get("skipped_seen",0),"skipped_banned":p.get("skipped_banned",0),
            "rejected":p.get("rejected",0),"round":p.get("round",0)}
    if t == "autotar":
        return {"done":p.get("joined",0),"failed":p.get("failed",0),"pending":p.get("pending",0),
            "in_progress":1 if op.get("status") == "running" else 0,"total":p.get("total",0),
            "already":p.get("already",0),"sent":p.get("sent",0),"left":p.get("left",0),
            "wave":p.get("wave",0),"tried":p.get("tried",0),
            "skipped_seen":p.get("skipped_seen",0),"skipped_banned":p.get("skipped_banned",0),
            "rejected":p.get("rejected",0),"round":p.get("round",0)}
    return {"done":p.get("sent",0),"failed":p.get("failed",0),"pending":p.get("pending",0),
        "in_progress":p.get("in_progress",0),"total":p.get("total",0),
        "blocked":p.get("blocked",0),"round":p.get("round",0)}
def _op_effective_status(op):
    st = op.get("status", "draft")
    if op.get("type") in ("joinlef","lefter","autotar"):
        if st in ("done","failed","cancelled","paused"): return st
        return "running"
    return st
def _op_short_title(op, n=32):
    t = op.get("type")
    if t == "joinlef": return f"{T('op_joiner')} ({op.get('max_join',0)})"
    if t == "lefter": return f"{T('op_lefter')} ({op.get('leave_mode','?')})"
    if t == "autotar":
        tpl = get_template(op.get("template_id"))
        return f"{T('op_autotar')}: {short(tpl.get('name','?'),20)}" if tpl else T("op_autotar")
    p = op.get("payload") or {}
    if p.get("text"): return f"{T('op_send')} «{p.get('text')[:n]}»"
    return T("op_send")
def _op_status_label(st): return T("op_" + st) if ("op_" + st) in _TR else st
def _op_progress_bar(op):
    s = _op_stats(op); done = s["done"] + s["failed"]; tot = s["total"] or 0
    if tot == 0: return "▱" * 16 + " 0%", 0
    pct = int(done * 100 / tot); fill = int(done * 16 / tot)
    if fill > 16: fill = 16
    return "▰" * fill + "▱" * (16 - fill) + f" {pct}%", pct

# ═══════════════ SENDER ═══════════════
async def _send_worker(aid, acc, op_id, cfg, stop, log):
    name = acc.get("name") or acc.get("phone") or aid
    op = _get_op(op_id)
    if not op: return
    lock = _get_op_lock(op_id); sent = 0; failed = 0; blocked = 0
    delay = float(op.get("delay", 1.5)); payload = op.get("payload") or {"text":"سلام"}
    text = payload.get("text") or "سلام"
    auto_left = bool(op.get("auto_left", False))
    attach_file = op.get("attach_file") or ""
    infinite_loop = bool(op.get("infinite_loop", False))
    loop_delay = float(op.get("loop_delay", 3.0))
    rescan_targets = bool(op.get("rescan_targets", True))
    cli = None
    async def _set_phase(phase):
        async with lock:
            op2 = _get_op(op_id)
            if op2: op2["progress"]["phase"] = phase; _save_op(op2)
        await _refresh_op_panel(op_id)
    try:
        await _set_phase(T("ph_connect"))
        cli, err = await _connect_with_retry(aid, _get_sess_path(aid), name=name, tries=3)
        if cli is None:
            async with lock:
                op2 = _get_op(op_id)
                if op2: op2["progress"]["phase"] = T("ph_connect_fail", n=err); op2["status"] = "done"; _save_op(op2)
            return
        await _set_phase(T("ph_collecting"))
        own_ids = get_own_channel_ids(aid)
        targets = await _collect_targets_for_send(cli, op.get("target","both"), exclude_ids=own_ids)
        if not targets and not infinite_loop:
            async with lock:
                op2 = _get_op(op_id)
                if op2: op2["progress"]["phase"] = T("ph_no_targets"); op2["status"] = "done"; _save_op(op2)
            return
        max_send = int(op.get("max", 0) or 0)
        if max_send and len(targets) > max_send: targets = targets[:max_send]
        loop_round = 0
        while True:
            loop_round += 1
            await _set_phase(T("ph_sending", n=len(targets)))
            async with lock:
                op2 = _get_op(op_id)
                if not op2 or op2.get("status") == "cancelled": return
            if stop.is_set(): break
            async with lock:
                op2 = _get_op(op_id)
                if op2:
                    op2["progress"]["pending"] = len(targets); op2["progress"]["in_progress"] = 1
                    op2["progress"]["total"] = len(targets)
                    if infinite_loop: op2["progress"]["round"] = loop_round
                    _save_op(op2)
            for i, t in enumerate(targets, 1):
                async with lock:
                    op2 = _get_op(op_id)
                    if not op2 or op2.get("status") == "cancelled": return
                if stop.is_set(): break
                try:
                    ent = t.get("target")
                    if attach_file and os.path.exists(attach_file):
                        _ok = await _send_file_rubpy(cli, ent, attach_file, text)
                    else:
                        await cli.send_message(object_guid=ent, text=text)
                        _ok = True
                    if _ok: sent += 1
                    else: failed += 1
                except Exception as e:
                    err = _fmt_error(e)
                    if _is_rate_limit(e): failed += 1; await asyncio.sleep(5); continue
                    failed += 1; add_error("send", err, t.get("name"), name)
                async with lock:
                    op2 = _get_op(op_id)
                    if op2:
                        op2["progress"]["sent"] = sent; op2["progress"]["failed"] = failed
                        op2["progress"]["pending"] = max(0, len(targets) - i); _save_op(op2)
                await asyncio.sleep(delay)
            if stop.is_set(): break
            if not infinite_loop: break
            if rescan_targets:
                await _set_phase(T("send_rescan"))
                try:
                    fresh = await _collect_targets_for_send(cli, op.get("target","both"), exclude_ids=own_ids)
                    old_ids = {t.get("target") for t in targets}
                    for t in fresh:
                        if t.get("target") in old_ids: continue
                        targets.append(t)
                except Exception: pass
            waited = 0.0
            while waited < loop_delay:
                if stop.is_set(): return
                await asyncio.sleep(min(1.0, loop_delay - waited)); waited += 1.0
        async with lock:
            op2 = _get_op(op_id)
            if op2:
                op2["progress"]["phase"] = f"✓ {sent} · ✗ {failed}"
                op2["status"] = "done"; op2["finished_at"] = int(time.time()); _save_op(op2)
    except asyncio.CancelledError: raise
    except Exception as e:
        flog(f"[sender] FATAL: {traceback.format_exc()}", "error")
        async with lock:
            op2 = _get_op(op_id)
            if op2: op2["status"] = "done"; _save_op(op2)
    finally:
        if cli:
            try: await cli._disconnect()
            except Exception: pass

async def _send_file_rubpy(bot, target, file_path, caption=""):
    """Send file using rubpy methods based on extension."""
    ext = (os.path.splitext(file_path)[1] or "").lower()
    try:
        if ext in (".jpg",".jpeg",".png",".gif",".webp"):
            await bot.send_photo(object_guid=target, photo=file_path, caption=caption or None)
        elif ext in (".mp4",".mov",".avi",".mkv",".webm"):
            await bot.send_video(object_guid=target, video=file_path, caption=caption or None)
        else:
            await bot.send_document(object_guid=target, document=file_path, caption=caption or None)
        return True
    except Exception as e:
        add_error("send_file", _fmt_error(e), target)
        return False

async def run_sender(op, log):
    accounts = list_accounts(); sel = op.get("accounts") or []
    if "all" in sel: sel = list(accounts.keys())
    op["progress"] = {"sent":0,"failed":0,"total":0,"pending":0,"in_progress":0,
        "phase":T("ph_start"),"blocked":0,"round":0}
    op["status"] = "running"; op["errors"] = []; _save_op(op)
    stop = asyncio.Event(); STATE["cancel_" + op["id"]] = stop
    tasks = []
    for aid in sel:
        a = accounts.get(aid)
        if not a: continue
        tasks.append(asyncio.create_task(_send_worker(aid, a, op["id"], _load(CFG_FILE, DEFAULT_CFG), stop, log)))
    if tasks: await asyncio.gather(*tasks, return_exceptions=True)
    op2 = _get_op(op["id"])
    if op2 and op2.get("status") not in ("cancelled","done"):
        op2["status"] = "done"; op2["finished_at"] = int(time.time()); _save_op(op2)

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
    else: t.setdefault(section, {})[field] = value
    save_templates(ts)
def new_template(name="قالب جدید"):
    return {"id":"tp_"+secrets.token_hex(4),"name":name,"created":int(time.time()),
        "channel":{"type":"private","title":"","username":"","about":"","photo_file":""},
        "profile":{"first_name":"","last_name":"","username":"","bio":"","photo_file":""},
        "joiner":{"max_join":0,"speed":"fast","groups_only":True},
        "sender":{"text":"","target":"groups","mode":"send_only","max_send":0,"delay":1.5,
            "infinite_loop":False,"loop_delay":3.0,"rescan_targets":True,
            "attach_file":"","attach_caption":""},
        "pv":{"enabled":False,"delay_seconds":0,"reply_once":True,"max_replies":1,
            "notify":True,"notify_on_receive":True,"notify_on_reply":True,"poll_seconds":3,
            "items":[{"kind":"text","text":"سلام 👋"}],"apply_to_accounts":True},
        "lefter":{"leave_mode":"closed"}}
def _substitute(pattern, ctx):
    if not pattern: return ""
    s = str(pattern)
    for k, v in ctx.items(): s = s.replace("{"+k+"}", str(v))
    return s
def _build_ctx():
    now = time.time()
    return {"n":int(now)%100000,"rnd":str(random.randint(100000,999999)),
        "rnd4":str(random.randint(1000,9999)),"date":time.strftime("%Y%m%d"),
        "time":time.strftime("%H%M%S")}

# ═══════════════ AUTOTAR ═══════════════
async def _auto_tar_worker(aid, acc, op_id, tpl, log):
    name = acc.get("name") or aid
    op = _get_op(op_id)
    if not op: return
    lock = _get_op_lock(op_id); ctx = _build_ctx()
    cli = None
    async def _phase(ph):
        async with lock:
            op2 = _get_op(op_id)
            if op2: op2["progress"]["phase"] = ph; _save_op(op2)
        await _refresh_op_panel(op_id)
    async def _finish(ph):
        async with lock:
            op2 = _get_op(op_id)
            if op2:
                op2["progress"]["phase"] = ph
                if op2.get("status") == "running": op2["status"] = "done"; op2["finished_at"] = int(time.time())
                _save_op(op2)
        await _refresh_op_panel(op_id)
    try:
        await _phase(T("ph_connect"))
        cli, err = await _connect_with_retry(aid, _get_sess_path(aid), name=name, tries=3)
        if cli is None: await _finish(T("ph_connect_fail", n=err)); return
        me = await cli.get_me(); me_d = _to_dict(me)
        my_guid = (me_d.get("user") or {}).get("user_guid") or me_d.get("user_guid")
        await _phase(T("ph_connected", n=(me_d.get("user") or {}).get("first_name") or aid))
        # channel creation
        ch = tpl.get("channel") or {}
        if ch.get("title"):
            title = _substitute(ch["title"], ctx)[:60] or f"channel {ctx['n']}"
            about = _substitute(ch.get("about",""), ctx)
            await _phase(T("ph_create_ch", n=title))
            try:
                r = await cli.add_channel(title=title, description=about or None)
                guid = _extract_guid_from_update(r)
                if guid:
                    add_channel_to_storage(aid, {"title":title,"description":about,"guid":guid,
                        "is_public":False,"type":"private","created":int(time.time())})
            except Exception as e: add_error("autotar-channel", _fmt_error(e), title, name)
        # profile
        p = tpl.get("profile") or {}
        if p.get("first_name") or p.get("last_name") or p.get("bio") or p.get("username"):
            await _phase(T("ph_update_prof"))
            try:
                # rubpy update_profile - try method name variations
                fn = getattr(cli, "update_profile", None) or getattr(cli, "updateProfile", None)
                if fn:
                    kwargs = {}
                    if p.get("first_name"): kwargs["first_name"] = _substitute(p["first_name"], ctx)[:64]
                    if p.get("last_name"): kwargs["last_name"] = _substitute(p["last_name"], ctx)[:64]
                    if p.get("bio"): kwargs["bio"] = _substitute(p["bio"], ctx)[:70]
                    if kwargs: await fn(**kwargs)
                if p.get("username"):
                    ufn = getattr(cli, "update_username", None) or getattr(cli, "updateUsername", None)
                    if ufn: await ufn(username=_substitute(p["username"], ctx))
            except Exception as e: add_error("autotar-profile", _fmt_error(e), None, name)
        # joiner + sender
        j = tpl.get("joiner") or {}; snd = tpl.get("sender") or {}
        mode = snd.get("mode", "send_only")
        sender_text = _substitute(snd.get("text",""), ctx) if snd.get("text") else ""
        max_join = int(j.get("max_join", 0) or 0)
        join_delay = {"ultra":0.2,"fast":0.6,"normal":1.5,"slow":4.0}.get(j.get("speed","fast"), 0.6)
        joined_count = 0; sent_count = 0; left_count = 0; failed_count = 0
        if max_join > 0:
            lds = list(load_link_donies())
            await _phase(T("ph_extract", n=1))
            ordered = {}
            for url in lds:
                try:
                    found = await _extract_from_linkdoni(aid, cli, url, limit=300, log=log)
                    for lk in found:
                        h = _hash_of(lk)
                        if not h: continue
                        if _is_seen(aid, h) or _is_banned(aid, h): continue
                        if lk not in ordered: ordered[lk] = True
                except Exception: pass
            new_links = list(ordered.keys())
            await _phase(T("ph_links", n=1, c=len(new_links)))
            for lk in new_links:
                async with lock:
                    op2 = _get_op(op_id)
                    if not op2 or op2.get("status") == "cancelled": return
                if joined_count >= max_join: break
                try:
                    ok, guid_j, tag, ent_new = await _try_join(cli, lk)
                    if not ok: failed_count += 1; continue
                    _mark_seen(aid, _hash_of(lk))
                    if tag != "already": joined_count += 1
                    if mode in ("join_send","join_send_leave") and sender_text and ent_new:
                        try:
                            await cli.send_message(object_guid=ent_new, text=sender_text)
                            sent_count += 1
                            if mode == "join_send_leave":
                                ok_l, _ = await _try_leave_one(cli, {"guid": ent_new, "kind":"group"})
                                if ok_l: left_count += 1
                        except Exception: pass
                except Exception: failed_count += 1
                async with lock:
                    op2 = _get_op(op_id)
                    if op2:
                        op2["progress"]["joined"] = joined_count
                        op2["progress"]["sent"] = sent_count
                        op2["progress"]["left"] = left_count
                        op2["progress"]["failed"] = failed_count
                        _save_op(op2)
                if join_delay > 0: await asyncio.sleep(join_delay)
        # send to existing
        if sender_text and mode == "send_only":
            await _phase(T("ph_send_final"))
            target = snd.get("target", "groups")
            chats = await _get_all_chats(cli)
            own_guids = get_own_channel_ids(aid)
            for c in chats:
                if c.get("guid") in own_guids or c.get("guid") == my_guid: continue
                if target == "pv" and c.get("type") != "User": continue
                if target == "groups" and not _is_true_group(c): continue
                if target == "both" and c.get("type") not in ("User","Group"): continue
                try:
                    await cli.send_message(object_guid=c.get("guid"), text=sender_text); sent_count += 1
                except Exception: failed_count += 1
                await asyncio.sleep(float(snd.get("delay", 1.5)))
        # lefter
        lf = tpl.get("lefter") or {}
        if lf.get("leave_mode"):
            await _phase(T("ph_leaving", m=lf["leave_mode"]))
            own_guids = get_own_channel_ids(aid)
            for t in await _lefter_collect(cli, lf["leave_mode"], exclude_ids=own_guids):
                try:
                    ok_l, _ = await _try_leave_one(cli, t)
                    if ok_l: left_count += 1
                except Exception: pass
                await asyncio.sleep(0.3)
        await _finish(T("ph_done"))
    except asyncio.CancelledError: await _finish(T("ph_cancelled")); raise
    except Exception as e:
        flog(f"[autotar] FATAL: {traceback.format_exc()}", "error")
        await _finish(T("ph_error", n=type(e).__name__))
    finally:
        if cli:
            try: await cli._disconnect()
            except Exception: pass

async def run_auto_tar(op, log):
    accounts = list_accounts(); sel = op.get("accounts") or []
    if "all" in sel: sel = list(accounts.keys())
    tpl = get_template(op.get("template_id"))
    if not tpl:
        op["status"] = "failed"; op["progress"]["phase"] = T("not_found"); _save_op(op); return
    op["progress"] = {"joined":0,"failed":0,"total":0,"pending":0,"in_progress":0,
        "phase":T("ph_start"),"sent":0,"already":0,"tried":0,"wave":0,"left":0,"round":0,
        "skipped_seen":0,"skipped_banned":0,"rejected":0}
    op["status"] = "running"; op["errors"] = []; _save_op(op)
    tasks = []
    for aid in sel:
        a = accounts.get(aid)
        if not a: continue
        tasks.append(asyncio.create_task(_auto_tar_worker(aid, a, op["id"], tpl, log)))
    if tasks: await asyncio.gather(*tasks, return_exceptions=True)
    op2 = _get_op(op["id"])
    if op2 and op2.get("status") not in ("cancelled","done"):
        op2["status"] = "done"; op2["finished_at"] = int(time.time()); _save_op(op2)

# ═══════════════ PV AutoResponder ═══════════════
PV_LISTENER_TASKS = {}; _PV_REPLY_TASKS = {}; _PV_STOP_EVENTS = {}
async def _sleep_or_stop(ev, sec):
    try: await asyncio.wait_for(ev.wait(), timeout=sec)
    except asyncio.TimeoutError: pass

async def _pv_send_reply(aid, acc, sender_guid, cfg, stop_event):
    name = acc.get("name") or aid; key = f"{aid}:{sender_guid}"
    cli = None; connected = False; send_ok = True; send_err = None
    def _fail(msg):
        nonlocal send_ok, send_err; send_ok = False; send_err = str(msg)[:150]
    try:
        for _ in range(int(cfg.get("delay_seconds", 0))):
            if stop_event.is_set(): _pv_count_add(aid, sender_guid, -1); return
            await asyncio.sleep(1)
        cfg = _load_pv_account(aid)
        try:
            cli, err = await _connect_with_retry(aid, _get_sess_path(aid), name=name, tries=2, per_timeout=20)
            if cli: connected = True
            else: _fail(f"connect: {err}")
        except Exception as e: _fail(f"{type(e).__name__}")
        if cli and connected:
            for item in cfg.get("items") or []:
                if stop_event.is_set(): break
                kind = item.get("kind","text")
                try:
                    if kind == "text" and item.get("text"):
                        await cli.send_message(object_guid=sender_guid, text=item["text"])
                    elif kind == "file":
                        fp = item.get("file_path")
                        if fp and os.path.exists(fp): await _send_file_rubpy(cli, sender_guid, fp, item.get("caption") or "")
                        else: _fail("file")
                    elif kind == "delay":
                        await asyncio.sleep(int(item.get("seconds", 3))); continue
                    await asyncio.sleep(random.uniform(0.5, 1.2))
                except Exception as e:
                    _fail(f"{type(e).__name__}")
    except asyncio.CancelledError:
        if not connected: _pv_count_add(aid, sender_guid, -1)
        raise
    except Exception as e: _fail(f"{type(e).__name__}")
    finally:
        if cli:
            try: await cli._disconnect()
            except Exception: pass
        _PV_REPLY_TASKS.pop(key, None)
    if not connected: _pv_count_add(aid, sender_guid, -1)
    try: _record_pv_reply(aid, sender_guid, ok=send_ok, err=send_err)
    except Exception: pass
    if cfg.get("notify", True) and cfg.get("notify_on_reply", True):
        if send_ok: await tg_send(f"✅ {T('ph_reply_ok', u=esc(sender_guid[:12]))}")
        else: await tg_send(f"❌ {T('ph_reply_fail', u=esc(sender_guid[:12]), e=esc(send_err or '?'))}")

async def _pv_poller_worker(aid, acc, stop_event):
    global _PV_WM_DIRTY
    name = acc.get("name") or aid; cli = None; my_guid = None
    flog(f"[pv] {name}: poller started")
    try:
        while not stop_event.is_set():
            cfg = _load_pv_account(aid)
            poll = max(2, int(cfg.get("poll_seconds", 3)))
            if not cfg.get("enabled"): await _sleep_or_stop(stop_event, poll); continue
            try:
                if cli is None:
                    cli, err = await _connect_with_retry(aid, _get_sess_path(aid), name=name, tries=1, per_timeout=20)
                    if cli is None: await _sleep_or_stop(stop_event, 10); continue
                    me = await cli.get_me(); me_d = _to_dict(me)
                    my_guid = (me_d.get("user") or {}).get("user_guid") or me_d.get("user_guid")
                chats = await _get_all_chats(cli)
                first = not (_wm_load().get(aid) or {}).get("_init")
                for c in chats:
                    if c.get("type") != "User": continue
                    if c.get("guid") == my_guid: continue
                    uid = c.get("guid")
                    if not uid: continue
                    try:
                        msgs_upd = await cli.get_messages(object_guid=uid, max_id="0", limit="1", sort="FromMax")
                        msgs = _messages_from_update(msgs_upd)
                    except Exception: continue
                    if not msgs: continue
                    last = msgs[0]; mid = last.get("id")
                    if not mid: continue
                    try:
                        if int(mid) <= _wm_get(aid, uid): continue
                    except Exception: continue
                    _wm_set(aid, uid, mid)
                    if first: continue
                    if last.get("is_mine"): continue
                    if _pv_limit_reached(aid, uid, cfg): continue
                    try: _record_pv_visit(aid, uid, {})
                    except Exception: pass
                    _pv_count_add(aid, uid, +1)
                    if cfg.get("notify", True) and cfg.get("notify_on_receive", True):
                        mt = last.get("text") or "📎"
                        await tg_send(f"🔔 <code>{esc(uid[:20])}</code>: <code>{esc(mt[:120])}</code>")
                    ev = _PV_STOP_EVENTS.get(aid)
                    if ev is None: ev = _PV_STOP_EVENTS[aid] = asyncio.Event()
                    key = f"{aid}:{uid}"
                    if key not in _PV_REPLY_TASKS or _PV_REPLY_TASKS[key].done():
                        _PV_REPLY_TASKS[key] = asyncio.create_task(_pv_send_reply(aid, acc, uid, cfg, ev))
                if first:
                    _wm_load().setdefault(aid, {})["_init"] = 1
                    _PV_WM_DIRTY = True
                _wm_flush()
            except asyncio.CancelledError: raise
            except Exception as e:
                flog(f"[pv] {name}: {type(e).__name__}", "warning")
                if cli:
                    try: await cli._disconnect()
                    except Exception: pass
                    cli = None
                await _sleep_or_stop(stop_event, 8); continue
            await _sleep_or_stop(stop_event, poll)
    finally:
        _wm_flush()
        if cli:
            try: await cli._disconnect()
            except Exception: pass

async def start_pv_responders():
    for aid, acc in list_accounts().items():
        cfg = _load_pv_account(aid)
        if not cfg.get("enabled"): continue
        ex = PV_LISTENER_TASKS.get(aid)
        if ex and not ex.done(): continue
        stop = asyncio.Event(); _PV_STOP_EVENTS[aid] = stop
        PV_LISTENER_TASKS[aid] = asyncio.create_task(_pv_poller_worker(aid, acc, stop))
def _stop_pv_for_account(aid):
    st = _PV_STOP_EVENTS.pop(aid, None)
    if st:
        try: st.set()
        except Exception: pass
    t = PV_LISTENER_TASKS.pop(aid, None)
    if t and not t.done(): t.cancel()

# ═══════════════ LISTENER / KEEPALIVE ═══════════════
LISTENER_TASKS = {}; LISTENER_SEEN = {}; LISTENER_SEEN_LOCK = threading.Lock()
async def _listener_loop(aid, acc, stop_event):
    name = acc.get("name") or aid
    while not stop_event.is_set():
        cli = None
        try:
            cli, err = await _connect_with_retry(aid, _get_sess_path(aid), name=name, tries=3)
            if cli is None: await asyncio.sleep(30); continue
            while not stop_event.is_set(): await asyncio.sleep(5)
        except asyncio.CancelledError: raise
        except Exception: await asyncio.sleep(20)
        finally:
            if cli:
                try: await cli._disconnect()
                except Exception: pass
async def start_all_listeners():
    for aid, acc in list_accounts().items():
        if aid in LISTENER_TASKS and not LISTENER_TASKS[aid].done(): continue
        stop = asyncio.Event(); STATE.setdefault("listener_stops", {})[aid] = stop
        LISTENER_TASKS[aid] = asyncio.create_task(_listener_loop(aid, acc, stop))
def _stop_listener_for(aid):
    loop = _loop_ref[0] or (asyncio.get_event_loop() if asyncio.get_event_loop() else None)
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
    LISTENER_TASKS.clear(); STATE["listener_stops"] = {}
    await asyncio.sleep(1); await start_all_listeners()

KEEPALIVE_SECONDS = 15 * 60
async def keepalive_loop():
    await asyncio.sleep(60)
    while True:
        try:
            for aid, acc in list_accounts().items():
                cli = None
                try:
                    cli, err = await _connect_with_retry(aid, _get_sess_path(aid), name=acc.get("name"), tries=2)
                    if cli: await cli.get_me()
                except Exception: pass
                finally:
                    if cli:
                        try: await cli._disconnect()
                        except Exception: pass
                await asyncio.sleep(random.uniform(3, 6))
            await asyncio.sleep(KEEPALIVE_SECONDS)
        except asyncio.CancelledError: raise
        except Exception: await asyncio.sleep(60)

# ═══════════════ TELEGRAM UI (identical to Soroosh) ═══════════════
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters as tg_filters
from telegram.request import HTTPXRequest
PAGE_SIZE = 6
def esc(s): return _html.escape(str(s if s is not None else ""))
def short(s, n=40):
    s = str(s or "").replace("\n", " ")
    return s if len(s) <= n else s[:n-1] + "…"
def _style_for(data):
    d = str(data or "").lower()
    if ":delok" in d: return "success"
    if d.endswith(":go") or "run_go" in d or ":run_acc" in d: return "success"
    if d.startswith("acc:add") or d.startswith("chnew:start") or d.startswith("at:new"): return "success"
    if d == "at:new" or ":add_text" in d or ":add_saved" in d or ":add_delay" in d: return "success"
    if ":restart" in d or ":refresh" in d: return "success"
    if any(k in d for k in (":accnext",":maxnext",":tgtnext",":composenext",":confirm",":delok")): return "success"
    if d.endswith(":del") or ":del:" in d or d.startswith("ld:del:"): return "danger"
    if "cancel" in d: return "danger"
    if d.startswith("op:stop:"): return "danger"
    if d == "err:clear": return "danger"
    if "clear_all" in d or "wipe" in d: return "danger"
    if ":clear_seen" in d or ":clear_banned" in d: return "danger"
    if ":reset_ld" in d or ":reset_prog" in d or d.startswith("ld:reset:"): return "danger"
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
                except Exception: pass
        return InlineKeyboardButton(label, callback_data=data)
    except Exception: return InlineKeyboardButton(label, callback_data=data)
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
def _bar(pct, n=14): return "█" * max(0, min(n, round(pct * n / 100))) + "░" * (n - max(0, min(n, round(pct * n / 100))))
def _eta(sec):
    sec = int(sec)
    if sec < 60: return f"{sec}ث"
    if sec < 3600: return f"{sec//60}د"
    return f"{sec//3600}س {(sec%3600)//60}د"
def authorized(update):
    try: return update.effective_chat.id == FORCED_OWNER
    except Exception: return False
_PANEL_SIG = {}
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
            STATE["panel"][cid] = m.message_id; _PANEL_SIG[cid] = (m.message_id, sig); return
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
_PAGE_STATE = {}
def _set_page(cid, tag):
    try: _PAGE_STATE[int(cid)] = str(tag)
    except Exception: pass
def _is_page(cid, tag):
    try: return _PAGE_STATE.get(int(cid)) == tag
    except Exception: return False

STATE = {"owner":None,"panel":{},"conv":{},"listener_stops":{},"op_panel":{},"listener_new_count":0}
_loop_ref = [None]
TG_TOKEN = ""
APP = None
_TMP_EDIT = {}
pending_inputs = {}

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
    rows += [[B(T("send"), "send:start"), B(T("joiner"), "jl:start")],
        [B(T("lefter"), "lf:start"), B(T("templates"), "at:menu")],
        [B(T("accounts_n"), "menu:acc"), B(T("pv"), "menu:pv")],
        [B(T("stats"), "menu:stats"), B(T("errors"), "menu:errors"), B(T("cache"), "menu:cache")],
        [B(T("listener"), "menu:listen"), B(T("linkdonies"), "ld:list:jl:back_to_settings")],
        [B(T("settings"), "menu:cfg")]]
    await panel(txt, kb_(*rows), page_tag="main")

async def show_cache_menu():
    accounts = list_accounts()
    txt = head("🗂", "cache") + T("select_account") + "\n\n"
    rows = []
    for aid, a in accounts.items():
        sn = _seen_count(aid); bn = _banned_count(aid); ln = len(_load_ldprog(aid))
        rows.append([B(f"{short(a.get('name','?'),14)} · {T('seen')} {sn} · {T('banned')} {bn} · {ln}", f"cache:acc:{aid}")])
    if not accounts: txt += T("empty")
    rows.append([B(T("wipe_all"), "cache:clear_all_accounts")]); rows.append(nav())
    await panel(txt, kb_(*rows), page_tag="cache")
async def show_cache_account(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="cache")
    sn = _seen_count(aid); bn = _banned_count(aid); ln = len(_load_ldprog(aid))
    txt = head("🗂", f"{T('cache')} · {a.get('name','?')}")
    txt += mrow("🔍","seen",sn) + "\n" + mrow("🚫","banned",bn) + "\n" + mrow("📡","ld_progress",ln)
    rows = [[B(T("clear_seen"), f"cache:acc:{aid}:clear_seen"), B(T("clear_banned"), f"cache:acc:{aid}:clear_banned")],
        [B(T("clear_both"), f"cache:acc:{aid}:clear_all"), B(T("reset_ld"), f"cache:acc:{aid}:reset_ld")],
        [B(T("refresh_stats"), f"acc:refresh_one:{aid}")], nav("menu:cache")]
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
        rows.append([B(f"{en}{short(a.get('name','?'),20)} · {items_n}", f"pv:acc:{aid}")])
    rows.append(nav())
    await panel(txt, kb_(*rows), page_tag="pv_menu")
async def show_pv_account_menu(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="pv_menu")
    cfg = _load_pv_account(aid)
    en = bool(cfg.get("enabled")); mx = int(cfg.get("max_replies",1) or 0)
    items = cfg.get("items") or []; notify_on = bool(cfg.get("notify", True))
    poll_sec = int(cfg.get("poll_seconds",3)); delay_sec = int(cfg.get("delay_seconds",0))
    pv_task = PV_LISTENER_TASKS.get(aid); poller_on = bool(pv_task and not pv_task.done())
    has_custom = _has_pv_account(aid)
    txt = head("💬", f"{T('pv')} · {a.get('name','?')}")
    txt += mrow("📶","pv_status", (T("pv_active") if en else T("pv_inactive"))) + "\n"
    txt += mrow("🔄","pv_poller", (T("on") if poller_on else T("off"))) + "\n"
    txt += mrow("👥","pv_max", (mx if mx else "∞")) + "\n"
    txt += mrow("⏱","pv_delay", f"{delay_sec}s") + "\n"
    txt += mrow("🔔","pv_notify", (T("on") if notify_on else T("off"))) + "\n"
    txt += mrow("🔄","pv_poll", f"{poll_sec}s") + "\n"
    txt += mrow("📨","pv_items", len(items))
    if has_custom: txt += f"  ({T('pv_custom')})"
    txt += "\n\n"
    for i, it in enumerate(items, 1):
        k = it.get("kind","text")
        if k == "text": txt += f"{i}. 💬 <code>{esc(short(it.get('text',''),40))}</code>\n"
        elif k == "file": txt += f"{i}. 📁 <code>{esc(os.path.basename(it.get('file_path','?')))}</code>\n"
        elif k == "delay": txt += f"{i}. ⏸ {it.get('seconds',3)}s\n"
    rows = [[B(T("toggle_off") if en else T("toggle_on"), f"pv:acc:{aid}:toggle")],
        [B(f"{T('pv_max')}: {mx if mx else '∞'}", f"pv:acc:{aid}:cycle_max"), B(T("pv_delay"), f"pv:acc:{aid}:set_delay")],
        [B(T("pv_add_text"), f"pv:acc:{aid}:add_text"), B(T("pv_add_file"), f"pv:acc:{aid}:add_saved"), B(T("pv_add_delay"), f"pv:acc:{aid}:add_delay")],
        [B(T("pv_list"), f"pv:acc:{aid}:list"), B(T("pv_report"), f"pv:acc:{aid}:report:0")],
        [B(f"{T('pv_notify')}: {'✓' if notify_on else '✗'}", f"pv:acc:{aid}:toggle_notify"), B(f"{T('pv_poll')} {poll_sec}s", f"pv:acc:{aid}:set_poll")],
        [B(T("pv_reset_counter"), f"pv:acc:{aid}:clear_replies"), B(T("pv_reset_custom"), f"pv:acc:{aid}:reset_to_global")],
        [B(T("pv_restart"), f"pv:acc:{aid}:restart")], nav("menu:pv")]
    await panel(txt, kb_(*rows), page_tag=f"pv_acc:{aid}")
async def show_pv_account_list(aid):
    cfg = _load_pv_account(aid); items = cfg.get("items") or []
    a = get_account(aid)
    txt = head("📋", f"{T('pv_list')} · {a.get('name','?') if a else aid}")
    for i, it in enumerate(items, 1):
        k = it.get("kind","text")
        if k == "text": txt += f"\n{i}. 💬 <code>{esc(short(it.get('text',''),60))}</code>"
        elif k == "file": txt += f"\n{i}. 📁 <code>{esc(os.path.basename(it.get('file_path','?')))}</code>"
        elif k == "delay": txt += f"\n{i}. ⏸ {it.get('seconds',3)}s"
    rows = [[B(f"{T('delete')} {i+1}", f"pv:acc:{aid}:del:{i}")] for i in range(len(items))]
    rows.append([B(f"« {T('back')}", f"pv:acc:{aid}")])
    await panel(txt, kb_(*rows), page_tag=f"pv_list:{aid}")
async def show_pv_account_report(aid, page=0):
    rep = _load_pv_report(); users = rep.get(aid) or {}
    rows_data = []
    for uid, data in users.items():
        rows_data.append({"uid":uid,"first_name":data.get("first_name") or "","count":data.get("count",1),
            "replied":data.get("replied",False),"reply_ok":data.get("reply_ok",False),
            "blocked":data.get("blocked",False),"error":data.get("error"),"last_seen":data.get("last_seen",0)})
    rows_data.sort(key=lambda x: x["last_seen"], reverse=True)
    PER = 8; pages = max(1, -(-len(rows_data)//PER)); page = max(0, min(page, pages-1))
    chunk = rows_data[page*PER:(page+1)*PER]
    a = get_account(aid)
    txt = head("📊", f"{T('pv_report')} · {a.get('name','?') if a else aid}")
    txt += f"👥 {T('pv_total')}: <b>{len(rows_data)}</b>   ·   📄 {T('pv_page')} {page+1}/{pages}\n\n"
    for r in chunk:
        st = "✅" if r["replied"] and r["reply_ok"] else ("❌" if r["replied"] else "⏳")
        if r["blocked"]: st += " 🚫"
        ago = int(time.time() - r["last_seen"])
        txt += f"{st} <b>{esc(short(r['uid'][:20],20))}</b> · 📨×{r['count']} · <i>{_eta(ago)}</i>\n"
    nav_btns = []
    if pages > 1:
        pr = []
        if page > 0: pr.append(B(T("prev"), f"pv:acc:{aid}:report:{page-1}"))
        pr.append(B(f"{page+1}/{pages}", "noop"))
        if page < pages-1: pr.append(B(T("next"), f"pv:acc:{aid}:report:{page+1}"))
        nav_btns.append(pr)
    nav_btns.append([B(f"« {T('back')}", f"pv:acc:{aid}")])
    await panel(txt, kb_(*nav_btns), page_tag=f"pv_rep:{aid}:{page}")

def _accounts_view(page):
    accounts = list_accounts(); items = list(accounts.items())
    pages = max(1, -(-len(items)//PAGE_SIZE)); page = max(0, min(page, pages-1))
    chunk = items[page*PAGE_SIZE:(page+1)*PAGE_SIZE]
    rows = []
    for aid, a in chunk:
        cfg = _load_pv_account(aid)
        pv_icon = "🟢" if cfg.get("enabled") else "⚪"
        rows.append([B(f"📱 {short(a.get('name','?'),14)} · {pv_icon}", f"acc:view:{aid}")])
    if pages > 1:
        pr = []
        if page > 0: pr.append(B("◀️", f"acc:page:{page-1}"))
        pr.append(B(f"{page+1}/{pages}", "noop"))
        if page < pages-1: pr.append(B("▶️", f"acc:page:{page+1}"))
        rows.append(pr)
    rows.append([B(f"➕ {T('add_account')}", "acc:add")])
    rows.append(nav())
    txt = head("📱", "accounts_n", len(accounts))
    return txt, kb_(*rows), f"acc_list:{page}", chunk
async def show_accounts(page=0):
    txt, kb, tag, chunk = _accounts_view(page); await panel(txt, kb, page_tag=tag)
async def show_account_detail(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    t = LISTENER_TASKS.get(aid); on = bool(t and not t.done())
    pvt = PV_LISTENER_TASKS.get(aid); pvon = bool(pvt and not pvt.done())
    pvc = _load_pv_account(aid)
    n_ch = len(get_stored_channels(aid))
    txt = head("📱", a.get("name", "?"))
    txt += f"📞 <code>{esc(a.get('phone','—'))}</code>\n"
    txt += f"🆔 <code>{esc(aid)}</code>\n"
    txt += f"✨ {T('channels_created')}: <b>{n_ch}</b>\n"
    txt += f"👂 <b>{'🟢' if on else '⚪'}</b>   ·   💬 {T('pv')} <b>{'🟢' if pvon else '⚪'}</b>\n"
    txt += f"🔍 {T('seen')}: <b>{_seen_count(aid)}</b>  ·  🚫 {T('banned')}: <b>{_banned_count(aid)}</b>"
    rows = grid([B(T("auto_tar"), f"acc:at:{aid}"), B(T("channels"), f"ch:menu:{aid}"),
        B(T("profile"), f"prof:menu:{aid}"),
        B((T("toggle_off") if on else T("toggle_on")) + " " + T("listener"), f"listen:toggle:{aid}"),
        B(T("pv"), f"pv:acc:{aid}"), B(T("photo"), f"accphoto:menu:{aid}"),
        B(T("lefter"), f"acc:lf:{aid}"), B(T("cache"), f"cache:acc:{aid}")])
    rows.append([B(f"🗑 {T('delete_account')}", f"acc:del:{aid}")])
    rows.append(nav("menu:acc"))
    await panel(txt, kb_(*rows), page_tag=f"acc:{aid}")
async def show_profile_menu(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    rows = grid([B(T("name"), f"prof:set:first:{aid}"), B(T("last_name"), f"prof:set:last:{aid}"),
        B(T("bio"), f"prof:set:about:{aid}"), B(T("username"), f"prof:set:username:{aid}"),
        B(T("photo"), f"accphoto:menu:{aid}")])
    rows.append(nav(f"acc:view:{aid}"))
    await panel(head("📝", "profile", a.get("name","?")) + f"📞 <code>{esc(a.get('phone','—'))}</code>", kb_(*rows), page_tag=f"prof:{aid}")
async def show_acc_photo_menu(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    rows = [[B(T("prof_set_photo"), f"accphoto:set:{aid}")], [B(T("prof_del_photo"), f"accphoto:del:{aid}")], nav(f"acc:view:{aid}")]
    await panel(head("🖼", "prof_photo_menu", a.get("name","?")), kb_(*rows), page_tag=f"accphoto:{aid}")
async def show_ch_photo_menu(aid, idx):
    a = get_account(aid); chs = get_stored_channels(aid)
    if not a or idx < 0 or idx >= len(chs): return await show_ch_list(aid)
    ch = chs[idx]
    rows = [[B(T("prof_set_photo"), f"chphoto:set:{aid}:{idx}")], [B(T("prof_del_photo"), f"chphoto:del:{aid}:{idx}")], nav(f"ch:view:{aid}:{idx}")]
    await panel(head("🖼", "ch_photo_menu", ch.get("title","?")), kb_(*rows), page_tag=f"chphoto:{aid}:{idx}")
def _ch_link(ch):
    un = (ch.get("username") or "").lstrip("@")
    return ch.get("join_link") or (f"https://rubika.ir/{un}" if un else "")
async def show_ch_menu(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    n = len(get_stored_channels(aid))
    txt = head("📢", "channels", a.get("name","?")) + f"✨ {T('channels_created')}: <b>{n}</b>"
    rows = [[B(f"📋 {T('my_channels')} ({n})", f"chlist:show:{aid}:0")], [B(T("create_channel"), f"chnew:start:{aid}")], nav(f"acc:view:{aid}")]
    await panel(txt, kb_(*rows), page_tag=f"ch_menu:{aid}")
async def show_ch_list(aid, page=0):
    channels = get_stored_channels(aid); per = 6
    pages = max(1, -(-len(channels)//per)); page = max(0, min(page, pages-1))
    rows = []
    for idx, ch in list(enumerate(channels))[page*per:(page+1)*per]:
        icon = "🌐" if (ch.get("type") == "public" or ch.get("username")) else "🔒"
        lbl = f"{icon} {short(ch.get('title','?'),24)}"
        if ch.get("username"): lbl += f" · @{ch['username']}"
        rows.append([B(lbl, f"ch:view:{aid}:{idx}")])
    if pages > 1:
        pr = []
        if page > 0: pr.append(B("◀️", f"chlist:show:{aid}:{page-1}"))
        pr.append(B(f"{page+1}/{pages}", "noop"))
        if page < pages-1: pr.append(B("▶️", f"chlist:show:{aid}:{page+1}"))
        rows.append(pr)
    rows.append([B(T("create_channel"), f"chnew:start:{aid}")]); rows.append(nav(f"ch:menu:{aid}"))
    txt = head("📋", "my_channels", len(channels))
    txt += T("ch_no_channels") if not channels else ""
    await panel(txt, kb_(*rows), page_tag=f"chlist:{aid}:{page}")
async def show_channel_view(aid, idx):
    if not get_account(aid): return await panel(T("not_found"), kb_(nav()), page_tag="main")
    channels = get_stored_channels(aid)
    if idx < 0 or idx >= len(channels): return await show_ch_list(aid)
    ch = channels[idx]; un = ch.get("username") or ""
    is_pub = ch.get("type") == "public" or bool(un); link = _ch_link(ch)
    txt = head("📢", ch.get("title") or "?")
    txt += mrow("🔖", "type", (T("public") if is_pub else T("private"))) + "\n"
    if un: txt += mrow("🔤", "username", f"@{esc(un)}") + "\n"
    txt += mrow("🔗", "link", (f"<code>{esc(link)}</code>" if link else "—"))
    rows = grid([B(T("send"), f"chsend:start:{aid}:{idx}"), B(T("profile"), f"chprof:show:{aid}:{idx}"),
        B(T("get_link"), f"ch:getlink:{aid}:{idx}"), B(T("set_link"), f"ch:setlink:{aid}:{idx}"),
        B(T("photo"), f"chphoto:menu:{aid}:{idx}"), B(T("file"), f"chfile:start:{aid}:{idx}"),
        B(T("debug"), f"ch:diag:{aid}:{idx}"), B(T("delete"), f"ch:del:{aid}:{idx}")])
    rows.append(nav(f"chlist:show:{aid}:0"))
    await panel(txt, kb_(*rows), page_tag=f"chview:{aid}:{idx}")
async def show_ch_new_type(aid, title):
    await panel(head("🏗", "create_channel") + f"📝 <b>{esc(title)}</b>\n\n{T('ch_new_type')}",
        kb_([B(T("public"), f"chnew:pub:{aid}"), B(T("private"), f"chnew:priv:{aid}")],
            [B(f"« {T('cancel')}", f"ch:menu:{aid}")]), page_tag=f"chnew_type:{aid}")
async def show_listen_menu():
    accounts = list_accounts(); txt = head("👂", "listener")
    btns = []
    for aid, a in accounts.items():
        t = LISTENER_TASKS.get(aid); run = t is not None and not t.done()
        btns.append(B(f"{'🟢' if run else '⚪'} {short(a.get('name','?'),14)}", f"listen:toggle:{aid}"))
    rows = grid(btns); rows.append([B(T("listener_restart_all"), "listen:restart")]); rows.append(nav())
    await panel(txt, kb_(*rows), page_tag="listen")
async def show_linkdonies(back_to="jl:back_to_settings"):
    lst = load_link_donies(); auto = int(_load(CFG_FILE, DEFAULT_CFG).get("auto_join_linkdoni", 1))
    txt = head("📡", "linkdonies", len(lst))
    txt += f"🔁 {T('ld_auto_join')}: <b>{'🟢' if auto else '🔴'}</b>\n"
    txt += f"<i>{T('ld_progress_per_acc')}</i>\n\n"
    for i, url in enumerate(lst): txt += f"{i+1}. <code>{esc(url)}</code>\n"
    rows = grid([B(f"🗑 {i+1}. {short(u.split('/')[-1],12)}", f"ld:del:{i}:{back_to}") for i, u in enumerate(lst)])
    rows.append([B(T("ld_add"), f"ld:add:{back_to}"), B(T("toggle_off") if auto else T("toggle_on"), f"ld:toggle_autojoin:{back_to}")])
    rows.append([B(T("ld_reset_prog"), f"ld:reset_prog:{back_to}")])
    rows.append([B(T("ld_reset_list"), f"ld:reset:{back_to}")])
    rows.append(nav(back_to, home=False))
    await panel(txt, kb_(*rows), page_tag="linkdonies")
_OP_LAST = {}
def _op_view(op):
    oid = op["id"]; t = op.get("type")
    st = _op_effective_status(op); s = _op_stats(op); p = op.get("progress") or {}
    tot = s["total"] or 0; proc = s["done"] + s["failed"]
    pct = min(100, int(proc*100/tot)) if tot else 0
    icon = {"joinlef":"🤝","lefter":"🚪","autotar":"🎯","send":"📤"}.get(t,"⚙️")
    label = {"joinlef":"op_joiner","lefter":"op_lefter","autotar":"op_autotar","send":"op_send"}.get(t,"?")
    txt = head(icon, label, oid[-6:])
    txt += f"<b>{_op_status_label(st)}</b>\n"
    txt += f"<code>{_bar(pct)} {pct}%</code>\n\n"
    if t in ("joinlef","autotar"):
        txt += f"🤝 {T('op_joined')}: <b>{s['done']}</b>   ✗ {T('op_failed_c')}: <b>{s['failed']}</b>"
        if op.get("max_join"): txt += f"   🎯 <b>{op['max_join']}</b>"
        if s.get("already"): txt += f"\n♻️ {T('op_already')}: <b>{s['already']}</b>"
        if s.get("sent"): txt += f"\n📤 {T('op_sent')}: <b>{s['sent']}</b>"
        if s.get("left"): txt += f"\n🚪 {T('op_left')}: <b>{s['left']}</b>"
        if s.get("skipped_seen"): txt += f"\n🔍 {T('op_skipped_seen')}: <b>{s['skipped_seen']}</b>"
        if s.get("skipped_banned"): txt += f"\n🚫 {T('op_skipped_banned')}: <b>{s['skipped_banned']}</b>"
        if s.get("wave"): txt += f"\n🌊 {T('op_wave')}: <b>{s['wave']}</b>"
    elif t == "lefter":
        txt += f"🚪 {T('op_left')}: <b>{s['done']}</b>   ✗ {T('op_failed_c')}: <b>{s['failed']}</b>"
    else:
        txt += f"✓ {T('op_sent')}: <b>{s['done']}</b>   ✗ {T('op_failed_c')}: <b>{s['failed']}</b>   ⏳ {s['pending']}"
    txt += f"\n\n📍 <i>{esc(p.get('phase','—'))}</i>"
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
async def show_op_detail(oid):
    op = _get_op(oid)
    if not op: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    cid = STATE.get("owner")
    if cid: STATE.setdefault("op_panel", {})[cid] = oid
    txt, kb = _op_view(op); await panel(txt, kb, page_tag=f"op:{oid}")
async def show_stats():
    ops = _load_ops(); ops.sort(key=lambda o: o.get("created", 0), reverse=True)
    errs = _load_errors()
    done = sum(_op_stats(o)["done"] for o in ops); failed = sum(_op_stats(o)["failed"] for o in ops)
    running = [o for o in ops if _op_effective_status(o) == "running"]
    txt = head("📊", "stats_title")
    txt += f"✅ <b>{done}</b>   ❌ <b>{failed}</b>   ⚠️ <b>{len(errs)}</b>\n"
    if running:
        txt += f"\n<b>🟢 {T('stats_running')}</b>\n"
        for o in running[:3]:
            s = _op_stats(o); txt += f"• {esc(_op_short_title(o, 22))}  ✅{s['done']} ❌{s['failed']}\n"
    rows = []
    for o in ops[:8]:
        s = _op_stats(o); prog = f"{s['done']}/{s['total']}" if s["total"] else "—"
        rows.append([B(f"{short(_op_short_title(o, 20), 22)} · {prog}", f"op:view:{o['id']}")])
    rows.append([B(T("errors"), "menu:errors"), B(T("back_to_panel"), "menu:main")])
    await panel(txt, kb_(*rows), page_tag="stats")
async def show_errors(page=0):
    errors = list(reversed(_load_errors()))
    if not errors: return await panel(head("⚠️", "errors") + T("errors_none"), kb_(nav()), page_tag="errors")
    PER = 4; pages = max(1, -(-len(errors)//PER)); page = max(0, min(page, pages-1))
    txt = head("⚠️", "errors", len(errors))
    for e in errors[page*PER:(page+1)*PER]:
        t = time.strftime("%m/%d %H:%M", time.localtime(e.get("time", 0)))
        txt += f"\n🕐 <code>{esc(t)}</code> · <b>{esc(e.get('source','?'))}</b>\n<code>{esc(str(e.get('error',''))[:220])}</code>\n"
    rows = []
    if pages > 1:
        pr = []
        if page > 0: pr.append(B(T("prev"), f"err:page:{page-1}"))
        pr.append(B(f"{page+1}/{pages}", "noop"))
        if page < pages-1: pr.append(B(T("next"), f"err:page:{page+1}"))
        rows.append(pr)
    rows.append([B(T("clear"), "err:clear"), B(T("back_to_panel"), "menu:main")])
    await panel(txt, kb_(*rows), page_tag=f"errors:{page}")
async def show_cfg():
    cfg = _load(CFG_FILE, DEFAULT_CFG); lang = _get_lang()
    txt = head("⚙️", "cfg_title")
    txt += mrow("🌐","cfg_lang", (T("cfg_lang_fa") if lang=="fa" else T("cfg_lang_en"))) + "\n"
    txt += mrow("⏱","cfg_join_delay", cfg.get("join_delay", DEFAULT_CFG["join_delay"])) + "\n"
    txt += mrow("🌊","cfg_wave_size", cfg.get("wave_size", DEFAULT_CFG["wave_size"])) + "\n"
    txt += mrow("📦","cfg_extract", cfg.get("extract_limit", DEFAULT_CFG["extract_limit"])) + "\n"
    txt += mrow("⏸","cfg_wait", cfg.get("wait_for_links_sec", DEFAULT_CFG["wait_for_links_sec"])) + "\n"
    auto = int(cfg.get("auto_join_linkdoni", 1)); txt += mrow("🔁","cfg_auto_join", (T("on") if auto else T("off"))) + "\n"
    lst = int(cfg.get("listener", 1)); txt += mrow("👂","cfg_listener", (T("on") if lst else T("off")))
    lang_btn = f"🌐 {T('cfg_lang')}: {'🇮🇷 ' + T('cfg_lang_fa') if lang=='fa' else '🇬🇧 ' + T('cfg_lang_en')}"
    rows = [[B(lang_btn, "cfg:lang")],
        [B(T("cfg_join_delay"), "cfg:set:join_delay"), B(T("cfg_wave_size"), "cfg:set:wave_size")],
        [B(T("cfg_extract"), "cfg:set:extract_limit"), B(T("cfg_wait"), "cfg:set:wait_for_links_sec")],
        [B(T("toggle_off") if auto else T("toggle_on"), "cfg:toggle_autojoin")],
        [B(T("toggle_off") if lst else T("toggle_on"), "cfg:toggle_listener")], nav()]
    await panel(txt, kb_(*rows), page_tag="cfg")

# ═══════════════ WIZARDS ═══════════════
def _send_conv(cid):
    c = get_conv(cid)
    if "send" not in c:
        c["send"] = {"step":"accounts","accounts":[],"payload":None,"target":"both","max":0,
            "auto_left":False,"attach_file":"","groups_only":True,
            "infinite_loop":False,"loop_delay":3.0,"rescan_targets":True}
    return c["send"]
def _send_summary(s):
    accs = s.get("accounts") or []; all_a = list_accounts()
    if "all" in accs: al = f"{T('all')} ({len(all_a)})"
    elif not accs: al = "—"
    else:
        names = [get_account(i).get("name","?") for i in accs[:2] if get_account(i)]
        al = "، ".join(names) + (f" +{len(accs)-2}" if len(accs) > 2 else "")
    p = s.get("payload")
    tgt = {"pv":T("send_target_pv"),"groups":T("send_target_gr"),"both":T("send_target_both")}.get(s.get("target","both"),"?")
    mx = s.get("max", 0) or 0
    return (f"\n👤 {esc(al)}\n✉️ " + (f"«{esc(short(p.get('text'),30))}»" if p else "—") +
        f"\n🎯 {esc(tgt)}   ·   🔢 {mx if mx else '∞'}")
async def send_step_accounts(cid, s):
    accounts = list_accounts()
    if not accounts:
        return await panel(T("jl_no_account"), kb_([B(f"➕ {T('add_account')}", "acc:add")], nav()), page_tag="send:1")
    sel = set(s.get("accounts") or []); all_sel = "all" in sel
    btns = [B(SEL((all_sel or aid in sel), short(a.get('name','?'),14)), f"send:acc:{aid}") for aid, a in accounts.items()]
    rows = grid(btns)
    rows.append([B(T("all") if not all_sel else T("cancel"), "send:accall"), B(T("next"), "send:accnext")])
    rows.append([B(f"« {T('cancel')}", "send:cancel")])
    await panel(head("📤", "send", dots(1,4)) + T("send_step1") + _send_summary(s), kb_(*rows), page_tag="send:1")
async def send_step_compose(cid, s):
    txt = head("📤", "send", dots(2,4)) + T("send_step2") + _send_summary(s)
    rows = []
    if s.get("payload"): rows.append([B(T("send_custom"), "send:recompose"), B(T("next"), "send:composenext")])
    rows.append([B(f"« {T('back')}", "send:prev"), B(T("cancel"), "send:cancel")])
    await panel(txt, kb_(*rows), page_tag="send:2")
async def send_step_target(cid, s):
    t = s.get("target", "both")
    mk = lambda k, l: B(SEL(t == k, l), f"send:tgt:{k}")
    grp_only = bool(s.get("groups_only", True))
    inf_on = bool(s.get("infinite_loop", False)); ld = s.get("loop_delay", 3.0)
    rs = bool(s.get("rescan_targets", True)); af = s.get("attach_file") or ""
    rows = [[mk("pv", T("send_target_pv")), mk("groups", T("send_target_gr")), mk("both", T("send_target_both"))],
        [B(SEL(grp_only, T("send_grp_only")), "send:toggle_groups_only")],
        [B(SEL(inf_on, T("send_infinite")), "send:toggle_infinite")],
        [B(f"⏱ {T('send_loop_delay')}: {ld}s", "send:loop_delay")],
        [B(SEL(rs, T("send_rescan")), "send:toggle_rescan")],
        [B(f"📎 {T('send_attach')}: {esc(short(os.path.basename(af),15) if af else '—')}", "send:attach")],
        [B(SEL(s.get("auto_left"), T("send_auto_left")), "send:toggle_auto_left")],
        [B(T("next"), "send:tgtnext")],
        [B(f"« {T('back')}", "send:prev"), B(T("cancel"), "send:cancel")]]
    await panel(head("📤", "send", dots(3,4)) + T("send_step3") + _send_summary(s), kb_(*rows), page_tag="send:3")
async def send_step_max(cid, s):
    mx = s.get("max", 0); mk = lambda n: B(SEL(mx == n, str(n)), f"send:max:{n}")
    rows = [[mk(50), mk(100), mk(500)], [mk(1000), mk(2000), mk(5000)],
        [B(SEL(mx == 0, T("send_unlimited")), "send:max:0"), B(T("send_custom"), "send:max:custom")],
        [B(T("confirm"), "send:maxnext")],
        [B(f"« {T('back')}", "send:prev"), B(T("cancel"), "send:cancel")]]
    await panel(head("📤", "send", dots(4,4)) + T("send_step4") + _send_summary(s), kb_(*rows), page_tag="send:4")
async def send_step_confirm(cid, s):
    accounts = list_accounts(); sel = s.get("accounts") or []
    if "all" in sel: sel = list(accounts.keys())
    if not sel: s["step"] = "accounts"; return await panel(T("empty"), kb_(nav()), page_tag="send:1")
    if not s.get("payload"): s["step"] = "compose"; return await panel(T("empty"), kb_(nav()), page_tag="send:2")
    await panel(head("📤", "confirm") + _send_summary(s),
        kb_([B(T("start"), "send:go")], [B(T("send_custom"), "send:back_edit"), B(T("cancel"), "send:cancel")]),
        page_tag="send:confirm")
async def show_send_step(cid):
    s = _send_conv(cid); step = s["step"]
    if step == "accounts": await send_step_accounts(cid, s)
    elif step == "compose": await send_step_compose(cid, s)
    elif step == "target": await send_step_target(cid, s)
    elif step == "max": await send_step_max(cid, s)
    elif step == "confirm": await send_step_confirm(cid, s)

def _jl_conv(cid):
    c = get_conv(cid)
    if "jl" not in c: c["jl"] = {"step":"account","accounts":[],"max_join":0,"speed":"fast","groups_only":True}
    return c["jl"]
async def jl_step_account(cid, s):
    accounts = list_accounts()
    if not accounts:
        return await panel(T("jl_no_account"), kb_([B(f"➕ {T('add_account')}", "acc:add")], nav()), page_tag="jl:1")
    sel = set(s.get("accounts") or [])
    rows = grid([B(SEL(aid in sel, short(a.get('name','?'),14)), f"jl:acc:{aid}") for aid, a in accounts.items()])
    rows.append([B(T("next"), "jl:next")]); rows.append([B(T("back_to_panel"), "menu:main")])
    await panel(head("🤝", "joiner", dots(1,3)) + f"{T('jl_select')}  <b>{len(sel)}</b>", kb_(*rows), page_tag="jl:1")
async def jl_step_settings(cid, s):
    speed = s.get("speed", "fast"); lds = load_link_donies()
    lbl = next((T(l) for k, l, _ in JL_SPEEDS if k == speed), "—")
    grp = T("on") if s.get("groups_only", True) else T("off")
    txt = head("🤝", "joiner", dots(2,3)) + mrow("🚀","jl_speed",lbl) + "\n" + mrow("📡","jl_ld",len(lds)) + "\n" + mrow("👥","jl_grp_only",grp)
    rows = grid([B(SEL(speed == k, T(l)), f"jl:speed:{k}") for k, l, _ in JL_SPEEDS])
    rows.append([B(f"📡 {T('jl_ld')} ({len(lds)})", "jl:linkdonies")])
    rows.append([B(SEL(s.get("groups_only", True), T("jl_grp_only")), "jl:toggle_groups_only")])
    rows.append([B(T("next"), "jl:next")]); rows.append(nav("jl:back"))
    await panel(txt, kb_(*rows), page_tag="jl:2")
async def jl_step_max(cid, s):
    mx = s.get("max_join", 0); mk = lambda n: B(SEL(mx == n, str(n)), f"jl:max:{n}")
    txt = head("🤝", "joiner", dots(3,3)) + f"{T('jl_max')}: <b>{mx if mx else '∞'}</b>"
    rows = [[mk(50), mk(100), mk(200)], [mk(500), mk(1000), mk(2000)], [B(T("send_custom"), "jl:max:custom")]]
    if mx: rows.append([B(T("start"), "jl:go")])
    rows.append(nav("jl:back"))
    await panel(txt, kb_(*rows), page_tag="jl:3")
async def show_jl_step(cid):
    s = _jl_conv(cid)
    if s["step"] == "account": await jl_step_account(cid, s)
    if s["step"] == "settings": await jl_step_settings(cid, s)
    if s["step"] == "max": await jl_step_max(cid, s)

def _lf_conv(cid):
    c = get_conv(cid)
    if "lf" not in c: c["lf"] = {"step":"account","accounts":[],"mode":"all","delay":0.5}
    return c["lf"]
def _lf_modes():
    return [("all","lf_mode_all"),("groups","lf_mode_groups"),("channels","lf_mode_channels"),("closed","lf_mode_closed")]
async def lf_step_account(cid, s):
    accounts = list_accounts()
    if not accounts:
        return await panel(T("jl_no_account"), kb_([B(f"➕ {T('add_account')}", "acc:add")], nav()), page_tag="lf:1")
    sel = set(s.get("accounts") or [])
    rows = grid([B(SEL(aid in sel, short(a.get('name','?'),14)), f"lf:acc:{aid}") for aid, a in accounts.items()])
    rows.append([B(T("next"), "lf:next")]); rows.append([B(T("back_to_panel"), "menu:main")])
    await panel(head("🚪", "lefter", dots(1,3)) + f"{T('jl_select')}  <b>{len(sel)}</b>", kb_(*rows), page_tag="lf:1")
async def lf_step_mode(cid, s):
    mode = s.get("mode", "all")
    btns = [B(SEL(mode == k, T(l)), f"lf:mode:{k}") for k, l in _lf_modes()]
    rows = [[b] for b in btns]
    rows.append([B(T("next"), "lf:next")]); rows.append(nav("lf:back"))
    await panel(head("🚪", "lefter", dots(2,3)) + T("lf_mode"), kb_(*rows), page_tag="lf:2")
async def lf_step_delay(cid, s):
    d = s.get("delay", 0.5); mk = lambda n, l: B(SEL(abs(d-n) < 0.01, l), f"lf:delay:{n}")
    txt = head("🚪", "lefter", dots(3,3)) + f"{T('lf_delay')}: <b>{d}s</b>"
    rows = [[mk(0.2,"🚀 0.2s"), mk(0.5,"⚡ 0.5s"), mk(1.0,"🐢 1.0s")], [mk(2.0,"🛡 2s")],
        [B(T("start"), "lf:go")], nav("lf:back")]
    await panel(txt, kb_(*rows), page_tag="lf:3")
async def show_lf_step(cid):
    s = _lf_conv(cid)
    if s["step"] == "account": await lf_step_account(cid, s)
    if s["step"] == "mode": await lf_step_mode(cid, s)
    if s["step"] == "delay": await lf_step_delay(cid, s)

async def show_at_menu():
    tpls = list_templates()
    txt = head("🎯", "at_title", len(tpls)) + f"<i>{T('at_desc')}</i>"
    rows = []
    for tid, t in list(tpls.items())[:8]:
        parts = []
        if t.get("channel",{}).get("title"): parts.append("🌐" if t.get("channel",{}).get("type")=="public" else "🔒")
        if t.get("profile",{}).get("first_name") or t.get("profile",{}).get("bio"): parts.append("📝")
        if int(t.get("joiner",{}).get("max_join",0) or 0) > 0: parts.append("🤝")
        if t.get("sender",{}).get("text"): parts.append("📤")
        if t.get("pv",{}).get("items"): parts.append("💬")
        if t.get("lefter",{}).get("leave_mode"): parts.append("🚪")
        rows.append([B(f"🎯 {short(t.get('name','?'),16)}  ·  {' '.join(parts) or '∅'}", f"at:{tid}:view")])
    rows.append([B(f"➕ {T('at_new')}", "at:new")]); rows.append(nav())
    await panel(txt, kb_(*rows), page_tag="at:menu")
async def show_at_view(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    ch = t.get("channel",{}); pr = t.get("profile",{}); jn = t.get("joiner",{})
    sn = t.get("sender",{}); lf = t.get("lefter",{}); pv = t.get("pv",{})
    def bd(d, k): return "🟢" if d.get(k) else "⚪"
    def bdn(d, k): return "🟢" if int(d.get(k,0) or 0) > 0 else "⚪"
    txt = head("🎯", t.get("name", "?"))
    txt += f"🏗 {T('at_channel')}: {bd(ch,'title')}"
    if ch.get("title"): txt += f" <i>{esc(short(ch['title'],20))}</i>"
    txt += f"\n📝 {T('at_profile')}: {bd(pr,'first_name') or bd(pr,'bio') or bd(pr,'username')}"
    txt += f"\n🤝 {T('at_joiner')}: {bdn(jn,'max_join')}"
    txt += f"\n📤 {T('at_sender')}: {bd(sn,'text')}"
    txt += f"\n💬 {T('at_pv')}: {'🟢' if pv.get('enabled') else '⚪'}  ·  {len(pv.get('items') or [])}"
    txt += f"\n🚪 {T('at_lefter')}: 🟢 <i>{lf.get('leave_mode','?')}</i>"
    rows = grid([B(T("at_channel"), f"at:{tid}:ch"), B(T("at_profile"), f"at:{tid}:pr"),
        B(T("at_joiner"), f"at:{tid}:jn"), B(T("at_sender"), f"at:{tid}:sn"),
        B(T("at_pv"), f"at:{tid}:pv"), B(T("at_lefter"), f"at:{tid}:lf"), B(T("at_rename"), f"at:{tid}:rename")])
    rows.append([B(T("at_run"), f"at:{tid}:run")])
    rows.append([B(T("at_delete"), f"at:{tid}:del"), B(T("back_to_panel"), "menu:main")])
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:view")
async def show_at_channel(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    c = t.get("channel",{}); is_pub = c.get("type","private") == "public"
    txt = head("🏗", "at_channel", t.get("name","?"))
    txt += mrow("🔖","type",(T("public") if is_pub else T("private"))) + "\n"
    txt += mrow("📝","channel_title", c.get("title") or "—") + "\n"
    if is_pub: txt += mrow("🔤","username", c.get("username") or "—") + "\n"
    txt += mrow("📖","about", short(c.get("about",""),40) or "—")
    rows = [[B(SEL(is_pub, T("public")), f"at:{tid}:chtype:public"), B(SEL(not is_pub, T("private")), f"at:{tid}:chtype:private")],
        [B(T("channel_title"), f"at:{tid}:chset:title")]]
    if is_pub: rows.append([B(T("username"), f"at:{tid}:chset:username")])
    rows.append([B(T("about"), f"at:{tid}:chset:about")]); rows.append(nav(f"at:{tid}:view"))
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:ch")
async def show_at_profile(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    p = t.get("profile",{})
    txt = head("📝","at_profile", t.get("name","?"))
    txt += mrow("👤","name", p.get("first_name") or "—") + "\n"
    txt += mrow("👤","last_name", p.get("last_name") or "—") + "\n"
    txt += mrow("🔤","username", p.get("username") or "—") + "\n"
    txt += mrow("📖","bio", short(p.get("bio",""),60) or "—")
    rows = [[B(T("name"), f"at:{tid}:prset:first_name"), B(T("last_name"), f"at:{tid}:prset:last_name")],
        [B(T("username"), f"at:{tid}:prset:username"), B(T("bio"), f"at:{tid}:prset:bio")],
        nav(f"at:{tid}:view")]
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:pr")
async def show_at_joiner(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    j = t.get("joiner",{}); spd = j.get("speed")
    spd_lbl = next((T(l) for k, l, _ in JL_SPEEDS if k == spd), spd)
    txt = head("🤝","at_joiner", t.get("name","?"))
    txt += mrow("🎯","jl_max", j.get("max_join",0)) + "\n"
    txt += mrow("🚀","jl_speed", spd_lbl) + "\n"
    txt += mrow("👥","jl_grp_only", ("🟢" if j.get("groups_only",True) else "⚪"))
    rows = [[B(T("jl_max"), f"at:{tid}:jnset:max_join")]]
    rows += grid([B(SEL(spd == k, T(l)), f"at:{tid}:jnspeed:{k}") for k, l, _ in JL_SPEEDS])
    rows.append([B(SEL(j.get("groups_only",True), T("jl_grp_only")), f"at:{tid}:jntoggle_groups_only")])
    rows.append(nav(f"at:{tid}:view"))
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:jn")
async def show_at_sender(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    s = t.get("sender",{})
    modes = {"send_only":T("at_mode_only"),"join_send":T("at_mode_js"),"join_send_leave":T("at_mode_jsl")}
    txt = head("📤","at_sender", t.get("name","?"))
    txt += mrow("✉️","text", short(s.get("text",""),50) or "—") + "\n"
    txt += mrow("🎯","target", s.get("target","?")) + "\n"
    txt += mrow("🔁","mode", modes.get(s.get("mode"), s.get("mode"))) + "\n"
    txt += mrow("🔢","max", s.get("max_send",0) or "∞") + "\n"
    txt += mrow("⏱","delay", f"{s.get('delay',1.5)}s")
    rows = [[B(T("text"), f"at:{tid}:snset:text")],
        [B(T("target"), f"at:{tid}:snset:target"), B(T("max"), f"at:{tid}:snset:max_send")],
        [B(T("delay"), f"at:{tid}:snset:delay"), B(T("mode"), f"at:{tid}:snmode")],
        nav(f"at:{tid}:view")]
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:sn")
async def show_at_sender_mode(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    cur = t["sender"].get("mode", "send_only")
    opts = [("send_only",T("at_mode_only")),("join_send",T("at_mode_js")),("join_send_leave",T("at_mode_jsl"))]
    rows = grid([B(SEL(cur == k, l), f"at:{tid}:snmode_set:{k}") for k, l in opts])
    rows.append(nav(f"at:{tid}:sn"))
    await panel(head("🔁","mode") + f"<b>{cur}</b>", kb_(*rows), page_tag=f"at:{tid}:snmode")
async def show_at_pv(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    pv = t.get("pv",{}); en = bool(pv.get("enabled")); mx = int(pv.get("max_replies",1) or 0)
    items = pv.get("items") or []; apply_acc = bool(pv.get("apply_to_accounts", True))
    txt = head("💬","at_pv", t.get("name","?"))
    txt += mrow("📶","pv_status", (T("pv_active") if en else T("pv_inactive"))) + "\n"
    txt += mrow("👥","pv_max", (mx if mx else "∞")) + "\n"
    txt += mrow("⏱","pv_delay", f"{pv.get('delay_seconds',0)}s") + "\n"
    txt += mrow("🔄","at_apply_acc", ("🟢" if apply_acc else "⚪")) + "\n"
    txt += mrow("📨","pv_items", len(items)) + "\n\n"
    for i, it in enumerate(items, 1):
        k = it.get("kind","text")
        if k == "text": txt += f"{i}. 💬 <code>{esc(short(it.get('text',''),40))}</code>\n"
        elif k == "file": txt += f"{i}. 📁 <code>{esc(os.path.basename(it.get('file_path','?')))}</code>\n"
        elif k == "delay": txt += f"{i}. ⏸ {it.get('seconds',3)}s\n"
    rows = [[B(T("toggle_off") if en else T("toggle_on"), f"at:{tid}:pv:toggle")],
        [B(f"{T('pv_max')}: {mx if mx else '∞'}", f"at:{tid}:pv:cycle_max"), B(T("pv_delay"), f"at:{tid}:pv:set_delay")],
        [B(T("pv_add_text"), f"at:{tid}:pv:add_text"), B(T("pv_add_file"), f"at:{tid}:pv:add_saved"), B(T("pv_add_delay"), f"at:{tid}:pv:add_delay")],
        [B(SEL(apply_acc, T("at_apply_acc")), f"at:{tid}:pv:toggle_apply")],
        [B(T("pv_list"), f"at:{tid}:pv:list")], nav(f"at:{tid}:view")]
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:pv")
async def show_at_pv_list(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    items = (t.get("pv") or {}).get("items") or []
    txt = head("📋","pv_list", len(items))
    for i, it in enumerate(items, 1):
        k = it.get("kind","text")
        if k == "text": txt += f"\n{i}. 💬 <code>{esc(short(it.get('text',''),60))}</code>"
        elif k == "file": txt += f"\n{i}. 📁 <code>{esc(os.path.basename(it.get('file_path','?')))}</code>"
        elif k == "delay": txt += f"\n{i}. ⏸ {it.get('seconds',3)}s"
    rows = [[B(f"{T('delete')} {i+1}", f"at:{tid}:pv:del:{i}")] for i in range(len(items))]
    rows.append([B(f"« {T('back')}", f"at:{tid}:pv")])
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:pv_list")
async def show_at_lefter(tid):
    t = get_template(tid)
    if not t: return await show_at_menu()
    l = t.get("lefter",{})
    txt = head("🚪","at_lefter", t.get("name","?")) + f"🎯 {T('lf_mode')}: <b>{l.get('leave_mode','?')}</b>"
    rows = []
    for k, lbl in _lf_modes(): rows.append([B(SEL(l.get("leave_mode") == k, T(lbl)), f"at:{tid}:lfset:{k}")])
    rows.append(nav(f"at:{tid}:view"))
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:lf")
async def show_at_run(tid, page=0):
    t = get_template(tid)
    if not t: return await show_at_menu()
    accounts = list_accounts(); items = list(accounts.items())
    per = 6; pages = max(1, -(-len(items)//per)); page = max(0, min(page, pages-1))
    chunk = items[page*per:(page+1)*per]
    cid = STATE.get("owner"); conv = get_conv(cid) if cid else {}
    selected = set((conv.get("at_run") or {}).get("accounts") or [])
    rows = []
    for aid, a in chunk: rows.append([B(SEL(aid in selected, short(a.get('name','?'),20)), f"at:{tid}:run_acc:{aid}")])
    if pages > 1:
        pr = []
        if page > 0: pr.append(B(T("prev"), f"at:{tid}:run:{page-1}"))
        pr.append(B(f"{page+1}/{pages}", "noop"))
        if page < pages-1: pr.append(B(T("next"), f"at:{tid}:run:{page+1}"))
        rows.append(pr)
    rows.append([B(T("start"), f"at:{tid}:run_go")]); rows.append(nav(f"at:{tid}:view"))
    txt = head("🎯","at_run_title", t.get("name","?")) + f"{T('jl_selected')}: <b>{len(selected)}</b>"
    await panel(txt, kb_(*rows), page_tag=f"at:{tid}:run:{page}")
async def show_acc_at_menu(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    tpls = list_templates()
    txt = head("🎯","auto_tar", a.get("name","?"))
    if not tpls: return await panel(txt + "\n\n" + T("empty"), kb_([B(f"➕ {T('at_new')}", "at:new"), B(T("back_to_panel"), "menu:main")]), page_tag=f"acc:at:{aid}")
    rows = []
    for tid, t in list(tpls.items())[:10]: rows.append([B(f"🎯 {short(t.get('name','?'),22)}", f"acc:at:run:{aid}:{tid}")])
    rows.append(nav(f"acc:view:{aid}"))
    await panel(txt, kb_(*rows), page_tag=f"acc:at:{aid}")
async def show_acc_lf(aid):
    a = get_account(aid)
    if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
    txt = head("🚪","lefter", a.get("name","?"))
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
    if pending_inputs.get(cid):
        q = pending_inputs[cid].get("q")
        if q:
            try: q.put(text); return
            except Exception: pass
    # PV wait
    if conv.get("pv_acc_wait"):
        w = conv.pop("pv_acc_wait"); aid = w.get("aid"); kind = w.get("kind")
        cfg = _load_pv_account(aid); items = cfg.get("items") or []
        if kind == "delay":
            try: cfg["delay_seconds"] = max(0, int(re.sub(r"[^\d]", "", text) or "0"))
            except: cfg["delay_seconds"] = 0
        elif kind == "poll":
            try: cfg["poll_seconds"] = max(2, int(re.sub(r"[^\d]", "", text) or "3"))
            except: cfg["poll_seconds"] = 3
        elif kind == "add_text":
            items.append({"kind":"text","text":text}); cfg["items"] = items
        elif kind == "add_delay_sec":
            try: sec = max(0, int(re.sub(r"[^\d]", "", text) or "3"))
            except: sec = 3
            items.append({"kind":"delay","seconds":sec}); cfg["items"] = items
        _save_pv_account(aid, cfg); await tg_send("✅"); return await show_pv_account_menu(aid)
    if conv.get("pv_acc_save_msg"):
        w = conv.pop("pv_acc_save_msg"); aid = w.get("aid")
        media = _extract_media(msg); caption = text or ""
        if not media and not caption: return await ask(T("enter"))
        local_path = None
        if media:
            try: local_path = await _download_tg_file(media, "pv", "pvitem")
            except Exception: pass
        cfg = _load_pv_account(aid); items = cfg.get("items") or []
        if local_path: items.append({"kind":"file","file_path":local_path,"caption":caption})
        else: items.append({"kind":"text","text":caption})
        cfg["items"] = items; _save_pv_account(aid, cfg); await tg_send("✅")
        return await show_pv_account_menu(aid)
    # ld wait
    if conv.get("ld_wait") == "url":
        back = conv.pop("ld_back", "jl:back_to_settings"); url = text.strip()
        if url.startswith("rubika.ir"): url = "@" + url.split("/")[-1]
        if add_link_doni(url): await tg_send("✅")
        else: await tg_send("ℹ️")
        return await show_linkdonies(back)
    # profile
    if conv.get("prof_field"):
        info = conv.pop("prof_field"); field = info["field"]; aid = info["aid"]
        STATE["panel"].pop(cid, None); a = get_account(aid)
        if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
        await panel(f"⏳ {T('loading')}", page_tag=f"prof:{aid}")
        ok = False; msg_r = ""; cli = None
        try:
            cli, err = await _connect_with_retry(aid, a["session_name"], name=a.get("name"), tries=3)
            if cli is None: ok, msg_r = False, f"connect: {err}"
            else:
                try:
                    fn = getattr(cli, "update_profile", None) or getattr(cli, "updateProfile", None)
                    if field == "first" and fn: await fn(first_name=text); ok, msg_r = True, "OK"
                    elif field == "last" and fn: await fn(last_name=text); ok, msg_r = True, "OK"
                    elif field == "about" and fn: await fn(bio=text); ok, msg_r = True, "OK"
                    elif field == "username":
                        ufn = getattr(cli, "update_username", None) or getattr(cli, "updateUsername", None)
                        if ufn: await ufn(username=text.lstrip("@")); ok, msg_r = True, "OK"
                except Exception as e: ok, msg_r = False, _fmt_error(e)
        except Exception as e: ok, msg_r = False, _fmt_error(e)
        finally:
            if cli:
                try: await cli._disconnect()
                except Exception: pass
        return await panel(("✅" if ok else f"⚠️ {esc(str(msg_r)[:200])}"), kb_([B(f"« {T('back')}", f"prof:menu:{aid}")]), page_tag=f"prof:{aid}")
    # channel send
    if conv.get("chsend") and conv["chsend"].get("step") == "compose":
        info = conv.pop("chsend"); aid = info["aid"]; idx = info["idx"]
        a = get_account(aid); chs = get_stored_channels(aid)
        if not a or idx >= len(chs): return await panel(T("not_found"), kb_(nav()), page_tag="main")
        ch = chs[idx]; guid = ch.get("guid")
        STATE["panel"].pop(cid, None); await panel(f"⏳ {T('loading')}", page_tag=f"chview:{aid}:{idx}")
        cli = None; ok = False; msg_r = ""
        try:
            cli, err = await _connect_with_retry(aid, a["session_name"], name=a.get("name"), tries=3)
            if cli:
                await cli.send_message(object_guid=guid, text=text); ok, msg_r = True, "OK"
            else: msg_r = f"connect: {err}"
        except Exception as e: msg_r = _fmt_error(e)
        finally:
            if cli:
                try: await cli._disconnect()
                except Exception: pass
        if ok: return await panel(head("✅", "send") + f"💬 <code>{esc(text[:100])}</code>", kb_([B(f"« {T('back')}", f"ch:view:{aid}:{idx}")]), page_tag=f"chview:{aid}:{idx}")
        return await panel(f"❌ <code>{esc(str(msg_r)[:400])}</code>", kb_([B(f"« {T('back')}", f"ch:view:{aid}:{idx}")]), page_tag=f"chview:{aid}:{idx}")
    # channel new
    if conv.get("chnew"):
        info = conv["chnew"]; step = info.get("step"); aid = info.get("aid")
        a = get_account(aid); STATE["panel"].pop(cid, None)
        if not a: conv.pop("chnew", None); return await panel(T("not_found"), kb_(nav()), page_tag="main")
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
            cli = None; ok = False; msg_r = ""; guid = None
            try:
                cli, err = await _connect_with_retry(aid, a["session_name"], name=a.get("name"), tries=3)
                if cli:
                    try:
                        r = await cli.add_channel(title=title)
                        guid = _extract_guid_from_update(r)
                        if guid and uname:
                            try:
                                await cli.edit_channel_info(channel_guid=guid, channel_type="Public")
                            except Exception: pass
                        ok = bool(guid)
                    except Exception as e: msg_r = _fmt_error(e)
                else: msg_r = f"connect: {err}"
            except Exception as e: msg_r = _fmt_error(e)
            finally:
                if cli:
                    try: await cli._disconnect()
                    except Exception: pass
            _STATS_CACHE.pop(aid, None)
            if ok and guid:
                add_channel_to_storage(aid, {"title":title,"description":"","guid":guid,
                    "username":uname,"is_public":True,"type":"public","created":int(time.time())})
                return await panel(head("✅", "ch_created") + f"📝 {esc(title)}\n🔗 @{esc(uname)}",
                    kb_([B(f"⚙️ {T('my_channels')}", f"chlist:show:{aid}:0")], [B(f"« {T('back')}", f"ch:menu:{aid}")]),
                    page_tag=f"ch_menu:{aid}")
            return await panel(f"❌ <code>{esc(str(msg_r)[:300])}</code>", kb_([B(f"« {T('back')}", f"ch:menu:{aid}")]), page_tag=f"ch_menu:{aid}")
    # jl max wait
    if "jl_wait" in conv:
        conv.pop("jl_wait"); jl = get_conv(cid).get("jl") or {}
        try: jl["max_join"] = max(1, int(re.sub(r"[^\d]", "", text)))
        except: return await ask(T("jl_max_q"))
        get_conv(cid)["jl"] = jl; return await jl_step_max(cid, jl)
    if "send_wait" in conv:
        conv.pop("send_wait"); s = _send_conv(cid)
        try: s["max"] = max(0, int(re.sub(r"[^\d]", "", text)))
        except: return await ask(T("send_max_q"))
        return await show_send_step(cid)
    if "send" in conv:
        s = conv["send"]
        if s.get("step") == "compose":
            STATE["panel"].pop(cid, None)
            if not text: return await ask(T("send_step2"))
            s["payload"] = {"text": text}; s["step"] = "target"
            return await show_send_step(cid)
    if "acc" in conv:
        a = conv["acc"]; step = a.get("step")
        STATE["panel"].pop(cid, None)
        if step == "phone":
            try: ph = normalize_phone(text)
            except Exception as e: return await ask(T("invalid_phone"), note=str(e)[:150])
            a["phone"] = ph
            await panel(f"⏳ {T('loading')} <code>{esc(ph)}</code>", page_tag="login_code")
            a["step"] = "login_code"; STATE["conv"][cid] = {"acc": a}
            return await panel(f"✅ <code>{esc(ph)}</code>", page_tag="login_code")
    if "acc" in conv and conv["acc"].get("step") == "login_code":
        # Actually login - need full interactive login
        phone = conv["acc"].get("phone")
        if not phone: return
        STATE["panel"].pop(cid, None)
        await panel(f"⏳ {T('loading')}", page_tag="login_verify")
        try: res = await _do_full_login(phone, text, cid)
        except Exception as e: res = {"ok":False,"status":_fmt_error(e)}
        clear_conv(cid)
        if res.get("ok"):
            try: await start_pv_responders()
            except Exception: pass
            await panel(head("✅", f"{res.get('name')}") + f"🆔 <code>{esc(res['aid'])}</code>",
                kb_([B(T("back_to_panel"), "menu:main")]), page_tag="main"); return
        await panel(f"❌ <code>{esc(str(res.get('status'))[:400])}</code>",
            kb_([B(T("add_account"), "acc:add")], [B(T("back_to_panel"), "menu:main")]), page_tag="main"); return
_on_message_orig = _on_message_impl
async def on_message(update, context):
    cid = None; had_conv = False
    try:
        cid = update.effective_chat.id
        had_conv = bool(STATE["conv"].get(cid)) or (cid in _TMP_EDIT)
    except Exception: pass
    await _on_message_orig(update, context)
    try:
        if had_conv and authorized(update) and update.message: await update.message.delete()
    except Exception: pass

# ═══════════════ CALLBACK ROUTER ═══════════════
async def route_cb(cid, data):
    p = data.split(":"); h = p[0]
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
        cur = _get_lang(); new = "en" if cur == "fa" else "fa"
        _set_lang(new); await tg_send(("🌐 " + T("cfg_lang_en")) if new == "en" else ("🌐 " + T("cfg_lang_fa")))
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
                    ex = PV_LISTENER_TASKS.get(aid)
                    if not ex or ex.done():
                        acc = get_account(aid)
                        if acc:
                            stop = asyncio.Event(); _PV_STOP_EVENTS[aid] = stop
                            PV_LISTENER_TASKS[aid] = asyncio.create_task(_pv_poller_worker(aid, acc, stop))
                else: _stop_pv_for_account(aid)
                return await show_pv_account_menu(aid)
            if act == "cycle_max":
                seq = [1,2,3,5,0]; cur = int(cfg.get("max_replies",1) or 0)
                cfg["max_replies"] = seq[(seq.index(cur)+1) % len(seq)] if cur in seq else 1
                _save_pv_account(aid, cfg); return await show_pv_account_menu(aid)
            if act == "set_delay": get_conv(cid)["pv_acc_wait"] = {"aid":aid,"kind":"delay"}; return await ask(T("pv_delay_q"))
            if act == "set_poll": get_conv(cid)["pv_acc_wait"] = {"aid":aid,"kind":"poll"}; return await ask(T("pv_poll_q"))
            if act == "toggle_notify": cfg["notify"] = not bool(cfg.get("notify", True)); _save_pv_account(aid, cfg); return await show_pv_account_menu(aid)
            if act == "add_text": get_conv(cid)["pv_acc_wait"] = {"aid":aid,"kind":"add_text"}; return await ask(T("pv_text_q"))
            if act == "add_saved": get_conv(cid)["pv_acc_save_msg"] = {"aid":aid}; return await ask(T("pv_file_q"))
            if act == "add_delay": get_conv(cid)["pv_acc_wait"] = {"aid":aid,"kind":"add_delay_sec"}; return await ask(T("pv_delaysec_q"))
            if act == "list": return await show_pv_account_list(aid)
            if act == "del" and len(p) >= 5:
                try: i = int(p[4])
                except: return await show_pv_account_list(aid)
                items = cfg.get("items") or []
                if 0 <= i < len(items): items.pop(i)
                cfg["items"] = items; _save_pv_account(aid, cfg); await tg_send("🗑"); return await show_pv_account_list(aid)
            if act == "clear_replies":
                try: d = _load(PV_COUNTS_FILE, {}); d.pop(aid, None); _save(PV_COUNTS_FILE, d)
                except Exception: pass
                try: w = _wm_load(); w.pop(aid, None); _wm_flush()
                except Exception: pass
                await tg_send("🧹"); return await show_pv_account_menu(aid)
            if act == "reset_to_global": _delete_pv_account(aid); await tg_send("♻️"); return await show_pv_account_menu(aid)
            if act == "restart":
                _stop_pv_for_account(aid); await asyncio.sleep(0.3)
                cfg2 = _load_pv_account(aid)
                if cfg2.get("enabled"):
                    acc = get_account(aid)
                    if acc:
                        stop = asyncio.Event(); _PV_STOP_EVENTS[aid] = stop
                        PV_LISTENER_TASKS[aid] = asyncio.create_task(_pv_poller_worker(aid, acc, stop))
                await tg_send("🔄"); return await show_pv_account_menu(aid)
            if act == "report":
                try: pg = int(p[4]) if len(p) > 4 else 0
                except: pg = 0
                return await show_pv_account_report(aid, pg)
    if h == "acc":
        if len(p) >= 5 and p[1] == "at" and p[2] == "run":
            aid = p[3]; tid = p[4]
            op = {"id":"at_"+secrets.token_hex(5),"created":int(time.time()),"type":"autotar","accounts":[aid],
                "template_id":tid,"status":"running","progress":{"joined":0,"failed":0,"total":0,"pending":0,
                "in_progress":0,"phase":T("ph_start"),"sent":0,"already":0,"tried":0,"wave":0,"left":0,
                "round":0,"skipped_seen":0,"skipped_banned":0,"rejected":0},"errors":[]}
            _save_op(op); asyncio.create_task(run_auto_tar(op, log_cb))
            return await show_op_detail(op["id"])
        if len(p) >= 3 and p[1] == "at": return await show_acc_at_menu(p[2])
        sub = p[1] if len(p) > 1 else ""
        if sub == "page": return await show_accounts(int(p[2]))
        if sub == "add": get_conv(cid)["acc"] = {"step":"phone"}; return await ask(T("add_account_q"))
        if sub == "view": return await show_account_detail(p[2])
        if sub == "del":
            a = get_account(p[2])
            if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
            return await panel(T("acc_delete_q", n=esc(a.get('name','?'))),
                kb_([B(T("yes"), f"acc:delok:{p[2]}"), B(T("no"), f"acc:view:{p[2]}")]), page_tag=f"acc_del:{p[2]}")
        if sub == "delok":
            _stop_listener_for(p[2]); _stop_pv_for_account(p[2])
            remove_account(p[2]); await tg_send("🗑"); return await show_accounts()
        if sub == "lf" and len(p) >= 5 and p[3] == "go":
            aid = p[2]; mode = p[4]
            op = {"id":"lf_"+secrets.token_hex(5),"created":int(time.time()),"type":"lefter","accounts":[aid],
                "leave_mode":mode,"delay":0.5,"status":"running","progress":{"joined":0,"failed":0,"total":0,
                "phase":T("ph_start")},"errors":[]}
            _save_op(op); asyncio.create_task(run_lefter(op, log_cb))
            return await show_op_detail(op["id"])
        if sub == "lf" and len(p) >= 3: return await show_acc_lf(p[2])
    if h == "accphoto":
        sub = p[1] if len(p) > 1 else ""
        if sub == "menu" and len(p) >= 3: return await show_acc_photo_menu(p[2])
        if sub == "set" and len(p) >= 3:
            get_conv(cid)["accphoto_upload"] = {"aid": p[2]}; return await ask(T("prof_send_photo"))
        if sub == "del" and len(p) >= 3:
            aid = p[2]; a = get_account(aid)
            if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
            await panel(f"⏳ {T('prof_deleting')}", page_tag=f"accphoto:{aid}")
            cli = None; ok = False; msg_r = ""
            try:
                cli, err = await _connect_with_retry(aid, a["session_name"], name=a.get("name"), tries=3)
                if cli:
                    fn = getattr(cli, "delete_avatar", None)
                    if fn: await fn(); ok, msg_r = True, "OK"
                    else: ok, msg_r = False, "no-api"
                else: msg_r = f"connect: {err}"
            except Exception as e: msg_r = _fmt_error(e)
            finally:
                if cli:
                    try: await cli._disconnect()
                    except Exception: pass
            await tg_send("✅" if ok else f"❌ {msg_r[:150]}")
            return await show_acc_photo_menu(aid)
    if h == "chphoto":
        sub = p[1] if len(p) > 1 else ""
        if sub == "menu" and len(p) >= 4: return await show_ch_photo_menu(p[2], int(p[3]))
        if sub == "set" and len(p) >= 4: get_conv(cid)["chphoto_upload"] = {"aid":p[2],"idx":int(p[3])}; return await ask(T("prof_send_photo"))
    if h == "jl":
        c = get_conv(cid)
        s = c.get("jl") or {"step":"account","accounts":[],"max_join":0,"speed":"fast","groups_only":True}
        c["jl"] = s; sub = p[1] if len(p) > 1 else ""
        if sub == "start":
            c["jl"] = {"step":"account","accounts":[],"max_join":0,"speed":"fast","groups_only":True}
            return await jl_step_account(cid, c["jl"])
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
            except: pass
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
            speed_map = {"ultra":0.2,"fast":0.6,"normal":1.5,"slow":4.0}
            spd = s.get("speed", "fast"); cfg = _load(CFG_FILE, DEFAULT_CFG)
            op = {"id":"jl_"+secrets.token_hex(5),"created":int(time.time()),"type":"joinlef",
                "accounts":s.get("accounts") or [],"max_join":s.get("max_join",0),"status":"running","speed":spd,
                "join_delay":speed_map.get(spd, 0.6),"groups_only":bool(s.get("groups_only", True)),
                "wave_size":int(cfg.get("wave_size",50)),"extract_limit":int(cfg.get("extract_limit",300)),
                "link_donies":list(load_link_donies()),
                "progress":{"joined":0,"failed":0,"total":0,"phase":T("ph_start"),
                    "skipped_seen":0,"skipped_banned":0,"rejected":0,"already":0,"sent":0,"wave":0,"tried":0,"left":0,"round":0},
                "errors":[]}
            _save_op(op); c.pop("jl", None)
            JL_JOBS[op["id"]] = asyncio.create_task(run_joiner_lefter(op, log_cb))
            return await show_op_detail(op["id"])
    if h == "lf":
        c = get_conv(cid)
        s = c.get("lf") or {"step":"account","accounts":[],"mode":"all","delay":0.5}
        c["lf"] = s; sub = p[1] if len(p) > 1 else ""
        if sub == "start":
            c["lf"] = {"step":"account","accounts":[],"mode":"all","delay":0.5}
            return await lf_step_account(cid, c["lf"])
        if sub == "acc" and len(p) >= 3:
            aid = p[2]; sel = s.setdefault("accounts", [])
            if aid in sel: sel.remove(aid)
            else: sel.append(aid)
            return await lf_step_account(cid, s)
        if sub == "mode" and len(p) >= 3: s["mode"] = p[2]; return await lf_step_mode(cid, s)
        if sub == "delay" and len(p) >= 3:
            try: s["delay"] = float(p[2])
            except: s["delay"] = 0.5
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
            op = {"id":"lf_"+secrets.token_hex(5),"created":int(time.time()),"type":"lefter",
                "accounts":s.get("accounts") or [],"leave_mode":s.get("mode","all"),"delay":s.get("delay",0.5),
                "status":"running","progress":{"joined":0,"failed":0,"total":0,"phase":T("ph_start")},"errors":[]}
            _save_op(op); c.pop("lf", None)
            asyncio.create_task(run_lefter(op, log_cb))
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
                return await panel(T("at_delete_q", n=esc(t.get('name','?'))),
                    kb_([B(T("yes"), f"at:{tid}:delok"), B(T("no"), f"at:{tid}:view")]), page_tag=f"at:{tid}:view")
            if act == "delok": delete_template(tid); await tg_send("🗑"); return await show_at_menu()
            if act == "rename": _TMP_EDIT[cid] = {"kind":"at_field","tid":tid,"section":"meta","field":"name"}; return await ask(T("at_rename_q"))
            if act == "ch": return await show_at_channel(tid)
            if act == "pr": return await show_at_profile(tid)
            if act == "jn": return await show_at_joiner(tid)
            if act == "sn": return await show_at_sender(tid)
            if act == "pv": return await show_at_pv(tid)
            if act == "lf": return await show_at_lefter(tid)
            if act == "snmode": return await show_at_sender_mode(tid)
            if act == "chtype" and len(p) >= 4: update_template(tid, "channel", "type", p[3]); return await show_at_channel(tid)
            if act == "chset" and len(p) >= 4:
                _TMP_EDIT[cid] = {"kind":"at_field","tid":tid,"section":"channel","field":p[3]}
                return await ask(T("enter"))
            if act == "prset" and len(p) >= 4:
                _TMP_EDIT[cid] = {"kind":"at_field","tid":tid,"section":"profile","field":p[3]}
                return await ask(T("enter"))
            if act == "jnset" and len(p) >= 4:
                _TMP_EDIT[cid] = {"kind":"at_field","tid":tid,"section":"joiner","field":p[3]}
                return await ask(T("jl_max"))
            if act == "jnspeed" and len(p) >= 4: update_template(tid, "joiner", "speed", p[3]); return await show_at_joiner(tid)
            if act == "jntoggle_groups_only":
                t = get_template(tid)
                if t: update_template(tid, "joiner", "groups_only", not bool(t.get("joiner",{}).get("groups_only", True)))
                return await show_at_joiner(tid)
            if act == "snset" and len(p) >= 4:
                _TMP_EDIT[cid] = {"kind":"at_field","tid":tid,"section":"sender","field":p[3]}
                return await ask(T("enter"))
            if act == "snmode_set" and len(p) >= 4: update_template(tid, "sender", "mode", p[3]); return await show_at_sender(tid)
            if act == "pv" and len(p) >= 4:
                sub_act = p[3]; t2 = get_template(tid)
                if not t2: return await show_at_menu()
                pv2 = t2.setdefault("pv", {}); items = pv2.get("items") or []
                if sub_act == "toggle":
                    pv2["enabled"] = not bool(pv2.get("enabled", False))
                    update_template(tid, "pv", "enabled", pv2["enabled"]); return await show_at_pv(tid)
                if sub_act == "cycle_max":
                    seq = [1,2,3,5,0]; cur = int(pv2.get("max_replies",1) or 0)
                    nv = seq[(seq.index(cur)+1) % len(seq)] if cur in seq else 1
                    update_template(tid, "pv", "max_replies", nv); return await show_at_pv(tid)
                if sub_act == "set_delay": get_conv(cid)["pv_tpl_wait"] = {"tid":tid,"kind":"delay"}; return await ask(T("pv_delay_q"))
                if sub_act == "toggle_apply":
                    update_template(tid, "pv", "apply_to_accounts", not bool(pv2.get("apply_to_accounts", True))); return await show_at_pv(tid)
                if sub_act == "add_text": get_conv(cid)["pv_tpl_wait"] = {"tid":tid,"kind":"add_text"}; return await ask(T("pv_text_q"))
                if sub_act == "add_saved": get_conv(cid)["pv_tpl_save_msg"] = {"tid":tid}; return await ask(T("pv_file_q"))
                if sub_act == "add_delay": get_conv(cid)["pv_tpl_wait"] = {"tid":tid,"kind":"add_delay_sec"}; return await ask(T("pv_delaysec_q"))
                if sub_act == "list": return await show_at_pv_list(tid)
                if sub_act == "del" and len(p) >= 5:
                    try: i = int(p[4])
                    except: return await show_at_pv_list(tid)
                    if 0 <= i < len(items): items.pop(i)
                    update_template(tid, "pv", "items", items); await tg_send("🗑"); return await show_at_pv_list(tid)
            if act == "lfset" and len(p) >= 4: update_template(tid, "lefter", "leave_mode", p[3]); return await show_at_lefter(tid)
            if act == "run": return await show_at_run(tid)
            if act == "run_acc" and len(p) >= 4:
                c = get_conv(cid); ar = c.setdefault("at_run", {"template_id":tid,"accounts":[]})
                sel = ar.setdefault("accounts", [])
                if p[3] in sel: sel.remove(p[3])
                else: sel.append(p[3])
                return await show_at_run(tid)
            if act == "run_go":
                c = get_conv(cid); ar = c.get("at_run") or {}
                sel = ar.get("accounts") or []
                if not sel: return await panel(T("empty"), kb_(nav(f"at:{tid}:view")), page_tag=f"at:{tid}:run:0")
                op = {"id":"at_"+secrets.token_hex(5),"created":int(time.time()),"type":"autotar","accounts":sel,
                    "template_id":tid,"status":"running","progress":{"joined":0,"failed":0,"total":0,"pending":0,
                    "in_progress":0,"phase":T("ph_start"),"sent":0,"already":0,"tried":0,"wave":0,"left":0,"round":0,
                    "skipped_seen":0,"skipped_banned":0,"rejected":0},"errors":[]}
                _save_op(op); c.pop("at_run", None)
                asyncio.create_task(run_auto_tar(op, log_cb))
                return await show_op_detail(op["id"])
            if len(p) == 3 and p[2].isdigit(): return await show_at_run(tid, int(p[2]))
    if h == "ch":
        sub = p[1] if len(p) > 1 else ""
        if sub == "menu": return await show_ch_menu(p[2])
        if sub == "view" and len(p) >= 4: return await show_channel_view(p[2], int(p[3]))
        if sub == "getlink" and len(p) >= 4:
            aid = p[2]; idx = int(p[3]); channels = get_stored_channels(aid)
            if idx >= len(channels): return await show_ch_list(aid)
            await panel(f"⏳ {T('ch_link_fetch')}", page_tag=f"chview:{aid}:{idx}")
            a = get_account(aid); cli = None; ok = False; link = ""
            try:
                cli, err = await _connect_with_retry(aid, a["session_name"], name=a.get("name"), tries=3)
                if cli:
                    try:
                        r = await cli.get_channel_link(channel_guid=channels[idx]["guid"])
                        d = _to_dict(r); link = d.get("link") or (d.get("channel") or {}).get("link") or ""
                        ok = bool(link)
                    except Exception as e: link = _fmt_error(e)
            finally:
                if cli:
                    try: await cli._disconnect()
                    except Exception: pass
            if ok: update_channel_field(aid, idx, "join_link", link)
            return await panel((f"✅ <code>{esc(link)}</code>" if ok else f"⚠️ {esc(str(link)[:200])}"),
                kb_([B(f"« {T('back')}", f"ch:view:{aid}:{idx}")]), page_tag=f"chview:{aid}:{idx}")
        if sub == "setlink" and len(p) >= 4:
            get_conv(cid)["setlink"] = {"aid":p[2],"idx":int(p[3])}; return await ask(T("ch_link_q"))
        if sub == "del" and len(p) >= 4:
            aid = p[2]; idx = int(p[3]); channels = get_stored_channels(aid)
            if idx >= len(channels): return await show_ch_list(aid)
            return await panel(T("ch_delete_q"),
                kb_([B(T("yes"), f"ch:delok:{aid}:{idx}"), B(T("no"), f"ch:view:{aid}:{idx}")]), page_tag=f"chview:{aid}:{idx}")
        if sub == "delok" and len(p) >= 4:
            aid = p[2]; idx = int(p[3]); channels = get_stored_channels(aid)
            if idx < len(channels):
                a = get_account(aid); cli = None
                try:
                    cli, err = await _connect_with_retry(aid, a["session_name"], name=a.get("name"), tries=3)
                    if cli:
                        try: await cli.remove_channel(channel_guid=channels[idx]["guid"])
                        except Exception: pass
                finally:
                    if cli:
                        try: await cli._disconnect()
                        except Exception: pass
                remove_channel_from_storage(aid, idx)
            await tg_send("🗑"); return await show_ch_list(aid)
    if h == "chlist":
        sub = p[1] if len(p) > 1 else ""
        if sub == "show": return await show_ch_list(p[2], int(p[3]) if len(p) > 3 else 0)
    if h == "chsend":
        sub = p[1] if len(p) > 1 else ""
        if sub == "start" and len(p) >= 4:
            get_conv(cid)["chsend"] = {"aid":p[2],"idx":int(p[3]),"step":"compose"}; return await ask(T("ch_send_q"))
    if h == "chnew":
        sub = p[1] if len(p) > 1 else ""
        if sub == "start":
            get_conv(cid)["chnew"] = {"aid":p[2],"step":"title"}; return await ask(T("ch_new_name_q"))
        if sub == "pub":
            aid = p[2]; info = get_conv(cid).get("chnew") or {}
            title = info.get("title")
            if not title: return await panel(T("not_found"), kb_(nav(f"ch:menu:{aid}")), page_tag=f"ch_menu:{aid}")
            get_conv(cid)["chnew"] = {"aid":aid,"step":"username","title":title}; return await ask(T("ch_new_user_q"))
        if sub == "priv":
            aid = p[2]; info = get_conv(cid).get("chnew") or {}; title = info.get("title")
            if not title: return await panel(T("not_found"), kb_(nav(f"ch:menu:{aid}")), page_tag=f"ch_menu:{aid}")
            get_conv(cid).pop("chnew", None); a = get_account(aid); STATE["panel"].pop(cid, None)
            if not a: return await panel(T("not_found"), kb_(nav()), page_tag="main")
            await panel(f"⏳ {T('ch_creating')}", page_tag="chnew_run")
            cli = None; ok = False; guid = None; msg_r = ""
            try:
                cli, err = await _connect_with_retry(aid, a["session_name"], name=a.get("name"), tries=3)
                if cli:
                    try:
                        r = await cli.add_channel(title=title); guid = _extract_guid_from_update(r); ok = bool(guid)
                    except Exception as e: msg_r = _fmt_error(e)
                else: msg_r = f"connect: {err}"
            finally:
                if cli:
                    try: await cli._disconnect()
                    except Exception: pass
            _STATS_CACHE.pop(aid, None)
            if ok and guid:
                add_channel_to_storage(aid, {"title":title,"description":"","guid":guid,
                    "is_public":False,"type":"private","created":int(time.time())})
                return await panel(head("✅", "ch_created") + f"📝 {esc(title)}",
                    kb_([B(f"⚙️ {T('my_channels')}", f"chlist:show:{aid}:0")], [B(f"« {T('back')}", f"ch:menu:{aid}")]),
                    page_tag=f"ch_menu:{aid}")
            return await panel(f"❌ <code>{esc(str(msg_r)[:300])}</code>", kb_([B(f"« {T('back')}", f"ch:menu:{aid}")]), page_tag=f"ch_menu:{aid}")
    if h == "prof":
        sub = p[1] if len(p) > 1 else ""
        if sub == "menu": return await show_profile_menu(p[2])
        if sub == "set":
            field = p[2]; aid = p[3]
            get_conv(cid)["prof_field"] = {"field":field,"aid":aid}
            prompts = {"first":T("prof_first_q"),"last":T("prof_last_q"),"about":T("prof_bio_q"),"username":T("prof_user_q")}
            return await ask(prompts.get(field, T("enter")))
    if h == "ld":
        sub = p[1] if len(p) > 1 else ""
        back = p[3] if len(p) > 3 else (p[2] if len(p) > 2 else "jl:back_to_settings")
        if sub == "list": return await show_linkdonies(back)
        if sub == "add": get_conv(cid)["ld_wait"] = "url"; get_conv(cid)["ld_back"] = back; return await ask(T("ld_add_q"))
        if sub == "del" and len(p) >= 3: remove_link_doni(int(p[2])); await tg_send("🗑"); return await show_linkdonies(back)
        if sub == "reset": save_link_donies(list(DEFAULT_LINK_DONIES)); await tg_send("🔄"); return await show_linkdonies(back)
        if sub == "reset_prog": _reset_ld_progress(); await tg_send("🔄"); return await show_linkdonies(back)
        if sub == "toggle_autojoin":
            cfg = _load(CFG_FILE, DEFAULT_CFG); cfg["auto_join_linkdoni"] = 0 if int(cfg.get("auto_join_linkdoni",1)) else 1
            _save(CFG_FILE, cfg); return await show_linkdonies(back)
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
                if op.get("type") in ("joinlef","autotar"):
                    t = JL_JOBS.get(oid)
                    if t and not t.done(): t.cancel()
                else:
                    st = STATE.get("cancel_" + oid)
                    if st: st.set()
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
        if sub == "attach": get_conv(cid)["send_file_upload"] = True; return await ask(T("send_attach_q"))
        if sub == "tgtnext": s["step"] = "max"; return await show_send_step(cid)
        if sub == "max" and len(p) >= 3:
            v = p[2]
            if v == "custom": get_conv(cid)["send_wait"] = "max"; return await ask(T("send_max_q"))
            try: s["max"] = int(v)
            except: pass
            return await show_send_step(cid)
        if sub == "maxnext": s["step"] = "confirm"; return await show_send_step(cid)
        if sub == "back": s["step"] = "accounts"; return await show_send_step(cid)
        if sub == "prev":
            order = ["accounts","compose","target","max","confirm"]
            i = order.index(s.get("step", "accounts")); s["step"] = order[max(0, i-1)]; return await show_send_step(cid)
        if sub == "back_edit": s["step"] = "accounts"; return await show_send_step(cid)
        if sub == "cancel": clear_conv(cid); return await show_main()
        if sub == "go":
            accounts = list_accounts(); sel = s.get("accounts") or []
            if "all" in sel: sel = list(accounts.keys())
            op = {"id":"sd_"+secrets.token_hex(5),"created":int(time.time()),"type":"send","accounts":sel,
                "target":s.get("target","both"),"max":s.get("max",0) or 0,
                "payload":s.get("payload") or {"text":"سلام"},"delay":1.5,
                "auto_left":bool(s.get("auto_left", False)),"status":"running",
                "groups_only":bool(s.get("groups_only", True)),"attach_file":s.get("attach_file",""),
                "infinite_loop":bool(s.get("infinite_loop", False)),"loop_delay":float(s.get("loop_delay",3.0)),
                "rescan_targets":bool(s.get("rescan_targets", True)),
                "progress":{"sent":0,"failed":0,"total":0,"pending":0,"in_progress":0,"phase":T("ph_start"),"blocked":0,"round":0},
                "errors":[]}
            _save_op(op); clear_conv(cid)
            asyncio.create_task(run_sender(op, log_cb))
            return await show_op_detail(op["id"])
    if h == "cfg":
        sub = p[1] if len(p) > 1 else ""
        if sub == "set" and len(p) >= 3:
            key = p[2]; get_conv(cid)["cfg_wait"] = key; return await ask(T("cfg_value_q", k=key))
        if sub == "toggle_autojoin":
            cfg = _load(CFG_FILE, DEFAULT_CFG); cfg["auto_join_linkdoni"] = 0 if int(cfg.get("auto_join_linkdoni",1)) else 1
            _save(CFG_FILE, cfg); return await show_cfg()
        if sub == "toggle_listener":
            cfg = _load(CFG_FILE, DEFAULT_CFG); cfg["listener"] = 0 if int(cfg.get("listener",1)) else 1
            _save(CFG_FILE, cfg); return await show_cfg()

# ═══════════════ BOOT ═══════════════
async def _post_init(app):
    try:
        await app.bot.set_my_commands([BotCommand("start", "شروع"), BotCommand("menu", "منو")])
    except Exception: pass
    try: _loop_ref[0] = asyncio.get_running_loop()
    except Exception: pass
    try:
        await start_all_listeners(); await start_pv_responders()
        asyncio.create_task(keepalive_loop())
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
    if token: TG_TOKEN = token
    else: TG_TOKEN = os.environ.get("TG_TOKEN", "").strip()
    if not TG_TOKEN or ":" not in TG_TOKEN: print("[x] TG_TOKEN نیست."); return
    if owner_id: FORCED_OWNER = int(owner_id)
    else:
        try: FORCED_OWNER = int(os.environ.get("TG_OWNER_ID", "8389746549"))
        except: FORCED_OWNER = 8389746549
    STATE["owner"] = FORCED_OWNER
    ensure_rubika_loop()
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