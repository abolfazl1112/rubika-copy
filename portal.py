#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portal bot (V7.4)
- Robust upload: overwrite → delete+upload → save_file_content
- Non-dotfile paths + auto-migration
- Customers + APK update + random slug
- Admin settings editor (cPanel persisted)
- Diagnostics
"""
import ast, asyncio, json, logging, os, re, secrets, shutil, string, tempfile, time, warnings
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

# ═══════════════════════════════════════════════════════════
# Default CONFIG
# ═══════════════════════════════════════════════════════════
CONFIG = {
    "bot_token": "8921325744:AAFXRJVzWotsUiZ9yslVpc7NevS2c-8DNnQ",
    "allowed_user_ids": [8389746549],
    "cpanel": {
        "host": "webiksahostfast.site", "port": "2083",
        "user": "vaacyvb", "token": "FOEJ2R2UG47IGIZ7DSIFNPPXLUDH7KL7",
        "verify_ssl": False, "base_path": "/public_html",
        "public_base_url": "https://link.webiksahostfast.site",
        "counter_file": "/public_html/counter.txt",
        "projects_file": "/public_html/projects.json",
    },
    "shortener": {
        "enabled": True, "base": "https://nxal.ir",
        "api_key": "nxal_haGkNEVXprw2GCUzNjeP1gh2jUIwqepxPBbKfsuS",
        "slug_prefix": "",
    },
    "upload": {"max_file_size_mb": 20, "max_apk_size_mb": 50, "webp_quality": 82},
}

PORTAL_DIR = Path(__file__).parent
CFG_LOCAL = PORTAL_DIR / "portal_bootstrap.json"
CFG_REMOTE_PATH = "/public_html/portal_config.json"
CUSTOMERS_REMOTE_PATH = "/public_html/customers.json"

DOTFILE_MIGRATION = [
    (".counter.txt", "counter.txt"),
    (".projects.json", "projects.json"),
    (".portal_config.json", "portal_config.json"),
    (".customers.json", "customers.json"),
]

warnings.filterwarnings("ignore", message="Unverified HTTPS request")
log = logging.getLogger("portal")


# ═══════════════════════════════════════════════════════════
# Config persistence
# ═══════════════════════════════════════════════════════════
def _deep_merge(base, override):
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_local():
    if not CFG_LOCAL.exists(): return {}
    try:
        with open(CFG_LOCAL, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception: return {}


def _save_local(data):
    try:
        tmp = str(CFG_LOCAL) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CFG_LOCAL)
    except Exception as e:
        log.error(f"save_local: {e}")


def _apply_from_local():
    global CONFIG
    local = _load_local()
    base = {
        "bot_token": CONFIG["bot_token"],
        "allowed_user_ids": list(CONFIG["allowed_user_ids"]),
        "cpanel": dict(CONFIG["cpanel"]),
        "shortener": dict(CONFIG["shortener"]),
        "upload": dict(CONFIG["upload"]),
    }
    CONFIG = _deep_merge(base, local)


try: _apply_from_local()
except Exception as e: log.error(f"apply_from_local: {e}")


_customers = {}
_config_loaded = False


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════
def is_admin(uid):
    try: return uid in CONFIG["allowed_user_ids"]
    except Exception: return False


def is_allowed(update):
    return bool(update.effective_user and is_admin(update.effective_user.id))


def _mask(s):
    if not s: return "—"
    return s[:6] + "…" + s[-4:] if len(s) > 12 else "…"


def _is_external(url):
    return url.lower().startswith(("http://", "https://", "//", "data:", "#", "javascript:", "mailto:"))


def _clean(url):
    p = urlparse(url).path
    p = unquote(p).replace("\\", "/").lstrip("/")
    while p.startswith("./"): p = p[2:]
    return p


def _safe_json(r, ctx=""):
    status = getattr(r, "status_code", 0)
    try: text = r.text or ""
    except Exception: text = ""
    if not text.strip():
        # Empty body — treat 2xx as success
        if status in (200, 201, 204):
            return {}, None
        return None, f"HTTP {status} empty ({ctx})"
    try: return r.json(), None
    except Exception:
        preview = text[:250].replace("\n", " ").replace("\r", " ")
        return None, f"HTTP {status} non-JSON ({ctx}): {preview}"


def _gen_short_slug() -> str:
    return ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(5))


try:
    import lxml  # noqa
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

    def _client(self, t=30): return httpx.AsyncClient(verify=self.verify, timeout=t)

    async def _get_raw(self, ep, params):
        async with self._client(60) as c:
            return await c.get(f"{self.base}/{ep}", headers=self.headers, params=params)

    async def _post_raw(self, ep, data=None, files=None):
        async with self._client(300) as c:
            return await c.post(f"{self.base}/{ep}", headers=self.headers, data=data, files=files)

    async def list_files(self, path="/", types="dir"):
        r = await self._get_raw("Fileman/list_files", {"path": path, "types": types})
        data, err = _safe_json(r, f"list_files({path})")
        if err: raise RuntimeError(err)
        return data

    async def _dir_exists(self, path):
        try: return (await self.list_files(path, "dir")).get("status") == 1
        except Exception: return False

    async def _api2(self, mod, fn, **params):
        url = f"https://{self.host}:{self.port}/json-api/cpanel"
        payload = {"cpanel_jsonapi_user": self.user, "cpanel_jsonapi_apiversion": "2",
                   "cpanel_jsonapi_module": mod, "cpanel_jsonapi_func": fn, **params}
        async with self._client(30) as c:
            r = await c.get(url, headers=self.headers, params=payload)
        data, err = _safe_json(r, f"api2 {mod}/{fn}")
        if err: raise RuntimeError(err)
        if (data or {}).get("cpanelresult", {}).get("error"):
            raise RuntimeError(f"API2 {mod}/{fn}: {data['cpanelresult']['error']}")
        return data

    async def ensure_dir(self, full):
        cur = ""
        for part in [p for p in full.split("/") if p]:
            parent = cur or "/"
            cur = f"{cur}/{part}"
            if await self._dir_exists(cur): continue
            await self._api2("Fileman", "mkdir", path=parent, name=part)

    # ═══════════════════════════════════════════════════════
    # Upload (V7.4 — robust)
    # ═══════════════════════════════════════════════════════
    async def _delete_file(self, rdir, fname):
        """Delete a file from cPanel. Returns True on success."""
        try:
            async with self._client(30) as c:
                r = await c.get(f"{self.base}/Fileman/delete_files",
                                headers=self.headers,
                                params={"path": rdir, "files": fname})
            data, err = _safe_json(r, "delete")
            if err: return False
            return data.get("status") == 1
        except Exception: return False

    async def upload(self, rdir, fname, content):
        """Robust upload: overwrite → delete+upload → save_file_content."""
        full_path = f"{rdir.rstrip('/')}/{fname}"
        is_text = any(fname.lower().endswith(ext) for ext in
                      (".txt", ".json", ".md", ".log", ".html", ".htm", ".xml", ".csv"))
        errors = []

        # ── M1: upload_files with overwrite=1 ──
        try:
            r = await self._post_raw("Fileman/upload_files",
                                      data={"dir": rdir, "overwrite": "1"},
                                      files={"file-1": (fname, content)})
            data, err = _safe_json(r, "upload")
            if not err and data.get("status") == 1:
                return data
            reason = "?"
            try:
                uploads = (data.get("data") or {}).get("uploads") or []
                if uploads: reason = uploads[0].get("reason") or "?"
            except: pass
            errors.append(f"M1:{str(reason)[:140]}")
        except Exception as e:
            errors.append(f"M1:{type(e).__name__}:{str(e)[:80]}")

        # ── M2: delete existing → upload fresh ──
        try:
            deleted = await self._delete_file(rdir, fname)
            if deleted:
                await asyncio.sleep(0.5)
            r = await self._post_raw("Fileman/upload_files",
                                      data={"dir": rdir},
                                      files={"file-1": (fname, content)})
            data, err = _safe_json(r, "upload2")
            if not err and data.get("status") == 1:
                log.info(f"[upload] M2 (del+up) OK: {full_path}")
                return data
            reason = "?"
            try:
                uploads = (data.get("data") or {}).get("uploads") or []
                if uploads: reason = uploads[0].get("reason") or "?"
            except: pass
            errors.append(f"M2:{str(reason)[:140]}")
        except Exception as e:
            errors.append(f"M2:{type(e).__name__}:{str(e)[:80]}")

        # ── M3: save_file_content (text only, param='file') ──
        if is_text:
            try:
                text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
                async with self._client(60) as c:
                    r = await c.post(
                        f"{self.base}/Fileman/save_file_content",
                        headers=self.headers,
                        data={"dir": rdir, "file": fname, "content": text}
                    )
                data, err = _safe_json(r, "save")
                if not err and data.get("status") == 1:
                    log.info(f"[upload] M3 (save) OK: {full_path}")
                    return {"status": 1, "_method": "save_file_content"}
                if err: errors.append(f"M3:{err[:100]}")
                else: errors.append(f"M3:{str(data.get('errors', '?'))[:100]}")
            except Exception as e:
                errors.append(f"M3:{type(e).__name__}:{str(e)[:80]}")

        raise RuntimeError(f"❌ '{fname}' → '{rdir}':\n" + "\n".join(errors))

    async def read(self, full):
        try:
            r = await self._get_raw("Fileman/get_file_content", {"path": full})
            data, err = _safe_json(r, f"read({full})")
            if err: return None
            return data.get("data", {}).get("content") if data.get("status") == 1 else None
        except Exception: return None

    async def next_project_num(self):
        counter = CONFIG["cpanel"]["counter_file"]
        cur = 0
        content = await self.read(counter)
        if not content:
            old_name = "." + os.path.basename(counter)
            content = await self.read(f"/public_html/{old_name}")
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
        data, err = _safe_json(r, "nxal.shorten")
        if err: raise RuntimeError(err)
        if not data.get("success"): raise RuntimeError(f"shorten: {data}")
        return data["data"]

    async def stats(self, link_id, days=30):
        if not self.enabled: raise RuntimeError("disabled")
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self.base}/api/v1/links/{link_id}/stats",
                          headers=self.headers, params={"days": days})
        data, err = _safe_json(r, "nxal.stats")
        if err: raise RuntimeError(err)
        if not data.get("success"): raise RuntimeError(f"stats: {data}")
        return data["data"]


# ═══════════════════════════════════════════════════════════
# Migration: old dotfiles → new names
# ═══════════════════════════════════════════════════════════
async def _migrate_dotfiles() -> int:
    cpanel = CPanelClient()
    migrated = 0
    for old_name, new_name in DOTFILE_MIGRATION:
        old_path = f"/public_html/{old_name}"
        new_path = f"/public_html/{new_name}"
        new_content = await cpanel.read(new_path)
        if new_content is not None and new_content.strip():
            log.info(f"[migrate] {new_name} exists ({len(new_content)}B), skip")
            continue
        old_content = await cpanel.read(old_path)
        if old_content is None or not old_content.strip():
            log.info(f"[migrate] {old_name} not found, skip")
            continue
        try:
            old_bytes = old_content.encode("utf-8") if isinstance(old_content, str) else old_content
            await cpanel.upload("/public_html", new_name, old_bytes)
            log.info(f"[migrate] {old_name} → {new_name} ({len(old_bytes)}B) ✓")
            migrated += 1
        except Exception as e:
            log.error(f"[migrate] {old_name} → {new_name} FAIL: {e}")
    return migrated


# ═══════════════════════════════════════════════════════════
# Config I/O with old-file fallback
# ═══════════════════════════════════════════════════════════
async def _load_remote_config() -> dict:
    try:
        cpanel = CPanelClient()
        content = await cpanel.read(CFG_REMOTE_PATH)
        if not content:
            content = await cpanel.read("/public_html/.portal_config.json")
        if not content: return {}
        d = json.loads(content)
        return d if isinstance(d, dict) else {}
    except Exception as e:
        log.warning(f"load_remote_config: {e}")
        return {}


async def _save_remote_config(overrides: dict) -> bool:
    try:
        cpanel = CPanelClient()
        data = json.dumps(overrides, ensure_ascii=False, indent=2).encode()
        await cpanel.upload("/public_html", "portal_config.json", data)
        return True
    except Exception as e:
        log.error(f"save_remote_config: {e}")
        return False


async def _load_remote_customers() -> dict:
    try:
        cpanel = CPanelClient()
        content = await cpanel.read(CUSTOMERS_REMOTE_PATH)
        if not content:
            content = await cpanel.read("/public_html/.customers.json")
        if not content: return {}
        d = json.loads(content)
        return d if isinstance(d, dict) else {}
    except Exception as e:
        log.warning(f"load_remote_customers: {e}")
        return {}


async def _save_remote_customers(customers: dict) -> bool:
    try:
        cpanel = CPanelClient()
        data = json.dumps(customers, ensure_ascii=False, indent=2).encode()
        await cpanel.upload("/public_html", "customers.json", data)
        return True
    except Exception as e:
        log.error(f"save_remote_customers: {e}")
        return False


async def _load_all_from_cpanel():
    global CONFIG, _customers, _config_loaded
    try:
        n = await _migrate_dotfiles()
        if n: log.info(f"[portal] migrated {n} dotfiles")
    except Exception as e:
        log.warning(f"[portal] migration: {e}")
    remote_cfg = await _load_remote_config()
    if remote_cfg:
        CONFIG = _deep_merge(CONFIG, remote_cfg)
    _customers = await _load_remote_customers()
    _config_loaded = True
    log.info(f"[portal] loaded: config={len(remote_cfg)} customers={len(_customers)}")


async def _set_value(section, key, value):
    if section == "telegram": CONFIG[key] = value
    else: CONFIG.setdefault(section, {})[key] = value
    remote = await _load_remote_config()
    if section == "telegram": remote[key] = value
    else: remote.setdefault(section, {})[key] = value
    if section == "cpanel" and key in ("host", "port", "user", "token", "verify_ssl"):
        local = _load_local()
        local.setdefault("cpanel", {})[key] = value
        _save_local(local)
    if section == "telegram" and key == "bot_token":
        local = _load_local()
        local["bot_token"] = value
        _save_local(local)
    ok = await _save_remote_config(remote)
    if not ok:
        return False, "ذخیره در cPanel ناموفق — فقط در حافظه"
    return True, None


# ═══════════════════════════════════════════════════════════
# Customers
# ═══════════════════════════════════════════════════════════
def _get_customer(uid):
    return _customers.get(str(uid)) or {}


async def _update_customer(uid, user=None, action=None):
    global _customers
    key = str(uid); now = int(time.time())
    if key not in _customers:
        _customers[key] = {"id": uid, "first_seen": now, "last_seen": now, "apk_updates": 0}
    c = _customers[key]; c["last_seen"] = now
    if user is not None:
        fn = getattr(user, "first_name", "") or ""
        ln = getattr(user, "last_name", "") or ""
        un = getattr(user, "username", "") or ""
        if fn: c["name"] = fn[:40]
        if ln: c["last_name"] = ln[:40]
        if un: c["username"] = un[:40]
    if action == "apk_update":
        c["apk_updates"] = int(c.get("apk_updates", 0)) + 1
    await _save_remote_customers(_customers)


# ═══════════════════════════════════════════════════════════
# Projects
# ═══════════════════════════════════════════════════════════
_projects_cache = {"data": None, "ts": 0}
_PROJECTS_TTL = 60


def invalidate_cache():
    _projects_cache["data"] = None; _projects_cache["ts"] = 0


async def get_projects(force=False):
    now = time.time()
    if not force and _projects_cache["data"] is not None and (now - _projects_cache["ts"]) < _PROJECTS_TTL:
        return _projects_cache["data"]
    cpanel = CPanelClient()
    content = await cpanel.read(CONFIG["cpanel"]["projects_file"])
    if not content:
        content = await cpanel.read("/public_html/.projects.json")
    if not content:
        _projects_cache["data"] = []; _projects_cache["ts"] = now
        return []
    try:
        d = json.loads(content)
        d = d if isinstance(d, list) else []
    except Exception:
        d = []
    _projects_cache["data"] = d; _projects_cache["ts"] = now
    return d


async def save_projects(projects):
    cpanel = CPanelClient()
    data = json.dumps(projects, ensure_ascii=False, indent=2).encode()
    await cpanel.upload("/public_html", "projects.json", data)
    invalidate_cache()


async def update_project(pid, updates):
    projects = await get_projects(force=True)
    for p in projects:
        if p.get("id") == pid:
            p.update(updates)
            await save_projects(projects)
            return True
    return False


async def _get_customer_projects(uid):
    projects = await get_projects()
    return [p for p in projects if p.get("owner_id") == uid]


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
# Project state
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
        self.owner_id = None
        self.apk_paths = [r["path"] for r in resources
                          if r["tag"] == "a" and r["path"].lower().endswith(".apk")]
    @property
    def done_count(self): return self.total - len(self.pending)
    def next_pending(self): return self.pending[0] if self.pending else None
    def cleanup(self): shutil.rmtree(self.tmp_dir, ignore_errors=True)


(WAITING_HTML, WAITING_FILES, WAITING_SETTING,
 WAITING_OWNER, WAITING_APK) = range(5)


# ═══════════════════════════════════════════════════════════
# Settings schema
# ═══════════════════════════════════════════════════════════
SETTINGS_SCHEMA = [
    ("telegram", "bot_token", "Bot Token", "str", True, True),
    ("telegram", "allowed_user_ids", "Allowed Admin IDs", "list_int", False, False),
    ("cpanel", "host", "cPanel Host", "str", False, False),
    ("cpanel", "port", "cPanel Port", "str", False, False),
    ("cpanel", "user", "cPanel User", "str", False, False),
    ("cpanel", "token", "cPanel API Token", "str", True, False),
    ("cpanel", "verify_ssl", "Verify SSL", "bool", False, False),
    ("cpanel", "base_path", "Base Path", "str", False, False),
    ("cpanel", "public_base_url", "Public Base URL", "str", False, False),
    ("cpanel", "counter_file", "Counter File", "str", False, False),
    ("cpanel", "projects_file", "Projects File", "str", False, False),
    ("shortener", "enabled", "Shortener Enabled", "bool", False, False),
    ("shortener", "base", "Shortener Base URL", "str", False, False),
    ("shortener", "api_key", "Shortener API Key", "str", True, False),
    ("shortener", "slug_prefix", "Slug Prefix", "str", False, False),
    ("upload", "max_file_size_mb", "Max File Size (MB)", "int", False, False),
    ("upload", "max_apk_size_mb", "Max APK Size (MB)", "int", False, False),
    ("upload", "webp_quality", "WebP Quality (1-100)", "int", False, False),
]
SCHEMA_BY_KEY = {(s, k): (lbl, typ, sec, rst) for (s, k, lbl, typ, sec, rst) in SETTINGS_SCHEMA}


def _get_value(section, key):
    if section == "telegram": return CONFIG.get(key)
    return CONFIG.get(section, {}).get(key)


def _parse_value(typ, raw):
    raw = (raw or "").strip()
    if typ == "str": return raw
    if typ == "int": return int(re.sub(r"[^\d\-]", "", raw))
    if typ == "bool":
        low = raw.lower()
        if low in ("true", "1", "yes", "on", "بله", "روشن"): return True
        if low in ("false", "0", "no", "off", "خیر", "خاموش"): return False
        raise ValueError(f"bool نامعتبر: {raw}")
    if typ == "list_int":
        parts = re.split(r"[,\s;]+", raw)
        out = [int(p) for p in parts if p.strip().isdigit()]
        if not out: raise ValueError("list خالی")
        return out
    raise ValueError(f"type ناشناخته: {typ}")


# ═══════════════════════════════════════════════════════════
# Keyboards
# ═══════════════════════════════════════════════════════════
def _admin_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 ساخت درگاه جدید", callback_data="portal:new")],
        [InlineKeyboardButton("📋 همه پروژه‌ها", callback_data="portal:projects:0")],
        [InlineKeyboardButton("📊 آمار", callback_data="portal:stats:list")],
        [InlineKeyboardButton("⚙️ تنظیمات", callback_data="portal:settings")],
    ])


def _settings_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 تلگرام", callback_data="portal:set:sec:telegram")],
        [InlineKeyboardButton("🖥 cPanel", callback_data="portal:set:sec:cpanel")],
        [InlineKeyboardButton("🔗 کوتاه‌ساز", callback_data="portal:set:sec:shortener")],
        [InlineKeyboardButton("📤 آپلود", callback_data="portal:set:sec:upload")],
        [InlineKeyboardButton("👥 مشتری‌ها", callback_data="portal:customers:0")],
        [InlineKeyboardButton("🔧 عیب‌یابی", callback_data="portal:diag")],
        [InlineKeyboardButton("🧪 تست write", callback_data="portal:diag_write")],
        [InlineKeyboardButton("🔄 ریست به defaults", callback_data="portal:set:reset_confirm")],
        [InlineKeyboardButton("« بازگشت", callback_data="portal:back")],
    ])


def _section_kb(section):
    rows = []
    for (s, k, lbl, typ, sec, rst) in SETTINGS_SCHEMA:
        if s != section: continue
        val = _get_value(s, k)
        if sec: show = _mask(str(val)) if val else "—"
        elif isinstance(val, list): show = ", ".join(str(x) for x in val) if val else "—"
        elif isinstance(val, bool): show = "✅" if val else "❌"
        else: show = str(val)[:30] if val not in (None, "") else "—"
        star = " 🔐" if sec else ""
        warn = " ⚠️" if rst else ""
        rows.append([InlineKeyboardButton(f"{lbl}{star}{warn}  →  {show}",
                                          callback_data=f"portal:set:edit:{s}:{k}")])
    rows.append([InlineKeyboardButton("« بازگشت", callback_data="portal:settings")])
    return InlineKeyboardMarkup(rows)


def _customer_home_kb(projects):
    rows = []
    for p in projects:
        pid = p.get("id", "?"); title = p.get("title") or f"#{pid}"
        rows.append([InlineKeyboardButton(f"📱 {title[:30]}", callback_data=f"portal:cust:view:{pid}")])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# Views
# ═══════════════════════════════════════════════════════════
async def _show_admin_menu(obj):
    if hasattr(obj, "edit_message_text"):
        try: await obj.edit_message_text("🎯 <b>پنل مدیریت</b>", parse_mode="HTML", reply_markup=_admin_menu_kb())
        except Exception: await obj.message.reply_text("🎯 <b>پنل مدیریت</b>", parse_mode="HTML", reply_markup=_admin_menu_kb())
    else:
        await obj.reply_text("🎯 <b>پنل مدیریت</b>", parse_mode="HTML", reply_markup=_admin_menu_kb())


async def _show_settings(q):
    remote_cfg = await _load_remote_config()
    n_cfg = sum(len(v) if isinstance(v, dict) else 1 for v in remote_cfg.values()) if remote_cfg else 0
    n_cust = len(_customers)
    txt = (f"⚙️ <b>تنظیمات</b>\n\n"
           f"📁 cPanel: <code>portal_config.json</code> ({n_cfg} کلید)\n"
           f"👥 cPanel: <code>customers.json</code> ({n_cust} مشتری)\n\n"
           f"<i>همه تنظیمات در cPanel ذخیره می‌شن.</i>")
    await q.edit_message_text(txt, parse_mode="HTML", reply_markup=_settings_kb())


async def _show_section(q, section):
    labels = {"telegram": "🤖 تلگرام", "cpanel": "🖥 cPanel",
              "shortener": "🔗 کوتاه‌ساز", "upload": "📤 آپلود"}
    await q.edit_message_text(f"{labels.get(section, section)}:", reply_markup=_section_kb(section))


async def _show_admin_projects(q, page=0, per=5):
    projects = await get_projects()
    if not projects:
        await q.edit_message_text("📭 خالی",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« بازگشت", callback_data="portal:back")]]))
        return
    total = len(projects); pages = max(1, -(-total // per))
    page = max(0, min(page, pages - 1))
    rev = list(reversed(projects)); chunk = rev[page * per:(page + 1) * per]
    txt = f"📋 <b>همه پروژه‌ها ({total})</b> — {page+1}/{pages}\n\n"
    rows = []
    for p in chunk:
        pid = p.get("id", "?"); title = p.get("title") or f"#{pid}"
        owner = p.get("owner_id")
        owner_str = f"👤 {owner}" if owner else "👤 —"
        txt += f"<b>#{pid}</b> — {title}\n  {owner_str}\n"
        rows.append([InlineKeyboardButton(f"📊 #{pid} {title[:20]}", callback_data=f"portal:stats:view:{pid}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("◀️", callback_data=f"portal:projects:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data="noop"))
    if page < pages-1: nav.append(InlineKeyboardButton("▶️", callback_data=f"portal:projects:{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("« بازگشت", callback_data="portal:back")])
    await q.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
                              disable_web_page_preview=True)


async def _show_stats_list(q):
    projects = await get_projects()
    if not projects:
        await q.edit_message_text("📭", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("« بازگشت", callback_data="portal:back")]]))
        return
    rows = []
    for p in projects[-10:]:
        pid = p.get("id", "?")
        rows.append([InlineKeyboardButton(f"📊 #{pid} — {(p.get('title') or '?')[:20]}",
                                          callback_data=f"portal:stats:view:{pid}")])
    rows.append([InlineKeyboardButton("« بازگشت", callback_data="portal:back")])
    await q.edit_message_text("📊:", reply_markup=InlineKeyboardMarkup(rows))


async def _show_stats(q, pid, uid):
    projects = await get_projects()
    project = next((p for p in projects if p.get("id") == pid), None)
    if not project: await q.edit_message_text("❌ پیدا نشد"); return
    if not is_admin(uid) and project.get("owner_id") != uid:
        await q.edit_message_text("⛔"); return
    sid = project.get("short_id", ""); stats_data = None
    if sid:
        try: stats_data = await NxalClient().stats(sid, days=30)
        except Exception as e: stats_data = {"error": str(e)[:200]}
    txt = f"📊 <b>{project.get('title') or pid}</b>\n\n"
    if project.get("owner_id"):
        cust = _get_customer(project["owner_id"]); cn = cust.get("name", "")
        txt += f"👤 {project['owner_id']}" + (f" — {cn}" if cn else "") + "\n"
    if project.get("short_url"): txt += f"🔗 {project['short_url']}\n"
    if project.get("real_url"): txt += f"🌐 {project['real_url']}\n"
    apks = project.get("apk_paths") or []
    if apks: txt += f"📱 APK: <code>{apks[0]}</code>\n"
    txt += "\n"
    if stats_data and "error" not in stats_data:
        def top(k, n=5):
            items = stats_data.get(k, [])[:n]
            return "\n".join(f"  • {i['name']}: {i['count']}" for i in items) if items else "  —"
        txt += (f"👁 <b>{stats_data.get('totalClicks', 0)}</b>  ·  👤 <b>{stats_data.get('uniqueClicks', 0)}</b>\n\n"
                f"🌍 {top('byCountry')}\n📱 {top('byDevice')}")
    elif stats_data: txt += f"⚠️ {stats_data.get('error')}"
    else: txt += "⚠️ لینک کوتاه ندارد"
    rows = []
    if is_admin(uid):
        rows.append([InlineKeyboardButton(f"👤 ایدی مشتری: {project.get('owner_id') or '—'}",
                                          callback_data=f"portal:edit_owner:{pid}")])
    rows.append([InlineKeyboardButton("« بازگشت",
                  callback_data="portal:stats:list" if is_admin(uid) else "portal:cust:home")])
    await q.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows),
                              disable_web_page_preview=True)


async def _show_customer_home(obj, uid, projects=None):
    if projects is None:
        all_p = await get_projects()
        projects = [p for p in all_p if p.get("owner_id") == uid]
    if not projects:
        txt = "📭 هیچ پروژه‌ای تخصیص نیافته."; kb = None
    else:
        txt = f"👋 <b>{len(projects)}</b> پروژه داری:"; kb = _customer_home_kb(projects)
    if hasattr(obj, "edit_message_text"):
        try: await obj.edit_message_text(txt, parse_mode="HTML", reply_markup=kb)
        except Exception: await obj.message.reply_text(txt, parse_mode="HTML", reply_markup=kb)
    else:
        await obj.reply_text(txt, parse_mode="HTML", reply_markup=kb)


async def _show_customer_project(q, uid, pid):
    projects = await get_projects()
    project = next((p for p in projects if p.get("id") == pid), None)
    if not project: await q.edit_message_text("❌"); return
    if project.get("owner_id") != uid and not is_admin(uid):
        await q.edit_message_text("⛔"); return
    title = project.get("title") or f"#{pid}"
    short_url = project.get("short_url", "")
    real_url = project.get("real_url", "")
    apks = project.get("apk_paths") or []
    updated = project.get("updated_at", "")
    txt = f"📱 <b>{title}</b>\n\n"
    if real_url: txt += f"🌐 <a href='{real_url}'>صفحه اصلی</a>\n"
    if short_url: txt += f"🔗 <a href='{short_url}'>{short_url}</a>\n"
    if apks:
        txt += f"\n📦 APK: <code>{apks[0]}</code>\n"
        if len(apks) > 1: txt += f"<i>+{len(apks)-1}</i>\n"
    if updated: txt += f"\n📅 آخرین آپدیت: <code>{updated[:10]}</code>\n"
    rows = []
    if apks:
        rows.append([InlineKeyboardButton("🔄 آپدیت APK", callback_data=f"portal:cust:apk:{pid}")])
    rows.append([InlineKeyboardButton("📊 آمار", callback_data=f"portal:stats:view:{pid}")])
    rows.append([InlineKeyboardButton("« بازگشت", callback_data="portal:cust:home")])
    await q.edit_message_text(txt, parse_mode="HTML",
                              reply_markup=InlineKeyboardMarkup(rows), disable_web_page_preview=True)


async def _show_customers(q, page=0, per=8):
    if not _customers:
        await q.edit_message_text("👥 <b>مشتریان</b>\n\n📭 خالی", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« بازگشت", callback_data="portal:settings")]]))
        return
    items = sorted(_customers.items(), key=lambda kv: kv[1].get("last_seen", 0), reverse=True)
    total = len(items); pages = max(1, -(-total // per)); page = max(0, min(page, pages - 1))
    chunk = items[page * per:(page + 1) * per]
    projects = await get_projects(); by_owner = {}
    for p in projects:
        oid = p.get("owner_id")
        if oid: by_owner[oid] = by_owner.get(oid, 0) + 1
    txt = f"👥 <b>مشتریان ({total})</b> — {page+1}/{pages}\n\n"
    rows = []
    for k, c in chunk:
        uid = c.get("id", k); name = c.get("name") or "?"
        un = c.get("username", ""); n_proj = by_owner.get(uid, 0); n_apk = c.get("apk_updates", 0)
        last = c.get("last_seen", 0); ago = int(time.time() - last) if last else 0
        txt += (f"👤 <code>{uid}</code> — {name}" + (f" (@{un})" if un else "") + "\n"
                f"   📱 {n_proj} · 🔄 {n_apk} · ⏱ {ago//3600}h\n")
        rows.append([InlineKeyboardButton(f"👤 {name[:20]} — {n_proj}📱",
                                          callback_data=f"portal:cust:info:{uid}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("◀️", callback_data=f"portal:customers:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data="noop"))
    if page < pages-1: nav.append(InlineKeyboardButton("▶️", callback_data=f"portal:customers:{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("« بازگشت", callback_data="portal:settings")])
    await q.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))


async def _show_customer_info(q, uid):
    cust = _get_customer(uid)
    if not cust: await q.edit_message_text("❌"); return
    projects = await _get_customer_projects(uid)
    txt = f"👤 <b>مشتری {uid}</b>\n\n📛 {cust.get('name', '?')}\n"
    if cust.get("username"): txt += f"🔗 @{cust['username']}\n"
    first = cust.get("first_seen", 0); last = cust.get("last_seen", 0)
    if first: txt += f"📅 اولین: <code>{datetime.fromtimestamp(first).strftime('%Y-%m-%d')}</code>\n"
    if last: txt += f"📅 آخرین: <code>{datetime.fromtimestamp(last).strftime('%Y-%m-%d')}</code>\n"
    txt += f"🔄 آپدیت APK: <b>{cust.get('apk_updates', 0)}</b>\n\n📱 <b>پروژه‌ها ({len(projects)})</b>:\n"
    for p in projects: txt += f"  • #{p.get('id')} — {p.get('title') or '?'}\n"
    await q.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("« بازگشت", callback_data="portal:customers:0")]]))


# ═══════════════════════════════════════════════════════════
# Customer entry
# ═══════════════════════════════════════════════════════════
async def handle_customer_start(update, ctx):
    uid = update.effective_user.id if update.effective_user else None
    if not uid: return False
    try:
        owned = await asyncio.wait_for(_get_customer_projects(uid), timeout=20)
    except asyncio.TimeoutError:
        log.warning(f"[customer_start] timeout uid={uid}")
        try: await update.message.reply_text("⏳ سرور کند، دوباره /start بزن")
        except: pass
        return True
    except Exception as e:
        log.error(f"[customer_start] err uid={uid}: {type(e).__name__}: {e}")
        if str(uid) in _customers:
            try: await update.message.reply_text(f"⚠️ خطای موقت: <code>{str(e)[:150]}</code>",
                                                  parse_mode="HTML")
            except: pass
            return True
        return False
    if not owned: return False
    try: await _update_customer(uid, user=update.effective_user)
    except Exception as e: log.warning(f"[customer_start] update: {e}")
    name = (update.effective_user.first_name or "مشتری")[:40]
    try:
        await update.message.reply_text(
            f"👋 سلام <b>{name}</b>\n\n📱 <b>{len(owned)}</b> پروژه داری:",
            parse_mode="HTML", reply_markup=_customer_home_kb(owned))
    except Exception as e: log.error(f"[customer_start] reply: {e}")
    return True


# ═══════════════════════════════════════════════════════════
# Handlers
# ═══════════════════════════════════════════════════════════
async def cmd_start(update, ctx):
    uid = update.effective_user.id if update.effective_user else None
    if not uid: return
    if is_admin(uid):
        await _show_admin_menu(update.message); return
    if await handle_customer_start(update, ctx): return
    await update.message.reply_text("⛔ دسترسی ندارید.")


async def cb_menu(update, ctx):
    q = update.callback_query
    if not q: return
    await q.answer()
    uid = q.from_user.id if q.from_user else None
    if not uid: return
    d = q.data

    if d == "portal:back":
        try: await _show_admin_menu(q)
        except Exception: await _show_admin_menu(q.message)
        return ConversationHandler.END
    if d == "portal:new":
        if not is_admin(uid):
            await q.answer("⛔", show_alert=True); return
        await q.edit_message_text("📄 <b>ساخت درگاه جدید</b>\n\nHTML بفرست:",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« لغو", callback_data="portal:back")]]))
        return WAITING_HTML

    if d == "portal:cust:home":
        await _show_customer_home(q, uid); return
    if d.startswith("portal:cust:view:"):
        await _show_customer_project(q, uid, d.split(":")[-1]); return
    if d.startswith("portal:cust:apk:"):
        pid = d.split(":")[-1]
        projects = await get_projects()
        project = next((p for p in projects if p.get("id") == pid), None)
        if not project or (project.get("owner_id") != uid and not is_admin(uid)):
            await q.answer("⛔", show_alert=True); return
        apks = project.get("apk_paths") or []
        if not apks: await q.answer("APK ندارد", show_alert=True); return
        ctx.user_data["apk_update"] = {"pid": pid, "apk_path": apks[0]}
        await q.edit_message_text(
            f"📱 <b>آپدیت APK</b>\n\n📦 <code>{apks[0]}</code>\n\nAPK جدید بفرست:",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« لغو", callback_data=f"portal:cust:view:{pid}")]]))
        return WAITING_APK

    if not is_admin(uid):
        await q.answer("⛔", show_alert=True); return

    if d.startswith("portal:projects:"): await _show_admin_projects(q, int(d.split(":")[-1]))
    elif d == "portal:stats:list": await _show_stats_list(q)
    elif d.startswith("portal:stats:view:"): await _show_stats(q, d.split(":")[-1], uid)
    elif d == "portal:settings": await _show_settings(q)
    elif d.startswith("portal:set:sec:"): await _show_section(q, d.split(":")[-1])
    elif d.startswith("portal:set:edit:"):
        parts = d.split(":", 4)
        if len(parts) < 5: return
        section, key = parts[3], parts[4]
        meta = SCHEMA_BY_KEY.get((section, key))
        if not meta: return
        lbl, typ, sec, rst = meta
        cur = _get_value(section, key)
        cur_show = ("(مخفی)" if sec else ", ".join(str(x) for x in cur) if isinstance(cur, list) else
                    ("true" if cur is True else "false" if cur is False else str(cur)))
        txt = f"✏️ <b>{lbl}</b>\n\nمقدار فعلی: <code>{cur_show}</code>\nنوع: <code>{typ}</code>\n"
        if rst: txt += "⚠️ نیاز به restart\n"
        txt += "\nمقدار جدید:"
        ctx.user_data["setting_edit"] = {"section": section, "key": key}
        await q.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("« لغو", callback_data=f"portal:set:sec:{section}")]]))
        return WAITING_SETTING
    elif d == "portal:set:reset_confirm":
        await q.edit_message_text("⚠️ <b>ریست</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ بله", callback_data="portal:set:reset_do")],
             [InlineKeyboardButton("« انصراف", callback_data="portal:settings")]]))
    elif d == "portal:set:reset_do":
        try:
            if CFG_LOCAL.exists(): CFG_LOCAL.unlink()
            await _save_remote_config({})
            _apply_from_local()
            await q.edit_message_text("✅ ریست شد (restart لازم).", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« بازگشت", callback_data="portal:settings")]]))
        except Exception as e: await q.edit_message_text(f"❌ {e}")
    elif d == "portal:diag": await cmd_diag_cb(q)
    elif d == "portal:diag_write":
        class _F:
            async def edit_message_text(self, *a, **k): await q.edit_message_text(*a, **k)
        await cmd_diag_write_cb(_F())
    elif d.startswith("portal:customers:"): await _show_customers(q, int(d.split(":")[-1]))
    elif d.startswith("portal:cust:info:"): await _show_customer_info(q, int(d.split(":")[-1]))
    elif d.startswith("portal:edit_owner:"):
        pid = d.split(":")[-1]
        projects = await get_projects()
        project = next((p for p in projects if p.get("id") == pid), None)
        if not project: return
        cur = project.get("owner_id") or "—"
        ctx.user_data["owner_edit"] = {"pid": pid}
        await q.edit_message_text(
            f"👤 <b>ویرایش مشتری #{pid}</b>\n\nایدی فعلی: <code>{cur}</code>\n\nایدی جدید (یا /skip):",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« لغو", callback_data=f"portal:stats:view:{pid}")]]))
        return WAITING_OWNER
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
# Settings value editor
# ═══════════════════════════════════════════════════════════
async def receive_setting_value(update, ctx):
    if not is_allowed(update): return ConversationHandler.END
    info = ctx.user_data.get("setting_edit")
    if not info: return ConversationHandler.END
    section, key = info["section"], info["key"]
    meta = SCHEMA_BY_KEY.get((section, key))
    if not meta: return ConversationHandler.END
    lbl, typ, sec, rst = meta
    raw = (update.message.text or "").strip()
    if raw.lower() in ("/cancel", "لغو"): return ConversationHandler.END
    try: val = _parse_value(typ, raw)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}\nدوباره بفرست یا /cancel")
        return WAITING_SETTING
    ok, err = await _set_value(section, key, val)
    show = _mask(str(val)) if sec else (", ".join(str(x) for x in val) if isinstance(val, list) else
                                        ("true" if val is True else "false" if val is False else str(val)))
    msg = f"✅ ذخیره (cPanel+local)\n<b>{lbl}</b> = <code>{show}</code>" if ok else f"⚠️ <b>{lbl}</b> = <code>{show}</code>\n\n<code>{err}</code>"
    if rst: msg += "\n\n⚠️ restart لازم"
    await update.message.reply_text(msg, parse_mode="HTML")
    ctx.user_data.pop("setting_edit", None)
    class _F:
        async def edit_message_text(self, *a, **k): await update.message.reply_text(*a, **k)
    await _show_section(_F(), section)
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
# Project creation flow
# ═══════════════════════════════════════════════════════════
def _is_html_doc(msg):
    return bool(msg.document and msg.document.file_name
                and msg.document.file_name.lower().endswith((".html", ".htm")))


async def receive_html(update, ctx):
    if not is_allowed(update): return
    msg = update.message
    if not _is_html_doc(msg):
        await msg.reply_text("⚠️ HTML بفرست (Document)"); return WAITING_HTML
    f = await msg.document.get_file()
    html_bytes = bytes(await f.download_as_bytearray())
    soup, resources = extract_resources(html_bytes)
    metadata = extract_metadata(html_bytes)
    state = ProjectState(html_bytes, resources, metadata)
    ctx.user_data["project"] = state
    if not resources:
        await msg.reply_text("✅ HTML دریافت شد.")
        return await _ask_owner_or_finalize(update, ctx, state, soup)
    icons = "".join("🖼" if r["tag"] == "img" else "📱" for r in resources[:10])
    apk_info = f"\n📦 {len(state.apk_paths)} APK" if state.apk_paths else ""
    await msg.reply_text(f"📋 {state.total} فایل\n{icons}{apk_info}\n\nشروع...")
    await _ask_next(msg, state)
    return WAITING_FILES


async def receive_file(update, ctx):
    if not is_allowed(update): return
    state = ctx.user_data.get("project")
    if not state:
        await update.message.reply_text("اول HTML بفرست یا /cancel"); return WAITING_HTML
    msg = update.message; nxt = state.next_pending()
    if not nxt:
        soup, _ = extract_resources(state.html_bytes)
        return await _ask_owner_or_finalize(update, ctx, state, soup)
    tg_file = None; size = 0
    if msg.document: size = msg.document.file_size or 0; tg_file = await msg.document.get_file()
    elif msg.photo: p = msg.photo[-1]; size = p.file_size or 0; tg_file = await p.get_file()
    else:
        await msg.reply_text(f"📥 منتظر: <code>{nxt}</code>", parse_mode="HTML"); return WAITING_FILES
    if size > int(CONFIG["upload"].get("max_file_size_mb", 20)) * 1024 * 1024:
        await msg.reply_text("❌ خیلی بزرگ"); return WAITING_FILES
    local = state.tmp_dir / nxt
    local.parent.mkdir(parents=True, exist_ok=True)
    await tg_file.download_to_drive(local)
    state.pending.pop(0); state.uploaded[nxt] = local
    await msg.reply_text(f"✅ {state.done_count}/{state.total}")
    if state.pending:
        await _ask_next(msg, state); return WAITING_FILES
    soup, _ = extract_resources(state.html_bytes)
    return await _ask_owner_or_finalize(update, ctx, state, soup)


async def _ask_next(msg, state):
    nxt = state.next_pending()
    if not nxt: return
    idx = state.done_count + 1
    icon = "🖼" if os.path.splitext(nxt)[1].lower() in CONVERTIBLE_EXTS | {".webp", ".svg"} else "📱"
    await msg.reply_text(f"📥 <b>[{idx}/{state.total}]</b>\n{icon} <code>{nxt}</code>\n\n<i>/cancel</i>",
                         parse_mode="HTML")


async def _ask_owner_or_finalize(update, ctx, state, soup):
    uid = update.effective_user.id if update.effective_user else None
    if not is_admin(uid):
        return await _finalize(update, ctx, state, soup, owner_id=None)
    await update.message.reply_text(
        "👤 <b>مالک پروژه</b>\n\n🆔 ایدی عددی مشتری یا <b>/skip</b> برای خودت:",
        parse_mode="HTML")
    return WAITING_OWNER


async def receive_owner(update, ctx):
    if not is_allowed(update): return ConversationHandler.END
    state = ctx.user_data.get("project")
    if state:
        raw = (update.message.text or "").strip()
        owner_id = None
        if raw.lower() not in ("/skip", "skip", "لغو", "نه", "/cancel"):
            try:
                owner_id = int(re.sub(r"[^\d]", "", raw))
                if owner_id <= 0 or owner_id > 10**15: raise ValueError
            except Exception:
                await update.message.reply_text("❌ ایدی نامعتبر. عدد یا /skip")
                return WAITING_OWNER
        soup, _ = extract_resources(state.html_bytes)
        return await _finalize(update, ctx, state, soup, owner_id=owner_id)
    info = ctx.user_data.pop("owner_edit", None)
    if info:
        pid = info["pid"]; raw = (update.message.text or "").strip()
        if raw.lower() in ("/skip", "skip", "حذف"): owner_id = None
        else:
            try:
                owner_id = int(re.sub(r"[^\d]", "", raw))
                if owner_id <= 0 or owner_id > 10**15: raise ValueError
            except Exception:
                await update.message.reply_text("❌ ایدی نامعتبر")
                ctx.user_data["owner_edit"] = info; return WAITING_OWNER
        try:
            await update_project(pid, {"owner_id": owner_id,
                                       "owner_updated_at": datetime.utcnow().isoformat() + "Z"})
            await update.message.reply_text(
                f"✅ مشتری #{pid} " + (f"= <code>{owner_id}</code>" if owner_id else "حذف شد"),
                parse_mode="HTML")
        except Exception as e: await update.message.reply_text(f"❌ {e}")
        return ConversationHandler.END
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
# APK update
# ═══════════════════════════════════════════════════════════
async def receive_apk(update, ctx):
    uid = update.effective_user.id if update.effective_user else None
    info = ctx.user_data.pop("apk_update", None)
    if not info:
        await update.message.reply_text("درخواست نامعتبر"); return ConversationHandler.END
    pid = info["pid"]; apk_path = info["apk_path"]
    projects = await get_projects()
    project = next((p for p in projects if p.get("id") == pid), None)
    if not project or (project.get("owner_id") != uid and not is_admin(uid)):
        await update.message.reply_text("⛔"); return ConversationHandler.END
    msg = update.message
    if not msg.document:
        await msg.reply_text("⚠️ APK به‌صورت Document بفرست")
        ctx.user_data["apk_update"] = info; return WAITING_APK
    fn = (msg.document.file_name or "").lower()
    if not fn.endswith(".apk"):
        await msg.reply_text("⚠️ باید .apk باشد")
        ctx.user_data["apk_update"] = info; return WAITING_APK
    max_apk = int(CONFIG["upload"].get("max_apk_size_mb", 50))
    if (msg.document.file_size or 0) > max_apk * 1024 * 1024:
        await msg.reply_text(f"❌ حداکثر {max_apk}MB"); return ConversationHandler.END
    f = await msg.document.get_file()
    tmp = Path(tempfile.mkdtemp(prefix="apkupd_")); local = tmp / "new.apk"
    status = await msg.reply_text("⏳ دانلود...")
    try:
        await f.download_to_drive(local)
        await status.edit_text("⏳ آپلود...")
        cpanel = CPanelClient()
        pdir = f"{CONFIG['cpanel']['base_path']}/{pid}"
        rel = os.path.dirname(apk_path); rdir = f"{pdir}/{rel}" if rel else pdir
        if rel: await cpanel.ensure_dir(rdir)
        content = local.read_bytes()
        await cpanel.upload(rdir, os.path.basename(apk_path), content)
        await update_project(pid, {"updated_at": datetime.utcnow().isoformat() + "Z",
                                   "apk_size": len(content)})
        await _update_customer(uid, action="apk_update")
        await status.edit_text(f"✅ <b>آپدیت شد</b>\n\n📦 <code>{apk_path}</code>\n📊 {len(content)//1024} KB",
                                parse_mode="HTML")
    except Exception as e:
        log.exception("apk update fail")
        await status.edit_text(f"❌ <code>{str(e)[:400]}</code>", parse_mode="HTML")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    class _F:
        async def edit_message_text(self, *a, **k): await update.message.reply_text(*a, **k)
    await _show_customer_project(_F(), uid, pid)
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
# Diagnostics
# ═══════════════════════════════════════════════════════════
async def cmd_diag_cb(q):
    await q.edit_message_text("⏳ تست...")
    lines = ["🔧 <b>عیب‌یابی</b>\n"]
    c = CONFIG["cpanel"]
    lines.append(f"🌐 {c['host']}:{c['port']}\n👤 {c['user']}\n🔑 {_mask(c['token'])}\n")
    cpanel = CPanelClient()
    try:
        r = await cpanel._get_raw("Fileman/list_files", {"path": "/public_html", "types": "dir"})
        data, err = _safe_json(r, "list")
        if err: lines.append(f"1) 📂 ❌ {err[:100]}")
        elif data.get("status") == 1: lines.append(f"1) 📂 ✅ ({len(data.get('data') or [])})")
        else: lines.append(f"1) 📂 ❌ status={data.get('status')}")
    except Exception as e: lines.append(f"1) 📂 ❌ {type(e).__name__}")
    for fn in ("counter.txt", "projects.json", "portal_config.json", "customers.json",
               ".counter.txt", ".projects.json", ".portal_config.json", ".customers.json"):
        try:
            content = await cpanel.read(f"/public_html/{fn}")
            sz = len(content) if content else 0
            lines.append(f"📄 {fn}: {'✅ '+str(sz)+'B' if content else '❌ none'}")
        except: lines.append(f"📄 {fn}: ❌")
    try:
        lines.append(f"💾 config keys: {len(await _load_remote_config())}")
        lines.append(f"👥 customers: {len(_customers)}")
    except: pass
    await q.edit_message_text("\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« بازگشت", callback_data="portal:settings")]]))


async def cmd_diag_write_cb(q):
    await q.edit_message_text("⏳ تست write permissions...")
    lines = ["🧪 <b>تست write permissions</b>\n"]
    cpanel = CPanelClient()

    try:
        r = await cpanel._get_raw("Fileman/list_files", {"path": "/public_html", "types": "dir"})
        data, err = _safe_json(r, "list")
        if err: lines.append(f"1️⃣ read: ❌ {err[:100]}")
        elif data.get("status") == 1: lines.append("1️⃣ read: ✅")
        else: lines.append(f"1️⃣ read: ❌ status={data.get('status')}")
    except Exception as e: lines.append(f"1️⃣ read: ❌ {type(e).__name__}")

    try:
        r = await cpanel._post_raw("Fileman/upload_files", data={"dir": "/public_html"},
                                    files={"file-1": ("_wtest1.txt", b"test1")})
        data, err = _safe_json(r, "t1")
        if err: lines.append(f"2️⃣ upload_files: ❌ {err[:100]}")
        elif data.get("status") == 1: lines.append("2️⃣ upload_files: ✅")
        else:
            reason = "?"
            try:
                uploads = (data.get("data") or {}).get("uploads") or []
                if uploads: reason = uploads[0].get("reason") or "?"
            except: pass
            lines.append(f"2️⃣ upload_files: ❌ <code>{str(reason)[:150]}</code>")
    except Exception as e: lines.append(f"2️⃣ upload_files: ❌ {type(e).__name__}")

    try:
        async with cpanel._client(60) as c:
            r = await c.post(f"{cpanel.base}/Fileman/save_file_content",
                             headers=cpanel.headers,
                             data={"dir": "/public_html", "file": "_wtest2.txt", "content": "test2"})
        data, err = _safe_json(r, "t2")
        if err: lines.append(f"3️⃣ save_file_content: ❌ {err[:100]}")
        elif data.get("status") == 1: lines.append("3️⃣ save_file_content: ✅")
        else: lines.append(f"3️⃣ save_file_content: ❌ {str(data.get('errors', '?'))[:150]}")
    except Exception as e: lines.append(f"3️⃣ save_file_content: ❌ {type(e).__name__}")

    try:
        await cpanel._api2("Fileman", "mkdir", path="/public_html", name="_wtestdir")
        lines.append("4️⃣ mkdir: ✅")
    except Exception as e: lines.append(f"4️⃣ mkdir: ❌ {str(e)[:100]}")

    lines.append("\n💡 حالا پروژه بساز — M2 (delete+upload) باید کار کنه")
    await q.edit_message_text("\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("« بازگشت", callback_data="portal:settings")]]))


async def cmd_diag(update, ctx):
    if not is_allowed(update): return
    msg = await update.message.reply_text("⏳")
    class _F:
        async def edit_message_text(self, *a, **k): await msg.edit_text(*a, **k)
    await cmd_diag_cb(_F())


async def cmd_cancel(update, ctx):
    if not update.effective_user: return ConversationHandler.END
    st = ctx.user_data.pop("project", None)
    if st: st.cleanup()
    ctx.user_data.pop("apk_update", None)
    ctx.user_data.pop("owner_edit", None)
    ctx.user_data.pop("setting_edit", None)
    if is_admin(update.effective_user.id):
        await _show_admin_menu(update.message)
    else:
        await update.message.reply_text("لغو شد")
    return ConversationHandler.END


async def hint(update, ctx):
    uid = update.effective_user.id if update.effective_user else None
    if is_admin(uid):
        await update.message.reply_text("از دکمه‌ها استفاده کن")
        return WAITING_HTML if not ctx.user_data.get("project") else WAITING_FILES
    await update.message.reply_text("از /start استفاده کن")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
# Finalize
# ═══════════════════════════════════════════════════════════
async def _finalize(update, ctx, state, soup, owner_id=None):
    msg = await update.message.reply_text("⏳ آپلود...")
    cpanel = CPanelClient(); nx = NxalClient(); step = "init"
    try:
        step = "next_num"
        pid = str(await cpanel.next_project_num())
        state.project_id = pid
        step = "webp"
        pmap = convert_webp(state)
        step = "mkdir"
        pdir = f"{CONFIG['cpanel']['base_path']}/{pid}"
        await cpanel.ensure_dir(pdir)
        step = "upload_files"
        for path_str, local in state.uploaded.items():
            rel = os.path.dirname(path_str); fn = os.path.basename(path_str)
            rdir = f"{pdir}/{rel}" if rel else pdir
            if rel: await cpanel.ensure_dir(rdir)
            await cpanel.upload(rdir, fn, local.read_bytes())
        step = "upload_index"
        base = CONFIG["cpanel"]["public_base_url"].rstrip("/")
        new_html = rewrite_paths(soup, state.resources, pmap, base, pid)
        await cpanel.upload(pdir, "index.html", new_html)
        real = f"{base}/{pid}/index.html"
        step = "shorten"
        short = {}
        try:
            try:
                short = await nx.shorten(real, slug=pid)
                log.info(f"[shorten] pid OK: {pid}")
            except Exception as e1:
                log.info(f"[shorten] pid '{pid}' fail: {str(e1)[:80]} → random")
                for _ in range(3):
                    rand = _gen_short_slug()
                    try:
                        short = await nx.shorten(real, slug=rand)
                        log.info(f"[shorten] random OK: {rand}"); break
                    except Exception: log.info(f"[shorten] '{rand}' fail")
                if not short:
                    try: short = await nx.shorten(real)
                    except Exception as e3: log.warning(f"[shorten] auto: {e3}")
        except Exception as e: log.warning(f"[shorten] outer: {e}")
        if not short or not short.get("shortUrl"):
            log.warning(f"[shorten] {pid} NO short link")
        step = "save_meta"
        projects = await get_projects(force=True)
        projects.append({
            "id": pid, "title": state.metadata.get("TITLE", ""),
            "description": state.metadata.get("DESCRIPTION", ""),
            "real_url": real, "short_url": short.get("shortUrl", "") if short else "",
            "short_id": short.get("id", "") if short else "",
            "slug": short.get("slug", "") if short else "",
            "owner_id": owner_id, "apk_paths": state.apk_paths,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z",
        })
        await save_projects(projects)
    except Exception as e:
        log.exception(f"fail at {step}")
        await msg.edit_text(f"❌ <b>خطا در {step}</b>\n<code>{str(e)[:500]}</code>\n\n<i>⚙️ → 🧪 تست write</i>",
                             parse_mode="HTML")
        state.cleanup(); ctx.user_data.pop("project", None)
        return ConversationHandler.END
    owner_line = f"\n👤 مشتری: <code>{owner_id}</code>" if owner_id else "\n👤 مشتری: —"
    apk_line = f"\n📦 {len(state.apk_paths)} APK" if state.apk_paths else ""
    short_line = (f"🔗 {short.get('shortUrl')}" if short and short.get("shortUrl")
                  else "⚠️ لینک کوتاه ساخته نشد")
    await msg.edit_text(
        f"✅ <b>منتشر شد!</b>\n\n📌 {state.metadata.get('TITLE', '')}"
        f"{owner_line}{apk_line}\n"
        f"🌐 <a href='{real}'>{real}</a>\n{short_line}\n🖼 {len(pmap)} WebP",
        parse_mode="HTML", disable_web_page_preview=True, reply_markup=_admin_menu_kb())
    state.cleanup(); ctx.user_data.pop("project", None)
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════
# Setup
# ═══════════════════════════════════════════════════════════
def setup_application(app):
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("portal", cmd_start),
            CommandHandler("new", cmd_start),
            CallbackQueryHandler(cb_menu, pattern="^portal:new$"),
            CallbackQueryHandler(cb_menu, pattern="^portal:set:edit:"),
            CallbackQueryHandler(cb_menu, pattern="^portal:cust:apk:"),
            CallbackQueryHandler(cb_menu, pattern="^portal:edit_owner:"),
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
            WAITING_SETTING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_setting_value),
                CallbackQueryHandler(cb_menu, pattern="^portal:"),
            ],
            WAITING_OWNER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_owner),
                CommandHandler("skip", receive_owner),
                CallbackQueryHandler(cb_menu, pattern="^portal:"),
            ],
            WAITING_APK: [
                MessageHandler(filters.Document.ALL, receive_apk),
                CallbackQueryHandler(cb_menu, pattern="^portal:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, hint),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
    )
    app.add_handler(conv, group=2)
    app.add_handler(CallbackQueryHandler(cb_menu, pattern="^portal:"), group=2)
    app.add_handler(CommandHandler("diag", cmd_diag), group=2)
    app.add_handler(CommandHandler("settings", cmd_start), group=2)
    return None


def main():
    logging.basicConfig(level=logging.INFO)
    app = Application.builder().token(CONFIG["bot_token"]).build()
    app.add_handler(CommandHandler("start", cmd_start))
    async def _post(app):
        await _load_all_from_cpanel()
    app.post_init = _post
    setup_application(app)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()