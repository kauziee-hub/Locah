"""A location's address and opening hours in the words people use.

One wording for every surface that states them — the business's website, its
AI receptionist, the Workspace — so they never disagree with the Locations page.
"""

from __future__ import annotations

from typing import Any

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ADDRESS_KEYS = ("line1", "line_1", "line2", "line_2", "street", "area", "locality", "landmark", "city", "district",
                "state", "postal_code", "pincode", "pin")


def hours_text(hours: dict[str, Any] | None) -> str:
    """{"mon": [["09:00","18:00"]], ...} → "Mon–Sat 9 am–6 pm; Sun closed" — the
    way people say it, not a 24-hour clock."""
    from platform_core.interview.hours import describe

    if not hours or not any(hours.get(d) for d in DAYS):
        return ""
    week = {d: [list(s) for s in hours.get(d) or []] for d in DAYS}
    said = describe(week)
    note = f" ({hours['note']})" if hours.get("note") else ""
    return str(said[:1].lower() + said[1:] if said.startswith("Every day") else said) + note


def address_text(address: dict[str, Any] | None) -> str:
    if not address:
        return ""
    keyed = [str(address[k]).strip() for k in ADDRESS_KEYS if isinstance(address.get(k), str) and address[k].strip()]
    rest = [str(v).strip() for k, v in address.items()
            if k not in ADDRESS_KEYS and isinstance(v, str) and v.strip() and k not in ("country", "lat", "lng")]
    return ", ".join(dict.fromkeys(keyed or rest))
