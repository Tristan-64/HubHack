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
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import detector
import review
import species
from enhance import describe_cfg, enhance_frame, normalize_cfg, settings_id

ROOT = Path(__file__).parent
UPLOADS = ROOT / "uploads"
UPLOADS.mkdir(exist_ok=True)
BROWSER_EXTS = {".mp4", ".m4v", ".mov"}

app = FastAPI()
JOBS = {}  # key -> status dict


def parse_cfg(raw):
    try:
        return normalize_cfg(json.loads(raw)) if raw else normalize_cfg()
    except Exception:
        return normalize_cfg()


def rfile(d, model, fps, sid=""):
    return d / (f"results_{model}_{fps:g}.json" if not sid else f"results_{model}_{fps:g}_{sid}.json")


def jkey(vid, model, fps, sid="", extra=""):
    return f"{vid}_{model}_{fps:g}_{sid}{extra}"


def read_frame(orig, idx):
    cap = cv2.VideoCapture(str(orig))
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, idx))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise HTTPException(404, "could not read that frame")
    return frame


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


def ensure_filtered(job, d, orig, cfg):
    """Render the whole video through enhance_frame -> filtered_<id>.mp4 (what the detector will see)."""
    sid = settings_id(cfg)
    if not sid:
        return None
    out = d / f"filtered_{sid}.mp4"
    if out.exists():
        return out.name
    import imageio_ffmpeg
    cap = cv2.VideoCapture(str(orig))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError("Could not read the video.")
    h, w = frame.shape[:2]
    tmp = d / f"filtered_{sid}.tmp.mp4"
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps}",
           "-i", "-", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(tmp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    job.update(stage="rendering", done=0, total=total)
    n = 0
    try:
        while ok:
            proc.stdin.write(enhance_frame(frame, cfg).tobytes())
            n += 1
            job["done"] = n
            ok, frame = cap.read()
    finally:
        cap.release()
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError("Could not make the filtered video.")
    tmp.rename(out)
    return out.name


def render_only(key, d, orig, model, sample_fps, cfg):
    job = JOBS[key]
    try:
        name = ensure_filtered(job, d, orig, cfg)
        p = rfile(d, model, sample_fps, settings_id(cfg))
        with RES_LOCK:
            r = json.loads(p.read_text())
            r["filtered"] = name
            p.write_text(json.dumps(r))
        job.update(stage="done")
    except Exception as e:
        traceback.print_exc()
        job.update(stage="error", error=friendly(e))


PREP = {}


def prepare(vid, d, orig):
    PREP[vid] = {"stage": "converting"}
    try:
        job = {}
        make_playable(d, orig, job)
        PREP[vid] = {"stage": "ready", "playable": job["playable"]}
    except Exception as e:
        traceback.print_exc()
        PREP[vid] = {"stage": "error", "error": friendly(e)}


def analyse(key, d, orig, model, sample_fps, cfg):
    job = JOBS[key]
    sid = settings_id(cfg)
    out = rfile(d, model, sample_fps, sid)
    try:
        cap = cv2.VideoCapture(str(orig))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = nframes / fps
        total = int(duration * sample_fps) + 1
        cap.release()
        conv_err = []
        t = threading.Thread(target=lambda: _safe(make_playable, conv_err, d, orig, job))
        t.start()
        filtered = ensure_filtered(job, d, orig, cfg)  # exact filtered video (None = no filters)
        cap = cv2.VideoCapture(str(d / filtered if filtered else orig))
        job.update(total=total, done=0)
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
               "fps": fps, "frames": nframes, "width": w, "height": h, "settings": cfg, "filtered": filtered, "samples": samples, "playable": job["playable"]}
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
async def upload(file: UploadFile = File(...)):
    """Only saves the video and prepares a playable copy. Detection starts later, after the filters are chosen."""
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
    if PREP.get(vid, {}).get("stage") not in ("converting", "ready"):
        threading.Thread(target=prepare, args=(vid, d, original_path(d)), daemon=True).start()
    return {"id": vid}


@app.get("/api/prepare/{vid}")
def prepare_status(vid: str):
    d = vdir(vid)
    orig = original_path(d)
    if vid not in PREP:
        threading.Thread(target=prepare, args=(vid, d, orig), daemon=True).start()
        PREP[vid] = {"stage": "converting"}
    st = dict(PREP[vid])
    if st["stage"] == "ready":
        cap = cv2.VideoCapture(str(orig))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        st.update(duration=n / fps, fps=fps, width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        cap.release()
        nm = d / "name.txt"
        st["name"] = nm.read_text() if nm.exists() else ""
    return st


@app.get("/api/status/{vid}")
def status(vid: str, model: str = "nano", sample_fps: float = 2.0, cfg: str = ""):
    d = vdir(vid)
    sid = settings_id(parse_cfg(cfg))
    key = jkey(vid, model, sample_fps, sid)
    if JOBS.get(key, {}).get("stage") in ("rendering", "loading", "downloading", "analysing"):
        return JOBS[key]
    if rfile(d, model, sample_fps, sid).exists():
        return {"stage": "done"}
    return JOBS.get(key, {"stage": "unknown"})


@app.get("/api/results/{vid}")
def results(vid: str, model: str = "nano", sample_fps: float = 2.0, cfg: str = ""):
    p = rfile(vdir(vid), model, sample_fps, settings_id(parse_cfg(cfg)))
    if not p.exists():
        raise HTTPException(404, "not ready")
    data = json.loads(p.read_text())
    data.setdefault("settings", normalize_cfg())
    data["settings_text"] = describe_cfg(data["settings"])
    n = vdir(vid) / "name.txt"
    data["name"] = n.read_text() if n.exists() else ""
    return JSONResponse(data)


RES_LOCK = threading.Lock()


def run_species(key, d, orig, model, sample_fps, conf, only, cfg):
    """Classify confident boxes. only = sample index (this frame) or None (whole video)."""
    job = JOBS[key]
    path = rfile(d, model, sample_fps, settings_id(cfg))
    try:
        res = json.loads(path.read_text())
        S = res["samples"]
        todo = []
        for i, s in enumerate(S):
            if only is not None and i != only:
                continue
            need = [j for j, b in enumerate(s["boxes"]) if b[4] >= conf and str(j) not in s.get("sp", {})]
            if need:
                todo.append((i, need))
        job.update(stage="loading", done=0, total=len(todo))
        if todo:
            species._classifier()
        job["stage"] = "analysing"
        fname = res.get("filtered")
        use_filtered = bool(fname) and (d / fname).exists()
        cap = cv2.VideoCapture(str(d / fname if use_filtered else orig))
        w, h = res["width"], res["height"]
        fi = 0
        for n, (i, need) in enumerate(todo):
            target = S[i]["frame"]
            if only is not None or target < fi:  # jump straight to the frame
                cap.set(cv2.CAP_PROP_POS_FRAMES, target)
                fi = target
            while fi < target:
                if not cap.grab():
                    break
                fi += 1
            ok, frame = cap.read()
            fi += 1
            if ok:
                if not use_filtered:
                    frame = enhance_frame(frame, cfg)
                crops = {j: species.crop(frame, S[i]["boxes"][j], w, h) for j in need}
                valid = [j for j, c in crops.items() if c is not None]
                preds = species.classify([crops[j] for j in valid])
                sp = S[i].setdefault("sp", {})
                for j in need:
                    sp[str(j)] = preds[valid.index(j)] if j in valid else []  # [] = too small to tell
            job["done"] = n + 1
        cap.release()
        with RES_LOCK:
            fresh = json.loads(path.read_text())
            fresh["species_conf"] = min(conf, fresh.get("species_conf", 1.0))
            for i, s in enumerate(S):
                if "sp" in s:
                    fresh["samples"][i].setdefault("sp", {}).update(s["sp"])
            path.write_text(json.dumps(fresh))
        job["stage"] = "done"
    except Exception as e:
        traceback.print_exc()
        msg = str(e)
        job.update(stage="error", error="Couldn't download or run the species model. It needs internet the first time."
                   if any(x in msg for x in ("urlopen", "Connection", "resolve", "CERTIFICATE", "offline", "huggingface"))
                   else friendly(e))


@app.get("/api/species/info")
def species_info():
    return {"available": species.available(), "species": [{"common": c, "scientific": s} for c, s in species.load_species()],
            "generic": species.GENERIC, "min_box_px": species.MIN_BOX_PX}


@app.post("/api/species/{vid}")
def species_run(vid: str, model: str = "nano", sample_fps: float = 2.0, conf: float = 0.6, sample: int = -1, cfg: str = ""):
    cfg = parse_cfg(cfg)
    if not species.available():
        raise HTTPException(400, "Species suggestions need an extra install: pip install -r requirements-ai.txt")
    d = vdir(vid)
    key = jkey(vid, model, sample_fps, settings_id(cfg), "_species")
    if JOBS.get(key, {}).get("stage") in ("loading", "analysing"):
        return {"started": False}
    JOBS[key] = {"stage": "loading", "done": 0, "total": 0}
    threading.Thread(target=run_species, args=(key, d, original_path(d), model, sample_fps, conf, None if sample < 0 else sample, cfg),
                     daemon=True).start()
    return {"started": True}


@app.get("/api/species_status/{vid}")
def species_status(vid: str, model: str = "nano", sample_fps: float = 2.0, cfg: str = ""):
    return JOBS.get(jkey(vid, model, sample_fps, settings_id(parse_cfg(cfg)), "_species"), {"stage": "idle"})


@app.post("/api/analyse/{vid}")
def analyse_again(vid: str, model: str = "nano", sample_fps: float = 2.0, cfg: str = ""):
    """Run (or reuse) detection with these filter settings."""
    cfg = parse_cfg(cfg)
    d = vdir(vid)
    sid = settings_id(cfg)
    key = jkey(vid, model, sample_fps, sid)
    if JOBS.get(key, {}).get("stage") in ("loading", "downloading", "analysing", "rendering"):
        return {"cached": False, "started": False}
    p = rfile(d, model, sample_fps, sid)
    if p.exists():
        r = json.loads(p.read_text())
        if not sid or (r.get("filtered") and (d / r["filtered"]).exists()):
            return {"cached": True}
        JOBS[key] = {"stage": "rendering", "done": 0, "total": 0}  # older run: make its filtered video
        threading.Thread(target=render_only, args=(key, d, original_path(d), model, sample_fps, cfg), daemon=True).start()
        return {"cached": False, "started": True}
    JOBS[key] = {"stage": "loading", "done": 0, "total": 0}
    threading.Thread(target=analyse, args=(key, d, original_path(d), model, sample_fps, cfg), daemon=True).start()
    return {"cached": False, "started": True}


@app.get("/api/runs/{vid}")
def runs(vid: str):
    out = []
    for p in sorted(vdir(vid).glob("results_*.json")):
        r = json.loads(p.read_text())
        cfg = normalize_cfg(r.get("settings"))
        out.append({"model": r["model"], "sample_fps": r["sample_fps"], "cfg": cfg, "sid": settings_id(cfg),
                    "text": describe_cfg(cfg)})
    return out


def _jpeg(img, maxw=None):
    if maxw and img.shape[1] > maxw:
        img = cv2.resize(img, (maxw, int(img.shape[0] * maxw / img.shape[1])), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return buf.tobytes()


@app.get("/api/compare/{vid}")
def compare(vid: str, t: float = 0.0, model: str = "nano", cfg: str = ""):
    """Original and enhanced version of one frame, each with its own detections."""
    import base64
    cfg = parse_cfg(cfg)
    orig = original_path(vdir(vid))
    cap = cv2.VideoCapture(str(orig))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()
    frame = read_frame(orig, round(t * fps))
    h, w = frame.shape[:2]
    det = detector.get_detector(model)
    out = {"width": w, "height": h}
    for name, img in (("original", frame), ("enhanced", enhance_frame(frame, cfg))):
        boxes = [[b[0] / w, b[1] / h, b[2] / w, b[3] / h, round(b[4], 4)] for b in det.detect(img)]
        out[name] = {"img": "data:image/jpeg;base64," + base64.b64encode(_jpeg(img, 1000)).decode(), "boxes": boxes}
    return out


# ---------------------------------------------------------------- reviewer edits
OUTPUTS = ROOT / "outputs"


def sfile(d, model, fps, sid=""):
    return d / (f"review_{model}_{fps:g}.json" if not sid else f"review_{model}_{fps:g}_{sid}.json")


def load_results(d, model, fps, sid):
    p = rfile(d, model, fps, sid)
    if not p.exists():
        raise HTTPException(404, "results not ready")
    return json.loads(p.read_text())


def outdir(d, vid):
    nm = d / "name.txt"
    stem = re.sub(r"[^\w.-]+", "_", Path(nm.read_text()).stem if nm.exists() else vid) or vid
    return OUTPUTS / stem


@app.get("/api/review/{vid}")
def review_get(vid: str, model: str = "nano", sample_fps: float = 2.0, cfg: str = ""):
    d = vdir(vid)
    return review.load_state(sfile(d, model, sample_fps, settings_id(parse_cfg(cfg))))


@app.put("/api/review/{vid}")
async def review_put(vid: str, request: Request, model: str = "nano", sample_fps: float = 2.0, cfg: str = ""):
    d = vdir(vid)
    body = await request.json()
    review.save_state(sfile(d, model, sample_fps, settings_id(parse_cfg(cfg))), body)
    return {"saved": True}


@app.post("/api/export/{vid}")
def export_reports(vid: str, model: str = "nano", sample_fps: float = 2.0, cfg: str = "", thr: float = 0.6):
    d = vdir(vid)
    c = parse_cfg(cfg)
    sid = settings_id(c)
    res = load_results(d, model, sample_fps, sid)
    st = review.load_state(sfile(d, model, sample_fps, sid))
    files, summary = review.write_exports(outdir(d, vid), original_name(d, vid), res, st, thr, f"{model}; {describe_cfg(c)}")
    return {"folder": str(outdir(d, vid)), "files": files, "summary": summary}


def original_name(d, vid):
    nm = d / "name.txt"
    return nm.read_text() if nm.exists() else vid


def run_outline(key, d, vid, model, sample_fps, cfg, thr):
    job = JOBS[key]
    try:
        sid = settings_id(cfg)
        res = load_results(d, model, sample_fps, sid)
        st = review.load_state(sfile(d, model, sample_fps, sid))
        boxes = review.materialize(res, st, thr)
        fname = res.get("filtered")
        src = d / fname if fname and (d / fname).exists() else original_path(d)
        job.update(stage="rendering", done=0, total=1)
        review.outline_video(src, res, boxes, outdir(d, vid) / "outlined.mp4",
                             progress=lambda a, b: job.update(done=a, total=b))
        job.update(stage="done")
    except Exception as e:
        traceback.print_exc()
        job.update(stage="error", error=friendly(e))


@app.post("/api/outline/{vid}")
def outline_start(vid: str, model: str = "nano", sample_fps: float = 2.0, cfg: str = "", thr: float = 0.6):
    d = vdir(vid)
    c = parse_cfg(cfg)
    key = jkey(vid, model, sample_fps, settings_id(c), "_outline")
    if JOBS.get(key, {}).get("stage") == "rendering":
        return {"started": False}
    JOBS[key] = {"stage": "rendering", "done": 0, "total": 1}
    threading.Thread(target=run_outline, args=(key, d, vid, model, sample_fps, c, thr), daemon=True).start()
    return {"started": True}


@app.get("/api/outline_status/{vid}")
def outline_status(vid: str, model: str = "nano", sample_fps: float = 2.0, cfg: str = ""):
    return JOBS.get(jkey(vid, model, sample_fps, settings_id(parse_cfg(cfg)), "_outline"), {"stage": "idle"})


@app.get("/download/{vid}/{name}")
def download(vid: str, name: str):
    d = vdir(vid)
    if name not in ("annotations.csv", "frames.csv", "summary.csv", "review_state.json", "outlined.mp4"):
        raise HTTPException(404)
    p = outdir(d, vid) / name
    if not p.exists():
        raise HTTPException(404, "not made yet")
    return FileResponse(p, filename=name)


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
