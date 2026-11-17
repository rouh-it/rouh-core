"""The open network (phase 5): other makers' A2A agents reaching a Rouh at Stranger level, and
being found by email through rouh.land. Off by the owner's settings. Filled in by phase 5."""
from __future__ import annotations


async def a2a_endpoint(request):
    from rouh.web.common import refuse

    return refuse("This Rouh does not take messages from other agents.", 404)
