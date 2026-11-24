"""An owner changes their website by saying so (website.site_assistant).

Every change is made through the same services the editor's own controls
call — the theme merge, a section patch, reorder, duplicate, remove, add — so
permissions, validation, audit and "only the draft changes" are exactly the
editor's. The reply says what was done and, plainly, what was not.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.exceptions import ResourceNotFound, ValidationError
from platform_core.logging import get_logger
from platform_core.services.website import SectionService, WebsiteService, WebsiteVersionService
from platform_core.services.website_composition import WebsiteCompositionService
from platform_core.website import site_assistant as sa
from platform_core.website.owner_style import FONT_PAIRS

_log = get_logger("website.assistant")

_NAMES = {
    "hero": "the top of the page", "about": "your story", "media_text": "your story", "contact": "contact details",
    "cta_band": "the closing call to action", "product_showcase": "what you sell", "category_showcase": "categories",
    "gallery": "the gallery", "faq": "questions and answers", "reviews_section": "reviews",
    "fulfilment_strip": "how ordering works", "marquee": "the moving band of words", "highlights": "the numbers",
    "feature_grid": "what you do", "pillars": "what you stand for", "statement": "the statement",
    "location_list": "locations", "enquiry_form": "the enquiry form", "plans_section": "plans",
    "rooms_section": "rooms", "classes_section": "classes", "text_block": "the text", "menu_section": "the menu",
    "offerings_list": "what you offer",
}
_SIZE_WORDS = {"small": "smaller", "regular": "standard size", "large": "larger", "xlarge": "largest"}
CAN_DO = ("I can change colours, fonts, text size and corners; flip or re-arrange a section; move, hide, "
          "show, copy or remove a section; "
          "add a gallery, text, contact or enquiry section; change a headline or a button; or write a section again.")


_ROLE_NAMES = {"story": "your story", "statement": "the statement", "pillars": "what you stand for",
               "numbers": "the numbers", "featured": "your signature range"}


def _name(section: dict[str, Any]) -> str:
    if section.get("section_type_id") == "composition":
        return _ROLE_NAMES.get(str((section.get("content") or {}).get("role") or ""), "that section")
    return _NAMES.get(str(section.get("section_type_id")), str(section.get("section_type_id", "")).replace("_", " "))


# A composed section answers to the words for what it holds.
_ROLE_KINDS = {
    "story": {"about", "media_text"}, "statement": {"statement"}, "pillars": {"pillars", "feature_grid"},
    "numbers": {"highlights"}, "featured": {"product_showcase", "category_showcase", "menu_section",
                                            "offerings_list"},
}


def _is_kind(section: dict[str, Any], kind: str) -> bool:
    if section.get("section_type_id") == kind:
        return True
    role = str((section.get("content") or {}).get("role") or "")
    return section.get("section_type_id") == "composition" and kind in _ROLE_KINDS.get(role, set())


def _find(sections: list[dict[str, Any]], words: str, *, hidden: bool | None = None) -> dict[str, Any] | None:
    """The section on this page an owner's words mean."""
    pool = [s for s in sections if hidden is None or (s.get("is_visible") is False) == hidden] or sections
    for kind in sa.section_kinds(words):
        match = next((s for s in pool if _is_kind(s, kind)), None)
        if match:
            return match
    low = words.casefold().strip()
    if low:
        for section in pool:  # by its own heading: "the 'Why us' part"
            content = section.get("content") or {}
            heading = " ".join(str(content.get(k) or "") for k in ("title", "headline", "eyebrow")).casefold()
            if low and low in heading:
                return section
    return None


class WebsiteAssistantService:
    @staticmethod
    async def plan(message: str, *, use_model: bool = True) -> sa.Plan:
        """Rules first; the model only for what the rules left unread."""
        plan = sa.read(message)
        if not use_model or not plan.unclear:
            return plan
        try:
            from platform_core.website.ai_provider import get_ai_provider

            provider = get_ai_provider()
            raw = await provider.generate_structured(
                " ".join(plan.unclear)[:600], sa.MODEL_SCHEMA,
                {"purpose": "website.assistant", "schema_name": "locah_site_changes",
                 "system_prompt": sa.MODEL_SYSTEM, "max_output_tokens": 500, "temperature": 0},
                timeout_seconds=15)
        except Exception as exc:  # noqa: BLE001 — the rules' reading stands on its own
            _log.info("website.assistant.model_unavailable", error=type(exc).__name__)
            return plan
        extra = sa.from_model(raw)
        if extra.changes:
            plan.changes.extend(extra.changes)
            plan.unclear = extra.unclear
        elif extra.unclear:
            plan.unclear = extra.unclear
        return plan

    @staticmethod
    async def ask(
        session: AsyncSession,
        *,
        business_id: uuid.UUID,
        actor_id: uuid.UUID,
        message: str,
        page_id: uuid.UUID | None = None,
        use_model: bool = True,
    ) -> dict[str, Any]:
        message = " ".join((message or "").split())[:600]
        if not message:
            raise ValidationError("Say what you would like to change")
        plan = await WebsiteAssistantService.plan(message, use_model=use_model)
        aggregate = await WebsiteService.get_aggregate(session, business_id=business_id)
        pages = aggregate["draft"].get("pages") or []
        page = next((p for p in pages if page_id and str(p.get("id")) == str(page_id)), None) or next(
            (p for p in pages if p.get("slug") == "home"), pages[0] if pages else None)
        if page is None:
            raise ResourceNotFound("Website page")
        theme = dict(aggregate["draft"].get("theme") or {})
        done: list[str] = []
        not_done: list[str] = list(plan.unclear)
        theme_edit: dict[str, Any] = {}
        style_edit: dict[str, Any] = {}
        rewrite: list[str] = []
        structure = False

        async def sections() -> list[dict[str, Any]]:
            fresh = await WebsiteService.get_aggregate(session, business_id=business_id)
            current = next((p for p in fresh["draft"].get("pages") or [] if p.get("id") == page.get("id")), page)
            return sorted(current.get("sections") or [], key=lambda s: s.get("sort_order") or 0)

        for change in plan.changes[:8]:
            try:
                if change.kind == "colour":
                    if change.target == "background":
                        from platform_core.website.owner_style import ground_family

                        dark = sa.luminance(change.value) < 0.18
                        theme_edit.update(ground_family(change.value, "#f5f1ea" if dark else "#1a1a1a", dark=dark))
                        done.append(f"The page background is now {change.value}; the words stay readable on it.")
                    else:
                        key = "primary_color" if change.target == "primary" else "accent_color"
                        if key == "primary_color" and theme.get("background_color") and abs(
                                sa.luminance(change.value) - sa.luminance(str(theme["background_color"]))) < 0.12:
                            not_done.append(f"{change.value} would disappear against your page background — "
                                            "try a darker or lighter shade.")
                            continue
                        theme_edit[key] = change.value
                        done.append(("Your main colour (buttons, links)" if key == "primary_color"
                                     else "Your accent colour (highlights, prices)") + f" is now {change.value}.")
                elif change.kind == "style":
                    style_now = {**(theme.get("owner_style") or {}), **style_edit}
                    if change.target in {"heading_size", "text_size"}:
                        was = str(style_now.get(change.target) or "regular")
                        now = sa.size_after(was, change.step)
                        what, verb = (("Headings", "are") if change.target == "heading_size"
                                      else ("Reading text", "is"))
                        if now == was:
                            not_done.append(f"{what} {verb} already at the "
                                            f"{'largest' if change.step > 0 else 'smallest'} "
                                            "size a page stays readable at.")
                            continue
                        style_edit[change.target] = now
                        done.append(f"{what} {verb} now {_SIZE_WORDS[now]}.")
                    elif change.target == "corners":
                        style_edit["corners"] = change.value
                        done.append(f"Buttons, cards and pictures now have {change.value} corners.")
                    elif change.target == "font":
                        keys = list(FONT_PAIRS)
                        value = change.value
                        if value == "next":
                            was = str(style_now.get("font") or "")
                            value = keys[(keys.index(was) + 1) % len(keys)] if was in keys else keys[0]
                        style_edit["font"] = value
                        done.append(f"The lettering is now “{FONT_PAIRS[value]['label']}” — "
                                    f"{FONT_PAIRS[value]['note'].lower()}.")
                elif change.kind == "undo_style":
                    theme_edit["owner_style"] = None
                    style_edit.clear()
                    done.append("Fonts, sizes and corners are back to the original design.")
                elif change.kind == "text":
                    target = _find(await sections(), change.section or "hero")
                    if target is None:
                        not_done.append(f"I could not find {change.section or 'the top of the page'} on this page.")
                        continue
                    content = dict(target.get("content") or {})
                    field = change.field_name
                    if target.get("section_type_id") != "hero" and field in {"headline", "subheadline"}:
                        field = "title" if field == "headline" else "subtitle"
                    if field == "title" and "title" not in content and "headline" in content:
                        field = "headline"
                    content[field] = change.value
                    await SectionService.patch_section(
                        session, business_id=business_id, section_id=uuid.UUID(str(target["id"])),
                        actor_id=actor_id, payload={"content": content})
                    label = {"headline": "headline", "subheadline": "supporting line", "cta_label": "button",
                             "title": "heading", "subtitle": "supporting line", "body": "text"}.get(field, field)
                    done.append(f"The {label} of {_name(target)} now reads “{change.value}”.")
                elif change.kind in {"visibility", "remove", "duplicate", "move"}:
                    current = await sections()
                    target = _find(current, change.section,
                                   hidden=(change.show if change.kind == "visibility" else None))
                    if target is None:
                        not_done.append(f"There is no “{change.section}” section on this page.")
                        continue
                    sid = uuid.UUID(str(target["id"]))
                    if change.kind == "visibility":
                        if target.get("section_type_id") == "hero" and not change.show:
                            not_done.append("The top of the page cannot be hidden — a site needs its first screen.")
                            continue
                        await SectionService.patch_section(session, business_id=business_id, section_id=sid,
                                                           actor_id=actor_id, payload={"is_visible": change.show})
                        done.append(f"{_name(target).capitalize()} is {'shown again' if change.show else 'hidden'}"
                                    f"{'' if change.show else ' — nothing is deleted; say “show it” to bring it back'}.")
                    elif change.kind == "remove":
                        if target.get("section_type_id") == "hero":
                            not_done.append("The top of the page cannot be removed.")
                            continue
                        if target.get("module_binding"):
                            # A tool's own section: hiding is the reversible way to take it off the page.
                            await SectionService.patch_section(session, business_id=business_id, section_id=sid,
                                                               actor_id=actor_id, payload={"is_visible": False})
                            done.append(f"{_name(target).capitalize()} is hidden (it belongs to one of your tools, "
                                        "so it is hidden rather than deleted).")
                        else:
                            await WebsiteCompositionService.remove_section(
                                session, business_id=business_id, section_id=sid, actor_id=actor_id)
                            done.append(f"{_name(target).capitalize()} is removed from this page.")
                    elif change.kind == "duplicate":
                        await WebsiteCompositionService.duplicate_section(
                            session, business_id=business_id, section_id=sid, actor_id=actor_id)
                        done.append(f"A copy of {_name(target)} is added right after it.")
                    else:
                        order = [s for s in current if s["id"] != target["id"]]
                        index = next(i for i, s in enumerate(current) if s["id"] == target["id"])
                        first_free = 1 if order and order[0].get("section_type_id") == "hero" else 0
                        if change.where == "top":
                            at = first_free
                        elif change.where == "bottom":
                            at = len(order)
                        elif change.where in {"before", "after"}:
                            anchor = _find(order, change.anchor)
                            if anchor is None:
                                not_done.append(f"There is no “{change.anchor}” section to put it next to.")
                                continue
                            at = order.index(anchor) + (1 if change.where == "after" else 0)
                        else:
                            at = index - 1 if change.where == "up" else index + 1
                        at = max(first_free if target.get("section_type_id") != "hero" else 0, min(len(order), at))
                        order.insert(at, target)
                        if [s["id"] for s in order] == [s["id"] for s in current]:
                            not_done.append(f"{_name(target).capitalize()} is already there.")
                            continue
                        await WebsiteCompositionService.reorder_sections(
                            session, business_id=business_id, page_id=uuid.UUID(str(page["id"])),
                            actor_id=actor_id, section_ids=[uuid.UUID(str(s["id"])) for s in order])
                        after = order[at - 1] if at > 0 else None
                        done.append(f"{_name(target).capitalize()} now sits "
                                    + (f"right after {_name(after)}." if after else "at the top of the page."))
                    structure = True
                elif change.kind in {"flip", "relayout"}:
                    current = await sections()
                    composed = [s for s in current if s.get("section_type_id") == "composition"]
                    target = _find(composed, change.section) if change.section else (composed[0] if composed else None)
                    if target is None:
                        not_done.append("That section has one fixed arrangement; only composed sections can be "
                                        "re-arranged." if change.section else
                                        "This page has no composed section to re-arrange.")
                        continue
                    await WebsiteArrangeService.arrange(
                        session, business_id=business_id, actor_id=actor_id,
                        section_id=uuid.UUID(str(target["id"])), action="flip" if change.kind == "flip" else "next")
                    structure = True
                    done.append(f"{_name(target).capitalize()} is " + (
                        "now the other way round." if change.kind == "flip" else "now in another arrangement."))
                elif change.kind == "add":
                    await WebsiteCompositionService.add_section(
                        session, business_id=business_id, page_id=uuid.UUID(str(page["id"])), actor_id=actor_id,
                        section_type_id=change.target, content=dict(sa.ADDABLE[change.target]))
                    structure = True
                    done.append(f"A new {change.target.replace('_', ' ')} section is at the end of this page — "
                                "open it in the editor to fill it in.")
                elif change.kind == "rewrite":
                    target = _find(await sections(), change.section) if change.section else None
                    if change.section and target is None:
                        not_done.append(f"There is no “{change.section}” section on this page to rewrite.")
                        continue
                    rewrite.append(str(target["id"]) if target else "")
            except ValidationError as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                not_done.append(str(detail.get("message") or "That change was not allowed."))

        if style_edit:
            theme_edit["owner_style"] = style_edit
        if theme_edit:
            await WebsiteVersionService.update_draft_chrome(
                session, business_id=business_id, actor_id=actor_id, theme=theme_edit)
        changed = bool(done)
        if not done and not rewrite:
            reply = ("I did not change anything. " + (" ".join(not_done[:2]) + " " if plan.changes else "")
                     + CAN_DO)
        else:
            reply = " ".join(done)
            if rewrite:
                reply = (reply + " " if reply else "") + "LOCAH is writing that again — it takes about a minute."
            if not_done:
                reply += " Not done: " + " ".join(not_done[:3])
            reply += " This is your draft; your live site changes when you publish."
        return {
            "reply": reply.strip(), "done": done, "not_done": not_done, "changed": changed,
            "structure_changed": structure, "theme_changed": bool(theme_edit),
            "rewrite_section_ids": rewrite, "page_id": str(page["id"]),
            "changes": [c.as_dict() for c in plan.changes[:8]],
        }


class WebsiteReferenceService:
    """"Make it look like this": a reference picture read into the site's own
    design language (website.reference_style) and laid over the draft."""

    @staticmethod
    async def match(session: AsyncSession, *, business_id: uuid.UUID, actor_id: uuid.UUID,
                    image: bytes, mime_type: str) -> dict[str, Any]:
        from platform_core.website import reference_style as rs
        from platform_core.website.ai_provider import get_ai_provider

        if mime_type not in rs.IMAGE_TYPES:
            raise ValidationError("Send a picture: a JPG, PNG or WebP screenshot of the design you like")
        if not image or len(image) > rs.MAX_IMAGE_BYTES:
            raise ValidationError("That picture is too large. Send one under 6 MB")
        aggregate = await WebsiteService.get_aggregate(session, business_id=business_id)
        theme = dict(aggregate["draft"].get("theme") or {})
        await session.commit()  # nothing held open across the provider call
        try:
            style = await rs.read_reference(get_ai_provider(), image, mime_type)
        except Exception as exc:  # noqa: BLE001 - say so; never pretend it matched
            _log.warning("website.reference.read_failed", error=type(exc).__name__, detail=str(exc)[:200])
            return {"matched": False, "kept": [], "dropped": [],
                    "reply": "LOCAH could not look at that picture just now. Nothing was changed. "
                             "Try again in a minute."}
        if style is None:
            return {"matched": False, "kept": [], "dropped": [],
                    "reply": "That does not look like a designed page, so nothing was changed. Send a "
                             "screenshot of a website, poster or brand layout you like."}
        # The first match keeps what was there, so undo returns to the designed look.
        stored = theme.get(rs.UNDO_KEY)
        before: dict[str, Any] = dict(stored) if isinstance(stored, dict) else rs.snapshot(theme)
        # Its arrangement shapes the composed sections of the same role: their
        # own words and pictures, placed the way the reference places things.
        from platform_core.interview.layout_engine import Style, from_geometry

        dna: dict[str, Any] = dict(theme["dna"]) if isinstance(theme.get("dna"), dict) else {}
        layout_style = Style(concept=str(dna.get("concept") or ""), shape=str(dna.get("shape") or "rect"),
                             budget=str(dna.get("budget") or "gentle"))
        arranged: list[tuple[str, dict[str, Any]]] = []
        previous = dict(before.get("sections") or {})
        for page in aggregate["draft"].get("pages") or []:
            for section in page.get("sections") or []:
                content = section.get("content") or {}
                role = str(content.get("role") or "")
                if section.get("section_type_id") != "composition" or role not in style.layouts:
                    continue
                remade = from_geometry(role, style.layouts[role], content, layout_style)
                if remade is None:
                    continue
                arranged.append((str(section["id"]), remade))
                previous.setdefault(str(section["id"]), content)
        if previous:
            before = {**before, "sections": previous}
        edit: dict[str, Any] = {**style.theme, rs.UNDO_KEY: before,
                                "reference": {"mood": style.mood, "why": style.why}}
        if isinstance(theme.get("dna"), dict):
            # A borrowed look is set in one voice: the site's own coloured or
            # italic accent phrase belongs to the design it replaces.
            edit["dna"] = {**theme["dna"], "headline": "none"}
        if "owner_style" in edit:
            # The reference decides lettering, corners and scale together.
            edit["owner_style"] = {"font": None, "corners": None, "heading_size": None, **edit["owner_style"]}
        draft = await WebsiteVersionService.update_draft_chrome(
            session, business_id=business_id, actor_id=actor_id, theme=edit)
        for section_id, content in arranged:
            await SectionService.patch_section(session, business_id=business_id, section_id=uuid.UUID(section_id),
                                               actor_id=actor_id, payload={"content": content})
        kept = list(style.kept)
        if arranged:
            kept.append(f"its arrangement for {len(arranged)} of your section{'s' if len(arranged) > 1 else ''}")
        reply = ("Your draft now takes after that design: " + ", ".join(kept) + ".") if kept else (
            "Nothing from that design could be used.")
        if style.dropped:
            reply += " Not followed: " + "; ".join(style.dropped) + "."
        reply += (" The pictures and words are still your own: it is a direction, not a copy. "
                  "You can undo this, or adjust anything in Design.")
        return {"matched": True, "reply": reply, "kept": kept, "dropped": style.dropped,
                "mood": style.mood, "why": style.why, "theme": dict(draft.theme or {}),
                "arranged": len(arranged)}

    @staticmethod
    async def undo(session: AsyncSession, *, business_id: uuid.UUID, actor_id: uuid.UUID) -> dict[str, Any]:
        from platform_core.website import reference_style as rs

        aggregate = await WebsiteService.get_aggregate(session, business_id=business_id)
        theme = dict(aggregate["draft"].get("theme") or {})
        back = rs.undo(theme)
        if back is None:
            return {"undone": False, "reply": "There is no matched design to undo.", "theme": theme}
        edit, drop = back
        before = theme[rs.UNDO_KEY]
        draft = await WebsiteVersionService.update_draft_chrome(
            session, business_id=business_id, actor_id=actor_id, theme=edit, drop=drop,
            restore_owner_style=dict(before.get("owner_style") or {}) or None)
        for section_id, content in dict(before.get("sections") or {}).items():
            # Each re-arranged section exactly as it was; one removed since is skipped.
            try:
                await SectionService.patch_section(session, business_id=business_id,
                                                   section_id=uuid.UUID(section_id), actor_id=actor_id,
                                                   payload={"content": content})
            except (ResourceNotFound, ValidationError):
                continue
        return {"undone": True, "reply": "Your draft is back to how it looked before the match.",
                "theme": dict(draft.theme or {})}


class WebsiteArrangeService:
    """A composed section the other way round, or in another arrangement: the
    same words and pictures, placed differently (interview.layout_engine)."""

    @staticmethod
    async def arrange(session: AsyncSession, *, business_id: uuid.UUID, actor_id: uuid.UUID,
                      section_id: uuid.UUID, action: str) -> dict[str, Any]:
        from platform_core.interview.layout_engine import Style, mirrored, rearranged

        if action not in {"flip", "next"}:
            raise ValidationError("Choose flip or next")
        aggregate = await WebsiteService.get_aggregate(session, business_id=business_id)
        section = next((s for p in aggregate["draft"].get("pages") or [] for s in p.get("sections") or []
                        if str(s.get("id")) == str(section_id)), None)
        if section is None:
            raise ResourceNotFound("Website section")
        if section.get("section_type_id") != "composition":
            raise ValidationError("Only a composed section can be re-arranged",
                                  details={"code": "not_composed"})
        content = dict(section.get("content") or {})
        changed: dict[str, Any] | None
        if action == "flip":
            changed = mirrored(content)
        else:
            theme = dict(aggregate["draft"].get("theme") or {})
            dna: dict[str, Any] = dict(theme["dna"]) if isinstance(theme.get("dna"), dict) else {}
            changed = rearranged(content, Style(concept=str(dna.get("concept") or ""),
                                                shape=str(dna.get("shape") or "rect"),
                                                budget=str(dna.get("budget") or "gentle")),
                                 seed=str(section_id))
            if changed is None:
                raise ValidationError("This section has no other arrangement for what it holds",
                                      details={"code": "no_other_arrangement"})
        updated = await SectionService.patch_section(session, business_id=business_id, section_id=section_id,
                                                     actor_id=actor_id, payload={"content": changed})
        from platform_core.resolvers.website_resolver import WebsiteResolver

        return dict(WebsiteResolver.serialize_section(updated))
