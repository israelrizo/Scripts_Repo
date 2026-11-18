"""Team-wide data shared through the Master, so every engineer's Control Center sees the same history.

On the Master (under <remote_root>/.jmcc, read and written over SSM as the scripts owner):
  history/<run_id>.json   one record per execution launched from any Control Center (who, what, result)
  shared/team.json        team settings published by an admin: New Relic key, default Google Chat spaces

On this computer (instance/team/):
  history.json            cache of the team records (shown in Executions → Team even with the Master off)
  state.json              last sync, revision of the team settings applied here

Identity: records carry the engineer's AWS SSO e-mail (aws.sso_email), never the full ARN.
"""
import base64
import io
import json
import re
import shlex
import socket
import tarfile
import threading
import time
from datetime import datetime

from . import aws, projects, runner, settings
from .config import Config

q = shlex.quote
RUN_ID_RE = re.compile(r"^[0-9a-f]{12}$")
RESULT_RE = re.compile(r"^([a-z0-9][a-z0-9\-]{1,40})/results/(Ejecucion_[^/\s]+)$")
LIST_LIMIT = 600          # most recent records listed per sync (fits the 24 KB SSM output limit)
BATCH = 20                # records per SSM command (gzip + base64 must stay under 24 KB)
_lock = threading.Lock()

REC_KEYS = ("id", "project", "tag", "script", "props", "distributed", "status", "created", "started", "ended",
            "returncode", "result_dir", "result_remote_only", "jira", "notes", "error")


class TeamError(RuntimeError):
    pass


# --------------------------------------------------------------------------- local cache
def _dir():
    d = Config.INSTANCE_DIR / "team"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(name, default):
    p = _dir() / name
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return default


def _store(name, data):
    p = _dir() / name
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    tmp.replace(p)


def state():
    return _load("state.json", {})


def _set_state(**changes):
    with _lock:
        s = state()
        s.update(changes)
        _store("state.json", s)


def cached_history():
    return _load("history.json", {})


def history(project=None, who=None, limit=500):
    """Team records newest first, with `local` (report downloaded here) and `mine` flags."""
    me = aws.sso_email(max_age=3600) if settings.aws_mode() else ""
    out = []
    for r in cached_history().values():
        if project and r.get("project") != project:
            continue
        if who and (r.get("email") or r.get("user") or "") != who:
            continue
        rd = r.get("result_dir") or r.get("result_remote_only")
        here = bool(RUN_ID_RE.match(r.get("id") or "") and (runner._runs_dir() / f"{r['id']}.json").exists())
        r = dict(r, result=rd, local=bool(rd and _local_result(r.get("project"), rd)),
                 mine=bool(me and r.get("email") == me), here=here)
        out.append(r)
    out.sort(key=lambda r: r.get("started") or r.get("created") or 0, reverse=True)
    return out[:limit]


def _local_result(project, rd):
    try:
        projects.result_dir(project, rd)
        return True
    except projects.ProjectError:
        return False


# --------------------------------------------------------------------------- Master helpers
def _jdir():
    return f"{aws.remote_root()}/.jmcc"


def master_ready():
    """(ok, reason): the Master is running and answering SSM."""
    c = aws.cfg()
    if not c.get("master"):
        return False, "Master instance not configured (Settings → AWS)"
    try:
        inst = next((i for i in aws.instances() if i["id"] == c["master"]), None)
    except aws.AwsError as exc:
        return False, str(exc)
    if not inst or inst["state"] != "running":
        return False, f"the Master is {inst['state'] if inst else 'not found'}"
    if not inst.get("ssm"):
        return False, "the Master is not answering SSM yet"
    return True, ""


def _write_remote(path, data, mode="644"):
    b64 = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
    d = path.rsplit("/", 1)[0]
    script = (f"umask 077; mkdir -p {q(d)} && printf %s {q(b64)} | base64 -d > {q(path)}.tmp "
              f"&& chmod {mode} {q(path)}.tmp && mv {q(path)}.tmp {q(path)} && echo @@OK@@")
    rc, out, err = aws.run(aws.cfg()["master"], script, timeout=60)
    if "@@OK@@" not in out:
        raise TeamError(f"could not write {path} on the Master: {(err or out).strip()[-200:]}")


# --------------------------------------------------------------------------- run records
def record(meta, summary=None):
    rec = {k: meta.get(k) for k in REC_KEYS}
    rec["email"] = meta.get("email") or ""
    rec["user"] = rec["email"] or meta.get("user")
    rec["host"] = _host()
    rec["slaves"] = len(meta.get("remote_hosts") or [])
    if meta.get("jira_bug"):
        rec["jira_bug"] = meta["jira_bug"]
    if summary:
        t = summary.get("totals") or {}
        if t:
            rec["totals"] = {k: t.get(k) for k in ("samples", "error_pct", "avg", "p95", "p99", "tps")}
        rec["verdict"] = summary.get("verdict") or ""
        rec["checks"] = [list(c) for c in summary.get("checks") or []]
    rec["updated"] = time.time()
    return rec


def _host():
    """Short computer name (macOS sometimes reports its IP address as the host name: keep it whole)."""
    name = socket.gethostname()
    return name if re.match(r"^[\d.]+$", name) else name.split(".")[0]


def publish(rec):
    if not RUN_ID_RE.match(rec.get("id") or ""):
        raise TeamError("bad run id")
    _write_remote(f"{_jdir()}/history/{rec['id']}.json", rec)
    with _lock:
        h = cached_history()
        h[rec["id"]] = rec
        _store("history.json", h)


def _log(meta, line):
    try:
        with (runner._runs_dir() / f"{meta['id']}.log").open("a") as fh:
            fh.write(f"### {time.strftime('%H:%M:%S')} {line}\n")
    except OSError:
        pass


def on_start(meta):
    if meta.get("kind") != "test" or meta.get("mode") != "aws":
        return
    try:
        publish(record(meta))
        _log(meta, "team: execution shared on the Master (Executions → Team)")
    except (TeamError, aws.AwsError) as exc:
        _log(meta, f"team: could not share this execution: {exc}")


def on_end(meta):
    if meta.get("kind") != "test" or meta.get("mode") != "aws":
        return
    from . import notify
    meta = runner.get(meta["id"]) or meta
    try:
        summary = notify.run_summary(meta)
    except Exception:  # noqa: BLE001 - the record is still useful without statistics
        summary = None
    try:
        publish(record(meta, summary))
        _log(meta, "team: result shared on the Master")
    except (TeamError, aws.AwsError) as exc:
        _log(meta, f"team: could not share the result: {exc}")


def republish(run_id):
    """After a change made here (e.g. a Jira bug was created) refresh the shared record."""
    meta = runner.get(run_id)
    if not meta or meta.get("mode") != "aws":
        return
    from . import notify
    cur = cached_history().get(run_id) or {}
    rec = record(meta)
    for k in ("totals", "verdict", "checks"):
        if k in cur:
            rec[k] = cur[k]
    if "totals" not in rec:
        try:
            rec = record(meta, notify.run_summary(meta))
        except Exception:  # noqa: BLE001
            pass
    publish(rec)


# --------------------------------------------------------------------------- sync (Master -> this computer)
def _list_remote():
    script = (f"cd {q(_jdir() + '/history')} 2>/dev/null || exit 0\n"
              f"ls -1t 2>/dev/null | grep -E '^[0-9a-f]{{12}}\\.json$' | head -{LIST_LIMIT} | "
              f"while read -r f; do echo \"@@F@@ ${{f%.json}} $(stat -c %Y \"$f\")\"; done")
    rc, out, err = aws.run(aws.cfg()["master"], script, timeout=60)
    return {i: int(t) for i, t in re.findall(r"@@F@@ ([0-9a-f]{12}) (\d+)", out)}


def _fetch_remote(ids, folder="history", name_re=RUN_ID_RE):
    files = " ".join(q(f"{i}.json") for i in ids if name_re.match(i))
    script = f"cd {q(_jdir() + '/' + folder)} && tar -czf - {files} 2>/dev/null | base64 -w0; echo; echo @@END@@"
    rc, out, err = aws.run(aws.cfg()["master"], script, timeout=90)
    raw = None
    if "@@END@@" in out:   # missing when SSM cut the output (24 KB): the batch is split below
        try:
            raw = base64.b64decode(out.split("@@END@@")[0].strip() or b"", validate=True)
        except ValueError:
            raw = None
    elif rc != 0 and not out.strip():
        raise TeamError(f"could not read the team history: {err.strip()[-200:]}")
    if raw is None or (raw and raw[:2] != b"\x1f\x8b"):
        if len(ids) > 1:   # output truncated by SSM: split the batch
            half = len(ids) // 2
            return _fetch_remote(ids[:half], folder, name_re) + _fetch_remote(ids[half:], folder, name_re)
        raise TeamError(f"team record {ids[0]} is too large to read")
    recs = []
    if raw:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
            for m in tf.getmembers():
                stem = m.name.rsplit(".", 1)[0]
                if m.isfile() and name_re.match(stem) and m.size < 256 * 1024:
                    try:
                        rec = json.loads(tf.extractfile(m).read())
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and (rec.get("id") or rec.get("project")) == stem:
                        recs.append(rec)
    return recs


def _remote_results():
    """Result folders on the Master for every project (covers runs made before the team history existed)."""
    script = (f"cd {q(aws.remote_root())} 2>/dev/null || exit 0\n"
              "ls -1dt */results/Ejecucion_*/ 2>/dev/null | head -250 | sed 's#/$##; s#^#@@R@@ #'")
    rc, out, err = aws.run(aws.cfg()["master"], script, timeout=60)
    found = []
    for line in re.findall(r"@@R@@ (\S+)", out):
        m = RESULT_RE.match(line)
        if m:
            found.append((m.group(1), m.group(2)))
    return found


def _started_from_name(rd):
    m = re.match(r"^Ejecucion_(\d{6})_(\d{6})_", rd)
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%d%m%y%H%M%S").timestamp() if m else None
    except ValueError:
        return None


def sync(log=print, fetch_reports=None):
    """Pull the team history, the team settings and (optionally) recent reports from the Master."""
    if not settings.aws_mode():
        log("team sync: AWS mode is off")
        return
    ok, why = master_ready()
    if not ok:
        log(f"team sync skipped: {why}. It runs again when the servers start.")
        return
    cfg = settings.get()["team"]

    # 1. execution records (incremental: only new or changed files)
    remote = _list_remote()
    seen = state().get("mtimes", {})
    changed = [i for i, t in remote.items() if seen.get(i) != t]
    recs = []
    for n in range(0, len(changed), BATCH):
        recs += _fetch_remote(changed[n:n + BATCH])
    with _lock:
        h = cached_history()
        for r in recs:
            h[r["id"]] = r
        # 2. result folders without a record (older runs, or runs started outside the Control Center)
        known = {(r.get("project"), r.get("result_dir") or r.get("result_remote_only")) for r in h.values()}
        legacy = 0
        try:
            for proj, rd in _remote_results():
                if (proj, rd) in known:
                    continue
                key = f"r-{proj}-{rd}"
                if key not in h:
                    legacy += 1
                h[key] = {"id": key, "legacy": True, "project": proj, "result_remote_only": rd,
                          "tag": rd.split("_", 3)[-1] if rd.count("_") >= 3 else rd, "status": "finished",
                          "started": _started_from_name(rd), "user": "", "email": "", "host": "Master"}
        except aws.AwsError as exc:
            log(f"team sync: result folders not listed ({exc})")
        _store("history.json", h)
    _set_state(mtimes={i: remote[i] for i in remote}, last_sync=time.time())
    log(f"team history: {len(recs)} new/updated execution(s), {legacy} older result folder(s), "
        f"{len(remote)} shared in total")

    # 3. project profiles (acceptance criteria and report data)
    try:
        log("project criteria: " + sync_profiles())
    except (TeamError, aws.AwsError) as exc:
        log(f"project criteria: not synced ({exc})")

    # 4. team settings (New Relic, default Chat spaces)
    try:
        applied = pull_shared()
        log("team settings: " + (f"updated (published by {applied})" if applied else "up to date"))
    except (TeamError, aws.AwsError) as exc:
        log(f"team settings: not read ({exc})")

    # 5. recent reports (HTML only, the .jtl stays on the Master)
    if fetch_reports is None:
        fetch_reports = cfg.get("auto_fetch_reports")
    if fetch_reports:
        fetch_recent(log, days=int(cfg.get("fetch_days") or 7), limit=int(cfg.get("fetch_max") or 10))


def fetch_recent(log, days=7, limit=10):
    from . import remote_run
    since = time.time() - days * 86400
    todo = []
    for r in history(limit=1000):
        rd = r.get("result")
        if not rd or r["local"] or (r.get("started") or 0) < since or r.get("status") not in ("finished", None):
            continue
        try:
            projects.project_dir(r["project"])
        except projects.ProjectError:
            continue
        todo.append(r)
    if not todo:
        log(f"reports: every report of the last {days} day(s) is already on this computer")
        return
    log(f"reports: downloading {min(len(todo), limit)} of {len(todo)} recent report(s) (HTML only, no .jtl)")
    for r in todo[:limit]:
        try:
            remote_run.collect(r["project"], r["result"], log, include_jtl=False)
        except Exception as exc:  # noqa: BLE001 - keep going with the next report
            log(f"  {r['result']}: not downloaded ({exc})")


def sync_quietly():
    """Background sync after aws sso login / server start; never raises."""
    def work():
        try:
            sync(lambda m: None)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=work, daemon=True).start()


# --------------------------------------------------------------------------- team settings
def publish_shared(by):
    """Publish this computer's New Relic key and default Chat spaces to every installation."""
    cfg = settings.get()
    nr = cfg["newrelic"]
    data = {"rev": int(time.time()), "by": by, "published": datetime.now().strftime("%Y-%m-%d %H:%M")}
    key = settings.decrypt(nr.get("api_key_enc", ""))
    if key and nr.get("account_id"):
        data["newrelic"] = {"enabled": bool(nr.get("enabled")), "region": nr.get("region", "us"),
                            "account_id": nr["account_id"], "api_key": key,
                            "lookback_hours": nr.get("lookback_hours", 24), "auto_on_run": bool(nr.get("auto_on_run"))}
    spaces = [{"name": s["name"], "url": settings.decrypt(s["url_enc"])}
              for s in cfg["chat"]["spaces"] if s.get("default") and settings.decrypt(s.get("url_enc", ""))]
    if spaces:
        ch = cfg["chat"]
        data["chat"] = {"enabled": bool(ch.get("enabled")), "notify_start": bool(ch.get("notify_start")),
                        "notify_end": bool(ch.get("notify_end")), "spaces": spaces}
    if "newrelic" not in data and "chat" not in data:
        raise TeamError("Nothing to publish: save the New Relic key and/or a default Google Chat space first")
    ok, why = master_ready()
    if not ok:
        raise TeamError(f"cannot publish: {why}")
    _write_remote(f"{_jdir()}/shared/team.json", data, mode="600")
    _set_state(shared_rev=data["rev"], shared_by=by, shared_at=data["published"])
    return data


def pull_shared(force=False):
    """Apply the published team settings here. Returns who published them when something changed."""
    rc, out, err = aws.run(aws.cfg()["master"],
                           f"f={q(_jdir() + '/shared/team.json')}; [ -f \"$f\" ] || {{ echo @@NONE@@; exit 0; }}; "
                           "printf '@@T@@ '; base64 -w0 < \"$f\"; echo", timeout=60)
    if "@@NONE@@" in out:
        return ""
    m = re.search(r"@@T@@ (\S+)", out)
    if not m:
        raise TeamError((err or out).strip()[-200:] or "empty answer")
    data = json.loads(base64.b64decode(m.group(1)))
    if not force and data.get("rev") == state().get("shared_rev"):
        return ""
    apply_shared(data)
    _set_state(shared_rev=data.get("rev"), shared_by=data.get("by", ""), shared_at=data.get("published", ""))
    return data.get("by") or "an admin"


def apply_shared(data):
    from . import google
    cfg = settings.get()
    nr = data.get("newrelic")
    if nr and nr.get("api_key") and nr.get("account_id"):
        cfg["newrelic"].update(enabled=bool(nr.get("enabled", True)), region=nr.get("region", "us"),
                               account_id=str(nr["account_id"]), api_key_enc=settings.encrypt(nr["api_key"]),
                               lookback_hours=int(nr.get("lookback_hours") or 24),
                               auto_on_run=bool(nr.get("auto_on_run", True)), shared=True)
    ch = data.get("chat")
    if ch:
        items = cfg["chat"]["spaces"]
        for sp in ch.get("spaces") or []:
            try:
                url = google.validate_webhook(sp.get("url"))
            except google.GoogleError:
                continue
            name = (sp.get("name") or "Team")[:40]
            cur = next((s for s in items if s["name"].strip().lower() == name.strip().lower()), None)
            if cur:
                cur.update(url_enc=settings.encrypt(url), default=True, shared=True)
            else:
                import uuid
                items.append({"id": uuid.uuid4().hex[:8], "name": name, "url_enc": settings.encrypt(url),
                              "default": True, "shared": True})
        cfg["chat"].update(spaces=items, enabled=bool(ch.get("enabled", True)),
                           notify_start=bool(ch.get("notify_start", True)), notify_end=bool(ch.get("notify_end", True)))
    settings.save(cfg)


# --------------------------------------------------------------------------- project profiles
# Acceptance criteria and report data of a project (report defaults: application, scenario, scope, base URL, tool,
# avg / p95 / error % / TPS criteria, Confluence space...). Shared so whoever picks up a project gets the same
# criteria and the same INSATISFACTORIA verdicts. Last change wins; each profile says who changed it and when.
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,60}$")


def profile_info(project):
    return (state().get("profiles") or {}).get(project) or {}


def _set_profile(project, **changes):
    with _lock:
        st = state()
        prof = st.setdefault("profiles", {})
        prof[project] = dict(prof.get(project) or {}, **changes)
        _store("state.json", st)


def _me(fallback=""):
    return (aws.sso_email() if settings.aws_mode() else "") or fallback


def save_profile(project, fields, by=""):
    """Save the project's report defaults here and share them. Returns a short status for the UI."""
    from . import report
    cur = report.load_defaults(project)
    cur.update({k: (fields.get(k) or "").strip() for k in report.DEFAULT_KEYS if k in fields})
    report.save_defaults(project, cur)
    return profile_changed(project, by, wait=True)


def profile_changed(project, by="", wait=False):
    """Mark the local profile as newer than the Master's and publish it (now, or in the background)."""
    if not PROJECT_RE.match(project or ""):
        return "saved"
    who = _me(by)
    _set_profile(project, rev=time.time(), by=who, at=datetime.now().strftime("%Y-%m-%d %H:%M"), pending=True)
    if not settings.aws_mode():
        return "saved on this computer (AWS mode is off: not shared)"

    def push():
        try:
            ok, why = master_ready()
            if not ok:
                return f"saved on this computer; shared on the next sync ({why})"
            publish_profile(project)
            return "saved and shared with the team"
        except (TeamError, aws.AwsError) as exc:
            return f"saved on this computer; not shared yet ({exc})"
    if wait:
        return push()
    threading.Thread(target=push, daemon=True).start()
    return "saved"


def publish_profile(project):
    from . import report
    info = profile_info(project)
    data = {"project": project, "rev": info.get("rev") or time.time(), "by": info.get("by") or _me(),
            "at": info.get("at") or datetime.now().strftime("%Y-%m-%d %H:%M"),
            "report_defaults": report.load_defaults(project)}
    _write_remote(f"{_jdir()}/projects/{project}.json", data)
    _set_profile(project, rev=data["rev"], by=data["by"], at=data["at"], pending=False)


def sync_profiles():
    from . import report
    rc, out, err = aws.run(aws.cfg()["master"],
                           f"cd {q(_jdir() + '/projects')} 2>/dev/null || exit 0\n"
                           "for f in *.json; do [ -f \"$f\" ] && echo \"@@P@@ ${f%.json}\"; done", timeout=60)
    names = [n for n in re.findall(r"@@P@@ (\S+)", out) if PROJECT_RE.match(n)]
    remote = {}
    for n in range(0, len(names), BATCH):
        for rec in _fetch_remote(names[n:n + BATCH], "projects", PROJECT_RE):
            remote[rec["project"]] = rec
    pulled, pushed = [], []
    for project, rec in remote.items():
        try:
            projects.project_dir(project)
        except projects.ProjectError:
            continue                       # project not cloned on this computer
        local = profile_info(project)
        has_local = bool(report.load_defaults(project))
        if local.get("pending") and (local.get("rev") or 0) > (rec.get("rev") or 0):
            publish_profile(project)
            pushed.append(project)
        elif (rec.get("rev") or 0) > (local.get("rev") or 0) or not has_local:
            src = Config.INSTANCE_DIR / "report_defaults" / f"{project}.json"
            if has_local and not local.get("rev") and src.exists():   # criteria from before sharing: keep a copy
                src.with_name(f"{project}.local-backup.json").write_text(src.read_text())
            report.save_defaults(project, rec.get("report_defaults") or {})
            _set_profile(project, rev=rec.get("rev"), by=rec.get("by", ""), at=rec.get("at", ""), pending=False)
            pulled.append(f"{project} ({rec.get('by') or '?'})")
    # profiles that exist only here (saved offline, or before sharing existed)
    for f in sorted((Config.INSTANCE_DIR / "report_defaults").glob("*.json")):
        project = f.stem
        if project in remote or not PROJECT_RE.match(project):
            continue
        if not profile_info(project).get("rev"):
            _set_profile(project, rev=f.stat().st_mtime, by=_me(), at=datetime.fromtimestamp(f.stat().st_mtime)
                         .strftime("%Y-%m-%d %H:%M"), pending=True)
        publish_profile(project)
        pushed.append(project)
    parts = []
    if pulled:
        parts.append("updated from the team: " + ", ".join(pulled))
    if pushed:
        parts.append("shared from this computer: " + ", ".join(pushed))
    return "; ".join(parts) or f"up to date ({len(remote)} project(s) shared)"
