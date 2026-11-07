# TideSight

## Fish counter app (Streamlit, no AI install needed)

Local web app for counting fish in dark GoPro footage. Nothing is uploaded.

```
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

1. Copy videos (mp4, mov, avi, m4v) into the `videos/` folder, then pick one in the app.
2. Trim, enhance, run detection (Motion by default), review each sampled frame, then build the report.
3. Results go to `outputs/<video name>/` (frames, screenshots, fish.csv, frames.csv, summary.csv).

Optional YOLO-Fish (AI): put these in `models/`:
- `yolo-fish-2.cfg` from https://github.com/tamim662/YOLO-Fish/tree/main/models
- `merge_yolo-fish-2.weights` from the "merged dataset" Google Drive link in that repo's README

Licence note: YOLO-Fish is GPL-3.0. This repo is MIT and does not include YOLO-Fish code, config or weights (weights are git-ignored), so MIT is fine. If you ever commit those files or copy its code, the combined project must be released under GPL-3.0.

The older Grounding-DINO scripts (`run_tidesight.py`, `test_detector.py`, `validate.py`, `config.yaml`) are not used by the app; they need `pip install -r requirements-legacy.txt`.

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
