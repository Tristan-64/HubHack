"""Optional AI species suggestions with BioCLIP 2 (pybioclip). Imported only when used."""
import csv
import importlib.util
from pathlib import Path

from PIL import Image

CSV = Path(__file__).parent / "species.csv"
GENERIC = "Actinopterygii"  # ray-finned fish: "a fish, but probably not one of ours"
MIN_BOX_PX = 40
_clf = {"labels": None, "obj": None}


def available():
    return importlib.util.find_spec("bioclip") is not None


def load_species():
    with open(CSV, newline="", encoding="utf-8") as f:
        return [(r["common_name"].strip(), r["scientific_name"].strip()) for r in csv.DictReader(f) if r.get("scientific_name")]


def labels():
    return [sci for _, sci in load_species()] + [GENERIC]


def _classifier():
    labs = labels()
    if _clf["labels"] != labs:
        from bioclip import CustomLabelsClassifier  # first use downloads BioCLIP 2 (needs internet)
        device = "cpu"
        try:
            import torch
            if torch.backends.mps.is_available():
                device = "mps"
            elif torch.cuda.is_available():
                device = "cuda"
        except Exception:
            pass
        try:
            obj = CustomLabelsClassifier(labs, device=device)
        except Exception:
            if device == "cpu":
                raise
            obj = CustomLabelsClassifier(labs, device="cpu")
        _clf.update(labels=labs, obj=obj)
    return _clf["obj"]


def crop(frame_bgr, box, w, h, margin=0.12):
    """box is normalised [x1,y1,x2,y2,...]. Returns a PIL crop with a small margin, or None if too small."""
    x1, y1, x2, y2 = box[0] * w, box[1] * h, box[2] * w, box[3] * h
    if min(x2 - x1, y2 - y1) < MIN_BOX_PX:
        return None
    mx, my = (x2 - x1) * margin, (y2 - y1) * margin
    a, b = max(0, int(x1 - mx)), max(0, int(y1 - my))
    c, d = min(w, int(x2 + mx)), min(h, int(y2 + my))
    return Image.fromarray(frame_bgr[b:d, a:c, :: -1])


def classify(crops, k=3):
    """crops: list of PIL images -> list of [[scientific_name, score], ...] (top k each)."""
    if not crops:
        return []
    preds = _classifier().predict(crops, k=k, batch_size=8)
    out = {}
    for p in preds:  # flat list of {file_name: index-as-string, classification, score}
        out.setdefault(p["file_name"], []).append([p["classification"], round(float(p["score"]), 4)])
    return [out[str(i)] for i in range(len(crops))]
