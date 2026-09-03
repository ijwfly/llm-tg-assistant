"""Per-topic and per-user switches with defaults from settings (PROJECT_SPEC 4.9)."""
from __future__ import annotations

import settings

# topic flags live in topics.settings; the default is read at call time so tests can override settings
TOPIC_FLAGS = {
    "stream_preview": lambda: settings.STREAM_PREVIEW,
    "thinking_preview": lambda: settings.THINKING_PREVIEW,
    "show_turn_stats": lambda: settings.SHOW_TURN_STATS,
    "voice": lambda: False,
    "verbose_tools": lambda: settings.VERBOSE_TOOL_OUTPUT,
}
# user flags live in users.settings
USER_FLAGS = {
    "voice_as_prompt": lambda: True,
    "forward_as_prompt": lambda: False,
    "reactions": lambda: settings.REACTIONS,
}
FLAG_LABELS = {
    "stream_preview": "Превью ответа", "thinking_preview": "Размышления", "show_turn_stats": "Статистика хода",
    "voice": "Голосом", "voice_as_prompt": "Голос = вопрос", "forward_as_prompt": "Форвард = вопрос",
    "reactions": "Реакции", "verbose_tools": "Вывод инструментов",
}
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
DEFAULT = "default"


def topic_flag(topic: dict, key: str) -> bool:
    value = (topic.get("settings") or {}).get(key)
    return bool(TOPIC_FLAGS[key]()) if value is None else bool(value)


def user_flag(user_settings: dict, key: str) -> bool:
    value = (user_settings or {}).get(key)
    return bool(USER_FLAGS[key]()) if value is None else bool(value)


def perm_cycle() -> list[str]:
    modes = ["prompt", "acceptEdits", "plan", "auto", "dontAsk"]
    return modes + (["bypass"] if settings.ALLOW_BYPASS else [])


def model_cycle() -> list[str]:
    return [DEFAULT] + [m for m in settings.MODEL_CHOICES if m != DEFAULT]


def effort_cycle() -> list[str]:
    return [DEFAULT] + EFFORTS


def next_in(cycle: list[str], current: str | None) -> str:
    current = current or DEFAULT
    if current not in cycle:
        return cycle[0]
    return cycle[(cycle.index(current) + 1) % len(cycle)]


def shown(value: str | None) -> str:
    return "по умолчанию" if not value or value == DEFAULT else value
