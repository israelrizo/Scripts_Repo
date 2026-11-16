"""New Relic (shared performance-engineering account) through NerdGraph + NRQL.

* discover(project, tag)      which APM services received the traffic of a script: matches the hosts and
                              request paths found in the JMX against Transaction events
                              (request.headers.host / request.uri) over the last N hours
* window_summary(apps, s, e)  APM + infrastructure metrics of those services during a run window
* project apps                the services are pinned per project (project → Settings) once confirmed;
                              runs use the pinned list, or auto-discovery when nothing is pinned
"""
import json
import re
import time
import urllib.error
import urllib.request

from . import connectivity, projects, settings
from .config import _env

ENDPOINTS = {"us": "https://api.newrelic.com/graphql", "eu": "https://api.eu.newrelic.com/graphql"}
UI = {"us": "https://one.newrelic.com", "eu": "https://one.eu.newrelic.com"}
SAFE = re.compile(r"[^A-Za-z0-9._\-/%:]")
APP_RE = re.compile(r"^[^'\\\n]{1,120}$")
ID_SEG = re.compile(r"^(\d+|[0-9a-fA-F\-]{8,}|\$\{.*\}|[A-Za-z0-9_\-]{20,})$")


class NewRelicError(RuntimeError):
    pass


def cfg():
    return settings.get()["newrelic"]


def enabled():
    c = cfg()
    return bool(c.get("enabled") and c.get("account_id") and c.get("api_key_enc"))


def _endpoint():
    return _env("SR_NEWRELIC_URL") or ENDPOINTS.get(cfg().get("region", "us"), ENDPOINTS["us"])


def graphql(query, variables=None, timeout=60):
    c = cfg()
    key = settings.decrypt(c.get("api_key_enc", ""))
    if not key:
        raise NewRelicError("New Relic API key not configured (Settings → New Relic)")
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(_endpoint(), data=body, method="POST",
                                 headers={"API-Key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        hint = " (check the User API key: it starts with NRAK-)" if exc.code in (401, 403) else ""
        raise NewRelicError(f"New Relic HTTP {exc.code}{hint}: {detail}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise NewRelicError(f"Cannot reach New Relic: {exc}")
    if data.get("errors"):
        raise NewRelicError("; ".join(e.get("message", "?") for e in data["errors"])[:400])
    return data.get("data") or {}


def nrql(query, timeout=60):
    acc = int(cfg()["account_id"])
    q = ("query($acc: Int!, $nrql: Nrql!) { actor { account(id: $acc) { nrql(query: $nrql, timeout: %d) "
         "{ results } } } }" % min(int(timeout), 120))
    d = graphql(q, {"acc": acc, "nrql": query}, timeout + 10)
    return ((d.get("actor") or {}).get("account") or {}).get("nrql", {}).get("results") or []


def test_connection():
    d = graphql("query($acc: Int!) { actor { user { email } account(id: $acc) { name } } }",
                {"acc": int(cfg()["account_id"])})
    actor = d.get("actor") or {}
    acc = actor.get("account")
    if not acc:
        raise NewRelicError("The API key has no access to that account id")
    return {"user": (actor.get("user") or {}).get("email"), "account": acc.get("name")}


def _lit(value):
    """NRQL string literal from JMX-derived text (only safe characters survive)."""
    return "'" + SAFE.sub("", value)[:200] + "'"


def _app_list(apps):
    clean = [a for a in apps if APP_RE.match(a or "")]
    if not clean:
        raise NewRelicError("No valid APM service names")
    return "(" + ", ".join("'" + a + "'" for a in clean[:20]) + ")"


# --------------------------------------------------------------------------- discovery
def path_patterns(paths, limit=10):
    """'/blacklist/api/v1/searches/5fd6d58.../logs' -> '/blacklist/api/v1/%' (first static segments)."""
    out = []
    for p in paths:
        segs = [s for s in p.strip().split("/") if s]
        static = []
        for s in segs:
            if ID_SEG.match(s) or "${" in s:
                break
            static.append(s)
            if len(static) == 3:
                break
        if not static:
            continue
        pat = "/" + "/".join(static) + "%"
        if pat not in out:
            out.append(pat)
    return out[:limit]


def script_signature(project, script, extra_args=""):
    eps = connectivity.endpoints(project, script, extra_args)
    hosts = sorted({e["host"] for e in eps if e["host"] and not e["unresolved"]})
    paths = [p for e in eps for p in e.get("paths", [])]
    return hosts, path_patterns(paths)


def discover(project, script, extra_args="", hours=None):
    hours = int(hours or cfg().get("lookback_hours") or 24)
    hosts, patterns = script_signature(project, script, extra_args)
    if not hosts and not patterns:
        return {"hosts": hosts, "patterns": patterns, "apps": [], "note": "No HTTP endpoints in this script"}
    conds = [f"request.headers.host LIKE {_lit(h.split(':')[0] + '%')}" for h in hosts]
    conds += [f"request.uri LIKE {_lit(p)}" for p in patterns]
    q = (f"SELECT count(*) AS 'requests', latest(request.headers.host) AS 'host', latest(request.uri) AS 'uri' "
         f"FROM Transaction WHERE {' OR '.join(conds)} FACET appName SINCE {hours} hours ago LIMIT 15")
    rows = nrql(q)
    apps = []
    for r in rows:
        name = _facet(r, "appName")
        if not name:
            continue
        host, uri = r.get("host") or "", r.get("uri") or ""
        by = []
        if any(host.startswith(h.split(":")[0]) for h in hosts):
            by.append(f"host {host}")
        if any(uri.startswith(p.rstrip("%")) for p in patterns):
            by.append(f"path {uri[:60]}")
        apps.append({"name": name, "requests": r.get("requests", 0), "matched_by": ", ".join(by) or "host/path",
                     "sample_uri": uri[:120]})
    note = "" if apps else (f"No APM transactions matched in the last {hours} h. Behind a gateway the APM agent may "
                            "not record request.uri; pin the services manually in project → Settings.")
    return {"hosts": hosts, "patterns": patterns, "apps": apps, "note": note}


def entity_links(apps):
    """{appName: permalink} for APM services."""
    if not apps:
        return {}
    names = " OR ".join(f"name = '{a}'" for a in apps if APP_RE.match(a))
    try:
        d = graphql("query($q: String!) { actor { entitySearch(query: $q) { results { entities { name guid permalink } } } } }",
                    {"q": f"domain = 'APM' AND type = 'APPLICATION' AND ({names})"})
    except NewRelicError:
        return {}
    ents = (((d.get("actor") or {}).get("entitySearch") or {}).get("results") or {}).get("entities") or []
    return {e["name"]: e.get("permalink") or f"{UI.get(cfg().get('region', 'us'))}/redirect/entity/{e['guid']}"
            for e in ents}


def apps_for(project, script=None, extra_args=""):
    """Pinned services of the project, else auto-discovered for the script."""
    pinned = [a for a in settings.project(project).get("nr_apps") or [] if APP_RE.match(a)]
    if pinned:
        return pinned, "pinned"
    if not script:
        return [], "none"
    found = discover(project, script, extra_args)["apps"]
    return [a["name"] for a in found[:5]], "auto"


# --------------------------------------------------------------------------- run window metrics
def window_summary(apps, start_ms, end_ms):
    if not apps:
        return None
    lst = _app_list(apps)
    since = f"SINCE {int(start_ms)} UNTIL {int(end_ms)}"
    span_min = max(1, (end_ms - start_ms) / 60000)
    out = {"apps": {}, "since": start_ms, "until": end_ms, "errors": []}

    def safe(name, q):
        try:
            return nrql(q)
        except NewRelicError as exc:
            out["errors"].append(f"{name}: {exc}")
            return []

    for r in safe("apm", f"SELECT count(*) AS 'requests', average(duration) * 1000 AS 'avg_ms', "
                         f"percentile(duration, 95) AS 'p95', percentage(count(*), WHERE error IS true) AS 'error_pct', "
                         f"average(databaseDuration) * 1000 AS 'db_ms', average(externalDuration) * 1000 AS 'ext_ms' "
                         f"FROM Transaction WHERE appName IN {lst} FACET appName {since} LIMIT 20"):
        name = _facet(r, "appName")
        p95 = r.get("p95")
        if isinstance(p95, dict):
            p95 = next(iter(p95.values()), None)
        out["apps"][name] = {"requests": r.get("requests") or 0, "avg_ms": _r(r.get("avg_ms")),
                             "p95_ms": _r((p95 or 0) * 1000), "error_pct": _r(r.get("error_pct"), 2),
                             "rpm": _r((r.get("requests") or 0) / span_min, 1),
                             "db_ms": _r(r.get("db_ms")), "ext_ms": _r(r.get("ext_ms")),
                             "cpu": None, "mem": None, "hosts": 0, "top": [], "error_classes": []}
    for name in list(out["apps"]):
        if not APP_RE.match(name or ""):
            out["apps"].pop(name, None)
            continue
        _infra(out, name, since, safe)
        out["apps"][name]["top"] = [
            {"name": _facet(t, "name"), "requests": t.get("requests") or 0, "avg_ms": _r(t.get("avg_ms")),
             "error_pct": _r(t.get("error_pct"), 2)}
            for t in safe("top", f"SELECT count(*) AS 'requests', average(duration) * 1000 AS 'avg_ms', "
                                 f"percentage(count(*), WHERE error IS true) AS 'error_pct' FROM Transaction "
                                 f"WHERE appName = '{name}' FACET name {since} LIMIT 5")]
        out["apps"][name]["error_classes"] = [
            {"class": _facet(e, "error.class"), "count": e.get("count")}
            for e in safe("errors", f"SELECT count(*) FROM TransactionError WHERE appName = '{name}' "
                                    f"FACET error.class {since} LIMIT 5")]
    out["links"] = entity_links(list(out["apps"]))
    return out


def _infra(out, name, since, safe):
    rows = safe("infra", f"SELECT average(cpuPercent) AS 'cpu', max(cpuPercent) AS 'cpu_max', "
                         f"average(memoryUsedPercent) AS 'mem', uniqueCount(hostname) AS 'hosts' FROM SystemSample "
                         f"WHERE apmApplicationNames LIKE '%|{name}|%' {since}")
    if rows:
        r = rows[0]
        out["apps"][name].update(cpu=_r(r.get("cpu"), 1), cpu_max=_r(r.get("cpu_max"), 1), mem=_r(r.get("mem"), 1),
                                 hosts=r.get("hosts") or 0)


def _facet(row, attr):
    """NRQL FACET value: NerdGraph returns it as the attribute key and/or 'facet' (str or list)."""
    v = row.get(attr) or row.get("facet")
    if isinstance(v, list):
        v = v[0] if v else None
    return v


def _r(v, d=0):
    if v is None:
        return None
    try:
        return round(float(v), d) if d else round(float(v))
    except (TypeError, ValueError):
        return None


def resources_text(summary):
    """Narrative for the 'Recursos Servidor' section of the Confluence report (Spanish)."""
    if not summary or not summary.get("apps"):
        return ""
    lines = ["Métricas de New Relic durante la ventana de ejecución:"]
    for name, a in summary["apps"].items():
        infra = (f"CPU promedio {a['cpu']} % (máx {a.get('cpu_max')} %), memoria {a['mem']} % en {a['hosts']} host(s)"
                 if a.get("cpu") is not None else "sin datos de infraestructura vinculados")
        lines.append(f"- {name}: {a['requests']:,} transacciones ({a['rpm']} rpm), promedio {a['avg_ms']} ms, "
                     f"p95 {a['p95_ms']} ms, error {a['error_pct']} %; base de datos {a['db_ms']} ms y servicios "
                     f"externos {a['ext_ms']} ms por transacción; {infra}.")
        if a.get("error_classes"):
            lines.append("  Errores: " + ", ".join(f"{e['class']} ({e['count']})" for e in a["error_classes"] if e.get("class")))
    return "\n".join(lines)


def run_hook(meta):
    """Called when a run ends: store the New Relic summary of the run window in the run metadata."""
    from . import runner
    if not enabled() or meta.get("kind") != "test" or not meta.get("started"):
        return
    if not cfg().get("auto_on_run", True):
        return
    t = projects.get_tag(meta["project"], meta.get("tag", "")) or {}
    apps, source = apps_for(meta["project"], meta.get("script"), t.get("extra_args", ""))
    log = runner._runs_dir() / f"{meta['id']}.log"
    if not apps:
        with log.open("a") as fh:
            fh.write(f"### {time.strftime('%H:%M:%S')} newrelic: no APM service matched this script\n")
        return
    start = int(meta["started"] * 1000) - 60000
    end = int((meta.get("ended") or time.time()) * 1000) + 60000
    summary = window_summary(apps, start, end)
    summary["source"] = source
    runner.update(meta["id"], newrelic=summary)
    with log.open("a") as fh:
        fh.write(f"### {time.strftime('%H:%M:%S')} newrelic: {len(summary['apps'])} service(s) ({source}): "
                 f"{', '.join(summary['apps'])}{' · ' + '; '.join(summary['errors']) if summary['errors'] else ''}\n")
