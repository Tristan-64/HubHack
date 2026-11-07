"""
TideSight - check the AI's counts against a person's counts using
Coastal Action's own quality-control rule (DRAFT protocol):

  * Two counts of the same frame should differ by less than 6%.
  * At least 95% of frames should agree.

Percent difference = |a - b| / average(a, b) x 100  (0% when both are 0).

Small counts make the 6% rule very strict (1 fish vs 2 fish = 67%), so the
report also shows exact matches and matches within one fish.

Usage:
    python validate.py outputs/VIDEO_ID/meancount_sheet.csv human_counts.csv

human_counts.csv needs two columns:
    subsample,human_count
    1,0
    2,2
    ...
"""

import argparse
import csv
import os
import sys

import yaml


def pct_diff(a, b):
    if a == 0 and b == 0:
        return 0.0
    return abs(a - b) / ((a + b) / 2) * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ai_sheet")
    ap.add_argument("human_counts")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    with open(args.config) as f:
        v = yaml.safe_load(f)["validation"]

    with open(args.ai_sheet) as f:
        ai = {int(r["subsample"]): r for r in csv.DictReader(f)}
    with open(args.human_counts) as f:
        human = {int(r["subsample"]): int(r["human_count"]) for r in csv.DictReader(f)}

    shared = sorted(set(ai) & set(human))
    if not shared:
        sys.exit("No matching subsample numbers between the two files.")

    rows, passed, exact, within1 = [], 0, 0, 0
    for s in shared:
        a, h = int(ai[s]["total_fish_count"]), human[s]
        d = pct_diff(a, h)
        ok = d < v["max_percent_difference"]
        passed += ok
        exact += a == h
        within1 += abs(a - h) <= 1
        rows.append({"subsample": s, "timestamp": ai[s]["timestamp"], "ai_count": a,
                     "human_count": h, "percent_difference": round(d, 1),
                     "within_protocol_limit": "yes" if ok else "no"})

    n = len(rows)
    agreement = passed / n * 100
    ai_mean = sum(r["ai_count"] for r in rows) / n
    human_mean = sum(r["human_count"] for r in rows) / n

    out = os.path.join(os.path.dirname(args.ai_sheet), "validation_report.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"Frames compared: {n}")
    print(f"MeanCount  AI: {ai_mean:.2f}   Person: {human_mean:.2f}")
    print(f"Within {v['max_percent_difference']}% (protocol rule): {passed}/{n} = {agreement:.0f}%  "
          f"-> {'PASSES' if agreement >= v['min_agreement_percent'] else 'does not pass'} "
          f"the {v['min_agreement_percent']}% target")
    print(f"Exact match: {exact}/{n}   Within 1 fish: {within1}/{n}")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
