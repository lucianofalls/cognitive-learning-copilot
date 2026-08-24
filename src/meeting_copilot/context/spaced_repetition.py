"""SM-2 spaced-repetition scheduler + local-only learning-item store.

Minimal SM-2 (the algorithm behind Anki), simplified to a binary recall
signal ("Lembrei" / "Não lembrei") instead of the original 0-5 quality
scale, since that is all the review UI asks the user for.

Deliberately reuses the *same* `privacy.persist_learning_notes` gate
that already governs `persistence/session_log.py`, rather than a new
dedicated flag. `LearningItem.context_sentence` holds the real English
sentence a chunk was heard in -- exactly the kind of raw English-
transcript content this project never persists by default (see
README.md's Privacy section), so `LearningItemStore` must only ever be
constructed when that flag is true (see app_state.py). This module has
no opinion of its own
on the flag -- same division of responsibility as `SessionLogWriter`.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class LearningItem(BaseModel):
    id: str
    kind: Literal["chunk", "grammar_point", "pronunciation"] = "chunk"
    content_en: str
    context_sentence: str = Field(default="", max_length=500)
    added_at: datetime
    ease_factor: float = 2.5
    interval_days: int = 1
    next_review_at: datetime
    review_count: int = 0


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _interleave_by_kind(items: list[LearningItem]) -> list[LearningItem]:
    """Round-robin across `kind` so the review queue doesn't run through
    one kind in a block before switching to the next.

    Interleaving Practice (LANGUAGE_COACH_PEDAGOGY.md theory #12): mixing
    practice types measurably improves discrimination and retention versus
    blocked practice (all of one kind, then all of another), even though
    blocked practice usually *feels* easier in the moment. Stable within
    each kind -- items of the same kind keep their original (due-order)
    relative order, only the interleaving across kinds is new.
    """
    buckets: dict[str, list[LearningItem]] = {}
    kind_order: list[str] = []
    for item in items:
        if item.kind not in buckets:
            buckets[item.kind] = []
            kind_order.append(item.kind)
        buckets[item.kind].append(item)

    interleaved: list[LearningItem] = []
    while any(buckets[kind] for kind in kind_order):
        for kind in kind_order:
            if buckets[kind]:
                interleaved.append(buckets[kind].pop(0))
    return interleaved


def sm2_reschedule(item: LearningItem, recalled: bool) -> LearningItem:
    """Return a copy of `item` rescheduled per SM-2, given a recall outcome.

    Standard SM-2 interval progression on success (1 day -> 6 days ->
    interval * ease_factor), reset to 1 day and ease_factor nudged down
    on failure -- never below 1.3, SM-2's own floor, so a few misses in
    a row can't make the interval collapse to zero or the ease factor
    spiral to something nonsensical.
    """
    if recalled:
        if item.review_count == 0:
            interval_days = 1
        elif item.review_count == 1:
            interval_days = 6
        else:
            interval_days = max(1, round(item.interval_days * item.ease_factor))
        ease_factor = max(1.3, item.ease_factor + 0.1)
        review_count = item.review_count + 1
    else:
        interval_days = 1
        ease_factor = max(1.3, item.ease_factor - 0.2)
        review_count = 0

    return item.model_copy(
        update={
            "ease_factor": ease_factor,
            "interval_days": interval_days,
            "next_review_at": _now() + timedelta(days=interval_days),
            "review_count": review_count,
        }
    )


class LearningItemStore:
    """Local-only JSON file under data/learning_items/items.json.

    One flat file, read-modify-write on every call -- this is a
    single-user local app with a handful of items at a time (see
    `docs/DECISIONS.md`'s precedent against introducing a database for
    this project), so there is no concurrency or scale concern that
    would justify anything heavier.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._path = directory / "items.json"

    def _load(self) -> list[LearningItem]:
        if not self._path.exists():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return [LearningItem.model_validate(entry) for entry in raw]

    def _save(self, items: list[LearningItem]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps([item.model_dump(mode="json") for item in items], ensure_ascii=False, indent=2)
        self._path.write_text(payload, encoding="utf-8")

    def add(self, content_en: str, context_sentence: str = "", kind: str = "chunk") -> LearningItem:
        items = self._load()
        now = _now()
        item = LearningItem(
            id=uuid.uuid4().hex[:12],
            kind=kind,
            content_en=content_en,
            context_sentence=context_sentence,
            added_at=now,
            next_review_at=now,
        )
        items.append(item)
        self._save(items)
        return item

    def due(self) -> list[LearningItem]:
        now = _now()
        due_items = [item for item in self._load() if item.next_review_at <= now]
        return _interleave_by_kind(due_items)

    def record_result(self, item_id: str, recalled: bool) -> LearningItem | None:
        items = self._load()
        for index, item in enumerate(items):
            if item.id == item_id:
                updated = sm2_reschedule(item, recalled)
                items[index] = updated
                self._save(items)
                return updated
        return None
