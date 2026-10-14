"""One conversation engine for chat and voice. No DB or HTTP dependencies.

Per owner message: ONE model call returns a TurnIntelligence. Locah then

1. reads the message in the light of the question it answers (the reader),
   which checks every extraction for its semantic type and is the whole of
   the understanding when the model cannot be reached;
2. merges what survived into the Blueprint;
3. judges coverage for THIS business and decides — the checkpoint when there
   is enough for a strong first version, the summary when the owner wants to
   build, otherwise the single most informative next question (planner).

Replies stay short enough to be spoken. Voice calls exactly this.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any, Literal, Protocol

from platform_core.business_type_profiles.registry import BusinessTypeProfileRegistry
from platform_core.interview import hours, planner
from platform_core.interview import reader as rd
from platform_core.interview.conversation import (
    ACKS,
    LOGO_QUEUED,
    LOGO_UNAVAILABLE,
    DOCUMENT_UPLOAD,
    LANGUAGE_SWITCHED,
    LOGO_UPLOAD,
    REDIRECT,
    REDUNDANT,
    SYSTEM_PROMPT,
    UNCLEAR,
    VISUALS_QUEUED,
    _lang,
    accept_answers,
    accept_highlights,
    accept_patterns,
    acknowledgement,
    govern_acknowledgement,
    govern_draft,
    govern_question,
    mark_redundant,
    merge_fact,
    speaks,
)
from platform_core.interview.coverage import assess, floor_met, worth_knowing
from platform_core.interview.discovery import (
    TARGETS,
    characteristics,
    fallback_question,
    profile_type,
    sync_from_facts,
)
from platform_core.interview.models import (
    AskRecord,
    BusinessBlueprint,
    DraftUpdate,
    ExtractedFact,
    Fact,
    FactKey,
    GroupProposal,
    ItemProposal,
    MediaGenerationRequest,
    Message,
    Question,
    TargetAnswer,
    TargetState,
    TurnIntelligence,
    TurnTelemetry,
    now,
)
from platform_core.logging import get_logger
from platform_core.website.ai_provider import AIModelProvider, get_ai_provider

# Kept for callers that seed a new Blueprint; the planner decides what is asked.
QUESTIONS = (
    Question(field="description",
             text="Tell me about your business in your own words.",
             reason="Your website needs a truthful introduction."),
)

OPENING = {
    "en": "Tell me about {name} in your own words — what you sell or provide, how customers usually "
          "buy, book or contact you, and anything you'd like the website to make easier.",
    "ta_en": "{name} pathi unga words-la sollunga — enna sell pannureenga illa enna service, customers "
             "eppadi vaanguvaanga, book pannuvaanga illa contact pannuvaanga, website enna easy "
             "pannanum?",
    "ta": "{name} பத்தி உங்க வார்த்தைகளில் சொல்லுங்க — என்ன விற்கிறீங்க அல்லது என்ன சேவை, வாடிக்கையாளர்கள் "
          "எப்படி வாங்குவாங்க அல்லது தொடர்பு கொள்வாங்க, வெப்சைட் எதை எளிதாக்கணும்?",
}
# Started by talking, before the business has a name.
OPENING_UNNAMED = {
    "en": "Tell me about your business in your own words — what you sell or provide, how customers usually "
          "buy, book or contact you, and anything you'd like the website to make easier.",
    "ta_en": "Unga business pathi unga words-la sollunga — enna sell pannureenga illa enna service, customers "
             "eppadi vaanguvaanga, book pannuvaanga illa contact pannuvaanga, website enna easy pannanum?",
    "ta": "உங்க பிசினஸ் பத்தி உங்க வார்த்தைகளில் சொல்லுங்க — என்ன விற்கிறீங்க அல்லது என்ன சேவை, "
          "வாடிக்கையாளர்கள் எப்படி வாங்குவாங்க அல்லது தொடர்பு கொள்வாங்க, வெப்சைட் எதை எளிதாக்கணும்?",
}
# The owner picked the kind of business first: acknowledge it, then ask.
OPENING_PICKED = {
    "en": "Got it — {kind}. Tell me a little about {subject} — what you sell or offer, how customers "
          "normally buy from you, and anything you'd like the website to make easier.",
    "ta_en": "Seri — {kind}. {subject} pathi konjam sollunga — enna sell / offer pannureenga, customers "
             "eppadi vaanguvaanga, website enna easy pannanum?",
    "ta": "சரி — {kind}. {subject} பத்தி கொஞ்சம் சொல்லுங்க — என்ன விற்கிறீங்க, வாடிக்கையாளர்கள் எப்படி "
          "வாங்குவாங்க, வெப்சைட் எதை எளிதாக்கணும்?",
}
KIND_UPDATED = {
    "en": "Got it — {kind}. I've updated that.",
    "ta_en": "Seri — {kind}. Maathitten.",
    "ta": "சரி — {kind}. மாத்திட்டேன்.",
}
NAME_THANKS = {"en": "{name} — lovely.", "ta_en": "{name} — nalla per.", "ta": "{name} — நல்ல பெயர்."}
# The opening answers these at once; what it leaves open is asked after.
OPENING_TARGETS = ("business.identity", "offerings.main", "commerce.action")
NO_PROBLEM = {"en": "No problem.", "ta_en": "Paravaalla.", "ta": "பரவாயில்லை."}
# A correction to something already known is said back as it now stands.
FACT_UPDATED = {
    "en": "Updated — {what}: {value}.",
    "ta_en": "Maathitten — {what}: {value}.",
    "ta": "மாத்திட்டேன் — {what}: {value}.",
}
UPDATED_FACT: dict[str, dict[str, str]] = {
    "opening_hours": {"en": "hours", "ta_en": "timing", "ta": "நேரம்"},
    "phone": {"en": "number", "ta_en": "number", "ta": "எண்"},
    "locations": {"en": "location", "ta_en": "location", "ta": "இடம்"},
    "email": {"en": "email", "ta_en": "email", "ta": "மின்னஞ்சல்"},
}

# Readable names for a typed correction that was the wrong kind of thing.
_SLOT_HINT = {
    "opening_hours": "That doesn't look like opening hours — try something like "
                     "\"9 am to 8 pm, Monday to Saturday\".",
    "phone": "That doesn't look like a phone number — a 10-digit mobile number works best.",
    "customer_actions": "Tell me what a customer does — for example \"order on WhatsApp\" or "
                        "\"book a table\".",
    "locations": "That doesn't look like a place — the area and city is enough.",
}


def _retain_explicit_multilingual_actions(extraction: TurnIntelligence, text: str) -> None:
    """Keep an exact Tamil booking sentence when the extractor overlooks it.

    This is deliberately narrow and quotation-only. It does not translate,
    infer a capability or invent an action; it preserves a sentence that
    explicitly contains both the Tamil-script appointment and booking terms.
    """
    if any(
        item.field == "customer_actions" and item.quote in text
        for item in extraction.facts
    ):
        return
    for sentence in re.findall(r"[^.!?]+[.!?]?", text):
        quote = sentence.strip()
        if re.search(r"அப்பாயிண்ட்மென்ட்|அபாயிண்ட்மென்ட்|முன்பதிவு", quote) and re.search(
            r"புக்|பண்ண|செய்ய", quote
        ):
            extraction.facts.append(
                ExtractedFact(field="customer_actions", quote=quote)
            )
            return


def _remove_superseded_location_echoes(bp: BusinessBlueprint, old_location: str) -> None:
    """Remove an old place from duplicated summary facts after a correction.

    Extractors often quote a rich opening answer both as `description` and as
    dedicated fields. Updating `locations` must not leave the old city visible
    inside that copied description. We retain only an unchanged sentence from
    the owner's earlier evidence; if none survives, the stale summary fact is
    removed and can be asked again.
    """
    if not old_location.strip():
        return
    pattern = re.compile(r"\b" + re.escape(old_location.strip()) + r"\b", re.I)
    for facts in (bp.unconfirmed_facts, bp.known_facts):
        for key, fact in list(facts.items()):
            if key == "locations" or not pattern.search(fact.value):
                continue
            negated_old = re.search(
                r"(?:,\s*)?\bnot\s+" + re.escape(old_location.strip()) + r"\b[.!?]?\s*$",
                fact.value,
                re.I,
            )
            if negated_old:
                survivor = fact.value[: negated_old.start()].strip()
                if survivor:
                    facts[key] = fact.model_copy(
                        update={
                            "value": survivor,
                            "evidence": survivor,
                            "confirmation": "unconfirmed",
                        }
                    )
                    continue
            location_suffix = re.search(
                r"(?:,\s*)?(?:and\s+)?(?:we\s+are\s+)?(?:located|based)\s+in\s+"
                + re.escape(old_location.strip())
                + r"[.!?]?\s*$|\s+in\s+"
                + re.escape(old_location.strip())
                + r"[.!?]?\s*$",
                fact.value,
                re.I,
            )
            if location_suffix:
                survivor = fact.value[: location_suffix.start()].strip().rstrip(",")
                if survivor:
                    facts[key] = fact.model_copy(
                        update={"value": survivor, "evidence": survivor, "confirmation": "unconfirmed"}
                    )
                    continue
            sentences = [
                sentence.strip()
                for sentence in re.findall(r"[^.!?]+[.!?]?", fact.value)
                if sentence.strip() and not pattern.search(sentence)
            ]
            if sentences:
                survivor = max(sentences, key=len)
                facts[key] = fact.model_copy(
                    update={
                        "value": survivor,
                        "evidence": survivor,
                        "confirmation": "unconfirmed",
                    }
                )
            else:
                del facts[key]


class VoiceAdapter(Protocol):
    """A real adapter supplies a final transcript to the SAME turn endpoint.

    No browser speech API or simulated microphone is offered as production voice.
    Transport must not own its own facts, history, completion rules or credentials.
    """
    async def transcribe(self, audio: bytes, *, mime_type: str) -> str: ...
    async def speak(self, text: str) -> bytes: ...


class BusinessInterviewOrchestrator:
    @staticmethod
    def project(bp: BusinessBlueprint, business_type: str | None = None) -> None:
        """Derive everything that follows from what is known — nothing is asked here."""
        sync_from_facts(bp)
        facts = {**bp.known_facts, **bp.unconfirmed_facts}
        bp.business_classification = facts.get("classification")
        for field in ("operating_model", "locations", "offerings", "customer_actions",
                      "operational_characteristics", "brand", "tone", "colours", "website_priorities"):
            setattr(bp, field, facts.get(field))
        bp.website_content = {k: v for k, v in facts.items() if k in {
            "description", "opening_hours", "phone", "email",
        }}
        bp.readiness = assess(bp, business_type)
        _remaining(bp)
        sufficient = bp.readiness.ready
        bp.completion_state.sufficient = sufficient
        bp.completion_state.confirmed = sufficient and not bp.unconfirmed_facts
        if bp.completion_state.status != "built":
            bp.completion_state.status = (
                "ready" if bp.completion_state.confirmed else "review" if sufficient else "collecting"
            )
        if sufficient and bp.completion_state.completed_at is None:
            bp.completion_state.completed_at = now()

    @staticmethod
    def confirm(bp: BusinessBlueprint, business_type: str | None = None) -> None:
        for key, fact in bp.unconfirmed_facts.items():
            bp.known_facts[key] = fact.model_copy(update={"confirmation": "confirmed"})
        bp.unconfirmed_facts.clear()
        BusinessInterviewOrchestrator.project(bp, business_type)

    @staticmethod
    def opening_question(bp: BusinessBlueprint) -> str:
        from platform_core.interview.understanding import kind_phrase, place_noun

        lang = _lang(bp.language_style)
        named = "display_name" in bp.identity and not bp.name_pending
        name = bp.identity["display_name"].value if named else ""
        kind = kind_phrase(bp) if lang == "en" else (bp.category.label if bp.category else "")
        if kind and bp.category and bp.category.source == "owner_picked":
            subject = name or f"the {place_noun(bp)}"
            return OPENING_PICKED[lang].format(kind=kind, subject=subject)
        if not named:
            return OPENING_UNNAMED[lang]
        return OPENING[lang].format(name=name)

    @staticmethod
    def open(bp: BusinessBlueprint) -> None:
        """Start the conversation with its one high-information question."""
        bp.messages = [Message(role="assistant", text=BusinessInterviewOrchestrator.opening_question(bp))]
        bp.asks = [AskRecord(ask="opening", targets=list(OPENING_TARGETS), turn=0)]

    @staticmethod
    def payload(bp: BusinessBlueprint, text: str, business_type: str | None) -> dict[str, Any]:
        """Compact structured state for the model — never the transcript."""
        facts = {**bp.known_facts, **bp.unconfirmed_facts}
        profile = BusinessTypeProfileRegistry.get_or_default(profile_type(bp, business_type))
        chars = characteristics(bp, business_type)
        understood = {
            tid: (state.summary or state.quote)[:160]
            for tid, state in bp.discovery.items()
            if state.status in {"answered", "partial"}
        }
        recent = [a.ask for a in bp.asks[-3:]]
        wd = bp.website_draft
        locked = [f for f in ("hero_headline", "hero_subheadline", "about", "cta_label")
                  if getattr(wd, f) and getattr(wd, f).provenance in {"owner_edited", "owner_approved"}]
        last_question = next((m.text for m in reversed(bp.messages) if m.role == "assistant"), "")
        last = planner.last_ask(bp)
        return {
            "business_name": bp.identity["display_name"].value if "display_name" in bp.identity else "",
            "profile_hint": {
                "type": bp.category.label if bp.category and bp.category.label else profile.display_name,
                "observed": sorted(c for c, how in chars.items() if how == "observed"),
            },
            "known": {k: v.value[:400] for k, v in facts.items()},
            "understood": understood,
            "asked_recently": recent,
            "declined": [tid for tid, s in bp.discovery.items() if s.status in {"declined", "deferred"}],
            "candidates": [
                {"id": item.ask.id, "covers": list(item.ask.targets),
                 "learn": "; ".join(t.learn for t in TARGETS if t.id in item.ask.targets)[:300]}
                for item in planner.rank(bp, business_type)[:5]
            ],
            "last_question": last_question[:300],
            "last_target": ",".join(last.targets) if last else "",
            "draft": {
                "fields": [f for f in ("hero_headline", "hero_subheadline", "about", "cta_label")
                           if getattr(wd, f)],
                "locked": locked + [f"offering:{o.name}" for o in wd.offerings if o.description
                                    and o.description.provenance in {"owner_edited", "owner_approved"}],
                "offerings": [o.name for o in wd.offerings],
                "owner_claims": [c.claim for c in wd.owner_claims],
            },
            # The language the owner asked Locah to reply in ("" = mirror the message).
            "reply_language": "" if bp.language_preference == "auto" else bp.language_preference,
            "catalogue": [
                {"group": g.name, "items": [i.name for i in g.items][:12], "sold_by": g.sold_by,
                 "still_unknown": [n for n in g.needs if n in {"varieties", "cuts", "sizes"}]}
                for g in bp.taxonomy.groups
            ],
            "message": text,
        }

    @staticmethod
    async def turn(
        bp: BusinessBlueprint,
        text: str,
        *,
        field: FactKey | None = None,
        provider: AIModelProvider | None = None,
        business_type: str | None = None,
        image_available: bool = False,
        via: str = "text",
    ) -> BusinessBlueprint:
        bp = bp.model_copy(deep=True)
        text = text.strip()
        if not text:
            raise ValueError("Tell us a little about your business first.")
        # Once the website exists the conversation changes it; it no longer interviews.
        built = bp.completion_state.status == "built"
        started = time.monotonic()
        provider = provider or get_ai_provider()
        fallback: str | None = None
        sync_from_facts(bp)
        if not bp.asks:
            # A Blueprint from before asks were recorded: the last question it
            # asked is what this message answers; with none, the opening.
            legacy = planner.ask_for_target(bp.last_asked_target or "")
            bp.asks = [AskRecord(ask=legacy.id, targets=[bp.last_asked_target or ""], turn=bp.turn_count)
                       if legacy and bp.last_asked_target
                       else AskRecord(ask="opening", targets=list(OPENING_TARGETS), turn=0)]
        said = text  # what the owner typed, as the transcript keeps it
        if not field:
            # "Tamil la pesalama?" changes how Locah talks, not what it knows: it
            # is held for the rest of the conversation, and a message that asked
            # nothing else answers no question (the one asked is asked again).
            request = rd.language_request(text)
            if request is not None:
                bp.language_preference = request[0]
                if request[1]:
                    return BusinessInterviewOrchestrator._language_turn(
                        bp, text, business_type=business_type, via=via, started=started)
                # The rest of the message is read without the request in it.
                text = rd.without_language_request(text)
        answering_targets = tuple(bp.asks[-1].targets) if bp.asks else ()
        reading = rd.read(text)
        # Explicit edits are user data, not a model task — and they are checked
        # for their type: "All india" is never saved as opening hours.
        if field:
            if not rd.valid_for(field, text):
                raise ValueError(_SLOT_HINT.get(field, "That doesn't fit there — try saying it another way."))
            ti = TurnIntelligence(
                facts=[ExtractedFact(field=field, quote=text, mode="replace")],
                language=bp.language_style,
            )
        else:
            try:
                config: dict[str, object] = {
                    "purpose": "business.interview",
                    "schema_name": "business_interview",
                    "system_prompt": SYSTEM_PROMPT,
                    "max_output_tokens": 4000,
                    "temperature": 0.3,
                }
                override = os.getenv("AI_INTERVIEW_MODEL", "").strip()
                if override:
                    config["model"] = override
                raw = await asyncio.wait_for(provider.generate_structured(
                    json.dumps(BusinessInterviewOrchestrator.payload(bp, text, business_type),
                               ensure_ascii=False),
                    TurnIntelligence.model_json_schema(), config, timeout_seconds=20,
                ), timeout=21)
                ti = TurnIntelligence.model_validate(raw)
                _retain_explicit_multilingual_actions(ti, text)
            except Exception as exc:
                # Do not log raw provider errors or the owner's private business narrative.
                fallback = type(exc).__name__
                ti = TurnIntelligence(language=bp.language_style)
        if not field and fallback is None:
            bp.language_style = ti.language
        elif not field:
            # No model to tell the language: the owner's own script and words do.
            # A short reply with one Tamil word ("weekend la 11 varaikum open")
            # keeps the Tanglish the owner has been using.
            seen = rd.language_of(text)
            if seen == "en" and bp.language_style in ("ta_en", "ta") and rd.has_tamil_words(text):
                seen = bp.language_style
            bp.language_style = seen
        if bp.language_preference != "auto":
            # What the owner asked for wins over how this one message was written.
            bp.language_style = bp.language_preference
        _validate_extraction(ti)
        _contextual_signals(bp, ti, text)
        if not field:
            _read_for_question(bp, ti, text, answering_targets, reading, model_ok=fallback is None)
        answering_name = bool(bp.asks) and bp.asks[-1].ask == "name"
        named_now = not field and _capture_name(bp, ti, text, answering_name)
        if named_now:
            understood_name = 1
        else:
            understood_name = 0
        kind_note = "" if field else _update_category(bp, text)
        if kind_note:
            # "No, actually we're a physiotherapy centre" is a correction, not a "no".
            reading.decline = False
            understood_name += 1
        # This check applies even if the model misclassifies a common off-topic query.
        off_topic = ti.off_topic or bool(re.search(
            r"\b(weather|tell me a joke|who is the president|who won|cricket match|"
            r"write (?:a|some) code|ignore .*instructions)\b",
            text, re.I,
        ))
        meta = "" if field or off_topic else _meta_question(text)
        signal = ti.owner_signal
        if signal == "none":
            signal = "wants_to_finish" if reading.finish else "redundant" if reading.redundant else "none"
        if reading.refine:
            bp.refining = True
        understood = understood_name
        media_note = ""
        # With no model, every fact is the owner's own words read by rule.
        source = "USER_STATEMENT" if field or fallback else "AI_EXTRACTION"
        # What a correction changes is said back ("Updated — hours: …").
        said_before = {k: f.value for k, f in {**bp.known_facts, **bp.unconfirmed_facts}.items() if k in UPDATED_FACT}
        from platform_core.interview.understanding import offer_groups

        groups_before = {g["name"].casefold() for g in offer_groups(bp)}
        if not off_topic and not meta:
            understood += _merge_facts(bp, ti, text, source)
            if field:
                target = next((t for t in TARGETS if t.fact == field), None)
                if target:
                    ti.answered.append(TargetAnswer(target=target.id, quote=text[:600],
                                                    summary=text[:240]))
            understood += accept_answers(bp, ti.answered, text, source=source)
            # Unknown intents are retained as evidence, NEVER interpreted as module IDs.
            from platform_core.interview.capabilities import canonical_intent

            for intent in ti.intents:
                if intent.original_request.strip() and intent.original_request in text:
                    intent = intent.model_copy(update={"intent": canonical_intent(intent.intent)})
                    if intent not in bp.requested_capabilities:
                        bp.requested_capabilities.append(intent)
                        understood += 1
            bp.requested_capabilities = bp.requested_capabilities[-40:]
            understood += accept_patterns(bp, ti.operating_patterns, text)
            accept_highlights(bp, ti.highlights, text)
            for wish in reading.content:
                if all(wish.casefold() != w.casefold() for w in bp.content_wishes):
                    bp.content_wishes = (bp.content_wishes + [wish])[-8:]
                    understood += 1
            if signal == "redundant":
                mark_redundant(bp)
                understood += 1
            media_note = _record_media_intent(bp, ti.media_intent, image_available)
            if media_note:
                understood += 1
            if govern_draft(bp, ti.draft, text):
                understood += 1
            from platform_core.interview.taxonomy import govern_catalogue, taxonomy_from_listing

            proposals = list(ti.catalogue)
            if not proposals:
                # No reading from the model: the owner's own list, one group per phrase.
                proposals = [
                    GroupProposal(group=g.name, unknown=["varieties"] if "varieties" in g.needs else [])
                    for fact in ti.facts if fact.field == "offerings" and fact.quote in text
                    for g in taxonomy_from_listing(fact.quote)
                ]
            if govern_catalogue(bp, proposals, text):
                understood += 1
            # A typed menu or price list ("Idli 40, Dosa 70"), and what the
            # owner says about it ("all veg", "biryani sells the most"), read
            # by rule — the whole list is kept, with or without the model.
            from platform_core.interview.catalogue_capture import capture

            if capture(bp, text, answering_targets):
                understood += 1
        BusinessInterviewOrchestrator.project(bp, business_type)

        lang = _lang(bp.language_style)
        ack = (REDUNDANT[lang] if signal == "redundant" and not govern_acknowledgement(ti.acknowledgement, text)
               else acknowledgement(bp, ti.acknowledgement, text, bp.language_style))
        from platform_core.interview.understanding import place_noun, read_back

        said_now = {k: f.value for k, f in {**bp.known_facts, **bp.unconfirmed_facts}.items() if k in UPDATED_FACT}
        changed = [k for k in UPDATED_FACT if said_before.get(k) and said_now.get(k) and said_now[k] != said_before[k]]
        if changed and not off_topic and signal != "redundant":
            words = UPDATED_FACT[changed[0]]
            ack = FACT_UPDATED[lang].format(what=words.get(lang, words["en"]), value=said_now[changed[0]][:160])
        opening_answer = bool(bp.asks) and bp.asks[-1].ask == "opening"
        if opening_answer and lang == "en" and not off_topic and understood:
            # Understand first: say back what the business is before asking
            # anything. It is the first summary, so the next comes later.
            said_back = read_back(bp, "first")
            if said_back:
                ack = said_back
                bp.synthesis_turn = bp.turn_count + 1
        if kind_note and not opening_answer:
            ack = kind_note
        elif named_now and answering_name:
            ack = NAME_THANKS[lang].format(name=bp.identity["display_name"].value)
        # The name is asked once, right after the first answer and before the
        # checkpoint — the website cannot be built without one.
        # Asked once; asked once more if the reply said something else instead
        # ("weekend la 11 varaikum open") — kept, and the name is still needed.
        name_asks = sum(1 for a in bp.asks if a.ask == "name")
        ask_name = bp.name_pending and not off_topic and (
            (name_asks == 0 and not answering_name) or (answering_name and name_asks < 2))
        name_question = planner.NAME_QUESTION[lang].format(noun=place_noun(bp)) if ask_name else ""
        next_item: planner.Ranked | None = None
        question = ""
        asked_name = False
        added = [g["name"] for g in offer_groups(bp) if g["name"].casefold() not in groups_before]
        if meta:
            answer = _answer_meta(bp, meta, lang, business_type)
            pending = ""
            if not built and not bp.readiness.ready:
                next_item = planner.choose(bp, "", business_type)
                pending = planner.phrase(next_item.ask, bp, lang) if next_item else ""
            elif not built:
                pending = planner.READY_AGAIN[lang]
            reply = " ".join(p for p in (answer, pending) if p)
        elif built and not off_topic:
            reply = " ".join(p for p in (ack if understood else "", media_note,
                                         planner.UPDATED[lang] if understood else planner.HELP_EDIT[lang]) if p)
        elif name_question and signal != "wants_to_finish":
            reply = " ".join(p for p in (ack, media_note, name_question) if p)
            asked_name = True
        elif off_topic:
            next_item = planner.choose(bp, "", business_type) if not bp.readiness.ready else None
            question = planner.phrase(next_item.ask, bp, lang) if next_item else ""
            reply = REDIRECT[lang] + question
        elif signal == "wants_to_finish" and bp.name_pending:
            reply = planner.NEED_ONE_MORE[lang] + planner.NAME_QUESTION[lang].format(noun=place_noun(bp))
            asked_name = True
        elif signal == "wants_to_finish":
            next_item = None if floor_met(bp, business_type) else planner.choose(bp, "", business_type)
            if next_item is None:
                bp.confirm_requested = True
                reply = planner.TO_CONFIRM[lang]
            else:
                reply = planner.NEED_ONE_MORE[lang] + planner.phrase(next_item.ask, bp, lang)
        elif bp.readiness.ready and bp.checkpoint_turn is None:
            bp.checkpoint_turn = bp.turn_count + 1
            worth = [w["short_ta" if lang == "ta" else "short"] for w in worth_knowing(bp, business_type, limit=3)]
            reply = " ".join(p for p in (ack, media_note, planner.checkpoint_message(bp, lang, worth)) if p)
        elif bp.readiness.ready:
            if bp.refining:
                next_item = planner.choose(bp, ti.next_target, business_type)
                question = _question(bp, ti, next_item, text, lang) if next_item else planner.NOTHING_LEFT[lang]
            elif added:
                # Say back what was added, by name ("Added sandwiches.").
                question = planner.ADDED_THESE[lang].format(items=_join_words(added[:4], lang)) + " " + \
                    planner.READY_AGAIN[lang]
            else:
                question = planner.AFTER_READY[lang] if understood else planner.READY_AGAIN[lang]
            opener = NO_PROBLEM[lang] if reading.decline and all(a.status == "declined" for a in ti.answered) else (
                ack if understood and not added else "")
            reply = " ".join(p for p in (opener, media_note, question) if p)
        else:
            next_item = planner.choose(bp, ti.next_target, business_type)
            if next_item is None and floor_met(bp, business_type):
                # Nothing left worth asking before a first version: that IS
                # enough. Never "build whenever you're ready" without a Build.
                bp.completion_state.ready_at = now()
                BusinessInterviewOrchestrator.project(bp, business_type)
                bp.checkpoint_turn = bp.turn_count + 1
                worth = [w["short_ta" if lang == "ta" else "short"] for w in worth_knowing(bp, business_type, limit=3)]
                reply = " ".join(p for p in (ack, media_note, planner.checkpoint_message(bp, lang, worth)) if p)
            else:
                question = _question(bp, ti, next_item, text, lang) if next_item else planner.phrase(
                    planner.ASKS_BY_ID["offer"], bp, lang)
                if next_item is None:
                    next_item = planner.Ranked(planner.ASKS_BY_ID["offer"], 0.0, "blocking")
                so_far = ""
                if understood and bp.turn_count + 1 - bp.synthesis_turn >= 2 and len(bp.asks) >= 2:
                    # The first mid-way summary is "the shape of it"; after that, short.
                    shaped = any(a.ask == "shape" for a in bp.asks) or "the shape of it" in " ".join(
                        m.text for m in bp.messages if m.role == "assistant")
                    so_far = planner.so_far_line(bp, lang, first_shape=not shaped)
                    if so_far:
                        bp.synthesis_turn = bp.turn_count + 1
                declined_only = reading.decline and all(a.status == "declined" for a in ti.answered)
                opener = NO_PROBLEM[lang] if declined_only else ack if understood else (
                    UNCLEAR[lang].strip() if not fallback else "")
                if so_far and opener and any(opener == a for options in ACKS.values() for a in options):
                    # The summary opens with its own "Okay —"; a stock "Understood." before it is one too many.
                    opener = ""
                reply = " ".join(p for p in (opener, media_note, so_far, question) if p)
        if asked_name:
            bp.asks = (bp.asks + [AskRecord(ask="name", targets=[], turn=bp.turn_count + 1)])[-60:]
        elif next_item:
            planner.record(bp, next_item.ask)
        elif bp.asks and bp.asks[-1].ask != "free":
            # No question this time: the next message answers nothing in
            # particular, and must not be read against the last question again.
            bp.asks = (bp.asks + [AskRecord(ask="free", targets=[], turn=bp.turn_count + 1)])[-60:]
        _remaining(bp)
        spoken: Literal["text", "voice"] = "voice" if via == "voice" else "text"
        bp.messages.extend([Message(role="user", text=said, via=spoken),
                            Message(role="assistant", text=reply, via=spoken)])
        bp.messages = bp.messages[-60:]
        bp.turn_count += 1
        usage = getattr(provider, "last_usage", None) or {}
        bp.last_turn = TurnTelemetry(
            provider="none" if field else provider.provider_name,
            model="deterministic" if field else str(usage.get("model") or provider.model_name),
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
            cost=usage.get("cost"), fallback_reason=fallback,
        )
        get_logger("business.interview").info(
            "interview.turn", business_id=str(bp.business_id), session_id=str(bp.session_id),
            turn_count=bp.turn_count, language=bp.language_style,
            next_ask=next_item.ask.id if next_item else None,
            ready=bp.readiness.ready, **bp.last_turn.model_dump(),
        )
        return bp

    @staticmethod
    def _language_turn(
        bp: BusinessBlueprint, text: str, *, business_type: str | None, via: str, started: float,
    ) -> BusinessBlueprint:
        """The owner asked to talk in another language and said nothing else.

        Say yes in that language and ask the question that is still open, in
        it. Nothing is extracted, nothing is answered, no question is skipped:
        the next message answers the same question it would have. Deterministic
        — no model call, so it works when the model does not.
        """
        from platform_core.interview.understanding import place_noun

        bp.language_style = bp.language_preference if bp.language_preference != "auto" else bp.language_style
        lang = _lang(bp.language_style)
        last = bp.asks[-1] if bp.asks else None
        if bp.completion_state.status == "built":
            question = planner.HELP_EDIT[lang]
        elif last is None or last.ask == "opening":
            question = BusinessInterviewOrchestrator.opening_question(bp)
        elif last.ask == "name":
            question = planner.NAME_QUESTION[lang].format(noun=place_noun(bp))
        elif last.ask in planner.ASKS_BY_ID:
            question = planner.phrase(planner.ASKS_BY_ID[last.ask], bp, lang)
        elif bp.readiness.ready:
            question = planner.AFTER_READY[lang]
        else:
            # Nothing was pending: what Locah would ask next, now asked in it.
            item = planner.choose(bp, "", business_type)
            question = planner.phrase(item.ask, bp, lang) if item else planner.NOTHING_LEFT[lang]
            if item:
                planner.record(bp, item.ask)
        reply = f"{LANGUAGE_SWITCHED[lang]} {question}".strip()
        spoken: Literal["text", "voice"] = "voice" if via == "voice" else "text"
        bp.messages.extend([Message(role="user", text=text, via=spoken),
                            Message(role="assistant", text=reply, via=spoken)])
        bp.messages = bp.messages[-60:]
        bp.turn_count += 1
        bp.last_turn = TurnTelemetry(provider="none", model="deterministic",
                                     latency_ms=int((time.monotonic() - started) * 1000))
        get_logger("business.interview").info(
            "interview.language_switched", business_id=str(bp.business_id), session_id=str(bp.session_id),
            turn_count=bp.turn_count, language=bp.language_style)
        return bp

    @staticmethod
    def refine(bp: BusinessBlueprint, business_type: str | None = None) -> BusinessBlueprint:
        """"Keep refining first": the next most useful question, asked now."""
        bp = bp.model_copy(deep=True)
        bp.refining = True
        bp.confirm_requested = False
        BusinessInterviewOrchestrator.project(bp, business_type)
        lang = _lang(bp.language_style)
        item = planner.choose(bp, "", business_type)
        if item:
            planner.record(bp, item.ask)
            text = planner.phrase(item.ask, bp, lang)
        else:
            text = planner.NOTHING_LEFT[lang]
        bp.messages = (bp.messages + [Message(role="assistant", text=text)])[-60:]
        return bp

    @staticmethod
    async def regenerate_draft(
        bp: BusinessBlueprint,
        field: str,
        offering_name: str = "",
        *,
        provider: AIModelProvider | None = None,
        business_type: str | None = None,
    ) -> BusinessBlueprint:
        """Rewrite one piece of website wording because the owner asked to."""
        from platform_core.interview.website_brief import build_brief

        bp = bp.model_copy(deep=True)
        provider = provider or get_ai_provider()
        wd = bp.website_draft
        facts = {**bp.known_facts, **bp.unconfirmed_facts}
        payload = {
            "business_name": bp.identity["display_name"].value if "display_name" in bp.identity else "",
            "known": {k: v.value[:400] for k, v in facts.items()},
            "brief": build_brief(bp, business_type).model_dump(exclude_defaults=True),
            "rewrite": field if field != "offering" else f"offerings: {offering_name}",
            "current": (getattr(wd, field).text if field != "offering" and getattr(wd, field) else ""),
        }
        prompt = (
            "Rewrite ONE piece of website wording for this small business: the field named in "
            "`rewrite`. Return JSON with only that field filled (for an offering, one item with "
            "the same name and a new one-sentence description). Make it clearly different from "
            "`current`, specific and warm. Never add facts the owner did not give — no prices, "
            "hours, years, certifications, 'fresh', 'farm', 'organic', 'premium', delivery, "
            "ratings — except lines in brief.owner_claims. No 'Welcome to'."
        )
        try:
            raw = await asyncio.wait_for(provider.generate_structured(
                json.dumps(payload, ensure_ascii=False), DraftUpdate.model_json_schema(),
                {"purpose": "business.interview", "system_prompt": prompt,
                 "max_output_tokens": 1500, "temperature": 0.7},
                timeout_seconds=20,
            ), timeout=21)
            proposal = DraftUpdate.model_validate(raw)
        except Exception as exc:
            raise ValueError("Locah couldn't rewrite that just now — try again in a moment.") from exc
        only = DraftUpdate()
        if field == "offering":
            only.offerings = [o for o in proposal.offerings if o.name.casefold() == offering_name.casefold()]
            for offering in wd.offerings:
                if offering.name.casefold() == offering_name.casefold() and offering.description:
                    offering.description = offering.description.model_copy(update={"provenance": "ai_suggestion"})
        else:
            setattr(only, field, getattr(proposal, field))
            wd.dismissed = [f for f in wd.dismissed if f != field]
            current = getattr(wd, field)
            if current is not None:  # the owner asked, so their lock is lifted for this field
                setattr(wd, field, current.model_copy(update={"provenance": "ai_suggestion"}))
        govern_draft(bp, only, "")
        return bp


def _capture_name(bp: BusinessBlueprint, ti: TurnIntelligence, text: str, answering: bool) -> bool:
    """Keep the business's name when the owner says it — only then."""
    if not bp.name_pending:
        return False
    said = ti.business_name.strip()
    candidate = said if said and said.casefold() in text.casefold() else ""
    candidate = candidate or rd.business_name(text)
    reading = rd.read(text)
    if not candidate and answering and not (reading.finish or reading.refine or reading.decline):
        # Answering "What's it called?": the reply is the name.
        short = re.sub(r"^\s*(?:it'?s|it is|we'?re|we are|the name is|name is|called|its)\s+", "",
                       text.strip(), flags=re.I).strip(" .!\"'“”")
        # Not a name: hours ("weekend la 11 varaikum open"), how people pay,
        # or how orders reach them — those answer something else.
        if (1 <= len(short.split()) <= 6 and len(short) <= 60 and not rd.read(short).decline
                and not rd.canonical_actions(short) and not rd.phone_number(short)
                and not rd.looks_like_hours(short) and not rd.hours_clause(short)
                and not rd.payment_methods(short) and not rd.fulfilment_modes(short)):
            candidate = short
    if not candidate:
        return False
    bp.identity["display_name"] = Fact(value=candidate[:120], source="USER_STATEMENT",
                                       confirmation="unconfirmed", evidence=text[:400])
    bp.name_pending = False
    return True


def _update_category(bp: BusinessBlueprint, text: str) -> str:
    """Read what kind of business this is from what the owner says.

    An owner-picked category stands unless the owner plainly corrects it ("no,
    actually we're mainly a physiotherapy centre"); an inferred one follows
    what they describe. Returns the line to say when the owner corrected it.
    """
    from platform_core.catalog.taxonomy import SUBCATEGORIES, infer_from_text
    from platform_core.interview.models import CategorySeed
    from platform_core.interview.understanding import kind_phrase

    def seed(key: str, source: Literal["owner_picked", "inferred"]) -> CategorySeed:
        category, sub = SUBCATEGORIES[key]
        return CategorySeed(category_key=category.key, subcategory_key=sub.key, label=sub.label,
                            source=source, group=category.label)

    current = bp.category
    # The business's own name is not evidence of its kind: "Grit Barbell Club"
    # is a gym, not a powerlifting club, because the owner said "a gym".
    name = bp.identity["display_name"].value if "display_name" in bp.identity else ""

    def unnamed(words: str) -> str:
        return re.sub(re.escape(name), " ", words, flags=re.I) if name and not bp.name_pending else words

    text = unnamed(text)
    said_now = infer_from_text(text)
    if said_now and said_now[1] >= 0.72 and rd.corrects_kind(text) and (
            current is None or current.subcategory_key != said_now[0]):
        bp.category = seed(said_now[0], "owner_picked")
        if current is None:
            return ""
        lang = _lang(bp.language_style)
        return KIND_UPDATED[lang].format(kind=kind_phrase(bp) if lang == "en" else bp.category.label)
    if current is None:
        # Read once, from what they have said so far; after that the kind only
        # changes when the owner corrects it — a later answer that mentions
        # "textile mills" (their customers) or "book a site visit" (a verb)
        # must not turn a pump supplier into a clothes shop or a bookshop.
        said = " ".join([unnamed(m.text) for m in bp.messages if m.role == "user"][:3] + [text])
        guess = infer_from_text(said)
        if guess and guess[1] >= 0.72:
            bp.category = seed(guess[0], "inferred")
    return ""


def _remaining(bp: BusinessBlueprint) -> None:
    """The business-truth fields the question on screen would fill — only that question.

    The old list was "the most valuable open fields", and a client used its
    first entry to save an answer to a *different* question: that is how a
    delivery area became opening hours.
    """
    facts = {**bp.known_facts, **bp.unconfirmed_facts}
    asked = planner.last_ask(bp)
    open_fields: list[Question] = []
    for target_id in (asked.targets if asked else ()):
        fact = next((t.fact for t in TARGETS if t.id == target_id), None)
        if fact and fact not in facts and all(q.field != fact for q in open_fields):
            open_fields.append(Question(field=fact, text=fallback_question(
                target_id, bp, bp.language_style), reason="The question just asked."))
    bp.remaining_questions = open_fields[:3]


def _question(
    bp: BusinessBlueprint, ti: TurnIntelligence, item: planner.Ranked, heard: str, lang: str
) -> str:
    """The model's wording when it proposed this very question and it reads well; else ours."""
    proposed = planner.ASKS_BY_ID.get(ti.next_target) or planner.ask_for_target(ti.next_target)
    if proposed and proposed.id == item.ask.id:
        governed = govern_question(ti.next_question, heard, bp)
        if governed and speaks(governed, bp.language_preference):
            return str(governed)
    return str(planner.phrase(item.ask, bp, lang))


# -------------------------------------------------------- semantic validation

# Slots whose value has a type the reader can check.
_TYPED_FACTS = {"opening_hours", "phone", "customer_actions", "locations"}
_TYPED_TARGETS = {"operations.hours", "contact.phone", "commerce.action", "contact.location",
                  "fulfilment.mode", "commerce.payment", "offerings.units"}


def _validate_extraction(ti: TurnIntelligence) -> None:
    """Drop what the model filed under the wrong kind of slot.

    "All india" is never opening hours, "Freshness and energy" never a phone
    number, "Gym equipment, dumbbells, contact section" never what a customer
    does. Better unknown than wrong: an unknown piece is asked, a wrong one is
    shown to the owner and built into their website.
    """
    ti.facts = [f for f in ti.facts if f.field not in _TYPED_FACTS or rd.valid_for(f.field, f.quote)]
    kept: list[TargetAnswer] = []
    for answer in ti.answered:
        evidence = answer.quote or answer.summary
        if answer.status == "declined" or answer.target not in _TYPED_TARGETS or rd.valid_for(answer.target, evidence):
            kept.append(answer)
    ti.answered = kept


def _answered(ti: TurnIntelligence, target: str) -> bool:
    return any(a.target == target for a in ti.answered)


# Questions whose answer is the owner's own sentence, with no type to check.
_FREE_TEXT = frozenset({
    "brand.story", "memberships.plans", "bookings.format", "b2b.customers", "b2b.process",
    "offerings.customisation", "services.providers", "operations.team", "operations.stock",
    "fulfilment.operator", "offerings.pricing",
})


def _read_for_question(
    bp: BusinessBlueprint,
    ti: TurnIntelligence,
    text: str,
    targets: tuple[str, ...],
    reading: rd.Reading,
    *,
    model_ok: bool,
) -> None:
    """Understand the answer as an answer to the question actually asked.

    With the model working this fills only what it missed; without it, this
    is the understanding. Every value is checked for its type first, so an
    answer is never filed under a question it does not answer.
    """
    words = re.findall(r"\w+", text)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if s]

    def answer(target: str, summary: str, status: str = "answered", evidence: str = "") -> None:
        # The evidence is the part of the message that answers THIS target — a
        # whole opening paragraph must never become the customer actions.
        if not _answered(ti, target):
            ti.answered.append(TargetAnswer(target=target, quote=(evidence or text)[:600],
                                            summary=summary[:240], status=status))

    def fact(field: str, value: str, mode: str = "replace") -> None:
        if value and value in text and not any(f.field == field for f in ti.facts):
            ti.facts.append(ExtractedFact(field=field, quote=value, mode=mode))

    def sentence_with(pattern_check: Any) -> str:
        return next((s for s in sentences if pattern_check(s)), "")

    # A phone number is a phone number whatever was asked.
    if reading.phone and not any(f.field == "phone" for f in ti.facts):
        digits = rd.phone_number(text)
        raw = next((m.group(0).strip() for m in rd._PHONE.finditer(text)
                    if re.sub(r"\D", "", m.group(0)).endswith(digits)), "")
        if raw:
            fact("phone", raw)
            answer("contact.phone", "Your number", evidence=raw)
    # Opening hours are opening hours whatever was asked ("Open 5:30 am to
    # 10 pm every day" once became the gym's membership plans).
    if not _answered(ti, "operations.hours") and not any(f.field == "opening_hours" for f in ti.facts):
        # Only the part that gives the hours ("open 9 to 10"), not the whole
        # opening message; a correction ("on weekends we're open till 11") too.
        said = rd.hours_clause(text)
        if said and rd.valid_for("operations.hours", said):
            fact("opening_hours", said)
            answer("operations.hours", said[:120], evidence=said)
    if reading.finish or (reading.decline and not reading.phone):
        # "No, just this much" / "skip" — the pieces just asked are declined, not answered.
        if reading.decline and not reading.finish:
            for target in targets[:2]:
                if not _answered(ti, target) and target not in {"business.identity"}:
                    answer(target, "", status="declined")
        return
    def offer(names: list[str], groups: list[tuple[str, list[str]]]) -> bool:
        """What is sold, as groups with their items when the owner listed them."""
        if groups:
            if not ti.catalogue:
                ti.catalogue = [GroupProposal(group=g, items=[ItemProposal(name=i) for i in items])
                                for g, items in groups]
            if not _answered(ti, "offerings.main"):
                fact("offerings", text if len(text) <= 400 else ", ".join(g for g, _ in groups), mode="add")
                answer("offerings.main", ", ".join(g for g, _ in groups))
            if not _answered(ti, "offerings.structure"):
                answer("offerings.structure",
                       "; ".join(f"{g}: {', '.join(items[:4])}" for g, items in groups))
            return True
        if names:
            if not ti.catalogue:
                ti.catalogue = [GroupProposal(group=n) for n in names][:12]
            clause = next((m.group(0) for m in rd._OFFER_STATEMENT.finditer(" ".join(text.split()))), "")
            evidence = clause if clause and clause in text else text
            fact("offerings", evidence, mode="add")
            answer("offerings.main", ", ".join(names), evidence=evidence)
            return True
        return False

    understood_any = False
    lead = targets[0] if targets else ""
    for target in targets:
        if _answered(ti, target):
            understood_any = True
            continue
        if target == "commerce.action" and reading.actions:
            evidence = rd.action_sentences(text)
            fact("customer_actions", evidence, mode="add")
            answer(target, ", ".join(rd.action_labels(reading.actions)), evidence=evidence)
        elif target == "fulfilment.mode" and reading.fulfilment:
            answer(target, ", ".join(reading.fulfilment),
                   evidence=sentence_with(rd.fulfilment_modes) or text)
        elif target == "fulfilment.area" and (
                area := rd.service_area(text) if lead == "fulfilment.area" else rd.service_area_said(text)) and (
                reading.fulfilment or lead == "fulfilment.area" or "fulfilment.mode" in targets):
            # Asked "where do you deliver?", the whole reply is the area;
            # otherwise only a place named after a delivery verb is.
            answer(target, area)
        elif target == "contact.location" and rd.location_text(text):
            place = rd.location_text(text)
            if place in text:
                fact("locations", place)
            answer(target, place, evidence=place)
        elif target == "commerce.payment" and reading.payment:
            answer(target, ", ".join(reading.payment), evidence=sentence_with(rd.payment_methods) or text)
        elif target == "offerings.units" and reading.units:
            answer(target, "By the kg" if reading.units == "weight" else "In fixed packs",
                   evidence=sentence_with(rd.units) or text)
        elif target == "operations.hours" and (rd.looks_like_hours(text) or hours.parse(text, asked=True)):
            # The answer to "when are you open?" — a bare "10 to 6" included.
            said = rd.hours_clause(text) or text
            fact("opening_hours", said)
            answer(target, said[:120], evidence=said)
        elif target in {"offerings.main", "offerings.structure"} and lead in {"offerings.main", "offerings.structure"} \
                and not model_ok:
            if not offer(rd.offer_statement(text) or rd.offering_names(text), rd.group_items(text)):
                continue
        elif target in _FREE_TEXT and target == lead and not text.rstrip().endswith("?") \
                and len(words) >= (2 if not model_ok else 3) \
                and not (rd.looks_like_hours(text) and _answered(ti, "operations.hours")):
            # (A reply that is the opening hours answers the hours, not the plans.)
            # A real reply to the question just asked answers it, even when the
            # model filed it elsewhere — the gym was asked "what do people book?"
            # twice. Only for questions whose answer is free text.
            answer(target, text[:240])
        else:
            continue
        understood_any = True
    # What the owner volunteered beyond the question — only the unambiguous
    # kinds, so an answer is never stretched to fit a question it didn't answer.
    if reading.fulfilment and not _answered(ti, "fulfilment.mode") and re.search(
            r"\b(we|i|people|customers|they|you can|naan|naanga|pannuvom|pannurom|panrom|pannuvaanga|"
            r"irukk?u|kudupp?om)\b|\bonly\b", text, re.I):
        said = sentence_with(rd.fulfilment_modes) or text
        answer("fulfilment.mode", ", ".join(reading.fulfilment), evidence=said)
        # Volunteered, so only an area named after a delivery verb counts: the
        # opening "I run Nila Cafe in Anna Nagar, … pickup and delivery" names
        # where the café is, not where it delivers.
        area = rd.service_area_said(said)
        if area and "delivery" in reading.fulfilment and not _answered(ti, "fulfilment.area"):
            answer("fulfilment.area", area, evidence=said)
        understood_any = True
    if reading.payment and not _answered(ti, "commerce.payment") and (
            "commerce.payment" in targets or re.search(r"\b(pay|payment|upi|cash|cod|gpay)\b", text, re.I)):
        answer("commerce.payment", ", ".join(reading.payment), evidence=sentence_with(rd.payment_methods) or text)
        understood_any = True
    if reading.units == "weight" and not _answered(ti, "offerings.units"):
        answer("offerings.units", "By the kg", evidence=sentence_with(rd.units) or text)
        understood_any = True
    known_action = (bp.discovery.get("commerce.action") or TargetState()).status == "answered"
    if reading.actions and not known_action and not _answered(ti, "commerce.action"):
        # "Select meat, select kg and order" says what customers do, whatever was asked.
        evidence = rd.action_sentences(text)
        fact("customer_actions", evidence, mode="add")
        answer("commerce.action", ", ".join(rd.action_labels(reading.actions)), evidence=evidence)
        understood_any = True
    if not model_ok and lead not in {"offerings.main", "offerings.structure"} and rd.group_items(text):
        # "Chicken - curry cut, boneless. Mutton - chops" is the range, whatever was asked.
        understood_any = offer([], rd.group_items(text)) or understood_any
    if not model_ok and lead not in {"offerings.main", "offerings.structure", "business.identity"}:
        # Explicit additions to the range are accepted whatever question was
        # pending. A bare noun answer still belongs only to an offerings ask.
        volunteered = rd.offer_statement(text) or rd.ta_offer_list(text)
        if volunteered:
            understood_any = offer(volunteered, rd.group_items(text)) or understood_any
    has_place_cue = re.search(r"\b(located|based|we are in|we're in|shop is (?:in|at|on)|address)\b", text, re.I)
    if not _answered(ti, "contact.location") and lead != "contact.location" and (
            has_place_cue or (reading.phone and rd._PLACE_WORDS.search(text))):
        place = rd.location_text(re.split(r"(?<=[.!?])\s+", text)[0] if not has_place_cue else text)
        if place and place in text:
            fact("locations", place)
            answer("contact.location", place, evidence=place)
            understood_any = True
    if not model_ok and lead == "business.identity":
        # The opening answer with no model: the owner's own description, what
        # they said they sell and what customers do.
        sentence = sentences[0] if sentences else text
        if sentence in text:
            fact("description", sentence[:400])
        answer("business.identity", sentence[:240], evidence=sentence)
        # "…a South Indian restaurant in Anna Nagar." — a capitalised place after "in".
        placed = re.search(r"\b(?:in|at|near)\s+([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,3})", " ".join(sentences[:2]))
        # …or in Tanglish, "Anna Nagar la".
        place = rd.location_text(placed.group(1)) if placed else rd.place_ta(" ".join(sentences[:2]))
        if place and place in text and not _answered(ti, "contact.location"):
            fact("locations", place)
            answer("contact.location", place, evidence=place)
        offer(rd.offer_statement(text) or rd.ta_offer_list(text), rd.group_items(text))
        if reading.actions and not _answered(ti, "commerce.action"):
            evidence = rd.action_sentences(text)
            fact("customer_actions", evidence, mode="add")
            answer("commerce.action", ", ".join(rd.action_labels(reading.actions)), evidence=evidence)


_GENERATE = re.compile(r"\b(generate|create|make|design|draw)\b.{0,20}\b(one|it|logo|for me)?", re.I)
_DECLINE = re.compile(r"^\s*(no|nope|skip|later|not now|don'?t know|no idea|nothing|illa|venaam)\b", re.I)
_YES = re.compile(r"^\s*(yes|yeah|yep|sure|ok(?:ay)?|please|go ahead|do it|seri|aamaa|ama|haan)\b", re.I)
_OWN_PHOTOS = re.compile(
    r"\b(i (?:have|'ll|will) (?:upload|send|share|add)|i have (?:photos|pictures|pics)|will upload)\b",
    re.I)
# "I have a menu / our price list / a brochure" — attach it, don't retype it.
_OWN_DOCUMENT = re.compile(
    r"\b(?:i|we)\s+(?:have|'ve got|got|can send|will send|can share)\s+(?:a|an|our|my|the)?\s*"
    r"(?:printed\s+|pdf\s+|full\s+)?(?:menu|menu card|catalogue|catalog|brochure|price ?list|rate ?card|rate list)\b",
    re.I)
# An explicit wish for a site WITHOUT generated pictures. "I don't have photos"
# is not this: an owner with no photos is exactly who draft visuals are for.
_TEXT_LED = re.compile(
    r"\b(?:no (?:pictures|images|visuals|photos) at all|without (?:any )?(?:pictures|images|visuals|photos)|"
    r"text[- ]only|only text|just text|text[- ]led|keep it (?:simple|plain) without|"
    r"(?:don'?t|do not|no need to|never)\b[^.]{0,20}\b(?:create|generate|make|draw|use)\b[^.]{0,20}"
    r"\b(?:pictures|images|visuals|photos|ai))\b",
    re.I)


def _contextual_signals(bp: BusinessBlueprint, ti: TurnIntelligence, text: str) -> None:
    """Read a short reply to a picture question in the light of that question."""
    asked = set(bp.asks[-1].targets) if bp.asks else set()
    if "media.logo" in asked and ti.media_intent == "none" and _GENERATE.search(text):
        ti.media_intent = "generate_logo"
    text_led = bool(_TEXT_LED.search(text))
    if ti.media_intent == "no_visuals" and not text_led:
        # "No, I don't have photos" is a yes to drafts: only an explicit wish for
        # a text-led site switches pictures off.
        ti.media_intent = "generate_visuals"
    if text_led and ti.media_intent == "none":
        # An explicit "text only, no pictures" counts whenever it is said.
        ti.media_intent = "no_visuals"
    if ti.media_intent == "none" and _OWN_DOCUMENT.search(text) and not any(
            d.status in {"reading", "ready", "applied"} for d in bp.documents):
        ti.media_intent = "will_upload_catalogue"
    if "media.photos" in asked and ti.media_intent == "none":
        if _OWN_PHOTOS.search(text):
            ti.media_intent = "will_upload_photos"
        elif _YES.search(text) or _GENERATE.search(text) or _DECLINE.search(text):
            # "yes, create them", "no photos yet", "nothing" — all mean: draw drafts.
            ti.media_intent = "generate_visuals"


def _merge_facts(bp: BusinessBlueprint, ti: TurnIntelligence, text: str, source: str) -> int:
    accepted = 0
    # A clear spoken "Coimbatore, not Chennai" is a location correction even
    # when the extractor filed the sentence as a new description and the old
    # city lived only inside that description.
    correction = re.search(
        r"\b(?P<new>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*,\s*not\s+"
        r"(?P<old>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",
        text,
    )
    if correction:
        _remove_superseded_location_echoes(bp, correction.group("old"))
        ti.facts = [item for item in ti.facts if item.field != "locations"]
        ti.facts.append(ExtractedFact(field="locations", quote=correction.group("new")))
    for item in ti.facts:
        if item.quote not in text:
            continue
        if correction and item.field == "description" and correction.group(0) in item.quote:
            prefix = item.quote.split(", not " + correction.group("old"), 1)[0]
            prefix = re.sub(r"^(?:Correction,\s*|Actually\s+)", "", prefix, flags=re.I)
            if " is in " not in prefix or prefix not in text:
                continue
            item = ExtractedFact(field="description", quote=prefix, mode="replace")
        # An unsupported workflow (live GPS tracking) stays as capability-gap
        # evidence and never becomes website content.
        if re.search(
            r"\b(?:gps|live\s+(?:\w+\s+)?track\w*|track\w*\s+live|courier.{0,40}\bmap)\b",
            item.quote, re.I,
        ):
            continue
        # Where the business delivers is not where it is: "we deliver around
        # Nookampalayam and Perumbakkam" once became part of the shop's address.
        if item.field == "locations" and (
            any(a.target == "fulfilment.area" and item.quote.casefold() in (a.quote or "").casefold()
                for a in ti.answered)
            or re.search(r"\b(?:deliver\w*|ship\w*)\b[^.]{0,60}" + re.escape(item.quote), text, re.I)
        ):
            continue
        previous = bp.unconfirmed_facts.get(item.field) or bp.known_facts.get(item.field)
        if (
            item.field == "locations" and item.mode == "replace" and previous
            and previous.value.casefold() != item.quote.casefold()
        ):
            _remove_superseded_location_echoes(bp, previous.value)
        if merge_fact(bp, item.field, item.quote, item.mode, source):
            accepted += 1
    return accepted


def _defer_open_targets(bp: BusinessBlueprint, business_type: str | None) -> None:
    """"That's all, build it" — the owner decides when enough is enough."""
    for item in planner.rank(bp, business_type):
        for target in item.ask.targets:
            state = bp.discovery.setdefault(target, TargetState())
            if state.status in {"open", "asked"}:
                state.status = "deferred"


def _record_media_intent(bp: BusinessBlueprint, intent: str, image_available: bool) -> str:
    """Record a request to draw something, and say what will happen — specifically."""
    name = bp.identity["display_name"].value if "display_name" in bp.identity else "your business"
    lang = _lang(bp.language_style)
    logo = bp.discovery.setdefault("media.logo", TargetState())
    if intent == "will_upload_logo":
        logo.status = "answered"
        logo.summary = "Will upload their own logo."
        return str(LOGO_UPLOAD[lang])
    if intent == "no_logo":
        logo.status = "declined"
        return ""
    if intent == "will_upload_catalogue":
        return str(DOCUMENT_UPLOAD[lang])
    if intent in {"generate_visuals", "will_upload_photos", "no_visuals"}:
        photos = bp.discovery.setdefault("media.photos", TargetState())
        photos.status = "answered" if intent != "no_visuals" else "declined"
        bp.visual_consent = {
            "generate_visuals": "draft_visuals", "will_upload_photos": "own_photos",
            "no_visuals": "none",
        }[intent]
        photos.summary = {
            "generate_visuals": "Locah will create draft visuals you can replace with real photos.",
            "will_upload_photos": "You'll add your own photos; Locah fills any gap with drafts until then.",
            "no_visuals": "A text-led website, without generated pictures.",
        }[intent]
        if intent == "generate_visuals" and image_available:
            return str(VISUALS_QUEUED[lang])
        return ""
    role = {"generate_logo": "logo", "generate_hero": "hero"}.get(intent)
    if role is None:
        return ""
    if role == "logo":
        logo.status = "answered"
        logo.summary = "Wants Locah to create a logo."
    if any(m.role == role and m.source == "USER_UPLOAD" for m in bp.media_assets):
        return ""
    existing = next((r for r in bp.media_generation_requests if r.role == role), None)
    if existing and existing.status in {"requested", "queued", "ready"}:
        return LOGO_QUEUED[lang].format(name=name) if role == "logo" else ""
    bp.media_generation_requests = [r for r in bp.media_generation_requests if r.role != role]
    if image_available:
        bp.media_generation_requests.append(MediaGenerationRequest(role=role, status="requested"))
        if role == "logo":
            bp.logo_state = "generation_requested"
        return LOGO_QUEUED[lang].format(name=name) if role == "logo" else ""
    bp.media_generation_requests.append(MediaGenerationRequest(
        role=role, status="unavailable",
        reason="Image generation isn't available on this environment right now.",
    ))
    return LOGO_UNAVAILABLE[lang] if role == "logo" else ""


# ---------------------------------------------------------------- questions about the conversation
_RECAP = re.compile(
    r"\b(what (?:have|did) you (?:understood?|got|learn(?:ed|t)?|note[d]?)|what do you (?:know|have) "
    r"(?:about|so far)|summari[sz]e|recap|what('?s| is) (?:my|the) (?:info|details))\b"
    r"|enna purinjudhu|enna therinjudhu|ippo varaikkum enna|என்ன புரிஞ்சுது|என்ன புரிந்தது|இதுவரை என்ன",
    re.I)
_TOOLS = re.compile(
    r"\b((?:which|what) (?:tools?|modules?|features?)\b.*\b(?:help|need|use|should|recommend|useful)|"
    r"what should i (?:turn on|enable|switch on|use)|(?:recommend|suggest) (?:some )?(?:tools?|modules?|features?)|"
    r"which tools?|what tools?)"
    r"|enna tools?|edhu useful|என்ன கருவிகள்|எது பயனுள்ள",
    re.I)


def _meta_question(text: str) -> str:
    """'recap' or 'tools' when the owner asks about the conversation itself, else ''."""
    said = re.sub(r"^please\s+", "", " ".join(text.split()), flags=re.I)
    if len(said) > 160:
        return ""
    if _RECAP.match(said):
        return "recap"
    if _TOOLS.match(said):
        return "tools"
    return ""


def _join_words(items: list[str], lang: str) -> str:
    items = [i.lower() if i[:1].isupper() and len(i.split()) == 1 else i for i in items]
    if len(items) <= 1:
        return "".join(items)
    tail = " and " if lang == "en" else ", "
    return ", ".join(items[:-1]) + tail + items[-1]


RECAP_INTRO = {"en": "Here's what I have so far:", "ta_en": "Ippo varaikkum enakku therinjadhu:",
               "ta": "இதுவரை எனக்குத் தெரிந்தது:"}
RECAP_NOTHING = {"en": "I don't know much yet — tell me what your business does.",
                 "ta_en": "Innum adhigam theriyala — unga business enna pannudhu-nu sollunga.",
                 "ta": "இன்னும் அதிகம் தெரியலை — உங்க தொழில் என்ன செய்யுது-ன்னு சொல்லுங்க."}
TOOLS_INTRO = {"en": "From what you've told me, these would help most:",
               "ta_en": "Neenga sonnadha vechu, idhu ellaam useful-aa irukkum:",
               "ta": "நீங்க சொன்னதை வைத்து, இவை உதவும்:"}
TOOLS_NOTHING = {"en": "Tell me a little more about how customers buy from you, and I'll suggest the tools that fit.",
                 "ta_en": "Customers eppadi vaanguvaanga-nu konjam sollunga, appo sariyaana tools sollren.",
                 "ta": "வாடிக்கையாளர்கள் எப்படி வாங்குவாங்க-ன்னு கொஞ்சம் சொல்லுங்க, பொருத்தமான கருவிகளைச் சொல்றேன்."}
TOOLS_AFTER = {"en": "Nothing turns on until you choose it in Tools.",
               "ta_en": "Neenga Tools-la choose pannaama edhuvum on aagaadhu.",
               "ta": "நீங்க தேர்ந்தெடுக்காம எதுவும் இயங்காது."}


def _answer_meta(bp: BusinessBlueprint, meta: str, lang: str, business_type: str | None) -> str:
    """Answer "what have you understood?" and "which tools would help?" from what
    is actually known — never by guessing, never by switching anything on."""
    from platform_core.interview.understanding import read_back, synthesis

    if meta == "recap":
        said = read_back(bp, "checkpoint") if lang == "en" else ""
        said = said or synthesis(bp, lang)
        if not said:
            return RECAP_NOTHING[lang]
        name = bp.identity.get("display_name")
        if name and name.value and name.value not in said:
            said = f"{name.value} — {said}"
        facts = {**bp.known_facts, **bp.unconfirmed_facts}
        extra = []
        hours = facts.get("opening_hours")
        if hours and hours.value and lang == "en":
            extra.append(f"Hours: {hours.value}.")
        return " ".join([RECAP_INTRO[lang], said.rstrip(".") + "."] + extra)
    from platform_core.interview.capabilities import FRIENDLY, ModuleRegistry, recommend

    picks = [(r.label, r.reason, r.strength) for r in bp.recommended_modules
             if r.choice != "declined" and r.strength != "dependency"]
    if not picks:
        # The API fills entitlement-aware cards after a turn. During the turn,
        # use the same evidence reader for advice, without claiming activation
        # or changing any previously declined choice.
        picks = [(FRIENDLY.get(key, definition.display_name), reason, strength)
                 for key, (strength, reason, _, _) in recommend(bp, business_type).items()
                 if key not in bp.declined_modules and (definition := ModuleRegistry.get(key))]
    picks.sort(key=lambda r: 0 if r[2] == "strong" else 1)
    if not picks:
        return TOOLS_NOTHING[lang]
    lines = [f"{label} — {reason.rstrip('.')}." if lang == "en" else label
             for label, reason, _ in picks[:3]]
    return " ".join([TOOLS_INTRO[lang], " ".join(lines) if lang == "en" else ", ".join(lines) + ".",
                     TOOLS_AFTER[lang]])
