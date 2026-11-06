"""Admin-editable global settings, per-project settings and an encrypted secret box.

instance/settings.json                 global (Grafana, SMTP, Jira/Bitbucket defaults, links)
instance/project_settings/<p>.json      per project (staff e-mails, Grafana dashboard, Bitbucket repo, shift-left)
instance/confluence.key                 Fernet key used for every stored secret (tokens, SMTP password)
"""
import copy
import json
import os
import re
import threading
import urllib.parse

from cryptography.fernet import Fernet, InvalidToken

from .config import Config, _env

_lock = threading.Lock()
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

DEFAULTS = {
    "app": {"public_url": "http://localhost:8090"},
    "grafana": {
        "url": _env("SR_GRAFANA_URL", ""),              # as the engineers' browser reaches it (SSM forward)
        "dashboard": _env("SR_GRAFANA_DASHBOARD_PATH", ""),  # e.g. /d/<uid>/jmeter-dashboard
        "app_var": "var-application",                   # dashboard variable holding the application
        "extra": "",                                    # e.g. &var-measurement_name=jmeter&orgId=1
    },
    "smtp": {
        "enabled": False, "host": "", "port": 587, "security": "starttls", "user": "", "password_enc": "",
        "from_addr": "", "always_to": "qaperformance@bancobase.com",
        "notify_start": True, "notify_end": True,
    },
    "jira": {"url": ""},
    "bitbucket": {"api": "https://api.bitbucket.org/2.0", "workspace": ""},
}

PROJECT_DEFAULTS = {
    "staff_emails": [],
    "grafana_dashboard": "",
    "jira_project": "",
    "bitbucket_repo": "",          # workspace/repo-slug of the application repository (shift-left)
    "shiftleft": {"tag": "", "threads": 5, "duration": 120, "sla_p95": 1500, "sla_err": 1.0,
                  "base_branch": "", "runner_label": "jmeter-master"},
}


# --------------------------------------------------------------------------- secrets
def _fernet():
    Config.INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    kf = Config.INSTANCE_DIR / "confluence.key"
    if not kf.exists():
        kf.write_bytes(Fernet.generate_key())
        os.chmod(kf, 0o600)
    return Fernet(kf.read_bytes().strip())


def encrypt(value):
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt(token):
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""


# --------------------------------------------------------------------------- storage helpers
def _merge(defaults, data):
    out = copy.deepcopy(defaults)
    for k, v in (data or {}).items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _global_path():
    return Config.INSTANCE_DIR / "settings.json"


def get():
    p = _global_path()
    return _merge(DEFAULTS, json.loads(p.read_text()) if p.exists() else {})


def save(data):
    with _lock:
        _write(_global_path(), _merge(DEFAULTS, data))


def _project_path(project):
    if not re.match(r"^[A-Za-z0-9_\-]+$", project or ""):
        raise ValueError("bad project")
    return Config.INSTANCE_DIR / "project_settings" / f"{project}.json"


def project(name):
    p = _project_path(name)
    return _merge(PROJECT_DEFAULTS, json.loads(p.read_text()) if p.exists() else {})


def save_project(name, data):
    with _lock:
        _write(_project_path(name), _merge(PROJECT_DEFAULTS, data))


def parse_emails(raw):
    emails = []
    for e in re.split(r"[\s,;]+", raw or ""):
        e = e.strip()
        if not e:
            continue
        if not EMAIL_RE.match(e):
            raise ValueError(f"Invalid e-mail: {e}")
        if e.lower() not in (x.lower() for x in emails):
            emails.append(e)
    return emails


def safe_http_url(url, allow_empty=True):
    url = (url or "").strip()
    if not url and allow_empty:
        return ""
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError(f"Invalid URL: {url}")
    return url.rstrip("/")


# --------------------------------------------------------------------------- Grafana
def grafana_link(project_name=None, app=None, start_ms=None, end_ms=None):
    """Deep link to the project's dashboard with the application variable and time range."""
    g = get()["grafana"]
    base = (g.get("url") or "").rstrip("/")
    if not base:
        return ""
    dash = g.get("dashboard") or ""
    if project_name:
        try:
            dash = project(project_name).get("grafana_dashboard") or dash
        except ValueError:
            pass
    if dash.startswith("http://") or dash.startswith("https://"):
        url = dash
    else:
        url = base + ("/" + dash.lstrip("/") if dash else "")
    params = []
    if app and g.get("app_var"):
        params.append(f"{urllib.parse.quote(g['app_var'])}={urllib.parse.quote(app)}")
    if start_ms:
        params.append(f"from={int(start_ms)}")
        params.append(f"to={int(end_ms) if end_ms else 'now'}")
        if not end_ms:
            params.append("refresh=5s")
    extra = (g.get("extra") or "").lstrip("&?")
    if extra:
        params.append(extra)
    if not dash:
        return base
    return url + ("&" if "?" in url else "?") + "&".join(params) if params else url
