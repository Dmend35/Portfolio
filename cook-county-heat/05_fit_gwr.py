"""Global OLS vs. Geographically Weighted Regression of summer LST on canopy, deprivation and impervious surface.

Variables are z-standardized before fitting, so coefficients are in standard-deviation units and comparable across
predictors. The all-water Lake Michigan tract (ALAND == 0; its values are imputed) is excluded and gets NaN results.
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import statsmodels.api as sm
from mgwr.gwr import GWR
from mgwr.sel_bw import Sel_BW

DATA_DIR = Path(__file__).resolve().parent / "data"
IN_PATH = DATA_DIR / "cook_county_processed.gpkg"
OUT_PATH = DATA_DIR / "cook_county_gwr_results.gpkg"
LAYER = "tracts_2022"

Y_COL = "lst_c"
X_COLS = ["tree_canopy_pct", "pca_socioeconomic_deprivation", "impervious_pct"]
TERMS = ["intercept", *X_COLS]
KERNEL = "bisquare"


def zscore(df):
    return (df - df.mean()) / df.std()


def aicc_gaussian(llf, n, k):
    # Same Gaussian AICc formula mgwr uses (Fotheringham et al. 2002, eq. 2.33), so OLS and GWR are comparable
    return -2.0 * llf + 2.0 * n * (k + 1.0) / (n - k - 2.0)


def fit_ols(y, X):
    ols = sm.OLS(y, sm.add_constant(X)).fit()
    n, k = ols.nobs, ols.df_model + 1
    return ols, aicc_gaussian(ols.llf, n, k)


def fit_gwr(coords, y, X):
    selector = Sel_BW(coords, y, X, kernel=KERNEL, fixed=False)
    bw = selector.search(criterion="AICc")
    results = GWR(coords, y, X, bw, kernel=KERNEL, fixed=False).fit()
    return bw, results


def gwr_columns(results):
    cols = {"gwr_local_r2": results.localR2.ravel()}
    crit_t = results.critical_tval()  # multiple-testing-corrected (da Silva & Fotheringham 2016)
    for j, term in enumerate(TERMS):
        cols[f"gwr_beta_{term}"] = results.params[:, j]
        cols[f"gwr_se_{term}"] = results.bse[:, j]
        cols[f"gwr_t_{term}"] = results.tvalues[:, j]
        cols[f"gwr_sig_{term}"] = np.abs(results.tvalues[:, j]) > crit_t
    cols["gwr_local_cn"] = results.local_collinearity()[2].ravel()  # local condition number; > 30 is a warning sign
    cols["gwr_residual"] = results.resid_response.ravel()
    return pd.DataFrame(cols), crit_t


def main():
    gdf = gpd.read_file(IN_PATH, layer=LAYER)
    model = gdf["ALAND"] > 0
    print(f"Loaded {len(gdf)} tracts; fitting on {model.sum()} (excluded {(~model).sum()} all-water tract)")

    data = gdf.loc[model]
    centroids = data.geometry.centroid  # layer is EPSG:32616, so centroids are UTM meters
    coords = np.column_stack([centroids.x, centroids.y])
    y = zscore(data[[Y_COL]]).to_numpy()
    X = zscore(data[X_COLS]).to_numpy()

    ols, ols_aicc = fit_ols(y, X)
    print("\nGlobal OLS (standardized coefficients):")
    print(pd.DataFrame({"coef": ols.params, "se": ols.bse, "t": ols.tvalues, "p": ols.pvalues},
                       index=TERMS).round(4).to_string())

    print(f"\nSelecting adaptive {KERNEL} bandwidth (AICc golden-section search)...")
    bw, gwr = fit_gwr(coords, y, X)
    cols, crit_t = gwr_columns(gwr)

    out = gdf.join(cols.set_index(data.index))  # excluded tracts get NaN / <NA>
    sig_cols = [c for c in cols if c.startswith("gwr_sig_")]
    out[sig_cols] = out[sig_cols].astype("boolean")
    out.to_file(OUT_PATH, layer=LAYER, driver="GPKG")
    print(f"Saved {len(out)} tracts with {len(cols.columns)} GWR columns to {OUT_PATH} (layer '{LAYER}')")

    print("\n=== Model comparison ===")
    print(f"{'':28}{'OLS':>12}{'GWR':>12}")
    print(f"{'R²':28}{ols.rsquared:>12.4f}{gwr.R2:>12.4f}")
    print(f"{'Adj. R²':28}{ols.rsquared_adj:>12.4f}{gwr.adj_R2:>12.4f}")
    print(f"{'Mean local R²':28}{'':>12}{gwr.localR2.mean():>12.4f}")
    print(f"{'AICc':28}{ols_aicc:>12.2f}{gwr.aicc:>12.2f}")
    print(f"Optimal bandwidth: {bw:.0f} nearest neighbors (adaptive {KERNEL}); effective parameters: {gwr.tr_S:.1f}")
    print(f"Corrected critical |t| (alpha 0.05): {crit_t:.3f}")

    print("\nLocal coefficients (standardized):")
    summary = pd.DataFrame({
        "min": gwr.params.min(axis=0), "median": np.median(gwr.params, axis=0), "max": gwr.params.max(axis=0),
        "% tracts significant": [cols[f"gwr_sig_{t}"].mean() * 100 for t in TERMS],
    }, index=TERMS)
    print(summary.round(3).to_string())
    print(f"\nTracts with local condition number > 30: {(cols['gwr_local_cn'] > 30).sum()}")


if __name__ == "__main__":
    main()
