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
    ("resumen", "Resumen", "line"), ("contexto", "Contexto", "text"), ("ambiente", "Ambiente", "line"),
    ("aplicacion", "Aplicación", "line"), ("fecha", "Fecha de ejecución", "line"),
    ("reportado_por", "Reportado por", "line"), ("objetivo", "Objetivo de la prueba", "text"),
    ("operaciones", "Operaciones simultáneas", "line"), ("endpoint", "Endpoint / servicio evaluado", "line"),
    ("volumen", "Volumen de datos", "line"), ("duracion", "Duración de la prueba", "line"),
    ("herramienta", "Herramienta utilizada", "line"), ("script", "Script utilizado", "line"),
    ("esperado", "Resultado esperado", "list"), ("actual", "Resultado actual", "list"),
    ("evidencia", "Evidencia", "list"), ("impacto", "Impacto", "text"), ("cierre", "Criterios de aceptación para cierre", "list"),
]
REQUIRED = ("resumen", "impacto")
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


def from_form(form):
    out = {}
    for key, _, kind in FIELDS:
        raw = (form.get(key) or "").strip()
        out[key] = [x.strip(" -•*\t") for x in raw.splitlines() if x.strip(" -•*\t")] if kind == "list" else raw
    return out


def _w(text):
    """Escape characters that Jira wiki markup would turn into macros or formatting inside plain text."""
    return (text or "").replace("{", "\\{").replace("}", "\\}").replace("[", "\\[").replace("]", "\\]")


def _cell(text):
    return _w(text).replace("|", "/").replace("\r", " ").replace("\n", " ").strip() or " "


def _items(values, box=False):
    return "\n".join(f"* {'☐ ' if box else ''}{_w(v)}" for v in values) if values else "* —"


def render_wiki(f):
    rows = [("Tipo", "Bug no funcional - Rendimiento"), ("Resumen", f["resumen"]), ("Ambiente", f["ambiente"]),
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
           "h2. Resultado actual", _items(f["actual"]), "",
           "h2. Evidencia", _items(f["evidencia"]), "",
           "h2. Impacto", _w(f["impacto"]) or "—", "",
           "h2. Criterios de aceptación para cierre", _items(f["cierre"], box=True)]
    return "\n".join(out)


def create(username, meta, fields, attach_report=True, by=""):
    """Create the issue in the project's board; returns {key, url, attached}."""
    missing = [label for key, label, _ in FIELDS if key in REQUIRED and not fields.get(key)]
    if missing:
        raise atlassian.AtlassianError(f"Complete: {', '.join(missing)}")
    key, itype, labels = target(meta["project"])
    if not key:
        raise atlassian.AtlassianError("No Jira project for bugs: set it in Settings → Jira (or the project's settings)")
    jira = atlassian.Jira(username)
    issue = jira.create_issue(key, itype, fields["resumen"], render_wiki(fields), labels)
    issue["attached"] = ""
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
