"""Catalogue import (Offerings → Import): CSV / XLSX into reviewed drafts.

read  → the sheet's columns, rows and a suggested column mapping; a PDF, photo
        or pasted menu is read by the AI document reader into the same table
check → each mapped row: ready / duplicate / error, with the reason
import → drafts through the catalogue's own create/update (never live)
review → the batch's items; make chosen drafts live

Needs `offerings.create` (and the catalogue switched on) to import, and
`offerings.update` to make items live. Opening stock is set only for people who
may adjust stock, and only while Inventory is on.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.db import get_db_session
from platform_api.dependencies import BusinessActorContext, require_business_actor
from platform_core.exceptions import ValidationError
from platform_core.permissions import INVENTORY_ADJUST, OFFERINGS_CREATE, OFFERINGS_READ, OFFERINGS_UPDATE
from platform_core.services.catalogue_import import CatalogueImportService

router = APIRouter(prefix="/v1/platform/businesses", tags=["catalogue-import"])
MODULE = "offerings-catalog"
_MAX_ROWS = 2000


def _meta(actor: BusinessActorContext) -> dict[str, Any]:
    return {"correlation_id": actor.request.correlation_id}


def _rows(rows: list[dict[str, str | None]]) -> list[dict[str, str]]:
    return [{k: (v or "") for k, v in r.items()} for r in rows]


class ReadBody(BaseModel):
    """A file (sheet, PDF or photo) — or a menu pasted as text."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(default="Pasted menu", min_length=1, max_length=200)
    content_base64: str | None = Field(default=None, min_length=1, max_length=10_700_000)
    text: str | None = Field(default=None, min_length=1, max_length=20_000)


class CheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[dict[str, str | None]] = Field(max_length=_MAX_ROWS)
    default_kind: str | None = Field(default=None, max_length=40)


class CommitBody(CheckBody):
    filename: str = Field(min_length=1, max_length=200)
    file_hash: str = Field(min_length=1, max_length=64)
    source: str = Field(pattern="^(csv|xlsx|document)$")
    decisions: dict[str, str] = Field(default_factory=dict)


class MakeLiveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offering_ids: list[UUID] = Field(min_length=1, max_length=_MAX_ROWS)


@router.post("/{business_id}/catalogue-import/read")
async def read_sheet(
    business_id: UUID,
    body: ReadBody,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_CREATE, MODULE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if body.text is not None:
        data = await CatalogueImportService.read_document(session, business_id, data=body.text.encode("utf-8"),
                                                          mime_type="text/plain")
    elif body.content_base64 is not None:
        data = await CatalogueImportService.read(session, business_id, filename=body.filename,
                                                 content_base64=body.content_base64)
    else:
        raise ValidationError("Choose a file or paste your menu", details={"field": "file"})
    return {"data": data, "meta": _meta(actor)}


@router.post("/{business_id}/catalogue-import/check")
async def check_rows(
    business_id: UUID,
    body: CheckBody,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_CREATE, MODULE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    data = await CatalogueImportService.check(
        session, business_id, rows=_rows(body.rows), default_kind=body.default_kind,
        may_adjust_stock=INVENTORY_ADJUST in actor.request.effective_permissions)
    return {"data": data, "meta": _meta(actor)}


@router.post("/{business_id}/catalogue-import")
async def import_rows(
    business_id: UUID,
    body: CommitBody,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_CREATE, MODULE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    decisions = {int(k): v for k, v in body.decisions.items() if k.isdigit()}
    data = await CatalogueImportService.commit(
        session, business_id, actor_id=actor.request.identity_id, correlation_id=actor.request.correlation_id,
        filename=body.filename, file_hash=body.file_hash, source=body.source, rows=_rows(body.rows),
        decisions=decisions, default_kind=body.default_kind,
        may_adjust_stock=INVENTORY_ADJUST in actor.request.effective_permissions)
    await session.commit()
    return {"data": data, "meta": _meta(actor)}


@router.get("/{business_id}/catalogue-import")
async def recent_imports(
    business_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_READ, MODULE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return {"data": await CatalogueImportService.recent(session, business_id), "meta": _meta(actor)}


@router.get("/{business_id}/catalogue-import/{import_id}")
async def get_import(
    business_id: UUID,
    import_id: UUID,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_READ, MODULE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return {"data": await CatalogueImportService.get(session, business_id, import_id), "meta": _meta(actor)}


@router.post("/{business_id}/catalogue-import/{import_id}/make-live")
async def make_live(
    business_id: UUID,
    import_id: UUID,
    body: MakeLiveBody,
    actor: BusinessActorContext = Depends(require_business_actor(OFFERINGS_UPDATE, MODULE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    data = await CatalogueImportService.make_live(
        session, business_id, import_id, offering_ids=body.offering_ids, actor_id=actor.request.identity_id,
        correlation_id=actor.request.correlation_id)
    await session.commit()
    return {"data": data, "meta": _meta(actor)}
