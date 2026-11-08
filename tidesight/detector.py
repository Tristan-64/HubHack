"""Community Fish Detector: weight download, loading, running. One class: fish."""
import threading
import urllib.request
from pathlib import Path

import numpy as np

MODEL_DIR = Path(__file__).parent / "models"
BASE = "https://github.com/filippovarini/community-fish-detector/releases/download/"
MODELS = {
    "nano": {"file": "cfd-rf-detr-nano-640-2026.02.02.cp-011.20260706-release.pth",
             "url": BASE + "2026.07.06-release/cfd-rf-detr-nano-640-2026.02.02.cp-011.20260706-release.pth",
             "label": "RF-DETR Nano (fastest)"},
    "small": {"file": "cfd-rf-detr-small-1024-2026.06.06.cp-016.20260706-release.pth",
              "url": BASE + "2026.07.06-release/cfd-rf-detr-small-1024-2026.06.06.cp-016.20260706-release.pth",
              "label": "RF-DETR Small (more accurate, slower)"},
    "yolo": {"file": "cfd-yolov12x-1.00.pt",
             "url": BASE + "cfd-1.00-yolov12x/cfd-yolov12x-1.00.pt",
             "label": "YOLOv12x (fallback, needs Ultralytics)"},
}
MIN_CONF = 0.2
_loaded = {}
_lock = threading.Lock()


# Download the model file once into models/ (needs internet only that first time).
def ensure_weights(name, progress=None):
    spec = MODELS[name]
    MODEL_DIR.mkdir(exist_ok=True)
    dest = MODEL_DIR / spec["file"]
    if dest.exists():
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")

    import ssl
    try:  # python.org builds of Python on macOS have no root certificates; certifi fixes that
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    with urllib.request.urlopen(spec["url"], context=ctx) as r, open(tmp, "wb") as f:
        total, got = int(r.headers.get("Content-Length") or 0), 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            got += len(chunk)
            if progress and total:
                progress(got, total)
    tmp.rename(dest)
    return dest


# Prefer the Mac GPU (mps), then CUDA, else CPU.
def _device():
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


class Detector:
    def __init__(self, name="nano", progress=None):
        self.name = name
        path = ensure_weights(name, progress)
        self.kind = "yolo" if name == "yolo" else "rfdetr"
        self.device = _device()
        if self.kind == "rfdetr":
            from rfdetr import from_checkpoint
            self.model = from_checkpoint(str(path))
        else:
            from ultralytics import YOLO
            self.model = YOLO(str(path))

    def detect(self, frame_bgr, conf=MIN_CONF):
        """Returns [[x1,y1,x2,y2,conf], ...] in pixels."""
        with _lock:
            return self._detect(frame_bgr, conf)

    def _detect(self, frame_bgr, conf):
        h, w = frame_bgr.shape[:2]
        if self.kind == "rfdetr":
            from PIL import Image
            img = Image.fromarray(frame_bgr[:, :, ::-1])
            det = self.model.predict(img, threshold=float(conf))
            xyxy, cs = det.xyxy, det.confidence
        else:
            r = self.model.predict(frame_bgr, conf=float(conf), imgsz=1024, verbose=False,
                                   device=self.device if self.device != "cuda" else 0)[0]
            xyxy, cs = r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()
        out = []
        for (x1, y1, x2, y2), c in zip(np.asarray(xyxy).reshape(-1, 4), np.asarray(cs).reshape(-1)):
            out.append([max(0.0, float(x1)), max(0.0, float(y1)), min(float(w), float(x2)), min(float(h), float(y2)), float(c)])
        return out


# One loaded detector per model name, reused across jobs.
def get_detector(name, progress=None):
    if name not in _loaded:
        _loaded[name] = Detector(name, progress)
    return _loaded[name]
