# JMeter Control Center — Deployment (engineer computers + Master + 2 Slaves on EC2)

## 1. Architecture

```text
 Engineer computer (each QA)                          AWS account (private subnets, no inbound ports)
 ───────────────────────────                          ──────────────────────────────────────────────────
 JMeter Control Center  http://localhost:8090         ┌──────────── MASTER (EC2) ──────────────┐
  ├─ your clone of the scripts repo (Bitbucket)       │ scripts folder (copied from engineers) │
  ├─ run history, reports, schedules, settings         │ jmeter + run_by_tag.sh                 │
  │                                                    │ .jmcc/active.d/<project> = test slots  │
  │  aws ec2 start/stop/describe ─────────────────────►│ .jmcc/runs/<id>.log  console           │
  │  aws ssm send-command (launch, poll, keys) ───────►│ InfluxDB :8086 · Grafana :3000         │
  │  rsync over ssh ⟶ AWS-StartSSHSession (scripts) ──►└───────┬─────────────────────▲──────────┘
  │  aws ssm start-session (tunnels 3000 / 8086,              RMI 1099 / 50000     metrics :8086
  │                        report download)          ┌────────┴────────┐   ┌────────┴────────┐
  │                                                  │ SLAVE 1          │   │ SLAVE 2          │
  ├─ SMTP (your Gmail + App Password) · Google Chat   │ jmeter-server    │   │ jmeter-server    │
  └─ Confluence / Jira / Bitbucket                    │ scripts folder   │   │ scripts folder   │
                                                      └──────────────────┘   └──────────────────┘
```

* **The site is always available**: it runs on each engineer's computer, the servers are started only when needed
  and are shut down automatically every day at **18:00** (configurable in *Settings → AWS → Daily auto-off*).
* **Everything goes through your AWS CLI session** (the SSM access you already use): no inbound rules, no public IPs.
  SSH is only used *inside* SSM (`AWS-StartSSHSession`), with your own key, which the app installs on the servers.
* **The servers do not need to reach Bitbucket.** Before every run the app copies **the project being run** (plus
  `webapp/bin`) from **your clone** to the Master — and to the Slaves when the run is distributed — with rsync (or a
  tar stream when rsync is missing, e.g. on Windows). Uncommitted changes travel too, so keep your work committed and
  pushed on the *Git* page to share it with the team. (*Settings → AWS → How scripts reach the servers* can switch
  back to the old "servers pull from git" mode where the servers do have repository access.)
* **Up to 3 tests at the same time on the Master, one per project** (*Settings → AWS → Tests at the same time*).
  Each running test holds a slot file `.jmcc/active.d/<project>` with who runs what; the Slaves serve **one**
  distributed test at a time (jmeter-server limit). Copies never touch a project whose test is running.
* **Runs use only the Master by default.** Tick *Distributed on N slaves* in the run dialog when you need them.
* A run keeps going on the Master if you close the app or your laptop sleeps; when the app starts again it
  re-attaches to it, mirrors the rest of the console and downloads the report.

### What a run does
1. **Servers** — starts Master + Slaves if they are stopped (option in the run dialog) and waits for SSM.
2. **Sync** — checks the project / Master / Slaves are free, then copies the project folder from your computer
   (rsync over SSH through SSM; your public key is added to `authorized_keys` of the scripts owner first).
3. **Slaves** — checks `jmeter-server` on port 1099 of each Slave from the Master (restarts it when needed).
4. **Launch** — takes a Master slot (atomic, `flock`) and starts `run_by_tag.sh <tag>` detached
   (`-R <slave IPs>`, `-G` properties only when distributed).
5. **Console** — mirrors the remote log to the run page every ~3 s through SSM.
6. **Report** — packs `results/Ejecucion_…`, downloads it through an SSM tunnel into your clone (the `.jtl` is
   skipped above *Download .jtl up to (MB)*; it stays on the Master — *Reports → Fetch from Master*).
7. **Notify** — e-mail from your account over SMTP (report attached), Google Chat spaces, Jira comment; optionally
   stops the servers (only when no other test is running on the Master).

## 2. Engineer computer setup (each QA, macOS or Windows)

Prerequisites: Python 3.9+, git, AWS CLI v2, the **Session Manager plugin**, and an AWS profile that can use SSM on
the generators (the one you already use). JMeter 5.6.3 locally is optional (to open scripts in the GUI).

**macOS**
```bash
git clone -b New_Repo <repo-url> ~/Documents/Github/Scripts_Repo
~/Documents/Github/Scripts_Repo/webapp/tools/service/install_macos.sh      # service + first login
~/Documents/Github/Scripts_Repo/webapp/tools/launcher/build_macos_app.sh   # app icon in Launchpad / Dock
```

**Windows** (normal user, **not** "Run as administrator")
```powershell
git clone <repo-url> $HOME\Documents\BitBucket\jmeter-framework
```
Then double-click `webapp\tools\service\install_windows.cmd`. It runs the installer with
`-ExecutionPolicy Bypass` for that run only (no "running scripts is disabled" error, no system change), ignores the
Microsoft Store `python` placeholder, offers to install missing Python / Git / AWS CLI / Session Manager plugin with
winget, creates your SSH key and refuses to run from an elevated window.
Creates the Python environment, your login, the background service (Task Scheduler task at logon) and the
**JMeter Control Center** shortcut (Start menu + Desktop) with the icon. Use `-NoService` to only run it manually
(`tools\launcher\jmeter-control-center.bat`). Git for Windows keeps `.sh` files with LF endings (`.gitattributes`).

**Corporate certificate (office network with TLS inspection).** If `aws sso login` fails with
`SSL validation failed ... self-signed certificate in certificate chain`, the installer asks for the corporate
certificate (`.crt`, `.cer` or `.pem`; DER is converted) or takes it directly:
`install_windows.cmd -CaBundle "C:\path\to\corp-ca.crt"`. It copies it to `%USERPROFILE%\.aws\corp-ca.pem` and sets
`ca_bundle` on your AWS profiles (and the one in Settings → AWS), so it works in every window and in the background
service. `$env:AWS_CA_BUNDLE = "..."` only lasts for that PowerShell window and the service never sees it. Manual
equivalent: `aws configure set ca_bundle "C:\path\to\corp-ca.pem" --profile <profile>`.

### Background service and scheduled runs

| | macOS | Windows |
|---|---|---|
| Service | LaunchAgent `com.bancobase.jmeter-control-center` (starts at login, restarts after a crash) | Task Scheduler `\JMeterControlCenter\JMeter Control Center` (at logon, hidden, restarts) |
| Keep awake while a run is close / running | `caffeinate` | `SetThreadExecutionState` |
| Wake from sleep 5 min before each slot | `pmset schedule wake` (optional sudoers rule offered by the installer) | Task Scheduler wake timers (no admin) |
| Logs | `~/Library/Logs/JMeterControlCenter.log`, `webapp/instance/service.log` | `webapp\instance\service.log` |
| Remove | `tools/service/uninstall_macos.sh [--purge] [--remove-data]` (no sudo) | `tools\service\uninstall_windows.cmd [-Purge] [-Elevated] [-RemoveData]` |

Scheduled runs start the load generators themselves (and can stop them at the end). A laptop with the lid closed
on battery may still sleep: keep night-schedule machines on the power adapter. The *Schedules* page shows whether
this computer can fire them (service, keep-awake, wake timers, next slots).

Open **JMeter Control Center**: the first time it creates its Python environment and asks for your login
(local to your computer). Then, in the app:

1. **Settings → AWS**: enable *Run tests on the AWS servers*, AWS profile + region, Master and Slave **instance
   ids**, Linux user and scripts folder on the servers, daily auto-off `18:00` → *Test connection*.
2. **Settings → E-mail**: your address + a Google **App Password** (see below) → *Send test*.
3. **Settings → Google Chat spaces**: add the team space(s) as *default*; project-specific spaces per project.
4. *Atlassian*: your Confluence / Jira / Bitbucket tokens (as before).

The command line equivalent of the launcher: `cd webapp && SR_MODE=aws ./.venv/bin/python run.py`.

**AWS permissions** needed by the engineers' profile (scope them to the generator instances):
`ec2:DescribeInstances`, `ec2:StartInstances`, `ec2:StopInstances`, `ssm:SendCommand` (document
`AWS-RunShellScript`), `ssm:GetCommandInvocation`, `ssm:DescribeInstanceInformation`, `ssm:StartSession`
(documents `AWS-StartPortForwardingSession` **and `AWS-StartSSHSession`**), `ssm:TerminateSession`,
`ssm:ResumeSession`, `sts:GetCallerIdentity`. `ssm:SendCommand` needs both the instances **and** the document
`arn:aws:ssm:<region>::document/AWS-RunShellScript` as resources.

**SSH key (push sync):** the app uses `~/.ssh/id_ed25519` (or the path in *Settings → AWS*). Create one with
`ssh-keygen -t ed25519` if you have none; a key with a passphrase needs `ssh-agent`. Windows needs the built-in
*OpenSSH Client* (Settings → Optional features); without rsync the app streams a tar.gz instead.

**E-mail with a Google App Password (no OAuth client, no admin rights):** turn on 2-Step Verification in your
Google account → <https://myaccount.google.com/apppasswords> → create "JMeter Control Center" → in *Settings → E-mail*
enter host `smtp.gmail.com`, port `587`, `starttls`, your address as user and the 16-character password (spaces are
removed automatically). If the page says App Passwords are not available, your Workspace admin blocks them.

## 3. Servers setup (Master and both Slaves)

* **SSM agent online** and an instance profile with `AmazonSSMManagedInstanceCore` (already the case).
* **Same scripts folder on the three servers** (e.g. `/mnt/jmeter/JMeter_Scripts/jmeter-framework`), writable by
  the Linux user set in *Settings → AWS* (e.g. `ubuntu`). It does not need to be a git clone and the servers do not
  need access to Bitbucket. Never edit files there: they are overwritten by the next copy (*Servers → Mirror*
  also deletes files that do not exist on your computer, except results and running projects).
* **`sshd` listening on port 22 (localhost is enough) and `rsync`** (`sudo apt-get install -y rsync`) on the three
  servers; `tar` is the fallback. The app adds each engineer's public key to `~/.ssh/authorized_keys` of the scripts
  owner through SSM. **Offboarding:** remove the person's key line from that file on the three servers.
* `flock` and `ss` (util-linux / iproute2, present on Ubuntu) on the Master: test slots and graceful stop of one
  test without touching the others.
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

* **E-mail**: sent **from the engineer's own account over SMTP** (Gmail: `smtp.gmail.com` + App Password) to
  `qaperformance@bancobase.com`, the project's staff (project → Settings) and the extra recipients of the run. The
  end-of-run e-mail attaches the HTML report (`.zip`, up to 15 MB) because links to `localhost` only work on the
  sender's computer. TLS is mandatory when a password is used.
* **Google Chat**: incoming webhooks. When you create the webhook, name it *JMeter Control Center* and use the
  Control Center icon as avatar URL: `https://raw.githubusercontent.com/israelrizo/Scripts_Repo/main/webapp/srapp/static/brand/chat-webhook-icon.png`
  (`webapp/srapp/static/brand/chat-webhook-icon.png`, 512×512, works with Chat's circular crop). *Default* spaces get every run; others are picked per project. Start and end
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

## 9b. Team history, shared settings and performance bugs

Each engineer runs their own Control Center, so the Master is where the team meets:

* **Identity** — runs are attributed to the engineer's **AWS SSO e-mail**, taken from the last part of the
  assumed-role ARN (`…/AWSReservedSSO_<set>_<hash>/<e-mail>`); the rest of the ARN is never stored or shown.
* **Team history** — every execution launched on the Master is written to `<remote_root>/.jmcc/history/<run>.json`
  (who, computer, project, tag, script, props, slaves, status, verdict, p95 / error %, Jira bug). *Executions →
  Team (Master)* lists them with filters by project and engineer; *Fetch* downloads a report on demand. Result
  folders on the Master without a record (older runs) appear as *folder only*. The Slaves keep no results: everything
  a distributed test produces ends on the Master.
* **Automatic sync** — after *aws sso login* (if the Master is up) and every *Start servers*, the app pulls new
  records and, optionally, the reports of the last N days (**HTML only**, the `.jtl` stays on the Master). *Settings
  → Team sharing*. The history is cached locally, so it stays visible with the Master off.
* **Team settings** — an admin saves the New Relic key and the default Google Chat space (e.g. *Performance
  Testing Team*) once, then *Settings → Team sharing → Publish to the team*. They are stored in
  `.jmcc/shared/team.json` on the Master (mode 600, scripts owner) and every installation applies them on its next
  sync. Never commit these values to the repository.
* **Project profiles** — everything a project needs so whoever picks it up continues with the same setup, in
  `.jmcc/projects/<project>.json` on the Master, pulled on every sync. Each section keeps who changed it and when,
  and the last change wins per section (two engineers editing different sections at the same time keep both):
  * *Acceptance criteria* (*project → Settings*): presets by layer — **Backend p95 ≤ 1000 ms**, **Middleware
    p95 ≤ 5000 ms**, **Front end p95 ≤ 10000 ms**, all with **error rate ≤ 5 %** — or custom values. Only p95 and
    error rate are evaluated (average and throughput are no longer criteria). Plus application, scenario, scope,
    base URL and tool for the reports.
  * *Baselines* (comparison baseline per script) and *project settings* (staff e-mails, Jira board, pinned New
    Relic services, Grafana dashboard, extra Chat spaces — matched by name on each computer).
  * *Confluence publications*: merged, so everyone sees which executions were already published and where.
  Edits made with the Master off are shared on the next sync; data that existed only on a computer before sharing is
  kept as `*.local-backup.json` when the team's version replaces it.
* **Team schedules** — each installation publishes its schedules to `.jmcc/schedules/` and *Schedules* shows the
  other engineers' ones (read-only: they fire only on their owner's computer), warning when one of yours starts
  within 2 h of a team schedule on the same project or the Slaves.
* **Infrastructure** — *Publish to the team* also shares Master/Slaves ids, region, paths, ports, auto-off,
  `max_runs`, Grafana, tunnels, time zone and the Jira board for bugs. A new engineer uses *Settings → AWS → Import
  setup* with the `jmcc-setup.json` an admin downloads there (no keys, tokens or passwords), signs in with AWS SSO,
  and the first sync brings the rest.
* **Performance bugs** — an execution that ends **finished or stopped** (a graceful stop still builds the report)
  with verdict **INSATISFACTORIA** offers **Create Jira bug** on its run page, and **🐞 Bug** in *Executions → Team*
  for any engineer's execution (after *Fetch*, the report must be on your computer). It opens the non-functional bug
  template prefilled from the run (scenario, criteria, results by transaction, evidence, HTML report attached);
  *Reportado por* is whoever files it, and the evidence says who launched the run. The engineer completes *Contexto*
  and *Impacto* and submits with their own Jira credentials. The **parent epic** (e.g. `PQA-298`) is required: the app checks that it exists and is an epic, links the bug to it (`parent`, or the legacy *Epic Link* field on older company-managed projects) and remembers it per project (*project → Settings → Parent epic for bugs*, shared with the team). The link is stored per execution and shared through the
  project profile, so every installation shows the bug and nobody files it twice. Board: *Settings → Jira →
  Performance bugs* (default project key, issue type, labels), overridable per project (*project → Settings → Jira
  project for bugs*).

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

## 12. Updating an existing installation

Step-by-step guide in Spanish (install, every credential, daily use, uninstall / reinstall):
`webapp/docs/Instalacion_y_Credenciales.md`, with the narrated video *JMeter_Control_Center_Tutorial.mp4*.


Every engineer, on their own computer (macOS or Windows). Settings, users, run history and reports in
`webapp/instance/` are kept.

1. **Stop the app**: close the launcher window (Ctrl+C). If the background service is installed it restarts the app
   by itself in step 4, no need to stop it.
2. **Get the new version** in your clone of the scripts repository (the one the service was installed from):
   `git pull` on the branch where the Control Center was merged — or, with the update package you received, from
   the repository root: `tar -xzf jmcc-update.tar.gz` (macOS and Windows 10+; it overwrites only Control Center
   files under `webapp/`), then commit & push them so the other engineers get the same version.
3. **Python packages** (only if `webapp/requirements.txt` changed):
   macOS `webapp/.venv/bin/pip install -r webapp/requirements.txt` · Windows
   `webapp\.venv\Scripts\pip install -r webapp\requirements.txt`.
4. **Restart**:
   * macOS with the service: `launchctl kickstart -k gui/$(id -u)/com.bancobase.jmeter-control-center`
     (**never with sudo**; to reinstall the service run `webapp/tools/service/install_macos.sh`, also without sudo).
   * Windows: double-click `webapp\tools\service\install_windows.cmd` again (repairs and restarts the service).
   * Without the service: open *JMeter Control Center* again.
5. **Check once** (admin): *Settings → AWS* → *How scripts reach the servers* = **Copy from this computer**, SSH key
   path (empty = `~/.ssh/id_ed25519`), *Tests at the same time* = 3 → **Save** → **Test connection** (must show
   *Master via SSH (push sync): …*). *Settings → E-mail*: your address + App Password → **Send test**.
6. **First copy**: *Servers* → **Copy all projects to the servers** (adds your key to the servers and copies every
   project; the next runs only copy the project being run).

What changes for the user: runs are Master-only unless *Distributed* is ticked; up to 3 projects can run at the same
time (one execution per project); the servers receive the scripts from the engineer's computer; e-mail uses the App
Password (the Gmail OAuth linking was removed). The bug also carries the **5 slowest transactions** (requests, error %, avg, p95, p99, max) and two charts, **response time** (average and p95) and **errors and hits per second** — the same charts as the run page —, attached as PNG and shown in the description. Their data comes from InfluxDB for the run window; when InfluxDB is not reachable it falls back to the JMeter HTML report (`html_report/content/js/graph.js`).