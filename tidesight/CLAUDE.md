# Working rules (FAST MODE)
- Build it completely, then give the exact commands to run and what to test.
- When the user reports a problem, fix it and say what to run next.
- Log every command and setting change in NOTES.md.
- Don't ask for approval on small steps.
- User is technical; the page's users are not: plain, friendly wording on screen.

# The app
One local web page (FastAPI + static HTML/JS) on http://127.0.0.1:8000 (bind 127.0.0.1 only).
Upload -> choose video filters (before any detection) -> Start detection -> Community Fish Detector (RF-DETR Nano default, Small optional,
YOLOv12x via Ultralytics as fallback) -> review the original video with a transparent canvas of
boxes + confidence, a shaded fish timeline, a confidence slider.
RULE (replaces the old "no species"): the AI only ever detects "fish" and never names species. Human reviewers may type a name on
any box (select, rename, move, resize, delete; AI boxes are "rejected", not erased) and the reports/outlined video carry those names.
BioCLIP/species suggestions and the moments list were removed (Nov 2026). No hosted AI.
Use the Mac GPU (mps) with CPU fallback. Commands are for macOS/zsh.
Files: app.py (FastAPI), detector.py, review.py (edits, CSV, outlined video), static/index.html, app.js, boxes.js, editor.js, style.css.
Side panels: left = fish lookup (fishmorph.py + fishmorph_clean.csv, top-5 nearest by typed traits, with reference photos hot-linked by the browser from the CSV's image URLs; credits shown; the app itself still sends no video or data anywhere), right = video filters; both docked, minimisable, and push the video.
Tests: selftest.py (Python + Node), component_test.py (headless Chrome, static/test_editor.html), tests/boxes_node_test.js.
Old Streamlit prototype lives in streamlit_app.py (+ detect.py, video.py, etc.); not used by this app.
