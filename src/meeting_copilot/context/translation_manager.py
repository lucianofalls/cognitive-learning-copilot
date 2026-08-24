"""Event-driven PT-BR translation of the rolling transcript.

`add_stable_text` accumulates transcript segments as they arrive;
`refresh` translates and clears whatever's pending. The caller decides
when to call `refresh` -- SessionService calls it after every new
transcript segment (see `_maybe_refresh_translation`), not on a timer.
That used to be batched (translate every N seconds or N new characters)
back when translation went through Ollama at 15-25s/call, which made
per-segment calls impractical -- see docs/DECISIONS.md, 2026-07-20
"Translation batching removed". Argos Translate replaced that path and
calls typically finish in well under a second, so nothing is gained by
waiting.

Pause markers: `add_stable_text` accepts an optional gap (seconds since
the previous transcript segment). Gaps at or above the threshold are
inlined as `[pausa: N.Ns]` markers in the pending text, which the
translation prompt is instructed to preserve -- this is the "speech
nuance" signal requested for the coaching/learning notes, without
building a full prosodic analysis pipeline.

The threshold must stay well above `whisper.step_ms` (3000ms by
default): whisper-stream physically cannot emit two transcript lines
less than one step apart, so during continuous, uninterrupted speech
the segment-to-segment gap still floors at ~3s. A threshold at or near
that floor mislabels routine step cadence as a speaker pause on nearly
every line. Confirmed 2026-07-20 against a real session log: with the
threshold at 2.0s, ~40 consecutive lines of continuous narration (no
real pauses) each carried a `[pausa: 3.0s]` marker -- gap_since_last_line
was clustering at 2.6-3.4s the whole time, i.e. step-driven jitter, not
speech. 6.0s (2x the default step) clears that jitter band with margin
while still catching genuine hesitation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

TranslateFn = Callable[[str], Awaitable[str]]

PAUSE_MARKER_THRESHOLD_SECONDS = 6.0


class TranslationManager:
    def __init__(self) -> None:
        self._pending_text = ""

    def add_stable_text(self, text: str, pause_seconds: float | None = None) -> None:
        if not text:
            return
        if pause_seconds is not None and pause_seconds >= PAUSE_MARKER_THRESHOLD_SECONDS:
            text = f"[pausa: {pause_seconds:.1f}s] {text}"
        self._pending_text = f"{self._pending_text} {text}".strip()

    async def refresh(self, translate_fn: TranslateFn) -> str:
        """Ask translate_fn to translate the pending text. Returns "" if nothing pending."""
        if not self._pending_text:
            return ""
        text = self._pending_text
        translated = await translate_fn(text)
        self._pending_text = ""
        return translated
