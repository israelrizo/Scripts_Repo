"""Remote execution on the JMeter Master through AWS SSM (the app itself runs on the engineer's computer).

Pipeline of a test run:
  1. servers   make sure Master (+ Slaves) are running and reachable by SSM (optionally start them)
  2. sync      push: copy this computer's project folder (+ webapp/bin) to every server over SSH through SSM
              git:  git fetch + fast-forward to origin/<branch> on every server
  3. slaves    check jmeter-server on each Slave from the Master (start it when needed)
  4. launch    take a Master slot (.jmcc/active.d/<project>: 1 test per project, max_runs per Master, Slaves for one
              distributed test) and start run_by_tag.sh detached (survives SSM / laptop sleep)
  5. monitor   poll the remote console log through SSM and mirror it into the local run log
  6. collect   download the result folder (tar.gz through an SSM tunnel) into this computer's clone
  7. finish    notifications, optional stop of the servers
Server maintenance jobs (start / stop / sync / health / SSO login) run as "ops" with the same console page.
"""
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from pathlib import Path

from . import aws, gitops, projects, push_sync, runner, settings
from .config import Config

q = shlex.quote
CHUNK = 16000          # SSM returns at most 24,000 characters of stdout per command
POLL_SECONDS = 3


class Abort(RuntimeError):
    pass


def _log(run_id, msg):
    with (runner._runs_dir() / f"{run_id}.log").open("a") as fh:
        fh.write(f"### [{time.strftime('%H:%M:%S')}] {msg}\n")


def _append(run_id, text):
    with (runner._runs_dir() / f"{run_id}.log").open("a") as fh:
        fh.write(text)


def _jdir():
    return f"{aws.remote_root()}/.jmcc"


def _cancelled(run_id):
    return (runner.get(run_id) or {}).get("status") == "stopping"


# --------------------------------------------------------------------------- pipeline
def pipeline(run_id):
    L = lambda m: _log(run_id, m)  # noqa: E731
    meta = runner.get(run_id)
    try:
        email = aws.sso_email()
        if email:   # who launched it, as the team sees it (AWS SSO e-mail)
            meta = runner.update(run_id, email=email)
        c = aws.cfg()
        master = c["master"]
        ids = aws.node_ids(meta["distributed"])
        _ensure_servers(run_id, meta, ids, L)
        if _cancelled(run_id):
            raise Abort("cancelled before launch")
        left = aws.auto_off_minutes()
        if left is not None and left < 90:
            L(f"WARNING: the servers shut down automatically at {c['auto_off']} (in {left:.0f} min)")

        _precheck(meta)
        if (meta.get("sync_method") or "git") == "push":
            L(f"sync: copying {meta['project']} from this computer to {len(ids)} server(s) (SSH through SSM)"
              + (f" · includes {meta['local_changes']} uncommitted change(s)" if meta.get("local_changes") else ""))
            try:
                push_sync.push(ids, L, only=[meta["project"], "webapp/bin"])
            except push_sync.SyncError as exc:
                raise Abort(str(exc))
            ids_to_check = []
        else:
            L(f"sync: {len(ids)} server(s) → origin/{meta['branch']} @ {meta['sha'][:8]}")
            results = aws.run_many(ids, gitops.server_sync_script(aws.remote_root(), meta["branch"]), timeout=180)
            ids_to_check = ids
        for iid in ids_to_check:
            r = results[iid]
            if isinstance(r, Exception):
                raise Abort(f"sync failed on {iid}: {r}")
            rc, out, err = r
            m = re.search(r"@@SHA@@ ([0-9a-f]{40})", out)
            if rc != 0 or not m:
                raise Abort(f"sync failed on {iid} (exit {rc}): {(out + err).strip()[-300:]} — "
                            f"{gitops.sync_hint(rc, out + err)}")
            if m.group(1) != meta["sha"]:
                raise Abort(f"{iid} is at {m.group(1)[:8]} but this computer is at {meta['sha'][:8]}")
        L("sync: all servers have this computer's files" if ids_to_check == [] else "sync: all servers at the same commit")

        ips = []
        if meta["distributed"]:
            ips = _check_slaves(run_id, master, ids[1:], L)
        if _cancelled(run_id):
            raise Abort("cancelled before launch")

        pid = _launch(run_id, meta, master, ips, L)
        meta = runner.update(run_id, status="running", started=time.time(), remote_pid=pid, remote_offset=0,
                             remote_hosts=ips, stage="running")
        if meta["status"] == "stopping":   # a stop arrived while launching
            stop(meta)
        runner._fire("start", meta)
    except (Abort, aws.AwsError, gitops.GitError, projects.ProjectError) as exc:
        L(f"ABORTED: {exc}")
        cur = runner.get(run_id) or {}
        runner.update(run_id, status="stopped" if cur.get("status") == "stopping" else "failed",
                      ended=time.time(), error=str(exc)[:300])
        return
    except Exception as exc:  # noqa: BLE001
        L(f"ABORTED (unexpected): {type(exc).__name__}: {exc}")
        runner.update(run_id, status="failed", ended=time.time(), error=str(exc)[:300])
        return
    monitor(run_id)


def _ensure_servers(run_id, meta, ids, L):
    inst = {i["id"]: i for i in aws.instances(use_cache=False)}
    missing = [i for i in ids if i not in inst or inst[i]["state"] == "not-found"]
    if missing:
        raise Abort(f"Instance(s) not found: {', '.join(missing)} (Settings → AWS)")
    down = [i for i in ids if inst[i]["state"] != "running" or not inst[i]["ssm"]]
    if not down:
        L("servers: " + ", ".join(f"{inst[i]['role']} running" for i in ids))
        return
    if not meta.get("auto_start"):
        raise Abort("Servers are not running: " + ", ".join(f"{inst[i]['role']} ({inst[i]['state']})" for i in down)
                    + ". Start them on the Servers page or tick 'Start servers if they are stopped'.")
    stopped = [i for i in down if inst[i]["state"] == "stopped"]
    if stopped:
        L(f"servers: starting {len(stopped)} instance(s)")
        aws.start(stopped)
        runner.update(run_id, started_servers=True)
    aws.wait_ready(ids, L)


def _check_slaves(run_id, master, slave_ids, L):
    c = aws.cfg()
    inst = {i["id"]: i for i in aws.instances(use_cache=False)}
    ips = [inst[s]["private_ip"] for s in slave_ids]
    if not all(ips):
        raise Abort("Could not read the private IP of every Slave")
    port = int(c.get("rmi_port") or 1099)
    probe = "\n".join(f'(timeout 4 bash -c "</dev/tcp/{ip}/{port}") 2>/dev/null && echo "@@UP@@ {ip}" || echo "@@DOWN@@ {ip}"'
                      for ip in ips)
    rc, out, _ = aws.run(master, probe, timeout=60)
    down = re.findall(r"@@DOWN@@ (\S+)", out)
    if down and c.get("slave_start_cmd"):
        L(f"slaves: jmeter-server not answering on {', '.join(down)}; starting it")
        for sid in slave_ids:
            if inst[sid]["private_ip"] in down:
                aws.run(sid, c["slave_start_cmd"], timeout=90, as_user=False)
        time.sleep(8)
        rc, out, _ = aws.run(master, probe, timeout=60)
        down = re.findall(r"@@DOWN@@ (\S+)", out)
    if down:
        raise Abort(f"jmeter-server is not reachable from the Master on {', '.join(down)}:{port}")
    L(f"slaves: jmeter-server up on {', '.join(ips)}")
    return ips


def _slot_scan():
    """Shell snippet: walk the Master slots, drop stale ones, count live ones (sets N, prints @@ACTIVE@@ lines)."""
    return r"""
N=0
for f in "$J"/active.d/* "$J/active"; do
  [ -f "$f" ] || continue
  APID= AUSER= ATAG= ARUN= APROJ= ADIST=
  read -r APID AUSER ATAG ARUN APROJ ADIST < "$f" || true
  if [ -n "$APID" ] && kill -0 "$APID" 2>/dev/null; then
    N=$((N+1)); echo "@@ACTIVE@@ $AUSER $ATAG $ARUN ${APROJ:--} ${ADIST:-0}"
  else
    rm -f "$f"
  fi
done
"""


def _launch(run_id, meta, master, ips, L):
    j = _jdir()
    root = aws.remote_root()
    proj = meta["project"]
    max_runs = int(aws.cfg().get("max_runs") or 3)
    dist = 1 if ips else 0
    script = f"""
J={q(j)}; RUN={q(run_id)}; P={q(proj)}; MAX={max_runs}; DIST={dist}
mkdir -p "$J/runs" "$J/active.d"
exec 9>"$J/slots.lock"
if command -v flock >/dev/null 2>&1; then flock -w 30 9 || {{ echo "@@LOCKWAIT@@"; exit 74; }}; fi
{_slot_scan()}
if [ -f "$J/active.d/$P" ]; then read -r a u t r rest < "$J/active.d/$P"; echo "@@BUSYPROJ@@ $u $t $r"; exit 75; fi
if [ "$DIST" = 1 ] && grep -qs ' 1$' "$J"/active.d/* ; then
  b=$(grep -ls ' 1$' "$J"/active.d/* | head -1); read -r a u t r rest < "$b"; echo "@@BUSYSLAVES@@ $u $t $r"; exit 75
fi
if [ "$N" -ge "$MAX" ]; then echo "@@BUSYMAX@@ $N"; exit 75; fi
REAL=$(command -v jmeter) || {{ echo "@@NOJMETER@@"; exit 76; }}
cd {q(root + '/' + proj)} || exit 77
export PATH={q(root + '/webapp/bin')}:"$PATH"
export SR_REAL_JMETER="$REAL" SR_EXTRA_PROPS={q(' '.join(meta['props']))} SR_REMOTE_HOSTS={q(','.join(ips))}
S=""; command -v setsid >/dev/null 2>&1 && S=setsid
$S nohup bash -c 'bash run_by_tag.sh "$0"; echo $? > "$1"' {q(meta['tag'])} "$J/runs/$RUN.rc" > "$J/runs/$RUN.log" 2>&1 < /dev/null 9>&- &
PID=$!
echo "$PID {q(meta['user'])} {q(meta['tag'])} $RUN $P $DIST" > "$J/active.d/$P"
echo "@@STARTED@@ $PID $REAL"
"""
    rc, out, err = aws.run(master, script, timeout=90)
    busy = re.search(r"@@BUSYPROJ@@ (\S+) (\S+) (\S+)", out)
    if busy:
        raise Abort(f"{meta['project']} is already running on the Master: {busy.group(1)} started {busy.group(2)} "
                    f"(run {busy.group(3)}). Only one execution per project at a time.")
    busy = re.search(r"@@BUSYSLAVES@@ (\S+) (\S+) (\S+)", out)
    if busy:
        raise Abort(f"The Slaves are in use by {busy.group(1)} ({busy.group(2)}, run {busy.group(3)}): only one "
                    "distributed test at a time. Run without the Slaves or wait.")
    m = re.search(r"@@BUSYMAX@@ (\d+)", out)
    if m:
        raise Abort(f"The Master already runs {m.group(1)} tests (maximum {max_runs} at the same time). Wait for one "
                    "to finish.")
    if "@@LOCKWAIT@@" in out:
        raise Abort("Another engineer is launching a test right now; try again in a few seconds")
    if "@@NOJMETER@@" in out:
        raise Abort(f"'jmeter' is not on the PATH of user {aws.cfg().get('remote_user') or 'root'} on the Master")
    m = re.search(r"@@STARTED@@ (\d+) (\S+)", out)
    if rc != 0 or not m:
        raise Abort(f"launch failed (exit {rc}): {(out + err).strip()[-300:]}")
    L(f"launched on the Master: pid {m.group(1)} · {m.group(2)}"
      + (f" · -R {','.join(ips)}" if ips else " · Master only"))
    _append(run_id, "#" * 60 + "\n")
    return int(m.group(1))


# --------------------------------------------------------------------------- monitor
def monitor(run_id):
    """Mirror the remote console into the local log until the run ends (safe to call again after a restart)."""
    L = lambda m: _log(run_id, m)  # noqa: E731
    master = aws.cfg()["master"]
    j = _jdir()
    fails, warned_auth = 0, False
    while True:
        meta = runner.get(run_id)
        if not meta or meta["status"] not in ("running", "stopping"):
            return
        off = int(meta.get("remote_offset") or 0)
        script = (f'L={q(j)}/runs/{q(run_id)}.log; S=$(stat -c %s "$L" 2>/dev/null || stat -f %z "$L" 2>/dev/null || echo 0)\n'
                  f'tail -c +{off + 1} "$L" 2>/dev/null | head -c {CHUNK}\n'
                  f'printf "\\n@@META@@ %s %s\\n" "$S" "$(cat {q(j)}/runs/{q(run_id)}.rc 2>/dev/null || echo -)"\n')
        try:
            rc, out, err = aws.run(master, script, timeout=60)
            fails = 0
            if warned_auth:
                L("AWS session is back, monitoring resumed")
                warned_auth = False
        except aws.AwsError as exc:
            if exc.auth:
                if not warned_auth:
                    L(f"AWS session problem: {exc}. Sign in again (Settings → AWS → SSO login); "
                      "the test keeps running on the Master and monitoring resumes automatically.")
                    warned_auth = True
                time.sleep(20)
                continue
            fails += 1
            state = None
            try:
                state = next((i["state"] for i in aws.instances(use_cache=False) if i["id"] == master), None)
            except aws.AwsError:
                pass
            if state and state != "running":
                hint = f" (daily auto-off {aws.cfg().get('auto_off')})" if aws.cfg().get("auto_off") else ""
                L(f"INTERRUPTED: the Master is {state}{hint}")
                meta = runner.update(run_id, status="interrupted", ended=time.time(), error=f"Master {state}")
                runner._fire("end", meta)
                return
            if fails >= 20:
                L(f"INTERRUPTED: lost contact with the Master ({exc})")
                meta = runner.update(run_id, status="interrupted", ended=time.time(), error=str(exc)[:200])
                runner._fire("end", meta)
                return
            time.sleep(6)
            continue
        m = re.search(r"\n@@META@@ (\d+) (\S+)\s*$", out)
        if not m:
            time.sleep(POLL_SECONDS)
            continue
        size, rcval = int(m.group(1)), m.group(2)
        chunk = out[:m.start()]
        consumed = min(CHUNK, max(0, size - off))
        if chunk and consumed:
            _append(run_id, chunk)
        new_off = off + consumed
        if new_off != off:
            runner.update(run_id, remote_offset=new_off)
        if rcval != "-" and new_off >= size:
            finish(run_id, int(rcval) if rcval.lstrip("-").isdigit() else 1)
            return
        if new_off < size:
            continue  # more output waiting
        time.sleep(POLL_SECONDS)


def finish(run_id, rc):
    L = lambda m: _log(run_id, m)  # noqa: E731
    meta = runner.get(run_id)
    master = aws.cfg()["master"]
    j = _jdir()
    _append(run_id, "\n" + "#" * 60 + "\n")
    try:
        aws.run(master, f'for f in {q(j)}/active.d/* {q(j)}/active; do [ -f "$f" ] || continue; '
                        f'read -r a b c r rest < "$f"; [ "$r" = {q(run_id)} ] && rm -f "$f"; done; true', 30)
    except aws.AwsError:
        pass
    status = "stopped" if meta["status"] == "stopping" else ("finished" if rc == 0 else "failed")
    text, _ = runner.read_log(run_id, 0, 20 * 1024 * 1024)
    result_dir = None
    for line in text.splitlines():
        m = runner.RESULT_RE.search(line)
        if m:
            result_dir = Path(m.group(1)).name
    updates = {"returncode": rc}
    if result_dir and result_dir.startswith("Ejecucion_") and aws.safe_name(result_dir):
        try:
            collect(meta["project"], result_dir, L, run_id)
            updates["result_dir"] = result_dir
        except (aws.AwsError, Abort, OSError, tarfile.TarError) as exc:
            L(f"WARNING: results not downloaded ({exc}). They stay on the Master; use Reports → Fetch from Master.")
            updates["result_remote_only"] = result_dir
    meta = runner.update(run_id, status=status, ended=time.time(), **updates)
    L(f"run {status} (exit {rc})")
    runner._fire("end", meta)
    if meta.get("stop_after"):
        time.sleep(2)
        try:
            others = master_active()
            if others:
                L("servers left running: other tests are still running on the Master ("
                  + ", ".join(f"{a['user']} {a['tag']}" for a in others) + ")")
                return
            ids = aws.node_ids(True)
            L(f"stopping {len(ids)} server(s) as requested")
            aws.stop(ids)
        except aws.AwsError as exc:
            L(f"WARNING: could not stop the servers: {exc}")


def collect(project, result_dir, L, token=None, include_jtl=True):
    """tar the result folder on the Master, download it through SSM and unpack it into the local clone."""
    c = aws.cfg()
    master = c["master"]
    token = token or f"fetch{int(time.time())}"
    outbox = f"{_jdir()}/outbox/{token}"
    limit = int(c.get("jtl_max_mb") or 200)
    script = f"""
cd {q(aws.remote_root() + '/' + project + '/results')} || exit 3
[ -d {q(result_dir)} ] || {{ echo "@@MISSING@@"; exit 4; }}
mkdir -p {q(outbox)}
MB=$(du -cm {q(result_dir)}/*.jtl 2>/dev/null | tail -1 | cut -f1)
EX=""
if [ {0 if include_jtl else 1} = 1 ]; then EX="--exclude=*.jtl"; echo "@@SKIPJTL@@";
elif [ "${{MB:-0}}" -gt {limit} ]; then EX="--exclude=*.jtl"; echo "@@NOJTL@@ $MB"; fi
tar -czf {q(outbox)}/{q(result_dir)}.tar.gz $EX {q(result_dir)} && echo "@@TAR@@ OK"
"""
    rc, out, err = aws.run(master, script, timeout=900)
    if "@@MISSING@@" in out:
        raise Abort(f"{result_dir} does not exist on the Master")
    if rc != 0 or "@@TAR@@ OK" not in out:
        raise Abort(f"could not package the results: {(out + err).strip()[-200:]}")
    nojtl = re.search(r"@@NOJTL@@ (\d+)", out)
    if nojtl:
        L(f"the .jtl is {nojtl.group(1)} MB (> {limit} MB): left on the Master, report downloaded without it")
    dest = projects.project_dir(project) / "results"
    dest.mkdir(exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="jmcc_", dir=str(Config.INSTANCE_DIR)))
    try:
        local_tar = tmpdir / f"{result_dir}.tar.gz"
        aws.fetch_file(master, outbox, f"{result_dir}.tar.gz", local_tar, L)
        with tarfile.open(local_tar) as tf:
            base = (tmpdir / "x").resolve()
            for member in tf.getmembers():
                target = (base / member.name).resolve()
                if base not in target.parents and target != base:
                    raise Abort("unsafe path in archive")
                if member.issym() or member.islnk() or member.isdev():
                    raise Abort("unsafe entry in archive")
            tf.extractall(base)
        src = base / result_dir
        if not src.is_dir():
            raise Abort("archive does not contain the result folder")
        final = dest / result_dir
        if final.exists():
            shutil.rmtree(final)
        shutil.move(str(src), str(final))
        L(f"results saved in {project}/results/{result_dir}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        try:
            aws.run(master, f"rm -rf {q(outbox)}", 60)
        except aws.AwsError:
            pass


def stop(meta, force=False):
    master = aws.cfg()["master"]
    pid = meta.get("remote_pid")
    if not pid:
        return "Cancelling before launch."
    if force:
        script = (f'kt() {{ for c in $(pgrep -P "$1" 2>/dev/null); do kt "$c"; done; kill -TERM "$1" 2>/dev/null; }}\n'
                  f"kill -TERM -- -{int(pid)} 2>/dev/null || kt {int(pid)}\n"
                  f'echo 143 > {q(_jdir())}/runs/{q(meta["id"])}.rc\n')
        aws.run(master, script, timeout=60)
        return "Kill sent to the Master (no HTML report will be generated)."
    # Several tests may run on the Master: send Shutdown only to the UDP port of THIS run's JMeter (4445…4455).
    script = f"""
kill -0 {int(pid)} 2>/dev/null || {{ echo "@@GONE@@"; exit 0; }}
d() {{ echo "$1"; for c in $(pgrep -P "$1" 2>/dev/null); do d "$c"; done; }}
PIDS=$(d {int(pid)} | tr '\\n' '|' | sed 's/|$//')
[ -n "$PIDS" ] || {{ echo "@@GONE@@"; exit 0; }}
PORTS=$(ss -Hulnp 2>/dev/null | grep -E "pid=($PIDS)," | grep -oE ':(444[5-9]|445[0-5]) ' | tr -d ': ' | sort -u)
[ -n "$PORTS" ] || {{ echo "@@NOPORT@@"; exit 0; }}
for p in $PORTS; do echo -n "Shutdown" > /dev/udp/127.0.0.1/$p && echo "@@SENT@@ $p"; done
"""
    rc, out, _ = aws.run(master, script, timeout=60)
    if "@@GONE@@" in out:
        return "The test already ended on the Master."
    if "@@SENT@@" not in out:
        return ("Could not find this run's JMeter shutdown port on the Master; use Force stop "
                "(other tests on the Master are not affected).")
    return "Graceful shutdown requested on the Master (threads finish their current iteration)."


def resume_all():
    """After an app restart: re-attach to runs still executing on the Master."""
    for meta in runner.list_runs(limit=100):
        if meta.get("mode") != "aws" or meta.get("kind") != "test":
            continue
        if meta["status"] in ("running", "stopping") and meta.get("remote_pid"):
            _log(meta["id"], "Control Center restarted: re-attaching to the run on the Master")
            threading.Thread(target=monitor, args=(meta["id"],), daemon=True).start()
        elif meta["status"] == "starting":
            runner.update(meta["id"], status="interrupted", ended=time.time(),
                          error="Control Center restarted before the launch")


# --------------------------------------------------------------------------- remote info
def master_active():
    """Tests running on the Master right now (any engineer): [{user, tag, run, project, distributed}]."""
    j = _jdir()
    rc, out, _ = aws.run(aws.cfg()["master"], f"J={q(j)}\n{_slot_scan()}\ntrue", timeout=40)
    return [{"user": u, "tag": t, "run": r, "project": "" if p == "-" else p, "distributed": d == "1"}
            for u, t, r, p, d in re.findall(r"@@ACTIVE@@ (\S+) (\S+) (\S+) (\S+) (\S+)", out)]


def _precheck(meta):
    """Fail fast (before copying anything) when the project, the Slaves or every Master slot is taken."""
    try:
        act = master_active()
    except aws.AwsError:
        return
    max_runs = int(aws.cfg().get("max_runs") or 3)
    for a in act:
        if a["project"] == meta["project"] and a["run"] != meta["id"]:
            raise Abort(f"{meta['project']} is already running on the Master: {a['user']} started {a['tag']} "
                        f"(run {a['run']}). Only one execution per project at a time.")
        if meta.get("distributed") and a["distributed"]:
            raise Abort(f"The Slaves are in use by {a['user']} ({a['tag']}): only one distributed test at a time.")
    if len(act) >= max_runs:
        raise Abort(f"The Master already runs {len(act)} tests (maximum {max_runs} at the same time).")


def remote_results(project, limit=40):
    """Result folders on the Master for a project: [{name, mb, local}]."""
    pdir = projects.project_dir(project)
    rc, out, err = aws.run(aws.cfg()["master"],
                           f"cd {q(aws.remote_root() + '/' + project + '/results')} 2>/dev/null || exit 0\n"
                           f"ls -1dt Ejecucion_*/ 2>/dev/null | head -{int(limit)} | while read -r d; do "
                           f'd=${{d%/}}; echo "@@R@@ $d $(du -sm "$d" | cut -f1) $([ -f "$d/html_report/index.html" ] && echo 1 || echo 0)"; done',
                           timeout=60)
    out_list = []
    for name, mb, has in re.findall(r"@@R@@ (\S+) (\d+) ([01])", out):
        out_list.append({"name": name, "mb": int(mb), "has_report": has == "1",
                         "local": (pdir / "results" / name).is_dir()})
    return out_list


# --------------------------------------------------------------------------- ops (server maintenance jobs)
def op_start(log):
    ids = aws.node_ids(True)
    inst = {i["id"]: i for i in aws.instances(use_cache=False)}
    stopped = [i for i in ids if inst[i]["state"] == "stopped"]
    if stopped:
        log(f"starting {len(stopped)} instance(s): {', '.join(inst[i]['role'] for i in stopped)}")
        aws.start(stopped)
    else:
        log("no stopped instances")
    aws.wait_ready(ids, log)
    left = aws.auto_off_minutes()
    if left is not None:
        log(f"servers ready · automatic shutdown at {aws.cfg()['auto_off']} (in {left / 60:.1f} h)")
    _team_sync(log)


def _team_sync(log):
    from . import team
    if not settings.get()["team"].get("auto_sync"):
        return
    try:
        team.sync(log)
    except Exception as exc:  # noqa: BLE001 - the sync never fails the job that triggered it
        log(f"team sync failed: {exc}")


def op_stop(log, force=False):
    ids = aws.node_ids(True)
    inst = {i["id"]: i for i in aws.instances(use_cache=False)}
    master = aws.cfg()["master"]
    if not force and inst.get(master, {}).get("state") == "running" and inst[master]["ssm"]:
        active = master_active()
        if active:
            raise Abort("Tests are running on the Master: " + ", ".join(f"{a['user']} {a['tag']}" for a in active)
                        + ". Stop them first (or use Force stop).")
    running = [i for i in ids if inst[i]["state"] in ("running", "pending")]
    if not running:
        log("all servers are already stopped")
        return
    from . import tunnels
    tunnels.close_all()
    log(f"stopping {len(running)} instance(s)")
    aws.stop(running)
    deadline = time.time() + 240
    while time.time() < deadline:
        cur = aws.instances(use_cache=False)
        log("servers: " + ", ".join(f"{i['role']}={i['state']}" for i in cur))
        if all(i["state"] in ("stopped", "terminated", "not-found") for i in cur):
            return
        time.sleep(8)


def op_sync(log, force=False, project=None):
    c = aws.cfg()
    inst = {i["id"]: i for i in aws.instances(use_cache=False)}
    ids = [i for i in aws.node_ids(True) if inst[i]["state"] == "running" and inst[i]["ssm"]]
    if not ids:
        raise Abort("no running servers to sync")
    if (c.get("sync_method") or "push") == "push":
        busy = []
        try:
            busy = sorted({a["project"] for a in master_active() if a["project"]})
        except aws.AwsError:
            pass
        br, sha, n = push_sync.local_state()
        log(f"{'MIRROR ' if force else ''}copy of {project or 'every project'} from this computer ({br}@{sha[:8]}"
            f"{f' + {n} uncommitted change(s)' if n else ''}) to {len(ids)} server(s)")
        if project and project in busy:
            raise Abort(f"{project} has a test running on the Master; its files cannot change until it ends")
        if busy and not project:
            log(f"  left untouched because a test is running: {', '.join(busy)}")
        try:
            if project:
                push_sync.push(ids, log, only=[project, "webapp/bin"])
            else:
                push_sync.push(ids, log, mirror=force, skip=busy)
        except push_sync.SyncError as exc:
            raise Abort(str(exc))
        log("all servers have this computer's scripts")
        return
    br = c.get("branch") or gitops.branch()
    try:
        gitops._git("fetch", "--quiet", "origin", br, timeout=60)
        want = gitops.head_sha(f"origin/{br}")
    except (gitops.GitError, subprocess.TimeoutExpired) as exc:
        raise Abort(f"cannot read origin/{br} from this computer: {exc}")
    log(f"{'FORCE ' if force else ''}sync origin/{br} @ {want[:8]} on {len(ids)} server(s)")
    results = aws.run_many(ids, gitops.server_sync_script(aws.remote_root(), br, force), timeout=180)
    bad = 0
    for iid in ids:
        r = results[iid]
        role = inst[iid]["role"]
        if isinstance(r, Exception):
            log(f"  {role}: ERROR {r}")
            bad += 1
            continue
        rc, out, err = r
        m = re.search(r"@@SHA@@ ([0-9a-f]{40})", out)
        if rc == 0 and m and m.group(1) == want:
            log(f"  {role}: OK {m.group(1)[:8]}")
        else:
            log(f"  {role}: FAILED (exit {rc}) {(out + err).strip()[-200:]} — {gitops.sync_hint(rc, out + err)}")
            bad += 1
    if bad:
        raise Abort(f"{bad} server(s) not in sync (see the reason above each server).")
    log("all servers in sync with the repository")


def op_health(log):
    c = aws.cfg()
    inst = aws.instances(use_cache=False)
    up = [i for i in inst if i["state"] == "running" and i["ssm"]]
    for i in inst:
        log(f"{i['role']}: {i['id']} {i['state']}{' · SSM online' if i['ssm'] else ''} {i['private_ip']} {i['type']}")
    if not up:
        return
    script = (f"echo \"host=$(hostname) up=$(uptime -p 2>/dev/null || uptime)\"\n"
              f"echo \"disk=$(df -h {q(aws.remote_root())} 2>/dev/null | tail -1 | awk '{{print $4\" free of \"$2}}')\"\n"
              f"echo \"jmeter=$(command -v jmeter || echo NOT-FOUND)\"\n"
              f"echo \"rsync=$(command -v rsync || echo no) ssh22=$( (exec 3<>/dev/tcp/127.0.0.1/22) 2>/dev/null && echo up || echo DOWN)\"\n"
              + ("" if (c.get("sync_method") or "push") == "push" else
                 f"cd {q(aws.remote_root())} 2>/dev/null && echo \"git=$(git rev-parse --abbrev-ref HEAD) "
                 f"$(git rev-parse --short HEAD) dirty=$(git status --porcelain 2>/dev/null | grep -v '^??' | wc -l | tr -d ' ')\"\n"))
    results = aws.run_many([i["id"] for i in up], script, timeout=90)
    for i in up:
        r = results[i["id"]]
        if isinstance(r, Exception):
            log(f"  {i['role']}: ERROR {r}")
        else:
            for line in r[1].strip().splitlines():
                log(f"  {i['role']}: {line}")
    master = next((i for i in up if i["id"] == c["master"]), None)
    slaves = [i for i in up if i["id"] != c["master"]]
    if master and slaves:
        port = int(c.get("rmi_port") or 1099)
        probe = "\n".join(f'(timeout 4 bash -c "</dev/tcp/{s["private_ip"]}/{port}") 2>/dev/null && echo "{s["role"]} '
                          f'jmeter-server UP ({s["private_ip"]}:{port})" || echo "{s["role"]} jmeter-server DOWN '
                          f'({s["private_ip"]}:{port})"' for s in slaves)
        rc, out, _ = aws.run(master["id"], probe, timeout=60)
        for line in out.strip().splitlines():
            log(f"  master → {line}")
    if master:
        active = master_active()
        mx = int(c.get("max_runs") or 3)
        if active:
            for a in active:
                log(f"  master slot: {a['user']} running {a['tag']} ({a['project'] or '?'}, run {a['run']}"
                    f"{', distributed' if a['distributed'] else ''})")
        log(f"  master slots in use: {len(active)}/{mx}")
    if (c.get("sync_method") or "push") == "push":
        for i in up:
            ok, msg = push_sync.test(i["id"])
            log(f"  {i['role']}: SSH through SSM {'OK ' + msg if ok else 'FAILED: ' + msg}")


def op_sso_login(log):
    args = aws._base_args() + ["sso", "login"]
    log("running: aws sso login (a browser window opens on this computer)")
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise Abort("AWS CLI not found on this computer")
    deadline = time.time() + 300
    for line in proc.stdout:
        log(line.rstrip())
        if time.time() > deadline:
            proc.kill()
            raise Abort("SSO login timed out")
    if proc.wait() != 0:
        raise Abort("aws sso login failed (is this profile an SSO profile? otherwise run 'aws configure')")
    aws.invalidate()
    ident = aws.identity()
    log(f"signed in: {ident['email'] or ident['arn'].rsplit('/', 1)[-1]}")
    from . import team
    ok, why = team.master_ready()
    if ok:
        _team_sync(log)
    else:
        log(f"team sync: {why} — it runs when the servers start")


def op_team_sync(log):
    from . import team
    team.sync(log)


def op_fetch(project, result_dir):
    def job(log):
        collect(project, result_dir, log)
    return job
