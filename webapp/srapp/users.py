"""File-backed user store (instance/users.json) with hashed passwords and 3 roles.

Roles:
  admin    - everything, plus user management and project creation
  operator - upload scripts/data, register tags, launch and stop runs
  viewer   - browse projects, tags and reports only
"""
import json
import os
import re
import threading
import time

from werkzeug.security import check_password_hash, generate_password_hash

from .config import Config

ROLES = ("admin", "operator", "viewer")
ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}
USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,32}$")
MIN_PASSWORD = 10
# pbkdf2 works on every Python build (scrypt needs OpenSSL 1.1+, missing on some AMIs/macOS)
HASH_METHOD = "pbkdf2:sha256:600000"

_lock = threading.Lock()


def _path():
    return Config.INSTANCE_DIR / "users.json"


def _load():
    p = _path()
    if not p.exists():
        return {}
    with p.open() as fh:
        return json.load(fh)


def _save(data):
    Config.INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    with tmp.open("w") as fh:
        json.dump(data, fh, indent=2)
    os.chmod(tmp, 0o600)
    tmp.replace(_path())


def list_users():
    return [{"username": u, "role": d.get("role"), "created": d.get("created"), "email": d.get("email", ""),
             "has_2fa": bool(d.get("totp_enc")), "tokens": len(d.get("api_tokens", []))}
            for u, d in sorted(_load().items())]


def get(username):
    return _load().get(username)


def count():
    return len(_load())


def validate_password(password):
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Password must have at least {MIN_PASSWORD} characters")


def create(username, password, role):
    if not USERNAME_RE.match(username or ""):
        raise ValueError("Username: 3-32 chars, letters, digits, '.', '_' or '-'")
    if role not in ROLES:
        raise ValueError(f"Role must be one of {', '.join(ROLES)}")
    validate_password(password)
    with _lock:
        data = _load()
        if username in data:
            raise ValueError("User already exists")
        data[username] = {"password": generate_password_hash(password, method=HASH_METHOD), "role": role,
                          "created": int(time.time())}
        _save(data)


def set_password(username, password):
    validate_password(password)
    with _lock:
        data = _load()
        if username not in data:
            raise ValueError("Unknown user")
        data[username]["password"] = generate_password_hash(password, method=HASH_METHOD)
        _save(data)


def set_role(username, role):
    if role not in ROLES:
        raise ValueError("Invalid role")
    with _lock:
        data = _load()
        if username not in data:
            raise ValueError("Unknown user")
        if data[username]["role"] == "admin" and role != "admin" and _admins(data) == 1:
            raise ValueError("Cannot demote the last admin")
        data[username]["role"] = role
        _save(data)


def delete(username):
    with _lock:
        data = _load()
        if username not in data:
            raise ValueError("Unknown user")
        if data[username]["role"] == "admin" and _admins(data) == 1:
            raise ValueError("Cannot delete the last admin")
        del data[username]
        _save(data)


def _admins(data):
    return sum(1 for d in data.values() if d.get("role") == "admin")


def authenticate(username, password):
    user = get(username or "")
    if not user:
        # constant-ish time: still run a hash check
        check_password_hash(generate_password_hash("x", method=HASH_METHOD), password or "")
        return None
    return user if check_password_hash(user["password"], password or "") else None


# --------------------------------------------------------------------------- profile / 2FA / API tokens
def _update(username, fn):
    with _lock:
        data = _load()
        if username not in data:
            raise ValueError("Unknown user")
        fn(data[username])
        _save(data)


def set_email(username, email):
    email = (email or "").strip()
    if email and not re.match(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$", email):
        raise ValueError("Invalid e-mail")
    _update(username, lambda u: u.__setitem__("email", email))


def set_totp(username, secret_enc):
    def fn(u):
        u["totp_enc"] = secret_enc
        u["totp_last"] = None
    _update(username, fn)


def clear_totp(username):
    def fn(u):
        u.pop("totp_enc", None)
        u.pop("totp_last", None)
    _update(username, fn)


def set_totp_last(username, counter):
    _update(username, lambda u: u.__setitem__("totp_last", counter))


def add_api_token(username, name):
    import hashlib
    import secrets as _s
    token = "jmcc_" + _s.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()

    def fn(u):
        u.setdefault("api_tokens", [])
        if len(u["api_tokens"]) >= 10:
            raise ValueError("Max 10 tokens per user")
        u["api_tokens"].append({"id": digest[:12], "name": (name or "ci")[:40], "sha256": digest,
                                "created": int(time.time()), "last_used": None})
    _update(username, fn)
    return token


def delete_api_token(username, token_id):
    _update(username, lambda u: u.__setitem__("api_tokens", [t for t in u.get("api_tokens", []) if t["id"] != token_id]))


def user_by_token(token):
    import hashlib
    import hmac as _h
    if not (token or "").startswith("jmcc_"):
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    with _lock:
        data = _load()
        for name, u in data.items():
            for t in u.get("api_tokens", []):
                if _h.compare_digest(t["sha256"], digest):
                    t["last_used"] = int(time.time())
                    _save(data)
                    return {"username": name, "role": u["role"]}
    return None
