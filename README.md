# 📅 Syllabus2Cal

Upload a syllabus (PDF / Word / screenshot / pasted text). Get every class, exam and deadline on your phone in one QR scan.

## Run it (about 2 minutes)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

export GEMINI_API_KEY=AIza...        # free key: https://aistudio.google.com/apikey
# or: export ANTHROPIC_API_KEY=sk-ant-...   (if both are set, Gemini is used)
# leave both unset to run in DEMO mode with sample data

uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Open http://localhost:8000

Optional env vars:
- `GEMINI_MODEL`: defaults to `gemini-3.8-flash`
- `ANTHROPIC_MODEL`: defaults to `claude-sonnet-4-5`
- `PUBLIC_BASE_URL`: the URL your phone should use, e.g. `https://xxxx.ngrok-free.app`

## Features
- **Calendar view in the site**: month grid, color per course, "coming up" strip for exams/deadlines
- **Edit anytime**: click an event to edit or delete it, click an empty day to add one, click a class to cancel that single day. The Courses tab has a full table editor. Changes autosave.
- **Re-upload to update**: uploading a new version of a course's syllabus merges into the existing course (matched by course code). Moved exams and new items are listed.
- **Saved calendars**: each calendar lives at `/?c=<id>` (stored in `data/<id>.json`). The `.ics` is rebuilt on every request, so **subscribed** phones pick up edits.

## Getting it onto a phone
The QR code points at `/cal/<id>.ics`, so the phone has to be able to reach your laptop:
- **Same Wi-Fi:** works as-is. The server detects your LAN IP. Hackathon Wi-Fi often blocks device-to-device traffic, so if the scan doesn't load, use a tunnel:
- **Tunnel (recommended for the demo):** `ngrok http 8000` or `cloudflared tunnel --url http://localhost:8000`, then restart with `PUBLIC_BASE_URL=<that https url>`.

| Phone | How |
|---|---|
| iPhone | Scan the QR with the Camera → Safari → **Add All** |
| Android | Google Calendar can't open .ics on the phone itself. On a computer, go to calendar.google.com → Settings → Import. Or subscribe by URL if the server is public. |
| Subscribe | The `webcal://` link keeps the calendar live-updating (needs a public URL) |

## How it works
```
file ──► extract.py ──► llm.py (Claude + forced tool call → strict JSON) ──► UI review/edit ──► ics.py ──► .ics + QR
```
- **extract.py**: text-layer PDFs → pdfplumber text (tables included). Scanned PDFs → sent to Claude as a native PDF. Images → Claude vision. .docx → python-docx.
- **llm.py**: a JSON schema covering meetings / no-class days / events / warnings. The prompt turns things like "Week 5 Thursday" into real dates.
- **ics.py**: each weekly class is **one** event with `RRULE` + `EXDATE` for holidays, so the calendar stays clean and holidays are skipped. Exams get reminders 1 week and 1 day ahead. Deadlines show as a 30-min block ending at the due time. DST is handled through a VTIMEZONE.

## Demo script (≈90 s)
1. The problem: "Every semester I type 5 syllabi into my calendar by hand and still miss a midterm."
2. Drag in a real PDF syllabus plus a **screenshot** of another one. Showing that images work too gets a strong reaction.
3. Show the review screen: a holiday is skipped automatically, and the "Double-check" warnings show it doesn't just guess silently.
4. Click Generate → scan the QR on stage → **Add All** → open the iPhone calendar to show the midterm with its reminder.

## Ideas if you have time left
- Merge multiple courses and flag **exam conflicts** / weeks with 3+ deadlines ("hell week" heatmap)
- Google Calendar OAuth to push events directly (fixes the Android flow)
- Per-course colors, a Canvas / Blackboard link import
