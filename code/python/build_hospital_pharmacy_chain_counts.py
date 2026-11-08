"""Build hospital-year chain and non-chain pharmacy counts for heterogeneity.

The distance convention matches the gross entry/exit builder: great-circle
distance from the hospital AOI point.  `is_chains` is the source classification;
it does not distinguish national large chains from smaller local chains.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(r"D:\Hospital_Pharmacy program")
PHARM = ROOT / "data/pharmacy/pharm_final"
HOSP = ROOT / "data/hospital_pharmacy/hosp_pharm_panel/hosp_pharm_v5.csv"
OUT = ROOT / "data/hospital_pharmacy/hosp_pharm_panel/hospital_pharmacy_chain_counts"
RADII = (200, 500, 800, 1000)
EARTH = 6_371_008.8


def xyz(lon, lat):
    lon, lat = np.radians(lon), np.radians(lat)
    c = np.cos(lat)
    return np.column_stack((c * np.cos(lon), c * np.sin(lon), np.sin(lat)))


def read_pharm(year):
    d = pd.read_csv(
        PHARM / f"dzdp_pharmacies_final_{year}.csv",
        usecols=["shop_id", "is_chains", "lon_wgs", "lat_wgs"],
        dtype={"shop_id": "string", "is_chains": "string"}, low_memory=False,
    )
    d["lon_wgs"] = pd.to_numeric(d.lon_wgs, errors="coerce")
    d["lat_wgs"] = pd.to_numeric(d.lat_wgs, errors="coerce")
    cmap = {"1": 1, "true": 1, "yes": 1, "是": 1,
            "0": 0, "false": 0, "no": 0, "否": 0}
    d["chain"] = d.is_chains.str.strip().str.lower().map(cmap)
    d = d.loc[d.lon_wgs.between(-180, 180) & d.lat_wgs.between(-90, 90) & d.chain.notna()]
    return d.drop_duplicates("shop_id", keep="first")


def counts(points, shops):
    result = {}
    tree = cKDTree(xyz(shops.lon_wgs.to_numpy(), shops.lat_wgs.to_numpy()))
    q = xyz(points.wgs_aoi_lng.to_numpy(), points.wgs_aoi_lat.to_numpy())
    for radius in RADII:
        chord = 2 * np.sin(radius / (2 * EARTH))
        result[radius] = np.fromiter(
            (len(x) for x in tree.query_ball_point(q, chord)), dtype=np.int32, count=len(points)
        )
    return result


def main():
    h = pd.read_csv(HOSP, usecols=["hospital_id", "year", "wgs_aoi_lng", "wgs_aoi_lat"], low_memory=False)
    h = h.loc[h.year.between(2013, 2018) & h.wgs_aoi_lng.between(-180, 180) & h.wgs_aoi_lat.between(-90, 90)]
    output = []
    for year in range(2013, 2019):
        hy = h.loc[h.year.eq(year)].copy().reset_index(drop=True)
        p = read_pharm(year)
        frame = hy[["hospital_id", "year"]].copy()
        for chain, label in [(0, "nonchain"), (1, "chain")]:
            c = counts(hy, p.loc[p.chain.eq(chain)])
            for radius in RADII:
                frame[f"pharm_{label}_{radius}m"] = c[radius]
        output.append(frame)
        print(year, "hospitals", len(hy), "chain shops", int(p.chain.eq(1).sum()),
              "non-chain shops", int(p.chain.eq(0).sum()))
    final = pd.concat(output, ignore_index=True)
    final.to_csv(OUT.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    final.to_stata(OUT.with_suffix(".dta"), write_index=False, version=118)
    print("saved", OUT, "rows", len(final))


if __name__ == "__main__":
    main()
