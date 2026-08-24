"""Incremental meeting summary (section 18).

The summary is refreshed by asking the LLM to merge new stable transcript
text into the existing MeetingSummary, then classify content into facts,
proposals, assumptions, confirmed_decisions, risks, open_questions, and
action_items. This module only decides *when* to refresh and *how to
bound* the text sent to the model; the actual LLM call is injected so
this class can be unit-tested without Ollama.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from meeting_copilot.models import MeetingSummary

SummaryRefreshFn = Callable[[MeetingSummary, str], Awaitable[MeetingSummary]]


class SummaryManager:
    def __init__(
        self,
        interval_seconds: int = 180,
        min_new_characters: int = 1500,
        max_summary_characters: int = 2500,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.min_new_characters = min_new_characters
        self.max_summary_characters = max_summary_characters
        self._summary = MeetingSummary()
        self._last_refresh_at: datetime | None = None
        self._pending_text = ""

    @property
    def summary(self) -> MeetingSummary:
        return self._summary

    def add_stable_text(self, text: str) -> None:
        if text:
            self._pending_text = f"{self._pending_text} {text}".strip()

    def should_refresh(self, now: datetime | None = None) -> bool:
        now = now or datetime.now().astimezone()
        if not self._pending_text:
            return False
        if len(self._pending_text) >= self.min_new_characters:
            return True
        if self._last_refresh_at is None:
            return True
        return now - self._last_refresh_at >= timedelta(seconds=self.interval_seconds)

    async def refresh(self, refresh_fn: SummaryRefreshFn, now: datetime | None = None) -> MeetingSummary:
        """Ask the LLM (via refresh_fn) to merge pending text into the summary."""
        if not self._pending_text:
            return self._summary
        self._summary = await refresh_fn(self._summary, self._pending_text)
        self._pending_text = ""
        self._last_refresh_at = now or datetime.now().astimezone()
        return self._summary

    def as_bounded_text(self) -> str:
        """A compact text rendering of the summary, capped for prompt budget."""
        parts: list[str] = []
        if self._summary.topic:
            parts.append(f"Topic: {self._summary.topic}")
        for label, items in (
            ("Facts", self._summary.facts),
            ("Proposals", self._summary.proposals),
            ("Assumptions", self._summary.assumptions),
            ("Confirmed decisions", self._summary.confirmed_decisions),
            ("Risks", self._summary.risks),
            ("Open questions", self._summary.open_questions),
            ("Action items", self._summary.action_items),
        ):
            if items:
                parts.append(f"{label}: " + "; ".join(items))
        text = "\n".join(parts)
        return text[: self.max_summary_characters]
