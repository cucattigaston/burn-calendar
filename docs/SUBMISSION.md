# Space Apps project page — text to paste

## Project Name
Burn Calendar

## High-Level Project Summary
Burn Calendar is a web application that harmonizes 25 years of NASA FIRMS active-fire hotspots from MODIS
(2000–) and VIIRS (2012–) into one consistent record, and shows it as a burning-activity calendar for any
area the user draws or types.

VIIRS reports about 3.2× as many hotspots as MODIS for the same fires in Argentina, so joining the records
as they are invents a fire boom in 2012. We convert every month into MODIS-equivalent hotspots with
regional, day/night conversion factors learned where both sensors overlap. Leave-one-year-out validation
cuts the national monthly error from 225% (raw VIIRS) to 7.5%.

Emergency managers can then see:
- which months usually burn;
- which years were exceptional;
- how the current month compares with a normal month.

Users can also download the hotspots and charts. As MODIS is retired in 2026–27, this keeps the 25-year
baseline usable.

## Link to Project Demo
<link to docs/demo/burn-calendar-demo.pdf in the GitHub repository>

## Link to Final Project
<GitHub Pages link>  (code: <GitHub repository link>)

## Detailed Project Description
**What it does.**
- **Choose an area:** draw a rectangle or polygon on a map, pick an example area, or type a bounding box.
- **Choose a date range,** and the years that define "normal" (default 2003–2022).
- **Read the calendar:**
  - years run down the rows and months across the columns, coloured with an accessible ember ramp;
  - a "Compared with normal" mode colours each month by its ratio to the median of the same calendar
    month (teal below, ember above);
  - a strip beside each year shows whether that period comes from observed MODIS or converted VIIRS.
- **Key figures:**
  - total hotspots;
  - the latest or clicked month against a normal month, with its rank among all such months since 2001;
  - the usual fire season and the most active year;
  - a ranking of the busiest months;
  - a chart of the selected year against the median year and the interquartile range;
  - hotspots per year.
- **Downloads:**
  - the raw hotspots inside the area and dates (CSV);
  - the harmonized monthly series (CSV, with source and ratio to normal);
  - each chart (PNG).

**How it works.** A Python pipeline (pandas) does the harmonization:
1. Cleans the FIRMS standard-processing hotspots for Argentina:
   - MODIS C6.1 with confidence ≥ 30;
   - VIIRS S-NPP 375 m with nominal or high confidence;
   - in both, only type 0 (vegetation and land fires); volcanoes, static industrial sources and offshore
     detections are dropped.
2. Counts hotspots on a 0.1° grid by month and by day or night overpass.
3. Learns MODIS ÷ VIIRS factors for each 2° region and overpass over 2012–2021. This is the clean overlap,
   before the Terra/Aqua orbit drift of the final mission years. Factors are shrunk toward the national
   factor (day 0.37, night 0.15) where fires are few.
4. Scales the Terra-only months of 2000–02 to Terra + Aqua the same way.
5. Joins the eras: MODIS observed until 2011, VIIRS converted from 2012. 2026 comes from the FIRMS API,
   using standard data through July and near-real-time data for August–October, clipped to Argentina.
   Months with satellite outage days are scaled to their full length and flagged.
6. Validates by hiding each year from 2012 to 2021, learning factors from the other years, and predicting
   the hidden year's MODIS counts. Four methods are compared at national, 2° and 0.5° scales.

| Scale | Raw VIIRS error | Harmonized error |
|---|---|---|
| National | 225% | 7.5% |
| 2° region | 227% | 18.7% |

National bias is under 1%, and converted VIIRS stays within ±10% of observed MODIS each year from 2012 to
2025.

The web app is static, with no server and no build step:
- a 3 MB binary grid, decoded in the browser;
- 1° tiles of raw hotspots for CSV export;
- D3 and Leaflet.

**Benefits.**
- A consistent baseline that does not break when a sensor changes.
- Anomalies against the median rather than the mean, so a few catastrophic years do not distort "normal".
- Runs from any static host.
- Every number traces back to public NASA data and an open script.

It also answers "is this month unusual?" for the present. January–October 2026 ran at about 45% of a
normal year in Argentina, and August 2026 at only 20% of a normal August. NOAA-20 VIIRS, an independent
satellite, confirms the drop.

The calendar recovers known disasters at a glance:
- Paraná Delta: August 2020 was 31× a normal August, and 2008 was 11.5× the median year.
- Northern Andean Patagonia: 2015 (Cholila fire) was 24× the median year.
- Corrientes: 2022 was 2.1× the median year.

**What we hope to achieve.** We want a tool CONAE and provincial fire services can use to anticipate
critical periods and judge whether current activity is unusual. Next steps:
- add NOAA-20 and NOAA-21 VIIRS;
- extend coverage to South America;
- update automatically each month and alert when an area runs above normal.

**Tools.** Python (pandas, NumPy), JavaScript, D3, Leaflet, Leaflet.draw, Archivo typeface, GitHub Pages.

## Use of Super Intelligence (SI)
Yes. We used Claude (Anthropic), an AI assistant, as a coding and writing tool:
- to help write and debug the Python pipeline and the web application;
- to suggest and test harmonization variants, which we then compared with leave-one-year-out validation;
- to draft documentation and slide text.

The data, validation numbers and figures come from running the code on NASA FIRMS data. All AI-assisted
code is marked in file headers and in the README. No AI-generated images or audio are used.

## NASA Data
- **NASA FIRMS** (Fire Information for Resource Management System, LANCE / NASA Earthdata):
  - MODIS Collection 6.1 active fire / thermal anomalies, 1 km, Terra and Aqua
    (DOI 10.5067/FIRMS/MODIS/MCD14ML), Argentina, 2000–2025;
  - VIIRS S-NPP 375 m active fire, standard (DOI 10.5067/FIRMS/VIIRS/VNP14IMGT.002) and near-real-time
    (DOI 10.5067/FIRMS/VIIRS/VNP14IMGT_NRT.002), Argentina, 2012 to October 2026;
  - FIRMS area API with a free MAP_KEY, used for 2026.
- FIRMS yearly country files: https://firms.modaps.eosdis.nasa.gov/country/

## Space Agency Partner Data and Other References
- CONAE (National Space Activities Commission of Argentina): challenge statement and its hotspot
  catalogue (Catálogo de Focos de Calor), used as a reference for the problem.
- D3 (ISC), Leaflet (BSD-2), Leaflet.draw (MIT), Archivo typeface (SIL OFL). All open source and bundled
  in the repository.
- Argentina boundary: Natural Earth 1:10m (public domain), via world-atlas.
- Basemap tiles © OpenStreetMap contributors © CARTO.
