"""Catalogue import — a sheet of items becomes reviewed drafts, never live items.

read (file → columns + suggested mapping) → check (mapped rows → ready /
duplicate / error, per row, with reasons) → import (drafts, through the
catalogue's own create and update) → review the batch → make chosen drafts live.

The catalogue's services do every write, so versions, audit and
`offering.created` / `offering.updated` events behave exactly as when an owner
adds items by hand. Stock is set through Inventory's opening-stock path, and
only when Inventory is on and the person may adjust stock.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections import Counter
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.catalog.offering_kinds import FIRST_LAUNCH_KINDS, KINDS
from platform_core.catalogue_import.reading import (
    MAX_DOCUMENT_BYTES,
    ReadProblem,
    Table,
    document_type,
    file_hash,
    read_table,
)
from platform_core.catalogue_import.rows import (
    FIELD_LABELS,
    FIELDS,
    Existing,
    RowResult,
    norm_name,
    suggest_mapping,
    validate_rows,
)
from platform_core.exceptions import ConflictError, ResourceNotFound, ValidationError
from platform_core.logging import get_logger
from platform_core.models import BusinessLocation, Offering, OfferingCatalogImport

DECISIONS = frozenset({"skip", "update", "create"})
# Kinds an import can create: First Launch kinds (a missing required detail, like
# a service's duration, is reported on the draft rather than refused) and any kind
# with no required detail. Membership plans belong to Memberships, not a sheet.
IMPORT_KINDS = tuple(k.key for k in KINDS.values()
                     if (k.key in FIRST_LAUNCH_KINDS or not any(f.required for f in k.fields))
                     and k.key != "membership_plan")
_BOOKING_FLOW = "booking"
_log = get_logger("catalogue.import")


def _kind_words() -> dict[str, str]:
    words: dict[str, str] = {}
    for key in IMPORT_KINDS:
        k = KINDS[key]
        for w in (key, key.replace("_", " "), k.label, k.plural):
            words.setdefault(norm_name(w), key)
    return words


def _message(exc: ValidationError | ConflictError) -> str:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return str(detail.get("message") or "This row could not be saved")


def bookable_kinds() -> frozenset[str]:
    return frozenset(k for k in IMPORT_KINDS if KINDS[k].flow == _BOOKING_FLOW)


class CatalogueImportService:
    # ------------------------------------------------------------ read

    @staticmethod
    async def read(session: AsyncSession, business_id: uuid.UUID, *, filename: str,
                   content_base64: str, provider: Any = None) -> dict[str, Any]:
        try:
            data = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValidationError("The file did not arrive intact. Try uploading it again.",
                                  details={"field": "file"}) from exc
        mime = document_type(filename, data)
        if mime is not None:
            return await CatalogueImportService.read_document(session, business_id, data=data, mime_type=mime,
                                                              provider=provider)
        try:
            table = read_table(filename, data)
        except ReadProblem as exc:
            raise ValidationError(str(exc), details={"field": "file"}) from exc
        return await CatalogueImportService._read_result(session, business_id, table)

    @staticmethod
    async def read_document(session: AsyncSession, business_id: uuid.UUID, *, data: bytes, mime_type: str,
                            provider: Any = None) -> dict[str, Any]:
        """A PDF, photo or pasted text menu, read by the AI document reader into the
        same table a sheet gives — so it goes through the same mapping, checks,
        drafts and review. Lines the reader was unsure of come back in
        `uncertain_rows`; nothing read this way is ever made live without review."""
        from platform_core.interview import documents
        from platform_core.website.ai_provider import get_ai_provider

        if not data.strip():
            raise ValidationError("There is nothing to read.", details={"field": "file"})
        if len(data) > MAX_DOCUMENT_BYTES:
            raise ValidationError("The file is larger than 8 MB. Use a smaller photo or a page at a time.",
                                  details={"field": "file"})
        provider = provider or get_ai_provider()
        if getattr(provider, "provider_name", "") == "unavailable":
            raise ValidationError("Reading a PDF, photo or pasted menu needs LOCAH's AI reader, which isn't set up "
                                  "here. Upload a .csv or .xlsx sheet instead.", details={"field": "file"})
        try:
            _, groups, _ = await documents.read(data, mime_type, provider=provider)
        except Exception as exc:  # noqa: BLE001 — told to the owner, never raised as a 500
            _log.warning("catalogue_import.document_read_failed", business_id=str(business_id),
                         error=type(exc).__name__)
            raise ValidationError("LOCAH couldn't read that file. Try a clearer photo, or upload a sheet.",
                                  details={"field": "file"}) from exc
        headers = ["Name", "Description", "Category", "Price"]
        rows: list[list[str]] = []
        uncertain: list[int] = []
        for group in groups:
            for item in group.items:
                size = item.variant or item.unit
                name = f"{item.name} ({size})" if size else item.name
                description = " · ".join(p for p in (item.description, item.attributes) if p)
                if item.confidence == "low":
                    uncertain.append(len(rows))
                rows.append([name, description, "" if group.name == "More" else group.name, item.price])
        if not rows:
            raise ValidationError("LOCAH couldn't find items in that file. Try a clearer photo, or upload a sheet.",
                                  details={"field": "file"})
        table = Table("document", headers, rows, file_hash(data), notes=[
            "Read by LOCAH from your file — check names and prices before importing."])
        result = await CatalogueImportService._read_result(session, business_id, table)
        result["uncertain_rows"] = uncertain
        return result

    @staticmethod
    async def _read_result(session: AsyncSession, business_id: uuid.UUID, table: Table) -> dict[str, Any]:
        previous = (await session.execute(
            select(OfferingCatalogImport).where(OfferingCatalogImport.business_id == business_id,
                                                OfferingCatalogImport.file_hash == table.file_hash)
            .order_by(OfferingCatalogImport.created_at.desc()).limit(1))).scalars().first()
        return {
            "source": table.source,
            "file_hash": table.file_hash,
            "headers": table.headers,
            "rows": table.rows,
            "suggested_mapping": suggest_mapping(table.headers),
            "fields": [{"key": f, "label": FIELD_LABELS[f]} for f in FIELDS],
            "notes": table.notes,
            "previous_import": None if previous is None else {
                "id": str(previous.id), "at": previous.created_at.isoformat() if previous.created_at else None,
                "created": previous.created_count},
        }

    # ------------------------------------------------------------ check

    @staticmethod
    async def _context(session: AsyncSession, business_id: uuid.UUID, *, may_adjust_stock: bool) -> dict[str, Any]:
        from platform_core.services.module_readiness import module_operational

        offerings = (await session.execute(select(Offering).where(
            Offering.business_id == business_id, Offering.deleted_at.is_(None),
            Offering.status != "archived"))).scalars().all()
        locations = (await session.execute(select(BusinessLocation).where(
            BusinessLocation.business_id == business_id, BusinessLocation.deleted_at.is_(None),
            BusinessLocation.status == "active").order_by(BusinessLocation.is_primary.desc()))).scalars().all()
        stock_on = may_adjust_stock and await module_operational(session, business_id, "inventory")
        return {
            "terminology_kind": await CatalogueImportService._terminology_kind(session, business_id),
            "existing": [Existing(str(o.id), o.title, o.status, o.sku) for o in offerings],
            "kinds_in_use": Counter(o.offering_type for o in offerings),
            "locations": {norm_name(loc.name): str(loc.id) for loc in locations if loc.name},
            "primary_location": str(locations[0].id) if locations else None,
            "stock_allowed": stock_on,
        }

    @staticmethod
    async def _terminology_kind(session: AsyncSession, business_id: uuid.UUID) -> str | None:
        """The kind the Business's own words name ("menu item" for a café), if one fits."""
        from platform_core.models import Business
        from platform_core.services.business_configuration import BusinessConfigurationResolver

        business = await session.get(Business, business_id)
        if business is None:
            return None
        terminology = BusinessConfigurationResolver.resolve_from_business(business).resolved.get("terminology") or {}
        return _kind_words().get(norm_name(str(terminology.get("product") or "")))

    @staticmethod
    def suggested_kind(kinds_in_use: Counter[str], terminology_kind: str | None = None) -> str:
        """What is already listed most; before anything is, what the Business calls its items."""
        for key, _ in kinds_in_use.most_common():
            if key in IMPORT_KINDS:
                return key
        return terminology_kind or "product"

    @staticmethod
    async def check(session: AsyncSession, business_id: uuid.UUID, *, rows: list[dict[str, str]],
                    default_kind: str | None, may_adjust_stock: bool) -> dict[str, Any]:
        ctx = await CatalogueImportService._context(session, business_id, may_adjust_stock=may_adjust_stock)
        kind = default_kind or CatalogueImportService.suggested_kind(ctx["kinds_in_use"], ctx["terminology_kind"])
        if kind not in IMPORT_KINDS:
            raise ValidationError("Choose what these items are", details={"field": "default_kind"})
        results = validate_rows(rows, existing=ctx["existing"], kinds=_kind_words(), default_kind=kind,
                                bookable_kinds=bookable_kinds(), location_names=ctx["locations"],
                                stock_allowed=ctx["stock_allowed"])
        for r in results:
            # Imported anyway, but say now what will hold it back from going live.
            k = KINDS.get(str(r.values.get("kind")))
            if r.status != "error" and k and r.values.get("duration") is None and any(
                    f.required and f.key == "duration_minutes" for f in k.fields):
                r.notes.append("No duration — it comes in as a draft; add how long it takes before it goes live")
        counts = Counter(r.status for r in results)
        return {
            "default_kind": kind,
            "kinds": [{"key": k, "label": KINDS[k].label, "plural": KINDS[k].plural} for k in IMPORT_KINDS],
            "stock_allowed": ctx["stock_allowed"],
            "rows": [r.as_dict() for r in results],
            "summary": {"ready": counts["ready"], "duplicate": counts["duplicate"], "error": counts["error"],
                        "total": len(results)},
        }

    # ------------------------------------------------------------ import

    @staticmethod
    async def commit(session: AsyncSession, business_id: uuid.UUID, *, actor_id: uuid.UUID, correlation_id: str,
                     filename: str, file_hash: str, source: str, rows: list[dict[str, str]],
                     decisions: dict[int, str], default_kind: str | None,
                     may_adjust_stock: bool) -> dict[str, Any]:
        from platform_core.services.audit import AuditService
        from platform_core.services.category import CategoryService
        from platform_core.services.inventory import InventoryService
        from platform_core.services.offering import OfferingService

        if source not in ("csv", "xlsx", "document"):
            raise ValidationError("Unknown import source", details={"field": "source"})
        if not rows:
            raise ValidationError("There is nothing to import", details={"field": "rows"})
        checked = await CatalogueImportService.check(session, business_id, rows=rows, default_kind=default_kind,
                                                     may_adjust_stock=may_adjust_stock)
        ctx = await CatalogueImportService._context(session, business_id, may_adjust_stock=may_adjust_stock)
        categories: dict[str, uuid.UUID] = {
            norm_name(c.name): c.id for c in await CategoryService.list_for_business(session, business_id)}
        offering_ids: list[uuid.UUID] = []
        outcome: list[dict[str, Any]] = []
        created = updated = skipped = errors = 0

        async def category_id(name: str) -> uuid.UUID | None:
            if not name:
                return None
            key = norm_name(name)
            if key not in categories:
                cat = await CategoryService.create_category(session, business_id=business_id, actor_id=actor_id,
                                                            correlation_id=correlation_id, payload={"name": name})
                categories[key] = cat.id
            return categories[key]

        for raw in checked["rows"]:
            r = RowResult(raw["index"], raw["values"], raw["status"], raw["problems"], raw["notes"],
                          raw["duplicate_of"], raw["repeats_row"])
            decision = decisions.get(r.index, "skip" if r.status == "duplicate" else "create")
            if decision not in DECISIONS:
                decision = "skip"
            v = r.values
            if r.status == "error":
                errors += 1
                outcome.append({"index": r.index, "result": "error", "problems": r.problems})
                continue
            if decision == "skip":  # a duplicate by default; any row the owner unticked
                skipped += 1
                outcome.append({"index": r.index, "result": "skipped"})
                continue
            if r.status == "duplicate" and decision == "update" and (
                    not r.duplicate_of or r.duplicate_of["status"] != "draft"):
                skipped += 1
                outcome.append({"index": r.index, "result": "skipped",
                                "problems": ["Only a draft can be updated by an import — this item is live"]})
                continue
            try:
                async with session.begin_nested():
                    attrs = {"duration_minutes": v["duration"]} if (
                        v.get("duration") and v["kind"] in bookable_kinds()) else None
                    if r.status == "duplicate" and decision == "update" and r.duplicate_of:
                        patch: dict[str, Any] = {}
                        if v.get("description"):
                            patch["description"] = v["description"]
                        if v.get("price") is not None:
                            patch.update({"price_type": "fixed", "price_amount": Decimal(v["price"])})
                        if v.get("category"):
                            patch["category_id"] = await category_id(v["category"])
                        if attrs:
                            patch["attributes"] = attrs
                        item = await OfferingService.patch_offering(
                            session, business_id=business_id, offering_id=uuid.UUID(r.duplicate_of["id"]),
                            actor_id=actor_id, correlation_id=correlation_id, payload=patch)
                        updated += 1
                        result = "updated"
                    else:
                        payload: dict[str, Any] = {
                            "title": v["name"], "description": v.get("description") or None,
                            "offering_type": v["kind"], "status": "draft", "visibility": "public",
                            "price_type": "fixed" if v.get("price") is not None else "enquiry",
                            "price_amount": Decimal(v["price"]) if v.get("price") is not None else None,
                            "sku": v.get("sku"), "category_id": await category_id(v.get("category") or ""),
                            "track_inventory": bool(ctx["stock_allowed"] and v.get("stock") is not None),
                        }
                        if attrs:
                            payload["attributes"] = attrs
                        item = await OfferingService.create_offering(
                            session, business_id=business_id, actor_id=actor_id, correlation_id=correlation_id,
                            payload=payload)
                        created += 1
                        result = "created"
                    if ctx["stock_allowed"] and v.get("stock") is not None:
                        location = v.get("location_id") or ctx["primary_location"]
                        if location:
                            await InventoryService.set_opening_stock(
                                session, business_id=business_id, actor_id=actor_id, correlation_id=correlation_id,
                                payload={"offering_id": str(item.id), "location_id": location,
                                         "quantity": v["stock"]})
                offering_ids.append(item.id)
                outcome.append({"index": r.index, "result": result, "offering_id": str(item.id)})
            except (ValidationError, ConflictError) as exc:
                errors += 1
                outcome.append({"index": r.index, "result": "error", "problems": [_message(exc)]})

        batch = OfferingCatalogImport(
            business_id=business_id, filename=(filename or "import")[:200], file_hash=file_hash[:64] or "-",
            source=source, row_count=len(rows), created_count=created, updated_count=updated,
            skipped_count=skipped, error_count=errors, offering_ids=offering_ids, created_by=actor_id)
        session.add(batch)
        await session.flush()
        await AuditService.record(
            session, event_type="offerings.imported", actor_identity_id=actor_id, actor_context="business",
            action="import", business_id=business_id, resource_type="offerings_catalog_import", resource_id=batch.id,
            after_state={"rows": len(rows), "created": created, "updated": updated, "skipped": skipped,
                         "errors": errors, "source": source})
        return {"id": str(batch.id), "created": created, "updated": updated, "skipped": skipped, "errors": errors,
                "rows": outcome}

    # ------------------------------------------------------------ review

    @staticmethod
    async def _batch(session: AsyncSession, business_id: uuid.UUID, import_id: uuid.UUID) -> OfferingCatalogImport:
        batch = await session.get(OfferingCatalogImport, import_id)
        if batch is None or batch.business_id != business_id:
            raise ResourceNotFound("Import")
        return batch

    @staticmethod
    def _live_problem(o: Offering) -> str | None:
        if o.status == "archived" or o.deleted_at is not None:
            return "This item was archived"
        if o.price_type == "fixed" and o.price_amount is None:
            return "Add a price first"
        k = KINDS.get(o.offering_type)
        attrs = o.attributes or {}
        for f in (k.fields if k else ()):
            if f.required and attrs.get(f.key) in (None, "", []):
                return "Add how long it takes first" if f.key == "duration_minutes" else f"Add {f.label.lower()} first"
        return None

    @staticmethod
    async def get(session: AsyncSession, business_id: uuid.UUID, import_id: uuid.UUID) -> dict[str, Any]:
        batch = await CatalogueImportService._batch(session, business_id, import_id)
        items = (await session.execute(select(Offering).where(
            Offering.business_id == business_id, Offering.id.in_(list(batch.offering_ids or []))))).scalars().all()
        order = {oid: i for i, oid in enumerate(batch.offering_ids or [])}
        return {
            "id": str(batch.id), "filename": batch.filename, "source": batch.source,
            "at": batch.created_at.isoformat() if batch.created_at else None,
            "summary": {"rows": batch.row_count, "created": batch.created_count, "updated": batch.updated_count,
                        "skipped": batch.skipped_count, "errors": batch.error_count},
            "items": [{
                "id": str(o.id), "title": o.title, "status": o.status, "kind": o.offering_type,
                "kind_label": KINDS[o.offering_type].label if o.offering_type in KINDS else o.offering_type,
                "price_type": o.price_type,
                "price_amount": float(o.price_amount) if o.price_amount is not None else None,
                "can_go_live": o.status == "draft" and CatalogueImportService._live_problem(o) is None,
                "problem": CatalogueImportService._live_problem(o) if o.status == "draft" else None,
            } for o in sorted(items, key=lambda x: order.get(x.id, 0))],
        }

    @staticmethod
    async def make_live(session: AsyncSession, business_id: uuid.UUID, import_id: uuid.UUID, *,
                        offering_ids: list[uuid.UUID], actor_id: uuid.UUID, correlation_id: str) -> dict[str, Any]:
        from platform_core.services.offering import OfferingService

        batch = await CatalogueImportService._batch(session, business_id, import_id)
        allowed = set(batch.offering_ids or [])
        results = []
        for oid in offering_ids:
            if oid not in allowed:
                results.append({"id": str(oid), "result": "error", "problem": "Not part of this import"})
                continue
            o = await session.get(Offering, oid)
            if o is None or o.business_id != business_id:
                results.append({"id": str(oid), "result": "error", "problem": "Not found"})
                continue
            if o.status == "active":
                results.append({"id": str(oid), "result": "live"})
                continue
            problem = CatalogueImportService._live_problem(o)
            if problem:
                results.append({"id": str(oid), "result": "error", "problem": problem})
                continue
            await OfferingService.patch_offering(session, business_id=business_id, offering_id=oid,
                                                 actor_id=actor_id, correlation_id=correlation_id,
                                                 payload={"status": "active"})
            results.append({"id": str(oid), "result": "live"})
        return {"results": results, "live": sum(1 for r in results if r["result"] == "live")}

    @staticmethod
    async def recent(session: AsyncSession, business_id: uuid.UUID, limit: int = 5) -> list[dict[str, Any]]:
        rows = (await session.execute(select(OfferingCatalogImport).where(
            OfferingCatalogImport.business_id == business_id).order_by(
            OfferingCatalogImport.created_at.desc()).limit(limit))).scalars().all()
        return [{"id": str(b.id), "filename": b.filename, "at": b.created_at.isoformat() if b.created_at else None,
                 "created": b.created_count, "updated": b.updated_count} for b in rows]
