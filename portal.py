#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portal bot (V6.1) — button-based UI, mergeable into main app
"""
import ast, json, logging, os, re, shutil, tempfile, warnings
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, unquote

import httpx
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters,
)

CONFIG = {
    "bot_token": "8921325744:AAFXRJVzWotsUiZ9yslVpc7NevS2c-8DNnQ",
    "allowed_user_ids": [8389746549],
    "cpanel": {
        "host": "webiksahostfast.site", "port": "2083",
        "user": "vaacyvb", "token": "BEWG8JLUYJWMO30IT14S0TNNFPYMRA6D",
        "verify_ssl": False, "base_path": "/public_html",
        "public_base_url": "https://link.webiksahostfast.site",
        "counter_file": "/public_html/.counter.txt",
        "projects_file": "/public_html/.projects.json",
    },
    "shortener": {
        "enabled": True, "base": "https://nxal.ir",
        "api_key": "nxal_haGkNEVXprw2GCUzNjeP1gh2jUIwqepxPBbKfsuS",
        "slug_prefix": "",
    },
    "upload": {"max_file_size_mb": 20, "webp_quality": 82},
}

warnings.filterwarnings("ignore", message="Unverified HTTPS request")
log = logging.getLogger("portal")

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


# ═══════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════
def is_allowed(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id in CONFIG["allowed_user_ids"])


def _mask(s: str) -> str:
    if not s: return "—"
    return s[:6] + "…" + s[-4:] if len(s) > 12 else "…"


def _is_external(url: str) -> bool:
    return url.lower().startswith(("http://", "https://", "//", "data:", "#", "javascript:", "mailto:"))


def _clean(url: str) -> str:
    p = urlparse(url).path
    p = unquote(p).replace("\\", "/").lstrip("/")
    while p.startswith("./"): p = p[2:]
    return p


def reload_config_from_file():
    global CONFIG
    src = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "CONFIG":
                    CONFIG = ast.literal_eval(node.value)
                    return


# ═══════════════════════════════════════════════════════════
# cPanel
# ═══════════════════════════════════════════════════════════
class CPanelClient:
    def __init__(self):
        c = CONFIG["cpanel"]
        self.host, self.port = c["host"], c["port"]
        self.user, self.token = c["user"], c["token"]
        self.verify = c["verify_ssl"]
        self.base = f"https://{self.host}:{self.port}/execute"
        self.headers = {"Authorization": f"cpanel {self.user}:{self.token}"}

    def _client(self, t):
        return httpx.AsyncClient(verify=self.verify, timeout=t)

    async def _dir_exists(self, p):
        try:
            async with self._client(30) as c:
                r = await c.get(f"{self.base}/Fileman/list_files", headers=self.headers,
                                params={"path": p, "types": "dir"})
                return r.json().get("status") == 1
        except Exception: return False

    async def _api2(self, mod, fn, **params):
        url = f"https://{self.host}:{self.port}/json-api/cpanel"
        payload = {"cpanel_jsonapi_user": self.user, "cpanel_jsonapi_apiversion": "2",
                   "cpanel_jsonapi_module": mod, "cpanel_jsonapi_func": fn, **params}
        async with self._client(30) as c:
            r = await c.get(url, headers=self.headers, params=payload)
            data = r.json()
            res = data.get("cpanelresult", {})
            if res.get("error"):
                raise RuntimeError(f"API2 {mod}/{fn}: {data}")
            return data

    async def ensure_dir(self, full):
        cur = ""
        for part in [p for p in full.split("/") if p]:
            parent = cur or "/"
            cur = f"{cur}/{part}"
            if await self._dir_exists(cur): continue
            await self._api2("Fileman", "mkdir", path=parent, name=part)

    async def upload(self, rdir, fname, content):
        async with self._client(300) as c:
            r = await c.post(f"{self.base}/Fileman/upload_files", headers=self.headers,
                             data={"dir": rdir}, files={"file-1": (fname, content)})
            data = r.json()
            if data.get("status") != 1:
                raise RuntimeError(f"Upload failed: {data}")

    async def read(self, full):
        try:
            async with self._client(30) as c:
                r = await c.get(f"{self.base}/Fileman/get_file_content",
                                headers=self.headers, params={"path": full})
                d = r.json()
                return d.get("data", {}).get("content") if d.get("status") == 1 else None
        except Exception: return None

    async def next_project_num(self):
        counter = CONFIG["cpanel"]["counter_file"]
        cur = 0
        content = await self.read(counter)
        if content:
            try: cur = int(content.strip())
            except ValueError: cur = 0
        new = cur + 1
        await self.upload(os.path.dirname(counter) or "/",
                         os.path.basename(counter), str(new).encode())
        return new


# ═══════════════════════════════════════════════════════════
# Shortener
# ═══════════════════════════════════════════════════════════
class NxalClient:
    def __init__(self):
        s = CONFIG["shortener"]
        self.enabled = bool(s.get("enabled"))
        self.base = (s.get("base") or "").rstrip("/")
        self.headers = {"X-Api-Key": s.get("api_key", ""), "Content-Type": "application/json"}
        self.prefix = s.get("slug_prefix", "")

    async def shorten(self, url, slug=None):
        if not self.enabled: raise RuntimeError("disabled")
        if slug and self.prefix: slug = f"{self.prefix}{slug}"
        payload = {"url": url}
        if slug: payload["slug"] = slug
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self.base}/api/v1/shorten", headers=self.headers, json=payload)
            data = r.json()
            if not data.get("success"): raise RuntimeError(f"shorten failed: {data}")
            return data["data"]

    async def stats(self, link_id, days=30):
        if not self.enabled: raise RuntimeError("disabled")
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self.base}/api/v1/links/{link_id}/stats",
                            headers=self.headers, params={"days": days})
            data = r.json()
            if not data.get("success"): raise RuntimeError(f"stats failed: {data}")
            return data["data"]


# ═══════════════════════════════════════════════════════════
# Storage
# ═══════════════════════════════════════════════════════════
async def load_projects(client):
    content = await client.read(CONFIG["cpanel"]["projects_file"])
    if not content: return []
    try:
        d = json.loads(content)
        return d if isinstance(d, list) else []
    except Exception: return []


async def save_projects(client, projects):
    data = json.dumps(projects, ensure_ascii=False, indent=2).encode()
    p = CONFIG["cpanel"]["projects_file"]
    await client.upload(os.path.dirname(p) or "/", os.path.basename(p), data)


# ═══════════════════════════════════════════════════════════
# HTML parsing
# ═══════════════════════════════════════════════════════════
META_RE = re.compile(r"<!--\s*CPANELBOT\s*(.*?)-->", re.DOTALL | re.IGNORECASE)


def extract_metadata(html_bytes):
    text = html_bytes.decode("utf-8", errors="ignore")
    m = META_RE.search(text)
    if not m: return {}
    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or ":" not in line: continue
        k, _, v = line.partition(":")
        if k.strip() and v.strip(): meta[k.strip().upper()] = v.strip()
    return meta


def extract_resources(html_bytes):
    soup = BeautifulSoup(html_bytes, HTML_PARSER)
    resources, seen = [], set()
    for img in soup.find_all("img"):
        src = img.get("src")
        if src and not _is_external(src):
            p = _clean(src)
            if p and p not in seen:
                seen.add(p); resources.append({"path": p, "tag": "img", "attr": "src"})
    for a in soup.find_all("a"):
        href = a.get("href")
        if not href or _is_external(href): continue
        if href.lower().split("?")[0].endswith(".apk"):
            p = _clean(href)
            if p and p not in seen:
                seen.add(p); resources.append({"path": p, "tag": "a", "attr": "href"})
    return soup, resources


def rewrite_paths(soup, resources, path_map, base, pid):
    for r in resources:
        old = r["path"]; new = path_map.get(old, old)
        url = f"{base}/{pid}/{new}"
        for tag in soup.find_all(r["tag"]):
            cur = tag.get(r["attr"])
            if cur and _clean(cur) == old: tag[r["attr"]] = url
    return str(soup).encode()


def convert_webp(state):
    if not PIL_AVAILABLE: return {}
    q = int(CONFIG["upload"].get("webp_quality", 82))
    pmap = {}
    for r in state.resources:
        if r["tag"] != "img": continue
        old = r["path"]
        if os.path.splitext(old)[1].lower() not in CONVERTIBLE_EXTS: continue
        local_old = state.uploaded.get(old)
        if not local_old or not local_old.exists(): continue
        new = os.path.splitext(old)[0] + ".webp"
        local_new = state.tmp_dir / new
        local_new.parent.mkdir(parents=True, exist_ok=True)
        try:
            with Image.open(local_old) as im:
                kw = {"quality": q, "method": 4}
                if getattr(im, "is_animated", False): kw["save_all"] = True
                im.save(local_new, "WEBP", **kw)
            state.uploaded.pop(old, None); state.uploaded[new] = local_new
            pmap[old] = new
        except Exception as e: log.warning(f"webp: {e}")
    return pmap


# ═══════════════════════════════════════════════════════════
# State
# ═══════════════════════════════════════════════════════════
class ProjectState:
    def __init__(self, html, resources, metadata):
        self.html_bytes = html
        self.resources = resources
        self.metadata = metadata
        self.pending = [r["path"] for r in resources]
        self.uploaded = {}
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="proj_"))
        self.total = len(resources)
        self.project_id = None

    @property
    def done_count(self): return self.total - len(self.pending)
    def next_pending(self): return self.pending[0] if self.pending else None
    def cleanup(self): shutil.rmtree(self.tmp_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════
# UI - Main menu with buttons
# ═══════════════════════════════════════════════════════════
WAITING_HTML, WAITING_FILES = range(2)


def _menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 ساخت درگاه جدید", callback_data="portal:new")],
        [InlineKeyboardButton("📋 پروژه‌های من", callback_data="portal:projects:0")],
        [InlineKeyboardButton("📊 آمار", callback_data="portal:stats:list")],
        [InlineKeyboardButton("⚙️ تنظیمات", callback_data="portal:settings")],
    ])


async def cmd_start(update, ctx):
    if not is_allowed(update): return
    await update.message.reply_text(
        "🎯 <b>پنل درگاه‌سازی</b>\n\n"
        "لینکدونی HTML خود را به یک صفحه‌ی آنلاین تبدیل کن:\n"
        "آپلود HTML → تبدیل WebP → کوتاه‌سازی با nxal → انتشار",
        parse_mode="HTML", reply_markup=_menu_kb(),
    )


async def cb_menu(update, ctx):
    q = update.callback_query
    if not q or not is_allowed(update): return
    await q.answer()
    d = q.data
    if d == "portal:new":
        await q.edit_message_text(
            "📄 <b>ساخت درگاه جدید</b>\n\n"
            "فایل HTML را به‌صورت Document بفرست:\n"
            "<i>(لغو: /cancel)</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« لغو", callback_data="portal:back")]]),
        )
        return WAITING_HTML
    if d == "portal:back":
        await q.edit_message_text("🎯 <b>پنل درگاه‌سازی</b>", parse_mode="HTML", reply_markup=_menu_kb())
        return ConversationHandler.END
    if d.startswith("portal:projects:"):
        page = int(d.split(":")[-1])
        await _show_projects(q, page)
    if d == "portal:stats:list":
        await _show_stats_list(q)
    if d.startswith("portal:stats:view:"):
        await _show_stats(q, d.split(":")[-1])
    if d == "portal:settings":
        await _show_settings(q)


async def _show_projects(q, page=0, per=5):
    cpanel = CPanelClient()
    try: projects = await load_projects(cpanel)
    except Exception as e:
        await q.edit_message_text(f"❌ {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« بازگشت", callback_data="portal:back")]]))
        return
    if not projects:
        await q.edit_message_text("📭 هنوز پروژه‌ای نساختی",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« بازگشت", callback_data="portal:back")]]))
        return
    total = len(projects); pages = max(1, -(-total // per))
    page = max(0, min(page, pages - 1))
    rev = list(reversed(projects))
    chunk = rev[page * per:(page + 1) * per]
    txt = f"📋 <b>پروژه‌ها ({total})</b> — صفحه {page+1}/{pages}\n\n"
    rows = []
    for p in chunk:
        pid = p.get("id", "?"); title = p.get("title") or f"#{pid}"
        short = p.get("short_url", "")
        txt += f"<b>#{pid}</b> — {title}\n"
        if short: txt += f"  🔗 {short}\n"
        rows.append([InlineKeyboardButton(f"📊 {title[:25]}", callback_data=f"portal:stats:view:{pid}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("◀️", callback_data=f"portal:projects:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data="noop"))
    if page < pages-1: nav.append(InlineKeyboardButton("▶️", callback_data=f"portal:projects:{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("« بازگشت", callback_data="portal:back")])
    await q.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
                              disable_web_page_preview=True)


async def _show_stats_list(q):
    cpanel = CPanelClient()
    try: projects = await load_projects(cpanel)
    except Exception: projects = []
    if not projects:
        await q.edit_message_text("📭 پروژه‌ای نیست",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« بازگشت", callback_data="portal:back")]]))
        return
    rows = []
    for p in projects[-10:]:
        pid = p.get("id", "?")
        rows.append([InlineKeyboardButton(f"📊 #{pid} — {(p.get('title') or '?')[:20]}",
                                          callback_data=f"portal:stats:view:{pid}")])
    rows.append([InlineKeyboardButton("« بازگشت", callback_data="portal:back")])
    await q.edit_message_text("📊 یک پروژه انتخاب کن:", reply_markup=InlineKeyboardMarkup(rows))


async def _show_stats(q, pid):
    cpanel = CPanelClient()
    try: projects = await load_projects(cpanel)
    except Exception: projects = []
    project = next((p for p in projects if p.get("id") == pid), None)
    if not project:
        await q.edit_message_text("❌ پیدا نشد",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« بازگشت", callback_data="portal:stats:list")]]))
        return
    sid = project.get("short_id", "")
    if not sid:
        await q.edit_message_text("❌ این پروژه لینک کوتاه ندارد",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« بازگشت", callback_data="portal:stats:list")]]))
        return
    nx = NxalClient()
    try: stats = await nx.stats(sid, days=30)
    except Exception as e:
        await q.edit_message_text(f"❌ {e}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« بازگشت", callback_data="portal:stats:list")]]))
        return
    def top(k, n=5):
        items = stats.get(k, [])[:n]
        return "\n".join(f"  • {i['name']}: {i['count']}" for i in items) if items else "  —"
    txt = (f"📊 <b>{project.get('title') or pid}</b>\n\n"
           f"👁 کلیک: <b>{stats.get('totalClicks', 0)}</b>\n"
           f"👤 یکتا: <b>{stats.get('uniqueClicks', 0)}</b>\n\n"
           f"🌍 کشورها:\n{top('byCountry')}\n\n"
           f"📱 دستگاه‌ها:\n{top('byDevice')}\n\n"
           f"🌐 مرورگر:\n{top('byBrowser')}")
    await q.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("« بازگشت", callback_data="portal:stats:list")]]), disable_web_page_preview=True)


async def _show_settings(q):
    c = CONFIG["cpanel"]; s = CONFIG["shortener"]; u = CONFIG["upload"]
    users = ", ".join(str(x) for x in CONFIG["allowed_user_ids"])
    txt = (f"⚙️ <b>تنظیمات</b>\n\n"
           f"<b>Telegram</b>\n  token: <code>{_mask(CONFIG['bot_token'])}</code>\n"
           f"  allowed: <code>{users}</code>\n\n"
           f"<b>cPanel</b>\n  host: <code>{c['host']}:{c['port']}</code>\n"
           f"  user: <code>{c['user']}</code>\n  token: <code>{_mask(c['token'])}</code>\n"
           f"  public: <code>{c['public_base_url']}</code>\n\n"
           f"<b>Shortener</b>\n  enabled: <code>{s['enabled']}</code>\n"
           f"  base: <code>{s['base']}</code>\n  key: <code>{_mask(s['api_key'])}</code>\n\n"
           f"<b>Upload</b>\n  max_mb: <code>{u['max_file_size_mb']}</code>\n"
           f"  webp_q: <code>{u['webp_quality']}</code>")
    await q.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 reload از فایل", callback_data="portal:reload")],
        [InlineKeyboardButton("« بازگشت", callback_data="portal:back")],
    ]))


async def cmd_reload(update, ctx):
    if not is_allowed(update): return
    try:
        reload_config_from_file()
        await update.message.reply_text("✅ تنظیمات reload شد (token نیاز به restart دارد)")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


# ═══════════════════════════════════════════════════════════
# Conversation - file upload flow
# ═══════════════════════════════════════════════════════════
class FilterHTML(MessageHandler):
    pass


def _is_html_doc(msg):
    return bool(msg.document and msg.document.file_name
                and msg.document.file_name.lower().endswith((".html", ".htm")))


async def receive_html(update, ctx):
    if not is_allowed(update): return
    msg = update.message
    if not _is_html_doc(msg):
        await msg.reply_text("⚠️ فایل HTML به‌صورت Document بفرست")
        return WAITING_HTML
    f = await msg.document.get_file()
    html_bytes = bytes(await f.download_as_bytearray())
    soup, resources = extract_resources(html_bytes)
    metadata = extract_metadata(html_bytes)
    state = ProjectState(html_bytes, resources, metadata)
    ctx.user_data["project"] = state

    if not resources:
        await msg.reply_text("✅ HTML دریافت شد، آپلود می‌کنم...")
        return await _finalize(update, ctx, state, soup)

    icons = "".join("🖼" if r["tag"] == "img" else "📱" for r in resources[:10])
    await msg.reply_text(f"📋 {state.total} فایل لازم است\n{icons}\n\nشروع...")
    await _ask_next(msg, state)
    return WAITING_FILES


async def receive_file(update, ctx):
    if not is_allowed(update): return
    state = ctx.user_data.get("project")
    if not state:
        await update.message.reply_text("اول HTML بفرست یا /cancel")
        return WAITING_HTML
    msg = update.message
    nxt = state.next_pending()
    if not nxt:
        soup, _ = extract_resources(state.html_bytes)
        return await _finalize(update, ctx, state, soup)

    tg_file = None; size = 0; original = ""
    if msg.document:
        original = msg.document.file_name or "doc"; size = msg.document.file_size or 0
        tg_file = await msg.document.get_file()
    elif msg.photo:
        p = msg.photo[-1]; original = f"photo.jpg"; size = p.file_size or 0
        tg_file = await p.get_file()
    else:
        await msg.reply_text(f"📥 منتظر فایل: <code>{nxt}</code>", parse_mode="HTML")
        return WAITING_FILES

    max_mb = int(CONFIG["upload"].get("max_file_size_mb", 20))
    if size > max_mb * 1024 * 1024:
        await msg.reply_text(f"❌ بیش از {max_mb}MB")
        return WAITING_FILES

    local = state.tmp_dir / nxt
    local.parent.mkdir(parents=True, exist_ok=True)
    await tg_file.download_to_drive(local)
    state.pending.pop(0); state.uploaded[nxt] = local

    await msg.reply_text(f"✅ {state.done_count}/{state.total}", parse_mode="HTML")
    if state.pending:
        await _ask_next(msg, state)
        return WAITING_FILES
    soup, _ = extract_resources(state.html_bytes)
    return await _finalize(update, ctx, state, soup)


async def _ask_next(msg, state):
    nxt = state.next_pending()
    if not nxt: return
    idx = state.done_count + 1
    icon = "🖼" if os.path.splitext(nxt)[1].lower() in CONVERTIBLE_EXTS | {".webp", ".svg"} else "📱"
    await msg.reply_text(
        f"📥 <b>[{idx}/{state.total}]</b>\n{icon} <code>{nxt}</code>\n\n"
        f"<i>لغو: /cancel</i>",
        parse_mode="HTML")


async def cmd_cancel(update, ctx):
    if not is_allowed(update): return ConversationHandler.END
    state = ctx.user_data.pop("project", None)
    if state: state.cleanup()
    await update.message.reply_text("لغو شد", reply_markup=_menu_kb())
    return ConversationHandler.END


async def hint(update, ctx):
    if not is_allowed(update): return
    await update.message.reply_text("از دکمه‌ها استفاده کن")
    return WAITING_HTML if not ctx.user_data.get("project") else WAITING_FILES


async def _finalize(update, ctx, state, soup):
    msg = await update.message.reply_text("⏳ آپلود...")
    cpanel = CPanelClient()
    nx = NxalClient()
    try:
        pid = str(await cpanel.next_project_num())
        state.project_id = pid
        pmap = convert_webp(state)
        pdir = f"{CONFIG['cpanel']['base_path']}/{pid}"
        await cpanel.ensure_dir(pdir)
        for path_str, local in state.uploaded.items():
            rel = os.path.dirname(path_str); fn = os.path.basename(path_str)
            rdir = f"{pdir}/{rel}" if rel else pdir
            if rel: await cpanel.ensure_dir(rdir)
            await cpanel.upload(rdir, fn, local.read_bytes())
        base = CONFIG["cpanel"]["public_base_url"].rstrip("/")
        new_html = rewrite_paths(soup, state.resources, pmap, base, pid)
        await cpanel.upload(pdir, "index.html", new_html)
        real = f"{base}/{pid}/index.html"
        short = {}
        try: short = await nx.shorten(real, slug=pid)
        except Exception as e: log.warning(f"shorten: {e}")
        projects = await load_projects(cpanel)
        projects.append({
            "id": pid, "title": state.metadata.get("TITLE", ""),
            "description": state.metadata.get("DESCRIPTION", ""),
            "real_url": real, "short_url": short.get("shortUrl", ""),
            "short_id": short.get("id", ""), "slug": short.get("slug", ""),
            "created_at": datetime.utcnow().isoformat() + "Z",
        })
        await save_projects(cpanel, projects)
    except Exception as e:
        log.exception("upload fail")
        await msg.edit_text(f"❌ {e}")
        state.cleanup(); ctx.user_data.pop("project", None)
        return ConversationHandler.END

    short_url = short.get("shortUrl", "")
    txt = (f"✅ <b>منتشر شد!</b>\n\n"
           f"📌 {state.metadata.get('TITLE', '')}\n"
           f"🌐 <a href='{real}'>{real}</a>\n"
           f"🔗 {short_url or '—'}\n"
           f"🖼 {len(pmap)} فایل WebP")
    await msg.edit_text(txt, parse_mode="HTML", disable_web_page_preview=True,
                        reply_markup=_menu_kb())
    state.cleanup(); ctx.user_data.pop("project", None)
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
# setup_application
# ═══════════════════════════════════════════════════════════
def setup_application(app):
    """V53: register Portal handlers into existing app. Returns None."""
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("portal", cmd_start),
            CommandHandler("new", cmd_start),
            CallbackQueryHandler(cb_menu, pattern="^portal:new$"),
        ],
        states={
            WAITING_HTML: [
                MessageHandler(filters.Document.ALL, receive_html),
                CallbackQueryHandler(cb_menu, pattern="^portal:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, hint),
            ],
            WAITING_FILES: [
                MessageHandler(filters.Document.ALL | filters.PHOTO, receive_file),
                CallbackQueryHandler(cb_menu, pattern="^portal:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, hint),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
    )
    app.add_handler(conv, group=2)
    app.add_handler(CallbackQueryHandler(cb_menu, pattern="^portal:"), group=2)
    app.add_handler(CommandHandler("settings", lambda u, c: _show_settings_from_cmd(u, c)), group=2)
    app.add_handler(CommandHandler("reload", cmd_reload), group=2)
    return None


async def _show_settings_from_cmd(update, ctx):
    if not is_allowed(update): return
    await update.message.reply_text("از دکمه‌ی تنظیمات در منوی /portal استفاده کن")


# ═══════════════════════════════════════════════════════════
# Standalone main (if run directly)
# ═══════════════════════════════════════════════════════════
def main():
    logging.basicConfig(level=logging.INFO)
    app = Application.builder().token(CONFIG["bot_token"]).build()
    app.add_handler(CommandHandler("start", cmd_start))
    setup_application(app)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()