"""The certification repair loop, orchestrated (python/testing/platform_testing/certify/).

No model, no API, no browser: the fix round, the re-render and the critic are
fakes. What is proven: the loop ends in a pass as soon as a re-critique passes,
fails closed with the owner's requests after the last round, stops early (and
says so) when a round finds nothing to try, never re-judges when every fix was
reverted, re-judges only the pages a kept fix touched; a fix is kept only when
its page clears the margin with no new critical defect, and is never tried
twice; the critic keeps an untouched page's judgment, asks a cut-off answer
once more with room, and drops section numbers it never listed; the re-render
merges only the touched pages and keeps the before.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from platform_testing.certify import critic, gate, repair, run

# ----------------------------------------------------------------- helpers


def _dims(value: float, **over: float) -> dict[str, float]:
    return {d: value for d in gate.DIMENSIONS} | over


def _critique(value: float, *, defects: list[dict[str, Any]] | None = None, **pages: float) -> dict[str, Any]:
    scores = _dims(value)
    return {"scores": scores, "weighted_score": round(gate.weighted_score(scores), 2),
            "page_weighted": pages or {"home": value}, "defects": defects or [], "complete": True,
            "category": "hotel", "business": "Valley Stay"}


PHOTO_INPUT = {"id": "r1:page:home:1", "page": "home", "section": 2, "severity": "critical", "layer": "input",
               "text": "The rooms show blank grey frames where photographs of the rooms should be.",
               "source": "vision"}


class Script:
    """A fix round and a rejudge that answer from lists and record their calls."""

    def __init__(self, rounds: list[list[dict[str, Any]]], judged: list[dict[str, Any]]) -> None:
        self.rounds, self.judged = rounds, judged
        self.fix_calls: list[tuple[dict[str, Any], int]] = []
        self.rejudge_calls: list[tuple[set[str], int]] = []

    async def fix_round(self, critique: dict[str, Any], round_no: int) -> list[dict[str, Any]]:
        self.fix_calls.append((critique, round_no))
        return self.rounds[len(self.fix_calls) - 1]

    async def rejudge(self, critique: dict[str, Any], pages: set[str], round_no: int) -> dict[str, Any]:
        self.rejudge_calls.append((pages, round_no))
        return self.judged[len(self.rejudge_calls) - 1]


def _kept(page: str) -> dict[str, Any]:
    return {"page": page, "lever": "variant", "kept": True}


def _reverted(page: str) -> dict[str, Any]:
    return {"page": page, "lever": "variant", "kept": False}


# ----------------------------------------------------------------- the gate's last word


def test_a_final_verdict_fails_closed_early_and_records_the_rounds_used() -> None:
    weak = _critique(6.0, defects=[PHOTO_INPUT])
    assert gate.decide(weak, rounds_used=1, max_rounds=3)["status"] == "repair"
    early = gate.decide(weak, rounds_used=1, max_rounds=3, final=True)
    assert early["status"] == "fail_closed" and early["rounds_used"] == 1
    assert any("no automatic repair left" in r for r in early["reasons"])
    assert early["owner_request_details"][0]["kind"] == "photos" and early["blocked_on"] == "owner"
    strong = _critique(9.0)
    assert gate.decide(strong, rounds_used=1, max_rounds=3, final=True)["status"] == "pass"


# ----------------------------------------------------------------- until_verdict


async def test_a_site_that_passes_first_is_never_repaired() -> None:
    script = Script([], [])
    out = await repair.until_verdict(_critique(9.0), fix_round=script.fix_round, rejudge=script.rejudge)
    assert out["verdict"]["status"] == "pass" and out["rounds_used"] == 1 and out["rounds"] == []
    assert script.fix_calls == []


async def test_the_loop_ends_in_a_pass_when_the_recritique_passes() -> None:
    start = _critique(7.5, home=7.0, visit=8.0)
    better = _critique(9.0, home=9.0, visit=9.0)
    script = Script([[_kept("home"), _reverted("visit")]], [better])
    out = await repair.until_verdict(start, fix_round=script.fix_round, rejudge=script.rejudge, max_rounds=3)
    assert out["verdict"]["status"] == "pass" and out["rounds_used"] == 2
    assert script.rejudge_calls == [({"home"}, 2)]  # only the page a kept fix touched
    assert out["critique"] is better
    assert out["rounds"] == [{"round": 2, "score_before": start["weighted_score"], "attempts": 2, "kept": 1,
                              "touched": ["home"], "score_after": better["weighted_score"]}]


async def test_after_the_last_round_the_site_fails_closed_with_owner_requests() -> None:
    start = _critique(5.0, defects=[PHOTO_INPUT])
    r2 = _critique(5.5, defects=[PHOTO_INPUT])
    r3 = _critique(6.0, defects=[PHOTO_INPUT])
    script = Script([[_kept("home")], [_kept("home"), _kept("about")]], [r2, r3])
    out = await repair.until_verdict(start, fix_round=script.fix_round, rejudge=script.rejudge, max_rounds=3)
    verdict = out["verdict"]
    assert verdict["status"] == "fail_closed" and verdict["rounds_used"] == 3
    assert [n for _, n in script.fix_calls] == [2, 3]
    assert script.fix_calls[1][0] is r2  # round 3 plans from round 2's critique
    assert script.rejudge_calls == [({"home"}, 2), ({"about", "home"}, 3)]
    assert verdict["owner_requests"] and "photographs" in verdict["owner_requests"][0]
    assert verdict["blocked_on"] == "owner"
    assert [r["score_after"] for r in out["rounds"]] == [r2["weighted_score"], r3["weighted_score"]]


async def test_a_round_with_nothing_to_try_stops_the_loop_early() -> None:
    start = _critique(5.0, defects=[PHOTO_INPUT])
    script = Script([[]], [])
    out = await repair.until_verdict(start, fix_round=script.fix_round, rejudge=script.rejudge, max_rounds=3)
    assert out["verdict"]["status"] == "fail_closed" and out["rounds_used"] == 1
    assert out["rounds"] == [{"round": 2, "score_before": start["weighted_score"], "attempts": 0, "kept": 0,
                              "touched": [], "stopped": "no automatic repair left"}]
    assert script.rejudge_calls == []
    assert out["verdict"]["owner_requests"]


async def test_reverted_fixes_leave_the_critique_and_the_next_round_tries_again() -> None:
    start = _critique(5.0)
    start["scores"]["imagery"] = 8.0  # nothing for the owner to send
    script = Script([[_reverted("home")], [_reverted("visit")]], [])
    out = await repair.until_verdict(start, fix_round=script.fix_round, rejudge=script.rejudge, max_rounds=3)
    assert script.rejudge_calls == []  # nothing changed on the site: nothing to judge again
    assert [c for c, _ in script.fix_calls] == [start, start]
    assert out["verdict"]["status"] == "fail_closed" and out["rounds_used"] == 3
    assert out["verdict"]["blocked_on"] == "platform"  # nothing the owner could add


# ----------------------------------------------------------------- one round, live levers faked

PAGE = {"slug": "home", "sections": [
    {"id": "s-hero", "section_type_id": "hero", "layout_variant": "window", "content": {"headline": "Stay"}},
    {"id": "s-faq", "section_type_id": "faq", "layout_variant": "list", "content": {"title": "Questions"}},
    {"id": "s-stmt", "section_type_id": "statement", "layout_variant": "giant", "content": {"text": "x"}},
]}


def _defect(text: str, layer: str = "styling", severity: str = "major") -> dict[str, Any]:
    return {"page": "home", "section": -1, "text": text, "layer": layer, "severity": severity, "source": "vision"}


JOURNEY = {"owner_id": "00000000-0000-0000-0000-000000000001", "owner_email": "owner@example.test",
           "business_id": "00000000-0000-0000-0000-000000000002", "slug": "valley-stay",
           "site_key": "hotel--normal", "public_url": "http://localhost:3200/valley-stay", "scenario": "hotel"}


@pytest.fixture
def levers(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """apply / revert / variants recorded instead of reaching the Workspace API."""
    seen: dict[str, list[Any]] = {"applied": [], "reverted": []}

    async def variants(ws: Any, b: str) -> dict[str, list[str]]:
        return {"hero": ["window", "split"], "faq": ["list"], "statement": ["giant", "quiet"]}

    async def apply(fix: dict[str, Any], site: Any, ws: Any, b: str, options: dict[str, list[str]]) -> dict[str, Any]:
        seen["applied"].append(fix["key"])
        if not [v for v in options.get(str(fix["section"]["section_type_id"]), [])
                if v != fix["section"]["layout_variant"]]:
            return {"skipped": "no other layout for this section"}
        return {"before": {}, "kind": fix["section"]["section_type_id"], "page": fix["page"]}

    async def revert(undo: dict[str, Any], fix: dict[str, Any], site: Any, ws: Any, b: str) -> None:
        seen["reverted"].append(fix["key"])

    monkeypatch.setattr(repair, "variants_by_type", variants)
    monkeypatch.setattr(repair, "apply", apply)
    monkeypatch.setattr(repair, "revert", revert)
    return seen


async def test_a_fix_is_kept_only_above_the_margin_and_never_tried_twice(
        tmp_path: Path, levers: dict[str, list[Any]]) -> None:
    after = iter([{"score": 5.2, "critical": 0}, {"score": 5.6, "critical": 0}, {"score": 5.9, "critical": 1}])

    async def score(folder: Path, journey: dict[str, Any], page: str, tag: str, category: str) -> dict[str, Any]:
        return next(after)

    critique: dict[str, Any] = {"page_weighted": {"home": 5.0}, "defects": [
        _defect("The hero is flat and timid", severity="critical"),
        _defect("The FAQ is cramped"),
        _defect("The statement feels like a template"),
    ]}
    async with repair.Repairer(tmp_path, JOURNEY, "hotel", score=score) as fixer:
        async def draft() -> dict[str, Any]:
            return {"pages": [PAGE]}

        fixer.site.draft = draft
        first = await fixer.round(critique, 2, per_round=3)
        assert [(a["section"], a["kept"]) for a in first] == [("hero", False), ("faq", False), ("statement", True)]
        assert first[0]["before"] == 5.0 and first[0]["after"] == 5.2  # +0.2 is inside the critic's wobble
        assert first[1]["why"] == "no other layout for this section"
        assert first[2]["after"] == 5.6
        assert levers["reverted"] == ["s-hero:variant"]

        after = iter([{"score": 5.95, "critical": 0}])
        second = await fixer.round(critique, 3, per_round=3)
        assert second == []  # every section's fix was tried already
        new = dict(critique, page_weighted={"home": 5.8}, defects=critique["defects"] + [
            _defect("The statement repeats the hero twice", layer="order")])
        third = await fixer.round(new, 3, per_round=3)
        # A new critique is the new baseline: 5.95 does not clear 5.8 + 0.25.
        assert [(a["lever"], a["before"], a["kept"]) for a in third] == [("hide", 5.8, False)]
        assert fixer.attempts == first + third
    assert levers["applied"] == ["s-hero:variant", "s-faq:variant", "s-stmt:variant", "s-stmt:hide"]


async def test_a_new_critical_defect_reverts_even_a_better_score(tmp_path: Path, levers: dict[str, list[Any]]) -> None:
    found = iter([{"score": 7.0, "critical": 2}, {"score": 7.0, "critical": 1}])

    async def score(folder: Path, journey: dict[str, Any], page: str, tag: str, category: str) -> dict[str, Any]:
        return next(found)

    owners = dict(_defect("No photographs of the rooms anywhere", layer="input", severity="critical"))
    async with repair.Repairer(tmp_path, JOURNEY, "hotel", score=score, levers={"variant"}) as fixer:
        async def draft() -> dict[str, Any]:
            return {"pages": [PAGE]}

        fixer.site.draft = draft
        critique = {"page_weighted": {"home": 5.0}, "defects": [
            owners, _defect("The hero is flat"), _defect("The hero photo is stock", layer="photo"),
            _defect("The statement feels like a template")]}
        done = await fixer.round(critique, 2)
    # The page had one critical defect (the owner's photographs): a fix that adds
    # a second is reverted; one that leaves it at one, and scores better, is kept.
    assert [(a["section"], a["lever"], a["critical_before"], a["critical_after"], a["kept"]) for a in done] == [
        ("hero", "variant", 1, 2, False), ("statement", "variant", 1, 1, True)]  # the photo lever is off
    assert levers["reverted"] == ["s-hero:variant"]


async def test_with_two_judgments_before_and_after_are_both_means(
        tmp_path: Path, levers: dict[str, list[Any]]) -> None:
    calls: list[str] = []
    found = iter([{"score": 4.6, "critical": 1},                                   # home as it stands, again
                  {"score": 5.4, "critical": 1}, {"score": 5.0, "critical": 2},   # the hero fix, twice
                  {"score": 5.3, "critical": 1}, {"score": 5.1, "critical": 1}])  # the statement fix, twice

    async def score(folder: Path, journey: dict[str, Any], page: str, tag: str, category: str) -> dict[str, Any]:
        calls.append(tag)
        return next(found)

    async with repair.Repairer(tmp_path, JOURNEY, "hotel", score=score, levers={"variant"}, judgments=2) as fixer:
        async def draft() -> dict[str, Any]:
            return {"pages": [PAGE]}

        fixer.site.draft = draft
        critique = {"page_weighted": {"home": 5.0}, "defects": [
            _defect("No photographs of the rooms anywhere", layer="input", severity="critical"),
            _defect("The hero is flat"), _defect("The statement feels like a template")]}
        done = await fixer.round(critique, 2)
    # The baseline is judged once more (5.0 and 4.6 → 4.8), each fix twice.
    assert calls == ["r2-0-base", "r2-0-0", "r2-0-1", "r2-1-0", "r2-1-1"]
    assert [(a["section"], a["before"], a["after"], a["readings"], a["critical_after"], a["kept"]) for a in done] == [
        ("hero", 4.8, 5.2, [5.4, 5.0], 2, False),       # better, but one reading found a new critical defect
        ("statement", 4.8, 5.2, [5.3, 5.1], 1, True)]   # 5.2 ≥ 4.8 + 0.25


# ----------------------------------------------------------------- the critic, between rounds


def _png(path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 180, 160)).save(path, format="PNG")


def _render_site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    pages = []
    for slug in ("home", "visit"):
        _png(site / "shots" / f"{slug}__laptop.png", (1440, 2400))
        _png(site / "shots" / f"{slug}__mobile.png", (390, 4000))
        pages.append({"slug": slug, "status": 200, "title": slug, "meta": {"description": "d"},
                      "viewports": {vp: {"png": f"shots/{slug}__{vp}.png", "overflow_x": False}
                                    for vp in ("laptop", "mobile")}})
    (site / "render.json").write_text(json.dumps({"pages": pages}), encoding="utf-8")
    return site


class Vision:
    model_name = "fake-vision"

    def __init__(self, answers: dict[str, list[Any]]) -> None:
        self.answers = answers
        self.calls: list[dict[str, Any]] = []

    async def generate_structured_with_images(self, prompt: str, images: list[Any], schema: dict[str, Any],
                                              model_config: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
        ctx = json.loads(prompt)
        for i in images:
            Image.open(io.BytesIO(i.data))
        key = ctx.get("page", "*")
        self.calls.append({"key": key, "ctx": ctx, "config": model_config})
        n = sum(1 for c in self.calls if c["key"] == key) - 1
        answer = self.answers[key][min(n, len(self.answers[key]) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return dict(answer)


def _page(value: float, *defects: dict[str, Any]) -> dict[str, Any]:
    return {"scores": {d: value for d in critic.PAGE_DIMENSIONS}, "verdict": "-", "defects": list(defects)}


CROSS = {"scores": {"consistency": 5, "originality": 5}, "verdict": "-", "defects": []}
DRAFT = {"draft": {"pages": [{"slug": "home", "sections": [
    {"section_type_id": "hero", "layout_variant": "window", "content": {"headline": "Valley Stay"}},
    {"section_type_id": "faq", "layout_variant": "list", "is_visible": False, "content": {"title": "Hidden"}},
    {"section_type_id": "product_showcase", "layout_variant": "stack", "content": {"title": "Rooms"}},
]}]}}


async def test_an_untouched_page_keeps_its_judgment_and_a_touched_one_is_judged_again(tmp_path: Path) -> None:
    site = _render_site(tmp_path)
    first = await critic.critique_site(
        Vision({"home": [_page(4, {"section": 1, "severity": "major", "layer": "styling",
                                   "text": "The rooms grid is cramped."})],
                "visit": [_page(5, {"section": 0, "severity": "critical", "layer": "architecture",
                                    "text": "No street address."})],
                "*": [CROSS]}),
        site, DRAFT, category="hotel", round_no=1, references_dir=tmp_path / "none")
    again = Vision({"home": [_page(6)], "visit": [_page(9)], "*": [CROSS]})
    second = await critic.critique_site(again, site, DRAFT, category="hotel", round_no=2,
                                        references_dir=tmp_path / "none", carry=first, rejudge={"home"})

    assert [c["key"] for c in again.calls] == ["home", "*"]  # visit was not judged again
    assert second["carried"] == ["visit"]
    assert second["page_scores"]["visit"] == first["page_scores"]["visit"]
    assert second["page_weighted"] == {"home": 6.0, "visit": 5.0}
    assert list(second["page_scores"]) == ["home", "visit"]  # render order
    carried = [d for d in second["defects"] if d.get("carried")]
    assert [(d["page"], d["text"]) for d in carried] == [("visit", "No street address.")]
    assert not [d for d in second["defects"] if d["page"] == "home" and d["source"] == "vision"]
    assert second["complete"] is True
    older = dict(first, version="certify-critic-v1",
                 defects=[dict(d, section=0) if d["page"] == "visit" else d for d in first["defects"]])
    third = await critic.critique_site(Vision({"home": [_page(6)], "*": [CROSS]}), site, DRAFT, category="hotel",
                                       round_no=3, write=False, references_dir=tmp_path / "none",
                                       carry=older, rejudge={"home"})
    assert [d["section"] for d in third["defects"] if d.get("carried")] == [-1]  # v1 never listed sections
    # The draft's visible sections are what the critic is shown, numbered as the page shows them.
    home_ctx = again.calls[0]["ctx"]
    assert home_ctx["sections"] == [{"index": 0, "type": "hero", "layout": "window", "title": "Valley Stay"},
                                    {"index": 1, "type": "product_showcase", "layout": "stack", "title": "Rooms"}]
    assert (site / "critique.r2.json").is_file()


async def test_a_cut_off_answer_is_asked_once_more_with_room(tmp_path: Path) -> None:
    site = _render_site(tmp_path)
    vision = Vision({"home": [RuntimeError("DeepSeek returned empty content (length)"), _page(5)],
                     "visit": [RuntimeError("deepseek unavailable (503): busy")], "*": [CROSS]})
    out = await critic.critique_site(vision, site, {}, category="hotel", round_no=1, write=False,
                                     references_dir=tmp_path / "none")
    home = [c for c in vision.calls if c["key"] == "home"]
    assert [c["config"]["max_output_tokens"] for c in home] == [critic.OUTPUT_TOKENS, critic.RETRY_OUTPUT_TOKENS]
    assert out["page_weighted"]["home"] == 5.0
    assert len([c for c in vision.calls if c["key"] == "visit"]) == 1  # any other failure is not retried
    assert any(e.startswith("visit: vision call failed") for e in out["errors"]) and out["complete"] is False


async def test_a_section_number_the_critic_was_never_shown_names_no_section(tmp_path: Path) -> None:
    site = _render_site(tmp_path)
    out = await critic.critique_site(
        Vision({"home": [_page(5, {"section": 7, "severity": "major", "layer": "styling", "text": "Odd gap."},
                                  {"section": 1, "severity": "major", "layer": "styling", "text": "Cramped."})],
                "visit": [_page(5, {"section": 0, "severity": "minor", "layer": "copy", "text": "Thin."})],
                "*": [CROSS]}),
        site, DRAFT, category="hotel", round_no=1, write=False, references_dir=tmp_path / "none")
    by = {d["text"]: d["section"] for d in out["defects"] if d["source"] == "vision"}
    assert by == {"Odd gap.": -1, "Cramped.": 1, "Thin.": -1}  # visit lists no sections


# ----------------------------------------------------------------- the re-render merge


def test_rerender_merges_only_the_touched_pages_and_keeps_the_before(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    site = _render_site(tmp_path)
    (site / "journey.json").write_text("{}", encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def node(*args: str, timeout: int = 900) -> tuple[int, str]:
        calls.append(args)
        out = Path(args[1])
        _png(out / "shots" / "home__laptop.png", (1440, 1000))
        (out / "render.json").write_text(json.dumps({"pages": [
            {"slug": "home", "status": 200, "title": "new", "viewports": {
                "laptop": {"png": "shots/home__laptop.png"}}},
            {"slug": "elsewhere", "status": 200, "viewports": {}}]}), encoding="utf-8")
        return 0, ""

    monkeypatch.setattr(run, "_node", node)
    merged = run.rerender(site, "http://localhost:3200/valley-stay", {"home"}, 2)
    assert merged == ["home"]
    assert calls[0][-3:] == ("--pages", "home", "--only")
    render = json.loads((site / "render.json").read_text(encoding="utf-8"))
    assert [(p["slug"], p["title"]) for p in render["pages"]] == [("home", "new"), ("visit", "visit")]
    assert render["rerendered"] == {"2": ["home"]}
    assert json.loads((site / "render.r1.json").read_text(encoding="utf-8"))["pages"][0]["title"] == "home"
    assert Image.open(site / "shots" / "home__laptop.png").size == (1440, 1000)
    assert Image.open(site / "shots-r1" / "home__laptop.png").size == (1440, 2400)
    assert sorted(p.name for p in (site / "shots-r1").iterdir()) == ["home__laptop.png", "home__mobile.png"]


def test_rerender_that_renders_nothing_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    site = _render_site(tmp_path)
    (site / "journey.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(run, "_node", lambda *a, timeout=900: (1, "chrome did not start"))
    with pytest.raises(RuntimeError, match="re-render"):
        run.rerender(site, "http://localhost:3200/valley-stay", {"home"}, 2)
    assert json.loads((site / "render.json").read_text(encoding="utf-8"))["pages"][0]["title"] == "home"


def test_the_command_line_reads_the_repair_options() -> None:
    args, opts = run._cli(["certify-out/run7", "hotel", "normal", "--reuse", "--repair", "--rounds", "2",
                           "--no-photos"])
    assert args == ["certify-out/run7", "hotel", "normal"]
    assert opts == {"max_rounds": 2, "reuse": True, "critic": True, "render": True, "repair": True,
                    "photos": False}
    _, fast = run._cli(["r", "s", "v", "--fast"])
    assert fast["critic"] is False and fast["render"] is False and fast["repair"] is False


# ----------------------------------------------------------------- the report


def test_the_report_shows_the_repair_rounds_and_the_final_verdict(tmp_path: Path) -> None:
    from platform_testing.certify import report

    folder = tmp_path / "run9" / "sites" / "hotel--normal"
    folder.mkdir(parents=True)
    files = {
        "journey.json": {"site_key": "hotel--normal", "scenario": "hotel", "variant": "normal", "pages": ["home"]},
        "critique.json": {"weighted_score": 4.6, "scores": _dims(4.6), "page_weighted": {"home": 4.6},
                          "defects": [PHOTO_INPUT], "complete": True, "version": "certify-critic-v2"},
        "gate.json": {"status": "fail_closed", "rounds_used": 3, "blocked_on": "owner",
                      "owner_requests": ["We need 2–3 photographs of your actual rooms."]},
        "repair.json": {"score_before": 4.18, "score_after": 4.6, "levers": ["hide", "variant"],
                        "rounds": [{"round": 2, "attempts": 3, "kept": 1, "touched": ["home"],
                                    "score_before": 4.18, "score_after": 4.6}],
                        "attempts": [{"round": 2, "page": "home", "section": "hero", "lever": "variant",
                                      "change": "stage → split", "before": 4.57, "after": 5.1, "kept": True,
                                      "defect": "major/composition: narrow | centred column"}]},
    }
    for name, body in files.items():
        (folder / name).write_text(json.dumps(body), encoding="utf-8")
    rows = report.build(tmp_path / "out", [tmp_path / "run9"])
    assert rows[0]["repair"]["score_after"] == 4.6 and rows[0]["rounds_used"] == 3
    md = (tmp_path / "out" / "REPORT.md").read_text(encoding="utf-8")
    assert "### hotel--normal — fail_closed (4.60, after 3 round(s))" in md
    assert "### hotel--normal — 4.18 → 4.60 (fail_closed)" in md
    assert "| 2 | home | hero | variant | stage → split | 4.57 | 5.1 | yes | major/composition: narrow / centred column |" in md
    assert "Owner request: We need 2–3 photographs of your actual rooms." in md
