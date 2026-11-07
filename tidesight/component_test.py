"""Component test for the box editor in a real (headless) Chrome.

Run:  source .venv/bin/activate && python component_test.py
It serves static/ on a temporary local port, loads static/test_editor.html in headless Chrome and reads the PASS/FAIL list.
"""
import html
import http.server
import re
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).parent
CHROME = next((p for p in ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                           "/Applications/Chromium.app/Contents/MacOS/Chromium",
                           "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"] if Path(p).exists()), None)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def log_message(self, *a):
        pass


def main():
    if not CHROME:
        print("component test: Chrome was not found (install Google Chrome).")
        return 2
    with socketserver.TCPServer(("127.0.0.1", 0), Quiet) as srv:
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=4000", "--dump-dom",
                            f"http://127.0.0.1:{port}/static/test_editor.html"], capture_output=True, text=True, timeout=90)
        srv.shutdown()
    m = re.search(r'<pre id="result"[^>]*>(.*?)</pre>', r.stdout, re.S)
    if not m:
        print("component test: no result found.\n", r.stderr[-500:])
        return 1
    out = html.unescape(m.group(1))
    print(out)
    return 0 if "ALL PASS" in out else 1


if __name__ == "__main__":
    sys.exit(main())
