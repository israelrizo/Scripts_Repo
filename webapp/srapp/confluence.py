"""Per-user Confluence connection settings (token encrypted at rest) and a minimal REST client.

Works with Confluence Cloud (email + API token, Basic auth) and Server/Data Center
(Personal Access Token, Bearer auth) through the REST v1 content API, available on both.
"""
import base64
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid

from cryptography.fernet import Fernet, InvalidToken

from .config import Config, _bool, _env

# Comma separated host suffixes the server may call, e.g. ".atlassian.net,confluence.bancobase.com".
ALLOWED_HOSTS = [h.strip().lower() for h in _env("SR_CONFLUENCE_ALLOWED_HOSTS", "").split(",") if h.strip()]
ALLOW_HTTP = _bool("SR_CONFLUENCE_ALLOW_HTTP", False)  # only for local testing
SPACE_RE = re.compile(r"^[A-Za-z0-9_~\-]{1,255}$")
_lock = threading.Lock()


class ConfluenceError(RuntimeError):
    pass


# --------------------------------------------------------------------------- encryption
def _fernet():
    Config.INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    kf = Config.INSTANCE_DIR / "confluence.key"
    if not kf.exists():
        kf.write_bytes(Fernet.generate_key())
        os.chmod(kf, 0o600)
    return Fernet(kf.read_bytes().strip())


def _settings_dir():
    d = Config.INSTANCE_DIR / "confluence"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _settings_path(username):
    if not re.match(r"^[a-zA-Z0-9._-]{3,32}$", username or ""):
        raise ConfluenceError("bad user")
    return _settings_dir() / f"{username}.json"


# --------------------------------------------------------------------------- settings
def validate_base_url(url):
    url = (url or "").strip().rstrip("/")
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("https",) + (("http",) if ALLOW_HTTP else ()):
        raise ConfluenceError("Confluence URL must start with https://")
    host = (p.hostname or "").lower()
    if not host or p.username or p.password:
        raise ConfluenceError("Invalid Confluence URL")
    if ALLOWED_HOSTS and not any(host == h.lstrip(".") or host.endswith(h if h.startswith(".") else "." + h)
                                 for h in ALLOWED_HOSTS):
        raise ConfluenceError(f"Host {host} is not allowed (SR_CONFLUENCE_ALLOWED_HOSTS)")
    return url


def get_settings(username, with_token=False):
    p = _settings_path(username)
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    token_enc = data.pop("token_enc", None)
    data["has_token"] = bool(token_enc)
    if with_token and token_enc:
        try:
            data["token"] = _fernet().decrypt(token_enc.encode()).decode()
        except InvalidToken:
            raise ConfluenceError("Stored token cannot be decrypted (key changed). Save it again.")
    return data


def save_settings(username, base_url, auth_type, account, token, space_key, parent_id):
    base_url = validate_base_url(base_url)
    if auth_type not in ("cloud", "pat"):
        raise ConfluenceError("Auth type must be cloud or pat")
    if auth_type == "cloud" and "@" not in (account or ""):
        raise ConfluenceError("Confluence Cloud needs the Atlassian account e-mail")
    space_key = (space_key or "").strip()
    if space_key and not SPACE_RE.match(space_key):
        raise ConfluenceError("Invalid space key")
    parent_id = (parent_id or "").strip()
    if parent_id and not parent_id.isdigit():
        raise ConfluenceError("Parent page id must be numeric (it is in the page URL)")
    with _lock:
        p = _settings_path(username)
        old = json.loads(p.read_text()) if p.exists() else {}
        data = {"base_url": base_url, "auth_type": auth_type, "account": (account or "").strip(),
                "space_key": space_key, "parent_id": parent_id}
        if token:
            data["token_enc"] = _fernet().encrypt(token.strip().encode()).decode()
            data["token_hint"] = "…" + token.strip()[-4:]
        else:
            data["token_enc"] = old.get("token_enc")
            data["token_hint"] = old.get("token_hint")
        if not data["token_enc"]:
            raise ConfluenceError("API token is required")
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(p)


def delete_settings(username):
    _settings_path(username).unlink(missing_ok=True)


# --------------------------------------------------------------------------- client
class Client:
    def __init__(self, settings):
        self.base = validate_base_url(settings["base_url"])
        if settings["auth_type"] == "cloud":
            raw = f"{settings['account']}:{settings['token']}".encode()
            self.auth = "Basic " + base64.b64encode(raw).decode()
        else:
            self.auth = "Bearer " + settings["token"]

    @classmethod
    def for_user(cls, username):
        s = get_settings(username, with_token=True)
        if not s or not s.get("token"):
            raise ConfluenceError("Configure your Confluence connection first (Account → Confluence)")
        return cls(s)

    def _req(self, method, path, body=None, headers=None, timeout=60):
        url = self.base + path
        h = {"Authorization": self.auth, "Accept": "application/json"}
        h.update(headers or {})
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            try:
                detail = json.loads(detail).get("message", detail)
            except ValueError:
                pass
            hint = {401: " (check e-mail/token)", 403: " (no permission in that space)",
                    404: " (wrong URL, space or page id)"}.get(exc.code, "")
            raise ConfluenceError(f"Confluence {exc.code}{hint}: {detail}")
        except (urllib.error.URLError, OSError) as exc:
            raise ConfluenceError(f"Cannot reach {self.base}: {exc}. Does the Master have egress/proxy (HTTPS_PROXY)?")

    # -- API
    def whoami(self):
        u = self._req("GET", "/rest/api/user/current")
        return u.get("displayName") or u.get("username") or u.get("publicName") or "?"

    def space(self, key):
        if not SPACE_RE.match(key or ""):
            raise ConfluenceError("Invalid space key")
        return self._req("GET", f"/rest/api/space/{urllib.parse.quote(key)}")

    def get_page(self, page_id):
        return self._req("GET", f"/rest/api/content/{int(page_id)}?expand=version,space")

    def find_page(self, space_key, title):
        q = urllib.parse.urlencode({"spaceKey": space_key, "title": title, "expand": "version"})
        res = self._req("GET", f"/rest/api/content?{q}").get("results", [])
        return res[0] if res else None

    def create_page(self, space_key, title, storage, parent_id=None):
        body = {"type": "page", "title": title, "space": {"key": space_key},
                "body": {"storage": {"value": storage, "representation": "storage"}}}
        if parent_id:
            body["ancestors"] = [{"id": str(parent_id)}]
        return self._req("POST", "/rest/api/content", body)

    def update_page(self, page_id, title, storage):
        current = self.get_page(page_id)
        body = {"id": str(page_id), "type": "page", "title": title,
                "version": {"number": current["version"]["number"] + 1, "message": "Updated by JMeter Control Center"},
                "body": {"storage": {"value": storage, "representation": "storage"}}}
        return self._req("PUT", f"/rest/api/content/{int(page_id)}", body)

    def put_attachment(self, page_id, filename, data, content_type):
        """Create or update (new version) an attachment with this file name."""
        boundary = uuid.uuid4().hex
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n".encode(), data, b"\r\n",
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"minorEdit\"\r\n\r\ntrue\r\n".encode(),
            f"--{boundary}--\r\n".encode(),
        ]
        return self._req("PUT", f"/rest/api/content/{int(page_id)}/child/attachment", b"".join(parts),
                         {"Content-Type": f"multipart/form-data; boundary={boundary}",
                          "X-Atlassian-Token": "no-check"}, timeout=300)

    def page_url(self, page):
        links = page.get("_links", {})
        base = links.get("base") or self.base
        return base + links.get("webui", f"/pages/viewpage.action?pageId={page.get('id')}")
