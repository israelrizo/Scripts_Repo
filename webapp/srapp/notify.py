"""E-mail quick report + run notifications (start / end) and Jira comments.

Recipients of every notification: settings.smtp.always_to (qaperformance@bancobase.com)
+ the project's staff e-mails (project settings) + extra addresses typed in the run dialog.
"""
import smtplib
import ssl
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from flask import render_template

from . import atlassian, projects, runner, settings
from . import report as rpt

ME = "JMeter Control Center"


# --------------------------------------------------------------------------- data
def _fmt_dt(ts):
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S") if ts else "—"


def _duration(meta):
    if not meta.get("started"):
        return "—"
    s = int((meta.get("ended") or time.time()) - meta["started"])
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def run_summary(meta):
    """Everything the quick report needs about one run (works for running and finished runs)."""
    cfg = settings.get()
    base_url = cfg["app"]["public_url"].rstrip("/")
    project = meta["project"]
    out = {
        "project": project, "label": project.replace("-jmeter-framework", "").upper(), "tag": meta.get("tag"),
        "script": meta.get("script", ""), "status": meta.get("status"), "user": meta.get("user"),
        "started": _fmt_dt(meta.get("started")), "ended": _fmt_dt(meta.get("ended")), "duration": _duration(meta),
        "props": " ".join(meta.get("props") or []), "slaves": meta.get("remote_hosts") or [],
        "jira": meta.get("jira") or "", "notes": meta.get("notes") or "",
        "run_url": f"{base_url}/runs/{meta['id']}", "totals": None, "worst": [], "checks": [], "verdict": "",
        "report_url": "", "grafana_url": "", "confluence_url": "", "jira_url": "", "result_dir": meta.get("result_dir"),
    }
    try:
        targets = rpt.influx.listener_targets(projects.project_dir(project) / meta["script"]) if meta.get("script") else []
    except projects.ProjectError:
        targets = []
    app = targets[0]["application"] if targets else None
    start_ms = int(meta["started"] * 1000) - 5000 if meta.get("started") else None
    end_ms = int(meta["ended"] * 1000) + 15000 if meta.get("ended") else None
    out["grafana_url"] = settings.grafana_link(project, app, start_ms, end_ms)
    rd = meta.get("result_dir")
    if rd:
        out["report_url"] = f"{base_url}/p/{project}/results/{rd}/report/"
        raw = rpt._raw_stats(project, rd) if _safe_result(project, rd) else {}
        if raw:
            t = rpt._totals(raw)
            out["totals"] = t
            out["worst"] = sorted(rpt._transactions(raw), key=lambda x: -(x["p95"] or 0))[:5]
            verdict, checks = rpt.evaluate(rpt.load_defaults(project), t)
            out["verdict"], out["checks"] = verdict, checks
        pub = rpt.history(project).get(rd)
        if pub:
            out["confluence_url"] = pub["url"]
    if out["jira"]:
        jira_base = settings.get()["jira"].get("url") or ""
        out["jira_url"] = f"{jira_base.rstrip('/')}/browse/{out['jira']}" if jira_base else ""
    return out


def _safe_result(project, rd):
    try:
        projects.result_dir(project, rd)
        return True
    except projects.ProjectError:
        return False


MOCK = {
    "project": "baseinet-jmeter-framework", "label": "BASEINET", "tag": "opt5_MetodosGenerales_QA1",
    "script": "tests/Optimizaciones/Paquete_5/SCRIPT09_OPT_P5_QA_BASEINET_METODOS_GENERALES.jmx",
    "status": "finished", "user": "qa.performance", "started": "06/11/2026 21:00:04", "ended": "06/11/2026 21:40:27",
    "duration": "00:40:23", "props": "-Jthreads=100 -Jrampup=300", "slaves": ["10.0.1.11", "10.0.1.12"],
    "jira": "PERF-123", "notes": "Validación de optimizaciones Paquete 5 previo a liberación.",
    "run_url": "http://localhost:8090/runs/abc123def456", "report_url": "http://localhost:8090/p/…/report/",
    "grafana_url": "http://localhost:3000/d/jmeter/jmeter?var-application=BASEINET_QA",
    "confluence_url": "https://bancobase.atlassian.net/wiki/spaces/QAPERF/pages/123456",
    "jira_url": "https://bancobase.atlassian.net/browse/PERF-123", "result_dir": "Ejecucion_061126_210004_SCRIPT09",
    "totals": {"samples": 482113, "errors": 1205, "error_pct": 0.25, "success_pct": 99.75, "avg": 184.2,
               "p90": 310.0, "p95": 412.0, "p99": 980.0, "max": 5210, "tps": 199.4, "duration_s": 2423},
    "worst": [{"name": "T05_CdGetMovimientos", "samples": 96000, "error_pct": 0.8, "avg": 420.0, "p95": 1180.0},
              {"name": "T03_CdGetCuentas", "samples": 96500, "error_pct": 0.1, "avg": 210.0, "p95": 560.0},
              {"name": "T01_Login", "samples": 97000, "error_pct": 0.0, "avg": 150.0, "p95": 330.0}],
    "checks": [("Percentil 95", "<= 1000 ms", "412.00 ms", True), ("Tasa de error", "<= 1 %", "0.25 %", True)],
    "verdict": "SATISFACTORIA",
}


# --------------------------------------------------------------------------- rendering / sending
def render(event, summary):
    subject_status = {"start": "▶ Inició", "end": {"finished": "✔ Finalizó", "failed": "✖ Falló",
                                                  "stopped": "■ Detenida", "interrupted": "✖ Interrumpida"}}
    s = subject_status["start"] if event == "start" else subject_status["end"].get(summary["status"], "■ Terminó")
    if event == "end" and summary["status"] == "finished" and summary.get("verdict") == "INSATISFACTORIA":
        s = "⚠ Finalizó"
    verdict = f" · {summary['verdict']}" if event == "end" and summary.get("verdict") else ""
    subject = f"[JMeter] {s}: {summary['label']} · {summary['tag']}{verdict}"
    html = render_template("email/quick_report.html", s=summary, event=event, subject=subject)
    text = render_template("email/quick_report.txt", s=summary, event=event, subject=subject)
    return subject, html, text


def recipients(project, extra=None):
    cfg = settings.get()["smtp"]
    to = settings.parse_emails(cfg.get("always_to", ""))
    try:
        to += settings.project(project).get("staff_emails", [])
    except ValueError:
        pass
    to += extra or []
    seen, out = set(), []
    for e in to:
        if e.lower() not in seen:
            seen.add(e.lower())
            out.append(e)
    return out


def send(to, subject, html, text):
    cfg = settings.get()["smtp"]
    if not cfg.get("enabled"):
        raise RuntimeError("E-mail notifications are disabled (Settings → E-mail)")
    if not cfg.get("host") or not cfg.get("from_addr"):
        raise RuntimeError("SMTP host / from address not configured")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((ME, cfg["from_addr"]))
    msg["To"] = ", ".join(to)
    msg["Message-ID"] = make_msgid(domain=cfg["from_addr"].split("@")[-1])
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    port = int(cfg.get("port") or 587)
    ctx = ssl.create_default_context()
    if cfg.get("security") == "ssl":
        server = smtplib.SMTP_SSL(cfg["host"], port, timeout=30, context=ctx)
    else:
        server = smtplib.SMTP(cfg["host"], port, timeout=30)
    try:
        if cfg.get("security") == "starttls":
            server.starttls(context=ctx)
        if cfg.get("user"):
            server.login(cfg["user"], settings.decrypt(cfg.get("password_enc", "")))
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:
            pass


def _log(meta, line):
    p = runner._runs_dir() / f"{meta['id']}.log"
    with p.open("a") as fh:
        fh.write(f"### {time.strftime('%H:%M:%S')} {line}\n")


# --------------------------------------------------------------------------- run hooks
def on_start(meta):
    if meta.get("kind") != "test":
        return
    cfg = settings.get()["smtp"]
    if cfg.get("enabled") and cfg.get("notify_start") and meta.get("notify", True):
        try:
            to = recipients(meta["project"], meta.get("extra_emails"))
            subject, html, text = render("start", run_summary(meta))
            send(to, subject, html, text)
            _log(meta, f"notify: start e-mail sent to {', '.join(to)}")
        except Exception as exc:  # noqa: BLE001 - never break a run because of e-mail
            _log(meta, f"notify: start e-mail FAILED: {exc}")


def on_end(meta):
    if meta.get("kind") != "test":
        return
    summary = run_summary(meta)
    cfg = settings.get()["smtp"]
    if cfg.get("enabled") and cfg.get("notify_end") and meta.get("notify", True):
        try:
            to = recipients(meta["project"], meta.get("extra_emails"))
            subject, html, text = render("end", summary)
            send(to, subject, html, text)
            _log(meta, f"notify: end e-mail sent to {', '.join(to)}")
        except Exception as exc:  # noqa: BLE001
            _log(meta, f"notify: end e-mail FAILED: {exc}")
    if meta.get("jira"):
        try:
            atlassian.Jira(meta["user"]).comment(meta["jira"], jira_comment(summary))
            _log(meta, f"jira: comment added to {meta['jira']}")
        except Exception as exc:  # noqa: BLE001
            _log(meta, f"jira: comment on {meta['jira']} FAILED: {exc}")


def jira_comment(s):
    """Jira wiki markup (REST v2 accepts it on Cloud and Data Center)."""
    lines = [f"h3. Ejecución de performance: {s['label']} · {s['tag']}",
             f"*Estado:* {s['status']}{' · *' + s['verdict'] + '*' if s.get('verdict') else ''}",
             f"*Ejecutado por:* {s['user']} · *Inicio:* {s['started']} · *Duración:* {s['duration']}"]
    if s["slaves"]:
        lines.append(f"*Generadores:* Master + {len(s['slaves'])} slaves")
    t = s.get("totals")
    if t:
        lines += ["", "||Peticiones||Error %||Promedio||p95||p99||TPS||",
                  f"|{t['samples']:,}|{t['error_pct']} %|{t['avg']:.0f} ms|{t['p95']:.0f} ms|"
                  f"{(t.get('p99') or 0):.0f} ms|{t['tps']}|"]
    for name, expected, actual, ok in s.get("checks", []):
        lines.append(f"* {'(/)' if ok else '(x)'} {name}: {actual} (criterio {expected})")
    links = [(n, u) for n, u in (("Reporte HTML", s["report_url"]), ("Grafana", s["grafana_url"]),
                                 ("Confluence", s["confluence_url"]), ("Ejecución", s["run_url"])) if u]
    if links:
        lines += ["", " · ".join(f"[{n}|{u}]" for n, u in links)]
    lines.append("_(Enlaces localhost: abrir con el túnel SSM del Control Center)_")
    return "\n".join(lines)
