"""Remote execution on the JMeter Master through AWS SSM (the app itself runs on the engineer's computer).

Pipeline of a test run:
  1. servers   make sure Master (+ Slaves) are running and reachable by SSM (optionally start them)
  2. sync      git fetch + fast-forward to origin/<branch> on every server (the repo is the source of truth)
  3. slaves    check jmeter-server on each Slave from the Master (start it when needed)
  4. launch    take the Master lock (.jmcc/active) and start run_by_tag.sh detached (survives SSM / laptop sleep)
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

from . import aws, gitops, projects, runner
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
        c = aws.cfg()
        master = c["master"]
        ids = aws.node_ids(meta["distributed"])
        _ensure_servers(run_id, meta, ids, L)
        if _cancelled(run_id):
            raise Abort("cancelled before launch")
        left = aws.auto_off_minutes()
        if left is not None and left < 90:
            L(f"WARNING: the servers shut down automatically at {c['auto_off']} (in {left:.0f} min)")

        L(f"sync: {len(ids)} server(s) → origin/{meta['branch']} @ {meta['sha'][:8]}")
        results = aws.run_many(ids, gitops.server_sync_script(aws.remote_root(), meta["branch"]), timeout=180)
        for iid in ids:
            r = results[iid]
            if isinstance(r, Exception):
                raise Abort(f"sync failed on {iid}: {r}")
            rc, out, err = r
            m = re.search(r"@@SHA@@ ([0-9a-f]{40})", out)
            if rc != 0 or not m:
                raise Abort(f"sync failed on {iid} (exit {rc}): {(out + err).strip()[-300:]} — "
                            "the server clone has local changes or diverged; use Servers → Force sync")
            if m.group(1) != meta["sha"]:
                raise Abort(f"{iid} is at {m.group(1)[:8]} but this computer is at {meta['sha'][:8]}")
        L("sync: all servers at the same commit")

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


def _launch(run_id, meta, master, ips, L):
    j = _jdir()
    root = aws.remote_root()
    script = f"""
J={q(j)}; RUN={q(run_id)}
mkdir -p "$J/runs"
if [ -f "$J/active" ]; then
  read -r APID AUSER ATAG ARUN < "$J/active" || true
  if [ -n "$APID" ] && kill -0 "$APID" 2>/dev/null; then echo "@@BUSY@@ $AUSER $ATAG $ARUN"; exit 75; fi
fi
REAL=$(command -v jmeter) || {{ echo "@@NOJMETER@@"; exit 76; }}
cd {q(root + '/' + meta['project'])} || exit 77
export PATH={q(root + '/webapp/bin')}:"$PATH"
export SR_REAL_JMETER="$REAL" SR_EXTRA_PROPS={q(' '.join(meta['props']))} SR_REMOTE_HOSTS={q(','.join(ips))}
S=""; command -v setsid >/dev/null 2>&1 && S=setsid
$S nohup bash -c 'bash run_by_tag.sh "$0"; echo $? > "$1"' {q(meta['tag'])} "$J/runs/$RUN.rc" > "$J/runs/$RUN.log" 2>&1 < /dev/null &
PID=$!
echo "$PID {q(meta['user'])} {q(meta['tag'])} $RUN" > "$J/active"
echo "@@STARTED@@ $PID $REAL"
"""
    rc, out, err = aws.run(master, script, timeout=90)
    busy = re.search(r"@@BUSY@@ (\S+) (\S+) (\S+)", out)
    if busy:
        raise Abort(f"The Master is busy: {busy.group(1)} is running {busy.group(2)} (run {busy.group(3)}). "
                    "Wait for it or ask them to stop it.")
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
        aws.run(master, f'grep -q " {q(run_id)}$" {q(j)}/active 2>/dev/null && rm -f {q(j)}/active; true', 30)
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
    if result_dir and re.match(r"^Ejecucion_[A-Za-z0-9_.\-]+$", result_dir):
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
            ids = aws.node_ids(True)
            L(f"stopping {len(ids)} server(s) as requested")
            aws.stop(ids)
        except aws.AwsError as exc:
            L(f"WARNING: could not stop the servers: {exc}")


def collect(project, result_dir, L, token=None):
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
if [ "${{MB:-0}}" -gt {limit} ]; then EX="--exclude=*.jtl"; echo "@@NOJTL@@ $MB"; fi
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
    aws.run(master, 'for p in 4445 4446 4447; do echo -n "Shutdown" > /dev/udp/127.0.0.1/$p; done 2>/dev/null; true',
            timeout=60)
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
    """Who holds the Master lock right now (any engineer), or None."""
    j = _jdir()
    rc, out, _ = aws.run(aws.cfg()["master"],
                         f'[ -f {q(j)}/active ] && read -r P U T R < {q(j)}/active && kill -0 "$P" 2>/dev/null '
                         f'&& echo "@@ACTIVE@@ $U $T $R"; true', timeout=40)
    m = re.search(r"@@ACTIVE@@ (\S+) (\S+) (\S+)", out)
    return {"user": m.group(1), "tag": m.group(2), "run": m.group(3)} if m else None


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


def op_stop(log, force=False):
    ids = aws.node_ids(True)
    inst = {i["id"]: i for i in aws.instances(use_cache=False)}
    master = aws.cfg()["master"]
    if not force and inst.get(master, {}).get("state") == "running" and inst[master]["ssm"]:
        active = master_active()
        if active:
            raise Abort(f"{active['user']} is running {active['tag']} on the Master. Stop that run first "
                        "(or use Force stop).")
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


def op_sync(log, force=False):
    c = aws.cfg()
    br = c.get("branch") or gitops.branch()
    try:
        gitops._git("fetch", "--quiet", "origin", br, timeout=60)
        want = gitops.head_sha(f"origin/{br}")
    except (gitops.GitError, subprocess.TimeoutExpired) as exc:
        raise Abort(f"cannot read origin/{br} from this computer: {exc}")
    inst = {i["id"]: i for i in aws.instances(use_cache=False)}
    ids = [i for i in aws.node_ids(True) if inst[i]["state"] == "running" and inst[i]["ssm"]]
    if not ids:
        raise Abort("no running servers to sync")
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
            log(f"  {role}: FAILED (exit {rc}) {(out + err).strip()[-200:]}")
            bad += 1
    if bad:
        raise Abort(f"{bad} server(s) not in sync. If they have local changes use Force sync (discards them).")
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
              f"cd {q(aws.remote_root())} 2>/dev/null && echo \"git=$(git rev-parse --abbrev-ref HEAD) "
              f"$(git rev-parse --short HEAD) dirty=$(git status --porcelain 2>/dev/null | grep -v '^??' | wc -l | tr -d ' ')\"\n")
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
        log(f"  master lock: {active['user']} running {active['tag']} ({active['run']})" if active
            else "  master lock: free")


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
    log(f"signed in: {ident['arn']}")


def op_fetch(project, result_dir):
    def job(log):
        collect(project, result_dir, log)
    return job
