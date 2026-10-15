"""Download Cook County, IL (FIPS 17031) 2022 census tracts, reproject to UTM 16N, save to GeoPackage."""

from pathlib import Path

from pygris import tracts

STATE_FIPS = "17"
COUNTY_FIPS = "031"
YEAR = 2022
TARGET_CRS = "EPSG:32616"  # WGS 84 / UTM Zone 16N

DATA_DIR = Path(__file__).resolve().parent / "data"
OUT_PATH = DATA_DIR / "cook_county_base.gpkg"
LAYER = "tracts_2022"


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # cb=False -> full TIGER/Line boundaries (cartographic boundary files clip to shoreline)
    gdf = tracts(state=STATE_FIPS, county=COUNTY_FIPS, year=YEAR, cb=False, cache=True)
    print(f"Downloaded {len(gdf)} tracts (source CRS: {gdf.crs})")

    gdf = gdf.to_crs(TARGET_CRS)
    gdf.to_file(OUT_PATH, layer=LAYER, driver="GPKG")

    print(f"Saved {len(gdf)} tracts to {OUT_PATH} (layer '{LAYER}', CRS: {gdf.crs})")


if __name__ == "__main__":
    main()
