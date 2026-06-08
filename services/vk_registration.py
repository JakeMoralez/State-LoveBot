"""Дата регистрации VK: foaf.php, затем оценка по ID."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import aiohttp

logger = logging.getLogger(__name__)

_FOAF_RE = re.compile(r'ya:created\s+dc:date="([^"]+)"', re.IGNORECASE)

# Грубые опорные точки (id → unix) для оценки, если foaf недоступен.
_VK_ID_ANCHORS: list[tuple[int, int]] = [
    (1, 1_160_956_800),
    (10_000, 1_167_609_600),
    (100_000, 1_175_385_600),
    (1_000_000, 1_206_931_200),
    (10_000_000, 1_262_304_000),
    (50_000_000, 1_325_376_000),
    (100_000_000, 1_356_998_400),
    (200_000_000, 1_420_070_400),
    (300_000_000, 1_451_606_400),
    (400_000_000, 1_483_228_800),
    (500_000_000, 1_514_764_800),
    (600_000_000, 1_546_300_800),
    (700_000_000, 1_577_836_800),
    (750_000_000, 1_609_459_200),
    (800_000_000, 1_640_995_200),
    (850_000_000, 1_672_531_200),
    (900_000_000, 1_704_067_200),
]


def _estimate_from_id(vk_id: int) -> datetime | None:
    if vk_id <= 0:
        return None
    anchors = _VK_ID_ANCHORS
    if vk_id <= anchors[0][0]:
        return datetime.fromtimestamp(anchors[0][1], tz=timezone.utc)
    if vk_id >= anchors[-1][0]:
        last_id, last_ts = anchors[-1]
        prev_id, prev_ts = anchors[-2]
        if last_id == prev_id:
            return datetime.fromtimestamp(last_ts, tz=timezone.utc)
        ratio = (vk_id - prev_id) / (last_id - prev_id)
        ts = int(prev_ts + ratio * (last_ts - prev_ts))
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    for (id_lo, ts_lo), (id_hi, ts_hi) in zip(anchors, anchors[1:]):
        if id_lo <= vk_id <= id_hi:
            if id_hi == id_lo:
                return datetime.fromtimestamp(ts_lo, tz=timezone.utc)
            ratio = (vk_id - id_lo) / (id_hi - id_lo)
            ts = int(ts_lo + ratio * (ts_hi - ts_lo))
            return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


async def _fetch_foaf_date(vk_id: int) -> datetime | None:
    url = f"https://vk.com/foaf.php?id={vk_id}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rdf+xml,application/xml,text/xml,*/*",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
    except Exception as exc:
        logger.debug("foaf fetch failed id=%s: %s", vk_id, exc)
        return None

    if not text:
        return None

    match = _FOAF_RE.search(text)
    if not match:
        return None

    raw = match.group(1).strip()
    try:
        if raw.isdigit():
            return datetime.fromtimestamp(int(raw), tz=timezone.utc)
        normalized = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except (ValueError, OSError, OverflowError):
        return None


async def resolve_registration_date(vk_id: int) -> tuple[datetime | None, str]:
    """(дата, источник): foaf | estimate | пусто."""
    foaf_dt = await _fetch_foaf_date(vk_id)
    if foaf_dt:
        return foaf_dt, "foaf"

    estimated = _estimate_from_id(vk_id)
    if estimated:
        return estimated, "estimate"
    return None, ""
