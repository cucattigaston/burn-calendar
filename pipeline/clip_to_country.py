#!/usr/bin/env python3
"""
Keep only hotspots inside Argentina (Natural Earth 1:10m boundary, via world-atlas).
Used for months fetched from the FIRMS area API, which returns a bounding box.
AI disclosure: written with assistance from Claude (Anthropic), an AI assistant.

    python pipeline/clip_to_country.py in.csv out.csv.gz [--check country_file.csv.gz]
"""
import argparse
import json
import os

import numpy as np
import pandas as pd
from matplotlib.path import Path

HERE = os.path.dirname(os.path.abspath(__file__))


def country_paths(geojson=os.path.join(HERE, "argentina_10m.geojson")):
    g = json.load(open(geojson))["features"][0]["geometry"]
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    return [Path(np.array(p[0])) for p in polys]   # outer rings (no holes in Argentina)


def inside(lat, lon, paths, buffer_deg=0.01):
    pts = np.column_stack([lon, lat])
    mask = np.zeros(len(pts), dtype=bool)
    for p in paths:
        mask |= p.contains_points(pts, radius=buffer_deg) | p.contains_points(pts, radius=-buffer_deg)
    return mask


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--check", help="FIRMS country file: report how many of its points fall inside")
    a = ap.parse_args()
    paths = country_paths()
    if a.check:
        c = pd.read_csv(a.check, usecols=["latitude", "longitude"])
        m = inside(c.latitude.values, c.longitude.values, paths)
        print(f"check: {m.mean() * 100:.2f}% of {len(c):,} FIRMS-Argentina points fall inside the boundary")
    df = pd.read_csv(a.src)
    m = inside(df.latitude.values, df.longitude.values, paths)
    df[m].to_csv(a.dst, index=False)
    print(f"{a.src}: {len(df):,} → {int(m.sum()):,} inside Argentina")


if __name__ == "__main__":
    main()
