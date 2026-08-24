"""Memory approval and feedback endpoints (sections 7.5, 27, 33)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from meeting_copilot.models import FeedbackEntry

router = APIRouter()


class ProposeMemoryRequest(BaseModel):
    text: str


class ApproveMemoryRequest(BaseModel):
    id: str
    text: str


@router.post("/api/memory/propose")
async def propose_memory(request: Request, body: ProposeMemoryRequest) -> dict[str, Any]:
    state = request.app.state.copilot
    item = state.session.memory_manager.propose(body.text)
    return item.model_dump(mode="json")


@router.post("/api/memory/approve")
async def approve_memory(request: Request, body: ApproveMemoryRequest) -> dict[str, Any]:
    from meeting_copilot.models import ApprovedMemoryItem

    state = request.app.state.copilot
    item = ApprovedMemoryItem(id=body.id, text=body.text)
    approved = state.session.memory_manager.approve(item)
    return approved.model_dump(mode="json")


@router.delete("/api/memory/{item_id}")
async def delete_memory(request: Request, item_id: str) -> dict[str, str]:
    state = request.app.state.copilot
    removed = state.session.memory_manager.remove(item_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Memory item not found")
    return {"status": "deleted"}


@router.post("/api/feedback")
async def submit_feedback(request: Request, body: FeedbackEntry) -> dict[str, str]:
    """Stores feedback in memory only (section 33) -- never sentence content."""
    state = request.app.state.copilot
    state.feedback.append(body.model_dump(mode="json"))
    return {"status": "recorded"}
