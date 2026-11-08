"""Reviewer edits on top of the AI's boxes: labels, moved/resized boxes, rejected AI boxes, own boxes.

The AI only ever says "fish". People may type any name on any box. Nothing here talks to a network.
Coordinates are normalised 0-1 (like results_*.json).
"""
import bisect
import csv
import json
import subprocess
from collections import Counter
from pathlib import Path

import cv2

DEFAULT_LABEL = "fish"
TOL = 1e-4
COORDS = ("x1", "y1", "x2", "y2")


# ---------------------------------------------------------------- state file
def empty_state():
    return {"version": 1, "ai": {}, "own": [], "next_id": 1}


def normalize_state(st):
    """Accepts older/partial files: missing label -> 'fish', missing original -> current."""
    out = empty_state()
    if not isinstance(st, dict):
        return out
    for key, e in (st.get("ai") or {}).items():
        if not isinstance(e, dict):
            continue
        e = dict(e)
        e["label"] = (e.get("label") or DEFAULT_LABEL).strip() or DEFAULT_LABEL
        e["rejected"] = bool(e.get("rejected", False))
        if "orig" in e and isinstance(e["orig"], dict):
            e["orig"] = {**{c: e[c] for c in COORDS if c in e}, "label": DEFAULT_LABEL, **e["orig"]}
        elif all(c in e for c in COORDS):
            e["orig"] = {**{c: e[c] for c in COORDS}, "label": e["label"]}  # old file: original = current
        out["ai"][key] = e
    for o in st.get("own") or []:
        if isinstance(o, dict) and all(c in o for c in COORDS) and "sample" in o:
            o = dict(o)
            o["label"] = (o.get("label") or DEFAULT_LABEL).strip() or DEFAULT_LABEL
            o.setdefault("id", f"r{len(out['own']) + 1}")
            out["own"].append(o)
    out["next_id"] = int(st.get("next_id") or (len(out["own"]) + 1))
    return out


def load_state(path):
    try:
        return normalize_state(json.loads(Path(path).read_text()))
    except Exception:
        return empty_state()


def save_state(path, state):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(normalize_state(state)))
    tmp.replace(path)


# ---------------------------------------------------------------- merge
def _differs(cur, orig):
    return any(abs(float(cur[c]) - float(orig[c])) > TOL for c in COORDS) or cur["label"] != orig["label"]


# Merge AI boxes + reviewer edits into one flat list. "counted" = not rejected and (own, or confidence >= slider, or edited). Same rule as boxes.js countedAt.
def materialize(res, state, thr):
    """Flat list of every box (AI + reviewer) with its final label / status / edited flag."""
    state = normalize_state(state)
    W, H = res["width"], res["height"]
    out = []
    for i, s in enumerate(res["samples"]):
        for j, b in enumerate(s["boxes"]):
            base = {"x1": b[0], "y1": b[1], "x2": b[2], "y2": b[3], "label": DEFAULT_LABEL}
            e = state["ai"].get(f"{i}:{j}")
            cur, orig, rejected = dict(base), dict(base), False
            if e:
                cur.update({k: e[k] for k in (*COORDS, "label") if k in e})
                orig = dict(e.get("orig") or cur)
                rejected = bool(e.get("rejected"))
            edited = _differs(cur, orig)
            conf = float(b[4])
            counted = (not rejected) and (conf >= thr or edited)
            out.append({"id": f"m{i}-{j}", "sample": i, "j": j, "t": s["t"], "frame": s["frame"], "source": "model",
                        "label": cur["label"], "confidence": conf, "status": "rejected" if rejected else "active",
                        "edited": edited, "counted": counted, "cur": cur, "orig": orig, "W": W, "H": H})
    for o in state["own"]:
        i = int(o["sample"])
        if not 0 <= i < len(res["samples"]):
            continue
        s = res["samples"][i]
        cur = {c: o[c] for c in COORDS}
        cur["label"] = o["label"]
        out.append({"id": o["id"], "sample": i, "j": None, "t": s["t"], "frame": s["frame"], "source": "reviewer",
                    "label": o["label"], "confidence": None, "status": "active", "edited": False, "counted": True,
                    "cur": cur, "orig": None, "W": W, "H": H})
    return out


def labels_used(boxes):
    c = Counter(b["label"] for b in boxes if b["counted"])
    return "; ".join(f"{k}: {v}" for k, v in sorted(c.items(), key=lambda kv: (-kv[1], kv[0] != DEFAULT_LABEL, kv[0])))


# ---------------------------------------------------------------- CSV
CSV_NAME = "fish_detections.csv"
ANN_COLS = ["video", "sample", "time_s", "frame", "box_id", "source", "label", "edited", "status", "confidence",
            "x1", "y1", "x2", "y2", "grid_cell", "counted", "original_label", "original_x1", "original_y1", "original_x2", "original_y2"]


def grid_cell(cx, cy, rows=3, cols=3):
    """A1, A2, B1... (letter = row from the top, number = column from the left)."""
    r_ = min(max(int(cy * rows), 0), rows - 1)
    c_ = min(max(int(cx * cols), 0), cols - 1)
    return f"{chr(ord('A') + r_)}{c_ + 1}"


def build_tables(video, res, boxes, thr, run_text, rows=3, cols=3):
    W, H = res["width"], res["height"]
    ann = []
    for b in boxes:
        row = {"video": video, "sample": b["sample"] + 1, "time_s": b["t"], "frame": b["frame"], "box_id": b["id"],
               "source": "auto" if b["source"] == "model" else "me", "label": b["label"], "edited": "yes" if b["edited"] else "no", "status": b["status"],
               "confidence": "" if b["confidence"] is None else round(b["confidence"], 4),
               "x1": round(b["cur"]["x1"] * W), "y1": round(b["cur"]["y1"] * H), "x2": round(b["cur"]["x2"] * W),
               "y2": round(b["cur"]["y2"] * H),
               "grid_cell": grid_cell((b["cur"]["x1"] + b["cur"]["x2"]) / 2, (b["cur"]["y1"] + b["cur"]["y2"]) / 2, rows, cols),
               "counted": "yes" if b["counted"] else "no",
               "original_label": "", "original_x1": "", "original_y1": "", "original_x2": "", "original_y2": ""}
        if b["source"] == "model" and b["edited"]:
            o = b["orig"]
            row.update(original_label=o["label"], original_x1=round(o["x1"] * W), original_y1=round(o["y1"] * H),
                       original_x2=round(o["x2"] * W), original_y2=round(o["y2"] * H))
        ann.append(row)
    frames = []
    for i, s in enumerate(res["samples"]):
        bs = [b for b in boxes if b["sample"] == i]
        frames.append({"sample": i + 1, "time_s": s["t"], "frame": s["frame"],
                       "ai_boxes": sum(1 for b in bs if b["source"] == "model" and b["counted"]),
                       "reviewer_boxes": sum(1 for b in bs if b["source"] == "reviewer"),
                       "rejected": sum(1 for b in bs if b["status"] == "rejected"),
                       "edited": sum(1 for b in bs if b["edited"]),
                       "counted_total": sum(1 for b in bs if b["counted"])})
    ai = [b for b in boxes if b["source"] == "model"]
    summary = {"video": video, "run_settings": run_text, "detector": res.get("model"), "pictures_per_second": res["sample_fps"],
               "confidence_threshold": thr, "sampled_frames": len(res["samples"]),
               "boxes_counted": sum(1 for b in boxes if b["counted"]),
               "ai_boxes_counted": sum(1 for b in ai if b["counted"]),
               "reviewer_boxes": sum(1 for b in boxes if b["source"] == "reviewer"),
               "boxes_rejected": sum(1 for b in boxes if b["status"] == "rejected"),
               "boxes_edited": sum(1 for b in boxes if b["edited"]), "labels_used": labels_used(boxes), "grid": f"{rows}x{cols}"}
    return ann, frames, summary


# Write fish_detections.csv (the only report) and the review_state.json save file.
def write_exports(outdir, video, res, state, thr, run_text, rows=3, cols=3):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    boxes = materialize(res, state, thr)
    ann, frames, summary = build_tables(video, res, boxes, thr, run_text, rows, cols)
    with open(outdir / CSV_NAME, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ANN_COLS)
        w.writeheader()
        w.writerows(ann)
    shutil_state = outdir / "review_state.json"
    shutil_state.write_text(json.dumps(normalize_state(state), indent=1))
    return [CSV_NAME, "review_state.json"], summary


# ---------------------------------------------------------------- outlined video
TEAL, BLUE, AMBER = (175, 196, 20), (246, 130, 59), (41, 180, 240)  # BGR


# Teal = AI box, blue = reviewer box, amber corner marker = edited AI box.
def draw_boxes(frame, shown, W, H):
    scale = max(0.5, W / 1600.0)
    th = max(2, round(2 * scale))
    for b in shown:
        c = b["cur"]
        x1, y1, x2, y2 = int(c["x1"] * W), int(c["y1"] * H), int(c["x2"] * W), int(c["y2"] * H)
        col = TEAL if b["source"] == "model" else BLUE
        cv2.rectangle(frame, (x1, y1), (x2, y2), col, th)
        text = b["label"] if b["confidence"] is None else f"{b['label']} {b['confidence']:.2f}"
        (tw, tht), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, th)
        ty = y1 - 4 if y1 - tht - 8 >= 0 else y1 + tht + 6
        top = ty - tht - 4
        cv2.rectangle(frame, (x1, top), (x1 + tw + 8, ty + 4), col, -1)
        cv2.putText(frame, text, (x1 + 4, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, (20, 20, 6), th, cv2.LINE_AA)
        if b["source"] == "model" and b["edited"]:  # small amber marker = edited AI box
            m = max(6, round(9 * scale))
            cv2.rectangle(frame, (x2 - m, y1), (x2, y1 + m), AMBER, -1)
    return frame


def outline_video(src, res, boxes, out_path, progress=None):
    """Re-encode the video with the counted, non-rejected boxes and their names drawn on it."""
    import imageio_ffmpeg
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or res["fps"] or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError("Could not read the video.")
    H, W = frame.shape[:2]
    times = [s["t"] for s in res["samples"]]
    by_sample = {}
    for b in boxes:
        if b["counted"] and b["status"] == "active":
            by_sample.setdefault(b["sample"], []).append(b)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp.mp4")
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", f"{fps}", "-i", "-",
           "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(tmp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = 0
    try:
        while ok:
            t = n / fps
            k = bisect.bisect_left(times, t)
            if k > 0 and (k == len(times) or abs(times[k - 1] - t) <= abs(times[k] - t)):
                k -= 1
            k = min(k, len(times) - 1)
            shown = by_sample.get(k, [])
            if shown and abs(times[k] - t) <= 1.01 / res["sample_fps"]:
                frame = draw_boxes(frame, shown, W, H)
            proc.stdin.write(frame.tobytes())
            n += 1
            if progress and n % 5 == 0:
                progress(n, total)
            ok, frame = cap.read()
    finally:
        cap.release()
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError("Could not make the outlined video.")
    tmp.replace(out_path)
    return out_path
