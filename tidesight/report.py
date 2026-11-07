"""CSV reports, MeanCount and screenshots."""
from pathlib import Path
import cv2
import pandas as pd
from video import mmss

OUT = Path(__file__).parent / "outputs"


def out_dir(video, *sub):
    p = OUT / Path(video).stem
    for s in sub:
        p = p / s
    p.mkdir(parents=True, exist_ok=True)
    return p


def frame_counts(frame):
    dets = frame["dets"]
    detected = len(dets)
    kept = sum(1 for d in dets if d["is_fish"])
    added = int(frame.get("missed", 0))
    return {"detected": detected, "removed": detected - kept, "added": added, "final": kept + added}


def mean_count(frames):
    return sum(frame_counts(f)["final"] for f in frames) / len(frames) if frames else 0.0


def save_screenshot(video, t, annotated_bgr):
    path = out_dir(video, "screenshots") / f"{Path(video).stem}_{mmss(t)}.png"
    cv2.imwrite(str(path), annotated_bgr)
    return path


def build_report(video, frames, settings):
    d = out_dir(video)
    fish_rows, frame_rows = [], []
    for i, f in enumerate(frames, 1):
        c = frame_counts(f)
        frame_rows.append({"sample": i, "time_s": f["t"], "detected": c["detected"], "removed_by_reviewer": c["removed"],
                           "added_by_reviewer": c["added"], "final_count": c["final"],
                           "confirmed": "yes" if f["confirmed"] else "no"})
        for det in f["dets"]:
            fish_rows.append({"video": video, "sample": i, "time_s": f["t"], "grid_cell": det["cell"], "x": det["x"],
                              "y": det["y"], "width": det["w"], "height": det["h"], "species": det["species"],
                              "is_fish": "yes" if det["is_fish"] else "no", "detection_method": settings["method"]})
    n_conf = sum(1 for f in frames if f["confirmed"])
    final = n_conf == len(frames) and len(frames) > 0
    summary = {"video": video, "trim_start_s": settings["start"], "trim_end_s": settings["end"],
               "sampling_interval_s": settings["interval"], "detection_method": settings["method"],
               "brightness": settings["brightness"], "contrast": settings["contrast"], "gamma": settings["gamma"],
               "sampled_frames": len(frames), "frames_confirmed": n_conf, "MeanCount": round(mean_count(frames), 3),
               "report_status": "FINAL" if final else "NOT FINAL (not every frame is confirmed)"}
    cols = ["video", "sample", "time_s", "grid_cell", "x", "y", "width", "height", "species", "is_fish", "detection_method"]
    paths = {"fish.csv": pd.DataFrame(fish_rows, columns=cols), "frames.csv": pd.DataFrame(frame_rows),
             "summary.csv": pd.DataFrame([summary])}
    for name, df in paths.items():
        df.to_csv(d / name, index=False)
    return d, {n: (d / n).read_bytes() for n in paths}, summary
