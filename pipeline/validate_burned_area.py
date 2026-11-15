#!/usr/bin/env python3
"""
Independent check against burned area (MODIS MCD64A1 c6.1, national monthly totals for
Argentina from the Global Fire Dashboard, Climatic Research Unit / UEA).

Question: if harmonization works, the relationship between hotspots and burned area
should not change when the record switches from MODIS to VIIRS in January 2012.
Without harmonization (raw VIIRS counts after 2011) it should jump.

Model (monthly, months with burned area > 0):
    log(hotspots) = a + b·log(burned area) + c·[month ≥ 2012-01] + month-of-year effects
c is the "sensor break". exp(c) is the multiplicative jump in hotspots per unit of
burned area at the switch. Harmonized: exp(c) ≈ 1. Naive: exp(c) ≈ 3.

AI disclosure: written with assistance from Claude (Anthropic), an AI assistant.

    python pipeline/validate_burned_area.py raw/external/cru_BA_Total_monthly_ARG.csv
"""
import json
import sys

import numpy as np
import pandas as pd

ba_path = sys.argv[1]
nat = pd.read_csv("reports/national_monthly.csv")
yearly = pd.read_csv("reports/yearly_sensor_comparison.csv")

ba = pd.read_csv(ba_path)
ba = ba.melt(id_vars=["year"], value_vars=[str(m) for m in range(1, 13)], var_name="m", value_name="ba")
ba["month"] = ba.year.astype(str) + "-" + ba.m.str.zfill(2)
ba = ba.dropna(subset=["ba"])[["month", "ba"]]

d = nat.merge(ba, on="month")
d["post"] = (d.month >= "2012-01").astype(int)
d["naive"] = np.where(d.post == 1, d.viirs, d.modis)
d["mo"] = d.month.str[5:7].astype(int)
d = d[(d.ba > 0) & (d.month >= "2001-01")]


def ols(y, X):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape
    s2 = resid @ resid / (n - k)
    cov = s2 * np.linalg.inv(X.T @ X)
    return beta, np.sqrt(np.diag(cov)), 1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))


def break_test(series):
    dd = d[d[series] > 0]
    y = np.log(dd[series].values)
    month_dummies = np.column_stack([(dd.mo == m).astype(float) for m in range(2, 13)])
    X = np.column_stack([np.ones(len(dd)), np.log(dd.ba.values), dd.post.values, month_dummies])
    beta, se, r2 = ols(y, X)
    c, c_se = beta[2], se[2]
    return {"jump_factor": round(float(np.exp(c)), 2),
            "jump_95ci": [round(float(np.exp(c - 1.96 * c_se)), 2), round(float(np.exp(c + 1.96 * c_se)), 2)],
            "slope_log_ba": round(float(beta[1]), 3), "r2": round(float(r2), 3), "n_months": int(len(dd))}


def break_test_window(series, y0, y1):
    global d
    full = d
    d = full[(full.month >= f"{y0}-01") & (full.month <= f"{y1}-12")]
    try:
        return break_test(series)
    finally:
        d = full


def corr(series, era):
    dd = d[(d.post == era) & (d[series] > 0)]
    return round(float(np.corrcoef(np.log(dd[series]), np.log(dd.ba))[0, 1]), 3)


res = {
    "source": "MODIS MCD64A1 c6.1 burned area, Argentina national monthly totals, "
              "Global Fire Dashboard (Climatic Research Unit, UEA), 2001-01..2023-06",
    "break_at_2012": {"harmonized": break_test("harmonized"), "naive (raw VIIRS after 2011)": break_test("naive"),
                      "MODIS observed throughout (reference)": break_test("modis")},
    "break_at_2012_window_2003_2021": {
        "note": "Terra+Aqua complete and before end-of-mission orbit drift",
        "harmonized": break_test_window("harmonized", 2003, 2021),
        "naive (raw VIIRS after 2011)": break_test_window("naive", 2003, 2021),
        "MODIS observed throughout (reference)": break_test_window("modis", 2003, 2021)},
    "log_correlation_with_burned_area": {
        "harmonized, 2001-2011": corr("harmonized", 0), "harmonized, 2012-2023": corr("harmonized", 1),
        "naive, 2012-2023": corr("naive", 1)},
}

# Annual ratio hotspots / burned area (complete years only), for the chart
d["year"] = d.month.str[:4].astype(int)
full = d.groupby("year").filter(lambda g: len(g) == 12)
ann = full.groupby("year")[["harmonized", "naive", "ba"]].sum()
ann["ratio_harmonized"] = ann.harmonized / ann.ba
ann["ratio_naive"] = ann.naive / ann.ba
ref = ann.loc[ann.index < 2012, "ratio_harmonized"].mean()
ann["ratio_harmonized_rel"] = (ann.ratio_harmonized / ref).round(3)
ann["ratio_naive_rel"] = (ann.ratio_naive / ref).round(3)
res["annual_ratio_relative_to_2001_2011"] = {
    int(y): {"harmonized": float(r.ratio_harmonized_rel), "naive": float(r.ratio_naive_rel)} for y, r in ann.iterrows()}
res["mean_relative_ratio_2012_2022"] = {
    "harmonized": round(float(ann.loc[ann.index >= 2012, "ratio_harmonized_rel"].mean()), 2),
    "naive": round(float(ann.loc[ann.index >= 2012, "ratio_naive_rel"].mean()), 2)}

json.dump(res, open("reports/validation_burned_area.json", "w"), indent=2)
print(json.dumps({k: v for k, v in res.items() if k != "annual_ratio_relative_to_2001_2011"}, indent=2))
print(ann[["ratio_harmonized_rel", "ratio_naive_rel"]].to_string())
