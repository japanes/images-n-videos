"""What a journal ref (``ai_call_refs``: type + id) points to.

The journal only stores ``("work", 3)``. To show "Work: Summer sale" with a
link, the module that owns the type registers a resolver. Built in: files and
jobs (core tables). Unknown types are shown as "type #id".
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from vf.core import db, files

log = logging.getLogger("vf.spend")

# resolver(ref_id) -> {"title", "link", "url", "thumb_url"} (each may be None) or None when the object is gone.
#   link: a route inside the app ("/avatars/5"); url: a file to open in a new tab ("/files/12").
Resolver = Callable[[int], dict | None]

_resolvers: dict[str, Resolver] = {}


def register_ref(ref_type: str, resolver: Resolver) -> None:
    _resolvers[ref_type] = resolver


def resolve(ref_type: str, ref_id: int) -> dict:
    out = {"type": ref_type, "id": ref_id, "title": None, "link": None, "url": None, "thumb_url": None,
           "exists": None}
    fn = _resolvers.get(ref_type)
    if fn is None:
        return out
    try:
        found = fn(ref_id)
    except Exception:  # a broken resolver must not break the spend screen
        log.exception("ref resolver for %s failed", ref_type)
        return out
    if found is None:
        out["exists"] = False
        return out
    out.update({k: found.get(k) for k in ("title", "link", "url", "thumb_url") if found.get(k) is not None})
    out["exists"] = True
    return out


def _file(file_id: int) -> dict | None:
    row = db.get("files", file_id)
    if row is None:
        return None
    thumb = None
    if row["kind"] == "image" or row.get("poster_path"):
        thumb = files.url(file_id, w=160)
    return {"title": row.get("title") or row.get("original_name"), "url": files.url(file_id), "thumb_url": thumb}


def _job(job_id: int) -> dict | None:
    row = db.get("jobs", job_id)
    if row is None:
        return None
    return {"title": row.get("title") or row.get("kind")}


register_ref("file", _file)
register_ref("job", _job)
