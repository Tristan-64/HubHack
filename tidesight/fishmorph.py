"""Look up the closest fish in fishmorph_clean.csv (FISHMORPH traits) from measurements typed by a person.

Everything is local. Only the traits you fill in are compared; blank ones are ignored.
"""
import math
from pathlib import Path

import numpy as np
import pandas as pd

CSV = Path(__file__).parent / "fishmorph_clean.csv"
# code, plain-language name, how to read it
TRAITS = [
    ("MBl", "Maximum body length", "cm"),
    ("BEl", "Body elongation", "body length ÷ body depth (long thin fish = high)"),
    ("VEp", "Vertical eye position", "eye height on the head (0 = low, 1 = top)"),
    ("REs", "Relative eye size", "eye size ÷ head depth"),
    ("OGp", "Oral gape position", "mouth position (0 = underneath, 1 = facing up)"),
    ("RMl", "Relative maxillary length", "upper jaw length ÷ head length"),
    ("BLs", "Body lateral shape", "head depth ÷ body depth"),
    ("PFv", "Pectoral fin vertical position", "fin height on the body (0 = low, 1 = high)"),
    ("PFs", "Pectoral fin size", "fin length ÷ body length"),
    ("CPt", "Caudal peduncle throttling", "tail fin depth ÷ narrowest part of the tail stalk"),
]
CODES = [t[0] for t in TRAITS]
LOGGED = {"MBl", "BEl"}                       # very skewed traits are compared on a log scale
ALIASES = {"mbi": "MBl", "bei": "BEl", "rmi": "RMl"}   # people often type a capital I for a small L
_cache = {}


def available():
    return CSV.exists()


# Accept any spelling of a trait code (e.g. MBI for MBl) and return the official one.
def canon(code):
    c = str(code).strip()
    low = c.lower()
    if low in ALIASES:
        return ALIASES[low]
    for t in CODES:
        if t.lower() == low:
            return t
    return None


# Log-scale the very skewed traits (MBl, BEl) so big fish do not swamp the comparison.
def _tf(code, v):
    return np.log10(v) if code in LOGGED else v


# Read fishmorph_clean.csv once and cache it (restart the app after editing the CSV).
def _load():
    if "df" in _cache:
        return _cache
    df = pd.read_csv(CSV, encoding="utf-8-sig")
    z, stats = {}, {}
    for c in CODES:
        col = pd.to_numeric(df[c], errors="coerce")
        if c in LOGGED:
            col = col.where(col > 0)
        t = np.log10(col) if c in LOGGED else col
        med = float(t.median())
        sd = float((t.quantile(.75) - t.quantile(.25)) / 1.349) or float(t.std()) or 1.0   # robust spread
        z[c] = ((t - med) / sd).to_numpy(dtype=float)
        stats[c] = {"min": float(col.min()), "median": float(col.median()), "max": float(col.max()), "centre": med, "spread": sd}
    _cache.update(df=df, z=z, stats=stats)
    return _cache


def _clean(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return ""
    return " ".join(str(v).split())          # one line, single spaces


# Only http/https links are accepted, so a bad CSV cell cannot become a javascript: link.
def _url(v):
    s = _clean(v)
    return s if s.lower().startswith(("https://", "http://")) else ""     # never javascript: or data: links


# Picture, credit, licence and source link for one species (None if it has no usable picture).
def _image(row):
    """Picture details for a species, or None when the table has no usable picture for it."""
    url, thumb = _url(row.get("image_url")), _url(row.get("thumbnail_url"))
    if not url and not thumb:
        return None
    return {"url": url or thumb, "thumb": thumb or url, "source": _clean(row.get("image_source")),
            "credit": _clean(row.get("image_credit")), "license": _clean(row.get("image_license")),
            "page": _url(row.get("image_page"))}


# What the page needs to build the lookup form: trait names, typical values, picture counts.
def info():
    st = _load()["stats"]
    df = _load()["df"]
    n_img = int(sum(1 for _, r in df.iterrows() if _image(r))) if "image_url" in df.columns else 0
    return {"rows": int(len(df)), "images": n_img,
            "traits": [{"code": c, "name": n, "hint": h, "min": st[c]["min"], "median": st[c]["median"], "max": st[c]["max"]} for c, n, h in TRAITS]}


# Closest k species: robust-scale each typed trait, then root-mean-square difference over the traits both sides have.
def search(values, k=5):
    """values: {trait code: number}. Returns the k closest species (smaller difference = closer)."""
    used = {}
    for key, v in (values or {}).items():
        code = canon(key)
        if code is None or v is None or v == "":
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{key}: please type a number")
        if math.isnan(x):
            continue
        if code in LOGGED and x <= 0:
            raise ValueError(f"{code}: must be bigger than 0")
        used[code] = x
    if not used:
        raise ValueError("Type at least one measurement first.")
    c = _load()
    n_used = len(used)
    total = np.zeros(len(c["df"]))
    count = np.zeros(len(c["df"]))
    for code, x in used.items():
        q = (_tf(code, x) - c["stats"][code]["centre"]) / c["stats"][code]["spread"]
        d = (c["z"][code] - q) ** 2
        ok = ~np.isnan(d)
        total[ok] += d[ok]
        count[ok] += 1
    need = max(1, math.ceil(n_used / 2))            # a fish must have at least half of the numbers you typed
    dist = np.where(count >= need, np.sqrt(total / np.maximum(count, 1)), np.inf)
    order = np.lexsort((-count, dist))[:k]
    df = c["df"]
    out = []
    for i in order:
        if not np.isfinite(dist[i]):
            break
        row = df.iloc[i]
        out.append({"species": str(row["Genus.Species"]), "family": str(row["Family"]), "order": str(row["Order"]),
                    "difference": round(float(dist[i]), 3), "compared": int(count[i]), "typed": n_used,
                    "values": {t: (None if pd.isna(row[t]) else round(float(row[t]), 3)) for t in CODES},
                    "image": _image(row)})
    return out
