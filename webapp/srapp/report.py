"""Builds the "Plantilla Reporte de Resultados" for one execution and publishes it to Confluence.

Data sources for a result folder results/Ejecucion_<DDMMYY_HHMMSS>_<SCRIPT>/:
  * html_report/statistics.json  -> Resultados Generales + per-transaction table
  * InfluxDB (Backend Listener)  -> active users, throughput, errors, response codes, charts
  * web-app run metadata         -> tag, user, -J overrides, console log, exact time window
"""
import base64
import binascii
import io
import json
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path

from markupsafe import Markup, escape

from . import confluence, influx, projects, runner
from .config import Config, _env

IMAGE_NAMES = {
    "usuarios_activos": "Usuarios activos",
    "throughput": "Throughput (hits/s)",
    "errores": "Errores por segundo",
    "codigos_respuesta": "Distribución de códigos de error",
    "tiempos_respuesta": "Tiempo de respuesta promedio y p95",
    "p95_transacciones": "Percentil 95 por transacción",
}
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_ATTACH_MB = int(_env("SR_CONFLUENCE_MAX_ATTACH_MB", "80"))
GRAFANA_DASHBOARD = _env("SR_GRAFANA_DASHBOARD_PATH", "")  # e.g. /d/jmeter/jmeter?var-application={app}
DEFAULT_KEYS = ("app_name", "scenario", "tool", "base_url", "alcance", "crit_avg", "crit_p95", "crit_err",
                "crit_tps", "stakeholders", "link_docs", "link_docs_desc", "space_key", "parent_id")
TEST_TYPES = [("SMOKE", "Prueba de Humo"), ("UNIT", "Prueba Unitaria"), ("DRY", "Prueba Dry Run"),
              ("SCALAB", "Prueba de Escalabilidad"), ("ESCALAB", "Prueba de Escalabilidad"),
              ("STRESS", "Prueba de Estrés"), ("ESTRES", "Prueba de Estrés"), ("SPIKE", "Prueba de Picos"),
              ("VOLUM", "Prueba de Volumen"), ("BASELINE", "Prueba de Línea Base"), ("SOAK", "Prueba de Resistencia"),
              ("LOAD", "Prueba de Carga"), ("CARGA", "Prueba de Carga")]


class ReportError(ValueError):
    pass


# --------------------------------------------------------------------------- formatting helpers
def paras(text):
    """Plain text -> XHTML paragraphs/lists (escaped). Blank line = new paragraph, '- ' = bullet."""
    out = []
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        lines = [l.rstrip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        if all(l.lstrip().startswith(("- ", "* ", "• ")) for l in lines):
            out.append("<ul>" + "".join(f"<li>{escape(l.lstrip()[2:].strip())}</li>" for l in lines) + "</ul>")
        else:
            out.append("<p>" + "<br/>".join(str(escape(l)) for l in lines) + "</p>")
    return Markup("".join(out))


def rows(text, cols):
    """'a | b | c' lines -> list of padded rows."""
    out = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        cells = [c.strip() for c in line.split("|")]
        out.append((cells + [""] * cols)[:cols])
    return out


def _fmt_ms(v):
    return "—" if v is None else f"{v:,.0f} ms"


def _num(v, d=0):
    if v is None:
        return "—"
    return f"{v:,.{d}f}"


# --------------------------------------------------------------------------- persistence
def _defaults_path(project):
    d = Config.INSTANCE_DIR / "report_defaults"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{project}.json"


def load_defaults(project):
    p = _defaults_path(project)
    return json.loads(p.read_text()) if p.exists() else {}


def save_defaults(project, fields):
    data = {k: fields.get(k, "") for k in DEFAULT_KEYS}
    _defaults_path(project).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _history_path(project):
    d = Config.INSTANCE_DIR / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{project}.json"


def history(project):
    p = _history_path(project)
    return json.loads(p.read_text()) if p.exists() else {}


def _record(project, run_name, entry):
    h = history(project)
    h[run_name] = entry
    _history_path(project).write_text(json.dumps(h, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- data gathering
def _run_meta(project, run_name):
    for m in runner.list_runs(project=project, limit=500):
        if m.get("result_dir") == run_name:
            return m
    return None


def _script_name(run_name):
    m = re.match(r"^Ejecucion_\d{6}_\d{6}_(.+)$", run_name)
    return m.group(1) if m else ""


def _find_script(project, run_name, meta):
    base = projects.project_dir(project)
    if meta and meta.get("script") and (base / meta["script"]).is_file():
        return meta["script"]
    name = _script_name(run_name) + ".jmx"
    for f in (base / "tests").rglob(name):
        return str(f.relative_to(base))
    return None


def _window(project, run_name, meta):
    if meta and meta.get("started"):
        return int(meta["started"] * 1000) - 5000, int((meta.get("ended") or time.time()) * 1000) + 15000
    m = re.match(r"^Ejecucion_(\d{6})_(\d{6})_", run_name)
    start = int(datetime.strptime(m.group(1) + m.group(2), "%d%m%y%H%M%S").timestamp() * 1000) if m else None
    d = projects.result_dir(project, run_name)
    stats = d / "html_report" / "statistics.json"
    end = int((stats.stat().st_mtime if stats.exists() else d.stat().st_mtime) * 1000) + 15000
    return start or end - 3600 * 1000, end


def _exec_number(project, run_name):
    script = _script_name(run_name)
    same = sorted((r for r in projects.list_results(project) if _script_name(r["name"]) == script),
                  key=lambda r: r["mtime"])
    for i, r in enumerate(same, 1):
        if r["name"] == run_name:
            return i
    return len(same) or 1


def _test_type(text):
    up = (text or "").upper()
    for key, label in TEST_TYPES:
        if key in up:
            return label
    return "Prueba de Performance"


def _raw_stats(project, run_name):
    f = projects.result_dir(project, run_name) / "html_report" / "statistics.json"
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return {}


def _totals(raw):
    t = raw.get("Total") or {}
    samples, tps = t.get("sampleCount") or 0, t.get("throughput") or 0
    duration = samples / tps if tps else None
    kb = lambda key: (t.get(key) or 0) * duration / 1024 if duration else None  # noqa: E731
    return {
        "samples": samples, "errors": t.get("errorCount") or 0, "error_pct": round(t.get("errorPct") or 0, 2),
        "success_pct": round(100 - (t.get("errorPct") or 0), 2), "avg": t.get("meanResTime"),
        "median": t.get("medianResTime"), "min": t.get("minResTime"), "max": t.get("maxResTime"),
        "p90": t.get("pct1ResTime"), "p95": t.get("pct2ResTime"), "p99": t.get("pct3ResTime"),
        "tps": round(tps, 2), "duration_s": round(duration) if duration else None,
        "sent_mb": kb("sentKBytesPerSec"), "recv_mb": kb("receivedKBytesPerSec"),
    }


def _transactions(raw):
    out = []
    for name, s in sorted(raw.items()):
        if name == "Total":
            continue
        out.append({"name": name, "samples": s.get("sampleCount") or 0, "errors": s.get("errorCount") or 0,
                    "error_pct": round(s.get("errorPct") or 0, 2), "avg": s.get("meanResTime"),
                    "p90": s.get("pct1ResTime"), "p95": s.get("pct2ResTime"), "p99": s.get("pct3ResTime"),
                    "max": s.get("maxResTime"), "tps": round(s.get("throughput") or 0, 2)})
    return out


def _duration_txt(secs):
    if not secs:
        return ""
    h, m, s = secs // 3600, secs % 3600 // 60, secs % 60
    return (f"{h} h " if h else "") + (f"{m} min " if m else "") + (f"{s} s" if s and not h else "")


def evaluate(fields, totals):
    """Returns (status, list of (criterion, expected, actual, ok)). Empty criteria are ignored."""
    checks = []

    def crit(name, key, actual, cmp, unit):
        raw = str(fields.get(key, "")).strip()
        if not raw or actual is None:
            return
        try:
            limit = float(raw)
        except ValueError:
            return
        ok = actual <= limit if cmp == "<=" else actual >= limit
        checks.append((name, f"{cmp} {limit:g} {unit}", f"{actual:,.2f} {unit}", ok))

    crit("Tiempo de respuesta promedio", "crit_avg", totals.get("avg"), "<=", "ms")
    crit("Percentil 95", "crit_p95", totals.get("p95"), "<=", "ms")
    crit("Tasa de error", "crit_err", totals.get("error_pct"), "<=", "%")
    crit("Throughput", "crit_tps", totals.get("tps"), ">=", "req/s")
    if not checks:
        return "", checks
    return ("SATISFACTORIA" if all(c[3] for c in checks) else "INSATISFACTORIA"), checks


def gather(project, run_name):
    """Everything known about one execution (no user input yet)."""
    projects.result_dir(project, run_name)
    meta = _run_meta(project, run_name)
    script = _find_script(project, run_name, meta)
    raw = _raw_stats(project, run_name)
    if not raw:
        raise ReportError("This execution has no html_report/statistics.json (did JMeter finish?)")
    start, end = _window(project, run_name, meta)
    targets = influx.listener_targets(projects.project_dir(project) / script) if script else []
    targets = [t for t in targets if influx.NAME_RE.match(t["db"] or "") and influx.NAME_RE.match(t["application"] or "")]
    live, live_error = None, None
    if targets:
        try:
            live = influx.dashboard(targets[0]["db"], targets[0]["application"], start, end, targets[0]["measurement"])
            if not live["totals"].get("req"):
                live_error = "InfluxDB has no samples for this execution window."
        except influx.InfluxError as exc:
            live_error = str(exc)
    else:
        live_error = "The script has no enabled InfluxDB Backend Listener."
    peak_users = max((v for _, v in live["vusers"]), default=None) if live else None
    if not peak_users and meta:
        for p in meta.get("props", []):
            m = re.match(r"^-[JG]threads=(\d+)$", p)
            if m:
                peak_users = int(m.group(1)) * max(1, len(meta.get("remote_hosts") or []))
    return {"meta": meta, "script": script, "totals": _totals(raw), "transactions": _transactions(raw),
            "start": start, "end": end, "targets": targets, "live": live, "live_error": live_error,
            "peak_users": peak_users, "exec_no": _exec_number(project, run_name)}


# --------------------------------------------------------------------------- drafts
def drafts(project, run_name, g, fields):
    """Pre-filled narrative for every section, in Spanish, from the measured values."""
    t, live = g["totals"], g["live"]
    app_name, scenario = fields["app_name"], fields["scenario"] or fields["test_name"]
    users = fields["users"] or "N"
    dur = _duration_txt(t["duration_s"]) or "{duración}"
    status, checks = evaluate(fields, t)
    cumple = {"SATISFACTORIA": "cumplió", "INSATISFACTORIA": "no cumplió"}.get(status, "{cumplió / no cumplió}")
    apta = {"SATISFACTORIA": "apta", "INSATISFACTORIA": "no apta"}.get(status, "{apta / no apta}")
    crit_txt = ", ".join(f"{c[0].lower()} {c[1]}" for c in checks) or "{criterios de aceptación}"
    out = {"draft_status": status or "SIN CRITERIOS"}
    out["objetivo"] = (
        f"El objetivo de esta prueba de performance es evaluar el comportamiento de {app_name} bajo el escenario "
        f"{scenario}, con una carga de {users} usuarios virtuales durante {dur}, con el fin de validar su estabilidad, "
        f"capacidad de respuesta, throughput y uso de recursos frente a los criterios de aceptación definidos: {crit_txt}.")
    out["resumen"] = (
        f"Durante la ejecución de la prueba de performance para {app_name}, bajo el escenario {scenario} y con una carga "
        f"de {users} usuarios virtuales, se observó que la aplicación {cumple} con los criterios de aceptación definidos."
        f"\n\nLos resultados principales fueron: tiempo de respuesta promedio de {_fmt_ms(t['avg'])}, percentil 95 de "
        f"{_fmt_ms(t['p95'])}, throughput de {_num(t['tps'], 2)} req/s y tasa de error de {t['error_pct']} % "
        f"({_num(t['errors'])} de {_num(t['samples'])} peticiones)."
        f"\n\nComo conclusión, {app_name} se considera {apta} para soportar la carga evaluada. "
        f"Se recomienda {{recomendación principal}} antes de avanzar a {{siguiente ambiente / liberación}}.")
    if live and live["vusers"]:
        vu = live["vusers"]
        peak = max(v for _, v in vu)
        t_peak = next(ts for ts, v in vu if v == peak)
        ramp_s = round((t_peak - vu[0][0]) / 1000)
        out["users_desc"] = (
            f"La carga alcanzó un pico de {peak:,.0f} usuarios virtuales concurrentes, {ramp_s} s después del inicio "
            f"(ramp-up). Duración total de la ejecución: {dur}.")
    else:
        out["users_desc"] = f"Usuarios virtuales configurados: {users}. Duración total de la ejecución: {dur}."
    peak_hps = max((v for _, v in live["hps"]), default=None) if live else None
    out["throughput_desc"] = (
        f"El sistema procesó {_num(t['samples'])} peticiones con un throughput promedio de {_num(t['tps'], 2)} req/s"
        + (f" y un máximo de {peak_hps:,.1f} hits/s." if peak_hps else ".")
        + " {Indicar si el throughput se mantuvo estable conforme aumentó la carga.}")
    err_lines = [f"Tasa de error global: {t['error_pct']} % ({_num(t['errors'])} peticiones fallidas)."]
    if live and live["codes"]:
        codes = [c for c in live["codes"] if not c["code"].startswith("OK")]
        if codes:
            err_lines.append("Códigos de error: " + ", ".join(f"{c['code']} ({c['count']:,})" for c in codes[:6]) + ".")
    bad_tx = sorted((x for x in g["transactions"] if x["errors"]), key=lambda x: -x["error_pct"])[:5]
    if bad_tx:
        err_lines.append("Transacciones más afectadas: " + ", ".join(f"{x['name']} ({x['error_pct']} %)" for x in bad_tx) + ".")
    out["errors_desc"] = "\n".join(err_lines)
    out["rt_desc"] = (
        f"Tiempo de respuesta promedio {_fmt_ms(t['avg'])}, mínimo {_fmt_ms(t['min'])}, máximo {_fmt_ms(t['max'])}; "
        f"percentiles p90 {_fmt_ms(t['p90'])}, p95 {_fmt_ms(t['p95'])} y p99 {_fmt_ms(t['p99'])}.")
    slow = sorted(g["transactions"], key=lambda x: -(x["p95"] or 0))[:3]
    if slow:
        out["rt_desc"] += "\nTransacciones con mayor p95: " + ", ".join(f"{x['name']} ({_fmt_ms(x['p95'])})" for x in slow) + "."
    out["resources_desc"] = ("{Describir CPU, memoria, red y base de datos de los servidores durante la prueba "
                             "(ver dashboard de monitoreo).}")
    obs = []
    try:
        lim_p95 = float(fields.get("crit_p95") or 0)
    except ValueError:
        lim_p95 = 0
    for x in g["transactions"]:
        if x["error_pct"] > 1:
            obs.append(f"- {x['name']}: tasa de error de {x['error_pct']} %.")
        if lim_p95 and (x["p95"] or 0) > lim_p95:
            obs.append(f"- {x['name']}: p95 de {_fmt_ms(x['p95'])}, por encima del criterio ({lim_p95:g} ms).")
    out["observaciones"] = "\n".join(obs) or "- Sin desviaciones relevantes frente a los criterios de aceptación."
    out["recomendaciones"] = (
        "- Analizar las transacciones con mayor tasa de error y p95 junto con el equipo de desarrollo.\n"
        "- Correlacionar los picos de latencia con el consumo de recursos del servidor.\n"
        "- Ejecutar una nueva corrida para confirmar las mejoras aplicadas."
        if status == "INSATISFACTORIA" or obs else
        "- Mantener esta ejecución como línea base para futuras comparaciones.\n"
        "- {Siguiente paso: incrementar carga / prueba de resistencia / liberación}.")
    return out


def initial_fields(project, run_name, g, user_settings):
    d = load_defaults(project)
    meta = g["meta"] or {}
    label = project[: -len(Config.PROJECT_SUFFIX)] if project.endswith(Config.PROJECT_SUFFIX) else project
    script_name = Path(g["script"]).name if g["script"] else _script_name(run_name) + ".jmx"
    test_name = _test_type((meta.get("tag") or "") + " " + script_name)
    run_dt = datetime.fromtimestamp(g["start"] / 1000)
    f = {
        "test_name": test_name, "app_name": d.get("app_name") or label.upper(), "exec_no": str(g["exec_no"]),
        "test_date": run_dt.strftime("%d/%m/%Y %H:%M"), "users": str(g["peak_users"] or ""),
        "tool": d.get("tool") or "Apache JMeter 5.6.3" + (" (distribuido: 1 Master + "
                                                          f"{len(meta['remote_hosts'])} Slaves)" if meta.get("remote_hosts") else ""),
        "scenario": d.get("scenario") or (meta.get("tag") or ""), "script": script_name,
        "execution": run_name, "status": "auto",
        "crit_avg": d.get("crit_avg", ""), "crit_p95": d.get("crit_p95", ""),
        "crit_err": d.get("crit_err", "1"), "crit_tps": d.get("crit_tps", ""),
        "base_url": d.get("base_url", ""),
        "alcance": d.get("alcance") or "\n".join(f"API | {x['name']} | {{GET / POST}} | {{Descripción}} | Media"
                                                 for x in g["transactions"]),
        "stakeholders": d.get("stakeholders") or "Performance QA | {Nombre} | QA | Diseño, ejecución y análisis | {correo}",
        "link_dashboard": grafana_link(g), "link_dashboard_desc": "Dashboard JMeter en Grafana para la ventana de ejecución",
        "link_docs": d.get("link_docs", ""), "link_docs_desc": d.get("link_docs_desc", ""),
        "attach_report": "1", "attach_jmx": "1", "attach_log": "1" if g["meta"] else "", "attach_jtl": "",
        "space_key": d.get("space_key") or (user_settings or {}).get("space_key", ""),
        "parent_id": d.get("parent_id") or (user_settings or {}).get("parent_id", ""),
    }
    f["title"] = f"{f['test_name']}: {f['app_name']} - Ejecución {f['exec_no']} ({run_dt.strftime('%d/%m/%Y %H:%M')})"
    f.update(drafts(project, run_name, g, f))
    return f


def grafana_link(g):
    if not influx.GRAFANA_URL:
        return ""
    app = g["targets"][0]["application"] if g["targets"] else ""
    path = GRAFANA_DASHBOARD.replace("{app}", app) if GRAFANA_DASHBOARD else ""
    sep = "&" if "?" in path else "?"
    return f"{influx.GRAFANA_URL.rstrip('/')}{path}{sep}from={g['start']}&to={g['end']}"


# --------------------------------------------------------------------------- rendering
def decode_images(form):
    images = {}
    for key in IMAGE_NAMES:
        raw = form.get(f"img_{key}", "")
        if not raw:
            continue
        if not raw.startswith("data:image/png;base64,"):
            raise ReportError(f"Invalid image {key}")
        try:
            data = base64.b64decode(raw.split(",", 1)[1], validate=True)
        except (binascii.Error, ValueError):
            raise ReportError(f"Invalid image {key}")
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > MAX_IMAGE_BYTES:
            raise ReportError(f"Invalid image {key}")
        images[key] = data
    return images


def build_attachments(project, run_name, g, fields):
    files = []
    d = projects.result_dir(project, run_name)
    if fields.get("attach_report") and (d / "html_report").is_dir():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in (d / "html_report").rglob("*"):
                if f.is_file():
                    zf.write(f, f"html_report/{f.relative_to(d / 'html_report')}")
        files.append(("📊 Reporte JMeter", "Dashboard HTML de JMeter (descomprimir y abrir index.html)",
                      f"{run_name}_html_report.zip", buf.getvalue(), "application/zip"))
    if fields.get("attach_jmx") and g["script"]:
        p = projects.safe_path(project, g["script"])
        files.append(("🧪 Script de prueba", "Script JMeter ejecutado", p.name, p.read_bytes(), "application/xml"))
    if fields.get("attach_log") and g["meta"]:
        text, _ = runner.read_log(g["meta"]["id"], 0, 20 * 1024 * 1024)
        files.append(("📈 Logs", "Consola de ejecución (run_by_tag.sh / JMeter)", f"{run_name}_console.log",
                      text.encode(), "text/plain"))
    if fields.get("attach_jtl"):
        for jtl in d.glob("*.jtl"):
            if jtl.stat().st_size > MAX_ATTACH_MB * 1024 * 1024:
                raise ReportError(f"{jtl.name} is larger than {MAX_ATTACH_MB} MB, untick the JTL attachment")
            files.append(("📊 Reporte JMeter", "Resultados crudos (.jtl)", jtl.name, jtl.read_bytes(), "text/csv"))
    total = sum(len(f[3]) for f in files)
    if total > MAX_ATTACH_MB * 1024 * 1024:
        raise ReportError(f"Attachments exceed {MAX_ATTACH_MB} MB")
    return files


def context(project, run_name, g, fields, images, attachments, preview):
    status = fields.get("status")
    auto_status, checks = evaluate(fields, g["totals"])
    if status not in ("SATISFACTORIA", "INSATISFACTORIA"):
        status = auto_status or "SIN EVALUAR"
    codes = [c for c in (g["live"] or {}).get("codes", []) if not c["code"].startswith("OK")]
    return {
        "f": fields, "t": g["totals"], "tx": g["transactions"], "codes": codes, "checks": checks,
        "status": status, "images": images, "image_names": IMAGE_NAMES, "attachments": attachments,
        "alcance": rows(fields.get("alcance"), 5), "stakeholders": rows(fields.get("stakeholders"), 5),
        "preview": preview, "b64": lambda b: base64.b64encode(b).decode(), "paras": paras,
        "num": _num, "ms": _fmt_ms, "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }


# --------------------------------------------------------------------------- publish
def publish(project, run_name, username, g, fields, images, storage, attachments):
    client = confluence.Client.for_user(username)
    space = (fields.get("space_key") or "").strip()
    if not confluence.SPACE_RE.match(space):
        raise ReportError("Space key is required")
    parent = (fields.get("parent_id") or "").strip()
    if parent and not parent.isdigit():
        raise ReportError("Parent page id must be numeric")
    title = (fields.get("title") or "").strip()[:255]
    if not title:
        raise ReportError("Title is required")

    previous = history(project).get(run_name)
    page = None
    if previous and fields.get("page_mode") != "new":
        try:
            page = client.update_page(previous["page_id"], title, storage)
        except confluence.ConfluenceError as exc:
            if "404" not in str(exc):
                raise
    if page is None:
        existing = client.find_page(space, title)
        page = client.update_page(existing["id"], title, storage) if existing else \
            client.create_page(space, title, storage, parent or None)
    page_id = page["id"]
    for key, data in images.items():
        client.put_attachment(page_id, f"{key}.png", data, "image/png")
    for _, _, name, data, ctype in attachments:
        client.put_attachment(page_id, name, data, ctype)
    url = client.page_url(page)
    _record(project, run_name, {"page_id": page_id, "url": url, "title": title, "user": username,
                                "ts": time.time(), "space": space, "version": page.get("version", {}).get("number")})
    save_defaults(project, fields)
    return url
