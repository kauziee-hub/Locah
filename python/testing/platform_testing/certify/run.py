"""One business through the whole certification, step by step.

    uv run python -m platform_testing.certify.run <run_dir> <scenario> <variant> [--reuse] [--no-critic] [--fast]
                                                    [--repair [--rounds 3] [--per-round 3] [--no-photos]
                                                     [--judgments 1]]

  journey   the owner, from "Create Business" to a published site (journey.py)
  setup     the owner's Workspace afternoon: the kept tools made operational
  customer  a guest orders / books / joins / enquires up to payment (API)
  shop      the same order in a real browser, desktop and phone (shop.mjs)
  render    every public page at four viewports + technical gates (render.mjs)
  critic    the vision critic against the reference class (critic.py)
  gate      pass / repair / fail closed (gate.py)
  repair    with --repair, while the gate says `repair`: one round of targeted
            fixes (each kept only when its page improves), the touched pages
            rendered again at every viewport, the site critiqued again
            (untouched pages keep their judgment), the gate again — up to
            --rounds (default 3: the first critique and two repair rounds),
            ending in a pass or fail closed with the owner's requests
            (repair.until_verdict; every round in repair.json)

Every step writes its own file in <run_dir>/sites/<scenario>--<variant>/;
summary.json says what passed. --reuse skips a step whose output exists (a
journey costs model calls and photo quota). --repair starts from the latest
critique.json (the site as it is now judged) and costs model calls; with
--no-photos it uses no lever that spends photo quota (no new photograph, no
rewrite: a scoped rewrite searches photos for every empty slot) — layout
variants and hiding a repeat only. --judgments N judges each candidate fix N
times and its page's starting score again, keeping on the means (the critic
wobbles by more than the keep margin). Run against the certification stack only
(tools/certify/stack).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Collection
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]


def _node(*args: str, timeout: int = 900) -> tuple[int, str]:
    proc = subprocess.run(["node", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout + proc.stderr)[-4000:]


async def record_verdict(business_id: str, verdict: dict[str, Any]) -> bool:
    """Write the gate's verdict to the certification database (local only)."""
    import os
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from platform_core.services.website_certification import WebsiteCertificationService

    url = os.getenv("DATABASE_URL", "")
    if "@localhost:" not in url and "@127.0.0.1:" not in url:
        return False  # never a hosted database
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as session:
            await WebsiteCertificationService.record(
                session, business_id=uuid.UUID(business_id), verdict=verdict, source="certify-harness")
            await session.commit()
        return True
    except Exception:  # noqa: BLE001 - the run's own gate.json still holds the verdict
        return False
    finally:
        await engine.dispose()


def _slug(page: dict[str, Any]) -> str:
    return str(page.get("slug") or "").strip("/") or "home"


def rerender(folder: Path, url: str, pages: Collection[str], round_no: int) -> list[str]:
    """Render ``pages`` again at every viewport (with the technical gates) into
    round-r<n>/, then merge them into the site's render.json and shots/; the
    render before is kept as render.r<n-1>.json and the replaced shots in
    shots-r<n-1>/ (before / after, side by side). Returns the pages merged."""
    out = folder / f"round-r{round_no}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy(folder / "journey.json", out / "journey.json")
    code, log = _node("tools/certify/render.mjs", str(out), url, "--pages", ",".join(sorted(pages)), "--only",
                      timeout=1800)
    fresh = json.loads((out / "render.json").read_text(encoding="utf-8")) if (out / "render.json").exists() else {}
    got = {_slug(pg): pg for pg in fresh.get("pages") or [] if isinstance(pg, dict) and _slug(pg) in pages}
    if not got:
        raise RuntimeError(f"re-render of {sorted(pages)} failed ({code}): {log[-400:]}")
    current = json.loads((folder / "render.json").read_text(encoding="utf-8"))
    before = folder / f"render.r{round_no - 1}.json"
    if not before.exists():
        shutil.copy(folder / "render.json", before)
    kept_dir = folder / f"shots-r{round_no - 1}"
    for slug in got:
        name = slug.replace("/", "_")
        for shot in (folder / "shots").glob(f"{name}__*.png"):
            kept_dir.mkdir(exist_ok=True)
            shutil.copy2(shot, kept_dir / shot.name)
        for shot in (out / "shots").glob(f"{name}__*.png"):
            shutil.copy2(shot, folder / "shots" / shot.name)
    merged = [got.get(_slug(pg), pg) for pg in current.get("pages") or []]
    merged += [pg for slug, pg in got.items() if slug not in {_slug(m) for m in merged}]
    current["pages"] = merged
    current.setdefault("rerendered", {})[str(round_no)] = sorted(got)
    (folder / "render.json").write_text(json.dumps(current, indent=1, ensure_ascii=False), encoding="utf-8")
    return sorted(got)


async def repair_rounds(folder: Path, journey: dict[str, Any], critique: dict[str, Any], category: str, *,
                        max_rounds: int, per_round: int, levers: Collection[str], judgments: int = 1) -> dict[str, Any]:
    """The bounded repair loop on the live site (repair.until_verdict with the
    real levers, renderer and critic); writes repair.json."""
    from platform_core.website.ai_provider import get_ai_provider
    from platform_testing.certify import repair as repair_step
    from platform_testing.certify.critic import critique_site

    provider = get_ai_provider()
    url = str(journey.get("public_url") or "")
    report: dict[str, Any] = {"site_key": journey.get("site_key"), "levers": sorted(levers), "judgments": judgments,
                              "score_before": critique.get("weighted_score"),
                              "page_before": critique.get("page_weighted"), "rounds": [], "attempts": []}
    try:
        async with repair_step.Repairer(folder, journey, category, levers=levers, judgments=judgments) as fixer:
            async def fix_round(current: dict[str, Any], round_no: int) -> list[dict[str, Any]]:
                attempts: list[dict[str, Any]] = await fixer.round(current, round_no, per_round)
                return attempts

            async def rejudge(current: dict[str, Any], pages: set[str], round_no: int) -> dict[str, Any]:
                rerender(folder, url, pages, round_no)
                draft = await fixer.draft()
                (folder / f"draft.r{round_no}.json").write_text(json.dumps(draft, indent=1, ensure_ascii=False),
                                                                 encoding="utf-8")
                judged: dict[str, Any] = await critique_site(
                    provider, folder, {"journey": journey, "draft": draft}, category=category,
                    round_no=round_no, carry=current, rejudge=pages)
                return judged

            try:
                loop = await repair_step.until_verdict(critique, fix_round=fix_round, rejudge=rejudge,
                                                       max_rounds=max_rounds)
            finally:
                report["attempts"] = fixer.attempts
        final = loop["critique"]
        report.update(rounds=loop["rounds"], rounds_used=loop["rounds_used"], verdict=loop["verdict"]["status"],
                      score_after=final.get("weighted_score"), page_after=final.get("page_weighted"),
                      owner_requests=loop["verdict"].get("owner_requests"))
        return {"critique": final, "verdict": loop["verdict"], "report": report}
    except Exception as exc:  # noqa: BLE001 — a broken loop is reported; the verdict stays unfinished
        report["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        return {"critique": critique, "verdict": None, "report": report}
    finally:
        (folder / "repair.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")


async def run(run_dir: Path, scenario: str, variant: str, *, reuse: bool = False, critic: bool = True,
              repair: bool = False, render: bool = True, max_rounds: int = 3, per_round: int = 3,
              photos: bool = True, judgments: int = 1) -> dict[str, Any]:
    from platform_testing.certify import customer as customer_step
    from platform_testing.certify import journey as journey_step
    from platform_testing.certify import setup as setup_step

    site_key = f"{scenario}--{variant}"
    folder = run_dir / "sites" / site_key
    summary: dict[str, Any] = {"site_key": site_key, "steps": {}}
    started = time.monotonic()

    def done(name: str) -> bool:
        return reuse and (folder / name).exists()

    if not done("journey.json"):
        j = await journey_step.run(run_dir, scenario, variant)
        j.save(folder)
    journey = json.loads((folder / "journey.json").read_text(encoding="utf-8"))
    summary["steps"]["journey"] = {"ok": bool(journey.get("published")) and not journey.get("errors"),
                                   "errors": journey.get("errors"), "pages": journey.get("pages")}
    if not journey.get("published"):
        summary["ok"] = False
        (folder / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        return summary
    url = str(journey.get("public_url") or "")

    if not done("setup.json"):
        await setup_step.run(run_dir, site_key)
    setup = json.loads((folder / "setup.json").read_text(encoding="utf-8"))
    summary["steps"]["setup"] = {"ok": not setup.get("findings"), "findings": setup.get("findings"),
                                "notes": setup.get("notes")}

    if not done("customer.json"):
        await customer_step.run(run_dir, site_key)
    cust = json.loads((folder / "customer.json").read_text(encoding="utf-8"))
    summary["steps"]["customer"] = {"ok": cust.get("ok"), "flows": {
        f["flow"]: f["ok"] for f in cust.get("flows") or []}}

    if (cust.get("capabilities") or {}).get("order"):
        for flag in ("", "--mobile"):
            name = "shop-mobile.json" if flag else "shop.json"
            if not done(name):
                _node("tools/certify/shop.mjs", str(folder), url, *([flag] if flag else []), timeout=300)
            shop = json.loads((folder / name).read_text(encoding="utf-8")) if (folder / name).exists() else {}
            summary["steps"][name[:-5]] = {"ok": shop.get("ok", False),
                                           "failed": [s["step"] for s in shop.get("steps") or [] if not s["ok"]]}

    if (cust.get("capabilities") or {}).get("book"):
        for flag in ("", "--mobile"):
            name = "book-mobile.json" if flag else "book.json"
            if not done(name):
                _node("tools/certify/book.mjs", str(folder), url, *([flag] if flag else []), timeout=300)
            booked = json.loads((folder / name).read_text(encoding="utf-8")) if (folder / name).exists() else {}
            summary["steps"][name[:-5]] = {"ok": booked.get("ok", False),
                                           "failed": [s["step"] for s in booked.get("steps") or [] if not s["ok"]]}

    if render and not done("render.json"):
        code, out = _node("tools/certify/render.mjs", str(folder), url, timeout=1800)
        summary["steps"]["render_log"] = out[-800:]
    rendered = json.loads((folder / "render.json").read_text(encoding="utf-8")) if (folder / "render.json").exists() else {}
    summary["steps"]["render"] = {"pages": [p.get("slug") for p in rendered.get("pages") or []]}

    if critic and rendered:
        from platform_core.website.ai_provider import get_ai_provider
        from platform_testing.certify.critic import critique_site
        from platform_testing.certify.gate import decide
        from platform_testing.certify.owners import DISTINCT, SCENARIOS

        found = SCENARIOS.get(journey["scenario"]) or next(
            s for group in DISTINCT.values() for s in group if s.key == journey["scenario"])
        draft_path = folder / "draft.json"
        manifest = {"journey": journey, "draft": json.loads(draft_path.read_text(encoding="utf-8"))
                    if draft_path.exists() else {}}
        if not done("critique.json"):
            await critique_site(get_ai_provider(), folder, manifest, category=found.kind or found.category_key,
                                round_no=1)
        crit = json.loads((folder / "critique.json").read_text(encoding="utf-8"))
        verdict = decide(crit, rounds_used=1, max_rounds=max_rounds)
        if repair and verdict.get("status") == "repair":
            from platform_testing.certify.repair import ALL_LEVERS, PHOTO_QUOTA_LEVERS

            levers = ALL_LEVERS if photos else ALL_LEVERS - PHOTO_QUOTA_LEVERS
            looped = await repair_rounds(folder, journey, crit, found.kind or found.category_key,
                                         max_rounds=max_rounds, per_round=per_round, levers=levers,
                                         judgments=judgments)
            rep = looped["report"]
            summary["steps"]["repair"] = {
                "ok": "error" not in rep, "error": rep.get("error"), "rounds_used": rep.get("rounds_used"),
                "attempts": len(rep.get("attempts") or []),
                "kept": sum(1 for a in rep.get("attempts") or [] if a.get("kept")),
                "score_before": rep.get("score_before"), "score_after": rep.get("score_after")}
            crit = looped["critique"]
            verdict = looped["verdict"] or verdict
        (folder / "gate.json").write_text(json.dumps(verdict, indent=1, ensure_ascii=False), encoding="utf-8")
        summary["steps"]["gate"] = {k: verdict.get(k) for k in ("status", "score", "reasons", "owner_requests",
                                                                "rounds_used", "blocked_on")}
        # The verdict is recorded on the business's draft, as the product reads
        # it at publish (services.website_certification).
        summary["steps"]["gate"]["recorded"] = await record_verdict(journey["business_id"], verdict)
        summary["steps"]["gate"]["would_publish_under_enforce"] = verdict.get("status") == "pass"

    summary["seconds"] = round(time.monotonic() - started, 1)
    summary["ok"] = all(v.get("ok", True) for v in summary["steps"].values() if isinstance(v, dict))
    (folder / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    return summary


def _cli(args: list[str]) -> tuple[list[str], dict[str, Any]]:
    """Positional arguments and options (``--rounds N``, ``--per-round N`` take a value)."""
    valued = {"--rounds": "max_rounds", "--per-round": "per_round", "--judgments": "judgments"}
    positional: list[str] = []
    options: dict[str, Any] = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a in valued and i + 1 < len(args):
            options[valued[a]] = int(args[i + 1])
            i += 2
            continue
        if not a.startswith("--"):
            positional.append(a)
        i += 1
    flags = set(args)
    fast = "--fast" in flags  # the owner and customer steps only: no render, no critic
    options |= {"reuse": "--reuse" in flags, "critic": "--no-critic" not in flags and not fast,
                "render": not fast, "repair": "--repair" in flags, "photos": "--no-photos" not in flags}
    return positional, options


if __name__ == "__main__":  # pragma: no cover — a tool
    argv, opts = _cli(sys.argv[1:])
    if len(argv) != 3:
        raise SystemExit("usage: python -m platform_testing.certify.run <run_dir> <scenario> <variant> "
                         "[--reuse] [--no-critic] [--fast] [--repair [--rounds 3] [--per-round 3] [--no-photos] "
                         "[--judgments 1]]")
    out = asyncio.run(run(Path(argv[0]), argv[1], argv[2], **opts))
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(json.dumps(out, indent=1, ensure_ascii=False)[:6000])
