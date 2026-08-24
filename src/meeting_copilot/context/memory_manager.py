"""Section 7.5 / 27: memory only becomes permanent with explicit approval.

`propose()` never writes anything durable -- it just returns a candidate
for the UI to show the user. Only `approve()` appends to the in-memory
approved list, and only `persist()` (called explicitly, e.g. from a
"Save memory" button) writes it to disk, gated by
`privacy.persist_summary`-style settings the caller must check.
"""

from __future__ import annotations

import json
from pathlib import Path

from meeting_copilot.models import ApprovedMemoryItem

# Categories that must never be auto-approved, per section 7.5.
DISALLOWED_AUTO_APPROVAL_HINTS = (
    "hypothesis",
    "opinion",
    "unvalidated",
    "secret",
    "credential",
    "password",
    "client name",
    "customer name",
    "not yet confirmed",
)


class MemoryManager:
    def __init__(self) -> None:
        self._approved: dict[str, ApprovedMemoryItem] = {}

    def propose(self, text: str) -> ApprovedMemoryItem:
        """Create a candidate memory item. Not stored until approve() is called."""
        return ApprovedMemoryItem(text=text)

    def approve(self, item: ApprovedMemoryItem) -> ApprovedMemoryItem:
        self._approved[item.id] = item
        return item

    def remove(self, item_id: str) -> bool:
        return self._approved.pop(item_id, None) is not None

    def list_approved(self) -> list[ApprovedMemoryItem]:
        return list(self._approved.values())

    def clear(self) -> None:
        self._approved.clear()

    def persist(self, path: Path) -> None:
        """Explicitly write approved memory to disk. Caller must confirm
        the user opted in -- this method performs no privacy checks itself."""
        payload = [item.model_dump(mode="json") for item in self._approved.values()]
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
