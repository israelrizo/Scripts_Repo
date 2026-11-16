"""SSM port-forward tunnels to the Master managed from the web page (Grafana 3000, InfluxDB 8086, custom)."""
import atexit
import re
import threading
import time

from . import aws, settings
from .config import Config

_lock = threading.Lock()
_open = {}  # name -> {"proc", "local", "remote", "since"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,23}$")


class TunnelError(RuntimeError):
    pass


def definitions():
    return settings.get()["tunnels"]["items"]


def _def(name):
    for d in definitions():
        if d["name"] == name:
            return d
    raise TunnelError(f"Unknown tunnel '{name}'")


def _reap():
    for name in [n for n, t in _open.items() if t["proc"].poll() is not None]:
        _open.pop(name, None)


def status():
    with _lock:
        _reap()
        out = []
        for d in definitions():
            t = _open.get(d["name"])
            listening = aws.port_open(d["local_port"])
            out.append({**d, "open": bool(t), "since": t["since"] if t else None,
                        # port answering without our tunnel = something else (or another app) owns it
                        "external": listening and not t, "url": f"http://localhost:{d['local_port']}"})
        return out


def is_open(name):
    with _lock:
        _reap()
        return name in _open


def open_tunnel(name):
    d = _def(name)
    with _lock:
        _reap()
        if name in _open:
            return d
        if aws.port_open(d["local_port"]):
            raise TunnelError(f"Local port {d['local_port']} is already in use on this computer")
        master = aws.cfg().get("master")
        if not master:
            raise TunnelError("Master instance not configured (Settings → AWS)")
        inst = next((i for i in aws.instances() if i["id"] == master), None)
        if not inst or inst["state"] != "running":
            raise TunnelError("The Master is stopped — start the servers first")
        if not inst["ssm"]:
            raise TunnelError("The Master is starting (SSM agent not online yet)")
        log_dir = Config.INSTANCE_DIR / "tunnels"
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            proc = aws.port_forward(master, d["remote_port"], d["local_port"], str(log_dir / f"{name}.log"))
        except aws.AwsError as exc:
            raise TunnelError(str(exc))
        _open[name] = {"proc": proc, "local": d["local_port"], "remote": d["remote_port"], "since": time.time()}
        return d


def close_tunnel(name):
    with _lock:
        t = _open.pop(name, None)
    if t:
        aws.terminate(t["proc"])


def close_all():
    with _lock:
        items = list(_open.values())
        _open.clear()
    for t in items:
        aws.terminate(t["proc"])


def ensure(name):
    """Open the tunnel if needed; returns its local base URL."""
    d = _def(name)
    if not is_open(name):
        # a tunnel opened outside the app (terminal, another tool) is fine too
        if aws.port_open(d["local_port"]):
            return f"http://127.0.0.1:{d['local_port']}"
        open_tunnel(name)
    return f"http://127.0.0.1:{d['local_port']}"


def save_definition(name, label, remote_port, local_port):
    if not NAME_RE.match(name or ""):
        raise TunnelError("Name: lowercase letters, digits, '-' or '_'")
    remote_port, local_port = int(remote_port), int(local_port)
    if not (1 <= remote_port <= 65535 and 1024 <= local_port <= 65535):
        raise TunnelError("Ports: remote 1-65535, local 1024-65535")
    if local_port == Config.PORT:
        raise TunnelError("That local port is used by the Control Center itself")
    cfg = settings.get()
    items = [i for i in cfg["tunnels"]["items"] if i["name"] != name]
    if any(i["local_port"] == local_port for i in items):
        raise TunnelError("Another tunnel already uses that local port")
    items.append({"name": name, "label": (label or name)[:30], "remote_port": remote_port, "local_port": local_port})
    cfg["tunnels"]["items"] = items
    settings.save(cfg)


def delete_definition(name):
    if name in ("grafana", "influx"):
        raise TunnelError("Built-in tunnels cannot be removed")
    close_tunnel(name)
    cfg = settings.get()
    cfg["tunnels"]["items"] = [i for i in cfg["tunnels"]["items"] if i["name"] != name]
    settings.save(cfg)


atexit.register(close_all)
