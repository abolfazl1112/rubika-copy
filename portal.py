#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات تلگرام آپلود خودکار HTML + منابع به cPanel (نسخه 4.0)
==========================================================
تغییرات نسبت به 3.8:
- پوشه پروژه با شماره ترتیبی (1, 2, 3, ...) → لینک کوتاه‌تر
- شمارنده در counter.txt روی هاست (بعد از restart حفظ می‌شود)
- محدودیت دسترسی به یک user_id مشخص
- پشتیبانی کامل از API 2 برای mkdir

پیش‌نیازها:
    pip install python-telegram-bot==21.6 httpx==0.27.2 \\
                beautifulsoup4==4.12.3 Pillow==10.4.0
"""

import logging
import os
import re
import shutil
import tempfile
import warnings
from pathlib import Path
from urllib.parse import urlparse, unquote

import httpx
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.ext.filters import MessageFilter

# ==============================================================
# ⚙️ تنظیمات
# ==============================================================

BOT_TOKEN         = "8921325744:AAFXRJVzWotsUiZ9yslVpc7NevS2c-8DNnQ"

CPANEL_HOST       = "webiksahostfast.site"
CPANEL_PORT       = "2083"
CPANEL_USER       = "vaacyvb"
CPANEL_TOKEN      = "BEWG8JLUYJWMO30IT14S0TNNFPYMRA6D"
CPANEL_VERIFY_SSL = False

CPANEL_BASE_PATH  = "/public_html"         # پوشه‌ها مستقیم در public_html ساخته می‌شوند (1، 2، 3...)
PUBLIC_BASE_URL   = "https://link.webiksahostfast.site"

# فقط این کاربر می‌تواند از ربات استفاده کند
ALLOWED_USER_ID   = 8389746549

COUNTER_FILE_PATH = "/public_html/.counter.txt"   # فایل شمارنده روی هاست

MAX_FILE_SIZE = 20 * 1024 * 1024
CONVERTIBLE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif"}
WEBP_QUALITY = 82

# ==============================================================

try:
    import lxml  # noqa: F401
    HTML_PARSER = "lxml"
except ImportError:
    HTML_PARSER = "html.parser"

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)
log.info(f"HTML parser: {HTML_PARSER} | Pillow: {'yes' if PIL_AVAILABLE else 'no'}")


# ==============================================================
# 🔒 بررسی دسترسی
# ==============================================================

def is_allowed(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id == ALLOWED_USER_ID)


async def _reject(update: Update):
    await update.effective_message.reply_text("⛔ دسترسی ندارید.")


# ==============================================================
# 🔍 فیلتر سفارشی HTML
# ==============================================================

class FilterHTMLDocument(MessageFilter):
    def filter(self, message):
        return bool(
            message.document
            and message.document.file_name
            and message.document.file_name.lower().endswith((".html", ".htm"))
        )


filter_html_doc = FilterHTMLDocument()


# ==============================================================
# ☁️ کلاینت cPanel
# ==============================================================

class CPanelClient:
    def __init__(self, host, port, user, token, verify_ssl=False):
        self.host = host
        self.port = port
        self.user = user
        self.token = token
        self.base = f"https://{host}:{port}/execute"
        self.headers = {"Authorization": f"cpanel {user}:{token}"}
        self.verify = verify_ssl

    def _client(self, timeout):
        return httpx.AsyncClient(verify=self.verify, timeout=timeout)

    # ---------- UAPI ----------

    async def _get(self, endpoint, params):
        async with self._client(60) as c:
            r = await c.get(f"{self.base}/{endpoint}", headers=self.headers, params=params)
            r.raise_for_status()
            data = r.json()
            if data.get("status") != 1:
                raise RuntimeError(f"cPanel {endpoint} failed: {data}")
            return data

    async def _dir_exists(self, path: str) -> bool:
        try:
            async with self._client(30) as c:
                r = await c.get(
                    f"{self.base}/Fileman/list_files",
                    headers=self.headers,
                    params={"path": path, "types": "dir"},
                )
                return r.json().get("status") == 1
        except Exception:
            return False

    async def _file_exists(self, path: str) -> bool:
        try:
            async with self._client(30) as c:
                r = await c.get(
                    f"{self.base}/Fileman/list_files",
                    headers=self.headers,
                    params={"path": path, "types": "file"},
                )
                return r.json().get("status") == 1
        except Exception:
            return False

    # ---------- API 2 ----------

    async def _api2_call(self, module: str, func: str, **params):
        url = f"https://{self.host}:{self.port}/json-api/cpanel"
        payload = {
            "cpanel_jsonapi_user": self.user,
            "cpanel_jsonapi_apiversion": "2",
            "cpanel_jsonapi_module": module,
            "cpanel_jsonapi_func": func,
            **params,
        }
        async with self._client(30) as c:
            r = await c.get(url, headers=self.headers, params=payload)
            r.raise_for_status()
            data = r.json()
            result = data.get("cpanelresult", {})
            if result.get("error"):
                raise RuntimeError(f"API2 {module}/{func} failed: {data}")
            if result.get("data"):
                first = result["data"][0] if isinstance(result["data"], list) else result["data"]
                if isinstance(first, dict) and first.get("result") == 0:
                    raise RuntimeError(f"API2 {module}/{func} failed: {first}")
            return data

    # ---------- عمومی ----------

    async def ensure_dir(self, full_path: str):
        parts = [p for p in full_path.split("/") if p]
        current = ""
        for part in parts:
            parent = current or "/"
            current = f"{current}/{part}"
            if await self._dir_exists(current):
                continue
            log.info(f"mkdir: {parent} / {part}")
            await self._api2_call("Fileman", "mkdir", path=parent, name=part)

    async def upload_file(self, remote_dir: str, filename: str, content: bytes):
        async with self._client(300) as c:
            r = await c.post(
                f"{self.base}/Fileman/upload_files",
                headers=self.headers,
                data={"dir": remote_dir},
                files={"file-1": (filename, content)},
            )
            r.raise_for_status()
            data = r.json()
            if data.get("status") != 1:
                raise RuntimeError(f"Upload failed: {data}")
            return data

    async def read_file(self, full_path: str) -> str | None:
        """خواندن محتوای یک فایل — برای counter.txt"""
        try:
            async with self._client(30) as c:
                r = await c.get(
                    f"{self.base}/Fileman/get_file_content",
                    headers=self.headers,
                    params={"path": full_path},
                )
                data = r.json()
                if data.get("status") == 1:
                    return data.get("data", {}).get("content")
                return None
        except Exception as e:
            log.warning(f"read_file failed: {e}")
            return None

    async def get_next_project_number(self, counter_file: str) -> int:
        """شمارنده را می‌خواند، +1 می‌کند، ذخیره می‌کند و برمی‌گرداند."""
        current = 0
        content = await self.read_file(counter_file)
        if content:
            try:
                current = int(content.strip())
            except ValueError:
                current = 0
        new_num = current + 1
        counter_dir = os.path.dirname(counter_file) or "/"
        counter_name = os.path.basename(counter_file)
        await self.upload_file(counter_dir, counter_name, str(new_num).encode("utf-8"))
        log.info(f"Project number: {new_num}")
        return new_num


# ==============================================================
# 🧩 پارسر HTML + متادیتا
# ==============================================================

EXTERNAL_PREFIXES = ("http://", "https://", "//", "data:", "#", "javascript:", "mailto:")
METADATA_REGEX = re.compile(r"<!--\s*CPANELBOT\s*(.*?)-->", re.DOTALL | re.IGNORECASE)


def _is_external(url: str) -> bool:
    return url.lower().startswith(EXTERNAL_PREFIXES)


def _clean(url: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path).replace("\\", "/").lstrip("/")
    while path.startswith("./"):
        path = path[2:]
    return path


def extract_metadata(html_bytes: bytes) -> dict:
    text = html_bytes.decode("utf-8", errors="ignore")
    m = METADATA_REGEX.search(text)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip().upper(), val.strip()
        if key and val:
            meta[key] = val
    return meta


def extract_resources(html_bytes: bytes):
    soup = BeautifulSoup(html_bytes, HTML_PARSER)
    resources, seen = [], set()

    for img in soup.find_all("img"):
        src = img.get("src")
        if src and not _is_external(src):
            p = _clean(src)
            if p and p not in seen:
                seen.add(p)
                resources.append({"path": p, "tag": "img", "attr": "src"})

    for a in soup.find_all("a"):
        href = a.get("href")
        if not href or _is_external(href):
            continue
        if href.lower().split("?")[0].endswith(".apk"):
            p = _clean(href)
            if p and p not in seen:
                seen.add(p)
                resources.append({"path": p, "tag": "a", "attr": "href"})

    return soup, resources


def rewrite_paths(soup, resources, path_map: dict, public_base: str, project_id: str) -> bytes:
    for r in resources:
        old = r["path"]
        new = path_map.get(old, old)
        new_url = f"{public_base}/{project_id}/{new}"
        for tag in soup.find_all(r["tag"]):
            cur = tag.get(r["attr"])
            if cur and _clean(cur) == old:
                tag[r["attr"]] = new_url
    return str(soup).encode("utf-8")


# ==============================================================
# 🖼 تبدیل WebP
# ==============================================================

def convert_images_to_webp(state) -> dict:
    if not PIL_AVAILABLE:
        log.warning("Pillow نصب نیست — تبدیل WebP رد شد.")
        return {}

    path_map = {}
    for r in state.resources:
        if r["tag"] != "img":
            continue
        old_path = r["path"]
        ext = os.path.splitext(old_path)[1].lower()
        if ext not in CONVERTIBLE_EXTS:
            continue
        local_old = state.uploaded.get(old_path)
        if not local_old or not local_old.exists():
            continue

        new_path = os.path.splitext(old_path)[0] + ".webp"
        local_new = state.tmp_dir / new_path
        local_new.parent.mkdir(parents=True, exist_ok=True)

        try:
            old_size = local_old.stat().st_size
            with Image.open(local_old) as im:
                kw = {"quality": WEBP_QUALITY, "method": 4}
                if getattr(im, "is_animated", False):
                    kw["save_all"] = True
                im.save(local_new, "WEBP", **kw)
            new_size = local_new.stat().st_size
            log.info(f"WebP: {old_path} {old_size}B -> {new_path} {new_size}B")

            state.uploaded.pop(old_path, None)
            state.uploaded[new_path] = local_new
            path_map[old_path] = new_path
        except Exception as e:
            log.warning(f"webp conversion failed for {old_path}: {e}")

    return path_map


# ==============================================================
# 🗂 وضعیت پروژه
# ==============================================================

class ProjectState:
    def __init__(self, html_bytes: bytes, resources, metadata: dict):
        self.html_bytes = html_bytes
        self.resources = resources
        self.metadata = metadata
        self.pending = [r["path"] for r in resources]
        self.uploaded: dict[str, Path] = {}
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="proj_"))
        self.total = len(resources)
        self.project_id: str | None = None   # بعد از دریافت شماره ست می‌شود

    @property
    def done_count(self) -> int:
        return self.total - len(self.pending)

    def next_pending(self) -> str | None:
        return self.pending[0] if self.pending else None

    def cleanup(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)


# ==============================================================
# 🎛 هندلرها
# ==============================================================

WAITING_HTML, WAITING_FILES = range(2)


def _progress_header(state: ProjectState) -> str:
    md = state.metadata
    lines = []
    if md.get("TITLE"):
        lines.append(f"📌 <b>{md['TITLE']}</b>")
    if md.get("DESCRIPTION"):
        lines.append(f"📝 {md['DESCRIPTION']}")
    if md.get("VERSION"):
        lines.append(f"🏷 نسخه: {md['VERSION']}")
    return ("\n".join(lines) + "\n\n") if lines else ""


def _is_image_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in (CONVERTIBLE_EXTS | {".webp", ".svg"})


async def _ask_next_file(message, state: ProjectState):
    nxt = state.next_pending()
    if not nxt:
        return
    idx = state.done_count + 1
    icon = "🖼" if _is_image_path(nxt) else "📱"
    await message.reply_text(
        f"📥 <b>[{idx}/{state.total}]</b> فایل مربوط به این مورد را بفرستید:\n\n"
        f"{icon} ذخیره خواهد شد به نام: <code>{nxt}</code>\n\n"
        f"<i>هر فایلی بفرستید قبول می‌شود (Document یا Photo).</i>\n"
        f"لغو: /cancel",
        parse_mode="HTML",
    )


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await _reject(update)
    await update.message.reply_text(
        "سلام 👋\n\n"
        "یک فایل HTML بفرستید (به‌صورت Document).\n"
        "سپس لیست فایل‌های مورد نیاز را نشان می‌دهم و یکی‌یکی می‌پرسم.\n"
        "نام فایل‌های ارسالی مهم نیست — خودم تغییر نام می‌دهم.\n"
        "تصاویر هنگام آپلود به WebP تبدیل می‌شوند.\n\n"
        "لغو: /cancel",
    )
    return WAITING_HTML


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await _reject(update)
    state: ProjectState | None = ctx.user_data.pop("project", None)
    if state:
        state.cleanup()
    await update.message.reply_text("لغو شد.")
    return ConversationHandler.END


async def receive_html(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await _reject(update)

    msg = update.message
    doc = msg.document
    if not doc or not doc.file_name.lower().endswith((".html", ".htm")):
        await msg.reply_text("لطفاً یک فایل HTML ارسال کنید (به‌صورت Document).")
        return WAITING_HTML

    tg_file = await doc.get_file()
    html_bytes = bytes(await tg_file.download_as_bytearray())

    soup, resources = extract_resources(html_bytes)
    metadata = extract_metadata(html_bytes)

    state = ProjectState(html_bytes, resources, metadata)
    ctx.user_data["project"] = state

    if not resources:
        head = _progress_header(state)
        await msg.reply_text(head + "منبع محلی‌ای پیدا نشد. در حال آپلود فایل HTML...")
        return await finalize(update, ctx, state, soup)

    head = _progress_header(state)
    list_lines = [head + f"📋 <b>{state.total}</b> فایل مورد نیاز است:\n"]
    for i, r in enumerate(resources, 1):
        icon = "🖼" if r["tag"] == "img" else "📱"
        list_lines.append(f"{i}. {icon} <code>{r['path']}</code>")
    list_lines.append("")
    list_lines.append("<i>حالا یکی‌یکی از شما می‌پرسم.</i>")
    await msg.reply_text("\n".join(list_lines), parse_mode="HTML")

    await _ask_next_file(msg, state)
    return WAITING_FILES


async def receive_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await _reject(update)

    state: ProjectState | None = ctx.user_data.get("project")
    if not state:
        await update.message.reply_text("ابتدا یک فایل HTML بفرستید یا /cancel بزنید.")
        return WAITING_HTML

    msg = update.message
    nxt = state.next_pending()
    if not nxt:
        await msg.reply_text("همه فایل‌ها دریافت شد. در حال آپلود...")
        soup, _ = extract_resources(state.html_bytes)
        return await finalize(update, ctx, state, soup)

    original_name = ""
    tg_file = None
    file_size = 0

    if msg.document:
        original_name = msg.document.file_name or "document"
        file_size = msg.document.file_size or 0
        tg_file = await msg.document.get_file()
    elif msg.photo:
        photo = msg.photo[-1]
        original_name = f"photo_{photo.file_unique_id}.jpg"
        file_size = photo.file_size or 0
        tg_file = await photo.get_file()
    else:
        icon = "🖼" if _is_image_path(nxt) else "📱"
        await msg.reply_text(
            f"⚠️ لطفاً فایل را به‌صورت <b>Document</b> یا <b>Photo</b> بفرستید.\n\n"
            f"📥 منتظر این هستم: {icon} <code>{nxt}</code>",
            parse_mode="HTML",
        )
        return WAITING_FILES

    if file_size and file_size > MAX_FILE_SIZE:
        await msg.reply_text("❌ حجم فایل بیشتر از ۲۰ مگابایت است.")
        return WAITING_FILES

    local = state.tmp_dir / nxt
    local.parent.mkdir(parents=True, exist_ok=True)
    await tg_file.download_to_drive(local)

    state.pending.pop(0)
    state.uploaded[nxt] = local

    if original_name.lower() != os.path.basename(nxt).lower():
        detail = (
            f"📥 دریافت: <code>{original_name}</code>\n"
            f"💾 ذخیره شد به: <code>{nxt}</code>"
        )
    else:
        detail = f"✅ دریافت شد: <code>{nxt}</code>"

    await msg.reply_text(
        f"{detail}\n📦 پیشرفت: ({state.done_count}/{state.total})",
        parse_mode="HTML",
    )

    if state.pending:
        await _ask_next_file(msg, state)
        return WAITING_FILES

    soup, _ = extract_resources(state.html_bytes)
    return await finalize(update, ctx, state, soup)


async def hint_html_state(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await _reject(update)
    await update.message.reply_text(
        "📄 لطفاً فایل HTML را به‌صورت <b>Document</b> بفرستید.\nلغو: /cancel",
        parse_mode="HTML",
    )
    return WAITING_HTML


async def hint_files_state(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await _reject(update)
    state: ProjectState | None = ctx.user_data.get("project")
    nxt = state.next_pending() if state else "?"
    await update.message.reply_text(
        f"📥 لطفاً فایل بعدی را بفرستید: <code>{nxt}</code>\n"
        f"<i>Document یا Photo قبول است.</i>\nلغو: /cancel",
        parse_mode="HTML",
    )
    return WAITING_FILES


async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await _reject(update)
    state: ProjectState | None = ctx.user_data.get("project")
    if not state:
        await update.message.reply_text("پروژه‌ای فعال نیست.")
        return ConversationHandler.END

    if state.pending:
        await update.message.reply_text(
            f"❌ هنوز <b>{len(state.pending)}</b> فایل باقی مانده.\n"
            f"لطفاً فایل بعدی: <code>{state.next_pending()}</code>",
            parse_mode="HTML",
        )
        return WAITING_FILES

    soup, _ = extract_resources(state.html_bytes)
    return await finalize(update, ctx, state, soup)


async def finalize(update, ctx, state: ProjectState, soup):
    msg = await update.message.reply_text("⏳ در حال تبدیل تصاویر و آپلود به cPanel...")

    client = CPanelClient(
        CPANEL_HOST, CPANEL_PORT, CPANEL_USER, CPANEL_TOKEN,
        verify_ssl=CPANEL_VERIFY_SSL,
    )

    try:
        # ۱) گرفتن شماره پروژه از شمارنده روی هاست
        project_num = await client.get_next_project_number(COUNTER_FILE_PATH)
        state.project_id = str(project_num)

        path_map = convert_images_to_webp(state)
        converted = len(path_map)

        # ۲) ساخت پوشه پروژه /public_html/N
        project_dir = f"{CPANEL_BASE_PATH}/{state.project_id}"
        log.info(f"Creating dir: {project_dir}")
        await client.ensure_dir(project_dir)

        # ۳) آپلود منابع
        for path_str, local in state.uploaded.items():
            rel_dir = os.path.dirname(path_str)
            filename = os.path.basename(path_str)
            remote_dir = f"{project_dir}/{rel_dir}" if rel_dir else project_dir
            if rel_dir:
                await client.ensure_dir(remote_dir)
            log.info(f"Upload: {remote_dir}/{filename}")
            await client.upload_file(remote_dir, filename, local.read_bytes())

        # ۴) بازنویسی HTML و آپلود index.html
        new_html = rewrite_paths(soup, state.resources, path_map,
                                 PUBLIC_BASE_URL, state.project_id)
        log.info(f"Upload index.html to {project_dir}")
        await client.upload_file(project_dir, "index.html", new_html)

    except Exception as e:
        log.exception("Upload failed")
        await msg.edit_text(f"❌ خطا در آپلود:\n<code>{e}</code>", parse_mode="HTML")
        state.cleanup()
        ctx.user_data.pop("project", None)
        return ConversationHandler.END

    # لینک نهایی: https://link.webiksahostfast.site/N/index.html
    public_url = f"{PUBLIC_BASE_URL}/{state.project_id}/index.html"
    short_url  = f"{PUBLIC_BASE_URL}/{state.project_id}"

    title = state.metadata.get("TITLE", "")
    title_line = f"📌 <b>{title}</b>\n\n" if title else ""
    convert_line = f"🖼 {converted} تصویر به WebP تبدیل شد\n" if converted else ""
    await msg.edit_text(
        f"✅ پروژه با موفقیت منتشر شد!\n\n"
        f"{title_line}{convert_line}"
        f"🔗 <a href='{public_url}'>{short_url}</a>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    state.cleanup()
    ctx.user_data.pop("project", None)
    return ConversationHandler.END


# ==============================================================
# 🚨 Error handler
# ==============================================================

async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("Exception while handling update:", exc_info=ctx.error)
    if ctx.error and "Conflict" in str(ctx.error):
        log.error("⚠️ دو نسخه از ربات همزمان اجرا شده‌اند! یکی را ببندید.")
        return
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ خطای داخلی رخ داد. دوباره تلاش کنید یا /cancel بزنید."
            )
        except Exception:
            pass


# ==============================================================
# 🚀 اجرا
# ==============================================================

def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .build()
    )

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            MessageHandler(filter_html_doc, receive_html),
        ],
        states={
            WAITING_HTML: [
                MessageHandler(filter_html_doc, receive_html),
                MessageHandler(filters.Document.ALL, hint_html_state),
                MessageHandler(filters.PHOTO, hint_html_state),
                MessageHandler(filters.TEXT & ~filters.COMMAND, hint_html_state),
            ],
            WAITING_FILES: [
                MessageHandler(filters.Document.ALL | filters.PHOTO, receive_file),
                MessageHandler(
                    ~filters.COMMAND & ~filters.Document.ALL & ~filters.PHOTO,
                    hint_files_state,
                ),
                CommandHandler("done", cmd_done),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=False,
    )
    app.add_handler(conv)
    app.add_error_handler(error_handler)

    log.info(f"Bot is running... (allowed user: {ALLOWED_USER_ID})")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        bootstrap_retries=5,
    )


if __name__ == "__main__":
    main()