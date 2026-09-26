"""Approved answers the agent may speak (tag `Knowledge`, staff)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from .. import schemas as s
from ..auth import require_scopes
from ..services import knowledge as svc
from .deps import ActingUser, Session, SettingsDep, errors, respond

router = APIRouter(tags=["Knowledge"], dependencies=[Depends(require_scopes("knowledge.write"))])


@router.get("/knowledge", operation_id="listKnowledge", summary="Knowledge entries (approved and drafts)",
            response_model=s.KnowledgeList, responses=errors(400, 401, 403))
async def list_knowledge(session: Session, topic: str | None = None, approved: bool | None = None):
    return respond(await svc.list_entries(session, topic=topic, approved=approved))


@router.post("/knowledge", operation_id="createKnowledgeEntry", summary="Add an answer (draft unless approved)",
             status_code=201, response_model=s.KnowledgeEntry, responses=errors(400, 401, 403))
async def create_knowledge(body: s.KnowledgeEntryInput, session: Session, settings: SettingsDep,
                           acting_user: ActingUser):
    return respond(await svc.create(session, settings, body, f"staff:{acting_user}"), 201)


@router.put("/knowledge/{entryId}", operation_id="updateKnowledgeEntry",
            summary="Replace an answer; the agent sees the change on its next question",
            response_model=s.KnowledgeEntry, responses=errors(400, 401, 403, 404))
async def update_knowledge(entryId: str, body: s.KnowledgeEntryInput, session: Session,  # noqa: N803
                           settings: SettingsDep, acting_user: ActingUser):
    return respond(await svc.update(session, settings, entryId, body, f"staff:{acting_user}"))


@router.delete("/knowledge/{entryId}", operation_id="deleteKnowledgeEntry", summary="Remove an answer",
               status_code=204, responses=errors(400, 401, 403, 404))
async def delete_knowledge(entryId: str, session: Session, acting_user: ActingUser):  # noqa: N803
    await svc.delete(session, entryId)
    return Response(status_code=204)
