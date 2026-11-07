"""Coastal Action fish counter. Run with: streamlit run app.py"""
import cv2
import pandas as pd
import streamlit as st

import detect
import report
from enhance import enhance
from grid import draw_grid
from video import VIDEO_DIR, default_trim, list_videos, mmss, read_frame_at, sample_times, video_info
from pathlib import Path

st.set_page_config(page_title="Fish counter", layout="wide")
S = st.session_state


def species_list():
    p = Path(__file__).parent / "species.csv"
    names = pd.read_csv(p)["common_name"].tolist() if p.exists() else []
    return names + ["Unknown"]


def reset_all():
    for k in list(S.keys()):
        del S[k]


def rgb(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


st.title("🐟 Fish counter")
st.caption("Count fish in underwater video, one sampled picture at a time. Everything stays on this computer.")

# ---------- Step 1: choose video ----------
videos = list_videos()
if not videos:
    st.warning(f"No videos found. Copy your video files (.mp4, .mov, .avi or .m4v) into this folder, then reload the page:\n\n`{VIDEO_DIR}`")
    st.stop()

locked = S.get("trim_confirmed", False)
video = st.selectbox("1. Choose a video", videos, disabled=locked)
if S.get("video") != video:
    reset_all()
    S["video"] = video
path = VIDEO_DIR / video
info = video_info(path)
if info["duration"] <= 0:
    st.error("This video could not be read. Try another file.")
    st.stop()
dur = info["duration"]
st.write(f"Length: **{mmss(dur)}** ({dur:.0f} seconds)")

# ---------- Step 2: trim ----------
st.header("2. Trim the video")
st.write("The first and last minute are skipped so stirred-up sediment can settle. You can change these.")
d_start, d_end = default_trim(dur)
c1, c2, c3 = st.columns([1, 1, 1])
start = c1.number_input("Start (seconds)", 0.0, float(dur), float(S.get("start", d_start)), 1.0, disabled=locked, key="in_start")
end = c2.number_input("End (seconds)", 0.0, float(dur), float(S.get("end", d_end)), 1.0, disabled=locked, key="in_end")
if not locked:
    if c3.button("Confirm trim", type="primary"):
        if end <= start:
            st.error("The end must be after the start.")
        else:
            S.update(trim_confirmed=True, start=start, end=end)
            st.rerun()
else:
    c3.success(f"Trim locked: {S['start']:.0f}s to {S['end']:.0f}s")
if st.button("Start a new session"):
    reset_all()
    st.rerun()
if not locked:
    st.info("Confirm the trim to continue.")
    st.stop()
start, end = S["start"], S["end"]

# ---------- Step 3: enhancement ----------
st.header("3. Make the picture easier to see")
e1, e2, e3 = st.columns(3)
bri = e1.slider("Brightness", -100, 100, 0)
con = e2.slider("Contrast", 0.5, 3.0, 1.0, 0.1)
gam = e3.slider("Gamma (higher = brighter shadows)", 0.3, 3.0, 1.0, 0.1)
pt = st.slider("Preview picture at (seconds)", float(start), float(end), float(start), 1.0)
pf = read_frame_at(path, pt)
if pf is not None:
    b, a = st.columns(2)
    b.image(rgb(pf), caption="Before", width="stretch")
    a.image(rgb(enhance(pf, bri, con, gam)), caption="After", width="stretch")

# ---------- Step 4: sampling and detection ----------
st.header("4. Find the fish")
s1, s2, s3 = st.columns(3)
interval = s1.number_input("Take a picture every (seconds)", 1.0, 600.0, 60.0, 1.0)
rows = s2.number_input("Grid rows", 1, 10, 3)
cols = s3.number_input("Grid columns", 1, 10, 3)
yolo_ok = detect.yolo_available()
method_label = st.radio("How should fish be found?",
                        ["Motion detection (default)", "YOLO-Fish (AI)"], index=0,
                        captions=["Looks for things that moved. No AI needed.", "AI trained on fish. Needs extra files."])
if method_label.startswith("YOLO") and not yolo_ok:
    st.error("YOLO-Fish needs two files in the 'models' folder, and they are missing. "
             "Get the config file (yolo-fish-2.cfg) from https://github.com/tamim662/YOLO-Fish/tree/main/models and the "
             "weights file (merge_yolo-fish-2.weights) from the 'merged dataset' Google Drive link in that page's README. "
             "Until then, please use Motion detection.")
use_yolo = method_label.startswith("YOLO") and yolo_ok
if use_yolo:
    conf = st.slider("Confidence (higher = fewer, surer detections)", 0.05, 0.95, 0.4, 0.05)
else:
    m1, m2 = st.columns(2)
    sens = m1.slider("Sensitivity (higher = notices fainter movement)", 1, 100, 50)
    minsize = m2.slider("Smallest fish size (pixels of area)", 20, 5000, 300, 10)
method = "YOLO-Fish" if use_yolo else "Motion"
can_run = not (method_label.startswith("YOLO") and not yolo_ok)

if st.button("Run detection", type="primary", disabled=not can_run):
    times = sample_times(start, end, interval)
    fdir = report.out_dir(video, "frames")
    frames, bar = [], st.progress(0.0, text="Looking for fish...")
    enh = lambda f: enhance(f, bri, con, gam)
    for i, t in enumerate(times):
        if use_yolo:
            raw = read_frame_at(path, t)
            if raw is None:
                continue
            img = enh(raw)
            dets = detect.detect_yolo(img, conf, rows, cols)
        else:
            dets, raw = detect.detect_motion(path, t, enh, sens, minsize, rows, cols)
            if raw is None:
                continue
            img = enh(raw)
        jpg = fdir / f"{Path(video).stem}_{mmss(t)}.jpg"
        cv2.imwrite(str(jpg), img)
        for d in dets:
            d.update(is_fish=True, species="Unknown")
        frames.append({"t": t, "jpg": str(jpg), "dets": dets, "missed": 0, "confirmed": False})
        bar.progress((i + 1) / len(times), text=f"Picture {i + 1} of {len(times)}")
    bar.empty()
    S.update(frames=frames, idx=0, run_id=S.get("run_id", 0) + 1, rows=rows, cols=cols,
             settings=dict(method=method, start=start, end=end, interval=interval, brightness=bri, contrast=con, gamma=gam))
    st.rerun()

frames = S.get("frames")
if not frames:
    st.stop()

# ---------- Step 5: review ----------
st.header("5. Check the results")
n = len(frames)
S["idx"] = min(S.get("idx", 0), n - 1)
nav1, nav2, nav3 = st.columns([1, 2, 1])
if nav1.button("◀ Previous", disabled=S["idx"] == 0):
    S["idx"] -= 1
    st.rerun()
if nav3.button("Next ▶", disabled=S["idx"] == n - 1):
    S["idx"] += 1
    st.rerun()
i = S["idx"]
f = frames[i]
nav2.subheader(f"Frame {i + 1} of {n}  (at {mmss(f['t'])})")

img = cv2.imread(f["jpg"])
left, right = st.columns([3, 2])
with right:
    species = species_list()
    base = pd.DataFrame({"Fish #": range(1, len(f["dets"]) + 1),
                         "Grid cell": [d["cell"] for d in f["dets"]],
                         "Is a fish": [d["is_fish"] for d in f["dets"]],
                         "Species": [d["species"] for d in f["dets"]]})
    if f["dets"]:
        st.caption("Untick 'Is a fish' for mistakes (algae, sediment, bubbles). Pick a species if you know it.")
        edited = st.data_editor(
            base, key=f"ed_{S['run_id']}_{i}", hide_index=True, width="stretch",
            disabled=["Fish #", "Grid cell"],
            column_config={"Species": st.column_config.SelectboxColumn("Species", options=species, required=True),
                           "Is a fish": st.column_config.CheckboxColumn("Is a fish")})
        for d, (_, row) in zip(f["dets"], edited.iterrows()):
            d["is_fish"], d["species"] = bool(row["Is a fish"]), row["Species"]
    else:
        st.info("Nothing was detected in this picture.")
    f["missed"] = st.number_input("Fish missed by the detector", 0, 500, int(f["missed"]), key=f"miss_{S['run_id']}_{i}")
    f["confirmed"] = st.checkbox("Count confirmed", f["confirmed"], key=f"conf_{S['run_id']}_{i}")
    c = report.frame_counts(f)
    st.metric("Final count for this frame", c["final"])
with left:
    ann = detect.draw_detections(draw_grid(img, S["rows"], S["cols"]), f["dets"], [d["is_fish"] for d in f["dets"]])
    st.image(rgb(ann), width="stretch")
    if st.button("Save screenshot"):
        p = report.save_screenshot(video, f["t"], ann)
        st.success(f"Screenshot saved to: {p}")

# ---------- Step 6: totals and report ----------
st.header("6. Results and report")
nconf = sum(1 for x in frames if x["confirmed"])
m1, m2 = st.columns(2)
m1.metric("MeanCount (average fish per picture)", f"{report.mean_count(frames):.2f}")
m2.metric("Frames confirmed", f"{nconf} of {n}")
if nconf == n:
    st.success("Every frame is confirmed. The report will be marked FINAL.")
else:
    st.warning(f"{n - nconf} frame(s) not confirmed yet. The report will be marked NOT FINAL.")
if st.button("Build report"):
    d, files, summ = report.build_report(video, frames, S["settings"])
    S["report_files"], S["report_dir"], S["report_status"] = files, str(d), summ["report_status"]
if "report_files" in S:
    st.success(f"Report saved in: {S['report_dir']}  —  Status: {S['report_status']}")
    for name, data in S["report_files"].items():
        st.download_button(f"Download {name}", data, file_name=name, mime="text/csv", key=f"dl_{name}")
