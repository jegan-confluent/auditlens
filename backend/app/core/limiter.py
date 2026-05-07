"""Shared slowapi Limiter instance.

Lives outside ``backend.app.main`` to avoid a circular import: route modules
need the limiter to decorate path operations, and ``main.py`` needs the route
modules to register them on the FastAPI app.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address


# Default budget is generous for normal dashboard traffic; the expensive
# /events list and detail routes layer on a stricter per-IP cap via their own
# ``@limiter.limit(...)`` decorators.
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
