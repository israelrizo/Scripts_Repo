"""Google integration for the engineer who runs the app on their computer:

* Gmail  — OAuth 2.0 (authorization-code flow, loopback redirect) with the single scope gmail.send:
           the app can send e-mail as the linked account, it cannot read the mailbox.
* Chat   — incoming webhooks of Google Chat spaces (a global default list + extra spaces per project).
"""
import base64
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import settings
from .config import _env

AUTH_URL = _env("SR_GOOGLE_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")
TOKEN_URL = _env("SR_GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")
USERINFO_URL = _env("SR_GOOGLE_USERINFO_URL", "https://openidconnect.googleapis.com/v1/userinfo")
GMAIL_SEND_URL = _env("SR_GMAIL_SEND_URL", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
CHAT_HOSTS = [h for h in _env("SR_CHAT_HOSTS", "chat.googleapis.com").split(",") if h]
SCOPES = "https://www.googleapis.com/auth/gmail.send openid email"
_token_cache = {"value": None, "exp": 0}


class GoogleError(RuntimeError):
    pass


def _post(url, data=None, headers=None, json_body=None, timeout=40):
    body = json.dumps(json_body).encode() if json_body is not None else urllib.parse.urlencode(data or {}).encode()
    h = {"Content-Type": "application/json; charset=UTF-8" if json_body is not None
         else "application/x-www-form-urlencoded"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, method="POST", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        try:
            j = json.loads(detail)
            err = j.get("error")
            detail = j.get("error_description") or (err.get("message") if isinstance(err, dict) else err) or detail
        except (ValueError, AttributeError):
            pass
        raise GoogleError(f"Google HTTP {exc.code}: {detail}")
    except (urllib.error.URLError, OSError) as exc:
        raise GoogleError(f"Cannot reach Google: {exc}")


# --------------------------------------------------------------------------- OAuth
def redirect_uri():
    return settings.get()["app"]["public_url"].rstrip("/") + "/oauth/google/callback"


def linked():
    g = settings.get()["google"]
    return {"email": g.get("email", ""), "linked": bool(g.get("refresh_enc")), "client_id": g.get("client_id", ""),
            "has_secret": bool(g.get("client_secret_enc"))}


def auth_url(state):
    g = settings.get()["google"]
    if not g.get("client_id") or not g.get("client_secret_enc"):
        raise GoogleError("Save the OAuth client ID and secret first")
    params = {"client_id": g["client_id"], "redirect_uri": redirect_uri(), "response_type": "code",
              "scope": SCOPES, "access_type": "offline", "prompt": "consent", "state": state}
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def new_state():
    return secrets.token_urlsafe(24)


def exchange(code):
    cfg = settings.get()
    g = cfg["google"]
    tok = _post(TOKEN_URL, {"code": code, "client_id": g["client_id"],
                            "client_secret": settings.decrypt(g["client_secret_enc"]),
                            "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})
    if not tok.get("refresh_token"):
        raise GoogleError("Google did not return a refresh token; remove the app access in your Google account "
                          "(Security → Third-party access) and link again")
    email = ""
    try:
        req = urllib.request.Request(USERINFO_URL, headers={"Authorization": f"Bearer {tok['access_token']}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            email = json.loads(resp.read()).get("email", "")
    except (urllib.error.URLError, OSError, ValueError):
        pass
    g["refresh_enc"] = settings.encrypt(tok["refresh_token"])
    g["email"] = email
    settings.save(cfg)
    _token_cache.update(value=tok.get("access_token"), exp=time.time() + int(tok.get("expires_in", 3000)) - 60)
    return email


def unlink():
    cfg = settings.get()
    cfg["google"]["refresh_enc"] = ""
    cfg["google"]["email"] = ""
    settings.save(cfg)
    _token_cache.update(value=None, exp=0)


def access_token():
    if _token_cache["value"] and time.time() < _token_cache["exp"]:
        return _token_cache["value"]
    g = settings.get()["google"]
    if not g.get("refresh_enc"):
        raise GoogleError("Gmail account not linked (Settings → E-mail)")
    tok = _post(TOKEN_URL, {"refresh_token": settings.decrypt(g["refresh_enc"]), "client_id": g["client_id"],
                            "client_secret": settings.decrypt(g["client_secret_enc"]),
                            "grant_type": "refresh_token"})
    _token_cache.update(value=tok["access_token"], exp=time.time() + int(tok.get("expires_in", 3000)) - 60)
    return tok["access_token"]


def send_gmail(mime_bytes):
    raw = base64.urlsafe_b64encode(mime_bytes).decode()
    return _post(GMAIL_SEND_URL, json_body={"raw": raw}, headers={"Authorization": f"Bearer {access_token()}"},
                 timeout=120)


# --------------------------------------------------------------------------- Google Chat
def validate_webhook(url):
    p = urllib.parse.urlparse((url or "").strip())
    if p.scheme != "https" and not _env("SR_CHAT_ALLOW_HTTP"):
        raise GoogleError("Webhook must be an https:// URL")
    if (p.hostname or "") not in CHAT_HOSTS or "/spaces/" not in p.path:
        raise GoogleError("Not a Google Chat webhook (space → Apps & integrations → Webhooks → copy the URL)")
    return url.strip()


def spaces():
    """[{id, name, default}] without the secret URLs."""
    return [{"id": s["id"], "name": s["name"], "default": bool(s.get("default"))}
            for s in settings.get()["chat"]["spaces"]]


def add_space(name, url, default):
    cfg = settings.get()
    name = (name or "").strip()[:40]
    if not name:
        raise GoogleError("Give the space a name")
    cfg["chat"]["spaces"].append({"id": uuid.uuid4().hex[:8], "name": name,
                                  "url_enc": settings.encrypt(validate_webhook(url)), "default": bool(default)})
    settings.save(cfg)


def update_space(space_id, default=None, delete=False):
    cfg = settings.get()
    items = cfg["chat"]["spaces"]
    if delete:
        items = [s for s in items if s["id"] != space_id]
    else:
        for s in items:
            if s["id"] == space_id and default is not None:
                s["default"] = bool(default)
    cfg["chat"]["spaces"] = items
    settings.save(cfg)


def chat_targets(project=None):
    """Spaces to notify for a project: every default space + the project's extra spaces."""
    cfg = settings.get()
    extra = set()
    if project:
        try:
            extra = set(settings.project(project).get("chat_spaces") or [])
        except ValueError:
            pass
    return [s for s in cfg["chat"]["spaces"] if s.get("default") or s["id"] in extra]


def send_chat(space, payload, thread_key=None):
    url = settings.decrypt(space["url_enc"])
    if thread_key:
        payload = dict(payload, thread={"threadKey": thread_key})
        url += ("&" if "?" in url else "?") + "messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
    return _post(url, json_body=payload)
