# Fish footage reviewer

A local web page for reviewing underwater survey video. You add a video, the **Community Fish Detector** marks the fish, and you review the original video with every detection and its confidence drawn on top, a shaded "fish timeline", a confidence slider and a list of fish moments. Nothing leaves your computer (the server only listens on 127.0.0.1).

## Setup (once)
```
cd tidesight
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
(PyTorch is included via `rfdetr`, so this is a big download, roughly 2 GB.)

## Run
```
source .venv/bin/activate
python app.py
```
Open http://127.0.0.1:8000. The first run downloads the model (about 120 MB) into `models/`.

## Notes
- Uploads are saved in `uploads/<id>/`, with results as `results_<model>_<rate>.json` beside the video. Uploading the same video again reuses the saved results.
- Videos the browser can't play (for example GoPro HEVC/H.265) are converted to an H.264 copy with the ffmpeg bundled in `imageio-ffmpeg`.
- Uses the Mac GPU (mps) when available, otherwise CPU. The detector runs at confidence 0.2 and the slider filters the saved boxes.
- Model: Community Fish Detector, https://github.com/WildHackers/community-fish-detector (RF-DETR Nano by default, Small optional; code and weights Apache-licensed per that repo). The deprecated YOLOv12x version is AGPL and only supported as a manual fallback (`pip install ultralytics`, model key "yolo").
- **Species suggestions (optional AI):** `pip install -r requirements-ai.txt` (pybioclip, BioCLIP 2). The first use downloads the model (large) and needs internet. Use "Identify species (AI)" for the paused frame or the whole video. Fish are cropped and matched against the scientific names in `species.csv` (edit that file to change the list) plus the generic label "Actinopterygii". Results are saved in the results JSON. They are suggestions for a person to check. A fish is "Unknown" if the top score is under the cut-off slider (0.5), the box is under 40 px, or the top match is "Actinopterygii" (possibly not on the list). BioCLIP 2 is MIT-licensed code with its own model licence on Hugging Face (imageomics/bioclip-2).
- The earlier Streamlit prototype is kept as `streamlit_app.py` (deps in `requirements-streamlit.txt`); the older Grounding-DINO scripts need `requirements-legacy.txt`.

---

# Original TideSight pipeline (legacy)

Automated MeanCount for Coastal Action's fish video surveys, built for RBC HubHacks 2026 (Problem Statement 2).

TideSight follows Coastal Action's draft Fish Video Analysis Protocol step for step. It trims the video, takes a subsample every 60 seconds, counts the fish in each one-second window, and writes the same spreadsheet staff fill in by hand, plus a screenshot of every analysed frame. Anything the model is unsure about is flagged for a person instead of being counted ("when in doubt, don't count").

Everything runs locally on one computer with an NVIDIA GPU. No video or data leaves the machine.

## How it works

1. **Analysis window**: skip the first and last minute (sediment), analyse 15 minutes.
2. **Subsampling**: one point every 60 s, so 15 subsamples per video. Change `interval_s` to 15 for 60 subsamples.
3. **Counting**: at each point, check 5 frames across the one-second window and keep the highest single-frame count, so no fish is counted twice.
4. **Detector**: Grounding DINO (zero-shot, prompt `"fish."`). Boxes above `count_threshold` are counted; boxes between `review_threshold` and `count_threshold` are flagged for review.
5. **Outputs**: the MeanCount spreadsheet, screenshots, and a VIAME-CSV that opens in VIAME's DIVE app for review and future model training.
6. **Validation**: `validate.py` compares the AI's counts with a person's counts using the protocol's own QC rule (under 6% difference, 95% agreement).

All protocol numbers live in `config.yaml`, because the protocol is still a draft.

## Setup

Requires Python 3.10+. Runs on an NVIDIA GPU (Coastal Action's target: 12 GB), an Apple Silicon Mac (uses the built-in GPU), or plain CPU (slower, still fine for 15 subsamples).

```
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

If the Mac GPU gives an error, add `--cpu` to any command.

The first run downloads the detector model (about 700 MB). After that it runs offline.

## Usage

```
# 1. Test the detector on one photo or video frame
python test_detector.py photo.jpg
python test_detector.py video.mp4 --time 180

# 2. Run the full protocol on a video
python run_tidesight.py video.mp4 --video-id T1_STAT1

# Sediment took longer to settle? Start later (seconds):
python run_tidesight.py video.mp4 --video-id T1_STAT1 --skip-start 240

# Test the pipeline without a GPU or model (random boxes):
python run_tidesight.py video.mp4 --dry-run

# 3. Check accuracy against a person's counts
python validate.py outputs/T1_STAT1/meancount_sheet.csv human_counts.csv
```

`human_counts.csv` has two columns, `subsample,human_count`.

## Outputs

`outputs/<video_id>/`

| File | What it is |
|---|---|
| `meancount_sheet.csv` | One row per subsample: timestamp, fish count, flagged possible fish, notes, screenshot |
| `summary.json` | MeanCount, analysis window, settings used, processing time |
| `screenshots/` | Each subsample frame. Green = counted, orange = flagged for review |
| `detections_viame.csv` | Every box in VIAME-CSV format. Open it with the video in DIVE Desktop to review |
| `validation_report.csv` | Per-frame AI vs person comparison (after running `validate.py`) |

## Reviewing in VIAME DIVE

1. Install [DIVE Desktop](https://kitware.github.io/dive/Dive-Desktop).
2. Import the video and choose `detections_viame.csv` as the annotation file.
3. Filter to `possible_fish`, then confirm, relabel or delete each box, and export.

Corrected boxes become training data for a Nova Scotia fish detector (roadmap).

## Limitations

- The detector was not trained on Nova Scotia footage, so it will miss some fish and mistake some algae or sediment for fish. Use the validation report to measure this honestly.
- Species identification is not included yet; counted fish go to "Unknown/Unable to ID".
- Invertebrate counts, visibility categories and juvenile presence are still recorded by staff.

## Roadmap

- Species suggestions with BioCLIP 2 and an editable Nova Scotia species list
- Train a local detector (VIAME / RF-DETR) on staff-corrected boxes
- Motion check for camouflaged fish (stationary camera)
- Automatic visibility estimate from the 0.5 m marks on the visibility pole
- Expected-species alerts for invasive and warm-water arrivals

## Data

Coastal Action's survey video is not included in this repository. Contact Coastal Action for access.

## Licences

| Component | Licence |
|---|---|
| TideSight code | MIT |
| Grounding DINO (IDEA-Research/grounding-dino-tiny) | Apache 2.0 |
| Hugging Face Transformers | Apache 2.0 |
| VIAME / DIVE | BSD-style permissive (see their repositories) |
