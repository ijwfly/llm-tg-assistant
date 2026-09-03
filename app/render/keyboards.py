"""Inline keyboards. callback_data = "<action>:<topic_id>[:<arg>]" (<= 64 bytes)."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def cb(action: str, topic_id: int, arg: str | None = None) -> str:
    data = f"{action}:{topic_id}" + (f":{arg}" if arg else "")
    assert len(data.encode()) <= 64, data
    return data


def parse_cb(data: str) -> tuple[str, int, str | None] | None:
    parts = data.split(":", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    return parts[0], int(parts[1]), (parts[2] if len(parts) > 2 else None)


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def cancel_kb(topic_id: int, label: str = "🛑 Прервать") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(label, cb("cancel", topic_id))]])


def retry_kb(topic_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("🔁 Повторить", cb("retry", topic_id))]])


def denied_kb(topic_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn("🔓 Разрешать правки", cb("perm", topic_id, "acceptEdits")),
        _btn("🔁 Повторить", cb("retry", topic_id)),
    ]])


def continue_kb(topic_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("▶️ Продолжить", cb("continue", topic_id))]])


def topic_card_kb(topic_id: int, *, running: bool) -> InlineKeyboardMarkup:
    rows = []
    if running:
        rows.append([_btn("🛑 Прервать", cb("cancel", topic_id))])
    rows.append([_btn("🆕 Новый контекст", cb("new", topic_id)), _btn("⏸ Стоп процесса", cb("stop", topic_id))])
    rows.append([_btn("🔄 Обновить", cb("refresh", topic_id)), _btn("✖ Скрыть", cb("hide", topic_id))])
    return InlineKeyboardMarkup(inline_keyboard=rows)
