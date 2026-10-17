"""The design loop: render a few pages of one built site and critique only those.

    uv run python -m platform_testing.certify.loop <site_dir> [--pages home,menu] [--tag t1]
                                                   [--viewports laptop,mobile] [--no-critic]

For iterating on the renderer and composer: a full certification run renders
every page at four viewports with accessibility and link checks; this renders
the named pages (laptop + phone by default) into <site_dir>/loop-<tag>/ and runs
the same vision critic on them, printing the weighted score per page and every
defect — minutes per round instead of a full run. The site is read where it is
published (journey.json's public_url); nothing is changed.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from platform_testing.certify.gate import WEIGHTS, weighted_score
from platform_testing.certify.run import _node


def _arg(name: str, default: str) -> str:
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


async def run(site_dir: Path, pages: list[str], viewports: str, tag: str, critic: bool) -> dict[str, Any]:
    from platform_core.website.ai_provider import get_ai_provider
    from platform_testing.certify.critic import critique_site
    from platform_testing.certify.owners import DISTINCT, SCENARIOS

    journey = json.loads((site_dir / "journey.json").read_text(encoding="utf-8"))
    out = site_dir / f"loop-{tag}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name in ("journey.json", "draft.json"):
        if (site_dir / name).exists():
            shutil.copy(site_dir / name, out / name)
    url = str(journey.get("public_url") or "")
    code, log = _node("tools/certify/render.mjs", str(out), url, "--pages", ",".join(pages), "--only",
                      "--viewports", viewports, "--no-axe", "--no-links", timeout=1800)
    if not (out / "render.json").exists():
        return {"error": f"render failed ({code}): {log[-600:]}"}
    if not critic:
        return {"rendered": str(out)}
    scenario = SCENARIOS.get(journey["scenario"]) or next(
        s for group in DISTINCT.values() for s in group if s.key == journey["scenario"])
    manifest = {"journey": journey,
                "draft": json.loads((out / "draft.json").read_text(encoding="utf-8"))
                if (out / "draft.json").exists() else {}}
    critique = await critique_site(get_ai_provider(), out, manifest, category=scenario.kind, round_no=1)
    per_page = {}
    for slug, scores in (critique.get("page_scores") or {}).items():
        per_page[slug] = round(weighted_score(scores, [d for d in scores if d in WEIGHTS]), 2)
    return {"dir": str(out), "complete": critique.get("complete"), "errors": critique.get("errors"),
            "site_score": round(weighted_score(critique.get("scores") or {}), 2),
            "page_scores": per_page, "scores": critique.get("scores"),
            "defects": [f"{d.get('severity')}/{d.get('layer')} {d.get('page')} {d.get('viewport')}: "
                        f"{d.get('text')}" for d in critique.get("defects") or []]}


if __name__ == "__main__":  # pragma: no cover — a tool
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    result = asyncio.run(run(
        Path(sys.argv[1]), _arg("--pages", "home").split(","), _arg("--viewports", "laptop,mobile"),
        _arg("--tag", "a"), "--no-critic" not in sys.argv))
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(json.dumps(result, indent=1, ensure_ascii=False))
