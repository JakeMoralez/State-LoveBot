"""Helpers for SQLite vs PostgreSQL database URLs."""

from __future__ import annotations


def is_sqlite_url(url: str) -> bool:
    return (url or "").strip().lower().startswith("sqlite:")


def is_postgres_url(url: str) -> bool:
    raw = (url or "").strip().lower()
    return raw.startswith("postgres://") or raw.startswith("postgresql://")
