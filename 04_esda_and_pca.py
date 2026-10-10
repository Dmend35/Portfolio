"""ESDA and feature engineering: VIF, PCA of demographic predictors, global/local Moran's I for summer LST."""

import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from esda.moran import Moran, Moran_Local
from libpysal.weights import Queen
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.tools.tools import add_constant

DATA_DIR = Path(__file__).resolve().parent / "data"
IN_PATH = DATA_DIR / "cook_county_vulnerability.gpkg"
OUT_PATH = DATA_DIR / "cook_county_processed.gpkg"
LAYER = "tracts_2022"

DEMOGRAPHICS = ["median_income", "poverty_rate", "minority_rate", "renter_rate", "elderly_rate"]
VIF_THRESHOLD = 5
LST_COL = "lst_c"
ALPHA = 0.05
PERMUTATIONS = 999
SEED = 42

# Each component is sign-flipped so that higher scores mean more of the named construct
PCA_COMPONENTS = {
    "pca_socioeconomic_deprivation": "poverty_rate",
    "pca_demographic_age": "elderly_rate",
}
# Moran_Local.q quadrant codes
LISA_LABELS = {1: "High-High", 2: "Low-High", 3: "Low-Low", 4: "High-Low"}


def calc_vif(df):
    X = add_constant(df)
    return pd.Series(
        [variance_inflation_factor(X.to_numpy(), i) for i in range(1, X.shape[1])], index=df.columns, name="VIF"
    )


def run_pca(df):
    pca = PCA(n_components=len(PCA_COMPONENTS))
    scores = pca.fit_transform(StandardScaler().fit_transform(df))
    loadings = pd.DataFrame(pca.components_.T, index=df.columns, columns=list(PCA_COMPONENTS))
    for i, (name, anchor) in enumerate(PCA_COMPONENTS.items()):
        if loadings.loc[anchor, name] < 0:
            scores[:, i] *= -1
            loadings[name] *= -1
    return pd.DataFrame(scores, index=df.index, columns=list(PCA_COMPONENTS)), loadings, pca.explained_variance_ratio_


def lisa_clusters(lisa):
    labels = pd.Series(lisa.q).map(LISA_LABELS)
    return labels.where(lisa.p_sim < ALPHA, "Not Significant").to_numpy()


def main():
    gdf = gpd.read_file(IN_PATH, layer=LAYER)
    print(f"Loaded {len(gdf)} tracts from {IN_PATH.name}\n")

    # --- Multicollinearity ---
    vif = calc_vif(gdf[DEMOGRAPHICS])
    print("Variance Inflation Factors (demographic predictors):")
    print(vif.round(2).to_string())
    high = vif[vif > VIF_THRESHOLD].index.tolist()
    print(f"Above VIF {VIF_THRESHOLD}: {high or 'none'}; PCA uses all {len(DEMOGRAPHICS)} demographic predictors\n")

    # --- PCA ---
    scores, loadings, evr = run_pca(gdf[DEMOGRAPHICS])
    gdf[scores.columns] = scores
    print("PCA explained variance ratio:")
    for name, ratio in zip(PCA_COMPONENTS, evr):
        print(f"  {name}: {ratio:.3f}")
    print(f"  cumulative: {evr.sum():.3f}")
    print("PCA loadings:")
    print(loadings.round(3).to_string(), "\n")

    # --- Spatial autocorrelation ---
    # All-water tracts (Lake Michigan) have imputed LST, which would show up as a spurious outlier and distort
    # neighbors' spatial lags, so they're left out of W and get null LISA results
    land = gdf[gdf["ALAND"] > 0]
    print(f"Spatial analysis on {len(land)} tracts (excluded {len(gdf) - len(land)} all-water tract)")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        w = Queen.from_dataframe(land, use_index=False)
    w.transform = "r"
    print(f"Queen contiguity W: {w.n} tracts, mean {w.mean_neighbors:.1f} neighbors, {len(w.islands)} islands")

    y = land[LST_COL].to_numpy()
    np.random.seed(SEED)  # Moran has no seed argument; its permutations use the global RNG
    moran = Moran(y, w, permutations=PERMUTATIONS)
    print(f"Global Moran's I ({LST_COL}): I = {moran.I:.4f}, z = {moran.z_sim:.2f}, "
          f"p (permutation) = {moran.p_sim:.4f}, p (normal) = {moran.p_norm:.2e}\n")

    lisa = Moran_Local(y, w, permutations=PERMUTATIONS, seed=SEED)
    gdf.loc[land.index, "lisa_i"] = lisa.Is
    gdf.loc[land.index, "lisa_p"] = lisa.p_sim
    gdf.loc[land.index, "lisa_cluster"] = lisa_clusters(lisa)
    print(f"LISA clusters (p < {ALPHA}):")
    print(gdf["lisa_cluster"].value_counts().to_string(), "\n")

    gdf.to_file(OUT_PATH, layer=LAYER, driver="GPKG")
    print(f"Saved {len(gdf)} tracts to {OUT_PATH} (layer '{LAYER}')")


if __name__ == "__main__":
    main()
