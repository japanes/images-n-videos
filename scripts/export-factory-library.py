#!/usr/bin/env python3
"""One-off export of the factory style library into this project's seed files.

Reads the factory MySQL database READ ONLY (a SELECT-only session inside the
`factory-db-1` container) and the factory upload folder, and writes:

  app/seeds/library/categories.json      the category tree (library part only)
  app/seeds/library/styles.json          built-in styles and photo styles
  app/seeds/library/previews/<code>.jpg  previews of built-in styles (re-encoded)
  app/prompts/layers/<group>/<CODE>/v1.md  service prompt layers (cf_prompts kind=layer)

Nothing in the factory is changed. The password is read from the factory .env and
passed to the container through the environment; it is never printed.

Usage: python3 scripts/export-factory-library.py [--factory PATH]
Needs Pillow and PyYAML on the host python.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "app" / "seeds" / "library"
PROMPTS = ROOT / "app" / "prompts" / "layers"

PREVIEW_MAX_SIDE = 640
PREVIEW_QUALITY = 82

# The avatar shot pack (`identity/...`) is a separate catalog owned by the avatar
# module; the style library is everything else.
EXCLUDED_CATEGORY_ROOTS = ("identity",)

# Which factory layers are ported, grouped by the module that will read them.
# Left out: social-post/topic/strategy/OpenMontage/reels layers (out of scope),
# SHOT_SERIES_INPUT (no reader in factory code), text/caption-only composer blocks,
# SUBJECT_DESCRIBE_INPUT (ported by the brand module under app/prompts/brand), the post
# blocks POST_TOPIC / POST_GOAL / POST_CAPTION (the studio spec drops them).
LAYERS: dict[str, tuple[str, ...]] = {
    "image": (
        "IMAGE_PART_SUBJECTS_HEADER", "IMAGE_PART_SUBJECT_MULTI_PHOTOS", "IMAGE_PART_CONTINUITY",
        "IMAGE_PART_CONTINUITY_NOTE_DEFAULT", "IMAGE_PART_CONTINUITY_SUBJECTS", "IMAGE_PART_REFERENCES",
        "IMAGE_PART_REFERENCES_SUBJECTS", "IMAGE_PART_REFERENCES_CONTINUITY", "IMAGE_PART_REFERENCES_ANCHOR",
        "IMAGE_PART_STYLE_SAMPLE", "IMAGE_PART_STYLE_SAMPLE_BRAND", "IMAGE_PART_STYLE_SAMPLE_SUBJECTS",
        "IMAGE_PART_EDIT_BASE", "IMAGE_PART_EDIT_REGION", "IMAGE_PART_EDIT_MARKER", "IMAGE_PART_FONT_SHEET",
        "EDIT_LETTERING_RULE", "EDIT_LETTERING_REPLACE", "IMAGE_SEGMENT_INPUT",
        "IMAGE_SLIDE_CONTINUITY", "IMAGE_SLIDE_FONT_SHEET", "IMAGE_SLIDE_STYLE_REFS",
        "IMAGE_SLIDE_STYLE_SAMPLE", "IMAGE_SLIDE_SUBJECTS",
    ),
    "ideas": ("SHOT_IDEAS_INPUT", "SHOT_RESEARCH_INPUT", "SHOT_SCENE_RULE"),
    "text": (
        "SLIDE_TEXT_PLACEMENT_SINGLE", "SLIDE_TEXT_PLACEMENT_SINGLE_SYSTEM", "SLIDE_TEXT_PLACEMENT_MULTI",
        "SLIDE_TEXT_PLACEMENT_MULTI_SYSTEM", "SLIDE_TEXT_PLACEMENT_MULTI_AVOID", "SLIDE_TEXT_HUMANIZER",
        "CAROUSEL_SLIDE_REWRITE", "CAROUSEL_SLIDE_REWRITE_BRIEF", "CAROUSEL_BLOCK_COUNT_FIXED",
        "CAROUSEL_BLOCK_COUNT_OPEN",
    ),
    "avatar": (
        "AVATAR_BASELINE", "AVATAR_IDENTITY_INPUT", "AVATAR_MASTER", "AVATAR_MASTER_RULE", "AVATAR_NEGATIVE",
        "AVATAR_REALISM", "AVATAR_SHOT", "AVATAR_VIDEO_NOTICE",
    ),
    "video": ("video_storyboard_reference", "video_storyboard_sheet", "video_storyboard_take"),
    "blocks": tuple(f"PROMPT_BLOCK_{name}" for name in (
        "OUTPUT_SIZE", "LANGUAGE", "LENGTH_LIMIT", "BRAND_COLORS", "BRAND_FONTS", "TONE_OF_VOICE", "LOGO",
        "PROJECT_REFERENCES", "TASK_ATTACHMENTS", "SUBJECTS", "IDENTITY_ASSETS", "STORY_BRIEF",
        "IMAGE_STYLE", "PHOTO_STYLE", "SLIDE_POSITION", "SLIDE_TEXT", "DRAW_TEXT",
        "NO_LETTERING", "AUTHOR_TEXT", "QUALITY", "VARIANT_DIVERSITY", "OVERLAY_SYSTEM", "OVERLAY_RULES",
        "FEEDBACK",
    )),
}


def db_password(factory: Path) -> str:
    for line in (factory / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DB_PASSWORD="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("DB_PASSWORD not found in the factory .env")


def query(password: str, sql: str) -> list[dict]:
    """Run one SELECT that yields a JSON_OBJECT per row, in a read-only session."""
    env = {**os.environ, "MYSQL_PWD": password}
    cmd = ["docker", "exec", "-e", "MYSQL_PWD", "factory-db-1", "mysql", "--default-character-set=utf8mb4",
           "-udirectus", "marketing_ai", "-N", "--raw", "-e", f"SET SESSION TRANSACTION READ ONLY; {sql}"]
    out = subprocess.run(cmd, env=env, check=True, capture_output=True, text=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def export_categories(password: str, factory: Path) -> list[dict]:
    rows = query(password, (
        "SELECT JSON_OBJECT('slug', slug, 'title', title, 'title_uk', title_uk, 'title_en', title_en, "
        "'depth', depth, 'sort', sort) FROM image_prompt_categories WHERE status = 'published' "
        "ORDER BY depth, sort, slug"
    ))
    out = []
    for row in rows:
        if row["slug"].split("/")[0] in EXCLUDED_CATEGORY_ROOTS:
            continue
        parent = row["slug"].rsplit("/", 1)[0] if "/" in row["slug"] else None
        item = {"slug": row["slug"], "parent": parent, "depth": row["depth"], "sort": row["sort"],
                "title": row["title"]}
        if row.get("title_uk"):
            item["title_uk"] = row["title_uk"]
        if row.get("title_en"):
            item["title_en"] = row["title_en"]
        out.append(item)
    # Same tree as the factory's own seed file, or something is off.
    shipped = json.loads((factory / "api/config/prompt-categories.json").read_text(encoding="utf-8"))
    if {c["slug"] for c in shipped} != {c["slug"] for c in out}:
        raise SystemExit("category tree differs from api/config/prompt-categories.json")
    slugs = {c["slug"] for c in out}
    for c in out:
        if c["parent"] and c["parent"] not in slugs:
            raise SystemExit(f"category {c['slug']} has no parent in the export")
    return out


def export_styles(password: str, factory: Path, categories: set[str]) -> tuple[list[dict], int]:
    rows = query(password, (
        "SELECT JSON_OBJECT('id', p.id, 'kind', p.kind, 'title', p.title, 'description', p.description, "
        "'prompt', p.prompt, 'text_zones', p.text_zones, 'category', p.category, 'sort', p.sort, "
        "'preview_disk', f.filename_disk) "
        "FROM image_prompt_presets p LEFT JOIN directus_files f ON f.id = p.preview "
        "WHERE p.status = 'published' AND p.visibility = 'global' AND p.kind IN ('style', 'photo_style') "
        "ORDER BY FIELD(p.kind, 'style', 'photo_style'), p.sort, p.id"
    ))
    previews = SEEDS / "previews"
    previews.mkdir(parents=True, exist_ok=True)
    for old in previews.glob("*.jpg"):
        old.unlink()
    total = 0
    out = []
    for row in rows:
        prefix = "style" if row["kind"] == "style" else "photo"
        code = f"{prefix}-{row['id']}"
        if row["category"] and row["category"] not in categories:
            raise SystemExit(f"{code}: category {row['category']} is not in the export")
        zones = row.get("text_zones")
        if isinstance(zones, str):
            zones = json.loads(zones) if zones.strip() else None
        item = {"code": code, "kind": row["kind"], "title": row["title"], "description": row["description"] or "",
                "prompt": row["prompt"] or "", "text_zones": zones, "category": row["category"],
                "sort": row["sort"] or 0, "preview": None}
        if row.get("preview_disk"):
            src = factory / ".data/directus/uploads" / row["preview_disk"]
            with Image.open(src) as img:
                img = img.convert("RGB")
                img.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=PREVIEW_QUALITY, optimize=True, progressive=True)
            dest = previews / f"{code}.jpg"
            dest.write_bytes(buf.getvalue())
            total += len(buf.getvalue())
            item["preview"] = f"previews/{code}.jpg"
        out.append(item)
    return out, total


def export_layers(password: str) -> list[str]:
    wanted = [code for codes in LAYERS.values() for code in codes]
    listed = ", ".join(f"'{code}'" for code in wanted)
    rows = query(password, (
        "SELECT JSON_OBJECT('code', code, 'name', name, 'description', description, 'version', version, "
        f"'template', template) FROM cf_prompts WHERE kind = 'layer' AND active = 1 AND code IN ({listed})"
    ))
    by_code = {row["code"]: row for row in rows}
    missing = sorted(set(wanted) - set(by_code))
    if missing:
        raise SystemExit(f"layers missing in factory: {missing}")
    written = []
    for group, codes in LAYERS.items():
        for code in codes:
            row = by_code[code]
            header = {
                "code": code,
                "version": 1,
                "role": None,
                "response": "text",
                "description": (row.get("name") or code).strip(),
                "kind": "layer",
                "engine": "layers",
                "source": f"factory cf_prompts {code} v{row.get('version') or 1}",
            }
            folder = PROMPTS / group / code
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "v1.md"
            if path.exists():
                written.append(str(path.relative_to(ROOT)) + " (kept)")
                continue
            text = "---\n" + yaml.safe_dump(header, allow_unicode=True, sort_keys=False, width=1000) + "---\n"
            path.write_text(text + (row["template"] or "").strip("\n") + "\n", encoding="utf-8")
            written.append(str(path.relative_to(ROOT)))
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--factory", default="/home/japanes/projects/factory", type=Path)
    args = parser.parse_args()
    password = db_password(args.factory)

    categories = export_categories(password, args.factory)
    styles, preview_bytes = export_styles(password, args.factory, {c["slug"] for c in categories})
    SEEDS.mkdir(parents=True, exist_ok=True)
    (SEEDS / "categories.json").write_text(
        json.dumps({"version": 1, "categories": categories}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (SEEDS / "styles.json").write_text(
        json.dumps({"version": 1, "styles": styles}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    layers = export_layers(password)

    kinds: dict[str, int] = {}
    for s in styles:
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    print(f"categories: {len(categories)}")
    print(f"styles: {kinds}")
    print(f"previews: {sum(1 for s in styles if s['preview'])} files, {preview_bytes} bytes")
    print(f"layers: {len(layers)} files")
    for line in layers:
        if line.endswith("(kept)"):
            print("  kept existing", line)


if __name__ == "__main__":
    sys.exit(main())
