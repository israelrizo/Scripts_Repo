"""Launches run_by_tag.sh (and slave syncs) as background processes and tracks them.

Each run is stored as instance/runs/<id>.json (metadata) + <id>.log (combined stdout/stderr),
so history and logs survive a restart of the web app.
"""
import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .config import WEBAPP_DIR, Config
from . import projects

SHIM_DIR = WEBAPP_DIR / "bin"
RESULT_RE = re.compile(r"(?:Resultados guardados en|Creando directorio):\s*(results/[^\s]+?)(?:/html_report)?\s*$")
_lock = threading.Lock()
_procs = {}
# Callbacks registered by the web app: HOOKS["start"|"end"] = [fn(meta)], run in background threads.
HOOKS = {"start": [], "end": []}
ISSUE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,19}-\d{1,9}$")


def _fire(event, meta):
    for fn in HOOKS.get(event, []):
        threading.Thread(target=_safe_hook, args=(fn, dict(meta)), daemon=True).start()


def _safe_hook(fn, meta):
    try:
        fn(meta)
    except Exception as exc:  # noqa: BLE001 - hooks must never break runs
        try:
            with (_runs_dir() / f"{meta['id']}.log").open("a") as fh:
                fh.write(f"### hook {getattr(fn, '__name__', fn)} failed: {exc}\n")
        except OSError:
            pass


def _runs_dir():
    d = Config.INSTANCE_DIR / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _meta_path(run_id):
    if not re.match(r"^[0-9a-f]{12}$", run_id or ""):
        raise ValueError("bad run id")
    return _runs_dir() / f"{run_id}.json"


def _save(meta):
    p = _meta_path(meta["id"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2))
    tmp.replace(p)


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


def get(run_id):
    p = _meta_path(run_id)
    if not p.exists():
        return None
    meta = json.loads(p.read_text())
    if meta["status"] in ("running", "stopping") and run_id not in _procs and not _pid_alive(meta.get("pid")):
        meta["status"] = "interrupted"
        meta.setdefault("ended", time.time())
        _save(meta)
    return meta


def list_runs(project=None, limit=50):
    metas = []
    for p in sorted(_runs_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        m = get(p.stem)
        if m and (project is None or m["project"] == project):
            metas.append(m)
        if len(metas) >= limit:
            break
    return metas


def active_runs():
    return [m for m in list_runs(limit=200) if m["status"] in ("running", "stopping")]


def read_log(run_id, offset=0, max_bytes=256 * 1024):
    _meta_path(run_id)
    p = _runs_dir() / f"{run_id}.log"
    if not p.exists():
        return "", offset
    with p.open("rb") as fh:
        fh.seek(offset)
        chunk = fh.read(max_bytes)
    return chunk.decode("utf-8", errors="replace"), offset + len(chunk)


def _spawn(meta, cmd, cwd, env):
    log_path = _runs_dir() / f"{meta['id']}.log"
    log = open(log_path, "ab", buffering=0)
    header = (f"### {time.strftime('%Y-%m-%d %H:%M:%S')}  user={meta['user']}  project={meta['project']}\n"
              f"### cwd={cwd}\n### cmd={' '.join(cmd)}\n")
    if meta.get("remote_hosts"):
        header += f"### distributed: -R {','.join(meta['remote_hosts'])}\n"
    if meta.get("props"):
        header += f"### extra properties: {' '.join(meta['props'])}\n"
    log.write((header + "#" * 60 + "\n").encode())
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, start_new_session=True)
    meta.update(pid=proc.pid, status="running", started=time.time())
    _save(meta)
    _procs[meta["id"]] = proc
    threading.Thread(target=_wait, args=(meta["id"], proc, log), daemon=True).start()
    _fire("start", meta)
    return meta


def _wait(run_id, proc, log):
    rc = proc.wait()
    log.close()
    _procs.pop(run_id, None)
    meta = json.loads(_meta_path(run_id).read_text())
    meta["returncode"] = rc
    meta["ended"] = time.time()
    if meta["status"] == "stopping":
        meta["status"] = "stopped"
    else:
        meta["status"] = "finished" if rc == 0 else "failed"
    text, _ = read_log(run_id, 0, 10 * 1024 * 1024)
    for line in text.splitlines():
        m = RESULT_RE.search(line)
        if m:
            meta["result_dir"] = Path(m.group(1)).name
    _save(meta)
    _fire("end", meta)


def start_tag_run(project, tag, user, props_raw="", distributed=False, jira="", notes="",
                  extra_emails=None, notify=True, source="web"):
    base = projects.project_dir(project)
    t = projects.get_tag(project, tag)
    if not t:
        raise projects.ProjectError("Unknown tag")
    if not t["exists"]:
        raise projects.ProjectError(f"Script for tag '{tag}' does not exist: {t['script']}")
    props = projects.validate_prop_args(props_raw)
    jira = (jira or "").strip().upper()
    if jira and not ISSUE_RE.match(jira):
        raise projects.ProjectError(f"Invalid Jira ticket '{jira}' (expected e.g. PERF-123)")
    notes = (notes or "").strip()[:500]
    if distributed and not Config.REMOTE_HOSTS:
        raise projects.ProjectError("No slaves configured (SR_REMOTE_HOSTS)")
    with _lock:
        if not Config.ALLOW_CONCURRENT_RUNS and any(r["kind"] == "test" for r in active_runs()):
            raise projects.ProjectError("Another test is running on this generator. Stop it or wait.")
        env = dict(os.environ)
        env["PATH"] = f"{SHIM_DIR}:{env.get('PATH', '')}"
        env["SR_REAL_JMETER"] = Config.JMETER_BIN
        env["SR_EXTRA_PROPS"] = " ".join(props)
        env["SR_REMOTE_HOSTS"] = ",".join(Config.REMOTE_HOSTS) if distributed else ""
        meta = {"id": uuid.uuid4().hex[:12], "kind": "test", "project": project, "tag": tag,
                "script": t["script"], "user": user, "props": props,
                "remote_hosts": Config.REMOTE_HOSTS if distributed else [], "status": "starting",
                "created": time.time(), "jira": jira, "notes": notes, "extra_emails": list(extra_emails or []),
                "notify": bool(notify), "source": source}
        _save(meta)
        return _spawn(meta, ["bash", "run_by_tag.sh", tag], base, env)


def start_sync(project, user):
    base = projects.project_dir(project)
    if not Config.REMOTE_HOSTS:
        raise projects.ProjectError("No slaves configured (SR_REMOTE_HOSTS)")
    if not Config.SLAVE_SSH_USER:
        raise projects.ProjectError("Slave sync disabled: set SR_SLAVE_SSH_USER (and SR_SLAVE_SSH_KEY)")
    ssh = "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
    if Config.SLAVE_SSH_KEY:
        ssh += f" -i {Config.SLAVE_SSH_KEY}"
    dest_root = f"{Config.SLAVE_REPO_ROOT.rstrip('/')}/{project}"
    parts = []
    for host in Config.REMOTE_HOSTS:
        target = f"{Config.SLAVE_SSH_USER}@{host}"
        parts.append(f'echo "==> {host}" && {ssh} {target} "mkdir -p {dest_root}" && '
                     f'rsync -az --info=stats1 -e "{ssh}" data tests "{target}:{dest_root}/"')
    script = " && ".join(parts) + ' && echo "==> Sync OK"'
    meta = {"id": uuid.uuid4().hex[:12], "kind": "sync", "project": project, "tag": "sync → slaves",
            "user": user, "props": [], "remote_hosts": Config.REMOTE_HOSTS, "status": "starting",
            "created": time.time()}
    _save(meta)
    return _spawn(meta, ["bash", "-c", script], base, dict(os.environ))


def stop(run_id, force=False):
    meta = get(run_id)
    if not meta or meta["status"] not in ("running", "stopping"):
        raise projects.ProjectError("Run is not active")
    meta["status"] = "stopping"
    _save(meta)
    if not force and meta["kind"] == "test":
        # Same as $JMETER_HOME/bin/shutdown.sh: graceful stop, JMeter still writes the HTML report.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for port in range(4445, 4450):
                sock.sendto(b"Shutdown", ("127.0.0.1", port))
        finally:
            sock.close()
        return "Graceful shutdown requested (threads finish their current iteration)."
    try:
        os.killpg(meta["pid"], signal.SIGTERM)
    except OSError:
        pass
    return "Process group terminated."


# --------------------------------------------------------------------------- slaves
def slave_status():
    out = []
    for host in Config.REMOTE_HOSTS:
        t0 = time.time()
        try:
            with socket.create_connection((host, Config.REMOTE_RMI_PORT), timeout=1.5):
                out.append({"host": host, "up": True, "ms": round((time.time() - t0) * 1000)})
        except OSError as exc:
            out.append({"host": host, "up": False, "error": str(exc)})
    return out


def jmeter_available():
    return os.access(Config.JMETER_BIN, os.X_OK)
