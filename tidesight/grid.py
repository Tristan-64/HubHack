"""Grid drawing and cell naming (rows = letters A.., columns = numbers 1..)."""
import string
import cv2


def cell_for_point(cx, cy, w, h, rows, cols):
    r = min(int(cy / h * rows), rows - 1)
    c = min(int(cx / w * cols), cols - 1)
    return f"{string.ascii_uppercase[r]}{c + 1}"


def draw_grid(frame, rows, cols):
    out = frame.copy()
    h, w = out.shape[:2]
    for r in range(1, rows):
        cv2.line(out, (0, h * r // rows), (w, h * r // rows), (255, 255, 0), 1)
    for c in range(1, cols):
        cv2.line(out, (w * c // cols, 0), (w * c // cols, h), (255, 255, 0), 1)
    for r in range(rows):
        for c in range(cols):
            cv2.putText(out, f"{string.ascii_uppercase[r]}{c + 1}", (w * c // cols + 6, h * r // rows + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2, cv2.LINE_AA)
    return out
