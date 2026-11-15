#!/usr/bin/env python3
"""Builds the English demo charts (timeline, pixels, overlap).
Written with assistance from Claude (Anthropic), an AI assistant."""
import pandas as pd

F = 'font-family="Arial, Helvetica, sans-serif"'
INK, INK2, RULE, EMBER, TEAL, SAND = "#1d2a2f", "#4c5a60", "#cfd4cf", "#b23a1c", "#2a7f86", "#e3a07a"
y = pd.read_csv("../../reports/yearly_sensor_comparison.csv").rename(columns={"month": "year"}).set_index("year")

# ---------------------------------------------------------------- 1. timeline
W, H, L, R = 1700, 430, 250, 40
x0, x1 = 2000, 2028
X = lambda t: L + (t - x0) / (x1 - x0) * (W - L - R)
rows = [
    ("Terra", "MODIS", 2000 + 10 / 12, 2026 + 3 / 12, "#8a979b", "data from Nov 2000 · in standby since Mar 2026"),
    ("Aqua", "MODIS", 2002 + 6 / 12, 2026 + 11 / 12, "#8a979b", "data from Jul 2002 · planned end 2027"),
    ("Suomi NPP", "VIIRS", 2012 + 0.6 / 12, 2026 + 11 / 12, INK, "data from Jan 2012 · continues"),
    ("NOAA-20 / 21", "VIIRS", 2018 + 3 / 12, 2026 + 11 / 12, "#6f7c80", "from 2018 / 2024 · continue the series"),
]
s = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" {F}>']
# overlap and calibration bands
s.append(f'<rect x="{X(2012):.0f}" y="20" width="{X(2026 + 11/12) - X(2012):.0f}" height="{H - 90}" fill="#f4d9c8" opacity=".55"/>')
s.append(f'<rect x="{X(2012):.0f}" y="20" width="{X(2022) - X(2012):.0f}" height="{H - 90}" fill="#e9a77f" opacity=".45"/>')
s.append(f'<text x="{(X(2012) + X(2022)) / 2:.0f}" y="48" text-anchor="middle" font-size="24" font-weight="700" fill="{EMBER}">2012–2021: conversion is learned here</text>')
s.append(f'<text x="{(X(2022) + X(2026.9)) / 2:.0f}" y="48" text-anchor="middle" font-size="20" fill="{EMBER}">both still fly</text>')
for i, (sat, inst, a, b, col, note) in enumerate(rows):
    yy = 78 + i * 74
    s.append(f'<text x="{L - 20}" y="{yy + 22}" text-anchor="end" font-size="28" font-weight="700" fill="{INK}">{sat}</text>')
    s.append(f'<text x="{L - 20}" y="{yy + 48}" text-anchor="end" font-size="22" fill="{INK2}">{inst}</text>')
    s.append(f'<rect x="{X(a):.0f}" y="{yy}" width="{X(b) - X(a):.0f}" height="34" rx="6" fill="{col}"/>')
    s.append(f'<text x="{X(a) + 12:.0f}" y="{yy + 58}" font-size="19" fill="{INK2}">{note}</text>')
    if inst == "MODIS":
        s.append(f'<rect x="{X(b):.0f}" y="{yy}" width="{X(2027.7) - X(b):.0f}" height="34" rx="6" fill="none" stroke="{col}" stroke-dasharray="6 5" stroke-width="2"/>')
for t in range(2000, 2029, 2):
    s.append(f'<line x1="{X(t):.0f}" x2="{X(t):.0f}" y1="{H - 66}" y2="{H - 58}" stroke="{INK2}"/>')
    s.append(f'<text x="{X(t):.0f}" y="{H - 30}" text-anchor="middle" font-size="20" fill="{INK2}">{t}</text>')
s.append(f'<line x1="{L}" x2="{W - R}" y1="{H - 66}" y2="{H - 66}" stroke="{RULE}" stroke-width="2"/></svg>')
open("en_timeline.svg", "w").write("".join(s))

# ---------------------------------------------------------------- 2. pixels
W, H = 900, 470
s = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" {F}>']
for k, (title, n, ox) in enumerate((("MODIS: one 1 km pixel", 1, 40), ("VIIRS: ~7 pixels of 375 m", 3, 480))):
    size = 360
    s.append(f'<text x="{ox + size / 2}" y="34" text-anchor="middle" font-size="26" font-weight="700" fill="{INK}">{title}</text>')
    s.append(f'<rect x="{ox}" y="56" width="{size}" height="{size}" fill="#eef0ec" stroke="{INK}" stroke-width="3"/>')
    if n > 1:
        step = size * 0.375
        for i in range(1, 3):
            s.append(f'<line x1="{ox + i * step:.0f}" x2="{ox + i * step:.0f}" y1="56" y2="416" stroke="{INK2}" stroke-width="1.5"/>')
            s.append(f'<line x1="{ox}" x2="{ox + size}" y1="{56 + i * step:.0f}" y2="{56 + i * step:.0f}" stroke="{INK2}" stroke-width="1.5"/>')
        # cells with fire
        for (cx, cy) in ((0, 0), (1, 0), (0, 1)):
            s.append(f'<rect x="{ox + cx * step + 3:.0f}" y="{56 + cy * step + 3:.0f}" width="{step - 6:.0f}" height="{step - 6:.0f}" fill="#f2a24c" opacity=".85"/>')
        s.append(f'<rect x="{ox + 2 * step + 3:.0f}" y="{56 + 2 * step + 3:.0f}" width="{size - 2 * step - 6:.0f}" height="{size - 2 * step - 6:.0f}" fill="#f2a24c" opacity=".85"/>')
    else:
        s.append(f'<rect x="{ox + 4}" y="60" width="{size - 8}" height="{size - 8}" fill="#f2a24c" opacity=".55"/>')
    # one big fire, one small fire
    s.append(f'<circle cx="{ox + 95}" cy="150" r="70" fill="{EMBER}" opacity=".85"/>')
    s.append(f'<circle cx="{ox + 300}" cy="360" r="14" fill="{EMBER}"/>')
s.append('</svg>')
open("en_pixels.svg", "w").write("".join(s))

# ---------------------------------------------------------------- 3. overlap bars
yrs = list(range(2012, 2022))
W, H, L, B, T = 1150, 560, 90, 60, 40
mx = y.loc[yrs, "viirs_raw"].max() * 1.12
bw = (W - L - 20) / len(yrs)
Y = lambda v: H - B - (H - B - T) * v / mx
s = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" {F}>']
for t in range(0, int(mx), 100000):
    s.append(f'<line x1="{L}" x2="{W - 20}" y1="{Y(t):.0f}" y2="{Y(t):.0f}" stroke="{RULE}"/><text x="{L - 12}" y="{Y(t) + 7:.0f}" text-anchor="end" font-size="20" fill="{INK2}">{t // 1000}k</text>')
for i, yr in enumerate(yrs):
    m, v = y.loc[yr, "modis_observed"], y.loc[yr, "viirs_raw"]
    xm = L + i * bw + bw * 0.1
    s.append(f'<rect x="{xm:.0f}" y="{Y(m):.0f}" width="{bw * 0.38:.0f}" height="{Y(0) - Y(m):.0f}" fill="#8a979b"/>')
    s.append(f'<rect x="{xm + bw * 0.4:.0f}" y="{Y(v):.0f}" width="{bw * 0.38:.0f}" height="{Y(0) - Y(v):.0f}" fill="{INK}"/>')
    s.append(f'<text x="{xm + bw * 0.39:.0f}" y="{Y(v) - 10:.0f}" text-anchor="middle" font-size="19" font-weight="700" fill="{EMBER}">{v / m:.1f}×</text>')
    s.append(f'<text x="{xm + bw * 0.39:.0f}" y="{H - B + 30}" text-anchor="middle" font-size="20" fill="{INK2}">{yr}</text>')
s.append("</svg>")
open("en_overlap.svg", "w").write("".join(s))
ratio = y.loc[yrs, "viirs_raw"].sum() / y.loc[yrs, "modis_observed"].sum()
print("overlap ratio 2012-2021:", round(ratio, 2), "range", round((y.loc[yrs, 'viirs_raw'] / y.loc[yrs, 'modis_observed']).min(), 2),
      round((y.loc[yrs, 'viirs_raw'] / y.loc[yrs, 'modis_observed']).max(), 2))
