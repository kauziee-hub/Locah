"""WhatsApp connection states, number registration, WABA webhooks, and calls.

Nothing here reaches Meta: the Cloud API adapter runs against an httpx mock
transport holding it to the request shapes in Meta's current documentation
(checked 2026-09-30; settings in docs/DEPLOYMENT.md), and the
sandbox number stands in for a real one. The Meta app values are fake test
values; the Graph version is deliberately not a real one, to prove it comes
from configuration and nowhere else.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from platform_api.main import app

from platform_core.calling.whatsapp import action_body, call_hours, permission_request_interactive, settings_body
from platform_core.messaging.connection import calling_state, messaging_state
from platform_core.models import MessagingChannel
from platform_testing.phase_b import create_business, new_identity, primary_location, sql

DB = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
client = TestClient(app)
SECRET = "test-app-secret"
VERSION = "v99.0"


def _meta_env(monkeypatch: Any) -> None:
    for k, v in {"META_APP_ID": "test-app-id", "META_APP_SECRET": SECRET, "META_GRAPH_VERSION": VERSION,
                 "META_ES_CONFIG_ID": "test-config", "META_ADVANCED_ACCESS": "1"}.items():
        monkeypatch.setenv(k, v)


def _signed(payload: dict[str, Any]) -> Any:
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/v1/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": sig})


# ------------------------------------------------------------------ states (pure)


def _channel(**kw: Any) -> MessagingChannel:
    base = {"provider": "meta_cloud", "status": "connected", "coexistence": False, "phone_registered_at": None,
            "last_error": None, "quality_rating": "GREEN", "calling_status": "off", "calling_error": None,
            "calling_checked_at": None, "messaging_limit": "TIER_10K", "registration_error": None}
    base.update(kw)
    return MessagingChannel(**base)


def test_the_state_says_what_is_true_and_never_more(monkeypatch: Any) -> None:
    from datetime import datetime, timezone

    monkeypatch.delenv("META_ADVANCED_ACCESS", raising=False)
    monkeypatch.delenv("WHATSAPP_CALLING_RUNTIME", raising=False)
    now = datetime.now(timezone.utc)

    def st(channel: MessagingChannel | None, **kw: Any) -> str:
        args = {"was_disconnected": False, "meta_ready": True, "sandbox_available": False, "approved_utility": 3,
                "awaiting_review": 0, **kw}
        return str(messaging_state(channel=channel, **args)["state"])

    assert st(None, meta_ready=False) == "ACTIVATION_REQUIRED"
    assert st(None) == "META_REVIEW_REQUIRED", "configured but not approved by Meta for other businesses"
    monkeypatch.setenv("META_ADVANCED_ACCESS", "1")
    assert st(None) == "NOT_CONNECTED"
    assert st(None, was_disconnected=True) == "DISCONNECTED"
    assert st(_channel(status="pending")) == "PHONE_VERIFICATION_REQUIRED"
    assert st(_channel(status="pending", coexistence=True)) == "SETUP_REQUIRED"
    registered = _channel(phone_registered_at=now)
    assert st(registered, approved_utility=0, awaiting_review=4) == "TEMPLATE_SETUP_REQUIRED"
    assert st(registered) == "ACTIVE"
    assert st(_channel(phone_registered_at=now, last_error="WhatsApp refused: 131047")) == "DEGRADED"
    assert st(_channel(phone_registered_at=now, quality_rating="RED")) == "DEGRADED"
    sandbox = messaging_state(channel=_channel(provider="sandbox", phone_registered_at=now), was_disconnected=False,
                              meta_ready=False, sandbox_available=True, approved_utility=3, awaiting_review=0)
    assert (sandbox["state"], sandbox["environment"], sandbox["label"]) == ("ACTIVE", "sandbox", "TEST / SANDBOX")

    active = {"state": "ACTIVE"}
    assert calling_state(None, {"state": "NOT_CONNECTED"})["state"] == "CALLING_NOT_AVAILABLE"
    assert calling_state(registered, active)["state"] == "CALLING_ACTIVATION_REQUIRED", "no runtime, no answering"
    monkeypatch.setenv("WHATSAPP_CALLING_RUNTIME", "fixture")
    assert calling_state(_channel(messaging_limit="TIER_1K"), active)["state"] == "CALLING_NOT_AVAILABLE"
    assert calling_state(registered, active)["state"] == "CALLING_ELIGIBLE"
    assert calling_state(_channel(calling_status="enabled"), active)["state"] == "CALLING_SETUP_REQUIRED"
    assert calling_state(_channel(calling_status="enabled", calling_checked_at=now), active)["state"] == \
        "CALLING_ACTIVE"
    assert calling_state(_channel(calling_status="enabled", calling_checked_at=now, calling_error="x"),
                         active)["state"] == "CALLING_DEGRADED"


def test_calling_requests_follow_metas_documented_shapes() -> None:
    hours = call_hours({"mon": [["09:00", "13:00"], ["14:00", "18:00"], ["19:00", "20:00"]], "sun": []},
                       "Asia/Kolkata")
    assert hours == {"status": "ENABLED", "timezone_id": "Asia/Kolkata", "weekly_operating_hours": [
        {"day_of_week": "MONDAY", "open_time": "0900", "close_time": "1300"},
        {"day_of_week": "MONDAY", "open_time": "1400", "close_time": "1800"}]}, "at most two spans a day"
    assert settings_body(True, hours) == {"calling": {"status": "ENABLED", "call_icon_visibility": "DEFAULT",
                                                      "callback_permission_status": "ENABLED", "call_hours": hours}}
    assert settings_body(False, hours) == {"calling": {"status": "DISABLED"}}
    assert action_body("wacid.1", "reject") == {"messaging_product": "whatsapp", "call_id": "wacid.1",
                                                "action": "reject"}
    assert action_body("wacid.1", "accept", "v=0...")["session"] == {"sdp_type": "answer", "sdp": "v=0..."}
    with pytest.raises(ValueError):
        action_body("wacid.1", "accept")  # no answering without a media runtime's SDP
    assert permission_request_interactive("May we call you about your order?") == {
        "type": "call_permission_request", "action": {"name": "call_permission_request"},
        "body": {"text": "May we call you about your order?"}}


# ------------------------------------------------------------------ Embedded Signup → registration


class _Meta:
    """A stand-in for graph.facebook.com that records every request."""

    def __init__(self, *, pin_ok: str = "246810") -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.pin_ok = pin_ok

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        self.calls.append((request.method, request.url.path, body))
        path = request.url.path
        assert path.startswith(f"/{VERSION}/"), "the Graph version comes from META_GRAPH_VERSION"
        if path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "business-token"})
        if path.endswith("/subscribed_apps"):
            return httpx.Response(200, json={"success": True})
        if path.endswith("/register"):
            if body["pin"] != self.pin_ok:
                return httpx.Response(400, json={"error": {"message": "Two-step verification PIN mismatch"}})
            return httpx.Response(200, json={"success": True})
        if path.endswith("/message_templates"):
            return httpx.Response(200, json={"id": f"tpl-{body['name']}-{body['language']}", "status": "PENDING",
                                             "category": body["category"]})
        if request.method == "GET":
            return httpx.Response(200, json={"display_phone_number": "+91 98400 00123", "verified_name": "Glow",
                                             "quality_rating": "GREEN", "messaging_limit_tier": "TIER_10K"})
        return httpx.Response(404, json={"error": {"message": "unexpected"}})


def _mock_graph(monkeypatch: Any, meta: _Meta) -> None:
    real = httpx.AsyncClient

    def client_with_mock(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(meta)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_with_mock)


@DB
def test_a_signed_up_number_is_registered_before_it_is_called_connected(monkeypatch: Any) -> None:
    import uuid

    _meta_env(monkeypatch)
    meta = _Meta()
    waba, pn = f"waba-{uuid.uuid4().hex[:10]}", f"pn-{uuid.uuid4().hex[:10]}"
    _mock_graph(monkeypatch, meta)
    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, modules=("customer-relationships", "messaging"))
    base = f"/v1/platform/businesses/{bid}/messaging"
    assert client.get(f"{base}/setup", headers=owner).json()["data"]["connection"]["messaging"]["state"] == \
        "NOT_CONNECTED"

    signup = client.post(f"{base}/channel/embedded-signup", json={
        "code": "code-from-browser", "waba_id": waba, "phone_number_id": pn}, headers=owner)
    assert signup.status_code == 200, signup.text
    assert signup.json()["data"]["status"] == "pending" and signup.json()["data"]["phone_registered_at"] is None
    conn = client.get(f"{base}/setup", headers=owner).json()["data"]["connection"]
    assert conn["messaging"]["state"] == "PHONE_VERIFICATION_REQUIRED"
    assert [p for m, p, _ in meta.calls] == [f"/{VERSION}/oauth/access_token", f"/{VERSION}/{waba}/subscribed_apps",
                                             f"/{VERSION}/{pn}"], "code exchanged, webhooks subscribed, number read"
    assert sql("select encrypted_token is not null and encrypted_token <> 'business-token' from messaging_channels "
               "where business_id = :b", b=bid) == [(True,)], "the token is stored encrypted, never in the clear"

    wrong = client.post(f"{base}/channel/register", json={"pin": "111111"}, headers=owner)
    assert wrong.status_code == 200
    assert wrong.json()["data"]["connection"]["messaging"]["state"] == "PHONE_VERIFICATION_REQUIRED"
    assert "PIN mismatch" in wrong.json()["data"]["connection"]["messaging"]["reason"]
    assert client.post(f"{base}/channel/register", json={"pin": "12ab56"}, headers=owner).status_code == 422
    right = client.post(f"{base}/channel/register", json={"pin": "246810"}, headers=owner)
    data = right.json()["data"]
    assert data["channel"]["status"] == "connected" and data["channel"]["phone_registered_at"]
    assert ("POST", f"/{VERSION}/{pn}/register", {"messaging_product": "whatsapp", "pin": "246810"}) in meta.calls
    assert data["connection"]["messaging"]["state"] == "TEMPLATE_SETUP_REQUIRED", "templates wait for Meta's review"
    [otp] = [b for m, p, b in meta.calls if p.endswith("/message_templates") and b["name"] == "quote_acceptance_code"
             and b["language"] == "en"]
    assert otp["category"] == "AUTHENTICATION" and otp["components"] == [
        {"type": "BODY", "add_security_recommendation": True},
        {"type": "FOOTER", "code_expiration_minutes": 10},
        {"type": "BUTTONS", "buttons": [{"type": "OTP", "otp_type": "COPY_CODE", "text": "Copy code"}]}], \
        "one-time codes go in Meta's preset authentication format, never custom text"
    assert data["connection"]["templates"]["awaiting_review"] > 0
    assert sql("select count(*) from platform_audit_events where business_id = :b and "
               "cast(after_state as text) like '%246810%'", b=bid) == [(0,)], "the PIN is never recorded"

    # Meta approves the booking reminder (utility) - by WABA, not by number.
    approved = _signed({"object": "whatsapp_business_account", "entry": [{"id": waba, "changes": [{
        "field": "message_template_status_update", "value": {
            "event": "APPROVED", "message_template_id": 1, "message_template_name": "booking_reminder",
            "message_template_language": "en", "reason": "NONE", "message_template_category": "UTILITY"}}]}]})
    assert approved.status_code == 200 and approved.json()["data"]["templates"] == 1, approved.text
    rejected = _signed({"object": "whatsapp_business_account", "entry": [{"id": waba, "changes": [{
        "field": "message_template_status_update", "value": {
            "event": "REJECTED", "message_template_name": "order_confirmed", "message_template_language": "hi",
            "reason": "INCORRECT_CATEGORY"}}]}]})
    assert rejected.json()["data"]["templates"] == 1
    assert sql("select status, rejected_reason from messaging_templates where business_id = :b and "
               "template_key = 'order_confirmed' and language = 'hi'", b=bid) == [("rejected", "INCORRECT_CATEGORY")]
    conn = client.get(f"{base}/setup", headers=owner).json()["data"]["connection"]
    assert conn["messaging"]["state"] == "ACTIVE" and conn["last_webhook_at"]
    assert conn["calling"]["state"] == "CALLING_ACTIVATION_REQUIRED"
    assert conn["telephony"]["state"] == "ACTIVATION_REQUIRED"

    flagged = _signed({"object": "whatsapp_business_account", "entry": [{"id": waba, "changes": [{
        "field": "phone_number_quality_update", "value": {"display_phone_number": "919840000123",
                                                          "event": "FLAGGED", "current_limit": "TIER_1K"}}]}]})
    assert flagged.json()["data"]["account"] == 1
    conn = client.get(f"{base}/setup", headers=owner).json()["data"]["connection"]
    assert conn["messaging"]["state"] == "DEGRADED"
    assert _signed({"object": "whatsapp_business_account", "entry": [{"id": "waba-other", "changes": [{
        "field": "message_template_status_update", "value": {"event": "APPROVED", "message_template_name":
                                                             "order_confirmed", "message_template_language": "hi"}}]}]}
                   ).json()["data"]["templates"] == 0, "another account's events touch nothing here"


# ------------------------------------------------------------------ calls (sandbox number)


def _sandbox_shop(monkeypatch: Any) -> tuple[dict[str, str], str, str]:
    monkeypatch.setenv("MESSAGING_SANDBOX", "1")
    monkeypatch.delenv("WHATSAPP_CALLING_RUNTIME", raising=False)
    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner, modules=("customer-relationships", "messaging"))
    base = f"/v1/platform/businesses/{bid}/messaging"
    assert client.post(f"{base}/channel/sandbox", json={"display_phone": "+919840000131", "display_name": "Glow"},
                       headers=owner).status_code == 200
    return owner, bid, base


@DB
def test_a_whatsapp_call_is_recorded_and_never_pretended_answered(monkeypatch: Any) -> None:
    owner, bid, base = _sandbox_shop(monkeypatch)
    conn = client.get(f"{base}/calling", headers=owner).json()["data"]["connection"]
    assert conn["messaging"]["label"] == "TEST / SANDBOX" and conn["calling"]["state"] == "CALLING_ACTIVATION_REQUIRED"
    refused = client.post(f"{base}/calling", json={"enabled": True}, headers=owner)
    assert refused.status_code == 409 and refused.json()["error"]["details"]["code"] == "calling_unavailable"

    ring = client.post(f"{base}/sandbox/call", json={"from_phone": "+919876500131", "name": "Anu"}, headers=owner)
    assert ring.status_code == 200 and ring.json()["data"]["calls"] == 1, ring.text
    call_id = ring.json()["data"]["call_id"]
    again = client.post(f"{base}/sandbox/call", json={"from_phone": "+919876500131", "call_id": call_id},
                        headers=owner)
    assert again.json()["data"]["calls"] == 0, "the same ring twice is one call"
    end = client.post(f"{base}/sandbox/call", json={"from_phone": "+919876500131", "call_id": call_id,
                                                     "event": "terminate", "duration": 0}, headers=owner)
    assert end.json()["data"]["calls"] == 1
    [call] = client.get(f"{base}/calling", headers=owner).json()["data"]["calls"]
    assert (call["channel"], call["direction"], call["state"], call["handled_by_type"]) == \
        ("whatsapp_call", "inbound", "missed", "none")
    assert "cannot answer" in call["note"] or "call the customer back" in call["note"]
    cols = {r[0] for r in sql("select column_name from information_schema.columns where table_name = 'calls_sessions'")}
    assert not cols & {"sdp", "session", "token", "media"}, "no media or secrets in the call record"


@DB
def test_a_business_calls_only_customers_who_allowed_it(monkeypatch: Any) -> None:
    from platform_core.calling.service import CallService
    from platform_core.exceptions import ConflictError
    from platform_testing.phase_b import db_url
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    import asyncio
    import uuid

    owner, bid, base = _sandbox_shop(monkeypatch)
    monkeypatch.setenv("WHATSAPP_CALLING_RUNTIME", "fixture")
    loc = primary_location(client, owner, bid)
    client.patch(f"/v1/platform/businesses/{bid}/locations/{loc}", json={"hours": {"mon": [["09:00", "18:00"]]}},
                 headers=owner)
    assert client.get(f"{base}/calling", headers=owner).json()["data"]["connection"]["calling"]["state"] == \
        "CALLING_ELIGIBLE"
    on = client.post(f"{base}/calling", json={"enabled": True}, headers=owner)
    assert on.status_code == 200 and on.json()["data"]["calling"]["state"] == "CALLING_ACTIVE", on.text

    async def may_call(wa_id: str) -> str:
        engine = create_async_engine(db_url(), poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, class_=AsyncSession)() as session:
                try:
                    await CallService.assert_may_call(session, uuid.UUID(bid), wa_id)
                    return "ok"
                except ConflictError as exc:
                    return str(exc.detail["details"]["code"])
        finally:
            await engine.dispose()

    assert asyncio.run(may_call("919876500141")) == "call_permission_required", "never unsolicited"
    # Calling in grants a temporary permission to call back.
    client.post(f"{base}/sandbox/call", json={"from_phone": "+919876500141", "name": "Ravi"}, headers=owner)
    assert asyncio.run(may_call("919876500141")) == "ok"
    [(status, permanent, source)] = sql("select status, is_permanent, source from calls_permissions "
                                         "where business_id = :b and wa_id = '919876500141'", b=bid)
    assert (status, permanent, source) == ("granted", False, "customer_called")

    # Asking: only inside the 24-hour window, and within Meta's limits.
    r = client.post(f"{base}/sandbox/inbound", json={"from_phone": "919876500142", "name": "Meena",
                                                     "text": "Can someone call me?"}, headers=owner)
    assert r.status_code == 200
    [(conv_id,)] = sql("select id::text from messaging_conversations where business_id = :b and wa_id = '919876500142'",
                       b=bid)
    ask = client.post(f"{base}/conversations/{conv_id}/call-permission",
                      json={"reason": "We would like to call you about your enquiry."}, headers=owner)
    assert ask.status_code == 200 and ask.json()["data"]["status"] == "requested", ask.text
    [(kind, payload)] = sql("select kind, payload from messaging_messages where conversation_id = :c and "
                            "direction = 'out' and kind = 'interactive'", c=conv_id)
    payload = json.loads(payload) if isinstance(payload, str) else payload
    assert kind == "interactive" and payload["interactive"]["type"] == "call_permission_request"
    twice = client.post(f"{base}/conversations/{conv_id}/call-permission",
                        json={"reason": "May we call you now?"}, headers=owner)
    assert twice.status_code == 409 and twice.json()["error"]["details"]["code"] == "request_limit"
    assert asyncio.run(may_call("919876500142")) == "call_permission_required", "asked is not allowed"

    # Meena says yes, permanently (Meta's call_permission_reply).
    monkeypatch.setenv("META_APP_SECRET", SECRET)
    [(pid,)] = sql("select phone_number_id from messaging_channels where business_id = :b and status = 'connected'",
                   b=bid)
    reply = _signed({"object": "whatsapp_business_account", "entry": [{"id": "sandbox", "changes": [{
        "field": "messages", "value": {"messaging_product": "whatsapp",
                                       "metadata": {"phone_number_id": pid, "display_phone_number": "919840000131"},
                                       "contacts": [{"profile": {"name": "Meena"}, "wa_id": "919876500142"}],
                                       "messages": [{"from": "919876500142", "id": f"wamid.perm.{uuid.uuid4().hex}",
                                                     "timestamp": str(int(time.time())), "type": "interactive",
                                                     "interactive": {"type": "call_permission_reply",
                                                                     "call_permission_reply": {
                                                                         "response": "accept", "is_permanent": True,
                                                                         "response_source": "user_action"}}}]}}]}]})
    assert reply.status_code == 200, reply.text
    assert asyncio.run(may_call("919876500142")) == "ok"
    assert sql("select status, is_permanent from calls_permissions where business_id = :b and wa_id = '919876500142'",
               b=bid) == [("granted", True)]


def test_a_one_time_code_is_sent_in_the_body_and_behind_the_copy_button(monkeypatch: Any) -> None:
    import asyncio

    from platform_core.messaging.provider import MetaCloudProvider

    _meta_env(monkeypatch)
    seen: list[dict[str, Any]] = []

    def graph(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.otp"}]})

    _mock_graph(monkeypatch, graph)  # type: ignore[arg-type]
    sent = asyncio.run(MetaCloudProvider().send_template("tok", "pn-1", "919876500001", "quote_acceptance_code",
                                                         "en", ["482915"]))
    assert sent.provider_message_id == "wamid.otp"
    assert seen[0]["template"]["components"] == [
        {"type": "body", "parameters": [{"type": "text", "text": "482915"}]},
        {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": "482915"}]}]
