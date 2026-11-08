"""Prepare read-only source data for additional hospital heterogeneity regressions.

Outputs are written to results/additional_hospital_analysis.  The paper, slides,
and their source files are not modified.
"""
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\Hospital_Pharmacy program")
PANEL = ROOT / "data/hospital_pharmacy/hosp_pharm_panel/hosp_pharm_v5_xqdistance.dta"
CENSUS = ROOT / "data/county/controls/第六次全国人口普查数据—区县整理版.xlsx"
COUNTY_PANEL = ROOT / "data/county/controls/county_panel_1020.dta"
HOSP_TYPE = ROOT / "data/hospital/AOI/hosp_final_clean_v4_name_classified.csv"
GROSS = ROOT / "data/hospital_pharmacy/hosp_pharm_panel/hospital_pharmacy_gross_flows.csv"
OUT = ROOT / "results/additional_hospital_analysis"
OUT.mkdir(parents=True, exist_ok=True)


def unique_column(columns: pd.Index, *needles: str) -> str:
    matches = [str(c) for c in columns if all(n in str(c) for n in needles)]
    if len(matches) != 1:
        raise ValueError(f"Expected one column containing {needles}, found {matches}")
    return matches[0]


def main() -> None:
    panel = pd.read_stata(
        PANEL,
        columns=[
            "hospital_id", "year", "spatial_province", "spatial_city",
            "spatial_county",
        ],
        convert_categoricals=False,
    )
    hospitals = panel.drop_duplicates("hospital_id").copy()

    census = pd.read_excel(CENSUS, sheet_name="原始数据")
    total_col = unique_column(census.columns, "人口统计-总人口_人")
    urban_col = unique_column(census.columns, "城乡人口-城镇人口数_人")
    educ_col = unique_column(census.columns, "平均受教育年限_年")
    elderly_age_bands = ["65-69岁", "70-74岁", "75-79岁", "80-84岁", "85岁以上"]
    elderly_count_cols = [
        str(col)
        for col in census.columns
        if str(col).startswith("人口统计-总人口-")
        and any(band in str(col) for band in elderly_age_bands)
        and str(col).endswith("_人")
    ]
    if len(elderly_count_cols) != 10:
        raise ValueError(f"Expected 10 elderly sex-by-age columns, found {elderly_count_cols}")
    census = census[
        ["行政区划代码", "所属省份", "所属城市", "地区", total_col,
         urban_col, educ_col] + elderly_count_cols
    ].copy()
    census = census.rename(
        columns={
            "行政区划代码": "census_code",
            "所属省份": "spatial_province",
            "所属城市": "spatial_city",
            "地区": "spatial_county",
            total_col: "census_pop2010",
            urban_col: "census_urban_pop2010",
            educ_col: "avg_education2010",
        }
    )
    census = census.drop_duplicates(
        ["spatial_province", "spatial_city", "spatial_county"], keep="first"
    )
    for col in ["census_pop2010", "census_urban_pop2010", "avg_education2010"] + elderly_count_cols:
        census[col] = pd.to_numeric(census[col], errors="coerce")
    census["elderly_pop2010"] = census[elderly_count_cols].sum(axis=1, min_count=len(elderly_count_cols))
    census["elderly_share2010"] = 100 * census["elderly_pop2010"] / census["census_pop2010"]
    census.loc[~census["elderly_share2010"].between(0, 100), "elderly_share2010"] = np.nan
    census["urban_share2010"] = (
        100 * census["census_urban_pop2010"] / census["census_pop2010"]
    )
    census.loc[~census["urban_share2010"].between(0, 100), "urban_share2010"] = np.nan

    area = pd.read_stata(
        COUNTY_PANEL,
        columns=["province", "city", "county", "county_area"],
        convert_categoricals=False,
    )
    area = area.dropna(subset=["county_area"]).drop_duplicates(
        ["province", "city", "county"], keep="first"
    )
    area = area.rename(
        columns={
            "province": "spatial_province",
            "city": "spatial_city",
            "county": "spatial_county",
            "county_area": "county_area_m2",
        }
    )

    controls = hospitals.merge(
        census,
        on=["spatial_province", "spatial_city", "spatial_county"],
        how="left",
        validate="many_to_one",
        indicator="census_merge",
    ).merge(
        area,
        on=["spatial_province", "spatial_city", "spatial_county"],
        how="left",
        validate="many_to_one",
        indicator="area_merge",
    )
    controls["population_density2010"] = (
        controls["census_pop2010"] * 1_000_000 / controls["county_area_m2"]
    )
    controls.loc[
        ~(controls["population_density2010"] > 0), "population_density2010"
    ] = np.nan
    controls["ln_population_density2010"] = np.log(
        controls["population_density2010"]
    )

    types = pd.read_csv(
        HOSP_TYPE,
        encoding="utf-8-sig",
        low_memory=False,
        usecols=["hospital_id", "hospital_type_final_ai", "hospital_type_final_source"],
    )
    types = types.drop_duplicates("hospital_id", keep="first")
    types["hospital_specialist"] = np.select(
        [
            types["hospital_type_final_ai"].eq("专科医院"),
            types["hospital_type_final_ai"].eq("全科（综合）医院"),
        ],
        [1, 0],
        default=np.nan,
    )
    controls = controls.merge(types, on="hospital_id", how="left", validate="one_to_one")

    keep = [
        "hospital_id", "census_code", "elderly_share2010", "urban_share2010",
        "avg_education2010", "population_density2010", "ln_population_density2010",
        "hospital_specialist", "hospital_type_final_ai", "hospital_type_final_source",
    ]
    prepared = controls[keep].copy()
    for col in prepared.select_dtypes(include=["object", "string"]).columns:
        prepared[col] = prepared[col].fillna("").astype(str)
    prepared.to_stata(OUT / "hospital_characteristics.dta", write_index=False, version=118)
    prepared.to_csv(OUT / "hospital_characteristics.csv", index=False, encoding="utf-8-sig")

    gross = pd.read_csv(GROSS, encoding="utf-8-sig", low_memory=False)
    gross.to_stata(OUT / "hospital_pharmacy_gross_flows.dta", write_index=False, version=118)

    audit_rows = [
        {"metric": "hospital_ids", "value": len(hospitals)},
        {"metric": "census_exact_matches", "value": int(controls["census_merge"].eq("both").sum())},
        {"metric": "area_exact_matches", "value": int(controls["area_merge"].eq("both").sum())},
        {"metric": "elderly_nonmissing", "value": int(controls["elderly_share2010"].notna().sum())},
        {"metric": "urban_nonmissing", "value": int(controls["urban_share2010"].notna().sum())},
        {"metric": "education_nonmissing", "value": int(controls["avg_education2010"].notna().sum())},
        {"metric": "density_nonmissing", "value": int(controls["ln_population_density2010"].notna().sum())},
        {"metric": "general_hospitals", "value": int(controls["hospital_specialist"].eq(0).sum())},
        {"metric": "specialist_hospitals", "value": int(controls["hospital_specialist"].eq(1).sum())},
    ]
    pd.DataFrame(audit_rows).to_csv(OUT / "merge_audit.csv", index=False, encoding="utf-8-sig")
    print(pd.DataFrame(audit_rows).to_string(index=False))
    print("saved", OUT)


if __name__ == "__main__":
    main()
