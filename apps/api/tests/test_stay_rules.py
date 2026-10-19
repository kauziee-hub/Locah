"""A hotel's own rules, from how the owner says them to the booking that keeps them.

Owner lab (hotel): "Check-in 1 pm, check-out 11 am" and "2-night minimum on
weekends" were "noted" in the chat, reached no room type, and a one-night
Saturday could be booked; a 14-room coffee-estate retreat was greeted as "a
homestay".
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest

from platform_core.catalog.offering_kinds import clean_attributes, kind
from platform_core.catalog.taxonomy import infer_from_text
from platform_core.exceptions import ValidationError
from platform_core.services.booking_slots import stay_rule_broken, stay_window
from platform_core.services.business_interview import _stay_rules

IST = ZoneInfo("Asia/Kolkata")


@pytest.mark.parametrize(("said", "rules"), [
    ("Check-in 1 pm, check-out 11 am . By the night, 2-night minimum on weekends.",
     {"check_in": "13:00", "check_out": "11:00", "weekend_min_nights": 2}),
    ("per nite, weekend min 2 nites . checkin 2pm checkout 11",
     {"check_in": "14:00", "check_out": "11:00", "weekend_min_nights": 2}),
    ("Check-in from 12 noon, check out by 10:30 am.", {"check_in": "12:00", "check_out": "10:30"}),
    ("Minimum stay two nights", {"min_nights": 2}),
    ("minimum stay is 2 nights on saturdays", {"weekend_min_nights": 2}),
    ("Check in at 14:00, check-out 11:00", {"check_in": "14:00", "check_out": "11:00"}),
    # Seasonal rules LOCAH cannot hold are never applied all year.
    ("Minimum 3 nights in December", {}),
    ("2 night min during peak season", {}),
    ("one night is fine", {}),
])
def test_the_owners_words_become_the_room_types_rules(said: str, rules: dict[str, Any]) -> None:
    assert _stay_rules(said) == rules


def _room(**attrs: Any) -> Any:
    return SimpleNamespace(attributes=attrs)


LOCATION = cast(Any, SimpleNamespace(timezone="Asia/Kolkata"))


def _stay(first: date, last: date, **attrs: Any) -> str | None:
    room = _room(**attrs)
    a, b = stay_window(LOCATION, room, first, last)
    return stay_rule_broken(room, LOCATION, a, b)


def test_a_weekend_stay_keeps_the_weekend_minimum() -> None:
    fri, sat, sun, mon, tue = (date(2026, 10, d) for d in (23, 24, 25, 26, 27))
    rules = {"weekend_min_nights": 2}
    assert _stay(sat, sun, **rules) == "A stay over a Friday or Saturday night is at least 2 nights"
    assert _stay(fri, sat, **rules) is not None
    assert _stay(fri, sun, **rules) is None
    assert _stay(mon, tue, **rules) is None, "a weekday night is not held to the weekend rule"
    assert _stay(mon, tue, min_nights=3) == "A stay here is at least 3 nights"
    assert _stay(mon, tue) is None


def test_a_stay_runs_from_the_room_types_check_in_to_its_check_out() -> None:
    a, b = stay_window(LOCATION, _room(check_in="13:00", check_out="11:00"), date(2026, 10, 26), date(2026, 10, 28))
    assert (a, b) == (datetime(2026, 10, 26, 13, 0, tzinfo=IST), datetime(2026, 10, 28, 11, 0, tzinfo=IST))


def test_a_room_type_says_its_check_in_and_shortest_stay() -> None:
    room = kind("accommodation")
    out = clean_attributes(room, {"max_guests": 2, "check_in": "13:00:00", "check_out": "11:00", "weekend_min_nights": 2})
    assert out == {"max_guests": 2, "check_in": "13:00", "check_out": "11:00", "weekend_min_nights": 2}
    with pytest.raises(ValidationError):
        clean_attributes(room, {"check_in": "25:00"})


@pytest.mark.parametrize(("said", "expected"), [
    ("Mistwood Estate Retreat, 14-room estate stay near Madikeri, Coorg. Cottages and pool villas in our coffee "
     "estate. Guests book online.", "resort"),
    ("mistwood estate retreat coorg madikeri, 14 rooms in our cofee estate, cottages + pool vilas", "resort"),
    ("A 40 room business hotel near the airport", "hotel"),
    ("We run a homestay with 3 rooms in our house in Ooty", "homestay"),
])
def test_a_fourteen_room_estate_is_a_resort_not_a_homestay(said: str, expected: str) -> None:
    found = infer_from_text(said)
    assert found is not None and found[0] == expected
