"""Build an .ics calendar (RFC 5545) from parsed course data.

Recurring class meetings become ONE weekly event with RRULE + EXDATE (holidays),
so the phone calendar stays clean. Exams/deadlines get reminders.
"""
import hashlib
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from icalendar import Alarm, Calendar, Event, vRecur

WEEKDAY_IDX = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
EMOJI = {
    "final": "🔥", "exam": "📝", "quiz": "✏️", "assignment": "📌",
    "project": "🧩", "presentation": "🎤", "other": "📅",
}
KIND_LABEL = {
    "lecture": "Lecture", "lab": "Lab", "discussion": "Discussion",
    "recitation": "Recitation", "seminar": "Seminar", "office_hours": "Office Hours",
}


def _d(s: str) -> date | None:
    try:
        return date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def _t(s: str) -> time | None:
    try:
        h, m = s.strip().split(":")[:2]
        return time(int(h), int(m))
    except (AttributeError, ValueError):
        return None


def _uid(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:20] + "@syllabus2cal"


def _alarm(trigger: timedelta, text: str) -> Alarm:
    a = Alarm()
    a.add("action", "DISPLAY")
    a.add("description", text)
    a.add("trigger", trigger)
    return a


def _no_class_days(course: dict) -> set[date]:
    days = set()
    for nc in course.get("no_class") or []:
        s, e = _d(nc.get("start", "")), _d(nc.get("end", "") or nc.get("start", ""))
        if not s:
            continue
        e = e or s
        while s <= e:
            days.add(s)
            s += timedelta(days=1)
    return days


def build_calendar(courses: list[dict], tz_name: str = "America/New_York", reminders: bool = True,
                   name: str = "My Courses") -> bytes:
    tz = ZoneInfo(tz_name)
    cal = Calendar()
    cal.add("prodid", "-//Syllabus2Cal//Hackathon//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", name or "My Courses")
    cal.add("name", name or "My Courses")
    # ask subscribed clients to re-fetch hourly so edits reach the phone
    cal.add("refresh-interval", timedelta(hours=1), parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", "PT1H")
    cal.add("x-wr-timezone", tz_name)
    now = datetime.now(tz)

    for course in courses:
        code = (course.get("course_code") or course.get("course_name") or "Course").strip()  # stable id part
        name = (course.get("course_name") or code).strip()  # what people see
        t_start, t_end = _d(course.get("term_start", "")), _d(course.get("term_end", ""))
        skip = _no_class_days(course)

        # ---- weekly meetings -------------------------------------------------
        for i, m in enumerate(course.get("meetings") or []):
            if m.get("include") is False:
                continue
            st, et = _t(m.get("start_time", "")), _t(m.get("end_time", ""))
            days = [d for d in (m.get("days") or []) if d in WEEKDAY_IDX]
            if not (st and et and days and t_start and t_end):
                continue
            wd = {WEEKDAY_IDX[d] for d in days}
            first = t_start
            while first.weekday() not in wd:
                first += timedelta(days=1)
            if first > t_end:
                continue

            ev = Event()
            ev.add("uid", _uid(code, "meeting", i, days, st))
            ev.add("dtstamp", now)
            kind = m.get("kind", "lecture")
            ev.add("summary", name if kind == "lecture" else f"{name} {KIND_LABEL.get(kind, 'Class')}")
            ev.add("dtstart", datetime.combine(first, st, tz))
            ev.add("dtend", datetime.combine(first, et, tz))
            until = datetime.combine(t_end, time(23, 59, 59), tz).astimezone(ZoneInfo("UTC"))
            ev.add("rrule", vRecur(freq="WEEKLY", byday=days, until=until))
            exdates = [datetime.combine(d, st, tz) for d in sorted(skip) if d.weekday() in wd and first <= d <= t_end]
            if exdates:
                ev.add("exdate", exdates)
            if m.get("location"):
                ev.add("location", m["location"])
            desc = [course.get("course_code", "")]
            if course.get("instructor"):
                desc.append(f"Instructor: {course['instructor']}")
            ev.add("description", "\n".join(x for x in desc if x))
            if reminders and m.get("kind") != "office_hours":
                ev.add_component(_alarm(timedelta(minutes=-15), f"{name} starts in 15 min"))
            cal.add_component(ev)

        # ---- one-off events --------------------------------------------------
        for j, e in enumerate(course.get("events") or []):
            if e.get("include") is False:
                continue
            d = _d(e.get("date", ""))
            if not d:
                continue
            cat = e.get("category", "other")
            st, et = _t(e.get("start_time", "")), _t(e.get("end_time", ""))

            ev = Event()
            ev.add("uid", _uid(code, "event", j, e.get("title"), d))
            ev.add("dtstamp", now)
            ev.add("summary", f"{EMOJI.get(cat, '📅')} {e.get('title', '').strip()} · {name}")
            ev.add("categories", [cat.upper()])
            if st:
                start = datetime.combine(d, st, tz)
                if et and et > st:
                    end = datetime.combine(d, et, tz)
                elif cat in ("final", "exam"):
                    end = start + timedelta(hours=2)
                else:  # deadline: a 30-min block ending at the due time
                    start, end = start - timedelta(minutes=30), start
                ev.add("dtstart", start)
                ev.add("dtend", end)
            else:
                ev.add("dtstart", d)  # all-day
                ev.add("dtend", d + timedelta(days=1))
            if e.get("location"):
                ev.add("location", e["location"])
            if e.get("notes"):
                ev.add("description", e["notes"])

            if reminders:
                label = f"{e.get('title', '')} ({name})"
                if cat in ("final", "exam"):
                    ev.add_component(_alarm(timedelta(days=-7), f"1 week until {label}"))
                    ev.add_component(_alarm(timedelta(days=-1), f"Tomorrow: {label}"))
                elif cat in ("quiz", "presentation", "project"):
                    ev.add_component(_alarm(timedelta(days=-1), f"Tomorrow: {label}"))
                elif cat == "assignment":
                    ev.add_component(_alarm(timedelta(days=-2) if not st else timedelta(hours=-24), f"Due soon: {label}"))
            cal.add_component(ev)

    cal.add_missing_timezones()
    return cal.to_ical()
