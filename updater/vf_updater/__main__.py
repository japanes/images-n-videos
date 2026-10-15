"""Command line.

  serve                       run the updater service (default)
  install --op FILE           helper: switch to the version of this image, verify, roll back
  apply --op FILE             helper: start the stack of this image's version (first start,
                              hand-over, restart of stopped services)
  rollback --op FILE          helper: return to the previous version of an interrupted update
  stop                        helper: stop all containers of the app
  health                      exit 0 when GET /health of this updater answers

The helper commands are a contract between versions: keep them working.
--op is accepted for compatibility; the operation file is always /data/update/op.json.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading

from . import config
from .app_client import health_version
from .engine import Engine


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vf_updater")
    parser.add_argument("command", nargs="?", default="serve",
                        choices=["serve", "install", "apply", "rollback", "stop", "health"])
    parser.add_argument("--op", default=None, help="operation file (default /data/update/op.json)")
    parser.add_argument("--version", default=None, help=argparse.SUPPRESS)
    args, _unknown = parser.parse_known_args(argv)

    cfg = config.load()
    engine = Engine(cfg)

    if args.command == "health":
        url = f"http://127.0.0.1:{cfg.listen_port}"
        return 0 if health_version(url, timeout=4) else 1
    if args.command == "serve":
        stop_event = threading.Event()

        def _stop(_signum, _frame):
            stop_event.set()

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        from .server import serve

        serve(engine, stop_event)
        return 0
    engine.store.ensure_dirs()
    if args.command == "install":
        return engine.helper_install()
    if args.command == "apply":
        return engine.helper_apply()
    if args.command == "rollback":
        return engine.helper_rollback()
    if args.command == "stop":
        return engine.helper_stop()
    return 2


if __name__ == "__main__":
    sys.exit(main())
