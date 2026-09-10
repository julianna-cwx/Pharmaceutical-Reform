from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import requests

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    from fuzzywuzzy import fuzz  # type: ignore


ROOT = Path(r"D:\Hospital_Pharmacy program")
CODE_DIR = ROOT / "code" / "python"
CLASSIFICATION_DIR = ROOT / "data" / "hospital" / "hosp_panel" / "hosp_classification"
RECHECK_INPUT = CLASSIFICATION_DIR / "hosp_real_different_coord_recheck.csv"
FULL_INPUT = CLASSIFICATION_DIR / "hosp_real_spatial_admin_matched_coord_rechecked.csv"
COUNTY_SHP = ROOT / "data" / "county" / "controls" / "county_boundaries" / "counties19.shp"

OUTPUT_DIFFERENT_DECISION = CLASSIFICATION_DIR / "hosp_real_different_coord_final_decision.csv"
OUTPUT_FULL_FINAL = CLASSIFICATION_DIR / "hosp_real_spatial_admin_matched_coord_final.csv"
OUTPUT_SUMMARY = CLASSIFICATION_DIR / "hosp_real_coord_final_decision_summary.csv"
REVERSE_CACHE = CLASSIFICATION_DIR / "hosp_real_conflict_reverse_geocode_cache.csv"

NAME_MATCH_THRESHOLD = 80
ADDRESS_MATCH_THRESHOLD = 85

REVERSE_CACHE_COLUMNS = [
    "reverse_key",
    "provider",
    "raw_lon",
    "raw_lat",
    "reverse_status",
    "reverse_province",
    "reverse_city",
    "reverse_district",
    "reverse_formatted_address",
    "reverse_poi_names",
    "reverse_error",
]


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


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def clean_text(value: Any) -> str:
    return "".join(ch for ch in safe_str(value) if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def valid_coord(lon: Any, lat: Any) -> bool:
    lon = pd.to_numeric(lon, errors="coerce")
    lat = pd.to_numeric(lat, errors="coerce")
    return pd.notna(lon) and pd.notna(lat) and 70 <= lon <= 140 and 15 <= lat <= 55 and lon != 0 and lat != 0


def reverse_key(provider: str, lon: Any, lat: Any) -> str:
    return f"{provider}|{float(lon):.7f}|{float(lat):.7f}"


def row_recheck_key(row: pd.Series) -> str:
    raw = "|".join([safe_str(row.get(c)) for c in ["companyid", "ENTNAME", "注册地址", "省份", "地区"]])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def load_api_keys() -> tuple[list[dict[str, str]], list[str]]:
    sys.path.insert(0, str(CODE_DIR))
    baidu_keys: list[dict[str, str]] = []
    gaode_keys: list[str] = []
    try:
        from datacleaning_baidu import API_KEYS as BAIDU_API_KEYS  # type: ignore

        baidu_keys = [k for k in BAIDU_API_KEYS if safe_str(k.get("ak")) and safe_str(k.get("sk"))]
    except Exception as exc:
        print("无法读取百度 API_KEYS:", repr(exc))
    try:
        from datacleaning_gaode import DEFAULT_GAODE_KEYS  # type: ignore

        gaode_keys = [safe_str(k) for k in DEFAULT_GAODE_KEYS if safe_str(k)]
    except Exception as exc:
        print("无法读取高德 DEFAULT_GAODE_KEYS:", repr(exc))
    env_gaode = [x.strip() for x in os.environ.get("GAODE_API_KEYS", "").split(",") if x.strip()]
    return baidu_keys, list(dict.fromkeys(env_gaode + gaode_keys))


def baidu_reverse_sn(lat: Any, lon: Any, ak: str, sk: str) -> str:
    query = (
        "/reverse_geocoding/v3/"
        f"?ak={ak}&output=json&coordtype=bd09ll&location={lat},{lon}&extensions_poi=1"
    )
    encoded = urllib.parse.quote(query, safe="/:=&?#+!$,;'@()*[]")
    raw = encoded + sk
    return hashlib.md5(urllib.parse.quote_plus(raw).encode("utf-8")).hexdigest()


def reverse_baidu(lon: Any, lat: Any, keys: list[dict[str, str]], min_interval: float) -> dict[str, Any]:
    if not valid_coord(lon, lat):
        return {"reverse_status": "invalid_coord", "reverse_error": "invalid baidu raw coord"}
    url = "https://api.map.baidu.com/reverse_geocoding/v3/"
    last_error = ""
    for key in keys:
        ak, sk = key["ak"], key["sk"]
        query = (
            f"ak={ak}&output=json&coordtype=bd09ll"
            f"&location={lat},{lon}&extensions_poi=1"
        )
        sn = baidu_reverse_sn(lat, lon, ak, sk)
        signed_url = f"{url}?{query}&sn={sn}"
        try:
            time.sleep(min_interval)
            data = requests.get(signed_url, timeout=12).json()
        except Exception as exc:
            last_error = repr(exc)
            continue
        if data.get("status") == 0:
            result = data.get("result") or {}
            comp = result.get("addressComponent") or {}
            pois = result.get("pois") or []
            poi_names = ";".join([safe_str(p.get("name")) for p in pois if safe_str(p.get("name"))])
            return {
                "reverse_status": "found",
                "reverse_province": comp.get("province"),
                "reverse_city": comp.get("city"),
                "reverse_district": comp.get("district"),
                "reverse_formatted_address": result.get("formatted_address") or result.get("sematic_description"),
                "reverse_poi_names": poi_names,
                "reverse_error": "",
            }
        last_error = f"status={data.get('status')}; msg={data.get('message') or data.get('msg')}"
    return {"reverse_status": "not_found", "reverse_error": last_error}


def reverse_gaode(lon: Any, lat: Any, keys: list[str], min_interval: float) -> dict[str, Any]:
    if not valid_coord(lon, lat):
        return {"reverse_status": "invalid_coord", "reverse_error": "invalid gaode raw coord"}
    url = "https://restapi.amap.com/v3/geocode/regeo"
    last_error = ""
    for key in keys:
        params = {
            "key": key,
            "location": f"{lon},{lat}",
            "extensions": "all",
            "output": "JSON",
            "radius": 1000,
        }
        try:
            time.sleep(min_interval)
            data = requests.get(url, params=params, timeout=12).json()
        except Exception as exc:
            last_error = repr(exc)
            continue
        if str(data.get("status")) == "1" and data.get("regeocode"):
            rg = data["regeocode"]
            comp = rg.get("addressComponent") or {}
            province = comp.get("province")
            city = comp.get("city")
            if isinstance(city, list):
                city = ""
            district = comp.get("district")
            if isinstance(district, list):
                district = ""
            pois = rg.get("pois") or []
            poi_names = ";".join([safe_str(p.get("name")) for p in pois if safe_str(p.get("name"))])
            return {
                "reverse_status": "found",
                "reverse_province": province,
                "reverse_city": city,
                "reverse_district": district,
                "reverse_formatted_address": rg.get("formatted_address"),
                "reverse_poi_names": poi_names,
                "reverse_error": "",
            }
        last_error = f"infocode={data.get('infocode')}; info={data.get('info')}"
    return {"reverse_status": "not_found", "reverse_error": last_error}


def load_reverse_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    df = read_csv_auto(path, dtype=str)
    if "reverse_key" not in df.columns:
        return {}
    return {safe_str(r["reverse_key"]): dict(r) for _, r in df.iterrows()}


def append_reverse_cache(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVERSE_CACHE_COLUMNS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow({col: row.get(col, "") for col in REVERSE_CACHE_COLUMNS})


def get_reverse(
    provider: str,
    lon: Any,
    lat: Any,
    baidu_keys: list[dict[str, str]],
    gaode_keys: list[str],
    cache: dict[str, dict[str, Any]],
    cache_path: Path,
    min_interval: float,
) -> dict[str, Any]:
    key = reverse_key(provider, lon, lat)
    if key in cache and not (
        provider == "baidu"
        and safe_str(cache[key].get("reverse_error")).find("SN校验失败") >= 0
    ):
        return cache[key]
    if provider == "baidu":
        res = reverse_baidu(lon, lat, baidu_keys, min_interval)
    else:
        res = reverse_gaode(lon, lat, gaode_keys, min_interval)
    out = {"reverse_key": key, "provider": provider, "raw_lon": lon, "raw_lat": lat, **res}
    append_reverse_cache(cache_path, out)
    cache[key] = out
    return out


def fuzzy_max(query: str, candidates: list[str]) -> int:
    q = clean_text(query)
    if not q:
        return 0
    scores = []
    for cand in candidates:
        c = clean_text(cand)
        if c:
            scores.append(max(fuzz.WRatio(q, c), fuzz.partial_ratio(q, c)))
    return int(max(scores)) if scores else 0


def admin_bonus(row: pd.Series, rev: dict[str, Any]) -> int:
    score = 0
    rev_prov = safe_str(rev.get("reverse_province"))
    rev_city = safe_str(rev.get("reverse_city"))
    rev_dist = safe_str(rev.get("reverse_district"))
    for col in ["business_province", "spatial_province", "省份"]:
        if rev_prov and rev_prov == safe_str(row.get(col)):
            score += 5
            break
    for col in ["business_city", "spatial_city", "地区"]:
        if rev_city and rev_city == safe_str(row.get(col)):
            score += 5
            break
    for col in ["business_county", "spatial_county"]:
        if rev_dist and rev_dist == safe_str(row.get(col)):
            score += 5
            break
    return score


def score_reverse_match(row: pd.Series, prefix: str, rev: dict[str, Any]) -> dict[str, Any]:
    ent = safe_str(row.get("ENTNAME"))
    reg_addr = safe_str(row.get("注册地址"))
    poi_names = safe_str(rev.get("reverse_poi_names"))
    formatted = safe_str(rev.get("reverse_formatted_address"))
    name_candidates = [x for x in poi_names.split(";") if x] + [formatted]
    name_score = fuzzy_max(ent, name_candidates)
    address_score = fuzzy_max(reg_addr, [formatted, poi_names])
    bonus = admin_bonus(row, rev)
    matched = (name_score >= NAME_MATCH_THRESHOLD) or (address_score >= ADDRESS_MATCH_THRESHOLD and bonus >= 10)
    return {
        f"{prefix}_reverse_status": rev.get("reverse_status"),
        f"{prefix}_reverse_province": rev.get("reverse_province"),
        f"{prefix}_reverse_city": rev.get("reverse_city"),
        f"{prefix}_reverse_district": rev.get("reverse_district"),
        f"{prefix}_reverse_formatted_address": formatted,
        f"{prefix}_reverse_poi_names": poi_names,
        f"{prefix}_reverse_name_score": name_score,
        f"{prefix}_reverse_address_score": address_score,
        f"{prefix}_reverse_admin_bonus": bonus,
        f"{prefix}_reverse_match_score": max(name_score, address_score) + bonus,
        f"{prefix}_reverse_match_flag": matched,
    }


def choose_conflict_source(row: pd.Series) -> tuple[str, str]:
    bd_ok = str(row.get("baidu_reverse_match_flag")).lower() == "true"
    gd_ok = str(row.get("gaode_reverse_match_flag")).lower() == "true"
    if bd_ok and gd_ok:
        bd_score = pd.to_numeric(row.get("baidu_reverse_match_score"), errors="coerce")
        gd_score = pd.to_numeric(row.get("gaode_reverse_match_score"), errors="coerce")
        if pd.isna(bd_score):
            bd_score = -1
        if pd.isna(gd_score):
            gd_score = -1
        if gd_score > bd_score:
            return "gaode", "replace_with_gaode_reverse_fuzzy_match"
        return "baidu", "replace_with_baidu_reverse_fuzzy_match"
    if bd_ok:
        return "baidu", "replace_with_baidu_reverse_fuzzy_match"
    if gd_ok:
        return "gaode", "replace_with_gaode_reverse_fuzzy_match"
    return "", "manual_query_required_reverse_fuzzy_unmatched"


def code6(values: pd.Series) -> pd.Series:
    s = pd.Series(values)
    out = pd.Series(pd.NA, index=s.index, dtype="string")
    numeric = pd.to_numeric(s, errors="coerce")
    mask = numeric.notna()
    if mask.any():
        out.loc[mask] = numeric.loc[mask].round().astype("Int64").astype("string")
    text = s.astype("string").str.extract(r"(\d{6})", expand=False)
    out = out.fillna(text)
    return out.astype("string").str.zfill(6)


def spatial_join_final(df: pd.DataFrame) -> pd.DataFrame:
    valid = df[df.apply(lambda r: valid_coord(r.get("final_wgs_lon"), r.get("final_wgs_lat")), axis=1)].copy()
    if valid.empty:
        return df
    counties = gpd.read_file(COUNTY_SHP).to_crs("EPSG:4326")
    counties = counties.rename(columns={
        "PAC": "final_spatial_county_code",
        "NAME": "final_spatial_county",
        "省代码": "final_spatial_province_code",
        "省": "final_spatial_province",
        "市代码": "final_spatial_city_code",
        "市": "final_spatial_city",
    })[[
        "final_spatial_county_code",
        "final_spatial_county",
        "final_spatial_province_code",
        "final_spatial_province",
        "final_spatial_city_code",
        "final_spatial_city",
        "geometry",
    ]]
    points = gpd.GeoDataFrame(valid, geometry=gpd.points_from_xy(valid["final_wgs_lon"], valid["final_wgs_lat"]), crs="EPSG:4326")
    joined = gpd.sjoin(points, counties, how="left", predicate="intersects")
    keep = [c for c in joined.columns if c.startswith("final_spatial_")]
    joined = joined[["recheck_key"] + keep].drop_duplicates("recheck_key", keep="first")
    out = df.drop(columns=[c for c in keep if c in df.columns], errors="ignore").merge(joined, on="recheck_key", how="left")
    for col in ["final_spatial_county_code", "final_spatial_province_code", "final_spatial_city_code"]:
        if col in out.columns:
            out[col] = code6(out[col])
    return out


def apply_decision(row: pd.Series) -> dict[str, Any]:
    flag = safe_str(row.get("coord_recheck_flag"))
    if flag in {"current_coord_confirmed_le_500m", "current_coord_near_500_1000m"}:
        return {
            "final_coord_decision": "keep_original_coord",
            "final_coord_source": "original_wgs",
            "final_wgs_lon": row.get("wgs_lon_true"),
            "final_wgs_lat": row.get("wgs_lat_true"),
            "final_manual_review_required": False,
        }
    if flag == "current_coord_suspect_query_sources_agree_far":
        src = safe_str(row.get("recheck_best_source")) or "recheck_best"
        return {
            "final_coord_decision": "replace_with_recheck_agree_far",
            "final_coord_source": src,
            "final_wgs_lon": row.get(f"{src}_wgs_lon_recheck") if src in {"baidu", "gaode"} else row.get("recheck_best_wgs_lon"),
            "final_wgs_lat": row.get(f"{src}_wgs_lat_recheck") if src in {"baidu", "gaode"} else row.get("recheck_best_wgs_lat"),
            "final_manual_review_required": False,
        }
    if flag == "manual_review_query_sources_conflict":
        src, decision = choose_conflict_source(row)
        if src:
            return {
                "final_coord_decision": decision,
                "final_coord_source": src,
                "final_wgs_lon": row.get(f"{src}_wgs_lon_recheck"),
                "final_wgs_lat": row.get(f"{src}_wgs_lat_recheck"),
                "final_manual_review_required": False,
            }
        return {
            "final_coord_decision": "manual_query_required_reverse_fuzzy_unmatched",
            "final_coord_source": "",
            "final_wgs_lon": row.get("wgs_lon_true"),
            "final_wgs_lat": row.get("wgs_lat_true"),
            "final_manual_review_required": True,
        }
    return {
        "final_coord_decision": "not_rechecked_keep_original",
        "final_coord_source": "original_wgs",
        "final_wgs_lon": row.get("wgs_lon_true"),
        "final_wgs_lat": row.get("wgs_lat_true"),
        "final_manual_review_required": False,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="根据坐标复核结果生成最终坐标决策")
    parser.add_argument("--recheck-input", type=Path, default=RECHECK_INPUT)
    parser.add_argument("--full-input", type=Path, default=FULL_INPUT)
    parser.add_argument("--output-different", type=Path, default=OUTPUT_DIFFERENT_DECISION)
    parser.add_argument("--output-full", type=Path, default=OUTPUT_FULL_FINAL)
    parser.add_argument("--summary-output", type=Path, default=OUTPUT_SUMMARY)
    parser.add_argument("--reverse-cache", type=Path, default=REVERSE_CACHE)
    parser.add_argument("--min-interval", type=float, default=0.25)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    recheck = read_csv_auto(args.recheck_input, dtype=str)
    full = read_csv_auto(args.full_input, dtype=str)
    if "recheck_key" not in recheck.columns:
        recheck["recheck_key"] = recheck.apply(row_recheck_key, axis=1)
    if "recheck_key" not in full.columns:
        full["recheck_key"] = full.apply(row_recheck_key, axis=1)
    conflict = recheck[recheck["coord_recheck_flag"].eq("manual_review_query_sources_conflict")].copy()
    if args.limit:
        conflict = conflict.head(args.limit).copy()

    baidu_keys, gaode_keys = load_api_keys()
    reverse_cache = load_reverse_cache(args.reverse_cache)

    conflict_records: list[pd.Series] = []
    for i, (_, row) in enumerate(conflict.iterrows(), start=1):
        bd_rev = get_reverse("baidu", row.get("baidu_raw_lon"), row.get("baidu_raw_lat"), baidu_keys, gaode_keys, reverse_cache, args.reverse_cache, args.min_interval)
        gd_rev = get_reverse("gaode", row.get("gaode_raw_lon"), row.get("gaode_raw_lat"), baidu_keys, gaode_keys, reverse_cache, args.reverse_cache, args.min_interval)
        extra = {}
        extra.update(score_reverse_match(row, "baidu", bd_rev))
        extra.update(score_reverse_match(row, "gaode", gd_rev))
        updated = row.copy()
        for k, v in extra.items():
            updated[k] = v
        conflict_records.append(updated)
        if i % 25 == 0 or i == len(conflict):
            print(f"reverse fuzzy checked {i}/{len(conflict)}")

    if conflict_records:
        conflict_scored = pd.DataFrame(conflict_records)
        recheck = recheck.merge(
            conflict_scored[[
                "recheck_key",
                "baidu_reverse_status", "baidu_reverse_province", "baidu_reverse_city", "baidu_reverse_district",
                "baidu_reverse_formatted_address", "baidu_reverse_poi_names", "baidu_reverse_name_score",
                "baidu_reverse_address_score", "baidu_reverse_admin_bonus", "baidu_reverse_match_score", "baidu_reverse_match_flag",
                "gaode_reverse_status", "gaode_reverse_province", "gaode_reverse_city", "gaode_reverse_district",
                "gaode_reverse_formatted_address", "gaode_reverse_poi_names", "gaode_reverse_name_score",
                "gaode_reverse_address_score", "gaode_reverse_admin_bonus", "gaode_reverse_match_score", "gaode_reverse_match_flag",
            ]],
            on="recheck_key",
            how="left",
        )

    decisions = recheck.apply(apply_decision, axis=1, result_type="expand")
    recheck = pd.concat([recheck, decisions], axis=1)
    recheck = spatial_join_final(recheck)
    recheck["final_matches_business_county"] = (
        recheck["final_spatial_county_code"].astype("string").str.strip()
        == recheck["business_county_code"].astype("string").str.strip()
    )
    recheck["final_matches_original_spatial_county"] = (
        recheck["final_spatial_county_code"].astype("string").str.strip()
        == recheck["spatial_county_code"].astype("string").str.strip()
    )

    full_out = full.merge(
        recheck[[
            "recheck_key", "final_coord_decision", "final_coord_source", "final_wgs_lon", "final_wgs_lat",
            "final_manual_review_required", "final_spatial_county_code", "final_spatial_county",
            "final_spatial_province_code", "final_spatial_province", "final_spatial_city_code", "final_spatial_city",
            "final_matches_business_county", "final_matches_original_spatial_county",
        ]],
        on="recheck_key",
        how="left",
    )
    non_rechecked = full_out["final_coord_decision"].isna()
    full_out.loc[non_rechecked, "final_coord_decision"] = "not_different_keep_original"
    full_out.loc[non_rechecked, "final_coord_source"] = "original_wgs"
    full_out.loc[non_rechecked, "final_wgs_lon"] = full_out.loc[non_rechecked, "wgs_lon_true"]
    full_out.loc[non_rechecked, "final_wgs_lat"] = full_out.loc[non_rechecked, "wgs_lat_true"]
    full_out.loc[non_rechecked, "final_manual_review_required"] = False

    summary = full_out["final_coord_decision"].value_counts(dropna=False).rename_axis("final_coord_decision").reset_index(name="rows")
    summary["share"] = summary["rows"] / len(full_out)
    manual = pd.DataFrame([{
        "final_coord_decision": "manual_review_required_total",
        "rows": int(full_out["final_manual_review_required"].astype(str).str.lower().eq("true").sum()),
        "share": float(full_out["final_manual_review_required"].astype(str).str.lower().eq("true").mean()),
    }])
    summary = pd.concat([summary, manual], ignore_index=True)

    args.output_different.parent.mkdir(parents=True, exist_ok=True)
    recheck.to_csv(args.output_different, index=False, encoding="utf-8-sig")
    full_out.to_csv(args.output_full, index=False, encoding="utf-8-sig")
    summary.to_csv(args.summary_output, index=False, encoding="utf-8-sig")
    print(summary)
    print("差异样本最终坐标决策:", args.output_different)
    print("全量最终坐标表:", args.output_full)
    print("最终决策汇总:", args.summary_output)
    print("逆地理编码缓存:", args.reverse_cache)


if __name__ == "__main__":
    main()
