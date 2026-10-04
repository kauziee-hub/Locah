"""Interview evaluation harness — real planner, scripted understanding, zero AI calls.

Each persona is a business owner: an opening message, and what they would say
to each kind of question (keyed by ask id). The model's reading of every
message is scripted as the TurnIntelligence a good model returns, so what is
evaluated is Locah's own behaviour: which questions it asks, in what order,
whether it re-asks, when it offers to build, what the side panel shows and
which tools it recommends. Each persona runs twice: with the scripted model,
and with the model unreachable (the deterministic reader alone).

Scores are deterministic. Transcripts are written for human review.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from platform_core.ai_guard import blocked_calls
from platform_core.interview.coverage import floor_met
from platform_core.interview.models import BusinessBlueprint, CategorySeed, Fact
from platform_core.interview.orchestrator import BusinessInterviewOrchestrator as Engine
from platform_core.interview.understanding import customer_actions, understanding

# ------------------------------------------------------------------ scripting


def intel(
    text: str,
    *,
    facts: dict[str, str] | None = None,
    answered: dict[str, str] | None = None,
    partial: dict[str, str] | None = None,
    patterns: dict[str, str] | None = None,
    catalogue: list[dict[str, Any]] | None = None,
    intents: dict[str, str] | None = None,
    signal: str = "none",
    media: str = "none",
    ack: str = "",
    draft: dict[str, Any] | None = None,
    language: str = "en",
) -> tuple[str, dict[str, Any]]:
    """An owner message and the TurnIntelligence a good model returns for it.

    Every quote must be words from the message — checked here, so a fixture
    cannot smuggle in something the owner never said.
    """
    def quote(value: str) -> str:
        if value not in text:
            raise ValueError(f"fixture quote {value!r} is not in {text!r}")
        return value

    out: dict[str, Any] = {"language": language, "acknowledgement": ack, "owner_signal": signal,
                           "media_intent": media}
    out["facts"] = [{"field": k, "quote": quote(v)} for k, v in (facts or {}).items()]
    out["answered"] = (
        [{"target": k, "summary": v, "quote": quote(v)} for k, v in (answered or {}).items()]
        + [{"target": k, "summary": v, "quote": quote(v), "status": "partial"} for k, v in (partial or {}).items()]
    )
    out["operating_patterns"] = [{"pattern": k, "quote": quote(v)} for k, v in (patterns or {}).items()]
    out["catalogue"] = catalogue or []
    out["intents"] = [{"intent": k, "original_request": quote(v)} for k, v in (intents or {}).items()]
    if draft:
        out["draft"] = draft
    return text, out


@dataclass
class Persona:
    key: str
    name: str
    business: str  # "Meat shop" — for the report
    category: tuple[str, str, str] | None  # (category_key, subcategory_key, label)
    business_type: str
    opening: tuple[str, dict[str, Any]]
    answers: dict[str, tuple[str, dict[str, Any]]]
    core: set[str]  # discovery targets that must be understood by the checkpoint
    actions: set[str]  # canonical customer actions expected (any of)
    tools: set[str]  # modules expected among recommendations
    never_tools: set[str] = field(default_factory=set)
    follow_ups: tuple[int, int] = (2, 6)  # expected follow-up questions before the checkpoint
    language: str = "en"
    # Started by talking: no category picked, no name typed — Locah reads the
    # kind from what is said and asks the name once.
    talk_first: bool = False


class ScriptedModel:
    """Returns the scripted reading of whichever message it is shown."""

    provider_name = "scripted"
    model_name = "scripted"
    last_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def __init__(self, script: dict[str, dict[str, Any]]) -> None:
        self.script = script

    async def generate_structured(self, prompt: str, schema: Any, config: Any, timeout_seconds: int) -> dict[str, Any]:
        message = json.loads(prompt)["message"]
        return self.script.get(message, {"acknowledgement": ""})


class Down:
    provider_name = "down"
    model_name = "down"
    last_usage = None

    async def generate_structured(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("model unreachable (evaluation)")


NOT_SURE = "Not sure about that — you decide."


def every_module_entitled() -> Any:
    """An entitlement in which every registered module is on — recommendations only."""
    from platform_core.entitlements.models import FeatureState, ModuleState, ResolvedEntitlement
    from platform_core.entitlements.module_registry import ModuleRegistry

    modules = {row["module_id"] for row in ModuleRegistry.list_modules()}
    features = {fid: FeatureState(fid, mid, True, True, "eval")
                for mid in modules for fid in ModuleRegistry.get_or_raise(mid).features}
    return ResolvedEntitlement(
        str(uuid4()), "eval", "1", "1", "other", frozenset(modules), frozenset(features),
        {mid: ModuleState(mid, True, "active", True, True, "eval") for mid in modules}, features, {}, {}, 1,
    )

# ------------------------------------------------------------------ running


@dataclass
class Run:
    persona: Persona
    mode: str
    transcript: list[tuple[str, str]]
    asks: list[str]
    checkpoint_after: int | None
    bp: BusinessBlueprint
    red_flags: list[str]
    score: int
    breakdown: dict[str, int]
    build_available_history: list[bool]


def _blueprint(p: Persona) -> BusinessBlueprint:
    bp = BusinessBlueprint(
        business_id=uuid4(),
        identity={"display_name": Fact(value="New business" if p.talk_first else p.name, source="PLATFORM",
                                       confirmation="confirmed")},
        language_style=p.language,
        name_pending=p.talk_first,
    )
    if p.category and not p.talk_first:
        bp.category = CategorySeed(category_key=p.category[0], subcategory_key=p.category[1], label=p.category[2])
    Engine.open(bp)
    return bp


async def run_persona(p: Persona, mode: str = "model", max_turns: int = 14) -> Run:
    script = {p.opening[0]: p.opening[1], **{text: data for text, data in p.answers.values()}}
    provider: Any = ScriptedModel(script) if mode == "model" else Down()
    bp = _blueprint(p)
    transcript: list[tuple[str, str]] = [("LOCAH", bp.messages[-1].text)]
    history: list[bool] = []
    answered_before: dict[str, int] = {}
    red: list[str] = []
    checkpoint_after: int | None = None
    message = p.opening[0]
    for turn in range(max_turns):
        before = {t for t, s in bp.discovery.items() if s.status == "answered"}
        bp = await Engine.turn(bp, message, provider=provider, business_type=p.business_type)
        transcript += [("OWNER", message), ("LOCAH", bp.messages[-1].text)]
        history.append(bool(bp.completion_state.ready_at is not None or floor_met(bp, p.business_type)))
        for target in {t for t, s in bp.discovery.items() if s.status == "answered"} - before:
            answered_before.setdefault(target, turn)
        last = bp.asks[-1] if bp.asks else None
        if last and last.ask not in {"opening", "free"} and last.turn == bp.turn_count:
            if last.targets and last.targets[0] in answered_before:
                red.append(f"re-asked what was answered: {last.ask}")
            action_known = (bp.discovery.get("commerce.action") or None) is not None and \
                bp.discovery["commerce.action"].status in {"answered", "declined"}
            if last.ask in {"photos", "logo"} and not action_known:
                red.append(f"{last.ask} asked before the transaction model")
        if bp.checkpoint_turn is not None and checkpoint_after is None:
            checkpoint_after = sum(1 for a in bp.asks if a.ask not in {"opening", "free"})
        if bp.readiness.ready and bp.checkpoint_turn is not None:
            break
        ask = bp.asks[-1].ask if bp.asks else ""
        # An owner with nothing to say to a question says so; the reader
        # recognises it (in both modes) and does not ask it again.
        message = p.name if ask == "name" else p.answers[ask][0] if ask in p.answers else NOT_SURE
    # The owner asks to build.
    bp = await Engine.turn(bp, "That's all, build it.", provider=provider, business_type=p.business_type)
    transcript += [("OWNER", "That's all, build it."), ("LOCAH", bp.messages[-1].text)]
    from platform_core.interview.capabilities import resolve_recommendations

    if bp.name_pending:
        red.append("never learned the business name")
    resolve_recommendations(bp, every_module_entitled(), p.business_type)
    history.append(bool(bp.completion_state.ready_at is not None or floor_met(bp, p.business_type)))
    asks = [a.ask for a in bp.asks if a.ask not in {"opening", "free"}]
    red += red_flags(bp, asks, transcript, history, p)
    score, breakdown = grade(bp, asks, checkpoint_after, red, p)
    return Run(p, mode, transcript, asks, checkpoint_after, bp, sorted(set(red)), score, breakdown, history)


_ENRICHMENT_ASKS = {"photos", "logo", "pricing", "hours", "payment", "team", "look", "stock"}
_TRANSACTION_TARGETS = {"commerce.action"}


def red_flags(bp: BusinessBlueprint, asks: list[str], transcript: list[tuple[str, str]],
              history: list[bool], p: Persona) -> list[str]:
    from platform_core.interview.playbooks import playbook_for

    flags: list[str] = []
    if any(a == b for a, b in zip(asks, asks[1:])):
        flags.append("same question twice in a row")
    if any(asks.count(a) > 2 for a in set(asks)):
        flags.append("a question asked three times")
    # Enrichment before the checkpoint — except photos (or a menu/catalogue)
    # where pictures carry the site: knowing what the owner has, or that LOCAH
    # should draw drafts, belongs before the first version there.
    critical_media = playbook_for(bp).media in {"critical", "high"}
    pre = asks[: (bp.checkpoint_turn or len(asks))]
    early = [a for a in pre if a in _ENRICHMENT_ASKS and not (a == "photos" and critical_media)]
    if early and not bp.refining:
        flags.append(f"enrichment before the first version: {', '.join(early)}")
    # 3+ questions in a row without a "so far" line.
    run_ = 0
    for speaker, text in transcript:
        if speaker != "LOCAH":
            continue
        if "?" in text:
            said_back = any(marker in text for marker in (
                "So far:", "Ippo varaikkum", "இதுவரை", "Got it — ", "the shape of it", "I've got enough"))
            run_ = 0 if said_back else run_ + 1
            if run_ >= 4:
                flags.append("4 questions without a summary")
                break
    if len(asks) >= 10:
        flags.append("10+ questions")
    if not bp.readiness.ready:
        flags.append("readiness never reached")
    if any(a and not b for a, b in zip(history, history[1:])):
        flags.append("build disappeared after being offered")
    panel = understanding(bp, p.business_type)
    labels = " ".join(a["label"] for a in panel["actions"]).lower()
    if panel["contact"]["hours"] and not re.search(r"\d|24|closed|all days|daily", panel["contact"]["hours"], re.I):
        flags.append("hours that are not a schedule")
    if re.search(r"\b(section|equipment|dumbb?ells?)\b", labels):
        flags.append("a product or website part shown as a customer action")
    return flags


def grade(bp: BusinessBlueprint, asks: list[str], checkpoint_after: int | None,
          red: list[str], p: Persona) -> tuple[int, dict[str, int]]:
    understood = {t for t, s in bp.discovery.items() if s.status in {"answered", "partial"}}
    core = len(p.core & understood) / max(len(p.core), 1)
    acts = set(customer_actions(bp))
    conversion = 1.0 if acts & p.actions else 0.0
    tools = {r.module_id for r in bp.recommended_modules if r.strength in {"strong", "useful"}}
    module = (len(p.tools & tools) / len(p.tools) if p.tools else 1.0) - 0.5 * bool(p.never_tools & tools)
    n = checkpoint_after if checkpoint_after is not None else len(asks)
    lo, hi = p.follow_ups
    turns = 1.0 if lo <= n <= hi else 0.6 if n <= hi + 1 else 0.2
    breakdown = {
        "core coverage": round(35 * core),
        "customer actions": round(15 * conversion),
        "question count": round(15 * turns),
        "readiness": 10 if bp.readiness.ready else 0,
        "tools": round(10 * max(module, 0.0)),
        "no red flags": max(0, 15 - 5 * len(red)),
    }
    return sum(breakdown.values()), breakdown


# ------------------------------------------------------------------ reporting


def transcript_markdown(run: Run) -> str:
    p = run.persona
    panel = understanding(run.bp, p.business_type)
    lines = [
        f"# {p.name} — {p.business} ({'scripted model' if run.mode == 'model' else 'model unreachable'})",
        "",
        f"- Follow-up questions before the checkpoint: **{run.checkpoint_after}**"
        f" (expected {p.follow_ups[0]}–{p.follow_ups[1]})",
        f"- Questions asked: {', '.join(run.asks) or '—'}",
        f"- Score: **{run.score}/100** · {', '.join(f'{k} {v}' for k, v in run.breakdown.items())}",
        f"- Red flags: {', '.join(run.red_flags) or 'none'}",
        "",
        "## Conversation",
        "",
    ]
    for speaker, text in run.transcript:
        lines.append(f"**{speaker}:** {text}")
        lines.append("")
    lines += [
        "## What Locah understood",
        "",
        f"- Business: {panel['business']['kind'] or '—'}",
        f"- Offers: {panel['offer']['summary'] or '—'}",
        f"- Customers can: {', '.join(a['label'] for a in panel['actions']) or '—'}",
        f"- How they buy: {'; '.join(r['text'] for r in panel['buying']) or '—'}",
        f"- Place: {panel['contact']['location'] or '—'} · Phone: {panel['contact']['phone'] or '—'}"
        f" · Hours: {panel['contact']['hours'] or '—'}",
        f"- Website parts asked for: {', '.join(panel['content']) or '—'}",
        f"- Recommended tools: {', '.join(t['label'] for t in panel['tools']) or '—'}",
        f"- Still worth knowing: {', '.join(w['label'] for w in panel['worth_knowing']) or '—'}",
        "",
    ]
    return "\n".join(lines)


async def run_all(personas: list[Persona], out: Path | None = None) -> list[Run]:
    runs: list[Run] = []
    for p in personas:
        for mode in ("model", "down"):
            runs.append(await run_persona(p, mode))
    if out:
        out.mkdir(parents=True, exist_ok=True)
        for run in runs:
            (out / f"{run.persona.key}-{run.mode}.md").write_text(transcript_markdown(run), encoding="utf-8")
        rows = ["| Business | Mode | Follow-ups | Core coverage | Redundant | Build offered after | Score | Red flags |",
                "|---|---|---|---|---|---|---|---|"]
        for run in runs:
            understood = {t for t, s in run.bp.discovery.items() if s.status in {"answered", "partial"}}
            redundant = sum(1 for f in run.red_flags if f.startswith("re-asked") or "twice" in f)
            rows.append(
                f"| {run.persona.business} | {'model' if run.mode == 'model' else 'no model'} | {len(run.asks)} | "
                f"{len(run.persona.core & understood)}/{len(run.persona.core)} | {redundant} | "
                f"{run.checkpoint_after if run.checkpoint_after is not None else 'never'} | {run.score} | "
                f"{'; '.join(run.red_flags) or '—'} |")
        (out / "SUMMARY.md").write_text(
            "# Interview evaluation\n\nScripted understanding, real planner, zero AI calls "
            f"(blocked attempts: {len(blocked_calls())}).\n\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return runs


def main(out: str = "acceptance-out/interview-transcripts") -> None:  # pragma: no cover
    from platform_testing.interview_personas import ALL_PERSONAS

    runs = asyncio.run(run_all(ALL_PERSONAS, Path(out)))
    for run in runs:
        print(f"{run.persona.business:28} {run.mode:5} asks={len(run.asks):2} checkpoint={run.checkpoint_after} "
              f"score={run.score:3} flags={run.red_flags}")
