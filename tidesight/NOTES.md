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
