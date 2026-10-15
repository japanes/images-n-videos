"""Spend log screen (module 03).

The journal itself (``ai_calls``, ``ai_call_refs``) lives in the core gateway;
this package only reads it: totals against the trial credit, a chart by days,
the table of calls with filters and the full card of one call.

Other modules can say what a ref points to (title and page link) so the call
card can link back to it::

    from vf.modules.spend import register_ref
    register_ref("work", lambda work_id: {"title": "...", "link": f"/chat/{chat_id}"})
"""

from vf.modules.spend.refs import register_ref
from vf.modules.spend.routes import router

__all__ = ["register_ref", "router"]
