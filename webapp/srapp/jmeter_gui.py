"""Open a project's .jmx in the JMeter GUI installed on the engineer's computer (per-user JMeter path)."""
import glob
import os
import shutil
import subprocess
from pathlib import Path

from . import projects, users
from .config import Config


class GuiError(RuntimeError):
    pass


def _exe_in(home):
    b = Path(home) / "bin"
    for name in (("jmeter.bat", "jmeter.cmd") if os.name == "nt" else ("jmeter", "jmeter.sh")):
        if (b / name).is_file():
            return str(b / name)
    return None


def resolve(path):
    """Accept a JMeter home folder or the jmeter executable; return the executable or raise."""
    path = (path or "").strip().strip('"')
    if not path:
        raise GuiError("Set your JMeter path first (Account → JMeter)")
    p = Path(os.path.expanduser(path))
    if p.is_dir():
        exe = _exe_in(p) or (_exe_in(p.parent) if p.name == "bin" else None)
        if not exe:
            raise GuiError(f"No bin/jmeter{'.bat' if os.name == 'nt' else ''} under {p}")
        return exe
    if p.is_file():
        if os.name != "nt" and not os.access(p, os.X_OK):
            raise GuiError(f"{p} is not executable")
        return str(p)
    raise GuiError(f"{p} does not exist on this computer")


def detect():
    """Best-effort guesses for the JMeter installation on this computer."""
    found = []
    w = shutil.which("jmeter.bat" if os.name == "nt" else "jmeter")
    if w:
        found.append(os.path.realpath(w))
    pats = ([r"C:\apache-jmeter*", r"C:\Program Files\apache-jmeter*", r"C:\tools\apache-jmeter*",
             os.path.expanduser(r"~\apache-jmeter*"), os.path.expanduser(r"~\Downloads\apache-jmeter*")]
            if os.name == "nt" else
            ["/opt/apache-jmeter*", "/opt/homebrew/Cellar/jmeter/*/libexec", "/usr/local/Cellar/jmeter/*/libexec",
             os.path.expanduser("~/apache-jmeter*"), os.path.expanduser("~/Applications/apache-jmeter*"),
             os.path.expanduser("~/Downloads/apache-jmeter*")])
    for pat in pats:
        for home in sorted(glob.glob(pat), reverse=True):
            exe = _exe_in(home)
            if exe and exe not in found:
                found.append(exe)
    return found


def open_script(username, project, script, extra_args=""):
    u = users.get(username) or {}
    exe = resolve(u.get("jmeter_path", ""))
    base = projects.project_dir(project)
    jmx = projects.safe_path(project, script)
    if jmx.suffix != ".jmx" or not jmx.is_file():
        raise GuiError("Script not found")
    args = [exe, "-t", str(jmx), f"-Jdata_dir={(base / 'data').as_posix()}"]
    args += [a for a in projects.validate_prop_args(extra_args)]
    log_dir = Config.INSTANCE_DIR / "gui"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = open(log_dir / "jmeter-gui.log", "ab")
    try:
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
            subprocess.Popen(args, cwd=str(base), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             creationflags=flags)
        else:
            subprocess.Popen(args, cwd=str(base), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True)
    except OSError as exc:
        raise GuiError(f"Could not start JMeter: {exc}")
    return exe
