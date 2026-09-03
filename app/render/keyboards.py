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


def cancel_kb(topic_id: int, label: str = "Прервать") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(label, cb("cancel", topic_id))]])


def retry_kb(topic_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("Повторить", cb("retry", topic_id))]])


def denied_kb(topic_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn("Разрешать правки", cb("perm", topic_id, "acceptEdits")),
        _btn("Повторить", cb("retry", topic_id)),
    ]])


def continue_kb(topic_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("Продолжить", cb("continue", topic_id))]])


def topic_card_kb(topic_id: int, *, running: bool) -> InlineKeyboardMarkup:
    rows = []
    if running:
        rows.append([_btn("Прервать", cb("cancel", topic_id))])
    rows.append([_btn("Новый контекст", cb("new", topic_id)), _btn("Стоп процесса", cb("stop", topic_id))])
    rows.append([_btn("Сессии", cb("sessions", topic_id)), _btn("Ветка", cb("branch", topic_id))])
    rows.append([_btn("Обновить", cb("refresh", topic_id)), _btn("Скрыть", cb("hide", topic_id)),
                 _btn("Удалить тему", cb("del", topic_id))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_kb(topic_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("Да, удалить тему", cb("delc", topic_id)),
                                                  _btn("Отмена", cb("refresh", topic_id))]])


def sessions_kb(topic_id: int, entries: list[tuple[str, bool]]) -> InlineKeyboardMarkup:
    """entries: (session id, same folder as the topic). Same folder → continue here; else a new topic."""
    rows = []
    for sid, same_folder in entries:
        if same_folder:
            rows.append([_btn(f"Продолжить здесь {sid[:8]}", cb("rs", topic_id, sid[:8]))])
        else:
            rows.append([_btn(f"Новая тема {sid[:8]}", cb("ns", topic_id, sid[:8]))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------- prompts (phase 5)

def permission_kb(topic_id: int, prompt_id: int, always_label: str | None) -> InlineKeyboardMarkup:
    pid = str(prompt_id)
    rows = [[_btn("Разрешить", cb("pa", topic_id, pid)), _btn("Отклонить", cb("pd", topic_id, pid))]]
    if always_label:
        rows.append([_btn(f"Всегда: {always_label}"[:64], cb("pw", topic_id, pid))])
    rows.append([_btn("Отклонить и объяснить", cb("pc", topic_id, pid))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def question_kb(topic_id: int, prompt_id: int, labels: list[str], *, multi: bool,
                selected: set[int] = frozenset()) -> InlineKeyboardMarkup:
    pid = str(prompt_id)
    rows = []
    for i, label in enumerate(labels):
        mark = ("☑ " if i in selected else "☐ ") if multi else ""
        rows.append([_btn((mark + label)[:64], cb("qo", topic_id, f"{pid}:{i}"))])
    if multi:
        rows.append([_btn("Готово", cb("qd", topic_id, pid))])
    rows.append([_btn("Свой ответ", cb("qc", topic_id, pid))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plan_kb(topic_id: int, prompt_id: int) -> InlineKeyboardMarkup:
    pid = str(prompt_id)
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("Выполнять, правки без вопросов", cb("pl", topic_id, f"{pid}:accept"))],
        [_btn("Выполнять, спрашивать про правки", cb("pl", topic_id, f"{pid}:ask"))],
        [_btn("Доработать план", cb("pl", topic_id, f"{pid}:rework"))],
    ])
