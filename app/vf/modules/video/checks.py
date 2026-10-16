"""The live Omni check of the connection screen: the cheapest real Omni clip.

Omni answers only to a real request, so the check pays for the shortest clip the
model allows at the smallest resolution. The clip is kept in the media library
("Connection test") so the money was not spent on nothing.
"""

from __future__ import annotations

from vf.core import files, prompts
from vf.core.google import video as google_video
from vf.core.google.gateway import PromptInfo
from vf.modules.connection import register_omni_check
from vf.modules.video import catalog

CHECK_PROMPT = "video.omni_check"
PURPOSE = "connection_check"


def check_request(m: dict) -> dict:
    """The smallest request the model takes: lowest resolution, shortest length, 16:9 when allowed."""
    table = catalog.resolutions(m)
    resolution = min(table, key=catalog.resolution_rank) if table else "720p"
    lengths = catalog.durations(m, resolution) or [4]
    shapes = catalog.aspects(m)
    aspect = "16:9" if "16:9" in shapes or not shapes else shapes[0]
    return {"seconds": int(min(lengths)), "resolution": resolution, "aspect": aspect}


async def omni_check(m: dict) -> dict:
    """``fn(model)`` for the connection module. Raises ``GoogleCallError`` when Google refuses."""
    rp = prompts.render(CHECK_PROMPT)
    req = check_request(m)
    answer = await google_video.generate_omni(
        model=m, prompt=rp.text.strip(), seconds=req["seconds"], resolution=req["resolution"],
        aspect=req["aspect"], purpose=PURPOSE, prompt_info=PromptInfo(rp.code, rp.version))
    saved = files.save_bytes(answer.data, mime=answer.mime, name="connection-test", origin="generated",
                             title="Connection test", source_type="connection_check")
    return {"cost_usd": round(answer.cost_usd or 0.0, 6), "file_id": saved["id"]}


register_omni_check(omni_check)

__all__ = ["check_request", "omni_check"]
