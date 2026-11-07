"""Reading, listing and trimming videos."""
from pathlib import Path
import cv2

VIDEO_DIR = Path(__file__).parent / "videos"
EXTS = {".mp4", ".mov", ".avi", ".m4v"}


def list_videos():
    VIDEO_DIR.mkdir(exist_ok=True)
    return sorted(p.name for p in VIDEO_DIR.iterdir() if p.suffix.lower() in EXTS and not p.name.startswith("."))


def video_info(path):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    cap.release()
    return {"fps": fps, "frames": int(n), "duration": (n / fps) if fps else 0.0}


def read_frame_at(path, t, cap=None):
    own = cap is None
    if own:
        cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_MSEC, max(t, 0) * 1000)
    ok, frame = cap.read()
    if own:
        cap.release()
    return frame if ok else None


def default_trim(duration, trim=60):
    start, end = float(trim), duration - trim
    if end <= start:  # short test video: use whole clip
        start, end = 0.0, float(duration)
    return start, end


def sample_times(start, end, interval):
    times, t = [], float(start)
    while t <= end + 1e-6:
        times.append(round(t, 2))
        t += interval
    return times


def mmss(t):
    return f"{int(t // 60):02d}m{int(t % 60):02d}s"
