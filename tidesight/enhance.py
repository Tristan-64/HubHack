"""Brightness / contrast / gamma."""
import cv2
import numpy as np


def enhance(frame, brightness=0, contrast=1.0, gamma=1.0):
    """brightness -100..100, contrast 0.5..3, gamma 0.3..3 (>1 brightens shadows)."""
    out = cv2.convertScaleAbs(frame, alpha=contrast, beta=brightness)
    if abs(gamma - 1.0) > 1e-3:
        lut = np.array([255 * (i / 255) ** (1.0 / gamma) for i in range(256)], dtype=np.uint8)
        out = cv2.LUT(out, lut)
    return out


# ---------------------------------------------------------------------------
# enhance_frame: the ONE function used for the preview, before/after view and
# for every frame that goes into the fish detector. Defaults change nothing.
# ---------------------------------------------------------------------------
import hashlib
import json

DEFAULTS = {"denoise": 0.0, "brightness": 0.0, "contrast": 1.0, "gamma": 1.0, "clahe": 0.0,
            "saturation": 1.0, "warmth": 0.0, "sharpen": 0.0}
LIMITS = {"denoise": (0, 20), "brightness": (-100, 100), "contrast": (0.5, 3.0), "gamma": (0.3, 3.0), "clahe": (0, 10),
          "saturation": (0, 3.0), "warmth": (-50, 50), "sharpen": (0, 3.0)}


def normalize_cfg(cfg=None):
    out = dict(DEFAULTS)
    for k, v in (cfg or {}).items():
        if k in DEFAULTS:
            try:
                lo, hi = LIMITS[k]
                out[k] = round(min(max(float(v), lo), hi), 3)
            except (TypeError, ValueError):
                pass
    return out


def is_default(cfg):
    return normalize_cfg(cfg) == DEFAULTS


def settings_id(cfg):
    """'' for the original (no changes), otherwise a short stable hash of the settings."""
    c = normalize_cfg(cfg)
    if c == DEFAULTS:
        return ""
    return hashlib.sha1(json.dumps(c, sort_keys=True).encode()).hexdigest()[:10]


def enhance_frame(frame_bgr, cfg=None):
    c = normalize_cfg(cfg)
    if c == DEFAULTS:
        return frame_bgr
    img = frame_bgr
    if c["denoise"] > 0:
        img = cv2.fastNlMeansDenoisingColored(img, None, c["denoise"], c["denoise"], 7, 21)
    if c["brightness"] != 0 or c["contrast"] != 1.0:
        img = cv2.convertScaleAbs(img, alpha=c["contrast"], beta=c["brightness"])
    if c["gamma"] != 1.0:
        lut = np.array([255 * (i / 255) ** (1.0 / c["gamma"]) for i in range(256)], dtype=np.uint8)
        img = cv2.LUT(img, lut)
    if c["clahe"] > 0:
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        lab[:, :, 0] = cv2.createCLAHE(clipLimit=c["clahe"], tileGridSize=(8, 8)).apply(lab[:, :, 0])
        img = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    if c["saturation"] != 1.0:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * c["saturation"], 0, 255)
        img = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    if c["warmth"] != 0:
        f = c["warmth"] / 100.0
        b, g, r = cv2.split(img.astype(np.float32))
        img = cv2.merge([np.clip(b * (1 - f), 0, 255), g, np.clip(r * (1 + f), 0, 255)]).astype(np.uint8)
    if c["sharpen"] > 0:
        blur = cv2.GaussianBlur(img, (0, 0), 1.5)
        img = cv2.addWeighted(img, 1 + c["sharpen"], blur, -c["sharpen"], 0)
    return img


def describe_cfg(cfg):
    """Plain-language list of the settings that differ from the defaults."""
    c = normalize_cfg(cfg)
    names = {"denoise": "Denoise", "brightness": "Brightness", "contrast": "Contrast", "gamma": "Gamma",
             "clahe": "Local contrast", "saturation": "Colour strength", "warmth": "Warmth", "sharpen": "Sharpen"}
    parts = [f"{names[k]} {c[k]:g}" for k in DEFAULTS if c[k] != DEFAULTS[k]]
    return ", ".join(parts) if parts else "Original (no changes)"
