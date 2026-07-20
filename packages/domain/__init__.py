"""Domain layer — entities and business rules.

No imports from Tortoise, FastAPI, vkbottle, or HTTP clients.
Apps and application import this; never the reverse.
"""

from packages.domain.access import ACCESS_LEVEL_NAMES, AccessLevel
from packages.domain.errors import DomainError, NotFoundError, PermissionDeniedError

__all__ = [
    "ACCESS_LEVEL_NAMES",
    "AccessLevel",
    "DomainError",
    "NotFoundError",
    "PermissionDeniedError",
]
