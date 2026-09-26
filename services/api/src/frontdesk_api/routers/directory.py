"""Resources, categories and the multilingual lexicon (tag `Directory`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from .. import schemas as s
from ..auth import require_scopes
from ..services import directory as svc
from .deps import Session, SettingsDep, errors, respond

router = APIRouter(tags=["Directory"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/categories", operation_id="listCategories", summary="Categories with localized names",
            response_model=s.CategoryList, responses=errors(401),
            dependencies=[Depends(require_scopes())])
async def list_categories(session: Session):
    body, etag = await svc.list_categories(session)
    return respond(body, 200, {"ETag": etag})


@router.put("/categories/{categoryId}", operation_id="upsertCategory",
            summary="Create or replace a category (admin, onboarding)", response_model=s.Category,
            responses=errors(400, 401, 403), dependencies=[Depends(require_scopes("directory.write"))])
async def upsert_category(
    categoryId: Annotated[str, Path(pattern=r"^[a-z0-9_]+$", max_length=50)],  # noqa: N803
    body: s.CategoryInput,
    session: Session,
):
    return respond(await svc.upsert_category(session, categoryId, body))


@router.get("/resources", operation_id="listResources",
            summary="Resource directory (staff and web; the agent uses availability-search)",
            response_model=s.ResourcePage, responses=errors(401),
            dependencies=[Depends(require_scopes())])
async def list_resources(
    session: Session,
    category: str | None = None,
    active: bool = True,
    limit: Limit = 25,
    offset: Offset = 0,
):
    return respond(await svc.list_resources(session, category=category, active=active,
                                          limit=limit, offset=offset))


@router.post("/resources", operation_id="createResource", summary="Add a resource (admin)", status_code=201,
             response_model=s.Resource, responses=errors(400, 403),
             dependencies=[Depends(require_scopes("directory.write"))])
async def create_resource(body: s.ResourceInput, session: Session, settings: SettingsDep):
    return respond(await svc.create_resource(session, body, settings.tenant_currency), 201)


@router.get("/resources/{resourceId}", operation_id="getResource",
            summary="One resource with schedule template summary",
            response_model=s.Resource, responses=errors(404),
            dependencies=[Depends(require_scopes())])
async def get_resource(resourceId: str, session: Session):  # noqa: N803
    return respond(await svc.get_resource(session, resourceId))


@router.put("/resources/{resourceId}", operation_id="updateResource",
            summary="Update a resource (admin). Sets dataConfirmed when the provider signs off.",
            response_model=s.Resource, responses=errors(400, 403, 404),
            dependencies=[Depends(require_scopes("directory.write"))])
async def update_resource(resourceId: str, body: s.ResourceInput, session: Session, settings: SettingsDep):  # noqa: N803
    return respond(await svc.update_resource(session, settings, resourceId, body, "staff"))


@router.get("/lexicon", operation_id="listLexicon", summary="Multilingual terms the resolver uses",
            response_model=s.LexiconList, responses=errors(403),
            dependencies=[Depends(require_scopes("directory.write"))])
async def list_lexicon(
    session: Session,
    concept_type: Annotated[s.LexiconConceptType | None, Query(alias="conceptType")] = None,
    language: str | None = None,
    approved: bool | None = None,
):
    return respond(await svc.list_lexicon(
        session, concept_type=concept_type.value if concept_type else None,
        language=language, approved=approved,
    ))


@router.post("/lexicon", operation_id="addLexiconEntry", summary="Add or approve a term", status_code=201,
             response_model=s.LexiconEntry, responses=errors(400, 403),
             dependencies=[Depends(require_scopes("directory.write"))])
async def add_lexicon_entry(body: s.LexiconEntryInput, session: Session, settings: SettingsDep):
    return respond(await svc.upsert_lexicon(session, body, settings.transfer_destinations), 201)
