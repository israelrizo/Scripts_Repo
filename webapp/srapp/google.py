"""Google Chat for the engineer who runs the app on their computer: incoming webhooks of Google Chat spaces
(a global default list + extra spaces per project). E-mail goes through SMTP (Gmail: smtp.gmail.com with an
App Password of the engineer's own account), see notify.send."""
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import settings
from .config import _env

CHAT_HOSTS = [h for h in _env("SR_CHAT_HOSTS", "chat.googleapis.com").split(",") if h]


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
    return [{"id": s["id"], "name": s["name"], "default": bool(s.get("default")), "shared": bool(s.get("shared"))}
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
