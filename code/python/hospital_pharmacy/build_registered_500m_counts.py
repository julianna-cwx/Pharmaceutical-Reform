import os

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree


ROOT = r"D:\Hospital_Pharmacy program"
COUNTS_DIR = os.path.join(
    ROOT,
    "data",
    "processed",
    "hospital_pharmacy",
    "hospital_with_pharmacy_counts_registered",
)
PHARMACY_DIR = os.path.join(
    ROOT,
    "data",
    "processed",
    "pharmacy",
    "real_pharmacy_data",
)

PANEL_CSV = os.path.join(COUNTS_DIR, "hospital_pharmacy_2012_2022.csv")
PANEL_DTA = os.path.join(COUNTS_DIR, "hospital_pharmacy_2012_2022.dta")

EARTH_RADIUS_M = 6_371_008.8
RADIUS_M = 500.0


def read_csv_flexible(path):
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "gb2312"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, low_memory=False)


def normalize_chain_flag(series):
    if series is None:
        return pd.Series(dtype="int8")
    s = series.copy()
    if s.dtype == object:
        s = s.astype(str).str.strip().str.lower()
        s = s.isin(["1", "true", "yes", "y", "chain", "连锁"]).astype("int8")
    else:
        s = pd.to_numeric(s, errors="coerce").fillna(0).astype("int8")
    return s


def compute_year_500m(year):
    count_path = os.path.join(COUNTS_DIR, f"hospital_with_pharmacy_counts_{year}.csv")
    pharmacy_path = os.path.join(
        PHARMACY_DIR,
        f"real_pharmacy_dzdp_pharmacies_{year}.csv",
    )

    if not os.path.exists(count_path):
        raise FileNotFoundError(count_path)
    if not os.path.exists(pharmacy_path):
        raise FileNotFoundError(pharmacy_path)

    hospitals = read_csv_flexible(count_path)
    pharmacies = read_csv_flexible(pharmacy_path)

    hospitals["pharmacy_count_500m"] = 0
    hospitals["chain_pharmacy_count_500m"] = 0

    h_lon = pd.to_numeric(hospitals.get("wgs_lon_true"), errors="coerce")
    h_lat = pd.to_numeric(hospitals.get("wgs_lat_true"), errors="coerce")
    p_lon = pd.to_numeric(pharmacies.get("lon_wgs"), errors="coerce")
    p_lat = pd.to_numeric(pharmacies.get("lat_wgs"), errors="coerce")

    valid_h = h_lon.notna() & h_lat.notna()
    valid_p = p_lon.notna() & p_lat.notna()

    if valid_h.any() and valid_p.any():
        pharmacy_coords = np.deg2rad(
            np.column_stack([p_lat.loc[valid_p].to_numpy(), p_lon.loc[valid_p].to_numpy()])
        )
        hospital_coords = np.deg2rad(
            np.column_stack([h_lat.loc[valid_h].to_numpy(), h_lon.loc[valid_h].to_numpy()])
        )

        tree = BallTree(pharmacy_coords, metric="haversine")
        neighbors = tree.query_radius(hospital_coords, r=RADIUS_M / EARTH_RADIUS_M)

        if "is_chains" in pharmacies.columns:
            chain_source = pharmacies.loc[valid_p, "is_chains"]
        else:
            chain_source = pd.Series(0, index=pharmacies.index[valid_p])
        chain_flag = normalize_chain_flag(chain_source)
        chain_arr = chain_flag.to_numpy()

        h_index = hospitals.index[valid_h].to_numpy()
        counts = np.fromiter((len(idx) for idx in neighbors), dtype=np.int64)
        chain_counts = np.fromiter((chain_arr[idx].sum() for idx in neighbors), dtype=np.int64)

        hospitals.loc[h_index, "pharmacy_count_500m"] = counts
        hospitals.loc[h_index, "chain_pharmacy_count_500m"] = chain_counts

    hospitals.to_csv(count_path, index=False, encoding="utf-8-sig")
    print(
        f"{year}: saved 500m counts to {count_path}; "
        f"mean count={hospitals['pharmacy_count_500m'].mean():.3f}"
    )

    return hospitals[["id", "pharmacy_count_500m", "chain_pharmacy_count_500m"]].assign(
        year=year
    )


def update_panel(yearly_500m):
    panel = read_csv_flexible(PANEL_CSV)
    add = pd.concat(yearly_500m, ignore_index=True)

    for col in ("pharmacy_count_500m", "chain_pharmacy_count_500m"):
        if col in panel.columns:
            panel = panel.drop(columns=[col])

    panel = panel.merge(add, on=["id", "year"], how="left")
    for col in ("pharmacy_count_500m", "chain_pharmacy_count_500m"):
        panel[col] = pd.to_numeric(panel[col], errors="coerce").fillna(0).astype("int64")

    panel.to_csv(PANEL_CSV, index=False, encoding="utf-8-sig")
    panel.to_stata(PANEL_DTA, write_index=False, version=118)
    print(f"Updated panel CSV: {PANEL_CSV}")
    print(f"Updated panel DTA: {PANEL_DTA}")
    print(f"Panel rows: {len(panel):,}; columns: {len(panel.columns):,}")


def main():
    yearly = [compute_year_500m(year) for year in range(2012, 2023)]
    update_panel(yearly)


if __name__ == "__main__":
    main()
