"""DNS -> TCP -> TLS -> HTTP reachability checks. Standard library only: this file is also sent to the
JMeter Master and executed there (python3 - <b64 json>) so the check runs from where the load comes from."""
import base64
import http.client
import json
import socket
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone


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


if __name__ == "__main__":
    print("@@JSON@@" + json.dumps(check_all(json.loads(base64.b64decode(sys.argv[1])))))
