"""Live metrics from InfluxDB written by JMeter's InfluxdbBackendListenerClient (InfluxQL / v1 API).

Schema written by JMeter (measurement "jmeter" by default):
  transaction=internal                         -> minAT, maxAT, meanAT, startedT, endedT  (virtual users)
  transaction=all, statut=all                  -> count, countError, hit, avg, min, max, pct95.0 ...
  transaction=<label>, statut=all|ok|ko        -> count, avg, min, max, pctXX
  transaction=<label>, responseCode, responseMessage -> count   (only for failed samples)
Optional user tags (TAG_host=${__machineName()}) are respected when summing slaves.

Every chart is an independent query: one failing panel never breaks the whole page.
"""
import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from defusedxml import ElementTree as ET

from .config import _env
from . import projects

INFLUX_URL = _env("SR_INFLUX_URL", "http://localhost:8086").rstrip("/")
INFLUX_USER = _env("SR_INFLUX_USER", "")
INFLUX_PASSWORD = _env("SR_INFLUX_PASSWORD", "")
INFLUX_TOKEN = _env("SR_INFLUX_TOKEN", "")  # InfluxDB 2.x (v1-compatible /query with DBRP mapping)
INFLUX_TIMEOUT = int(_env("SR_INFLUX_TIMEOUT", "20"))
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
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{INFLUX_URL}/query", data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    if INFLUX_TOKEN:
        req.add_header("Authorization", f"Token {INFLUX_TOKEN}")
    elif INFLUX_USER:
        token = base64.b64encode(f"{INFLUX_USER}:{INFLUX_PASSWORD}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=INFLUX_TIMEOUT) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        try:
            detail = json.loads(detail).get("error", detail)
        except ValueError:
            pass
        hint = {401: " (set SR_INFLUX_USER/PASSWORD or SR_INFLUX_TOKEN)",
                404: " (InfluxDB 2.x needs a DBRP mapping for this database)"}.get(exc.code, "")
        raise InfluxError(f"InfluxDB HTTP {exc.code}{hint}: {detail}")
    except Exception as exc:  # noqa: BLE001 - surface any connectivity error to the UI
        raise InfluxError(f"InfluxDB not reachable at {INFLUX_URL}: {exc}")
    results = body.get("results", [])
    if body.get("error"):
        raise InfluxError(body["error"])
    for r in results:
        if "error" in r:
            raise InfluxError(r["error"])
    return results


def _series(result):
    return result.get("series", []) if result else []


def _first(results):
    return results[0] if results else {}


def ping():
    try:
        query(None, "SHOW DATABASES")
        return True, INFLUX_URL
    except InfluxError as exc:
        return False, str(exc)


def databases():
    res = _first(query(None, "SHOW DATABASES"))
    return sorted(v[0] for s in _series(res) for v in s.get("values", []) if v and v[0] != "_internal")


def applications(db, measurement="jmeter"):
    _check(db, measurement)
    res = _first(query(db, f'SHOW TAG VALUES FROM "{measurement}" WITH KEY = "application"'))
    return sorted(v[1] for s in _series(res) for v in s.get("values", []) if len(v) > 1)


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
                    "localhost": "localhost" in url or "127.0.0.1" in url,
                    "host_tag": any(k.startswith("TAG_") for k in args)})
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
            if len(v) > col and v[col] is not None:
                out.append([v[0], v[col]])
    return out


def _panel_queries(app, start_ms, end_ms, measurement, b):
    m = f'"{measurement}"'
    tr = f"time >= {int(start_ms)}ms AND time <= {int(end_ms)}ms"
    where = f'"application" = {_q(app)} AND {tr}'
    gb = f"GROUP BY time({b}s) fill(none)"
    real_tx = '"transaction" != \'all\' AND "transaction" != \'internal\''
    return {
        # virtual users: max per slave/host, summed (outer query needs its own time range)
        "vusers": [
            f'SELECT sum("u") FROM (SELECT max("maxAT") AS "u" FROM {m} WHERE {where} AND "transaction" = \'internal\' '
            f'GROUP BY time({b}s), "host" fill(none)) WHERE {tr} {gb}',
            # fallback without subquery (very old InfluxDB or no host tag)
            f'SELECT max("maxAT") FROM {m} WHERE {where} AND "transaction" = \'internal\' {gb}',
        ],
        "rates": [
            f'SELECT sum("hit") / {b} AS "hps", sum("countError") / {b} AS "eps", mean("avg") AS "avg", '
            f'max("pct95.0") AS "p95" FROM {m} WHERE {where} AND "transaction" = \'all\' AND "statut" = \'all\' {gb}',
        ],
        "totals": [
            f'SELECT sum("count") AS "req", sum("countError") AS "err", mean("avg") AS "avg", '
            f'max("pct95.0") AS "p95", max("max") AS "max" FROM {m} '
            f'WHERE {where} AND "transaction" = \'all\' AND "statut" = \'all\'',
        ],
        "codes": [
            f'SELECT sum("count") FROM {m} WHERE {where} AND "responseCode" != \'\' GROUP BY "responseCode"',
        ],
        "tx": [
            f'SELECT sum("count") AS "count", mean("avg") AS "avg", max("pct95.0") AS "p95", max("max") AS "max" '
            f'FROM {m} WHERE {where} AND "statut" = \'all\' AND {real_tx} GROUP BY "transaction"',
        ],
        "tx_err": [
            f'SELECT sum("count") FROM {m} WHERE {where} AND "statut" = \'ko\' AND {real_tx} GROUP BY "transaction"',
        ],
        "tx_p95": [
            f'SELECT max("pct95.0") FROM {m} WHERE {where} AND "statut" = \'all\' AND {real_tx} '
            f'GROUP BY time({b}s), "transaction" fill(none)',
        ],
    }


def _run_panels(db, queries):
    out, errors = {}, {}
    for name, candidates in queries.items():
        last = None
        for q in candidates:
            try:
                out[name] = _first(query(db, q))
                last = None
                break
            except InfluxError as exc:
                last = str(exc)
                if "not reachable" in last:
                    raise
        if last:
            out[name] = {}
            errors[name] = last
    return out, errors


def dashboard(db, app, start_ms, end_ms, measurement="jmeter"):
    _check(db, app, measurement)
    b = _bucket(start_ms, end_ms)
    res, errors = _run_panels(db, _panel_queries(app, start_ms, end_ms, measurement, b))

    rates = {"hps": [], "eps": [], "avg": [], "p95": []}
    for s in _series(res["rates"]):
        cols = s.get("columns", [])
        for v in s.get("values", []):
            for k in rates:
                if k in cols and v[cols.index(k)] is not None:
                    rates[k].append([v[0], round(v[cols.index(k)], 2)])

    totals = {"req": 0, "err": 0, "avg": None, "p95": None, "max": None}
    for s in _series(res["totals"]):
        cols, vals = s.get("columns", []), s.get("values") or [[]]
        row = vals[0]
        totals.update({k: row[cols.index(k)] for k in list(totals) if k in cols and cols.index(k) < len(row)})
    req, err = totals["req"] or 0, totals["err"] or 0
    totals["error_pct"] = round(err * 100.0 / req, 2) if req else 0.0

    codes = {}
    for s in _series(res["codes"]):
        vals = s.get("values") or [[None, 0]]
        codes[s.get("tags", {}).get("responseCode", "?")] = vals[0][1] or 0
    ok = max(0, req - err)
    pie = [{"code": "OK (2xx/3xx)", "count": ok}] if ok else []
    pie += [{"code": str(c), "count": n} for c, n in sorted(codes.items(), key=lambda kv: -kv[1])]

    tx = {}
    for s in _series(res["tx"]):
        name = s.get("tags", {}).get("transaction")
        cols, row = s.get("columns", []), (s.get("values") or [[]])[0]
        tx[name] = {"transaction": name, "errors": 0,
                    **{k: (row[cols.index(k)] if k in cols else None) for k in ("count", "avg", "p95", "max")}}
    for s in _series(res["tx_err"]):
        name = s.get("tags", {}).get("transaction")
        tx.setdefault(name, {"transaction": name, "count": 0, "avg": None, "p95": None, "max": None})
        tx[name]["errors"] = (s.get("values") or [[None, 0]])[0][1] or 0
    for t in tx.values():
        t["error_pct"] = round((t["errors"] or 0) * 100.0 / t["count"], 2) if t.get("count") else 0.0

    p95_tx = {}
    for s in _series(res["tx_p95"]):
        p95_tx[s.get("tags", {}).get("transaction")] = [[v[0], round(v[1], 1)] for v in s.get("values", [])
                                                         if v[1] is not None]
    top = sorted(tx.values(), key=lambda t: -(t.get("p95") or 0))[:8]

    return {
        "bucket_s": b, "vusers": _points(res["vusers"]), "hps": rates["hps"], "eps": rates["eps"],
        "avg": rates["avg"], "p95": rates["p95"], "totals": totals, "codes": pie,
        "transactions": sorted(tx.values(), key=lambda t: t["transaction"] or ""),
        "p95_by_tx": {t["transaction"]: p95_tx.get(t["transaction"], []) for t in top},
        "errors": errors,
    }


# --------------------------------------------------------------------------- diagnostics
def diagnostics(db="", app="", measurement="jmeter", minutes=60):
    """Step-by-step checks shown on the admin Settings page."""
    steps = []

    def step(name, fn):
        t0 = time.time()
        try:
            detail = fn()
            steps.append({"name": name, "ok": True, "detail": detail, "ms": round((time.time() - t0) * 1000)})
            return True
        except Exception as exc:  # noqa: BLE001
            steps.append({"name": name, "ok": False, "detail": str(exc), "ms": round((time.time() - t0) * 1000)})
            return False

    if not step(f"Connect to {INFLUX_URL}", lambda: f"databases: {', '.join(databases()) or 'none'}"):
        return steps
    if not db:
        return steps
    step(f"Measurements in {db}", lambda: ", ".join(
        v[0] for s in _series(_first(query(db, "SHOW MEASUREMENTS"))) for v in s.get("values", [])) or "none")
    step(f'Applications in "{measurement}"', lambda: ", ".join(applications(db, measurement)) or "none")
    if not app:
        return steps

    def last_point():
        res = _first(query(db, f'SELECT last("count") FROM "{measurement}" WHERE "application" = {_q(app)}'))
        pts = _points(res)
        if not pts:
            return "no points written yet for this application"
        age = (time.time() * 1000 - pts[0][0]) / 1000
        return f"last sample {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(pts[0][0] / 1000))} ({age:,.0f} s ago)"
    step("Last sample written", last_point)

    end = int(time.time() * 1000)
    start = end - minutes * 60 * 1000
    b = _bucket(start, end)
    for name, candidates in _panel_queries(app, start, end, measurement, b).items():
        def run(cands=candidates):
            errs = []
            for q in cands:
                try:
                    res = _first(query(db, q))
                    n = sum(len(s.get("values", [])) for s in _series(res))
                    return f"{n} rows" + (" (fallback query)" if errs else "")
                except InfluxError as exc:
                    errs.append(str(exc))
            raise InfluxError(" | ".join(errs))
        step(f"Panel query: {name} (last {minutes} min)", run)
    return steps
