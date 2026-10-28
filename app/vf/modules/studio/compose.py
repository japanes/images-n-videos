"""What goes to the image model for one frame: the pictures with their captions,
then the text (the brief or the correction, then the prompt blocks that apply).

A block goes only when the frame has what it is made from (see ``blocks``);
style and lettering are the person's own words in the brief.

Order of the parts (the text goes last):
  edit:  the picture being corrected, the marked copy (when an object is picked)
  full:  subjects -> logo -> references (pilot first) -> attached photos
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vf.core import files, google, prompts
from vf.core.errors import AppError
from vf.modules import brand, library
from vf.modules.models import service as models_service
from vf.modules.studio import blocks, imaging
from vf.modules.studio import works as W
from vf.modules.studio.common import MAX_EDIT, clean_block


@dataclass
class Picture:
    """One picture of the request. ``file_id`` None: made on the fly (the marked copy)
    and then ``data`` holds the bytes."""

    role: str            # subject | logo | anchor | reference | attachment | edit_base | edit_marker
    label: str
    file_id: int | None = None
    data: bytes | None = None
    mime: str | None = None
    shrink: bool = False


@dataclass
class Group:
    caption: str                                 # text before the pictures ("" = none)
    pictures: list[Picture] = field(default_factory=list)


@dataclass
class Plan:
    mode: str
    eff: dict
    facts: blocks.Facts
    codes: list[str]                             # blocks sent
    groups: list[Group]
    text: str                                    # what follows the pictures
    target: tuple[int, int] | None               # exact output size (1K with a configured size)

    @property
    def picture_count(self) -> int:
        return sum(len(g.pictures) for g in self.groups)

    def attachments(self) -> list[dict]:
        """What the frame keeps as "what was sent": ``[{role, label, file_id, mime, caption}]``."""
        out = []
        for g in self.groups:
            for i, p in enumerate(g.pictures):
                out.append({"role": p.role, "label": p.label, "file_id": p.file_id, "mime": p.mime,
                            "caption": g.caption if i == 0 else ""})
        return out

    def contents(self) -> list[Any]:
        """The parts for ``google.generate``: captions and pictures, then the text."""
        out: list[Any] = []
        for g in self.groups:
            if g.caption:
                out.append(g.caption)
            for p in g.pictures:
                out.append(_blob(p))
        return out


def _blob(p: Picture) -> google.Blob:
    if p.data is not None:
        data, mime = p.data, p.mime or "image/png"
    else:
        row = files.get(p.file_id)
        data, mime = files.read_bytes(p.file_id), row["mime"]
    if p.shrink:
        data, mime = imaging.shrink(data, mime)
    return google.Blob(data, mime, p.file_id)


def _layer(code: str, **values: Any) -> str:
    return library.render_layer(code, values).strip()


def _part(code: str, **values: Any) -> str:
    """A studio caption (plain prompt file ``STUDIO_PART_*``, every value always filled)."""
    return prompts.render(code, **values).text.strip()


def output_target(work: dict, eff: dict) -> tuple[int, int] | None:
    """The configured output size for the work's aspect; only for 1K pictures
    (2K and 4K keep the model's own, larger, size)."""
    if eff["image_size"] != "1K":
        return None
    return models_service.output_size(work["aspect"])


def generated_count(frame: dict) -> int:
    return sum(1 for v in frame.get("versions_json") or [] if v.get("mode") == "full")


def facts(work: dict, frame: dict, eff: dict) -> blocks.Facts:
    """What the blocks of this frame are made from."""
    anchor = W.anchor_file(work, frame)
    return blocks.Facts(
        brand=work.get("brand_json"),
        references=len(eff["references"]) + (1 if anchor else 0),
        attachments=len(eff["attachments"]),
        subjects=brand.describe_subjects(eff["subjects"]),
        photo_style=library.photo_style_text(eff["photo_style"]),
        size=output_target(work, eff),
        large=eff["image_size"] != "1K",
        variant=generated_count(frame) + 1,
        feedback=eff["feedback"] or "",
    )


def _file_picture(role: str, label: str, file_id: int, *, shrink: bool = False) -> Picture | None:
    try:
        row = files.get(file_id)
    except AppError:
        return None
    return Picture(role, label, file_id=row["id"], mime=row["mime"], shrink=shrink)


def full_text(work: dict, frame: dict, codes: list[str], f: blocks.Facts) -> str:
    """The brief, then the texts of the blocks that apply."""
    brief = (frame.get("brief") or "").strip() or (W.settings_of(work).get("ideas_brief") or "").strip()
    if not brief:
        raise AppError("brief_required", 400, "Write what the picture should show")
    return "\n\n".join([brief, *blocks.render(codes, f)])


def plan_full(work: dict, frame: dict, eff: dict | None = None) -> Plan:
    eff = eff or W.effective(work, frame)
    f = facts(work, frame, eff)
    codes = blocks.active(f)
    snap = work.get("brand_json") or {}
    groups: list[Group] = []

    subjects_sent = False
    if "subjects" in codes:
        found = brand.subject_groups(eff["subjects"])
        if found:
            subjects_sent = True
            groups.append(Group(_layer("IMAGE_PART_SUBJECTS_HEADER", count=len(found))))
            for index, s in enumerate(found, start=1):
                described = " ".join(str(s.get("description") or "").split())
                kind = s["kind"] or "object"
                if described:
                    head = _part("STUDIO_PART_SUBJECT_DESCRIBED", index=index, name=s["name"], kind=kind,
                                 description=described)
                else:
                    head = _part("STUDIO_PART_SUBJECT", index=index, name=s["name"], kind=kind)
                if len(s["photos"]) > 1:
                    head += " " + _layer("IMAGE_PART_SUBJECT_MULTI_PHOTOS", count=len(s["photos"]),
                                         kind=s["kind"] or "object")
                groups.append(Group(head))
                for j, photo in enumerate(s["photos"], start=1):
                    pic = _file_picture("subject", s["name"], photo["file_id"])
                    if pic:
                        angle = str(photo.get("angle") or "").strip()
                        values = {"name": s["name"], "index": j, "count": len(s["photos"])}
                        caption = (_part("STUDIO_PART_SUBJECT_PHOTO_ANGLE", angle=angle, **values) if angle
                                   else _part("STUDIO_PART_SUBJECT_PHOTO", **values))
                        groups.append(Group(caption + ":", [pic]))

    if "logo" in codes:
        logo = blocks.logo_of(snap)
        pic = _file_picture("logo", logo.get("name") or "logo", logo["file_id"]) if logo else None
        if pic:
            groups.append(Group(_part("STUDIO_PART_LOGO") + ":", [pic]))

    anchor = W.anchor_file(work, frame)
    refs: list[Picture] = []
    if anchor and (pic := _file_picture("anchor", "pilot frame", anchor, shrink=True)):
        refs.append(pic)
    anchored = len(refs)
    if "project_references" in codes:
        refs += [p for fid in eff["references"] if fid != anchor
                 and (p := _file_picture("reference", "reference", fid, shrink=True))]
    if refs:
        caption = _layer("IMAGE_PART_REFERENCES", count=len(refs))
        if anchored:
            caption += _layer("IMAGE_PART_REFERENCES_ANCHOR", count=anchored)
        if subjects_sent:
            caption += _layer("IMAGE_PART_REFERENCES_SUBJECTS")
        groups.append(Group(caption + ":", refs))

    if "task_attachments" in codes:
        pics = [p for fid in eff["attachments"] if (p := _file_picture("attachment", "attached photo", fid,
                                                                         shrink=True))]
        if pics:
            groups.append(Group(_part("STUDIO_PART_ATTACHMENTS") + ":", pics))

    text = full_text(work, frame, codes, f)
    return _checked(Plan("full", eff, f, codes, groups, text, output_target(work, eff)))


def edit_text(edit: str, region: dict | None) -> str:
    """The correction, with the picked object's place."""
    edit = clean_block(edit, MAX_EDIT)
    if not edit:
        raise AppError("edit_text_required", 400, "Write what to change")
    if region:
        return _layer("IMAGE_PART_EDIT_REGION", label=region["label"] or "object",
                      area=imaging.area_words(region["box"])) + "\n\n" + edit
    return edit


def plan_edit(work: dict, frame: dict, edit: str, region: dict | None = None, eff: dict | None = None,
              *, base_bytes: bytes | None = None) -> Plan:
    """A correction of the current picture: the picture, the marked copy, the text."""
    eff = eff or W.effective(work, frame)
    if not frame.get("file_id"):
        raise AppError("frame_no_picture", 409, "The frame has no picture to correct")
    f = facts(work, frame, eff)
    text = edit_text(edit, region)
    row = files.get(frame["file_id"])
    groups = [Group(_layer("IMAGE_PART_EDIT_BASE") + ":",
                    [Picture("edit_base", "picture being corrected", file_id=row["id"], mime=row["mime"])])]
    if region:
        data = base_bytes if base_bytes is not None else files.read_bytes(row["id"])
        marked = imaging.marked_copy(data, region["box"])
        if marked:
            label = region["label"] or "object"
            groups.append(Group(_layer("IMAGE_PART_EDIT_MARKER", colour=imaging.MARKER_COLOUR_NAME, label=label) + ":",
                                [Picture("edit_marker", label, data=marked, mime="image/png")]))
    return _checked(Plan("edit", eff, f, [], groups, text, output_target(work, eff)))


def _checked(plan: Plan) -> Plan:
    limit = int((plan.eff["model"].get("caps") or {}).get("max_references") or 14)
    if plan.picture_count > limit:
        raise AppError("too_many_images", 400, "Too many pictures for this model", count=plan.picture_count,
                       max=limit)
    return plan


def find_region(frame: dict, region: Any) -> dict | None:
    """The picked object: ``{"id"}`` of a found object, or ``{"label", "box"}`` drawn by hand."""
    if not region:
        return None
    if not isinstance(region, dict):
        raise AppError("bad_request", 400, "The picked object must be an object")
    found = W.current_objects(frame)
    if region.get("id") and found:
        item = next((o for o in found.get("items") or [] if o.get("id") == region["id"]), None)
        if item:
            return {"id": item["id"], "label": item.get("label") or "", "box": item["box"]}
    box = region.get("box")
    if not isinstance(box, dict):
        raise AppError("bad_request", 400, "The picked object has no rectangle")
    try:
        clean = {k: min(max(float(box[k]), 0.0), 1.0) for k in ("x", "y", "w", "h")}
    except (KeyError, TypeError, ValueError):
        raise AppError("bad_request", 400, "The picked object has a bad rectangle") from None
    if clean["w"] <= 0 or clean["h"] <= 0:
        raise AppError("bad_request", 400, "The picked object has a bad rectangle")
    return {"id": None, "label": " ".join(str(region.get("label") or "").split())[:80], "box": clean}
