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


def _onoff(value: bool) -> str:
    return "вкл" if value else "выкл"


def topic_card_kb(topic_id: int, *, running: bool, perm: str, model: str, effort: str,
                  flags: dict[str, bool], labels: dict[str, str], page: str = "main",
                  rules: int = 0, rewind: bool = False) -> InlineKeyboardMarkup:
    """The topic card keyboard. `flags`/`labels`: switch key -> value / caption (PROJECT_SPEC 4.9);
    `rules` = «Всегда» rules added by the bot in this topic (a «Забыть правила» button when > 0)."""
    if page == "more":
        keys = list(flags)
        rows = [[_btn(f"{labels[k]}: {_onoff(flags[k])}", cb("tgl", topic_id, k)) for k in keys[i:i + 2]]
                for i in range(0, len(keys), 2)]
        if rules:
            rows.append([_btn(f"Забыть правила «Всегда» ({rules})", cb("forget", topic_id))])
        if rewind:
            rows.append([_btn("Откатить файлы", cb("rwl", topic_id))])
        rows.append([_btn("Назад", cb("page", topic_id, "main"))])
        return InlineKeyboardMarkup(inline_keyboard=rows)
    rows = []
    if running:
        rows.append([_btn("Прервать", cb("cancel", topic_id))])
    rows.append([_btn("Новый контекст", cb("new", topic_id)), _btn("Стоп процесса", cb("stop", topic_id))])
    rows.append([_btn(f"Права: {perm}", cb("cyc", topic_id, "perm")), _btn(f"Модель: {model}", cb("cyc", topic_id, "model")),
                 _btn(f"Усилие: {effort}", cb("cyc", topic_id, "effort"))])
    rows.append([_btn("Сессии", cb("sessions", topic_id)), _btn("Ветка", cb("branch", topic_id)),
                 _btn("Ещё", cb("page", topic_id, "more"))])
    rows.append([_btn("Обновить", cb("refresh", topic_id)), _btn("Скрыть", cb("hide", topic_id)),
                 _btn("Удалить тему", cb("del", topic_id))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rewind_list_kb(topic_id: int, turns: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """turns: (turn id, prompt label)."""
    rows = [[_btn(f"До: «{label}»"[:64], cb("rw", topic_id, str(tid)))] for tid, label in turns]
    rows.append([_btn("Скрыть", cb("hide", topic_id))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rewind_confirm_kb(topic_id: int, turn_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("Да, откатить", cb("rwc", topic_id, str(turn_id))),
                                                  _btn("Отмена", cb("hide", topic_id))]])


def hide_kb(topic_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("Скрыть", cb("hide", topic_id))]])


def confirm_delete_kb(topic_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("Да, удалить тему", cb("delc", topic_id)),
                                                  _btn("Отмена", cb("refresh", topic_id))]])


BUTTON_LABEL_LIMIT = 48   # what fits on a phone; the callback carries the id, the label carries the name


def _label(text: str) -> str:
    return text if len(text) <= BUTTON_LABEL_LIMIT else text[:BUTTON_LABEL_LIMIT - 1] + "…"


def sessions_kb(topic_id: int, entries: list[tuple[str, bool, str, str]], page: int = 0, pages: int = 1) -> InlineKeyboardMarkup:
    """entries: (session id, same folder as the topic, folder name, when). The label is the folder name
    only (plus «· when» if the folder repeats on the page); same folder → continue here (`rs`), else a
    new topic (`ns`). Pages: «Назад» / «Дальше» edit the card in place (`sp:<topic>:<page>`)."""
    rows = []
    folders = [e[2] for e in entries]
    for sid, same_folder, folder, when in entries:
        label = folder if folders.count(folder) == 1 else f"{folder} · {when}"
        rows.append([_btn(_label(label), cb("rs" if same_folder else "ns", topic_id, sid[:8]))])
    nav = []
    if page > 0:
        nav.append(_btn("Назад", cb("sp", topic_id, str(page - 1))))
    if page + 1 < pages:
        nav.append(_btn("Дальше", cb("sp", topic_id, str(page + 1))))
    if nav:
        rows.append(nav)
    rows.append([_btn("Скрыть", cb("hide", topic_id))])
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
