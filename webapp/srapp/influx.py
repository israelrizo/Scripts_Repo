"""Live metrics from InfluxDB 1.x written by JMeter's InfluxdbBackendListenerClient.

Schema written by JMeter (measurement "jmeter" by default):
  transaction=internal                         -> minAT, maxAT, meanAT, startedT, endedT  (virtual users)
  transaction=all, statut=all                  -> count, countError, hit, avg, min, max, pct95.0 ...
  transaction=<label>, statut=all|ok|ko        -> count, avg, min, max, pctXX
  transaction=<label>, responseCode, responseMessage -> count   (only for failed samples)
Optional user tags (TAG_host=${__machineName()}) are respected when summing slaves.
"""
import base64
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from defusedxml import ElementTree as ET

from .config import _env
from . import projects

INFLUX_URL = _env("SR_INFLUX_URL", "http://localhost:8086").rstrip("/")
INFLUX_USER = _env("SR_INFLUX_USER", "")
INFLUX_PASSWORD = _env("SR_INFLUX_PASSWORD", "")
GRAFANA_URL = _env("SR_GRAFANA_URL", "")
NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,80}$")


class InfluxError(RuntimeError):
    pass


def _q(s):
    """Quote an InfluxQL string literal (values are pre-validated with NAME_RE)."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def query(db, q):
    params = {"q": q, "epoch": "ms"}
    if db:
        params["db"] = db
    req = urllib.request.Request(f"{INFLUX_URL}/query?{urllib.parse.urlencode(params)}")
    if INFLUX_USER:
        token = base64.b64encode(f"{INFLUX_USER}:{INFLUX_PASSWORD}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001 - surface any connectivity error to the UI
        raise InfluxError(f"InfluxDB not reachable at {INFLUX_URL}: {exc}")
    results = body.get("results", [])
    for r in results:
        if "error" in r:
            raise InfluxError(r["error"])
    return results


def _series(result):
    return result.get("series", []) if result else []


def ping():
    try:
        query(None, "SHOW DATABASES")
        return True, INFLUX_URL
    except InfluxError as exc:
        return False, str(exc)


def databases():
    res = query(None, "SHOW DATABASES")
    return sorted(v[0] for s in _series(res[0]) for v in s.get("values", []) if v[0] != "_internal")


def applications(db):
    _check(db)
    res = query(db, 'SHOW TAG VALUES FROM "jmeter" WITH KEY = "application"')
    return sorted(v[1] for s in _series(res[0]) for v in s.get("values", []))


def _check(*names):
    for n in names:
        if not NAME_RE.match(n or ""):
            raise InfluxError(f"Invalid name '{n}'")


# --------------------------------------------------------------------------- JMX discovery
def listener_targets(jmx: Path):
    """Return [{db, application, url}] for each enabled InfluxDB Backend Listener of a JMX."""
    out = []
    try:
        tree = ET.parse(str(jmx))
    except Exception:  # noqa: BLE001 - malformed/hostile XML just means "no listener found"
        return out
    for bl in tree.iter("BackendListener"):
        if bl.get("enabled") == "false":
            continue
        cls = bl.find("./stringProp[@name='classname']")
        if cls is None or "influxdb" not in (cls.text or "").lower():
            continue
        args = {}
        for el in bl.iter("elementProp"):
            name = el.find("./stringProp[@name='Argument.name']")
            val = el.find("./stringProp[@name='Argument.value']")
            if name is not None and val is not None:
                args[name.text] = (val.text or "").strip()
        url = args.get("influxdbUrl", "")
        db = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("db", [""])[0]
        out.append({"db": db, "application": args.get("application", ""), "url": url,
                    "measurement": args.get("measurement", "jmeter") or "jmeter",
                    "localhost": "localhost" in url or "127.0.0.1" in url})
    return out


def project_targets(project):
    base = projects.project_dir(project)
    seen, out = set(), []
    for t in projects.parse_tags(project):
        if not t["exists"]:
            continue
        for tgt in listener_targets(base / t["script"]):
            key = (tgt["db"], tgt["application"])
            if key not in seen and NAME_RE.match(tgt["db"] or "") and NAME_RE.match(tgt["application"] or ""):
                seen.add(key)
                out.append(tgt)
    return out


# --------------------------------------------------------------------------- dashboard
def _bucket(start_ms, end_ms):
    span = max(1, (end_ms - start_ms) / 1000)
    for b in (5, 10, 15, 30, 60, 120, 300, 600):
        if span / b <= 240:
            return b
    return 900


def _points(res, col=1):
    out = []
    for s in _series(res):
        for v in s.get("values", []):
            if v[col] is not None:
                out.append([v[0], v[col]])
    return out


def dashboard(db, app, start_ms, end_ms, measurement="jmeter"):
    _check(db, app, measurement)
    b = _bucket(start_ms, end_ms)
    m = f'"{measurement}"'
    where = f'"application" = {_q(app)} AND time >= {int(start_ms)}ms AND time <= {int(end_ms)}ms'
    gb = f"GROUP BY time({b}s) fill(none)"
    qs = [
        # 0 virtual users (sum per slave/host if TAG_host is configured)
        f'SELECT sum("u") FROM (SELECT max("maxAT") AS "u" FROM {m} WHERE {where} AND "transaction" = \'internal\' '
        f'GROUP BY time({b}s), "host" fill(none)) {gb}',
        # 1 hits/s, errors/s, avg, p95
        f'SELECT sum("hit") / {b} AS "hps", sum("countError") / {b} AS "eps", mean("avg") AS "avg", '
        f'max("pct95.0") AS "p95" FROM {m} WHERE {where} AND "transaction" = \'all\' AND "statut" = \'all\' {gb}',
        # 2 totals
        f'SELECT sum("count") AS "req", sum("countError") AS "err", mean("avg") AS "avg", max("pct95.0") AS "p95", '
        f'max("max") AS "max" FROM {m} WHERE {where} AND "transaction" = \'all\' AND "statut" = \'all\'',
        # 3 response code distribution of failed samples
        f'SELECT sum("count") FROM {m} WHERE {where} AND "responseCode" =~ /.+/ GROUP BY "responseCode"',
        # 4 per-transaction table
        f'SELECT sum("count") AS "count", mean("avg") AS "avg", max("pct95.0") AS "p95", max("max") AS "max" '
        f'FROM {m} WHERE {where} AND "statut" = \'all\' AND "transaction" !~ /^(all|internal)$/ GROUP BY "transaction"',
        # 5 per-transaction errors
        f'SELECT sum("count") FROM {m} WHERE {where} AND "statut" = \'ko\' AND "transaction" !~ /^(all|internal)$/ '
        f'GROUP BY "transaction"',
        # 6 per-transaction p95 over time (top series for the chart)
        f'SELECT max("pct95.0") FROM {m} WHERE {where} AND "statut" = \'all\' AND "transaction" !~ /^(all|internal)$/ '
        f'GROUP BY time({b}s), "transaction" fill(none)',
    ]
    res = query(db, ";".join(qs))
    res += [{}] * (len(qs) - len(res))

    vusers = _points(res[0])
    rates = {"hps": [], "eps": [], "avg": [], "p95": []}
    for s in _series(res[1]):
        cols = s["columns"]
        for v in s.get("values", []):
            for k in rates:
                val = v[cols.index(k)]
                if val is not None:
                    rates[k].append([v[0], round(val, 2)])

    totals = {"req": 0, "err": 0, "avg": None, "p95": None, "max": None}
    for s in _series(res[2]):
        cols = s["columns"]
        row = s["values"][0]
        totals.update({k: row[cols.index(k)] for k in totals if k in cols})
    req, err = totals["req"] or 0, totals["err"] or 0
    totals["error_pct"] = round(err * 100.0 / req, 2) if req else 0.0

    codes = {}
    for s in _series(res[3]):
        codes[s.get("tags", {}).get("responseCode", "?")] = s["values"][0][1]
    ok = max(0, req - err)
    pie = [{"code": "OK (2xx/3xx)", "count": ok}] if ok else []
    pie += [{"code": str(c), "count": n} for c, n in sorted(codes.items(), key=lambda kv: -kv[1])]

    tx = {}
    for s in _series(res[4]):
        name = s.get("tags", {}).get("transaction")
        cols = s["columns"]
        row = s["values"][0]
        tx[name] = {"transaction": name, "errors": 0, **{k: row[cols.index(k)] for k in ("count", "avg", "p95", "max")}}
    for s in _series(res[5]):
        name = s.get("tags", {}).get("transaction")
        tx.setdefault(name, {"transaction": name, "count": 0, "avg": None, "p95": None, "max": None})
        tx[name]["errors"] = s["values"][0][1]
    for t in tx.values():
        t["error_pct"] = round((t["errors"] or 0) * 100.0 / t["count"], 2) if t.get("count") else 0.0

    p95_tx = {}
    for s in _series(res[6]):
        p95_tx[s.get("tags", {}).get("transaction")] = [[v[0], round(v[1], 1)] for v in s["values"] if v[1] is not None]
    top = sorted(tx.values(), key=lambda t: -(t.get("p95") or 0))[:8]

    return {
        "bucket_s": b, "vusers": vusers, "hps": rates["hps"], "eps": rates["eps"],
        "avg": rates["avg"], "p95": rates["p95"], "totals": totals, "codes": pie,
        "transactions": sorted(tx.values(), key=lambda t: t["transaction"] or ""),
        "p95_by_tx": {t["transaction"]: p95_tx.get(t["transaction"], []) for t in top},
    }
