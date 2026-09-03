"""Domain-level view of what the user saw, on top of the recording session."""
from __future__ import annotations

from tests.support.session import RecordingSession

TEXT_METHODS = {"SendMessage", "SendRichMessage", "EditMessageText", "SendDocument", "SendPhoto"}


class TelegramSpy:
    def __init__(self, session: RecordingSession):
        self.session = session

    def calls(self, method_name: str | None = None) -> list[dict]:
        return [p for n, p in self.session.calls if method_name is None or n == method_name]

    @staticmethod
    def _text_of(payload: dict) -> str | None:
        if payload.get("text"):
            return payload["text"]
        if payload.get("caption"):
            return payload["caption"]
        rich = payload.get("rich_message") or {}
        return rich.get("markdown") or rich.get("html")

    def sent_texts(self, chat_id: int | None = None) -> list[str]:
        out = []
        for name, payload in self.session.calls:
            if name in TEXT_METHODS and (chat_id is None or payload.get("chat_id") == chat_id):
                text = self._text_of(payload)
                if text:
                    out.append(text)
        return out

    def last_text(self) -> str | None:
        texts = self.sent_texts()
        return texts[-1] if texts else None

    def assert_shown_text_contains(self, fragment: str) -> None:
        assert any(fragment in t for t in self.sent_texts()), \
            f"{fragment!r} not shown; shown: {self.sent_texts()!r}"

    def assert_nothing_sent(self) -> None:
        assert self.session.calls == [], f"unexpected calls: {self.session.calls!r}"
