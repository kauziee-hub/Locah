"""The Workspace in English, Tamil or Hindi (P1-10E6; MD "Dashboard Language —
UI language preference (English / Tamil / Hindi)"; GP-22 P1 part).

Reads the translated Workspace surfaces' source (apps/workspace — read as text,
not imported) and their phrase table (apps/workspace/src/lib/ws-words.json):
every t('…') literal, every navigation label, the order label tables, and the
labels the API sends those surfaces (Home bands and rows, role names and
their questions, the order board's columns) have Tamil and Hindi wording with
the same blanks, in their own script. The first surfaces are the navigation,
Home, Orders and an order; the rest of the Workspace is still English. The
wording is LOCAH's first draft, pending a native speaker's review (VB-22).
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from platform_api.main import app

from platform_core.messaging.words import detect
from platform_testing.phase_b import create_business, new_identity

DB = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL required")
client = TestClient(app)
ROOT = Path(__file__).resolve().parents[3]
WS = ROOT / "apps" / "workspace" / "src"
CORE = ROOT / "python" / "core" / "platform_core"
TABLE: dict[str, dict[str, str]] = json.loads((WS / "lib" / "ws-words.json").read_text(encoding="utf-8"))
CALL = re.compile(r"""\bt\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""")
BLANKS = re.compile(r"\{(\w+)\}")
TRANSLATED = ["components/AppSidebar.tsx", "components/MoneyPanel.tsx", "components/MoneySection.tsx",
              "app/b/[businessId]/page.tsx", "app/b/[businessId]/orders/page.tsx",
              "app/b/[businessId]/orders/[orderId]/page.tsx", "app/b/[businessId]/orders/[orderId]/ChangeOrder.tsx",
              "app/b/[businessId]/orders/[orderId]/OrderBill.tsx", "app/b/[businessId]/orders/ItemPicker.tsx",
              "app/b/[businessId]/orders/new/page.tsx", "app/b/[businessId]/orders/new/PhoneOrder.tsx",
              "app/b/[businessId]/orders/production/page.tsx", "components/StageTrack.tsx"]


def _said() -> dict[str, str]:
    found: dict[str, str] = {}
    for rel in TRANSLATED:
        for m in CALL.finditer((WS / rel).read_text(encoding="utf-8")):
            found.setdefault(m.group(1) if m.group(1) is not None else m.group(2), rel)
    return found


def _table_values(rel: str, *names: str) -> set[str]:
    """The string values of `const NAME: Record<string, string> = {…}` tables in a TS file."""
    text = (WS / rel).read_text(encoding="utf-8")
    out: set[str] = set()
    for name in names:
        body = re.search(rf"{name}[^=]*=\s*{{(.*?)\n}}", text, re.S)
        assert body, f"{name} not found in {rel}"
        out |= set(re.findall(r":\s*'([^']+)'", body.group(1)))
    return out


def _nav_labels() -> set[str]:
    text = (WS / "lib" / "workspace-nav.ts").read_text(encoding="utf-8")
    return set(re.findall(r"label: '([^']+)'", text)) | set(re.findall(r"return '([^']+)'", text))


def _home_labels() -> set[str]:
    """What role_home and the order board put on Home and Orders: row labels, band titles, empties, stat labels."""
    tree = ast.parse((CORE / "services" / "role_home.py").read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_item" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                out.add(first.value)
            if len(node.args) > 3 and isinstance(node.args[3], ast.Constant) and isinstance(node.args[3].value, str):
                out.add(node.args[3].value)  # a fixed detail, e.g. "No products or services yet — …"
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in ("title", "empty", "label", "value") \
                        and isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value:
                    out.add(v.value)
        if isinstance(node, ast.IfExp):
            for branch in (node.body, node.orelse):
                if isinstance(branch, ast.Constant) and isinstance(branch.value, str) and branch.value[:1].isupper():
                    out.add(branch.value)
    from platform_core.authorization.role_templates import OWNER, ROLE_TEMPLATES
    from platform_core.orders.board import BUCKETS

    for tpl in (OWNER, *ROLE_TEMPLATES.values()):
        out |= {tpl.label, tpl.home}
    out |= {"Team member", "Your work today"} | {label for _, label in BUCKETS}
    # The top of Home: greetings, quick actions and the fixed open-state words.
    from platform_core.services import home_header

    out |= {"Good morning", "Good afternoon", "Good evening", "Opening hours not set", "Closed"}
    out |= {label for _, _, _, label in home_header.QUICK_ACTIONS}
    out |= set(home_header.ITEM_WORDS.values())
    return out


def test_every_word_on_the_translated_workspace_surfaces_has_tamil_and_hindi() -> None:
    said = _said()
    assert len(said) > 60, f"the translated surfaces go through t() ({len(said)} phrases found)"
    missing = [f"{where}: {text!r}" for text, where in said.items() if text not in TABLE]
    assert missing == [], "Workspace phrases without Tamil/Hindi wording:\n" + "\n".join(missing)


def test_the_navigation_and_order_words_have_their_wording() -> None:
    labels = _nav_labels() | _table_values("app/b/[businessId]/orders/labels.ts", "CHANNEL", "PAY_METHOD", "PAY_STATUS")
    missing = sorted(label for label in labels if label not in TABLE)
    assert missing == [], "navigation / order labels without wording:\n" + "\n".join(missing)


def test_what_the_api_puts_on_home_and_the_board_has_its_wording() -> None:
    missing = sorted(label for label in _home_labels() if label not in TABLE)
    assert missing == [], "Home / board labels from the API without wording:\n" + "\n".join(missing)


def _money_labels() -> set[str]:
    """What the money panel shows from the API: states, purposes, how it was paid, why it cannot be collected."""
    from platform_core.services import invoicing
    from platform_core.services.payment_collect import ATTEMPT_METHOD_WORDS, PURPOSES, STATE_WORDS

    out = set(STATE_WORDS.values()) | set(PURPOSES.values()) | set(ATTEMPT_METHOD_WORDS.values())
    out |= {"Pay at pickup", "Cash on delivery"} | set(invoicing.KIND_LABEL.values())
    tree = ast.parse((CORE / "services" / "payment_collect.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "why" for t in node.targets) \
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            out.add(node.value.value)
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "failure_reason"
                                                for t in node.targets) and isinstance(node.value, ast.Constant):
            out.add(str(node.value.value))
        if isinstance(node, ast.keyword) and node.arg == "failure_reason" and isinstance(node.value, ast.Constant):
            out.add(str(node.value.value))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Source":
            for arg in node.args:
                if isinstance(arg, ast.IfExp) and isinstance(arg.body, ast.Constant):
                    out.add(str(arg.body.value))
                if isinstance(arg, ast.IfExp) and isinstance(arg.orelse, ast.Constant) and arg.orelse.value:
                    out.add(str(arg.orelse.value))
    return out


def test_what_the_api_puts_in_the_money_panel_has_its_wording() -> None:
    missing = sorted(label for label in _money_labels() if label not in TABLE)
    assert missing == [], "money panel labels from the API without wording:\n" + "\n".join(missing)


def test_wording_keeps_the_blanks_and_is_written_in_its_script() -> None:
    latin_ok = {"GST", "UPI", "WhatsApp", "CGST + SGST", "IGST", "POS"}
    for text, wording in TABLE.items():
        assert set(wording) == {"ta", "hi"}, f"{text!r} needs exactly ta and hi"
        for lang, words in wording.items():
            assert sorted(BLANKS.findall(words)) == sorted(BLANKS.findall(text)), \
                f"{text!r} [{lang}] fills different blanks: {words!r}"
            if text not in latin_ok:
                assert detect(BLANKS.sub("", words)) == lang, f"{text!r} [{lang}] is not written in its script: {words!r}"


@DB
def test_a_person_keeps_their_workspace_language(monkeypatch: Any) -> None:
    _, owner = new_identity(monkeypatch)
    bid = create_business(client, owner)
    headers = {**owner, "X-Operating-Context": "business", "X-Business-Id": bid}
    assert client.get("/v1/me/context", headers=headers).json()["data"]["workspace_language"] == "en"
    assert client.put("/v1/me/workspace-language", json={"language": "fr"}, headers=owner).status_code == 422
    r = client.put("/v1/me/workspace-language", json={"language": "ta"}, headers=owner)
    assert r.status_code == 200 and r.json()["data"]["workspace_language"] == "ta"
    assert client.get("/v1/me/context", headers=headers).json()["data"]["workspace_language"] == "ta"
    _, other = new_identity(monkeypatch)
    create_business(client, other)
    assert client.get("/v1/me/context", headers=other).json()["data"]["workspace_language"] == "en", \
        "one person's choice is theirs alone"
