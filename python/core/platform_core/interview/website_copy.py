"""Website copy: written by the model, governed by Locah.

A website whose headline is the business name and whose every paragraph is the
owner's raw answer reads like a form that was filled in. The model is allowed
to write — a headline with a point of view, a short subheadline, section
titles, one-line descriptions of what the owner named — because that is
editorial work, and it is the difference between a site and a data dump.

What it may not do is add evidence. Every piece of copy passes `govern_copy`
before it is used, and a field that fails is dropped rather than repaired, so
the composer falls back to the owner's own words for it:

* a number must be one the owner said;
* a claim word (certified, award-winning, guaranteed, organic, since 1990...)
  must be one the owner used;
* a feature or step title must be built from the owner's own words;
* the accent must actually occur in the headline;
* the stock phrases that make a site read as generated ("Welcome to...",
  "your trusted partner", "quality and excellence") are removed on sight.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from platform_core.interview.models import BusinessBlueprint


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeatureCopy(_Model):
    title: str = Field(min_length=1, max_length=80)
    body: str = Field(default="", max_length=240)


class StepCopy(_Model):
    title: str = Field(min_length=1, max_length=60)
    body: str = Field(default="", max_length=160)
    # The owner's sentence this step is drawn from. Required: a step with no
    # source is a process Locah invented.
    quote: str = Field(min_length=1, max_length=300)


class PillarCopy(_Model):
    """One thing the business stands on, drawn from one owner sentence."""

    title: str = Field(min_length=1, max_length=48)
    body: str = Field(default="", max_length=160)
    # The owner's sentence it came from. Required: a pillar with no source is
    # a value Locah invented.
    quote: str = Field(min_length=1, max_length=300)


class NamedLine(_Model):
    """One short line about one thing the owner named — a category or an item."""

    name: str = Field(min_length=1, max_length=80)
    line: str = Field(min_length=1, max_length=160)


class WebsiteCopy(_Model):
    headline: str = Field(default="", max_length=90)
    headline_accent: str = Field(default="", max_length=40)
    subheadline: str = Field(default="", max_length=220)
    about_title: str = Field(default="", max_length=70)
    about_body: str = Field(default="", max_length=800)
    offerings_title: str = Field(default="", max_length=60)
    offerings_subtitle: str = Field(default="", max_length=160)
    features: list[FeatureCopy] = Field(default_factory=list, max_length=8)
    steps_title: str = Field(default="", max_length=60)
    steps: list[StepCopy] = Field(default_factory=list, max_length=4)
    closing_headline: str = Field(default="", max_length=90)
    closing_body: str = Field(default="", max_length=200)
    contact_title: str = Field(default="", max_length=60)
    # Headings for browsing what is sold ("Shop by category", "Our menu").
    categories_title: str = Field(default="", max_length=60)
    products_title: str = Field(default="", max_length=60)
    category_lines: list[NamedLine] = Field(default_factory=list, max_length=8)
    item_lines: list[NamedLine] = Field(default_factory=list, max_length=24)
    # The premium site (site_pages): one sentence as a centrepiece, what the
    # business stands on, and the opening lines of its inner pages.
    statement: str = Field(default="", max_length=200)
    statement_highlight: str = Field(default="", max_length=50)
    pillars_title: str = Field(default="", max_length=60)
    pillars: list[PillarCopy] = Field(default_factory=list, max_length=4)
    catalogue_intro: str = Field(default="", max_length=200)
    about_intro: str = Field(default="", max_length=200)
    visit_intro: str = Field(default="", max_length=200)


# Claims that need the owner's own evidence. Allowed only when the owner used
# the same word.
_CLAIMS = (
    r"certif\w*", r"accredit\w*", r"licen[cs]ed", r"award\w*", r"guarantee\w*", r"warrant\w*",
    r"best", r"#\s?1", r"no\.?\s?1", r"number one", r"leading", r"top[- ]rated", r"finest",
    r"world[- ]class", r"state[- ]of[- ]the[- ]art", r"trusted", r"organic", r"authentic",
    r"100\s?%", r"free", r"cheapest", r"lowest", r"fastest", r"iso", r"experts?", r"experienced",
    r"years?", r"since", r"established", r"doctors?", r"surgeons?", r"specialists?", r"team",
    # Sourcing, freshness and quality claims a food or product site reaches for.
    r"farms?", r"farm[- ]fresh", r"fresh\w*", r"halal", r"antibiotic\w*", r"hormone\w*",
    r"chemical\w*", r"premium", r"hygien\w*", r"same[- ]day", r"free[- ]range", r"grass[- ]fed",
    r"natural", r"pure", r"sourced", r"hand[- ]picked", r"home[- ]grown", r"deliver\w*",
    r"doorstep", r"daily",
)
_CLAIM_RE = re.compile(r"\b(" + "|".join(_CLAIMS) + r")\b", re.I)

# The register of a generated site. Never useful, always recognisable.
_STOCK = re.compile(
    r"welcome to|your trusted partner|quality and excellence|committed to (?:excellence|providing)|"
    r"one[- ]stop|look no further|second to none|unparalleled|exceptional service|cutting[- ]edge|"
    r"seamless|elevate your|unlock|in today'?s|we pride ourselves|your satisfaction|go-to",
    re.I,
)
_DIGITS = re.compile(r"\d[\d,.]*")
_WORD = re.compile(r"[a-zA-Z஀-௿]{3,}")


def owner_corpus(bp: BusinessBlueprint) -> str:
    """Everything the owner actually said, for grounding checks."""
    facts = {**bp.known_facts, **bp.unconfirmed_facts}
    parts = [fact.value for fact in facts.values()]
    parts += [fact.value for fact in bp.identity.values()]
    parts += [message.text for message in bp.messages if message.role == "user"]
    return " ".join(parts)


def _clean(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _grounded(text: str, corpus: str) -> bool:
    """No number, and no claim word, the owner did not supply themselves."""
    low = corpus.casefold()
    owner_digits = {re.sub(r"[,.]", "", n) for n in _DIGITS.findall(corpus)}
    for number in _DIGITS.findall(text):
        if re.sub(r"[,.]", "", number) not in owner_digits:
            return False
    for match in _CLAIM_RE.finditer(text):
        if _claim_root(match.group(0)) not in low:
            return False
    return not _STOCK.search(text)


def _claim_root(word: str) -> str:
    """"delivered" is the owner's "we deliver"; "daily" is not their "every morning"."""
    word = word.casefold()
    for suffix in ("ies", "ied", "ing", "ery", "ers", "ed", "er", "es", "ly", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _built_from_owner_words(title: str, corpus: str) -> bool:
    words = [w.casefold() for w in _WORD.findall(title)]
    if not words:
        return False
    low = corpus.casefold()
    # Allow simple plural/singular drift ("sofa" vs "sofas").
    return all(w in low or w.rstrip("s") in low for w in words)


def govern_copy(copy: WebsiteCopy, bp: BusinessBlueprint) -> WebsiteCopy:
    """Drop every field that adds evidence; keep everything that only writes."""
    corpus = owner_corpus(bp)
    data: dict[str, Any] = {}
    for field in (
        "headline", "subheadline", "about_title", "about_body", "offerings_title",
        "offerings_subtitle", "steps_title", "closing_headline", "closing_body", "contact_title",
        "categories_title", "products_title", "statement", "pillars_title", "catalogue_intro",
        "about_intro", "visit_intro",
    ):
        text = _clean(getattr(copy, field))
        if text and _grounded(text, corpus):
            data[field] = text
    mark = _clean(copy.statement_highlight)
    if mark and data.get("statement") and mark in data["statement"] and mark != data["statement"]:
        data["statement_highlight"] = mark
    pillars: list[PillarCopy] = []
    for pillar in copy.pillars:
        quote, title, body = _clean(pillar.quote), _clean(pillar.title), _clean(pillar.body)
        if not quote or quote.casefold() not in corpus.casefold() or not title or not _grounded(title, corpus):
            continue
        pillars.append(PillarCopy(title=title, body=body if body and _grounded(body, corpus) else "", quote=quote))
    data["pillars"] = pillars if len(pillars) >= 2 else []
    accent = _clean(copy.headline_accent)
    if accent and data.get("headline") and accent in data["headline"] and accent != data["headline"]:
        data["headline_accent"] = accent
    features: list[FeatureCopy] = []
    for item in copy.features:
        title = _clean(item.title)
        if not title or not _built_from_owner_words(title, corpus):
            continue
        body = _clean(item.body)
        features.append(FeatureCopy(title=title, body=body if body and _grounded(body, corpus) else ""))
    data["features"] = features
    steps: list[StepCopy] = []
    for step in copy.steps:
        quote = _clean(step.quote)
        title = _clean(step.title)
        if not quote or quote.casefold() not in corpus.casefold() or not _grounded(title, corpus):
            continue
        body = _clean(step.body)
        steps.append(StepCopy(title=title, body=body if body and _grounded(body, corpus) else "", quote=quote))
    data["steps"] = steps if len(steps) >= 2 else []
    # A line belongs to something the owner named, and adds no evidence.
    named = {g.name.casefold() for g in bp.taxonomy.groups}
    named |= {i.name.casefold() for g in bp.taxonomy.groups for i in g.items}
    for field in ("category_lines", "item_lines"):
        kept: list[NamedLine] = []
        for entry in getattr(copy, field):
            name, line = _clean(entry.name), _clean(entry.line)
            if name.casefold() in named and line and _grounded(line, corpus) and not _PADDING.search(line):
                kept.append(NamedLine(name=name, line=line))
        data[field] = kept
    return WebsiteCopy(**data)


# A line that only says where or how a thing is booked says nothing about it:
# "Full-head colour, done at the salon.", "Makeup for your wedding day — book
# it ahead." (certification: a service list a critic called tautological).
# Such a line is dropped, not shown.
_PADDING = re.compile(
    r"\b(?:done|available|offered|made|served) (?:at|in) (?:the|our) "
    r"(?:salon|clinic|shop|store|studio|kitchen|bakery|gym|centre|center)\b|"
    r"\bbook (?:it|a time|ahead|now)\b|\bon appointment\b|\bthat suits you\b", re.I)


COPY_PROMPT = (
    "Also write the website's words, in the `copy` object. You are writing for a real small "
    "business, from what the owner told you. Be specific, short and human — the way a good "
    "local designer would write it, not the way an AI template would.\n"
    "- headline: 3-8 words with a point of view about THIS business (e.g. 'Wardrobes built "
    "for your room.'), not just its name. headline_accent: 1-3 consecutive words from the "
    "headline to set in the brand colour.\n"
    "- subheadline: one sentence saying what they do and for whom, from their words.\n"
    "- features: one item per thing the owner named that they sell or do. title uses the "
    "owner's own words (tidy capitalisation only); body is one short plain sentence about "
    "what that thing is, without inventing materials, prices, timings or quantities.\n"
    "- steps: only if the owner described how customers work with them (e.g. WhatsApp, then "
    "visit, then delivery): 2-4 steps, each with `quote` = the exact owner sentence it came from.\n"
    "- about_title / about_body: a short, warm paragraph drawn only from what they said.\n"
    "- offerings_title, steps_title, closing_headline, closing_body, contact_title: short and "
    "specific.\n"
    "- products_title / categories_title: the heading over what can be bought or chosen, in the "
    "voice of this kind of site ('Shop by category', 'Our menu', 'Featured projects') — never "
    "'What we do' for things people buy.\n"
    "- statement: ONE sentence (10-28 words) that says what this business is about, in the "
    "owner's spirit and from their words — the line a visitor remembers. statement_highlight: "
    "2-4 consecutive words from it to set apart.\n"
    "- pillars_title and pillars: 3-4 things this business stands on (how it makes, sells or "
    "serves), each with a short title (2-5 words), one sentence body, and `quote` = the exact "
    "owner sentence it came from. Leave empty if the owner did not say enough.\n"
    "- catalogue_intro, about_intro, visit_intro: one short opening sentence for the menu/shop, "
    "story and visit pages, from what the owner said.\n"
    "- category_lines / item_lines: for each group and item in brief.catalogue, one short "
    "appetising line (at most 14 words) about what the customer gets — what is in it, what it "
    "is for or what it is like — naming it exactly as given; never a price, weight, origin or "
    "quality claim the owner did not make, and never only where or how it is booked ('done at "
    "the salon', 'book it ahead' say nothing). Leave a line out rather than pad it.\n"
    "NEVER add numbers, years, awards, certifications, guarantees, ratings, reviews, "
    "staff, 'best', 'trusted', 'organic', 'authentic' or any fact the owner did not say. "
    "Never write 'Welcome to', 'your trusted partner', 'quality and excellence', 'one-stop' "
    "or similar stock phrases. Write in English, keeping the owner's product names as they "
    "said them, unless the owner wrote mostly in Tamil script — then write in natural Tamil."
    "\nThe `brief` in the context is what the conversation established. Where it already has a "
    "hero_headline, hero_subheadline or about, the owner has seen those lines: keep them unless a "
    "field is empty, and never contradict them. owner_claims are lines the owner asked for — you "
    "may use them. Use sold_by, fulfilment and payment to write the steps and closing lines."
)
