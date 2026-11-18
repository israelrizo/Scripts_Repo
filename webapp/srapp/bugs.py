"""Non-functional (performance) Jira bug from a run that failed its acceptance criteria.

Follows the team template "Reporte de bug no funcional - Prueba de rendimiento": the run data fills what the
app knows (scenario, criteria, results, evidence); the engineer reviews it and completes context and impact.
The description is Jira wiki markup (REST API v2, Jira Cloud and Data Center).
"""
import json
import re
import time

from . import atlassian, notify, projects, report, runner, settings
from .config import Config

ENV_RE = re.compile(r"(?<![A-Za-z])(QA\d*|UAT\d*|DEV\d*|STG|STAGING|PREPROD|PRE|SANDBOX|PROD|PRD)(?![A-Za-z])")
THREADS_RE = re.compile(r"^-J(?:threads|hilos|users|usuarios|vus?|num_?threads)\w*=(\d+)$", re.IGNORECASE)

# (key, label, kind) in template order; kind: line | text | list
FIELDS = [
    ("epica", "Épica padre (ej. PQA-298)", "line"),
    ("resumen", "Resumen", "line"), ("contexto", "Contexto", "text"), ("ambiente", "Ambiente", "line"),
    ("aplicacion", "Aplicación", "line"), ("fecha", "Fecha de ejecución", "line"),
    ("reportado_por", "Reportado por", "line"), ("objetivo", "Objetivo de la prueba", "text"),
    ("operaciones", "Operaciones simultáneas", "line"), ("endpoint", "Endpoint / servicio evaluado", "line"),
    ("volumen", "Volumen de datos", "line"), ("duracion", "Duración de la prueba", "line"),
    ("herramienta", "Herramienta utilizada", "line"), ("script", "Script utilizado", "line"),
    ("esperado", "Resultado esperado", "list"), ("actual", "Resultado actual", "list"),
    ("evidencia", "Evidencia", "list"), ("impacto", "Impacto", "text"), ("cierre", "Criterios de aceptación para cierre", "list"),
]
REQUIRED = ("epica", "resumen", "impacto")
BUG_STATUSES = ("finished", "stopped")   # a graceful stop still produces the HTML report


def target(project):
    """(project key, issue type, labels) for this project's bugs."""
    j = settings.get()["jira"]
    try:
        key = settings.project(project).get("jira_project") or ""
    except ValueError:
        key = ""
    labels = [x.strip() for x in (j.get("bug_labels") or "").split(",") if x.strip()]
    return (key or j.get("bug_project") or "").upper(), j.get("bug_issue_type") or "Bug", labels


def project_epic(project):
    """Parent epic last used for this project's bugs (project settings, shared with the team)."""
    try:
        return settings.project(project).get("jira_epic") or ""
    except ValueError:
        return ""


def eligible(summary):
    return summary.get("status") in BUG_STATUSES and summary.get("verdict") == "INSATISFACTORIA"


# --------------------------------------------------------------------------- bugs filed per result (shared)
# instance/bugs/<project>.json = {result_dir: {key, url, by, ts}}; merged with the team through the project profile
def _store_path(project):
    d = Config.INSTANCE_DIR / "bugs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{project}.json"


def filed(project):
    p = _store_path(project)
    try:
        data = json.loads(p.read_text()) if p.exists() else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def save_filed(project, data):
    clean = {k: v for k, v in (data or {}).items()
             if isinstance(v, dict) and str(k).startswith("Ejecucion_") and "/" not in str(k)
             and atlassian.ISSUE_RE.match(str(v.get("key") or ""))}
    _store_path(project).write_text(json.dumps(clean, indent=2, ensure_ascii=False))


def bug_for(project, result_dir):
    return filed(project).get(result_dir) if result_dir else None


def meta_for_result(project, result_dir):
    """Run data for a result folder, wherever the run was launched: this computer's run, else the team record,
    else what the folder name says. Raises ProjectError when the report is not on this computer."""
    projects.result_dir(project, result_dir)
    local = next((m for m in runner.list_runs(project=project, limit=1000) if m.get("result_dir") == result_dir), None)
    if local:
        return dict(local, launched_by=local.get("email") or local.get("user") or "")
    from . import team
    rec = next((r for r in team.cached_history().values() if r.get("project") == project
                and (r.get("result_dir") or r.get("result_remote_only")) == result_dir), None) or {}
    started = rec.get("started") or team._started_from_name(result_dir)
    return {"id": rec.get("id") or "team", "kind": "test", "project": project, "result_dir": result_dir,
            "tag": rec.get("tag") or (result_dir.split("_", 3)[-1] if result_dir.count("_") >= 3 else result_dir),
            "script": rec.get("script") or "", "props": rec.get("props") or [],
            "remote_hosts": ["slave"] * int(rec.get("slaves") or 0), "status": rec.get("status") or "finished",
            "started": started, "ended": rec.get("ended"), "notes": rec.get("notes") or "",
            "email": rec.get("email") or "", "user": rec.get("email") or rec.get("user") or "",
            "launched_by": rec.get("email") or rec.get("user") or "", "team": True}


def prefill(meta, summary=None, reporter=""):
    s = summary or notify.run_summary(meta)
    d = report.load_defaults(meta["project"])
    t = s.get("totals") or {}
    checks = s.get("checks") or []
    failed = [c for c in checks if not c[3]]
    text = f"{meta.get('tag', '')} {meta.get('script', '')}".upper()
    env = ENV_RE.search(text)
    app = d.get("app_name") or s["label"]
    ttype = report._test_type(f"{meta.get('tag', '')} {meta.get('script', '')}")
    threads = next((m.group(1) for m in (THREADS_RE.match(p) for p in meta.get("props") or []) if m), "")

    worst = [w for w in s.get("worst") or [] if w.get("p95") is not None][:3]
    endpoint = d.get("base_url") or ""
    if worst:
        endpoint = (endpoint + " · " if endpoint else "") + ", ".join(w["name"] for w in worst)

    actual = [f"{name}: {act} (criterio {exp})" for name, exp, act, ok in failed]
    actual += [f"{name}: {act} cumple (criterio {exp})" for name, exp, act, ok in checks if ok]
    for w in worst:
        actual.append(f"{w['name']}: p95 {w['p95']:,.0f} ms · promedio {w['avg']:,.0f} ms · error {w['error_pct']} %")

    evidence = []
    for label, url in (("Reporte HTML de JMeter", s.get("report_url")), ("Dashboard de Grafana", s.get("grafana_url")),
                       ("Reporte en Confluence", s.get("confluence_url"))):
        if url and not settings.is_local_url(url):
            evidence.append(f"{label}: {url}")
    if meta.get("result_dir"):
        evidence.append(f"Resultados: {meta['result_dir']} (reporte HTML adjunto)")
    launched = meta.get("launched_by") or meta.get("email") or ""
    if launched and launched != reporter:
        evidence.append(f"Ejecución lanzada por {launched}")
    for a in s.get("newrelic") or []:
        evidence.append(f"New Relic {a['name']}: p95 {a['p95_ms']} ms · error {a['error_pct']} %"
                        + (f" · CPU {a['cpu']} %" if a.get("cpu") is not None else "") + (f" · {a['link']}" if a.get("link") else ""))

    slaves = len(meta.get("remote_hosts") or [])
    layer = report.preset_label(d)
    names = ", ".join(c[0].lower() for c in failed) or "los criterios de aceptación"
    return {
        "epica": project_epic(meta["project"]),
        "resumen": f"[Rendimiento] {app} no cumple {names} en {ttype.lower()} ({meta.get('tag')})"[:250],
        "contexto": d.get("scenario") or meta.get("notes") or "",
        "ambiente": env.group(1) if env else "",
        "aplicacion": app,
        "fecha": s.get("started") or "",
        "reportado_por": reporter or meta.get("email") or s.get("user") or "",
        "objetivo": d.get("alcance") or f"Validar que {app} cumpla los criterios de aceptación de rendimiento "
                                         f"durante una {ttype.lower()}.",
        "operaciones": f"{threads} usuarios virtuales (hilos)" if threads else "",
        "endpoint": endpoint,
        "volumen": f"{t['samples']:,} peticiones · {t.get('tps')} req/s" if t.get("samples") else "",
        "duracion": s.get("duration") or "",
        "herramienta": (d.get("tool") or "Apache JMeter") + (f" (distribuida: Master + {slaves} slave{'s' if slaves != 1 else ''})" if slaves else ""),
        "script": meta.get("script") or "",
        "esperado": [f"{name} {exp}" + (f" (capa {layer})" if layer else "") for name, exp, act, ok in checks],
        "actual": actual,
        "evidencia": evidence,
        "impacto": "",
        "cierre": [f"{name} {exp} en una nueva ejecución con la misma carga" for name, exp, act, ok in failed]
                  + ["Evidencia de la re-ejecución (reporte HTML y Grafana) adjunta al bug"],
    }


# --------------------------------------------------------------------------- charts and slowest transactions
CHARTS = {"bug_tiempo_respuesta.png": "Tiempo de respuesta (promedio y percentil 95)", "bug_errores.png": "Errores y hits por segundo"}
MAX_CHART_BYTES = 3 * 1024 * 1024


def _graph_js(project, result_dir):
    """Time series of the JMeter HTML report (html_report/content/js/graph.js): {graph: {label: [[ms, value]]}}."""
    import json
    try:
        f = projects.result_dir(project, result_dir) / "html_report" / "content" / "js" / "graph.js"
        text = f.read_text(errors="replace")
    except (projects.ProjectError, OSError):
        return {}
    dec, out = json.JSONDecoder(), {}
    for m in re.finditer(r"var\s+(\w+)Infos\s*=\s*\{\s*data\s*:\s*", text):
        try:
            obj, _ = dec.raw_decode(text, m.end())
        except ValueError:
            continue
        series = ((obj or {}).get("result") or {}).get("series") or [] if isinstance(obj, dict) else []
        graph = {}
        for sr in series:
            pts = sorted([float(p[0]), float(p[1])] for p in sr.get("data") or []
                         if isinstance(p, list) and len(p) >= 2 and p[0] is not None and p[1] is not None)
            if pts:
                graph[str(sr.get("label") or "")] = pts
        if graph:
            out[m.group(1)] = graph
    return out


def slowest(summary, n=5):
    """Top n transactions by p95 (statistics.json of the report)."""
    return [w for w in summary.get("worst") or [] if w.get("p95") is not None][:n]


def chart_series(meta, summary):
    """What the bug charts draw: {source, rt: [{label, pts, dash?, color?, fill?}], err: [...]} (empty = no data).
    Source: InfluxDB for the run window first — the same data as the run page and the Live monitor —, then the
    JMeter HTML report (content/js/graph.js) when InfluxDB is not reachable or has nothing for this run."""
    top = [w["name"] for w in slowest(summary)]
    out = {"source": "", "rt": [], "err": []}
    errors = []
    try:
        targets = report.influx.listener_targets(projects.project_dir(meta["project"]) / meta["script"]) \
            if meta.get("script") else []
        if targets and meta.get("result_dir"):
            start, end = report._window(meta["project"], meta["result_dir"], meta if meta.get("started") else None)
            t = targets[0]
            d = report.influx.dashboard(t["db"], t["application"], start, end, t.get("measurement", "jmeter"))
            if (d.get("totals") or {}).get("req"):
                out["rt"] = [{"label": "Promedio", "pts": d["avg"], "color": "#1868db"},
                             {"label": "Percentil 95", "pts": d["p95"], "dash": True, "color": "#c9372c"}]
                out["err"] = [{"label": "Errores por segundo", "pts": d["eps"], "color": "#c9372c", "fill": True},
                              {"label": "Hits por segundo", "pts": d["hps"], "color": "#1f845a"}]
                out["source"] = "InfluxDB (las mismas gráficas de la ejecución)"
            else:
                errors.append("InfluxDB has no samples for this execution window")
        elif not targets:
            errors.append("the script has no InfluxDB Backend Listener")
    except Exception as exc:  # noqa: BLE001 - fall back to the HTML report
        errors.append(f"InfluxDB: {exc}")
    g = {} if out["source"] or not meta.get("result_dir") else _graph_js(meta["project"], meta["result_dir"])
    if g:
        rt = g.get("responseTimesOverTime") or {}
        out["rt"] = [{"label": f"{n} (promedio)", "pts": rt[n]} for n in top if n in rt]
        pct = g.get("responseTimePercentilesOverTime") or {}
        p95 = next((v for k, v in pct.items() if "95" in k), None)
        if p95:
            out["rt"].append({"label": "Percentil 95 (general)", "pts": p95, "dash": True, "color": "#c9372c"})
        tps = g.get("totalTPS") or {}
        fail = next((v for k, v in tps.items() if k.lower().endswith("failure")), None)
        if fail:
            out["err"].append({"label": "Errores por segundo", "pts": fail, "color": "#c9372c", "fill": True})
        for code, pts in (g.get("codesPerSecond") or {}).items():
            if not code[:1] in ("2", "3"):
                out["err"].append({"label": f"Código {code}", "pts": pts})
        if out["rt"] or out["err"]:
            out["source"] = "Reporte HTML de JMeter (InfluxDB no disponible)"
    if not out["source"] and errors:
        out["error"] = "; ".join(errors)
    # Keep the points of this execution only: a report can carry samples far from the run (a reused .jtl,
    # clock skew between generators), which stretches the time axis until the lines are invisible.
    try:
        start, end = report._window(meta["project"], meta["result_dir"], meta if meta.get("started") else None) \
            if meta.get("result_dir") else (None, None)
    except (projects.ProjectError, OSError, ValueError):
        start, end = None, None
    if start and end:
        lo, hi = start - 120000, end + 120000
        for key in ("rt", "err"):
            clipped = [dict(x, pts=[p for p in x["pts"] if lo <= p[0] <= hi]) for x in out[key]]
            if any(len(x["pts"]) for x in clipped):   # all outside = clocks/zones differ: keep the report's own axis
                out[key] = clipped
                out["window"] = [lo, hi]
    out["rt"] = [x for x in out["rt"] if x["pts"]]
    out["err"] = [x for x in out["err"] if x["pts"]]
    xs = [pt[0] for x in out["rt"] + out["err"] for pt in x["pts"]]
    if xs and "window" in out:   # axis from the first to the last sample of the run (no empty margins)
        out["window"] = [min(xs), max(xs)] if max(xs) > min(xs) else [min(xs) - 60000, max(xs) + 60000]
    out["points"] = max([len(x["pts"]) for x in out["rt"] + out["err"]] or [0])
    return out


def charts_from_form(form):
    """PNG charts rendered by the bug form ({filename: bytes}); anything that is not a small PNG is ignored."""
    import base64
    import binascii
    out = {}
    for name in CHARTS:
        raw = form.get("img_" + name.split(".")[0], "")
        if not raw.startswith("data:image/png;base64,"):
            continue
        try:
            data = base64.b64decode(raw.split(",", 1)[1], validate=True)
        except (binascii.Error, ValueError):
            continue
        if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) <= MAX_CHART_BYTES:
            out[name] = data
    return out


def from_form(form):
    out = {}
    for key, _, kind in FIELDS:
        raw = (form.get(key) or "").strip()
        out[key] = [x.strip(" -•*\t") for x in raw.splitlines() if x.strip(" -•*\t")] if kind == "list" else raw
    out["epica"] = out["epica"].upper().replace(" ", "")
    return out


def _w(text):
    """Escape characters that Jira wiki markup would turn into macros or formatting inside plain text."""
    return (text or "").replace("{", "\\{").replace("}", "\\}").replace("[", "\\[").replace("]", "\\]")


def _cell(text):
    return _w(text).replace("|", "/").replace("\r", " ").replace("\n", " ").strip() or " "


def _items(values, box=False):
    return "\n".join(f"* {'☐ ' if box else ''}{_w(v)}" for v in values) if values else "* —"


def _ms(v):
    return f"{v:,.0f}" if isinstance(v, (int, float)) else "—"


def render_wiki(f, slow=(), charts=()):
    rows = [("Tipo", "Bug no funcional - Rendimiento"), ("Épica padre", f.get("epica", "")), ("Resumen", f["resumen"]), ("Ambiente", f["ambiente"]),
            ("Aplicación", f["aplicacion"]), ("Fecha de ejecución", f["fecha"]), ("Reportado por", f["reportado_por"])]
    scen = [("Operaciones simultáneas", f["operaciones"]), ("Endpoint / servicio evaluado", f["endpoint"]),
            ("Volumen de datos", f["volumen"]), ("Duración de la prueba", f["duracion"]),
            ("Herramienta utilizada", f["herramienta"]), ("Script utilizado", f["script"])]
    out = ["h1. Reporte de bug no funcional - Prueba de rendimiento", "",
           f"*Contexto:* {_w(f['contexto']) or '—'}", "",
           "||Campo||Detalle||", *[f"|{k}|{_cell(v)}|" for k, v in rows], "",
           "h2. Objetivo de la prueba", _w(f["objetivo"]) or "—", "",
           "h2. Escenario de escalabilidad", "||Parámetro||Valor esperado / observado||",
           *[f"|{k}|{_cell(v)}|" for k, v in scen], "",
           "h2. Resultado esperado", _items(f["esperado"]), "",
           "h2. Resultado actual", _items(f["actual"]), ""]
    if slow:
        out += ["h3. Transacciones más lentas (top 5 por percentil 95)",
                "||Transacción||Peticiones||Error %||Promedio (ms)||p95 (ms)||p99 (ms)||Máximo (ms)||",
                *[f"|{_cell(w['name'])}|{w.get('samples') or 0:,}|{w.get('error_pct', 0)} %|{_ms(w.get('avg'))}|"
                  f"{_ms(w.get('p95'))}|{_ms(w.get('p99'))}|{_ms(w.get('max'))}|" for w in slow], ""]
    if charts:
        out += ["h3. Gráficas de la ejecución"]
        for name in charts:
            out += [f"*{CHARTS.get(name, name)}*", f"!{name}|width=900!", ""]
    out += ["h2. Evidencia", _items(f["evidencia"]), "",
           "h2. Impacto", _w(f["impacto"]) or "—", "",
           "h2. Criterios de aceptación para cierre", _items(f["cierre"], box=True)]
    return "\n".join(out)


def create(username, meta, fields, attach_report=True, by="", charts=None, slow=()):
    """Create the issue in the project's board; returns {key, url, attached, charts}.
    `charts` ({filename: png bytes}) are attached and shown in the description; `slow` is the top 5 table."""
    missing = [label for key, label, _ in FIELDS if key in REQUIRED and not fields.get(key)]
    if missing:
        raise atlassian.AtlassianError(f"Complete: {', '.join(missing)}")
    key, itype, labels = target(meta["project"])
    if not key:
        raise atlassian.AtlassianError("No Jira project for bugs: set it in Settings → Jira (or the project's settings)")
    jira = atlassian.Jira(username)
    charts = charts or {}
    epic = jira.epic(fields["epica"])          # must exist and be an epic, before anything is created
    issue = jira.create_issue(key, itype, fields["resumen"], render_wiki(fields, slow, list(charts)), labels,
                              epic=epic["key"])
    issue["epic"] = epic
    if epic["key"] != project_epic(meta["project"]):   # next bug of this project starts with the same epic
        try:
            ps = settings.project(meta["project"])
            ps["jira_epic"] = epic["key"]
            settings.save_project(meta["project"], ps)
            issue["epic_saved"] = True
        except (ValueError, OSError):
            pass
    issue["attached"], issue["charts"] = "", []
    for name, data in charts.items():    # the description shows them once attached (!name!)
        try:
            jira.attach(issue["key"], name, data, "image/png")
            issue["charts"].append(name)
        except atlassian.AtlassianError as exc:
            issue["attach_error"] = str(exc)
    if attach_report and meta.get("result_dir"):
        att = _report_zip(meta["project"], meta["result_dir"])
        if att:
            try:
                jira.attach(issue["key"], *att)
                issue["attached"] = att[0]
            except atlassian.AtlassianError as exc:
                issue["attach_error"] = str(exc)
    link = {"key": issue["key"], "url": issue["url"]}
    if runner.get(meta["id"]) if re.match(r"^[0-9a-f]{12}$", meta.get("id") or "") else None:
        runner.update(meta["id"], jira_bug=link)
    if meta.get("result_dir"):
        data = filed(meta["project"])
        data[meta["result_dir"]] = dict(link, by=by or username, ts=time.time())
        save_filed(meta["project"], data)
    return issue


def _report_zip(project, result_dir, max_mb=20):
    import io
    import zipfile
    try:
        d = projects.result_dir(project, result_dir) / "html_report"
    except projects.ProjectError:
        return None
    if not d.is_dir():
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in d.rglob("*"):
            if f.is_file():
                zf.write(f, f"html_report/{f.relative_to(d).as_posix()}")
    data = buf.getvalue()
    return (f"{result_dir}_html_report.zip", data) if len(data) <= max_mb * 1024 * 1024 else None
