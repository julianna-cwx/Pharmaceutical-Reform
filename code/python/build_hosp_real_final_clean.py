from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(r"D:\Hospital_Pharmacy program")
CLASSIFICATION_DIR = ROOT / "data" / "hospital" / "hosp_panel" / "hosp_classification"
INPUT_FINAL = CLASSIFICATION_DIR / "hosp_real_spatial_admin_matched_coord_final.csv"
OUTPUT_FINAL = CLASSIFICATION_DIR / "hosp_real_final_clean.csv"
OUTPUT_SUMMARY = CLASSIFICATION_DIR / "hosp_real_final_clean_summary.csv"


def read_csv_auto(path: Path, **kwargs: Any) -> pd.DataFrame:
    last_error: Exception | None = None
    for enc in ["utf-8-sig", "utf-8", "gb18030", "gbk", "cp936"]:
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False, **kwargs)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return pd.read_csv(path, **kwargs)


def nonempty(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype("string").str.strip().ne("")


def coalesce(df: pd.DataFrame, preferred: str, fallback: str) -> pd.Series:
    preferred_series = df[preferred] if preferred in df.columns else pd.Series(pd.NA, index=df.index)
    fallback_series = df[fallback] if fallback in df.columns else pd.Series(pd.NA, index=df.index)
    return preferred_series.where(nonempty(preferred_series), fallback_series)


def neq_when_comparable(left: pd.Series, right: pd.Series) -> pd.Series:
    l = left.astype("string").str.strip()
    r = right.astype("string").str.strip()
    comparable = nonempty(l) & nonempty(r)
    return comparable & l.ne(r)


def classify_diff(row: pd.Series) -> str:
    if bool(row.get("province_diff_final")):
        return "province_diff"
    if bool(row.get("city_diff_final")):
        return "city_diff"
    if bool(row.get("county_diff")):
        return "county_diff"
    comparable = (
        bool(row.get("province_comparable"))
        or bool(row.get("city_comparable"))
        or bool(row.get("county_comparable"))
    )
    return "same" if comparable else "unmatched"


def main() -> None:
    df = read_csv_auto(INPUT_FINAL, dtype=str)

    # Coordinates: replace wgs_lon_true/wgs_lat_true only when a final non-manual
    # decision produced a usable final coordinate. Manual-query rows keep the
    # current coordinate and are flagged for review.
    manual_required = df["final_manual_review_required"].astype("string").str.lower().eq("true")
    has_final_coord = nonempty(df.get("final_wgs_lon", pd.Series(pd.NA, index=df.index))) & nonempty(
        df.get("final_wgs_lat", pd.Series(pd.NA, index=df.index))
    )
    replace_coord = (~manual_required) & has_final_coord & df["final_coord_decision"].isin(
        [
            "replace_with_recheck_agree_far",
            "replace_with_baidu_reverse_fuzzy_match",
            "replace_with_gaode_reverse_fuzzy_match",
        ]
    )

    df["original_wgs_lon_true"] = df["wgs_lon_true"]
    df["original_wgs_lat_true"] = df["wgs_lat_true"]
    df.loc[replace_coord, "wgs_lon_true"] = df.loc[replace_coord, "final_wgs_lon"]
    df.loc[replace_coord, "wgs_lat_true"] = df.loc[replace_coord, "final_wgs_lat"]
    df["coord_replaced"] = replace_coord
    df["manual_coord_query_required"] = manual_required

    # Use final spatial join for replaced/rechecked different rows, otherwise
    # keep the original spatial join result.
    df["spatial_province"] = coalesce(df, "final_spatial_province", "spatial_province")
    df["spatial_city"] = coalesce(df, "final_spatial_city", "spatial_city")
    df["spatial_county"] = coalesce(df, "final_spatial_county", "spatial_county")
    if "spatial_county_type" not in df.columns:
        df["spatial_county_type"] = pd.NA

    business_province = df["business_province"]
    business_city = df["business_city"]
    business_county = df["business_county"]
    spatial_province = df["spatial_province"]
    spatial_city = df["spatial_city"]
    spatial_county = df["spatial_county"]

    df["province_comparable"] = nonempty(business_province) & nonempty(spatial_province)
    df["city_comparable"] = nonempty(business_city) & nonempty(spatial_city)
    df["county_comparable"] = nonempty(business_county) & nonempty(spatial_county)

    df["province_diff_final"] = neq_when_comparable(business_province, spatial_province)
    df["city_diff_final"] = neq_when_comparable(business_city, spatial_city)
    df["county_diff"] = neq_when_comparable(business_county, spatial_county)
    df["diff"] = df.apply(classify_diff, axis=1)

    keep_cols = [
        "companyid",
        "ENTNAME",
        "经营范围",
        "注册地址",
        "所在行政区划",
        "wgs_lon_true",
        "wgs_lat_true",
        "original_wgs_lon_true",
        "original_wgs_lat_true",
        "coord_replaced",
        "manual_coord_query_required",
        "final_coord_decision",
        "final_coord_source",
        "成立日期",
        "企业状态编码",
        "注销日期",
        "吊销日期",
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
    ]
    keep_cols = [c for c in keep_cols if c in df.columns]
    final = df[keep_cols].copy()

    final.to_csv(OUTPUT_FINAL, index=False, encoding="utf-8-sig")

    summary_rows = [
        ("total_rows", len(final)),
        ("coord_replaced_total", int(final["coord_replaced"].sum())),
        ("manual_coord_query_required", int(final["manual_coord_query_required"].sum())),
    ]
    summary_rows.extend(
        (f"final_coord_decision_{k}", int(v))
        for k, v in final["final_coord_decision"].value_counts(dropna=False).items()
    )
    summary_rows.extend((f"diff_{k}", int(v)) for k, v in final["diff"].value_counts(dropna=False).items())
    summary = pd.DataFrame(summary_rows, columns=["metric", "rows"])
    summary["share"] = summary["rows"] / len(final)
    summary.to_csv(OUTPUT_SUMMARY, index=False, encoding="utf-8-sig")

    print(summary)
    print("最终清理文件:", OUTPUT_FINAL)
    print("最终清理汇总:", OUTPUT_SUMMARY)
    print("保留列:", keep_cols)


if __name__ == "__main__":
    main()
