"""Models, roles and general settings (module 02).

The registry and the role table live in the core; this package adds the
availability check, checked price edits, the general settings and the API
behind the "Models" and "Settings" screens. Other modules may reuse::

    from vf.modules.models import service
    await service.check_availability()   # e.g. after a key is connected
    service.output_size("4:5")           # (1080, 1350)
"""

from vf.modules.models import service
from vf.modules.models.routes import router

__all__ = ["router", "service"]
