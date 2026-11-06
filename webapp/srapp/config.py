"""Runtime configuration, read from environment variables (see config.env.example)."""
import os
import secrets
from pathlib import Path

WEBAPP_DIR = Path(__file__).resolve().parent.parent


def _env(name, default=None):
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _bool(name, default=False):
    return str(_env(name, "1" if default else "0")).lower() in ("1", "true", "yes", "on")


class Config:
    # Root of Scripts_Repo (folder that contains the *-jmeter-framework projects)
    REPO_ROOT = Path(_env("SR_REPO_ROOT", str(WEBAPP_DIR.parent))).resolve()

    # Private state: users, secret key, run history/logs. Never served, never committed.
    INSTANCE_DIR = Path(_env("SR_INSTANCE_DIR", str(WEBAPP_DIR / "instance"))).resolve()

    # Bind to loopback only: SSM port forwarding connects to localhost on the instance.
    HOST = _env("SR_HOST", "127.0.0.1")
    PORT = int(_env("SR_PORT", "8090"))

    # JMeter on the Master: SR_JMETER_BIN, else the `jmeter` found on PATH, else $JMETER_HOME/bin/jmeter
    JMETER_BIN = None  # resolved below

    # Distributed mode: comma separated slave addresses (private IPs) running jmeter-server
    REMOTE_HOSTS = [h.strip() for h in _env("SR_REMOTE_HOSTS", "").split(",") if h.strip()]
    REMOTE_RMI_PORT = int(_env("SR_REMOTE_RMI_PORT", "1099"))

    # Optional: rsync project data/ (and tests/) to slaves over SSH before distributed runs
    SLAVE_SSH_USER = _env("SR_SLAVE_SSH_USER", "")
    SLAVE_SSH_KEY = _env("SR_SLAVE_SSH_KEY", "")
    SLAVE_REPO_ROOT = _env("SR_SLAVE_REPO_ROOT", str(REPO_ROOT))

    # Project folders are discovered with this suffix
    PROJECT_SUFFIX = _env("SR_PROJECT_SUFFIX", "-jmeter-framework")
    # Folder used as base template when the bundled template is not wanted
    TEMPLATE_DIR = Path(_env("SR_TEMPLATE_DIR", str(WEBAPP_DIR / "project_template"))).resolve()

    MAX_UPLOAD_MB = int(_env("SR_MAX_UPLOAD_MB", "300"))
    ALLOW_CONCURRENT_RUNS = _bool("SR_ALLOW_CONCURRENT_RUNS", False)
    SESSION_HOURS = int(_env("SR_SESSION_HOURS", "12"))

    DATA_EXTENSIONS = {".csv", ".txt", ".json", ".xml", ".dat", ".tsv", ".properties", ".pdf",
                       ".zip", ".b64", ".xlsx", ".jpg", ".png"}


def _resolve_jmeter():
    """Find the real jmeter binary, never our own PATH shim in webapp/bin."""
    explicit = _env("SR_JMETER_BIN")
    if explicit:
        return explicit
    shim_dir = (WEBAPP_DIR / "bin").resolve()
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        cand = Path(d) / "jmeter"
        try:
            if cand.resolve().parent == shim_dir:
                continue
        except OSError:
            continue
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    home = _env("SR_JMETER_HOME") or _env("JMETER_HOME")
    if home:
        return str(Path(home) / "bin" / "jmeter")
    return "/opt/apache-jmeter-5.6.3/bin/jmeter"


Config.JMETER_BIN = _resolve_jmeter()


def load_secret_key():
    key = _env("SR_SECRET_KEY")
    if key:
        return key
    Config.INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    key_file = Config.INSTANCE_DIR / "secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    os.chmod(key_file, 0o600)
    return key
