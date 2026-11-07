"""Fish video reviewer. Run:  python app.py   ->  http://127.0.0.1:8000  (local only)"""
import hashlib
import json
import re
import shutil
import subprocess
import threading
import traceback
from pathlib import Path

import cv2
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import detector

ROOT = Path(__file__).parent
UPLOADS = ROOT / "uploads"
UPLOADS.mkdir(exist_ok=True)
BROWSER_EXTS = {".mp4", ".m4v", ".mov"}

app = FastAPI()
JOBS = {}  # key -> status dict


def vdir(vid):
    if not re.fullmatch(r"[0-9a-f]{16}", vid):
        raise HTTPException(400, "bad id")
    return UPLOADS / vid


def original_path(d):
    for p in d.glob("original.*"):
        return p
    raise HTTPException(404, "video not found")


def probe_codec(path):
    import imageio_ffmpeg
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Video:\s*(\w+)", r.stderr)
    return m.group(1).lower() if m else ""


def make_playable(d, orig, job):
    """Browser-friendly H.264 copy if the original isn't already H.264 in mp4/mov."""
    if (d / "playable.mp4").exists():
        job["playable"] = "playable.mp4"
        return
    if orig.suffix.lower() in BROWSER_EXTS and probe_codec(orig) == "h264":
        job["playable"] = orig.name
        return
    job["converting"] = True
    import imageio_ffmpeg
    tmp = d / "playable.tmp.mp4"
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(orig), "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(tmp)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:  # retry without audio (some GoPro audio tracks fail)
        cmd = cmd[:cmd.index("-c:a")] + ["-an"] + cmd[cmd.index("-movflags"):]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("Could not convert the video to a format the browser can play.")
    tmp.rename(d / "playable.mp4")
    job["playable"] = "playable.mp4"
    job["converting"] = False


def analyse(key, d, orig, model, sample_fps):
    job = JOBS[key]
    out = d / f"results_{model}_{sample_fps:g}.json"
    try:
        cap = cv2.VideoCapture(str(orig))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = nframes / fps
        total = int(duration * sample_fps) + 1
        job.update(total=total, done=0)
        conv_err = []
        t = threading.Thread(target=lambda: _safe(make_playable, conv_err, d, orig, job))
        t.start()
        job["stage"] = "loading"
        det = detector.get_detector(model, progress=lambda a, b: job.update(stage="downloading" if a < b else "loading", dl=a / b))
        job["stage"] = "analysing"
        samples, next_i, fi = [], 0, 0
        step = fps / sample_fps
        while True:
            target = round(next_i * step)
            if target >= nframes:
                break
            while fi < target:
                if not cap.grab():
                    break
                fi += 1
            ok, frame = cap.read()
            if not ok:
                break
            fi += 1
            boxes = [[b[0] / w, b[1] / h, b[2] / w, b[3] / h, round(b[4], 4)] for b in det.detect(frame)]
            samples.append({"t": round(target / fps, 3), "frame": target, "boxes": boxes})
            next_i += 1
            job["done"] = next_i
        cap.release()
        t.join()
        if conv_err:
            raise conv_err[0]
        res = {"model": model, "sample_fps": sample_fps, "min_conf": detector.MIN_CONF, "duration": duration,
               "fps": fps, "frames": nframes, "width": w, "height": h, "samples": samples, "playable": job["playable"]}
        out.write_text(json.dumps(res))
        job.update(stage="done", done=len(samples), total=len(samples))
    except Exception as e:
        traceback.print_exc()
        job.update(stage="error", error=friendly(e))


def _safe(fn, errs, *a):
    try:
        fn(*a)
    except Exception as e:
        errs.append(e)


def friendly(e):
    s = str(e)
    if "No space left" in s or "out of space" in s:
        return "The computer's disk is full. Free some space and try again."
    if "urlopen" in s.lower() or "CERTIFICATE" in s:
        return "Couldn't download the fish detector. Check the internet connection and try again."
    return s or e.__class__.__name__


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), model: str = Form("nano"), sample_fps: float = Form(2.0)):
    if model not in detector.MODELS:
        raise HTTPException(400, "unknown model")
    sample_fps = max(0.1, min(float(sample_fps), 30.0))
    tmpdir = UPLOADS / "_incoming"
    tmpdir.mkdir(exist_ok=True)
    tmp = tmpdir / (hashlib.md5(file.filename.encode()).hexdigest() + ".part")
    sha = hashlib.sha256()
    with tmp.open("wb") as f:
        while chunk := await file.read(4 * 1024 * 1024):
            sha.update(chunk)
            f.write(chunk)
    vid = sha.hexdigest()[:16]
    d = UPLOADS / vid
    d.mkdir(exist_ok=True)
    ext = Path(file.filename).suffix.lower() or ".mp4"
    if not list(d.glob("original.*")):
        shutil.move(str(tmp), d / f"original{ext}")
        (d / "name.txt").write_text(file.filename)
    else:
        tmp.unlink()
    orig = original_path(d)
    key = f"{vid}_{model}_{sample_fps:g}"
    cached = d / f"results_{model}_{sample_fps:g}.json"
    if cached.exists():
        JOBS[key] = {"stage": "done", "cached": True}
    elif JOBS.get(key, {}).get("stage") not in ("loading", "downloading", "analysing"):
        JOBS[key] = {"stage": "loading", "done": 0, "total": 0}
        threading.Thread(target=analyse, args=(key, d, orig, model, sample_fps), daemon=True).start()
    return {"id": vid, "key": key, "model": model, "sample_fps": sample_fps}


@app.get("/api/status/{vid}")
def status(vid: str, model: str = "nano", sample_fps: float = 2.0):
    d = vdir(vid)
    key = f"{vid}_{model}_{sample_fps:g}"
    if (d / f"results_{model}_{sample_fps:g}.json").exists():
        return {"stage": "done"}
    return JOBS.get(key, {"stage": "unknown"})


@app.get("/api/results/{vid}")
def results(vid: str, model: str = "nano", sample_fps: float = 2.0):
    p = vdir(vid) / f"results_{model}_{sample_fps:g}.json"
    if not p.exists():
        raise HTTPException(404, "not ready")
    data = json.loads(p.read_text())
    n = vdir(vid) / "name.txt"
    data["name"] = n.read_text() if n.exists() else ""
    return JSONResponse(data)


@app.get("/api/models")
def models():
    return {k: v["label"] for k, v in detector.MODELS.items() if k != "yolo"}


@app.get("/video/{vid}/{name}")
def video(vid: str, name: str):
    p = vdir(vid) / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
