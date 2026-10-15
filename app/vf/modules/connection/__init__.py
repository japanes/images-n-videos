"""Google connection (module 01): first-run wizard, key upload, connection checks.

The video module plugs in the live Omni check::

    from vf.modules.connection import register_omni_check
    register_omni_check(my_cheapest_omni_call)   # async fn(model) -> {"cost_usd": ...}
"""

from vf.modules.connection.routes import router
from vf.modules.connection.service import register_omni_check

__all__ = ["register_omni_check", "router"]
