"""Near-duplicate pictures: two different files a visitor sees as the same picture.

A page must never show one picture twice — and "twice" includes a different
file of the same view: the same photograph from two libraries or in two crops,
or drawings that came back alike (three near-identical white rooms on one hotel
site, 2026-11-24). A difference hash (dHash) of a small greyscale copy is
compared bit by bit; pictures within NEAR bits of each other are one picture.
"""

from __future__ import annotations

import io

from PIL import Image

# Of 64 bits. Same photo re-encoded or resized: 0-4; same scene, other shot: ~6-12;
# unrelated pictures: ~25-40. Ten keeps a second view of one place apart from a copy.
NEAR = 10


def fingerprint(data: bytes) -> int | None:
    """A 64-bit difference hash of an image, or None when it cannot be read."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            small = im.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
            px = list(small.getdata())
    except Exception:  # noqa: BLE001 — an unreadable preview is simply not compared
        return None
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (1 if px[row * 9 + col] > px[row * 9 + col + 1] else 0)
    return bits


def distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def near_any(fp: int | None, others: list[int]) -> bool:
    """Whether a fingerprint is a near-duplicate of any of `others`."""
    return fp is not None and any(distance(fp, other) <= NEAR for other in others)
