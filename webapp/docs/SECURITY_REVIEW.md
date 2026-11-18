# Security review — JMeter Control Center

Scope: the web app that runs on each engineer's computer (`webapp/`), its access to AWS (EC2, SSM Run Command,
SSM sessions), the copy of scripts to the servers, notifications and stored secrets. Threats considered: other
web pages open in the engineer's browser, other users of the shared Master, a stolen laptop or leaked
`webapp/instance/` folder, and mistakes that expose credentials.

## Fixed in this review

| # | Finding | Risk | Fix |
|---|---------|------|-----|
| S1 | No Content-Security-Policy; inline `onclick` handlers | An HTML injection anywhere would run script with the engineer's session (AWS, Git, e-mail) | Strict CSP on every page: `script-src 'self' 'nonce-…'`, `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'self'`; inline handlers replaced by `data-*` attributes. JMeter HTML dashboards keep the basic headers (they need inline scripts). |
| S2 | Any `Host` header accepted | **DNS rebinding**: a malicious page can point its own domain at 127.0.0.1 and talk to the app from the browser | Only `localhost`, `127.0.0.1`, `[::1]`, the host of *Settings → Application → public URL* and `SR_ALLOWED_HOSTS` are answered (400 otherwise). |
| S3 | `?next=` after login accepted `/\evil.com` | Open redirect (phishing with a real localhost link) | Only same-site paths: no `//`, no `\`, no scheme/host, no control characters. |
| S4 | Gmail OAuth flow (client secret + refresh token stored) | Long-lived Google token on disk; needed a Cloud project | Removed. E-mail uses SMTP with a Google **App Password** (revocable per app, send-only via SMTP), encrypted at rest. |
| S5 | SMTP security `none` allowed with a password | Password sent in clear text | Refused unless the host is localhost; App Password spaces are stripped. |
| S6 | Graceful stop sent `Shutdown` to UDP 4445–4447 | With several tests on the Master, one engineer's stop would stop the others' tests | Only the UDP port owned by **that** run's JMeter process tree is used; otherwise *Force stop* is suggested. |
| S7 | A copy/sync could overwrite files of a project whose test is running | Corrupted CSVs / scripts in the middle of someone else's test | Runs copy only their own project; full copies skip projects with a live slot; a project with a live slot cannot be copied. |
| S8 | Servers needed repository credentials (personal tokens left on shared servers) | Personal credentials on machines used by the whole team | Push sync: the servers need no repository access; each engineer authenticates with their own SSH key **inside** SSM. |
| S9 | SSH settings could be injected through the key path | A crafted path with a newline would add `ProxyCommand` lines to the generated ssh config | Key path validated (no control characters or quotes, ≤ 300 chars); profile/region/user/instance ids/remote folder were already validated with strict patterns. |
| S10 | Sensitive pages cacheable | Settings/account pages kept in the browser cache | `Cache-Control: no-store` on `/login`, `/account`, `/admin`; `Cross-Origin-Opener-Policy: same-origin` everywhere. |

## Verified (already in place)

* Listens on **127.0.0.1** only; session cookie `HttpOnly`, `SameSite=Strict`; CSRF token on every POST; login
  throttling per IP + user; optional TOTP 2FA; roles viewer / operator / admin checked on every route.
* Passwords hashed (Werkzeug PBKDF2/scrypt); API tokens stored as SHA-256 and compared in constant time.
* Secrets (Confluence/Jira/Bitbucket/New Relic tokens, SMTP password, Chat webhooks) encrypted with Fernet; key and
  settings files are `0600`; `webapp/instance/` is in `.gitignore`.
* Every value placed in a remote shell script is either validated with a strict pattern or `shlex.quote`d; scripts
  travel base64-encoded through SSM and run as the scripts owner, not root (only the Slave restart command runs as
  root, and it is admin-only).
* Uploads: size limit, allowed extensions, `secure_filename`, path-traversal checks; reports served with
  `send_from_directory`.
* SSH host keys: `StrictHostKeyChecking accept-new` with a known_hosts file per app; the connection itself is the
  SSM channel to a specific instance id, authenticated by AWS.
* Jinja auto-escaping; the few `Markup` uses escape their inputs first.

## Residual risks and recommendations

1. **Engineer keys on the servers.** Each engineer's public key is added to `authorized_keys` of the scripts owner.
   When someone leaves, remove their line on the three servers (or rotate the file from the AMI).
2. **Fernet key next to the data.** Encryption protects against accidental commits and casual reading, not against
   someone with full access to the laptop. Keep FileVault/BitLocker on.
3. **Shared Linux user.** All engineers act as the same user on the servers, so the Master cannot tell who changed a
   file; the run log and the slot file record the engineer name given by the app.
4. **Hard-coded tokens in scripts.** The quality review found Bearer tokens committed in many `.jmx` files
   (rule R14). Rotate them and move them to properties or CSV data.
5. **JMeter HTML reports** are served from the app's origin without CSP (they need inline scripts). They are
   generated by JMeter from run results, not uploaded by users.
6. **IAM.** Scope `ssm:SendCommand` / `ssm:StartSession` to the generator instances (or a tag) and to the three
   documents used (`AWS-RunShellScript`, `AWS-StartPortForwardingSession`, `AWS-StartSSHSession`).
