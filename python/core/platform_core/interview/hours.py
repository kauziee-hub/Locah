"""Opening hours from what the owner said, as a week — and corrections to it.

"Open 9 to 10" is every day 9 am to 10 pm; "on weekends we're open till 11"
then changes Saturday and Sunday only. Deterministic and conservative: a time
is read only when the owner gave one, and a statement that cannot be read as a
schedule returns None so the caller keeps the owner's own words instead.

The week is the same shape the Workspace saves on a location:
{"mon": [["09:00", "22:00"]], ..., "sun": []}.
"""

from __future__ import annotations

import re

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_WORDS = {
    "mon": "mon", "monday": "mon", "tue": "tue", "tues": "tue", "tuesday": "tue", "wed": "wed",
    "wednesday": "wed", "thu": "thu", "thur": "thu", "thurs": "thu", "thursday": "thu", "fri": "fri",
    "friday": "fri", "sat": "sat", "saturday": "sat", "sun": "sun", "sunday": "sun",
}
Week = dict[str, list[list[str]]]

_T = r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?"
_SPAN = re.compile(rf"\b{_T}\s*(?:to|till|until|-|–|—)\s*{_T}", re.I)
_UNTIL = re.compile(rf"\b(?:till|until|upto|up to|to)\s+{_T}", re.I)
_FROM = re.compile(rf"\b(?:from|opens?(?:\s+at)?)\s+{_T}", re.I)
_ALL_DAY = re.compile(r"\b24\s*(?:x|/|\*)\s*7\b|\b24 hours\b|\bround the clock\b", re.I)
_CLOSED = re.compile(r"\b(closed|holiday|shut|off)\b", re.I)
_RANGE = re.compile(r"\b([a-z]+)\s*(?:to|-|–|through|till)\s*([a-z]+)\b", re.I)


def _minutes(h: str, m: str | None, half: str | None) -> int | None:
    hour, minute = int(h), int(m or 0)
    if hour > 24 or minute > 59:
        return None
    half = (half or "").replace(".", "").lower()
    if half == "pm" and hour < 12:
        hour += 12
    if half == "am" and hour == 12:
        hour = 0
    return hour * 60 + minute


def _clock(minutes: int) -> str:
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _evening(end: int, start: int | None, near: int | None = None) -> int:
    """A closing hour said without am/pm: the evening one when the morning one
    would make a day of under four hours, or when it is nearer the closing
    time already known ("till 11" after closing at 10 pm is 11 pm)."""
    if end >= 12 * 60:
        return end
    later = end + 12 * 60
    if near is not None:
        return later if abs(later - near) < abs(end - near) else end
    if start is not None and (end <= start or end - start < 4 * 60):
        return later
    return end


def _span(match: re.Match[str], part: str = "") -> tuple[int, int] | None:
    """`part`: the clause says dinner/evening ("evening": bare hours are pm) or
    breakfast/morning ("morning": they are am)."""
    h1, m1, a1, h2, m2, a2 = match.groups()
    if part == "evening" and not a1 and not a2:
        a1 = "pm" if int(h1) < 12 else None
        a2 = "pm" if int(h2) < 12 and int(h2) >= int(h1) else None
    if part == "morning" and not a1 and not a2 and int(h2) > int(h1):
        a1 = a2 = "am"
    start, end = _minutes(h1, m1, a1), _minutes(h2, m2, a2)
    if start is None or end is None:
        return None
    if not a2:
        end = _evening(end, start)
    return start, 0 if end == 24 * 60 else end


def _until(match: re.Match[str], open_at: int | None, old_close: int | None) -> int | None:
    h, m, half = match.groups()
    end = _minutes(h, m, half)
    if end is None:
        return None
    if not half:
        end = _evening(end, open_at, old_close)
    return 0 if end == 24 * 60 else end


def days_named(text: str) -> list[str]:
    """The days a statement is about; empty when it names none (= every day)."""
    low = text.lower()
    if re.search(r"\b(weekends?|sat(?:urday)?s? (?:and|&) sun(?:day)?s?)\b", low):
        days = ["sat", "sun"]
    elif re.search(r"\b(weekdays?|week days?)\b", low):
        days = ["mon", "tue", "wed", "thu", "fri"]
    else:
        days = []
    for a, b in _RANGE.findall(low):
        if a in _DAY_WORDS and b in _DAY_WORDS:
            i, j = DAYS.index(_DAY_WORDS[a]), DAYS.index(_DAY_WORDS[b])
            days += [DAYS[k % 7] for k in range(i, (j if j >= i else j + 7) + 1)]
    for word in re.findall(r"[a-z]+", low):
        if word.rstrip("s") in _DAY_WORDS or word in _DAY_WORDS:
            days.append(_DAY_WORDS.get(word) or _DAY_WORDS[word.rstrip("s")])
    if re.search(r"\b(every ?day|daily|all days|7 days)\b", low):
        return list(DAYS)
    return [d for d in DAYS if d in days]


# A statement is split where it moves on: "10 am to 9 pm, closed on Sundays".
_CLAUSE = re.compile(
    r"\s*(?:[,;]|\bbut\b|\band\b(?=\s+(?:on\s+)?(?:closed|open|mon|tue|wed|thu|fri|sat|sun|week)))\s*", re.I)
# Times are read only in a clause that is about opening: "deliver within 5 to
# 7 km" has numbers, not hours.
_CUE = re.compile(
    r"\b(open\w*|clos\w*|timings?|timing|hours?|shut|holiday|daily|every ?day|weekends?|weekdays?|breakfast|lunch|"
    r"dinner|thirappom|thirak\w*|"
    r"(?:mon|tue|wed|thu|fri|sat|sun)(?:day)?s?|tues|thurs|am|pm|a\.m|p\.m|morning|evening|night|midnight|"
    r"round the clock)\b|\b24\s*(?:x|/|\*)\s*7\b|\d[:.]\d{2}",
    re.I)


_N = r"(\d{1,2}(?:[:.]\d{2})?)"
_NAMED_TIMES = (
    (re.compile(r"\bmidnight\b", re.I), "12 am"), (re.compile(r"\bnoon\b", re.I), "12 pm"),
    # Tamil, in English letters and in Tamil script: "kaalai 9 to raathiri 10",
    # "11 varaikum open" (till 11), "weekend la" (on weekends).
    (re.compile(rf"(?:\b(?:kaalai|kalai|kaal(?:a|e))|காலை)\s*{_N}", re.I), r"\1 am"),
    (re.compile(rf"(?:\b(?:raathiri|rathiri|raatri|ratri|iravu|maalai|malai|saayangaalam|sayangalam)|இரவு|மாலை)\s*{_N}",
                re.I), r"\1 pm"),
    (re.compile(rf"(?:\b(?:madhiyam|mathiyam)|மதியம்)\s*{_N}", re.I), r"\1 pm"),
    # "9 am முதல் 10 pm வரை" / "9 mudhal 10 varai": from 9 to 10.
    (re.compile(rf"{_N}(\s*(?:am|pm))?\s*(?:\b(?:mudhal|muthal|mudal)\b|முதல்)\s*{_N}(\s*(?:am|pm))?\s*"
                r"(?:\b(?:varaikum|varaikkum|varaiku|varai|vara)\b|வரைக்கும்|வரை)?", re.I), r"\1\2 to \3\4"),
    (re.compile(rf"{_N}(\s*(?:am|pm))?\s*(?:mani\s*)?(?:\b(?:varaikum|varaikkum|varaiku|varai|vara)\b|வரைக்கும்|வரை)",
                re.I), r"till \1\2"),
    (re.compile(r"\b(?:sani|sanikizhamai)\b|சனி\w*", re.I), "saturday"),
    (re.compile(r"\b(?:nyayiru|gnayiru|nyaayiru|nyayitru\w*)\b|ஞாயிறு\w*", re.I), "sunday"),
    (re.compile(r"\b(?:leave|holiday|lieve)\b", re.I), "closed"),
)


def parse(text: str, current: Week | None = None, *, asked: bool = False) -> Week | None:
    """The week this statement describes, applied over `current` when it
    corrects some days only. None when there is no schedule in it.

    `asked`: the statement answers "what are your opening hours?", so a bare
    "10 to 6" is a schedule too."""
    week: Week = {d: [list(s) for s in (current or {}).get(d, [])] for d in DAYS}
    flat = " ".join((text or "").split())
    for pattern, said in _NAMED_TIMES:
        flat = pattern.sub(said, flat)
    changed = undated = False
    for clause in _CLAUSE.split(flat):
        if clause and (asked or _CUE.search(clause)):
            # "12 to 3 for lunch, dinner 7 to 11": a second set of times for
            # the same (unnamed) days adds to the first instead of replacing it.
            again = undated and not days_named(clause)
            found = _clause(clause, week, add=again)
            if found is not None:
                week, changed = found, True
                undated = undated or not days_named(clause)
    # "Closed on Mondays" alone says nothing about when it IS open.
    return week if changed and any(week[d] for d in DAYS) else None


_EVENING = re.compile(r"\b(dinner|evenings?|nights?)\b", re.I)
_MORNING = re.compile(r"\b(breakfast|mornings?)\b", re.I)


def _clause(flat: str, current: Week, *, add: bool = False) -> Week | None:
    days = days_named(flat)
    week: Week = {d: [list(s) for s in current.get(d, [])] for d in DAYS}
    targets = days or list(DAYS)
    if _ALL_DAY.search(flat):
        for d in targets:
            week[d] = [["00:00", "00:00"]]
        return week
    if days and _CLOSED.search(flat) and not _SPAN.search(flat) and not _UNTIL.search(flat):
        for d in days:
            week[d] = []
        return week
    part = "evening" if _EVENING.search(flat) else "morning" if _MORNING.search(flat) else ""
    spans = [_span(m, part) for m in _SPAN.finditer(flat)]
    if spans:
        if None in spans:
            return None
        # "6 am to 10 am and 5 pm to 9 pm": a morning and an evening.
        found = [[_clock(a), _clock(b)] for a, b in sorted(s for s in spans if s is not None)]
        for d in targets:
            week[d] = sorted(week[d] + found) if add else found
        return week
    until = _UNTIL.search(flat)
    since = _FROM.search(flat)
    if not until and not since:
        return None
    for d in targets:
        old = week[d][0] if week[d] else None
        old_open, old_close = (_at(old[0]), _at(old[1])) if old else (None, None)
        open_at = _minutes(*since.groups()) if since else old_open
        close = _until(until, open_at, old_close) if until else old_close
        if open_at is None or close is None:
            return None  # "till 11" with no opening time known
        week[d] = [[_clock(open_at), _clock(close)]]
    return week


def _at(clock: str) -> int:
    """Minutes past midnight; a close at "00:00" is the end of the day."""
    h, m = clock.split(":")
    minutes = int(h) * 60 + int(m)
    return minutes or 24 * 60


def for_location(week: Week) -> dict[str, list[list[str]]]:
    """The week as a location saves it (validation.location.validate_hours):
    every span opens before it closes on the same day, at most three a day.
    A close at midnight is 23:59; a span past midnight carries on into the
    next morning; open all day is 00:00–23:59."""
    out: dict[str, list[list[str]]] = {d: [] for d in DAYS}
    for i, day in enumerate(DAYS):
        for a, b in week.get(day) or []:
            if a == b:
                out[day].append(["00:00", "23:59"])
            elif b == "00:00":
                out[day].append([a, "23:59"])
            elif b < a:
                out[day].append([a, "23:59"])
                out[DAYS[(i + 1) % 7]].append(["00:00", b])
            else:
                out[day].append([a, b])
    clean: dict[str, list[list[str]]] = {}
    for day, spans in out.items():
        merged: list[list[str]] = []
        for a, b in sorted(spans):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        if merged:
            clean[day] = merged[:3]
    return clean


def _say(clock: str) -> str:
    h, m = (int(x) for x in clock.split(":"))
    if h == 0 and m == 0:
        return "midnight"
    if h == 12 and m == 0:
        return "noon"
    return f"{h % 12 or 12}{f':{m:02d}' if m else ''} {'am' if h < 12 else 'pm'}"


def describe(week: Week) -> str:
    """"Mon–Fri 9 am–10 pm; Sat–Sun 9 am–11 pm"."""
    def spans(d: str) -> str:
        if week.get(d) == [["00:00", "00:00"]]:
            return "open 24 hours"
        return ", ".join(f"{_say(a)}–{_say(b)}" for a, b in week.get(d) or []) or "closed"

    said = [spans(d) for d in DAYS]
    if len(set(said)) == 1:
        return f"Every day {said[0]}" if said[0] != "closed" else "Closed"
    parts, start = [], 0
    for i in range(1, 8):
        if i == 7 or said[i] != said[start]:
            name = DAYS[start].title() if i - 1 == start else f"{DAYS[start].title()}–{DAYS[i - 1].title()}"
            parts.append(f"{name} {said[start]}")
            start = i
    return "; ".join(parts)
