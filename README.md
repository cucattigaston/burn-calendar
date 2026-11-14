# Burn Calendar — harmonized MODIS + VIIRS fire hotspots

**NASA Space Apps Challenge 2026 · Harmonization of MODIS and VIIRS Hot Spots (challenge proposed by CONAE, Argentina)**

Burn Calendar turns 25 years of satellite fire hotspots into one consistent record and shows it as a
burning-activity calendar for any area you choose. Emergency managers, firefighters, scientists and land
managers can see which months of the year usually burn, which years were exceptional, and how the
current month compares with a normal one.

**Live app:** https://cucattigaston.github.io/burn-calendar/ · **Demo slides:** [docs/demo/burn-calendar-demo.pdf](docs/demo/burn-calendar-demo.pdf) · **Coverage:** Argentina, November 2000 → October 2026

![Calendar screenshot](docs/screenshot.png)

## What you can do

- **Choose an area:** draw a rectangle or polygon on the map, pick an example area, or type a
  bounding box in decimal degrees.
- **Choose dates** and the years that define "normal". By default, normal is the 2003–2022 median for each
  calendar month.
- **Read the calendar:** years run down the rows and months across the columns, with an accessible ember
  colour ramp. Switch to *Compared with normal* to see each month as a ratio to the median of the same
  month, with teal for below normal and ember for above. A thin strip beside each year shows whether the
  month comes from MODIS or from converted VIIRS.
- **Get the key figures:**
  - total hotspots in the selected range;
  - the latest (or clicked) month against a normal month;
  - the usual fire season;
  - the most active year;
  - a ranking of the busiest months;
  - a chart of the selected year against the median year and the interquartile band;
  - hotspots per year.
- **Download:**
  - the raw hotspots inside your area and dates (CSV, both sensors);
  - the harmonized monthly series (CSV, with source and ratio to normal);
  - each chart (PNG).

## The harmonization

MODIS (Terra + Aqua, 1 km pixels, since 2000) is being retired. VIIRS (375 m pixels, since 2012) continues
the record but sees more and smaller fires, so it reports about **3.2× as many hotspots** as MODIS for the
same activity in Argentina. Adding them as they are would invent a fire boom in 2012.

Burn Calendar expresses every month in **MODIS-equivalent hotspots** (what Terra + Aqua would have
counted):

| Period | Source |
|---|---|
| Nov 2000 – Jun 2002 | MODIS Terra only, scaled to Terra + Aqua with regional day/night ratios learned in 2003–2011 |
| Jul 2002 – Dec 2011 | MODIS Terra + Aqua, observed |
| Jan 2012 – Jul 2026 | VIIRS S-NPP (standard processing), converted to MODIS-equivalent |
| Aug 2026 – Oct 2026 | VIIRS S-NPP near-real-time, converted to MODIS-equivalent |

**Conversion.** Hotspots are first cleaned. MODIS needs confidence ≥ 30 and VIIRS needs nominal or high
confidence; in both, only FIRMS `type = 0` (vegetation and land fires) is kept, which removes volcanoes,
static industrial sources and offshore detections. They are then counted on a 0.1° grid by month and by
day or night overpass. For each 2° region and overpass, a factor *k = MODIS / VIIRS* is learned over the
clean overlap years 2012–2021, chosen to avoid the Terra/Aqua orbit drift of the final mission years. The
factors are shrunk toward the national factor (prior weight 300 VIIRS hotspots), so regions with few fires
stay stable. National factors are 0.37 for day and 0.15 for night: VIIRS sees many small night fires that
MODIS misses.

**Satellite outages.** On some days a satellite delivered no data at all over Argentina: Terra in mid-2001 and
early 2002, and S-NPP in July–August 2022, July 2024 and a few days of 2026. For those months the
harmonized value is scaled by *days in month ÷ days with data*. The calendar marks every month with 3 or
more missing days, and the tooltip says how many days were missing. January 2012, when VIIRS starts on the
20th, is handled the same way.

**Validation (leave one year out).** Each year from 2012 to 2021 was hidden in turn. The factors were
learned from the other nine years and used to predict the hidden year's MODIS counts from VIIRS. The table
shows the weighted absolute error of monthly counts:

| Method | National | Region (2°) | Local (0.5°) |
|---|---|---|---|
| Raw VIIRS (no harmonization) | 224.8 % | 226.5 % | 231.0 % |
| National ratio | 9.9 % | 22.2 % | 37.6 % |
| National ratio, day/night | 9.5 % | 22.3 % | 37.7 % |
| Regional ratio (2°) | 8.4 % | 19.7 % | 35.9 % |
| **Regional, day/night, shrinkage (used)** | **7.5 %** | **18.7 %** | **35.7 %** |

National bias after harmonization is below 1 %. Year by year, converted VIIRS stays within about ±10 % of
observed MODIS from 2012 to 2025 (`reports/yearly_sensor_comparison.csv`), with no jump at the switch.

**Limitations.**
- Hotspots measure burning activity, not burned area.
- Cloud and smoke hide fires differently for each sensor.
- Error grows for very small areas, because monthly counts of a few hotspots are noisy for any sensor.
- Near-real-time months (August–October 2026) lack FIRMS' `type` flag. Instead, detections on ~1 km cells
  that the standard archive flagged as static sources are removed. Later reprocessing may change these
  months slightly.
- An outage-day correction assumes the missing days were as active as the rest of the month.

## Run it yourself

```bash
pip install pandas numpy
# 1. Download FIRMS yearly country files for Argentina (MODIS C6.1 and VIIRS S-NPP) from
#    https://firms.modaps.eosdis.nasa.gov/country/ and combine them per sensor.
#    For the current year, use the FIRMS area API (free MAP_KEY) with VIIRS_SNPP_SP and
#    VIIRS_SNPP_NRT, then keep only points inside Argentina:
#    python pipeline/clip_to_country.py box.csv raw/viirs_snpp_SP_2026_ARG.csv.gz
# 2. Build the harmonized data used by the web app:
python pipeline/harmonize.py \
  --modis raw/firms_modis_ARG_2000_2025.csv.gz \
  --viirs raw/firms_viirs_snpp_ARG_2012_2025.csv.gz raw/viirs_snpp_SP_2026_ARG.csv.gz \
  --viirs-nrt raw/viirs_snpp_NRT_2026_ARG.csv.gz --until 2026-10 \
  --out web/data --reports reports
# 3. Serve the static site
cd web && python -m http.server 8000
```

The app is a static site with no server or build step:
- `web/data/grid.bin.gz` (≈3 MB) holds the harmonized 0.1° × month grid;
- `web/data/tiles/` holds the raw hotspots in 1° tiles for CSV export;
- `web/data/meta.json` holds the eras, factors and validation.

## Data and credits

- **NASA FIRMS** (Fire Information for Resource Management System, LANCE / NASA Earthdata):
  - MODIS Collection 6.1 active fire / thermal anomalies, 1 km (MCD14), DOI 10.5067/FIRMS/MODIS/MCD14ML;
  - VIIRS S-NPP 375 m active fire, standard (DOI 10.5067/FIRMS/VIIRS/VNP14IMGT.002) and near-real-time
    (DOI 10.5067/FIRMS/VIIRS/VNP14IMGT_NRT.002).
- **Challenge:** CONAE (Comisión Nacional de Actividades Espaciales, Argentina).
- **Boundary:** Argentina from Natural Earth 1:10m (public domain), via world-atlas. It agrees with 99.99%
  of FIRMS' own Argentina assignments for 2025.
- **Libraries:** D3 (ISC), Leaflet (BSD-2), Leaflet.draw (MIT), Archivo typeface (SIL OFL). All are bundled
  in `web/vendor`.
- **Basemap:** © OpenStreetMap contributors.

## Use of AI

This project was built with help from **Claude (Anthropic)**, an AI assistant. It was used to:
- help write and debug the Python pipeline and the web application code;
- compare harmonization methods;
- draft this README.

All code and text generated with AI assistance is marked as such in this README and in the file headers.
The data, validation numbers and figures come from running the code on NASA FIRMS data. No AI-generated
images are used.

## License

MIT (code). Data remain subject to NASA FIRMS terms of use.
