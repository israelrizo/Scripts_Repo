"""Routes for the "runs on the engineer's computer" mode: servers (EC2 via AWS CLI), SSM tunnels,
AWS settings / SSO, Gmail account linking, Google Chat spaces and fetching reports from the Master."""
import secrets

from flask import abort, flash, g, jsonify, redirect, render_template, request, session, url_for

from . import aws, gitops, google, newrelic, notify, power, projects, remote_run, runner, scheduler, settings, tunnels
from .app import _project_or_404, app, can, login_required


def _op(title, fn):
    meta = runner.start_op(title, g.user["username"], fn)
    return redirect(url_for("run_detail", run_id=meta["id"]))


def _require_aws():
    if not settings.aws_mode():
        flash("Remote (AWS) mode is disabled. Enable it in Settings → AWS.", "warn")
        return redirect(url_for("admin_settings", _anchor="aws"))
    return None


# --------------------------------------------------------------------------- servers page
@app.get("/servers")
@login_required()
def servers_page():
    r = _require_aws()
    if r:
        return r
    c = aws.cfg()
    inst, error = [], None
    try:
        inst = aws.instances(use_cache=False)
    except aws.AwsError as exc:
        error = str(exc)
    left = aws.auto_off_minutes()
    try:
        git = {"branch": gitops.branch(), "sha": gitops.head_sha()[:8]}
    except Exception:  # noqa: BLE001
        git = None
    return render_template("servers.html", inst=inst, error=error, auth_error=bool(error) and aws.AwsError(error).auth,
                           c=c, auto_off_left=left, tunnels=tunnels.status(), git=git,
                           ops=[m for m in runner.list_runs(limit=60) if m.get("kind") == "ops"][:8])


@app.get("/api/servers")
@login_required()
def api_servers():
    if not settings.aws_mode():
        return jsonify(enabled=False)
    out = {"enabled": True, "auto_off": aws.cfg().get("auto_off"), "auto_off_min": aws.auto_off_minutes()}
    try:
        out["instances"] = aws.instances()
    except aws.AwsError as exc:
        out["error"] = str(exc)
        out["auth"] = exc.auth
        return jsonify(out)
    if request.args.get("detail"):
        master = next((i for i in out["instances"] if i["role"] == "master"), None)
        if master and master["state"] == "running" and master["ssm"]:
            try:
                out["active"] = remote_run.master_active()
            except aws.AwsError as exc:
                out["active_error"] = str(exc)
    out["tunnels"] = tunnels.status()
    return jsonify(out)


@app.post("/servers/action")
@login_required("operator")
def servers_action():
    r = _require_aws()
    if r:
        return r
    action = request.form.get("action")
    if action == "start":
        return _op("Start servers", remote_run.op_start)
    if action == "stop":
        return _op("Stop servers", lambda log: remote_run.op_stop(log, force=False))
    if action == "force_stop":
        return _op("Stop servers (force)", lambda log: remote_run.op_stop(log, force=True))
    if action == "sync":
        return _op("Sync repository on servers", lambda log: remote_run.op_sync(log, force=False))
    if action == "force_sync":
        return _op("Force sync repository on servers", lambda log: remote_run.op_sync(log, force=True))
    if action == "health":
        return _op("Servers health check", remote_run.op_health)
    if action == "sso":
        return _op("AWS SSO login", remote_run.op_sso_login)
    abort(400)


# --------------------------------------------------------------------------- tunnels
@app.post("/tunnels")
@login_required("operator")
def tunnels_action():
    r = _require_aws()
    if r:
        return r
    action, name = request.form.get("action"), request.form.get("name", "")
    try:
        if action == "open":
            d = tunnels.open_tunnel(name)
            flash(f"Tunnel open: localhost:{d['local_port']} → Master:{d['remote_port']}", "ok")
        elif action == "close":
            tunnels.close_tunnel(name)
            flash(f"Tunnel {name} closed.", "ok")
        elif action == "save":
            tunnels.save_definition(name.strip().lower(), request.form.get("label"), request.form.get("remote_port"),
                                    request.form.get("local_port"))
            flash("Tunnel saved.", "ok")
        elif action == "delete":
            tunnels.delete_definition(name)
            flash("Tunnel removed.", "ok")
    except (tunnels.TunnelError, aws.AwsError, ValueError) as exc:
        flash(str(exc), "error")
    return redirect(request.referrer or url_for("servers_page"))


@app.get("/tunnels/<name>/go")
@login_required()
def tunnel_go(name):
    """Open the tunnel if needed and jump to it (used by the Grafana links)."""
    try:
        base = tunnels.ensure(name).replace("127.0.0.1", "localhost")
    except (tunnels.TunnelError, aws.AwsError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("servers_page"))
    nxt = request.args.get("next", "")
    return redirect(nxt if nxt.startswith(base) else base)


# --------------------------------------------------------------------------- AWS settings
@app.post("/admin/settings/aws")
@login_required("admin")
def aws_settings():
    f = request.form
    cfg = settings.get()
    c = cfg["aws"]
    try:
        if f.get("action") == "identity":
            ident = aws.identity()
            flash(f"AWS identity: {ident['arn']} (account {ident['account']})", "ok")
        elif f.get("action") == "test":
            inst = aws.instances(use_cache=False)
            flash("Instances: " + ", ".join(f"{i['role']} {i['state']}{' · SSM online' if i['ssm'] else ''}"
                                             for i in inst), "ok")
            master = inst[0]
            if master["state"] == "running" and master["ssm"]:
                rc, out, err = aws.run(master["id"], 'echo "user=$(whoami) jmeter=$(command -v jmeter || echo NOT-FOUND) '
                                       f'repo=$([ -d {aws.remote_root()}/.git ] && echo ok || echo MISSING)"', 60)
                flash(f"Master via SSM: {out.strip() or err.strip()}", "ok" if rc == 0 else "error")
        else:
            c.update(enabled=bool(f.get("enabled")), profile=f.get("profile", "").strip(),
                     region=f.get("region", "").strip(), master=f.get("master", "").strip(),
                     slaves=[s for s in f.get("slaves", "").replace(",", " ").split() if s],
                     remote_user=f.get("remote_user", "").strip(), remote_root=f.get("remote_root", "").strip(),
                     branch=f.get("branch", "").strip(), auto_off=f.get("auto_off", "").strip(),
                     slave_start_cmd=f.get("slave_start_cmd", "").strip()[:200],
                     jtl_max_mb=int(f.get("jtl_max_mb") or 200))
            aws.validate(c)
            if c["enabled"] and not c["master"]:
                raise ValueError("Set the Master instance id")
            cfg["tunnels"]["auto_influx"] = bool(f.get("auto_influx"))
            settings.save(cfg)
            aws.invalidate()
            flash("AWS settings saved.", "ok")
    except (ValueError, aws.AwsError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_settings", _anchor="aws"))


# --------------------------------------------------------------------------- Gmail account + Chat spaces
@app.post("/admin/settings/google")
@login_required("admin")
def google_settings():
    f = request.form
    cfg = settings.get()
    try:
        action = f.get("action")
        if action == "client":
            cfg["google"]["client_id"] = f.get("client_id", "").strip()
            if f.get("client_secret"):
                cfg["google"]["client_secret_enc"] = settings.encrypt(f.get("client_secret").strip())
            settings.save(cfg)
            flash("OAuth client saved. Now link your Gmail account.", "ok")
        elif action == "link":
            state = google.new_state()
            session["google_state"] = state
            return redirect(google.auth_url(state))
        elif action == "unlink":
            google.unlink()
            flash("Gmail account unlinked.", "ok")
        elif action == "space_add":
            google.add_space(f.get("name"), f.get("url"), f.get("default"))
            flash("Chat space added.", "ok")
        elif action == "space_default":
            google.update_space(f.get("id"), default=f.get("value") == "1")
        elif action == "space_delete":
            google.update_space(f.get("id"), delete=True)
            flash("Chat space removed.", "ok")
        elif action == "chat":
            cfg["chat"].update(enabled=bool(f.get("enabled")), notify_start=bool(f.get("notify_start")),
                               notify_end=bool(f.get("notify_end")))
            settings.save(cfg)
            flash("Chat settings saved.", "ok")
        elif action == "space_test":
            space = next(s for s in settings.get()["chat"]["spaces"] if s["id"] == f.get("id"))
            google.send_chat(space, notify.chat_payload("end", notify.MOCK))
            flash(f"Test message sent to {space['name']}.", "ok")
    except (google.GoogleError, StopIteration, ValueError) as exc:
        flash(str(exc) or "Unknown space", "error")
    return redirect(url_for("admin_settings", _anchor="smtp" if f.get("action") in ("client", "unlink") else "chat"))


@app.get("/oauth/google/callback")
@login_required("admin")
def google_callback():
    expected = session.pop("google_state", None)
    if request.args.get("error"):
        flash(f"Google sign-in cancelled: {request.args.get('error')}", "error")
    elif not expected or not secrets.compare_digest(expected, request.args.get("state", "")):
        flash("Google sign-in rejected (state mismatch). Try again.", "error")
    else:
        try:
            email = google.exchange(request.args.get("code", ""))
            flash(f"Gmail account linked: {email or 'ok'}. Notifications are sent from this account.", "ok")
        except google.GoogleError as exc:
            flash(str(exc), "error")
    return redirect(url_for("admin_settings", _anchor="smtp"))


# --------------------------------------------------------------------------- reports stored on the Master
@app.get("/p/<name>/remote-results")
@login_required()
def remote_results(name):
    _project_or_404(name)
    try:
        return jsonify(results=remote_run.remote_results(name))
    except (aws.AwsError, projects.ProjectError) as exc:
        return jsonify(error=str(exc)), 502


@app.post("/p/<name>/remote-results")
@login_required("operator")
def remote_results_fetch(name):
    _project_or_404(name)
    rd = request.form.get("result", "")
    if not rd.startswith("Ejecucion_") or "/" in rd or ".." in rd:
        abort(400)
    return _op(f"Fetch {rd}", remote_run.op_fetch(name, rd))


# --------------------------------------------------------------------------- New Relic
# the New Relic lookup runs at the start of notify.on_end, so e-mail / chat / Jira include it


@app.post("/admin/settings/newrelic")
@login_required("admin")
def newrelic_settings():
    f = request.form
    cfg = settings.get()
    c = cfg["newrelic"]
    try:
        if f.get("action") == "test":
            info = newrelic.test_connection()
            flash(f"New Relic OK: account '{info['account']}' as {info['user']}.", "ok")
        else:
            acc = f.get("account_id", "").strip()
            if acc and not acc.isdigit():
                raise ValueError("Account id must be numeric")
            c.update(enabled=bool(f.get("enabled")), region="eu" if f.get("region") == "eu" else "us",
                     account_id=acc, lookback_hours=max(1, min(168, int(f.get("lookback_hours") or 24))),
                     auto_on_run=bool(f.get("auto_on_run")))
            if f.get("api_key"):
                if not f.get("api_key").strip().startswith("NRAK-"):
                    raise ValueError("Use a User API key (starts with NRAK-), not a license/ingest key")
                c["api_key_enc"] = settings.encrypt(f.get("api_key").strip())
            settings.save(cfg)
            flash("New Relic settings saved.", "ok")
    except (ValueError, newrelic.NewRelicError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_settings", _anchor="newrelic"))


@app.get("/p/<name>/newrelic")
@login_required()
def newrelic_discover(name):
    _project_or_404(name)
    if not newrelic.enabled():
        return jsonify(error="New Relic is not configured (Settings → New Relic)"), 400
    t = projects.get_tag(name, request.args.get("tag", ""))
    if not t or not t["exists"]:
        return jsonify(error="Unknown tag"), 404
    try:
        d = newrelic.discover(name, t["script"], t["extra_args"])
    except (newrelic.NewRelicError, projects.ProjectError) as exc:
        return jsonify(error=str(exc)), 502
    d["pinned"] = settings.project(name).get("nr_apps") or []
    d["links"] = newrelic.entity_links([a["name"] for a in d["apps"]])
    return jsonify(d)


@app.post("/p/<name>/newrelic")
@login_required("operator")
def newrelic_pin(name):
    _project_or_404(name)
    apps = [a for a in request.form.getlist("apps") if newrelic.APP_RE.match(a)][:20]
    ps = settings.project(name)
    ps["nr_apps"] = apps
    settings.save_project(name, ps)
    flash(f"New Relic services for this project: {', '.join(apps) or 'auto-discovery'}.", "ok")
    return redirect(request.referrer or url_for("project", name=name, tab="settings"))


@app.route("/runs/<run_id>/newrelic", methods=["GET", "POST"])
@login_required()
def run_newrelic(run_id):
    meta = runner.get(run_id)
    if not meta or meta.get("kind") != "test":
        abort(404)
    if request.method == "GET" and meta.get("newrelic") and meta["status"] not in ("running", "starting", "stopping"):
        return jsonify(meta["newrelic"])
    if not newrelic.enabled():
        return jsonify(error="New Relic is not configured"), 400
    try:
        t = projects.get_tag(meta["project"], meta.get("tag", "")) or {}
        apps, source = newrelic.apps_for(meta["project"], meta.get("script"), t.get("extra_args", ""))
        if not apps:
            return jsonify(error="No APM service matched this script; pin them in project → Settings"), 404
        start = int((meta.get("started") or meta["created"]) * 1000) - 60000
        end = int((meta.get("ended") or __import__("time").time()) * 1000) + 60000
        summary = newrelic.window_summary(apps, start, end)
        summary["source"] = source
        if meta["status"] not in ("running", "starting", "stopping"):
            runner.update(run_id, newrelic=summary)
        return jsonify(summary)
    except (newrelic.NewRelicError, projects.ProjectError) as exc:
        return jsonify(error=str(exc)), 502


# --------------------------------------------------------------------------- quick run
def recent_tags(limit=6):
    seen, out = set(), []
    for m in runner.list_runs(limit=80):
        if m.get("kind") != "test" or (m["project"], m.get("tag")) in seen:
            continue
        seen.add((m["project"], m.get("tag")))
        out.append({"project": m["project"], "tag": m.get("tag"), "props": " ".join(m.get("props") or []),
                    "status": m["status"], "when": m.get("started") or m.get("created"), "id": m["id"]})
        if len(out) >= limit:
            break
    return out


@app.get("/api/tags")
@login_required()
def api_tags():
    recent = {(r["project"], r["tag"]) for r in recent_tags(10)}
    tags = []
    for p in projects.list_projects():
        for t in projects.parse_tags(p["name"]):
            tags.append({"project": p["name"], "tag": t["tag"], "script": t["script"], "exists": t["exists"],
                         "recent": (p["name"], t["tag"]) in recent})
    tags.sort(key=lambda t: (not t["recent"], t["project"], t["tag"]))
    return jsonify(tags=tags)


# --------------------------------------------------------------------------- script quality review
@app.get("/p/<name>/quality.md")
@login_required()
def quality_markdown(name):
    from . import quality
    _project_or_404(name)
    md = quality.to_markdown(quality.review_project(projects.project_dir(name)),
                             f"Revisión de calidad de scripts · {name}")
    return app.response_class(md, mimetype="text/markdown", headers={
        "Content-Disposition": f"attachment; filename=calidad_{name}.md"})


# --------------------------------------------------------------------------- JMeter GUI on this computer
@app.post("/p/<name>/gui")
@login_required("operator")
def open_in_jmeter(name):
    from . import jmeter_gui
    _project_or_404(name)
    t = projects.get_tag(name, request.form.get("tag", "")) if request.form.get("tag") else None
    script = t["script"] if t else request.form.get("script", "")
    try:
        exe = jmeter_gui.open_script(g.user["username"], name, script, (t or {}).get("extra_args", ""))
        msg = (f"Opening {script.rsplit('/', 1)[-1]} in JMeter ({exe}). After saving your changes, commit & push "
               "them on the Git page so the servers use them.")
        if request.headers.get("X-CSRF-Token"):
            return jsonify(ok=True, message=msg)
        flash(msg, "ok")
    except (jmeter_gui.GuiError, projects.ProjectError) as exc:
        if request.headers.get("X-CSRF-Token"):
            return jsonify(error=str(exc)), 400
        flash(str(exc), "error")
    return redirect(request.referrer or url_for("project", name=name))


# --------------------------------------------------------------------------- scheduler service / power
@app.get("/api/scheduler")
@login_required()
def api_scheduler():
    slots = scheduler.upcoming_slots()
    return jsonify(power=power.status(), next=[x.strftime("%Y-%m-%d %H:%M") for x in slots[:5]],
                   keep_awake_hours=settings.get()["scheduler"].get("keep_awake_hours"))


@app.post("/schedules/power")
@login_required("operator")
def scheduler_power_settings():
    cfg = settings.get()
    try:
        cfg["scheduler"].update(keep_awake_hours=max(0.0, min(24.0, float(request.form.get("keep_awake_hours") or 0))),
                                wake_timers=bool(request.form.get("wake_timers")))
        settings.save(cfg)
        scheduler._power["key"] = None   # re-apply wake timers on the next tick
        flash("Scheduler power settings saved.", "ok")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("schedules"))


@app.context_processor
def _remote_ctx():
    return {"aws_mode": settings.aws_mode(), "slave_list": runner.slave_list,
            "chat_spaces_all": google.spaces(), "auto_off": settings.get()["aws"].get("auto_off"),
            "nr_enabled": newrelic.enabled(), "recent_tags": recent_tags}
