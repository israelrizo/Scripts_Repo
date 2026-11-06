"""Find the servers a JMX hits and check they are reachable from the Master.

Resolves ${var} (User Defined Variables) and ${__P(name,default)} / ${__property(name,,default)}
with the tag's EXTRA_ARGS and the overrides typed in the UI, then checks DNS → TCP → TLS → HTTP.
"""
import http.client
import re
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

from defusedxml import ElementTree as ET

from . import projects

FN_P = re.compile(r"\$\{__P\(\s*([^,)]+?)\s*(?:,\s*([^)]*?))?\s*\)\}")
FN_PROPERTY = re.compile(r"\$\{__property\(\s*([^,)]+?)\s*(?:,[^,)]*)?(?:,\s*([^)]*?))?\s*\)\}")
VAR = re.compile(r"\$\{([A-Za-z0-9_.\-]+)\}")


def _props(args):
    out = {}
    for tok in (args or "").split():
        m = re.match(r"^-[JG]([^=]+)=(.*)$", tok)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _resolve(value, variables, props):
    v = value or ""
    for _ in range(6):
        before = v
        v = FN_P.sub(lambda m: props.get(m.group(1), m.group(2) or ""), v)
        v = FN_PROPERTY.sub(lambda m: props.get(m.group(1), m.group(2) or ""), v)
        v = VAR.sub(lambda m: variables.get(m.group(1), m.group(0)), v)
        if v == before:
            break
    return v.strip()


def endpoints(project, script, extra_args="", overrides=""):
    path = projects.safe_path(project, script)
    try:
        tree = ET.parse(str(path))
    except Exception as exc:  # noqa: BLE001
        raise projects.ProjectError(f"Cannot parse JMX: {exc}")
    props = _props(extra_args)
    props.update(_props(overrides))

    variables = {}
    for args in tree.iter("elementProp"):
        if args.get("elementType") == "Argument":
            n = args.find("./stringProp[@name='Argument.name']")
            val = args.find("./stringProp[@name='Argument.value']")
            if n is not None and n.text and val is not None:
                variables.setdefault(n.text.strip(), val.text or "")
    variables = {k: _resolve(v, variables, props) for k, v in variables.items()}

    def get(el, name):
        p = el.find(f"./stringProp[@name='HTTPSampler.{name}']")
        return _resolve(p.text if p is not None else "", variables, props)

    defaults = {"domain": "", "port": "", "protocol": ""}
    for cfg in tree.iter("ConfigTestElement"):
        if cfg.get("guiclass") == "HttpDefaultsGui" and cfg.get("enabled") != "false":
            for k in defaults:
                defaults[k] = get(cfg, k) or defaults[k]

    found = {}
    for smp in tree.iter("HTTPSamplerProxy"):
        if smp.get("enabled") == "false":
            continue
        domain, port, proto, spath = get(smp, "domain"), get(smp, "port"), get(smp, "protocol"), get(smp, "path")
        if spath.lower().startswith(("http://", "https://")):
            u = urlparse(spath)
            domain, port, proto = u.hostname or domain, str(u.port or ""), u.scheme
        domain = domain or defaults["domain"]
        proto = (proto or defaults["protocol"] or "http").lower()
        port = port or defaults["port"] or ("443" if proto == "https" else "80")
        key = (proto, domain, port)
        e = found.setdefault(key, {"protocol": proto, "host": domain, "port": port, "samplers": 0,
                                   "unresolved": "${" in domain or "${" in port})
        e["samplers"] += 1
    return sorted(found.values(), key=lambda e: (-e["samplers"], e["host"]))


def check(ep, timeout=5):
    res = {**ep, "dns": None, "tcp_ms": None, "tls": None, "http": None, "ok": False, "error": None}
    if ep["unresolved"] or not ep["host"]:
        res["error"] = "Host/port not resolvable from the script (pass the property in the overrides)"
        return res
    try:
        port = int(ep["port"])
        infos = socket.getaddrinfo(ep["host"], port, proto=socket.IPPROTO_TCP)
        res["dns"] = sorted({i[4][0] for i in infos})[:4]
    except (socket.gaierror, ValueError) as exc:
        res["error"] = f"DNS: {exc}"
        return res
    try:
        t0 = time.time()
        sock = socket.create_connection((ep["host"], port), timeout=timeout)
        res["tcp_ms"] = round((time.time() - t0) * 1000, 1)
    except OSError as exc:
        res["error"] = f"TCP {ep['host']}:{port}: {exc}"
        return res
    try:
        if ep["protocol"] == "https":
            ctx = ssl.create_default_context()
            try:
                tls = ctx.wrap_socket(sock, server_hostname=ep["host"])
                cert = tls.getpeercert()
                exp = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                days = (exp - datetime.now(timezone.utc)).days
                res["tls"] = f"{tls.version()} · cert expires in {days} days"
                tls.close()
            except ssl.SSLCertVerificationError as exc:
                res["tls"] = f"certificate NOT trusted by the Master: {exc.verify_message}"
                res["http"] = "skipped (untrusted certificate; JMeter itself does not verify certificates)"
                res["ok"] = True  # reachable; JMeter's HTTP sampler accepts any certificate
                sock.close()
                return res
            conn = http.client.HTTPSConnection(ep["host"], port, timeout=timeout, context=ctx)
        else:
            sock.close()
            conn = http.client.HTTPConnection(ep["host"], port, timeout=timeout)
        t0 = time.time()
        conn.request("GET", "/", headers={"User-Agent": "JMeter-Control-Center-check"})
        r = conn.getresponse()
        res["http"] = f"HTTP {r.status} in {round((time.time() - t0) * 1000)} ms"
        conn.close()
        res["ok"] = True
    except (OSError, http.client.HTTPException) as exc:
        res["http"] = f"no HTTP answer: {exc}"
        res["ok"] = res["tcp_ms"] is not None  # port is open, protocol may differ
    return res


def check_all(eps):
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(check, eps[:20]))
