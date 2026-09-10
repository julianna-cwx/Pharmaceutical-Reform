from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


ROOT = Path(r"D:\Hospital_Pharmacy program")
FINAL_CLEAN_PATH = ROOT / "data" / "hospital" / "hosp_panel" / "hosp_classification" / "hosp_real_final_clean.csv"
PENDING_OUTPUT_PATH = FINAL_CLEAN_PATH.with_name("hosp_real_final_clean_policy_rematched_pending.csv")
POLICY_PATH = ROOT / "data" / "hospital" / "policy_year.xlsx"


def read_csv_auto(path: Path, **kwargs) -> tuple[pd.DataFrame, str]:
    last_error: Exception | None = None
    for encoding in ["utf-8-sig", "utf-8", "gb18030", "gbk"]:
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs), encoding
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


def province_key(value) -> str:
    text = clean_text(value)
    replacements = {
        "\u5317\u4eac\u5e02": "\u5317\u4eac",
        "\u5929\u6d25\u5e02": "\u5929\u6d25",
        "\u4e0a\u6d77\u5e02": "\u4e0a\u6d77",
        "\u91cd\u5e86\u5e02": "\u91cd\u5e86",
        "\u5185\u8499\u53e4\u81ea\u6cbb\u533a": "\u5185\u8499\u53e4",
        "\u5e7f\u897f\u58ee\u65cf\u81ea\u6cbb\u533a": "\u5e7f\u897f",
        "\u897f\u85cf\u81ea\u6cbb\u533a": "\u897f\u85cf",
        "\u5b81\u590f\u56de\u65cf\u81ea\u6cbb\u533a": "\u5b81\u590f",
        "\u65b0\u7586\u7ef4\u543e\u5c14\u81ea\u6cbb\u533a": "\u65b0\u7586",
    }
    if text in replacements:
        return replacements[text]
    text = re.sub(r"(\u7701|\u5e02|\u58ee\u65cf\u81ea\u6cbb\u533a|\u56de\u65cf\u81ea\u6cbb\u533a|\u7ef4\u543e\u5c14\u81ea\u6cbb\u533a|\u81ea\u6cbb\u533a)$", "", text)
    return text


def area_key(value) -> str:
    text = clean_text(value)
    text = re.sub(r"\uff08.*?\uff09|\(.*?\)", "", text)
    alias = {
        "\u84df\u53bf": "\u84df\u5dde\u533a",
        "\u5f00\u53bf": "\u5f00\u5dde\u533a",
        "\u6b66\u9686\u53bf": "\u6b66\u9686\u533a",
        "\u5f6d\u6c34\u53bf": "\u5f6d\u6c34\u82d7\u65cf\u571f\u5bb6\u65cf\u81ea\u6cbb\u53bf",
        "\u9149\u9633\u53bf": "\u9149\u9633\u571f\u5bb6\u65cf\u82d7\u65cf\u81ea\u6cbb\u53bf",
        "\u9675\u6c34\u53bf": "\u9675\u6c34\u9ece\u65cf\u81ea\u6cbb\u53bf",
        "\u4fdd\u4ead\u53bf": "\u4fdd\u4ead\u9ece\u65cf\u82d7\u65cf\u81ea\u6cbb\u53bf",
        "\u660c\u6c5f\u53bf": "\u660c\u6c5f\u9ece\u65cf\u81ea\u6cbb\u53bf",
    }
    return alias.get(text, text)


def area_variants(value) -> set[str]:
    text = area_key(value)
    variants = {text} if text else set()
    for suffix in [
        "\u571f\u5bb6\u65cf\u82d7\u65cf\u81ea\u6cbb\u53bf",
        "\u82d7\u65cf\u571f\u5bb6\u65cf\u81ea\u6cbb\u53bf",
        "\u9ece\u65cf\u82d7\u65cf\u81ea\u6cbb\u53bf",
        "\u9ece\u65cf\u81ea\u6cbb\u53bf",
        "\u81ea\u6cbb\u5dde",
        "\u81ea\u6cbb\u53bf",
        "\u5730\u533a",
        "\u5e02",
        "\u53bf",
        "\u533a",
        "\u65d7",
    ]:
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            variants.add(text[: -len(suffix)])
    return variants


def parse_policy_year(value) -> pd._libs.missing.NAType | int:
    text = clean_text(value)
    match = re.search(r"(19|20)\d{2}", text)
    if not match:
        return pd.NA
    return int(match.group(0))


def is_county_level(county_type: str, county: str) -> bool:
    ctype = clean_text(county_type)
    county = clean_text(county)
    if ctype in {"\u53bf", "\u53bf\u7ea7\u5e02", "\u81ea\u6cbb\u53bf", "\u65d7", "\u81ea\u6cbb\u65d7", "\u7279\u533a", "\u6797\u533a"}:
        return True
    if ctype == "\u5e02\u8f96\u533a":
        return False
    return bool(re.search(r"(\u53bf|\u53bf\u7ea7\u5e02|\u81ea\u6cbb\u53bf|\u65d7|\u81ea\u6cbb\u65d7)$", county))


def is_urban_area(county_type: str, county: str) -> bool:
    ctype = clean_text(county_type)
    county = clean_text(county)
    return ctype == "\u5e02\u8f96\u533a" or county.endswith("\u533a")


def scope_matches_level(level: str, scope: str, county_type: str, county: str) -> bool:
    text = clean_text(level) + " " + clean_text(scope)
    if "\u53bf\u7ea7" in text or "\u65d7\u53bf" in text or "\u5168\u90e8\u53bf\u7ea7" in text:
        return is_county_level(county_type, county)
    if "\u57ce\u5e02" in text or "\u5e02\u5c5e" in text or "\u533a\u5c5e" in text:
        return is_urban_area(county_type, county)
    if "\u5168\u90e8\u516c\u7acb\u533b\u9662" in text or "\u5168\u7701" in text or "\u5168\u5e02" in text or "\u5168\u533a" in text:
        return True
    return True


def classify_policy_rule(row: pd.Series, hospital: pd.Series) -> tuple[bool, int, str]:
    prov = province_key(row["policy_province"])
    if prov != province_key(hospital["spatial_province"]):
        return False, 99, ""

    place = clean_text(row["policy_place"])
    place_clean = area_key(place)
    level = clean_text(row["policy_level"])
    scope = clean_text(row["policy_scope"])
    spatial_city = clean_text(hospital["spatial_city"])
    spatial_county = clean_text(hospital["spatial_county"])
    county_type = clean_text(hospital["spatial_county_type"])

    city_variants = area_variants(spatial_city)
    county_variants = area_variants(spatial_county)
    place_variants = area_variants(place_clean)

    if any(token in place for token in ["\u90e8\u5206", "4\u5bb6", "\u8bd5\u70b9\u53bf", "\u4e2a\u65d7\u53bf", "\u4e2a\u53bf"]):
        return False, 99, ""

    if "\u9664\u676d\u5dde\u5916" in place:
        matched = province_key(hospital["spatial_province"]) == "\u6d59\u6c5f" and spatial_city != "\u676d\u5dde\u5e02" and is_urban_area(county_type, spatial_county)
        return matched, 3, "special_city_except_hangzhou" if matched else ""

    if "116\u4e2a\u53bf\u5e02" in place:
        matched = province_key(hospital["spatial_province"]) == "\u4e91\u5357" and spatial_city != "\u6606\u660e\u5e02" and is_county_level(county_type, spatial_county)
        return matched, 3, "special_county_except_kunming" if matched else ""

    if place_clean in {"\u5168\u5e02", "\u5168\u7701", "\u5168\u533a"} or place.startswith("\u5168\u5e02"):
        matched = scope_matches_level(level, scope, county_type, spatial_county)
        if not matched:
            return False, 99, ""
        if "\u53bf\u7ea7" in level + scope or "\u65d7\u53bf" in level + scope:
            return True, 4, "province_county_scope"
        if "\u57ce\u5e02" in level + scope:
            return True, 4, "province_city_scope"
        return True, 5, "province_all_scope"

    if place_variants & county_variants:
        return True, 1, "exact_county"
    if place_variants & city_variants:
        return True, 2, "exact_city"
    return False, 99, ""


def build_policy_rules(policy_raw: pd.DataFrame) -> pd.DataFrame:
    cols = list(policy_raw.columns)
    rules = pd.DataFrame(
        {
            "policy_province": policy_raw[cols[1]],
            "policy_place": policy_raw[cols[2]],
            "policy_level": policy_raw[cols[3]],
            "policy_time_raw": policy_raw[cols[4]],
            "policy_scope": policy_raw[cols[5]],
            "policy_note": policy_raw[cols[6]] if len(cols) > 6 else "",
        }
    ).fillna("")
    rules["policy_year_spatial"] = rules["policy_time_raw"].map(parse_policy_year)
    rules = rules[rules["policy_year_spatial"].notna()].copy()
    rules["policy_year_spatial"] = rules["policy_year_spatial"].astype(int)
    rules["policy_province_key"] = rules["policy_province"].map(province_key)
    return rules


def match_policy_for_hospital(hospital: pd.Series, rules_by_province: dict[str, list[dict]]) -> dict[str, str]:
    matches = []
    for rule in rules_by_province.get(province_key(hospital["spatial_province"]), []):
        matched, priority, match_level = classify_policy_rule(rule, hospital)
        if matched:
            matches.append(
                {
                    "priority": priority,
                    "policy_year_spatial": int(rule["policy_year_spatial"]),
                    "policy_time_spatial_raw": clean_text(rule["policy_time_raw"]),
                    "policy_match_level": match_level,
                    "policy_match_rule": (
                        f"{clean_text(rule['policy_province'])}|{clean_text(rule['policy_place'])}|"
                        f"{clean_text(rule['policy_level'])}|{clean_text(rule['policy_scope'])}"
                    ),
                }
            )
    if not matches:
        return {
            "policy_year_spatial": "",
            "policy_time_spatial_raw": "",
            "policy_match_level": "unmatched",
            "policy_match_rule": "",
        }
    best = sorted(matches, key=lambda item: (item["priority"], item["policy_year_spatial"]))[0]
    return {key: clean_text(value) for key, value in best.items() if key != "priority"}


def compare_policy_year(old_value, new_value) -> tuple[str, str]:
    old_num = pd.to_numeric(pd.Series([old_value]), errors="coerce").iloc[0]
    new_num = pd.to_numeric(pd.Series([new_value]), errors="coerce").iloc[0]
    old_missing = pd.isna(old_num)
    new_missing = pd.isna(new_num)
    if old_missing and new_missing:
        return "both_missing", ""
    if old_missing and not new_missing:
        return "old_missing_new_matched", ""
    if not old_missing and new_missing:
        return "new_missing_old_matched", ""
    old_int = int(old_num)
    new_int = int(new_num)
    if old_int == new_int:
        return "same", "0"
    return "changed", str(new_int - old_int)


def main() -> None:
    hospital, input_encoding = read_csv_auto(FINAL_CLEAN_PATH, dtype=str, low_memory=False)
    hospital = hospital.fillna("")
    policy_raw = pd.read_excel(POLICY_PATH, sheet_name=0, dtype=str).fillna("")
    rules = build_policy_rules(policy_raw)
    rules_by_province = {
        province: group.drop(columns=["policy_province_key"]).to_dict("records")
        for province, group in rules.groupby("policy_province_key", dropna=False)
    }

    required_cols = ["spatial_province", "spatial_city", "spatial_county", "spatial_county_type", "policy_year"]
    missing = [col for col in required_cols if col not in hospital.columns]
    if missing:
        raise KeyError(f"Missing required columns in final clean file: {missing}")

    if "policy_year_original_before_spatial_rematch" not in hospital.columns:
        hospital["policy_year_original_before_spatial_rematch"] = hospital["policy_year"]

    for col in ["spatial_province", "spatial_city", "spatial_county", "spatial_county_type"]:
        hospital[col] = normalize_series(hospital[col])

    match_results = hospital.apply(
        lambda row: match_policy_for_hospital(row, rules_by_province),
        axis=1,
        result_type="expand",
    )
    for col in ["policy_year_spatial", "policy_time_spatial_raw", "policy_match_level", "policy_match_rule"]:
        hospital[col] = match_results[col].fillna("").astype(str)

    comparisons = hospital.apply(
        lambda row: compare_policy_year(row["policy_year_original_before_spatial_rematch"], row["policy_year_spatial"]),
        axis=1,
        result_type="expand",
    )
    hospital["policy_year_diff_status"] = comparisons[0]
    hospital["policy_year_diff_value"] = comparisons[1]
    hospital["policy_year"] = hospital["policy_year_spatial"].replace("", pd.NA)

    preferred_policy_cols = [
        "policy_year",
        "policy_year_original_before_spatial_rematch",
        "policy_year_spatial",
        "policy_time_spatial_raw",
        "policy_match_level",
        "policy_match_rule",
        "policy_year_diff_status",
        "policy_year_diff_value",
    ]
    ordered = []
    for col in hospital.columns:
        if col == "policy_year":
            for policy_col in preferred_policy_cols:
                if policy_col in hospital.columns and policy_col not in ordered:
                    ordered.append(policy_col)
        elif col not in preferred_policy_cols and col not in ordered:
            ordered.append(col)
    hospital = hospital[ordered]

    output_path = FINAL_CLEAN_PATH
    try:
        hospital.to_csv(FINAL_CLEAN_PATH, index=False, encoding="utf-8-sig")
    except PermissionError:
        hospital.to_csv(PENDING_OUTPUT_PATH, index=False, encoding="utf-8-sig")
        output_path = PENDING_OUTPUT_PATH

    print("spatial policy year rematch summary")
    print(f"input encoding: {input_encoding}")
    print(f"rows: {len(hospital):,}")
    print("\npolicy match level:")
    print(hospital["policy_match_level"].value_counts(dropna=False).to_string())
    print("\npolicy year diff status:")
    print(hospital["policy_year_diff_status"].value_counts(dropna=False).to_string())
    print("\nchanged old -> new top 20:")
    changed = hospital[hospital["policy_year_diff_status"].eq("changed")].copy()
    if changed.empty:
        print("(none)")
    else:
        old_new = (
            changed.groupby(["policy_year_original_before_spatial_rematch", "policy_year_spatial"], dropna=False)
            .size()
            .rename("rows")
            .reset_index()
            .sort_values("rows", ascending=False)
            .head(20)
        )
        print(old_new.to_string(index=False))
    if output_path != FINAL_CLEAN_PATH:
        print(f"\nFinal file is locked, wrote pending output instead: {output_path}")
        print(f"Close the program occupying {FINAL_CLEAN_PATH}, then rerun this cell to update the final CSV.")
    else:
        print(f"\nUpdated: {FINAL_CLEAN_PATH}")


if __name__ == "__main__":
    main()
