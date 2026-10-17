"""Premium site lab: real businesses' sites, pictured by the real photo pipeline.

Each lab business is a scripted persona interview, enriched the way a full
interview would leave it (story, priced catalogue, owner claims), composed by
the real composer with governed copy — and, in `photos` mode, pictured by the
real pipeline: PhotoBrief → model-written searches → Unsplash + Pixabay pool →
filters → vision judge → choice (website.image_retrieval). The picks, their
credits and the full selection audit are saved, so re-rendering costs no API
call. Pixabay picks are copied to apps/web/public/site-lab-photos/ (Pixabay
does not allow permanent hotlinking); Unsplash picks are hotlinked and their
download is tracked, as Unsplash's API guidelines require.

  uv run python -m platform_testing.premium_lab slots [keys]     # compose; list the photo slots (no API)
  uv run --env-file .env python -m platform_testing.premium_lab photos [keys]
                                                                 # REAL calls: Unsplash, Pixabay, the AI provider
  uv run python -m platform_testing.premium_lab write [keys]     # lab files from saved picks (no API)

Then `tools/site-lab/serve.sh` and open http://localhost:3005/site-lab/<key>.
Keys: lab-cleaver, lab-selvam, lab-ishant, lab-saffron, lab-grit, lab-crumb.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from platform_core.interview.capabilities import resolve_recommendations
from platform_core.interview.creative_director import direct
from platform_core.interview.distinctness import signature
from platform_core.interview.media_director import plan_media, plan_slots, record
from platform_core.interview.models import CatalogueItem, Message, OwnerClaim, TargetState
from platform_core.interview.site_composer import compose_site
from platform_core.interview.website_copy import NamedLine, PillarCopy, WebsiteCopy, govern_copy
from platform_testing.interview_eval import every_module_entitled, run_persona
from platform_testing.website_fixtures import FIXTURE_PERSONAS, SiteFixture, contact_for, write_lab

ROOT = Path(__file__).resolve().parents[3]
LAB_DIR = ROOT / ".site-lab"
PHOTO_DIR = ROOT / "apps/web/public/site-lab-photos"
PICKS = LAB_DIR / "photo-picks.json"
REPORT = LAB_DIR / "photo-report.json"


def items(*rows: tuple[str, str, str, str]) -> list[CatalogueItem]:
    return [CatalogueItem(name=n, price=p, unit=u, description=d) for n, p, u, d in rows]


LAB: dict[str, dict[str, Any]] = {
    "lab-cleaver": {
        "persona": "premium-butcher", "concept": "quiet_luxury",
        "said": [
            "Our mutton is dry-aged for seven days in our own cold room, so it is tender and full of flavour.",
            "Every steak is hand-cut to the thickness you ask for.",
            "Our chicken is free-range, from one farm in Chengalpattu.",
            "We started The Cleaver Room for home chefs who care where their meat comes from.",
            "Mutton leg is 1450 a kg, chops 1250, the shoulder 1300. Free-range whole chicken 520 a kg, "
            "breast 480. Tenderloin steak 1800 a kg, ribeye 1650, striploin 1550.",
            "Delivery is same day across central Chennai if you order before 2 pm.",
        ],
        "story": "We started The Cleaver Room for home chefs who care where their meat comes from.",
        "catalogue": {
            "Mutton": items(("Dry-aged mutton leg", "₹1,450", "per kg", "Aged seven days in our cold room"),
                            ("Mutton chops", "₹1,250", "per kg", "Hand-cut to your thickness"),
                            ("Mutton shoulder", "₹1,300", "per kg", "")),
            "Chicken": items(("Free-range whole chicken", "₹520", "per kg", "From one farm in Chengalpattu"),
                             ("Chicken breast", "₹480", "per kg", "")),
            "Steaks": items(("Tenderloin steak", "₹1,800", "per kg", "Hand-cut to the thickness you ask for"),
                            ("Ribeye", "₹1,650", "per kg", ""), ("Striploin", "₹1,550", "per kg", "")),
        },
        "copy": dict(
            headline="Meat for home chefs who care where it comes from", headline_accent="care",
            subheadline="Dry-aged mutton, free-range chicken and hand-cut steaks, delivered the same day across central Chennai.",
            statement="Every steak is hand-cut to the thickness you ask for, and our mutton is dry-aged for seven days in our own cold room.",
            statement_highlight="dry-aged for seven days",
            pillars_title="How we keep it", about_title="Why The Cleaver Room",
            about_body="We started The Cleaver Room for home chefs who care where their meat comes from. Our mutton is dry-aged for seven days in our own cold room, so it is tender and full of flavour. Our chicken is free-range, from one farm in Chengalpattu.",
            pillars=[PillarCopy(title="Dry-aged seven days", body="In our own cold room, so it is tender and full of flavour.",
                                quote="Our mutton is dry-aged for seven days in our own cold room, so it is tender and full of flavour."),
                     PillarCopy(title="Hand-cut to order", body="Every steak cut to the thickness you ask for.",
                                quote="Every steak is hand-cut to the thickness you ask for."),
                     PillarCopy(title="One free-range farm", body="Our chicken comes from one farm in Chengalpattu.",
                                quote="Our chicken is free-range, from one farm in Chengalpattu."),
                     PillarCopy(title="Same-day delivery", body="Across central Chennai if you order before 2 pm.",
                                quote="Delivery is same day across central Chennai if you order before 2 pm.")],
            catalogue_intro="Dry-aged mutton, free-range chicken and hand-cut steaks — priced by the kg.",
            offerings_subtitle="Every steak is hand-cut to the thickness you ask for; delivery is same day across central Chennai.",
            category_lines=[NamedLine(name="Mutton", line="Dry-aged for seven days in our own cold room."),
                            NamedLine(name="Chicken", line="Free-range, from one farm in Chengalpattu."),
                            NamedLine(name="Steaks", line="Hand-cut to the thickness you ask for.")],
            closing_headline="Order before 2 pm. Cook tonight.",
        ),
    },
    "lab-selvam": {
        "persona": "family-butcher", "concept": "warm_craft",
        "said": [
            "My father started this stall in 1987 and we still cut every order by hand.",
            "Our goats come from farms near Kanchipuram, fresh every morning.",
            "Goat mutton curry cut is 800 a kg, boneless 950, liver 600. Chicken curry cut 240, whole chicken 220. "
            "Country eggs 10 each, a tray of 30 is 270.",
            "Call us and we will keep your order aside, ready when you come.",
            "Open 6 am to 1 pm every day except Monday.",
        ],
        "story": "My father started this stall in 1987 and we still cut every order by hand.",
        "catalogue": {
            "Mutton": items(("Goat mutton curry cut", "₹800", "per kg", "Cut by hand to order"),
                            ("Boneless mutton", "₹950", "per kg", ""), ("Mutton liver", "₹600", "per kg", "")),
            "Chicken": items(("Chicken curry cut", "₹240", "per kg", ""), ("Whole chicken", "₹220", "per kg", "")),
            "Eggs": items(("Country eggs", "₹10", "each", ""), ("Tray of 30 eggs", "₹270", "", "")),
        },
        "copy": dict(
            headline="Saidapet's mutton stall, since 1987", headline_accent="since 1987",
            subheadline="Goat mutton, chicken and country eggs — cut fresh by hand, every morning.",
            statement="My father started this stall in 1987 and we still cut every order by hand.",
            statement_highlight="by hand",
            pillars_title="The way we have always done it",
            pillars=[PillarCopy(title="Cut by hand", body="Every order, the way my father did.",
                                quote="My father started this stall in 1987 and we still cut every order by hand."),
                     PillarCopy(title="Goats from Kanchipuram", body="From farms near Kanchipuram, fresh every morning.",
                                quote="Our goats come from farms near Kanchipuram, fresh every morning."),
                     PillarCopy(title="Kept aside for you", body="Call us and your order is ready when you come.",
                                quote="Call us and we will keep your order aside, ready when you come.")],
            catalogue_intro="Fresh every morning, priced by the kg.",
            offerings_subtitle="Call us and we will keep your order aside, ready when you come.",
            category_lines=[NamedLine(name="Mutton", line="Goats from farms near Kanchipuram, cut by hand."),
                            NamedLine(name="Chicken", line="Curry cut or whole, fresh every morning."),
                            NamedLine(name="Eggs", line="Country eggs, by the piece or by the tray.")],
            closing_headline="Call us. We'll keep it aside.",
        ),
    },
    "lab-ishant": {
        "persona": "meat-shop", "concept": "noir_editorial",
        "said": [
            "Chicken curry cut is 260 a kg, boneless 380, wings 220. Mutton curry cut 850, chops 900. "
            "Seer fish 900 a kg, pomfret 700, prawns 550, crab 450, squid 400.",
            "Everything is cleaned and cut only after you order, never kept pre-cut.",
            "Fish comes from Kasimedu harbour every morning.",
            "We cut it to your kg exactly, no extra bones.",
        ],
        "story": "Everything is cleaned and cut only after you order, never kept pre-cut.",
        "copy": dict(
            headline="Cut only after you order", headline_accent="after you order",
            subheadline="Chicken, mutton and fish from Kasimedu harbour — pick your kg on WhatsApp, we deliver around Nookampalayam and Perumbakkam.",
            statement="Everything is cleaned and cut only after you order, never kept pre-cut.",
            statement_highlight="never kept pre-cut",
            pillars_title="Why it tastes fresher",
            pillars=[PillarCopy(title="Cut after you order", body="Never kept pre-cut.",
                                quote="Everything is cleaned and cut only after you order, never kept pre-cut."),
                     PillarCopy(title="Kasimedu every morning", body="Fish comes from Kasimedu harbour every morning.",
                                quote="Fish comes from Kasimedu harbour every morning."),
                     PillarCopy(title="Your kg exactly", body="No extra bones.",
                                quote="We cut it to your kg exactly, no extra bones.")],
            offerings_subtitle="Pick the meat and the kg on WhatsApp; we deliver around Nookampalayam and Perumbakkam.",
            category_lines=[NamedLine(name="Chicken", line="Curry cut, boneless and wings, cut after you order."),
                            NamedLine(name="Mutton", line="Curry cut and chops, cut to your kg exactly."),
                            NamedLine(name="Fish & Seafood", line="From Kasimedu harbour every morning.")],
            closing_headline="Pick your kg. We'll do the rest.",
        ),
    },
    "lab-saffron": {
        "persona": "restaurant", "concept": "warm_craft",
        "said": [
            "Chettinad chicken is 320, chicken 65 is 280, mutton chukka 380. Ghee roast dosa 140, podi dosa 120, "
            "masala dosa 110. Full meals 220 for lunch, with sambar, rasam, kootu and payasam.",
            "We grind our Chettinad masala fresh every morning on a stone.",
            "Lunch is 12 to 3:30, dinner 7 to 11.",
            "The full meals is served on a banana leaf.",
        ],
        "story": "Our recipes are from my grandmother's Karaikudi kitchen.",
        "catalogue": {
            "Chettinad chicken": items(("Chettinad chicken", "₹320", "", "Masala ground fresh on a stone"),
                                       ("Chicken 65", "₹280", "", ""), ("Mutton chukka", "₹380", "", "")),
            "Dosas": items(("Ghee roast dosa", "₹140", "", ""), ("Podi dosa", "₹120", "", ""),
                           ("Masala dosa", "₹110", "", "")),
            "Full meals": items(("Full meals", "₹220", "", "Sambar, rasam, kootu and payasam on a banana leaf")),
        },
        "copy": dict(
            headline="Karaikudi recipes in Anna Nagar", headline_accent="Karaikudi",
            subheadline="Chettinad chicken, dosas and full meals on a banana leaf — from my grandmother's kitchen.",
            statement="Our recipes are from my grandmother's Karaikudi kitchen, and we grind our Chettinad masala fresh every morning on a stone.",
            statement_highlight="on a stone",
            pillars_title="From her kitchen to yours",
            pillars=[PillarCopy(title="Grandmother's recipes", body="From her Karaikudi kitchen.",
                                quote="Our recipes are from my grandmother's Karaikudi kitchen."),
                     PillarCopy(title="Stone-ground masala", body="Ground fresh every morning on a stone.",
                                quote="We grind our Chettinad masala fresh every morning on a stone."),
                     PillarCopy(title="On a banana leaf", body="The full meals, served the old way.",
                                quote="The full meals is served on a banana leaf.")],
            about_title="My grandmother's kitchen",
            about_body="Our recipes are from my grandmother's Karaikudi kitchen. We grind our Chettinad masala fresh every morning on a stone, and the full meals is served on a banana leaf.",
            offerings_subtitle="Chettinad chicken, dosas and full meals on a banana leaf.",
            category_lines=[NamedLine(name="Chettinad chicken", line="Masala ground fresh every morning on a stone."),
                            NamedLine(name="Dosas", line="Ghee roast, podi and masala."),
                            NamedLine(name="Full meals", line="Sambar, rasam, kootu and payasam on a banana leaf.")],
            closing_headline="Book a table for the weekend.",
        ),
    },
    "lab-grit": {
        "persona": "gym", "concept": "kinetic_sport",
        "said": [
            "Our coaches are national-level powerlifters.",
            "Every member gets a written programme, not random workouts.",
            "We have competition barbells and calibrated plates.",
            "Open 5 am to 10 pm, Sunday till 1 pm.",
        ],
        "story": "Every member gets a written programme, not random workouts.",
        "copy": dict(
            headline="Strength, written down", headline_accent="written down",
            subheadline="Powerlifting, strength classes and personal training in Velachery — coached by national-level powerlifters.",
            statement="Every member gets a written programme, not random workouts.",
            statement_highlight="written programme",
            pillars_title="Built for lifters",
            pillars=[PillarCopy(title="National-level coaches", body="Our coaches are national-level powerlifters.",
                                quote="Our coaches are national-level powerlifters."),
                     PillarCopy(title="A written programme", body="Not random workouts.",
                                quote="Every member gets a written programme, not random workouts."),
                     PillarCopy(title="Competition kit", body="Competition barbells and calibrated plates.",
                                quote="We have competition barbells and calibrated plates.")],
            closing_headline="Your first session is free.",
        ),
    },
}

# lab-ishant's catalogue as the owner priced it (the persona's own items).
ISHANT_PRICES = {"Curry cut": ("₹260", "per kg"), "Boneless": ("₹380", "per kg"), "Wings": ("₹220", "per kg"),
                 "Chops": ("₹900", "per kg"), "Seer fish": ("₹900", "per kg"), "Pomfret": ("₹700", "per kg"),
                 "Prawns": ("₹550", "per kg"), "Crab": ("₹450", "per kg"), "Squid": ("₹400", "per kg")}

LAB["lab-crumb"] = {
    "persona": "bakery", "concept": "warm_craft",
    "said": [
        "Everything is baked fresh every morning, eggless options too.",
        "Our milk bread comes out of the oven at seven every morning.",
        "Puffs are made with butter pastry we roll by hand.",
        "Custom cakes for birthdays with name and photo, order two days before.",
    ],
    "story": "Everything is baked fresh every morning in our Adyar shop.",
    "catalogue": {
        "Breads": items(("Milk bread", "₹45", "", "Out of the oven at seven every morning"),
                        ("Brown bread", "₹55", "", "")),
        "Puffs": items(("Veg puff", "₹25", "", "Butter pastry rolled by hand"), ("Egg puff", "₹30", "", "")),
        "Cookies": items(("Butter cookies", "₹120", "250 g", "")),
        "Custom cakes": items(("Custom birthday cake", "₹650", "per kg", "Name and photo, order two days before")),
    },
    "copy": dict(
        headline="Baked in Adyar before you wake", headline_accent="before you wake",
        subheadline="Milk bread, butter puffs, cookies and custom cakes — baked fresh every morning, eggless options too.",
        statement="Everything is baked fresh every morning, and our milk bread comes out of the oven at seven.",
        statement_highlight="fresh every morning",
        pillars_title="How we bake",
        pillars=[PillarCopy(title="Fresh every morning", body="Nothing is kept from yesterday.",
                            quote="Everything is baked fresh every morning, eggless options too."),
                 PillarCopy(title="Hand-rolled pastry", body="Butter pastry for every puff.",
                            quote="Puffs are made with butter pastry we roll by hand."),
                 PillarCopy(title="Cakes with your name", body="Order two days before.",
                            quote="Custom cakes for birthdays with name and photo, order two days before.")],
        catalogue_intro="Breads, puffs, cookies and custom cakes — fresh every morning.",
        offerings_subtitle="Walk in for bread and puffs; order cakes on WhatsApp two days before.",
        category_lines=[NamedLine(name="Breads", line="Milk bread out of the oven at seven."),
                        NamedLine(name="Puffs", line="Butter pastry, rolled by hand."),
                        NamedLine(name="Cookies", line="Butter cookies by the 250 g."),
                        NamedLine(name="Custom cakes", line="Name and photo, two days' notice.")],
        closing_headline="Order your cake two days before.",
    ),
}



async def build(key: str, pictured: set[str] | None = None) -> dict[str, Any]:
    """Compose one lab business; returns its fixture, payload, slots, Blueprint and direction.

    `pictured`: the slot keys that really have a photograph. As in a real build, a slot
    that found none is not placed at all (no placeholder), so the page is composed
    the way it would be without it."""
    spec = LAB[key]
    persona = next(p for p in FIXTURE_PERSONAS if p.key == spec["persona"])
    run = await run_persona(persona, "model")
    bp = run.bp
    bp.business_id = uuid.uuid5(uuid.NAMESPACE_URL, f"locah-lab/{key}")
    for text in spec["said"]:
        bp.messages.append(Message(role="user", text=text))
    if spec.get("story"):
        bp.discovery["brand.story"] = TargetState(status="answered", quote=spec["story"], summary=spec["story"][:200])
    for name, rows in (spec.get("catalogue") or {}).items():
        group = next((g for g in bp.taxonomy.groups if g.name.casefold() == name.casefold()), None)
        if group is not None:
            group.items = rows
    if key == "lab-ishant":
        for g in bp.taxonomy.groups:
            for it in g.items:
                if g.name == "Mutton" and it.name == "Curry cut":
                    it.price, it.unit = "₹850", "per kg"
                elif it.name in ISHANT_PRICES:
                    it.price, it.unit = ISHANT_PRICES[it.name]
            g.items = [it for it in g.items if it.name != "Fish"]
    bp.website_draft.owner_claims = [OwnerClaim(claim=s, quote=s) for s in spec["said"][1:3]]
    resolve_recommendations(bp, every_module_entitled(), persona.business_type)
    active = frozenset(m.module_id for m in bp.recommended_modules if m.strength == "strong")
    direction = direct(bp, persona.business_type, media_expected=True)
    direction.model_choices = {**(direction.model_choices or {}), "concept": spec["concept"]}
    plan_media(bp, direction)
    slots = [s for s in plan_slots(bp, direction) if s.truth_class != "factual"]
    for slot in slots:
        if pictured is None or slot.key in pictured:
            record(bp, slot, uuid.uuid5(bp.business_id, slot.key), stock=True)
        else:
            record(bp, slot, None, "none_qualified", stock=True)
    copy = govern_copy(WebsiteCopy(**spec["copy"]), bp)
    payload = dict(compose_site(bp, direction, copy, business_type=persona.business_type, contact=contact_for(bp),
                                active_modules=active, meta={"stage": "lab"}))
    theme = payload["theme_hints"]
    dims = dict((theme.get("creative_direction") or {}).get("dimensions") or {})
    fixture = SiteFixture(key, persona.name, persona.business, bp, payload, signature(payload), dims)
    return {"fixture": fixture, "payload": payload, "slots": slots, "bp": bp, "direction": direction,
            "concept": str(theme["dna"]["concept"]), "persona": persona}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


async def _keep_copy(key: str, found: Any) -> str | None:
    """A Pixabay pick, copied for the lab (no permanent hotlinking); the lab URL."""
    from platform_core.website.image_retrieval import fetch_full_image

    fetched = await fetch_full_image(found.url)
    if fetched is None:
        return None
    body, mime = fetched
    folder = PHOTO_DIR / key
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{found.provider}-{found.photo_id}.{'png' if mime == 'image/png' else 'webp' if mime == 'image/webp' else 'jpg'}"
    (folder / name).write_bytes(body)
    return f"/site-lab-photos/{key}/{name}"


async def photos(key: str, built: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Real retrieval for every slot of one lab site. Returns (picks, report)."""
    from platform_core.services.business_interview import _trade
    from platform_core.website.image_retrieval import SiteMemory, brief_for_slot, retrieve_many
    from platform_core.website.image_search import get_search_provider

    bp, direction = built["bp"], built["direction"]
    trade = _trade(bp, direction.archetype)
    briefs = [brief_for_slot(s, direction, trade, bp=bp, concept=built["concept"]) for s in built["slots"]]
    only = {k.strip() for k in os.getenv("PREMIUM_LAB_SLOTS", "").split(",") if k.strip()}
    if only:
        # Re-run some slots only; the others keep their saved picks and audit.
        briefs = [b for b in briefs if b.key in only]
    search = get_search_provider()
    if search is None:
        raise SystemExit("No photo source configured: set UNSPLASH_ACCESS_KEY and/or PIXABAY_API_KEY in .env")
    site = SiteMemory()
    previous_picks = dict((_load(PICKS).get(key) or {})) if only else {}
    previous = (_load(REPORT).get(key) or {}) if only else {}
    for kept in previous.get("slots", []):
        if kept.get("slot") not in only and kept.get("provider") and kept.get("photo_id"):
            site.used.add(f"{kept['provider']}:{kept['photo_id']}")  # never repeat a photo the site has
    results = await retrieve_many(briefs, search=search, site=site)
    picks: dict[str, Any] = {k: v for k, v in previous_picks.items()
                             if k not in {str(uuid.uuid5(bp.business_id, s)) for s in only}}
    report: dict[str, Any] = {"concept": built["concept"], "trade": trade,
                              "slots": [r for r in previous.get("slots", []) if r.get("slot") not in only]}
    by_key = {s.key: s for s in built["slots"]}
    for brief, outcome in results:
        slot = by_key[brief.key]
        row: dict[str, Any] = {"slot": brief.key, "role": brief.section_role, "subject": brief.subject,
                               "aspect": brief.aspect, "reason": outcome.reason, "log": outcome.log}
        found = outcome.found
        if found is not None:
            url = found.url
            if found.must_store:
                url = await _keep_copy(key, found) or ""
            if url:
                picks[str(uuid.uuid5(bp.business_id, slot.key))] = {
                    "url": url, "alt_text": f"Photograph: {slot.subject}"[:200], "credit": found.attribution}
            row.update(provider=found.provider, photo_id=found.photo_id, page_url=found.page_url, url=found.url,
                       score=found.score, rubric=found.rubric, query=found.query,
                       selection_reason=found.selection_reason, credit=found.attribution.get("line", ""))
        report["slots"].append(row)
    remaining = [getattr(p, "remaining", None) for p in getattr(search, "providers", [search])
                 if getattr(p, "provider_name", "") == "unsplash"]
    report["unsplash_requests_left_this_hour"] = remaining[0] if remaining else None
    return picks, report


async def main(argv: list[str]) -> None:
    mode = argv[0] if argv else "slots"
    keys = argv[1:] or list(LAB)
    all_picks, all_reports = _load(PICKS), _load(REPORT)
    LAB_DIR.mkdir(exist_ok=True)
    for key in keys:
        built = await build(key)
        if mode == "photos":
            picks, report = await photos(key, built)
            all_picks[key], all_reports[key] = picks, report
            PICKS.write_text(json.dumps(all_picks, ensure_ascii=False, indent=1), encoding="utf-8")
            REPORT.write_text(json.dumps(all_reports, ensure_ascii=False, indent=1), encoding="utf-8")
        if mode in {"photos", "write"}:
            found = {r["slot"] for r in (all_reports.get(key) or {}).get("slots", []) if r.get("reason") == "ok"}
            if all_reports.get(key):
                built = await build(key, pictured=found)  # composed as a real build would be
            pages = write_lab(LAB_DIR, built["fixture"], all_picks.get(key) or {})
            print(key, built["concept"], pages)
        if mode == "slots" or mode == "photos":
            print(f"{key}  concept={built['concept']}")
            for slot in built["slots"]:
                line = f"   {slot.key:28} {slot.aspect:5} {slot.subject[:70]}"
                if mode == "photos":
                    hit: dict[str, Any] = next((r for r in all_reports[key]["slots"] if r["slot"] == slot.key), {})
                    line += f"  -> {hit.get('provider', '-')}:{hit.get('photo_id', '-')} {hit.get('reason')}"
                print(line)


if __name__ == "__main__":  # pragma: no cover — a tool
    asyncio.run(main(sys.argv[1:]))
