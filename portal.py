#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portal bot (V8.3) — رفع باگ دسترسی مشتری به آمار
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
# HOST / CONFIG
# ═══════════════════════════════════════════════════════════
CPANEL_USER = "zcxzgdu"
HOME = f"/home/{CPANEL_USER}"

CONFIG = {
    "bot_token": "8921325744:AAFXRJVzWotsUiZ9yslVpc7NevS2c-8DNnQ",
    "allowed_user_ids": [8389746549],
    "cpanel": {
        "host": "webiksahost.site", "port": "2083",
        "user": CPANEL_USER, "token": "R7C0LL4F49LU3NW42BE3C0S71DOKLBIE",
        "verify_ssl": False,
        "base_path": f"{HOME}/public_html",
        "public_base_url": "https://link8.webiksahost.site",
        "counter_file": f"{HOME}/public_html/counter.txt",
        "projects_file": f"{HOME}/public_html/projects.json",
    },
    "shortener": {
        "enabled": True, "base": "https://nxal.ir",
        "api_key": "nxal_haGkNEVXprw2GCUzNjeP1gh2jUIwqepxPBbKfsuS",
        "slug_prefix": "",
    },
    "upload": {"max_file_size_mb": 20, "max_apk_size_mb": 50, "webp_quality": 82},
}

# ═══════════════════════════════════════════════════════════
# BINARY DETECTION
# ═══════════════════════════════════════════════════════════
BINARY_EXTS = {
    ".apk", ".aab", ".ipa", ".jar", ".war", ".ear",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico", ".tiff", ".tif",
    ".mp3", ".mp4", ".avi", ".mkv", ".mov", ".wav", ".flac", ".ogg", ".m4a",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".iso", ".img", ".dmg",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".class", ".pyc", ".o", ".a",
}

def _is_binary_name(fname: str) -> bool:
    return os.path.splitext(fname.lower())[1] in BINARY_EXTS

PORTAL_DIR = Path(__file__).parent
CFG_LOCAL = PORTAL_DIR / "portal_bootstrap.json"
CFG_REMOTE_PATH = f"{HOME}/public_html/portal_config.json"
CUSTOMERS_REMOTE_PATH = f"{HOME}/public_html/customers.json"

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
        self.host = c["host"].rstrip("/")
        self.port = c["port"]
        self.user = c["user"]
        self.token = c["token"]
        self.verify = c["verify_ssl"]
        scheme = "https" if "://" not in self.host else ""
        self.base = f"{scheme}://{self.host}:{self.port}" if scheme else f"{self.host}:{self.port}"
        self.headers = {
            "Authorization": f"cpanel {self.user}:{self.token}",
            "Accept": "application/json",
        }

    def _client(self, t=30):
        return httpx.AsyncClient(verify=self.verify, timeout=t)

    def _parse(self, r, ctx):
        if r.status_code in (401, 403):
            raise RuntimeError(f"{ctx}: HTTP {r.status_code} access denied")
        if r.status_code >= 400:
            raise RuntimeError(f"{ctx}: HTTP {r.status_code}")
        try:
            data = r.json()
        except Exception:
            text = (r.text or "")[:300]
            raise RuntimeError(f"{ctx}: non-JSON: {text}")

        if "result" in data and isinstance(data["result"], dict):
            res = data["result"]
            if res.get("status") != 1:
                raise RuntimeError(f"{ctx}: {res.get('errors') or 'unknown'}")
            return res.get("data")

        if "cpanelresult" in data:
            res = data["cpanelresult"]
            ev = res.get("event", {}) or {}
            if ev.get("result") != 1:
                raise RuntimeError(f"{ctx}: {ev.get('reason', 'unknown')}")
            return res.get("data")

        if "errors" in data and "data" in data:
            if data["errors"]:
                raise RuntimeError(f"{ctx}: {data['errors']}")
            return data["data"]

        if "status" in data:
            if data["status"] != 1:
                raise RuntimeError(f"{ctx}: {data.get('errors') or data}")
            return data.get("data")

        raise RuntimeError(f"{ctx}: unknown format: {json.dumps(data)[:200]}")

    async def _uapi(self, function, params=None, files=None, ctx=""):
        url = f"{self.base}/execute/Fileman/{function}"
        timeout = 180 if files else 60
        async with self._client(timeout) as c:
            if files:
                r = await c.post(url, headers=self.headers, data=params or {}, files=files)
            elif params and any(len(str(v)) > 500 for v in params.values()):
                r = await c.post(url, headers=self.headers, data=params or {})
            else:
                r = await c.get(url, headers=self.headers, params=params or {})
        return self._parse(r, f"uapi {function}{ctx}")

    async def _api2(self, function, params=None, ctx=""):
        url = f"{self.base}/json-api/cpanel"
        payload = {
            "cpanel_jsonapi_user": self.user,
            "cpanel_jsonapi_apiversion": "2",
            "cpanel_jsonapi_module": "Fileman",
            "cpanel_jsonapi_func": function,
        }
        payload.update(params or {})
        async with self._client(60) as c:
            r = await c.get(url, headers=self.headers, params=payload)
        return self._parse(r, f"api2 {function}{ctx}")

    async def _fileop(self, op, sources, dests=None, destdir=None):
        def _norm(x):
            if isinstance(x, (list, tuple)):
                return json.dumps(list(x))
            return x
        params = {
            "op": op,
            "sourcefiles": _norm(sources),
            "destfiles": _norm(dests or ""),
            "doubledecode": 1,
        }
        if destdir: params["destdir"] = destdir
        data = await self._api2("fileop", params)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("result") == 0:
                    raise RuntimeError(f"fileop {op} fail: {item.get('err', '?')} [src={item.get('src', '?')}]")
        return data

    async def list_files(self, path="/"):
        return await self._uapi("list_files", {"dir": path})

    async def _dir_exists(self, path):
        try:
            data = await self.list_files(path)
            return isinstance(data, list)
        except Exception: return False

    async def ensure_dir(self, full):
        cur = ""
        for part in [p for p in full.split("/") if p]:
            parent = cur or "/"
            cur = f"{cur}/{part}"
            if await self._dir_exists(cur): continue
            try:
                await self._api2("mkdir", {"path": parent, "name": part, "permissions": "0755"})
            except RuntimeError as e:
                if "exist" in str(e).lower(): continue
                raise

    async def _read_raw(self, full_path):
        try:
            if not full_path.startswith("/"):
                return None
            dir_path = os.path.dirname(full_path)
            fname = os.path.basename(full_path)
            data = await self._uapi("get_file_content", {"dir": dir_path, "file": fname})
            if isinstance(data, dict):
                return data.get("content", "")
            return str(data) if data is not None else None
        except Exception: return None

    async def _verify_written(self, full_path, expected, retries=3):
        exp_str = expected.decode("utf-8", errors="replace") if isinstance(expected, bytes) else str(expected)
        min_len = max(1, len(exp_str) // 2)
        for i in range(retries):
            await asyncio.sleep(0.5 + 0.3 * i)
            content = await self._read_raw(full_path)
            if content is not None and len(content) >= min_len:
                log.info(f"[verify_text] {full_path} OK ({len(content)}B)")
                return True
        return False

    async def _verify_exists_with_size(self, rdir, fname, expected_size, retries=3):
        for i in range(retries):
            await asyncio.sleep(0.4 + 0.3 * i)
            try:
                data = await self.list_files(rdir)
                if isinstance(data, list):
                    for item in data:
                        if item.get("file") == fname:
                            actual = int(item.get("size", 0))
                            if actual == expected_size:
                                log.info(f"[verify_bin] {fname} OK ({actual}B)")
                                return True
                            log.warning(
                                f"[verify_bin] {fname} size mismatch: "
                                f"got {actual}B, expected {expected_size}B"
                            )
                            return False
            except Exception as e:
                log.warning(f"[verify_bin] list_files({rdir}) error: {e}")
        return False

    async def _delete_file(self, rdir, fname):
        full = f"{rdir.rstrip('/')}/{fname}"
        try:
            await self._fileop("unlink", sources=full)
            return True
        except Exception: pass
        try:
            await self._uapi("delete_files", {"path": rdir, "files": fname})
            return True
        except Exception: return False

    async def upload(self, rdir, fname, content):
        full_path = f"{rdir.rstrip('/')}/{fname}"
        content_bytes = content.encode("utf-8") if isinstance(content, str) else content
        size = len(content_bytes)
        is_binary = _is_binary_name(fname)
        errors = []

        if not is_binary:
            try:
                text = content_bytes.decode("utf-8", errors="replace")
                await self._uapi("save_file_content", {
                    "dir": rdir, "file": fname, "content": text
                })
                if await self._verify_written(full_path, text):
                    log.info(f"[upload] M1 OK ({size}B): {full_path}")
                    return {"ok": True, "_method": "save_file_content"}
                errors.append("M1:verify_fail")
            except Exception as e:
                errors.append(f"M1:{str(e)[:100]}")

        try:
            result = await self._uapi(
                "upload_files",
                {"dir": rdir, "overwrite": "1"},
                files={"file-1": (fname, content_bytes, "application/octet-stream")},
            )
            if isinstance(result, dict):
                succeeded = int(result.get("succeeded", 0))
                failed = int(result.get("failed", 0))
                log.info(f"[upload M2] server: succeeded={succeeded} failed={failed}")
                if failed > 0:
                    reasons = [
                        (up.get("reason") or "?")
                        for up in (result.get("uploads") or [])
                        if not up.get("status")
                    ]
                    errors.append(f"M2:server_reject ({'; '.join(reasons[:2]) or '?'})")
                else:
                    if is_binary:
                        if await self._verify_exists_with_size(rdir, fname, size):
                            log.info(f"[upload] M2 OK ({size}B binary): {full_path}")
                            return {"ok": True, "_method": "upload_files_binary"}
                    else:
                        if await self._verify_written(full_path, content_bytes.decode("utf-8", errors="replace")):
                            log.info(f"[upload] M2 OK ({size}B text): {full_path}")
                            return {"ok": True, "_method": "upload_files_text"}
                    errors.append("M2:verify_fail")
            else:
                if is_binary:
                    ok = await self._verify_exists_with_size(rdir, fname, size)
                else:
                    ok = await self._verify_written(full_path, content_bytes.decode("utf-8", errors="replace"))
                if ok:
                    log.info(f"[upload] M2 OK (no-status): {full_path}")
                    return {"ok": True, "_method": "upload_files_raw"}
                errors.append("M2:verify_fail")
        except Exception as e:
            errors.append(f"M2:{str(e)[:100]}")

        try:
            await self._delete_file(rdir, fname)
            await asyncio.sleep(0.5)
            await self._uapi(
                "upload_files",
                {"dir": rdir},
                files={"file-1": (fname, content_bytes, "application/octet-stream")},
            )
            if is_binary:
                if await self._verify_exists_with_size(rdir, fname, size):
                    log.info(f"[upload] M3 OK ({size}B binary): {full_path}")
                    return {"ok": True, "_method": "delete+upload_binary"}
            else:
                if await self._verify_written(full_path, content_bytes.decode("utf-8", errors="replace")):
                    log.info(f"[upload] M3 OK ({size}B text): {full_path}")
                    return {"ok": True, "_method": "delete+upload_text"}
            errors.append("M3:verify_fail")
        except Exception as e:
            errors.append(f"M3:{str(e)[:100]}")

        raise RuntimeError(
            f"❌ upload '{full_path}' failed ({size}B):\n" + "\n".join(errors)
        )

    async def read(self, full):
        return await self._read_raw(full)

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
        if not data.get("success"): raise RuntimeError(f"shorten: {data}")
        return data["data"]

    async def stats(self, link_id, days=30):
        if not self.enabled: raise RuntimeError("disabled")
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self.base}/api/v1/links/{link_id}/stats",
                          headers=self.headers, params={"days": days})
        data = r.json()
        if not data.get("success"): raise RuntimeError(f"stats: {data}")
        return data["data"]


# ═══════════════════════════════════════════════════════════
# Config I/O
# ═══════════════════════════════════════════════════════════
async def _load_remote_config() -> dict:
    try:
        cpanel = CPanelClient()
        content = await cpanel.read(CFG_REMOTE_PATH)
        if not content: return {}
        return json.loads(content)
    except Exception as e:
        log.warning(f"load_remote_config: {e}")
        return {}


async def _save_remote_config(overrides: dict) -> bool:
    try:
        cpanel = CPanelClient()
        data = json.dumps(overrides, ensure_ascii=False, indent=2).encode()
        await cpanel.upload(os.path.dirname(CFG_REMOTE_PATH), os.path.basename(CFG_REMOTE_PATH), data)
        return True
    except Exception as e:
        log.error(f"save_remote_config: {e}")
        return False


async def _load_remote_customers() -> dict:
    try:
        cpanel = CPanelClient()
        content = await cpanel.read(CUSTOMERS_REMOTE_PATH)
        if not content: return {}
        return json.loads(content)
    except Exception as e:
        log.warning(f"load_remote_customers: {e}")
        return {}


async def _save_remote_customers(customers: dict) -> bool:
    try:
        cpanel = CPanelClient()
        data = json.dumps(customers, ensure_ascii=False, indent=2).encode()
        await cpanel.upload(os.path.dirname(CUSTOMERS_REMOTE_PATH), os.path.basename(CUSTOMERS_REMOTE_PATH), data)
        return True
    except Exception as e:
        log.error(f"save_remote_customers: {e}")
        return False


async def _load_all_from_cpanel():
    global CONFIG, _customers, _config_loaded
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
    ok = await _save_remote_config(remote)
    if not ok:
        return False, "ذخیره در cPanel ناموفق"
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
        un = getattr(user, "username", "") or ""
        if fn: c["name"] = fn[:40]
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
        _projects_cache["data"] = []; _projects_cache["ts"] = now
        return []
    try:
        d = json.loads(content)
        d = d if isinstance(d, list) else []
        log.info(f"[get_projects] {len(d)} projects")
    except Exception as e:
        log.error(f"[get_projects] JSON fail: {e}")
        d = []
    _projects_cache["data"] = d; _projects_cache["ts"] = now
    return d


async def save_projects(projects):
    cpanel = CPanelClient()
    data = json.dumps(projects, ensure_ascii=False, indent=2).encode()
    p = CONFIG["cpanel"]["projects_file"]
    await cpanel.upload(os.path.dirname(p), os.path.basename(p), data)
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
        [InlineKeyboardButton("📁 محتوای فایل‌ها", callback_data="portal:diag_files")],
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
async def _show_admin_menu(obj):
    if hasattr(obj, "edit_message_text"):
        try: await obj.edit_message_text("🎯 <b>پنل مدیریت</b>", parse_mode="HTML", reply_markup=_admin_menu_kb())
        except Exception: await obj.message.reply_text("🎯 <b>پنل مدیریت</b>", parse_mode="HTML", reply_markup=_admin_menu_kb())
    else:
        await obj.reply_text("🎯 <b>پنل مدیریت</b>", parse_mode="HTML", reply_markup=_admin_menu_kb())


async def _show_settings(q):
    remote_cfg = await _load_remote_config()
    n_cfg = sum(len(v) if isinstance(v, dict) else 1 for v in remote_cfg.values()) if remote_cfg else 0
    txt = (f"⚙️ <b>تنظیمات</b>\n\n"
           f"📁 cPanel: <code>portal_config.json</code> ({n_cfg} کلید)\n"
           f"👥 cPanel: <code>customers.json</code> ({len(_customers)} مشتری)\n\n"
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
        txt += f"<b>#{pid}</b> — {title}\n  👤 {owner or '—'}\n"
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


# ═══════════════════════════════════════════════════════════
# STATS HELPERS
# ═══════════════════════════════════════════════════════════
def _fmt_num(n):
    try: return f"{int(n):,}"
    except: return str(n)


def _render_stats_block(stats_data):
    lines = []
    total  = int(stats_data.get("totalClicks", 0) or 0)
    unique = int(stats_data.get("uniqueClicks", 0) or 0)

    lines.append("┌──────────────────────")
    lines.append(f"│ 👁 <b>بازدید کل:</b>     <code>{_fmt_num(total)}</code>")
    lines.append(f"│ 👤 <b>بازدید یکتا:</b>   <code>{_fmt_num(unique)}</code>")
    if unique > 0:
        avg = total / unique
        lines.append(f"│ 🔁 <b>میانگین تکرار:</b> <code>{avg:.1f}</code> بار/نفر")
    lines.append("└──────────────────────")
    lines.append("")

    countries = stats_data.get("byCountry", [])
    if countries:
        lines.append("🌍 <b>کشورها:</b>")
        total_c = sum(int(c.get("count", 0) or 0) for c in countries) or 1
        for c in countries[:10]:
            n   = int(c.get("count", 0) or 0)
            pct = (n / total_c) * 100
            bar = "█" * max(1, min(20, int(pct / 5)))
            lines.append(f"  • {c.get('name', '?')[:20]}: <code>{_fmt_num(n)}</code> "
                         f"({pct:.1f}%) {bar}")
        lines.append("")

    devices = stats_data.get("byDevice", [])
    if devices:
        dev_icons = {
            "mobile": "📱", "desktop": "💻", "tablet": "📟",
            "bot": "🤖", "smarttv": "📺", "console": "🎮", "unknown": "❓",
        }
        lines.append("📱 <b>دستگاه‌ها:</b>")
        total_d = sum(int(d.get("count", 0) or 0) for d in devices) or 1
        for d in devices[:10]:
            n    = int(d.get("count", 0) or 0)
            pct  = (n / total_d) * 100
            name = d.get("name", "?")
            icon = dev_icons.get(name.lower(), "📱")
            bar  = "█" * max(1, min(20, int(pct / 5)))
            lines.append(f"  {icon} {name[:20]}: <code>{_fmt_num(n)}</code> "
                         f"({pct:.1f}%) {bar}")
        lines.append("")

    browsers = stats_data.get("byBrowser", [])
    if browsers:
        lines.append("🌐 <b>مرورگرها:</b>")
        total_b = sum(int(b.get("count", 0) or 0) for b in browsers) or 1
        for b in browsers[:8]:
            n   = int(b.get("count", 0) or 0)
            pct = (n / total_b) * 100
            lines.append(f"  • {b.get('name', '?')[:20]}: <code>{_fmt_num(n)}</code> ({pct:.1f}%)")
        lines.append("")

    oses = stats_data.get("byOS", []) or stats_data.get("byOs", [])
    if oses:
        lines.append("💻 <b>سیستم‌عامل:</b>")
        total_o = sum(int(o.get("count", 0) or 0) for o in oses) or 1
        for o in oses[:8]:
            n   = int(o.get("count", 0) or 0)
            pct = (n / total_o) * 100
            lines.append(f"  • {o.get('name', '?')[:20]}: <code>{_fmt_num(n)}</code> ({pct:.1f}%)")
        lines.append("")

    refs = stats_data.get("byReferrer", []) or stats_data.get("byRef", [])
    if refs:
        lines.append("🔗 <b>منابع ورودی:</b>")
        total_r = sum(int(r.get("count", 0) or 0) for r in refs) or 1
        for r in refs[:8]:
            n    = int(r.get("count", 0) or 0)
            pct  = (n / total_r) * 100
            name = r.get("name", "?") or "مستقیم"
            if not name or name.lower() in ("direct", "none"): name = "مستقیم"
            lines.append(f"  • {name[:25]}: <code>{_fmt_num(n)}</code> ({pct:.1f}%)")
        lines.append("")

    return "\n".join(lines).rstrip()


async def _show_stats(q, pid, uid):
    try:
        projects = await get_projects()
    except Exception as e:
        log.exception(f"[stats] get_projects failed")
        try: await q.edit_message_text(f"❌ خطا در خواندن پروژه‌ها:\n<code>{str(e)[:200]}</code>", parse_mode="HTML")
        except: pass
        return

    project = next((p for p in projects if p.get("id") == pid), None)
    if not project:
        try: await q.edit_message_text(f"❌ پروژه #{pid} پیدا نشد.")
        except: pass
        return

    admin = is_admin(uid)
    owner_id = project.get("owner_id")
    if not admin and owner_id != uid:
        try: await q.edit_message_text("⛔ این پروژه متعلق به شما نیست.")
        except: pass
        return

    sid = project.get("short_id", "")
    stats_data = None
    stats_err  = None

    if sid:
        try:
            stats_data = await NxalClient().stats(sid, days=30)
        except Exception as e:
            log.warning(f"[stats] nxal: {e}")
            stats_err = str(e)[:200]

    # ── هدر ──
    txt = f"📊 <b>{project.get('title') or f'پروژه #{pid}'}</b>\n\n"
    if admin and owner_id:
        cust = _get_customer(owner_id)
        cn = cust.get("name", "")
        txt += f"👤 مشتری: <code>{owner_id}</code>" + (f" — {cn}" if cn else "") + "\n"
    if project.get("short_url"):
        txt += f"🔗 <a href='{project['short_url']}'>{project['short_url']}</a>\n"
    if project.get("real_url"):
        txt += f"🌐 <a href='{project['real_url']}'>صفحه اصلی</a>\n"
    apks = project.get("apk_paths") or []
    if apks:
        txt += f"📦 APK: <code>{apks[0]}</code>\n"
    created = project.get("created_at", "")
    if created:
        txt += f"📅 تاریخ ساخت: <code>{created[:10]}</code>\n"
    updated = project.get("updated_at", "")
    if updated and updated != created:
        txt += f"🔄 آخرین آپدیت: <code>{updated[:10]}</code>\n"

    txt += "\n" + "─" * 22 + "\n\n"

    # ── بدنه آمار ──
    try:
        if stats_data and "error" not in stats_data:
            txt += _render_stats_block(stats_data)
        elif stats_err:
            txt += f"⚠️ <b>خطا در دریافت آمار</b>\n<code>{stats_err}</code>"
        elif not sid:
            txt += "⚠️ این پروژه لینک کوتاه ندارد، آمار در دسترس نیست."
        else:
            txt += "📭 هنوز بازدیدی ثبت نشده."
    except Exception as e:
        log.exception(f"[stats] render failed")
        txt += f"⚠️ خطا در نمایش آمار: <code>{str(e)[:200]}</code>"

    # ── دکمه‌ها ──
    rows = []
    if project.get("short_url"):
        rows.append([InlineKeyboardButton("🔗 باز کردن لینک کوتاه", url=project["short_url"])])
    if project.get("real_url"):
        rows.append([InlineKeyboardButton("🌐 دیدن صفحه اصلی", url=project["real_url"])])
    if admin:
        rows.append([InlineKeyboardButton(
            f"👤 ایدی مشتری: {owner_id or '—'}",
            callback_data=f"portal:edit_owner:{pid}")])
        rows.append([InlineKeyboardButton(
            "🔄 بروزرسانی آمار",
            callback_data=f"portal:stats:view:{pid}")])
        rows.append([InlineKeyboardButton(
            "« بازگشت به آمار", callback_data="portal:stats:list")])
    else:
        rows.append([InlineKeyboardButton(
            "« بازگشت به پروژه", callback_data=f"portal:cust:view:{pid}")])
        rows.append([InlineKeyboardButton(
            "🏠 پروژه‌های من", callback_data="portal:cust:home")])

    # ── ارسال با fallback ──
    for attempt_txt in (txt, txt[:3900] + "\n\n<i>…</i>"):
        try:
            await q.edit_message_text(
                attempt_txt, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(rows),
                disable_web_page_preview=True)
            return
        except Exception as e:
            log.warning(f"[stats] edit failed: {e}")

    # آخرین تلاش: send_message
    try:
        await q.message.reply_text(
            txt[:3900], parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(rows),
            disable_web_page_preview=True)
    except Exception as e:
        log.error(f"[stats] send failed: {e}")


# ═══════════════════════════════════════════════════════════
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
        log.error(f"[customer_start] err uid={uid}: {e}")
        if str(uid) in _customers:
            try: await update.message.reply_text(f"⚠️ خطا: <code>{str(e)[:150]}</code>", parse_mode="HTML")
            except: pass
            return True
        return False
    if not owned: return False
    try: await _update_customer(uid, user=update.effective_user)
    except: pass
    name = (update.effective_user.first_name or "مشتری")[:40]
    try:
        await update.message.reply_text(
            f"👋 سلام <b>{name}</b>\n\n📱 <b>{len(owned)}</b> پروژه داری:",
            parse_mode="HTML", reply_markup=_customer_home_kb(owned))
    except: pass
    return True


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

    # فقط یک بار answer — برای حذف لودینگ دکمه
    try: await q.answer()
    except: pass

    uid = q.from_user.id if q.from_user else None
    if not uid: return
    d = q.data

    # ── بازگشت به منوی ادمین ──
    if d == "portal:back":
        if not is_admin(uid):
            await q.edit_message_text("⛔ دسترسی ندارید")
            return ConversationHandler.END
        try: await _show_admin_menu(q)
        except: await _show_admin_menu(q.message)
        return ConversationHandler.END

    # ── ساخت پروژه جدید (فقط ادمین) ──
    if d == "portal:new":
        if not is_admin(uid):
            await q.edit_message_text("⛔ دسترسی ندارید")
            return ConversationHandler.END
        await q.edit_message_text("📄 <b>ساخت درگاه جدید</b>\n\nHTML بفرست:",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« لغو", callback_data="portal:back")]]))
        return WAITING_HTML

    # ═══════════════════════════════════════════════════════
    # ★★ مسیرهای مشتری (قبل از چک ادمین) ★★
    # ═══════════════════════════════════════════════════════
    if d == "portal:cust:home":
        await _show_customer_home(q, uid)
        return ConversationHandler.END

    if d.startswith("portal:cust:view:"):
        pid = d.split(":")[-1]
        await _show_customer_project(q, uid, pid)
        return ConversationHandler.END

    # ★★★ این همان چیزی است که قبلاً کار نمی‌کرد ★★★
    if d.startswith("portal:stats:view:"):
        pid = d.split(":")[-1]
        await _show_stats(q, pid, uid)
        return ConversationHandler.END

    if d.startswith("portal:cust:apk:"):
        pid = d.split(":")[-1]
        projects = await get_projects()
        project = next((p for p in projects if p.get("id") == pid), None)
        if not project or (project.get("owner_id") != uid and not is_admin(uid)):
            await q.edit_message_text("⛔ دسترسی ندارید")
            return ConversationHandler.END
        apks = project.get("apk_paths") or []
        if not apks:
            await q.edit_message_text("⚠️ این پروژه APK ندارد")
            return ConversationHandler.END
        ctx.user_data["apk_update"] = {"pid": pid, "apk_path": apks[0]}
        await q.edit_message_text(
            f"📱 <b>آپدیت APK</b>\n\n📦 <code>{apks[0]}</code>\n\nAPK جدید بفرست:",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« لغو", callback_data=f"portal:cust:view:{pid}")]]))
        return WAITING_APK

    # ═══════════════════════════════════════════════════════
    # از این‌جا به بعد فقط ادمین
    # ═══════════════════════════════════════════════════════
    if not is_admin(uid):
        await q.edit_message_text("⛔ دسترسی ندارید")
        return ConversationHandler.END

    if d.startswith("portal:projects:"):
        await _show_admin_projects(q, int(d.split(":")[-1]))
    elif d == "portal:stats:list":
        await _show_stats_list(q)
    elif d == "portal:settings":
        await _show_settings(q)
    elif d.startswith("portal:set:sec:"):
        await _show_section(q, d.split(":")[-1])
    elif d.startswith("portal:set:edit:"):
        parts = d.split(":", 4)
        if len(parts) < 5: return ConversationHandler.END
        section, key = parts[3], parts[4]
        meta = SCHEMA_BY_KEY.get((section, key))
        if not meta: return ConversationHandler.END
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
        except Exception as e:
            await q.edit_message_text(f"❌ {e}")
    elif d == "portal:diag":
        await cmd_diag_cb(q)
    elif d == "portal:diag_write":
        await cmd_diag_write_cb(q)
    elif d == "portal:diag_files":
        await cmd_diag_files_cb(q)
    elif d.startswith("portal:customers:"):
        await _show_customers(q, int(d.split(":")[-1]))
    elif d.startswith("portal:cust:info:"):
        await _show_customer_info(q, int(d.split(":")[-1]))
    elif d.startswith("portal:edit_owner:"):
        pid = d.split(":")[-1]
        projects = await get_projects()
        project = next((p for p in projects if p.get("id") == pid), None)
        if not project: return ConversationHandler.END
        cur = project.get("owner_id") or "—"
        ctx.user_data["owner_edit"] = {"pid": pid}
        await q.edit_message_text(
            f"👤 <b>ویرایش مشتری #{pid}</b>\n\nایدی فعلی: <code>{cur}</code>\n\nایدی جدید (یا /skip):",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« لغو", callback_data=f"portal:stats:view:{pid}")]]))
        return WAITING_OWNER

    return ConversationHandler.END


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
    msg = f"✅ ذخیره\n<b>{lbl}</b> = <code>{show}</code>" if ok else f"⚠️ <b>{lbl}</b> = <code>{show}</code>\n<code>{err}</code>"
    if rst: msg += "\n⚠️ restart لازم"
    await update.message.reply_text(msg, parse_mode="HTML")
    ctx.user_data.pop("setting_edit", None)
    class _F:
        async def edit_message_text(self, *a, **k): await update.message.reply_text(*a, **k)
    await _show_section(_F(), section)
    return ConversationHandler.END


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
async def cmd_diag_cb(q):
    await q.edit_message_text("⏳ تست...")
    lines = ["🔧 <b>عیب‌یابی</b>\n"]
    c = CONFIG["cpanel"]
    lines.append(f"🌐 {c['host']}:{c['port']}\n👤 {c['user']}\n🔑 {_mask(c['token'])}\n")
    cpanel = CPanelClient()
    try:
        data = await cpanel.list_files(HOME)
        lines.append(f"1) 📂 home: ✅ ({len(data) if isinstance(data, list) else '?'} items)")
    except Exception as e: lines.append(f"1) 📂 home: ❌ {str(e)[:80]}")
    for fn in ("counter.txt", "projects.json", "portal_config.json", "customers.json"):
        try:
            content = await cpanel.read(f"{c['base_path']}/{fn}")
            sz = len(content) if content else 0
            lines.append(f"📄 {fn}: {'✅ '+str(sz)+'B' if content else '❌ none'}")
        except: lines.append(f"📄 {fn}: ❌")
    lines.append(f"💾 config: {len(await _load_remote_config())} keys")
    lines.append(f"👥 customers: {len(_customers)}")
    await q.edit_message_text("\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« بازگشت", callback_data="portal:settings")]]))


async def cmd_diag_write_cb(q):
    await q.edit_message_text("⏳ تست write...")
    lines = ["🧪 <b>تست write</b>\n"]
    cpanel = CPanelClient()
    test_name = f"_wtest_{int(time.time())}.txt"
    test_content = f"probe_{int(time.time())}"

    try:
        await cpanel._uapi("save_file_content", {"dir": CONFIG["cpanel"]["base_path"],
                                                   "file": test_name, "content": test_content})
        lines.append("1️⃣ save_file_content: ✅ (تأیید شد)" if await cpanel._verify_written(
            f"{CONFIG['cpanel']['base_path']}/{test_name}", test_content) else "1️⃣ save_file_content: ⚠️ status=1 ولی نوشته نشد")
    except Exception as e: lines.append(f"1️⃣ save_file_content: ❌ {str(e)[:100]}")

    bin_name = f"_wtest_bin_{int(time.time())}.apk"
    bin_content = b"PK\x03\x04FAKE_APK_CONTENT" + b"\x00" * 100
    try:
        await cpanel._uapi("upload_files",
                            {"dir": CONFIG["cpanel"]["base_path"], "overwrite": "1"},
                            files={"file-1": (bin_name, bin_content, "application/octet-stream")})
        ok = await cpanel._verify_exists_with_size(CONFIG["cpanel"]["base_path"], bin_name, len(bin_content))
        lines.append(f"2️⃣ upload_files (binary): {'✅' if ok else '❌ verify fail'}")
        try: await cpanel._fileop("unlink", sources=f"{CONFIG['cpanel']['base_path']}/{bin_name}")
        except: pass
    except Exception as e: lines.append(f"2️⃣ upload_files (binary): ❌ {str(e)[:100]}")

    try:
        await cpanel._fileop("unlink", sources=f"{CONFIG['cpanel']['base_path']}/{test_name}")
        lines.append("3️⃣ fileop unlink: ✅")
    except Exception as e: lines.append(f"3️⃣ fileop unlink: ❌ {str(e)[:100]}")

    await q.edit_message_text("\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("« بازگشت", callback_data="portal:settings")]]))


async def cmd_diag_files_cb(q):
    await q.edit_message_text("⏳ خواندن...")
    import html as _h
    lines = ["📁 <b>محتوای فایل‌ها</b>\n"]
    cpanel = CPanelClient()
    for fn in ("counter.txt", "projects.json", "portal_config.json", "customers.json"):
        try:
            content = await cpanel.read(f"{CONFIG['cpanel']['base_path']}/{fn}")
            if content is None: lines.append(f"❌ <b>{fn}</b>: نیست")
            elif not content.strip(): lines.append(f"⚠️ <b>{fn}</b>: خالی")
            else:
                preview = content[:300].replace("\n", " ")
                lines.append(f"✅ <b>{fn}</b> ({len(content)}B):\n<code>{_h.escape(preview)}</code>")
        except Exception as e:
            lines.append(f"❌ <b>{fn}</b>: {type(e).__name__}")
    await q.edit_message_text("\n\n".join(lines), parse_mode="HTML",
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
                log.info(f"[shorten] pid fail → random")
                for _ in range(3):
                    rand = _gen_short_slug()
                    try:
                        short = await nx.shorten(real, slug=rand)
                        log.info(f"[shorten] random OK: {rand}"); break
                    except: pass
                if not short:
                    try: short = await nx.shorten(real)
                    except Exception as e3: log.warning(f"[shorten] auto: {e3}")
        except Exception as e: log.warning(f"[shorten] outer: {e}")
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
        await msg.edit_text(f"❌ <b>خطا در {step}</b>\n<code>{str(e)[:500]}</code>\n\n<i>⚙️ → 🔧 عیب‌یابی</i>",
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