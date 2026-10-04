"""Recommended for your Business — the evidence, the ranking and "Not now".

`catalog.recommendation_evidence.rank` decides; this module gathers what it
decides from, all read-only:

* what the owner said to LOCAH (the interview's evidence-backed suggestions in
  `businesses.metadata.interview.recommended_modules`);
* counts from their own records (items by kind, sizes/options, stock tracking,
  orders, bookings, enquiries, customers, team, locations) — the same kind of
  read-only checks module readiness makes, kept in this one place;
* the operating traits the owner switched on beyond their category's defaults;
* what businesses like theirs run (`catalog.recommendation.recommend`).

It never switches a tool on (Doc 08 §8.4 rule 1): enabling stays the owner's
explicit action through ModuleService. "Not now" is remembered with the
reasons known at the time, so the same suggestion does not come back on the
same evidence.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.catalog.modules import MODULES, is_built
from platform_core.catalog.recommendation import recommend, trigger_reasons, triggered_by_trait
from platform_core.catalog.recommendation_evidence import Signals, rank, record_evidence, trait_evidence
from platform_core.exceptions import ValidationError
from platform_core.models import Business, BusinessModuleDismissal

# What each module's customer surface adds to the website (website/capabilities).
SITE_WORDS = {
    "catalogue": "your items and prices on your website",
    "cart": "a cart on your website", "checkout": "checkout", "my_orders": "orders in the customer's account",
    "track_order": "an order tracking page", "book": "online booking", "my_bookings": "bookings in the "
    "customer's account", "plans": "your plans on your website", "join": "joining online",
    "my_membership": "membership in the customer's account", "enquire": "an enquiry form",
    "request_quote": "quote requests", "reviews": "verified reviews", "queue_status": "a live queue page",
    "loyalty": "a loyalty card", "my_invoices": "bills in the customer's account",
    "request_service": "service requests", "courses": "your courses", "donate": "online giving",
}
# Each count is one read-only query, scoped to the Business.
_COUNTS = {
    "variants": "SELECT count(DISTINCT v.offering_id) FROM offerings_catalog_variants v "
                "JOIN offerings_catalog_offerings o ON o.id = v.offering_id "
                "WHERE o.business_id = CAST(:b AS uuid) AND o.deleted_at IS NULL AND v.deleted_at IS NULL",
    "options": "SELECT count(*) FROM offerings_catalog_offerings WHERE business_id = CAST(:b AS uuid) "
               "AND deleted_at IS NULL AND jsonb_array_length(coalesce(option_groups, '[]'::jsonb)) > 0",
    "tracked": "SELECT count(*) FROM offerings_catalog_offerings WHERE business_id = CAST(:b AS uuid) "
               "AND deleted_at IS NULL AND track_inventory",
    "orders": "SELECT count(*) FROM orders_orders WHERE business_id = CAST(:b AS uuid) AND deleted_at IS NULL",
    "bookings": "SELECT count(*) FROM bookings_bookings WHERE business_id = CAST(:b AS uuid) "
                "AND deleted_at IS NULL",
    "leads": "SELECT count(*) FROM leads_leads WHERE business_id = CAST(:b AS uuid) AND deleted_at IS NULL",
    "customers": "SELECT count(*) FROM customer_relationships_contacts WHERE business_id = CAST(:b AS uuid) "
                 "AND deleted_at IS NULL",
    "team": "SELECT count(*) FROM business_memberships WHERE business_id = CAST(:b AS uuid) "
            "AND status = 'active' AND deleted_at IS NULL",
    "locations": "SELECT count(*) FROM business_locations WHERE business_id = CAST(:b AS uuid) "
                 "AND status = 'active' AND deleted_at IS NULL",
}


async def signals(session: AsyncSession, business_id: uuid.UUID) -> Signals:
    b = {"b": str(business_id)}
    kinds = {row[0]: int(row[1]) for row in (await session.execute(text(
        "SELECT offering_type, count(*) FROM offerings_catalog_offerings WHERE business_id = CAST(:b AS uuid) "
        "AND deleted_at IS NULL AND status IN ('active', 'draft') GROUP BY offering_type"), b)).all()}
    n = {key: int((await session.execute(text(sql), b)).scalar() or 0) for key, sql in _COUNTS.items()}
    return Signals(kinds=kinds, variants=n["variants"] + n["options"], weighed=kinds.get("weighed_product", 0),
                   tracked=n["tracked"], orders=n["orders"], bookings=n["bookings"], leads=n["leads"],
                   customers=n["customers"], team=max(n["team"], 1), locations=max(n["locations"], 1))


async def _dismissed(session: AsyncSession, business_id: uuid.UUID) -> dict[str, list[str]]:
    rows = (await session.execute(select(BusinessModuleDismissal).where(
        BusinessModuleDismissal.business_id == business_id,
        BusinessModuleDismissal.restored_at.is_(None)))).scalars().all()
    return {r.module_id: list(r.evidence_keys or []) for r in rows}


async def _ranked(session: AsyncSession, business: Business) -> tuple[list[Any], dict[str, Any], set[str],
                                                                       dict[str, dict[str, Any]]]:
    from platform_core.services.business_classification import (
        TRAIT_LABELS,
        BusinessClassificationService,
        _subcategory,
        default_traits,
    )
    from platform_core.services.module_readiness import readiness

    traits = await BusinessClassificationService.effective_traits(session, business)
    defaults = default_traits(business)
    found = _subcategory(business)
    rec = recommend(subcategory_key=found[1].key if found else None,
                    playbook=found[1].playbook if found else None, traits=traits, default_traits=defaults)
    # Say why in this Business's terms: a pick that fits how it works says so;
    # one that is only common for its kind names its kind, briefly.
    fits = trigger_reasons(traits)
    kind = found[1].label if found else "yours"
    picks = []
    for pick in rec.as_dict()["modules"]:
        module = str(pick["module"])
        if pick["tier"] == "optional" and module in fits:
            # The family does not list it, but how this Business works switches
            # it on (a café that delivers needs Pickup & delivery even though
            # its family only lists Dispatch): a real fit, not an extra.
            pick = {**pick, "tier": "recommended"}
        if pick["tier"] in ("core", "recommended"):
            if module in fits:
                pick = {**pick, "fit": True, "reason": f"Fits how you work: {fits[module]}."}
            else:
                usual = "usually run" if pick["tier"] == "core" else "often add"
                pick = {**pick, "reason": f"Businesses like yours ({kind}) {usual} this."}
        picks.append(pick)
    interview = ((business.metadata_ or {}).get("interview") or {}).get("recommended_modules") or []
    states = await readiness(session, business.id)
    enabled = {k for k, v in states.items() if v["enabled"]}
    built = {k for k in MODULES if is_built(k)}
    added = traits - defaults
    suggestions, evidence, put_off = rank(
        picks=picks,
        said=interview,
        records=record_evidence(await signals(session, business.id)),
        traits=trait_evidence(added, triggered_by_trait(added), TRAIT_LABELS),
        enabled=enabled,
        built=built,
        dismissed=await _dismissed(session, business.id),
    )
    return suggestions, evidence, put_off, states


def _card(module: str, evidence: list[Any], states: dict[str, dict[str, Any]], resurfaced: bool) -> dict[str, Any]:
    from platform_core.services.workspace_projection import navigation_state

    info = MODULES[module]
    state = states.get(module) or {}
    deps = []
    for dep in info.depends_on:
        dep_state = states.get(dep) or {}
        deps.append({"module": dep, "label": MODULES[dep].label if dep in MODULES else dep,
                     "ready": bool(dep_state.get("ready")), "enabled": bool(dep_state.get("enabled"))})
    # The tool's own setup, then any tool it needs that is off (Enable turns
    # those on with it).
    steps = [s["label"] for s in state.get("steps") or [] if not s.get("done")]
    steps += [f"Turn on {d['label']}" for d in deps if not d["enabled"]]
    unlocks = [SITE_WORDS[s] for s in info.site if s in SITE_WORDS]
    return {
        "module": module,
        "label": info.label,
        "reason": evidence[0].text if evidence else "",
        # Where the first reason comes from, for its label: what the owner said,
        # their records, how they work (their own traits, or a family tool their
        # traits call for), or only what businesses like theirs run.
        "source": ("fit" if evidence and evidence[0].key.endswith(":fit") else
                   evidence[0].kind if evidence else "profile"),
        "evidence": [e.as_dict() for e in evidence[:3]],
        "resurfaced": resurfaced,
        "value": info.does,
        "customer_can": list(info.customer_can),
        "staff_can": list(info.staff_can),
        "unlocks": unlocks,
        "setup": {"steps": steps, "effort": "none" if not steps else "quick" if len(steps) == 1 else "a few steps"},
        "dependencies": deps,
        "included": bool(state.get("entitled", True)),
        "state": navigation_state(state) if state else "not_enabled",
    }


async def for_you(session: AsyncSession, business: Business, *, limit: int | None = None) -> dict[str, Any]:
    """The ranked suggestions for this Business, and the ones it put off."""
    suggestions, evidence, put_off, states = await _ranked(session, business)
    shown = suggestions[:limit] if limit else suggestions
    return {
        "recommended": [_card(s.module, s.evidence, states, s.resurfaced) for s in shown],
        "put_off": [{"module": m, "label": MODULES[m].label} for m in sorted(put_off) if m in MODULES],
        "total": len(suggestions),
    }


async def put_off(session: AsyncSession, business: Business, module: str, *, actor_id: uuid.UUID) -> None:
    """"Not now": remember the tool and the reasons LOCAH had for it today."""
    from platform_core.services.audit import AuditService

    if module not in MODULES:
        raise ValidationError("Unknown tool", details={"field": "module_id"})
    _, evidence, _, _ = await _ranked(session, business)
    keys = sorted({e.key for e in evidence.get(module, [])})
    row = await session.get(BusinessModuleDismissal, (business.id, module))
    if row is None:
        session.add(BusinessModuleDismissal(business_id=business.id, module_id=module, evidence_keys=keys,
                                            dismissed_by=actor_id))
    else:
        row.evidence_keys, row.dismissed_by = keys, actor_id
        row.dismissed_at, row.restored_at = datetime.now(timezone.utc), None
    await session.flush()
    await AuditService.record(session, event_type="module.recommendation.put_off", actor_identity_id=actor_id,
                              actor_context="business", business_id=business.id, resource_type="module",
                              resource_id=None, action="put_off", after_state={"module_id": module,
                                                                               "evidence": keys})


async def bring_back(session: AsyncSession, business: Business, module: str, *, actor_id: uuid.UUID) -> None:
    """The owner wants a put-off suggestion back in the list."""
    from platform_core.services.audit import AuditService

    row = await session.get(BusinessModuleDismissal, (business.id, module))
    if row is None or row.restored_at is not None:
        return
    row.restored_at = datetime.now(timezone.utc)
    await session.flush()
    await AuditService.record(session, event_type="module.recommendation.restored", actor_identity_id=actor_id,
                              actor_context="business", business_id=business.id, resource_type="module",
                              resource_id=None, action="restore", after_state={"module_id": module})
