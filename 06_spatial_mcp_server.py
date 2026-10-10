"""MCP server exposing the Cook County heat-vulnerability / GWR results to an LLM via DuckDB Spatial.

No PostGIS credentials are configured, so data lives in a local DuckDB database (cook_county.duckdb, table
cook_county_gwr). Geometry (`geom`) is EPSG:32616 (UTM 16N, meters); `lon`/`lat` are WGS84 tract centroids.

    .venv/bin/python 06_spatial_mcp_server.py --load   # (re)build the database from the GWR GeoPackage and exit
    .venv/bin/python 06_spatial_mcp_server.py          # run the MCP server over stdio (builds the database if missing)
"""

import argparse
import math
import sys
from pathlib import Path

import duckdb
from mcp.server.mcpserver import MCPServer

ROOT = Path(__file__).resolve().parent
GPKG_PATH = ROOT / "data" / "cook_county_gwr_results.gpkg"
DB_PATH = ROOT / "cook_county.duckdb"
LAYER = "tracts_2022"
TABLE = "cook_county_gwr"
MAX_ROWS = 500
MAX_TOP_N = 100

TERMS = ["intercept", "tree_canopy_pct", "pca_socioeconomic_deprivation", "impervious_pct"]
SECTIONS = {
    "tract": ["GEOID", "NAMELSAD", "ALAND", "AWATER", "lon", "lat"],
    "demographics": ["median_income", "poverty_rate", "minority_rate", "elderly_rate", "renter_rate",
                     "pca_socioeconomic_deprivation", "pca_demographic_age"],
    "climate": ["lst_c", "tree_canopy_pct", "impervious_pct", "lisa_cluster", "lisa_i", "lisa_p"],
    "gwr": ["gwr_local_r2", "gwr_local_cn", "gwr_residual",
            *[f"gwr_{stat}_{t}" for t in TERMS for stat in ("beta", "se", "t", "sig")]],
}
# find_hotspots metric name -> column
METRICS = {
    "heat": "lst_c",
    "vulnerability": "pca_socioeconomic_deprivation",
    "elderly": "pca_demographic_age",
    "impervious": "impervious_pct",
    "beta_tree_canopy": "gwr_beta_tree_canopy_pct",
    "beta_deprivation": "gwr_beta_pca_socioeconomic_deprivation",
    "beta_impervious": "gwr_beta_impervious_pct",
    "local_r2": "gwr_local_r2",
}

mcp = MCPServer(
    "cook-county-spatial",
    instructions=(
        f"Census tracts of Cook County, IL (2022) in DuckDB table {TABLE}: ACS demographics, summer 2022 land surface "
        "temperature (lst_c, °C), NLCD tree canopy / impervious %, LISA heat clusters and GWR results "
        "(lst_c ~ tree canopy + deprivation + impervious; standardized coefficients)."
    ),
)


def load_database():
    if not GPKG_PATH.exists():
        raise SystemExit(f"{GPKG_PATH} not found; run 05_fit_gwr.py first")
    with duckdb.connect(str(DB_PATH)) as con:
        con.install_extension("spatial")
        con.load_extension("spatial")
        con.execute(f"""
            CREATE OR REPLACE TABLE {TABLE} AS
            SELECT * EXCLUDE (geom),
                   ST_X(c) AS lon, ST_Y(c) AS lat,
                   geom
            FROM (
                SELECT *, ST_Transform(ST_Centroid(geom), 'EPSG:32616', 'EPSG:4326', always_xy := true) AS c
                FROM ST_Read('{GPKG_PATH}', layer = '{LAYER}')
            )
        """)
        con.execute(f"ALTER TABLE {TABLE} DROP COLUMN c")
        n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    print(f"Loaded {n} tracts into {DB_PATH.name} (table {TABLE})", file=sys.stderr)


def connect():
    """Read-only connection with filesystem/network access disabled, so arbitrary SQL can't modify or exfiltrate."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.load_extension("spatial")
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con


def clean(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (bytes, bytearray)):
        return "<geometry: select ST_AsText(geom) or ST_AsGeoJSON(geom) to read it>"
    return value


def query(sql, params=None, limit=MAX_ROWS):
    with connect() as con:
        cur = con.execute(sql, params or [])
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(limit + 1)
    return columns, [{c: clean(v) for c, v in zip(columns, row)} for row in rows[:limit]], len(rows) > limit


@mcp.tool()
def get_tract_vulnerability(geoid: str) -> dict:
    """Demographic, climate (heat, canopy, impervious, LISA cluster) and GWR results for one Cook County census tract.

    geoid: 11-digit tract GEOID (e.g. "17031030101") or 6-digit tract code (e.g. "030101").
    GWR coefficients are standardized (SD units); gwr_sig_* uses a multiple-testing-corrected critical t.
    """
    geoid = geoid.strip()
    if len(geoid) == 6:
        geoid = f"17031{geoid}"
    cols = [c for section in SECTIONS.values() for c in section]
    _, rows, _ = query(f"SELECT {', '.join(cols)} FROM {TABLE} WHERE GEOID = ?", [geoid])
    if not rows:
        return {"error": f"No tract with GEOID {geoid!r} in Cook County"}
    return {name: {c: rows[0][c] for c in section} for name, section in SECTIONS.items()}


@mcp.tool()
def find_hotspots(metric: str = "heat", top_n: int = 10, lowest: bool = False) -> dict:
    """Top N tracts ranked by a metric (highest first; lowest=True for the bottom N).

    metric: heat (lst_c), vulnerability (socioeconomic deprivation PCA score), elderly (age PCA score), impervious,
    beta_tree_canopy, beta_deprivation, beta_impervious (local GWR coefficients), local_r2.
    Tree canopy betas are mostly negative (cooling); use lowest=True to find where canopy cools most.
    """
    if metric not in METRICS:
        return {"error": f"Unknown metric {metric!r}", "valid_metrics": list(METRICS)}
    col = METRICS[metric]
    top_n = max(1, min(int(top_n), MAX_TOP_N))
    order = "ASC" if lowest else "DESC"
    _, rows, _ = query(f"""
        SELECT GEOID, NAMELSAD, {col} AS value, lst_c, tree_canopy_pct, pca_socioeconomic_deprivation,
               lisa_cluster, lon, lat
        FROM {TABLE}
        WHERE {col} IS NOT NULL
        ORDER BY {col} {order}
        LIMIT {top_n}
    """)
    return {"metric": metric, "column": col, "order": order.lower(), "tracts": rows}


@mcp.tool()
def query_spatial_stats(sql_query: str) -> dict:
    """Run a read-only DuckDB Spatial SQL query against table cook_county_gwr (one row per tract, 1332 rows).

    Geometry column `geom` is EPSG:32616 (meters), so ST_Area/ST_Distance return m² / m; lon/lat are WGS84 centroids.
    Key columns: GEOID, NAMELSAD, median_income, poverty_rate, minority_rate, elderly_rate, renter_rate,
    pca_socioeconomic_deprivation, pca_demographic_age, lst_c, tree_canopy_pct, impervious_pct,
    lisa_cluster ('High-High', 'Low-Low', 'High-Low', 'Low-High', 'Not Significant'), gwr_local_r2,
    gwr_beta_/gwr_se_/gwr_t_/gwr_sig_ + (intercept | tree_canopy_pct | pca_socioeconomic_deprivation | impervious_pct).
    Results are capped at 500 rows; wrap geometries in ST_AsText()/ST_AsGeoJSON() to read them.
    """
    try:
        columns, rows, truncated = query(sql_query)
    except duckdb.Error as e:
        return {"error": str(e)}
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--load", action="store_true", help="(re)build the DuckDB database and exit")
    args = parser.parse_args()

    if args.load:
        load_database()
        return
    if not DB_PATH.exists():
        load_database()
    mcp.run("stdio")


if __name__ == "__main__":
    main()
