"""render → screenshot → critique → revise → render again, over the site lab.

    uv run python -m platform_testing.site_vision_loop lab-cleaver lab-selvam [--rounds 2] [--dry-run]

Needs the site lab running (tools/site-lab/serve.sh, port 3005) and a Chrome or
Chromium binary (CHROME_PATH, else the usual install paths). Each page of each
fixture is shot section by section with headless Chrome — reduced motion forced
on, so every section is in its final, fully visible state — on a desktop and a
phone viewport (the lab's `?from=&to=` renders one section at a time). The
shots go to the vision critic (interview/site_vision_critic.py) through the
configured AI provider's image call; its revisions are written back to the lab
files and the site is shot again. A report (scores per round, findings, what
changed) and a contact sheet of the last round land in <lab dir>/critique/.

`--dry-run` uses a canned critic (no AI call, no cost): it exercises the whole
loop. A real run calls the provider once per round per fixture — it is a tool
a person runs on purpose, never part of the test suite.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from platform_core.interview.site_vision_critic import Review, Shot, critique, revise, to_findings

LAB = Path(os.getenv("LOCAH_SITE_LAB_DIR") or ".site-lab")
BASE = os.getenv("LOCAH_SITE_LAB_URL", "http://localhost:3005")
CHROMES = [os.getenv("CHROME_PATH", ""), r"C:\Program Files\Google\Chrome\Application\chrome.exe",
           "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
           "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
VIEWPORTS = {"desktop": (1440, 1000), "phone": (390, 844)}


def chrome() -> str:
    found = next((c for c in CHROMES if c and Path(c).exists()), "") or shutil.which("chromium") or ""
    if not found:
        raise SystemExit("No Chrome found: set CHROME_PATH")
    return found


def shoot(url: str, viewport: str) -> bytes:
    """One screenshot, reduced motion on, scrollbars hidden; a JPEG to keep it light.

    A phone shot goes through the lab's phone frame: desktop Chrome will not
    open a window narrower than ~500px, so the page is framed at 390px wide."""
    width, height = VIEWPORTS[viewport]
    crop = None
    if viewport == "phone":
        from urllib.parse import quote, urlsplit

        parts = urlsplit(url)
        local = parts.path + (f"?{parts.query}" if parts.query else "")
        url = f"{parts.scheme}://{parts.netloc}/site-lab-frame?w={width}&h={height}&src={quote(local, safe='')}"
        crop = (0, 0, width, height)
        width = 520
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "shot.png"
        subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-prefers-reduced-motion", f"--window-size={width},{height}",
                        "--virtual-time-budget=6000", f"--screenshot={out}", url],
                       capture_output=True, timeout=90, check=False)
        data = out.read_bytes() if out.exists() else b""
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(data)).convert("RGB")
        if crop:
            image = image.crop(crop)
        image.thumbnail((960, 960))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=80)
        return buffer.getvalue()
    except Exception:  # noqa: BLE001 — Pillow absent or no image: send what Chrome wrote
        return data


def pages_of(key: str) -> dict[str, Path]:
    found = {"home": LAB / f"{key}.json"}
    for path in sorted(LAB.glob(f"{key}~*.json")):
        found[path.stem.split("~", 1)[1]] = path
    return {slug: path for slug, path in found.items() if path.exists()}


def load(key: str) -> tuple[dict[str, Any], dict[str, Path]]:
    files = pages_of(key)
    datas = {slug: json.loads(path.read_text(encoding="utf-8")) for slug, path in files.items()}
    payload = {"pages": [{"slug": slug, "sections": data["page"]["sections"]} for slug, data in datas.items()],
               "theme_hints": datas["home"].get("theme") or {}}
    return {"payload": payload, "datas": datas}, files


def save(state: dict[str, Any], files: dict[str, Path]) -> None:
    for page in state["payload"]["pages"]:
        data = state["datas"][page["slug"]]
        data["page"]["sections"] = page["sections"]
        files[page["slug"]].write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def shots_for(key: str, payload: dict[str, Any]) -> list[Shot]:
    """Each home section on a desktop; the inner pages' first three; the phone's
    first screens of home — what a client looks at first."""
    shots: list[Shot] = []
    for page in payload["pages"]:
        slug, sections = str(page["slug"]), page["sections"]
        path = f"{BASE}/site-lab/{key}" + ("" if slug == "home" else f"/{slug}")
        limit = len(sections) if slug == "home" else min(3, len(sections))
        for i in range(limit):
            shots.append(Shot(shoot(f"{path}?from={i}&to={i}", "desktop"), slug, "desktop",
                              ((i, str(sections[i]["section_type_id"])),)))
        if slug == "home":
            for i in range(min(3, len(sections))):
                shots.append(Shot(shoot(f"{path}?from={i}&to={i}", "phone"), slug, "phone",
                                  ((i, str(sections[i]["section_type_id"])),)))
    return shots


class CannedCritic:
    """--dry-run: a critic that always says the same, so the loop runs free."""

    async def generate_structured_with_images(self, prompt: str, images: list[Any], schema: dict[str, Any],
                                              model_config: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
        del prompt, images, schema, model_config, timeout_seconds
        return {"scores": {"hierarchy": 6, "imagery": 6, "rhythm": 6, "distinctness": 6, "mobile": 6},
                "findings": [{"code": "excessive_cards", "page": "home", "section": 3, "severity": "medium",
                              "note": "Two grids of boxes in a row."},
                             {"code": "weak_hierarchy", "page": "home", "section": 1, "severity": "low",
                              "note": "The statement competes with the hero."}]}


def sheet(shots: list[Shot], out: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        return
    tiles = [Image.open(io.BytesIO(s.png)).convert("RGB") for s in shots if s.png]
    if not tiles:
        return
    width = 480
    tiles = [t.resize((width, int(t.height * width / t.width))) for t in tiles]
    cols = 4
    rows = [tiles[i:i + cols] for i in range(0, len(tiles), cols)]
    height = sum(max(t.height for t in row) + 8 for row in rows)
    canvas = Image.new("RGB", (cols * (width + 8), height), "#222")
    y = 0
    for row in rows:
        for c, tile in enumerate(row):
            canvas.paste(tile, (c * (width + 8), y))
        y += max(t.height for t in row) + 8
    canvas.save(out, quality=82)


async def run(keys: list[str], rounds: int, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        provider: Any = CannedCritic()
    else:
        from platform_core.website.ai_provider import get_ai_provider

        provider = get_ai_provider()
        if not hasattr(provider, "generate_structured_with_images"):
            raise SystemExit("The configured AI provider cannot look at pictures")
    report: dict[str, Any] = {}
    out_dir = LAB / "critique"
    out_dir.mkdir(parents=True, exist_ok=True)
    for key in keys:
        state, files = load(key)
        history = []
        shots: list[Shot] = []
        tried: set[tuple[str, int, str]] = set()
        for round_no in range(1, rounds + 1):
            shots = shots_for(key, state["payload"])
            review: Review = await critique(provider, shots, state["payload"])
            done = revise(state["payload"], review.findings, tried)
            history.append({"round": round_no, "scores": review.scores, "shots": len(shots),
                            "findings": [f.as_dict() for f in review.findings], "revised": done})
            print(f"{key} round {round_no}: scores={review.scores} findings={len(review.findings)} revised={done}")
            if not done:
                break
            save(state, files)
        sheet(shots, out_dir / f"{key}.jpg")
        report[key] = history
    (out_dir / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


def main(argv: list[str]) -> None:  # pragma: no cover — a tool
    rounds = int(argv[argv.index("--rounds") + 1]) if "--rounds" in argv else 2
    keys = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--rounds")]
    asyncio.run(run(keys, rounds, "--dry-run" in argv))


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])


__all__ = ["CannedCritic", "run", "shots_for", "to_findings"]
