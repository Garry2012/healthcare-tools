"""Doctors, departments and the multilingual lexicon (tag `Directory`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from .. import schemas as s
from ..auth import require_scopes
from ..services import directory as svc
from .deps import Session, SettingsDep, errors, respond

router = APIRouter(tags=["Directory"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/departments", operation_id="listDepartments", summary="Departments with localized names",
            response_model=s.DepartmentList, responses=errors(401),
            dependencies=[Depends(require_scopes())])
async def list_departments(session: Session):
    body, etag = await svc.list_departments(session)
    return respond(body, 200, {"ETag": etag})


@router.get("/doctors", operation_id="listDoctors",
            summary="Doctor directory (staff and web; the agent uses availability-search)",
            response_model=s.DoctorPage, responses=errors(401),
            dependencies=[Depends(require_scopes())])
async def list_doctors(
    session: Session,
    department: str | None = None,
    active: bool = True,
    limit: Limit = 25,
    offset: Offset = 0,
):
    return respond(await svc.list_doctors(session, department=department, active=active,
                                          limit=limit, offset=offset))


@router.post("/doctors", operation_id="createDoctor", summary="Add a doctor (admin)", status_code=201,
             response_model=s.Doctor, responses=errors(400, 403),
             dependencies=[Depends(require_scopes("directory.write"))])
async def create_doctor(body: s.DoctorInput, session: Session, settings: SettingsDep):
    return respond(await svc.create_doctor(session, body, settings.tenant_currency), 201)


@router.get("/doctors/{doctorId}", operation_id="getDoctor", summary="One doctor with schedule template summary",
            response_model=s.Doctor, responses=errors(404),
            dependencies=[Depends(require_scopes())])
async def get_doctor(doctorId: str, session: Session):  # noqa: N803
    return respond(await svc.get_doctor(session, doctorId))


@router.put("/doctors/{doctorId}", operation_id="updateDoctor",
            summary="Update a doctor (admin). Sets dataConfirmed when the hospital signs off.",
            response_model=s.Doctor, responses=errors(400, 403, 404),
            dependencies=[Depends(require_scopes("directory.write"))])
async def update_doctor(doctorId: str, body: s.DoctorInput, session: Session, settings: SettingsDep):  # noqa: N803
    return respond(await svc.update_doctor(session, doctorId, body, settings.tenant_currency))


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
