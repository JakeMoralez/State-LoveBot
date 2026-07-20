"""Domain errors — mapped to VK messages / HTTP status in adapters."""

from __future__ import annotations


class DomainError(Exception):
    """Base domain exception."""


class NotFoundError(DomainError):
    """Entity not found."""


class PermissionDeniedError(DomainError):
    """Caller lacks required access."""


class ValidationError(DomainError):
    """Invalid input / invariant broken."""
