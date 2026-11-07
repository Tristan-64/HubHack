# Working rules (FAST MODE)
- Build it completely, then give the exact commands to run and what to test.
- When the user reports a problem, fix it and say what to run next.
- Log every command and setting change in NOTES.md.
- Don't ask for approval on small steps.
- User is technical; the page's users are not: plain, friendly wording on screen.

# The app
One local web page (FastAPI + static HTML/JS) on http://127.0.0.1:8000 (bind 127.0.0.1 only).
Upload an underwater video -> Community Fish Detector (RF-DETR Nano default, Small optional,
YOLOv12x via Ultralytics as fallback) -> review the original video with a transparent canvas of
boxes + confidence, a shaded fish timeline, a confidence slider and a "fish moments" list.
No species, no reports, no grids. Use the Mac GPU (mps) with CPU fallback.
Files: app.py (FastAPI), detector.py, static/index.html, static/app.js, static/style.css.
Old Streamlit prototype lives in streamlit_app.py (+ detect.py, video.py, etc.); not used by this app.
