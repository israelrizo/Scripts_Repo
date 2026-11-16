"""Routes for the "runs on the engineer's computer" mode: servers (EC2 via AWS CLI), SSM tunnels,
AWS settings / SSO, Gmail account linking, Google Chat spaces and fetching reports from the Master."""
import secrets

from flask import abort, flash, g, jsonify, redirect, render_template, request, session, url_for

from . import aws, gitops, google, notify, projects, remote_run, runner, settings, tunnels
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


@app.context_processor
def _remote_ctx():
    return {"aws_mode": settings.aws_mode(), "slave_list": runner.slave_list,
            "chat_spaces_all": google.spaces(), "auto_off": settings.get()["aws"].get("auto_off")}
