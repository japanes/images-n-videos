"""Style library and prompt templates (module 07).

Python API for the studio (04), the chat (15), ideas (05), text (06), avatars (09)
and video (11)::

    from vf.modules import library

    # styles — the picker, the dice, the brief
    library.list_styles(tab="all", kind="style", category="obuv", q="neon", limit=48)
    library.category_tree(tab="all", kind="style")   # flat list with parent links and counts
    library.get_style(42) / library.get_style("style-14")   # raises not_found
    library.find_style(42)                               # None when gone
    library.random_style(kind="style", exclude=last_id)  # the dice next to the chat input
    ref = library.make_style_ref(style, {"brand": "SALT"}, extra="warmer light")   # what a brief stores
    library.render_style(ref)            # {preset_id, kind, title, prompt, text_zones, values, ...} or None
    library.resolve_style_value(value)   # a brief field: reference or plain typed words
    library.photo_style_text(photo_style_id)   # wording or None (plain photo)
    library.preview_blob(42)             # google.Blob of the example picture, or None

    # service prompt templates ("layers", app/prompts/layers/...)
    library.render_layer("IMAGE_PART_STYLE_SAMPLE", {...})
    library.layer_variables("PROMPT_BLOCK_IMAGE_STYLE")

Built-ins are synced from ``app/seeds/library`` on every start (``seed.sync``).
"""

from vf.modules.library import seed
from vf.modules.library.routes import router
from vf.modules.library.service import (
    KINDS,
    category_path,
    category_tree,
    copy_style,
    create_style,
    delete_style,
    find_style,
    get_style,
    list_styles,
    photo_style_text,
    preview_blob,
    random_style,
    render_style,
    resolve_style_value,
    update_style,
)
from vf.modules.library.templates import (
    layer_codes,
    layer_variables,
    render_layer,
    render_text,
    resolve_layers,
)
from vf.modules.library.variables import (
    extract_variables,
    fill_variables,
    is_style_ref,
    make_style_ref,
    parse_style_ref,
    parse_text_zones,
)


async def on_startup() -> None:
    seed.sync()


__all__ = [
    "KINDS", "category_path", "category_tree", "copy_style", "create_style", "delete_style", "extract_variables",
    "fill_variables", "find_style", "get_style", "is_style_ref", "layer_codes", "layer_variables", "list_styles",
    "make_style_ref", "on_startup", "parse_style_ref", "parse_text_zones", "photo_style_text", "preview_blob",
    "random_style", "render_layer", "render_style", "render_text", "resolve_layers", "resolve_style_value",
    "router", "update_style",
]
