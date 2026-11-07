"""
TideSight - automated MeanCount for Coastal Action fish video surveys.

Follows the DRAFT Fish Video Analysis Protocol:
  1. Trim the start and end of the video (sediment settling).
  2. Take a subsample every N seconds across the analysis window.
  3. At each subsample, count fish in the 1-second window (highest single-frame count).
  4. Write the protocol spreadsheet (one row per subsample) and the MeanCount.
  5. Save a screenshot of every subsample with boxes drawn on it.
  6. Write a VIAME-CSV so every detection can be reviewed in VIAME's DIVE app.

Usage:
    python run_tidesight.py VIDEO.mp4
    python run_tidesight.py VIDEO.mp4 --video-id T1_STAT1 --skip-start 120
    python run_tidesight.py VIDEO.mp4 --dry-run     # test the pipeline without a GPU or model
"""

import argparse
import csv
import json
import os
import random
import sys
import time

import cv2
import yaml

GREEN = (80, 200, 60)    # counted
ORANGE = (0, 165, 255)   # flagged for review


# ---------------------------------------------------------------- detector

def pick_device(torch):
    """NVIDIA GPU if present, else Apple Silicon GPU (MPS), else CPU."""
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class ZeroShotDetector:
    """Grounding DINO: finds objects matching a text prompt, no training needed."""

    def __init__(self, model_id, prompt, min_score, device=None):
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # Mac: run unsupported steps on CPU
        import torch
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
        self.torch = torch
        self.device = device or pick_device(torch)
        print(f"Loading {model_id} on {self.device} ...")
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(self.device)
        self.model.eval()
        self.prompt = prompt
        self.min_score = min_score

    def __call__(self, frame_bgr):
        from PIL import Image
        image = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        inputs = self.processor(images=image, text=self.prompt, return_tensors="pt").to(self.device)
        with self.torch.no_grad():
            outputs = self.model(**inputs)
        sizes = [image.size[::-1]]
        try:
            r = self.processor.post_process_grounded_object_detection(
                outputs, inputs.input_ids, threshold=self.min_score,
                text_threshold=self.min_score, target_sizes=sizes)[0]
        except TypeError:  # older transformers versions
            r = self.processor.post_process_grounded_object_detection(
                outputs, inputs.input_ids, box_threshold=self.min_score,
                text_threshold=self.min_score, target_sizes=sizes)[0]
        labels = r.get("text_labels", r["labels"])
        return [
            {"label": str(l) or "fish", "score": float(s), "box": [int(round(v)) for v in b.tolist()]}
            for l, s, b in zip(labels, r["scores"], r["boxes"])
        ]


class FakeDetector:
    """Random boxes, for testing the pipeline with --dry-run (no GPU, no model)."""

    def __init__(self, seed=7):
        self.rng = random.Random(seed)

    def __call__(self, frame_bgr):
        h, w = frame_bgr.shape[:2]
        out = []
        for _ in range(self.rng.choice([0, 0, 1, 1, 2, 3])):
            x, y = self.rng.randint(0, w - 120), self.rng.randint(0, h - 70)
            out.append({"label": "fish", "score": round(self.rng.uniform(0.2, 0.9), 2),
                        "box": [x, y, x + 120, y + 70]})
        return out


# ---------------------------------------------------------------- protocol steps

def analysis_window(duration_s, cfg, skip_start=None):
    """Return (start_s, end_s) of the analysis segment, per the protocol."""
    a = cfg["analysis_window"]
    start = a["skip_start_s"] if skip_start is None else skip_start
    end = min(duration_s - a["skip_end_s"], start + a["length_min"] * 60)
    if end <= start:
        sys.exit(f"Video is only {duration_s:.0f} s long; too short for the analysis window. "
                 "Lower skip_start_s / skip_end_s in config.yaml.")
    return start, end


def subsample_times(start, end, interval):
    """Equally spaced subsample points: start+interval/2, then every interval seconds."""
    times, t = [], start + interval / 2
    while t < end:
        times.append(round(t, 2))
        t += interval
    return times


def read_frame(cap, t_s):
    cap.set(cv2.CAP_PROP_POS_MSEC, t_s * 1000)
    ok, frame = cap.read()
    return frame if ok else None


def count_at(cap, t, detector, cfg):
    """Count fish in the 1-second window around t. Returns the best single frame."""
    c, d = cfg["counting"], cfg["detector"]
    n = max(1, c["frames_in_window"])
    offsets = [0.0] if n == 1 else [
        -c["half_window_s"] + i * (2 * c["half_window_s"]) / (n - 1) for i in range(n)]
    best = None
    for off in offsets:
        frame = read_frame(cap, max(0.0, t + off))
        if frame is None:
            continue
        dets = detector(frame)
        counted = [x for x in dets if x["score"] >= d["count_threshold"]]
        flagged = [x for x in dets if d["review_threshold"] <= x["score"] < d["count_threshold"]]
        cand = {"t": t + off, "frame": frame, "counted": counted, "flagged": flagged}
        # highest count wins; ties go to the frame closest to the subsample point
        if best is None or len(counted) > len(best["counted"]) or (
                len(counted) == len(best["counted"]) and abs(off) < abs(best["t"] - t)):
            best = cand
    return best


def draw(frame, counted, flagged, caption):
    img = frame.copy()
    for color, dets, tag in ((ORANGE, flagged, "?"), (GREEN, counted, "")):
        for x in dets:
            x1, y1, x2, y2 = x["box"]
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            cv2.putText(img, f"{tag}{x['label']} {x['score']:.2f}", (x1, max(18, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    cv2.rectangle(img, (0, 0), (img.shape[1], 34), (0, 0, 0), -1)
    cv2.putText(img, caption, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return img


def mmss(t):
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def viame_ts(t):
    h, m, s = int(t // 3600), int(t // 60) % 60, t % 60
    return f"{h:02d}:{m:02d}:{s:09.6f}"


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Automated MeanCount for fish survey video.")
    ap.add_argument("video")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--video-id", help="Video ID as in Coastal Action's spreadsheet (default: file name)")
    ap.add_argument("--skip-start", type=float, help="override seconds skipped at the start (sediment)")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--dry-run", action="store_true", help="use random boxes instead of the model")
    ap.add_argument("--cpu", action="store_true", help="force CPU (use if the Mac GPU gives an error)")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        sys.exit(f"Could not open video: {args.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps

    video_id = args.video_id or os.path.splitext(os.path.basename(args.video))[0]
    out_dir = os.path.join(args.out, video_id)
    shots_dir = os.path.join(out_dir, "screenshots")
    os.makedirs(shots_dir, exist_ok=True)

    start, end = analysis_window(duration, cfg, args.skip_start)
    times = subsample_times(start, end, cfg["subsampling"]["interval_s"])
    print(f"Video {video_id}: {duration / 60:.1f} min at {fps:.1f} fps")
    print(f"Analysis window {mmss(start)} to {mmss(end)}, {len(times)} subsamples")

    detector = FakeDetector() if args.dry_run else ZeroShotDetector(
        cfg["detector"]["model"], cfg["detector"]["prompt"], cfg["detector"]["review_threshold"],
        device="cpu" if args.cpu else None)

    rows, viame_rows, det_id = [], [], 0
    t0 = time.time()
    for i, t in enumerate(times, start=1):
        best = count_at(cap, t, detector, cfg)
        if best is None:
            print(f"  #{i:02d} {mmss(t)}  could not read frame, skipped")
            continue
        n, nf = len(best["counted"]), len(best["flagged"])
        shot = f"subsample_{i:02d}_{mmss(t).replace(':', 'm').replace('.', 's')}.jpg"
        caption = f"{video_id}  #{i}  {mmss(t)}  fish counted: {n}  flagged: {nf}"
        cv2.imwrite(os.path.join(shots_dir, shot), draw(best["frame"], best["counted"], best["flagged"], caption))

        notes = []
        if nf:
            notes.append(f"{nf} possible fish below count threshold, needs review")
        rows.append({
            "video_id": video_id, "subsample": i, "timestamp": mmss(t),
            "total_fish_count": n, "possible_fish_flagged": nf,
            "needs_review": "yes" if nf else "no",
            "unknown_unable_to_id": n,   # species step not added yet: every counted fish is unknown species
            "invertebrate_count": "",
            "notes": "; ".join(notes), "screenshot": f"screenshots/{shot}",
        })
        frame_no = int(round(best["t"] * fps))
        for x in best["counted"] + best["flagged"]:
            x1, y1, x2, y2 = x["box"]
            label = "fish" if x in best["counted"] else "possible_fish"
            viame_rows.append([det_id, viame_ts(best["t"]), frame_no, x1, y1, x2, y2,
                               f"{x['score']:.3f}", -1, label, f"{x['score']:.3f}"])
            det_id += 1
        print(f"  #{i:02d} {mmss(t)}  counted {n}  flagged {nf}")
    cap.release()

    if not rows:
        sys.exit("No subsamples could be read.")
    mean_count = sum(r["total_fish_count"] for r in rows) / len(rows)

    with open(os.path.join(out_dir, "meancount_sheet.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    with open(os.path.join(out_dir, "detections_viame.csv"), "w", newline="") as f:
        f.write("# 1: Detection or Track-id,2: Video or Image Identifier,3: Unique Frame Identifier,"
                "4-7: Img-bbox(TL_x,TL_y,BR_x,BR_y),8: Detection or Length Confidence,"
                "9: Target Length (0 or -1 if invalid),10-11+: Repeated Species,Confidence Pairs or Attributes\n")
        f.write(f"# metadata,fps: {fps:.3f}\n")
        csv.writer(f).writerows(viame_rows)

    summary = {
        "video_id": video_id, "video_file": os.path.basename(args.video),
        "duration_min": round(duration / 60, 2), "fps": round(fps, 3),
        "analysis_start": mmss(start), "analysis_end": mmss(end),
        "subsamples": len(rows), "mean_count": round(mean_count, 3),
        "subsamples_needing_review": sum(r["needs_review"] == "yes" for r in rows),
        "detector": "dry-run (random boxes)" if args.dry_run else cfg["detector"]["model"],
        "count_threshold": cfg["detector"]["count_threshold"],
        "review_threshold": cfg["detector"]["review_threshold"],
        "processing_seconds": round(time.time() - t0, 1),
    }
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nMeanCount = {mean_count:.2f} fish per subsample ({len(rows)} subsamples)")
    print(f"Subsamples needing review: {summary['subsamples_needing_review']}")
    print(f"Processing time: {summary['processing_seconds']} s")
    print(f"Outputs in: {out_dir}/  (meancount_sheet.csv, detections_viame.csv, summary.json, screenshots/)")


if __name__ == "__main__":
    main()
