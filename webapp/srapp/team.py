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

    # 3. project profiles (criteria, baselines, project settings, Confluence publications) and schedules
    try:
        log("projects: " + sync_profiles())
    except (TeamError, aws.AwsError) as exc:
        log(f"projects: not synced ({exc})")
    try:
        log("schedules: " + sync_schedules())
    except (TeamError, aws.AwsError) as exc:
        log(f"schedules: not synced ({exc})")

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
# Infrastructure every installation must agree on (no secrets): servers, paths, ports, Grafana, tunnels, time zone.
# The AWS CLI profile name stays local (each engineer names it as they like).
INFRA_AWS = ("region", "master", "slaves", "remote_user", "remote_root", "branch", "auto_off", "rmi_port",
             "slave_start_cmd", "jtl_max_mb", "sync_method", "max_runs")


def infra_snapshot(cfg=None):
    cfg = cfg or settings.get()
    return {"aws": {k: cfg["aws"].get(k) for k in INFRA_AWS},
            "grafana": {k: cfg["grafana"].get(k, "") for k in ("url", "dashboard", "app_var", "extra")},
            "tunnels": cfg["tunnels"], "timezone": cfg["app"].get("timezone", ""),
            "jira_url": cfg["jira"].get("url", ""),
            "jira_bugs": {k: cfg["jira"].get(k, "") for k in ("bug_project", "bug_issue_type", "bug_labels")},
            "smtp_always_to": cfg["smtp"].get("always_to", "")}


def apply_infra(cfg, infra):
    a = infra.get("aws") or {}
    for k in INFRA_AWS:
        if k in a and a[k] is not None:
            cfg["aws"][k] = a[k]
    if not isinstance(cfg["aws"].get("slaves"), list):
        cfg["aws"]["slaves"] = []
    if a.get("master"):
        cfg["aws"]["enabled"] = True
    g = infra.get("grafana") or {}
    cfg["grafana"].update({k: g[k] for k in ("url", "dashboard", "app_var", "extra") if k in g})
    if isinstance(infra.get("tunnels"), dict) and infra["tunnels"].get("items"):
        cfg["tunnels"] = infra["tunnels"]
    if infra.get("timezone") is not None:
        cfg["app"]["timezone"] = infra["timezone"]
    if infra.get("jira_url"):
        cfg["jira"]["url"] = infra["jira_url"]
    cfg["jira"].update({k: v for k, v in (infra.get("jira_bugs") or {}).items() if v})
    if infra.get("smtp_always_to"):
        cfg["smtp"]["always_to"] = infra["smtp_always_to"]
    return cfg


def setup_file():
    """Onboarding file for a new engineer (no secrets): import it, sign in with AWS SSO, and the first sync
    brings the team settings, criteria and history."""
    return {"kind": "jmcc-setup", "version": 1, "exported": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "by": _me(), "infra": infra_snapshot(), "team": settings.get()["team"]}


def import_setup(data):
    from . import aws as _aws
    if not isinstance(data, dict) or data.get("kind") != "jmcc-setup":
        raise TeamError("Not a Control Center setup file")
    cfg = apply_infra(settings.get(), data.get("infra") or {})
    if isinstance(data.get("team"), dict):
        cfg["team"].update({k: v for k, v in data["team"].items() if k in cfg["team"]})
    _aws.validate(cfg["aws"])
    settings.save(cfg)
    _aws.invalidate()
    return cfg


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
    data["infra"] = infra_snapshot(cfg)
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
    if data.get("infra"):
        trial = apply_infra(json.loads(json.dumps(cfg)), data["infra"])
        try:
            aws.validate(trial["aws"])
            cfg = trial
        except ValueError:
            pass   # unsafe/incomplete infrastructure values are ignored, the rest still applies
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
# What a project needs so whoever picks it up continues with the same setup. One file per project on the Master,
# .jmcc/projects/<project>.json, with independent sections (each with its own who/when; last change wins per
# section, so a criteria change and a baseline change made at the same time by two engineers both survive):
#   report_defaults   acceptance criteria (preset, p95, error %) and report data (application, scenario, scope...)
#   baselines         baseline execution per script (comparisons)
#   project_settings  staff e-mails, Jira board, pinned New Relic services, Grafana dashboard, extra Chat spaces...
# plus "publications": Confluence pages already published per execution (merged, never overwritten).
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,60}$")
SECTIONS = ("report_defaults", "baselines", "project_settings")
SECTION_LABELS = {"report_defaults": "criteria", "baselines": "baselines", "project_settings": "settings"}


def _get_section(project, section):
    from . import compare, report
    if section == "report_defaults":
        return report.load_defaults(project)
    if section == "baselines":
        return compare.baselines(project)
    ps = settings.project(project)
    names = {s["id"]: s["name"] for s in settings.get()["chat"]["spaces"]}
    ps = dict(ps, chat_spaces=[names[i] for i in ps.get("chat_spaces") or [] if i in names])  # ids are per computer
    return ps


def _has_data(project, section):
    from . import compare, report
    if section == "report_defaults":
        return bool(report.load_defaults(project))
    if section == "baselines":
        return bool(compare.baselines(project))
    return settings._project_path(project).exists()


def _put_section(project, section, data):
    from . import compare, report
    if section == "report_defaults":
        report.save_defaults(project, data or {})
    elif section == "baselines":
        compare.save_baselines(project, data or {})
    else:
        ids = {s["name"].strip().lower(): s["id"] for s in settings.get()["chat"]["spaces"]}
        data = dict(data or {})
        data["chat_spaces"] = [ids[n.strip().lower()] for n in data.get("chat_spaces") or [] if n.strip().lower() in ids]
        settings.save_project(project, data)


def _local_file(project, section):
    from . import compare
    if section == "report_defaults":
        return Config.INSTANCE_DIR / "report_defaults" / f"{project}.json"
    if section == "baselines":
        return compare._bpath(project)
    return settings._project_path(project)


def profile_info(project, section="report_defaults"):
    return ((state().get("profiles") or {}).get(project) or {}).get(section) or {}


def _set_profile(project, section, **changes):
    with _lock:
        st = state()
        prof = st.setdefault("profiles", {}).setdefault(project, {})
        if not isinstance(prof.get(section), dict):
            prof[section] = {}
        prof[section].update(changes)
        _store("state.json", st)


def _me(fallback=""):
    return (aws.sso_email() if settings.aws_mode() else "") or fallback


def save_profile(project, fields, by=""):
    """Acceptance criteria editor: save the project's report defaults here and share them."""
    from . import report
    cur = report.load_defaults(project)
    cur.update({k: (fields.get(k) or "").strip() for k in report.DEFAULT_KEYS if k in fields})
    report.save_defaults(project, cur)
    return profile_changed(project, "report_defaults", by, wait=True)


def profile_changed(project, section="report_defaults", by="", wait=False):
    """A section was changed on this computer: mark it newer than the Master's and share it."""
    if not PROJECT_RE.match(project or ""):
        return "saved"
    if section in SECTIONS:
        _set_profile(project, section, rev=time.time(), by=_me(by), at=datetime.now().strftime("%Y-%m-%d %H:%M"),
                     pending=True)
    if not settings.aws_mode():
        return "saved on this computer (AWS mode is off: not shared)"

    def push():
        try:
            ok, why = master_ready()
            if not ok:
                return f"saved on this computer; shared on the next sync ({why})"
            reconcile(project)
            return "saved and shared with the team"
        except (TeamError, aws.AwsError) as exc:
            return f"saved on this computer; not shared yet ({exc})"
    if wait:
        return push()
    threading.Thread(target=push, daemon=True).start()
    return "saved"


def _read_profile(project):
    rc, out, err = aws.run(aws.cfg()["master"],
                           f"f={q(_jdir() + '/projects/' + project + '.json')}; [ -f \"$f\" ] || {{ echo @@NONE@@; exit 0; }}; "
                           "printf '@@J@@ '; base64 -w0 < \"$f\"; echo", timeout=60)
    if "@@NONE@@" in out:
        return {}
    m = re.search(r"@@J@@ (\S+)", out)
    if not m:
        raise TeamError((err or out).strip()[-200:] or "empty answer")
    return json.loads(base64.b64decode(m.group(1)))


def reconcile(project, remote=None):
    """Merge this computer's profile of `project` with the Master's. Returns (pulled sections, pushed sections)."""
    from . import report
    if remote is None:
        remote = _read_profile(project)
    if remote and "sections" not in remote:             # first version of the format: criteria only
        remote = {"project": project, "sections": {"report_defaults": {k: remote.get(k) for k in ("rev", "by", "at")}
                                                   | {"data": remote.get("report_defaults") or {}}}}
    rsec = dict(remote.get("sections") or {})
    pulled, pushed = [], []
    for section in SECTIONS:
        L, R = profile_info(project, section), rsec.get(section) or {}
        lrev, rrev = L.get("rev") or 0, R.get("rev") or 0
        if L.get("pending") and lrev >= rrev:
            rsec[section] = {"rev": lrev, "by": L.get("by", ""), "at": L.get("at", ""), "data": _get_section(project, section)}
            _set_profile(project, section, pending=False)
            pushed.append(section)
        elif R and rrev > lrev:
            f = _local_file(project, section)
            if f.exists() and not lrev:                  # data from before sharing: keep a copy
                f.with_name(f"{f.stem}.local-backup.json").write_text(f.read_text())
            _put_section(project, section, R.get("data"))
            _set_profile(project, section, rev=rrev, by=R.get("by", ""), at=R.get("at", ""), pending=False)
            pulled.append(section)
        elif not R and _has_data(project, section):
            mtime = _local_file(project, section).stat().st_mtime
            info = {"rev": lrev or mtime, "by": L.get("by") or _me(),
                    "at": L.get("at") or datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")}
            rsec[section] = dict(info, data=_get_section(project, section))
            _set_profile(project, section, pending=False, **info)
            pushed.append(section)
    # Confluence publications: union (keep the newest entry per execution)
    local_pub, remote_pub = report.history(project), dict(remote.get("publications") or {})
    merged = dict(remote_pub)
    for k, v in local_pub.items():
        if k not in merged or (v.get("ts") or 0) > (merged[k].get("ts") or 0):
            merged[k] = v
    if merged != local_pub:
        report._history_path(project).write_text(json.dumps(merged, indent=2, ensure_ascii=False))
        pulled.append("publications")
    if merged != remote_pub:
        pushed.append("publications")
    if pushed:
        _write_remote(f"{_jdir()}/projects/{project}.json",
                      {"project": project, "sections": rsec, "publications": merged, "updated": time.time()})
    return pulled, pushed


def _local_projects():
    try:
        return [p["name"] for p in projects.list_projects()]
    except OSError:
        return []


def sync_profiles():
    rc, out, err = aws.run(aws.cfg()["master"],
                           f"cd {q(_jdir() + '/projects')} 2>/dev/null || exit 0\n"
                           "for f in *.json; do [ -f \"$f\" ] && echo \"@@P@@ ${f%.json}\"; done", timeout=60)
    names = [n for n in re.findall(r"@@P@@ (\S+)", out) if PROJECT_RE.match(n)]
    remote = {}
    for n in range(0, len(names), BATCH):
        for rec in _fetch_remote(names[n:n + BATCH], "projects", PROJECT_RE):
            remote[rec["project"]] = rec
    here = set(_local_projects())
    pulled, pushed = [], []
    for project in sorted(here):
        if not PROJECT_RE.match(project):
            continue
        pl, ps = reconcile(project, remote.get(project) or {})
        label = project.replace(Config.PROJECT_SUFFIX, "")
        if pl:
            pulled.append(f"{label} ({', '.join(SECTION_LABELS.get(x, x) for x in pl)})")
        if ps:
            pushed.append(f"{label} ({', '.join(SECTION_LABELS.get(x, x) for x in ps)})")
    parts = []
    if pulled:
        parts.append("updated from the team: " + "; ".join(pulled))
    if pushed:
        parts.append("shared from this computer: " + "; ".join(pushed))
    return " · ".join(parts) or f"up to date ({len(remote)} project(s) shared)"


# --------------------------------------------------------------------------- schedules (read-only view of the team's)
# Schedules fire only on the computer that created them; the team sees each other's to avoid fighting for the Master
# and the Slaves. One file per installation: .jmcc/schedules/<install id>.json
INSTALL_RE = re.compile(r"^[0-9a-f]{16}$")


def install_id():
    sid = state().get("install_id")
    if not sid:
        import uuid
        sid = uuid.uuid4().hex[:16]
        _set_state(install_id=sid)
    return sid


def _schedule_payload():
    from . import scheduler
    items = []
    for s in scheduler.load():
        nr = scheduler.next_run(s)
        items.append({"project": s["project"], "tag": s["tag"], "describe": scheduler.describe(s),
                      "enabled": bool(s.get("enabled")), "distributed": bool(s.get("distributed")),
                      "stop_after": bool(s.get("stop_after")), "next": nr.isoformat() if nr else None})
    return {"id": install_id(), "by": _me(), "host": _host(), "updated": time.time(),
            "tz": str(scheduler.tz()), "items": items}


def schedules_changed():
    if not settings.aws_mode():
        return

    def push():
        try:
            if master_ready()[0]:
                publish_schedules()
        except (TeamError, aws.AwsError):
            pass
    threading.Thread(target=push, daemon=True).start()


def publish_schedules():
    data = _schedule_payload()
    _write_remote(f"{_jdir()}/schedules/{data['id']}.json", data)


def sync_schedules():
    publish_schedules()
    rc, out, err = aws.run(aws.cfg()["master"],
                           f"cd {q(_jdir() + '/schedules')} 2>/dev/null || exit 0\n"
                           "for f in *.json; do [ -f \"$f\" ] && echo \"@@S@@ ${f%.json}\"; done", timeout=60)
    names = [n for n in re.findall(r"@@S@@ (\S+)", out) if INSTALL_RE.match(n) and n != install_id()]
    others = []
    for n in range(0, len(names), BATCH):
        others += _fetch_remote(names[n:n + BATCH], "schedules", INSTALL_RE)
    _store("schedules.json", {r["id"]: r for r in others})
    return f"{sum(len(r.get('items') or []) for r in others)} schedule(s) from {len(others)} other computer(s)"


def team_schedules():
    """Schedules of the other installations, next run first: [{project, tag, describe, next, by, host, ...}]."""
    from . import scheduler
    now = scheduler.now()
    out = []
    for inst in _load("schedules.json", {}).values():
        for it in inst.get("items") or []:
            nxt = None
            if it.get("next"):
                try:
                    nxt = datetime.fromisoformat(it["next"])
                except ValueError:
                    nxt = None
            if nxt and nxt < now:
                nxt = None   # already fired (the owner's computer publishes the next one on its next sync)
            out.append(dict(it, by=inst.get("by") or "unknown", host=inst.get("host", ""), next_dt=nxt,
                            updated=inst.get("updated")))
    out.sort(key=lambda r: (r["next_dt"] is None, r["next_dt"] or now))
    return out


def schedule_conflicts(mine):
    """Warnings for my schedules that start within 2 h of a team schedule that needs the same project or the Slaves."""
    from . import scheduler
    warn = {}
    team = [t for t in team_schedules() if t["next_dt"] and t.get("enabled")]
    for s in mine:
        nr = scheduler.next_run(s)
        if not nr:
            continue
        for t in team:
            if abs((t["next_dt"] - nr).total_seconds()) > 2 * 3600:
                continue
            if t["project"] == s["project"]:
                warn[s["id"]] = f"{t['by']} runs {t['project'].replace(Config.PROJECT_SUFFIX, '')} at {t['next_dt']:%H:%M}"
            elif t["distributed"] and s.get("distributed"):
                warn[s["id"]] = f"{t['by']} uses the Slaves at {t['next_dt']:%H:%M}"
    return warn
