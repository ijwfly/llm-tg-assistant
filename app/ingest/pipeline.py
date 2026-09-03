"""Turn assembly from a batch of Telegram messages: downloads, transcription, staging, submit."""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path

from aiogram.types import Message

import settings
from app.core import actions
from app.core.runtime import TurnRequest
from app.ingest.classify import PROMPT, SKIP, STAGING, classify, forward_attribution, is_forward, is_voice
from app.ingest.transcribe import transcribe
from app.transport import texts

log = logging.getLogger(__name__)

GROUP_FORWARD, GROUP_FILE, GROUP_TRANSCRIPT, GROUP_TEXT = 0, 1, 2, 3
MB = 1024 * 1024
QUOTE_LIMIT = 700


@dataclass
class Item:
    kind: str                       # prompt | staging | skip
    group: int
    text: str = ""
    images: list[str] = field(default_factory=list)   # local paths of images to attach
    message_id: int | None = None
    staging_kind: str = "forward"


def reply_quote(message: Message, bot_id: int) -> str | None:
    reply = message.reply_to_message
    if reply is None or reply.forum_topic_created is not None or is_forward(message):
        return None
    quoted = message.quote.text if message.quote else (reply.text or reply.caption)
    if not quoted:
        return None
    who = "твой ответ" if reply.from_user and reply.from_user.id == bot_id else "сообщение"
    return f"[в ответ на {who}: «{quoted[:QUOTE_LIMIT]}»]"


def _image_block(path: str) -> dict | None:
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if len(data) > 5 * MB:
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(data).decode()}}


def _human_size(n: int | None) -> str:
    if not n:
        return "?"
    return f"{n} B" if n < 1024 else (f"{n // 1024} KB" if n < MB else f"{n / MB:.1f} MB")


class Ingest:
    def __init__(self, app):
        self.app = app

    # ---------------------------------------------------------------- items

    async def build_item(self, topic: dict, m: Message, user_settings: dict, flags: list[str]) -> Item:
        kind = classify(m, user_settings)
        forward = is_forward(m) and not {**{"forward_as_prompt": False}, **user_settings}.get("forward_as_prompt")
        item = Item(kind=kind, group=GROUP_TEXT, message_id=m.message_id)
        lines: list[str] = []
        if "edited" in flags:
            lines.append("[правка предыдущего сообщения]")
        if forward:
            item.group, item.staging_kind = GROUP_FORWARD, "forward"
            who = forward_attribution(m)
            lines.append(f"[переслано от {who}]" if who else "[переслано]")
        body = m.text or m.caption or ""

        if m.photo:
            largest = m.photo[-1]
            if largest.file_size and largest.file_size > settings.FILE_MAX_MB * MB:
                await self._warn(topic, m, texts.FILE_TOO_BIG.format(limit=settings.FILE_MAX_MB))
            else:
                path = await self.app.inbox.download(topic["id"], largest.file_id, f"photo_{m.message_id}.jpg", "photo")
                item.images.append(str(path))
                lines.append(f"[фото сохранено: {path}]")
        if m.document:
            doc = m.document
            if doc.file_size and doc.file_size > settings.FILE_MAX_MB * MB:
                await self._warn(topic, m, texts.FILE_TOO_BIG.format(limit=settings.FILE_MAX_MB))
            else:
                path = await self.app.inbox.download(topic["id"], doc.file_id, doc.file_name or f"document_{m.message_id}", "document")
                lines.append(f"[файл {path.name}: {path}] ({_human_size(doc.file_size)})")
                if not forward:
                    item.group, item.staging_kind = GROUP_FILE, "document"
        if is_voice(m):
            media = m.voice or m.audio or m.video_note
            ext = "ogg" if m.voice else ("mp4" if m.video_note else "audio")
            name = getattr(media, "file_name", None) or f"voice_{m.message_id}.{ext}"
            if media.file_size and media.file_size > settings.VOICE_MAX_MB * MB:
                await self._warn(topic, m, texts.VOICE_TOO_BIG.format(limit=settings.VOICE_MAX_MB))
            else:
                path = await self.app.inbox.download(topic["id"], media.file_id, name, "voice")
                text = await transcribe(path)
                if text:
                    lines.append(text)
                    await self.app.sender.send_markdown(topic["chat_id"], topic["thread_id"], f"🎤 _{text[:300]}_",
                                                        reply_to_message_id=m.message_id, topic_id=topic["id"], role="echo")
                else:
                    lines.append(f"[голосовое: {path}]")
                if not forward:
                    item.group, item.staging_kind = GROUP_TRANSCRIPT, "voice"
        if body:
            lines.append(body)
        item.text = "\n".join(lines)
        return item

    async def _warn(self, topic: dict, m: Message, text: str) -> None:
        await self.app.sender.send_text(topic["chat_id"], topic["thread_id"], text, reply_to_message_id=m.message_id,
                                        topic_id=topic["id"])

    # ---------------------------------------------------------------- batch

    async def process_batch(self, topic: dict, messages: list[Message], flags: list[str]) -> None:
        store = self.app.store
        anchor = messages[0]
        user_settings = await store.users.settings(anchor.from_user.id) if anchor.from_user else {}
        items = [await self.build_item(topic, m, user_settings, flags) for m in messages]
        items = [i for i in items if i.kind != SKIP and (i.text or i.images)]
        if not items:
            return
        for m in messages:
            await store.links.link(m.chat.id, m.message_id, topic["id"], "user")
        if not any(i.kind == PROMPT for i in items):
            for i in items:
                await store.staging.add(topic["id"], i.staging_kind, i.group, {"text": i.text, "images": i.images},
                                        i.message_id)
            if settings.REACTIONS and user_settings.get("reactions", True):
                for i in items:
                    await self.app.sender.react(topic["chat_id"], i.message_id, "👀", topic_id=topic["id"])
            return
        if "edited" in flags:
            await self.app.sender.send_text(topic["chat_id"], topic["thread_id"], texts.EDIT_SEEN, topic_id=topic["id"])
        content = await self.assemble(topic, anchor, items)
        await actions.submit_turn(self.app, topic, TurnRequest(content=content))

    async def assemble(self, topic: dict, anchor: Message, items: list[Item]) -> list[dict]:
        """Content blocks: reply quote → staged items (by group) → batch items (by message_id)."""
        parts: list[Item] = []
        for row in await self.app.store.staging.take_all(topic["id"]):
            parts.append(Item(kind=STAGING, group=row["order_group"], text=row["payload"].get("text", ""),
                              images=row["payload"].get("images", [])))
        # forwards → files → transcripts → texts, then by message id: context lands before the question
        # even when Telegram delivers a forward's comment first
        parts.extend(sorted(items, key=lambda i: (i.group, i.message_id or 0)))
        blocks: list[dict] = []
        text_acc: list[str] = []
        quote = reply_quote(anchor, self.app.bot.id)
        if quote:
            text_acc.append(quote)

        def flush_text():
            if text_acc:
                blocks.append({"type": "text", "text": "\n\n".join(text_acc)})
                text_acc.clear()

        for p in parts:
            if p.text:
                text_acc.append(p.text)
            for path in p.images:
                block = _image_block(path)
                if block:
                    flush_text()
                    blocks.append(block)
        flush_text()
        return blocks
