"""The certification gate: does a critiqued site pass, go back for repair, or
fail closed with a concrete request to the owner?

    decide(critique, rounds_used=1, max_rounds=3)
    → {"status": "pass" | "repair" | "fail_closed", "score": 8.62,
       "reasons": [...], "owner_requests": ["We need 2–3 photographs of …"], ...}

PASS (docs/certification/PLAN.md §2.7) needs every one of:

- weighted score ≥ 8.5 / 10 (hero 1.5; typography, composition, imagery,
  art_direction, catalog_presentation, mobile 1.2; every other dimension 1.0);
- every dimension ≥ 7 — a dimension the critic did not score counts as 0;
- zero critical defects and at most two major ones;
- a complete critique (every page judged).

These numbers are the founder's bar and are never lowered to let a site
through: a failure is fixed in the generator, the composer, the renderer or
the pipeline. When the site is not good enough and repair rounds remain the
answer is `repair`; when none remain it is `fail_closed`, and the owner gets
kind, specific requests built from what only they can supply (real photographs,
fuller descriptions, their story) — or, when nothing the owner could add would
fix it, `blocked_on: "platform"` says the remaining work is Locah's.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from platform_testing.certify.references import category_family

DIMENSIONS: tuple[str, ...] = (
    "hero", "typography", "spacing", "composition", "imagery", "art_direction", "page_depth",
    "originality", "relevance", "cta_hierarchy", "catalog_presentation", "mobile", "consistency",
    "motion", "not_template",
)
WEIGHTS: dict[str, float] = {d: 1.0 for d in DIMENSIONS} | {
    "hero": 1.5, "typography": 1.2, "composition": 1.2, "imagery": 1.2, "art_direction": 1.2,
    "catalog_presentation": 1.2, "mobile": 1.2,
}
PASS_SCORE = 8.5
DIMENSION_FLOOR = 7.0
MAX_CRITICAL = 0
MAX_MAJOR = 2
SEVERITIES = ("critical", "major", "minor")
LAYERS = ("copy", "photo", "composition", "order", "styling", "motion", "responsive",
          "architecture", "input")

# Float sums of tenths are not exact (8.5 can come out 8.4999999); this only
# absorbs that, it is not a tolerance.
_EPS = 1e-9


def _num(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(10.0, max(0.0, f)) if math.isfinite(f) else 0.0


def weighted_score(scores: Mapping[str, Any], dims: Iterable[str] = DIMENSIONS) -> float:
    """The weighted mean over ``dims`` (missing scores count as 0), unrounded."""
    names = [d for d in dims if d in WEIGHTS]
    total = sum(WEIGHTS[d] for d in names)
    if not total:
        return 0.0
    return sum(WEIGHTS[d] * _num(scores.get(d)) for d in names) / total


def counts(defects: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    out = {s: 0 for s in SEVERITIES}
    for d in defects:
        sev = str(d.get("severity") or "")
        if sev in out:
            out[sev] += 1
    return out


# ----------------------------------------------------------------- owner requests

_PHOTO_NOUN = {
    "restaurant": "your actual restaurant — the dining room, the kitchen at work and your "
                  "signature dishes",
    "bakery": "your actual bakery — the counter, the ovens and your fresh bakes",
    "meat": "your actual shop — the counter, your cuts and the people behind it",
    "retail": "your actual store and your best-selling products",
    "gym": "your actual gym — the training floor, the equipment and your coaches",
    "salon": "your actual salon, your team and finished work",
    "clinic": "your actual clinic and team",
    "consultant": "you at work (a portrait) and your workspace",
    "architecture": "your completed projects — interiors and exteriors",
    "hotel": "your actual rooms, the lobby and the view",
    "ngo": "your programmes and the people you work with (with their consent)",
    "other": "your actual place, your team and your work",
}

_CATALOGUE_NOUN = {
    "restaurant": "menu", "bakery": "bakes", "meat": "product", "retail": "product",
    "gym": "programme", "salon": "treatment", "clinic": "service", "consultant": "service",
    "architecture": "project", "hotel": "room", "ngo": "programme", "other": "offering",
}

_CATALOGUE_QUESTIONS: dict[str, tuple[str, str, str]] = {
    "restaurant": (
        "Which 3–5 dishes are you proudest of, and what makes each one special (an ingredient, "
        "a technique, a family recipe)?",
        "How would you describe each section of your menu in one sentence?",
        "Where do your key ingredients come from, and what do you make in-house?"),
    "bakery": (
        "Which bakes are you known for, and what goes into each one?",
        "What is baked fresh each day, and at what time is it ready?",
        "Do you take custom orders (cakes, events)? What can customers ask for?"),
    "meat": (
        "Which cuts or products are you known for, and how would you describe each one?",
        "Where does your meat come from (farms, breeds, how the animals are raised)?",
        "How do you prepare it (ageing, marinades, cleaning), and how should customers cook it?"),
    "retail": (
        "Which 3–5 products sell best, and who are they for?",
        "What are they made of, or which brands do you carry, and why did you choose them?",
        "Why should someone buy from you rather than elsewhere (advice, fit, service, price)?"),
    "gym": (
        "Which programmes or classes do you run, and who is each one for?",
        "What does a new member's first week look like?",
        "Who are your coaches, and what are their backgrounds or certifications?"),
    "salon": (
        "Which 3–5 treatments are your signatures, and what is included in each?",
        "How long does each take, and which products do you use?",
        "What should a first-time client expect from a visit?"),
    "clinic": (
        "Which services or departments do you offer, and what does each treat?",
        "What does a patient's first visit look like, from booking to follow-up?",
        "Who are your doctors, and what are their qualifications and specialities?"),
    "consultant": (
        "What exactly do you help clients with, and what outcome does each service deliver?",
        "Who is your ideal client, and what problem do they have when they come to you?",
        "How does a typical engagement run, from first call to result?"),
    "architecture": (
        "Which 3–5 projects best show your work, and what was the brief for each?",
        "How do you work with a client, from first meeting to handover?",
        "Which materials, ideas or principles define your design approach?"),
    "hotel": (
        "What makes each room type special (view, size, bed, bath, light)?",
        "Which amenities and services do guests value most?",
        "What can guests experience nearby that you would recommend?"),
    "ngo": (
        "Which programmes do you run, and who does each one help?",
        "What has changed for the people you serve? One story or number per programme helps.",
        "How is a donation used — what does a typical amount make possible?"),
    "other": (
        "Which 3–5 offerings are you proudest of, and what makes each one special?",
        "Who is each one for, and what do customers get?",
        "Why do customers choose you over the alternatives?"),
}

_STORY_QUESTIONS: tuple[str, str, str] = (
    "How did {business} start, and what has stayed the same since?",
    "What do customers say about you most often — one or two real quotes are perfect.",
    "Who is behind {business}? A sentence about each key person helps.",
)

_PHOTO_WORDS = re.compile(r"photo|picture|image|gallery|portrait|shot|imagery|visual",
                          re.IGNORECASE)
_CATALOGUE_WORDS = re.compile(
    r"descri|menu|catalog|service|product|dish|item|price|treatment|class|room|programme|program|"
    r"offering|range|cut|bake|project|package", re.IGNORECASE)
_STORY_WORDS = re.compile(
    r"about|story|founder|owner|team|history|mission|testimonial|review|credential|qualif|"
    r"trust|award|experience|bio", re.IGNORECASE)


def _defect_kind(defect: Mapping[str, Any]) -> str | None:
    """photo | catalogue | story | other — or None when it is not the owner's to fix."""
    layer = str(defect.get("layer") or "")
    if str(defect.get("source") or "") in {"render", "distinct"}:
        return None  # a broken page or a look-alike site is Locah's fault, never the owner's
    text = str(defect.get("text") or "")
    if layer == "photo":
        return "photo"
    if layer != "input":
        return None
    if _PHOTO_WORDS.search(text):
        return "photo"
    if _CATALOGUE_WORDS.search(text):
        return "catalogue"
    if _STORY_WORDS.search(text):
        return "story"
    return "other"


def owner_requests(critique: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Kind, concrete requests from the defects only the owner can fix, at most
    one per kind (photos, catalogue, story) plus up to two specific asks."""
    family = category_family(str(critique.get("category") or ""))
    business = str(critique.get("business") or "").strip() or "your business"
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for d in critique.get("defects") or []:
        if isinstance(d, Mapping) and str(d.get("severity") or "") in SEVERITIES:
            kind = _defect_kind(d)
            if kind:
                grouped.setdefault(kind, []).append(d)
    scores = critique.get("scores") or {}
    out: list[dict[str, Any]] = []
    photo_defects = grouped.get("photo", [])
    imagery_low = _num(scores.get("imagery")) < DIMENSION_FLOOR
    if photo_defects or imagery_low:
        out.append({
            "kind": "photos",
            "message": f"We need 2–3 photographs of {_PHOTO_NOUN[family]} to finish this site to "
                       "our quality standard. Phone photos in good daylight are perfect.",
            "questions": [],
            "defect_ids": [str(d.get("id") or "") for d in photo_defects],
        })
    if grouped.get("catalogue"):
        questions = list(_CATALOGUE_QUESTIONS[family])
        out.append({
            "kind": "catalogue",
            "message": f"The {_CATALOGUE_NOUN[family]} descriptions are too limited to build the "
                       "experience properly. Please answer these three questions: "
                       + " ".join(f"{i}. {q}" for i, q in enumerate(questions, 1)),
            "questions": questions,
            "defect_ids": [str(d.get("id") or "") for d in grouped["catalogue"]],
        })
    if grouped.get("story"):
        questions = [q.format(business=business) for q in _STORY_QUESTIONS]
        out.append({
            "kind": "story",
            "message": f"Your story is what makes {business} different, and we have too little of "
                       "it to tell it well. Please answer these three questions: "
                       + " ".join(f"{i}. {q}" for i, q in enumerate(questions, 1)),
            "questions": questions,
            "defect_ids": [str(d.get("id") or "") for d in grouped["story"]],
        })
    for d in sorted(grouped.get("other", []), key=lambda d: SEVERITIES.index(str(d["severity"])))[:2]:
        page = str(d.get("page") or "").strip("*/ ") or "home"
        text = str(d.get("text") or "").strip().rstrip(".")
        out.append({
            "kind": "other",
            "message": f"One more thing would let us finish your {page} page properly: {text}. "
                       "Could you send us what you have?",
            "questions": [],
            "defect_ids": [str(d.get("id") or "")],
        })
    return out


# ----------------------------------------------------------------- the decision


def decide(critique: Mapping[str, Any], *, rounds_used: int, max_rounds: int) -> dict[str, Any]:
    """pass | repair | fail_closed, with the weighted score and every reason."""
    scores: Mapping[str, Any] = critique.get("scores") or {}
    defects = [d for d in critique.get("defects") or [] if isinstance(d, Mapping)]
    score = weighted_score(scores)
    tally = counts(defects)
    reasons: list[str] = []
    if score + _EPS < PASS_SCORE:
        reasons.append(f"weighted score {score:.2f} is below {PASS_SCORE}")
    low = {d: round(_num(scores.get(d)), 2) for d in DIMENSIONS
           if d not in scores or _num(scores.get(d)) + _EPS < DIMENSION_FLOOR}
    for dim, value in low.items():
        reasons.append(f"{dim} was not scored" if dim not in scores
                       else f"{dim} {value:g} is below {DIMENSION_FLOOR:g}")
    if tally["critical"] > MAX_CRITICAL:
        names = "; ".join(str(d.get("text") or "")[:90] for d in defects
                          if d.get("severity") == "critical")[:400]
        reasons.append(f"{tally['critical']} critical defect(s): {names}")
    if tally["major"] > MAX_MAJOR:
        reasons.append(f"{tally['major']} major defects (at most {MAX_MAJOR})")
    if critique.get("complete") is False:
        errors = "; ".join(str(e) for e in critique.get("errors") or [])[:300]
        reasons.append("the critique is incomplete" + (f": {errors}" if errors else ""))

    result: dict[str, Any] = {
        "status": "pass", "score": round(score, 2), "reasons": reasons, "owner_requests": [],
        "owner_request_details": [], "counts": tally, "dimension_failures": low,
        "thresholds": {"score": PASS_SCORE, "dimension": DIMENSION_FLOOR,
                       "critical": MAX_CRITICAL, "major": MAX_MAJOR},
        "rounds_used": rounds_used, "max_rounds": max_rounds,
    }
    if not reasons:
        return result
    if rounds_used < max_rounds:
        result["status"] = "repair"
        return result
    details = owner_requests(critique)
    result["status"] = "fail_closed"
    result["owner_request_details"] = details
    result["owner_requests"] = [r["message"] for r in details]
    result["blocked_on"] = "owner" if details else "platform"
    if not details:
        reasons.append("nothing the owner could add would fix the remaining defects: "
                       "the generator, composer or renderer must")
    return result
