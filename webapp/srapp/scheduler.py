"""Scheduled executions (one-time, daily, weekly) stored in instance/schedules.json.

A background thread checks every 20 s. When a slot is due and the generator is busy it keeps
retrying for RETRY_MINUTES, then records the slot as skipped. Runs are launched as the user who
created the schedule (Jira comments use that user's token).
"""
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from . import projects, runner, settings
from .config import Config, _env

RETRY_MINUTES = 30
DAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
_lock = threading.Lock()
_thread = None


def tz():
    name = settings.get()["app"].get("timezone") or _env("SR_TIMEZONE", "America/Mexico_City")
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        return None


def now():
    z = tz()
    return datetime.now(z) if z else datetime.now().astimezone()


def _path():
    return Config.INSTANCE_DIR / "schedules.json"


def load():
    p = _path()
    return json.loads(p.read_text()) if p.exists() else []


def _save(items):
    Config.INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    tmp.replace(_path())


def _parse_time(hhmm):
    if not re.match(r"^\d{2}:\d{2}$", hhmm or ""):
        raise ValueError("Time must be HH:MM")
    h, m = map(int, hhmm.split(":"))
    if h > 23 or m > 59:
        raise ValueError("Invalid time")
    return h, m


def _occurrence_before(s, ref):
    """Most recent scheduled datetime <= ref (aware), or None."""
    h, m = _parse_time(s["at"])
    if s["kind"] == "once":
        d = datetime.strptime(s["date"], "%Y-%m-%d").replace(hour=h, minute=m, tzinfo=ref.tzinfo)
        return d if d <= ref else None
    for back in range(0, 8):
        d = (ref - timedelta(days=back)).replace(hour=h, minute=m, second=0, microsecond=0)
        if d > ref:
            continue
        if s["kind"] == "daily" or d.weekday() in s.get("days", []):
            return d
    return None


def next_run(s, ref=None):
    ref = ref or now()
    if not s.get("enabled"):
        return None
    h, m = _parse_time(s["at"])
    if s["kind"] == "once":
        d = datetime.strptime(s["date"], "%Y-%m-%d").replace(hour=h, minute=m, tzinfo=ref.tzinfo)
        return d if d > ref or not s.get("last_fired") else None
    for fwd in range(0, 8):
        d = (ref + timedelta(days=fwd)).replace(hour=h, minute=m, second=0, microsecond=0)
        if d <= ref:
            continue
        if s["kind"] == "daily" or d.weekday() in s.get("days", []):
            return d
    return None


def describe(s):
    if s["kind"] == "once":
        return f"Una vez · {s['date']} {s['at']}"
    if s["kind"] == "daily":
        return f"Diario · {s['at']}"
    return "Semanal · " + ", ".join(DAYS[d] for d in sorted(s.get("days", []))) + f" · {s['at']}"


def create(user, project, tag, kind, at, date="", days=None, props="", distributed=False, jira="",
           notes="", extra_emails=None):
    projects.project_dir(project)
    t = projects.get_tag(project, tag)
    if not t or not t["exists"]:
        raise ValueError("Unknown tag or missing script")
    projects.validate_prop_args(props)
    _parse_time(at)
    if kind not in ("once", "daily", "weekly"):
        raise ValueError("Invalid schedule type")
    if kind == "once":
        try:
            when = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Date must be YYYY-MM-DD")
        h, m = _parse_time(at)
        if when.replace(hour=h, minute=m, tzinfo=now().tzinfo) <= now():
            raise ValueError("That date/time is in the past")
    days = sorted({int(d) for d in (days or []) if str(d).isdigit() and 0 <= int(d) <= 6})
    if kind == "weekly" and not days:
        raise ValueError("Pick at least one weekday")
    if jira and not runner.ISSUE_RE.match(jira.strip().upper()):
        raise ValueError("Invalid Jira ticket")
    item = {"id": uuid.uuid4().hex[:10], "project": project, "tag": tag, "kind": kind, "at": at, "date": date,
            "days": days, "props": props.strip(), "distributed": bool(distributed), "jira": jira.strip().upper(),
            "notes": notes.strip()[:500], "extra_emails": list(extra_emails or []), "enabled": True,
            "created_by": user, "created": time.time(), "last_fired": None, "history": []}
    with _lock:
        items = load()
        items.append(item)
        _save(items)
    return item


def update(sid, **changes):
    with _lock:
        items = load()
        for s in items:
            if s["id"] == sid:
                s.update(changes)
                _save(items)
                return s
    raise ValueError("Unknown schedule")


def delete(sid):
    with _lock:
        items = [s for s in load() if s["id"] != sid]
        _save(items)


def _record(s, slot, result):
    s["last_fired"] = slot.isoformat()
    s["history"] = ([{"slot": slot.isoformat(), "result": result, "at": time.time()}] + s.get("history", []))[:20]
    if s["kind"] == "once":
        s["enabled"] = False


def tick():
    ref = now()
    with _lock:
        items = load()
        changed = False
        for s in items:
            if not s.get("enabled"):
                continue
            try:
                slot = _occurrence_before(s, ref)
            except ValueError:
                continue
            if not slot:
                continue
            last = datetime.fromisoformat(s["last_fired"]) if s.get("last_fired") else None
            if last and last >= slot:
                continue
            if s.get("created") and slot.timestamp() < s["created"]:
                continue  # slot before the schedule existed
            if (ref - slot) > timedelta(minutes=RETRY_MINUTES):
                _record(s, slot, "skipped: generator busy or app down")
                changed = True
                continue
            try:
                meta = runner.start_tag_run(
                    s["project"], s["tag"], s["created_by"], s.get("props", ""), s.get("distributed", False),
                    jira=s.get("jira", ""), notes=s.get("notes") or f"Ejecución programada ({describe(s)})",
                    extra_emails=s.get("extra_emails"), source=f"schedule:{s['id']}")
                _record(s, slot, f"run {meta['id']}")
                changed = True
            except projects.ProjectError as exc:
                if "Another test is running" in str(exc):
                    continue  # retry on next tick
                _record(s, slot, f"error: {exc}")
                changed = True
        if changed:
            _save(items)


def start_background():
    global _thread
    if _thread and _thread.is_alive():
        return

    def loop():
        while True:
            try:
                tick()
            except Exception as exc:  # noqa: BLE001
                print(f"[scheduler] {exc}", flush=True)
            time.sleep(20)

    _thread = threading.Thread(target=loop, name="scheduler", daemon=True)
    _thread.start()
