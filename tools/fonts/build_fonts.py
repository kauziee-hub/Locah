"""Self-hosted, subset typefaces for LOCAH's apps: no build ever fetches a font.

`next/font/google` downloaded every face from Google at build time, so a
production build failed whenever one fetch did (2026-11-24). The faces now live
in the repository as small WOFF2 files cut by this script.

Sources are the OFL originals in github.com/google/fonts at one pinned commit,
recorded with checksums in `sources.lock.json`. Each face is cut to what a page
draws:

  latin       Latin-1, general punctuation and the rupee sign. Google files ₹
              (U+20B9) under latin-ext, so a menu with prices downloaded a
              second, ~100 KB file for that one glyph (392 KB of fonts on the
              baseline restaurant page).
  tamil       the Tamil block (and danda) only: never ₹ or shared punctuation,
  devanagari  so a page downloads an Indic face only when it shows that script.

Axes the CSS never moves are pinned (Fraunces's upright is never wonky; Noto's
width is always 100). Hinting is dropped; layout features are kept.

  uv run --no-project --with fonttools==4.55.3 --with brotli==1.1.0 \\
      python tools/fonts/build_fonts.py [--fetch]

`--fetch` downloads the sources into certify-out/font-src (once); without it the
script only cuts from that cache and checks every source against the lock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "certify-out" / "font-src"
LOCK = Path(__file__).with_name("sources.lock.json")
WEB_OUT = ROOT / "apps" / "web" / "src" / "fonts"
WORKSPACE_OUT = ROOT / "apps" / "workspace" / "src" / "app" / "fonts"

GOOGLE_FONTS_COMMIT = "83c62e30d87daa70216dab6b984d00d20d96d585"

# Google's own latin subset, plus U+20B9 (₹).
LATIN = (
    "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,"
    "U+0329,U+2000-206F,U+20AC,U+20B9,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"
)
# The glyphs an Indic face carries (shaping needs ZWJ/ZWNJ and the dotted circle)...
TAMIL_GLYPHS = "U+0964-0965,U+0B80-0BFF,U+200C-200D,U+25CC"
DEVANAGARI_GLYPHS = "U+0900-097F,U+1CD0-1CF9,U+200C-200D,U+25CC,U+A830-A839,U+A8E0-A8FF"
# ...and the range that makes a browser download it: the script itself, nothing shared.
UNICODE_RANGE = {
    "latin": LATIN.replace(",", ", "),
    "tamil": "U+0B80-0BFF",
    "devanagari": "U+0900-097F, U+1CD0-1CF9, U+A8E0-A8FF",
}
GLYPHS = {"latin": LATIN, "tamil": TAMIL_GLYPHS, "devanagari": DEVANAGARI_GLYPHS}

# pyftsubset's defaults (kerning, ligatures, marks, Indic shaping) plus the numeral
# and case features the site CSS asks for. Not "*": stylistic sets and swashes
# would bring in hundreds of alternate glyphs no page draws.
EXTRA_FEATURES = ["tnum", "lnum", "onum", "pnum", "case"]


@dataclass(frozen=True)
class Cut:
    """One output file: a source file, the axes pinned in it, the glyph set."""

    out: str
    source: str
    subset: str = "latin"
    pin: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Face:
    family_dir: str
    cuts: tuple[Cut, ...]


def _v(name: str, *, italic: str | None = None, pin: dict[str, float] | None = None,
       italic_pin: dict[str, float] | None = None, subset: str = "latin") -> tuple[Cut, ...]:
    """A variable face: its upright and (optionally) italic source file."""
    stem = name.split("[")[0]
    out = [Cut(f"{stem.lower()}-normal.woff2", name, subset, pin or {})]
    if italic:
        out.append(Cut(f"{stem.lower()}-italic.woff2", italic, subset, italic_pin or {}))
    return tuple(out)


FACES: list[Face] = [
    # Fraunces: the upright is never wonky (site-dna.css pins WONK 0); the italic
    # keeps WONK and SOFT for warm_craft's hand-cut accent.
    Face("fraunces", _v("Fraunces[SOFT,WONK,opsz,wght].ttf", italic="Fraunces-Italic[SOFT,WONK,opsz,wght].ttf",
                         pin={"WONK": 0})),
    Face("anton", (Cut("anton-normal.woff2", "Anton-Regular.ttf"),)),
    Face("manrope", _v("Manrope[wght].ttf")),
    Face("playfairdisplay", _v("PlayfairDisplay[wght].ttf", italic="PlayfairDisplay-Italic[wght].ttf")),
    Face("dmsans", _v("DMSans[opsz,wght].ttf", italic="DMSans-Italic[opsz,wght].ttf")),
    Face("archivo", _v("Archivo[wdth,wght].ttf", italic="Archivo-Italic[wdth,wght].ttf")),
    Face("outfit", _v("Outfit[wght].ttf")),
    Face("ibmplexsans", _v("IBMPlexSans[wdth,wght].ttf", pin={"wdth": 100})),
    Face("cormorantgaramond", _v("CormorantGaramond[wght].ttf", italic="CormorantGaramond-Italic[wght].ttf")),
    Face("bricolagegrotesque", _v("BricolageGrotesque[opsz,wdth,wght].ttf")),
    Face("newsreader", _v("Newsreader[opsz,wght].ttf", italic="Newsreader-Italic[opsz,wght].ttf")),
    Face("ibmplexmono", (Cut("ibmplexmono-400.woff2", "IBMPlexMono-Regular.ttf"),
                         Cut("ibmplexmono-500.woff2", "IBMPlexMono-Medium.ttf"))),
    Face("syne", _v("Syne[wght].ttf")),
    Face("unbounded", _v("Unbounded[wght].ttf")),
    Face("dmserifdisplay", (Cut("dmserifdisplay-normal.woff2", "DMSerifDisplay-Regular.ttf"),
                            Cut("dmserifdisplay-italic.woff2", "DMSerifDisplay-Italic.ttf"))),
    Face("bodonimoda", _v("BodoniModa[opsz,wght].ttf", italic="BodoniModa-Italic[opsz,wght].ttf")),
    Face("youngserif", (Cut("youngserif-normal.woff2", "YoungSerif-Regular.ttf"),)),
    Face("bigshouldersdisplay", _v("BigShouldersDisplay[wght].ttf")),
    Face("spacegrotesk", _v("SpaceGrotesk[wght].ttf")),
    Face("italiana", (Cut("italiana-normal.woff2", "Italiana-Regular.ttf"),)),
    Face("instrumentserif", (Cut("instrumentserif-normal.woff2", "InstrumentSerif-Regular.ttf"),
                             Cut("instrumentserif-italic.woff2", "InstrumentSerif-Italic.ttf"))),
    Face("intertight", _v("InterTight[wght].ttf", italic="InterTight-Italic[wght].ttf")),
    Face("instrumentsans", _v("InstrumentSans[wdth,wght].ttf", italic="InstrumentSans-Italic[wdth,wght].ttf")),
    Face("caveat", _v("Caveat[wght].ttf")),
    # LOCAH's own pages (apps/web/src/app/layout.tsx).
    Face("plusjakartasans", _v("PlusJakartaSans[wght].ttf")),
    Face("aneklatin", _v("AnekLatin[wdth,wght].ttf")),
    # Indic: width is always 100.
    Face("notosanstamil", (Cut("notosanstamil-normal.woff2", "NotoSansTamil[wdth,wght].ttf", "tamil",
                               {"wdth": 100}),)),
    Face("notosansdevanagari", (Cut("notosansdevanagari-normal.woff2", "NotoSansDevanagari[wdth,wght].ttf",
                                    "devanagari", {"wdth": 100}),)),
]
# The Workspace takes its own copies of the Indic cuts (apps do not import other apps).
WORKSPACE_COPIES = {"notosanstamil-normal.woff2", "notosansdevanagari-normal.woff2"}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "locah-font-build"})
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 — fixed https hosts
        return bytes(resp.read())


def fetch() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    lock: dict[str, dict[str, str]] = {}
    for face in FACES:
        for cut in face.cuts:
            target = CACHE / cut.source
            rel = f"ofl/{face.family_dir}/{cut.source}"
            if not target.exists():
                url = (f"https://raw.githubusercontent.com/google/fonts/{GOOGLE_FONTS_COMMIT}/"
                       + urllib.parse.quote(rel))
                print("fetch", rel, flush=True)
                target.write_bytes(_get(url))
            lock[cut.source] = {"path": rel, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
        # The family's own copyright and licence travel with its files (OFL 1.1, condition 2).
        licence = CACHE / f"{face.family_dir}.OFL.txt"
        if not licence.exists():
            licence.write_bytes(_get(f"https://raw.githubusercontent.com/google/fonts/{GOOGLE_FONTS_COMMIT}/"
                                     f"ofl/{face.family_dir}/OFL.txt"))
        lock[licence.name] = {"path": f"ofl/{face.family_dir}/OFL.txt",
                              "sha256": hashlib.sha256(licence.read_bytes()).hexdigest()}
    LOCK.write_text(json.dumps({"repository": "google/fonts", "commit": GOOGLE_FONTS_COMMIT,
                                "licence": "SIL Open Font License 1.1", "files": lock}, indent=1) + "\n",
                    encoding="utf-8")


def _verify(source: str) -> Path:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))["files"]
    path = CACHE / source
    if not path.exists():
        sys.exit(f"missing source {source}: run with --fetch")
    if hashlib.sha256(path.read_bytes()).hexdigest() != lock[source]["sha256"]:
        sys.exit(f"source {source} does not match sources.lock.json")
    return path


def cut_one(cut: Cut) -> bytes:
    from io import BytesIO

    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    font = TTFont(_verify(cut.source))
    if cut.pin and "fvar" in font:
        pinned = BytesIO()
        instancer.instantiateVariableFont(font, dict(cut.pin)).save(pinned)
        pinned.seek(0)
        font = TTFont(pinned)  # reloaded: the subsetter cannot read a just-instanced gvar
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = [*options.layout_features, *EXTRA_FEATURES]
    options.hinting = False
    options.desubroutinize = True
    # Names, with the copyright (0), licence (13) and licence URL (14) kept in the file.
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
    options.notdef_outline = True
    sub = subset.Subsetter(options)
    sub.populate(unicodes=subset.parse_unicodes(GLYPHS[cut.subset]))
    sub.subset(font)
    buf = BytesIO()
    font.flavor = "woff2"
    font.save(buf)
    return buf.getvalue()


def build() -> None:
    WEB_OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    manifest: dict[str, dict[str, object]] = {}
    for face in FACES:
        licence = _verify(f"{face.family_dir}.OFL.txt").read_bytes()
        (WEB_OUT / "licences").mkdir(exist_ok=True)
        (WEB_OUT / "licences" / f"{face.family_dir}.txt").write_bytes(licence)
        if any(cut.out in WORKSPACE_COPIES for cut in face.cuts):
            (WORKSPACE_OUT / "licences").mkdir(exist_ok=True)
            (WORKSPACE_OUT / "licences" / f"{face.family_dir}.txt").write_bytes(licence)
        for cut in face.cuts:
            data = cut_one(cut)
            (WEB_OUT / cut.out).write_bytes(data)
            if cut.out in WORKSPACE_COPIES:
                (WORKSPACE_OUT / cut.out).write_bytes(data)
            total += len(data)
            manifest[cut.out] = {"source": cut.source, "subset": cut.subset, "pinned": cut.pin,
                                 "unicode_range": UNICODE_RANGE[cut.subset], "kb": round(len(data) / 1024, 1)}
            print(f"{len(data) / 1024:7.1f} KB  {cut.out}", flush=True)
    (WEB_OUT / "fonts.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"{total / 1024:7.1f} KB  total")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if args.fetch:
        fetch()
    build()
