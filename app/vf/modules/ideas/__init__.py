"""Shot ideas and niche research (module 05): a brief in, a concept and one
production prompt per frame out, drawn by the image studio (module 04).

Everything happens in a chat (module 15): the «Ideas» button of the composer
opens the brief window, the set is a chat message of kind ``ideas.concept`` with
editable cards, «Draw» / «Draw all» put an ordinary picture result under it.

HTTP: /api/ideas/… (contract in docs/dev/ideas-api.md). Python API::

    from vf.modules import ideas

    ideas.start({"chat_id": 3, "brief": {"niche": "…"}, "scene": {}, "research": False,
                 "draw_first": True, "product_to_frames": False})   # {set, message}; job "ideas.write"
    ideas.get_set(set_id)                  # the view the card shows
    ideas.draw_cards(set_id, "all") / ideas.draw_cards(set_id, [2])  # {set, message}
    ideas.roll_scene()                     # a free setting by the dice

Journal refs: ("ideas_set", id), ("chat", id), ("chat_message", card id); purposes
"shot_ideas", "shot_research" (with Google Search) and "shot_idea_frame" (the dice on one card).
Job kind: "ideas.write" (group "text"). The card follows the set through "chat.updated".
"""

from vf.modules.ideas import usage as _usage  # noqa: F401  (media usages, spend refs)
from vf.modules.ideas import write as _write  # noqa: F401  (the job handler)
from vf.modules.ideas.draw import draw as draw_cards  # not ``draw``: that name is the submodule
from vf.modules.ideas.routes import router
from vf.modules.ideas.scene import roll as roll_scene
from vf.modules.ideas.sets import get as get_set
from vf.modules.ideas.sets import sweep
from vf.modules.ideas.write import start


async def on_startup() -> None:
    """Sets left "writing" by a stop of the app are closed with ``interrupted``."""
    sweep()


__all__ = ["draw_cards", "get_set", "on_startup", "roll_scene", "router", "start", "sweep"]
