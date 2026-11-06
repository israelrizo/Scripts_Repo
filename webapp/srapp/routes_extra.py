"""Routes for: admin settings & Influx diagnostics, project settings, server checks, schedules,
e-mail quick report, Jira lookups, git/Bitbucket sync, shift-left PRs, CI API (/api/v1)."""
import time

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for

from . import (atlassian, connectivity, gitops, influx, notify, projects, runner, scheduler, settings,
               shiftleft, users)
from .app import _project_or_404, app, can, login_required
from .config import Config


# --------------------------------------------------------------------------- run hooks (e-mail, Jira)
def _with_ctx(fn):
    def wrapper(meta):
        with app.app_context():
            fn(meta)
    wrapper.__name__ = fn.__name__
    return wrapper


runner.HOOKS["start"].append(_with_ctx(notify.on_start))
runner.HOOKS["end"].append(_with_ctx(notify.on_end))


# --------------------------------------------------------------------------- admin settings
@app.route("/admin/settings", methods=["GET", "POST"])
@login_required("admin")
def admin_settings():
    cfg = settings.get()
    if request.method == "POST":
        section = request.form.get("section")
        f = request.form
        try:
            if section == "app":
                cfg["app"]["public_url"] = settings.safe_http_url(f.get("public_url"), allow_empty=False)
                tzname = f.get("timezone", "").strip()
                if tzname:
                    from zoneinfo import ZoneInfo
                    ZoneInfo(tzname)
                cfg["app"]["timezone"] = tzname
            elif section == "grafana":
                cfg["grafana"].update(url=settings.safe_http_url(f.get("url")), dashboard=f.get("dashboard", "").strip(),
                                      app_var=f.get("app_var", "").strip(), extra=f.get("extra", "").strip())
            elif section == "smtp":
                s = cfg["smtp"]
                s.update(enabled=bool(f.get("enabled")), host=f.get("host", "").strip(),
                         port=int(f.get("port") or 587), security=f.get("security", "starttls"),
                         user=f.get("user", "").strip(), from_addr=f.get("from_addr", "").strip(),
                         always_to=", ".join(settings.parse_emails(f.get("always_to", ""))),
                         notify_start=bool(f.get("notify_start")), notify_end=bool(f.get("notify_end")))
                if f.get("password"):
                    s["password_enc"] = settings.encrypt(f.get("password"))
                if s["from_addr"]:
                    settings.parse_emails(s["from_addr"])
            elif section == "smtp_test":
                to = settings.parse_emails(f.get("test_to", ""))
                if not to:
                    raise ValueError("Type a recipient for the test e-mail")
                subject, html, text = notify.render("end", notify.MOCK)
                notify.send(to, "[TEST] " + subject, html, text)
                flash(f"Test e-mail sent to {', '.join(to)}.", "ok")
                return redirect(url_for("admin_settings", _anchor="smtp"))
            elif section == "jira":
                cfg["jira"]["url"] = settings.safe_http_url(f.get("url"))
            elif section == "bitbucket":
                cfg["bitbucket"].update(api=settings.safe_http_url(f.get("api"), allow_empty=False),
                                        workspace=f.get("workspace", "").strip())
            settings.save(cfg)
            flash("Settings saved.", "ok")
        except Exception as exc:  # noqa: BLE001
            flash(f"Not saved: {exc}", "error")
        return redirect(url_for("admin_settings", _anchor=section))
    diag = None
    if request.args.get("diag"):
        diag = influx.diagnostics(request.args.get("db", ""), request.args.get("app", ""),
                                  request.args.get("measurement", "jmeter") or "jmeter",
                                  request.args.get("minutes", 60, type=int))
    return render_template("settings.html", s=cfg, diag=diag, influx_url=influx.INFLUX_URL,
                           smtp_has_password=bool(cfg["smtp"].get("password_enc")),
                           tz_now=scheduler.now().strftime("%Y-%m-%d %H:%M %Z"))


# --------------------------------------------------------------------------- project settings + shift-left
@app.post("/p/<name>/settings")
@login_required("operator")
def project_settings(name):
    _project_or_404(name)
    f = request.form
    try:
        s = settings.project(name)
        s["staff_emails"] = settings.parse_emails(f.get("staff_emails", ""))
        s["grafana_dashboard"] = f.get("grafana_dashboard", "").strip()
        repo = f.get("bitbucket_repo", "").strip()
        if repo and not atlassian.REPO_RE.match(repo):
            raise ValueError("Repository must be <workspace>/<repo-slug>")
        s["bitbucket_repo"] = repo
        sl = s["shiftleft"]
        sl.update(tag=f.get("sl_tag", ""), threads=int(f.get("sl_threads") or 5),
                  duration=int(f.get("sl_duration") or 120), sla_p95=float(f.get("sl_p95") or 1500),
                  sla_err=float(f.get("sl_err") or 1), base_branch=f.get("sl_branch", "").strip(),
                  runner_label=(f.get("sl_runner") or "jmeter-master").strip())
        if sl["tag"] and not projects.get_tag(name, sl["tag"]):
            raise ValueError("Unknown tag for shift-left")
        settings.save_project(name, s)
        flash("Project settings saved.", "ok")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("project", name=name, tab="settings"))


@app.get("/p/<name>/shiftleft/files")
@login_required()
def shiftleft_files(name):
    _project_or_404(name)
    try:
        files = shiftleft.generate(name)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(files)


@app.post("/p/<name>/shiftleft/pr")
@login_required("operator")
def shiftleft_pr(name):
    _project_or_404(name)
    try:
        url, created = shiftleft.open_pull_request(g.user["username"], name)
        flash(f"Pull request opened{' (with a new bitbucket-pipelines.yml)' if created else ''}: {url}", "ok")
    except (ValueError, atlassian.AtlassianError) as exc:
        flash(f"Pull request not created: {exc}", "error")
    return redirect(url_for("project", name=name, tab="settings"))


# --------------------------------------------------------------------------- server connectivity
@app.get("/p/<name>/servers")
@login_required()
def servers(name):
    _project_or_404(name)
    t = projects.get_tag(name, request.args.get("tag", ""))
    if not t or not t["exists"]:
        return jsonify(error="Unknown tag"), 404
    eps = connectivity.endpoints(name, t["script"], t["extra_args"], request.args.get("props", ""))
    if not eps:
        return jsonify(script=t["script"], results=[], note="No HTTP samplers found in this script")
    return jsonify(script=t["script"], results=connectivity.check_all(eps),
                   note="Checked from the Master; the slaves are expected to share its network route.")


# --------------------------------------------------------------------------- Jira lookup
@app.get("/api/jira/<key>")
@login_required("operator")
def jira_lookup(key):
    try:
        return jsonify(atlassian.Jira(g.user["username"]).issue(key.strip().upper()))
    except atlassian.AtlassianError as exc:
        return jsonify(error=str(exc)), 400


@app.post("/account/atlassian")
@login_required()
def atlassian_settings():
    f = request.form
    try:
        if f.get("action") == "test_jira":
            key = f.get("jira_test_key", "").strip().upper()
            j = atlassian.Jira(g.user["username"])
            info = j.issue(key) if key else None
            flash(f"Jira OK{': ' + info['key'] + ' · ' + info['summary'] if info else ''}.", "ok")
        elif f.get("action") == "test_bitbucket":
            repo = f.get("bb_test_repo", "").strip()
            info = atlassian.Bitbucket(g.user["username"]).repo(repo)
            flash(f"Bitbucket OK: {info['full_name']} (main branch {info['main']}).", "ok")
        else:
            atlassian.save(g.user["username"], f.get("jira_url"), f.get("jira_token"), f.get("bb_user"),
                           f.get("bb_token"))
            flash("Jira / Bitbucket settings saved.", "ok")
    except Exception as exc:  # noqa: BLE001
        flash(str(exc), "error")
    return redirect(url_for("confluence_settings", _anchor="jira"))


# --------------------------------------------------------------------------- schedules
@app.route("/schedules", methods=["GET", "POST"])
@login_required()
def schedules():
    if request.method == "POST":
        if not can("operator"):
            abort(403)
        f = request.form
        action = f.get("action", "create")
        try:
            if action == "create":
                scheduler.create(g.user["username"], f.get("project", ""), f.get("tag", ""), f.get("kind", "once"),
                                 f.get("at", ""), f.get("date", ""), f.getlist("days"), f.get("props", ""),
                                 bool(f.get("distributed")), f.get("jira", ""), f.get("notes", ""),
                                 settings.parse_emails(f.get("extra_emails", "")))
                flash("Execution scheduled.", "ok")
            elif action == "toggle":
                s = next(x for x in scheduler.load() if x["id"] == f.get("id"))
                scheduler.update(s["id"], enabled=not s["enabled"])
            elif action == "delete":
                scheduler.delete(f.get("id", ""))
                flash("Schedule deleted.", "ok")
        except (ValueError, StopIteration, projects.ProjectError) as exc:
            flash(str(exc) or "Unknown schedule", "error")
        return redirect(url_for("schedules"))
    items = scheduler.load()
    for s in items:
        s["describe"] = scheduler.describe(s)
        nr = scheduler.next_run(s)
        s["next"] = nr.strftime("%Y-%m-%d %H:%M") if nr else "—"
    plist = projects.list_projects()
    tags = {p["name"]: [t["tag"] for t in projects.parse_tags(p["name"]) if t["exists"]] for p in plist}
    return render_template("schedules.html", items=items, tags=tags, days=scheduler.DAYS,
                           tz_now=scheduler.now().strftime("%Y-%m-%d %H:%M %Z"), slaves=Config.REMOTE_HOSTS,
                           preset_project=request.args.get("project", ""), preset_tag=request.args.get("tag", ""))


# --------------------------------------------------------------------------- e-mail quick report
@app.get("/email/mock")
@login_required()
def email_mock():
    event = "start" if request.args.get("event") == "start" else "end"
    subject, html, _ = notify.render(event, notify.MOCK)
    return html


@app.get("/runs/<run_id>/email")
@login_required()
def run_email(run_id):
    meta = runner.get(run_id)
    if not meta or meta["kind"] != "test":
        abort(404)
    event = "start" if meta["status"] in ("running", "starting") else "end"
    subject, html, _ = notify.render(event, notify.run_summary(meta))
    return html


@app.post("/runs/<run_id>/notify")
@login_required("operator")
def run_notify(run_id):
    meta = runner.get(run_id)
    if not meta or meta["kind"] != "test":
        abort(404)
    try:
        event = "start" if meta["status"] in ("running", "starting") else "end"
        to = notify.recipients(meta["project"], meta.get("extra_emails"))
        subject, html, text = notify.render(event, notify.run_summary(meta))
        notify.send(to, subject, html, text)
        flash(f"E-mail sent to {', '.join(to)}.", "ok")
    except Exception as exc:  # noqa: BLE001
        flash(f"E-mail not sent: {exc}", "error")
    return redirect(url_for("run_detail", run_id=run_id))


# --------------------------------------------------------------------------- git / Bitbucket sync
@app.route("/git", methods=["GET", "POST"])
@login_required()
def git_page():
    if not gitops.available():
        flash(f"{Config.REPO_ROOT} is not a git repository.", "error")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        if not can("operator"):
            abort(403)
        try:
            if request.form.get("action") == "pull":
                flash(gitops.pull(), "ok")
            else:
                me = users.get(g.user["username"]) or {}
                sha = gitops.commit_and_push(request.form.getlist("paths"), request.form.get("message"),
                                             g.user["username"], me.get("email", ""))
                flash(f"Committed and pushed {sha}.", "ok")
        except Exception as exc:  # noqa: BLE001
            flash(str(exc), "error")
        return redirect(url_for("git_page"))
    try:
        st = gitops.status(fetch=bool(request.args.get("fetch")))
    except Exception as exc:  # noqa: BLE001
        flash(str(exc), "error")
        return redirect(url_for("dashboard"))
    return render_template("git.html", st=st)


# --------------------------------------------------------------------------- CI API (Bearer tokens)
def _api_summary(meta):
    s = notify.run_summary(meta)
    return s, s.get("totals")


@app.post("/api/v1/runs")
@login_required("operator")
def api_start_run():
    d = request.get_json(silent=True) or {}
    try:
        meta = runner.start_tag_run(d.get("project", ""), d.get("tag", ""), g.user["username"], d.get("props", ""),
                                    bool(d.get("distributed")), jira=d.get("jira", ""), notes=d.get("notes", ""),
                                    extra_emails=settings.parse_emails(",".join(d.get("emails", []))),
                                    source="api")
    except (projects.ProjectError, ValueError) as exc:
        return jsonify(error=str(exc)), 409 if "Another test" in str(exc) else 400
    return jsonify(id=meta["id"], status=meta["status"], url=f"/runs/{meta['id']}"), 201


@app.get("/api/v1/runs/<run_id>")
@login_required()
def api_run_status(run_id):
    try:
        meta = runner.get(run_id)
    except ValueError:
        meta = None
    if not meta:
        return jsonify(error="not found"), 404
    out = {"id": meta["id"], "status": meta["status"], "project": meta["project"], "tag": meta.get("tag"),
           "result_dir": meta.get("result_dir"), "started": meta.get("started"), "ended": meta.get("ended")}
    if meta["status"] not in ("running", "starting", "stopping") and meta.get("kind") == "test":
        s, t = _api_summary(meta)
        out["summary"] = t
        out["report_url"] = s.get("report_url")
        checks = []
        if t:
            p95 = request.args.get("sla_p95", type=float)
            err = request.args.get("sla_err", type=float)
            if p95 is not None:
                checks.append({"name": "p95", "limit": f"<= {p95:g} ms", "actual": round(t["p95"] or 0, 1),
                               "ok": (t["p95"] or 0) <= p95})
            if err is not None:
                checks.append({"name": "error %", "limit": f"<= {err:g} %", "actual": t["error_pct"],
                               "ok": t["error_pct"] <= err})
        out["sla"] = {"passed": bool(t) and all(c["ok"] for c in checks), "checks": checks}
    return jsonify(out)


@app.get("/api/v1/runs/<run_id>/log")
@login_required()
def api_run_log(run_id):
    text, offset = runner.read_log(run_id, request.args.get("offset", 0, type=int))
    return jsonify(text=text, offset=offset)


@app.context_processor
def _extra_ctx():
    return {"server_time": time.strftime("%H:%M"), "project_settings": settings.project}
