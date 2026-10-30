#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات تلگرام آپلود HTML + لینک کوتاه (نسخه 6.0)
==============================================
- همه چیز در یک فایل — تنظیمات در دیکشنری CONFIG
- /reload → بارگذاری مجدد تنظیمات از همین فایل (بدون restart)
- /settings → نمایش تنظیمات فعلی (کلیدها مخفی)
- /projects → لیست پروژه‌ها
- /stats <slug> → آمار پروژه

پیش‌نیازها:
    pip install python-telegram-bot==21.6 httpx==0.27.2 \\
                beautifulsoup4==4.12.3 Pillow==10.4.0
"""

import ast
import json
import logging
import os
import re
import shutil
import tempfile
import warnings
from datetime import datetime
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
# 🎛 تنظیمات — این بخش را ویرایش کنید
# ==============================================================
# بعد از تغییر، در تلگرام /reload بزنید (بدون restart اعمال می‌شود)

CONFIG = {
    # ---------- تلگرام ----------
    "bot_token": "8921325744:AAFXRJVzWotsUiZ9yslVpc7NevS2c-8DNnQ",
    "allowed_user_ids": [8389746549],   # لیست آیدی‌های مجاز

    # ---------- cPanel ----------
    "cpanel": {
        "host": "webiksahostfast.site",
        "port": "2083",
        "user": "vaacyvb",
        "token": "BEWG8JLUYJWMO30IT14S0TNNFPYMRA6D",
        "verify_ssl": False,
        "base_path": "/public_html",
        "public_base_url": "https://link.webiksahostfast.site",
        "counter_file": "/public_html/.counter.txt",
        "projects_file": "/public_html/.projects.json",
    },

    # ---------- کوتاه‌کننده لینک ----------
    "shortener": {
        "enabled": True,
        "base": "https://nxal.ir",
        "api_key": "nxal_haGkNEVXprw2GCUzNjeP1gh2jUIwqepxPBbKfsuS",
        "slug_prefix": "",     # مثلاً "p-" تا slugها یکتا شوند
    },

    # ---------- آپلود ----------
    "upload": {
        "max_file_size_mb": 20,
        "webp_quality": 82,
    },
}
# ==============================================================


# ==============================================================
# 🔄 بارگذاری تنظیمات از همین فایل (برای /reload)
# ==============================================================

def reload_config_from_file() -> dict:
    """بلوک CONFIG را از فایل منبع همین ماژول دوباره می‌خواند."""
    global CONFIG
    src = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "CONFIG":
                    new_cfg = ast.literal_eval(node.value)
                    # اعتبارسنجی
                    _validate_config(new_cfg)
                    CONFIG = new_cfg
                    return new_cfg
    raise RuntimeError("بلوک CONFIG در فایل پیدا نشد")


def _validate_config(cfg: dict):
    if not cfg.get("bot_token"):
        raise RuntimeError("bot_token خالی است")
    if not isinstance(cfg.get("allowed_user_ids"), list) or not cfg["allowed_user_ids"]:
        raise RuntimeError("allowed_user_ids باید لیست غیرخالی باشد")
    c = cfg.get("cpanel", {})
    for k in ("host", "user", "token", "public_base_url"):
        if not c.get(k):
            raise RuntimeError(f"cpanel.{k} خالی است")


_validate_config(CONFIG)


# ==============================================================
# 📦 logging / parser / Pillow
# ==============================================================

warnings.filterwarnings("ignore", message="Unverified HTTPS request")
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

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

CONVERTIBLE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif"}
log.info(f"HTML parser: {HTML_PARSER} | Pillow: {'yes' if PIL_AVAILABLE else 'no'}")


# ==============================================================
# 🔒 دسترسی
# ==============================================================

def is_allowed(update: Update) -> bool:
    return bool(
        update.effective_user
        and update.effective_user.id in CONFIG["allowed_user_ids"]
    )


async def _reject(update: Update):
    await update.effective_message.reply_text("⛔ دسترسی ندارید.")


# ==============================================================
# 🔍 فیلتر HTML
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
# 🔗 کلاینت کوتاه‌کننده
# ==============================================================

class NxalClient:
    def __init__(self):
        s = CONFIG["shortener"]
        self.enabled = bool(s.get("enabled"))
        self.base = (s.get("base") or "").rstrip("/")
        self.headers = {
            "X-Api-Key": s.get("api_key", ""),
            "Content-Type": "application/json",
        }
        self.slug_prefix = s.get("slug_prefix", "")

    async def shorten(self, url: str, slug: str | None = None) -> dict:
        if not self.enabled:
            raise RuntimeError("shortener غیرفعال است")
        if slug and self.slug_prefix:
            slug = f"{self.slug_prefix}{slug}"
        payload = {"url": url}
        if slug:
            payload["slug"] = slug
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{self.base}/api/v1/shorten",
                headers=self.headers,
                json=payload,
            )
            data = r.json()
            if not data.get("success"):
                raise RuntimeError(f"shortener failed: {data}")
            return data["data"]

    async def get_stats(self, link_id: str, days: int = 30) -> dict:
        if not self.enabled:
            raise RuntimeError("shortener غیرفعال است")
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"{self.base}/api/v1/links/{link_id}/stats",
                headers=self.headers,
                params={"days": days},
            )
            data = r.json()
            if not data.get("success"):
                raise RuntimeError(f"stats failed: {data}")
            return data["data"]


# ==============================================================
# ☁️ کلاینت cPanel
# ==============================================================

class CPanelClient:
    def __init__(self):
        c = CONFIG["cpanel"]
        self.host = c["host"]
        self.port = c["port"]
        self.user = c["user"]
        self.token = c["token"]
        self.verify = c["verify_ssl"]
        self.base = f"https://{self.host}:{self.port}/execute"
        self.headers = {"Authorization": f"cpanel {self.user}:{self.token}"}

    def _client(self, timeout):
        return httpx.AsyncClient(verify=self.verify, timeout=timeout)

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

    async def ensure_dir(self, full_path: str):
        parts = [p for p in full_path.split("/") if p]
        current = ""
        for part in parts:
            parent = current or "/"
            current = f"{current}/{part}"
            if await self._dir_exists(current):
                continue
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

    async def get_next_project_number(self) -> int:
        counter = CONFIG["cpanel"]["counter_file"]
        current = 0
        content = await self.read_file(counter)
        if content:
            try:
                current = int(content.strip())
            except ValueError:
                current = 0
        new_num = current + 1
        d = os.path.dirname(counter) or "/"
        n = os.path.basename(counter)
        await self.upload_file(d, n, str(new_num).encode("utf-8"))
        return new_num


# ==============================================================
# 📚 لیست پروژه‌ها
# ==============================================================

async def load_projects(client: CPanelClient) -> list[dict]:
    content = await client.read_file(CONFIG["cpanel"]["projects_file"])
    if not content:
        return []
    try:
        return json.loads(content)
    except Exception:
        return []


async def save_projects(client: CPanelClient, projects: list[dict]):
    data = json.dumps(projects, ensure_ascii=False, indent=2).encode("utf-8")
    p = CONFIG["cpanel"]["projects_file"]
    await client.upload_file(os.path.dirname(p) or "/", os.path.basename(p), data)


# ==============================================================
# 🧩 پارسر HTML
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
        k, _, v = line.partition(":")
        k, v = k.strip().upper(), v.strip()
        if k and v:
            meta[k] = v
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


def rewrite_paths(soup, resources, path_map, public_base, project_id) -> bytes:
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
# 🖼 WebP
# ==============================================================

def convert_images_to_webp(state) -> dict:
    if not PIL_AVAILABLE:
        return {}
    quality = int(CONFIG["upload"].get("webp_quality", 82))
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
            with Image.open(local_old) as im:
                kw = {"quality": quality, "method": 4}
                if getattr(im, "is_animated", False):
                    kw["save_all"] = True
                im.save(local_new, "WEBP", **kw)
            state.uploaded.pop(old_path, None)
            state.uploaded[new_path] = local_new
            path_map[old_path] = new_path
        except Exception as e:
            log.warning(f"webp conversion failed for {old_path}: {e}")
    return path_map


# ==============================================================
# 🗂 وضعیت
# ==============================================================

class ProjectState:
    def __init__(self, html_bytes, resources, metadata):
        self.html_bytes = html_bytes
        self.resources = resources
        self.metadata = metadata
        self.pending = [r["path"] for r in resources]
        self.uploaded: dict[str, Path] = {}
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="proj_"))
        self.total = len(resources)
        self.project_id: str | None = None

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
        "منابع را یکی‌یکی می‌پرسم، تصاویر به WebP تبدیل می‌شوند،\n"
        "و در پایان یک <b>لینک کوتاه</b> می‌گیرید.\n\n"
        "📋 دستورات:\n"
        "/projects — لیست پروژه‌ها\n"
        "/stats &lt;slug&gt; — آمار یک پروژه\n"
        "/settings — نمایش تنظیمات\n"
        "/reload — بارگذاری مجدد تنظیمات\n"
        "/cancel — لغو",
        parse_mode="HTML",
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
        await msg.reply_text(head + "منبع محلی‌ای پیدا نشد. در حال آپلود...")
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
            f"📥 منتظر: {icon} <code>{nxt}</code>",
            parse_mode="HTML",
        )
        return WAITING_FILES

    max_mb = int(CONFIG["upload"].get("max_file_size_mb", 20))
    if file_size and file_size > max_mb * 1024 * 1024:
        await msg.reply_text(f"❌ حجم فایل بیشتر از {max_mb} مگابایت است.")
        return WAITING_FILES

    local = state.tmp_dir / nxt
    local.parent.mkdir(parents=True, exist_ok=True)
    await tg_file.download_to_drive(local)

    state.pending.pop(0)
    state.uploaded[nxt] = local

    if original_name.lower() != os.path.basename(nxt).lower():
        detail = (
            f"📥 دریافت: <code>{original_name}</code>\n"
            f"💾 ذخیره به: <code>{nxt}</code>"
        )
    else:
        detail = f"✅ دریافت: <code>{nxt}</code>"

    await msg.reply_text(
        f"{detail}\n📦 ({state.done_count}/{state.total})",
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
        f"📥 لطفاً فایل بعدی: <code>{nxt}</code>\nلغو: /cancel",
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
            f"❌ هنوز <b>{len(state.pending)}</b> فایل مانده.\n"
            f"لطفاً: <code>{state.next_pending()}</code>",
            parse_mode="HTML",
        )
        return WAITING_FILES

    soup, _ = extract_resources(state.html_bytes)
    return await finalize(update, ctx, state, soup)


# ==============================================================
# 🚀 finalize
# ==============================================================

async def finalize(update, ctx, state: ProjectState, soup):
    msg = await update.message.reply_text("⏳ در حال آپلود به cPanel و ساخت لینک کوتاه...")

    cpanel = CPanelClient()
    nxal = NxalClient()

    try:
        project_num = await cpanel.get_next_project_number()
        state.project_id = str(project_num)

        path_map = convert_images_to_webp(state)
        converted = len(path_map)

        project_dir = f"{CONFIG['cpanel']['base_path']}/{state.project_id}"
        await cpanel.ensure_dir(project_dir)

        for path_str, local in state.uploaded.items():
            rel_dir = os.path.dirname(path_str)
            filename = os.path.basename(path_str)
            remote_dir = f"{project_dir}/{rel_dir}" if rel_dir else project_dir
            if rel_dir:
                await cpanel.ensure_dir(remote_dir)
            await cpanel.upload_file(remote_dir, filename, local.read_bytes())

        public_base = CONFIG["cpanel"]["public_base_url"].rstrip("/")
        new_html = rewrite_paths(soup, state.resources, path_map,
                                 public_base, state.project_id)
        await cpanel.upload_file(project_dir, "index.html", new_html)

        real_url = f"{public_base}/{state.project_id}/index.html"

        short_data = {}
        try:
            short_data = await nxal.shorten(real_url, slug=state.project_id)
        except Exception as e:
            log.warning(f"shorten failed: {e}")

        projects = await load_projects(cpanel)
        projects.append({
            "id": state.project_id,
            "title": state.metadata.get("TITLE", ""),
            "description": state.metadata.get("DESCRIPTION", ""),
            "version": state.metadata.get("VERSION", ""),
            "real_url": real_url,
            "short_url": short_data.get("shortUrl", ""),
            "short_id": short_data.get("id", ""),
            "slug": short_data.get("slug", ""),
            "created_at": datetime.utcnow().isoformat() + "Z",
        })
        await save_projects(cpanel, projects)

    except Exception as e:
        log.exception("Upload failed")
        await msg.edit_text(f"❌ خطا:\n<code>{e}</code>", parse_mode="HTML")
        state.cleanup()
        ctx.user_data.pop("project", None)
        return ConversationHandler.END

    title = state.metadata.get("TITLE", "")
    title_line = f"📌 <b>{title}</b>\n\n" if title else ""
    convert_line = f"🖼 {converted} تصویر به WebP تبدیل شد\n" if converted else ""

    short_url = short_data.get("shortUrl", "")
    short_line = (
        f"🔗 کوتاه: <a href='{short_url}'>{short_url}</a>\n"
        if short_url else "⚠️ لینک کوتاه ساخته نشد\n"
    )

    await msg.edit_text(
        f"✅ پروژه منتشر شد!\n\n"
        f"{title_line}{convert_line}{short_line}"
        f"🌐 اصلی: <a href='{real_url}'>{real_url}</a>\n\n"
        f"📊 آمار: /stats {short_data.get('slug', state.project_id)}",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    state.cleanup()
    ctx.user_data.pop("project", None)
    return ConversationHandler.END


# ==============================================================
# 📋 /projects
# ==============================================================

async def cmd_projects(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await _reject(update)

    cpanel = CPanelClient()
    try:
        projects = await load_projects(cpanel)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا:\n<code>{e}</code>", parse_mode="HTML")
        return

    if not projects:
        await update.message.reply_text("📭 هنوز پروژه‌ای ساخته نشده.")
        return

    recent = list(reversed(projects))[:20]
    lines = [f"📋 <b>{len(projects)} پروژه</b> (نمایش ۲۰ مورد آخر)\n"]
    for p in recent:
        title = p.get("title") or f"پروژه {p['id']}"
        short = p.get("short_url", "")
        real = p.get("real_url", "")
        line = f"\n<b>#{p['id']}</b> — {title}"
        if short:
            line += f"\n   🔗 <a href='{short}'>{short}</a>"
        if real and real != short:
            line += f"\n   🌐 <a href='{real}'>صفحه اصلی</a>"
        line += f"\n   📊 /stats {p.get('slug') or p['id']}"
        lines.append(line)

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n\n<i>...</i>"

    await update.message.reply_text(
        text, parse_mode="HTML", disable_web_page_preview=True,
    )


# ==============================================================
# 📊 /stats
# ==============================================================

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await _reject(update)

    if not ctx.args:
        await update.message.reply_text(
            "📊 استفاده: <code>/stats &lt;slug&gt;</code>\n"
            "مثال: <code>/stats 1</code>\n"
            "برای لیست: /projects",
            parse_mode="HTML",
        )
        return

    slug = ctx.args[0].strip()
    cpanel = CPanelClient()
    try:
        projects = await load_projects(cpanel)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}")
        return

    project = None
    for p in projects:
        if p.get("slug") == slug or p.get("id") == slug:
            project = p
            break

    if not project:
        await update.message.reply_text(f"❌ پروژه‌ای با «{slug}» پیدا نشد.")
        return

    short_id = project.get("short_id", "")
    if not short_id:
        await update.message.reply_text("❌ این پروژه لینک کوتاه ندارد.")
        return

    nxal = NxalClient()
    try:
        stats = await nxal.get_stats(short_id, days=30)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا:\n<code>{e}</code>", parse_mode="HTML")
        return

    title = project.get("title") or f"پروژه {project['id']}"
    short_url = project.get("short_url", "")
    real_url  = project.get("real_url", "")
    total = stats.get("totalClicks", 0)
    unique = stats.get("uniqueClicks", 0)

    def top_list(key, limit=5):
        items = stats.get(key, [])[:limit]
        if not items:
            return "   —"
        return "\n".join(f"   • {i['name']}: {i['count']}" for i in items)

    text = (
        f"📊 <b>آمار «{title}»</b>\n\n"
        f"🔗 <a href='{short_url}'>{short_url}</a>\n"
        f"🌐 <a href='{real_url}'>صفحه اصلی</a>\n\n"
        f"👁 کلیک: <b>{total}</b>   |   👤 یکتا: <b>{unique}</b>\n\n"
        f"🌍 کشورها:\n{top_list('byCountry')}\n\n"
        f"📱 دستگاه‌ها:\n{top_list('byDevice')}\n\n"
        f"🌐 مرورگرها:\n{top_list('byBrowser')}\n\n"
        f"💻 سیستم‌عامل:\n{top_list('byOs')}\n\n"
        f"🔗 منابع ورود:\n{top_list('byReferer')}"
    )
    if len(text) > 4000:
        text = text[:4000] + "\n\n<i>...</i>"

    await update.message.reply_text(
        text, parse_mode="HTML", disable_web_page_preview=True,
    )


# ==============================================================
# ⚙️ /settings — نمایش تنظیمات فعلی
# ==============================================================

def _mask(s: str) -> str:
    if not s:
        return "—"
    return s[:6] + "…" + s[-4:] if len(s) > 12 else "…"


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await _reject(update)

    c = CONFIG["cpanel"]
    s = CONFIG["shortener"]
    u = CONFIG["upload"]
    users = ", ".join(str(x) for x in CONFIG["allowed_user_ids"])

    text = (
        "⚙️ <b>تنظیمات فعلی</b>\n\n"
        f"<b>تلگرام</b>\n"
        f"  bot_token: <code>{_mask(CONFIG['bot_token'])}</code>\n"
        f"  allowed: <code>{users}</code>\n\n"
        f"<b>cPanel</b>\n"
        f"  host: <code>{c['host']}:{c['port']}</code>\n"
        f"  user: <code>{c['user']}</code>\n"
        f"  token: <code>{_mask(c['token'])}</code>\n"
        f"  ssl verify: <code>{c['verify_ssl']}</code>\n"
        f"  base_path: <code>{c['base_path']}</code>\n"
        f"  public_url: <code>{c['public_base_url']}</code>\n\n"
        f"<b>کوتاه‌کننده</b>\n"
        f"  enabled: <code>{s['enabled']}</code>\n"
        f"  base: <code>{s['base']}</code>\n"
        f"  api_key: <code>{_mask(s['api_key'])}</code>\n"
        f"  slug_prefix: <code>{s.get('slug_prefix') or '—'}</code>\n\n"
        f"<b>آپلود</b>\n"
        f"  max_mb: <code>{u['max_file_size_mb']}</code>\n"
        f"  webp_quality: <code>{u['webp_quality']}</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ==============================================================
# 🔄 /reload — بارگذاری مجدد تنظیمات از فایل
# ==============================================================

async def cmd_reload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await _reject(update)
    try:
        reload_config_from_file()
        await update.message.reply_text(
            "✅ تنظیمات با موفقیت بارگذاری شد.\n"
            "⚠️ تغییر <b>bot_token</b> نیاز به ری‌استارت کامل دارد.\n"
            "سایر تغییرات همین حالا اعمال شدند.",
            parse_mode="HTML",
        )
        log.info("Config reloaded from file")
    except Exception as e:
        await update.message.reply_text(
            f"❌ خطا در بارگذاری:\n<code>{e}</code>",
            parse_mode="HTML",
        )


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
        .token(CONFIG["bot_token"])
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

    app.add_handler(CommandHandler("projects", cmd_projects))
    app.add_handler(CommandHandler("stats",    cmd_stats))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("reload",   cmd_reload))

    app.add_error_handler(error_handler)

    log.info(f"Bot is running... (allowed: {CONFIG['allowed_user_ids']})")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        bootstrap_retries=5,
    )


if __name__ == "__main__":
    main()