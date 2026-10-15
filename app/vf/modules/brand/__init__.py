"""Brand kits and subjects (module 08).

Python API for the studio (04), the chat (15) and fonts (06)::

    from vf.modules import brand

    snap = brand.snapshot_kit(kit_id)          # copy of colors, tone, fonts, logos, elements, references
    brand.kit_changed(snap)                    # True -> offer "update from kit"; None -> kit deleted

    brand.get_subject(subject_id)              # card with photos (raises not_found)
    brand.subject_images(subject_id)           # first 4 photos in order: [{file_id, angle, mime}]
    brand.subject_groups(ids, blobs=True)      # per subject: name, kind, description, photos (+ google.Blob)
    brand.describe_subjects(ids)               # words only: [{id, name, kind, description}]
    brand.find_subject_by_name("Red mug")      # library subject or None
    brand.match_mentions("put @Red mug on …")  # [{id, name, start, end}]
    brand.create_subject(name, kind, one_off=True)   # quick subject from a picker

    brand.add_catalog_font(kit_id, family, category, file_id=...)   # module 06
"""

from vf.modules.brand.describe import describe_subject
from vf.modules.brand.fonts import CATEGORIES as FONT_CATEGORIES
from vf.modules.brand.fonts import inspect_font
from vf.modules.brand.kits import (
    ELEMENT_KINDS,
    add_catalog_font,
    get_kit,
    kit_changed,
    list_kits,
    snapshot_kit,
)
from vf.modules.brand.routes import router
from vf.modules.brand.subjects import (
    KINDS as SUBJECT_KINDS,
)
from vf.modules.brand.subjects import (
    PHOTOS_SENT,
    create_subject,
    describe_subjects,
    find_subject_by_name,
    get_subject,
    list_subjects,
    match_mentions,
    normalize_subject_ids,
    subject_groups,
    subject_images,
)

__all__ = [
    "ELEMENT_KINDS", "FONT_CATEGORIES", "PHOTOS_SENT", "SUBJECT_KINDS", "add_catalog_font", "create_subject",
    "describe_subject", "describe_subjects", "find_subject_by_name", "get_kit", "get_subject", "inspect_font",
    "kit_changed", "list_kits", "list_subjects", "match_mentions", "normalize_subject_ids", "router",
    "snapshot_kit", "subject_groups", "subject_images",
]
