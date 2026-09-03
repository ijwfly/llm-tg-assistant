"""Speech to text through an external shell command (settings.TRANSCRIBE_CMD)."""
from __future__ import annotations

import asyncio
import logging
import shlex
from pathlib import Path

import settings

log = logging.getLogger(__name__)


async def transcribe(path: Path) -> str | None:
    """Returns the recognized text, or None when no command is configured or it failed."""
    cmd = settings.TRANSCRIBE_CMD
    if not cmd:
        return None
    wav = path.with_suffix(".wav")
    command = cmd.replace("{file}", shlex.quote(str(path))).replace("{wav}", shlex.quote(str(wav)))
    try:
        proc = await asyncio.create_subprocess_shell(command, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=settings.TRANSCRIBE_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("transcribe: timeout after %ss", settings.TRANSCRIBE_TIMEOUT)
        return None
    except OSError as e:
        log.warning("transcribe: cannot run command: %s", e)
        return None
    finally:
        try:
            wav.unlink(missing_ok=True)
        except OSError:
            pass
    if proc.returncode != 0:
        log.warning("transcribe: exit %s: %s", proc.returncode, err.decode(errors="replace")[:300])
        return None
    text = out.decode(errors="replace").strip()
    return text or None
