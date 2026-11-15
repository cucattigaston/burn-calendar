#!/usr/bin/env python3
"""
Comparison with CONAE's hotspot catalogue (Catálogo de Focos de Calor, catalogos5.conae.gov.ar).
CONAE runs its own MODIS processing chain (contextual algorithm, Giglio et al.) on Aqua data
received for Argentina. We downloaded monthly totals by province (Aqua, confidence ≥ 50) for
July 2002 – October 2026.

Checks
  1. Agreement of processing chains: CONAE Aqua vs FIRMS Aqua (same satellite, same threshold).
  2. Continuity of our harmonized series: harmonized ÷ CONAE-Aqua should stay flat
     across the 2012 MODIS→VIIRS switch and through 2026.

AI disclosure: written with assistance from Claude (Anthropic), an AI assistant.

    python pipeline/validate_conae.py raw/external/conae_aqua_monthly_prov_2002_2026.csv raw/firms_modis_ARG_2000_2025.csv.gz
"""
import json
import sys

import numpy as np
import pandas as pd

conae = pd.read_csv(sys.argv[1], encoding="latin-1")
conae.columns = ["sat", "inst", "prov", "month", "n"]
cm = conae.groupby("month").n.sum().rename("conae_aqua")

firms = pd.read_csv(sys.argv[2], usecols=["acq_date", "satellite", "confidence", "type"])
firms = firms[(firms.satellite.str.upper().str.startswith("A")) & (pd.to_numeric(firms.confidence, errors="coerce") >= 50)]
firms["month"] = firms.acq_date.str[:7]
fa_all = firms.groupby("month").size().rename("firms_aqua_all_types")
fa_veg = firms[firms["type"] == 0].groupby("month").size().rename("firms_aqua_vegetation")

nat = pd.read_csv("reports/national_monthly.csv").set_index("month")
d = pd.concat([cm, fa_all, fa_veg, nat.harmonized], axis=1).dropna(subset=["conae_aqua"]).fillna(0)
d = d[d.index >= "2002-07"]


def stats(a, b, mask):
    x, y = d.loc[mask, a], d.loc[mask, b]
    ok = (x > 0) & (y > 0)
    return {"ratio_of_totals": round(float(y.sum() / x.sum()), 3),
            "pearson_r_monthly": round(float(np.corrcoef(x, y)[0, 1]), 3),
            "pearson_r_log": round(float(np.corrcoef(np.log(x[ok]), np.log(y[ok]))[0, 1]), 3),
            "n_months": int(mask.sum())}


m_overlap = (d.index >= "2002-07") & (d.index <= "2023-12")
res = {"source": "CONAE Catálogo de Focos de Calor, Aqua MODIS, confidence ≥ 50, monthly totals by province "
                 "(summed), 2002-07..2026-10. CONAE labels the instrument column 'VIIRS' for Aqua rows; "
                 "the satellite is Aqua (MODIS).",
       "conae_vs_firms_aqua_all_types": stats("conae_aqua", "firms_aqua_all_types", m_overlap),
       "conae_vs_firms_aqua_vegetation": stats("conae_aqua", "firms_aqua_vegetation", m_overlap)}

# Continuity: harmonized / CONAE-Aqua by year, relative to the MODIS era (2003-2011)
d["year"] = d.index.str[:4].astype(int)
yr = d.groupby("year")[["harmonized", "conae_aqua"]].sum()
yr["ratio"] = yr.harmonized / yr.conae_aqua
ref = yr.loc[2003:2011, "ratio"].mean()
yr["ratio_rel"] = (yr.ratio / ref).round(3)
res["harmonized_over_conae_relative_to_2003_2011"] = {int(y): float(v) for y, v in yr.ratio_rel.items()}
res["mean_relative"] = {
    "2003-2011 (MODIS era)": 1.0,
    "2012-2021 (VIIRS era, calibration years)": round(float(yr.loc[2012:2021, "ratio_rel"].mean()), 3),
    "2022-2023 (VIIRS era, after calibration window)": round(float(yr.loc[2022:2023, "ratio_rel"].mean()), 3)}
# From 2024 CONAE's catalogue holds far fewer Aqua hotspots than FIRMS Aqua: a catalogue gap, not a fire signal
fy = d.groupby("year")[["conae_aqua", "firms_aqua_all_types"]].sum()
res["conae_catalogue_vs_firms_aqua_by_year_2018_2025"] = {
    int(y): round(float(r.conae_aqua / r.firms_aqua_all_types), 2) for y, r in fy.loc[2018:2025].iterrows()}
res["log_correlation_harmonized_vs_conae_2012_2023"] = round(float(np.corrcoef(
    np.log(d.loc[(d.year >= 2012) & (d.year <= 2023) & (d.harmonized > 0) & (d.conae_aqua > 0), "harmonized"]),
    np.log(d.loc[(d.year >= 2012) & (d.year <= 2023) & (d.harmonized > 0) & (d.conae_aqua > 0), "conae_aqua"]))[0, 1]), 3)

json.dump(res, open("reports/validation_conae.json", "w"), indent=2, ensure_ascii=False)
print(json.dumps({k: v for k, v in res.items() if k != "harmonized_over_conae_relative_to_2003_2011"}, indent=2, ensure_ascii=False))
print(yr[["harmonized", "conae_aqua", "ratio_rel"]].round(0).to_string())
