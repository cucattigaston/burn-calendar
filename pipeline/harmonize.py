#!/usr/bin/env python3
"""
Harmonized burning-activity calendar — data pipeline
NASA Space Apps Challenge 2026 · "Harmonization of MODIS and VIIRS Hot Spots"

Input : NASA FIRMS standard-processing hotspots for Argentina
        MODIS C6.1 (Terra + Aqua, 2000-11 →) and VIIRS S-NPP 375 m (2012-01 →),
        optionally VIIRS S-NPP NRT for the current year.
Output: web/data/*  — a 0.1° × month grid of harmonized hotspot counts plus
        per-tile raw hotspots for CSV export, and validation reports.

Harmonized unit: "MODIS-equivalent hotspots" = the number of hotspots that
Terra+Aqua MODIS would have reported. It keeps 25 years comparable.

Steps
  1. Clean      : MODIS confidence ≥ 30, VIIRS nominal/high, type = 0 (vegetation /
                  land fires; volcanoes, static industrial sources and offshore removed).
  2. Grid       : 0.1° cells, calendar months, split by day/night.
  3. Terra→T+A  : 2000-11..2002-06 only Terra flew. Scaled to Terra+Aqua with a
                  regional ratio learned in 2003–2011.
  4. VIIRS→MODIS: regional ratios with shrinkage toward the national ratio, learned
                  over the clean overlap (2012–2021, before MODIS orbit drift), separately
                  for day and night overpasses.
  5. Validate   : leave-one-year-out cross-validation at national, regional (2°) and
                  local (0.5°) scales; several methods compared; the best is used.
  6. Series     : MODIS era (2000-11..2011-12) + VIIRS era converted (2012-01 → now).

AI disclosure: this file was written with assistance from Claude (Anthropic), an AI assistant.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import struct
import sys
import time

import numpy as np
import pandas as pd

CELL = 0.1            # grid resolution (deg) used by the web app
REGION = 2.0          # calibration region size (deg)
TILE = 1.0            # raw-hotspot tile size for CSV export (deg)
CALIB_YEARS = (2012, 2021)   # clean overlap: before Terra/Aqua orbit drift
TERRA_ONLY_END = pd.Period("2002-06", "M")
VIIRS_START = pd.Period("2012-01", "M")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# 1. Load + clean
# --------------------------------------------------------------------------- #
def load(path_list, sensor):
    frames = []
    for p in path_list:
        df = pd.read_csv(p, dtype={"satellite": str, "confidence": str, "daynight": str})
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    n0 = len(df)
    if "type" not in df:          # NRT files have no "type"; static sources removed later
        df["type"] = 0
    df["type"] = pd.to_numeric(df["type"], errors="coerce").fillna(0).astype(int)
    if sensor == "MODIS":
        conf = pd.to_numeric(df.confidence, errors="coerce")
        keep = conf >= 30
        df["sat"] = np.where(df.satellite.str.upper().str.startswith("T"), "Terra", "Aqua")
    else:
        keep = df.confidence.str.lower().str[0].isin(["n", "h"])
        df["sat"] = "SNPP"
    n_conf = int(keep.sum())
    keep &= df["type"] == 0
    df = df[keep].copy()
    df["date"] = pd.to_datetime(df.acq_date)
    df["month"] = df.date.dt.to_period("M")
    df["dn"] = df.daynight.str.upper().str[0].where(lambda s: s.isin(["D", "N"]), "D")
    df["sensor"] = sensor
    log(f"{sensor}: {n0:,} raw → {n_conf:,} confident → {len(df):,} vegetation/land fires")
    return df[["latitude", "longitude", "date", "acq_time", "month", "dn", "sat",
               "sensor", "confidence", "frp"]], {"raw": n0, "confident": n_conf, "kept": len(df)}


def add_keys(df):
    df["cy"] = np.floor((df.latitude + 90) / CELL).astype(np.int32)
    df["cx"] = np.floor((df.longitude + 180) / CELL).astype(np.int32)
    df["ry"] = np.floor((df.latitude + 90) / REGION).astype(np.int32)
    df["rx"] = np.floor((df.longitude + 180) / REGION).astype(np.int32)
    return df


# --------------------------------------------------------------------------- #
# 2. Monthly grids
# --------------------------------------------------------------------------- #
def grid_counts(df, by_sat=False):
    keys = ["cy", "cx", "ry", "rx", "month", "dn"] + (["sat"] if by_sat else [])
    return df.groupby(keys, observed=True).size().rename("n").reset_index()


def months_covered(df):
    lo, hi = df.month.min(), df.month.max()
    return pd.period_range(lo, hi, freq="M")


# --------------------------------------------------------------------------- #
# 3/4. Ratio models with shrinkage
# --------------------------------------------------------------------------- #
def fit_ratio(target, source, keys, alpha, split_dn=True):
    """k = (Σtarget + alpha·k_parent) / (Σsource + alpha) per key; parent = national."""
    gkeys = (["dn"] if split_dn else [])
    t = target.groupby(gkeys + keys, observed=True).n.sum() if keys or gkeys else target.n.sum()
    s = source.groupby(gkeys + keys, observed=True).n.sum() if keys or gkeys else source.n.sum()
    both = pd.concat([t.rename("t"), s.rename("s")], axis=1).fillna(0)
    if split_dn:
        nat = both.groupby(level="dn").sum()
        nat["k"] = nat.t / nat.s.clip(lower=1)
        parent = both.index.get_level_values("dn").map(nat.k)
    else:
        k0 = both.t.sum() / max(both.s.sum(), 1)
        parent = k0
        nat = pd.DataFrame({"k": [k0]})
    both["k"] = (both.t + alpha * parent) / (both.s + alpha)
    return {"k": both.k, "national": nat.k, "keys": keys, "split_dn": split_dn}


def apply_ratio(model, counts):
    gkeys = (["dn"] if model["split_dn"] else []) + model["keys"]
    k = model["k"]
    if gkeys:
        idx = pd.MultiIndex.from_frame(counts[gkeys]) if len(gkeys) > 1 else pd.Index(counts[gkeys[0]])
        kk = k.reindex(idx).values
        nat = (counts["dn"].map(model["national"]).values if model["split_dn"]
               else np.full(len(counts), float(model["national"].iloc[0])))
        kk = np.where(np.isnan(kk), nat, kk)
    else:
        kk = float(k)
    return counts.n.values * kk


METHODS = {
    # name: (region keys, alpha, split day/night)
    "national ratio": (["_all"], 0, False),
    "national ratio, day/night": (["_all"], 0, True),
    "regional ratio (2°)": (["ry", "rx"], 0, False),
    "regional ratio (2°), day/night, shrinkage": (["ry", "rx"], 300, True),
}


# --------------------------------------------------------------------------- #
# 5. Validation: leave-one-year-out
# --------------------------------------------------------------------------- #
def scale_agg(df, scale):
    if scale == "national":
        return df.groupby("month").v.sum()
    if scale == "regional (2°)":
        return df.groupby(["ry", "rx", "month"]).v.sum()
    # local 0.5°
    return df.assign(ly=df.cy // 5, lx=df.cx // 5).groupby(["ly", "lx", "month"]).v.sum()


def metrics(obs, pred):
    both = pd.concat([obs.rename("o"), pred.rename("p")], axis=1).fillna(0)
    both = both[(both.o > 0) | (both.p > 0)]
    o, p = both.o.values, both.p.values
    wape = np.abs(p - o).sum() / o.sum() * 100
    bias = (p.sum() - o.sum()) / o.sum() * 100
    r = np.corrcoef(o, p)[0, 1] if len(o) > 2 else np.nan
    return {"wape_pct": round(float(wape), 1), "bias_pct": round(float(bias), 1),
            "pearson_r": round(float(r), 3), "n": int(len(o))}


def validate(mod_c, vii_c, years):
    """For each held-out year: fit on the other overlap years, predict MODIS from VIIRS."""
    scales = ["national", "regional (2°)", "local (0.5°)"]
    preds = {m: [] for m in METHODS}
    obs = []
    for y in years:
        tr_m = mod_c[(mod_c.month.dt.year != y)]
        tr_v = vii_c[(vii_c.month.dt.year != y)]
        te_m = mod_c[mod_c.month.dt.year == y]
        te_v = vii_c[vii_c.month.dt.year == y]
        obs.append(te_m.assign(v=te_m.n))
        for name, (keys, alpha, dn) in METHODS.items():
            model = fit_ratio(tr_m, tr_v, keys, alpha, dn)
            preds[name].append(te_v.assign(v=apply_ratio(model, te_v)))
    obs = pd.concat(obs)
    out = {"held_out_years": [int(y) for y in years], "scales": {}}
    for sc in scales:
        o = scale_agg(obs, sc)
        res = {"raw VIIRS (no harmonization)": metrics(o, scale_agg(pd.concat(
            [vii_c[vii_c.month.dt.year.isin(years)].assign(v=lambda d: d.n)]), sc))}
        for name in METHODS:
            res[name] = metrics(o, scale_agg(pd.concat(preds[name]), sc))
        out["scales"][sc] = res
    # choose by local-scale WAPE (what users see when they draw small areas), tie → regional
    loc = out["scales"]["local (0.5°)"]
    out["best_method"] = min(METHODS, key=lambda m: (loc[m]["wape_pct"],
                                                     out["scales"]["regional (2°)"][m]["wape_pct"]))
    return out


# --------------------------------------------------------------------------- #
# 5b. Uncertainty: empirical 80% ranges from leave-one-year-out predictions
# --------------------------------------------------------------------------- #
UNC_EDGES = [0.5, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000]
UNC_SCALES = {"0.1°": 1, "0.5°": 5, "1°": 10, "2°": 20, "national": None}


def loyo_pairs(target_c, source_c, keys, alpha, split_dn, years):
    """Cell × month observed target vs predicted-from-source, each year predicted by a model
    fitted on the other years. Day and night are summed after prediction."""
    out = []
    for y in years:
        model = fit_ratio(target_c[target_c.month.dt.year != y], source_c[source_c.month.dt.year != y],
                          keys, alpha, split_dn)
        te_s = source_c[source_c.month.dt.year == y]
        pred = te_s.assign(pred=apply_ratio(model, te_s)).groupby(["cy", "cx", "month"]).pred.sum()
        obs = target_c[target_c.month.dt.year == y].groupby(["cy", "cx", "month"]).n.sum().rename("obs")
        out.append(pd.concat([obs, pred], axis=1).fillna(0).reset_index())
    return pd.concat(out, ignore_index=True)


def interval_table(pairs, level=0.8):
    """Quantiles of observed/predicted by size of the predicted value, pooled over area sizes
    from one 0.1° cell to the whole country, for monthly values and for annual totals."""
    lo_q, hi_q = (1 - level) / 2, 1 - (1 - level) / 2
    res = {"level": level, "edges": UNC_EDGES}
    for period in ("monthly", "annual"):
        rows = []
        for name, f in UNC_SCALES.items():
            p = pairs.copy()
            p["t"] = p.month if period == "monthly" else p.month.dt.year
            if f is None:
                g = p.groupby("t")[["obs", "pred"]].sum()
            else:
                p["gy"], p["gx"] = p.cy // f, p.cx // f
                g = p.groupby(["gy", "gx", "t"])[["obs", "pred"]].sum()
            rows.append(g[(g.obs > 0) | (g.pred > 0)])
        allp = pd.concat(rows)
        bins, cover = [], []
        tiny = allp[allp.pred < UNC_EDGES[0]]
        # below the first edge the value is "about zero": give an absolute upper bound
        res[f"{period}_below_first_edge_abs_hi"] = float(np.quantile(tiny.obs, hi_q)) if len(tiny) else 1.0
        for a, b in zip(UNC_EDGES, UNC_EDGES[1:] + [np.inf]):
            sel = allp[(allp.pred >= a) & (allp.pred < b)]
            if len(sel) < 30:          # too few cases: reuse the previous bin
                bins.append(bins[-1] if bins else [0.5, 1.5, 0])
                continue
            r = sel.obs / sel.pred
            lo, hi = float(np.quantile(r, lo_q)), float(np.quantile(r, hi_q))
            bins.append([round(lo, 3), round(hi, 3), int(len(sel))])
            cover.append(((r >= lo) & (r <= hi)).mean())
        # widths must not grow with the value (more hotspots → relatively less noise)
        for i in range(1, len(bins)):
            lo, hi, n = bins[i]
            bins[i] = [round(max(lo, bins[i - 1][0]), 3), round(min(hi, bins[i - 1][1]), 3), n]
        res[period] = bins
        res[f"{period}_n_pairs"] = int(len(allp))
    return res
# --------------------------------------------------------------------------- #
def write_grid_bin(path, cells, months, layers):
    """
    Binary layout (little endian), gzip-compressed:
      header: magic 'FCAL', uint16 version, uint16 nLayers, uint32 nRecords,
              int16 firstYear, uint8 firstMonth, uint8 pad, float32 cell size
      records (nRecords): uint16 cy, uint16 cx, uint16 monthIndex, then
              nLayers × float32 values
    """
    first = months.min()
    midx = ((months.dt.year - first.year) * 12 + months.dt.month - first.month).astype(np.uint16)
    n = len(cells)
    rec = np.zeros(n, dtype=[("cy", "<u2"), ("cx", "<u2"), ("m", "<u2")] +
                   [(f"l{i}", "<f4") for i in range(len(layers))])
    rec["cy"], rec["cx"], rec["m"] = cells.cy.values, cells.cx.values, midx.values
    for i, arr in enumerate(layers):
        rec[f"l{i}"] = arr
    hdr = b"FCAL" + struct.pack("<HHIhBBf", 1, len(layers), n, first.year, first.month, 0, CELL)
    with gzip.open(path, "wb", compresslevel=9) as f:
        f.write(hdr + rec.tobytes())


def write_tiles(outdir, raw):
    os.makedirs(outdir, exist_ok=True)
    raw = raw.copy()
    raw["ty"] = np.floor(raw.latitude / TILE).astype(int)
    raw["tx"] = np.floor(raw.longitude / TILE).astype(int)
    raw["latitude"] = raw.latitude.round(4)
    raw["longitude"] = raw.longitude.round(4)
    raw["acq_date"] = raw.date.dt.strftime("%Y-%m-%d")
    raw["acq_time"] = raw.acq_time.astype(int).map("{:04d}".format)
    cols = ["latitude", "longitude", "acq_date", "acq_time", "sat", "dn", "confidence", "frp"]
    index = []
    for (ty, tx), g in raw.groupby(["ty", "tx"]):
        name = f"t{ty}_{tx}.csv.gz"
        g = g.sort_values(["date", "acq_time"])
        with gzip.open(os.path.join(outdir, name), "wt", compresslevel=9) as f:
            g[cols].to_csv(f, index=False, header=False)
        index.append({"ty": int(ty), "tx": int(tx), "n": int(len(g)), "file": name})
    return index


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modis", nargs="+", required=True)
    ap.add_argument("--viirs", nargs="+", required=True)
    ap.add_argument("--viirs-nrt", nargs="*", default=[],
                    help="VIIRS S-NPP NRT CSVs for months after the standard archive")
    ap.add_argument("--until", default=None,
                    help="Last complete month to keep, YYYY-MM (drops partial months at the end)")
    ap.add_argument("--out", default="web/data")
    ap.add_argument("--reports", default="reports")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.reports, exist_ok=True)

    log("1) Load and clean")
    mod, s_mod = load(args.modis, "MODIS")
    vii, s_vii = load(args.viirs, "VIIRS")
    s_nrt = None
    if args.viirs_nrt:
        nrt, s_nrt = load(args.viirs_nrt, "VIIRS")
        last_sp = vii.month.max()
        nrt = nrt[nrt.month > last_sp]
        # NRT has no "type" flag: drop detections on ~1 km cells that the standard
        # archive flagged as static sources (industry, gas flares), volcanoes or offshore.
        sp = pd.concat([pd.read_csv(p, usecols=["latitude", "longitude", "type"]) for p in args.viirs])
        sp = sp[sp["type"] != 0]
        static = set(zip(np.round(sp.latitude, 2), np.round(sp.longitude, 2)))
        is_static = np.array([(a, b) in static for a, b in
                              zip(np.round(nrt.latitude, 2), np.round(nrt.longitude, 2))], dtype=bool)
        log(f"   NRT: removed {int(is_static.sum()):,} detections on known static-source cells")
        nrt = nrt[~is_static]
        s_nrt["kept"] = int(len(nrt))
        vii = pd.concat([vii, nrt], ignore_index=True)
        log(f"   VIIRS NRT adds {len(nrt):,} hotspots after {last_sp}")
    nrt_from = str(last_sp + 1) if args.viirs_nrt else None
    if args.until:
        until = pd.Period(args.until, "M")
        mod, vii = mod[mod.month <= until], vii[vii.month <= until]
        log(f"   keeping months up to {until}")
    mod, vii = add_keys(mod), add_keys(vii)

    log("2) Grid 0.1° × month × day/night")
    mod_sat = grid_counts(mod, by_sat=True)
    mod_c = grid_counts(mod)
    vii_c = grid_counts(vii)
    mod_c["_all"] = 0
    vii_c["_all"] = 0

    log("3) Terra-only period → Terra+Aqua equivalent")
    ref = mod_sat[mod_sat.month.dt.year.between(2003, 2011)]
    ta = ref.groupby(["ry", "rx", "dn"]).n.sum()
    terra = ref[ref.sat == "Terra"].groupby(["ry", "rx", "dn"]).n.sum()
    both = pd.concat([ta.rename("t"), terra.rename("s")], axis=1).fillna(0)
    nat_terra = both.groupby(level="dn").sum()
    nat_terra["k"] = nat_terra.t / nat_terra.s
    alpha = 300
    both["k"] = (both.t + alpha * both.index.get_level_values("dn").map(nat_terra.k)) / (both.s + alpha)
    early = mod_c.month <= TERRA_ONLY_END
    k_early = both.k.reindex(pd.MultiIndex.from_frame(mod_c.loc[early, ["ry", "rx", "dn"]])).values
    k_early = np.where(np.isnan(k_early), mod_c.loc[early, "dn"].map(nat_terra.k).values, k_early)
    mod_c["n_eq"] = mod_c.n.astype(float)
    mod_c.loc[early, "n_eq"] = mod_c.loc[early, "n"].values * k_early
    log(f"   national Terra→Terra+Aqua factor: day {nat_terra.k.get('D', np.nan):.2f}, "
        f"night {nat_terra.k.get('N', np.nan):.2f}")

    log("4-5) Validate VIIRS→MODIS methods (leave-one-year-out, 2012–2021)")
    yrs = list(range(CALIB_YEARS[0], CALIB_YEARS[1] + 1))
    cal_m = mod_c[mod_c.month.dt.year.isin(yrs)][["cy", "cx", "ry", "rx", "_all", "month", "dn", "n"]]
    cal_v = vii_c[vii_c.month.dt.year.isin(yrs)]
    val = validate(cal_m, cal_v, yrs)
    for sc, res in val["scales"].items():
        log(f"   {sc}:")
        for m, r in res.items():
            log(f"      {m:45s} WAPE {r['wape_pct']:6.1f}%  bias {r['bias_pct']:6.1f}%  r {r['pearson_r']}")
    best = val["best_method"]
    log(f"   → best: {best}")

    keys, alpha_v, dn = METHODS[best]
    model = fit_ratio(cal_m, cal_v, keys, alpha_v, dn)
    vii_c["n_eq"] = apply_ratio(model, vii_c)
    nat_k = {str(k): round(float(v), 4) for k, v in model["national"].items()}
    log(f"   national VIIRS→MODIS factor: {nat_k}")

    log("5b) Uncertainty ranges from leave-one-year-out predictions")
    unc = {"viirs": interval_table(loyo_pairs(cal_m, cal_v, keys, alpha_v, dn, yrs))}
    ta_c = mod_sat[mod_sat.month.dt.year.between(2003, 2011)].groupby(
        ["cy", "cx", "ry", "rx", "month", "dn"]).n.sum().reset_index()
    te_c = mod_sat[mod_sat.month.dt.year.between(2003, 2011) & (mod_sat.sat == "Terra")].groupby(
        ["cy", "cx", "ry", "rx", "month", "dn"]).n.sum().reset_index()
    unc["terra"] = interval_table(loyo_pairs(ta_c, te_c, ["ry", "rx"], 300, True, list(range(2003, 2012))))
    for k, u in unc.items():
        m = {e: b[:2] for e, b in zip(UNC_EDGES, u["monthly"])}
        log(f"   {k}: monthly 80% range of observed/estimated at 10 → {m[10]}, 100 → {m[100]}, 1000 → {m[1000]}")

    # Post-calibration check: does MODIS drift away from VIIRS-equivalent after 2021?
    yearly = pd.DataFrame({
        "modis_observed": mod_c.groupby(mod_c.month.dt.year).n.sum(),
        "viirs_raw": vii_c.groupby(vii_c.month.dt.year).n.sum(),
        "viirs_as_modis_eq": vii_c.groupby(vii_c.month.dt.year).n_eq.sum(),
    }).round(0)
    yearly["diff_pct"] = ((yearly.viirs_as_modis_eq / yearly.modis_observed - 1) * 100).round(1)

    log("6) Build harmonized series (MODIS era + VIIRS era)")
    m_era = mod_c[mod_c.month < VIIRS_START]
    v_era = vii_c[vii_c.month >= VIIRS_START]
    keys_c = ["cy", "cx", "month"]
    h = pd.concat([m_era.groupby(keys_c).n_eq.sum().rename("harmonized"),
                   mod_c.groupby(keys_c).n.sum().rename("modis"),
                   vii_c.groupby(keys_c).n.sum().rename("viirs")], axis=1).fillna(0).reset_index()
    v_h = v_era.groupby(keys_c).n_eq.sum()
    hi = pd.MultiIndex.from_frame(h[keys_c])
    h["harmonized"] = h.harmonized.values + v_h.reindex(hi).fillna(0).values
    h = h[(h.harmonized > 0) | (h.modis > 0) | (h.viirs > 0)].sort_values(["month", "cy", "cx"])
    months_all = pd.period_range(mod.month.min(), vii.month.max(), freq="M")

    # Coverage: a run of OUTAGE_MIN_RUN or more consecutive days with no detection at all over
    # Argentina means the satellite did not deliver data (e.g. Terra June 2001, S-NPP July–Aug
    # 2022 and July 2024 safe-holds). Isolated empty days are kept as real: in winter, and with
    # Terra alone in 2000–02, a day without any fire is plausible. The harmonized value of an
    # outage month is scaled by days / days-with-data.
    OUTAGE_MIN_RUN = 3

    def missing_days(df, first_day, min_run=OUTAGE_MIN_RUN):
        have = set(df.date.dt.normalize().unique())
        days = pd.date_range(first_day, df.date.max().normalize() + pd.offsets.MonthEnd(0), freq="D")
        miss = pd.Series([d not in have for d in days], index=days)
        run_id = (miss != miss.shift()).cumsum()
        run_len = miss.groupby(run_id).transform("size")
        outage = miss & (run_len >= min_run)
        isolated = miss & ~outage
        out = outage.groupby(days.to_period("M")).agg(["sum", "size"])
        out["isolated"] = isolated.groupby(days.to_period("M")).sum()
        return out
    gaps, isolated_kept = {}, 0
    for sensor, df, first, era in (("MODIS", mod, mod.date.min().normalize(), lambda m: m < VIIRS_START),
                                   ("VIIRS", vii, pd.Timestamp("2012-01-01"), lambda m: m >= VIIRS_START)):
        md = missing_days(df, first)
        for m, r in md.iterrows():
            if not era(m):
                continue
            isolated_kept += int(r["isolated"])
            if r["sum"] > 0:
                gaps[str(m)] = {"sensor": sensor, "missing_days": int(r["sum"]), "days": int(r["size"])}
    log(f"   outage rule: runs of ≥{OUTAGE_MIN_RUN} empty days; {isolated_kept} isolated empty days kept as real")
    factor = h.month.astype(str).map(lambda m: gaps[m]["days"] / (gaps[m]["days"] - gaps[m]["missing_days"])
                                     if m in gaps and gaps[m]["days"] > gaps[m]["missing_days"] else 1.0)
    h["harmonized"] = h.harmonized * factor.values
    log(f"   coverage correction applied to {len(gaps)} months with missing satellite days")

    nat = h.groupby("month")[["harmonized", "modis", "viirs"]].sum().reindex(months_all, fill_value=0)
    log(f"   {len(h):,} cell-month records, {months_all[0]}..{months_all[-1]}")

    log("   writing grid.bin.gz")
    write_grid_bin(os.path.join(args.out, "grid.bin.gz"), h[["cy", "cx"]], h.month,
                   [h.harmonized.values.astype(np.float32), h.modis.values.astype(np.float32),
                    h.viirs.values.astype(np.float32)])

    log("   writing raw hotspot tiles")
    raw = pd.concat([mod, vii], ignore_index=True)
    tiles = write_tiles(os.path.join(args.out, "tiles"), raw)

    meta = {
        "title": "Harmonized burning activity calendar — Argentina",
        "unit": "MODIS-equivalent hotspots (Terra+Aqua)",
        "cell_deg": CELL, "tile_deg": TILE,
        "first_month": str(months_all[0]), "last_month": str(months_all[-1]),
        "layers": ["harmonized", "modis", "viirs"],
        "eras": [
            {"from": str(months_all[0]), "to": str(TERRA_ONLY_END), "source": "MODIS Terra, scaled to Terra+Aqua"},
            {"from": "2002-07", "to": str(VIIRS_START - 1), "source": "MODIS Terra+Aqua (observed)"},
            {"from": str(VIIRS_START), "to": str(pd.Period(nrt_from, "M") - 1) if nrt_from else str(months_all[-1]),
             "source": "VIIRS S-NPP, converted to MODIS-equivalent"},
        ] + ([{"from": nrt_from, "to": str(months_all[-1]),
               "source": "VIIRS S-NPP near-real-time, converted to MODIS-equivalent"}] if nrt_from else []),
        "method": best,
        "gaps": gaps,
        "gaps_rule": "a month is scaled only for runs of 3 or more consecutive days with no detection over Argentina",
        "uncertainty": unc,
        "national_factors": {"viirs_to_modis": nat_k,
                             "terra_to_terra_aqua": {str(k): round(float(v), 4) for k, v in nat_terra.k.items()}},
        "validation": {sc: {m: r for m, r in res.items()} for sc, res in val["scales"].items()},
        "cleaning": {"MODIS": s_mod, "VIIRS": s_vii, "VIIRS_NRT": s_nrt},
        "tiles": tiles,
        "generated": time.strftime("%Y-%m-%d %H:%M"),
    }
    with open(os.path.join(args.out, "meta.json"), "w") as f:
        json.dump(meta, f, separators=(",", ":"))

    nat_out = nat.reset_index().rename(columns={"index": "month"})
    nat_out["month"] = nat_out.month.astype(str)
    nat_out.round(1).to_csv(os.path.join(args.reports, "national_monthly.csv"), index=False)
    yearly.to_csv(os.path.join(args.reports, "yearly_sensor_comparison.csv"))
    with open(os.path.join(args.reports, "validation.json"), "w") as f:
        json.dump(val, f, indent=2)
    log("done")
    print(yearly.to_string())


if __name__ == "__main__":
    main()
