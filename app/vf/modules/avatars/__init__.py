"""Avatars (module 09): one person — photographed or invented — with a written
identity, a chosen face and a pack of 36 shots drawn against it.

Everything happens in an avatar chat (module 15, chat kind "avatar"): the card
of the avatar, «Describe» (the identity), the face candidates and the pack are
chat messages of the kinds ``avatar.card``, ``avatar.identity``,
``avatar.candidates`` and ``avatar.pack``. The full-screen 36-slot grid works on
the same avatar and its results come back to the same chat.

A ready avatar is mirrored into a "person" subject of the brand library
(module 08), so it is picked in the studio like any subject and called with
``@name`` in any chat.

HTTP: /api/avatars/… (contract in docs/dev/avatars-api.md). Python API::

    from vf.modules import avatars

    avatars.create({"name": "Anna", "mode": "reference"})   # {avatar, chat_id, message_id}
    avatars.get(avatar_id) / avatars.list_avatars()
    avatars.estimate(avatar_id, {"action": "pack"})        # price and time before the button

Journal refs: ("avatar", id), ("avatar_photo", id), ("chat", id), ("chat_message", id);
purposes "avatar_identity", "avatar_master", "avatar_shot", "avatar_fix".
Job kinds: "avatar.photo" (group "avatar"), "avatar.describe" (group "text").
Events: "avatars.updated" {what: "avatar", avatar_id, chat_id} (+ "chat.updated" for the messages).
"""

from vf.modules.avatars import draw as _draw  # noqa: F401  (the job handler)
from vf.modules.avatars import identity as _identity  # noqa: F401  (the job handler)
from vf.modules.avatars import usage as _usage  # noqa: F401  (media usages, spend refs, sweeper)
from vf.modules.avatars.estimate import estimate
from vf.modules.avatars.routes import router
from vf.modules.avatars.store import create, get, list_avatars


async def on_startup() -> None:
    """Pictures and «Describe» messages left running by a stop of the app are put in order."""
    _draw.sweep()
    _identity.settle_all()


__all__ = ["create", "estimate", "get", "list_avatars", "on_startup", "router"]
