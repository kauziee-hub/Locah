"""The Website Builder Certification Report, from the runs' own files.

    uv run python -m platform_testing.certify.report <out_dir> <run_dir> [<run_dir> ...]

Reads every ``<run_dir>/sites/<scenario>--<variant>/`` (journey, setup,
customer, browser flows, render, critique, gate, repair) and writes into
``<out_dir>``:

  report.json   one row per site (the latest run of each site wins)
  REPORT.md     the matrix, the gate verdicts, the owner requests, the
                repair rounds (score before and after, every fix tried and
                whether it was kept), the defects by layer, the technical
                gates and the photo audit
  sheets/       one contact sheet per site (home on a laptop and a phone,
                every other page as a thumbnail) — what the critic judged

Nothing here decides anything: the numbers are the critic's and the gate's,
copied as they were recorded. A site with no critique is reported as
"not judged", never as passed.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SHEET_WIDTH = 1500


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _count(value: Any) -> int:
    """A count the renderer wrote as a number or as the list of what it found."""
    if isinstance(value, (list, tuple, dict)):
        return len(value)
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def site_row(folder: Path) -> dict[str, Any]:
    """Everything the report says about one site, from its run folder."""
    journey = _load(folder / "journey.json")
    setup = _load(folder / "setup.json")
    customer = _load(folder / "customer.json")
    render = _load(folder / "render.json")
    critique = _load(folder / "critique.json")
    gate = _load(folder / "gate.json")
    repair = _load(folder / "repair.json")
    build = journey.get("build") or {}
    flows = {str(f.get("flow")): bool(f.get("ok")) for f in customer.get("flows") or []}
    for name in ("shop", "shop-mobile", "book", "book-mobile"):
        browser = _load(folder / f"{name}.json")
        if browser:
            flows[f"browser {name}"] = bool(browser.get("ok"))
    tech: Counter[str] = Counter()
    lcp: list[float] = []
    for page in render.get("pages") or []:
        for vp_name, vp in (page.get("viewports") or {}).items():
            if not isinstance(vp, dict):
                continue
            tech["overflow"] += bool(vp.get("overflow_x"))
            tech["broken_images"] += _count(vp.get("broken_images"))
            tech["imgs_without_alt"] += _count(vp.get("imgs_without_alt"))
            tech["console_errors"] += len(vp.get("console_errors") or [])
            tech["axe_serious"] += sum(1 for a in vp.get("axe") or []
                                       if isinstance(a, dict) and a.get("impact") in {"serious", "critical"})
            if vp_name == "laptop" and isinstance(vp.get("lcp_ms"), (int, float)):
                lcp.append(float(vp["lcp_ms"]))
    defects = critique.get("defects") or []
    audit = build.get("photo_audit") or []
    return {
        "site_key": journey.get("site_key") or folder.name,
        "run": folder.parent.parent.name,
        "scenario": journey.get("scenario"),
        "variant": journey.get("variant"),
        "business_id": journey.get("business_id"),
        "public_url": journey.get("public_url"),
        "modules": journey.get("modules_enabled") or [],
        "modules_failed": journey.get("modules_failed") or {},
        "turns": len(journey.get("turns") or []),
        "asks": [t.get("next_ask") for t in journey.get("turns") or []],
        "published": bool(journey.get("published")),
        "journey_errors": journey.get("errors") or [],
        "pages": journey.get("pages") or [],
        "archetype": build.get("archetype"),
        "profile": build.get("reference_profile"),
        "photos": {"placed": build.get("media_drawn"), "failed": build.get("media_failed"),
                   "reasons": dict(Counter(str(r.get("reason")) for r in audit if r.get("reason") != "ok"))},
        "build_seconds": build.get("seconds"),
        "setup_findings": setup.get("findings") or [],
        "setup_notes": setup.get("notes") or [],
        "flows": flows,
        "flows_ok": bool(flows) and all(flows.values()),
        "tech": dict(tech),
        "lcp_ms_max": max(lcp) if lcp else None,
        "broken_links": len(render.get("broken_links") or []),
        "judged": bool(critique),
        "score": critique.get("weighted_score"),
        "scores": critique.get("scores") or {},
        "page_scores": critique.get("page_weighted") or {},
        "critique_complete": critique.get("complete"),
        "critique_errors": critique.get("errors") or [],
        "critic_version": critique.get("version"),
        "defects": {"critical": sum(1 for d in defects if d.get("severity") == "critical"),
                    "major": sum(1 for d in defects if d.get("severity") == "major"),
                    "minor": sum(1 for d in defects if d.get("severity") == "minor")},
        "defects_by_layer": dict(Counter(str(d.get("layer")) for d in defects
                                         if d.get("severity") in {"critical", "major"})),
        "top_defects": [f"{d.get('severity')}/{d.get('layer')} {d.get('page')}: {d.get('text')}"
                        for d in defects if d.get("severity") == "critical"][:6],
        "gate": gate.get("status") or ("not judged" if not critique else "unknown"),
        "rounds_used": gate.get("rounds_used"),
        "blocked_on": gate.get("blocked_on"),
        "owner_requests": gate.get("owner_requests") or [],
        "repair": {
            "score_before": repair.get("score_before"), "score_after": repair.get("score_after"),
            "page_before": repair.get("page_before") or {}, "page_after": repair.get("page_after") or {},
            "rounds": repair.get("rounds") or [], "rounds_used": repair.get("rounds_used"),
            "levers": repair.get("levers") or [], "error": repair.get("error"),
            "attempts": [{k: a.get(k) for k in ("round", "page", "section", "lever", "change", "before", "after",
                                                 "critical_after", "kept", "why", "defect")}
                         for a in repair.get("attempts") or []],
        } if repair else None,
        "folder": str(folder),
    }


def contact_sheet(folder: Path, out: Path) -> str | None:
    """Home on a laptop (the first screens) and a phone, then a strip of the other pages."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover — the report still writes its tables
        return None
    shots = folder / "shots"
    laptop, phone = shots / "home__laptop.png", shots / "home__mobile.png"
    if not laptop.exists():
        return None
    big = Image.open(laptop).convert("RGB")
    big_w = 980
    big = big.resize((big_w, int(big.height * big_w / big.width)))
    big = big.crop((0, 0, big_w, min(big.height, 2200)))
    tiles = [big]
    if phone.exists():
        small = Image.open(phone).convert("RGB")
        small = small.resize((240, int(small.height * 240 / small.width)))
        tiles.append(small.crop((0, 0, 240, min(small.height, 2200))))
    others = sorted(p for p in shots.glob("*__laptop.png") if not p.name.startswith("home__"))[:4]
    strip = []
    for path in others:
        thumb = Image.open(path).convert("RGB")
        thumb = thumb.resize((240, int(thumb.height * 240 / thumb.width)))
        strip.append(thumb.crop((0, 0, 240, min(thumb.height, 1060))))
    height = max(t.height for t in tiles) if not strip else max(max(t.height for t in tiles), 1080 * 2 + 20)
    sheet = Image.new("RGB", (SHEET_WIDTH, height), (245, 244, 240))
    x = 0
    for tile in tiles:
        sheet.paste(tile, (x, 0))
        x += tile.width + 10
    for i, thumb in enumerate(strip):
        sheet.paste(thumb, (x + (i % 1) * 250, (i // 1) * 545 if i < 4 else 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=78, optimize=True)
    return out.name


def markdown(rows: list[dict[str, Any]]) -> str:
    judged = [r for r in rows if r["judged"]]
    passed = [r for r in judged if r["gate"] == "pass"]
    lines = [
        "# Website Builder Certification Report",
        "",
        f"Sites: {len(rows)} · judged by the vision critic: {len(judged)} · passed the gate: {len(passed)} "
        f"(pass = weighted score ≥ 8.5, every dimension ≥ 7, no critical, ≤ 2 major).",
        "",
        "Numbers are the critic's and the gate's as recorded; a site that was not judged is not counted as "
        "passed. A failed gate is held back from publish under `WEBSITE_CERTIFICATION=enforce`.",
        "",
        "## Matrix",
        "",
        "| Site | Run | Modules | Turns | Pages | Flows | Photos placed/failed | Score | Gate | Crit/Major |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        flows = "all pass" if r["flows_ok"] else ", ".join(k for k, v in r["flows"].items() if not v) or "—"
        photos = f"{r['photos']['placed']}/{r['photos']['failed']}"
        score = f"{r['score']:.2f}" if isinstance(r["score"], (int, float)) else "—"
        lines.append(f"| {r['site_key']} | {r['run']} | {', '.join(r['modules'])} | {r['turns']} | "
                     f"{len(r['pages'])} | {flows} | {photos} | {score} | {r['gate']} | "
                     f"{r['defects']['critical']}/{r['defects']['major']} |")
    lines += ["", "## Gate verdicts and owner requests", ""]
    for r in judged:
        score = f"{r['score']:.2f}" if isinstance(r["score"], (int, float)) else "—"
        rounds = f", after {r['rounds_used']} round(s)" if r.get("rounds_used") else ""
        lines.append(f"### {r['site_key']} — {r['gate']} ({score}{rounds})")
        if r.get("critique_complete") is False:
            lines.append("Critique incomplete: " + "; ".join(str(e) for e in r.get("critique_errors") or [])[:300])
        if r.get("blocked_on"):
            lines.append(f"Blocked on: {r['blocked_on']}")
        if r["page_scores"]:
            lines.append("Pages: " + ", ".join(f"{k} {v:.2f}" for k, v in r["page_scores"].items()))
        weakest = sorted(r["scores"].items(), key=lambda kv: kv[1])[:4]
        if weakest:
            lines.append("Weakest dimensions: " + ", ".join(f"{k} {v:.1f}" for k, v in weakest))
        if r["defects_by_layer"]:
            lines.append("Critical+major by layer: " + ", ".join(
                f"{k} {v}" for k, v in sorted(r["defects_by_layer"].items(), key=lambda kv: -kv[1])))
        for request in r["owner_requests"]:
            lines.append(f"- Owner request: {request}")
        for defect in r["top_defects"]:
            lines.append(f"- {defect}")
        lines.append("")
    repaired = [r for r in rows if r.get("repair")]
    if repaired:
        lines += ["## Repair rounds", "",
                  "Each fix is one lever on one section through the owner's own editing API, published, the "
                  "page rendered and judged alone, and kept only when the page's score rises by at least 0.25 "
                  "with no new critical defect (otherwise reverted). After a round, the touched pages are "
                  "rendered again at every viewport and the site is judged again (untouched pages keep their "
                  "judgment).", ""]
        for r in repaired:
            rep = r["repair"]
            before, after = rep.get("score_before"), rep.get("score_after")
            head = f"### {r['site_key']} — "
            head += (f"{before:.2f} → {after:.2f}" if isinstance(before, (int, float))
                     and isinstance(after, (int, float)) else f"{before} → {after}")
            lines.append(head + f" ({r['gate']})")
            if rep.get("levers"):
                lines.append("Levers allowed: " + ", ".join(rep["levers"]))
            if rep.get("error"):
                lines.append(f"Loop error: {rep['error']}")
            for rnd in rep.get("rounds") or []:
                bits = [f"round {rnd.get('round')}: {rnd.get('attempts')} tried, {rnd.get('kept')} kept"]
                if rnd.get("touched"):
                    bits.append("re-judged " + ", ".join(rnd["touched"]))
                if rnd.get("stopped"):
                    bits.append(str(rnd["stopped"]))
                if rnd.get("score_after") is not None:
                    bits.append(f"site {rnd.get('score_before')} → {rnd.get('score_after')}")
                lines.append("- " + "; ".join(bits))
            if rep.get("attempts"):
                lines += ["", "| Round | Page | Section | Lever | Change | Page before | After | Kept | Defect |",
                          "|---|---|---|---|---|---|---|---|---|"]
                for a in rep["attempts"]:
                    change = a.get("change") or a.get("why") or ""
                    defect = str(a.get("defect") or "").replace("|", "/")[:120]
                    lines.append(f"| {a.get('round')} | {a.get('page')} | {a.get('section')} | {a.get('lever')} | "
                                 f"{change} | {a.get('before')} | {a.get('after')} | "
                                 f"{'yes' if a.get('kept') else 'no'} | {defect} |")
            if rep.get("page_after"):
                lines.append("")
                lines.append("Pages after: " + ", ".join(f"{k} {v}" for k, v in rep["page_after"].items()))
            lines.append("")
    lines += ["## Technical gates (all pages × viewports)", "",
              "| Site | Overflow | Broken images | Images w/o alt | Console errors | axe serious | "
              "Broken links | Max LCP laptop (ms) |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        t = r["tech"]
        lcp = f"{r['lcp_ms_max']:.0f}" if isinstance(r["lcp_ms_max"], (int, float)) else "—"
        lines.append(f"| {r['site_key']} | {t.get('overflow', 0)} | {t.get('broken_images', 0)} | "
                     f"{t.get('imgs_without_alt', 0)} | {t.get('console_errors', 0)} | {t.get('axe_serious', 0)} | "
                     f"{r['broken_links']} | {lcp} |")
    lines += ["", "## Photographs", "",
              "| Site | Placed | Failed | Why slots stayed empty |", "|---|---|---|---|"]
    for r in rows:
        why = ", ".join(f"{k} ×{v}" for k, v in r["photos"]["reasons"].items()) or "—"
        lines.append(f"| {r['site_key']} | {r['photos']['placed']} | {r['photos']['failed']} | {why} |")
    return "\n".join(lines) + "\n"


def build(out_dir: Path, run_dirs: list[Path]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for run_dir in run_dirs:
        for folder in sorted((run_dir / "sites").glob("*--*")):
            if not (folder / "journey.json").exists():
                continue
            row = site_row(folder)
            latest[row["site_key"]] = row  # later runs replace earlier ones
    rows = sorted(latest.values(), key=lambda r: str(r["site_key"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        row["sheet"] = contact_sheet(Path(row["folder"]), out_dir / "sheets" / f"{row['site_key']}.jpg")
    (out_dir / "report.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / "REPORT.md").write_text(markdown(rows), encoding="utf-8")
    return rows


if __name__ == "__main__":  # pragma: no cover — a tool
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    made = build(Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]])
    print(f"{len(made)} sites; judged {sum(1 for r in made if r['judged'])}; "
          f"passed {sum(1 for r in made if r['gate'] == 'pass')}")
