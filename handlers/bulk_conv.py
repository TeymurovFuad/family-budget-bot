"""/bulk conversation — import transactions from photo, file, or pasted text."""

import asyncio
import json
import re
from datetime import datetime, date, timezone
from pathlib import Path

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.error import BadRequest
from telegram.ext import ContextTypes, ConversationHandler

from ai_parser import parse_text, parse_image, _chunk_statement_text
from config import auth, log
from data import load_reference_data
import settings
from excel_ops import async_append_batch
from models import Transaction
from states import BULK_RECEIVE, BULK_CONFIRM



async def _announce_parse_plan(update: Update, text: str) -> None:
    """Tell the user up front when a large input will be parsed in chunks."""
    n_chunks = len(_chunk_statement_text(text))
    if n_chunks > 1:
        await update.message.reply_text(
            f"📄 That's a big statement — I'll parse it in {n_chunks} parts. "
            f"This can take a minute or two, hang on..."
        )
    else:
        await update.message.reply_text("🔍 Parsing transactions...")

def _bulk_draft_dir() -> Path:
    return settings.BULK_DRAFTS_DIR


def _user_draft_path(user_id: int) -> Path:
    return _bulk_draft_dir() / f"{user_id}.json"


def _load_bulk_drafts() -> dict[str, list[dict]]:
    draft_dir = _bulk_draft_dir()
    draft_dir.mkdir(parents=True, exist_ok=True)
    drafts: dict[str, list[dict]] = {}
    for path in draft_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                drafts[path.stem] = data
        except Exception:
            log.exception("Could not read bulk draft from %s", path)
    return drafts


def _load_user_draft(user_id: int) -> list[dict]:
    """Read one user's draft directly — avoids scanning every user's file."""
    path = _user_draft_path(user_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        log.exception("Could not read bulk draft from %s", path)
        return []


def _save_bulk_draft(user_id: int, rows: list[dict]) -> None:
    path = _user_draft_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def _delete_bulk_draft(user_id: int) -> None:
    path = _user_draft_path(user_id)
    if path.exists():
        path.unlink(missing_ok=True)


def _sort_bulk_rows(parsed: list[dict]) -> list[dict]:
    def _date_key(item: dict) -> tuple[int, date]:
        value = str(item.get("date", "")).strip()
        try:
            return (0, date.fromisoformat(value))
        except Exception:
            return (1, date.max)

    return sorted([dict(item) for item in parsed], key=_date_key)


def _merge_bulk_draft(user_id: int, parsed: list[dict]) -> list[dict]:
    previous = _load_user_draft(user_id)
    if not isinstance(previous, list):
        previous = []
    normalized_previous = []
    for item in previous:
        row = dict(item)
        row.setdefault("status", "pending")
        normalized_previous.append(row)
    merged = _sort_bulk_rows(normalized_previous + [dict(item) for item in parsed])
    for item in merged:
        item.setdefault("status", "pending")
    _save_bulk_draft(user_id, merged)
    log.info("User %s bulk draft updated: %d pending entries", user_id, len(merged))
    return merged


# Maximum rows a pending draft may hold before new imports are refused.
_DRAFT_LIMIT_ENTRIES = 50


def _normalize_parsed_rows(parsed: list[dict], lists: dict) -> tuple[list[dict], list[str]]:
    """
    Enforce Lists reference data on AI output — the model drifts no matter what
    the prompt says (invents 'Shopping' next to 'Gifts & Shopping', puts
    transfer recipients into person). Auto-correct what's unambiguous, report
    every correction so the user sees them in the preview.
    """
    categories = lists.get("categories") or []
    cat_by_lower = {c.lower(): c for c in categories}
    persons = {str(p).strip() for p in (lists.get("persons") or [])}
    types = set(lists.get("txn_types") or ["Expense", "Income", "Savings"])
    corrections: list[str] = []

    for i, row in enumerate(parsed, 1):
        # Category: exact -> case-insensitive -> substring fuzzy -> Other
        cat = str(row.get("category") or "").strip()
        if cat and cat not in categories:
            fixed = cat_by_lower.get(cat.lower())
            if not fixed:
                fuzzy = [c for c in categories
                         if cat.lower() in c.lower() or c.lower() in cat.lower()]
                fixed = fuzzy[0] if len(fuzzy) == 1 else None
            row["category"] = fixed or "Other"
            corrections.append(f"row {i}: category '{cat}' → '{row['category']}'")

        # Person: must be a known household member — recipients go to description
        per = str(row.get("person") or "").strip()
        if per and per not in persons:
            desc = str(row.get("description") or "").strip()
            row["description"] = (f"{desc} — {per}" if desc else per)[:120]
            row["person"] = ""
            corrections.append(f"row {i}: person '{per}' moved to description")

        # Type: whitelist, default Expense
        typ = str(row.get("type") or "").strip()
        if typ and typ not in types:
            ci = next((t for t in types if t.lower() == typ.lower()), None)
            row["type"] = ci or "Expense"
            corrections.append(f"row {i}: type '{typ}' → '{row['type']}'")

    return parsed, corrections


def _draft_limit_reached(user_id: int) -> bool:
    previous = _load_user_draft(user_id)
    if not isinstance(previous, list):
        return False
    return len(previous) > _DRAFT_LIMIT_ENTRIES


# Telegram hard limit is 4096 chars; leave headroom for the header/footer.
_PREVIEW_MSG_LIMIT = 3500


def _md_escape(text: str) -> str:
    """Escape Markdown control chars in untrusted text (bank descriptions etc.)."""
    return re.sub(r"([_*`\[\]])", r"\\\1", str(text))


def _format_bulk_preview(parsed: list[dict]) -> list[str]:
    """
    Render the draft preview as a LIST of messages, each under Telegram's
    length limit. Row numbers are stable across all pages.
    """
    footer = (
        "\nReply with edits like: `2 category=Transport` or `1 description=Lunch`\n"
        "Send `save` to store them all, or `cancel` to stop."
    )
    row_lines = []
    for i, t in enumerate(parsed, 1):
        person = t.get("person") or ""
        txn_type = t.get("type") or ""
        person_suffix = f" | person={_md_escape(person)}" if person else ""
        type_suffix = f" | type={_md_escape(txn_type)}" if txn_type else ""
        row_lines.append(
            f"{i}. {t.get('date', '')} | {t.get('value', '')} {t.get('currency', 'PLN')} | "
            f"{_md_escape(t.get('category', ''))} | {_md_escape(t.get('description', ''))}"
            f"{type_suffix}{person_suffix}"
        )

    messages = []
    current = [f"Found *{len(parsed)}* transaction(s):\n"]
    current_len = len(current[0])
    for line in row_lines:
        if current_len + len(line) + 1 > _PREVIEW_MSG_LIMIT:
            messages.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        messages.append("\n".join(current))

    messages[-1] += "\n" + footer
    return messages


async def _send_bulk_preview(update: Update, parsed: list[dict]) -> None:
    """Send the preview as one or more messages; keyboard only on the last."""
    keyboard = ReplyKeyboardMarkup([["Save", "Cancel"]], one_time_keyboard=True, resize_keyboard=True)
    pages = _format_bulk_preview(parsed)
    for i, page in enumerate(pages):
        try:
            await update.message.reply_text(
                page,
                parse_mode="Markdown",
                reply_markup=keyboard if i == len(pages) - 1 else None,
            )
        except BadRequest:
            # Malformed entity despite escaping — resend as plain text.
            await update.message.reply_text(
                page,
                reply_markup=keyboard if i == len(pages) - 1 else None,
            )


def _apply_bulk_edit(message: str, parsed: list[dict]) -> tuple[bool, str]:
    text = message.strip()
    if not text:
        return False, ""

    # Accept both "save" and "/save" — users naturally type slash commands.
    normalized = text.lower().lstrip("/")
    if normalized in {"save", "yes"}:
        return True, ""
    if normalized in {"cancel", "no"}:
        return False, "cancel"

    match = re.match(r"^(\d+)\s+(\w+)=(.+)$", text)
    if not match:
        return False, "invalid"

    idx = int(match.group(1)) - 1
    field = match.group(2).strip().lower()
    value = match.group(3).strip()
    if not (0 <= idx < len(parsed)):
        return False, "invalid"
    if field not in {"date", "value", "currency", "type", "category", "description", "person"}:
        return False, "invalid"

    if field == "value":
        try:
            value = float(value)
        except ValueError:
            return False, "invalid"

    parsed[idx][field] = value
    return False, "edited"


async def bulk_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Conversation expired while the user was reviewing — tell them how to resume."""
    if update.effective_message:
        await update.effective_message.reply_text(
            "⏰ Bulk import session expired, but your draft is safe. "
            "Run /bulk and send any text to see it again, then `save` or `cancel`.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
    return ConversationHandler.END


@auth
async def cmd_bulk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Resume an unfinished draft directly — no need to re-upload anything.
    draft = _load_user_draft(update.effective_user.id)
    if isinstance(draft, list) and draft:
        ctx.user_data["bulk_parsed"] = draft
        await update.message.reply_text(
            f"📋 You have an unfinished draft with {len(draft)} transaction(s). "
            f"Review it below — `save` to store, `cancel` to discard, "
            f"or edit rows first."
        )
        await _send_bulk_preview(update, draft)
        return BULK_CONFIRM

    await update.message.reply_text(
        "📎 Send me a photo, document, or paste your transaction text.\n"
        "I'll extract and preview all transactions before saving.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return BULK_RECEIVE


@auth
async def bulk_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    parsed = []
    lists  = load_reference_data()
    try:
        uid = update.effective_user.id
        src = 'unknown'
        loop = asyncio.get_running_loop()
        if update.message.photo:
            src = 'photo'
            photo       = update.message.photo[-1]
            file        = await photo.get_file()
            image_bytes = bytes(await file.download_as_bytearray())
            await update.message.reply_text("🔍 Analysing image...")
            parsed = await loop.run_in_executor(None, lambda: parse_image(image_bytes, lists))

        elif update.message.document:
            src = 'document'
            document = update.message.document
            file = await document.get_file()
            file_bytes = await file.download_as_bytearray()
            mime_type = (document.mime_type or "").lower()
            if mime_type and not mime_type.startswith("text/") and "plain" not in mime_type:
                await update.message.reply_text("Please upload a plain text file (.txt).")
                return BULK_RECEIVE
            text = file_bytes.decode("utf-8", errors="replace")
            await _announce_parse_plan(update, text)
            parsed = await loop.run_in_executor(None, lambda: parse_text(text, lists))

        elif update.message.text:
            src = 'text'
            text = update.message.text.strip()
            if text.startswith("/"):
                await update.message.reply_text("Send the transaction text, not a command.")
                return BULK_RECEIVE
            await _announce_parse_plan(update, text)
            parsed = await loop.run_in_executor(None, lambda: parse_text(text, lists))

        else:
            await update.message.reply_text("Send a photo, document, or text.")
            return BULK_RECEIVE

    except Exception as e:
        log.exception("bulk_receive parse error for user %s (src=%s)", update.effective_user.id, src)
        await update.message.reply_text(f"❌ Parsing failed: {e}")
        return ConversationHandler.END

    if not parsed:
        await update.message.reply_text("No transactions found in the input.")
        return ConversationHandler.END

    parsed, corrections = _normalize_parsed_rows(parsed, lists)
    if corrections:
        shown = "\n".join(f"  • {c}" for c in corrections[:10])
        more = f"\n  … and {len(corrections) - 10} more" if len(corrections) > 10 else ""
        await update.message.reply_text(
            f"🛡 Auto-corrected {len(corrections)} value(s) the AI got wrong:\n{shown}{more}"
        )
        log.info("User %s bulk normalize: %d corrections", uid, len(corrections))

    if _draft_limit_reached(uid):
        # Do NOT merge the new rows — but never discard them silently either.
        await update.message.reply_text(
            f"⚠️ Your draft is full ({_DRAFT_LIMIT_ENTRIES}+ entries), so the {len(parsed)} "
            f"row(s) I just parsed were NOT added. Send `save` to store the existing draft "
            f"or `cancel` to discard it — then re-send this input.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([["Save", "Cancel"]], one_time_keyboard=True, resize_keyboard=True),
        )
        ctx.user_data["bulk_parsed"] = _load_user_draft(uid)
        return BULK_CONFIRM

    parsed = _sort_bulk_rows(parsed)
    draft_rows = _merge_bulk_draft(uid, parsed)
    ctx.user_data["bulk_parsed"] = draft_rows
    log.info("User %s bulk parse completed: %d items (src=%s)", update.effective_user.id, len(parsed), src)
    if len(draft_rows) > len(parsed):
        await update.message.reply_text(
            f"ℹ️ {len(draft_rows) - len(parsed)} row(s) from a previous draft were merged in. "
            f"The preview below is the full set that `save` will store.",
            parse_mode="Markdown",
        )
    # Preview the MERGED draft — exactly what `save` will write.
    await _send_bulk_preview(update, draft_rows)
    return BULK_CONFIRM


@auth
async def bulk_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    parsed = _sort_bulk_rows(ctx.user_data.get("bulk_parsed", []))
    text = update.message.text.strip()
    action, reason = _apply_bulk_edit(text, parsed)

    if reason == "cancel":
        _delete_bulk_draft(update.effective_user.id)
        log.info("User %s cancelled bulk import draft", update.effective_user.id)
        await update.message.reply_text(
            "Cancelled — draft discarded.", reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    if reason == "edited":
        parsed = _sort_bulk_rows(parsed)
        ctx.user_data["bulk_parsed"] = parsed
        # Persist so a timeout/restart doesn't roll back to pre-edit values.
        _save_bulk_draft(update.effective_user.id, parsed)
        log.info("User %s edited bulk draft row via message: %s", update.effective_user.id, text)
        await _send_bulk_preview(update, parsed)
        return BULK_CONFIRM

    if reason == "invalid":
        await update.message.reply_text(
            "Please reply with edits like `2 category=Transport` or `1 description=Lunch`.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([["Save", "Cancel"]], one_time_keyboard=True, resize_keyboard=True),
        )
        return BULK_CONFIRM

    if not action:
        log.info("User %s sent non-action bulk message: %s", update.effective_user.id, text)
        await update.message.reply_text(
            "Please reply with edits, or send `save` to store them all.",
            reply_markup=ReplyKeyboardMarkup([["Save", "Cancel"]], one_time_keyboard=True, resize_keyboard=True),
        )
        return BULK_CONFIRM

    parsed = _sort_bulk_rows(parsed)
    ctx.user_data["bulk_parsed"] = parsed
    transactions  = []
    errors        = []
    failed_items  = []  # raw rows that never made it into `transactions`, kept for retry

    for i, item in enumerate(parsed, 1):
        try:
            txn_date = date.fromisoformat(item.get("date", str(datetime.now(timezone.utc).date())))
            transactions.append(Transaction(
                date=txn_date,
                value=float(item["value"]),
                currency=item.get("currency", "PLN").upper(),
                transaction_type=item.get("type", "Expense"),
                category=item.get("category", "Other"),
                person=item.get("person", ""),
                description=item.get("description", ""),
                is_recurring=False,
            ))
        except Exception as e:
            errors.append(f"Row {i}: {e}")
            failed_items.append(item)

    saved = 0
    write_failed = False
    if transactions:
        try:
            log.info("User %s saving bulk batch: %d transactions", update.effective_user.id, len(transactions))
            await async_append_batch(transactions)
            saved = len(transactions)
            log.info("User %s bulk batch saved: %d transactions", update.effective_user.id, saved)
        except Exception as e:
            log.exception("bulk_confirm batch write failed for user %s", update.effective_user.id)
            errors.append(f"Write failed: {e}")
            write_failed = True

    if write_failed:
        # The whole batch write failed — nothing was saved, so keep every row
        # (including the ones that parsed fine) in the draft for a clean retry.
        _save_bulk_draft(update.effective_user.id, parsed)
    elif failed_items:
        # Partial save: the valid rows are already in the workbook. Keep only
        # the rows that failed to construct so the user can fix/retry them
        # instead of losing them when the whole draft is wiped.
        _save_bulk_draft(update.effective_user.id, failed_items)
    else:
        _delete_bulk_draft(update.effective_user.id)

    if settings.STORAGE_BACKEND == "gcs" or settings.GCS_BUCKET_NAME:
        destination = f"gs://{settings.GCS_BUCKET_NAME}/{settings.GCS_OBJECT_NAME}"
    elif settings.STORAGE_BACKEND == "s3" or settings.S3_BUCKET_NAME:
        destination = f"s3://{settings.S3_BUCKET_NAME}/{settings.S3_OBJECT_NAME}"
    else:
        destination = str(settings.XLSX_PATH)
    msg = (
        f"✅ Saved {saved} of {len(parsed)} transaction(s) "
        f"to the MasterData sheet of:\n{destination}"
    )
    if errors:
        msg += "\n\n⚠️ Errors:\n" + "\n".join(errors[:5])
    if failed_items and not write_failed:
        msg += (
            f"\n\n{len(failed_items)} row(s) could not be saved and are kept in your draft — "
            "reply with edits (e.g. `1 value=12.50`) and send `save` again to retry them."
        )
    await update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END
