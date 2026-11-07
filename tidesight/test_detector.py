"""
TideSight - Step 1: test a zero-shot fish detector on ONE image or ONE video frame.

Zero-shot means no training: you describe what to find in words ("fish")
and the model draws boxes around anything that matches.

Model: Grounding DINO (tiny), Apache 2.0 licence. This is the same model
VIAME uses in its detector_huggingface_zeroshot pipeline.

Usage:
    python test_detector.py photo.jpg
    python test_detector.py video.mp4 --time 180       # frame at 3:00
    python test_detector.py photo.jpg --prompt "fish. crab." --threshold 0.25

Output:
    <name>_detections.jpg  - the image with boxes drawn on it
    a printed list of every box, its label and its confidence
"""

import argparse
import os
import sys

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # Mac: run unsupported steps on CPU

import cv2
import torch
from PIL import Image
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

MODEL_ID = "IDEA-Research/grounding-dino-tiny"
VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".m4v")


def load_image(path, time_s):
    """Return a PIL image from a photo, or from a video at time_s seconds."""
    if path.lower().endswith(VIDEO_EXTS):
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            sys.exit(f"Could not open video: {path}")
        cap.set(cv2.CAP_PROP_POS_MSEC, time_s * 1000)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            sys.exit(f"Could not read a frame at {time_s} s. Is the video that long?")
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    return Image.open(path).convert("RGB")


def detect(image, prompt, threshold, device):
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(MODEL_ID).to(device)

    inputs = processor(images=image, text=prompt, return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs)

    sizes = [image.size[::-1]]  # (height, width)
    # The argument name changed between transformers versions; try both.
    try:
        result = processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, threshold=threshold,
            text_threshold=threshold, target_sizes=sizes)[0]
    except TypeError:
        result = processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, box_threshold=threshold,
            text_threshold=threshold, target_sizes=sizes)[0]

    labels = result.get("text_labels", result["labels"])
    return [
        (str(label), float(score), [int(round(v)) for v in box.tolist()])
        for label, score, box in zip(labels, result["scores"], result["boxes"])
    ]


def draw(image, detections, out_path):
    canvas = cv2.cvtColor(__import__("numpy").array(image), cv2.COLOR_RGB2BGR)
    for label, score, (x1, y1, x2, y2) in detections:
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 220, 255), 2)
        cv2.putText(canvas, f"{label} {score:.2f}", (x1, max(15, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 255), 2)
    cv2.imwrite(out_path, canvas)


def main():
    ap = argparse.ArgumentParser(description="Test a zero-shot fish detector.")
    ap.add_argument("path", help="photo or video file")
    ap.add_argument("--time", type=float, default=60.0,
                    help="seconds into the video to grab (videos only)")
    ap.add_argument("--prompt", default="fish.",
                    help='what to look for, lower case, each ending in "." e.g. "fish. crab."')
    ap.add_argument("--threshold", type=float, default=0.25,
                    help="minimum confidence to keep a box (0 to 1)")
    ap.add_argument("--cpu", action="store_true",
                    help="force CPU (use if the Mac GPU gives an error)")
    args = ap.parse_args()

    if args.cpu:
        device = "cpu"
    elif torch.cuda.is_available():
        device = "cuda"
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        device = "mps"   # Apple Silicon GPU
    else:
        device = "cpu"
    print(f"Running on: {device}")

    image = load_image(args.path, args.time)
    detections = detect(image, args.prompt, args.threshold, device)

    base = os.path.splitext(os.path.basename(args.path))[0]
    out_path = f"{base}_detections.jpg"
    draw(image, detections, out_path)

    print(f"\nFound {len(detections)} box(es) with confidence >= {args.threshold}:")
    for label, score, box in sorted(detections, key=lambda d: -d[1]):
        print(f"  {label:<10} {score:.2f}  box(x1,y1,x2,y2)={box}")
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
