# JMeter Control Center — Deployment (engineer computers + Master + 2 Slaves on EC2)

## 1. Architecture

```text
 Engineer computer (each QA)                          AWS account (private subnets, no inbound ports)
 ───────────────────────────                          ──────────────────────────────────────────────────
 JMeter Control Center  http://localhost:8090         ┌──────────── MASTER (EC2) ──────────────┐
  ├─ clone of the scripts repo (origin = source        │ git clone of the scripts repo          │
  │   of truth: commit & push from the Git page)       │ jmeter + run_by_tag.sh                 │
  ├─ run history, reports, schedules, settings         │ .jmcc/active  = who is running (lock)  │
  │                                                    │ .jmcc/runs/<id>.log  console           │
  │  aws ec2 start/stop/describe ─────────────────────►│ InfluxDB :8086 · Grafana :3000         │
  │  aws ssm send-command (git pull, launch, poll) ───►└───────┬─────────────────────▲──────────┘
  │  aws ssm start-session (tunnels 3000 / 8086,              RMI 1099 / 50000     metrics :8086
  │                        report download)          ┌────────┴────────┐   ┌────────┴────────┐
  │                                                  │ SLAVE 1          │   │ SLAVE 2          │
  ├─ Gmail API (your account) · Google Chat webhooks  │ jmeter-server    │   │ jmeter-server    │
  └─ Confluence / Jira / Bitbucket                    │ same git clone   │   │ same git clone   │
                                                      └──────────────────┘   └──────────────────┘
```

* **The site is always available**: it runs on each engineer's computer, the servers are started only when needed
  and are shut down automatically every day at **18:00** (configurable in *Settings → AWS → Daily auto-off*).
* **Everything goes through your AWS CLI session** (the SSM access you already use): no SSH keys, no inbound rules,
  no public IPs, nothing listening on the servers except what JMeter itself needs.
* **The repository is the single source of truth.** Uploads, new projects and tag edits happen in your local clone;
  a run is refused until they are committed and pushed (*Git* page). Before every run the app fast-forwards the
  Master **and** the Slaves to the same commit and verifies it.
* **One test at a time on the Master**, across all engineers: the Master keeps a lock (`.jmcc/active`) with who is
  running what; the Servers page shows it and new runs wait.
* A run keeps going on the Master if you close the app or your laptop sleeps; when the app starts again it
  re-attaches to it, mirrors the rest of the console and downloads the report.

### What a run does
1. **Servers** — starts Master + Slaves if they are stopped (option in the run dialog) and waits for SSM.
2. **Sync** — `git fetch` + fast-forward to `origin/<branch>` on every server; aborts if one diverges.
3. **Slaves** — checks `jmeter-server` on port 1099 of each Slave from the Master (restarts it when needed).
4. **Launch** — takes the Master lock and starts `run_by_tag.sh <tag>` detached (`-R <slave IPs>`, `-G` properties).
5. **Console** — mirrors the remote log to the run page every ~3 s through SSM.
6. **Report** — packs `results/Ejecucion_…`, downloads it through an SSM tunnel into your clone (the `.jtl` is
   skipped above *Download .jtl up to (MB)*; it stays on the Master — *Reports → Fetch from Master*).
7. **Notify** — e-mail from your Gmail (report attached), Google Chat spaces, Jira comment; optionally stops the servers.

## 2. Engineer computer setup (each QA, macOS or Windows)

Prerequisites: Python 3.9+, git, AWS CLI v2, the **Session Manager plugin**, and an AWS profile that can use SSM on
the generators (the one you already use). JMeter 5.6.3 locally is optional (to open scripts in the GUI).

**macOS**
```bash
git clone -b New_Repo <repo-url> ~/Documents/Github/Scripts_Repo
~/Documents/Github/Scripts_Repo/webapp/tools/service/install_macos.sh      # service + first login
~/Documents/Github/Scripts_Repo/webapp/tools/launcher/build_macos_app.sh   # app icon in Launchpad / Dock
```

**Windows** (PowerShell, no administrator rights needed)
```powershell
git clone -b New_Repo <repo-url> $HOME\Documents\Github\Scripts_Repo
powershell -ExecutionPolicy Bypass -File $HOME\Documents\Github\Scripts_Repo\webapp\tools\service\install_windows.ps1
```
Creates the Python environment, your login, the background service (Task Scheduler task at logon) and the
**JMeter Control Center** shortcut (Start menu + Desktop) with the icon. Use `-NoService` to only run it manually
(`tools\launcher\jmeter-control-center.bat`). Git for Windows keeps `.sh` files with LF endings (`.gitattributes`).

### Background service and scheduled runs

| | macOS | Windows |
|---|---|---|
| Service | LaunchAgent `com.bancobase.jmeter-control-center` (starts at login, restarts after a crash) | Task Scheduler `\JMeterControlCenter\JMeter Control Center` (at logon, hidden, restarts) |
| Keep awake while a run is close / running | `caffeinate` | `SetThreadExecutionState` |
| Wake from sleep 5 min before each slot | `pmset schedule wake` (optional sudoers rule offered by the installer) | Task Scheduler wake timers (no admin) |
| Logs | `~/Library/Logs/JMeterControlCenter.log`, `webapp/instance/service.log` | `webapp\instance\service.log` |
| Remove | `tools/service/uninstall_macos.sh` | `tools\service\uninstall_windows.ps1` |

Scheduled runs start the load generators themselves (and can stop them at the end). A laptop with the lid closed
on battery may still sleep: keep night-schedule machines on the power adapter. The *Schedules* page shows whether
this computer can fire them (service, keep-awake, wake timers, next slots).

Open **JMeter Control Center**: the first time it creates its Python environment and asks for your login
(local to your computer). Then, in the app:

1. **Settings → AWS**: enable *Run tests on the AWS servers*, AWS profile + region, Master and Slave **instance
   ids**, Linux user and scripts folder on the servers, daily auto-off `18:00` → *Test connection*.
2. **Settings → E-mail → Gmail account**: OAuth client (once per team, see below) → *Link my Gmail account*.
3. **Settings → Google Chat spaces**: add the team space(s) as *default*; project-specific spaces per project.
4. *Atlassian*: your Confluence / Jira / Bitbucket tokens (as before).

The command line equivalent of the launcher: `cd webapp && SR_MODE=aws ./.venv/bin/python run.py`.

**AWS permissions** needed by the engineers' profile (scope them to the generator instances):
`ec2:DescribeInstances`, `ec2:StartInstances`, `ec2:StopInstances`, `ssm:SendCommand` (document
`AWS-RunShellScript`), `ssm:GetCommandInvocation`, `ssm:DescribeInstanceInformation`, `ssm:StartSession`
(document `AWS-StartPortForwardingSession`), `ssm:TerminateSession`, `sts:GetCallerIdentity`.

**Gmail OAuth client (once, Google Cloud admin of the team):** APIs & Services → enable *Gmail API* → OAuth consent
screen (Internal) → Credentials → *OAuth client ID* → type **Web application** → authorized redirect URI
`http://localhost:8090/oauth/google/callback`. Share the client ID/secret with the team; each engineer links their
own account (scope `gmail.send` only: the app can send, not read).

## 3. Servers setup (Master and both Slaves)

* **SSM agent online** and an instance profile with `AmazonSSMManagedInstanceCore` (already the case).
* **Same scripts path on the three servers**: a git clone of the repository at
  `/mnt/jmeter/JMeter_Scripts/jmeter-framework`, owned by the Linux user set in *Settings → AWS* (e.g. `ubuntu`),
  on the same branch. Never edit files there: the app fast-forwards them before each run (*Servers → Force sync*
  discards local changes).
* **Git read access to the repository from the servers** for that user (deploy key / read-only token / credential
  helper), so `git fetch` works non-interactively. Test with `sudo -u ubuntu git -C <path> fetch`.
* **`jmeter` on the login PATH** of that user on the Master, and `python3` (used to hand reports to the tunnel).
* SSM runs commands as root; the app switches to the scripts owner with `sudo -u <user> -H bash -l`.
* **Slaves**: `jmeter-server` as a service (`deploy/jmeter-server.service`); the app can restart it with the command
  in *Settings → AWS* when a Slave does not answer on 1099.
* InfluxDB and Grafana stay on the Master, reached from your computer through SSM tunnels (Servers page).

## 4. Slaves setup (both)

1. Same JMeter version **and the same plugins** as the Master (incl. `lib/ext/jmeter-plugins-*`). A plugin missing on a slave makes the remote engine fail to load the plan.
2. `server.rmi.ssl.disable=true` on **Master and Slaves** (or generate `rmi_keystore.jks` with
   `bin/create-rmi-keystore.sh` and copy it to all three). Mismatches give "Connection refused / SSL" errors.
3. Fixed RMI ports so the Security Group is small: `server_port=1099`, `server.rmi.localport=50000`
   (see `deploy/jmeter-server.service`, set `java.rmi.server.hostname` to each slave's private IP).
   On the Master also set `client.rmi.localport=60000` in `user.properties` (slaves call back to it).
4. Security Groups (all private, SG-to-SG references):

   | From → To | Ports | Purpose |
   |-----------|-------|---------|
   | Master → Slaves | 1099, 50000 | start/stop remote engines |
   | Slaves → Master | 60000-60002 | sample results back to the client |
   | Slaves → Master | 8086 | Backend Listener → InfluxDB |
   | Master → Slaves | 22 | optional, *Sync to slaves* (rsync) |

5. The scripts folder is a git clone at the same absolute path on every server (see §3); the app syncs it before each run.
6. **CSV paths in distributed mode:** a relative path such as `data/usuarios.csv` is resolved by each slave
   against the folder where `jmeter-server` was started, not against the project, so it fails on the slaves.
   Use `${__P(data_dir,data)}/usuarios.csv` in the CSV Data Set Config: local/CLI runs keep working
   (`data_dir` defaults to `data`) and web runs pass `-Gdata_dir=<project>/data` automatically, an absolute
   path that exists on every node.

The dashboard shows each slave as **up/down** by probing its RMI port.

## 5. Things that will bite you in distributed mode (found while reading the branch)

| # | Finding | Impact | Fix |
|---|---------|--------|-----|
| 1 | Every Backend Listener uses `http://localhost:8086/write?db=…` | With `-R`, each **slave** runs the listener and writes to *its own* localhost → Grafana/Live monitor stay empty | Use the Master's private IP, ideally as a property: `${__P(influx_url,http://localhost:8086/write?db=BlackList_QA)}` and pass `-Ginflux_url=http://10.0.1.10:8086/write?db=BlackList_QA` |
| 2 | Two slaves write identical series (same `application`, `transaction`, timestamp) | InfluxDB keeps the last point → counts are halved, not summed | Add a Backend Listener argument `TAG_host` = `${__machineName()}`. The Live monitor already sums per `host`. |
| 3 | Properties in `EXTRA_ARGS` use `-J` | `-J` only reaches the Master; slaves evaluate `${__P(threads)}` with their defaults | The web app's shim mirrors every `-J` as `-G` automatically. For CLI runs use `-G`. |
| 4 | Each slave runs the **full** thread count | 2 slaves ⇒ 2× the load you designed | Divide threads by the number of slaves (or use `-Gthreads=<total/2>`). The run dialog reminds you. |
| 5 | CSV Data Set Config is read from each slave's disk | Missing/old files on slaves ⇒ `FileNotFoundException`, or both slaves using the **same** rows (duplicate logins) | Use *Sync to slaves* before runs; split user CSVs per slave if the same user can't log in twice. |
| 6 | Some JMX reference Windows paths (`C:\Users\emancilla\…\squads-jmeter-framework\data\…`, `C:/Users/…/backoffice-jmeter-framework/data/mock_clientes_empresas.csv`) and `/CSV/usuarios_baseinet_enero25` | Fails on Linux generators | Use `data/<file>.csv` relative paths. Uploads through the UI now warn about this. |
| 7 | `run_by_tag.sh` (all 9 projects) ignores extra CLI args, although the docs show `./run_by_tag.sh <tag> -JP_DNS=…` | Overrides in the docs silently do nothing | Template now forwards `"$@"`. The web app works anyway (shim). Port the 3-line change to existing projects when convenient. |
| 8 | `baseinet`: tag `opt5_MetodosGenerales_QA2` defined twice; `motordecorreos`: tag `bow_scalability_test` points to a non-existent script (copy from backoffice) | Wrong script / failure | Both are flagged in the Tags tab (`duplicate`, `missing file`). |
| 9 | `run_test.sh` uses `ipconfig getifaddr` (macOS) and hardcodes `"BDT"` as Drive folder in every project; READMEs/docs of blacklist say "BDT" | Wrong link / folder on Linux | Fixed in the new template (`hostname -I`, `{{APP_NAME}}`). |
| 10 | `.gitignore` rule `data/usuarios_backend_baseinet_*.csv` is anchored to the repo root, so it matches nothing; files such as `Usuarios_BBD_UserPassToken.csv` (user/password/token) are committed | Credentials in Git history | Use `**/data/usuarios_*.csv`-style rules, rotate the test credentials, keep only `*.sample.csv` in Git. |
| 11 | `jmeter.log` files committed in each project | Noise in diffs | Template writes `-j results/<run>/jmeter.log`; add `*/jmeter.log` to `.gitignore`. |

## 6. Operating model

* **Servers page**: state of each instance, start / stop, who holds the Master, health check (disk, jmeter, git
  commit, jmeter-server reachability), repository sync, and the **tunnels** (Grafana 3000, InfluxDB 8086 and any
  custom port) — each opens `localhost:<port>` on your computer.
* **Daily auto-off at 18:00**: the run dialog and the Servers page show the time left; a run still going at
  18:00 is marked *interrupted* (its partial results stay on the Master). Schedule long tests earlier.
* **Stop vs Kill**: *Stop* sends JMeter's `Shutdown` (the HTML report is still generated); *Kill* terminates the
  process tree on the Master.
* **AWS session expired** during a run: the test continues on the Master; the console shows a notice — click
  *AWS SSO login* (Servers page or Settings → AWS) and monitoring resumes where it was.
* **Roles** are per computer (local users); every server action is still attributed to the engineer's AWS identity.
* **Sizing**: JMeter `-Xmx` ≈ 50-70 % of RAM on each node, `ulimit -n 65536`, generator CPU < 80 %.

## 6b. New Relic (shared account)

*Settings → New Relic*: account id, region and a **User API key** (`NRAK-…`, read-only use). For each script the app
takes the hosts and request paths of the JMX and asks New Relic which APM services received that traffic
(`Transaction` events: `request.headers.host` / `request.uri`, last 24 h). Confirm them once per project
(*Tags → New Relic → Pin*). At the end of every run it reads, for the run window: throughput, average and p95,
error %, database and external time, top transactions, error classes and the CPU/memory of the linked hosts
(`SystemSample.apmApplicationNames`). Shown on the run page and included in the e-mail, Chat, Jira comment and the
*Recursos Servidor* section of the Confluence report. If the APM agent behind a gateway does not record
`request.uri`, pin the services manually.

## 6c. Script quality review

Rules R01–R20 of the scripting guide (`docs/Guia_Scripting_JMeter_Control_Center.md`). Run on upload, in the
*Quality* tab (feedback downloadable as Markdown), on the *Git* page before committing (errors require explicit
confirmation) and by the GitHub workflow `.github/workflows/jmx-quality.yml` on every push / pull request that
changes a `.jmx` (results in the job summary). CLI: `cd webapp && python -m srapp.quality [paths]`.

## 7. Notifications

* **E-mail**: sent **from the engineer's own Gmail** (linked account) to `qaperformance@bancobase.com`, the project's
  staff (project → Settings) and the extra recipients of the run. The end-of-run e-mail attaches the HTML report
  (`.zip`, up to 15 MB) because links to `localhost` only work on the sender's computer. An SMTP server can still be
  used instead (*Settings → E-mail → Send with*).
* **Google Chat**: incoming webhooks. *Default* spaces get every run; others are picked per project. Start and end
  messages of a run go to the same thread.

## 8. Confluence reports

* Publishing happens from your computer, so it only needs your normal internet access.
  Confluence Data Center inside the VPN/VPC works the same way with a Personal Access Token.
* Set `SR_CONFLUENCE_ALLOWED_HOSTS` (e.g. `.atlassian.net`) so user-provided URLs cannot point the Master anywhere else.
* Each user publishes with **their own** token, so Confluence permissions and page history show the real author.
* Tokens are encrypted at rest with `webapp/instance/confluence.key`; losing that file only means users must re-enter tokens.
* Charts in the report come from InfluxDB: fix findings #1 and #2 above (listener URL and `TAG_host`) before relying on them for distributed runs.

## 9. Jira, Bitbucket and shift-left


* **Jira** — each engineer sets the Jira URL (and token, or reuses the Confluence token) under *Atlassian*. The
  ticket typed in the run dialog / schedule gets a comment with the results, SLA verdict and links at the end.
* **Bitbucket (scripts repo)** — *Git* page: pull, and commit & push the changes made in the UI (uploads, tags,
  new projects) authored by the web user. Uses the Master's existing git credentials for `origin`.
* **Shift-left (application repos, e.g. baseinet)** — *project → Settings*: application repository
  (`workspace/repo`), tag, users, duration and SLA → **Open PR in Bitbucket**. The PR adds `perf/perf-gate.sh`
  (+ a custom pipeline if the repo has no `bitbucket-pipelines.yml`). One-time per repo:
  1. The gate calls the Control Center API, which now runs on an engineer's computer: install the Bitbucket self-hosted
     runner (Linux Shell, label `jmeter-master`) on a machine where the Control Center runs permanently in AWS mode
     (e.g. a small always-on EC2 in the same account), or run the gate manually from a laptop. See §10.
  2. Create an API token (*Account → API tokens*, operator user) and save it as a **secured** repository
     variable `JMCC_TOKEN` (optional `JMCC_JIRA`).
  The step fails the pipeline when the run fails or the p95 / error % SLA is not met.
* **Scheduler** — runs inside the app on your computer: schedules fire only while the app is open and the computer
  awake. Scheduled runs start the servers and can stop them at the end. Timezone: *Settings → Application*.

## 10. Legacy: Control Center hosted on the Master

The previous model (app as a systemd service on the Master, reached through an SSM port forward to 8090) still works:
leave *Settings → AWS* disabled and use `deploy/install_master.sh` + `deploy/jmeter-control-center.service`. In that
mode runs execute locally on the Master and slaves are reached by IP (`SR_REMOTE_HOSTS`).

## 11. Live monitor troubleshooting

*Settings → InfluxDB diagnostics* runs every query of the monitor one by one and shows InfluxDB's exact answer
(connection, databases, measurements, applications, last sample, each panel). In AWS mode the queries go through the
InfluxDB SSM tunnel, which opens by itself while the Master is running. Typical causes:

| Symptom | Cause / fix |
|---------|-------------|
| `InfluxDB tunnel: The Master is stopped` | Start the servers (Servers page); metrics live on the Master's InfluxDB |
| `Session Manager plugin` / port errors | Install the Session Manager plugin; free local port 28086/8086 (Settings → tunnels) |
| `HTTP 401` | InfluxDB auth enabled → `SR_INFLUX_USER` / `SR_INFLUX_PASSWORD` (1.x) or `SR_INFLUX_TOKEN` (2.x) |
| `HTTP 404` on `/query` | InfluxDB 2.x without a DBRP mapping for the database |
| Applications list empty | Backend Listener writing to another InfluxDB (slaves' `localhost`, see §4 #1) or different measurement |
| Last sample is old | Nothing is writing: check the listener URL / port 8086 from the slaves |
| Users panel 0 while others work | Fixed in this version (the outer sub-query had no time range → InfluxDB 1.x HTTP 500) |
