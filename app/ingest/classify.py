"""Prompt-or-staging decisions, forward attribution, file-name sanitizing (pure functions)."""
from __future__ import annotations

import re

from aiogram.types import Message

USER_DEFAULTS = {"forward_as_prompt": False, "voice_as_prompt": True, "reactions": True}

PROMPT, STAGING, SKIP = "prompt", "staging", "skip"


def is_forward(message: Message) -> bool:
    return bool(message.forward_origin or message.forward_from or message.forward_from_chat
                or message.forward_sender_name)


def is_voice(message: Message) -> bool:
    return bool(message.voice or message.audio or message.video_note)


def classify(message: Message, user_settings: dict) -> str:
    """Matrix from PROJECT_SPEC 4.4.2."""
    s = {**USER_DEFAULTS, **(user_settings or {})}
    if is_forward(message) and not s["forward_as_prompt"]:
        return STAGING
    if is_voice(message):
        return PROMPT if s["voice_as_prompt"] else STAGING
    if message.document:
        return PROMPT if message.caption else STAGING
    if message.text or message.caption or message.photo:
        return PROMPT
    return SKIP


def forward_attribution(message: Message) -> str | None:
    origin = message.forward_origin
    if origin is not None:
        t = origin.type
        if t == "user":
            u = origin.sender_user
            name = " ".join(x for x in (u.first_name, u.last_name) if x)
            return f"{name} (@{u.username})" if u.username else name
        if t == "hidden_user":
            return origin.sender_user_name
        if t in ("chat", "channel"):
            chat = origin.sender_chat if t == "chat" else origin.chat
            return f'Chat name "{chat.title or chat.username or chat.id}"'
    if message.forward_from:
        u = message.forward_from
        name = " ".join(x for x in (u.first_name, u.last_name) if x)
        return f"{name} (@{u.username})" if u.username else name
    if message.forward_from_chat:
        return f'Chat name "{message.forward_from_chat.title}"'
    if message.forward_sender_name:
        return message.forward_sender_name
    return None


_SAFE = re.compile(r"[^\w.\-]", re.UNICODE)


def sanitize_filename(name: str | None, fallback: str = "file") -> str:
    base = _SAFE.sub("_", (name or "").strip()).strip("._") or fallback
    return base[:120]
