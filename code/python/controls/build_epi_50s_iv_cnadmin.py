# -*- coding: utf-8 -*-
"""
Build 1950s epidemiology-station IVs using cnadmin's underlying historical
administrative-code database.

This implements the same principle as `cnadmin 1986 2019`: trace GB86 county
codes through the administrative lineage graph and allocate split units with
1/N weights. It avoids a Stata/Python block parsing problem observed when
running the cnadmin ado in this Windows Stata 17 setup.
"""

from __future__ import annotations

import collections
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\Hospital_Pharmacy program")
RAW = (
    ROOT
    / "data"
    / "raw"
    / "controls"
    / "China county-level data on hospitals and epidemiology stations, 1950-1985"
    / "China county-level data on hospitals and epidemiology stations, 1950-1985"
)
DATA = ROOT / "data" / "processed" / "hospital_pharmacy" / "county_pharmacy_panel"
OUT = ROOT / "output" / "regression" / "controls"
CNADMIN_DATA = ROOT / "code" / "stata" / "external" / "cnadmin" / "cnadmin_data.maint"


def to_int(x):
    try:
        if pd.isna(x):
            return None
        return int(float(x))
    except Exception:
        return None


def load_epi_iv() -> pd.DataFrame:
    epi = pd.read_csv(RAW / "episxq.dat", sep="\t", dtype={"GB86SXQ": "string"})
    numeric_cols = [c for c in epi.columns if c != "GB86SXQ"]
    epi[numeric_cols] = epi[numeric_cols].apply(pd.to_numeric, errors="coerce")
    epi[numeric_cols] = epi[numeric_cols].mask(epi[numeric_cols] < 0)

    fnd_50s = [f"EFND{year:02d}" for year in range(50, 60)]
    iv = pd.DataFrame({"gb86sxq": epi["GB86SXQ"].astype("string").str.zfill(6)})
    iv["epi_fnd_50s"] = epi[fnd_50s].sum(axis=1, min_count=1)
    iv["epi_cnt_1959"] = epi["ECNT59"]
    iv["epi_yrs_50s"] = epi["EYRS59"]
    iv["epi_any_50s"] = np.where(iv["epi_cnt_1959"].notna(), (iv["epi_cnt_1959"] > 0).astype("int8"), np.nan)

    first_year = pd.Series(pd.NA, index=epi.index, dtype="Int64")
    for year in range(50, 60):
        col = f"EFND{year:02d}"
        mask = first_year.isna() & (epi[col].fillna(0) > 0)
        first_year.loc[mask] = 1900 + year
    iv["epi_first_year_50s"] = first_year
    iv["ln_epi_cnt_1959_1p"] = np.log(iv["epi_cnt_1959"] + 1)
    iv["ln_epi_yrs_50s_1p"] = np.log(iv["epi_yrs_50s"] + 1)
    return iv


def build_cnadmin_graph():
    df = pd.read_csv(CNADMIN_DATA, dtype=str, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    df["start_yr"] = df["启用时间"].apply(to_int)
    df["end_yr"] = df["变更/弃用时间"].apply(to_int)

    events = collections.defaultdict(lambda: collections.defaultdict(list))
    death_years = {}
    birth_years = {}
    code_info_history = collections.defaultdict(list)

    for _, row in df.iterrows():
        code = str(row["代码"]).strip()
        if not code or code == "nan":
            continue

        prov = "" if pd.isna(row["一级行政区"]) else str(row["一级行政区"]).strip()
        city = "" if pd.isna(row["二级行政区"]) else str(row["二级行政区"]).strip()
        name = "" if pd.isna(row["名称"]) else str(row["名称"]).strip()
        status = "" if pd.isna(row["状态"]) else str(row["状态"]).strip()
        start_yr = row["start_yr"]
        end_yr = row["end_yr"]

        if start_yr is not None:
            birth_years[code] = min(start_yr, birth_years.get(code, start_yr))
        code_info_history[code].append((start_yr, end_yr if end_yr is not None else 9999, prov, city, name))

        if status == "弃用" and end_yr is not None:
            death_years[code] = end_yr

        new_codes = "" if pd.isna(row["新代码"]) else str(row["新代码"]).strip()
        if new_codes and new_codes not in {"nan", "None"}:
            for part in new_codes.split(";"):
                part = part.strip()
                if not part:
                    continue
                if "[" in part:
                    target = part.split("[")[0]
                    year = int(part.split("[")[1].replace("]", ""))
                else:
                    target = part
                    year = end_yr if end_yr is not None else 9999
                if year != 9999:
                    events[code][year].append(target)

    return events, death_years, birth_years, code_info_history


def trace_forward(code, current_year, target_year, events, death_years, memo):
    key = (code, current_year, target_year)
    if key in memo:
        return memo[key]

    valid_years = sorted(y for y in events[code].keys() if current_year < y <= target_year)
    if not valid_years:
        if code not in death_years or death_years[code] > target_year:
            memo[key] = [code]
        else:
            memo[key] = []
        return memo[key]

    next_year = valid_years[0]
    targets = events[code][next_year]
    result = []
    for target in targets:
        result.extend(trace_forward(target, next_year, target_year, events, death_years, memo))

    died_at_change = code in death_years and death_years[code] == next_year
    if not died_at_change:
        result.extend(trace_forward(code, next_year, target_year, events, death_years, memo))

    memo[key] = sorted(set(result))
    return memo[key]


def get_info(code, target_year, code_info_history):
    hist = code_info_history.get(code, [])
    for start_yr, end_yr, prov, city, name in hist:
        if start_yr is not None and start_yr <= target_year <= end_yr:
            return prov, city, name
    if hist:
        last = sorted(hist, key=lambda x: x[1])[-1]
        return last[2], last[3], last[4]
    return "", "", ""


def build_crosswalk(source_codes: pd.Series) -> pd.DataFrame:
    events, death_years, _birth_years, code_info_history = build_cnadmin_graph()
    memo = {}
    rows = []
    for gb86 in sorted(set(source_codes.dropna().astype(str).str.zfill(6))):
        targets = trace_forward(gb86, 1986, 2019, events, death_years, memo)
        if not targets:
            rows.append({"gb86sxq": gb86, "county_id": np.nan, "cw_weight": np.nan, "cw_type": 0})
            continue
        weight = 1.0 / len(targets)
        from_info = get_info(gb86, 1986, code_info_history)
        for target in targets:
            to_info = get_info(target, 2019, code_info_history)
            if len(targets) > 1:
                cw_type = 3
            elif gb86 == target and from_info[2] == to_info[2]:
                cw_type = 1
            else:
                cw_type = 2
            rows.append(
                {
                    "gb86sxq": gb86,
                    "county_id": int(target) if str(target).isdigit() else np.nan,
                    "county_id_2019": str(target).zfill(6),
                    "cw_weight": weight,
                    "cw_type": cw_type,
                    "province_1986": from_info[0],
                    "city_1986": from_info[1],
                    "county_1986": from_info[2],
                    "province_2019": to_info[0],
                    "city_2019": to_info[1],
                    "county_2019": to_info[2],
                }
            )
    return pd.DataFrame(rows)


def write_outputs(iv_gb86: pd.DataFrame, cw: pd.DataFrame) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    iv_gb86.to_csv(DATA / "epi_50s_iv_gb86sxq.csv", index=False, encoding="utf-8-sig")
    iv_gb86.to_stata(DATA / "epi_50s_iv_gb86sxq.dta", write_index=False, version=118)

    cw.to_csv(DATA / "crosswalk_gb86sxq_to_pac19_cnadmin.csv", index=False, encoding="utf-8-sig")
    cw.to_stata(DATA / "crosswalk_gb86sxq_to_pac19_cnadmin.dta", write_index=False, version=118)

    merged = cw.merge(iv_gb86, on="gb86sxq", how="left")
    for var in [
        "epi_fnd_50s",
        "epi_cnt_1959",
        "epi_yrs_50s",
        "epi_any_50s",
        "ln_epi_cnt_1959_1p",
        "ln_epi_yrs_50s_1p",
    ]:
        merged[f"w_{var}"] = merged[var] * merged["cw_weight"]

    iv_pac19 = (
        merged.dropna(subset=["county_id"])
        .groupby("county_id", as_index=False)
        .agg(
            epi_fnd_50s=("w_epi_fnd_50s", "sum"),
            epi_cnt_1959=("w_epi_cnt_1959", "sum"),
            epi_yrs_50s=("w_epi_yrs_50s", "sum"),
            epi_any_50s=("w_epi_any_50s", "sum"),
            ln_epi_cnt_1959_1p=("w_ln_epi_cnt_1959_1p", "sum"),
            ln_epi_yrs_50s_1p=("w_ln_epi_yrs_50s_1p", "sum"),
            n_gb86_sources=("gb86sxq", "nunique"),
        )
    )
    iv_pac19["county_id"] = iv_pac19["county_id"].astype("int64")
    iv_pac19["epi_iv_crosswalk_method"] = 1
    iv_pac19.to_csv(DATA / "epi_50s_iv_pac19_cnadmin.csv", index=False, encoding="utf-8-sig")
    iv_pac19.to_stata(DATA / "epi_50s_iv_pac19_cnadmin.dta", write_index=False, version=118)

    panel = pd.read_stata(DATA / "county_pharmacy_panel_all_years.dta", convert_categoricals=False)
    panel_iv = panel.merge(iv_pac19, on="county_id", how="left", indicator="merge_epi_50s_iv")
    panel_iv["merge_epi_50s_iv"] = panel_iv["merge_epi_50s_iv"].map({"left_only": 1, "both": 3}).astype("int8")
    panel_iv.to_stata(DATA / "county_pharmacy_panel_all_years_epi50s_iv_cnadmin.dta", write_index=False, version=118)

    quality = cw["cw_type"].value_counts(dropna=False).sort_index().rename_axis("cw_type").reset_index(name="count")
    quality.to_csv(OUT / "epi_50s_cnadmin_match_quality.csv", index=False, encoding="utf-8-sig")
    by_year = panel_iv.groupby(["year", "merge_epi_50s_iv"]).size().reset_index(name="count")
    by_year.to_csv(OUT / "merge_epi_50s_iv_cnadmin_by_year.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    iv_gb86 = load_epi_iv()
    cw = build_crosswalk(iv_gb86["gb86sxq"])
    write_outputs(iv_gb86, cw)
    print("GB86 IV rows:", len(iv_gb86))
    print("Crosswalk rows:", len(cw), "unique target counties:", cw["county_id"].nunique(dropna=True))
    print(cw["cw_type"].value_counts(dropna=False).sort_index())


if __name__ == "__main__":
    main()
