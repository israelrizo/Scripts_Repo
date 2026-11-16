"""Keep the engineer's computer able to fire scheduled runs.

* keep-awake   while a test is running or a scheduled run is due within N hours, the computer must not
               idle-sleep:  macOS `caffeinate -i -w <pid>` · Windows SetThreadExecutionState · Linux systemd-inhibit
* wake timers  wake the computer from sleep a few minutes before each scheduled slot:
               Windows: a per-user Task Scheduler task with WakeToRun (no admin rights needed)
               macOS:   `pmset schedule wake` (needs the optional sudoers rule added by the service installer)
A lid-closed laptop on battery may still sleep or refuse wake timers (OS power policy).
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import timedelta

from .config import Config

WAKE_TASK = r"\JMeterControlCenter\WakeForScheduledRuns"
WAKE_LEAD_MIN = 5
_state = {"held": False, "reason": "", "method": "", "error": "", "wake": {"slots": [], "ok": None, "detail": ""}}
_lock = threading.Lock()
_holder = {"proc": None, "thread": None, "stop": None}


def os_name():
    return {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}.get(platform.system(), platform.system())


def service_mode():
    return os.environ.get("SR_SERVICE", "")


# --------------------------------------------------------------------------- keep-awake
def _win_hold(stop):
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_AWAYMODE_REQUIRED = 0x80000000, 0x00000001, 0x00000040
    k32 = ctypes.windll.kernel32
    if not k32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED):
        k32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    stop.wait()
    k32.SetThreadExecutionState(ES_CONTINUOUS)


def hold(reason):
    with _lock:
        _state["reason"] = reason
        if _state["held"]:
            return
        try:
            system = platform.system()
            if system == "Darwin" and shutil.which("caffeinate"):
                _holder["proc"] = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())],
                                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                _state["method"] = "caffeinate"
            elif system == "Windows":
                stop = threading.Event()
                t = threading.Thread(target=_win_hold, args=(stop,), daemon=True, name="keep-awake")
                t.start()
                _holder.update(thread=t, stop=stop)
                _state["method"] = "SetThreadExecutionState"
            elif shutil.which("systemd-inhibit"):
                _holder["proc"] = subprocess.Popen(
                    ["systemd-inhibit", "--what=idle:sleep", "--who=JMeter Control Center",
                     "--why=Scheduled performance test", "--mode=block", "sleep", "infinity"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                _state["method"] = "systemd-inhibit"
            else:
                _state["method"] = "unsupported"
                return
            _state.update(held=True, error="")
        except Exception as exc:  # noqa: BLE001
            _state["error"] = str(exc)


def release():
    with _lock:
        if not _state["held"]:
            return
        proc = _holder.get("proc")
        if proc and proc.poll() is None:
            proc.terminate()
        if _holder.get("stop"):
            _holder["stop"].set()
        _holder.update(proc=None, thread=None, stop=None)
        _state.update(held=False, reason="")


# --------------------------------------------------------------------------- wake timers
def _wake_file():
    return Config.INSTANCE_DIR / "wake_timers.json"


def _task_xml(slots):
    triggers = "".join(f"<TimeTrigger><StartBoundary>{s.strftime('%Y-%m-%dT%H:%M:%S')}</StartBoundary>"
                       f"<Enabled>true</Enabled></TimeTrigger>" for s in slots)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Wakes the computer before scheduled JMeter Control Center runs.</Description></RegistrationInfo>
  <Triggers>{triggers}</Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <WakeToRun>true</WakeToRun><StartWhenAvailable>true</StartWhenAvailable>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit><Enabled>true</Enabled><Hidden>true</Hidden>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
  </Settings>
  <Actions Context="Author"><Exec><Command>cmd.exe</Command><Arguments>/c exit 0</Arguments></Exec></Actions>
</Task>"""


def set_wake_timers(slots):
    """slots: aware datetimes (local timezone of the schedules). Idempotent; returns (ok, detail)."""
    wakes = sorted({(s - timedelta(minutes=WAKE_LEAD_MIN)).astimezone().replace(tzinfo=None, microsecond=0)
                    for s in slots})[:8]
    key = [w.isoformat() for w in wakes]
    try:
        prev = json.loads(_wake_file().read_text())
    except (OSError, ValueError):
        prev = {}
    if prev.get("slots") == key and prev.get("ok"):
        _state["wake"] = prev
        return prev["ok"], prev.get("detail", "")
    system = platform.system()
    ok, detail = False, ""
    try:
        if system == "Windows":
            if not wakes:
                subprocess.run(["schtasks", "/Delete", "/TN", WAKE_TASK, "/F"], capture_output=True)
                ok, detail = True, "no upcoming slots"
            else:
                fd, path = tempfile.mkstemp(suffix=".xml")
                os.close(fd)
                with open(path, "w", encoding="utf-16") as fh:
                    fh.write(_task_xml(wakes))
                p = subprocess.run(["schtasks", "/Create", "/TN", WAKE_TASK, "/XML", path, "/F"],
                                   capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                os.remove(path)
                ok = p.returncode == 0
                detail = "Task Scheduler wake timers set" if ok else (p.stderr or p.stdout).strip()[:200]
        elif system == "Darwin":
            done = set(prev.get("slots") or []) if prev.get("ok") else set()
            errors = []
            for w in wakes:
                if w.isoformat() in done or w <= w.now():
                    continue
                p = subprocess.run(["sudo", "-n", "/usr/bin/pmset", "schedule", "wake", w.strftime("%m/%d/%Y %H:%M:%S")],
                                   capture_output=True, text=True)
                if p.returncode != 0:
                    errors.append((p.stderr or p.stdout).strip()[:120])
            ok = not errors
            detail = "pmset wake events scheduled" if ok else (
                "pmset needs the optional sudoers rule (re-run the service installer and answer yes): " + errors[0])
        else:
            ok, detail = False, "wake timers not supported on this OS (keep the machine awake)"
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, str(exc)
    info = {"slots": key, "ok": ok, "detail": detail, "updated": time.time()}
    try:
        _wake_file().write_text(json.dumps(info))
    except OSError:
        pass
    _state["wake"] = info
    return ok, detail


def status():
    return {"os": os_name(), "service": service_mode(), "python": sys.version.split()[0], **{
        k: v for k, v in _state.items()}}
