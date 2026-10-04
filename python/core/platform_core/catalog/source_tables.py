"""Parse a playbook family's module list ("offerings (weighed), inventory (yield)").

`families.py` keeps each family's Core and Recommended modules in the words
the playbook used; this turns one of those lists into canonical module IDs and
their configuration hints, for the recommender and the stock profile.
"""

from __future__ import annotations

import re

_NAME = {
    "offerings": "offerings-catalog",
    "queue": "queue-operations",
    "insights": "analytics",
    "website": "core-website",
    "rentals": "bookings",
    "price lists": "offerings-catalog",
}
_FUTURE = {"payroll FUTURE"}


def parse_module_list(text: str) -> list[tuple[str, str]]:
    """'offerings (weighed), inventory (yield)' -> [('offerings-catalog','weighed'), ...].

    Commas inside parentheses belong to the hint.
    """
    items: list[str] = []
    depth, buf = 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            items.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        items.append(buf)
    out: list[tuple[str, str]] = []
    for raw in items:
        raw = raw.strip().rstrip(".")
        if not raw or raw == "—" or raw in _FUTURE:
            continue
        m = re.match(r"^(.*?)\s*\((.*)\)\s*$", raw)
        name, hint = (m.group(1), m.group(2)) if m else (raw, "")
        name = name.strip()
        if name == "rentals":
            hint = hint or "rental"
        if name == "price lists":
            hint = "price_lists"
        out.append((_NAME.get(name, name), hint.strip()))
    return out
