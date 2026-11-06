# JMeter Control Center (Scripts_Repo web UI)

Web front end for the `*-jmeter-framework` projects of this repository. Runs on the load-generator
**Master** at `127.0.0.1:8090` and is reached through an SSM port forward.

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
| Users with roles `admin` / `operator` / `viewer` | Users |

## Quick start (local)

```bash
cd webapp
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python manage_users.py add admin --role admin
SR_JMETER_BIN=$(which jmeter) ./.venv/bin/python run.py      # → http://127.0.0.1:8090
```

Configuration is environment-based, see `config.env.example`. Production install, slave setup and the
distributed-mode checklist are in **[DEPLOYMENT.md](DEPLOYMENT.md)**.

## How runs work

The app executes the project's own `bash run_by_tag.sh <tag>` (nothing is re-implemented), with
`webapp/bin` prepended to `PATH`. Its `jmeter` shim calls the real JMeter and, only for web runs:

* appends the UI overrides (`SR_EXTRA_PROPS`, validated `-Jname=value` tokens);
* in distributed mode adds `-R <slaves>` and mirrors every `-J` as `-G` so the slaves receive them.

So existing projects work unchanged, and CLI/Jenkins runs behave exactly as before.

## Layout

```text
webapp/
├── run.py                # waitress server (SR_HOST:SR_PORT)
├── manage_users.py       # CLI user management
├── bin/jmeter            # PATH shim (distributed + overrides)
├── srapp/                # Flask app: app.py, projects.py, runner.py, influx.py, users.py,
│                         #   confluence.py (client + encrypted tokens), report.py (template builder)
├── project_template/     # base for new *-jmeter-framework folders
├── deploy/               # systemd units + installer
└── instance/             # (git-ignored) users.json, secret key, run logs, backups, trash
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
