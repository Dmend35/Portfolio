# Cook County Spatial

Spatial data science project on Cook County, IL (state FIPS 17, county 031, full GEOID prefix `17031`). Early stage: so far the project has tract geometry plus ACS socioeconomic and environmental (heat, tree canopy, impervious) predictors, ESDA/PCA features, OLS and GWR models of summer heat, and an MCP server that exposes the results to an LLM.

## Environment

- Python 3.13 virtualenv at `.venv/`. Run things with `.venv/bin/python <script>` (no need to activate).
- Installed: geopandas 1.2, pandas 3.0, shapely 2.2, pygris 0.2.1, pyrosm 0.17, rasterstats 0.21 (with rasterio 1.5), matplotlib, scikit-learn 1.9, statsmodels 0.15, libpysal 4.15, esda 2.10, mgwr 2.2, duckdb 1.5 (spatial extension), mcp 2.3.
- **mcp 2.x:** `FastMCP` was renamed `MCPServer` (`from mcp.server.mcpserver import MCPServer`). Older v1 examples won't import.
- **GDAL/PROJ conflict:** the user's shell exports miniconda's `GDAL_DATA`, `GDAL_DRIVER_PATH` and `PROJ_DATA`. These break rasterio's bundled copies ("EPSG code is unknown" / `proj.db` layout errors). Any script using rasterio must `os.environ.pop` those variables before importing it, as `03_` does.
- Dependencies are pinned in `requirements.txt`; if you add one, install it into `.venv`, add it there, and mention it to the user. There's no git repo yet.
- `README.md` quotes specific results (Moran's I, GWR metrics, LISA counts, neighborhood tables). If you re-run the pipeline or change methods, update those numbers. The neighborhood names come from an ad-hoc join to Chicago community areas (Socrata `igwz-8jzy`) and Census places, which isn't part of the pipeline.

## Pipeline

Scripts are numbered in run order (`01_`, `02_`, ...) and are run from the project root. Each one is a small, standalone script with constants at the top and a `main()` function.

| Script | Does | Output |
|---|---|---|
| `01_fetch_cook_county.py` | Downloads 2022 TIGER/Line census tracts with `pygris.tracts(..., cb=False, cache=True)`, then reprojects them | `data/cook_county_base.gpkg`, layer `tracts_2022` |
| `02_fetch_demographics.py` | Pulls 2022 ACS 5-Year data from the Census API (`requests`), calculates `median_income`, `poverty_rate`, `minority_rate`, `elderly_rate` and `renter_rate` (rates are percentages, 0-100), left-joins them to the tracts on `GEOID`, and fills NaN/inf values with the column median | `data/cook_county_vulnerability.gpkg`, layer `tracts_2022` |
| `03_fetch_environmental.py` | Composites mean summer (Jun–Aug 2022) Landsat 8/9 C2 L2 surface temperature (`lwir11`) from the Planetary Computer STAC API, using plain `requests` with a SAS token rather than pystac-client. Masks cloud/shadow/snow/water/fill pixels per pixel via `qa_pixel` and averages all clear readings (median about 6 per pixel). Downloads NLCD 2021 Tree Canopy Cover and NLCD 2021 Impervious Surface from the MRLC WCS (`NLCD_LAYERS` dict). Takes zonal means over each tract's **land** area (TIGER `area_water` erased), adds `lst_c`, `tree_canopy_pct` and `impervious_pct` to the vulnerability layer, median-imputes, and saves a map | `data/lst_summer_2022.tif`, `data/tree_canopy_2021.tif`, `data/impervious_2021.tif` (cached: delete them to re-download), `lst_c`, `tree_canopy_pct` and `impervious_pct` columns in `cook_county_vulnerability.gpkg`, `figures/lst_preview.png` |
| `04_esda_and_pca.py` | Computes VIF for the 5 demographic predictors and runs PCA on them (standardized, 2 components; signs flipped so higher = more deprived / older). Builds a row-standardized Queen contiguity W, then runs global Moran's I and LISA on `lst_c`, excluding the all-water tract (its `lisa_*` values are null) (999 permutations, seed 42, p < 0.05) | `data/cook_county_processed.gpkg`, layer `tracts_2022`: all vulnerability columns + `pca_socioeconomic_deprivation`, `pca_demographic_age`, `lisa_i`, `lisa_p`, `lisa_cluster` (High-High / Low-Low / High-Low / Low-High / Not Significant) |
| `05_fit_gwr.py` | Models `lst_c ~ tree_canopy_pct + pca_socioeconomic_deprivation + impervious_pct`, all z-standardized, with OLS (statsmodels) and GWR (mgwr, adaptive bisquare, bandwidth selected by AICc via `Sel_BW`, UTM centroid coordinates). Excludes the all-water tract. OLS AICc uses mgwr's Gaussian formula so the two models are comparable | `data/cook_county_gwr_results.gpkg`, layer `tracts_2022`: processed columns + `gwr_local_r2`, `gwr_{beta,se,t,sig}_{intercept,tree_canopy_pct,pca_socioeconomic_deprivation,impervious_pct}` (`sig` uses mgwr's multiple-testing-corrected critical t), `gwr_local_cn`, `gwr_residual` |
| `06_spatial_mcp_server.py` | `--load` rebuilds DuckDB from the GWR GeoPackage. With no flag it runs the MCP server over stdio, building the DB first if it's missing. Tools: `get_tract_vulnerability(geoid)` (11-digit GEOID or 6-digit tract code), `find_hotspots(metric, top_n, lowest=False)` (metrics are whitelisted in `METRICS`; "vulnerability" = deprivation PCA score), and `query_spatial_stats(sql_query)` (arbitrary SQL, max 500 rows) | `cook_county.duckdb` (project root), table `cook_county_gwr`: all GWR columns + WGS84 centroid `lon`/`lat`; `geom` is EPSG:32616 |
| `07_export_dashboard.py` | Exports the land tracts (all-water tract dropped) to a lightweight GeoJSON: 5 m simplification, 5-decimal coordinates, short rounded property names (`lst`, `r2`, `b_canopy`, `t_canopy`, `sig_canopy`, `lisa`, `canopy`, `imperv`, `poverty`, `income`, `minority`, `elderly`, `renter`). Writes a single-page Leaflet 1.9.4 + Chart.js 4.4.1 dashboard; the HTML template is the `HTML` string inside the script | `dashboard/cook_county_data.geojson` (~1 MB), `dashboard/index.html`. Serve with `python3 -m http.server 8000 --directory dashboard` (the page `fetch`es the GeoJSON, so `file://` won't work) |

**The Census API requires a key:** set `CENSUS_API_KEY` in the environment. Without one, the API redirects to an HTML error page instead of returning data, and `02_` exits with a message saying so. ACS negative sentinel values (e.g. `-666666666`) are converted to NaN before calculating, so they get imputed. In the 2022 run, 16 tracts had median income imputed and 4 had the rates imputed (presumably tracts with no residents). `median_income` is capped at 250001, ACS's code for "$250,000 or more".

**`03_` details:**
- **Re-running `03_` is safe:** it drops any existing `lst_c` and `tree_canopy_pct` columns before re-adding them. `02_` overwrites the whole vulnerability file, so after re-running `02_` you must re-run `03_`.
- **Canopy GeoTIFF quirks:** the WCS response comes without a usable CRS, so the script assigns EPSG:5070. It also marks 0 as nodata even though 0 means 0% canopy, so the script sets nodata to 255 instead.
- **Canopy runs low in the city:** NLCD canopy (30 m) underestimates urban canopy compared with high-resolution sources (about 8.6% tract mean).
- **What LST means here:** daytime land *surface* temperature around the 10:30 am Landsat overpass, not air temperature.
- **One tract is all water** (Lake Michigan). It has no land pixels, so its LST and canopy are median-imputed, and the map skips it.

**`04_` results (2022 data):**
- **VIFs are all below 3** (max: `median_income` 2.83), so no variable is "high-VIF." PCA still runs on all five demographic variables at the user's request.
- **Components:** PC1 (deprivation) explains 56% of variance and loads on income (negative), poverty, minority and renter share. PC2 (age) explains 23% and is dominated by `elderly_rate` (0.87).
- **Spatial clustering:** global Moran's I for LST is significant at p = 0.001, the minimum possible with 999 permutations. - **All-water tract excluded:** before this exclusion, the imputed lake tract appeared as a spurious High-Low outlier. With it excluded: I = 0.746; LISA finds 321 High-High, 273 Low-Low, 14 High-Low and 5 Low-High tracts.
- **Naming:** the LST column is `lst_c`; the user's spec called it `mean_lst_celsius`.

**`05_` results:**
- **OLS:** R² 0.524, AICc 2799. Impervious +0.50, canopy −0.28, deprivation −0.07 (standardized).
- **GWR:** R² 0.927, mean local R² 0.735, AICc 914, bandwidth 50 nearest neighbors.
- **Local collinearity:** canopy and impervious are correlated, and 50 tracts have a local condition number above 30. Interpret their local coefficients with caution.

**`06_` safety and database notes:**
- **Locked-down SQL:** every query uses a read-only DuckDB connection with `enable_external_access = false` and `lock_configuration = true`, so `query_spatial_stats` can't write, read local files or reach the network.
- **No PostGIS:** no credentials are configured (no `PG*`/`DATABASE_URL`), so the server uses DuckDB only. There is no PostGIS code path.
- **Stale database:** re-running upstream scripts doesn't update the database. Run `06_ --load` to refresh it.

**`07_` dashboard notes:**
- **Basemap:** CARTO tiles now require an API key (keyless requests return watermarked tiles), so the dashboard uses OSM standard tiles. A CSS grayscale filter mutes them, inverted in dark mode.
- **Colors:**
  - LST: blue↔red diverging scale centered on the county mean, with 1-SD classes.
  - Canopy β: diverging scale centered on 0, with non-significant tracts faded.
  - Local R²: sequential blue scale.
  - LISA palettes: light `#e34948/#eda100/#1baf7a/#2a78d6`, dark `#e34948/#c98500/#199e70/#3987e5`. These were validated with the dataviz skill's validator (all pairs). They carry a CVD warning, so cluster names are always shown as text.
- **Inspector chart:** shows the tract's predictors as z-scores against the county tract mean. Mixed units can't share one axis, so a table twin shows the raw values.
- **URL state:** `?layer=lst|r2|beta|lisa` picks the layer and `#<GEOID>` selects a tract.
- **Headless screenshots:** Chrome won't go narrower than about 500 px, so test the mobile layout inside a 390 px iframe.

`tracts_2022` has 1332 polygons with the standard TIGER columns (`GEOID`, `TRACTCE`, `NAME`, `NAMELSAD`, `ALAND`, `AWATER`, `INTPTLAT`, `INTPTLON`, ...). Use `GEOID` (11 characters, a string) as the join key for Census/ACS data, and keep it as a string so the leading zeros survive.

## Conventions

- **Project CRS is EPSG:32616 (WGS 84 / UTM 16N, meters).** Reproject every layer to it before overlay, buffering, distance or area calculations.
- `cb=False` is deliberate: full TIGER boundaries extend into Lake Michigan, while cartographic-boundary files are clipped to the shoreline. Don't switch to `cb=True` without asking the user.
- Data outputs go in `data/`, figures in `figures/`. Prefer adding new layers to `cook_county_base.gpkg` (or another GeoPackage) over writing shapefiles.
- Write paths relative to the script (`Path(__file__).resolve().parent`), as `01_` does.

## Likely next steps

The installed packages point to these next stages. They aren't built yet, so confirm scope with the user before starting:
- **pyrosm:** pull OpenStreetMap features (roads, POIs, buildings) from an Illinois/Chicago `.osm.pbf`, clip them to the tract extent, and summarize them by tract.
- A composite heat-vulnerability index. None exists yet; `find_hotspots("vulnerability")` ranks by the deprivation PCA score.
- MGWR (variable-specific bandwidths), maps of GWR coefficients and LISA clusters, and registering the MCP server with Claude (`claude mcp add`).
