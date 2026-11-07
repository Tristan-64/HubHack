"""Self test for the reviewer box editing (labels, move/resize/delete state, exports, outlined video).

Run:  source .venv/bin/activate && python selftest.py
Needs no network and no AI model. Creates (and removes) a temporary upload id and outputs/selftest/.
"""
import copy
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import review  # noqa: E402

PASS = []


def ok(cond, msg):
    assert cond, "FAILED: " + msg
    PASS.append(msg)


W, H, FPS = 320, 180, 10


def fixture():
    res = {"model": "nano", "sample_fps": 2.0, "min_conf": 0.2, "duration": 1.2, "fps": FPS, "frames": 12, "width": W, "height": H,
           "settings": {}, "filtered": None, "playable": "original.mp4",
           "samples": [{"t": 0.0, "frame": 0, "boxes": [[.1, .1, .3, .3, .9], [.5, .5, .7, .7, .4]]},
                       {"t": 0.5, "frame": 5, "boxes": [[.2, .2, .4, .4, .8]]},
                       {"t": 1.0, "frame": 10, "boxes": []}]}
    c = {"x1": .1, "y1": .1, "x2": .3, "y2": .3}
    state = {"version": 1, "next_id": 2,
             "ai": {"0:0": {"x1": .12, "y1": .1, "x2": .32, "y2": .3, "label": "cunner", "rejected": False, "orig": {**c, "label": "fish"}},
                    "0:1": {"x1": .5, "y1": .5, "x2": .7, "y2": .7, "label": "fish", "rejected": True,
                            "orig": {"x1": .5, "y1": .5, "x2": .7, "y2": .7, "label": "fish"}}},
           "own": [{"id": "r1", "sample": 1, "x1": .5, "y1": .3, "x2": .8, "y2": .7, "label": "fish"}]}
    return res, state


def make_video(path, frames=12):
    tmp = Path(tempfile.mkdtemp()) / "raw.mp4"
    w = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for _ in range(frames):
        w.write(np.full((H, W, 3), 40, np.uint8))
    w.release()
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(tmp), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                   capture_output=True, check=True)


def frame_at(path, idx):
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok_, f = cap.read()
    cap.release()
    assert ok_
    return f


# ---------------------------------------------------------------- 1. review.py logic
res, state = fixture()
boxes = {b["id"]: b for b in review.materialize(res, state, 0.6)}
ok(boxes["m0-0"]["edited"] and boxes["m0-0"]["label"] == "cunner" and boxes["m0-0"]["source"] == "model", "AI box renamed+moved: source=model, edited=yes")
ok(boxes["m0-0"]["orig"]["label"] == "fish" and abs(boxes["m0-0"]["orig"]["x1"] - .1) < 1e-9, "original label and box are kept")
ok(boxes["m0-1"]["status"] == "rejected" and not boxes["m0-1"]["counted"], "deleted AI box is rejected and not counted")
ok(boxes["m1-0"]["counted"] and not boxes["m1-0"]["edited"] and boxes["m1-0"]["label"] == "fish", "untouched AI box: label fish, unedited")
ok(boxes["r1"]["source"] == "reviewer" and boxes["r1"]["counted"], "reviewer box counted")
ok(review.labels_used(list(boxes.values())) == "fish: 2; cunner: 1", "labels_used string")
back = copy.deepcopy(state)
back["ai"]["0:0"].update(x1=.1, x2=.3, label="fish")
ok(not {b["id"]: b for b in review.materialize(res, back, 0.6)}["m0-0"]["edited"], "moving back to the original place and name = unedited")
old = {"ai": {"0:0": {"x1": .15, "y1": .1, "x2": .3, "y2": .3}}, "own": [{"id": "r5", "sample": 0, "x1": .5, "y1": .5, "x2": .6, "y2": .6}]}
ob = {b["id"]: b for b in review.materialize(res, old, 0.6)}
ok(ob["m0-0"]["label"] == "fish" and not ob["m0-0"]["edited"] and ob["r5"]["label"] == "fish", "old saved file without labels opens (label fish, original = current)")
ok(review.load_state(ROOT / "does_not_exist.json") == review.empty_state(), "missing state file = empty state")

# ---------------------------------------------------------------- 2. JS model agrees with Python
with tempfile.TemporaryDirectory() as td:
    fx = Path(td) / "fx.json"
    fx.write_text(json.dumps({"results": res, "state": state}))
    out = subprocess.run(["node", str(ROOT / "tests" / "boxes_node_test.js"), str(fx)], capture_output=True, text=True, check=True).stdout
    parsed = json.loads(out)
    js = {b["id"]: b for b in parsed["boxes"]}
    py_counts = [sum(1 for b in review.materialize(res, state, 0.6) if b["sample"] == i and b["counted"]) for i in range(len(res["samples"]))]
    ok(parsed["counts"] == py_counts, f"fish count per picture agrees between the page and the report: {py_counts}")
    for bid, b in boxes.items():
        ok(js[bid]["edited"] == b["edited"] and js[bid]["label"] == b["label"] and js[bid]["rejected"] == (b["status"] == "rejected"),
           f"JS and Python agree on box {bid}")
r = subprocess.run(["node", str(ROOT / "tests" / "boxes_node_test.js")], capture_output=True, text=True)
ok(r.returncode == 0, "Node tests of boxes.js pass: " + (r.stdout.strip() or r.stderr.strip()[-300:]))

# ---------------------------------------------------------------- 3. exports
tmp_out = Path(tempfile.mkdtemp())
files, summary = review.write_exports(tmp_out, "video.mp4", res, state, 0.6, "nano; Original (no changes)")
rows = list(csv.DictReader(open(tmp_out / "annotations.csv")))
cols = rows[0].keys()
ok({"label", "edited", "original_label", "original_x1", "original_y1", "original_x2", "original_y2", "source", "status"} <= set(cols), "annotations.csv has the new columns")
a = {r_["box_id"]: r_ for r_ in rows}
ok(a["m0-0"]["source"] == "model" and a["m0-0"]["edited"] == "yes" and a["m0-0"]["label"] == "cunner" and a["m0-0"]["original_label"] == "fish"
   and a["m0-0"]["original_x1"] == str(round(.1 * W)), "edited AI box row: source=model, edited=yes, new label, original box")
ok(a["m0-1"]["status"] == "rejected", "rejected AI box is in annotations.csv as rejected")
ok(a["m1-0"]["original_label"] == "" and a["m1-0"]["edited"] == "no", "unedited AI box has no original columns")
ok(a["m0-0"]["grid_cell"] == "A1" and a["r1"]["grid_cell"] == "B2", "annotations.csv names the grid cell (A1, B2) of each box")
ok(review.grid_cell(0.99, 0.99, 3, 3) == "C3" and review.grid_cell(0.5, 0.0, 2, 4) == "A3", "grid cells are lettered by row, numbered by column")
fr = list(csv.DictReader(open(tmp_out / "frames.csv")))
ok("edited" in fr[0] and fr[0]["edited"] == "1", "frames.csv has an edited count")
sm = list(csv.DictReader(open(tmp_out / "summary.csv")))[0]
ok(sm["boxes_edited"] == "1" and sm["labels_used"] == "fish: 2; cunner: 1", "summary.csv: boxes_edited and labels_used")
ok((tmp_out / "review_state.json").exists(), "review_state.json is saved with the report")
shutil.rmtree(tmp_out)

# ---------------------------------------------------------------- 4. outlined video
work = Path(tempfile.mkdtemp())
src = work / "src.mp4"
make_video(src)
outp = review.outline_video(src, res, review.materialize(res, state, 0.6), work / "outlined.mp4")
f0 = frame_at(outp, 1)      # picture 0: renamed AI box at x .12-.32, y .1-.3
bg = np.array([40, 40, 40])
edge = f0[int(.2 * H), int(.12 * W)]
ok(np.abs(edge.astype(int) - bg).sum() > 80, "accepted AI box is drawn in the outlined video")
label_zone = f0[max(0, int(.1 * H) - 16):int(.1 * H), int(.12 * W):int(.12 * W) + 40]
ok(np.abs(label_zone.astype(int) - bg).sum(axis=2).mean() > 60, "the box label is drawn above the box")
f_rej = frame_at(outp, 5)   # picture 1 (t=.5): rejected m0-1 belongs to picture 0, so check picture 0 area instead
rej_px = f0[int(.6 * H), int(.5 * W)]   # edge of the rejected box (.5-.7) in picture 0
ok(np.abs(rej_px.astype(int) - bg).sum() < 40, "rejected AI box is not drawn in the outlined video")
st2 = copy.deepcopy(state)
st2["ai"]["0:1"]["rejected"] = False
restored = review.outline_video(src, res, review.materialize(res, st2, 0.0), work / "outlined2.mp4")   # thr 0: the 0.4 box counts
ok(np.abs(frame_at(restored, 1)[int(.6 * H), int(.5 * W)].astype(int) - bg).sum() > 80, "restoring the AI box brings it back")
shutil.rmtree(work)

# ---------------------------------------------------------------- 5. API round trip (state survives, exports, outline)
from fastapi.testclient import TestClient  # noqa: E402
import app as appmod  # noqa: E402

VID = "feedfacecafebeef"
d = appmod.UPLOADS / VID
shutil.rmtree(d, ignore_errors=True)
d.mkdir(parents=True)
make_video(d / "original.mp4")
(d / "name.txt").write_text("selftest.mp4")
(d / "results_nano_2.json").write_text(json.dumps(res))
c = TestClient(appmod.app)
q = {"model": "nano", "sample_fps": 2}
ok(c.get(f"/api/review/{VID}", params=q).json()["own"] == [], "no saved edits yet")
ok(c.put(f"/api/review/{VID}", params=q, json=state).json()["saved"], "edits saved")
back = c.get(f"/api/review/{VID}", params=q).json()           # what a page refresh would load
ok(back["ai"]["0:0"]["label"] == "cunner" and back["ai"]["0:1"]["rejected"] and back["own"][0]["id"] == "r1", "edits survive a reload (new request)")
e = c.post(f"/api/export/{VID}", params={**q, "thr": 0.6}).json()
ok('id="cntBig"' in c.get("/").text, "the fish count badge is on the page")
ok(set(e["files"]) >= {"annotations.csv", "frames.csv", "summary.csv"}, "export wrote the CSV files")
ok(c.get(f"/download/{VID}/annotations.csv").status_code == 200, "CSV download works")
ok(c.post(f"/api/outline/{VID}", params={**q, "thr": 0.6}).json()["started"], "outlined video started")
for _ in range(120):
    s = c.get(f"/api/outline_status/{VID}", params=q).json()
    if s["stage"] in ("done", "error"):
        break
    time.sleep(0.5)
ok(s["stage"] == "done", "outlined video finished: " + str(s))
ok(c.get(f"/download/{VID}/outlined.mp4").status_code == 200, "outlined video download works")
ok(c.get(f"/download/{VID}/passwd").status_code == 404, "only known files can be downloaded")
shutil.rmtree(d, ignore_errors=True)
shutil.rmtree(appmod.OUTPUTS / "selftest", ignore_errors=True)

# ---------------------------------------------------------------- 6. fish lookup (fishmorph_clean.csv)
import fishmorph  # noqa: E402
import pandas as pd  # noqa: E402

ok(fishmorph.available(), "fishmorph_clean.csv is in the tidesight folder")
inf = fishmorph.info()
ok(inf["rows"] > 8000 and [t_["code"] for t_ in inf["traits"]] == ["MBl", "BEl", "VEp", "REs", "OGp", "RMl", "BLs", "PFv", "PFs", "CPt"], "all 10 traits are known")
row = pd.read_csv(fishmorph.CSV, encoding="utf-8-sig").dropna(subset=fishmorph.CODES).iloc[250]
vals = {k: float(row[k]) for k in fishmorph.CODES}
top = fishmorph.search(vals)
ok(len(top) == 5 and top[0]["species"] == row["Genus.Species"] and top[0]["difference"] == 0, "searching with a real fish's numbers finds that fish first, difference 0")
ok(all(top[i]["difference"] <= top[i + 1]["difference"] for i in range(4)), "results are sorted closest first")
ok(len(fishmorph.search({"MBI": 15, "bei": 4})) == 5, "capital-I names (MBI, BEI, RMI) and lower case are accepted")
for bad, why in (({}, "nothing typed"), ({"MBl": "abc"}, "not a number"), ({"MBl": -3}, "negative length")):
    try:
        fishmorph.search(bad)
        ok(False, "should reject: " + why)
    except ValueError:
        ok(True, "rejects " + why)
c = TestClient(appmod.app)
ok(c.get("/api/fishmorph/info").json()["available"], "fish lookup info endpoint works")
r_ = c.post("/api/fishmorph/search", json={"values": {"MBl": 12, "VEp": 0.55}})
ok(r_.status_code == 200 and len(r_.json()["results"]) == 5, "fish lookup search endpoint returns 5 fish")
ok(c.post("/api/fishmorph/search", json={"values": {}}).status_code == 400, "empty search gives a friendly error")
page = c.get("/").text
ok('id="lpanel"' in page and 'id="srchBtn"' in page and 'id="lpRail"' in page and 'id="rpRail"' in page, "page has the left lookup panel and both minimise rails")

print(f"selftest: {len(PASS)} checks passed")
