# Working rules (FAST MODE)
- Build complete, working features. End with ONE command to run and a short list of what to test.
- When the user reports an error, fix it and say what to run next.
- Don't ask for approval on small steps.
- Log every command and setting change in NOTES.md.
- User is technical; app users are not: on-screen text must be plain language.
- App deps only: streamlit, opencv-python, numpy, pandas. No PyTorch.
- Modules: video.py, enhance.py, detect.py, grid.py, report.py; app.py is the Streamlit page.
