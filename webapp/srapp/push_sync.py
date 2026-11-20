"""Push sync: copy this computer's clone of the scripts repository to the Master and Slaves.

Used when the servers cannot reach the repository host (sync_method = "push", the default). Every engineer pushes
their own working copy, the same way as a manual

    rsync -az -e "ssh -o ProxyCommand='aws ssm start-session --target %h --document-name AWS-StartSSHSession
                  --parameters portNumber=%p'" <local clone>/ <user>@<instance id>:<scripts folder>/

* SSH goes through SSM (document AWS-StartSSHSession): no inbound ports, no public IPs.
* The engineer's public key is added to ~/.ssh/authorized_keys of the scripts owner on each server through
  SSM Run Command first (idempotent), so Slaves work without any manual step.
* rsync is used when it exists on both sides (delta transfer); otherwise the files are streamed as tar.gz over
  the same SSH connection (Windows without rsync, servers without rsync).
* Results, local state and git metadata are never copied; files on the servers that are excluded here
  (results of other engineers, .jmcc locks) are never deleted, not even by a mirror sync.
"""
import base64
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import threading
import time
from pathlib import Path

from . import aws
from .config import Config

EXCLUDES = [".git/", ".jmcc/", ".venv/", "webapp/instance/", "__pycache__/", "*.pyc", ".DS_Store", "Thumbs.db",
            "/*/results/Ejecucion_*/", "/*/results/*.tar.gz", "/*/results/*.zip", "*.log.lck"]
_SKIP_DIRS = {".git", ".jmcc", ".venv", "__pycache__", "node_modules"}
_SKIP_FILES = re.compile(r"(\.pyc|\.DS_Store|Thumbs\.db|\.log\.lck)$")
_RESULT_RE = re.compile(r"^[^/]+/results/(Ejecucion_[^/]*(/|$)|[^/]+\.(tar\.gz|zip)$)")
NOWIN = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
_prepared = {}          # instance id -> (time, uses_rsync) : key installed recently
_plock = threading.Lock()


class SyncError(RuntimeError):
    pass


# --------------------------------------------------------------------------- local tools
def method():
    return (aws.cfg().get("sync_method") or "push").lower()


def local_root():
    return Path(Config.REPO_ROOT)


def key_path():
    """Private key used for SSH: Settings → AWS, else the usual defaults in ~/.ssh."""
    k = (aws.cfg().get("ssh_key") or "").strip()
    if k:
        return Path(os.path.expanduser(k))
    for name in ("id_ed25519", "id_ecdsa", "id_rsa"):
        p = Path.home() / ".ssh" / name
        if p.is_file():
            return p
    return None


def make_key(path=None):
    """Create an ed25519 key pair in OpenSSH format (no passphrase) for the copy to the servers.
    Uses the cryptography package (already required by the app), so it works the same on Windows and macOS."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    p = Path(os.path.expanduser(path)) if path else Path.home() / ".ssh" / "id_ed25519"
    if p.exists() or Path(str(p) + ".pub").exists():
        raise SyncError(f"{p} already exists; not overwritten")
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    key = ed25519.Ed25519PrivateKey.generate()
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                             serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "engineer"
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(priv)
    Path(str(p) + ".pub").write_text(pub.decode() + f" {user}@jmeter-control-center\n")
    return p


_PUB_RE = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)|sk-ssh-ed25519@openssh\.com|"
                     r"sk-ecdsa-sha2-nistp256@openssh\.com)\s+([A-Za-z0-9+/]+={0,3})(?:\s+(.*))?$")


def _decode(raw):
    """Text of a key file as Windows tools write it: UTF-8 (with or without BOM) or UTF-16 (PowerShell 5.1 '>' and
    Out-File write UTF-16 LE with BOM)."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if b"\x00" in raw[:200]:
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def parse_public_key(text):
    """One authorized_keys line from the text of a .pub file, or None. Tolerates BOMs, CRLF, blank lines and
    Windows comments (DOMAIN\\user@HOST): a comment that is unsafe in a shell is rewritten; a safe one is kept as is
    so a key already authorized on the servers still matches its line."""
    for line in (text or "").replace("\ufeff", "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _PUB_RE.match(line)
        if not m:
            continue
        ktype, b64, comment = m.group(1), m.group(2), (m.group(3) or "").strip()
        try:
            blob = base64.b64decode(b64, validate=True)
            n = int.from_bytes(blob[:4], "big")
            if blob[4:4 + n].decode("ascii") != ktype:
                continue
        except (ValueError, UnicodeDecodeError):
            continue
        if comment and not re.match(r"^[^\n'\"\\\\]*$", comment):
            comment = re.sub(r"[^\w@.\-]+", "_", comment).strip("_")
        return f"{ktype} {b64}" + (f" {comment}" if comment else "")
    return None


def public_key():
    k = key_path()
    if not k or not k.is_file():
        raise SyncError("No SSH key found. Create one with: ssh-keygen -t ed25519   (or set its path in Settings → AWS)")
    pub = Path(str(k) + ".pub")
    key = None
    if pub.is_file():
        try:
            key = parse_public_key(_decode(pub.read_bytes()))
        except OSError:
            key = None
    if not key:
        # no usable .pub: derive the public key from the private key
        try:
            out = subprocess.run([tool("ssh-keygen"), "-y", "-f", str(k)], capture_output=True, text=True,
                                 timeout=20, stdin=subprocess.DEVNULL, **NOWIN)
            key = parse_public_key(out.stdout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SyncError(f"Cannot read the public key of {k}: {exc}")
        if not key:
            detail = (out.stderr or "").strip()[-200:]
            raise SyncError(f"{pub} is not a valid OpenSSH public key and it could not be derived from {k}"
                            + (f" ({detail})" if detail else "") + ". Regenerate it with: ssh-keygen -y -f "
                            f"\"{k}\" | Out-File -Encoding ascii \"{pub}\"   (PowerShell) or ssh-keygen -t ed25519")
    return key


def tool(name):
    found = shutil.which(name)
    if not found and os.name == "nt" and name in ("ssh", "ssh-keygen"):
        cand = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "OpenSSH" / f"{name}.exe"
        found = str(cand) if cand.is_file() else None
    if not found:
        hint = {"ssh": "install the OpenSSH client (Windows: Settings → Optional features → OpenSSH Client)",
                "session-manager-plugin": "install the AWS Session Manager plugin"}.get(name, "")
        raise SyncError(f"'{name}' not found on this computer" + (f": {hint}" if hint else ""))
    return found


def has_rsync():
    return shutil.which("rsync") is not None


def _q(s):
    """Quote a value for ssh_config (double quotes; paths may contain spaces on Windows)."""
    s = str(s)
    return '"' + s.replace('"', '') + '"' if re.search(r'[\s#"]', s) or os.name == "nt" else s


def ssh_config():
    """Write instance/ssh/config: every i-xxxx host goes through SSM with the engineer's key."""
    c = aws.cfg()
    k = key_path()
    if not k or not k.is_file():
        public_key()   # raises the helpful error
    tool("session-manager-plugin")
    d = Path(Config.INSTANCE_DIR) / "ssh"
    d.mkdir(parents=True, exist_ok=True)
    awsbin = shutil.which(aws.AWS_BIN) or aws.AWS_BIN
    proxy = [_q(awsbin)]
    if c.get("profile"):
        proxy += ["--profile", c["profile"]]
    if c.get("region"):
        proxy += ["--region", c["region"]]
    proxy += ["ssm", "start-session", "--target", "%h", "--document-name", "AWS-StartSSHSession",
              "--parameters", "portNumber=%p"]
    text = (f"# generated by JMeter Control Center ({time.strftime('%Y-%m-%d %H:%M:%S')}); do not edit\n"
            f"Host i-* mi-*\n"
            f"  User {c.get('remote_user') or 'ubuntu'}\n"
            f"  IdentityFile {_q(k)}\n"
            f"  IdentitiesOnly yes\n"
            f"  BatchMode yes\n"
            f"  StrictHostKeyChecking accept-new\n"
            f"  UserKnownHostsFile {_q(d / 'known_hosts')}\n"
            f"  ConnectTimeout 60\n"
            f"  ServerAliveInterval 20\n"
            f"  ServerAliveCountMax 6\n"
            f"  ProxyCommand {' '.join(proxy)}\n")
    p = d / "config"
    if not p.is_file() or p.read_text().split("\n", 1)[1:] != text.split("\n", 1)[1:]:
        p.write_text(text)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    return p


def _ssh_base():
    return [tool("ssh"), "-F", str(ssh_config())]


def explain(output):
    low = (output or "").lower()
    if "permission denied (publickey" in low:
        return ("the server rejected your SSH key (is it protected by a passphrase without ssh-agent, or was "
                "authorized_keys changed?)")
    if "accessdenied" in low or "not authorized to perform: ssm:startsession" in low:
        return ("your AWS role cannot open SSH sessions: it needs ssm:StartSession on the document "
                "AWS-StartSSHSession for these instances")
    if "targetnotconnected" in low:
        return "the instance is not connected to SSM (stopped or SSM agent offline)"
    if "connection closed" in low or "kex_exchange_identification" in low or "connection refused" in low:
        return "SSH did not answer on the server (is sshd running on port 22?)"
    if "host key verification failed" in low or "remote host identification has changed" in low:
        return (f"the server's SSH host key changed (instance replaced?): delete its line from "
                f"{Path(Config.INSTANCE_DIR) / 'ssh' / 'known_hosts'}")
    if "rsync: command not found" in low or "rsync: not found" in low:
        return "rsync is not installed on the server"
    if "token" in low and "expired" in low or "sso" in low and "expired" in low:
        return "your AWS session expired: use AWS SSO login on the Servers page"
    return ""


# --------------------------------------------------------------------------- server preparation (SSM Run Command)
def prepare(ids, log=lambda m: None, force=False):
    """Authorize the engineer's key on each server and check the scripts folder. Returns {id: remote_has_rsync}."""
    pub = public_key()
    root = aws.remote_root()
    need = [i for i in ids if force or i not in _prepared or time.time() - _prepared[i][0] > 3600]
    if need:
        script = f"""
K={shlex.quote(pub)}
umask 077; mkdir -p "$HOME/.ssh" && touch "$HOME/.ssh/authorized_keys" || {{ echo "@@NOHOME@@"; exit 3; }}
grep -qxF "$K" "$HOME/.ssh/authorized_keys" && echo "@@KEY@@ present" || {{ echo "$K" >> "$HOME/.ssh/authorized_keys" && echo "@@KEY@@ added"; }}
chmod 700 "$HOME/.ssh"; chmod 600 "$HOME/.ssh/authorized_keys"
umask 022; mkdir -p {shlex.quote(root)} 2>/dev/null; mkdir -p {shlex.quote(root + "/webapp/bin")} 2>/dev/null
[ -w {shlex.quote(root)} ] && echo "@@ROOT@@ ok" || echo "@@ROOT@@ not-writable"
command -v rsync >/dev/null 2>&1 && echo "@@RSYNC@@ yes" || echo "@@RSYNC@@ no"
command -v tar >/dev/null 2>&1 && echo "@@TAR@@ yes" || echo "@@TAR@@ no"
"""
        results = aws.run_many(need, script, timeout=60)
        for iid in need:
            r = results[iid]
            if isinstance(r, Exception):
                raise SyncError(f"{iid}: cannot prepare the server through SSM: {r}")
            rc, out, err = r
            if "@@ROOT@@ not-writable" in out:
                raise SyncError(f"{iid}: {root} does not exist or is not writable by "
                                f"{aws.cfg().get('remote_user') or 'the scripts owner'}")
            if rc != 0 or "@@KEY@@" not in out:
                raise SyncError(f"{iid}: preparation failed (exit {rc}): {(out + err).strip()[-200:]}")
            if "@@KEY@@ added" in out:
                log(f"  {iid}: your SSH public key was added to authorized_keys")
            rs = "@@RSYNC@@ yes" in out
            if not rs and "@@TAR@@ yes" not in out:
                raise SyncError(f"{iid}: neither rsync nor tar is installed on the server")
            with _plock:
                _prepared[iid] = (time.time(), rs)
    return {i: _prepared[i][1] for i in ids}


# --------------------------------------------------------------------------- transfer
def _rsync_one(iid, src_rel, excludes, mirror, timeout):
    root = aws.remote_root().rstrip("/") + "/"
    ssh_cmd = " ".join('"' + a + '"' if " " in a else a for a in _ssh_base())
    cmd = ["rsync", "-rlptz", "-e", ssh_cmd]
    if mirror:
        cmd.append("--delete")
    for e in excludes:
        cmd += ["--exclude", e]
    src = local_root() / src_rel if src_rel else local_root()
    cmd += ["-v", str(src).rstrip("/\\") + "/", f"{iid}:{root}{src_rel + '/' if src_rel else ''}"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, **NOWIN)
    out = (p.stdout or "") + (p.stderr or "")
    files = [ln for ln in (p.stdout or "").splitlines()
             if ln and not ln.endswith("/") and not re.match(r"^(sent |total size|sending |building |receiving |"
                                                              r"Transfer starting|deleting |created directory)", ln)]
    return p.returncode, out, len(files)


def _rsync(iid, mirror, log, timeout, only=None, skip=()):
    if only:
        jobs = []
        for rel in only:
            ex = list(EXCLUDES[:6]) + ["/results/Ejecucion_*/", "/results/*.tar.gz", "/results/*.zip", "*.log.lck"] \
                if "/" not in rel and rel != "webapp" else list(EXCLUDES)
            jobs.append((rel, ex))
    else:
        jobs = [("", list(EXCLUDES) + [f"/{p}/" for p in skip])]
    total, outs = 0, []
    for rel, ex in jobs:
        rc, out, n = _rsync_one(iid, rel, ex, mirror, timeout)
        outs.append(out)
        total += n
        if rc != 0:
            return rc, "\n".join(outs), total
    return 0, "\n".join(outs), total


def _iter_files(only=None, skip=()):
    base = local_root()
    starts = [base / rel for rel in only] if only else [base]
    for start in starts:
        if not start.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(start):
            rel_dir = Path(dirpath).relative_to(base).as_posix()
            rel_dir = "" if rel_dir == "." else rel_dir + "/"
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and (rel_dir + d) != "webapp/instance"
                           and not _RESULT_RE.match(rel_dir + d) and (rel_dir or d not in skip)]
            for f in filenames:
                rel = rel_dir + f
                if _SKIP_FILES.search(f) or _RESULT_RE.match(rel):
                    continue
                yield Path(dirpath) / f, rel


def _tar(iid, mirror, log, timeout, only=None, skip=()):
    root = aws.remote_root()
    remote = (f"set -e; cd {shlex.quote(root)}; tar -xzmf - --no-same-owner 2>&1; find . -path ./.git -prune -o -name '*.sh' -type f "
              f"-exec chmod 755 {{}} + ; chmod 755 webapp/bin/jmeter 2>/dev/null; echo @@TAR_OK@@")
    proc = subprocess.Popen(_ssh_base() + [iid, remote], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, **NOWIN)
    count = 0
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    try:
        with tarfile.open(fileobj=proc.stdin, mode="w|gz", format=tarfile.GNU_FORMAT) as tf:
            for path, rel in _iter_files(only, skip):
                try:
                    info = tf.gettarinfo(str(path), arcname=rel)
                except OSError:
                    continue
                if not info.isfile():
                    continue
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o755 if rel.endswith(".sh") or rel == "webapp/bin/jmeter" else 0o644
                with open(path, "rb") as fh:
                    tf.addfile(info, fh)
                count += 1
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    out = proc.stdout.read().decode(errors="replace")
    rc = proc.wait()
    timer.cancel()
    if rc == 0 and "@@TAR_OK@@" not in out:
        rc = 1
    if mirror and rc == 0:
        log(f"  {iid}: mirror (delete extra files) needs rsync; files were updated but nothing was deleted")
    return rc, out, count


def push(ids, log=lambda m: None, mirror=False, timeout=1200, only=None, skip=()):
    """Copy the local clone to every server in parallel. Raises SyncError listing the failed servers.

    only: top-level folders to copy (a run copies its project + webapp/bin and nothing else, so tests of other
          projects running on the same Master are never touched).
    skip: top-level folders left alone in a full sync (projects with a test running right now)."""
    if not ids:
        return
    remote_rsync = prepare(ids, log)
    results = {}

    def one(iid):
        use_rsync = has_rsync() and remote_rsync.get(iid)
        t0 = time.time()
        try:
            rc, out, n = (_rsync if use_rsync else _tar)(iid, mirror, log, timeout, only, skip)
        except subprocess.TimeoutExpired:
            rc, out, n = 124, "timed out", 0
        except SyncError as exc:
            rc, out, n = 1, str(exc), 0
        except OSError as exc:
            rc, out, n = 1, f"{type(exc).__name__}: {exc}", 0
        results[iid] = (rc, out, n, "rsync" if use_rsync else "tar", time.time() - t0)

    threads = [threading.Thread(target=one, args=(i,), daemon=True) for i in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    bad = []
    for iid in ids:
        rc, out, n, how, secs = results[iid]
        if rc == 0:
            what = f"{n} file(s) updated" if how == "rsync" else f"{n} file(s) copied"
            log(f"  {iid}: OK · {how} · {what} · {secs:.0f}s")
        else:
            reason = explain(out)
            tail = " ".join(out.strip().splitlines()[-3:])[-300:]
            log(f"  {iid}: FAILED ({how}, exit {rc}) {tail}" + (f" — {reason}" if reason else ""))
            bad.append(iid)
            with _plock:
                _prepared.pop(iid, None)
    if bad:
        raise SyncError(f"push sync failed on {len(bad)} server(s): {', '.join(bad)} (reason above)")


def test(iid):
    """Quick SSH round trip through SSM. Returns (ok, message)."""
    try:
        prepare([iid], force=True)
        p = subprocess.run(_ssh_base() + [iid, "echo @@SSH_OK@@ $(whoami)@$(hostname) rsync=$(command -v rsync || echo no)"],
                           capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, **NOWIN)
    except (SyncError, aws.AwsError) as exc:
        return False, str(exc)
    except subprocess.TimeoutExpired:
        return False, "SSH through SSM timed out"
    out = (p.stdout or "") + (p.stderr or "")
    m = re.search(r"@@SSH_OK@@ (.+)", out)
    if p.returncode == 0 and m:
        return True, m.group(1).strip() + (" · local rsync" if has_rsync() else " · no local rsync (tar fallback)")
    return False, (explain(out) or out.strip()[-300:])


def local_state():
    """(branch, sha, n_changed) of this computer's clone, tolerant of a folder that is not a git clone."""
    from . import gitops
    try:
        br, sha = gitops.branch(), gitops.head_sha()
        n = len([ln for ln in gitops._git("status", "--porcelain=v1").splitlines()
                 if not gitops.IGNORED.search(ln[3:])])
        return br, sha, n
    except Exception:  # noqa: BLE001
        return "local", "0" * 40, 0


if __name__ == "__main__":
    import sys
    if "--make-key" in sys.argv:
        try:
            print(f"SSH key created: {make_key()}")
        except SyncError as exc:
            print(exc)
            sys.exit(1)
