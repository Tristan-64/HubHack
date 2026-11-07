# NOTES — commands and setting changes

- Existing `.venv` was broken (pointed at /Users/zahera/Downloads/tidesight). Recreated: `python3.12 -m venv .venv`
- `pip install -r requirements.txt` (streamlit, opencv-python, numpy, pandas)
- requirements.txt reduced to the 4 app deps; old torch list saved as requirements-legacy.txt (only for run_tidesight.py / test_detector.py / validate.py)
- .gitignore: added `videos/*` (keeps videos/.gitkeep) and `models/*.weights` (`outputs/` already ignored)
- Added: CLAUDE.md, species.csv, video.py, enhance.py, grid.py, detect.py, report.py, app.py, videos/, models/
- Tested with a synthetic 30 s video (deleted afterwards) via streamlit.testing AppTest; outputs/ cleaned.
- Motion detection: uses average of |frame - frame(-0.5s)| and |frame - frame(+0.5s)|, threshold from sensitivity, morphology open (5x5) + close (31x31).
- Created ~/.streamlit/credentials.toml (empty email) to skip Streamlit's first-run prompt
- Added Community Fish Detector option (RF-DETR small, 1024). `requirements-ai.txt` = rfdetr. .gitignore: models/*.pth, models/*.pt
- Tested in a separate scratch venv (not .venv) so the main venv stays PyTorch-free; downloaded weights to models/ (git-ignored, 127 MB)
- Deleted the scratch venv afterwards (disk was 98% full)

## New task: FastAPI fish reviewer
- Replaced Streamlit app.py with FastAPI app.py: `git mv app.py streamlit_app.py`, old requirements saved as requirements-streamlit.txt, removed requirements-ai.txt
- New requirements.txt (fastapi, uvicorn, python-multipart, opencv-python, numpy, pillow, imageio-ffmpeg, rfdetr, certifi); `pip install -r requirements.txt` into .venv (adds torch 2.15, ~1.7 GB venv)
- .gitignore: added uploads/, models/
- Fix: python.org Python on macOS had no SSL root certs -> weight download failed; detector.py now uses certifi
- Tested with a synthetic mp4v video: transcode to H.264, nano model auto-download, mps available, JSON cache reuse, HTTP range requests. Test uploads deleted.
- design_reference.html and screenshot were NOT found in the folder; styling is my own (teal/amber, light) pending the real file.

## Species suggestions (BioCLIP 2)
- Added species.py (lazy pybioclip import, CustomLabelsClassifier, labels = species.csv scientific names + "Actinopterygii"), API routes /api/species/*, UI in static/. requirements-ai.txt = pybioclip (NOT installed by me).
- species.csv replaced with the 30 Nova Scotia species (the old 18-species Streamlit seed is overwritten; streamlit_app.py still reads common_name).
- Tested with a fake classifier via FastAPI TestClient (single frame, whole video, skip-already-done, small-box -> Unknown, unavailable -> HTTP 400). Real BioCLIP not run (not installed).
- No commands run besides tests; test upload dir removed.

## Picture filters
- enhance.py: enhance_frame/normalize_cfg/settings_id/describe_cfg (old enhance() kept for streamlit_app.py)
- app.py: cfg plumbing (results_<model>_<fps>[_<settingsid>].json, "" id = original), new /api/analyse, /api/runs, /api/preview, /api/compare; detector.py: lock around detect()
- static/: side panel (filters, preview, Reset, Re-run, saved runs), Before/after, comparison line
- Tested with FastAPI TestClient + real Nano model on a synthetic video: identity at defaults, every filter changes output, cached re-run, runs list, preview JPEG, compare. Browser UI not tested (no browser here). No pip installs; test uploads removed.

## Filters moved onto the video, chosen before detection
- Upload no longer starts detection; /api/prepare makes the playable copy; "Start detection" calls /api/analyse
- app.py: ensure_filtered() renders filtered_<id>.mp4 (OpenCV -> enhance_frame -> ffmpeg pipe, libx264 veryfast, no audio); detector reads the filtered file; render_only() backfills older runs; removed /api/preview
- static/: live SVG-filter preview on the <video> (approximate), exact filtered video once results exist, "stage-filters" layout before detection
- Tested via TestClient with the real Nano model: upload starts no detection, filtered video has same frame count/size, cached re-run, default cfg skips rendering, backfill, species path still importable. Browser UI not tested. No pip installs; test uploads removed.
