"""Screenshots of site-lab pages for before/after comparisons — no API, no model.

    uv run python -m platform_testing.lab_shots <out_dir> lab-crumb lab-ishant …

Needs the site lab running (tools/site-lab/serve.sh, port 3005) and Chrome.
For each key: the home page's first screen on a desktop (1440) and a phone
(390), then each home section on its own (desktop), so heroes, ranges,
stories and statements can be compared one by one; and a contact sheet of
everything in <out_dir>/<key>/sheet.jpg. Reduced motion is forced on, so
every section is in its final, fully visible state.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from platform_testing.site_vision_loop import BASE, LAB, shoot


def sheet(images: list[tuple[str, bytes]], out: Path, columns: int = 3) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:  # pragma: no cover
        return
    tiles = []
    for label, data in images:
        try:
            tile = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:  # noqa: BLE001
            continue
        tile.thumbnail((640, 640))
        canvas = Image.new("RGB", (640, tile.height + 28), "white")
        canvas.paste(tile, (0, 28))
        ImageDraw.Draw(canvas).text((8, 8), label, fill="black")
        tiles.append(canvas)
    if not tiles:
        return
    rows = (len(tiles) + columns - 1) // columns
    height = max(t.height for t in tiles)
    board = Image.new("RGB", (640 * columns, height * rows), (240, 240, 240))
    for i, tile in enumerate(tiles):
        board.paste(tile, ((i % columns) * 640, (i // columns) * height))
    board.save(out, "JPEG", quality=82)


def main(out_dir: str, keys: list[str]) -> None:  # pragma: no cover — a tool
    root = Path(out_dir)
    for key in keys:
        folder = root / key
        folder.mkdir(parents=True, exist_ok=True)
        page = json.loads((LAB / f"{key}.json").read_text(encoding="utf-8"))
        sections = page["page"]["sections"]
        url = f"{BASE}/site-lab/{key}"
        shots: list[tuple[str, bytes]] = []
        for viewport in ("desktop", "phone"):
            data = shoot(url, viewport)
            (folder / f"first-screen-{viewport}.jpg").write_bytes(data)
            shots.append((f"{key} first screen ({viewport})", data))
        for i, section in enumerate(sections):
            kind = str(section.get("section_type_id") or section.get("layout_variant") or "section")
            data = shoot(f"{url}?from={i}&to={i}", "desktop")
            (folder / f"section-{i:02d}-{kind}.jpg").write_bytes(data)
            shots.append((f"{i:02d} {kind} / {section.get('layout_variant')}", data))
        sheet(shots, folder / "sheet.jpg")
        print(key, len(shots), "shots ->", folder)


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1], sys.argv[2:])
