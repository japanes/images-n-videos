"""Text on image and the canvas editor (module 06).

The «Text on image» action under a picture of the chat (module 15) opens a full-screen tool on
that studio frame (module 04): the words (written by hand or by the ``image_text`` model), their
places (editor layers → the style's text map → the paid ``text_placement`` vision call → the
bottom third), the canvas with text, logo and shape layers, ready layouts and new backgrounds.
«Save» draws the layers with Pillow and puts the picture into the frame as a new version
(source «editor»); the layers stay with it, so the next opening shows them again.

HTTP: /api/text/… (contract in docs/dev/text-api.md). Python API::

    from vf.modules import text

    text.open_design({"frame_id": 7, "file_id": 31, "chat_id": 2, "message_id": 40})  # the design view
    text.save_design(design_id)          # {design, frame, report, file}: a new frame version
    text.render_png(design_id)           # (png, report) without storing anything
    text.ensure_font_sheet(kit_id)       # the kit's type specimen {file_id, url, fonts, …} (free)
    text.font_sheet_parts(kit_id)        # [label, Blob] for «the model draws the letters» (studio)
    text.font_sheet_rule()               # the line the picture prompt gets with the sheet
    await text.add_google_font(kit_id, "Montserrat")   # downloads the TTF, brand.add_catalog_font

Journal refs: ("text_design", id), ("frame", id), ("chat", id), ("chat_message", id); purposes
"text_placement", "text_write", "text_variants", "text_humanize", "text_background".
Job kind: "text.background" (group "image", ref "text_design"). Events: "text.updated"
``{design_id, …}`` after every change a running job or a save makes.
"""

from vf.modules.text import backgrounds as _backgrounds  # noqa: F401  (the job handler)
from vf.modules.text import usage as _usage  # noqa: F401  (media usages, spend refs)
from vf.modules.text.backgrounds import sweep
from vf.modules.text.designs import open_design, render_png, view
from vf.modules.text.designs import save as save_design
from vf.modules.text.font_sheet import ensure_sheet as ensure_font_sheet
from vf.modules.text.font_sheet import lettering_rule as font_sheet_rule
from vf.modules.text.font_sheet import studio_parts as font_sheet_parts
from vf.modules.text.google_fonts import add_to_kit as add_google_font
from vf.modules.text.routes import router


async def on_startup() -> None:
    """Backgrounds left «drawing» by a stop of the app are closed with ``interrupted``."""
    sweep()


__all__ = ["add_google_font", "ensure_font_sheet", "font_sheet_parts", "font_sheet_rule", "on_startup",
           "open_design", "render_png", "router", "save_design", "sweep", "view"]
