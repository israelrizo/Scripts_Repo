"""Git sync of the scripts repository (Bitbucket remote) from the UI: status, pull, commit & push.

Uses the git credentials already configured on the Master for `origin` (SSH key or credential
helper). Commits are authored by the web user (name + profile e-mail) so history shows who changed what.
"""
import os
import re
import subprocess

from .config import Config

SAFE_PATH = re.compile(r"^[A-Za-z0-9_.\-/ ]+$")


class GitError(RuntimeError):
    pass


def _git(*args, timeout=60, check=True):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", LC_ALL="C")
    if os.name != "nt":
        env["GIT_ASKPASS"] = "true"
    p = subprocess.run(["git", "-C", str(Config.REPO_ROOT), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, env=env,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if check and p.returncode != 0:
        raise GitError((p.stderr or p.stdout).strip()[:800] or f"git {args[0]} failed")
    return p.stdout


def available():
    try:
        _git("rev-parse", "--is-inside-work-tree", timeout=10)
        return True
    except (GitError, OSError, subprocess.TimeoutExpired):
        return False


def status(fetch=False):
    if fetch:
        try:
            _git("fetch", "--quiet", "origin", timeout=60)
        except (GitError, subprocess.TimeoutExpired) as exc:
            fetch_error = str(exc)
        else:
            fetch_error = None
    else:
        fetch_error = None
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
    ahead = behind = None
    try:
        out = _git("rev-list", "--left-right", "--count", "@{u}...HEAD").split()
        behind, ahead = int(out[0]), int(out[1])
    except GitError:
        pass
    files = []
    for line in _git("status", "--porcelain=v1", "-uall").splitlines():
        code, path = line[:2], line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        if IGNORED.search(path):
            continue
        files.append({"code": code.strip() or "?", "path": path,
                      "kind": {"M": "modified", "A": "added", "D": "deleted", "R": "renamed",
                               "??": "new"}.get(code.strip(), code.strip())})
    last = _git("log", "-1", "--format=%h · %an · %ar · %s").strip()
    remote = _git("remote", "get-url", "origin", check=False).strip()
    remote = re.sub(r"//[^@/]+@", "//", remote)  # never show embedded credentials
    return {"branch": branch, "ahead": ahead, "behind": behind, "files": files, "last": last,
            "remote": remote, "fetch_error": fetch_error}


def pull():
    return _git("pull", "--ff-only", "origin", timeout=120).strip() or "Already up to date."


def commit_and_push(paths, message, author_name, author_email):
    message = (message or "").strip()
    if len(message) < 5:
        raise GitError("Write a commit message (min. 5 characters)")
    paths = [p for p in paths if p]
    if not paths:
        raise GitError("Select at least one file")
    for p in paths:
        if not SAFE_PATH.match(p) or p.startswith("/") or ".." in p.split("/") or p.startswith("webapp/instance"):
            raise GitError(f"Refusing path {p}")
    _git("add", "-A", "--", *paths)
    # keep shell scripts executable for the Linux servers, also when committed from Windows
    for p in paths:
        if p.endswith(".sh") and (Config.REPO_ROOT / p).is_file():
            _git("update-index", "--chmod=+x", "--", p, check=False)
    email = author_email or f"{author_name}@users.noreply.local"
    _git("-c", f"user.name={author_name}", "-c", f"user.email={email}",
         "commit", "-m", message, "--", *paths)
    sha = _git("rev-parse", "--short", "HEAD").strip()
    try:
        _git("push", "origin", "HEAD", timeout=120)
    except (GitError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"Committed {sha} locally but the push failed (pull first?): {exc}")
    return sha


# --------------------------------------------------------------------------- centralized sync (AWS mode)
IGNORED = re.compile(r"(^|/)results/|^\.jmcc/|\.DS_Store$|^webapp/instance/")


def branch():
    return _git("rev-parse", "--abbrev-ref", "HEAD").strip()


def head_sha(ref="HEAD"):
    return _git("rev-parse", ref).strip()


def require_pushed(project=None):
    """The repository (origin) is the single source of truth for Master and Slaves.
    Returns (branch, sha) when this computer's clone is clean and identical to origin; raises GitError otherwise."""
    br = branch()
    if br == "HEAD":
        raise GitError("The local repository is in detached HEAD; check out a branch first")
    try:
        _git("fetch", "--quiet", "origin", br, timeout=60)
    except (GitError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"Cannot reach the repository (origin): {exc}")
    dirty = []
    for line in _git("status", "--porcelain=v1", "-uall").splitlines():
        path = line[3:].split(" -> ")[-1].strip('"')
        if IGNORED.search(path):
            continue
        if project is None or path.startswith(project + "/") or path.startswith("webapp/bin/"):
            dirty.append(path)
    if dirty:
        shown = ", ".join(dirty[:4]) + (f" (+{len(dirty) - 4} more)" if len(dirty) > 4 else "")
        raise GitError(f"Uncommitted changes: {shown}. Commit & push them on the Git page so the servers get them.")
    try:
        behind, ahead = map(int, _git("rev-list", "--left-right", "--count", f"origin/{br}...HEAD").split())
    except GitError:
        raise GitError(f"Branch {br} does not exist on origin yet; push it first (Git page)")
    if ahead:
        raise GitError(f"{ahead} local commit(s) not pushed. Push them on the Git page so the servers get them.")
    if behind:
        raise GitError(f"This computer is {behind} commit(s) behind origin/{br}. Pull on the Git page first.")
    return br, head_sha()


def server_sync_script(remote_root, br, force=False):
    """Script run on Master/Slaves: bring the server clone to origin/<branch> and print the commit."""
    import shlex
    q = shlex.quote
    if force:
        update = f"git checkout -q -f {q(br)} 2>&1 && git reset -q --hard origin/{q(br)} 2>&1"
    else:
        update = (f"(git checkout -q {q(br)} 2>&1 || git checkout -q -b {q(br)} --track origin/{q(br)} 2>&1) && "
                  f"git merge -q --ff-only origin/{q(br)} 2>&1")
    return (f"cd {q(remote_root)} || exit 3\n"
            f"export GIT_TERMINAL_PROMPT=0\n"
            f"git fetch -q origin {q(br)} 2>&1 || exit 4\n"
            f"{update} || exit 5\n"
            f"echo \"@@SHA@@ $(git rev-parse HEAD)\"\n")
