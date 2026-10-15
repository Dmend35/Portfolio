"""Add mean summer Land Surface Temperature, % tree canopy and % impervious surface per tract to the vulnerability layer.

LST: Landsat 8/9 Collection 2 Level-2 surface temperature (Microsoft Planetary Computer STAC), Jun-Aug 2022,
     cloud/shadow/water masked per pixel, averaged over all clear observations.
Canopy / impervious: NLCD 2021 Tree Canopy Cover (USFS, v2021-4) and NLCD 2021 Impervious Surface via the MRLC WCS.
Zonal means use tract land area only (TIGER area-water polygons erased), so Lake Michigan doesn't skew lakefront tracts.
"""

import os
from pathlib import Path

# The user's shell exports miniconda's GDAL/PROJ paths, which break the rasterio wheel's bundled copies
for var in ("GDAL_DATA", "GDAL_DRIVER_PATH", "PROJ_DATA", "PROJ_LIB"):
    os.environ.pop(var, None)

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import requests
from pygris import area_water
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterstats import zonal_stats

STATE_FIPS = "17"
COUNTY_FIPS = "031"
TARGET_CRS = "EPSG:32616"

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
FIG_DIR = ROOT / "figures"
BASE_PATH = DATA_DIR / "cook_county_base.gpkg"
VULN_PATH = DATA_DIR / "cook_county_vulnerability.gpkg"
LAYER = "tracts_2022"
LST_PATH = DATA_DIR / "lst_summer_2022.tif"
CANOPY_PATH = DATA_DIR / "tree_canopy_2021.tif"
IMPERVIOUS_PATH = DATA_DIR / "impervious_2021.tif"

STAC_SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
STAC_TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/landsat-c2-l2"
SUMMER = "2022-06-01/2022-08-31"
MAX_SCENE_CLOUD = 60  # scene-level filter; clouds are also masked per pixel
ST_SCALE, ST_OFFSET = 0.00341802, 149.0  # Collection 2 ST_B10 -> Kelvin
# QA_PIXEL bits to reject: fill, dilated cloud, cirrus, cloud, cloud shadow, snow, water
QA_REJECT = sum(1 << b for b in (0, 1, 2, 3, 4, 5, 7))

MRLC_WCS = "https://www.mrlc.gov/geoserver/ows"
NLCD_CRS = "EPSG:5070"  # canopy WCS GeoTIFFs come with an unusable LOCAL_CS; both coverages are native Albers
NLCD_NODATA = 255  # WCS marks 0 as nodata, but 0 is a valid value (0%); values > 100 are background/no data
# output column -> (WCS coverage id, cached raster path)
NLCD_LAYERS = {
    "tree_canopy_pct": ("mrlc_download__nlcd_tcc_conus_2021_v2021-4", CANOPY_PATH),
    "impervious_pct": ("mrlc_download__NLCD_2021_Impervious_L48", IMPERVIOUS_PATH),
}

RES = 30
NODATA = -9999.0
NEW_COLS = ["lst_c", *NLCD_LAYERS]


def land_zones(tracts):
    """Tract geometries with water removed; all-water tracts end up empty."""
    water = area_water(state=STATE_FIPS, county=COUNTY_FIPS, year=2022, cache=True).to_crs(tracts.crs)
    zones = tracts[["GEOID", "geometry"]].copy()
    zones["geometry"] = zones.geometry.difference(water.union_all())
    return zones


def fetch_lst(bounds):
    if LST_PATH.exists():
        print(f"Using cached {LST_PATH.name}")
        return

    xmin, ymin = np.floor(bounds[:2] / RES) * RES
    xmax, ymax = np.ceil(bounds[2:] / RES) * RES
    width, height = int((xmax - xmin) / RES), int((ymax - ymin) / RES)
    transform = from_origin(xmin, ymax, RES, RES)

    bbox_ll = gpd.GeoSeries.from_xy([xmin, xmax], [ymin, ymax], crs=TARGET_CRS).to_crs(4326).total_bounds
    body = {
        "collections": ["landsat-c2-l2"],
        "bbox": bbox_ll.tolist(),
        "datetime": SUMMER,
        "query": {"platform": {"in": ["landsat-8", "landsat-9"]}, "eo:cloud_cover": {"lt": MAX_SCENE_CLOUD}},
        "limit": 100,
    }
    items = requests.post(STAC_SEARCH, json=body, timeout=60).json()["features"]
    token = requests.get(STAC_TOKEN, timeout=60).json()["token"]
    print(f"Compositing LST from {len(items)} Landsat scenes ({SUMMER})")

    total = np.zeros((height, width))
    count = np.zeros((height, width), dtype=np.uint16)
    vrt_opts = dict(crs=TARGET_CRS, transform=transform, width=width, height=height, resampling=Resampling.nearest)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        for item in items:
            hrefs = {k: f"{item['assets'][k]['href']}?{token}" for k in ("lwir11", "qa_pixel")}
            with rasterio.open(hrefs["qa_pixel"]) as src, WarpedVRT(src, nodata=1, **vrt_opts) as vrt:
                qa = vrt.read(1)  # nodata=1 -> outside-scene pixels read as "fill"
            with rasterio.open(hrefs["lwir11"]) as src, WarpedVRT(src, **vrt_opts) as vrt:
                st = vrt.read(1)
            clear = ((qa & QA_REJECT) == 0) & (st > 0)
            total[clear] += st[clear] * ST_SCALE + ST_OFFSET - 273.15
            count += clear
            print(f"  {item['id']}: {clear.mean():.0%} of grid clear")

    lst = np.where(count > 0, total / np.maximum(count, 1), NODATA).astype("float32")
    profile = dict(driver="GTiff", dtype="float32", count=1, width=width, height=height,
                   crs=TARGET_CRS, transform=transform, nodata=NODATA, compress="deflate")
    with rasterio.open(LST_PATH, "w", **profile) as dst:
        dst.write(lst, 1)
    print(f"Saved {LST_PATH.name}; clear observations per pixel: median {np.median(count[count > 0]):.0f}")


def fetch_nlcd(coverage, path, bounds_5070):
    if path.exists():
        print(f"Using cached {path.name}")
        return

    xmin, ymin, xmax, ymax = bounds_5070 + np.array([-RES, -RES, RES, RES]) * 10
    params = [
        ("service", "WCS"), ("version", "2.0.1"), ("request", "GetCoverage"),
        ("coverageId", coverage), ("format", "image/geotiff"),
        ("subset", f"X({xmin:.0f},{xmax:.0f})"), ("subset", f"Y({ymin:.0f},{ymax:.0f})"),
    ]
    resp = requests.get(MRLC_WCS, params=params, timeout=300)
    resp.raise_for_status()
    if "tiff" not in resp.headers.get("Content-Type", ""):
        raise SystemExit(f"MRLC WCS did not return a GeoTIFF:\n{resp.text[:500]}")

    with rasterio.MemoryFile(resp.content) as mem, mem.open() as src:
        data = src.read(1)
        profile = src.profile
    data[data > 100] = NLCD_NODATA
    profile.update(crs=NLCD_CRS, nodata=NLCD_NODATA, compress="deflate")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)
    print(f"Saved {path.name} (mean {data[data <= 100].mean():.1f}%)")


def zonal_mean(zones, raster_path):
    with rasterio.open(raster_path) as src:
        zones = zones.to_crs(src.crs)
        arr, affine, nodata = src.read(1), src.transform, src.nodata
    # rasterstats can't handle empty geometries (all-water tracts) -> leave those NaN
    has_land = ~zones.geometry.is_empty
    means = np.full(len(zones), np.nan)
    stats = zonal_stats(zones.geometry[has_land], arr, affine=affine, nodata=nodata, stats="mean")
    means[has_land.to_numpy()] = [s["mean"] if s["mean"] is not None else np.nan for s in stats]
    return means


def impute_median(gdf, cols):
    gdf[cols] = gdf[cols].replace([np.inf, -np.inf], np.nan)
    for col in cols:
        n_missing = gdf[col].isna().sum()
        if n_missing:
            median = gdf[col].median()
            gdf[col] = gdf[col].fillna(median)
            print(f"  {col}: imputed {n_missing} tract(s) with median {median:.2f}")
    return gdf


def plot_lst(gdf, zones):
    FIG_DIR.mkdir(exist_ok=True)
    # Draw land areas only, so imputed all-water (Lake Michigan) tracts don't show as real readings
    land = gdf.set_geometry(zones.geometry.to_numpy())
    land = land[~land.geometry.is_empty]
    fig, ax = plt.subplots(figsize=(8, 9))
    land.plot(column="lst_c", cmap="RdYlBu_r", linewidth=0, ax=ax,
             legend=True, legend_kwds={"label": "Mean summer LST (°C)", "shrink": 0.6})
    ax.set_title("Cook County, IL: mean summer 2022 land surface temperature by tract")
    ax.set_axis_off()
    out = FIG_DIR / "lst_preview.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved map to {out}")
    plt.show()


def main():
    tracts = gpd.read_file(BASE_PATH, layer=LAYER)
    zones = land_zones(tracts)

    fetch_lst(tracts.total_bounds)
    bounds_5070 = tracts.to_crs(NLCD_CRS).total_bounds
    for coverage, path in NLCD_LAYERS.values():
        fetch_nlcd(coverage, path, bounds_5070)

    gdf = gpd.read_file(VULN_PATH, layer=LAYER).drop(columns=NEW_COLS, errors="ignore")
    zones = zones.set_index("GEOID").loc[gdf["GEOID"]].reset_index()  # align row order
    gdf["lst_c"] = zonal_mean(zones, LST_PATH)
    for col, (_, path) in NLCD_LAYERS.items():
        gdf[col] = zonal_mean(zones, path)

    print("Cleaning NaN/inf values with median imputation:")
    gdf = impute_median(gdf, NEW_COLS)

    gdf.to_file(VULN_PATH, layer=LAYER, driver="GPKG")
    print(f"Saved {len(gdf)} tracts to {VULN_PATH} (layer '{LAYER}')\n")
    print(gdf[NEW_COLS].describe().round(2))

    plot_lst(gdf, zones)


if __name__ == "__main__":
    main()
