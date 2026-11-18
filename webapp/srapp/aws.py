"""AWS CLI / SSM layer: the app runs on the engineer's computer and drives Master + Slaves remotely.

Everything goes through the `aws` command already configured on the computer (profile / SSO):
  * EC2:  describe / start / stop instances
  * SSM:  send-command (AWS-RunShellScript) to run scripts on the servers,
          start-session (AWS-StartPortForwardingSession) for tunnels and file download
No SSH keys and no inbound ports are needed.
"""
import base64
import json
import os
import re
import shlex
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid

from . import settings
from .config import Config, _env

AWS_BIN = _env("SR_AWS_BIN", "aws")
ID_RE = re.compile(r"^i-[0-9a-f]{8,17}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_\-]{0,31}$")
PATH_RE = re.compile(r"^/[A-Za-z0-9_.\-/]{1,200}$")
AUTH_HINTS = ("expired", "sso", "unable to locate credentials", "invalidclienttokenid", "token", "unauthorized",
              "not authorized", "accessdenied", "login")
_cache = {"ts": 0, "data": None}
_cache_lock = threading.Lock()


class AwsError(RuntimeError):
    @property
    def auth(self):
        low = str(self).lower()
        return any(h in low for h in AUTH_HINTS)


def cfg():
    return settings.get()["aws"]


def validate(c):
    """Raises ValueError when the AWS settings are unsafe or incomplete."""
    for key in ("profile", "region"):
        if c.get(key) and not NAME_RE.match(c[key]):
            raise ValueError(f"Invalid AWS {key}")
    ids = [c.get("master", "")] + list(c.get("slaves") or [])
    for i in ids:
        if i and not ID_RE.match(i):
            raise ValueError(f"Invalid instance id '{i}' (expected i-0123456789abcdef0)")
    if c.get("remote_user") and not USER_RE.match(c["remote_user"]):
        raise ValueError("Invalid remote user")
    if not PATH_RE.match(c.get("remote_root") or "") or ".." in c["remote_root"]:
        raise ValueError("Remote scripts folder must be an absolute path")
    if c.get("branch") and not re.match(r"^[A-Za-z0-9_.\-/]{1,100}$", c["branch"]):
        raise ValueError("Invalid branch name")
    if c.get("auto_off") and not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", c["auto_off"]):
        raise ValueError("Auto-off time must be HH:MM")
    if (c.get("sync_method") or "push") not in ("push", "git"):
        raise ValueError("Sync method must be push or git")
    key = c.get("ssh_key") or ""
    if key and (len(key) > 300 or re.search(r'[\x00-\x1f"\x7f]', key)):
        raise ValueError("Invalid SSH key path")
    try:
        if not 1 <= int(c.get("max_runs") or 3) <= 10:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("Tests at the same time must be between 1 and 10")
    return c


def _base_args():
    c = cfg()
    args = [AWS_BIN]
    if c.get("profile"):
        args += ["--profile", c["profile"]]
    if c.get("region"):
        args += ["--region", c["region"]]
    return args


def call(args, timeout=60, parse=True):
    cmd = _base_args() + list(args) + (["--output", "json"] if parse else [])
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           encoding="utf-8", errors="replace",
                           env=dict(os.environ, AWS_PAGER="", AWS_CLI_AUTO_PROMPT="off"),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        raise AwsError("AWS CLI not found on this computer (install AWS CLI v2)")
    except subprocess.TimeoutExpired:
        raise AwsError(f"aws {' '.join(args[:2])} timed out after {timeout}s")
    if p.returncode != 0:
        msg = (p.stderr or p.stdout).strip().splitlines()
        raise AwsError(" ".join(msg[-3:])[:500] or f"aws {' '.join(args[:2])} failed")
    if not parse:
        return p.stdout
    try:
        return json.loads(p.stdout) if p.stdout.strip() else {}
    except ValueError:
        raise AwsError(f"Unexpected output from aws {' '.join(args[:2])}")


# --------------------------------------------------------------------------- identity / instances
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_ident_cache = {"at": 0.0, "value": None}


def identity():
    d = call(["sts", "get-caller-identity"], timeout=30)
    arn = d.get("Arn") or ""
    return {"account": d.get("Account"), "arn": arn, "email": email_from_arn(arn)}


def email_from_arn(arn):
    """AWS SSO assumed-role ARNs end with the user's e-mail:
    arn:aws:sts::<acct>:assumed-role/AWSReservedSSO_<PermissionSet>_<hash>/<e-mail>  ->  <e-mail> (lower case).
    Anything else (IAM users, other roles) -> ''."""
    tail = (arn or "").rsplit("/", 1)[-1].strip()
    return tail.lower() if ":assumed-role/" in (arn or "") and EMAIL_RE.match(tail) else ""


def sso_email(max_age=600):
    """E-mail of the engineer signed in with aws sso login ('' when unknown). Cached for a few minutes."""
    if time.time() - _ident_cache["at"] < max_age and _ident_cache["value"] is not None:
        return _ident_cache["value"]
    try:
        value = identity()["email"]
    except AwsError:
        value = ""
    _ident_cache.update(at=time.time(), value=value)
    return value


def node_ids(distributed=True):
    c = cfg()
    ids = [c["master"]] if c.get("master") else []
    if distributed:
        ids += [s for s in c.get("slaves") or [] if s]
    return ids


def instances(use_cache=True, max_age=8):
    """[{id, role, name, state, private_ip, ssm}] for master + slaves (cached a few seconds)."""
    with _cache_lock:
        if use_cache and _cache["data"] is not None and time.time() - _cache["ts"] < max_age:
            return _cache["data"]
    c = cfg()
    ids = node_ids()
    if not ids:
        raise AwsError("No instances configured (Settings → AWS)")
    d = call(["ec2", "describe-instances", "--instance-ids", *ids], timeout=40)
    found = {}
    for r in d.get("Reservations", []):
        for i in r.get("Instances", []):
            name = next((t["Value"] for t in i.get("Tags", []) if t.get("Key") == "Name"), "")
            found[i["InstanceId"]] = {"id": i["InstanceId"], "name": name, "state": i["State"]["Name"],
                                      "private_ip": i.get("PrivateIpAddress", ""), "type": i.get("InstanceType", "")}
    online = set()
    running = [i for i, v in found.items() if v["state"] == "running"]
    if running:
        try:
            info = call(["ssm", "describe-instance-information", "--filters",
                         f"Key=InstanceIds,Values={','.join(running)}"], timeout=40)
            online = {x["InstanceId"] for x in info.get("InstanceInformationList", []) if x.get("PingStatus") == "Online"}
        except AwsError:
            pass
    out = []
    for n, iid in enumerate(ids):
        v = found.get(iid, {"id": iid, "name": "", "state": "not-found", "private_ip": "", "type": ""})
        v["role"] = "master" if iid == c.get("master") else f"slave {n}"
        v["ssm"] = iid in online
        out.append(v)
    with _cache_lock:
        _cache.update(ts=time.time(), data=out)
    return out


def invalidate():
    with _cache_lock:
        _cache["data"] = None
    _ident_cache.update(at=0.0, value=None)


def start(ids):
    if ids:
        call(["ec2", "start-instances", "--instance-ids", *ids], timeout=60)
        invalidate()


def stop(ids):
    if ids:
        call(["ec2", "stop-instances", "--instance-ids", *ids], timeout=60)
        invalidate()


def wait_ready(ids, log=lambda m: None, timeout=420):
    """Wait until every instance is running AND its SSM agent is online."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        cur = {i["id"]: i for i in instances(use_cache=False) if i["id"] in ids}
        state = ", ".join(f"{v['role']}={v['state']}{'/ssm' if v['ssm'] else ''}" for v in cur.values())
        if state != last:
            log(f"servers: {state}")
            last = state
        if all(v["state"] == "running" and v["ssm"] for v in cur.values()) and len(cur) == len(ids):
            return list(cur.values())
        if any(v["state"] in ("terminated", "shutting-down", "not-found") for v in cur.values()):
            raise AwsError(f"Instance not usable: {state}")
        time.sleep(6)
    raise AwsError(f"Servers not ready after {timeout}s ({last})")


def auto_off_minutes(now=None):
    """Minutes until the daily automatic shutdown, or None when not configured."""
    from . import scheduler
    hhmm = cfg().get("auto_off") or ""
    if not hhmm:
        return None
    now = now or scheduler.now()
    h, m = map(int, hhmm.split(":"))
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    diff = (target - now).total_seconds() / 60
    return diff if diff >= 0 else diff + 24 * 60


# --------------------------------------------------------------------------- remote commands (SSM)
def _wrap(script, as_user=True):
    """Ship the script base64-encoded and run it in a login shell of the scripts owner."""
    user = cfg().get("remote_user") if as_user else ""
    b64 = base64.b64encode(script.encode()).decode()
    tmp = f"/tmp/jmcc_{uuid.uuid4().hex[:12]}.sh"
    runner = f"sudo -u {shlex.quote(user)} -H bash -l {tmp}" if user else f"bash -l {tmp}"
    return (f"umask 022; echo {b64} | base64 -d > {tmp} && chmod 755 {tmp}; {runner}; rc=$?; "
            f"rm -f {tmp}; exit $rc")


def run(instance_id, script, timeout=120, as_user=True):
    """Run a bash script on an instance. Returns (exit_code, stdout, stderr)."""
    if not ID_RE.match(instance_id or ""):
        raise AwsError("Invalid instance id")
    payload = {"InstanceIds": [instance_id], "DocumentName": "AWS-RunShellScript",
               "TimeoutSeconds": max(30, min(int(timeout), 172800)),
               "Parameters": {"commands": [_wrap(script, as_user)], "executionTimeout": [str(int(timeout))]}}
    d = call(["ssm", "send-command", "--cli-input-json", json.dumps(payload)], timeout=40)
    cid = d["Command"]["CommandId"]
    deadline = time.time() + timeout + 30
    delay = 0.4
    while time.time() < deadline:
        time.sleep(delay)
        delay = min(delay * 1.4, 3)
        try:
            inv = call(["ssm", "get-command-invocation", "--command-id", cid, "--instance-id", instance_id],
                       timeout=40)
        except AwsError as exc:
            if "InvocationDoesNotExist" in str(exc):
                continue
            raise
        status = inv.get("Status")
        if status in ("Pending", "InProgress", "Delayed"):
            continue
        out, err = inv.get("StandardOutputContent", ""), inv.get("StandardErrorContent", "")
        if status in ("Success", "Failed"):
            return int(inv.get("ResponseCode", 1 if status == "Failed" else 0)), out, err
        raise AwsError(f"SSM command {status} on {instance_id}: {(err or out)[:300]}")
    raise AwsError(f"SSM command timed out on {instance_id}")


def run_many(ids, script, timeout=120):
    """Run the same script on several instances in parallel -> {id: (rc, out, err) | AwsError}."""
    results = {}

    def work(i):
        try:
            results[i] = run(i, script, timeout)
        except AwsError as exc:
            results[i] = exc

    threads = [threading.Thread(target=work, args=(i,), daemon=True) for i in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


# --------------------------------------------------------------------------- port forwarding / download
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_open(port, host="127.0.0.1"):
    try:
        with socket.create_connection((host, port), timeout=0.6):
            return True
    except OSError:
        return False


def port_forward(instance_id, remote_port, local_port, log_path=None):
    """Start an SSM port-forwarding session (subprocess). Caller owns/terminates the process."""
    params = json.dumps({"portNumber": [str(int(remote_port))], "localPortNumber": [str(int(local_port))]})
    cmd = _base_args() + ["ssm", "start-session", "--target", instance_id,
                          "--document-name", "AWS-StartPortForwardingSession", "--parameters", params]
    out = open(log_path, "ab") if log_path else subprocess.DEVNULL
    try:
        extra = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} \
            if os.name == "nt" else {"start_new_session": True}
        proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env=dict(os.environ, AWS_PAGER=""), **extra)
    except FileNotFoundError:
        raise AwsError("AWS CLI not found on this computer")
    deadline = time.time() + 25
    while time.time() < deadline:
        if proc.poll() is not None:
            detail = ""
            if log_path:
                try:
                    detail = open(log_path, errors="replace").read()[-300:]
                except OSError:
                    pass
            raise AwsError(f"SSM session ended (is the Session Manager plugin installed?) {detail}".strip())
        if port_open(local_port):
            return proc
        time.sleep(0.3)
    terminate(proc)
    raise AwsError(f"Port forward to {instance_id}:{remote_port} did not open")


def kill_tree(pid):
    """Stop a process and its children (aws -> session-manager-plugin)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        return
    try:
        os.killpg(pid, 15)
    except OSError:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def terminate(proc):
    if proc and proc.poll() is None:
        kill_tree(proc.pid)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def safe_name(name):
    """A single file/folder name that is safe once shell-quoted: no path separators, no '..',
    no leading '-' or '.', no control characters. Allows report names such as ACCTS&MVMTS."""
    return bool(name) and len(name) <= 255 and "/" not in name and "\\" not in name and ".." not in name \
        and name[0] not in "-." and all(ch.isprintable() and not ch.isspace() for ch in name)


def fetch_file(instance_id, remote_dir, filename, local_path, log=lambda m: None):
    """Download remote_dir/filename through an SSM tunnel (loopback-only one-shot HTTP server on the server)."""
    if not safe_name(filename):
        raise AwsError(f"Invalid file name: {filename!r}")
    rport = 20000 + int(uuid.uuid4().int % 9000)
    q = shlex.quote
    rc, out, err = run(instance_id, f"cd {q(remote_dir)} && "
                       f"(nohup python3 -m http.server {rport} --bind 127.0.0.1 >/dev/null 2>&1 & echo $!)", 60)
    pid = (out.strip().splitlines() or [""])[-1]
    if rc != 0 or not pid.isdigit():
        raise AwsError(f"Could not start the transfer on the server: {(err or out)[:200]}")
    proc = None
    try:
        lport = free_port()
        proc = port_forward(instance_id, rport, lport)
        log(f"downloading {filename} through SSM (localhost:{lport})")
        tmp = str(local_path) + ".part"
        with urllib.request.urlopen(f"http://127.0.0.1:{lport}/{urllib.parse.quote(filename)}", timeout=120) as resp, open(tmp, "wb") as fh:
            total = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
                total += len(chunk)
        os.replace(tmp, local_path)
        log(f"downloaded {total / 1024 / 1024:.1f} MB")
        return total
    except OSError as exc:
        raise AwsError(f"Download failed: {exc}")
    finally:
        terminate(proc)
        try:
            run(instance_id, f"kill {pid} 2>/dev/null; true", 30)
        except AwsError:
            pass


def remote_root():
    return cfg()["remote_root"].rstrip("/")
