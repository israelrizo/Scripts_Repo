"""E-mail quick report + run notifications (start / end) and Jira comments.

Recipients of every notification: settings.smtp.always_to (qaperformance@bancobase.com)
+ the project's staff e-mails (project settings) + extra addresses typed in the run dialog.
"""
import io
import smtplib
import ssl
import time
import zipfile
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from flask import render_template

from . import atlassian, google, projects, runner, settings
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
        "newrelic": _nr_rows(meta.get("newrelic")),
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
    out["local_links"] = settings.is_local_url(base_url)
    if out["jira"]:
        jira_base = settings.get()["jira"].get("url") or ""
        out["jira_url"] = f"{jira_base.rstrip('/')}/browse/{out['jira']}" if jira_base else ""
    return out


def _nr_rows(nr):
    if not nr or not nr.get("apps"):
        return []
    links = nr.get("links") or {}
    return [{"name": n, **a, "link": links.get(n, "")} for n, a in nr["apps"].items()]


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


def report_attachment(project, result_dir):
    """Zip of html_report for e-mail (recipients cannot open links to the engineer's localhost)."""
    cfg = settings.get()["smtp"]
    if not cfg.get("attach_report") or not result_dir:
        return None
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
    if len(data) > int(cfg.get("attach_max_mb") or 15) * 1024 * 1024:
        return None
    return f"{result_dir}_html_report.zip", data


def sender():
    cfg = settings.get()["smtp"]
    if cfg.get("provider", "gmail") == "gmail":
        return google.linked()["email"]
    return cfg.get("from_addr", "")


def send(to, subject, html, text, attachment=None):
    cfg = settings.get()["smtp"]
    if not cfg.get("enabled"):
        raise RuntimeError("E-mail notifications are disabled (Settings → E-mail)")
    if not to:
        raise RuntimeError("No recipients")
    provider = cfg.get("provider", "gmail")
    from_addr = sender()
    if not from_addr:
        raise RuntimeError("Gmail account not linked (Settings → E-mail)" if provider == "gmail"
                           else "SMTP from address not configured")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((ME, from_addr)) if provider != "gmail" else from_addr
    msg["To"] = ", ".join(to)
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1])
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    if attachment:
        msg.add_attachment(attachment[1], maintype="application", subtype="zip", filename=attachment[0])
    if provider == "gmail":
        google.send_gmail(msg.as_bytes())
        return
    if not cfg.get("host"):
        raise RuntimeError("SMTP host not configured")
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


# --------------------------------------------------------------------------- Google Chat
def chat_payload(event, s):
    """Text + card for a Google Chat space."""
    icon = "▶️" if event == "start" else {"SATISFACTORIA": "✅", "INSATISFACTORIA": "⚠️"}.get(
        s.get("verdict"), "✅" if s["status"] == "finished" else "❌")
    title = f"{icon} {s['label']} · {s['tag']}"
    state = "En ejecución" if event == "start" else (s.get("verdict") or s["status"].upper())
    lines = [f"*{title}*", f"{state} · por {s['user']} · {s['started']}"
             + (f" · duración {s['duration']}" if event == "end" else "")]
    widgets = [{"decoratedText": {"topLabel": "Estado", "text": f"<b>{state}</b>"}},
               {"decoratedText": {"topLabel": "Ejecutado por", "text": f"{s['user']} · {s['started']}"}}]
    if s.get("slaves"):
        widgets.append({"decoratedText": {"topLabel": "Generadores", "text": f"Master + {len(s['slaves'])} slaves"}})
    if s.get("notes"):
        widgets.append({"decoratedText": {"topLabel": "Notas", "text": s["notes"], "wrapText": True}})
    t = s.get("totals")
    if event == "end" and t:
        kpi = (f"{t['samples']:,} peticiones · error {t['error_pct']} % · prom {t['avg'] or 0:.0f} ms · "
               f"p95 {t['p95'] or 0:.0f} ms · {t['tps']} TPS")
        lines.append(kpi)
        widgets.append({"decoratedText": {"topLabel": "Resultados", "text": kpi, "wrapText": True}})
        for name, expected, actual, ok in s.get("checks", []):
            widgets.append({"decoratedText": {"topLabel": name, "text": f"{'✅' if ok else '❌'} {actual} (criterio {expected})"}})
        for a in s.get("newrelic", [])[:5]:
            txt = (f"{a['rpm']} rpm · prom {a['avg_ms']} ms · p95 {a['p95_ms']} ms · error {a['error_pct']} %"
                   + (f" · CPU {a['cpu']} %" if a.get("cpu") is not None else ""))
            lines.append(f"New Relic {a['name']}: {txt}")
            widgets.append({"decoratedText": {"topLabel": f"New Relic · {a['name']}", "text": txt, "wrapText": True}})
    buttons = [{"text": label, "onClick": {"openLink": {"url": url}}}
               for label, url in (("Confluence", s.get("confluence_url")), ("Jira", s.get("jira_url")))
               if url and not settings.is_local_url(url)]
    if buttons:
        widgets.append({"buttonList": {"buttons": buttons}})
    return {"text": "\n".join(lines),
            "cardsV2": [{"cardId": "jmcc", "card": {
                "header": {"title": f"{s['label']} · {s['tag']}", "subtitle": "JMeter Control Center · " + state},
                "sections": [{"widgets": widgets}]}}]}


def send_chat(event, meta, summary):
    cfg = settings.get()["chat"]
    if not cfg.get("enabled") or not cfg.get(f"notify_{event}", True) or not meta.get("notify", True):
        return
    targets = google.chat_targets(meta["project"])
    if not targets:
        return
    payload = chat_payload(event, summary)
    ok, bad = [], []
    for space in targets:
        try:
            google.send_chat(space, payload, thread_key=f"jmcc-{meta['id']}")
            ok.append(space["name"])
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{space['name']} ({exc})")
    if ok:
        _log(meta, f"chat: {event} message sent to {', '.join(ok)}")
    if bad:
        _log(meta, f"chat: FAILED for {'; '.join(bad)}")


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
            _log(meta, f"notify: start e-mail sent from {sender()} to {', '.join(to)}")
        except Exception as exc:  # noqa: BLE001 - never break a run because of e-mail
            _log(meta, f"notify: start e-mail FAILED: {exc}")
    try:
        send_chat("start", meta, run_summary(meta))
    except Exception as exc:  # noqa: BLE001
        _log(meta, f"chat: FAILED: {exc}")


def on_end(meta):
    if meta.get("kind") != "test":
        return
    try:
        from . import newrelic
        newrelic.run_hook(meta)
        meta = runner.get(meta["id"]) or meta
    except Exception as exc:  # noqa: BLE001 - New Relic must never block notifications
        _log(meta, f"newrelic: lookup FAILED: {exc}")
    summary = run_summary(meta)
    cfg = settings.get()["smtp"]
    if cfg.get("enabled") and cfg.get("notify_end") and meta.get("notify", True):
        try:
            to = recipients(meta["project"], meta.get("extra_emails"))
            subject, html, text = render("end", summary)
            att = report_attachment(meta["project"], meta.get("result_dir"))
            send(to, subject, html, text, att)
            _log(meta, f"notify: end e-mail sent from {sender()} to {', '.join(to)}"
                 + (f" (attached {att[0]}, {len(att[1]) / 1024:.0f} KB)" if att else ""))
        except Exception as exc:  # noqa: BLE001
            _log(meta, f"notify: end e-mail FAILED: {exc}")
    try:
        send_chat("end", meta, summary)
    except Exception as exc:  # noqa: BLE001
        _log(meta, f"chat: FAILED: {exc}")
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
    if s.get("newrelic"):
        lines += ["", "*New Relic (APM durante la prueba)*", "||Servicio||RPM||Promedio||p95||Error %||CPU||"]
        lines += [f"|{a['name']}|{a['rpm']}|{a['avg_ms']} ms|{a['p95_ms']} ms|{a['error_pct']} %|"
                  f"{a['cpu'] if a.get('cpu') is not None else '—'} %|" for a in s["newrelic"]]
    links = [(n, u) for n, u in (("Reporte HTML", s["report_url"]), ("Grafana", s["grafana_url"]),
                                 ("Confluence", s["confluence_url"]), ("Ejecución", s["run_url"]))
             if u and not settings.is_local_url(u)]
    if links:
        lines += ["", " · ".join(f"[{n}|{u}]" for n, u in links)]
    return "\n".join(lines)
