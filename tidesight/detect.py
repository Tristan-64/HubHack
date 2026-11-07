"""Fish detection: motion (default) and YOLO-Fish via OpenCV DNN."""
from pathlib import Path
import cv2
import numpy as np
from grid import cell_for_point
from video import read_frame_at

MODEL_DIR = Path(__file__).parent / "models"
CFG = MODEL_DIR / "yolo-fish-2.cfg"
WEIGHTS = MODEL_DIR / "merge_yolo-fish-2.weights"
_net = None


def _finish(boxes, shape, rows, cols, scores=None):
    h, w = shape[:2]
    out = []
    for i, (x, y, bw, bh) in enumerate(boxes):
        cx, cy = x + bw // 2, y + bh // 2
        out.append({"x": int(x), "y": int(y), "w": int(bw), "h": int(bh), "cx": int(cx), "cy": int(cy),
                    "cell": cell_for_point(cx, cy, w, h, rows, cols),
                    "score": float(scores[i]) if scores is not None else None})
    out.sort(key=lambda d: (d["cy"], d["cx"]))
    return out


def detect_motion(path, t, enhance_fn, sensitivity, min_size, rows, cols, gap=0.5):
    """sensitivity 1..100 (higher = picks up fainter movement); min_size in pixels (blob area)."""
    cur = read_frame_at(path, t)
    if cur is None:
        return [], None
    before = read_frame_at(path, max(t - gap, 0))
    after = read_frame_at(path, t + gap)
    g = lambda f: cv2.GaussianBlur(cv2.cvtColor(enhance_fn(f), cv2.COLOR_BGR2GRAY), (5, 5), 0)
    gc = g(cur)
    diffs = [cv2.absdiff(gc, g(o)) for o in (before, after) if o is not None]
    if not diffs:
        return [], cur
    # average of the two differences: catches slow fish, and ghosts of fast fish are fainter
    diff = cv2.addWeighted(diffs[0], 0.5, diffs[-1], 0.5, 0)
    thr = int(np.interp(sensitivity, [1, 100], [60, 5]))
    _, mask = cv2.threshold(diff, thr, 255, cv2.THRESH_BINARY)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = [cv2.boundingRect(c) for c in cnts if cv2.contourArea(c) >= min_size]
    return _finish(boxes, cur.shape, rows, cols), cur


def yolo_available():
    return CFG.exists() and WEIGHTS.exists()


def detect_yolo(frame, conf, rows, cols, nms=0.4, size=416):
    global _net
    if _net is None:
        _net = cv2.dnn.readNetFromDarknet(str(CFG), str(WEIGHTS))
    h, w = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(frame, 1 / 255.0, (size, size), swapRB=True, crop=False)
    _net.setInput(blob)
    outs = _net.forward(_net.getUnconnectedOutLayersNames())
    boxes, scores = [], []
    for o in outs:
        for d in o:
            s = float(d[4] * (d[5:].max() if len(d) > 5 else 1))
            if s >= conf:
                bw, bh = int(d[2] * w), int(d[3] * h)
                boxes.append([int(d[0] * w - bw / 2), int(d[1] * h - bh / 2), bw, bh])
                scores.append(s)
    keep = cv2.dnn.NMSBoxes(boxes, scores, conf, nms)
    keep = np.array(keep).flatten().astype(int) if len(keep) else []
    return _finish([boxes[i] for i in keep], frame.shape, rows, cols, [scores[i] for i in keep])


def draw_detections(frame, dets, is_fish=None):
    out = frame.copy()
    for i, d in enumerate(dets):
        ok = True if is_fish is None else bool(is_fish[i])
        col = (0, 255, 0) if ok else (0, 0, 255)
        cv2.rectangle(out, (d["x"], d["y"]), (d["x"] + d["w"], d["y"] + d["h"]), col, 2)
        cv2.putText(out, str(i + 1), (d["x"], max(d["y"] - 5, 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2, cv2.LINE_AA)
    return out
