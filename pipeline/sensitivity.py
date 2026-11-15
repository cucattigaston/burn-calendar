#!/usr/bin/env python3
"""
Sensitivity analysis of the VIIRS → MODIS conversion. Every variant is scored with the same
leave-one-year-out test as the pipeline (2012–2021), at national, 2° and 0.5° scales.

  A. Is the conversion factor stable in time?   national day/night factor year by year + trend
  B. Calibration region size                    1°, 2° (used), 4°, national
  C. Shrinkage weight toward the national factor  0, 30, 100, 300 (used), 1000, 3000

AI disclosure: written with assistance from Claude (Anthropic), an AI assistant.

    python pipeline/sensitivity.py --modis raw/firms_modis_ARG_2000_2025.csv.gz \
        --viirs raw/firms_viirs_snpp_ARG_2012_2025.csv.gz
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harmonize as H  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--modis", nargs="+", required=True)
ap.add_argument("--viirs", nargs="+", required=True)
ap.add_argument("--out", default="reports/sensitivity.json")
args = ap.parse_args()

mod, _ = H.load(args.modis, "MODIS")
vii, _ = H.load(args.viirs, "VIIRS")
mod, vii = H.add_keys(mod), H.add_keys(vii)
YEARS = list(range(2012, 2022))
mod = mod[mod.month.dt.year.between(2012, 2025)]
vii = vii[vii.month.dt.year.between(2012, 2025)]


def counts(df):
    c = df.groupby(["cy", "cx", "ry", "rx", "month", "dn"], observed=True).size().rename("n").reset_index()
    c["_all"] = 0
    lat = (c.cy + 0.5) * H.CELL - 90
    lon = (c.cx + 0.5) * H.CELL - 180
    for size in (1, 2, 4):
        c[f"ry{size}"] = np.floor((lat + 90) / size).astype(int)
        c[f"rx{size}"] = np.floor((lon + 180) / size).astype(int)
    return c


mc_all, vc_all = counts(mod), counts(vii)
mc = mc_all[mc_all.month.dt.year.isin(YEARS)]
vc = vc_all[vc_all.month.dt.year.isin(YEARS)]


def loyo(keys, alpha, split_dn=True):
    """Leave-one-year-out WAPE at three evaluation scales for one calibration variant."""
    obs, pred = [], []
    for y in YEARS:
        model = H.fit_ratio(mc[mc.month.dt.year != y], vc[vc.month.dt.year != y], keys, alpha, split_dn)
        te_v = vc[vc.month.dt.year == y]
        pred.append(te_v.assign(v=H.apply_ratio(model, te_v)))
        te_m = mc[mc.month.dt.year == y]
        obs.append(te_m.assign(v=te_m.n.astype(float)))
    obs, pred = pd.concat(obs), pd.concat(pred)
    out = {}
    for sc in ("national", "regional (2°)", "local (0.5°)"):
        r = H.metrics(H.scale_agg(obs, sc), H.scale_agg(pred, sc))
        out[sc] = r["wape_pct"]
    return out


res = {"test": "leave-one-year-out 2012–2021; weighted absolute error (%) of monthly counts; lower is better"}

# A. stability in time
yr = []
for y in range(2012, 2026):
    m = mc_all[mc_all.month.dt.year == y].groupby("dn").n.sum()
    v = vc_all[vc_all.month.dt.year == y].groupby("dn").n.sum()
    yr.append({"year": y, "day": round(float(m.get("D", 0) / v.get("D", 1)), 3),
               "night": round(float(m.get("N", 0) / v.get("N", 1)), 3)})
yr_df = pd.DataFrame(yr).set_index("year")


def trend(series):
    x = np.array(series.index, dtype=float)
    yv = series.values
    b, a = np.polyfit(x, yv, 1)
    resid = yv - (a + b * x)
    se = np.sqrt(resid @ resid / (len(x) - 2) / ((x - x.mean()) @ (x - x.mean())))
    return {"slope_pct_per_year": round(float(b / yv.mean() * 100), 2),
            "slope_95ci_pct_per_year": [round(float((b - 1.96 * se) / yv.mean() * 100), 2),
                                        round(float((b + 1.96 * se) / yv.mean() * 100), 2)]}


cal = yr_df.loc[2012:2021]
res["A_factor_by_year"] = {
    "national_factor_by_year": yr.copy(),
    "trend_2012_2021_day": trend(cal.day),
    "trend_2012_2021_night": trend(cal.night),
    "day_factor_range_2012_2021": [float(cal.day.min()), float(cal.day.max())],
    "night_factor_range_2012_2021": [float(cal.night.min()), float(cal.night.max())],
    "note": "2022–2025 shown for reference only (Terra/Aqua orbit drift; not used for calibration)",
}

# B. region size
res["B_region_size"] = {}
for name, keys in (("1°", ["ry1", "rx1"]), ("2° (used)", ["ry2", "rx2"]), ("4°", ["ry4", "rx4"]), ("national", ["_all"])):
    res["B_region_size"][name] = loyo(keys, 300)
    print("B", name, res["B_region_size"][name], flush=True)

# C. shrinkage weight
res["C_shrinkage_weight"] = {}
for a in (0, 30, 100, 300, 1000, 3000):
    label = f"{a} (used)" if a == 300 else str(a)
    res["C_shrinkage_weight"][label] = loyo(["ry2", "rx2"], a)
    print("C", label, res["C_shrinkage_weight"][label], flush=True)

json.dump(res, open(args.out, "w"), indent=2, ensure_ascii=False)
print(yr_df.to_string())
print(json.dumps({k: v for k, v in res["A_factor_by_year"].items() if k != "national_factor_by_year"}, indent=1))
