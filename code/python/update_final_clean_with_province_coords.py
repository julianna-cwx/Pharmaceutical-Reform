from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd


ROOT = Path(r"D:\Hospital_Pharmacy program")
CLASSIFICATION_DIR = ROOT / "data" / "hospital" / "hosp_panel" / "hosp_classification"
FINAL_CLEAN_PATH = CLASSIFICATION_DIR / "hosp_real_final_clean.csv"
PROVINCE_REVIEW_PATH = CLASSIFICATION_DIR / "hosp_real_province_diff_review.csv"
RECHECK_PATH = CLASSIFICATION_DIR / "hosp_real_different_coord_recheck.csv"
COUNTY_SHP = ROOT / "data" / "county" / "controls" / "county_boundaries" / "counties19.shp"


SPATIAL_COLS = ["spatial_province", "spatial_city", "spatial_county", "spatial_county_type"]
UPDATE_AUDIT_COLS = [
    "province_review_side",
    "province_review_confirmed_province",
    "province_review_status",
    "province_review_confidence",
    "province_coord_update_target",
    "province_coord_update_status",
    "province_coord_update_source",
    "province_coord_update_old_lon",
    "province_coord_update_old_lat",
    "province_coord_update_old_spatial_province",
    "province_coord_update_old_spatial_city",
    "province_coord_update_old_spatial_county",
    "province_coord_update_baidu_spatial_province",
    "province_coord_update_gaode_spatial_province",
]


def read_csv_auto(path: Path, **kwargs) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ["utf-8-sig", "utf-8", "gb18030", "gbk"]:
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except Exception as exc:  # noqa: BLE001 - try common Chinese CSV encodings.
            last_error = exc
    raise RuntimeError(f"Cannot read {path}") from last_error


def clean_text(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "<na>"} else text


def normalize_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().replace({"nan": "", "None": "", "<NA>": ""})


def same_text(left, right) -> bool:
    return clean_text(left) == clean_text(right) and clean_text(left) != ""


def to_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def valid_lon_lat(lon: pd.Series, lat: pd.Series) -> pd.Series:
    return lon.notna() & lat.notna() & lon.between(-180, 180) & lat.between(-90, 90)


def spatial_join_points(points: pd.DataFrame, lon_col: str, lat_col: str, counties: gpd.GeoDataFrame) -> pd.DataFrame:
    out_cols = ["companyid", "province", "city", "county", "county_type"]
    if points.empty:
        return pd.DataFrame(columns=out_cols)

    lon = to_num(points[lon_col])
    lat = to_num(points[lat_col])
    valid = valid_lon_lat(lon, lat)
    valid_points = points.loc[valid, ["companyid"]].copy()
    if valid_points.empty:
        return pd.DataFrame(columns=out_cols)

    gdf = gpd.GeoDataFrame(
        valid_points,
        geometry=gpd.points_from_xy(lon.loc[valid], lat.loc[valid]),
        crs="EPSG:4326",
    )
    joined = gpd.sjoin(
        gdf,
        counties[["省", "市", "NAME", "类型", "geometry"]],
        how="left",
        predicate="within",
    )
    joined = joined.drop_duplicates("companyid", keep="first")
    return pd.DataFrame(
        {
            "companyid": joined["companyid"].astype(str),
            "province": joined["省"].fillna("").astype(str),
            "city": joined["市"].fillna("").astype(str),
            "county": joined["NAME"].fillna("").astype(str),
            "county_type": joined["类型"].fillna("").astype(str),
        }
    )


def build_diff(row: pd.Series) -> tuple[str, bool]:
    bp = clean_text(row.get("business_province"))
    bc = clean_text(row.get("business_city"))
    bct = clean_text(row.get("business_county"))
    sp = clean_text(row.get("spatial_province"))
    sc = clean_text(row.get("spatial_city"))
    sct = clean_text(row.get("spatial_county"))

    if not (bp and sp):
        return "unmatched", False
    if bp != sp:
        return "province_diff", bct != "" and sct != "" and bct != sct
    if bc and sc and bc != sc:
        return "city_diff", bct != "" and sct != "" and bct != sct
    if bct and sct and bct != sct:
        return "county_diff", True
    return "same", False


def main() -> None:
    final = read_csv_auto(FINAL_CLEAN_PATH, dtype=str, low_memory=False).fillna("")
    recheck = read_csv_auto(RECHECK_PATH, dtype=str, low_memory=False).fillna("")
    counties = gpd.read_file(COUNTY_SHP).to_crs("EPSG:4326")

    for col in ["companyid", "spatial_province", "business_province"]:
        final[col] = normalize_series(final[col])
    recheck["companyid"] = normalize_series(recheck["companyid"])

    review_cols = [
        "companyid",
        "province_review_side",
        "province_review_confirmed_province",
        "province_review_status",
        "province_review_confidence",
    ]
    if PROVINCE_REVIEW_PATH.exists():
        review = read_csv_auto(PROVINCE_REVIEW_PATH, dtype=str, low_memory=False).fillna("")
        for col in review_cols:
            review[col] = normalize_series(review[col])
        final = final.drop(columns=[c for c in review_cols if c != "companyid" and c in final.columns], errors="ignore")
        final = final.merge(review[review_cols].drop_duplicates("companyid"), on="companyid", how="left")
    elif not all(col in final.columns for col in review_cols):
        missing_cols = [col for col in review_cols if col not in final.columns]
        raise FileNotFoundError(
            f"Missing {PROVINCE_REVIEW_PATH} and final clean lacks review columns: {missing_cols}"
        )
    for col in review_cols:
        if col != "companyid":
            final[col] = normalize_series(final[col])

    target_mask = (
        final["province_review_confirmed_province"].ne("")
        & final["spatial_province"].ne("")
        & final["province_review_confirmed_province"].ne(final["spatial_province"])
    )
    targets = final.loc[target_mask, ["companyid", "province_review_confirmed_province"]].copy()

    candidate_cols = [
        "companyid",
        "baidu_wgs_lon_recheck",
        "baidu_wgs_lat_recheck",
        "gaode_wgs_lon_recheck",
        "gaode_wgs_lat_recheck",
    ]
    candidates = targets.merge(recheck[candidate_cols].drop_duplicates("companyid"), on="companyid", how="left")

    baidu_sp = spatial_join_points(candidates, "baidu_wgs_lon_recheck", "baidu_wgs_lat_recheck", counties)
    gaode_sp = spatial_join_points(candidates, "gaode_wgs_lon_recheck", "gaode_wgs_lat_recheck", counties)
    baidu_sp = baidu_sp.rename(
        columns={
            "province": "baidu_spatial_province",
            "city": "baidu_spatial_city",
            "county": "baidu_spatial_county",
            "county_type": "baidu_spatial_county_type",
        }
    )
    gaode_sp = gaode_sp.rename(
        columns={
            "province": "gaode_spatial_province",
            "city": "gaode_spatial_city",
            "county": "gaode_spatial_county",
            "county_type": "gaode_spatial_county_type",
        }
    )
    decisions = candidates.merge(baidu_sp, on="companyid", how="left").merge(gaode_sp, on="companyid", how="left")
    decisions = decisions.fillna("")

    decision_records = {}
    for row in decisions.to_dict("records"):
        companyid = str(row["companyid"])
        correct_province = clean_text(row["province_review_confirmed_province"])
        baidu_matches = clean_text(row.get("baidu_spatial_province")) == correct_province
        gaode_matches = clean_text(row.get("gaode_spatial_province")) == correct_province

        source = ""
        status = "not_replaced_no_candidate_matches_confirmed_province"
        lon = ""
        lat = ""
        if baidu_matches:
            source = "baidu_recheck_wgs84"
            status = "replaced_baidu_matches_confirmed_province"
            lon = clean_text(row.get("baidu_wgs_lon_recheck"))
            lat = clean_text(row.get("baidu_wgs_lat_recheck"))
        elif gaode_matches:
            source = "gaode_recheck_wgs84"
            status = "replaced_gaode_matches_confirmed_province"
            lon = clean_text(row.get("gaode_wgs_lon_recheck"))
            lat = clean_text(row.get("gaode_wgs_lat_recheck"))

        decision_records[companyid] = {
            "province_coord_update_status": status,
            "province_coord_update_source": source,
            "new_lon": lon,
            "new_lat": lat,
            "baidu_spatial_province": clean_text(row.get("baidu_spatial_province")),
            "gaode_spatial_province": clean_text(row.get("gaode_spatial_province")),
        }

    for col in UPDATE_AUDIT_COLS:
        if col not in final.columns:
            final[col] = ""
    final["province_coord_update_target"] = target_mask.map({True: "True", False: "False"})
    final["province_coord_update_status"] = final["province_coord_update_status"].where(
        final["province_coord_update_status"].ne(""), "not_target"
    )

    old_lon = final["wgs_lon_true"].copy()
    old_lat = final["wgs_lat_true"].copy()
    old_spatial = {col: final[col].copy() for col in SPATIAL_COLS}

    replaced = 0
    not_replaced = 0
    for idx, row in final.loc[target_mask].iterrows():
        companyid = str(row["companyid"])
        decision = decision_records.get(companyid, {})
        final.at[idx, "province_coord_update_old_lon"] = old_lon.at[idx]
        final.at[idx, "province_coord_update_old_lat"] = old_lat.at[idx]
        final.at[idx, "province_coord_update_old_spatial_province"] = old_spatial["spatial_province"].at[idx]
        final.at[idx, "province_coord_update_old_spatial_city"] = old_spatial["spatial_city"].at[idx]
        final.at[idx, "province_coord_update_old_spatial_county"] = old_spatial["spatial_county"].at[idx]
        final.at[idx, "province_coord_update_baidu_spatial_province"] = decision.get("baidu_spatial_province", "")
        final.at[idx, "province_coord_update_gaode_spatial_province"] = decision.get("gaode_spatial_province", "")
        final.at[idx, "province_coord_update_status"] = decision.get(
            "province_coord_update_status", "not_replaced_no_recheck_candidate"
        )
        final.at[idx, "province_coord_update_source"] = decision.get("province_coord_update_source", "")

        if decision.get("new_lon") and decision.get("new_lat"):
            final.at[idx, "wgs_lon_true"] = decision["new_lon"]
            final.at[idx, "wgs_lat_true"] = decision["new_lat"]
            final.at[idx, "coord_replaced"] = "True"
            final.at[idx, "manual_coord_query_required"] = "False"
            final.at[idx, "final_coord_source"] = decision["province_coord_update_source"]
            final.at[idx, "final_coord_decision"] = final.at[idx, "province_coord_update_status"]
            replaced += 1
        else:
            final.at[idx, "manual_coord_query_required"] = "True"
            not_replaced += 1

    # Re-run spatial join for all final coordinates after province-coordinate correction.
    spatial_all = spatial_join_points(final[["companyid", "wgs_lon_true", "wgs_lat_true"]], "wgs_lon_true", "wgs_lat_true", counties)
    spatial_all = spatial_all.rename(
        columns={
            "province": "new_spatial_province",
            "city": "new_spatial_city",
            "county": "new_spatial_county",
            "county_type": "new_spatial_county_type",
        }
    )
    final = final.drop(columns=["new_spatial_province", "new_spatial_city", "new_spatial_county", "new_spatial_county_type"], errors="ignore")
    final = final.merge(spatial_all, on="companyid", how="left")
    final["spatial_province"] = normalize_series(final["new_spatial_province"])
    final["spatial_city"] = normalize_series(final["new_spatial_city"])
    final["spatial_county"] = normalize_series(final["new_spatial_county"])
    final["spatial_county_type"] = normalize_series(final["new_spatial_county_type"])
    final = final.drop(columns=["new_spatial_province", "new_spatial_city", "new_spatial_county", "new_spatial_county_type"])

    diff_results = final.apply(build_diff, axis=1, result_type="expand")
    final["diff"] = diff_results[0]
    final["county_diff"] = diff_results[1].map({True: "True", False: "False"})

    # Keep the original compact output shape first, then audit columns.
    preferred_order = [
        "companyid",
        "ENTNAME",
        "\u7ecf\u8425\u8303\u56f4",
        "\u6ce8\u518c\u5730\u5740",
        "\u6240\u5728\u884c\u653f\u533a\u5212",
        "wgs_lon_true",
        "wgs_lat_true",
        "original_wgs_lon_true",
        "original_wgs_lat_true",
        "coord_replaced",
        "manual_coord_query_required",
        "final_coord_decision",
        "final_coord_source",
        "\u6210\u7acb\u65e5\u671f",
        "\u4f01\u4e1a\u72b6\u6001\u7f16\u7801",
        "\u6ce8\u9500\u65e5\u671f",
        "\u540a\u9500\u65e5\u671f",
        "score",
        "public",
        "policy_year",
        "realness_score_100",
        "real_hospital_label",
        "is_likely_real_hospital",
        "classification_reason",
        "positive_evidence",
        "negative_evidence",
        "scoring_version",
        "business_province",
        "business_city",
        "business_county",
        "business_match_level",
        "business_admin_type",
        "spatial_province",
        "spatial_city",
        "spatial_county",
        "spatial_county_type",
        "county_diff",
        "diff",
    ] + UPDATE_AUDIT_COLS
    existing_order = [col for col in preferred_order if col in final.columns]
    other_cols = [col for col in final.columns if col not in existing_order]
    final = final[existing_order + other_cols]

    final.to_csv(FINAL_CLEAN_PATH, index=False, encoding="utf-8-sig")

    cleanup_paths = [
        PROVINCE_REVIEW_PATH,
        CLASSIFICATION_DIR / "hosp_real_final_clean_province_reviewed.csv",
        CLASSIFICATION_DIR / "hosp_real_province_diff_web_cache.csv",
    ]
    deleted_paths = []
    for path in cleanup_paths:
        if path.exists():
            path.unlink()
            deleted_paths.append(str(path))

    print("province coordinate update summary")
    print(f"final rows: {len(final):,}")
    print(f"targets confirmed_province != old spatial_province: {int(target_mask.sum()):,}")
    print(f"coordinates replaced: {replaced:,}")
    print(f"targets not replaced: {not_replaced:,}")
    print("\nupdate status:")
    print(final.loc[target_mask, "province_coord_update_status"].value_counts(dropna=False).to_string())
    print("\ncoord source:")
    print(final.loc[target_mask, "province_coord_update_source"].replace("", "not_replaced").value_counts(dropna=False).to_string())
    print("\nnew diff:")
    print(final["diff"].value_counts(dropna=False).to_string())
    if deleted_paths:
        print("\ndeleted intermediate files:")
        for path in deleted_paths:
            print(path)
    print(f"\nUpdated: {FINAL_CLEAN_PATH}")


if __name__ == "__main__":
    main()
