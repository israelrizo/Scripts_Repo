#!/usr/bin/env python3
"""Start the JMeter Control Center (waitress) on SR_HOST:SR_PORT (127.0.0.1:8090).

  python run.py                      interactive (launcher window)
  python run.py --service            background service (macOS LaunchAgent / Windows scheduled task):
                                     no console, output to webapp/instance/service.log
  python run.py --mode aws|local     override the execution mode for this start
"""
import argparse
import os
import signal
import sys

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--service", nargs="?", const="service", default=None,
                help="run as a background service (optional label, e.g. macos-launchagent)")
ap.add_argument("--mode", choices=("aws", "local"))
args = ap.parse_args()
if args.mode:
    os.environ["SR_MODE"] = args.mode
if args.service:
    os.environ["SR_SERVICE"] = args.service

from waitress import serve  # noqa: E402

from srapp import scheduler, users  # noqa: E402
from srapp.app import app  # noqa: E402
from srapp.config import Config  # noqa: E402


def _service_logging():
    """pythonw / launchd have no usable console: send stdout, stderr and logging to a rotating file."""
    import logging
    from logging.handlers import RotatingFileHandler
    Config.INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(Config.INSTANCE_DIR / "service.log", maxBytes=2_000_000, backupCount=3,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)

    class _Writer:
        def __init__(self, level):
            self.level, self.buf = level, ""

        def write(self, text):
            self.buf += text
            while "\n" in self.buf:
                line, self.buf = self.buf.split("\n", 1)
                if line.strip():
                    logging.log(self.level, line)

        def flush(self):
            pass

    sys.stdout, sys.stderr = _Writer(logging.INFO), _Writer(logging.ERROR)


if __name__ == "__main__":
    if args.service:
        _service_logging()
    if users.count() == 0:
        sys.exit("No users yet. Create the first admin:\n"
                 "  python3 manage_users.py add <username> --role admin")
    # Closing the launcher window (SIGHUP) or stopping the service (SIGTERM) must still run the atexit
    # cleanup that closes the SSM tunnels; Python skips atexit on those signals unless we exit explicitly.
    for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: sys.exit(0))
    if os.name == "nt" and not args.service:
        # closing the console window on Windows: close the SSM tunnels before the process is killed
        import ctypes

        from srapp import tunnels

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
        def _console_close(_event):
            tunnels.close_all()
            return False

        ctypes.windll.kernel32.SetConsoleCtrlHandler(_console_close, True)
    from srapp import tunnels
    stale = tunnels.cleanup_stale()
    if stale:
        print(f"closed {stale} SSM tunnel(s) left by a previous run")
    scheduler.start_background()
    from srapp import settings
    if settings.aws_mode():
        from srapp import remote_run
        remote_run.resume_all()   # re-attach to tests still running on the Master
    print(f"JMeter Control Center on http://{Config.HOST}:{Config.PORT}  repo={Config.REPO_ROOT}"
          f"{'  (service: ' + args.service + ')' if args.service else ''}")
    serve(app, host=Config.HOST, port=Config.PORT, threads=8, max_request_body_size=app.config["MAX_CONTENT_LENGTH"])
