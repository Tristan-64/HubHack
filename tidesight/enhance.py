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
