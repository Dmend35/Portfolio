# Cook County Heat Vulnerability

**Applied spatial econometrics and an LLM agent interface for climate equity in Cook County, Illinois.**

This project measures where summer heat concentrates across Cook County's 1,331 land census tracts, who lives there, and how much tree canopy and impervious surface explain the pattern, *neighborhood by neighborhood*. The results are served through three interfaces: a spatial SQL database, a [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that lets an LLM agent query the results, and an interactive Leaflet web dashboard.

![Mean summer 2022 land surface temperature by census tract](figures/lst_preview.png)

---

## Contents

- [Project overview and objectives](#project-overview-and-objectives)
- [Architecture](#architecture)
- [Data sources](#data-sources)
- [Methodology](#methodology)
- [Key spatial insights](#key-spatial-insights)
- [Installation and reproducibility](#installation-and-reproducibility)
- [Using the MCP server](#using-the-mcp-server)
- [Limitations](#limitations)
- [Repository layout](#repository-layout)

---

## Project overview and objectives

Extreme heat is the deadliest weather hazard in the United States, and its burden is not evenly shared. Within one county, surface temperatures can differ by more than 15 °C between a forest-preserve edge and a treeless industrial corridor. Those differences often line up with historical disinvestment and present-day socioeconomic disadvantage.

This project asks three questions:

1. **Where is heat clustered?** Are hot tracts randomly scattered, or do they form statistically significant hotspots?
2. **Who is exposed?** How do hotspot neighborhoods differ in income, poverty, race/ethnicity, age and housing tenure?
3. **What drives heat locally, and does that vary across space?** Is the cooling effect of tree canopy the same everywhere, or are there places where an additional tree buys more cooling than elsewhere?

**Objectives:**

| # | Objective | Approach |
|---|---|---|
| 1 | Build a tract-level heat-vulnerability dataset from public APIs | Census TIGER + ACS 5-Year, Landsat 8/9 thermal imagery, NLCD canopy and imperviousness |
| 2 | Reduce correlated socioeconomic indicators to interpretable indices | VIF diagnostics, then principal component analysis (PCA) |
| 3 | Test for spatial clustering of heat | Global Moran's *I* and Local Moran's *I* (LISA) |
| 4 | Model spatially varying drivers of heat | OLS baseline vs. geographically weighted regression (GWR) |
| 5 | Make results queryable by an LLM agent | DuckDB Spatial + an MCP server with three spatial tools |
| 6 | Communicate results to non-specialists | Single-page Leaflet + Chart.js dashboard |

---

## Architecture

```
 ┌──────────────────────────────────────────────────────────────────────────────────────┐
 │  1. DATA EXTRACTION                                                                  │
 │                                                                                      │
 │   01_fetch_cook_county.py        02_fetch_demographics.py     03_fetch_environmental.py
 │   ┌──────────────────────┐       ┌──────────────────────┐     ┌──────────────────────┐
 │   │ Census TIGER/Line    │       │ ACS 2022 5-Year API  │     │ Planetary Computer   │
 │   │ 2022 tracts (pygris) │       │ income, poverty,     │     │  STAC: Landsat 8/9   │
 │   │ → EPSG:32616 (UTM)   │       │ race, age 65+, rent  │     │  summer LST composite│
 │   └──────────┬───────────┘       └──────────┬───────────┘     │ MRLC WCS: NLCD 2021  │
 │              │                              │                 │  canopy, impervious  │
 │              │                              │                 │ zonal mean over land │
 │              │                              │                 └──────────┬───────────┘
 │              ▼                              ▼                            ▼
 │      cook_county_base.gpkg ──────► cook_county_vulnerability.gpkg ◄─────┘
 └──────────────────────────────────────────────┬───────────────────────────────────────┘
                                                │
 ┌──────────────────────────────────────────────▼───────────────────────────────────────┐
 │  2. FEATURE ENGINEERING & ESDA                         04_esda_and_pca.py            │
 │     VIF ─► standardized PCA (deprivation, age indices)                               │
 │     Queen contiguity W ─► Global Moran's I ─► LISA clusters (HH / LL / HL / LH)      │
 │                                             ─► cook_county_processed.gpkg            │
 └──────────────────────────────────────────────┬───────────────────────────────────────┘
                                                │
 ┌──────────────────────────────────────────────▼───────────────────────────────────────┐
 │  3. SPATIAL REGRESSION                                 05_fit_gwr.py                 │
 │     LST ~ tree canopy + deprivation + impervious                                     │
 │     Global OLS baseline ─► adaptive bisquare GWR (AICc bandwidth)                    │
 │     local β, SE, t, corrected significance, local R², condition number               │
 │                                             ─► cook_county_gwr_results.gpkg          │
 └──────────────┬───────────────────────────────────────────────────────┬───────────────┘
                │                                                       │
 ┌──────────────▼──────────────────────────────┐   ┌────────────────────▼───────────────┐
 │  4. SPATIAL DATABASE                        │   │  6. WEB DASHBOARD                  │
 │     06_spatial_mcp_server.py --load         │   │     07_export_dashboard.py         │
 │     DuckDB Spatial: cook_county.duckdb      │   │     simplified GeoJSON (~1 MB)     │
 │     table cook_county_gwr                   │   │     Leaflet map, 4 layers          │
 │     (PostGIS-style ST_* SQL)                │   │     Chart.js tract inspector       │
 └──────────────┬──────────────────────────────┘   │     dashboard/index.html           │
                │                                  └────────────────────────────────────┘
 ┌──────────────▼──────────────────────────────┐
 │  5. MCP SERVER (stdio)                      │
 │     06_spatial_mcp_server.py                │        ┌────────────────────────────┐
 │     • get_tract_vulnerability(geoid)        │◄──────►│ LLM agent                  │
 │     • find_hotspots(metric, top_n)          │  MCP   │ (Claude Code, Claude       │
 │     • query_spatial_stats(sql_query)        │        │  Desktop, any MCP client)  │
 │     read-only, sandboxed connection         │        └────────────────────────────┘
 └─────────────────────────────────────────────┘
```

Each stage reads only the output file of the stage before it, so any step can be re-run on its own.

---

## Data sources

| Dataset | Provider | Access | Used for |
|---|---|---|---|
| 2022 TIGER/Line census tracts and area water | U.S. Census Bureau | `pygris` | Tract geometry; water masking |
| ACS 2022 5-Year estimates (B19013, B17001, B03002, B01001, B25003) | U.S. Census Bureau | Census Data API | Socioeconomic predictors |
| Landsat 8/9 Collection 2 Level-2 surface temperature (`ST_B10`), Jun–Aug 2022 | USGS, via Microsoft Planetary Computer | STAC API | Land surface temperature |
| NLCD 2021 Tree Canopy Cover (v2021-4) | USFS / MRLC | MRLC WCS | % tree canopy |
| NLCD 2021 Impervious Surface | USGS / MRLC | MRLC WCS | % impervious surface |
| OpenStreetMap | OSM contributors | Tile server | Dashboard basemap |

---

## Methodology

### 1. Building the dataset

**Geography.** The study area is the 1,332 Cook County census tracts from the 2022 full TIGER/Line boundaries, projected to **EPSG:32616 (WGS 84 / UTM 16N)** so distances and areas are in meters. One tract (`17031990000`) lies entirely in Lake Michigan. It has no land pixels and no residents, so it is excluded from all spatial statistics and modeling, which leaves **n = 1,331**.

**Socioeconomic predictors** come from the ACS 2022 5-Year estimates:

| Variable | Definition |
|---|---|
| `median_income` | B19013_001 |
| `poverty_rate` | B17001_002 / B17001_001 × 100 |
| `minority_rate` | (B03002_001 − B03002_003) / B03002_001 × 100 (everyone other than non-Hispanic white) |
| `elderly_rate` | Σ B01001 age 65+ cells (male 020–025, female 044–049) / B01001_001 × 100 |
| `renter_rate` | B25003_003 / B25003_001 × 100 |

ACS suppression sentinels (e.g. `-666666666`) and zero denominators are converted to missing and then median-imputed. This affected 16 tracts for income and 4 for the rates.

**Land surface temperature (LST).** All 16 Landsat 8/9 Level-2 scenes from June–August 2022 with < 60% scene cloud cover are retrieved from the Planetary Computer STAC API. Each scene is warped onto a common 30 m UTM grid. Every pixel flagged in `QA_PIXEL` as fill, cloud, dilated cloud, cirrus, cloud shadow, snow or water is masked out. Surface temperature is converted with the Collection 2 scale factors:

$$
T_{\text{°C}} = 0.00341802 \cdot DN + 149.0 - 273.15
$$

The summer LST at each pixel is the mean of all its clear observations (median: 6 per pixel). This measures *daytime land surface* temperature at the ~10:30 a.m. satellite overpass, not air temperature.

**Canopy and imperviousness.** NLCD 2021 rasters (30 m) are subset over the county through the MRLC Web Coverage Service. The WCS response flags 0 as nodata, even though 0 is a valid value here (0% canopy). The pipeline overrides this so fully paved pixels aren't silently dropped.

**Zonal statistics over land only.** Full TIGER tract boundaries extend into Lake Michigan. Averaging lake pixels into lakefront tracts would bias their LST downward and their canopy toward zero. So before computing means with `rasterstats`, TIGER area-water polygons are erased from each tract. After erasing, each tract's remaining area matches its Census land area (`ALAND`) to within 0.4%.

### 2. Multicollinearity and PCA feature reduction

**Variance inflation factors** are computed for the five demographic predictors:

$$
\text{VIF}_k = \frac{1}{1 - R_k^2}
$$

Here $R_k^2$ comes from regressing predictor $k$ on the other four. All VIFs fall between 1.3 and 2.8, below the conventional thresholds of 5–10. Even so, income, poverty, minority share and renter share are strongly inter-correlated (|r| = 0.42–0.73), which suggests one underlying "disadvantage" dimension.

**Principal component analysis** is run on the z-standardized predictors. It decomposes their correlation matrix and keeps the first two components:

| Loading | PC1: `pca_socioeconomic_deprivation` | PC2: `pca_demographic_age` |
|---|---:|---:|
| median_income | −0.510 | −0.300 |
| poverty_rate | 0.516 | 0.094 |
| minority_rate | 0.497 | 0.153 |
| renter_rate | 0.455 | −0.346 |
| elderly_rate | −0.138 | **0.871** |
| **Explained variance** | **56.3%** | **22.5%** |

Together they retain 78.9% of the variance. Each component is sign-oriented so that higher scores mean *more deprived* (PC1) or *older* (PC2).

### 3. Spatial autocorrelation: Moran's *I* and LISA

**Spatial weights.** A Queen contiguity matrix $W$ is built with `libpysal`: tracts $i$ and $j$ are neighbors if they share any edge or vertex. It is then row-standardized so that $\sum_j w_{ij} = 1$. On average each tract has 6.6 neighbors, and no tract is without neighbors.

**Global Moran's *I*** tests whether LST is clustered across the county as a whole:

$$
I = \frac{n}{S_0} \cdot \frac{\sum_i \sum_j w_{ij}\, z_i z_j}{\sum_i z_i^2}, \qquad z_i = x_i - \bar{x}, \quad S_0 = \sum_i \sum_j w_{ij}
$$

Values near +1 mean similar values sit next to each other, values near 0 indicate spatial randomness, and negative values indicate a checkerboard pattern. Significance comes from 999 random permutations of the values across tracts.

**Local Moran's *I* (LISA)** breaks the global statistic down into each tract's contribution:

$$
I_i = \frac{z_i}{m_2} \sum_j w_{ij}\, z_j, \qquad m_2 = \frac{\sum_i z_i^2}{n}
$$

Each tract is then classified by comparing its own value with the weighted average of its neighbors (its *spatial lag*), keeping only tracts with permutation p < 0.05:

| Cluster | Meaning |
|---|---|
| **High-High** | Hot tract surrounded by hot tracts (a *heat hotspot*) |
| **Low-Low** | Cool tract surrounded by cool tracts (a *coldspot*) |
| **High-Low** | Hot outlier among cooler neighbors |
| **Low-High** | Cool outlier among hotter neighbors |

### 4. Geographically weighted regression

**Model specification.** All variables are z-standardized, so coefficients are in standard-deviation units and can be compared across predictors:

$$
\text{LST}_i = \beta_0 + \beta_1\,\text{Canopy}_i + \beta_2\,\text{Deprivation}_i + \beta_3\,\text{Impervious}_i + \varepsilon_i
$$

**OLS baseline.** OLS fits this model once, assuming every coefficient is the same everywhere in the county.

**GWR** relaxes that assumption by fitting a separate weighted regression at each tract centroid $(u_i, v_i)$. Nearby tracts get more weight in each local fit:

$$
\text{LST}_i = \beta_0(u_i,v_i) + \sum_{k=1}^{3} \beta_k(u_i,v_i)\, x_{ik} + \varepsilon_i,
\qquad
\hat{\boldsymbol\beta}(u_i,v_i) = \left(X^\top W_i X\right)^{-1} X^\top W_i\, y
$$

The weights come from an **adaptive bisquare kernel**:

$$
w_{ij} =
\begin{cases}
\left[1 - \left(d_{ij}/b_i\right)^2\right]^2 & d_{ij} < b_i \\
0 & \text{otherwise}
\end{cases}
$$

Here $b_i$ is the distance from tract $i$ to its $k$-th nearest neighbor. An adaptive bandwidth suits Cook County because tract density varies widely: small tracts in Chicago, much larger ones in the outer suburbs.

**Bandwidth selection.** The neighbor count $k$ is chosen by golden-section search (`mgwr.Sel_BW`) to minimize the corrected Akaike information criterion:

$$
\text{AICc} = 2n\ln\hat\sigma + n\ln 2\pi + n\,\frac{n + \text{tr}(S)}{n - 2 - \text{tr}(S)}
$$

Here $\text{tr}(S)$ is the effective number of parameters. The OLS AICc uses the same Gaussian formula, so the two models can be compared directly.

**Inference.** GWR tests a local coefficient at every tract, so significance uses the multiple-testing-corrected critical *t* of da Silva & Fotheringham (2016) rather than the usual 1.96. For each tract and coefficient the pipeline saves $\hat\beta$, its standard error, its *t*-value, a significance flag, the local $R^2$, and the local condition number as a collinearity diagnostic.

---

## Key spatial insights

> Figures are for summer 2022, n = 1,331 land tracts. Neighborhood names come from joining tract representative points to City of Chicago community areas and, for suburban tracts, Census incorporated places.

### Heat is strongly clustered

- **Global Moran's *I* = 0.746** (z = 49.6, permutation p = 0.001, the smallest p-value possible with 999 permutations). Summer surface temperature is far more clustered than random chance would produce.
- **LISA identifies 321 heat hotspot tracts (High-High) and 273 coldspot tracts (Low-Low)**, plus 14 hot outliers, 5 cool outliers, and 718 tracts with no significant pattern.
- **81% of hotspots are inside the City of Chicago**, although the city has only 59% of the county's tracts. The hotspots form a continuous belt across the West and Southwest Sides. Coldspots follow the forest preserves (Palos, Poplar Creek) and the North Shore suburbs (Evanston, Glenview), plus Hyde Park and Palatine.

### Hotspots and coldspots are different neighborhoods

| | Hotspots (HH) | Coldspots (LL) |
|---|---:|---:|
| Mean summer LST | **41.2 °C** | **34.8 °C** |
| Tree canopy | 4.3% | 15.5% |
| Impervious surface | 75.4% | 46.5% |
| Median household income (median tract) | $66,800 | $88,400 |
| Minority (non-white) share | 72.8% | 47.0% |
| Poverty rate | 14.9% | 11.5% |
| Share of tracts above median deprivation | **63%** | **30%** |

Hotspot tracts are 6.4 °C hotter at the surface, have about a quarter of the tree canopy, and are about twice as likely to be socioeconomically deprived as coldspot tracts.

### Highest-risk neighborhoods

These are tracts that are *both* LISA heat hotspots *and* above the county median on the deprivation index (203 tracts in total). They are concentrated in:

| Community area / municipality | High-risk tracts | Mean LST | Mean canopy | Mean poverty | Minority share |
|---|---:|---:|---:|---:|---:|
| South Lawndale (Little Village) | 18 | 41.3 °C | 3.1% | 22.7% | 94.8% |
| Austin | 17 | 41.1 °C | 4.7% | 26.8% | 96.8% |
| Belmont Cragin | 15 | 42.0 °C | 4.2% | 14.8% | 86.2% |
| Cicero | 14 | 41.2 °C | 3.5% | 14.2% | 93.4% |
| Near West Side | 13 | 40.4 °C | 2.1% | 30.1% | 76.0% |
| Brighton Park | 10 | 42.1 °C | 3.5% | 17.3% | 92.7% |
| Lower West Side (Pilsen) | 10 | 41.6 °C | 1.0% | 13.9% | 79.7% |

The single hottest tract in the county is **Census Tract 2916 in North Lawndale**, at 44.8 °C with 2.4% tree canopy and 84% impervious surface.

### GWR explains far more than a global model

| Metric | Global OLS | GWR |
|---|---:|---:|
| R² | 0.524 | **0.927** |
| Adjusted R² | 0.523 | 0.910 |
| Mean local R² | — | 0.735 |
| AICc | 2,799.0 | **914.3** |
| Bandwidth | — | 50 nearest neighbors (adaptive bisquare) |
| Effective parameters | 4 | 247.8 |

- **Letting coefficients vary across space nearly doubles the explained variance** (R² 0.52 → 0.93). AICc falls by about 1,885, which rules out overfitting as the explanation. The drivers of heat really do differ from place to place, and a single countywide model hides that.
- **The local fit is usually strong.** Median local R² is 0.76 and the interquartile range is 0.63–0.88. The weakest fits (local R² < 0.5, 132 tracts) are concentrated in West Town, Edgewater and Lincoln Square. There, factors outside the model, such as lake-breeze cooling, roof materials and building height, probably matter more.

### What drives heat, and where

- **Impervious surface is the dominant driver.** In OLS, β = +0.50 (SD units), and the effect is significant in 42.5% of tracts locally. In 562 of those 566 tracts, more pavement means more heat.
- **Tree canopy cools, but unevenly.** In OLS, β = −0.28. Locally, canopy has a significant **cooling** effect in 179 tracts and a significant warming effect in only 24. The strongest significant cooling (standardized β < −1.5, 24 tracts) is concentrated in the **Near West Side, New City, Lower West Side and Brighton Park**. In the steepest tract (Near West Side), each extra percentage point of canopy goes with about **−1.5 °C** of surface temperature. Lower West Side and Brighton Park are also on the highest-risk list above, so new tree canopy there would target both the hottest, most deprived residents and the places where trees cool most effectively.
- **Deprivation affects heat through the built environment, not directly.** On its own, deprivation is positively correlated with LST (r = +0.25). But once canopy and impervious surface are controlled for, its coefficient turns slightly *negative* (OLS β = −0.07), and 175 of the 183 locally significant tracts are negative. In other words, deprived neighborhoods are hotter *because* they have less canopy and more pavement, not because of some other factor. That points directly at greening and de-paving as equity interventions.

---

## Installation and reproducibility

### Prerequisites

- **Python 3.13**, macOS or Linux. Every package installs from wheels, so no system GDAL is needed.
- **A Census API key**, free at <https://api.census.gov/data/key_signup.html>. It's needed for step 02.
- **Internet access** for the Census, Planetary Computer and MRLC APIs.
- **About 300 MB of disk** for rasters and intermediate GeoPackages.

### 1. Set up the environment

```bash
git clone <this-repo> cook-county-spatial
cd cook-county-spatial

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

All commands below call the virtualenv's interpreter directly (`.venv/bin/python`), so there's no need to activate it. If you prefer to activate it, run `source .venv/bin/activate` and use `python` instead.

```bash
export CENSUS_API_KEY="your-key-here"     # add to ~/.zshrc or ~/.bashrc to persist
```

### 2. Run the pipeline

Run the scripts in order from the repository root. Each one prints a summary of what it produced.

```bash
.venv/bin/python 01_fetch_cook_county.py     # tracts → data/cook_county_base.gpkg
.venv/bin/python 02_fetch_demographics.py    # ACS predictors → data/cook_county_vulnerability.gpkg
.venv/bin/python 03_fetch_environmental.py   # LST, canopy, impervious (+ figures/lst_preview.png)
.venv/bin/python 04_esda_and_pca.py          # VIF, PCA, Moran's I, LISA → data/cook_county_processed.gpkg
.venv/bin/python 05_fit_gwr.py               # OLS + GWR → data/cook_county_gwr_results.gpkg
.venv/bin/python 06_spatial_mcp_server.py --load   # → cook_county.duckdb
.venv/bin/python 07_export_dashboard.py      # → dashboard/index.html + cook_county_data.geojson
```

| Step | Typical runtime | Notes |
|---|---|---|
| 01 | ~10 s | Downloads are cached by `pygris` |
| 02 | ~5 s | Requires `CENSUS_API_KEY` |
| 03 | 3–10 min the first time, ~30 s after | Raster downloads are cached in `data/*.tif`; delete them to re-fetch |
| 04 | ~20 s | 999-permutation inference; fixed seed (42) for reproducible results |
| 05 | ~30 s | Bandwidth search is the slow part |
| 06 `--load` | ~5 s | Downloads the DuckDB `spatial` extension on first run |
| 07 | ~5 s | |

**Re-run order matters.** Step 02 rewrites `cook_county_vulnerability.gpkg` and drops the columns added by step 03. After changing any step, re-run every step after it, including `06 --load` to refresh the database.

### 3. View the dashboard

```bash
python3 -m http.server 8000 --directory dashboard
# open http://localhost:8000
```

The page loads its data with `fetch`, so it must be served over HTTP; opening `index.html` as a file won't work. URLs are shareable: `?layer=lst|r2|beta|lisa` picks the map layer and `#<GEOID>` selects a tract, e.g. <http://localhost:8000/?layer=beta#17031833100>.

### Troubleshooting

| Symptom | Fix |
|---|---|
| `CRSError: The EPSG code is unknown` / `proj.db ... from another PROJ installation` | Your shell exports another installation's `GDAL_DATA` / `PROJ_DATA` (often conda). Scripts 03 and 07 unset these themselves; for ad-hoc work, run `unset GDAL_DATA GDAL_DRIVER_PATH PROJ_DATA`. |
| Step 02 exits with `CENSUS_API_KEY is not set` or `Census API rejected the request` | Export a valid key. The API answers a missing or invalid key with an HTML redirect, not an error code. |
| Dashboard shows "Could not load cook_county_data.geojson" | Serve the folder over HTTP (see above) instead of opening the file directly. |

---

## Using the MCP server

`06_spatial_mcp_server.py` exposes the results to any MCP-compatible LLM client over stdio. It uses the official Python MCP SDK v2 (`mcp.server.mcpserver.MCPServer`).

| Tool | Purpose |
|---|---|
| `get_tract_vulnerability(geoid)` | Returns a tract's full profile in four groups: tract, demographics, climate, GWR. Accepts an 11-digit GEOID or a 6-digit tract code. |
| `find_hotspots(metric, top_n, lowest=False)` | Ranks the top-N tracts by `heat`, `vulnerability` (deprivation index), `elderly`, `impervious`, `beta_tree_canopy`, `beta_deprivation`, `beta_impervious` or `local_r2`. |
| `query_spatial_stats(sql_query)` | Runs arbitrary DuckDB Spatial SQL against table `cook_county_gwr`. Results are capped at 500 rows; `geom` is in EPSG:32616. |

**Security.** `query_spatial_stats` runs LLM-written SQL, so every query goes through a **read-only** connection with `enable_external_access = false` and `lock_configuration = true`. Queries cannot modify the database, read local files, reach the network, or re-enable any of these.

**Register with Claude Code:**

```bash
claude mcp add cook-county -- "$PWD/.venv/bin/python" "$PWD/06_spatial_mcp_server.py"
```

**Or with Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "cook-county": {
      "command": "/absolute/path/to/cook-county-spatial/.venv/bin/python",
      "args": ["/absolute/path/to/cook-county-spatial/06_spatial_mcp_server.py"]
    }
  }
}
```

Example prompts once the server is connected:

- *"Which 10 tracts have the strongest tree-canopy cooling effect, and what's their current canopy?"*
- *"Compare average LST and poverty between High-High and Low-Low clusters."*
- *"Give me the full vulnerability profile for tract 291600."*

**Database backend.** The pipeline currently uses DuckDB Spatial, which needs no server and uses PostGIS-style `ST_*` functions. A PostGIS backend is not implemented yet. Adding one would mean replacing `load_database()` and `connect()` in `06_spatial_mcp_server.py`.

---

## Limitations

- **Surface temperature ≠ air temperature.** Landsat measures the skin temperature of roofs, pavement and vegetation at about 10:30 a.m. It is a strong proxy for urban heat island intensity, but it is not the air temperature people experience, and it says nothing about nighttime heat retention.
- **Canopy is underestimated in dense urban areas.** NLCD canopy is a 30 m modeled product and misses many street trees. The 8.6% countywide tract mean is below high-resolution estimates for Chicago, so use the canopy values to compare tracts rather than as true percentages.
- **Canopy and impervious surface are collinear** (r = −0.87). The model can't fully separate their individual effects, and 50 tracts have a local condition number above 30, so their local coefficients should be interpreted with caution. A natural next step is MGWR (multiscale GWR), which estimates a separate bandwidth for each predictor.
- **Ecological inference.** All results are tract-level associations, not individual-level exposures or causal effects.
- **Single summer.** 2022 only, with about 6 clear observations per pixel. A multi-year composite would be more robust.
- **Imputation.** 16 tracts (income) and 4 tracts (rates) carry median-imputed ACS values, mostly tracts with very few or no residents.

---

## Repository layout

```
cook-county-spatial/
├── 01_fetch_cook_county.py        # Census tracts → UTM GeoPackage
├── 02_fetch_demographics.py       # ACS 5-Year predictors
├── 03_fetch_environmental.py      # Landsat LST, NLCD canopy & impervious, zonal stats
├── 04_esda_and_pca.py             # VIF, PCA, Moran's I, LISA
├── 05_fit_gwr.py                  # OLS vs. GWR
├── 06_spatial_mcp_server.py       # DuckDB loader + MCP server
├── 07_export_dashboard.py         # GeoJSON export + Leaflet/Chart.js dashboard
├── requirements.txt
├── CLAUDE.md                      # Working notes for Claude Code sessions
├── data/                          # GeoPackages + cached rasters (generated)
├── figures/                       # Static maps (generated)
├── dashboard/                     # index.html + cook_county_data.geojson (generated)
└── cook_county.duckdb             # Spatial database (generated)
```

---

## References

- Anselin, L. (1995). Local indicators of spatial association—LISA. *Geographical Analysis*, 27(2), 93–115.
- Fotheringham, A. S., Brunsdon, C., & Charlton, M. (2002). *Geographically Weighted Regression: The Analysis of Spatially Varying Relationships*. Wiley.
- da Silva, A. R., & Fotheringham, A. S. (2016). The multiple testing issue in geographically weighted regression. *Geographical Analysis*, 48(3), 233–247.
- Oshan, T. M., Li, Z., Kang, W., Wolf, L. J., & Fotheringham, A. S. (2019). mgwr: A Python implementation of multiscale geographically weighted regression. *ISPRS International Journal of Geo-Information*, 8(6), 269.
- Rey, S. J., & Anselin, L. (2007). PySAL: A Python library of spatial analytical methods. *The Review of Regional Studies*, 37(1), 5–27.

Data © U.S. Census Bureau, USGS, USFS/MRLC (public domain); basemap © OpenStreetMap contributors (ODbL).
