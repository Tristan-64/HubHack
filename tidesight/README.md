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
- **Video filters (chosen before detection):** after you add a video, the page shows it with a slide-out filters drawer on the right (open/close with the 🎛 Filters button or tab, ✕ or Esc) holding manual sliders (brightness, contrast, gamma, local contrast, denoise, sharpen, colour strength, warmth). Defaults change nothing and "Reset" restores them. Moving a slider changes the playing video straight away as a quick, approximate preview (a browser filter; it cannot show local contrast or denoise, and Chrome is smoother than Safari). "Start detection" first renders the exact filtered video with `enhance_frame` (`enhance.py`), then runs the fish detector on those same frames, so what you review is what the detector saw. Results and filtered videos are saved per settings combination (`results_<model>_<rate>_<id>.json`, `filtered_<id>.mp4`); "Saved results" switches instantly. Changing the sliders afterwards and clicking "Re-run detection" makes a new run. The line under the summary compares the original with the current settings, and "Before / after" shows the paused frame with and without filters, each with its own detections. Denoise is slow on long videos. The filtered video has no sound.
- **Checking and fixing boxes (names, move, resize, delete):** every box has a name. The AI only ever says "fish"; a person can type any other name. Click a box to select it, then:
  - **Rename:** type in the Name box (suggestions are only names already used in this video) and press Enter.
  - **Move / resize:** drag the selected box, or drag one of its white handles. Dragging from a box that is *not* selected draws a new box instead. Arrow keys nudge the selected box (Shift = bigger steps).
  - **Draw a new box:** drag on an empty part of the picture (the video pauses). It belongs to the nearest checked picture.
  - **Delete:** "Delete box" removes your own box completely. "Delete AI box" marks an AI box as *rejected* (dashed grey): it stays in the report as rejected and can be brought back with "Restore AI box". "Undo" (or Ctrl/Cmd+Z) undoes the last change; "Reset to the AI's box" puts an edited AI box back as the AI drew it.
  - Edited AI boxes stay `source=model` and are marked ✎ and `edited=yes`; the original box and name are kept. Moving a box back to its original place and name makes it unedited again.
  - Every box has a tick under the timeline (click to jump to it); the Boxes list has a Name column and a "Boxes I edited" filter. Shortcuts (Delete, arrows, Esc, undo) never fire while you are typing in the Name box.
  - Everything saves by itself (`uploads/<id>/review_*.json`) and is still there after a page refresh.
  - **Save report (CSV)** writes one file, `fish_detections.csv` (one row per box: who made it (`auto` or `me`), species name, edited, original label and box for edited AI boxes, confidence, grid cell), plus the `review_state.json` save file, to `outputs/<video name>/`. **Update the outlined video** writes `outlined.mp4` with the names on the boxes (AI boxes also show confidence; edited AI boxes get a small amber marker). Boxes below the confidence slider are only included if you edited them; rejected AI boxes are left out.
- **Side panels (they push the video, they never cover it):** the left panel is *Fish lookup*, the right panel is the *Video filters*. Each has a « / » button to minimise it to a thin rail (click the rail to open it again). The video gets bigger when panels are closed and smaller when they are open.
- **Fish lookup (left panel):** click a fish box on the video, press **Search fish**, type any of the measurements you know (MBl, BEl, VEp, REs, OGp, RMl, BLs, PFv, PFs, CPt; capital-I spellings like MBI also work; leave the others blank), then **Find the 5 closest fish**. It compares your numbers with `fishmorph_clean.csv` (the FISHMORPH trait table, kept in the tidesight folder) and lists the 5 closest species with a difference score (lower = closer). Only the numbers you type are compared (MBl and BEl on a log scale; every trait is scaled by how much it varies across all fish; a fish must have at least half of your numbers). "Use as this box's name" copies a species into the box's name. Each of the 5 closest fish shows its picture (from the `image_url` columns of `fishmorph_clean.csv`) with the photographer's credit, licence and a link to the source page; fish with no picture get a plain "No picture available" box. The matching is local; the pictures are loaded by your browser from iNaturalist/Wikipedia, so they need internet (offline you still see the details). Restart the app after you change the CSV. Typed numbers are remembered per box until you refresh the page.
- **Fish count and grid:** the count under the video ("Fish in this picture: N (x found automatically + y added by you)") goes up when you add a box and down when you delete one (undo and restore move it back). It counts fish in the picture on screen (not rejected, and confident or edited). In the Filters drawer, "Show a grid over the video" draws an A1, B2… grid (rows and columns adjustable) on the video, also during the filter step. With the grid on, the Boxes list shows each box's cell, and "Save report" adds a `grid_cell` column to `fish_detections.csv`.
- **Tests:** `source .venv/bin/activate && python selftest.py && python component_test.py` (the second one needs Google Chrome).
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


## Clean-up round (Nov 2026)
- Pictures checked per second moves in 0.5 steps (min 0.5). Fish lookup: MBl, BEl, CPt step by 1; the other traits by 0.1.
- Removed: BioCLIP species suggestions, the fish-moments list, previous/next fish, the summary box above the video, the 🐟 badge and the detail line under the count.
- Boxes list filters: show 50/100/all, minimum confidence, time range (m:ss), sort by time or confidence. The Who column says Auto or Me.
- Before / after: Still pictures or Video (two videos that play together, controlled by the normal play/scrub/step buttons) with a Show boxes switch for both.
