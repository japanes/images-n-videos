"""What goes to the image model for one avatar picture.

  candidate  (reference mode only) the uploaded photos as one "person" group,
             then AVATAR_MASTER: the identity, the SHOT_01 wording, the candidate number
  shot       the face and the marked pictures (up to 4) as one "person" group,
             then AVATAR_SHOT: the identity and the shot wording (catalog or own)
  fix        the same person group, then the current picture (IMAGE_PART_EDIT_BASE),
             then the correction phrase as the person wrote it

Every caption is a prompt file or a layer; nothing is sent that the person
cannot see in «What is sent» of the picture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vf.core import files, google, models_registry, prompts
from vf.core.errors import AppError
from vf.modules import library
from vf.modules.avatars import catalog, store
from vf.modules.avatars.common import (
    ASPECT,
    FACE_CODE,
    IMAGE_SIZE,
    MAX_FIX,
    PROMPT_FIX,
    PROMPT_MASTER,
    PROMPT_SHOT,
    PURPOSE_FIX,
    PURPOSE_MASTER,
    PURPOSE_SHOT,
    SUBJECT_PHOTOS,
    clean_lines,
)

MAX_SENT_SIDE = 2048   # stored pictures larger than this are sent smaller (JPEG)


@dataclass
class Picture:
    file_id: int
    role: str          # face | photo | edit_base
    caption: str


@dataclass
class Plan:
    mode: str                      # candidate | shot | fix
    purpose: str
    prompt_code: str
    model: dict
    image_size: str
    parts: list[Any] = field(default_factory=list)   # captions (str) and Pictures, in order
    text: str = ""                 # what follows the pictures

    @property
    def picture_count(self) -> int:
        return sum(1 for p in self.parts if isinstance(p, Picture))

    def attachments(self) -> list[dict]:
        """What the picture keeps as "what was sent": ``[{role, file_id, caption}]``."""
        return [{"role": p.role, "file_id": p.file_id, "caption": p.caption}
                for p in self.parts if isinstance(p, Picture)]

    def contents(self) -> list[Any]:
        """The parts for ``google.generate`` (without the final text)."""
        from vf.modules.studio import imaging

        out: list[Any] = []
        for p in self.parts:
            if not isinstance(p, Picture):
                out.append(p)
                continue
            if p.caption:
                out.append(p.caption)
            row = files.get(p.file_id)
            data, mime = files.read_bytes(p.file_id), row["mime"]
            if max(row.get("width") or 0, row.get("height") or 0) > MAX_SENT_SIDE or mime not in (
                    "image/png", "image/jpeg", "image/webp"):
                data, mime = imaging.shrink(data, mime, max_side=MAX_SENT_SIDE)
            out.append(google.Blob(data, mime, p.file_id))
        return out


def _layer(code: str, **values: Any) -> str:
    return library.render_layer(code, values).strip()


def _part(code: str, **values: Any) -> str:
    return prompts.render(code, **values).text.strip()


def pick_size(model: dict) -> str:
    """1K when the model makes it, else its first size (the answer is fitted to 864×1152 anyway)."""
    allowed = list((model.get("caps") or {}).get("allowed_resolutions") or [IMAGE_SIZE])
    return IMAGE_SIZE if IMAGE_SIZE in allowed else allowed[0]


def image_model(avatar: dict) -> dict:
    """The avatar's own model, else the default image model (both from settings, never from code)."""
    return models_registry.resolve("image", avatar.get("image_model_id") or None)


def _exists(file_id: int | None) -> bool:
    if not file_id:
        return False
    try:
        files.get(file_id)
    except AppError:
        return False
    return True


# ── which pictures go ───────────────────────────────────────────────────────

def candidate_photos(avatar: dict) -> list[dict]:
    """Reference mode: the uploaded photos only (marked first), up to 4. Other modes: none."""
    if avatar["init_mode"] != "reference":
        return []
    rows = [p for p in store.sources_of(avatar["id"]) if _exists(p["file_id"])]
    rows.sort(key=lambda p: (0 if p.get("marked") else 1, p.get("sort") or 0, p["id"]))
    return rows[:SUBJECT_PHOTOS]


def shot_photos(avatar: dict, exclude_id: int | None = None) -> list[dict]:
    """The face first, then the marked pictures (uploads before drawn shots), up to 4 in all.
    ``[{file_id, angle, role}]``."""
    out: list[dict] = []
    seen: set[int] = set()
    face = avatar.get("face_file_id")
    if face and _exists(face):
        face_row = store.face_row(avatar["id"])
        out.append({"file_id": face, "angle": (face_row or {}).get("angle") or "", "role": "face"})
        seen.add(face)
    marked = [p for p in store.photos_of(avatar["id"]) if p.get("marked") and p.get("file_id")
              and p["kind"] in ("source", "shot") and p.get("shot_code") != FACE_CODE and p["id"] != exclude_id]
    marked.sort(key=lambda p: (0 if p["kind"] == "source" or p.get("origin") == "upload" else 1,
                               0 if p["kind"] == "source" else 1, p.get("sort") or 0, p["id"]))
    for p in marked:
        if len(out) >= SUBJECT_PHOTOS:
            break
        if p["file_id"] in seen or not _exists(p["file_id"]):
            continue
        seen.add(p["file_id"])
        out.append({"file_id": p["file_id"], "angle": p.get("angle") or "", "role": "photo"})
    return out


def person_group(name: str, photos: list[dict]) -> list[Any]:
    """The pictures of the person as one subject group (the same captions the studio sends)."""
    if not photos:
        return []
    name = name or "Avatar"
    head = _part("STUDIO_PART_SUBJECT", index=1, name=name, kind="person")
    if len(photos) > 1:
        head += " " + _layer("IMAGE_PART_SUBJECT_MULTI_PHOTOS", count=len(photos), kind="person")
    parts: list[Any] = [_layer("IMAGE_PART_SUBJECTS_HEADER", count=1), head]
    for index, p in enumerate(photos, start=1):
        angle = str(p.get("angle") or "").strip()
        values = {"name": name, "index": index, "count": len(photos)}
        caption = (_part("STUDIO_PART_SUBJECT_PHOTO_ANGLE", angle=angle, **values) if angle
                   else _part("STUDIO_PART_SUBJECT_PHOTO", **values))
        parts.append(Picture(p["file_id"], p.get("role") or "photo", caption + ":"))
    return parts


# ── the plans ───────────────────────────────────────────────────────────────

def _identity(avatar: dict) -> str:
    identity = (avatar.get("identity") or "").strip()
    if not identity:
        raise AppError("avatar_no_identity", 409, "Describe the person first")
    return identity


def shot_wording(row: dict) -> str:
    """The person's own wording of the shot, else the catalog one."""
    own = (row.get("custom_prompt") or "").strip()
    return own or catalog.shot(row["shot_code"])["prompt"]


def plan_candidate(avatar: dict, variation: int) -> Plan:
    identity = _identity(avatar)
    model = image_model(avatar)
    photos = candidate_photos(avatar)
    if avatar["init_mode"] == "reference" and not photos:
        # «From photos» without photos would quietly draw a stranger: say so instead.
        raise AppError("avatar_no_photos", 409, "Add at least one photo of the person")
    parts = person_group(avatar["name"], [{"file_id": p["file_id"], "angle": p.get("angle"), "role": "photo"}
                                          for p in photos])
    text = _layer("AVATAR_MASTER", identity=identity, shot=catalog.shot(FACE_CODE)["prompt"],
                  variation=int(variation), from_reference=bool(photos))
    return Plan("candidate", PURPOSE_MASTER, PROMPT_MASTER, model, pick_size(model), parts, text)


def plan_shot(avatar: dict, row: dict) -> Plan:
    identity = _identity(avatar)
    if not avatar.get("face_file_id"):
        raise AppError("avatar_no_face", 409, "Choose the face first")
    if row.get("shot_code") == FACE_CODE:
        raise AppError("avatar_face_slot", 409, "The face is chosen from the candidates or the photos")
    model = image_model(avatar)
    parts = person_group(avatar["name"], shot_photos(avatar, exclude_id=row["id"]))
    text = _layer("AVATAR_SHOT", identity=identity, shot=shot_wording(row))
    return Plan("shot", PURPOSE_SHOT, PROMPT_SHOT, model, pick_size(model), parts, text)


def clean_fix(text: Any) -> str:
    fix = clean_lines(str(text or ""))
    if not fix:
        raise AppError("avatar_fix_required", 400, "Write what to change")
    if len(fix) > MAX_FIX:
        raise AppError("avatar_fix_too_long", 400, "The correction is too long", max=MAX_FIX)
    return fix


def plan_fix(avatar: dict, row: dict, fix: Any) -> Plan:
    text = clean_fix(fix)
    if row.get("shot_code") == FACE_CODE or row["kind"] != "shot":
        raise AppError("avatar_face_slot", 409, "Only a shot of the pack can be fixed")
    if not row.get("file_id") or not _exists(row["file_id"]):
        raise AppError("avatar_no_picture", 409, "The shot has no picture to fix")
    model = image_model(avatar)
    parts = person_group(avatar["name"], shot_photos(avatar, exclude_id=row["id"]))
    parts.append(Picture(row["file_id"], "edit_base", _layer("IMAGE_PART_EDIT_BASE") + ":"))
    return Plan("fix", PURPOSE_FIX, PROMPT_FIX, model, pick_size(model), parts, text)


def plan_for(avatar: dict, row: dict, mode: str, fix: Any = None) -> Plan:
    if mode == "candidate":
        return plan_candidate(avatar, int((row.get("meta_json") or {}).get("variation") or 1))
    if mode == "fix":
        return plan_fix(avatar, row, fix)
    return plan_shot(avatar, row)


def aspect() -> str:
    return ASPECT
