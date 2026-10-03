"""\"Around 4\" into a clock time, in the venue's own time zone.

The guide's examples, verbatim: "Call at 4" -> 4 PM; "He's here after 5"
-> shortly after 5; "Try in an hour" -> one hour later; "Tomorrow
morning" -> a morning retry; "Usually between 3 and 6" -> inside the
window. Deterministic, no model, so a wrong answer can be read off the
code. Returns (utc_naive_datetime | None, kind, pretty) where kind is
one of specific | window | day | soon | vague.
"""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Longest phrases first, matched on word boundaries: "afternoon" must not
# be read as "noon", "after lunch" must beat "lunch".
PARTS = [("end of the day", 16, 30, "window"), ("end of day", 16, 30, "window"),
         ("first thing", 9, 0, "window"), ("after lunch", 13, 30, "window"),
         ("afternoon", 15, 0, "window"), ("morning", 10, 0, "window"),
         ("evening", 18, 0, "window"), ("tonight", 18, 0, "window"),
         ("midday", 12, 0, "specific"), ("noon", 12, 0, "specific"),
         ("lunch", 12, 30, "window"), ("dinner", 18, 30, "window"),
         ("closing", 21, 0, "window")]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday"]
WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
         "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
         "thirty": 30, "forty": 40, "forty-five": 45, "fortyfive": 45,
         "a couple of": 2, "a couple": 2, "couple of": 2, "couple": 2,
         "a few": 3, "few": 3, "half an": 0.5, "half a": 0.5, "half": 0.5}
CLOCK = re.compile(r"(?<![\d:])(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?|o'?clock)?(?!\d)")
REL = re.compile(r"\bin\s+(a couple of|a couple|couple of|couple|a few|few|half an|half a|an|a|\d+|[a-z]+)\b"
                 r"(?:\s+(?:more\s+)?(minutes?|mins?|hours?|hrs?|days?))?")


def _utc(dt_local):
    return dt_local.astimezone(timezone.utc).replace(tzinfo=None)


def _pretty(dt_local, now_local):
    day = ("today" if dt_local.date() == now_local.date()
           else "tomorrow" if dt_local.date() == (now_local + timedelta(days=1)).date()
           else dt_local.strftime("%a %b %-d"))
    return f"{day} {dt_local.strftime('%-I:%M %p')}"


def resolve(said, zone="America/New_York", now=None):
    s = " ".join((said or "").lower().replace("\u2019", "'").split())
    if not s:
        return None, "vague", ""
    try:
        tz = ZoneInfo(zone or "America/New_York")
    except Exception:
        tz = ZoneInfo("America/New_York")
    now_utc = now or datetime.now(timezone.utc).replace(tzinfo=None)
    now_local = now_utc.replace(tzinfo=timezone.utc).astimezone(tz)

    # 1. relative: "in 30 minutes", "in an hour", "in a couple of hours"
    if s in ("later", "later today", "a bit later", "later on", "in a bit",
             "in a while", "a little later"):
        target = (now_local + timedelta(hours=2)).replace(second=0, microsecond=0)
        return _utc(target), "soon", _pretty(target, now_local)
    m = REL.search(s)
    if m:
        qty, unit = m.group(1), (m.group(2) or "")
        n = WORDS.get(qty, None)
        if n is None:
            try:
                n = float(qty)
            except ValueError:
                n = None
        if n is not None:
            if unit.startswith("d"):
                target = (now_local + timedelta(days=n)).replace(hour=11, minute=0, second=0, microsecond=0)
                return _utc(target), "day", _pretty(target, now_local)
            minutes = n * 60 if (unit.startswith("h") or not unit and n <= 3) else n
            if unit.startswith("m"):
                minutes = n
            target = (now_local + timedelta(minutes=minutes)).replace(second=0, microsecond=0)
            return _utc(target), "soon", _pretty(target, now_local)

    # 2. the day
    day_offset, day_named = None, False
    if "tomorrow" in s:
        day_offset, day_named = 1, True
    elif "today" in s:
        day_offset, day_named = 0, True
    for i, name in enumerate(WEEKDAYS):
        if re.search(rf"\b{name[:3]}[a-z]*\b", s):
            ahead = (i - now_local.weekday()) % 7
            if ahead == 0:
                ahead = 7
            if "next" in s and ahead < 7:
                pass
            day_offset, day_named = ahead, True
            break
    if day_offset is None and "next week" in s:
        day_offset, day_named = 7, True

    # 3. the clock
    hour = minute = None
    kind = None
    pm_words = any(w in s for w in ("afternoon", "evening", "tonight", "dinner", "pm", "p.m"))
    rng = re.search(r"between\s+(\d{1,2})\s*(?:and|to|-)\s*(\d{1,2})", s)
    if rng:
        a, b = int(rng.group(1)), int(rng.group(2))
        hour, minute, kind = (a + 1 if b > a else a), 0, "window"
        if hour < 12 and (hour <= 7 or pm_words):
            hour += 12
    else:
        cm = CLOCK.search(s)
        if cm and not re.search(r"\b\d{1,2}\s*(minutes?|mins?|hours?|hrs?)\b", s):
            hour, minute = int(cm.group(1)), int(cm.group(2) or 0)
            suffix = (cm.group(3) or "").replace(".", "")
            if suffix.startswith("p") and hour < 12:
                hour += 12
            elif suffix.startswith("a") and hour == 12:
                hour = 0
            elif not suffix.startswith(("a", "p")):
                if hour < 12 and (hour <= 7 or pm_words):
                    hour += 12
            kind = "specific"
            if re.search(r"\bafter\b", s):
                minute = minute or 15
            elif re.search(r"\b(before|by)\b", s):
                hour, minute = (hour - 1, 30) if minute == 0 else (hour, 0)
    if hour is None:
        for word, h, mnt, k in PARTS:
            if re.search(rf"\b{re.escape(word)}\b", s):
                hour, minute, kind = h, mnt, k
                break
    if hour is None and day_named:
        hour, minute, kind = 11, 0, "day"
    if hour is None:
        return None, "vague", ""
    hour = min(max(hour, 0), 23)

    target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if day_offset:
        target += timedelta(days=day_offset)
    elif not day_named and target <= now_local + timedelta(minutes=2):
        target += timedelta(days=1)
    return _utc(target), kind, _pretty(target, now_local)
