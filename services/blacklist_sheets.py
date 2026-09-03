"""Проверка чёрных списков (Google Sheets, публичный CSV export)."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass
from difflib import SequenceMatcher

import aiohttp

from config.settings import BLACKLIST_CACHE_TTL_SEC, BLACKLIST_SHEET_ID

logger = logging.getLogger(__name__)

BLACKLIST_TABS: tuple[str, ...] = (
    "ЧС Лидеров/Замов",
    "ЧС ГОС",
    "ЧС ЦА",
    "ЧС МЮ",
    "ЧС МО",
    "ЧС МЗ",
)

_FUZZY_THRESHOLD = 0.86
_FIRST_PART_THRESHOLD = 0.78
_LAST_PART_THRESHOLD = 0.88

_cache_lock = asyncio.Lock()
_cache_rows: dict[str, list[list[str]]] | None = None
_cache_at: float = 0.0


@dataclass(frozen=True)
class BlacklistHit:
    sheet: str
    uuid: str
    nickname: str
    status: str
    reason: str
    date_added: str
    date_removed: str
    degree: str
    admin: str
    sphere: str
    match_score: float


def _normalize_nick(value: str) -> str:
    text = (value or "").strip().lower()
    text = text.replace("［", "[").replace("］", "]")
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"[^\w\s_]+", " ", text, flags=re.UNICODE)
    text = re.sub(r"[\s]+", "_", text.strip())
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _nick_variants(cell: str) -> list[str]:
    raw = (cell or "").strip()
    if not raw:
        return []
    parts = re.split(r"\s*/\s*", raw)
    variants: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for candidate in (part, part.replace(" ", "_")):
            norm = _normalize_nick(candidate)
            if norm and norm not in seen:
                seen.add(norm)
                variants.append(norm)
    return variants


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _nickname_match_score(query: str, cell: str) -> float:
    q = _normalize_nick(query)
    if not q:
        return 0.0
    q_parts = [p for p in q.split("_") if p]
    best = 0.0
    for nick in _nick_variants(cell):
        if q == nick:
            return 1.0

        n_parts = [p for p in nick.split("_") if p]

        # Name_Surname — обе части должны совпасть (не только фамилия)
        if len(q_parts) >= 2 and len(n_parts) >= 2:
            first = _similarity(q_parts[0], n_parts[0])
            last = _similarity(q_parts[-1], n_parts[-1])
            if first >= _FIRST_PART_THRESHOLD and last >= _LAST_PART_THRESHOLD:
                best = max(best, first * 0.55 + last * 0.45)
            continue

        ratio = _similarity(q, nick)
        if ratio >= _FUZZY_THRESHOLD:
            best = max(best, ratio)

        # Одно слово в запросе — допускаем вхождение в ник (Daniel + Bradberry)
        if len(q_parts) == 1 and len(q) >= 4:
            if q == nick:
                best = max(best, 1.0)
            elif nick.endswith(f"_{q}") or nick.startswith(f"{q}_"):
                best = max(best, 0.95)
    return best


def _find_header_row(rows: list[list[str]]) -> int:
    for idx, row in enumerate(rows[:15]):
        joined = " ".join(cell or "" for cell in row).lower()
        if "никнейм" in joined or "игровой ник" in joined:
            return idx
    for idx, row in enumerate(rows[:15]):
        joined = " ".join(cell or "" for cell in row).lower()
        if "uuid" in joined and ("активен" in joined or "чс" in joined):
            return idx
    return 0


def _build_col_map(header_row: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        text = (cell or "").lower().strip()
        if not text:
            continue
        if "uuid" in text and "uuid" not in mapping:
            mapping["uuid"] = idx
        elif "никнейм" in text:
            mapping["nickname"] = idx
        elif "активен" in text or "чс активен" in text:
            mapping["status"] = idx
        elif "причин" in text:
            mapping["reason"] = idx
        elif "дата занес" in text:
            mapping["date_added"] = idx
        elif "дата вынес" in text:
            mapping["date_removed"] = idx
        elif "степень" in text:
            mapping["degree"] = idx
        elif "администратор" in text:
            mapping["admin"] = idx
        elif text == "сфера" or (text.startswith("сфера") and "дата" not in text):
            mapping["sphere"] = idx
    if "nickname" not in mapping and len(header_row) >= 2:
        second = (header_row[1] or "").lower()
        if "ник" in second:
            mapping["nickname"] = 1
    if "uuid" not in mapping and header_row:
        first = (header_row[0] or "").lower()
        if "uuid" in first:
            mapping["uuid"] = 0
    return mapping


def _cell(row: list[str], col_map: dict[str, int], key: str) -> str:
    idx = col_map.get(key)
    if idx is None or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def _parse_sheet_rows(sheet: str, rows: list[list[str]]) -> list[BlacklistHit]:
    if not rows:
        return []
    header_idx = _find_header_row(rows)
    col_map = _build_col_map(rows[header_idx])
    if "nickname" not in col_map:
        return []

    hits: list[BlacklistHit] = []
    for row in rows[header_idx + 1 :]:
        nickname = _cell(row, col_map, "nickname")
        if not nickname:
            continue
        hits.append(
            BlacklistHit(
                sheet=sheet,
                uuid=_cell(row, col_map, "uuid"),
                nickname=nickname,
                status=_cell(row, col_map, "status"),
                reason=_cell(row, col_map, "reason"),
                date_added=_cell(row, col_map, "date_added"),
                date_removed=_cell(row, col_map, "date_removed"),
                degree=_cell(row, col_map, "degree"),
                admin=_cell(row, col_map, "admin"),
                sphere=_cell(row, col_map, "sphere"),
                match_score=0.0,
            )
        )
    return hits


async def _fetch_tab(session: aiohttp.ClientSession, sheet: str) -> list[list[str]]:
    url = (
        f"https://docs.google.com/spreadsheets/d/{BLACKLIST_SHEET_ID}/gviz/tq"
        f"?tqx=out:csv&sheet={urllib.parse.quote(sheet)}"
    )
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
        resp.raise_for_status()
        raw = await resp.text()
    return list(csv.reader(io.StringIO(raw)))


async def _load_all_tabs(*, force: bool = False) -> dict[str, list[BlacklistHit]]:
    global _cache_rows, _cache_at

    now = time.time()
    async with _cache_lock:
        if (
            not force
            and _cache_rows is not None
            and now - _cache_at < BLACKLIST_CACHE_TTL_SEC
        ):
            parsed = {
                tab: _parse_sheet_rows(tab, rows)
                for tab, rows in _cache_rows.items()
            }
            return parsed

        async with aiohttp.ClientSession() as session:
            results = await asyncio.gather(
                *(_fetch_tab(session, tab) for tab in BLACKLIST_TABS),
                return_exceptions=True,
            )

        rows_by_tab: dict[str, list[list[str]]] = {}
        for tab, result in zip(BLACKLIST_TABS, results, strict=True):
            if isinstance(result, Exception):
                logger.warning("blacklist fetch failed tab=%s: %s", tab, result)
                rows_by_tab[tab] = []
                continue
            rows_by_tab[tab] = result
            logger.info(
                "blacklist tab=%s rows=%s parsed=%s",
                tab,
                len(result),
                len(_parse_sheet_rows(tab, result)),
            )

        _cache_rows = rows_by_tab
        _cache_at = now

    return {tab: _parse_sheet_rows(tab, rows) for tab, rows in rows_by_tab.items()}


def _normalize_account_id(value: str) -> str:
    text = (value or "").strip()
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def _is_account_id_query(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    # Игровой ник Name_Surname — не ID аккаунта
    if re.fullmatch(r"[A-Za-z0-9]+_[A-Za-z0-9_]*", q):
        return False
    if q.isdigit():
        return True
    if re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        q,
        re.IGNORECASE,
    ):
        return True
    if re.fullmatch(r"[0-9a-f]{8,}", q, re.IGNORECASE):
        return True
    return False


def _account_id_match_score(query: str, entry_uuid: str) -> float:
    if not entry_uuid:
        return 0.0
    q = _normalize_account_id(query).lower()
    uid = _normalize_account_id(entry_uuid).lower()
    if not q or not uid:
        return 0.0
    if q == uid:
        return 1.0
    if len(q) >= 8 and q in uid:
        return 0.98
    return 0.0


def _is_active_status(status: str) -> bool:
    text = (status or "").strip().lower()
    if text in {"вынесен"} or "вынес" in text:
        return False
    if text in {"активен", "вечный", "бессрочно", "без права на амнистию"}:
        return True
    return bool(text)


def _status_emoji(status: str) -> str:
    return "🟥" if _is_active_status(status) else "🟩"


def search_blacklist(query: str, entries_by_tab: dict[str, list[BlacklistHit]]) -> list[BlacklistHit]:
    q = (query or "").strip()
    if not q:
        return []

    q_lower = q.lower()
    is_account_id = _is_account_id_query(q)

    found: list[BlacklistHit] = []
    seen: set[tuple[str, str, str]] = set()

    for tab, entries in entries_by_tab.items():
        for entry in entries:
            score = 0.0
            if is_account_id:
                score = _account_id_match_score(q, entry.uuid)
            else:
                score = _nickname_match_score(q, entry.nickname)

            if score < _FUZZY_THRESHOLD:
                continue

            key = (tab, entry.nickname.lower(), entry.date_added)
            if key in seen:
                continue
            seen.add(key)
            found.append(
                BlacklistHit(
                    sheet=entry.sheet,
                    uuid=entry.uuid,
                    nickname=entry.nickname,
                    status=entry.status,
                    reason=entry.reason,
                    date_added=entry.date_added,
                    date_removed=entry.date_removed,
                    degree=entry.degree,
                    admin=entry.admin,
                    sphere=entry.sphere,
                    match_score=score,
                )
            )

    found.sort(
        key=lambda h: (
            -int(_is_active_status(h.status)),
            -h.match_score,
            h.sheet,
            h.nickname.lower(),
        )
    )
    return found


def format_blacklist_results(
    query: str,
    hits: list[BlacklistHit],
    *,
    tabs_checked: int | None = None,
) -> str:
    if not hits:
        suffix = ""
        if tabs_checked:
            suffix = f"\nℹ️ Проверены все {tabs_checked} листов таблицы."
        return f"✅ {query} — не найден в чёрных списках.{suffix}"

    lines = [f"📋 Чёрный список — {query}"]
    if hits[0].match_score < 0.999:
        lines.append(
            f"ℹ️ Найдено по похожести ({int(hits[0].match_score * 100)}%): {hits[0].nickname}"
        )

    for hit in hits[:8]:
        status = hit.status or "—"
        degree = f" ({hit.degree})" if hit.degree else ""
        lines.append(f"\n{_status_emoji(status)} {hit.sheet} — {status}{degree}")
        lines.append(f"Ник: {hit.nickname}")
        lines.append(f"ID аккаунта: {hit.uuid or 'нет'}")
        if hit.sphere:
            lines.append(f"Сфера: {hit.sphere}")
        if hit.reason:
            lines.append(f"Причина: {hit.reason}")
        meta: list[str] = []
        if hit.date_added:
            meta.append(f"занесён: {hit.date_added}")
        if hit.date_removed:
            meta.append(f"вынесен: {hit.date_removed}")
        if hit.admin:
            meta.append(f"админ: {hit.admin}")
        if meta:
            lines.append(" · ".join(meta))

    if len(hits) > 8:
        lines.append(f"\n… и ещё {len(hits) - 8} записей.")
    return "\n".join(lines)


async def check_blacklist(query: str) -> str:
    if not BLACKLIST_SHEET_ID:
        return "❌ Таблица чёрных списков не настроена."
    q = (query or "").strip()
    if not q:
        return "❌ /checkbl [ник / ID аккаунта]\nПример: /checkbl Daniel_Bradberry"

    try:
        entries = await _load_all_tabs()
    except Exception as exc:
        logger.exception("blacklist load failed: %s", exc)
        return "❌ Не удалось загрузить таблицу чёрных списков."

    hits = search_blacklist(q, entries)
    loaded_tabs = sum(1 for rows in entries.values() if rows)
    return format_blacklist_results(
        q,
        hits,
        tabs_checked=len(BLACKLIST_TABS) if loaded_tabs else None,
    )
