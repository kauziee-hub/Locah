"""One business through the whole certification, step by step.

    uv run python -m platform_testing.certify.run <run_dir> <scenario> <variant> [--reuse] [--no-critic] [--fast]

  journey   the owner, from "Create Business" to a published site (journey.py)
  setup     the owner's Workspace afternoon: the kept tools made operational
  customer  a guest orders / books / joins / enquires up to payment (API)
  shop      the same order in a real browser, desktop and phone (shop.mjs)
  render    every public page at four viewports + technical gates (render.mjs)
  critic    the vision critic against the reference class (critic.py)
  gate      pass / repair / fail closed (gate.py)

Every step writes its own file in <run_dir>/sites/<scenario>--<variant>/;
summary.json says what passed. --reuse skips a step whose output exists (a
journey costs model calls and photo quota). Run against the certification
stack only (tools/certify/stack).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]


def _node(*args: str, timeout: int = 900) -> tuple[int, str]:
    proc = subprocess.run(["node", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout + proc.stderr)[-4000:]


async def run(run_dir: Path, scenario: str, variant: str, *, reuse: bool = False, critic: bool = True,
              render: bool = True) -> dict[str, Any]:
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
        verdict = decide(crit, rounds_used=1, max_rounds=3)
        (folder / "gate.json").write_text(json.dumps(verdict, indent=1, ensure_ascii=False), encoding="utf-8")
        summary["steps"]["gate"] = {k: verdict.get(k) for k in ("status", "score", "reasons", "owner_requests")}

    summary["seconds"] = round(time.monotonic() - started, 1)
    summary["ok"] = all(v.get("ok", True) for v in summary["steps"].values() if isinstance(v, dict))
    (folder / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    return summary


if __name__ == "__main__":  # pragma: no cover — a tool
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(argv) != 3:
        raise SystemExit("usage: python -m platform_testing.certify.run <run_dir> <scenario> <variant> "
                         "[--reuse] [--no-critic]")
    fast = "--fast" in sys.argv  # the owner and customer steps only: no render, no critic
    out = asyncio.run(run(Path(argv[0]), argv[1], argv[2], reuse="--reuse" in sys.argv,
                          critic="--no-critic" not in sys.argv and not fast, render=not fast))
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(json.dumps(out, indent=1, ensure_ascii=False)[:6000])
