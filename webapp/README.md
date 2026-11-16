# JMeter Control Center (Scripts_Repo web UI)

Web front end for the `*-jmeter-framework` projects of this repository. It runs **on each performance engineer's
computer** (`http://localhost:8090`) and drives the JMeter **Master + Slaves on EC2 through the AWS CLI / SSM**:
it starts the servers only when needed (they shut down automatically at 18:00), keeps them in sync with the
repository, launches the tests on the Master, streams the console and downloads the reports.

| Feature | Where |
|---------|-------|
| Browse every client project, its tags (`run_by_tag.sh`), scripts, data files | Projects → project |
| Run a tag (optional `-J/-G` overrides, distributed on the slaves), live console, graceful stop / kill | Tags → ▶ Run |
| Upload `.jmx` (validated, scanned for bad CSV paths) into any `tests/` sub-folder, register its tag | Scripts |
| Upload CSV/TXT/… to `data/`, rsync `data/` + `tests/` to the slaves | Data files · Sync to slaves |
| Create a new project with the standard structure (template from `blacklist-jmeter-framework`) | Projects → ＋ New project |
| Live charts from InfluxDB: virtual users, hits/s, errors/s, avg & p95, requests, errored requests, error %, response-code pie, p95 per transaction | Run page · Live monitor |
| HTML reports of every execution, `.tar.gz` download, comparison of runs vs. a baseline | Reports · Compare |
| **Confluence results report** ("Plantilla Reporte de Resultados") pre-filled from the HTML report + InfluxDB, charts as images, zipped report/.jmx/log attached, per-user API token | Reports → Confluence |
| **Schedules**: once / daily / weekly per tag, timezone-aware, waits if the generator is busy | Schedules |
| **Server check**: resolves the hosts a script calls (variables + `__P()` defaults) and tests DNS → TCP → TLS → HTTP | Tags → Servers |
| **E-mail quick report** at run start / end to qaperformance@bancobase.com + project staff (+ mock preview) | Settings → SMTP · project → Settings |
| **Jira**: ticket per run (typed in the run dialog), results comment posted when the run ends | Run dialog · Atlassian |
| **Bitbucket**: commit & push / pull of this repo from the UI; **1-click shift-left** PR in the app repo | Git · project → Settings |
| **CI API** (`/api/v1/runs`, Bearer tokens) used by the shift-left performance gate | Account → API tokens |
| Grafana deep links (project dashboard + application + run window) | Run · Reports · Monitor |
| Comparison vs a pinned **baseline**, regression threshold, Δ% charts, trend, CSV | Reports → Compare |
| Optional **2FA** (TOTP) per user, admin reset | Account |
| Desktop **launcher** with icon that opens the SSM tunnels (8090 + Grafana) | `tools/launcher/` |
| **Servers**: start / stop Master + Slaves (EC2), state, SSM, auto-off countdown, health check, who holds the Master | Servers |
| **Remote runs** on the Master via SSM: repo sync on every server, live console, report download, optional auto start / stop | Tags → ▶ Run |
| **Tunnels** (SSM port forwarding) to Grafana 3000, InfluxDB 8086 or any port; Live monitor opens InfluxDB by itself | Servers |
| **Repository as source of truth**: runs blocked until local changes are committed & pushed; sync / force-sync servers | Git · Servers |
| E-mail **from your own Gmail** (OAuth, send-only) with the HTML report attached | Settings → E-mail |
| **Google Chat** messages (start / end, same thread) to default spaces + per-project spaces | Settings → Google Chat |
| Users with roles `admin` / `operator` / `viewer` | Users |

## Quick start

```bash
cd webapp/tools/launcher && ./build_macos_app.sh     # or ./install_linux_desktop.sh
```

Open **JMeter Control Center** (creates the Python environment and your login the first time), then
*Settings → AWS* (profile, region, instance ids) and *Settings → E-mail* (link your Gmail). Full guide:
**[DEPLOYMENT.md](DEPLOYMENT.md)**. Without the launcher:

```bash
cd webapp
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python manage_users.py add <you> --role admin
SR_MODE=aws ./.venv/bin/python run.py      # → http://localhost:8090
```

## How runs work

**AWS mode** (default with the launcher): the app checks that your clone is committed and pushed, starts the servers
if needed, fast-forwards Master and Slaves to the same commit with `aws ssm send-command`, verifies `jmeter-server` on
the Slaves, takes the Master lock and starts `run_by_tag.sh <tag>` detached on the Master. The console is mirrored
every few seconds; at the end the result folder is downloaded through an SSM tunnel into your clone, notifications
go out, and the servers can be stopped. Closing the app does not stop the test; the app re-attaches on next start.

On the Master the project's own `run_by_tag.sh` runs unchanged with `webapp/bin` first on `PATH`. Its `jmeter` shim
calls the real JMeter and appends the UI overrides, `-Jdata_dir=<project>/data`, and in distributed mode
`-R <slave IPs>` with every `-J` mirrored as `-G`.

**Local mode** (*Settings → AWS* disabled): the same, executed on the machine where the app runs (legacy setup with
the app installed on the Master).

## Layout

```text
webapp/
├── run.py                # waitress server (SR_HOST:SR_PORT)
├── manage_users.py       # CLI user management
├── bin/jmeter            # PATH shim (distributed + overrides)
├── srapp/                # Flask app: app.py, projects.py, runner.py, influx.py, users.py, report.py, ...
│                         #   aws.py (EC2/SSM), remote_run.py (remote pipeline), tunnels.py, google.py (Gmail/Chat)
├── project_template/     # base for new *-jmeter-framework folders
├── tools/launcher/       # laptop launcher (macOS app / Linux menu entry) with icon
├── deploy/               # jmeter-server unit for the slaves (+ legacy Master install)
└── instance/             # (git-ignored, per computer) users, settings, encrypted tokens, run logs
```

## Confluence report

1. Each user: **Confluence** (top bar) → URL, type (Cloud: e-mail + API token · Data Center: PAT), default space / parent page → *Test connection*.
2. Reports → an execution → **Confluence**. The form follows the *Plantilla Reporte de Resultados* section by section:
   * header, *Resultados Generales* and the per-transaction table come from `html_report/statistics.json`;
   * peak users, throughput, errors/s, response-code distribution and p95 per transaction come from InfluxDB for the execution window, rendered as PNG charts;
   * acceptance criteria (avg, p95, error %, TPS) set the **SATISFACTORIA / INSATISFACTORIA** status macro automatically (overridable);
   * all narrative sections are drafted in Spanish from the measured values and stay editable (*Regenerar textos* redrafts them).
3. *Vista previa* shows the page exactly as it will look; *Publicar* creates the page (or a new version of the same page on re-publish) and uploads charts, the zipped HTML report, the .jmx and the console log as attachments.

Per-project defaults (app name, scope rows, criteria, stakeholders, space/parent) are remembered after each publish.
Tokens are encrypted with `instance/confluence.key` (Fernet); back up that file together with `instance/confluence/`.
