"""Ask Claude to pull a structured schedule out of a syllabus.

We force a tool call so the answer always comes back as JSON matching SCHEMA.
"""
import json
import os
import re
import time
from datetime import date
from pathlib import Path

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")  # used only when ANTHROPIC_API_KEY is set

TIME = {"type": "string", "description": "24h HH:MM, or empty string if unknown"}
DATE = {"type": "string", "description": "YYYY-MM-DD"}

SCHEMA = {
    "type": "object",
    "properties": {
        "course_code": {"type": "string", "description": "e.g. CS 101"},
        "course_name": {"type": "string"},
        "instructor": {"type": "string"},
        "term_start": {**DATE, "description": "First day of classes (YYYY-MM-DD)"},
        "term_end": {**DATE, "description": "Last day of classes, NOT including the final exam (YYYY-MM-DD)"},
        "meetings": {
            "type": "array",
            "description": "Recurring weekly class meetings",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["lecture", "lab", "discussion", "recitation", "seminar", "office_hours"]},
                    "days": {"type": "array", "items": {"type": "string", "enum": ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]}},
                    "start_time": TIME,
                    "end_time": TIME,
                    "location": {"type": "string"},
                },
                "required": ["kind", "days", "start_time", "end_time"],
            },
        },
        "no_class": {
            "type": "array",
            "description": "Holidays / breaks / cancelled classes. Use start==end for a single day.",
            "items": {
                "type": "object",
                "properties": {"start": DATE, "end": DATE, "reason": {"type": "string"}},
                "required": ["start", "end"],
            },
        },
        "events": {
            "type": "array",
            "description": "One-off dated items: exams, quizzes, assignment/project deadlines, presentations",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short, e.g. 'Midterm 1' or 'HW3 due'"},
                    "category": {"type": "string", "enum": ["final", "exam", "quiz", "assignment", "project", "presentation", "other"]},
                    "date": DATE,
                    "start_time": TIME,
                    "end_time": TIME,
                    "location": {"type": "string"},
                    "notes": {"type": "string", "description": "Weight %, topics covered, etc. Keep short."},
                },
                "required": ["title", "category", "date"],
            },
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Anything ambiguous or guessed that the student should double-check (write in the syllabus language)",
        },
    },
    "required": ["course_code", "course_name", "term_start", "term_end", "meetings", "events"],
}

SYSTEM = """You extract calendar data from university course syllabi.
Rules:
- Today is {today}. If the syllabus omits the year, infer it from context (the upcoming or current term).
- If the user supplied a term start/end, prefer it over guesses.
- Weekly schedules like "Week 5: Midterm (Thu)" must be converted into real dates using the term start date and the class meeting days.
- If an exam's time is not stated but it happens "in class", use the lecture meeting time and location.
- If a deadline has a time ("11:59pm"), put it in start_time. Do not invent times otherwise.
- Only include items with a concrete (or reliably inferable) date. Put anything you had to guess into warnings.
- Do not list every individual lecture topic as an event.
- Always answer by calling the save_schedule tool exactly once."""


def provider() -> str | None:
    """Which LLM to use, based on which API key is set. None -> demo mode."""
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "claude"
    return None


def parse_syllabus(blocks: list[dict], term_start: str = "", term_end: str = "", known: list | None = None) -> dict:
    hint = "Extract the course schedule from the syllabus above."
    if term_start or term_end:
        hint += f" The student says the term runs {term_start or '?'} to {term_end or '?'}."
    if known:
        # Lets a re-uploaded (updated) syllabus line up with what's already saved,
        # so the app can update in place instead of adding a duplicate course.
        hint += ("\nCourses already in the student's calendar: " + json.dumps(known, ensure_ascii=False)[:6000] +
                 "\nIf this syllabus is for one of these courses (e.g. an updated version), copy its course_code and "
                 "course_name EXACTLY, and reuse the existing event titles for the same items "
                 "(same exam/assignment = same title, even if its date changed). Use new titles only for genuinely new items.")
    if provider() == "gemini":
        return _parse_gemini(blocks, hint)
    return _parse_claude(blocks, hint)


def _parse_gemini(blocks: list[dict], hint: str) -> dict:
    """Google Gemini (free tier via aistudio.google.com). Reads text, images and PDFs."""
    import base64

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    parts = []
    for b in blocks:
        if b["type"] == "text":
            parts.append(types.Part.from_text(text=b["text"]))
        else:  # image / document -> raw bytes
            src = b["source"]
            parts.append(types.Part.from_bytes(data=base64.b64decode(src["data"]), mime_type=src["media_type"]))
    parts.append(types.Part.from_text(
        text=hint + "\nReturn ONLY a JSON object matching this JSON Schema:\n" + json.dumps(SCHEMA)))

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM.format(today=date.today().isoformat()).replace(
            "Always answer by calling the save_schedule tool exactly once.", "Answer with JSON only."),
        response_mime_type="application/json",
        temperature=0,
    )
    contents = [types.Content(role="user", parts=parts)]
    resp = _gemini_call(client, contents, config)
    text = (resp.text or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    data = json.loads(text)
    if isinstance(data, list):  # occasionally wrapped in a list
        data = data[0]
    for key in ("meetings", "events", "no_class", "warnings"):
        data.setdefault(key, [])
    return data


def gemini_models(client=None) -> list[str]:
    """Flash-type models this key can actually call, newest first."""
    from google import genai
    client = client or genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    names = []
    for m in client.models.list():
        name = (m.name or "").removeprefix("models/")
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" in actions and "flash" in name and not any(x in name for x in ("tts", "image", "audio", "live", "embedding")):
            names.append(name)
    return sorted(set(names), reverse=True)


def _gemini_call(client, contents, config):
    """Call Gemini robustly: back off on 503/429 (overloaded), then fall back to other models.
    Order: GEMINI_MODEL -> GEMINI_FALLBACK_MODELS -> whatever flash models the key can list."""
    models = [os.getenv("GEMINI_MODEL", "gemini-3.8-flash")]
    models += [m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "").split(",") if m.strip()]
    listed = False
    tried = []
    last = None
    i = 0
    while i < len(models) and len(tried) < 6:
        model = models[i]
        tried.append(model)
        for attempt in range(2):
            try:
                resp = client.models.generate_content(model=model, contents=contents, config=config)
                print(f"[gemini] ok with {model}")
                return resp
            except Exception as e:
                last, msg = e, str(e)
                print(f"[gemini] {model} failed: {msg[:120]}")
                suggested = re.search(r"use models/([\w.\-]+)", msg)
                if suggested and suggested.group(1) not in models:
                    models.insert(i + 1, suggested.group(1))
                busy = any(k in msg for k in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "overloaded"))
                if busy and attempt == 0:
                    time.sleep(3)
                    continue
                if not busy and "404" not in msg and "NOT_FOUND" not in msg:
                    raise
                break  # busy twice or model gone -> next model
        i += 1
        if i >= len(models) and not listed:  # ran out: ask Google which models this key has
            listed = True
            try:
                models += [m for m in gemini_models(client) if m not in models]
            except Exception as e:
                print(f"[gemini] could not list models: {e}")
    raise RuntimeError(f"All Gemini models busy/unavailable (tried {', '.join(tried)}). Last error: {last}")


def _parse_claude(blocks: list[dict], hint: str) -> dict:
    import anthropic  # imported lazily so demo mode works without the SDK configured

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM.format(today=date.today().isoformat()),
        tools=[{"name": "save_schedule", "description": "Save the extracted schedule", "input_schema": SCHEMA}],
        tool_choice={"type": "tool", "name": "save_schedule"},
        messages=[{"role": "user", "content": [*blocks, {"type": "text", "text": hint}]}],
    )
    for block in msg.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError("Model did not return a schedule")


def demo_result() -> dict:
    """Canned output used when no ANTHROPIC_API_KEY is set (handy for offline demos)."""
    return json.loads((Path(__file__).parent / "demo_result.json").read_text())
