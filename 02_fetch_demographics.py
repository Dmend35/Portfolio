"""Fetch 2022 ACS 5-Year tract demographics for Cook County, IL, merge onto tract geometry, save vulnerability layer."""

import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

STATE_FIPS = "17"
COUNTY_FIPS = "031"
YEAR = 2022
ACS_URL = f"https://api.census.gov/data/{YEAR}/acs/acs5"

DATA_DIR = Path(__file__).resolve().parent / "data"
BASE_PATH = DATA_DIR / "cook_county_base.gpkg"
OUT_PATH = DATA_DIR / "cook_county_vulnerability.gpkg"
LAYER = "tracts_2022"

# B01001 age 65+ categories: male 020-025, female 044-049
AGE_65_PLUS = [f"B01001_{i:03d}E" for i in [*range(20, 26), *range(44, 50)]]

ACS_VARS = [
    "B19013_001E",  # median household income
    "B17001_001E",  # poverty status universe
    "B17001_002E",  # income below poverty level
    "B03002_001E",  # total population (race/ethnicity)
    "B03002_003E",  # non-Hispanic white alone
    "B01001_001E",  # total population (sex by age)
    *AGE_65_PLUS,
    "B25003_001E",  # occupied housing units
    "B25003_003E",  # renter-occupied
]

PREDICTORS = ["median_income", "poverty_rate", "minority_rate", "elderly_rate", "renter_rate"]


def fetch_acs():
    key = os.environ.get("CENSUS_API_KEY")
    if not key:
        raise SystemExit(
            "CENSUS_API_KEY is not set. Get a free key at https://api.census.gov/data/key_signup.html,\n"
            "then run: CENSUS_API_KEY=<your key> .venv/bin/python 02_fetch_demographics.py"
        )
    params = {
        "get": ",".join(ACS_VARS),
        "for": "tract:*",
        "in": f"state:{STATE_FIPS} county:{COUNTY_FIPS}",
        "key": key,
    }

    resp = requests.get(ACS_URL, params=params, timeout=60, allow_redirects=False)
    # An invalid/missing key comes back as a redirect to an HTML error page, not JSON
    if resp.is_redirect:
        raise SystemExit(f"Census API rejected the request (redirected to {resp.headers.get('Location')}). Check CENSUS_API_KEY.")
    resp.raise_for_status()
    header, *rows = resp.json()
    df = pd.DataFrame(rows, columns=header)

    df["GEOID"] = df["state"] + df["county"] + df["tract"]
    df[ACS_VARS] = df[ACS_VARS].apply(pd.to_numeric, errors="coerce")
    # ACS uses large negative sentinels (e.g. -666666666) for suppressed/unavailable estimates
    df[ACS_VARS] = df[ACS_VARS].mask(df[ACS_VARS] < 0)
    return df


def calc_predictors(df):
    out = pd.DataFrame({"GEOID": df["GEOID"]})
    out["median_income"] = df["B19013_001E"]
    out["poverty_rate"] = df["B17001_002E"] / df["B17001_001E"] * 100
    out["minority_rate"] = (df["B03002_001E"] - df["B03002_003E"]) / df["B03002_001E"] * 100
    out["elderly_rate"] = df[AGE_65_PLUS].sum(axis=1, min_count=1) / df["B01001_001E"] * 100
    out["renter_rate"] = df["B25003_003E"] / df["B25003_001E"] * 100
    return out


def impute_median(gdf):
    gdf[PREDICTORS] = gdf[PREDICTORS].replace([np.inf, -np.inf], np.nan)
    for col in PREDICTORS:
        n_missing = gdf[col].isna().sum()
        if n_missing:
            median = gdf[col].median()
            gdf[col] = gdf[col].fillna(median)
            print(f"  {col}: imputed {n_missing} tract(s) with median {median:,.2f}")
    return gdf


def main():
    acs = fetch_acs()
    print(f"Fetched ACS {YEAR} 5-Year data for {len(acs)} tracts")
    predictors = calc_predictors(acs)

    tracts = gpd.read_file(BASE_PATH, layer=LAYER)
    gdf = tracts.merge(predictors, on="GEOID", how="left")
    unmatched = gdf["median_income"].isna() & ~gdf["GEOID"].isin(predictors["GEOID"])
    print(f"Merged onto {len(gdf)} tracts ({unmatched.sum()} with no ACS match)")

    print("Cleaning NaN/inf values with median imputation:")
    gdf = impute_median(gdf)

    gdf.to_file(OUT_PATH, layer=LAYER, driver="GPKG")
    print(f"Saved {len(gdf)} tracts to {OUT_PATH} (layer '{LAYER}', CRS: {gdf.crs})\n")

    with pd.option_context("display.float_format", "{:,.2f}".format, "display.width", 120):
        print(gdf[PREDICTORS].describe())


if __name__ == "__main__":
    main()
