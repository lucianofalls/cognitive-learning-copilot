"""One-shot Portuguese speech recognition -- the "Falar em português" button.

A reverse-direction feature: speak in Portuguese, see it in English.
The continuous `whisper-stream` process only ever loads
`ggml-small.en.bin` (English-only) -- it can't transcribe Portuguese at
all, and the hard constraint that the main pipeline's transcription/
translation speed must never regress, plus this project's own
established pattern (see context/pronunciation.py), both rule out
touching it.

So this is a **second, separate, one-shot** `whisper-cli` call, exactly
like pronunciation.py's, using a **different, multilingual** model
(`ggml-small.bin`, `whisper.multilingual_model_path` in config.py) with
`-l pt`. Never the continuous whisper-stream process -- there is no
shared state between this and the live meeting's English transcription,
so one genuinely cannot slow down the other.

Verified directly: synthesized a Portuguese clip via macOS `say` and
confirmed `ggml-small.bin -l pt` transcribes it correctly, accents and
all ("Bom dia pessoal, vamos começar a reunião de hoje.").
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from meeting_copilot.config import WhisperSettings


class PortugueseSpeechError(Exception):
    pass


async def transcribe_portuguese(audio_bytes: bytes, whisper_settings: WhisperSettings) -> str:
    """Run whisper-cli once over a short Portuguese recording (WAV bytes)."""
    whisper_cli = whisper_settings.cli_binary_path_expanded
    if not whisper_cli.exists():
        raise PortugueseSpeechError(f"whisper-cli not found at {whisper_cli}.")
    model_path = whisper_settings.multilingual_model_path_expanded
    if not model_path.exists():
        raise PortugueseSpeechError(
            f"Multilingual whisper model not found at {model_path}. "
            "Run: cd <whisper.cpp repo> && sh ./models/download-ggml-model.sh small"
        )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
        tmp_in.write(audio_bytes)
        input_path = Path(tmp_in.name)

    try:
        process = await asyncio.create_subprocess_exec(
            str(whisper_cli),
            "-m",
            str(model_path),
            "-f",
            str(input_path),
            "-l",
            "pt",
            "-np",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip() or "whisper-cli exited with a non-zero status."
            raise PortugueseSpeechError(detail)

        # No -oj/-otxt here (unlike pronunciation.py) -- this only needs
        # the plain transcript text, not per-word confidence, so reading
        # stdout directly avoids an extra temp output file to clean up.
        # whisper-cli's stdout lines look like:
        #   [00:00:00.000 --> 00:00:03.660]   Bom dia pessoal, ...
        lines = []
        for raw_line in stdout.decode("utf-8", errors="replace").splitlines():
            if "-->" not in raw_line:
                continue
            _, _, text = raw_line.partition("]")
            text = text.strip()
            if text:
                lines.append(text)
        return " ".join(lines)
    finally:
        input_path.unlink(missing_ok=True)
