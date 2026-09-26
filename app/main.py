import io
import json
import os
import re
import secrets
import socket
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
import segno
from pydantic import BaseModel

from .extract import file_to_blocks
from .ics import build_calendar
from .storage import make_store
from .llm import demo_result, gemini_models, parse_syllabus, provider

ROOT = Path(__file__).resolve().parent.parent
STORE = make_store(ROOT / "data")

app = FastAPI(title="Syllabus2Cal")


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _public_base(request: Request) -> str:
    """URL a phone can reach. Set PUBLIC_BASE_URL when using ngrok/cloudflared/a deploy."""
    public = os.getenv("PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL")  # Render sets the latter
    if public:
        return public.rstrip("/")
    host = request.url.hostname or ""
    port = request.url.port
    if host in ("localhost", "127.0.0.1", "0.0.0.0"):
        host = _lan_ip()
    return f"{request.url.scheme}://{host}{f':{port}' if port else ''}"


@app.get("/api/status")
def status():
    return {"demo_mode": provider() is None, "provider": provider(), "storage": STORE.kind}


@app.get("/api/models")
def models():
    """Debug helper: which Gemini models does this key have?"""
    if provider() != "gemini":
        return {"provider": provider()}
    try:
        return {"provider": "gemini", "configured": os.getenv("GEMINI_MODEL", "gemini-3.8-flash"), "available": gemini_models()}
    except Exception as e:
        raise HTTPException(502, str(e))


@app.post("/api/parse")
async def parse(
    files: list[UploadFile] = File(default=[]),
    text: str = Form(default=""),
    term_start: str = Form(default=""),
    term_end: str = Form(default=""),
):
    if provider() is None:
        demo = demo_result()
        if files and files[0].filename:  # label demo courses by file name so multi-upload is visible
            demo["course_code"] = Path(files[0].filename).stem[:20]
        return {**demo, "demo": True}

    blocks = []
    for f in files:
        data = await f.read()
        if data:
            blocks += file_to_blocks(f.filename, f.content_type, data)
    if text.strip():
        blocks.append({"type": "text", "text": f"=== Pasted syllabus text ===\n{text[:120_000]}"})
    if not blocks:
        raise HTTPException(400, "Upload a file or paste some text")
    try:
        return parse_syllabus(blocks, term_start, term_end)
    except Exception as e:  # surface API errors to the UI
        raise HTTPException(502, f"LLM parsing failed: {e}")


# ---------------------------------------------------------------------------
# Saved calendars: data/<id>.json holds the editable state; the .ics is rebuilt
# from it on every request, so a phone that SUBSCRIBED always gets the latest.
# ---------------------------------------------------------------------------
ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")


class CalendarState(BaseModel):
    name: str = "My Courses"
    courses: list[dict] = []
    timezone: str = "America/New_York"
    reminders: bool = True


def _check_id(cal_id: str) -> None:
    if not ID_RE.match(cal_id):
        raise HTTPException(404, "Calendar not found")


def _load(cal_id: str) -> dict:
    _check_id(cal_id)
    data = STORE.get(cal_id)
    if data is None:
        raise HTTPException(404, "Calendar not found")
    return data


def _qr(url: str) -> str:
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=6, border=2, dark="#111", light="#fff", omitsize=True)
    return buf.getvalue().decode()


@app.post("/api/calendars")
def create_calendar(state: CalendarState):
    cal_id = secrets.token_urlsafe(9)
    data = {**state.model_dump(), "updated_at": datetime.now().isoformat(timespec="seconds")}
    STORE.put(cal_id, data)
    return {"id": cal_id, **data}


@app.get("/api/calendars/{cal_id}")
def read_calendar(cal_id: str):
    return {"id": cal_id, **_load(cal_id)}


@app.put("/api/calendars/{cal_id}")
def save_calendar(cal_id: str, state: CalendarState):
    _load(cal_id)  # 404 if missing
    try:  # make sure it still builds before saving
        build_calendar(state.courses, state.timezone, state.reminders, state.name)
    except Exception as e:
        raise HTTPException(400, f"Could not build calendar: {e}")
    data = {**state.model_dump(), "updated_at": datetime.now().isoformat(timespec="seconds")}
    STORE.put(cal_id, data)
    return {"id": cal_id, "updated_at": data["updated_at"]}


@app.get("/api/calendars/{cal_id}/share")
def share_calendar(cal_id: str, request: Request):
    _load(cal_id)
    url = f"{_public_base(request)}/cal/{cal_id}.ics"
    webcal = re.sub(r"^https?://", "webcal://", url)
    return {
        "url": url,          # one-time import (iPhone Safari -> "Add All")
        "webcal": webcal,    # subscribe -> phone keeps pulling updates
        "download": f"/cal/{cal_id}.ics?download=1",
        "qr_import": _qr(url),
        "qr_subscribe": _qr(webcal),
        "google_subscribe": "https://calendar.google.com/calendar/r?cid=" + webcal,
        "public": bool(os.getenv("PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL")),  # reachable from any network?
    }


@app.get("/cal/{cal_id}.ics")
def get_calendar(cal_id: str, download: int = 0):
    data = _load(cal_id)
    ics = build_calendar(data["courses"], data.get("timezone", "America/New_York"),
                         data.get("reminders", True), data.get("name", "My Courses"))
    disp = "attachment" if download else "inline"  # inline: iOS Safari offers "Add All"
    return Response(ics, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'{disp}; filename="my-courses.ics"',
                             "Cache-Control": "no-cache"})


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
