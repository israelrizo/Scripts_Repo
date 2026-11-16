"""Find the servers a JMX hits and check they are reachable from the Master.

Resolves ${var} (User Defined Variables) and ${__P(name,default)} / ${__property(name,,default)}
with the tag's EXTRA_ARGS and the overrides typed in the UI, then checks DNS → TCP → TLS → HTTP.
"""
import base64
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from defusedxml import ElementTree as ET

from . import netcheck, projects

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


def check_all(eps):
    """Local mode: check from this machine. AWS mode: run the same checks on the Master through SSM."""
    from . import settings
    if not settings.aws_mode():
        return netcheck.check_all(eps)
    from . import aws
    master = aws.cfg().get("master")
    inst = next((i for i in aws.instances() if i["id"] == master), None)
    if not inst or inst["state"] != "running" or not inst["ssm"]:
        raise projects.ProjectError("The Master is stopped: start the servers to check connectivity from it")
    src = Path(netcheck.__file__).read_text()
    arg = base64.b64encode(json.dumps(eps[:20]).encode()).decode()
    rc, out, err = aws.run(master, f"python3 - {arg} <<'JMCC_PY'\n{src}\nJMCC_PY\n", timeout=120)
    marker = out.rfind("@@JSON@@")
    if marker < 0:
        raise projects.ProjectError(f"Check failed on the Master: {(err or out)[-200:]}")
    return json.loads(out[marker + 8:])
