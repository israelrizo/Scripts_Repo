"""Scripts_Repo JMeter Control Center - Flask application."""
import functools
import io
import re
import secrets
import tarfile
import time
from datetime import datetime, timedelta

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   send_file, send_from_directory, session, url_for)
from markupsafe import Markup

from . import confluence, influx, projects, runner, users
from . import report as rpt
from .config import Config, load_secret_key

app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_secret_key(),
    MAX_CONTENT_LENGTH=Config.MAX_UPLOAD_MB * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_NAME="sr_session",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=Config.SESSION_HOURS),
)

_failed_logins = {}  # (ip, user) -> [count, first_ts]
LOCK_AFTER, LOCK_SECONDS = 5, 300


# --------------------------------------------------------------------------- helpers
@app.template_filter("dt")
def _dt(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "—"


@app.template_filter("size")
def _size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


@app.template_filter("duration")
def _duration(meta):
    if not meta.get("started"):
        return "—"
    secs = int((meta.get("ended") or time.time()) - meta["started"])
    return f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def _load_user():
    g.user = None
    name = session.get("user")
    if name:
        u = users.get(name)
        if u:
            g.user = {"username": name, "role": u["role"]}
        else:
            session.clear()
    if request.method == "POST":
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400, "Invalid or missing CSRF token, reload the page.")


@app.after_request
def _headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


@app.context_processor
def _ctx():
    return {"me": g.get("user"), "can": can, "cfg": Config, "grafana_url": influx.GRAFANA_URL}


def can(role):
    return bool(g.get("user")) and users.ROLE_RANK[g.user["role"]] >= users.ROLE_RANK[role]


def login_required(role="viewer"):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            if not g.user:
                if request.path.startswith("/api/"):
                    return jsonify(error="login required"), 401
                return redirect(url_for("login", next=request.full_path))
            if not can(role):
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def _project_or_404(name):
    try:
        projects.project_dir(name)
    except projects.ProjectError:
        abort(404)
    return name


@app.errorhandler(projects.ProjectError)
def _project_error(exc):
    if request.path.startswith("/api/"):
        return jsonify(error=str(exc)), 400
    flash(str(exc), "error")
    return redirect(request.referrer or url_for("dashboard"))


@app.errorhandler(413)
def _too_big(_exc):
    flash(f"File too large (limit {Config.MAX_UPLOAD_MB} MB, SR_MAX_UPLOAD_MB).", "error")
    return redirect(request.referrer or url_for("dashboard"))


# --------------------------------------------------------------------------- auth
@app.route("/login", methods=["GET", "POST"])
def login():
    if users.count() == 0:
        return render_template("login.html", no_users=True)
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        key = (request.remote_addr, username.lower())
        count, first = _failed_logins.get(key, (0, time.time()))
        if count >= LOCK_AFTER and time.time() - first < LOCK_SECONDS:
            flash("Too many failed attempts, try again in a few minutes.", "error")
            return render_template("login.html"), 429
        if users.authenticate(username, request.form.get("password", "")):
            _failed_logins.pop(key, None)
            session.clear()
            session.permanent = True
            session["user"] = username
            csrf_token()
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
        if time.time() - first >= LOCK_SECONDS:
            count, first = 0, time.time()
        _failed_logins[key] = (count + 1, first)
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/account", methods=["GET", "POST"])
@login_required()
def account():
    if request.method == "POST":
        if not users.authenticate(g.user["username"], request.form.get("current", "")):
            flash("Current password is wrong.", "error")
        elif request.form.get("new") != request.form.get("confirm"):
            flash("New passwords do not match.", "error")
        else:
            try:
                users.set_password(g.user["username"], request.form.get("new", ""))
                flash("Password updated.", "ok")
            except ValueError as exc:
                flash(str(exc), "error")
        return redirect(url_for("account"))
    return render_template("account.html")


# --------------------------------------------------------------------------- dashboard
@app.get("/")
@login_required()
def dashboard():
    return render_template("dashboard.html", projects=projects.list_projects(),
                           active=runner.active_runs(), recent=runner.list_runs(limit=8),
                           jmeter_ok=runner.jmeter_available())


@app.get("/api/status")
@login_required()
def api_status():
    ok, detail = influx.ping()
    return jsonify(slaves=runner.slave_status(), active=runner.active_runs(),
                   influx={"ok": ok, "detail": detail}, jmeter=runner.jmeter_available())


@app.route("/projects/new", methods=["GET", "POST"])
@login_required("admin")
def new_project():
    if request.method == "POST":
        folder = projects.create_project(request.form.get("slug"), request.form.get("app_name"),
                                         request.form.get("folders"))
        flash(f"Project {folder} created from the template. Upload scripts and register tags.", "ok")
        return redirect(url_for("project", name=folder, tab="scripts"))
    return render_template("new_project.html", suffix=Config.PROJECT_SUFFIX)


# --------------------------------------------------------------------------- project
@app.get("/p/<name>")
@login_required()
def project(name):
    _project_or_404(name)
    tab = request.args.get("tab", "tags")
    ctx = {"name": name, "tab": tab, "tags": projects.parse_tags(name), "slaves": Config.REMOTE_HOSTS}
    if tab == "scripts":
        ctx.update(scripts=projects.list_scripts(name), folders=projects.test_subfolders(name))
    elif tab == "data":
        ctx.update(data=projects.list_data(name))
    elif tab == "results":
        ctx.update(results=projects.list_results(name), published=rpt.history(name))
    elif tab == "runs":
        ctx.update(runs=runner.list_runs(project=name))
    elif tab == "monitor":
        ctx.update(targets=_safe_targets(name))
    if tab in ("tags", "scripts"):
        ctx.update(all_scripts=[s["path"] for s in projects.list_scripts(name) if s["path"].endswith(".jmx")])
    return render_template("project.html", **ctx)


def _safe_targets(name):
    try:
        return influx.project_targets(name)
    except projects.ProjectError:
        return []


@app.post("/p/<name>/tags")
@login_required("operator")
def add_tag(name):
    _project_or_404(name)
    projects.add_tag(name, request.form.get("tag", "").strip(), request.form.get("script", ""),
                     request.form.get("extra_args", ""), request.form.get("group", ""))
    flash(f"Tag '{request.form.get('tag')}' added to run_by_tag.sh (backup kept in instance/backups).", "ok")
    return redirect(url_for("project", name=name, tab="tags"))


@app.post("/p/<name>/tags/<tag>/delete")
@login_required("operator")
def delete_tag(name, tag):
    _project_or_404(name)
    projects.remove_tag(name, tag)
    flash(f"Tag '{tag}' removed.", "ok")
    return redirect(url_for("project", name=name, tab="tags"))


@app.post("/p/<name>/upload")
@login_required("operator")
def upload(name):
    _project_or_404(name)
    kind = request.form.get("kind")
    files = request.files.getlist("files")
    if not files or not files[0].filename:
        raise projects.ProjectError("Choose at least one file")
    saved = []
    for storage in files:
        rel, warnings = projects.save_upload(name, kind, storage, request.form.get("subfolder", ""),
                                             overwrite=bool(request.form.get("overwrite")))
        saved.append(rel)
        for w in warnings:
            flash(f"{rel}: {w}", "warn")
    tag = request.form.get("tag", "").strip()
    if kind == "script" and tag:
        if len(saved) != 1:
            flash("Tag not registered: provide a tag only when uploading a single script.", "warn")
        else:
            projects.add_tag(name, tag, saved[0], request.form.get("extra_args", ""), request.form.get("group", ""))
            flash(f"Tag '{tag}' registered for {saved[0]}.", "ok")
    flash(f"Uploaded: {', '.join(saved)}", "ok")
    return redirect(url_for("project", name=name, tab="scripts" if kind == "script" else "data"))


@app.post("/p/<name>/files/delete")
@login_required("operator")
def delete_file(name):
    _project_or_404(name)
    rel = request.form.get("path", "")
    projects.remove_file(name, rel)
    flash(f"{rel} moved to the web app trash (instance/trash).", "ok")
    return redirect(request.referrer or url_for("project", name=name))


@app.get("/p/<name>/files/download")
@login_required()
def download_file(name):
    _project_or_404(name)
    f = projects.safe_path(name, request.args.get("path", ""))
    if not f.is_file():
        abort(404)
    return send_file(f, as_attachment=True)


@app.post("/p/<name>/run")
@login_required("operator")
def run(name):
    _project_or_404(name)
    meta = runner.start_tag_run(name, request.form.get("tag", ""), g.user["username"],
                                request.form.get("props", ""), bool(request.form.get("distributed")))
    return redirect(url_for("run_detail", run_id=meta["id"]))


@app.post("/p/<name>/sync")
@login_required("operator")
def sync(name):
    _project_or_404(name)
    meta = runner.start_sync(name, g.user["username"])
    return redirect(url_for("run_detail", run_id=meta["id"]))


# --------------------------------------------------------------------------- results
@app.get("/p/<name>/results/<run_name>/report/")
@app.get("/p/<name>/results/<run_name>/report/<path:filename>")
@login_required()
def report(name, run_name, filename="index.html"):
    _project_or_404(name)
    d = projects.result_dir(name, run_name) / "html_report"
    return send_from_directory(d, filename)


@app.get("/p/<name>/results/<run_name>/download")
@login_required()
def download_result(name, run_name):
    _project_or_404(name)
    d = projects.result_dir(name, run_name)
    tar = d.parent / f"{run_name}.tar.gz"
    if tar.is_file():
        return send_file(tar, as_attachment=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(str(d), arcname=run_name)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"{run_name}.tar.gz", mimetype="application/gzip")


@app.get("/p/<name>/compare")
@login_required()
def compare(name):
    _project_or_404(name)
    selected = request.args.getlist("r")[:6]
    if not selected:
        selected = [r["name"] for r in projects.list_results(name, limit=2) if r["has_report"]]
    stats = {r: projects.result_stats(name, r) for r in selected}
    tx_names = sorted({t for s in stats.values() for t in s if t != "Total"})
    return render_template("compare.html", name=name, selected=selected, stats=stats, tx_names=tx_names,
                           all_results=[r for r in projects.list_results(name) if r["has_report"]])


def _result_window(run_name):
    """Ejecucion_DDMMYY_HHMMSS_<script> -> (start_ms) in generator local time."""
    m = re.match(r"^Ejecucion_(\d{6})_(\d{6})_", run_name)
    if not m:
        return None
    return int(datetime.strptime(m.group(1) + m.group(2), "%d%m%y%H%M%S").timestamp() * 1000)


# --------------------------------------------------------------------------- runs
@app.get("/runs")
@login_required()
def runs():
    return render_template("runs.html", runs=runner.list_runs(limit=200))


@app.get("/runs/<run_id>")
@login_required()
def run_detail(run_id):
    meta = runner.get(run_id)
    if not meta:
        abort(404)
    targets = []
    if meta["kind"] == "test":
        try:
            targets = influx.listener_targets(projects.project_dir(meta["project"]) / meta["script"])
        except projects.ProjectError:
            targets = []
    return render_template("run.html", run=meta, targets=targets)


@app.get("/api/runs/<run_id>/log")
@login_required()
def run_log(run_id):
    meta = runner.get(run_id)
    if not meta:
        return jsonify(error="not found"), 404
    text, offset = runner.read_log(run_id, int(request.args.get("offset", 0)))
    return jsonify(text=text, offset=offset, status=meta["status"], result_dir=meta.get("result_dir"),
                   started=meta.get("started"), ended=meta.get("ended"))


@app.post("/runs/<run_id>/stop")
@login_required("operator")
def stop_run(run_id):
    flash(runner.stop(run_id, force=request.form.get("force") == "1"), "ok")
    return redirect(url_for("run_detail", run_id=run_id))


# --------------------------------------------------------------------------- live monitor
@app.get("/monitor")
@login_required()
def monitor():
    db, app_name = request.args.get("db", ""), request.args.get("app", "")
    start = request.args.get("from", type=int)
    end = request.args.get("to", type=int)
    run_name = request.args.get("result")
    if run_name and not start:
        start = _result_window(run_name)
    try:
        dbs = influx.databases()
        err = None
    except influx.InfluxError as exc:
        dbs, err = [], str(exc)
    return render_template("monitor.html", dbs=dbs, db=db, app_name=app_name, start=start, end=end,
                           influx_error=err)


@app.get("/api/influx/apps")
@login_required()
def influx_apps():
    try:
        return jsonify(apps=influx.applications(request.args.get("db", "")))
    except influx.InfluxError as exc:
        return jsonify(error=str(exc)), 502


@app.get("/api/influx/dashboard")
@login_required()
def influx_dashboard():
    now = int(time.time() * 1000)
    end = request.args.get("to", type=int) or now
    start = request.args.get("from", type=int) or (end - request.args.get("range", 900, type=int) * 1000)
    try:
        data = influx.dashboard(request.args.get("db", ""), request.args.get("app", ""), start, end,
                                request.args.get("measurement", "jmeter"))
    except influx.InfluxError as exc:
        return jsonify(error=str(exc)), 502
    data.update(start=start, end=end)
    return jsonify(data)


# --------------------------------------------------------------------------- confluence
@app.route("/account/confluence", methods=["GET", "POST"])
@login_required()
def confluence_settings():
    me = g.user["username"]
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "delete":
                confluence.delete_settings(me)
                flash("Confluence connection removed.", "ok")
            elif action == "test":
                client = confluence.Client.for_user(me)
                who = client.whoami()
                s = confluence.get_settings(me)
                msg = f"Connected as {who}."
                if s.get("space_key"):
                    msg += f" Space {s['space_key']}: {client.space(s['space_key']).get('name', 'ok')}."
                flash(msg, "ok")
            else:
                confluence.save_settings(me, request.form.get("base_url"), request.form.get("auth_type"),
                                         request.form.get("account"), request.form.get("token"),
                                         request.form.get("space_key"), request.form.get("parent_id"))
                flash("Confluence connection saved. Use 'Test connection' to verify it.", "ok")
        except confluence.ConfluenceError as exc:
            flash(str(exc), "error")
        return redirect(url_for("confluence_settings"))
    return render_template("confluence_settings.html", s=confluence.get_settings(me))


@app.route("/p/<name>/results/<run_name>/confluence", methods=["GET", "POST"])
@login_required()
def confluence_report(name, run_name):
    _project_or_404(name)
    me = g.user["username"]
    try:
        data = rpt.gather(name, run_name)
    except rpt.ReportError as exc:
        flash(str(exc), "error")
        return redirect(url_for("project", name=name, tab="results"))
    settings = confluence.get_settings(me)
    fields = rpt.initial_fields(name, run_name, data, settings)
    published = rpt.history(name).get(run_name)
    action = request.form.get("action") if request.method == "POST" else None
    if action:
        fields = {k: request.form.get(k, "") for k in list(fields) + ["page_mode"]}
    if action == "regen":
        fields.update(rpt.drafts(name, run_name, data, fields))
        flash("Texts regenerated from the current values and criteria.", "ok")
    elif action in ("preview", "publish"):
        now_status = rpt.evaluate(fields, data["totals"])[0] or "SIN CRITERIOS"
        if fields.get("status") == "auto" and fields.get("draft_status") and fields["draft_status"] != now_status:
            flash(f"The texts were drafted for status {fields['draft_status']} but the criteria now give "
                  f"{now_status}. Use 'Regenerar textos' or review the narrative before publishing.", "warn")
        try:
            images = rpt.decode_images(request.form)
            attachments = rpt.build_attachments(name, run_name, data, fields)
            if action == "preview":
                ctx = rpt.context(name, run_name, data, fields, images, attachments, preview=True)
                body = Markup(render_template("report/storage.xml", **ctx))
                return render_template("report/preview.html", f=fields, body=body)
            if not can("operator"):
                abort(403)
            ctx = rpt.context(name, run_name, data, fields, images, attachments, preview=False)
            storage = render_template("report/storage.xml", **ctx)
            url = rpt.publish(name, run_name, me, data, fields, images, storage, attachments)
            flash(Markup('Published to Confluence: <a href="{0}" target="_blank" rel="noopener">{0}</a>').format(url), "ok")
            return redirect(url_for("confluence_report", name=name, run_name=run_name))
        except (rpt.ReportError, confluence.ConfluenceError) as exc:
            flash(str(exc), "error")
    auto_status, _ = rpt.evaluate(fields, data["totals"])
    return render_template("report_form.html", name=name, run_name=run_name, d=data, f=fields,
                           settings=settings, published=published, auto_status=auto_status,
                           image_names=rpt.IMAGE_NAMES, max_mb=rpt.MAX_ATTACH_MB)


# --------------------------------------------------------------------------- admin
@app.route("/admin/users", methods=["GET", "POST"])
@login_required("admin")
def admin_users():
    if request.method == "POST":
        action = request.form.get("action")
        username = request.form.get("username", "").strip()
        try:
            if action == "create":
                users.create(username, request.form.get("password", ""), request.form.get("role", "viewer"))
                flash(f"User {username} created.", "ok")
            elif action == "role":
                users.set_role(username, request.form.get("role", ""))
                flash(f"Role of {username} updated.", "ok")
            elif action == "password":
                users.set_password(username, request.form.get("password", ""))
                flash(f"Password of {username} reset.", "ok")
            elif action == "delete":
                if username == g.user["username"]:
                    raise ValueError("You cannot delete yourself")
                users.delete(username)
                flash(f"User {username} deleted.", "ok")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("admin_users"))
    return render_template("users.html", users=users.list_users(), roles=users.ROLES)
