from pathlib import Path

from app.ingest.classify import PROMPT, SKIP, STAGING, classify, forward_attribution, sanitize_filename
from app.ingest.files import InboxService
from tests.support.updates import message, user


def test_classification_matrix():
    assert classify(message("hi"), {}) == PROMPT
    assert classify(message(photo_id="p"), {}) == PROMPT
    assert classify(message("fwd", forward_from=user(2)), {}) == STAGING
    assert classify(message("fwd", forward_from=user(2)), {"forward_as_prompt": True}) == PROMPT
    assert classify(message(voice_id="v"), {}) == PROMPT
    assert classify(message(voice_id="v"), {"voice_as_prompt": False}) == STAGING
    assert classify(message(document=("d", "a.txt", 1)), {}) == STAGING
    assert classify(message(document=("d", "a.txt", 1), caption="read it"), {}) == PROMPT
    assert classify(message(document=("d", "a.txt", 1), caption="x", forward_from=user(2)), {}) == STAGING
    assert classify(message(), {}) == SKIP


def test_forward_attribution_variants():
    u = user(3).model_copy(update={"first_name": "Ann", "last_name": None, "username": None})
    assert forward_attribution(message("x", forward_from=u)) == "Ann"
    assert forward_attribution(message("x", forward_from=user(3))) == "Test User (@tester)"
    assert forward_attribution(message("x", forward_channel="News")) == 'Chat name "News"'
    assert forward_attribution(message("x")) is None


def test_sanitize_filename_keeps_cyrillic_and_replaces_the_rest():
    assert sanitize_filename("отчёт (final) v2.pdf") == "отчёт__final__v2.pdf"
    assert sanitize_filename("../../etc/passwd") == "etc_passwd"
    assert sanitize_filename("   ") == "file"
    assert len(sanitize_filename("x" * 300)) == 120


def test_unique_path_adds_numeric_suffix(tmp_path: Path):
    (tmp_path / "a.txt").write_text("1")
    (tmp_path / "a_1.txt").write_text("2")
    assert InboxService.unique_path(tmp_path, "a.txt").name == "a_2.txt"
    assert InboxService.unique_path(tmp_path, "b.txt").name == "b.txt"
    (tmp_path / "noext").write_text("3")
    assert InboxService.unique_path(tmp_path, "noext").name == "noext_1"
