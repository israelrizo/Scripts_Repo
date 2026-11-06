# JMeter Control Center — Deployment on the Load Generators (Master + 2 Slaves, EC2 + SSM)

## 1. Target architecture

```text
 Your laptop                                   AWS VPC (private subnets, no public IPs)
 ───────────                                   ─────────────────────────────────────────────────────────
 browser → http://localhost:8090               ┌──────────────── MASTER (EC2) ────────────────┐
     │                                         │  JMeter Control Center  127.0.0.1:8090        │
     │  aws ssm start-session                  │   ├─ runs run_by_tag.sh (per project folder)  │
     └──── AWS-StartPortForwardingSession ────►│   ├─ jmeter shim adds  -R slave1,slave2 + -G  │
           (8090 → 8090, no inbound SG rule)   │   ├─ reads InfluxDB :8086  (live charts)      │
                                               │   └─ serves results/*/html_report             │
                                               │  InfluxDB :8086 · Grafana :3000               │
                                               │  /mnt/jmeter/JMeter_Scripts/jmeter-framework  │
                                               └──────┬──────────────────────────▲─────────────┘
                                         RMI 1099 + 50000                metrics :8086 (HTTP)
                                       ┌──────────────┴──────┐     ┌───────────┴─────────┐
                                       │ SLAVE 1 jmeter-server│     │ SLAVE 2 jmeter-server│
                                       │ same /mnt/jmeter path│     │ same /mnt/jmeter path│
                                       │ (data/ synced)       │     │ (data/ synced)       │
                                       └──────────────────────┘     └──────────────────────┘
```

Why this shape:

* **The web app only listens on `127.0.0.1:8090`.** SSM port forwarding terminates on the instance's
  loopback, so nothing has to be opened in the Security Group and the UI is never exposed to the VPC.
  Authentication (users/roles) is a second layer on top of IAM/SSM.
* **Only the Master runs the web app.** Slaves stay "dumb" `jmeter-server` engines. The Master's JMeter
  client orchestrates them with `-R`, collects samples and builds the HTML report locally, so every
  report lands in `<project>/results/` on the Master, where the UI shows and compares them.

## 2. Master setup

The app works from wherever the repository already lives; nothing has to be under `/opt`.
With the scripts in `/mnt/jmeter/JMeter_Scripts/jmeter-framework/`:

```bash
cd /mnt/jmeter/JMeter_Scripts/jmeter-framework
git pull                                          # brings webapp/ (branch New_Repo)
cd webapp
./deploy/install_master.sh                        # venv, deps, systemd unit, /etc env file
sudo vi /etc/jmeter-control-center.env            # SR_REMOTE_HOSTS, Influx/Grafana, Confluence hosts
stat -c %U /mnt/jmeter/JMeter_Scripts/jmeter-framework   # -> Linux owner, e.g. ubuntu
sudo -u ubuntu ./.venv/bin/python manage_users.py add alexis --role admin   # asks for a password
sudo systemctl enable --now jmeter-control-center
journalctl -u jmeter-control-center -f
```

* `ubuntu` = the **Linux user that owns the scripts folder** (output of the `stat` command); the service runs as it.
* `alexis` = the **web app login** you are creating (any name; it is *not* an Ubuntu account and lives only in
  `webapp/instance/users.json`). Sign in with it at `http://localhost:8090`, then add the other engineers from
  the **Users** page.

The installer:

* takes the repo root from its own location (`SR_REPO_ROOT` = parent of `webapp/`);
* runs the service as the **owner of the scripts folder** (override with `SERVICE_USER=…`), so `results/`,
  `tests/` and `run_by_tag.sh` stay writable without changing any permissions on `/mnt/jmeter`;
* resolves `jmeter` from that user's login shell and writes it to `SR_JMETER_BIN`, because systemd does not
  read `/etc/profile.d` or `~/.bashrc`. If `jmeter` works in your terminal, it will work in the service.
* adds `RequiresMountsFor=` so the app only starts after `/mnt/jmeter` is mounted.

From your laptop (Session Manager plugin installed):

```bash
aws ssm start-session --target i-0123456789abcdef0 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8090"],"localPortNumber":["8090"]}'
# open http://localhost:8090
```

Forward Grafana the same way (`3000`) if you want the "Grafana ↗" link to work.
Python 3.9+ is enough (Amazon Linux 2023 ships 3.9/3.11). No Node/npm, no build step; Chart.js is vendored.

## 3. Slaves setup (both)

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

5. The scripts must exist on every slave at the **same absolute path** (`/mnt/jmeter/JMeter_Scripts/jmeter-framework`).
   If `/mnt/jmeter` is a shared filesystem (EFS/NFS) mounted on all three nodes, that is already true and
   *Sync to slaves* is unnecessary (leave `SR_SLAVE_SSH_USER` empty). Otherwise sync it.
6. **CSV paths in distributed mode:** a relative path such as `data/usuarios.csv` is resolved by each slave
   against the folder where `jmeter-server` was started, not against the project, so it fails on the slaves.
   Use `${__P(data_dir,data)}/usuarios.csv` in the CSV Data Set Config: local/CLI runs keep working
   (`data_dir` defaults to `data`) and web runs pass `-Gdata_dir=<project>/data` automatically, an absolute
   path that exists on every node.

The dashboard shows each slave as **up/down** by probing its RMI port.

## 4. Things that will bite you in distributed mode (found while reading the branch)

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

## 5. Operating model

* **Roles**: `admin` (users, new projects), `operator` (upload scripts/data, register tags, run/stop, sync),
  `viewer` (read projects, live monitor, reports). Create one user per person so runs are attributable
  (`user=` is recorded in every execution log).
* **One test at a time** per generator (`SR_ALLOW_CONCURRENT_RUNS=0`), otherwise two tests share CPU/NIC
  and both results are invalid.
* **Stop** sends JMeter's `Shutdown` command (UDP 4445, same as `bin/shutdown.sh`): threads finish their
  iteration and the HTML report is still generated. **Kill** terminates the process group (no report).
* **Git**: uploads and tag edits change the working tree on the Master. Commit them from the Master
  (or pull before editing) so the repository stays the source of truth; every `run_by_tag.sh` edit is
  backed up in `instance/backups/` and removed files go to `instance/trash/`.
* **Sizing**: give JMeter on each node `-Xmx` ≈ 50-70 % of RAM (`JVM_ARGS`), `ulimit -n 65536`, and
  watch the generators' own CPU (< 80 %) — add the generators to Grafana (node-exporter/Telegraf).
* **Reports**: every run produces `results/Ejecucion_<DDMMYY_HHMMSS>_<script>/html_report` on the Master.
  The *Reports* tab lists them with totals and the *Compare* view shows avg/p95/error %/TPS deltas vs. a
  baseline run. Old results can be archived to S3 (`aws s3 sync results/ s3://…`) instead of Drive,
  since the Drive script only works on a Mac with Drive for desktop.

## 6. Confluence reports from the Master

* The Master needs **outbound HTTPS** to Confluence (NAT Gateway, or `HTTPS_PROXY` in `/etc/jmeter-control-center.env`).
  Confluence Data Center inside the VPN/VPC works the same way with a Personal Access Token.
* Set `SR_CONFLUENCE_ALLOWED_HOSTS` (e.g. `.atlassian.net`) so user-provided URLs cannot point the Master anywhere else.
* Each user publishes with **their own** token, so Confluence permissions and page history show the real author.
* Tokens are encrypted at rest with `webapp/instance/confluence.key`; losing that file only means users must re-enter tokens.
* Charts in the report come from InfluxDB: fix findings #1 and #2 above (listener URL and `TAG_host`) before relying on them for distributed runs.

## 7. Opening the Control Center from a laptop (launcher with icon)

`webapp/tools/launcher/` contains a launcher for the engineers' laptops (macOS / Linux / WSL):

```bash
cd webapp/tools/launcher
./build_macos_app.sh            # macOS: creates ~/Applications/JMeter Control Center.app (Dock / Launchpad icon)
./install_linux_desktop.sh      # Linux: adds it to the application menu
vi ~/.jmeter-control-center.conf   # INSTANCE_ID of the Master, AWS_PROFILE, AWS_REGION
```

Double-clicking it opens a Terminal that starts the SSM port forwards (`8090` and Grafana `3000`), waits until
the port answers and opens `http://localhost:8090`. Closing the window closes the tunnels. Requires AWS CLI v2 and
the Session Manager plugin; set `AWS_SSO_LOGIN=yes` if you use IAM Identity Center.

## 8. E-mail, Jira, Bitbucket and shift-left

* **E-mail** — *Settings → E-mail notifications*: SMTP host (Gmail/Google Workspace relay, Amazon SES, Office 365),
  from address and `Always notify` (default `qaperformance@bancobase.com`). Each project adds its staff in
  *project → Settings*; the run dialog adds extra recipients. *Preview quick report (mock)* shows the template.
* **Jira** — each engineer sets the Jira URL (and token, or reuses the Confluence token) under *Atlassian*. The
  ticket typed in the run dialog / schedule gets a comment with the results, SLA verdict and links at the end.
* **Bitbucket (scripts repo)** — *Git* page: pull, and commit & push the changes made in the UI (uploads, tags,
  new projects) authored by the web user. Uses the Master's existing git credentials for `origin`.
* **Shift-left (application repos, e.g. baseinet)** — *project → Settings*: application repository
  (`workspace/repo`), tag, users, duration and SLA → **Open PR in Bitbucket**. The PR adds `perf/perf-gate.sh`
  (+ a custom pipeline if the repo has no `bitbucket-pipelines.yml`). One-time per repo:
  1. Install a **Bitbucket self-hosted runner (Linux Shell)** on the Master with label `jmeter-master`
     (Repository/Workspace settings → Runners). The Control Center only listens on `127.0.0.1`, so the gate must run there.
  2. Create an API token (*Account → API tokens*, operator user) and save it as a **secured** repository
     variable `JMCC_TOKEN` (optional `JMCC_JIRA`).
  The step fails the pipeline when the run fails or the p95 / error % SLA is not met.
* **Scheduler** — runs inside the service; set the timezone in *Settings → Application* (EC2 is UTC).

## 9. Live monitor troubleshooting

*Settings → InfluxDB diagnostics* runs every query of the monitor one by one and shows InfluxDB's exact answer
(connection, databases, measurements, applications, last sample, each panel). Typical causes:

| Symptom | Cause / fix |
|---------|-------------|
| `HTTP 401` | InfluxDB auth enabled → `SR_INFLUX_USER` / `SR_INFLUX_PASSWORD` (1.x) or `SR_INFLUX_TOKEN` (2.x) |
| `HTTP 404` on `/query` | InfluxDB 2.x without a DBRP mapping for the database |
| Applications list empty | Backend Listener writing to another InfluxDB (slaves' `localhost`, see §4 #1) or different measurement |
| Last sample is old | Nothing is writing: check the listener URL / port 8086 from the slaves |
| Users panel 0 while others work | Fixed in this version (the outer sub-query had no time range → InfluxDB 1.x HTTP 500) |
