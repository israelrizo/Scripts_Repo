"""Per-user Jira and Bitbucket Cloud credentials + minimal REST clients.

Credentials are stored next to the Confluence ones (instance/confluence/<user>.json), encrypted:
  * Jira:      URL + (its own token, or the Confluence token when empty — same Atlassian account on Cloud)
  * Bitbucket: Atlassian e-mail + Bitbucket API token (scopes: read/write repository, write pull requests)
"""
import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import confluence, settings

ISSUE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,19}-\d{1,9}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}/[A-Za-z0-9_.\-]{1,128}$")


class AtlassianError(RuntimeError):
    pass


def _http(method, url, auth, body=None, headers=None, timeout=60):
    h = {"Authorization": auth, "Accept": "application/json"}
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
        detail = exc.read().decode(errors="replace")[:500]
        try:
            j = json.loads(detail)
            detail = (j.get("errorMessages") or [None])[0] or j.get("error", {}).get("message") \
                or j.get("message") or json.dumps(j.get("errors") or j)[:300]
        except (ValueError, AttributeError):
            pass
        raise AtlassianError(f"HTTP {exc.code}: {detail}")
    except (urllib.error.URLError, OSError) as exc:
        raise AtlassianError(f"Cannot reach {urllib.parse.urlparse(url).netloc}: {exc}")


# --------------------------------------------------------------------------- credentials
def get(username):
    s = confluence.get_settings(username) or {}
    return {
        "jira_url": s.get("jira_url", ""), "has_jira_token": bool(s.get("jira_token_enc")),
        "bb_user": s.get("bb_user", ""), "has_bb_token": bool(s.get("bb_token_enc")),
        "has_confluence": bool(s.get("has_token")),
    }


def save(username, jira_url, jira_token, bb_user, bb_token):
    path = confluence._settings_path(username)
    data = json.loads(path.read_text()) if path.exists() else {}
    if jira_url:
        data["jira_url"] = confluence.validate_base_url(jira_url)
    else:
        data.pop("jira_url", None)
    if jira_token:
        data["jira_token_enc"] = settings.encrypt(jira_token.strip())
    data["bb_user"] = (bb_user or "").strip()
    if bb_token:
        data["bb_token_enc"] = settings.encrypt(bb_token.strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)


def _raw(username):
    path = confluence._settings_path(username)
    return json.loads(path.read_text()) if path.exists() else {}


# --------------------------------------------------------------------------- Jira
class Jira:
    def __init__(self, username):
        raw = _raw(username)
        self.base = raw.get("jira_url") or settings.get()["jira"].get("url") or ""
        if not self.base:
            raise AtlassianError("Jira URL not configured (Account → Atlassian)")
        self.base = confluence.validate_base_url(self.base)
        token = settings.decrypt(raw.get("jira_token_enc", "")) or \
            (confluence.get_settings(username, with_token=True) or {}).get("token", "")
        if not token:
            raise AtlassianError("No Jira/Confluence token stored for this user")
        if raw.get("auth_type", "cloud") == "pat":
            self.auth = "Bearer " + token
        else:
            self.auth = "Basic " + base64.b64encode(f"{raw.get('account', '')}:{token}".encode()).decode()

    def issue(self, key):
        if not ISSUE_RE.match(key or ""):
            raise AtlassianError(f"Invalid Jira key '{key}'")
        j = _http("GET", f"{self.base}/rest/api/2/issue/{key}?fields=summary,status", self.auth)
        return {"key": j.get("key"), "summary": j.get("fields", {}).get("summary"),
                "status": j.get("fields", {}).get("status", {}).get("name"),
                "url": f"{self.base}/browse/{j.get('key')}"}

    def comment(self, key, text):
        if not ISSUE_RE.match(key or ""):
            raise AtlassianError(f"Invalid Jira key '{key}'")
        return _http("POST", f"{self.base}/rest/api/2/issue/{key}/comment", self.auth, {"body": text[:30000]})


# --------------------------------------------------------------------------- Bitbucket Cloud
class Bitbucket:
    def __init__(self, username):
        raw = _raw(username)
        token = settings.decrypt(raw.get("bb_token_enc", ""))
        user = raw.get("bb_user") or raw.get("account", "")
        if not token or not user:
            raise AtlassianError("Bitbucket credentials not configured (Account → Atlassian)")
        self.api = settings.get()["bitbucket"].get("api", "https://api.bitbucket.org/2.0").rstrip("/")
        self.auth = "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()

    def _repo(self, full):
        if not REPO_RE.match(full or ""):
            raise AtlassianError("Repository must be <workspace>/<repo-slug>")
        ws, slug = full.split("/", 1)
        return f"{self.api}/repositories/{urllib.parse.quote(ws)}/{urllib.parse.quote(slug)}"

    def repo(self, full):
        j = _http("GET", self._repo(full), self.auth)
        return {"full_name": j.get("full_name"), "main": (j.get("mainbranch") or {}).get("name", "main"),
                "url": j.get("links", {}).get("html", {}).get("href")}

    def file_exists(self, full, branch, path):
        try:
            _http("GET", f"{self._repo(full)}/src/{urllib.parse.quote(branch)}/{path}?format=meta", self.auth)
            return True
        except AtlassianError as exc:
            if "404" in str(exc):
                return False
            raise

    def commit_files(self, full, branch, parent_branch, message, files):
        """Create/overwrite files on `branch` (created from parent_branch when missing)."""
        boundary = uuid.uuid4().hex
        parts = []

        def field(name, value, filename=None):
            disp = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
            parts.append(f"--{boundary}\r\nContent-Disposition: {disp}\r\n\r\n".encode())
            parts.append(value if isinstance(value, bytes) else value.encode())
            parts.append(b"\r\n")

        head = _http("GET", f"{self._repo(full)}/refs/branches/{urllib.parse.quote(parent_branch)}", self.auth)
        field("message", message)
        field("branch", branch)
        field("parents", head["target"]["hash"])
        for path, content in files.items():
            field(path, content.encode() if isinstance(content, str) else content, filename=path.split("/")[-1])
        parts.append(f"--{boundary}--\r\n".encode())
        return _http("POST", f"{self._repo(full)}/src", self.auth, b"".join(parts),
                     {"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def pull_request(self, full, source, destination, title, description):
        j = _http("POST", f"{self._repo(full)}/pullrequests", self.auth, {
            "title": title, "description": description, "close_source_branch": True,
            "source": {"branch": {"name": source}}, "destination": {"branch": {"name": destination}}})
        return j.get("links", {}).get("html", {}).get("href")
