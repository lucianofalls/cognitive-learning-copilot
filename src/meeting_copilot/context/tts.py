"""Text-to-speech via macOS's `say` -- Language Coach "Ouvir" affordance.

Shells out to the system `say` binary (confirmed present via `man say`;
voice "Daniel" (en_GB) confirmed installed via `say -v '?'`) rather
than adding a new Python dependency -- zero new cost, and this app is
already Mac-only, so it doesn't cost any portability either.

Non-blocking: `asyncio.create_subprocess_exec`, same pattern as
`argos_translate.py`'s CPU-bound work, so this never stalls the event
loop the transcription/translation hot path also runs on.

`--file-format`/`--data-format` are passed explicitly rather than
relying on `say`'s extension-sniffing (the man page's "generally,
it's easier to specify a suitable file extension" claim): a bare
`-o out.wav` reproducibly fails on this machine with "Opening output
file failed: fmt?" (verified directly, not assumed) -- WAVE apparently
needs its PCM sample format spelled out. AIFF works with no explicit
data-format, but WAV has universal `<audio>` support in browsers and
AIFF does not, so WAV plus an explicit linear-PCM format is the
reliable choice here, confirmed with `file` reporting a valid
"WAVE audio ... 16 bit, mono 22050 Hz" container.

This project's "do not persist audio, ever" rule applies to this
synthesized speech exactly as it does to recorded meeting audio: the WAV is written
to a temp file only because `say` has no stdout-streaming mode, read
back into memory, and unlinked in a `finally` block before this
function returns -- nothing survives the call.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path


class SpeechSynthesisError(Exception):
    pass


async def synthesize_speech(text: str, voice: str = "Daniel") -> bytes:
    text = text.strip()
    if not text:
        raise SpeechSynthesisError("Cannot synthesize empty text.")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        try:
            process = await asyncio.create_subprocess_exec(
                "say",
                "-v",
                voice,
                "--file-format=WAVE",
                "--data-format=LEI16@22050",
                "-o",
                str(tmp_path),
                "--",
                text,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise SpeechSynthesisError("The 'say' command is not available on this machine.") from exc

        _, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip() or "say exited with a non-zero status."
            raise SpeechSynthesisError(detail)
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)
