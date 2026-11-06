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
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="true", LC_ALL="C")
    p = subprocess.run(["git", "-C", str(Config.REPO_ROOT), *args], capture_output=True, text=True,
                       timeout=timeout, env=env)
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
        if path.endswith(".DS_Store") or path.startswith("webapp/instance/"):
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
    email = author_email or f"{author_name}@users.noreply.local"
    _git("-c", f"user.name={author_name}", "-c", f"user.email={email}",
         "commit", "-m", message, "--", *paths)
    sha = _git("rev-parse", "--short", "HEAD").strip()
    try:
        _git("push", "origin", "HEAD", timeout=120)
    except (GitError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"Committed {sha} on the Master but the push failed (pull first?): {exc}")
    return sha
