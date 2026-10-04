"""Counter billing (Capability Universe §14.1–§14.3, §14.5).

A register is the invoicing register (§14.4): the counter's bills are numbered
from its own series. A cash shift opens with the opening cash and closes with
the counted cash against what the drawer should hold:

    expected = opening + cash sales + cash put in − cash refunds − petty expenses − cash taken out

Each register holds a block of numbers (default 50) so bills rung up without a
connection keep legal sequential numbering (§14.2). The block stays with the
register across shifts; at close the unused end goes back to the series when
nothing was numbered after it, so the series stays gapless.

A cashier's limits are the owner's: a discount cap per role, a return window;
past them a manager approves with their PIN on the cashier's screen. The
approval is a short-lived signed token naming the approver and what they
approved — prompts, devices and cashiers cannot raise their own limits.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ConflictError, PermissionDenied, ResourceNotFound, ValidationError
from platform_core.invoicing.tax_engine import dec, money
from platform_core.models import (
    BusinessLocation,
    BusinessMembership,
    InventoryRecord,
    InvoicingDocument,
    InvoicingPayment,
    InvoicingRegister,
    InvoicingRegistration,
    InvoicingTaxProfile,
    LedgerEntry,
    Offering,
    OfferingVariant,
    PlatformIdentity,
    PosApprovalPin,
    PosCashMovement,
    PosSettings,
    PosShift,
)
from platform_core.pos.barcodes import clean_weighed_format
from platform_core.secrets import resolve_signing_secret
from platform_core.services.audit import AuditService
from platform_core.services.invoicing_setup import TaxRateService, local_today
from platform_core.services.number_series import Block, NumberSeriesService, financial_year

DEFAULT_BLOCK = 50
LOW_BLOCK = 10
APPROVAL_TTL = 600
PIN_LOCK_AFTER = 5
PIN_LOCK_MINUTES = 15
APPROVAL_ACTIONS = {"discount": "a discount above the cashier's limit", "void": "cancelling a bill",
                    "return": "a return after the return window", "credit": "khata above the customer's limit"}
CASH_KINDS = {"petty_expense": "Petty expense", "cash_in": "Cash put in", "cash_out": "Cash taken out",
              "refund": "Cash refund"}
_VPA = re.compile(r"^[A-Za-z0-9._-]{2,255}@[A-Za-z][A-Za-z0-9.-]{1,64}$")
# Kinds sold at a counter (a cart kind with a price). Enquiry-only kinds
# (property, vehicles, portfolio) and gifts stay off the counter.
COUNTER_KINDS = ("product", "weighed_product", "menu_item", "digital_product", "package", "service")


def _err(field: str, message: str) -> ValidationError:
    return ValidationError(message, details={"errors": [{"field": field, "message": message}], "field": field})


def _f(v: Any) -> float:
    return float(dec(v))


def holder(register_id: uuid.UUID) -> str:
    return f"register:{register_id}"


def series_key(register_id: uuid.UUID) -> str:
    return f"inv:{register_id}"


# ---------------------------------------------------------------------- approvals
def _secret() -> bytes:
    return str(resolve_signing_secret("POS_APPROVAL_SECRET", "pos-approval-dev-secret",
                                      fallback_env="SUPABASE_JWT_SECRET")).encode()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_approval(claims: dict[str, Any]) -> str:
    body = _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    mac = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{mac}"


def read_approval(token: str | None, business_id: uuid.UUID, action: str) -> dict[str, Any] | None:
    """The approval's claims if it is genuine, unexpired and for this action."""
    if not token or "." not in token:
        return None
    body, mac = token.rsplit(".", 1)
    good = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(good, mac):
        return None
    try:
        claims = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if claims.get("b") != str(business_id) or claims.get("action") != action or claims.get("exp", 0) < time.time():
        return None
    return dict(claims)


def _hash_pin(pin: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 120_000)
    return f"pbkdf2${_b64(salt)}${_b64(digest)}"


def _pin_ok(pin: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(_hash_pin(pin, _unb64(salt)).split("$")[2], digest)


class PosService:
    # ------------------------------------------------------------------ settings
    @staticmethod
    def serialize_settings(s: PosSettings | None) -> dict[str, Any]:
        return {
            "upi_vpa": s.upi_vpa if s else None,
            "upi_payee_name": s.upi_payee_name if s else None,
            "return_window_days": s.return_window_days if s else 7,
            "discount_caps": dict(s.discount_caps or {}) if s else {},
            "block_size": s.block_size if s else DEFAULT_BLOCK,
            "weighed_label": s.weighed_label if s else None,
            "receipt_footer": s.receipt_footer if s else None,
            "configured": s is not None,
        }

    @staticmethod
    async def settings(session: AsyncSession, business_id: uuid.UUID) -> PosSettings | None:
        return await session.get(PosSettings, business_id)

    @staticmethod
    async def save_settings(session: AsyncSession, business_id: uuid.UUID, actor_id: uuid.UUID,
                            payload: dict[str, Any]) -> PosSettings:
        vpa = (str(payload.get("upi_vpa") or "").strip() or None)
        if vpa and not _VPA.match(vpa):
            raise _err("upi_vpa", "A UPI ID looks like name@bank")
        caps_raw = payload.get("discount_caps") or {}
        caps: dict[str, float] = {}
        for role, pct in dict(caps_raw).items():
            try:
                value = float(pct)
            except (TypeError, ValueError) as exc:
                raise _err("discount_caps", "Discount limits are percentages") from exc
            if not 0 <= value <= 100:
                raise _err("discount_caps", "Discount limits are between 0 and 100%")
            caps[str(role)] = value
        window = int(payload.get("return_window_days", 7))
        block = int(payload.get("block_size", DEFAULT_BLOCK))
        if not 0 <= window <= 365:
            raise _err("return_window_days", "Between 0 and 365 days")
        if not 10 <= block <= 500:
            raise _err("block_size", "Between 10 and 500 numbers")
        fmt = clean_weighed_format(payload.get("weighed_label"))
        row = await session.get(PosSettings, business_id)
        before = PosService.serialize_settings(row)
        if row is None:
            row = PosSettings(business_id=business_id)
            session.add(row)
        row.upi_vpa, row.upi_payee_name = vpa, (str(payload.get("upi_payee_name") or "").strip()[:100] or None)
        row.discount_caps, row.return_window_days, row.block_size = caps, window, block
        row.weighed_label = fmt.as_dict() if fmt else None
        row.receipt_footer = str(payload.get("receipt_footer") or "").strip()[:300] or None
        row.updated_by, row.updated_at = actor_id, datetime.now(timezone.utc)
        await session.flush()
        await AuditService.record(session, event_type="pos.settings.updated", actor_identity_id=actor_id,
                                  actor_context="business", action="update", business_id=business_id,
                                  resource_type="pos_settings", before_state=before,
                                  after_state=PosService.serialize_settings(row))
        return row

    @staticmethod
    async def set_upi(session: AsyncSession, business_id: uuid.UUID, actor_id: uuid.UUID, *,
                      upi_vpa: str | None, upi_payee_name: str | None) -> PosSettings:
        """The business's one UPI ID — used at the counter and on payment links.
        Set from Payments without touching the counter's other settings."""
        vpa = (upi_vpa or "").strip() or None
        if vpa and not _VPA.match(vpa):
            raise _err("upi_vpa", "A UPI ID looks like name@bank")
        row = await session.get(PosSettings, business_id)
        before = PosService.serialize_settings(row)
        if row is None:
            row = PosSettings(business_id=business_id)
            session.add(row)
        row.upi_vpa, row.upi_payee_name = vpa, ((upi_payee_name or "").strip()[:100] or None)
        row.updated_by, row.updated_at = actor_id, datetime.now(timezone.utc)
        await session.flush()
        await AuditService.record(session, event_type="payments.upi.updated", actor_identity_id=actor_id,
                                  actor_context="business", action="update", business_id=business_id,
                                  resource_type="pos_settings", before_state=before,
                                  after_state=PosService.serialize_settings(row))
        return row

    # ------------------------------------------------------------------ PINs and approvals
    @staticmethod
    async def set_pin(session: AsyncSession, business_id: uuid.UUID, identity_id: uuid.UUID, pin: str) -> None:
        if not re.fullmatch(r"\d{4,6}", pin or ""):
            raise _err("pin", "A PIN is 4 to 6 digits")
        if len(set(pin)) == 1 or pin in "0123456789" or pin in "9876543210":
            raise _err("pin", "Choose a PIN that is not a run or a repeat")
        row = await session.get(PosApprovalPin, (business_id, identity_id))
        if row is None:
            row = PosApprovalPin(business_id=business_id, identity_id=identity_id, pin_hash="")
            session.add(row)
        row.pin_hash, row.failed_attempts, row.locked_until = _hash_pin(pin), 0, None
        row.updated_at = datetime.now(timezone.utc)
        await session.flush()
        await AuditService.record(session, event_type="pos.pin.set", actor_identity_id=identity_id,
                                  actor_context="business", action="set_pin", business_id=business_id,
                                  resource_type="pos_approval_pin")

    @staticmethod
    async def approvers(session: AsyncSession, business_id: uuid.UUID) -> list[dict[str, Any]]:
        """People who can approve at the counter: an approval PIN and pos.approve today."""
        from platform_core.authorization.resolver import AuthorizationService

        rows = (await session.execute(
            select(PosApprovalPin.identity_id, PlatformIdentity.display_name, PlatformIdentity.email)
            .join(PlatformIdentity, PlatformIdentity.id == PosApprovalPin.identity_id)
            .where(PosApprovalPin.business_id == business_id)
        )).all()
        out = []
        for identity_id, name, email in rows:
            perms = await AuthorizationService.effective_permissions(session, business_id=business_id,
                                                                     identity_id=identity_id)
            if "pos.approve" in perms:
                out.append({"identity_id": str(identity_id), "name": name or (email or "").split("@")[0]})
        return out

    @staticmethod
    async def approve(
        session: AsyncSession, business_id: uuid.UUID, *, requester_id: uuid.UUID, approver_id: uuid.UUID,
        pin: str, action: str, max_discount_pct: float | None = None, document_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """A manager approves on the cashier's screen with their PIN."""
        from platform_core.authorization.resolver import AuthorizationService

        if action not in APPROVAL_ACTIONS:
            raise _err("action", "Unknown approval")
        row = await session.get(PosApprovalPin, (business_id, approver_id))
        now = datetime.now(timezone.utc)
        if row is None:
            raise _err("approver", "That person has no approval PIN")
        if row.locked_until and row.locked_until > now:
            raise ConflictError("Too many wrong PINs. Try again in a few minutes.")
        perms = await AuthorizationService.effective_permissions(session, business_id=business_id,
                                                                 identity_id=approver_id)
        if "pos.approve" not in perms:
            raise PermissionDenied("pos.approve")
        if not _pin_ok(pin, row.pin_hash):
            row.failed_attempts += 1
            if row.failed_attempts >= PIN_LOCK_AFTER:
                row.locked_until, row.failed_attempts = now + timedelta(minutes=PIN_LOCK_MINUTES), 0
            await session.flush()
            raise _err("pin", "That PIN is not right")
        row.failed_attempts, row.locked_until = 0, None
        claims: dict[str, Any] = {"b": str(business_id), "action": action, "by": str(approver_id),
                                  "for": str(requester_id), "exp": int(time.time()) + APPROVAL_TTL,
                                  "n": uuid.uuid4().hex}
        if max_discount_pct is not None:
            claims["max_pct"] = float(max_discount_pct)
        if document_id is not None:
            claims["doc"] = str(document_id)
        await AuditService.record(session, event_type="pos.approval.granted", actor_identity_id=approver_id,
                                  actor_context="business", action=action, business_id=business_id,
                                  resource_type="pos_approval", after_state={k: v for k, v in claims.items() if k != "n"})
        return {"token": sign_approval(claims), "expires_in": APPROVAL_TTL, "action": action}

    # ------------------------------------------------------------------ role limits
    @staticmethod
    async def role_key(session: AsyncSession, business_id: uuid.UUID, identity_id: uuid.UUID) -> str:
        from platform_core.services.role_home import RoleHomeService

        m = (await session.execute(select(BusinessMembership).where(
            BusinessMembership.business_id == business_id, BusinessMembership.identity_id == identity_id,
            BusinessMembership.status == "active", BusinessMembership.deleted_at.is_(None)))).scalars().first()
        return await RoleHomeService.role_key(session, m) if m else "member"

    @staticmethod
    async def discount_cap(session: AsyncSession, business_id: uuid.UUID, identity_id: uuid.UUID) -> float | None:
        """The largest discount (percent of the bill) this person may give; None = no limit (owner)."""
        key = await PosService.role_key(session, business_id, identity_id)
        if key == "owner":
            return None
        s = await session.get(PosSettings, business_id)
        return float((s.discount_caps or {}).get(key, 0)) if s else 0.0

    # ------------------------------------------------------------------ catalogue
    @staticmethod
    async def catalogue(session: AsyncSession, business_id: uuid.UUID, location_id: uuid.UUID) -> dict[str, Any]:
        """Everything the counter needs to sell offline, with a version stamp."""
        offerings = list((await session.execute(select(Offering).where(
            Offering.business_id == business_id, Offering.deleted_at.is_(None), Offering.status == "active",
            Offering.offering_type.in_(COUNTER_KINDS), Offering.price_amount.is_not(None),
        ).order_by(Offering.title))).scalars())
        ids = [o.id for o in offerings]
        variants: dict[uuid.UUID, list[OfferingVariant]] = {}
        for v in (await session.execute(select(OfferingVariant).where(
                OfferingVariant.offering_id.in_(ids), OfferingVariant.deleted_at.is_(None),
                OfferingVariant.status == "active").order_by(OfferingVariant.sort_order))).scalars():
            variants.setdefault(v.offering_id, []).append(v)
        stock = {(r.offering_id, r.variant_id): r.quantity_on_hand - r.quantity_reserved
                 for r in (await session.execute(select(InventoryRecord).where(
                     InventoryRecord.business_id == business_id, InventoryRecord.location_id == location_id,
                     InventoryRecord.owner_customer_id.is_(None),
                     InventoryRecord.offering_id.in_(ids)))).scalars()}
        # §15.1: units in stock here by serial, so scanning the IMEI on the box
        # adds that phone — offline too (up to 300 per item on the counter).
        serials: dict[uuid.UUID, list[str]] = {}
        serial_ids = [o.id for o in offerings if o.serial_tracked]
        if serial_ids:
            from platform_core.models import InventorySerial

            for oid, serial in (await session.execute(select(InventorySerial.offering_id, InventorySerial.serial).where(
                    InventorySerial.business_id == business_id, InventorySerial.location_id == location_id,
                    InventorySerial.offering_id.in_(serial_ids), InventorySerial.status == "in_stock")
                    .order_by(InventorySerial.received_at))).all():
                if len(serials.setdefault(oid, [])) < 300:
                    serials[oid].append(serial)
        today = local_today()
        rates = await TaxRateService.resolve(session, business_id, [(o.id, o.hsn_sac, o.tax_rate) for o in offerings],
                                             today)
        version = max([o.updated_at for o in offerings], default=datetime.now(timezone.utc))
        latest_rate = (await session.execute(text(
            "SELECT max(created_at) FROM invoicing_tax_rates WHERE business_id = :b"), {"b": str(business_id)})).scalar()
        if latest_rate and latest_rate > version:
            version = latest_rate
        items = []
        for o, rate in zip(offerings, rates):
            from platform_core.services.offering_pricing import price_selection

            packs = []
            for p in o.sell_units or []:
                try:
                    priced = price_selection(o, None, {"pack": p.get("label")})
                    packs.append({"label": p.get("label"), "price": _f(priced.unit_price),
                                  "stock_per_unit": priced.stock_per_unit})
                except Exception:  # noqa: BLE001 — a pack the catalogue cannot price is left off the counter
                    continue
            items.append({
                "id": str(o.id), "title": o.title, "kind": o.offering_type, "price": _f(o.price_amount),
                "sku": o.sku, "barcode": o.barcode, "hsn_sac": o.hsn_sac,
                "rate": _f(rate) if rate is not None else None, "stock_unit": o.stock_unit,
                "price_per": (o.attributes or {}).get("price_per"), "track_inventory": o.track_inventory,
                "available": stock.get((o.id, None)), "packs": packs,
                "serial_tracked": o.serial_tracked, "serials": serials.get(o.id, []),
                "variants": [{"id": str(v.id), "name": v.name, "sku": v.sku, "barcode": getattr(v, "barcode", None),
                              "price": _f(v.price_amount) if v.price_amount is not None else _f(o.price_amount),
                              "available": stock.get((o.id, v.id))} for v in variants.get(o.id, [])],
            })
        return {"version": version.isoformat(), "items": items, "today": today.isoformat()}

    # ------------------------------------------------------------------ number blocks
    @staticmethod
    async def _active_blocks(session: AsyncSession, business_id: uuid.UUID, register_id: uuid.UUID,
                             period: str) -> list[tuple[Block, int]]:
        """The register's active blocks in order, each with its next unused
        number; used-up blocks are marked exhausted on the way."""
        ids = [r[0] for r in (await session.execute(text(
            "SELECT id FROM number_series_blocks WHERE business_id = :b AND series_key = :k AND period = :p "
            "AND holder = :h AND status = 'active' ORDER BY start_value"),
            {"b": str(business_id), "k": series_key(register_id), "p": period, "h": holder(register_id)})).all()]
        out: list[tuple[Block, int]] = []
        for bid in ids:
            blk = await NumberSeriesService.block(session, business_id, bid)
            nxt = await PosService._next_in(session, business_id, register_id, blk)
            if nxt is None or nxt > blk.end:
                await session.execute(text(
                    "UPDATE number_series_blocks SET status = 'exhausted' WHERE business_id = :b AND id = :id"),
                    {"b": str(business_id), "id": str(bid)})
                continue
            out.append((blk, nxt))
        return out

    @staticmethod
    async def ensure_block(session: AsyncSession, business_id: uuid.UUID, register: InvoicingRegister,
                           *, fy: str | None = None) -> dict[str, Any]:
        """Numbers the register may use without a connection: its current block
        and, when fewer than LOW_BLOCK are left, the next block too (§14.2)."""
        period = fy or financial_year(local_today())
        blocks = await PosService._active_blocks(session, business_id, register.id, period)
        left = sum(b.end - n + 1 for b, n in blocks)
        if left < LOW_BLOCK:
            settings = await session.get(PosSettings, business_id)
            fresh = await NumberSeriesService.reserve_block(
                session, business_id, series_key=series_key(register.id), holder=holder(register.id),
                period=period, prefix=register.code, pad=register.pad,
                size=settings.block_size if settings else DEFAULT_BLOCK)
            blocks.append((fresh, fresh.start))
        current, nxt = blocks[0]
        view = PosService._block_view(current, nxt)
        if len(blocks) > 1:
            view["next_block"] = PosService._block_view(*blocks[1])
        return view

    @staticmethod
    def _block_view(blk: Block, next_value: int) -> dict[str, Any]:
        return {"id": str(blk.id), "start": blk.start, "end": blk.end, "next": next_value, "period": blk.period,
                "prefix": blk.prefix, "pad": blk.pad}

    @staticmethod
    async def _next_in(session: AsyncSession, business_id: uuid.UUID, register_id: uuid.UUID,
                       blk: Block) -> int | None:
        used = (await session.execute(select(func.max(InvoicingDocument.seq)).where(
            InvoicingDocument.business_id == business_id, InvoicingDocument.series_key == series_key(register_id),
            InvoicingDocument.fy == blk.period, InvoicingDocument.seq.between(blk.start, blk.end),
        ).execution_options(skip_location_scope=True))).scalar()
        nxt = (int(used) + 1) if used else blk.start
        return nxt if nxt <= blk.end + 1 else None

    # ------------------------------------------------------------------ shifts
    @staticmethod
    def serialize_shift(s: PosShift, summary: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "id": str(s.id), "register_id": str(s.register_id), "location_id": str(s.location_id),
            "device_id": s.device_id, "status": s.status, "opened_at": s.opened_at.isoformat() if s.opened_at else None,
            "opened_by": str(s.opened_by), "opening_cash": _f(s.opening_cash),
            "closed_at": s.closed_at.isoformat() if s.closed_at else None,
            "expected_cash": _f(s.expected_cash) if s.expected_cash is not None else None,
            "counted_cash": _f(s.counted_cash) if s.counted_cash is not None else None,
            "variance": _f(s.variance) if s.variance is not None else None, "close_note": s.close_note,
            **({"summary": summary} if summary is not None else {}),
        }

    @staticmethod
    async def _register(session: AsyncSession, business_id: uuid.UUID, register_id: uuid.UUID) -> InvoicingRegister:
        reg = (await session.execute(select(InvoicingRegister).where(
            InvoicingRegister.business_id == business_id, InvoicingRegister.id == register_id))).scalars().first()
        if reg is None:
            raise ResourceNotFound("Register")
        if reg.status != "active":
            raise ConflictError("That register is switched off")
        return reg

    @staticmethod
    async def open_shift(
        session: AsyncSession, business_id: uuid.UUID, actor_id: uuid.UUID, *, register_id: uuid.UUID,
        device_id: str, opening_cash: Any,
    ) -> tuple[PosShift, dict[str, Any]]:
        register = await PosService._register(session, business_id, register_id)
        if await session.get(InvoicingTaxProfile, business_id) is None:
            raise ConflictError("Set up how you bill first: Settings → Tax & invoicing", details={"needs": "tax_profile"})
        existing = (await session.execute(select(PosShift).where(
            PosShift.business_id == business_id, PosShift.register_id == register_id,
            PosShift.status == "open").with_for_update())).scalars().first()
        if existing is not None:
            if existing.opened_by != actor_id:
                raise ConflictError("This register already has an open shift. Close it first, or use another register.",
                                    details={"shift_id": str(existing.id)})
            existing.device_id = device_id  # the same person continues on this device
            await session.flush()
            return existing, await PosService.ensure_block(session, business_id, register)
        cash = money(dec(opening_cash))
        if cash < 0:
            raise _err("opening_cash", "Opening cash cannot be negative")
        shift = PosShift(business_id=business_id, location_id=register.location_id, register_id=register.id,
                         device_id=device_id[:80], opened_by=actor_id, opening_cash=cash)
        session.add(shift)
        await session.flush()
        block = await PosService.ensure_block(session, business_id, register)
        await AuditService.record(session, event_type="pos.shift.opened", actor_identity_id=actor_id,
                                  actor_context="business", action="open", business_id=business_id,
                                  resource_type="pos_shift", resource_id=shift.id,
                                  after_state={"register": register.code, "opening_cash": _f(cash)})
        return shift, block

    @staticmethod
    async def get_shift(session: AsyncSession, business_id: uuid.UUID, shift_id: uuid.UUID, *,
                        lock: bool = False) -> PosShift:
        q = select(PosShift).where(PosShift.business_id == business_id, PosShift.id == shift_id)
        if lock:
            q = q.with_for_update().execution_options(populate_existing=True)
        shift = (await session.execute(q)).scalars().first()
        if shift is None:
            raise ResourceNotFound("Shift")
        return shift

    @staticmethod
    async def summary(session: AsyncSession, shift: PosShift) -> dict[str, Any]:
        pay = (await session.execute(
            select(InvoicingPayment.method, InvoicingPayment.verification, func.coalesce(func.sum(InvoicingPayment.amount), 0))
            .join(InvoicingDocument, InvoicingDocument.id == InvoicingPayment.document_id)
            .where(InvoicingPayment.shift_id == shift.id, InvoicingDocument.status == "issued")
            .group_by(InvoicingPayment.method, InvoicingPayment.verification)
        )).all()
        by: dict[str, Decimal] = {}
        to_verify = Decimal(0)
        for method, verification, total in pay:
            if verification == "not_received":
                continue
            by[method] = by.get(method, Decimal(0)) + dec(total)
            if verification == "to_verify":
                to_verify += dec(total)
        moves = {k: dec(v) for k, v in (await session.execute(
            select(PosCashMovement.kind, func.coalesce(func.sum(PosCashMovement.amount), 0))
            .where(PosCashMovement.shift_id == shift.id).group_by(PosCashMovement.kind))).all()}
        counts: dict[str, int] = {str(k): int(v) for k, v in (await session.execute(
            select(InvoicingDocument.status, func.count()).where(
                InvoicingDocument.shift_id == shift.id, InvoicingDocument.doc_kind != "credit_note")
            .group_by(InvoicingDocument.status))).all()}
        sales = dec((await session.execute(select(func.coalesce(func.sum(InvoicingDocument.amount_due), 0)).where(
            InvoicingDocument.shift_id == shift.id, InvoicingDocument.status == "issued",
            InvoicingDocument.doc_kind != "credit_note"))).scalar())
        returns = (await session.execute(select(func.count()).select_from(InvoicingDocument).where(
            InvoicingDocument.shift_id == shift.id, InvoicingDocument.doc_kind == "credit_note",
            InvoicingDocument.status == "issued"))).scalar()
        # Khata at this counter (§14.5): credit given on bills, and money paid
        # off accounts — the cash part is in the drawer.
        khata: dict[str, Decimal] = {}
        for kind, method, total in (await session.execute(
            select(LedgerEntry.kind, LedgerEntry.method, func.coalesce(func.sum(LedgerEntry.amount), 0))
            .where(LedgerEntry.shift_id == shift.id).group_by(LedgerEntry.kind, LedgerEntry.method))).all():
            key = "given" if kind == "credit_sale" else f"paid_{method or 'other'}" if kind == "payment_received" \
                else "other"
            khata[key] = khata.get(key, Decimal(0)) + dec(total)
        # A voided khata bill's credit is taken back by an adjustment on the bill.
        voided_khata = dec((await session.execute(
            select(func.coalesce(func.sum(LedgerEntry.amount), 0))
            .join(InvoicingDocument, InvoicingDocument.id == LedgerEntry.document_id)
            .where(LedgerEntry.shift_id == shift.id, LedgerEntry.kind == "credit_sale",
                   InvoicingDocument.status == "cancelled"))).scalar())
        zero = Decimal(0)
        khata_cash = -khata.get("paid_cash", zero)
        expected = (dec(shift.opening_cash) + by.get("cash", zero) + moves.get("cash_in", zero) + khata_cash
                    - moves.get("refund", zero) - moves.get("petty_expense", zero) - moves.get("cash_out", zero))
        return {
            "bills": int(counts.get("issued", 0)), "voided": int(counts.get("cancelled", 0)), "returns": int(returns or 0),
            "sales_total": _f(sales), "cash_sales": _f(by.get("cash", zero)), "upi": _f(by.get("upi", zero)),
            "upi_to_verify": _f(to_verify), "card": _f(by.get("card", zero)),
            "cash_in": _f(moves.get("cash_in", zero)), "cash_out": _f(moves.get("cash_out", zero)),
            "refunds": _f(moves.get("refund", zero)), "petty_expenses": _f(moves.get("petty_expense", zero)),
            "opening_cash": _f(shift.opening_cash), "expected_cash": _f(expected),
            "khata_given": _f(khata.get("given", zero) - voided_khata),
            "khata_received": _f(-sum((v for k, v in khata.items() if k.startswith("paid_")), zero)),
            "khata_cash": _f(khata_cash),
        }

    @staticmethod
    async def close_shift(
        session: AsyncSession, business_id: uuid.UUID, actor_id: uuid.UUID, shift_id: uuid.UUID, *,
        counted_cash: Any, note: str | None, last_used: int | None,
    ) -> PosShift:
        shift = await PosService.get_shift(session, business_id, shift_id, lock=True)
        if shift.status != "open":
            raise ConflictError("This shift is already closed")
        counted = money(dec(counted_cash))
        if counted < 0:
            raise _err("counted_cash", "Counted cash cannot be negative")
        summary = await PosService.summary(session, shift)
        expected = money(dec(summary["expected_cash"]))
        shift.status, shift.closed_by, shift.closed_at = "closed", actor_id, datetime.now(timezone.utc)
        shift.counted_cash, shift.expected_cash, shift.variance = counted, expected, counted - expected
        shift.close_note = (note or "").strip()[:500] or None
        register = await session.get(InvoicingRegister, shift.register_id)
        assert register is not None
        blocks = await PosService._active_blocks(session, business_id, register.id, financial_year(local_today()))
        known_last = max((n - 1 for _, n in blocks), default=None)
        if last_used is not None and blocks and known_last is not None and last_used > known_last \
                and any(b.start <= last_used <= b.end for b, _ in blocks):
            raise ConflictError("Bills on this device have not reached LOCAH yet. Sync them, then close the shift.",
                                details={"last_used": last_used, "known": known_last})
        returned = 0
        for blk, nxt in reversed(blocks):  # the newest block is the series tail
            returned += await NumberSeriesService.return_tail(session, business_id, blk.id,
                                                              nxt - 1 if nxt > blk.start else None)
        await session.flush()
        await AuditService.record(session, event_type="pos.shift.closed", actor_identity_id=actor_id,
                                  actor_context="business", action="close", business_id=business_id,
                                  resource_type="pos_shift", resource_id=shift.id,
                                  after_state={"expected": _f(expected), "counted": _f(counted),
                                               "variance": _f(shift.variance), "numbers_returned": returned})
        if shift.variance != 0:
            from platform_core.permissions import POS_APPROVE
            from platform_core.services.notification import NotificationService

            word = "short" if shift.variance < 0 else "over"
            await NotificationService.fan_out(
                session, business_id=business_id, notification_type="pos.drawer_variance",
                title=f"Drawer {word} by ₹{abs(_f(shift.variance)):,.2f} at {register.name}",
                body=f"Expected ₹{_f(expected):,.2f}, counted ₹{_f(counted):,.2f}.",
                required_permission=POS_APPROVE, severity="warning", resource_type="pos_shift",
                resource_id=shift.id, location_id=shift.location_id, exclude_identity_id=actor_id,
            )
        return shift

    @staticmethod
    async def cash_movement(
        session: AsyncSession, business_id: uuid.UUID, actor_id: uuid.UUID, shift_id: uuid.UUID, *, kind: str,
        amount: Any, reason: str, document_id: uuid.UUID | None = None, client_mutation_id: uuid.UUID | None = None,
    ) -> PosCashMovement:
        if kind not in CASH_KINDS:
            raise _err("kind", "Unknown drawer movement")
        shift = await PosService.get_shift(session, business_id, shift_id, lock=True)
        if shift.status != "open":
            raise ConflictError("The shift is closed")
        value = money(dec(amount))
        if value <= 0:
            raise _err("amount", "Enter the amount")
        if not (reason or "").strip():
            raise _err("reason", "Say what it was for")
        row = PosCashMovement(business_id=business_id, shift_id=shift.id, location_id=shift.location_id, kind=kind,
                              amount=value, reason=reason.strip()[:300], document_id=document_id,
                              client_mutation_id=client_mutation_id, created_by=actor_id)
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def shifts(session: AsyncSession, business_id: uuid.UUID, limit: int = 60) -> list[dict[str, Any]]:
        rows = (await session.execute(
            select(PosShift, InvoicingRegister.name, InvoicingRegister.code, BusinessLocation.name,
                   PlatformIdentity.display_name)
            .join(InvoicingRegister, InvoicingRegister.id == PosShift.register_id)
            .join(BusinessLocation, BusinessLocation.id == PosShift.location_id)
            .outerjoin(PlatformIdentity, PlatformIdentity.id == PosShift.opened_by)
            .where(PosShift.business_id == business_id).order_by(PosShift.opened_at.desc()).limit(limit)
        )).all()
        out = []
        for shift, rname, code, lname, who in rows:
            summary = await PosService.summary(session, shift)
            out.append({**PosService.serialize_shift(shift, summary), "register": f"{rname} ({code})",
                        "location_name": lname, "opened_by_name": who})
        return out

    # ------------------------------------------------------------------ UPI
    @staticmethod
    def upi_uri(vpa: str, name: str, amount: Any, note: str) -> str:
        from urllib.parse import quote

        return (f"upi://pay?pa={quote(vpa, safe='@.')}&pn={quote(name[:40])}&am={money(dec(amount)):.2f}"
                f"&cu=INR&tn={quote(note[:40])}")

    @staticmethod
    def qr_svg(data: str) -> str:
        from reportlab.graphics import renderSVG
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing

        widget = QrCodeWidget(data)
        x0, y0, x1, y1 = widget.getBounds()
        d = Drawing(220, 220, transform=[220 / (x1 - x0), 0, 0, 220 / (y1 - y0), 0, 0])
        d.add(widget)
        return str(renderSVG.drawToString(d))

    @staticmethod
    async def to_verify(session: AsyncSession, business_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = (await session.execute(
            select(InvoicingPayment, InvoicingDocument.number)
            .join(InvoicingDocument, InvoicingDocument.id == InvoicingPayment.document_id)
            .where(InvoicingPayment.business_id == business_id, InvoicingPayment.verification == "to_verify",
                   InvoicingDocument.status == "issued")
            .order_by(InvoicingPayment.created_at)
        )).all()
        return [{"id": str(p.id), "document_id": str(p.document_id), "number": n, "amount": _f(p.amount),
                 "method": p.method, "reference": p.reference, "received_on": p.received_on.isoformat()}
                for p, n in rows]

    @staticmethod
    async def verify_payment(session: AsyncSession, business_id: uuid.UUID, actor_id: uuid.UUID,
                             payment_id: uuid.UUID, received: bool) -> None:
        pay = (await session.execute(select(InvoicingPayment).where(
            InvoicingPayment.business_id == business_id, InvoicingPayment.id == payment_id).with_for_update())).scalars().first()
        if pay is None:
            raise ResourceNotFound("Payment")
        if pay.verification != "to_verify":
            raise ConflictError("That payment was already checked")
        pay.verification = "verified" if received else "not_received"
        pay.verified_by, pay.verified_at = actor_id, datetime.now(timezone.utc)
        if not received:
            doc = await session.get(InvoicingDocument, pay.document_id)
            if doc is not None:
                doc.amount_paid = max(Decimal(0), dec(doc.amount_paid) - dec(pay.amount))
                doc.version += 1
        await session.flush()
        await AuditService.record(session, event_type="pos.upi.verified", actor_identity_id=actor_id,
                                  actor_context="business", action="received" if received else "not_received",
                                  business_id=business_id, resource_type="invoicing_payment", resource_id=pay.id)

    # ------------------------------------------------------------------ setup for the counter screen
    @staticmethod
    async def setup(session: AsyncSession, business_id: uuid.UUID, actor_id: uuid.UUID) -> dict[str, Any]:
        profile = await session.get(InvoicingTaxProfile, business_id)
        registers = list((await session.execute(
            select(InvoicingRegister, BusinessLocation.name, InvoicingRegistration)
            .join(BusinessLocation, BusinessLocation.id == InvoicingRegister.location_id)
            .join(InvoicingRegistration, InvoicingRegistration.id == InvoicingRegister.registration_id)
            .where(InvoicingRegister.business_id == business_id, InvoicingRegister.status == "active")
            .order_by(BusinessLocation.name, InvoicingRegister.code)
        )).all())
        open_shifts = {s.register_id: s for s in (await session.execute(select(PosShift).where(
            PosShift.business_id == business_id, PosShift.status == "open"))).scalars()}
        settings = await session.get(PosSettings, business_id)
        cap = await PosService.discount_cap(session, business_id, actor_id)
        return {
            "profile": {"prices_include_tax": profile.prices_include_tax, "round_off": profile.round_off}
            if profile else None,
            "registers": [{"id": str(r.id), "name": r.name, "code": r.code, "location_id": str(r.location_id),
                           "location_name": lname, "scheme": g.scheme, "state_code": g.state_code,
                           # What an offline receipt prints (§14.4 outputs).
                           "seller": {"legal_name": g.legal_name, "trade_name": g.trade_name, "gstin": g.gstin,
                                      "address": g.address, "declaration": g.composition_declaration},
                           "open_shift": PosService.serialize_shift(open_shifts[r.id]) if r.id in open_shifts else None}
                          for r, lname, g in registers],
            "settings": PosService.serialize_settings(settings),
            "discount_cap": cap, "me": str(actor_id),
            "approvers": await PosService.approvers(session, business_id),
            "cash_kinds": {k: v for k, v in CASH_KINDS.items() if k != "refund"},
        }
