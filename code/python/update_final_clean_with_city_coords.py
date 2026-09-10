from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd


ROOT = Path(r"D:\Hospital_Pharmacy program")
CLASSIFICATION_DIR = ROOT / "data" / "hospital" / "hosp_panel" / "hosp_classification"
FINAL_CLEAN_PATH = CLASSIFICATION_DIR / "hosp_real_final_clean.csv"
RECHECK_PATH = CLASSIFICATION_DIR / "hosp_real_different_coord_recheck.csv"
COUNTY_SHP = ROOT / "data" / "county" / "controls" / "county_boundaries" / "counties19.shp"

ADDR_COL = "\u6ce8\u518c\u5730\u5740"

CITY_AUDIT_COLS = [
    "city_coord_update_target",
    "city_coord_confirmed_city",
    "city_coord_confirm_status",
    "city_coord_confirm_basis",
    "city_coord_update_status",
    "city_coord_update_source",
    "city_coord_update_old_lon",
    "city_coord_update_old_lat",
    "city_coord_update_old_spatial_city",
    "city_coord_update_old_spatial_county",
    "city_coord_update_baidu_spatial_city",
    "city_coord_update_baidu_spatial_county",
    "city_coord_update_gaode_spatial_city",
    "city_coord_update_gaode_spatial_county",
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


def strip_admin_suffix(name: str) -> list[str]:
    name = clean_text(name)
    if not name:
        return []
    variants = {name}
    for suffix in ["自治州", "地区", "盟", "市", "县", "区"]:
        if name.endswith(suffix) and len(name) > len(suffix) + 1:
            variants.add(name[: -len(suffix)])
    return sorted(variants, key=len, reverse=True)


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


def build_county_city_lookup(counties: gpd.GeoDataFrame) -> dict[str, set[str]]:
    lookup: dict[str, set[str]] = {}
    for _, row in counties[["省", "市", "NAME"]].dropna().iterrows():
        province = clean_text(row["省"])
        city = clean_text(row["市"])
        county = clean_text(row["NAME"])
        if not province or not city or not county:
            continue
        for term in strip_admin_suffix(county):
            lookup.setdefault(f"{province}|{term}", set()).add(city)
    return lookup


def text_score_for_city(text: str, province: str, city: str, county: str, county_lookup: dict[str, set[str]]) -> tuple[int, list[str]]:
    score = 0
    hits: list[str] = []
    province = clean_text(province)
    city = clean_text(city)
    county = clean_text(county)
    if not city:
        return 0, []

    for term in strip_admin_suffix(city):
        if len(term) >= 2 and term in text:
            score += 8 if term == city else 5
            hits.append(f"city:{term}")
    for term in strip_admin_suffix(county):
        if len(term) >= 2 and term in text:
            score += 8
            hits.append(f"county:{term}")
    for key, cities in county_lookup.items():
        key_province, term = key.split("|", 1)
        if key_province == province and city in cities and len(term) >= 2 and term in text:
            score += 6
            hits.append(f"county_lookup:{term}->{city}")
    return score, hits


def choose_confirmed_city(row: pd.Series, county_lookup: dict[str, set[str]]) -> dict[str, str]:
    text = " ".join(
        [
            clean_text(row.get("ENTNAME")),
            clean_text(row.get(ADDR_COL)),
            clean_text(row.get("positive_evidence")),
            clean_text(row.get("classification_reason")),
        ]
    )
    province = clean_text(row.get("business_province")) or clean_text(row.get("spatial_province"))
    current_city = clean_text(row.get("spatial_city"))
    business_city = clean_text(row.get("business_city"))
    original_city = clean_text(row.get("original_spatial_city"))
    baidu_city = clean_text(row.get("baidu_spatial_city"))
    gaode_city = clean_text(row.get("gaode_spatial_city"))

    candidate_cities = []
    for city in [current_city, original_city, business_city, baidu_city, gaode_city]:
        if city and city not in candidate_cities:
            candidate_cities.append(city)

    scores: dict[str, int] = {city: 0 for city in candidate_cities}
    text_scores: dict[str, int] = {city: 0 for city in candidate_cities}
    reasons: dict[str, list[str]] = {city: [] for city in candidate_cities}

    for city in candidate_cities:
        county = ""
        if city == current_city:
            county = clean_text(row.get("spatial_county"))
        elif city == original_city:
            county = clean_text(row.get("original_spatial_county"))
        elif city == business_city:
            county = clean_text(row.get("business_county"))
        elif city == baidu_city:
            county = clean_text(row.get("baidu_spatial_county"))
        elif city == gaode_city:
            county = clean_text(row.get("gaode_spatial_county"))
        text_score, hits = text_score_for_city(text, province, city, county, county_lookup)
        text_scores[city] = text_score
        scores[city] += text_score
        reasons[city].extend(hits)

    if baidu_city:
        scores[baidu_city] = scores.get(baidu_city, 0) + 3
        reasons.setdefault(baidu_city, []).append("baidu_candidate")
    if gaode_city:
        scores[gaode_city] = scores.get(gaode_city, 0) + 3
        reasons.setdefault(gaode_city, []).append("gaode_candidate")
    if baidu_city and gaode_city and baidu_city == gaode_city:
        scores[baidu_city] += 5
        reasons[baidu_city].append("baidu_gaode_agree")
    if current_city:
        scores[current_city] = scores.get(current_city, 0) + 2
        reasons.setdefault(current_city, []).append("current_spatial")
    if original_city:
        scores[original_city] = scores.get(original_city, 0) + 2
        reasons.setdefault(original_city, []).append("original_wgs_spatial")
    if business_city:
        scores[business_city] = scores.get(business_city, 0) + 1
        reasons.setdefault(business_city, []).append("business_admin_low_weight")

    text_ranked = sorted(text_scores.items(), key=lambda item: item[1], reverse=True)
    if text_ranked and text_ranked[0][1] >= 5:
        best_text_city, best_text_score = text_ranked[0]
        second_text_score = text_ranked[1][1] if len(text_ranked) > 1 else 0
        if best_text_score >= second_text_score + 2:
            return {
                "city_coord_confirmed_city": best_text_city,
                "city_coord_confirm_status": "confirmed_by_name_or_registered_address",
                "city_coord_confirm_basis": (
                    f"text_scores={text_scores}; scores={scores}; reasons={reasons}; "
                    f"current_city={current_city}; original_city={original_city}; "
                    f"business_city={business_city}; baidu_city={baidu_city}; gaode_city={gaode_city}"
                ),
            }

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] <= 0:
        return {
            "city_coord_confirmed_city": "",
            "city_coord_confirm_status": "manual_review_no_city_evidence",
            "city_coord_confirm_basis": "no positive city evidence",
        }
    best_city, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0

    status = "confirmed_by_name_address_and_map_candidates"
    if best_score - second_score < 3 and best_score < 10:
        status = "manual_review_weak_city_evidence"
    elif not any(hit.startswith(("city:", "county:", "county_lookup:")) for hit in reasons.get(best_city, [])):
        status = "confirmed_by_baidu_gaode_candidates"

    return {
        "city_coord_confirmed_city": best_city,
        "city_coord_confirm_status": status,
        "city_coord_confirm_basis": (
            f"scores={scores}; reasons={reasons}; "
            f"text_scores={text_scores}; current_city={current_city}; original_city={original_city}; business_city={business_city}; "
            f"baidu_city={baidu_city}; gaode_city={gaode_city}"
        ),
    }


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
    county_lookup = build_county_city_lookup(counties)

    final["companyid"] = normalize_series(final["companyid"])
    recheck["companyid"] = normalize_series(recheck["companyid"])

    prior_city_update_mask = (
        final.get("final_coord_decision", pd.Series("", index=final.index))
        .fillna("")
        .astype(str)
        .str.startswith("city_")
    )
    prior_city_target_mask = (
        final.get("city_coord_update_target", pd.Series("", index=final.index))
        .fillna("")
        .astype(str)
        .eq("True")
    )
    target_mask = final["diff"].eq("city_diff") | prior_city_update_mask | prior_city_target_mask
    targets = final.loc[target_mask, ["companyid"]].copy()

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
    original_candidates = final.loc[target_mask, ["companyid", "original_wgs_lon_true", "original_wgs_lat_true"]].copy()
    original_sp = spatial_join_points(original_candidates, "original_wgs_lon_true", "original_wgs_lat_true", counties)
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
    original_sp = original_sp.rename(
        columns={
            "province": "original_spatial_province",
            "city": "original_spatial_city",
            "county": "original_spatial_county",
            "county_type": "original_spatial_county_type",
        }
    )

    candidate_spatial = (
        candidates.merge(baidu_sp, on="companyid", how="left")
        .merge(gaode_sp, on="companyid", how="left")
        .merge(original_sp, on="companyid", how="left")
    )
    candidate_spatial = candidate_spatial.fillna("")
    final = final.drop(columns=[c for c in candidate_spatial.columns if c != "companyid" and c in final.columns], errors="ignore")
    final = final.merge(candidate_spatial, on="companyid", how="left")
    final = final.fillna("")

    for col in CITY_AUDIT_COLS:
        if col in final.columns:
            final[col] = ""
        else:
            final[col] = ""
    final["city_coord_update_target"] = target_mask.map({True: "True", False: "False"})

    old_lon = final["wgs_lon_true"].copy()
    old_lat = final["wgs_lat_true"].copy()
    old_spatial_city = final["spatial_city"].copy()
    old_spatial_county = final["spatial_county"].copy()

    replaced = 0
    keep_current = 0
    manual = 0
    target_indices = final.index[final["city_coord_update_target"].eq("True")].tolist()
    for idx in target_indices:
        row = final.loc[idx]
        decision = choose_confirmed_city(row, county_lookup)
        confirmed_city = decision["city_coord_confirmed_city"]
        confirm_status = decision["city_coord_confirm_status"]

        final.at[idx, "city_coord_confirmed_city"] = confirmed_city
        final.at[idx, "city_coord_confirm_status"] = confirm_status
        final.at[idx, "city_coord_confirm_basis"] = decision["city_coord_confirm_basis"]
        final.at[idx, "city_coord_update_old_lon"] = old_lon.at[idx]
        final.at[idx, "city_coord_update_old_lat"] = old_lat.at[idx]
        final.at[idx, "city_coord_update_old_spatial_city"] = old_spatial_city.at[idx]
        final.at[idx, "city_coord_update_old_spatial_county"] = old_spatial_county.at[idx]
        final.at[idx, "city_coord_update_baidu_spatial_city"] = clean_text(row.get("baidu_spatial_city"))
        final.at[idx, "city_coord_update_baidu_spatial_county"] = clean_text(row.get("baidu_spatial_county"))
        final.at[idx, "city_coord_update_gaode_spatial_city"] = clean_text(row.get("gaode_spatial_city"))
        final.at[idx, "city_coord_update_gaode_spatial_county"] = clean_text(row.get("gaode_spatial_county"))

        current_city = clean_text(row.get("spatial_city"))
        baidu_city = clean_text(row.get("baidu_spatial_city"))
        gaode_city = clean_text(row.get("gaode_spatial_city"))
        original_city = clean_text(row.get("original_spatial_city"))
        if not confirmed_city or confirm_status.startswith("manual_review"):
            final.at[idx, "city_coord_update_status"] = "not_replaced_manual_review_city_unconfirmed"
            final.at[idx, "manual_coord_query_required"] = "True"
            manual += 1
        elif confirmed_city == current_city:
            final.at[idx, "city_coord_update_status"] = "keep_current_coord_city_confirmed"
            final.at[idx, "city_coord_update_source"] = clean_text(row.get("final_coord_source")) or "current_wgs"
            keep_current += 1
        elif original_city == confirmed_city and clean_text(row.get("original_wgs_lon_true")) and clean_text(row.get("original_wgs_lat_true")):
            final.at[idx, "wgs_lon_true"] = clean_text(row.get("original_wgs_lon_true"))
            final.at[idx, "wgs_lat_true"] = clean_text(row.get("original_wgs_lat_true"))
            final.at[idx, "manual_coord_query_required"] = "False"
            final.at[idx, "final_coord_source"] = "original_wgs_restored_city_confirmed"
            final.at[idx, "final_coord_decision"] = "city_restored_original_wgs_matches_confirmed_city"
            final.at[idx, "city_coord_update_status"] = "restored_original_wgs_matches_confirmed_city"
            final.at[idx, "city_coord_update_source"] = "original_wgs_restored_city_confirmed"
            replaced += 1
        elif baidu_city == confirmed_city and clean_text(row.get("baidu_wgs_lon_recheck")) and clean_text(row.get("baidu_wgs_lat_recheck")):
            final.at[idx, "wgs_lon_true"] = clean_text(row.get("baidu_wgs_lon_recheck"))
            final.at[idx, "wgs_lat_true"] = clean_text(row.get("baidu_wgs_lat_recheck"))
            final.at[idx, "coord_replaced"] = "True"
            final.at[idx, "manual_coord_query_required"] = "False"
            final.at[idx, "final_coord_source"] = "baidu_recheck_wgs84"
            final.at[idx, "final_coord_decision"] = "city_replaced_baidu_matches_confirmed_city"
            final.at[idx, "city_coord_update_status"] = "replaced_baidu_matches_confirmed_city"
            final.at[idx, "city_coord_update_source"] = "baidu_recheck_wgs84"
            replaced += 1
        elif gaode_city == confirmed_city and clean_text(row.get("gaode_wgs_lon_recheck")) and clean_text(row.get("gaode_wgs_lat_recheck")):
            final.at[idx, "wgs_lon_true"] = clean_text(row.get("gaode_wgs_lon_recheck"))
            final.at[idx, "wgs_lat_true"] = clean_text(row.get("gaode_wgs_lat_recheck"))
            final.at[idx, "coord_replaced"] = "True"
            final.at[idx, "manual_coord_query_required"] = "False"
            final.at[idx, "final_coord_source"] = "gaode_recheck_wgs84"
            final.at[idx, "final_coord_decision"] = "city_replaced_gaode_matches_confirmed_city"
            final.at[idx, "city_coord_update_status"] = "replaced_gaode_matches_confirmed_city"
            final.at[idx, "city_coord_update_source"] = "gaode_recheck_wgs84"
            replaced += 1
        else:
            final.at[idx, "city_coord_update_status"] = "not_replaced_no_candidate_matches_confirmed_city"
            final.at[idx, "manual_coord_query_required"] = "True"
            manual += 1

    final["city_coord_update_status"] = final["city_coord_update_status"].where(
        final["city_coord_update_status"].ne(""), "not_target"
    )

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

    # Remove temporary candidate spatial columns from the final dataset.
    final = final.drop(
        columns=[
            "province_review_side",
            "province_review_confirmed_province",
            "province_review_status",
            "province_review_confidence",
            "baidu_wgs_lon_recheck",
            "baidu_wgs_lat_recheck",
            "gaode_wgs_lon_recheck",
            "gaode_wgs_lat_recheck",
            "baidu_spatial_province",
            "baidu_spatial_city",
            "baidu_spatial_county",
            "baidu_spatial_county_type",
            "gaode_spatial_province",
            "gaode_spatial_city",
            "gaode_spatial_county",
            "gaode_spatial_county_type",
            "original_spatial_province",
            "original_spatial_city",
            "original_spatial_county",
            "original_spatial_county_type",
        ],
        errors="ignore",
    )

    preferred_order = [
        "companyid",
        "ENTNAME",
        "\u7ecf\u8425\u8303\u56f4",
        ADDR_COL,
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
    ] + [c for c in final.columns if c.startswith("province_coord_update_")] + CITY_AUDIT_COLS
    existing_order = []
    for col in preferred_order:
        if col in final.columns and col not in existing_order:
            existing_order.append(col)
    other_cols = [col for col in final.columns if col not in existing_order]
    final = final[existing_order + other_cols]

    final.to_csv(FINAL_CLEAN_PATH, index=False, encoding="utf-8-sig")

    print("city coordinate update summary")
    print(f"final rows: {len(final):,}")
    print(f"city_diff targets before update: {int(target_mask.sum()):,}")
    print(f"coordinates replaced: {replaced:,}")
    print(f"current coordinates kept as confirmed: {keep_current:,}")
    print(f"manual/not replaced: {manual:,}")
    print("\nupdate status:")
    print(final.loc[final["city_coord_update_target"].eq("True"), "city_coord_update_status"].value_counts(dropna=False).to_string())
    print("\ncoord source:")
    print(
        final.loc[final["city_coord_update_target"].eq("True"), "city_coord_update_source"]
        .replace("", "not_replaced")
        .value_counts(dropna=False)
        .to_string()
    )
    print("\nnew diff:")
    print(final["diff"].value_counts(dropna=False).to_string())
    print(f"\nUpdated: {FINAL_CLEAN_PATH}")


if __name__ == "__main__":
    main()
