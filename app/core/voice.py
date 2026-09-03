"""Voice answers: prose of the turn → external TTS command → OGG/Opus file (PROJECT_SPEC 4.8)."""
from __future__ import annotations

import asyncio
import logging
import shlex
from pathlib import Path

import settings
from app.bridge.cli import child_env
from app.render.tts import speakable

log = logging.getLogger(__name__)


async def synthesize(text: str, out_path: Path) -> Path | None:
    """Run TTS_CMD ({text_file}, {wav}, {out}) with the same secret-free environment as claude.
    Returns the produced file or None (logged) — a failed voice must never break the turn."""
    cmd = settings.TTS_CMD
    if not cmd or not text.strip():
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text_file = out_path.with_suffix(".txt")
    wav = out_path.with_suffix(".wav")
    text_file.write_text(text)
    command = cmd.format(text_file=shlex.quote(str(text_file)), wav=shlex.quote(str(wav)), out=shlex.quote(str(out_path)))
    try:
        proc = await asyncio.create_subprocess_shell(command, stdout=asyncio.subprocess.DEVNULL,
                                                     stderr=asyncio.subprocess.PIPE, env=child_env())
        _, err = await asyncio.wait_for(proc.communicate(), timeout=settings.TTS_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("tts timed out after %ss", settings.TTS_TIMEOUT)
        return None
    except OSError as e:
        log.warning("tts failed to start: %r", e)
        return None
    finally:
        for p in (text_file, wav):
            try:
                p.unlink()
            except OSError:
                pass
    if proc.returncode != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        log.warning("tts failed (code %s): %s", proc.returncode, (err or b"")[-500:].decode(errors="replace"))
        return None
    return out_path


async def voice_for_turn(segments: list[str], turn_id: int) -> Path | None:
    prose = speakable("\n\n".join(segments), settings.TTS_MAX_CHARS)
    if not prose:
        return None
    return await synthesize(prose, Path(settings.INBOX_DIR) / "out" / f"voice-{turn_id}.ogg")
