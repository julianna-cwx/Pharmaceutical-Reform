"""Describe whether newly observed pharmacies near hospitals are chain stores.

Entry follows the hospital gross-flow analysis: a shop_id present in year t but
absent in t-1.  Distance is straight-line distance from the hospital AOI point.
Each entrant is counted once per radius even if it is close to several hospitals.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(r"D:\Hospital_Pharmacy program")
PHARM = ROOT / "data/pharmacy/pharm_final"
HOSP = ROOT / "data/hospital_pharmacy/hosp_pharm_panel/hosp_pharm_v5.csv"
OUT = ROOT / "results/hospital_entry_chain"
RADII = (200, 500, 800, 1000)
EARTH = 6_371_008.8


def xyz(lon, lat):
    lon = np.radians(np.asarray(lon, dtype=float))
    lat = np.radians(np.asarray(lat, dtype=float))
    c = np.cos(lat)
    return np.column_stack((c * np.cos(lon), c * np.sin(lon), np.sin(lat)))


def read_pharm(year):
    f = PHARM / f"dzdp_pharmacies_final_{year}.csv"
    d = pd.read_csv(
        f,
        usecols=["shop_id", "name", "is_chains", "lon_wgs", "lat_wgs"],
        dtype={"shop_id": "string", "name": "string", "is_chains": "string"},
        low_memory=False,
    )
    d["lon_wgs"] = pd.to_numeric(d.lon_wgs, errors="coerce")
    d["lat_wgs"] = pd.to_numeric(d.lat_wgs, errors="coerce")
    cmap = {"1": 1, "true": 1, "yes": 1, "是": 1, "0": 0, "false": 0, "no": 0, "否": 0}
    d["chain"] = d.is_chains.str.strip().str.lower().map(cmap)
    d = d.loc[d.lon_wgs.between(-180, 180) & d.lat_wgs.between(-90, 90)]
    return d.drop_duplicates("shop_id", keep="first").reset_index(drop=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    h = pd.read_csv(HOSP, usecols=["year", "wgs_aoi_lng", "wgs_aoi_lat"], low_memory=False)
    h = h.loc[h.year.between(2014, 2018)]
    h = h.loc[h.wgs_aoi_lng.between(-180, 180) & h.wgs_aoi_lat.between(-90, 90)]
    panels = {y: read_pharm(y) for y in range(2013, 2019)}
    rows, entrants_all, national_rows = [], [], []

    for year in range(2014, 2019):
        cur, prev = panels[year], panels[year - 1]
        entrants = cur.loc[~cur.shop_id.isin(set(prev.shop_id))].copy()
        national_known = entrants.chain.notna().sum()
        national_rows.append({
            "year": year,
            "all_entrants": len(entrants),
            "all_chain_known": int(national_known),
            "all_chain_entrants": int(entrants.chain.eq(1).sum()),
            "all_chain_share_known": entrants.chain.eq(1).sum() / national_known if national_known else np.nan,
        })
        tree = cKDTree(xyz(h.loc[h.year.eq(year), "wgs_aoi_lng"], h.loc[h.year.eq(year), "wgs_aoi_lat"]))
        distance, _ = tree.query(xyz(entrants.lon_wgs, entrants.lat_wgs), k=1)
        entrants["nearest_hospital_m"] = 2 * EARTH * np.arcsin(np.clip(distance / 2, 0, 1))
        entrants["year"] = year
        entrants_all.append(entrants[["year", "shop_id", "name", "chain", "nearest_hospital_m"]])
        for radius in RADII:
            s = entrants.loc[entrants.nearest_hospital_m.le(radius)]
            known = s.chain.notna().sum()
            rows.append({
                "year": year,
                "radius_m": radius,
                "entrants": len(s),
                "chain_known": int(known),
                "chain_entrants": int(s.chain.eq(1).sum()),
                "nonchain_entrants": int(s.chain.eq(0).sum()),
                "chain_share_known": s.chain.eq(1).sum() / known if known else np.nan,
            })

    detail = pd.concat(entrants_all, ignore_index=True)
    annual = pd.DataFrame(rows)
    national = pd.DataFrame(national_rows)
    annual = annual.merge(national, on="year", how="left", validate="many_to_one")
    annual["near_minus_all_chain_share_pp"] = 100 * (
        annual.chain_share_known - annual.all_chain_share_known
    )
    pooled = (annual.groupby("radius_m", as_index=False)
              .agg(entrants=("entrants", "sum"), chain_known=("chain_known", "sum"),
                   chain_entrants=("chain_entrants", "sum"), nonchain_entrants=("nonchain_entrants", "sum")))
    pooled["chain_share_known"] = pooled.chain_entrants / pooled.chain_known
    annual.to_csv(OUT / "entry_chain_by_year_radius.csv", index=False, encoding="utf-8-sig")
    pooled.to_csv(OUT / "entry_chain_pooled.csv", index=False, encoding="utf-8-sig")
    detail.to_csv(OUT / "entrant_nearest_hospital_detail.csv", index=False, encoding="utf-8-sig")

    # Names are not standardized brand IDs; this table is only a transparent
    # frequency check among records already labelled as chains.
    near500 = detail.loc[detail.nearest_hospital_m.le(500) & detail.chain.eq(1)].copy()
    top_names = (near500.groupby("name", dropna=False).size().rename("entrant_records")
                 .reset_index().sort_values("entrant_records", ascending=False).head(50))
    top_names.to_csv(OUT / "chain_entrant_top_names_500m.csv", index=False, encoding="utf-8-sig")
    print(pooled.to_string(index=False))
    print("\nMissing chain among entrants within 500m:",
          int(detail.loc[detail.nearest_hospital_m.le(500), "chain"].isna().sum()))
    print("Saved to", OUT)


if __name__ == "__main__":
    main()
