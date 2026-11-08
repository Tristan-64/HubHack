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

## Filter panel as a slide-out drawer
- static/: removed the 2-column layout; #side is now a fixed right-edge drawer (Filters button, edge tab, ✕, Esc, scrim on narrow screens), opens automatically for the filter step and during runs, closes after results; "changed" badge when sliders differ from loaded results; extra "Start detection" button under the video in the filter step
- Checked: node syntax, DOM-id cross-check, app restarted and serving. Browser UI not tested here. No installs.

## Reviewer box editing (names, move, resize, delete/restore)
- Spec adapted: the pasted spec named files that do not exist here (review_component/, pipeline.py, PowerShell...); built on this FastAPI app instead. Fish-database part ignored on request.
- New: review.py (state, materialize, CSV exports, outlined video), static/boxes.js (model), static/editor.js (pointer/keyboard), tests/boxes_node_test.js, selftest.py, component_test.py + static/test_editor.html
- app.py: /api/review (GET/PUT), /api/export, /api/outline + /api/outline_status, /download/<id>/<file>; state per run in uploads/<id>/review_<model>_<fps>[_<sid>].json; exports in outputs/<video stem>/
- static/: Name box + Delete/Restore/Reset/Undo bar, tick row, Boxes list (Name column, "Boxes I edited" filter), stats (AI boxes edited, Boxes I drew), Save report / outlined video buttons; fish moments/timeline now use effective boxes (rejected removed, own added)
- Bug found by tests and fixed: rejecting an untouched AI box was silently undone by the "unedited again" clean-up (boxes.js ensureAI)
- Tests run: python selftest.py -> 34 checks passed; python component_test.py -> ALL PASS 11 (headless Chrome); real page loads in headless Chrome with no console errors. No pip installs.

## Fish count + grid overlay
- static/: "Fish in this picture" count bar (updateCount/countNow/peakCount), grid overlay in the Filters drawer (drawGrid, rows/cols 1-12), Cell column in the Boxes list
- review.py: grid_cell(), grid_cell column in annotations.csv, grid in summary.csv; app.py /api/export takes rows & cols
- selftest.py: grid_cell checks. Box add/remove/edit already existed (previous task), nothing new needed for that.

## Count badge on the video
- boxes.js: countedAt() (the one counting rule, same as report counted_total); app.js uses it for the badge (#cntBig on the video) and the bar; tests: Node (adds/removes/restore/accept), selftest (page count == frames.csv), Chrome component test (draw/delete/undo). No installs.

- Count badge now shows where the number comes from: "AI x + you y" (countedAt returns ai/own).

## Side panels + fish lookup
- Layout: 3-column grid (left lookup | video | right filters); both panels minimise to rails; removed the floating filter drawer/scrim/tab; fixed a stray </div> that had put the filters aside outside the layout
- fishmorph.py: nearest-species search over fishmorph_clean.csv (robust-scaled traits, log for MBl/BEl, missing-aware, aliases MBI/BEI/RMI); app.py /api/fishmorph/info + /search; left panel UI in static/app.js
- Tests: selftest.py (lookup + endpoints), component_test.py (static/test_layout.html measures the real page: video shrinks/grows, panels never cover it, rails work). Screenshot checked by eye. No installs.

## Fish pictures in the lookup results
- fishmorph_clean.csv now has image_url/thumbnail_url/image_source/image_credit/image_license/image_page (5,434 of 8,316 fish have pictures). fishmorph.py returns an "image" dict per result (cleaned, http(s) only) or null; app.js showResults draws the picture + credit + source link (all text escaped), falls back url -> thumb -> plain box.
- Tests: selftest (cleaning, rejection of javascript: links, null for fish without pictures, endpoint) and the Chrome layout test (5 cards, placeholders, escaping, load-failure fallback). No installs.

## Clean-up round
- Removed species.py, requirements-ai.txt, /api/species routes (species.csv kept for the old Streamlit app), moments, prev/next, summary stats, video count badge, detail/peak lines.
- Exports: only fish_detections.csv (+ review_state.json save file); source column auto/me.
- UI: sfps step 0.5; lookup steps; Boxes filters; before/after video mode + Show boxes. Tests: selftest 56, Chrome layout 29. No installs.
