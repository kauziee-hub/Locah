"""Razorpay client: platform Route settlement + legacy key verification.

LOCAH holds one platform Razorpay account (RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET).
Businesses are onboarded as Route linked accounts. Customer checkout creates a
Razorpay order with a transfer to that linked account. LOCAH never redistributes
funds in application code.

Route must be enabled on the Razorpay platform account — that is an external
dashboard dependency. If it is not enabled, linked-account creation fails
honestly rather than collecting money onto the platform account.

`verify_key_pair` remains for the legacy merchant-key path (already shipped).
The normal merchant UX no longer requires it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx

_V1 = "https://api.razorpay.com/v1"
_V2 = "https://api.razorpay.com/v2"
_TIMEOUT = httpx.Timeout(15.0)


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    detail: str


@dataclass(frozen=True)
class PlatformCredentials:
    key_id: str
    key_secret: str
    fee_bps: int
    mode: str


@dataclass(frozen=True)
class LinkedAccountResult:
    ok: bool
    account_id: str | None
    status: str | None
    detail: str
    external_dependency: bool = False


@dataclass(frozen=True)
class RouteOrderResult:
    ok: bool
    order_id: str | None
    amount_paise: int
    transfer_paise: int
    platform_fee_paise: int
    detail: str


def platform_credentials() -> PlatformCredentials | None:
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        return None
    if not key_id.startswith(("rzp_test_", "rzp_live_")):
        return None
    raw_bps = os.getenv("RAZORPAY_PLATFORM_FEE_BPS", "0").strip() or "0"
    try:
        fee_bps = max(0, min(int(raw_bps), 10000))
    except ValueError:
        fee_bps = 0
    mode = "test" if key_id.startswith("rzp_test_") else "live"
    return PlatformCredentials(key_id=key_id, key_secret=key_secret, fee_bps=fee_bps, mode=mode)


def split_amount(gross: Decimal, fee_bps: int) -> tuple[Decimal, Decimal]:
    """Return (platform_fee, business_amount) in major units."""
    fee = (gross * Decimal(fee_bps) / Decimal(10000)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if fee > gross:
        fee = gross
    return fee, gross - fee


def _to_paise(amount: Decimal) -> int:
    return int((amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def verify_key_pair(key_id: str, key_secret: str) -> VerificationResult:
    """Confirm a Razorpay key pair by making one authenticated read call."""
    key_id = key_id.strip()
    key_secret = key_secret.strip()
    if not key_id or not key_secret:
        return VerificationResult(False, "Key ID and Key Secret are both required.")
    if not key_id.startswith(("rzp_test_", "rzp_live_")):
        return VerificationResult(
            False,
            "That does not look like a Razorpay Key ID (expected rzp_test_... or rzp_live_...).",
        )

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_V1}/payments",
                params={"count": 1},
                auth=(key_id, key_secret),
            )
    except httpx.TimeoutException:
        return VerificationResult(False, "Razorpay did not respond in time. Try again.")
    except httpx.HTTPError as exc:
        return VerificationResult(False, f"Could not reach Razorpay: {exc}")

    if resp.status_code == 200:
        return VerificationResult(True, "Razorpay credentials verified.")
    if resp.status_code == 401:
        return VerificationResult(
            False, "Razorpay rejected these credentials (401). Check the Key ID and Key Secret."
        )
    body = resp.text[:200]
    return VerificationResult(
        False, f"Razorpay returned {resp.status_code} while verifying: {body}"
    )


def _route_unavailable(body: str) -> bool:
    lowered = body.lower()
    return any(
        token in lowered
        for token in (
            "route feature not enabled",
            "route is not enabled",
            "this transfer is not supported",
            "marketplace feature is not enabled",
            "linked account",
            "accounts feature",
            "the requested url was not found on the server",
        )
    )


def _razorpay_error_description(body: str) -> str:
    """Surface Razorpay's own description; never invent a dashboard diagnosis."""
    try:
        payload = json.loads(body)
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict) and err.get("description"):
            return str(err["description"])
    except Exception:  # noqa: BLE001 — body may not be JSON
        pass
    return body[:300]


async def create_linked_account(
    *,
    email: str,
    legal_business_name: str,
    reference_id: str,
    contact_name: str | None = None,
    phone: str | None = None,
) -> LinkedAccountResult:
    """Create a Razorpay Route linked account for a LOCAH Business.

    Uses the platform key pair. Does not collect merchant API secrets.
    """
    creds = platform_credentials()
    if creds is None:
        return LinkedAccountResult(
            ok=False,
            account_id=None,
            status=None,
            detail=(
                "LOCAH has not configured its Razorpay platform account yet "
                "(RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET). Cash and pay-at-business still work."
            ),
            external_dependency=True,
        )

    payload: dict[str, Any] = {
        "email": email,
        "phone": (phone or "9000000000")[:15],
        "type": "route",
        "reference_id": reference_id[:20],
        "legal_business_name": legal_business_name[:200],
        "business_type": "individual",
        "contact_name": (contact_name or legal_business_name)[:200],
        "profile": {"category": "others", "subcategory": "others"},
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_V2}/accounts",
                json=payload,
                auth=(creds.key_id, creds.key_secret),
            )
    except httpx.TimeoutException:
        return LinkedAccountResult(
            False, None, None, "Razorpay did not respond in time. Try again."
        )
    except httpx.HTTPError as exc:
        return LinkedAccountResult(False, None, None, f"Could not reach Razorpay: {exc}")

    body = resp.text[:800]
    if resp.status_code in {200, 201}:
        data = resp.json()
        account_id = str(data.get("id") or "")
        status = str(data.get("status") or "created")
        if not account_id:
            return LinkedAccountResult(False, None, None, "Razorpay created an account without an id.")
        return LinkedAccountResult(True, account_id, status, "Linked account created.")
    description = _razorpay_error_description(body)
    if resp.status_code in {400, 401, 403, 404} and (
        _route_unavailable(body) or _route_unavailable(description)
    ):
        return LinkedAccountResult(
            ok=False,
            account_id=None,
            status=None,
            detail=(
                f"Razorpay rejected linked-account creation ({resp.status_code}): "
                f"{description}. Cash and pay-at-business still work."
            ),
            external_dependency=True,
        )
    return LinkedAccountResult(
        False,
        None,
        None,
        f"Razorpay returned {resp.status_code} creating a linked account: {description}",
    )


async def create_route_order(
    *,
    amount: Decimal,
    currency: str,
    receipt: str,
    linked_account_id: str,
    notes: dict[str, str] | None = None,
) -> RouteOrderResult:
    """Create a Razorpay order that transfers the business share to a linked account."""
    creds = platform_credentials()
    if creds is None:
        return RouteOrderResult(
            False, None, 0, 0, 0, "Platform Razorpay credentials are not configured."
        )
    fee, business_share = split_amount(amount, creds.fee_bps)
    amount_paise = _to_paise(amount)
    transfer_paise = _to_paise(business_share)
    fee_paise = amount_paise - transfer_paise
    body: dict[str, Any] = {
        "amount": amount_paise,
        "currency": currency,
        "receipt": receipt[:40],
        "payment_capture": 1,
        "notes": notes or {},
        "transfers": [
            {
                "account": linked_account_id,
                "amount": transfer_paise,
                "currency": currency,
                "notes": notes or {},
            }
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_V1}/orders",
                json=body,
                auth=(creds.key_id, creds.key_secret),
            )
    except httpx.TimeoutException:
        return RouteOrderResult(
            False, None, amount_paise, transfer_paise, fee_paise,
            "Razorpay did not respond in time.",
        )
    except httpx.HTTPError as exc:
        return RouteOrderResult(
            False, None, amount_paise, transfer_paise, fee_paise,
            f"Could not reach Razorpay: {exc}",
        )
    if resp.status_code in {200, 201}:
        data = resp.json()
        order_id = str(data.get("id") or "")
        if not order_id:
            return RouteOrderResult(
                False, None, amount_paise, transfer_paise, fee_paise,
                "Razorpay created an order without an id.",
            )
        return RouteOrderResult(True, order_id, amount_paise, transfer_paise, fee_paise, "ok")
    return RouteOrderResult(
        False,
        None,
        amount_paise,
        transfer_paise,
        fee_paise,
        f"Razorpay returned {resp.status_code} creating an order: {_razorpay_error_description(resp.text)}",
    )


@dataclass(frozen=True)
class RefundResult:
    """What Razorpay said to a refund request: accepted with its refund id and
    status ("pending" / "processed"), or refused with the reason."""

    ok: bool
    refund_id: str | None
    status: str
    detail: str


async def create_refund(
    *,
    payment_reference: str,
    amount: Decimal,
    receipt: str,
    notes: dict[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> RefundResult:
    """Refund a captured Route payment from the platform account.

    `reverse_all` takes the business's transferred share back from its linked
    account, so the refund does not come out of the platform's fee balance.
    The outcome arrives later as a `refund.processed` / `refund.failed` webhook.
    """
    creds = platform_credentials()
    if creds is None:
        return RefundResult(False, None, "failed", "Platform Razorpay credentials are not configured.")
    if not payment_reference.startswith("pay_"):
        return RefundResult(False, None, "failed",
                            "This payment has no Razorpay payment id yet, so it cannot be refunded online.")
    body: dict[str, Any] = {
        "amount": _to_paise(amount),
        "speed": "normal",
        "receipt": receipt[:40],
        "notes": notes or {},
        "reverse_all": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport) as client:
            resp = await client.post(
                f"{_V1}/payments/{payment_reference}/refund",
                json=body,
                auth=(creds.key_id, creds.key_secret),
            )
    except httpx.TimeoutException:
        return RefundResult(False, None, "failed", "Razorpay did not respond in time. Try again.")
    except httpx.HTTPError as exc:
        return RefundResult(False, None, "failed", f"Could not reach Razorpay: {exc}")
    if resp.status_code in {200, 201}:
        data = resp.json()
        refund_id = str(data.get("id") or "")
        if not refund_id:
            return RefundResult(False, None, "failed", "Razorpay accepted the refund without an id.")
        return RefundResult(True, refund_id, str(data.get("status") or "pending"), "ok")
    return RefundResult(False, None, "failed",
                        f"Razorpay refused the refund ({resp.status_code}): "
                        f"{_razorpay_error_description(resp.text)}")
