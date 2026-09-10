from __future__ import annotations

from pathlib import Path
import re
import shutil
import unicodedata

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process


BASE = Path(r"D:\Hospital_Pharmacy program")
DP_DIR = BASE / "data" / "hospital" / "hosp_dp" / "cleaned"
BZ_DIR = BASE / "data" / "hospital" / "hosp_panel" / "hosp_year"
OUT_DIR = BASE / "data" / "hospital" / "hosp_dp" / "diff_dp_bz"
RULE_VERSION = "dp_bz_fuzzy_match_yearly_v1_2026-07-14"


NOISE_TERMS = (
    "\u505c\u8f66\u573a",
    "\u505c\u8f66",
    "\u5bbf\u820d",
    "\u5bb6\u5c5e\u9662",
    "\u5bb6\u5c5e\u533a",
    "\u4f4f\u5b85",
    "\u5c0f\u533a",
    "\u516c\u4ea4",
    "\u516c\u4ea4\u7ad9",
    "\u5730\u94c1",
    "\u836f\u5e97",
    "\u836f\u623f",
    "\u9910\u5385",
    "\u98df\u5802",
    "\u8d85\u5e02",
    "\u4fbf\u5229\u5e97",
    "\u5bbe\u9986",
    "\u9152\u5e97",
    "\u94f6\u884c",
    "\u5b66\u6821",
    "\u5e7c\u513f\u56ed",
)

ADMIN_SUFFIXES = (
    "\u7ef4\u543e\u5c14\u81ea\u6cbb\u533a",
    "\u58ee\u65cf\u81ea\u6cbb\u533a",
    "\u56de\u65cf\u81ea\u6cbb\u533a",
    "\u81ea\u6cbb\u533a",
    "\u7279\u522b\u884c\u653f\u533a",
    "\u81ea\u6cbb\u5dde",
    "\u5730\u533a",
    "\u76df",
    "\u7701",
    "\u5e02",
    "\u53bf",
    "\u533a",
    "\u65d7",
)


def normalize_name(value) -> str:
    if pd.isna(value):
        return ""
    s = unicodedata.normalize("NFKC", str(value)).strip().lower()
    s = re.sub(r"\s+", "", s)
    punct_pattern = "[()\uff08\uff09\\[\\]\u3010\u3011{}<>\u300a\u300b\u00b7\u2022,\uff0c.\u3002;\uff1b:\uff1a\u3001/\\\\|\"'\u201c\u201d\u2018\u2019_\\-\u2014]+"
    return re.sub(punct_pattern, "", s)


def normalize_text(value) -> str:
    if pd.isna(value):
        return ""
    s = unicodedata.normalize("NFKC", str(value)).strip().lower()
    return re.sub(r"\s+", "", s)


def normalize_code(series: pd.Series) -> pd.Series:
    num = pd.to_numeric(series, errors="coerce")
    out = num.astype("Int64").astype("string")
    out = out.where(num.notna(), "")
    out = out.str.zfill(6)
    out = out.where(out != "<NA>", "")
    return out.fillna("")


def simple_admin(value) -> str:
    s = normalize_text(value)
    for suffix in ADMIN_SUFFIXES:
        s = s.replace(suffix, "")
    return s


def remove_admin_tokens(name: str, tokens: list[str]) -> str:
    out = name
    for token in sorted({t for t in tokens if t}, key=len, reverse=True):
        out = out.replace(token, "")
        out = out.replace(simple_admin(token), "")
    return out or name


def haversine_km(lon1, lat1, lon2, lat2) -> pd.Series:
    lon1 = pd.to_numeric(lon1, errors="coerce")
    lat1 = pd.to_numeric(lat1, errors="coerce")
    lon2 = pd.to_numeric(lon2, errors="coerce")
    lat2 = pd.to_numeric(lat2, errors="coerce")
    valid = (
        lon1.between(-180, 180)
        & lon2.between(-180, 180)
        & lat1.between(-90, 90)
        & lat2.between(-90, 90)
    )
    dist = pd.Series(np.nan, index=lon1.index, dtype="float64")
    if valid.any():
        radius = 6371.0088
        phi1 = np.radians(lat1[valid].astype(float))
        phi2 = np.radians(lat2[valid].astype(float))
        dphi = np.radians((lat2[valid] - lat1[valid]).astype(float))
        dlambda = np.radians((lon2[valid] - lon1[valid]).astype(float))
        a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
        dist.loc[valid] = 2 * radius * np.arcsin(np.sqrt(a))
    return dist


def scalar_distance(row: dict, cand: pd.Series) -> float:
    return float(
        haversine_km(
            pd.Series([row.get("lon_wgs")]),
            pd.Series([row.get("lat_wgs")]),
            pd.Series([cand.get("wgs_lon_true", cand.get("lon"))]),
            pd.Series([cand.get("wgs_lat_true", cand.get("lat"))]),
        ).iloc[0]
    )


def noise_extra(a: str, b: str) -> bool:
    if a in b:
        extra = b.replace(a, "", 1)
    elif b in a:
        extra = a.replace(b, "", 1)
    else:
        return False
    return any(term in extra for term in NOISE_TERMS)


def name_score(dp_norm: str, dp_alias: str, bz_norm: str, bz_alias: str) -> float:
    if not dp_alias or not bz_alias:
        return 0.0
    scores = [
        fuzz.ratio(dp_norm, bz_norm),
        fuzz.ratio(dp_alias, bz_alias),
        fuzz.WRatio(dp_alias, bz_alias),
    ]
    shorter, longer = sorted((dp_alias, bz_alias), key=len)
    if len(shorter) >= 5 and shorter in longer:
        scores.append(88.0 if noise_extra(shorter, longer) else 96.0)
    return float(max(scores))


def clear_output_dir() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for child in OUT_DIR.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def prepare_inputs() -> tuple[pd.DataFrame, pd.DataFrame, int]:
    dp_frames = []
    for path in sorted(DP_DIR.glob("hosp_dp_*_scored.csv")):
        frame = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
        frame["dp_source_file"] = path.name
        dp_frames.append(frame)
    dp_all = pd.concat(dp_frames, ignore_index=True)
    dp_raw_rows = len(dp_all)
    dp_all["_is_hospital_num"] = pd.to_numeric(dp_all.get("is_hospital"), errors="coerce")
    dp = dp_all.loc[dp_all["_is_hospital_num"].eq(1)].copy()
    dp.drop(columns=["_is_hospital_num"], inplace=True)
    dp.insert(0, "dp_uid", np.arange(1, len(dp) + 1, dtype=np.int64))

    bz_frames = []
    for path in sorted(BZ_DIR.glob("hospital_year_20*.csv")):
        if "panel" in path.name or "duplicates" in path.name:
            continue
        frame = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
        frame["bz_source_file"] = path.name
        bz_frames.append(frame)
    bz = pd.concat(bz_frames, ignore_index=True)
    bz.insert(0, "bz_uid", np.arange(1, len(bz) + 1, dtype=np.int64))

    for df, name_col in ((dp, "name"), (bz, "ENTNAME")):
        df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
        df["name_norm"] = df[name_col].map(normalize_name)

    dp["county_code_norm"] = normalize_code(dp.get("PAC", pd.Series(index=dp.index)))
    bz["county_code_norm"] = normalize_code(bz.get("county_id", pd.Series(index=bz.index)))
    dp["province_norm"] = dp.get("province19", pd.Series(index=dp.index)).map(normalize_text)
    dp["city_norm"] = dp.get("city19", pd.Series(index=dp.index)).map(normalize_text)
    dp["county_norm"] = dp.get("county19", pd.Series(index=dp.index)).map(normalize_text)
    bz["province_norm"] = bz.get("business_province", pd.Series(index=bz.index)).map(normalize_text)
    bz["city_norm"] = bz.get("business_city", pd.Series(index=bz.index)).map(normalize_text)
    bz["county_norm"] = bz.get("business_county", pd.Series(index=bz.index)).map(normalize_text)

    dp["name_alias"] = [
        remove_admin_tokens(row.name_norm, [row.province_norm, row.city_norm, row.county_norm])
        for row in dp.itertuples(index=False)
    ]
    bz["name_alias"] = [
        remove_admin_tokens(row.name_norm, [row.province_norm, row.city_norm, row.county_norm])
        for row in bz.itertuples(index=False)
    ]

    dp["match_bz_uid"] = pd.NA
    dp["match_level"] = ""
    dp["match_key_used"] = ""
    dp["match_score"] = np.nan
    dp["name_match_score"] = np.nan
    return dp, bz, dp_raw_rows


def build_blocks(bz: pd.DataFrame, keys: list[str], label_col: str) -> dict[tuple, dict]:
    keep = ["bz_uid", "name_norm", "name_alias", "wgs_lon_true", "wgs_lat_true", "lon", "lat"] + [label_col]
    keep = list(dict.fromkeys([col for col in keep if col in bz.columns]))
    blocks = {}
    for key, group in bz.groupby(keys, dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        if any(pd.isna(item) or item == "" for item in key):
            continue
        rows = group[keep].copy().set_index("bz_uid", drop=False)
        choices = {int(row.bz_uid): getattr(row, label_col) for row in rows.itertuples(index=False) if getattr(row, label_col)}
        if choices:
            blocks[key] = {"rows": rows, "choices": choices}
    return blocks


def choose_candidate(row: dict, block: dict, mode: str, threshold: float, max_km: float | None) -> tuple[int, float] | None:
    if mode == "exact_norm":
        candidate_ids = [uid for uid, label in block["choices"].items() if label == row["name_norm"]]
    elif mode == "exact_alias":
        candidate_ids = [uid for uid, label in block["choices"].items() if label == row["name_alias"]]
    else:
        hits = process.extract(row["name_alias"], block["choices"], scorer=fuzz.WRatio, limit=10)
        candidate_ids = [uid for _, _, uid in hits]

    best = None
    for uid in candidate_ids:
        cand = block["rows"].loc[uid]
        score = 100.0 if mode.startswith("exact") else name_score(row["name_norm"], row["name_alias"], cand["name_norm"], cand["name_alias"])
        if score < threshold:
            continue
        dist = scalar_distance(row, cand)
        if max_km is not None and not (pd.notna(dist) and dist <= max_km):
            continue
        rank = (score, -dist if pd.notna(dist) else -999999.0, -int(uid))
        if best is None or rank > best[0]:
            best = (rank, int(uid), float(score))
    if best is None:
        return None
    return best[1], best[2]


def assign_stage(dp: pd.DataFrame, bz: pd.DataFrame, level: str, keys: list[str], label_col: str, mode: str, threshold: float, max_km: float | None) -> dict:
    print(f"Running {level}...", flush=True)
    mask = dp["match_bz_uid"].isna()
    for key_col in keys:
        mask &= dp[key_col].astype("string").fillna("").ne("")

    if mode.startswith("exact"):
        dp_cols = list(dict.fromkeys(["dp_uid", "lon_wgs", "lat_wgs"] + keys))
        bz_cols = list(dict.fromkeys(["bz_uid", "wgs_lon_true", "wgs_lat_true", "lon", "lat"] + keys))
        cand = dp.loc[mask, [col for col in dp_cols if col in dp.columns]].merge(
            bz[[col for col in bz_cols if col in bz.columns]],
            on=keys,
            how="inner",
        )
        before_distance = len(cand)
        if not cand.empty:
            cand["_distance_km"] = haversine_km(
                cand.get("lon_wgs"),
                cand.get("lat_wgs"),
                cand.get("wgs_lon_true", cand.get("lon")),
                cand.get("wgs_lat_true", cand.get("lat")),
            )
            if max_km is not None:
                cand = cand.loc[cand["_distance_km"].le(max_km)].copy()
            cand["_distance_sort"] = cand["_distance_km"].fillna(999999.0)
            cand = cand.sort_values(["dp_uid", "_distance_sort", "bz_uid"]).drop_duplicates("dp_uid")
            uid_to_bz = cand.set_index("dp_uid")["bz_uid"]
            target = dp["dp_uid"].isin(uid_to_bz.index)
            dp.loc[target, "match_bz_uid"] = dp.loc[target, "dp_uid"].map(uid_to_bz).astype("Int64")
            dp.loc[target, "match_level"] = level
            key_note = "+".join(keys)
            if max_km is not None:
                key_note += f";coord<={max_km:g}km"
            dp.loc[target, "match_key_used"] = key_note
            dp.loc[target, "match_score"] = 100.0
            dp.loc[target, "name_match_score"] = 100.0
        return {
            "match_level": level,
            "match_mode": mode,
            "match_key_used": "+".join(keys),
            "name_threshold": threshold,
            "distance_threshold_km": max_km,
            "candidate_dp_rows_checked": int(mask.sum()),
            "candidate_unique_blocks_checked": np.nan,
            "candidate_rows_before_distance_filter": int(before_distance),
            "new_matched_dp_rows": int(0 if cand.empty else len(cand)),
            "candidate_bz_blocks": np.nan,
        }

    blocks = build_blocks(bz, keys, label_col)
    mask &= dp["name_alias"].astype(str).ne("")
    work_cols = list(dict.fromkeys(["dp_uid", "name_norm", "name_alias", "lon_wgs", "lat_wgs"] + keys))
    work = dp.loc[mask, [col for col in work_cols if col in dp.columns]].copy()

    group_cols = list(dict.fromkeys(["name_norm", "name_alias"] + keys))
    if max_km is not None:
        work["_lon_round"] = pd.to_numeric(work.get("lon_wgs"), errors="coerce").round(5)
        work["_lat_round"] = pd.to_numeric(work.get("lat_wgs"), errors="coerce").round(5)
        group_cols += ["_lon_round", "_lat_round"]

    unique_work = work.drop_duplicates(group_cols)
    matches = []
    for row in unique_work.to_dict("records"):
        if len(row.get("name_alias", "")) < 4:
            continue
        key = tuple(row.get(col) for col in keys)
        block = blocks.get(key)
        if not block:
            continue
        chosen = choose_candidate(row, block, mode, threshold, max_km)
        if not chosen:
            continue
        bz_uid, score = chosen
        item = {col: row.get(col) for col in group_cols}
        item["bz_uid"] = bz_uid
        item["score"] = score
        matches.append(item)

    matched_rows = 0
    if matches:
        match_df = pd.DataFrame(matches).drop_duplicates(group_cols)
        row_matches = work.merge(match_df, on=group_cols, how="inner").drop_duplicates("dp_uid")
        matched_rows = len(row_matches)
        uid_to_bz = row_matches.set_index("dp_uid")["bz_uid"]
        uid_to_score = row_matches.set_index("dp_uid")["score"]
        target = dp["dp_uid"].isin(uid_to_bz.index)
        dp.loc[target, "match_bz_uid"] = dp.loc[target, "dp_uid"].map(uid_to_bz).astype("Int64")
        dp.loc[target, "match_level"] = level
        key_note = "+".join(keys)
        key_note += f";fuzzy_score>={threshold:g}"
        if max_km is not None:
            key_note += f";coord<={max_km:g}km"
        dp.loc[target, "match_key_used"] = key_note
        dp.loc[target, "match_score"] = dp.loc[target, "dp_uid"].map(uid_to_score)
        dp.loc[target, "name_match_score"] = dp.loc[target, "dp_uid"].map(uid_to_score)

    return {
        "match_level": level,
        "match_mode": mode,
        "match_key_used": "+".join(keys),
        "name_threshold": threshold,
        "distance_threshold_km": max_km,
        "candidate_dp_rows_checked": int(len(work)),
        "candidate_unique_blocks_checked": int(len(unique_work)),
        "candidate_rows_before_distance_filter": np.nan,
        "new_matched_dp_rows": int(matched_rows),
        "candidate_bz_blocks": int(len(blocks)),
    }


def run_matching(dp: pd.DataFrame, bz: pd.DataFrame) -> pd.DataFrame:
    stages = [
        ("exact_name_county", ["year", "name_norm", "county_code_norm"], "name_norm", "exact_norm", 100.0, None),
        ("exact_name_city", ["year", "name_norm", "province_norm", "city_norm"], "name_norm", "exact_norm", 100.0, None),
        ("exact_alias_county", ["year", "name_alias", "county_code_norm"], "name_alias", "exact_alias", 100.0, None),
        ("exact_alias_city_coord50", ["year", "name_alias", "province_norm", "city_norm"], "name_alias", "exact_alias", 100.0, 50.0),
        ("exact_name_province_coord20", ["year", "name_norm", "province_norm"], "name_norm", "exact_norm", 100.0, 20.0),
        ("fuzzy_county_name", ["year", "county_code_norm"], "name_alias", "fuzzy", 92.0, None),
        ("fuzzy_city_name_coord50", ["year", "province_norm", "city_norm"], "name_alias", "fuzzy", 93.0, 50.0),
    ]
    return pd.DataFrame([assign_stage(dp, bz, *stage) for stage in stages])


def yearly_summary_row(summary: pd.DataFrame, year: int) -> pd.DataFrame:
    row = summary.loc[summary["year"].astype(str).eq(str(year))]
    return row.copy()


def write_yearly_outputs(
    years: list[int],
    matched_out: pd.DataFrame,
    dp_only_out: pd.DataFrame,
    bz_only_out: pd.DataFrame,
    summary: pd.DataFrame,
    level_summary: pd.DataFrame,
    step_stats: pd.DataFrame,
    bz_multiplicity: pd.DataFrame,
) -> None:
    for year in years:
        year_dir = OUT_DIR / str(year)
        year_dir.mkdir(parents=True, exist_ok=True)

        y_matched = matched_out.loc[pd.to_numeric(matched_out["dp_year"], errors="coerce").eq(year)].copy()
        y_dp_only = dp_only_out.loc[pd.to_numeric(dp_only_out["dp_year"], errors="coerce").eq(year)].copy()
        y_bz_only = bz_only_out.loc[pd.to_numeric(bz_only_out["bz_year"], errors="coerce").eq(year)].copy()
        y_all = pd.concat([y_matched, y_dp_only, y_bz_only], ignore_index=True, sort=False)
        y_level = level_summary.loc[pd.to_numeric(level_summary["year"], errors="coerce").eq(year)].copy()
        y_summary = yearly_summary_row(summary, year)
        y_mult = bz_multiplicity.loc[pd.to_numeric(bz_multiplicity["bz_year"], errors="coerce").eq(year)].copy()

        y_matched.to_csv(year_dir / "matched_both.csv", index=False, encoding="utf-8-sig")
        y_dp_only.to_csv(year_dir / "only_dp_missing_hosp_year.csv", index=False, encoding="utf-8-sig")
        y_bz_only.to_csv(year_dir / "only_hosp_year_missing_dp.csv", index=False, encoding="utf-8-sig")
        y_all.to_csv(year_dir / "merge_all_status.csv", index=False, encoding="utf-8-sig")
        y_summary.to_csv(year_dir / "match_summary.csv", index=False, encoding="utf-8-sig")
        y_level.to_csv(year_dir / "match_summary_by_level.csv", index=False, encoding="utf-8-sig")
        step_stats.to_csv(year_dir / "match_step_stats_global_rules.csv", index=False, encoding="utf-8-sig")
        y_mult.to_csv(year_dir / "bz_matched_multiplicity.csv", index=False, encoding="utf-8-sig")

        year_report = [
            f"Year {year} match summary",
            f"matched_dp_rows={len(y_matched):,}",
            f"only_dp_rows={len(y_dp_only):,}",
            f"only_hosp_year_rows={len(y_bz_only):,}",
            f"matched_unique_hosp_year_rows={y_summary['matched_unique_hosp_year_rows'].iloc[0] if not y_summary.empty else 0:,}",
            "",
            "Files: matched_both.csv, only_dp_missing_hosp_year.csv, only_hosp_year_missing_dp.csv, merge_all_status.csv, match_summary.csv, match_summary_by_level.csv, bz_matched_multiplicity.csv",
        ]
        (year_dir / "year_report.txt").write_text("\n".join(year_report), encoding="utf-8-sig")


def write_outputs(dp: pd.DataFrame, bz: pd.DataFrame, raw_dp_rows: int, step_stats: pd.DataFrame) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    matched_dp = dp.loc[dp["match_bz_uid"].notna()].copy()
    unmatched_dp = dp.loc[dp["match_bz_uid"].isna()].copy()
    matched_bz_ids = set(matched_dp["match_bz_uid"].dropna().astype("int64").tolist())
    matched_bz = bz.loc[bz["bz_uid"].isin(matched_bz_ids)].copy()
    unmatched_bz = bz.loc[~bz["bz_uid"].isin(matched_bz_ids)].copy()

    bz_for_matched = bz.set_index("bz_uid", drop=False).loc[matched_dp["match_bz_uid"].astype("int64").tolist()].reset_index(drop=True)
    matched_dp = matched_dp.reset_index(drop=True)
    matched_status = pd.DataFrame(
        {
            "source_status": ["matched_both"] * len(matched_dp),
            "missing_source": ["none"] * len(matched_dp),
            "match_level": matched_dp["match_level"],
            "match_key_used": matched_dp["match_key_used"],
            "match_score": matched_dp["match_score"],
            "name_match_score": matched_dp["name_match_score"],
            "coord_distance_km": haversine_km(
                matched_dp.get("lon_wgs"),
                matched_dp.get("lat_wgs"),
                bz_for_matched.get("wgs_lon_true", bz_for_matched.get("lon")),
                bz_for_matched.get("wgs_lat_true", bz_for_matched.get("lat")),
            ).round(3),
            "match_rule_version": [RULE_VERSION] * len(matched_dp),
        }
    )
    matched_out = pd.concat([matched_status, matched_dp.add_prefix("dp_"), bz_for_matched.add_prefix("bz_")], axis=1)

    dp_only_status = pd.DataFrame(
        {
            "source_status": ["only_dp"] * len(unmatched_dp),
            "missing_source": ["hosp_year"] * len(unmatched_dp),
            "match_level": [""] * len(unmatched_dp),
            "match_key_used": [""] * len(unmatched_dp),
            "match_score": [np.nan] * len(unmatched_dp),
            "name_match_score": [np.nan] * len(unmatched_dp),
            "coord_distance_km": [np.nan] * len(unmatched_dp),
            "match_rule_version": [RULE_VERSION] * len(unmatched_dp),
        }
    )
    dp_only_out = pd.concat([dp_only_status, unmatched_dp.reset_index(drop=True).add_prefix("dp_")], axis=1)

    bz_only_status = pd.DataFrame(
        {
            "source_status": ["only_hosp_year"] * len(unmatched_bz),
            "missing_source": ["hosp_dp"] * len(unmatched_bz),
            "match_level": [""] * len(unmatched_bz),
            "match_key_used": [""] * len(unmatched_bz),
            "match_score": [np.nan] * len(unmatched_bz),
            "name_match_score": [np.nan] * len(unmatched_bz),
            "coord_distance_km": [np.nan] * len(unmatched_bz),
            "match_rule_version": [RULE_VERSION] * len(unmatched_bz),
        }
    )
    bz_only_out = pd.concat([bz_only_status, unmatched_bz.reset_index(drop=True).add_prefix("bz_")], axis=1)
    all_status = pd.concat([matched_out, dp_only_out, bz_only_out], ignore_index=True, sort=False)

    dp_counts = dp.groupby("year", dropna=False).size().rename("dp_hospital_rows")
    bz_counts = bz.groupby("year", dropna=False).size().rename("hosp_year_rows")
    matched_dp_counts = matched_dp.groupby("year", dropna=False).size().rename("matched_dp_rows")
    matched_bz_counts = matched_bz.groupby("year", dropna=False).size().rename("matched_unique_hosp_year_rows")
    summary = pd.concat([dp_counts, bz_counts, matched_dp_counts, matched_bz_counts], axis=1).fillna(0).astype(int).reset_index()
    summary["unmatched_dp_rows"] = summary["dp_hospital_rows"] - summary["matched_dp_rows"]
    summary["unmatched_hosp_year_rows"] = summary["hosp_year_rows"] - summary["matched_unique_hosp_year_rows"]
    summary["dp_row_match_rate"] = np.where(summary["dp_hospital_rows"] > 0, summary["matched_dp_rows"] / summary["dp_hospital_rows"], np.nan)
    summary["hosp_year_match_rate"] = np.where(summary["hosp_year_rows"] > 0, summary["matched_unique_hosp_year_rows"] / summary["hosp_year_rows"], np.nan)
    summary = summary.sort_values("year")
    summary = pd.concat(
        [
            summary,
            pd.DataFrame(
                [
                    {
                        "year": "ALL",
                        "dp_hospital_rows": len(dp),
                        "hosp_year_rows": len(bz),
                        "matched_dp_rows": len(matched_dp),
                        "matched_unique_hosp_year_rows": len(matched_bz),
                        "unmatched_dp_rows": len(unmatched_dp),
                        "unmatched_hosp_year_rows": len(unmatched_bz),
                        "dp_row_match_rate": len(matched_dp) / len(dp) if len(dp) else np.nan,
                        "hosp_year_match_rate": len(matched_bz) / len(bz) if len(bz) else np.nan,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    level_summary = matched_dp.groupby(["year", "match_level"], dropna=False).size().reset_index(name="matched_dp_rows")
    bz_multiplicity = matched_dp.groupby("match_bz_uid", dropna=False).size().reset_index(name="matched_dp_rows_per_bz")
    bz_multiplicity = bz_multiplicity.sort_values("matched_dp_rows_per_bz", ascending=False).merge(
        bz.add_prefix("bz_"),
        left_on="match_bz_uid",
        right_on="bz_bz_uid",
        how="left",
    )
    top_dp_unmatched = (
        unmatched_dp.groupby(["year", "province19", "city19", "county19", "name"], dropna=False)
        .size()
        .reset_index(name="dp_rows")
        .sort_values(["dp_rows", "year"], ascending=[False, True])
        .head(1000)
    )
    top_bz_unmatched = (
        unmatched_bz.groupby(["year", "business_province", "business_city", "business_county", "ENTNAME"], dropna=False)
        .size()
        .reset_index(name="hosp_year_rows")
        .sort_values(["hosp_year_rows", "year"], ascending=[False, True])
        .head(1000)
    )
    dist_summary = matched_out["coord_distance_km"].describe(percentiles=[0.25, 0.5, 0.75, 0.9, 0.95, 0.99]).to_frame("coord_distance_km").reset_index().rename(columns={"index": "metric"})
    dist_by_level = matched_out.groupby("match_level")["coord_distance_km"].describe(percentiles=[0.5, 0.75, 0.9, 0.95, 0.99]).reset_index()
    score_by_level = matched_out.groupby("match_level")["name_match_score"].describe(percentiles=[0.5, 0.75, 0.9, 0.95, 0.99]).reset_index()
    high_distance = matched_out.loc[matched_out["coord_distance_km"].gt(50)].sort_values("coord_distance_km", ascending=False)

    outputs = [
        ("matched_both.csv", matched_out),
        ("only_dp_missing_hosp_year.csv", dp_only_out),
        ("only_hosp_year_missing_dp.csv", bz_only_out),
        ("merge_all_status.csv", all_status),
        ("match_summary_by_year.csv", summary),
        ("match_summary_by_level.csv", level_summary),
        ("match_step_stats.csv", step_stats),
        ("bz_matched_multiplicity.csv", bz_multiplicity),
        ("top_unmatched_dp.csv", top_dp_unmatched),
        ("top_unmatched_hosp_year.csv", top_bz_unmatched),
        ("matched_coordinate_distance_summary.csv", dist_summary),
        ("matched_coordinate_distance_by_level.csv", dist_by_level),
        ("matched_name_score_by_level.csv", score_by_level),
        ("matched_high_distance_review_over50km.csv", high_distance),
    ]
    for name, frame in outputs:
        frame.to_csv(OUT_DIR / name, index=False, encoding="utf-8-sig")

    years = sorted({int(y) for y in pd.concat([dp["year"].dropna(), bz["year"].dropna()]).astype(int).unique()})
    write_yearly_outputs(years, matched_out, dp_only_out, bz_only_out, summary, level_summary, step_stats, bz_multiplicity)

    fuzzy_rows = int(matched_dp["match_level"].astype(str).str.startswith("fuzzy_").sum())
    many_to_one_bz = int((bz_multiplicity["matched_dp_rows_per_bz"] > 1).sum())
    report = [
        "DP hospital to business-registry hospital fuzzy match",
        "",
        f"rule_version={RULE_VERSION}",
        f"output_dir={OUT_DIR}",
        f"dp_raw_rows={raw_dp_rows:,}",
        f"dp_hospital_rows_after_latest_cleaning={len(dp):,}",
        f"hosp_year_rows={len(bz):,}",
        "",
        "Matching policy:",
        "- Each DP hospital row can match at most one business-registry row.",
        "- One business-registry row may match many DP rows, allowing branch/POI duplication in DP when only one registration exists.",
        "- Match order: exact name+county, exact name+city, exact alias after removing admin tokens, exact alias+city with coord<=50km, exact name+province with coord<=20km, fuzzy county name, fuzzy city name with coord<=50km.",
        "- Fuzzy matching uses rapidfuzz. Ancillary POI suffixes such as parking/pharmacy/dormitory reduce containment scores.",
        "",
        "Overall:",
        f"matched_dp_rows={len(matched_dp):,}",
        f"fuzzy_matched_dp_rows={fuzzy_rows:,}",
        f"unmatched_dp_rows={len(unmatched_dp):,}",
        f"matched_unique_hosp_year_rows={len(matched_bz):,}",
        f"unmatched_hosp_year_rows={len(unmatched_bz):,}",
        f"business_rows_matched_to_2plus_dp_rows={many_to_one_bz:,}",
        f"high_distance_over50km_rows={len(high_distance):,}",
        "",
        "Top-level files:",
    ]
    report.extend(f"- {name}" for name, _ in outputs)
    report.append("")
    report.append("Year folders:")
    report.extend(f"- {year}/" for year in years)
    (OUT_DIR / "match_analysis_report.txt").write_text("\n".join(report), encoding="utf-8-sig")

    print("OUTPUT_DIR=", OUT_DIR)
    print(summary.to_string(index=False))
    print("\nStep stats:")
    print(step_stats.to_string(index=False))
    print("\nYear folders:", ", ".join(str(y) for y in years))
    print("Files written:", len(list(OUT_DIR.glob("*"))))


def main() -> None:
    clear_output_dir()
    dp, bz, raw_dp_rows = prepare_inputs()
    step_stats = run_matching(dp, bz)
    write_outputs(dp, bz, raw_dp_rows, step_stats)


if __name__ == "__main__":
    main()
