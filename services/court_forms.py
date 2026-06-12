"""Парсинг и форматирование игровых форм (/form, /forms)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from database.models.court_form import CourtForm, CourtFormStatus, CourtFormType
from database.repository.court_form_repo import NewCourtForm

_FORM_CMD_RE = re.compile(
    r"^[!/]?(uvaloff|apunishoff|unapunishoff|notif)\b",
    re.IGNORECASE,
)
_THREAD_ID_RE = re.compile(
    r"(?:https?://)?(?:[\w.-]+\.)?arizona-rp\.com/threads/(?:[^/\s?#]+\.)?(\d+)",
    re.IGNORECASE,
)
_LAWSUIT_HASH_RE = re.compile(r"(?:суд\s*#?\s*|#)(\d+)", re.IGNORECASE)
_NICK_RE = re.compile(r"^[A-Za-z0-9]+_[A-Za-z0-9_]*$")
_NOTIF_LINE_RE = re.compile(r"^[!/]?notif\b", re.IGNORECASE)

_STATUS_LABELS: dict[str, str] = {
    CourtFormStatus.PENDING: "🕐 Ожидает",
    CourtFormStatus.ACCEPTED: "✅ Принята",
    CourtFormStatus.REJECTED: "❌ Отклонена",
}

_FORM_TYPE_LABELS: dict[str, str] = {
    CourtFormType.UVALOFF: "Увольнение",
    CourtFormType.APUNISHOFF: "ТСР (посадить)",
    CourtFormType.UNAPUNISHOFF: "ТСР (вытащить)",
    CourtFormType.NOTIF: "Уведомление",
}

FORM_HELP_TEXT = (
    "📋 Заполнение форм\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "✅ Примеры команд\n\n"
    "♻ Увольнение из организации\n"
    "/uvaloff Nick_Name суд #12345\n\n"
    "♻ Посадить игрока в ТСР\n"
    "/apunishoff Nick_Name 3 суд #12345\n\n"
    "♻ Вытащить игрока из ТСР\n"
    "/unapunishoff Nick_Name суд #12345\n\n"
    "♻ Уведомление игроку\n"
    "/notif Nick_Name Текст сообщения\n\n"
    "💡 Многострочное /notif — одна форма.\n"
    "Строки без /notif дополняются автоматически:\n"
    "/notif Jack_Stabos Здравствуйте! Иск (...)\n"
    "Предоставьте видео...\n"
    "→ сохранится как две команды /notif с тем же ником.\n\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "ℹ️ Номер иска — цифры в URL после /threads/\n"
    "ℹ️ Ник строго с «_», иначе будет ошибка"
)

VK_MESSAGE_LIMIT = 4090


@dataclass
class ParsedCourtForm:
    form: NewCourtForm


@dataclass
class FormParseFailure:
    line_hint: str
    reason: str


def form_type_label(form_type: str) -> str:
    return _FORM_TYPE_LABELS.get(form_type, form_type)


def format_status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, status)


def _form_word(count: int) -> str:
    n = abs(count) % 100
    n1 = n % 10
    if 11 <= n <= 19:
        return "форм"
    if n1 == 1:
        return "форму"
    if 2 <= n1 <= 4:
        return "формы"
    return "форм"


def _strip_form_command(text: str, command: str) -> str:
    pattern = re.compile(rf"^[!/]?{re.escape(command)}\s*", re.IGNORECASE)
    return pattern.sub("", text.strip(), count=1).strip()


def _validate_nick(nick: str) -> str | None:
    nick = nick.strip()
    if not nick:
        return "не указан ник"
    if "_" not in nick:
        return f"ник «{nick}» без «_»"
    if not _NICK_RE.match(nick):
        return f"некорректный ник «{nick}»"
    return None


def _extract_lawsuit_id(text: str) -> int | None:
    match = _THREAD_ID_RE.search(text)
    if match:
        return int(match.group(1))
    match = _LAWSUIT_HASH_RE.search(text)
    if match:
        return int(match.group(1))
    parts = text.split()
    if parts and parts[-1].isdigit():
        return int(parts[-1])
    return None


def _split_blocks(body: str) -> list[str]:
    lines = body.splitlines()
    blocks: list[str] = []
    current: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                current.append("")
            continue
        if _FORM_CMD_RE.match(stripped):
            if current:
                first_line = current[0].strip().lower()
                if (
                    first_line.startswith(("/notif", "!notif"))
                    and _NOTIF_LINE_RE.match(stripped)
                ):
                    current.append(stripped)
                    continue
                blocks.append("\n".join(current).strip())
            current = [stripped]
        elif current:
            current.append(stripped)

    if current:
        blocks.append("\n".join(current).strip())
    return blocks


def _normalize_notif_raw_text(nick: str, lines: list[str]) -> str:
    """Продолжение без /notif → /notif Nick ...; уже с /notif — как есть."""
    out: list[str] = []
    rest = _strip_form_command(lines[0], "notif")
    parts = rest.split(maxsplit=1)
    first_msg = parts[1].strip() if len(parts) > 1 else ""
    out.append(f"/notif {nick} {first_msg}".rstrip())

    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if _NOTIF_LINE_RE.match(stripped):
            if not stripped.startswith("/"):
                stripped = "/" + stripped.lstrip("!")
            out.append(stripped)
        else:
            out.append(f"/notif {nick} {stripped}")
    return "\n".join(out)


def _form_block_text(row: CourtForm, *, with_ids: bool) -> str:
    block = row.raw_text.strip()
    if with_ids:
        return f"#{row.id}\n{block}"
    return block


def _split_text_chunks(blocks: list[str], *, empty_text: str | None) -> list[str]:
    if not blocks:
        return [empty_text] if empty_text else []

    chunks: list[str] = []
    current = ""
    for block in blocks:
        if not block:
            continue
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) > VK_MESSAGE_LIMIT and current:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or ([empty_text] if empty_text else [])


def format_forms_copy_list(
    rows: list[CourtForm],
    *,
    with_ids: bool = False,
    empty_text: str | None = "📭 Нет форм, ожидающих принятия.",
) -> list[str]:
    """Текст форм для копирования. with_ids — номер #id перед каждой формой."""
    blocks = [_form_block_text(row, with_ids=with_ids) for row in rows]
    blocks = [b for b in blocks if b]
    return _split_text_chunks(blocks, empty_text=empty_text)


def _parse_uvaloff(block: str) -> ParsedCourtForm | FormParseFailure:
    rest = _strip_form_command(block.splitlines()[0], "uvaloff")
    parts = rest.split(maxsplit=1)
    if not parts:
        return FormParseFailure("/uvaloff", "не указан ник")
    nick = parts[0]
    err = _validate_nick(nick)
    if err:
        return FormParseFailure("/uvaloff", err)
    lawsuit_text = parts[1] if len(parts) > 1 else ""
    lawsuit_id = _extract_lawsuit_id(lawsuit_text)
    if lawsuit_id is None:
        return FormParseFailure("/uvaloff", "не указан номер иска")
    return ParsedCourtForm(
        NewCourtForm(
            form_type=CourtFormType.UVALOFF,
            target_nickname=nick,
            lawsuit_id=lawsuit_id,
            raw_text=block,
        )
    )


def _parse_apunishoff(block: str) -> ParsedCourtForm | FormParseFailure:
    rest = _strip_form_command(block.splitlines()[0], "apunishoff")
    parts = rest.split()
    if len(parts) < 3:
        return FormParseFailure(
            "/apunishoff",
            "формат: /apunishoff Nick_Name 1-6 суд #номер",
        )
    nick, stars_raw, *lawsuit_parts = parts
    err = _validate_nick(nick)
    if err:
        return FormParseFailure("/apunishoff", err)
    try:
        stars = int(stars_raw)
    except ValueError:
        return FormParseFailure("/apunishoff", "звёзды должны быть числом 1–6")
    if stars < 1 or stars > 6:
        return FormParseFailure("/apunishoff", "звёзды — от 1 до 6")
    lawsuit_id = _extract_lawsuit_id(" ".join(lawsuit_parts))
    if lawsuit_id is None:
        return FormParseFailure("/apunishoff", "не указан номер иска")
    return ParsedCourtForm(
        NewCourtForm(
            form_type=CourtFormType.APUNISHOFF,
            target_nickname=nick,
            lawsuit_id=lawsuit_id,
            stars=stars,
            raw_text=block,
        )
    )


def _parse_unapunishoff(block: str) -> ParsedCourtForm | FormParseFailure:
    rest = _strip_form_command(block.splitlines()[0], "unapunishoff")
    parts = rest.split(maxsplit=1)
    if not parts:
        return FormParseFailure("/unapunishoff", "не указан ник")
    nick = parts[0]
    err = _validate_nick(nick)
    if err:
        return FormParseFailure("/unapunishoff", err)
    lawsuit_text = parts[1] if len(parts) > 1 else ""
    lawsuit_id = _extract_lawsuit_id(lawsuit_text)
    if lawsuit_id is None:
        return FormParseFailure("/unapunishoff", "не указан номер иска")
    return ParsedCourtForm(
        NewCourtForm(
            form_type=CourtFormType.UNAPUNISHOFF,
            target_nickname=nick,
            lawsuit_id=lawsuit_id,
            raw_text=block,
        )
    )


def _parse_notif(block: str) -> ParsedCourtForm | FormParseFailure:
    lines = block.splitlines()
    rest = _strip_form_command(lines[0], "notif")
    parts = rest.split(maxsplit=1)
    if not parts:
        return FormParseFailure("/notif", "не указан ник")
    nick = parts[0]
    err = _validate_nick(nick)
    if err:
        return FormParseFailure("/notif", err)

    raw_text = _normalize_notif_raw_text(nick, lines)

    message_parts = []
    if len(parts) > 1 and parts[1].strip():
        message_parts.append(parts[1].strip())
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if _NOTIF_LINE_RE.match(stripped):
            line_rest = _strip_form_command(stripped, "notif")
            line_parts = line_rest.split(maxsplit=1)
            if len(line_parts) > 1 and line_parts[1].strip():
                message_parts.append(line_parts[1].strip())
        else:
            message_parts.append(stripped)

    message = "\n".join(message_parts).strip()
    if not message:
        return FormParseFailure("/notif", "не указан текст уведомления")
    lawsuit_id = _extract_lawsuit_id(message)
    return ParsedCourtForm(
        NewCourtForm(
            form_type=CourtFormType.NOTIF,
            target_nickname=nick,
            lawsuit_id=lawsuit_id,
            message=message,
            raw_text=raw_text,
        )
    )


def _parse_block(block: str) -> ParsedCourtForm | FormParseFailure:
    first = block.splitlines()[0].strip().lower()
    if first.startswith(("/uvaloff", "!uvaloff")):
        return _parse_uvaloff(block)
    if first.startswith(("/apunishoff", "!apunishoff")):
        return _parse_apunishoff(block)
    if first.startswith(("/unapunishoff", "!unapunishoff")):
        return _parse_unapunishoff(block)
    if first.startswith(("/notif", "!notif")):
        return _parse_notif(block)
    return FormParseFailure(block.splitlines()[0][:40], "неизвестная команда")


def parse_form_batch(body: str) -> tuple[list[NewCourtForm], list[FormParseFailure]]:
    blocks = _split_blocks(body)
    if not blocks:
        return [], []

    ok: list[NewCourtForm] = []
    failed: list[FormParseFailure] = []
    for block in blocks:
        result = _parse_block(block)
        if isinstance(result, FormParseFailure):
            failed.append(result)
        else:
            ok.append(result.form)
    return ok, failed


def format_submit_result(
    saved: int,
    failed: int,
    *,
    errors: list[FormParseFailure] | None = None,
) -> str:
    lines = [
        f"✅В базу данных записано {saved} {_form_word(saved)}✅",
        f"⛔Не удалось записать {failed} {_form_word(failed)}⛔",
    ]
    if errors:
        for item in errors[:8]:
            lines.append(f"• {item.line_hint}: {item.reason}")
        if len(errors) > 8:
            lines.append(f"… и ещё {len(errors) - 8}")
    return "\n".join(lines)


def format_pending_copy_list(rows: list[CourtForm]) -> list[str]:
    """Без номеров — для вставки в игру."""
    return format_forms_copy_list(rows, with_ids=False)


def format_pending_list_with_ids(rows: list[CourtForm]) -> list[str]:
    """С #id перед каждой формой — для модерации."""
    return format_forms_copy_list(rows, with_ids=True)


def format_my_forms(rows: list[CourtForm]) -> str:
    if not rows:
        return "📭 У вас пока нет отправленных форм."

    lines = [f"📂 Ваши формы ({len(rows)}):", ""]
    for row in rows:
        status = format_status_label(row.status)
        extra = ""
        if row.status == CourtFormStatus.REJECTED and row.reject_reason:
            extra = f" · {row.reject_reason[:60]}"
        lines.append(
            f"{status} · #{row.id} · {form_type_label(row.form_type)} · "
            f"{row.target_nickname}{extra}"
        )
    return "\n".join(lines)


def format_review_usage() -> str:
    return (
        "📋 Модерация форм\n\n"
        "/forms — команды для игры (без номеров)\n"
        "/forms id — то же, с #id формы\n"
        "/acceptform [id|all] — принять\n"
        "/rejectform [id|all] [причина] — отклонить\n\n"
        "Или кнопки в беседе след. ЦА при новой заявке."
    )
