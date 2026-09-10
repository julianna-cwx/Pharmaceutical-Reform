from __future__ import annotations

import argparse
import csv
import hashlib
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
    import eviltransform
except Exception as exc:  # pragma: no cover
    raise RuntimeError("需要 eviltransform 用于 BD-09/GCJ-02 转 WGS84") from exc


ROOT = Path(r"D:\Hospital_Pharmacy program")
CODE_DIR = ROOT / "code" / "python"
CLASSIFICATION_DIR = ROOT / "data" / "hospital" / "hosp_panel" / "hosp_classification"
INPUT_MATCHED = CLASSIFICATION_DIR / "hosp_real_spatial_admin_matched.csv"
COUNTY_SHP = ROOT / "data" / "county" / "controls" / "county_boundaries" / "counties19.shp"

OUTPUT_RECHECK = CLASSIFICATION_DIR / "hosp_real_different_coord_recheck.csv"
OUTPUT_MERGED = CLASSIFICATION_DIR / "hosp_real_spatial_admin_matched_coord_rechecked.csv"
OUTPUT_SUMMARY = CLASSIFICATION_DIR / "hosp_real_different_coord_recheck_summary.csv"
CACHE_PATH = CLASSIFICATION_DIR / "hosp_real_different_coord_recheck_cache.csv"

CONFIRM_DISTANCE_M = 500
NEAR_DISTANCE_M = 1000
PROVIDER_AGREE_DISTANCE_M = 500

CACHE_COLUMNS = [
    "recheck_key",
    "companyid",
    "ENTNAME",
    "注册地址",
    "candidate_count",
    "candidate_first",
    "baidu_status",
    "baidu_query",
    "baidu_raw_lon",
    "baidu_raw_lat",
    "baidu_wgs_lon_recheck",
    "baidu_wgs_lat_recheck",
    "baidu_confidence",
    "baidu_level",
    "baidu_error",
    "gaode_status",
    "gaode_query",
    "gaode_raw_lon",
    "gaode_raw_lat",
    "gaode_wgs_lon_recheck",
    "gaode_wgs_lat_recheck",
    "gaode_formatted_address",
    "gaode_level",
    "gaode_error",
    "baidu_to_original_distance_m",
    "gaode_to_original_distance_m",
    "baidu_gaode_recheck_distance_m",
    "recheck_best_source",
    "recheck_best_wgs_lon",
    "recheck_best_wgs_lat",
    "recheck_min_distance_m",
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


def valid_coord(lon: Any, lat: Any) -> bool:
    lon = pd.to_numeric(lon, errors="coerce")
    lat = pd.to_numeric(lat, errors="coerce")
    return pd.notna(lon) and pd.notna(lat) and 70 <= lon <= 140 and 15 <= lat <= 55 and lon != 0 and lat != 0


def haversine_m(lon1: Any, lat1: Any, lon2: Any, lat2: Any) -> float | None:
    if not (valid_coord(lon1, lat1) and valid_coord(lon2, lat2)):
        return None
    lon1, lat1, lon2, lat2 = map(float, [lon1, lat1, lon2, lat2])
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bd09_to_wgs84(lon: Any, lat: Any) -> tuple[float | None, float | None]:
    if not valid_coord(lon, lat):
        return None, None
    wgs_lat, wgs_lon = eviltransform.bd2wgs(float(lat), float(lon))
    return float(wgs_lon), float(wgs_lat)


def gcj02_to_wgs84(lon: Any, lat: Any) -> tuple[float | None, float | None]:
    if not valid_coord(lon, lat):
        return None, None
    wgs_lat, wgs_lon = eviltransform.gcj2wgs(float(lat), float(lon))
    return float(wgs_lon), float(wgs_lat)


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
    gaode_keys = list(dict.fromkeys(env_gaode + gaode_keys))
    return baidu_keys, gaode_keys


def baidu_sn(address: str, ak: str, sk: str) -> str:
    query_str = f"/geocoding/v3/?address={address}&output=json&ak={ak}&ret_coordtype=bd09ll"
    encoded = urllib.parse.quote(query_str, safe="/:=&?#+!$,;'@()*[]")
    raw = encoded + sk
    return hashlib.md5(urllib.parse.quote_plus(raw).encode("utf-8")).hexdigest()


def query_baidu(candidates: list[str], keys: list[dict[str, str]], min_interval: float) -> dict[str, Any]:
    url = "https://api.map.baidu.com/geocoding/v3/"
    last_error = ""
    for candidate in candidates:
        for key in keys:
            ak, sk = key["ak"], key["sk"]
            sn = baidu_sn(candidate, ak, sk)
            params = {"address": candidate, "output": "json", "ak": ak, "ret_coordtype": "bd09ll", "sn": sn}
            try:
                time.sleep(min_interval)
                r = requests.get(url, params=params, timeout=12)
                data = r.json()
            except Exception as exc:
                last_error = repr(exc)
                continue
            status = data.get("status")
            if status == 0 and data.get("result", {}).get("location"):
                loc = data["result"]["location"]
                bd_lon, bd_lat = loc.get("lng"), loc.get("lat")
                wgs_lon, wgs_lat = bd09_to_wgs84(bd_lon, bd_lat)
                return {
                    "baidu_status": "found",
                    "baidu_query": candidate,
                    "baidu_raw_lon": bd_lon,
                    "baidu_raw_lat": bd_lat,
                    "baidu_wgs_lon_recheck": wgs_lon,
                    "baidu_wgs_lat_recheck": wgs_lat,
                    "baidu_confidence": data.get("result", {}).get("confidence"),
                    "baidu_level": data.get("result", {}).get("level"),
                    "baidu_error": "",
                }
            last_error = f"status={status}; msg={data.get('message') or data.get('msg')}"
    return {"baidu_status": "not_found", "baidu_query": "", "baidu_error": last_error}


def query_gaode(candidates: list[str], keys: list[str], min_interval: float) -> dict[str, Any]:
    url = "https://restapi.amap.com/v3/geocode/geo"
    last_error = ""
    for candidate in candidates:
        for key in keys:
            params = {"address": candidate, "key": key, "output": "JSON"}
            try:
                time.sleep(min_interval)
                r = requests.get(url, params=params, timeout=12)
                data = r.json()
            except Exception as exc:
                last_error = repr(exc)
                continue
            if str(data.get("status")) == "1" and data.get("geocodes"):
                geo = data["geocodes"][0]
                loc = safe_str(geo.get("location"))
                if "," in loc:
                    gcj_lon, gcj_lat = loc.split(",", 1)
                    wgs_lon, wgs_lat = gcj02_to_wgs84(gcj_lon, gcj_lat)
                    return {
                        "gaode_status": "found",
                        "gaode_query": candidate,
                        "gaode_raw_lon": float(gcj_lon),
                        "gaode_raw_lat": float(gcj_lat),
                        "gaode_wgs_lon_recheck": wgs_lon,
                        "gaode_wgs_lat_recheck": wgs_lat,
                        "gaode_formatted_address": geo.get("formatted_address"),
                        "gaode_level": geo.get("level"),
                        "gaode_error": "",
                    }
            last_error = f"infocode={data.get('infocode')}; info={data.get('info')}"
    return {"gaode_status": "not_found", "gaode_query": "", "gaode_error": last_error}


def build_candidates(row: pd.Series) -> list[str]:
    ent = safe_str(row.get("ENTNAME"))
    reg_addr = safe_str(row.get("注册地址"))
    province = safe_str(row.get("省份"))
    city = safe_str(row.get("地区"))
    business_province = safe_str(row.get("business_province"))
    business_city = safe_str(row.get("business_city"))
    spatial_province = safe_str(row.get("spatial_province"))
    spatial_city = safe_str(row.get("spatial_city"))
    candidates = [
        reg_addr,
        f"{business_province}{business_city}{ent}",
        f"{spatial_province}{spatial_city}{ent}",
        f"{province}{city}{ent}",
        f"{city}{ent}",
        f"{province}{ent}",
        ent,
    ]
    return list(dict.fromkeys([x for x in candidates if x]))


def recheck_key(row: pd.Series) -> str:
    raw = "|".join([safe_str(row.get(c)) for c in ["companyid", "ENTNAME", "注册地址", "省份", "地区"]])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    df = read_csv_auto(path, dtype=str)
    if "recheck_key" not in df.columns:
        return {}
    return {safe_str(r["recheck_key"]): dict(r) for _, r in df.iterrows()}


def append_cache(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CACHE_COLUMNS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow({col: row.get(col, "") for col in CACHE_COLUMNS})


def choose_best(row: dict[str, Any], orig_lon: Any, orig_lat: Any) -> dict[str, Any]:
    bd_lon, bd_lat = row.get("baidu_wgs_lon_recheck"), row.get("baidu_wgs_lat_recheck")
    gd_lon, gd_lat = row.get("gaode_wgs_lon_recheck"), row.get("gaode_wgs_lat_recheck")
    bd_dist = haversine_m(orig_lon, orig_lat, bd_lon, bd_lat)
    gd_dist = haversine_m(orig_lon, orig_lat, gd_lon, gd_lat)
    provider_dist = haversine_m(bd_lon, bd_lat, gd_lon, gd_lat)
    row["baidu_to_original_distance_m"] = bd_dist
    row["gaode_to_original_distance_m"] = gd_dist
    row["baidu_gaode_recheck_distance_m"] = provider_dist
    candidates = [("baidu", bd_dist, bd_lon, bd_lat), ("gaode", gd_dist, gd_lon, gd_lat)]
    candidates = [x for x in candidates if x[1] is not None]
    if not candidates:
        row.update({"recheck_best_source": "", "recheck_best_wgs_lon": None, "recheck_best_wgs_lat": None, "recheck_min_distance_m": None})
        return row
    best = min(candidates, key=lambda x: x[1])
    row.update({
        "recheck_best_source": best[0],
        "recheck_best_wgs_lon": best[2],
        "recheck_best_wgs_lat": best[3],
        "recheck_min_distance_m": best[1],
    })
    return row


def classify(row: pd.Series) -> str:
    min_dist = pd.to_numeric(row.get("recheck_min_distance_m"), errors="coerce")
    provider_dist = pd.to_numeric(row.get("baidu_gaode_recheck_distance_m"), errors="coerce")
    bd_found = safe_str(row.get("baidu_status")) == "found"
    gd_found = safe_str(row.get("gaode_status")) == "found"
    if not bd_found and not gd_found:
        return "query_not_found"
    if pd.notna(min_dist) and min_dist <= CONFIRM_DISTANCE_M:
        return "current_coord_confirmed_le_500m"
    if pd.notna(min_dist) and min_dist <= NEAR_DISTANCE_M:
        return "current_coord_near_500_1000m"
    if bd_found and gd_found and pd.notna(provider_dist):
        if provider_dist <= PROVIDER_AGREE_DISTANCE_M:
            return "current_coord_suspect_query_sources_agree_far"
        return "manual_review_query_sources_conflict"
    return "manual_review_single_source_far"


def spatial_join_best(recheck: pd.DataFrame) -> pd.DataFrame:
    valid = recheck[
        recheck["recheck_best_wgs_lon"].apply(lambda x: valid_coord(x, 30))
        & recheck["recheck_best_wgs_lat"].apply(lambda x: valid_coord(110, x))
    ].copy()
    if valid.empty:
        return recheck
    counties = gpd.read_file(COUNTY_SHP).to_crs("EPSG:4326")
    counties = counties.rename(columns={
        "PAC": "recheck_spatial_county_code",
        "NAME": "recheck_spatial_county",
        "省代码": "recheck_spatial_province_code",
        "省": "recheck_spatial_province",
        "市代码": "recheck_spatial_city_code",
        "市": "recheck_spatial_city",
    })[[
        "recheck_spatial_county_code",
        "recheck_spatial_county",
        "recheck_spatial_province_code",
        "recheck_spatial_province",
        "recheck_spatial_city_code",
        "recheck_spatial_city",
        "geometry",
    ]]
    points = gpd.GeoDataFrame(
        valid,
        geometry=gpd.points_from_xy(valid["recheck_best_wgs_lon"], valid["recheck_best_wgs_lat"]),
        crs="EPSG:4326",
    )
    joined = gpd.sjoin(points, counties, how="left", predicate="intersects")
    keep = [c for c in joined.columns if c.startswith("recheck_spatial_")]
    joined = joined[["recheck_key"] + keep].drop_duplicates("recheck_key", keep="first")
    return recheck.merge(joined, on="recheck_key", how="left")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="复核 spatial_match_status=different 的医院地图坐标")
    parser.add_argument("--input", type=Path, default=INPUT_MATCHED)
    parser.add_argument("--output", type=Path, default=OUTPUT_RECHECK)
    parser.add_argument("--merged-output", type=Path, default=OUTPUT_MERGED)
    parser.add_argument("--summary-output", type=Path, default=OUTPUT_SUMMARY)
    parser.add_argument("--cache", type=Path, default=CACHE_PATH)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-interval", type=float, default=0.35)
    parser.add_argument("--force", action="store_true", help="忽略已有复核缓存，重新查询")
    args = parser.parse_args(argv)

    df = read_csv_auto(args.input, dtype=str)
    different = df[df["spatial_match_status"].eq("different")].copy()
    different["recheck_key"] = different.apply(recheck_key, axis=1)
    if args.limit:
        different = different.head(args.limit).copy()

    baidu_keys, gaode_keys = load_api_keys()
    if not baidu_keys and not gaode_keys:
        raise RuntimeError("没有可用的百度或高德 API key")

    cache = {} if args.force else load_cache(args.cache)
    records: list[dict[str, Any]] = []
    for idx, row in different.iterrows():
        key = recheck_key(row)
        if key in cache:
            record = cache[key]
        else:
            candidates = build_candidates(row)
            record = {
                "recheck_key": key,
                "companyid": row.get("companyid"),
                "ENTNAME": row.get("ENTNAME"),
                "注册地址": row.get("注册地址"),
                "candidate_count": len(candidates),
                "candidate_first": candidates[0] if candidates else "",
            }
            if baidu_keys:
                record.update(query_baidu(candidates, baidu_keys, args.min_interval))
            else:
                record.update({"baidu_status": "not_configured", "baidu_error": "no_key"})
            if gaode_keys:
                record.update(query_gaode(candidates, gaode_keys, args.min_interval))
            else:
                record.update({"gaode_status": "not_configured", "gaode_error": "no_key"})
            record = choose_best(record, row.get("wgs_lon_true"), row.get("wgs_lat_true"))
            append_cache(args.cache, record)
            print(f"rechecked {len(records) + 1}/{len(different)}: {record.get('ENTNAME')} -> {record.get('recheck_best_source') or 'not_found'}")
        records.append(record)

    recheck = pd.DataFrame(records)
    if recheck.empty:
        print("没有 spatial_match_status=different 的记录需要复核")
        return
    recheck = spatial_join_best(recheck)
    out = different.merge(recheck, on="recheck_key", how="left", suffixes=("", "_recheck"))
    out["coord_recheck_flag"] = out.apply(classify, axis=1)
    out["recheck_matches_current_spatial_county"] = (
        out.get("recheck_spatial_county_code").astype("string").str.strip()
        == out.get("spatial_county_code").astype("string").str.strip()
    )
    out["recheck_matches_business_county"] = (
        out.get("recheck_spatial_county_code").astype("string").str.strip()
        == out.get("business_county_code").astype("string").str.strip()
    )

    df["recheck_key"] = df.apply(recheck_key, axis=1)
    merged = df.merge(
        out[["recheck_key", "coord_recheck_flag", "recheck_best_source", "recheck_min_distance_m",
             "recheck_best_wgs_lon", "recheck_best_wgs_lat", "recheck_spatial_county_code", "recheck_spatial_county"]],
        on="recheck_key",
        how="left",
    ).drop(columns=["recheck_key"], errors="ignore")

    summary = out["coord_recheck_flag"].value_counts(dropna=False).rename_axis("coord_recheck_flag").reset_index(name="rows")
    summary["share"] = summary["rows"] / len(out)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False, encoding="utf-8-sig")
    merged.to_csv(args.merged_output, index=False, encoding="utf-8-sig")
    summary.to_csv(args.summary_output, index=False, encoding="utf-8-sig")
    print(summary)
    print("复核明细:", args.output)
    print("合并标记:", args.merged_output)
    print("复核汇总:", args.summary_output)
    print("缓存:", args.cache)


if __name__ == "__main__":
    main()
