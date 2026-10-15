"""Logging setup. Every record passes a scrubber so a service-account key,
an OAuth token or a private key can never reach stdout."""

from __future__ import annotations

import logging
import re
import sys

_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[private key]"),
    (re.compile(r'("private_key"\s*:\s*")[^"]*(")'), r"\1[redacted]\2"),
    (re.compile(r"(ya29\.)[A-Za-z0-9_\-\.]+"), r"\1[redacted]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.=]+", re.I), r"\1[redacted]"),
    (re.compile(r'("private_key_id"\s*:\s*")[^"]*(")'), r"\1[redacted]\2"),
]


def scrub(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class ScrubFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        clean = scrub(message)
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = scrub(record.exc_text)
        if clean != message or record.args:
            record.msg = clean
            record.args = None
        return True


def configure(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(ScrubFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
