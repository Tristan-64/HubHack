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


def canon(code):
    c = str(code).strip()
    low = c.lower()
    if low in ALIASES:
        return ALIASES[low]
    for t in CODES:
        if t.lower() == low:
            return t
    return None


def _tf(code, v):
    return np.log10(v) if code in LOGGED else v


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


def info():
    st = _load()["stats"]
    return {"rows": int(len(_load()["df"])),
            "traits": [{"code": c, "name": n, "hint": h, "min": st[c]["min"], "median": st[c]["median"], "max": st[c]["max"]} for c, n, h in TRAITS]}


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
                    "values": {t: (None if pd.isna(row[t]) else round(float(row[t]), 3)) for t in CODES}})
    return out
