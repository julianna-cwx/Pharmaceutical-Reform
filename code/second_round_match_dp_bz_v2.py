from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
import math
import re
import unicodedata

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process
from scipy.spatial import cKDTree


BASE = Path(r"D:\Hospital_Pharmacy program")
V1_DIR = BASE / "data" / "hospital" / "hosp_dp" / "diff_dp_bz"
BZ_DIR = BASE / "data" / "hospital" / "hosp_panel" / "hosp_year"
V2_DIR = V1_DIR / "v2"
YEARS = list(range(2012, 2020))
RULE_VERSION = "dp_bz_second_round_v2_2026-07-28"

COL_NAME = "\u533b\u9662\u540d\u79f0"
COL_SOURCE = "\u5408\u5e76\u540e\u7684\u6570\u636e\u6765\u6e90"
COL_STAGE = "\u5339\u914d\u9636\u6bb5"
COL_RULE = "\u4e8c\u6b21\u5339\u914d\u89c4\u5219"
COL_NAME_SCORE = "\u540d\u79f0\u76f8\u4f3c\u5ea6"
COL_DISTANCE = "\u5750\u6807\u8ddd\u79bb_km"
COL_COMPOSITE = "\u7efc\u5408\u5339\u914d\u5f97\u5206"
COL_VERSION = "\u5339\u914d\u7248\u672c"

BASE_COLUMNS = [
    "year",
    COL_NAME,
    "bz_public",
    "bz_lon",
    "bz_spatial_province",
    "bz_spatial_city",
    "bz_spatial_county",
    "dp_province19",
    "dp_city19",
    "dp_county19",
    "dp_lon_wgs",
    "dp_lat_wgs",
    COL_SOURCE,
]

AUDIT_COLUMNS = [
    COL_STAGE,
    COL_RULE,
    COL_NAME_SCORE,
    COL_DISTANCE,
    COL_COMPOSITE,
    COL_VERSION,
]

PUNCT_RE = re.compile(
    r"[()\uff08\uff09\[\]\u3010\u3011{}<>\u300a\u300b"
    r"\u00b7\u2022,\uff0c.\u3002;\uff1b:\uff1a\u3001/\\|"
    r"\"'\u201c\u201d\u2018\u2019_\-\u2014]+"
)
BRACKET_RE = re.compile(r"[\(\uff08\[\u3010]([^\)\uff09\]\u3011]*)[\)\uff09\]\u3011]")

ADMIN_SUFFIXES = (
    "\u7ef4\u543e\u5c14\u81ea\u6cbb\u533a",
    "\u58ee\u65cf\u81ea\u6cbb\u533a",
    "\u56de\u65cf\u81ea\u6cbb\u533a",
    "\u81ea\u6cbb\u533a",
    "\u7279\u522b\u884c\u653f\u533a",
    "\u81ea\u6cbb\u5dde",
    "\u5730\u533a",
    "\u7701",
    "\u5e02",
    "\u53bf",
    "\u533a",
    "\u65d7",
    "\u76df",
)

BRANCH_TERMS = (
    "\u5e97",
    "\u5206\u9662",
    "\u9662\u533a",
    "\u603b\u9662",
    "\u95e8\u8bca",
    "\u5206\u90e8",
    "\u65d7\u8230",
    "\u65b0\u9662",
    "\u8001\u9662",
    "\u4e1c\u9662",
    "\u897f\u9662",
    "\u5357\u9662",
    "\u5317\u9662",
)

LEGAL_TERMS = (
    "\u80a1\u4efd\u6709\u9650\u516c\u53f8",
    "\u6709\u9650\u8d23\u4efb\u516c\u53f8",
    "\u6709\u9650\u516c\u53f8",
    "\u533b\u7597\u6295\u8d44\u7ba1\u7406",
    "\u533b\u7597\u7ba1\u7406",
    "\u5065\u5eb7\u7ba1\u7406",
    "\u6295\u8d44\u7ba1\u7406",
    "\u4f01\u4e1a\u7ba1\u7406",
    "\u5408\u4f19\u4f01\u4e1a",
    "\u6709\u9650\u5408\u4f19",
    "\u666e\u901a\u5408\u4f19",
    "\u96c6\u56e2",
    "\u5206\u516c\u53f8",
    "\u516c\u53f8",
)

FACILITY_SUFFIXES = (
    "\u793e\u533a\u536b\u751f\u670d\u52a1\u4e2d\u5fc3",
    "\u5987\u5e7c\u4fdd\u5065\u533b\u9662",
    "\u5987\u5e7c\u4fdd\u5065\u9662",
    "\u53e3\u8154\u533b\u9662",
    "\u4e2d\u533b\u533b\u9662",
    "\u4e2d\u533b\u9662",
    "\u4f53\u68c0\u4e2d\u5fc3",
    "\u533b\u5b66\u4e2d\u5fc3",
    "\u533b\u7597\u4e2d\u5fc3",
    "\u536b\u751f\u9662",
    "\u95e8\u8bca\u90e8",
    "\u8bca\u6240",
    "\u533b\u9662",
)

GENERIC_ALIASES = {
    "\u533b\u9662",
    "\u536b\u751f\u9662",
    "\u8bca\u6240",
    "\u95e8\u8bca\u90e8",
    "\u4eba\u6c11\u533b\u9662",
    "\u4e2d\u533b\u9662",
    "\u5987\u5e7c\u4fdd\u5065\u9662",
    "\u4e2d\u5fc3\u533b\u9662",
    "\u53e3\u8154\u533b\u9662",
    "\u7b2c\u4e00\u4eba\u6c11\u533b\u9662",
    "\u7b2c\u4e8c\u4eba\u6c11\u533b\u9662",
    "\u513f\u7ae5\u533b\u9662",
    "\u773c\u79d1\u533b\u9662",
    "\u5987\u4ea7\u533b\u9662",
    "\u6574\u5f62\u533b\u9662",
    "\u5eb7\u590d\u533b\u9662",
    "\u4f53\u68c0\u4e2d\u5fc3",
}

NON_HOSPITAL_CANDIDATE_TERMS = (
    "\u94f6\u884c",
    "\u652f\u884c",
    "\u4fe1\u7528\u793e",
    "\u836f\u5e97",
    "\u836f\u623f",
    "\u505c\u8f66\u573a",
    "\u505c\u8f66",
    "\u5bbf\u820d",
    "\u5bb6\u5c5e\u9662",
    "\u5bb6\u5c5e\u533a",
    "\u9910\u5385",
    "\u98df\u5802",
    "\u8d85\u5e02",
    "\u4fbf\u5229\u5e97",
    "\u5bbe\u9986",
    "\u9152\u5e97",
    "\u5b66\u6821",
    "\u5e7c\u513f\u56ed",
)

ORDINAL_RE = re.compile(r"\u7b2c([0-9\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+)")

GENERIC_CORES = {
    "\u4eba\u6c11",
    "\u4e2d\u5fc3",
    "\u4e2d\u533b",
    "\u53e3\u8154",
    "\u7259\u79d1",
    "\u9f7f\u79d1",
    "\u5987\u5e7c\u4fdd\u5065",
    "\u513f\u7ae5",
    "\u773c\u79d1",
    "\u5987\u4ea7",
    "\u6574\u5f62",
    "\u5eb7\u590d",
    "\u4f53\u68c0",
    "\u5987\u79d1",
    "\u7537\u79d1",
    "\u9aa8\u79d1",
    "\u9aa8\u4f24",
    "\u76ae\u80a4",
    "\u809b\u80a0",
    "\u98ce\u6e7f",
    "\u80bf\u7624",
    "\u7cbe\u795e",
    "\u4e73\u817a",
    "\u6ccc\u5c3f",
    "\u809d\u75c5",
    "\u751f\u6b96",
}

SPECIALTY_GROUPS = {
    "dental": ("\u53e3\u8154", "\u7259\u79d1", "\u9f7f\u79d1"),
    "eye": ("\u773c\u79d1", "\u773c\u75c5"),
    "maternity": ("\u5987\u4ea7", "\u5987\u5e7c", "\u4ea7\u79d1", "\u4ea7\u9662"),
    "children": ("\u513f\u7ae5", "\u513f\u79d1"),
    "tcm": ("\u4e2d\u533b", "\u4e2d\u897f\u533b"),
    "tumor": ("\u80bf\u7624",),
    "mental": ("\u7cbe\u795e", "\u5fc3\u7406"),
    "rehab": ("\u5eb7\u590d",),
    "orthopedic": ("\u9aa8\u79d1", "\u9aa8\u4f24"),
    "dermatology": ("\u76ae\u80a4",),
    "cosmetic": ("\u6574\u5f62", "\u533b\u7f8e", "\u7f8e\u5bb9"),
    "checkup": ("\u4f53\u68c0",),
    "liver": ("\u809d\u75c5", "\u809d\u80c6"),
    "urology": ("\u6ccc\u5c3f", "\u7537\u79d1"),
    "breast": ("\u4e73\u817a",),
    "anorectal": ("\u809b\u80a0",),
    "rheumatology": ("\u98ce\u6e7f",),
    "infertility": ("\u4e0d\u5b55", "\u751f\u6b96"),
}


def text_value(value) -> str:
    if pd.isna(value):
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip().lower()


def normalize_text(value) -> str:
    return re.sub(r"\s+", "", text_value(value))


def normalize_name(value) -> str:
    return PUNCT_RE.sub("", normalize_text(value))


def simple_admin(value) -> str:
    out = normalize_text(value)
    for suffix in ADMIN_SUFFIXES:
        out = out.replace(suffix, "")
    return out


def remove_branch_brackets(value) -> str:
    raw = text_value(value)

    def repl(match: re.Match) -> str:
        inner = normalize_text(match.group(1))
        return "" if any(term in inner for term in BRANCH_TERMS) else inner

    return BRACKET_RE.sub(repl, raw)


def aggressive_alias(name, province="", city="", county="") -> str:
    out = normalize_name(remove_branch_brackets(name))
    for token in sorted(
        {
            normalize_text(province),
            normalize_text(city),
            normalize_text(county),
            simple_admin(province),
            simple_admin(city),
            simple_admin(county),
        }
        - {""},
        key=len,
        reverse=True,
    ):
        out = out.replace(token, "")
    for term in LEGAL_TERMS:
        out = out.replace(term, "")
    out = out.replace("\u4e2d\u533b\u533b\u9662", "\u4e2d\u533b\u9662")
    out = out.replace("\u5987\u5e7c\u4fdd\u5065\u533b\u9662", "\u5987\u5e7c\u4fdd\u5065\u9662")
    for term in (
        "\u65d7\u8230\u5e97",
        "\u603b\u9662",
        "\u5206\u9662",
        "\u9662\u533a",
        "\u5206\u90e8",
        "\u95e8\u8bca\u90e8",
        "\u95e8\u8bca",
    ):
        if out.endswith(term) and len(out) - len(term) >= 4:
            out = out[: -len(term)]
    return out


def core_alias(alias: str) -> str:
    out = alias
    for suffix in FACILITY_SUFFIXES:
        if out.endswith(suffix) and len(out) - len(suffix) >= 2:
            out = out[: -len(suffix)]
            break
    return out


def specialty_set(name: str) -> frozenset[str]:
    return frozenset(
        group
        for group, terms in SPECIALTY_GROUPS.items()
        if any(term in name for term in terms)
    )


def specialty_conflict(left: frozenset[str], right: frozenset[str]) -> bool:
    return bool(left and right and left.isdisjoint(right))


def ordinal_value(name: str) -> str:
    match = ORDINAL_RE.search(name)
    return match.group(1) if match else ""


def distinctive_overlap(left_alias: str, right_alias: str) -> bool:
    left = core_alias(left_alias)
    right = core_alias(right_alias)
    if (
        len(left) < 2
        or len(right) < 2
        or left in GENERIC_CORES
        or right in GENERIC_CORES
    ):
        return False
    if left in right or right in left:
        return True
    if min(len(left), len(right)) < 3:
        return False
    left_bigrams = {left[i : i + 2] for i in range(len(left) - 1)}
    right_bigrams = {right[i : i + 2] for i in range(len(right) - 1)}
    return bool(left_bigrams & right_bigrams) and fuzz.ratio(left, right) >= 65


def haversine_scalar(lon1, lat1, lon2, lat2) -> float:
    values = [lon1, lat1, lon2, lat2]
    try:
        lon1, lat1, lon2, lat2 = [float(value) for value in values]
    except (TypeError, ValueError):
        return math.nan
    if not (
        -180 <= lon1 <= 180
        and -180 <= lon2 <= 180
        and -90 <= lat1 <= 90
        and -90 <= lat2 <= 90
    ):
        return math.nan
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def to_xyz(lon: pd.Series, lat: pd.Series) -> np.ndarray:
    lon_rad = np.radians(pd.to_numeric(lon, errors="coerce").to_numpy(dtype=float))
    lat_rad = np.radians(pd.to_numeric(lat, errors="coerce").to_numpy(dtype=float))
    cos_lat = np.cos(lat_rad)
    return np.column_stack(
        [cos_lat * np.cos(lon_rad), cos_lat * np.sin(lon_rad), np.sin(lat_rad)]
    )


def same_nonempty(left, right) -> bool:
    return bool(left and right and left == right)


def compute_name_score(dp_row, bz_row) -> tuple[float, bool, bool]:
    dp_norm = dp_row["_name_norm"]
    bz_norm = bz_row["_name_norm"]
    dp_alias = dp_row["_alias"]
    bz_alias = bz_row["_alias"]
    dp_core = dp_row["_core"]
    bz_core = bz_row["_core"]
    exact_alias = bool(dp_alias and bz_alias and dp_alias == bz_alias)
    exact_core = bool(
        dp_core
        and bz_core
        and len(dp_core) >= 4
        and dp_core == bz_core
    )
    scores = [
        fuzz.ratio(dp_norm, bz_norm),
        fuzz.ratio(dp_alias, bz_alias),
        fuzz.ratio(dp_core, bz_core),
    ]
    if exact_alias:
        scores.append(100.0)
    if exact_core:
        scores.append(96.0)
    shorter, longer = sorted((dp_alias, bz_alias), key=len)
    shorter_core = core_alias(shorter)
    if (
        len(shorter) >= 4
        and shorter in longer
        and len(shorter_core) >= 2
        and shorter_core not in GENERIC_CORES
    ):
        scores.append(97.0 if len(shorter_core) >= 4 else 94.0)
    return float(max(scores)), exact_alias, exact_core


def evaluate_candidate(dp_row, bz_row):
    name_score, exact_alias, exact_core = compute_name_score(dp_row, bz_row)
    distance = haversine_scalar(
        dp_row["dp_lon_wgs"],
        dp_row["dp_lat_wgs"],
        bz_row["_bz_lon"],
        bz_row["_bz_lat"],
    )
    same_province = same_nonempty(dp_row["_province"], bz_row["_province"])
    same_city = same_nonempty(dp_row["_city"], bz_row["_city"])
    same_county = same_nonempty(dp_row["_county"], bz_row["_county"])
    conflict = specialty_conflict(dp_row["_specialties"], bz_row["_specialties"])
    has_distinctive_overlap = distinctive_overlap(
        dp_row["_alias"], bz_row["_alias"]
    )
    alias = dp_row["_alias"]
    generic_alias = alias in GENERIC_ALIASES or bz_row["_alias"] in GENERIC_ALIASES
    dp_ordinal = ordinal_value(dp_row["_name_norm"])
    bz_ordinal = ordinal_value(bz_row["_name_norm"])
    if dp_ordinal and bz_ordinal and dp_ordinal != bz_ordinal:
        return None
    if (
        dp_ordinal != bz_ordinal
        and "\u9644\u5c5e" in dp_row["_name_norm"]
        and "\u9644\u5c5e" in bz_row["_name_norm"]
    ):
        return None

    rule = ""
    if exact_alias and len(alias) >= 4 and same_city:
        if generic_alias:
            if same_county and pd.notna(distance) and distance <= 10:
                rule = "exact_alias_generic_same_county_10km"
        elif pd.notna(distance):
            alias_core_length = len(core_alias(alias))
            if same_county and distance <= 30:
                rule = "exact_aggressive_alias_same_county"
            elif distance <= 3:
                rule = "exact_aggressive_alias_same_city_3km"
            elif alias_core_length >= 4 and distance <= 20:
                rule = "exact_aggressive_alias_same_city_20km"
    if not rule and exact_core and same_city and not generic_alias:
        if pd.notna(distance) and distance <= 20:
            rule = "exact_core_alias_same_city"
    if not rule and generic_alias:
        return None
    if not rule and pd.notna(distance) and same_city and not conflict:
        if distance <= 0.3 and name_score >= 85 and has_distinctive_overlap:
            rule = "coord_300m_name85_distinctive"
        elif (
            distance <= 1
            and name_score >= 88
            and has_distinctive_overlap
            and (same_county or same_city)
        ):
            rule = "coord_1km_name88_distinctive"
        elif distance <= 3 and name_score >= 90 and has_distinctive_overlap:
            rule = "coord_3km_name90_distinctive"
        elif (
            distance <= 10
            and same_county
            and name_score >= 90
            and has_distinctive_overlap
        ):
            rule = "same_county_10km_name90_distinctive"
        elif distance <= 30 and same_county and name_score >= 93:
            rule = "same_county_30km_name93"
        elif distance <= 50 and name_score >= 97:
            if same_county or len(core_alias(dp_row["_alias"])) >= 4:
                rule = "same_city_50km_name97"
    if not rule:
        return None

    region_bonus = 12 if same_county else 7 if same_city else 3 if same_province else 0
    if pd.isna(distance):
        distance_bonus = 0
    elif distance <= 0.3:
        distance_bonus = 16
    elif distance <= 1:
        distance_bonus = 13
    elif distance <= 3:
        distance_bonus = 10
    elif distance <= 10:
        distance_bonus = 6
    elif distance <= 30:
        distance_bonus = 3
    else:
        distance_bonus = 0
    exact_bonus = 8 if exact_alias else 4 if exact_core else 0
    composite = min(100.0, 0.75 * name_score + region_bonus + distance_bonus + exact_bonus)
    return {
        "rule": rule,
        "name_score": round(name_score, 3),
        "distance_km": round(distance, 3) if pd.notna(distance) else math.nan,
        "composite_score": round(composite, 3),
    }


def prepare_dp(dp: pd.DataFrame) -> pd.DataFrame:
    out = dp.reset_index(drop=True).copy()
    out["_dp_uid"] = np.arange(len(out), dtype=np.int64)
    out["_province"] = out["dp_province19"].map(normalize_text)
    out["_city"] = out["dp_city19"].map(normalize_text)
    out["_county"] = out["dp_county19"].map(normalize_text)
    out["_name_norm"] = out[COL_NAME].map(normalize_name)
    out["_alias"] = [
        aggressive_alias(name, province, city, county)
        for name, province, city, county in zip(
            out[COL_NAME],
            out["dp_province19"],
            out["dp_city19"],
            out["dp_county19"],
        )
    ]
    out["_core"] = out["_alias"].map(core_alias)
    out["_specialties"] = out["_name_norm"].map(specialty_set)
    return out


def source_coord(frame: pd.DataFrame, primary: str, fallback: str) -> pd.Series:
    primary_values = pd.to_numeric(frame.get(primary), errors="coerce")
    fallback_values = pd.to_numeric(frame.get(fallback), errors="coerce")
    return primary_values.where(primary_values.notna(), fallback_values)


def bz_key(name, lon, province, city, county) -> tuple:
    lon_value = pd.to_numeric(pd.Series([lon]), errors="coerce").iloc[0]
    lon_round = round(float(lon_value), 6) if pd.notna(lon_value) else math.nan
    return (
        normalize_name(name),
        lon_round,
        normalize_text(province),
        normalize_text(city),
        normalize_text(county),
    )


def load_bz_candidates(year: int, bz_only: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    path = BZ_DIR / f"hospital_year_{year}.csv"
    source = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    source = source.loc[pd.to_numeric(source["year"], errors="coerce").eq(year)].copy()
    source["_bz_uid"] = np.arange(len(source), dtype=np.int64)
    source["_bz_lon"] = source_coord(source, "wgs_lon_true", "lon")
    source["_bz_lat"] = source_coord(source, "wgs_lat_true", "lat")
    source["_province_display"] = source.get("spatial_province").where(
        source.get("spatial_province").notna(), source.get("business_province")
    )
    source["_city_display"] = source.get("spatial_city").where(
        source.get("spatial_city").notna(), source.get("business_city")
    )
    source["_county_display"] = source.get("spatial_county").where(
        source.get("spatial_county").notna(), source.get("business_county")
    )
    source["_province"] = source["_province_display"].map(normalize_text)
    source["_city"] = source["_city_display"].map(normalize_text)
    source["_county"] = source["_county_display"].map(normalize_text)
    source["_name_norm"] = source["ENTNAME"].map(normalize_name)
    source["_alias"] = [
        aggressive_alias(name, province, city, county)
        for name, province, city, county in zip(
            source["ENTNAME"],
            source["_province_display"],
            source["_city_display"],
            source["_county_display"],
        )
    ]
    source["_core"] = source["_alias"].map(core_alias)
    source["_specialties"] = source["_name_norm"].map(specialty_set)
    source["_candidate_allowed"] = ~source["_name_norm"].map(
        lambda value: any(term in value for term in NON_HOSPITAL_CANDIDATE_TERMS)
    )
    source["_v1_bz_index"] = pd.NA

    key_to_bz_indices: dict[tuple, deque] = defaultdict(deque)
    for idx, row in bz_only.iterrows():
        key_to_bz_indices[
            bz_key(
                row[COL_NAME],
                row["bz_lon"],
                row["bz_spatial_province"],
                row["bz_spatial_city"],
                row["bz_spatial_county"],
            )
        ].append(idx)

    mapped = 0
    for idx, row in source.iterrows():
        key = bz_key(
            row["ENTNAME"],
            row["_bz_lon"],
            row["_province_display"],
            row["_city_display"],
            row["_county_display"],
        )
        queue = key_to_bz_indices.get(key)
        if queue:
            source.at[idx, "_v1_bz_index"] = queue.popleft()
            mapped += 1

    remaining = [
        compact_idx
        for queue in key_to_bz_indices.values()
        for compact_idx in queue
    ]
    source_by_name = {
        name: group.index.to_numpy()
        for name, group in source.groupby("_name_norm", sort=False)
        if name
    }
    used_source = set(
        source.loc[source["_v1_bz_index"].notna()].index.astype(int).tolist()
    )
    fallback_mapped = 0
    for compact_idx in remaining:
        row = bz_only.loc[compact_idx]
        name_norm = normalize_name(row[COL_NAME])
        candidates = source_by_name.get(name_norm, np.array([], dtype=int))
        candidates = [int(idx) for idx in candidates if int(idx) not in used_source]
        if not candidates:
            continue
        target_lon = pd.to_numeric(pd.Series([row["bz_lon"]]), errors="coerce").iloc[0]
        if pd.notna(target_lon):
            chosen = min(
                candidates,
                key=lambda idx: abs(float(source.at[idx, "_bz_lon"]) - float(target_lon))
                if pd.notna(source.at[idx, "_bz_lon"])
                else math.inf,
            )
        else:
            chosen = candidates[0]
        source.at[chosen, "_v1_bz_index"] = compact_idx
        used_source.add(chosen)
        fallback_mapped += 1

    stats = {
        "bz_source_rows": int(len(source)),
        "bz_only_rows": int(len(bz_only)),
        "bz_only_exact_source_mapping": int(mapped),
        "bz_only_fallback_source_mapping": int(fallback_mapped),
        "bz_only_unmapped": int(
            len(bz_only) - source["_v1_bz_index"].notna().sum()
        ),
        "bz_candidates_missing_coord": int(
            source[["_bz_lon", "_bz_lat"]].isna().any(axis=1).sum()
        ),
        "bz_candidates_disallowed_noise": int(
            (~source["_candidate_allowed"]).sum()
        ),
    }
    return source.reset_index(drop=True), stats


def candidate_maps(bz: pd.DataFrame):
    city_alias = defaultdict(list)
    county_alias = defaultdict(list)
    province_alias = defaultdict(list)
    city_blocks = defaultdict(dict)
    for row in bz.to_dict("records"):
        if not row["_candidate_allowed"]:
            continue
        uid = int(row["_bz_uid"])
        alias = row["_alias"]
        if not alias:
            continue
        if row["_province"] and row["_city"]:
            city_alias[(row["_province"], row["_city"], alias)].append(uid)
            city_blocks[(row["_province"], row["_city"])][uid] = alias
        if row["_province"] and row["_county"]:
            county_alias[(row["_province"], row["_county"], alias)].append(uid)
        if row["_province"]:
            province_alias[(row["_province"], alias)].append(uid)
    return city_alias, county_alias, province_alias, city_blocks


def choose_best(dp_row, bz: pd.DataFrame, candidate_uids) -> tuple[int, dict] | None:
    best = None
    for uid in dict.fromkeys(int(value) for value in candidate_uids):
        candidate = bz.iloc[uid]
        result = evaluate_candidate(dp_row, candidate)
        if result is None:
            continue
        distance_rank = (
            -result["distance_km"]
            if pd.notna(result["distance_km"])
            else -999999.0
        )
        rank = (
            result["composite_score"],
            result["name_score"],
            distance_rank,
            -uid,
        )
        if best is None or rank > best[0]:
            best = (rank, uid, result)
    if best is None:
        return None
    return best[1], best[2]


def run_second_round(dp: pd.DataFrame, bz: pd.DataFrame) -> pd.DataFrame:
    city_alias, county_alias, province_alias, city_blocks = candidate_maps(bz)
    matches: dict[int, tuple[int, dict]] = {}

    for row in dp.to_dict("records"):
        if not row["_alias"]:
            continue
        candidates = []
        candidates.extend(
            county_alias.get(
                (row["_province"], row["_county"], row["_alias"]), []
            )
        )
        candidates.extend(
            city_alias.get((row["_province"], row["_city"], row["_alias"]), [])
        )
        candidates.extend(
            province_alias.get((row["_province"], row["_alias"]), [])
        )
        if candidates:
            chosen = choose_best(row, bz, candidates)
            if chosen:
                matches[int(row["_dp_uid"])] = chosen
    print(f"  exact/alias stage: {len(matches):,}", flush=True)

    valid_bz = (
        bz[["_bz_lon", "_bz_lat"]].notna().all(axis=1)
        & bz["_candidate_allowed"]
    )
    valid_dp = dp[["dp_lon_wgs", "dp_lat_wgs"]].notna().all(axis=1)
    bz_valid = bz.loc[valid_bz].copy()
    if not bz_valid.empty:
        tree = cKDTree(to_xyz(bz_valid["_bz_lon"], bz_valid["_bz_lat"]))
        dp_candidates = dp.loc[valid_dp & ~dp["_dp_uid"].isin(matches)].copy()
        if not dp_candidates.empty:
            k = min(12, len(bz_valid))
            _, nearest_positions = tree.query(
                to_xyz(dp_candidates["dp_lon_wgs"], dp_candidates["dp_lat_wgs"]),
                k=k,
            )
            if k == 1:
                nearest_positions = nearest_positions.reshape(-1, 1)
            bz_uids = bz_valid["_bz_uid"].to_numpy(dtype=int)
            for row, positions in zip(
                dp_candidates.to_dict("records"), nearest_positions
            ):
                candidate_uids = bz_uids[np.asarray(positions, dtype=int)].tolist()
                chosen = choose_best(row, bz, candidate_uids)
                if chosen:
                    matches[int(row["_dp_uid"])] = chosen
    print(f"  coordinate stage cumulative: {len(matches):,}", flush=True)

    remaining = dp.loc[~dp["_dp_uid"].isin(matches)].copy()
    for block_key, group in remaining.groupby(["_province", "_city"], sort=False):
        choices = city_blocks.get(tuple(block_key))
        if not choices:
            continue
        alias_cache: dict[str, list[int]] = {}
        for alias in group["_alias"].dropna().unique():
            if not alias or len(alias) < 4:
                continue
            hits = process.extract(
                alias,
                choices,
                scorer=fuzz.WRatio,
                score_cutoff=72,
                limit=5,
            )
            alias_cache[alias] = [int(uid) for _, _, uid in hits]
        for row in group.to_dict("records"):
            candidate_uids = alias_cache.get(row["_alias"], [])
            if not candidate_uids:
                continue
            chosen = choose_best(row, bz, candidate_uids)
            if chosen:
                matches[int(row["_dp_uid"])] = chosen
    print(f"  fuzzy city stage cumulative: {len(matches):,}", flush=True)

    records = []
    for dp_uid, (bz_uid, result) in matches.items():
        records.append(
            {
                "_dp_uid": dp_uid,
                "_bz_uid": bz_uid,
                COL_RULE: result["rule"],
                COL_NAME_SCORE: result["name_score"],
                COL_DISTANCE: result["distance_km"],
                COL_COMPOSITE: result["composite_score"],
            }
        )
    return pd.DataFrame(records)


def build_new_both(
    dp: pd.DataFrame, bz: pd.DataFrame, matches: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if matches.empty:
        empty = pd.DataFrame(columns=BASE_COLUMNS + AUDIT_COLUMNS)
        return empty, pd.DataFrame()
    joined = (
        matches.merge(dp, on="_dp_uid", how="left", validate="one_to_one")
        .merge(
            bz[
                [
                    "_bz_uid",
                    "ENTNAME",
                    "public",
                    "_bz_lon",
                    "_bz_lat",
                    "_province_display",
                    "_city_display",
                    "_county_display",
                    "_v1_bz_index",
                ]
            ],
            on="_bz_uid",
            how="left",
            validate="many_to_one",
        )
    )
    out = joined[BASE_COLUMNS].copy()
    out[COL_NAME] = joined["ENTNAME"].where(
        joined["ENTNAME"].notna(), joined[COL_NAME]
    )
    out["bz_public"] = joined["public"]
    out["bz_lon"] = joined["_bz_lon"]
    out["bz_spatial_province"] = joined["_province_display"]
    out["bz_spatial_city"] = joined["_city_display"]
    out["bz_spatial_county"] = joined["_county_display"]
    out[COL_SOURCE] = "both"
    out[COL_STAGE] = "\u4e8c\u6b21\u5339\u914d"
    out[COL_RULE] = joined[COL_RULE]
    out[COL_NAME_SCORE] = joined[COL_NAME_SCORE]
    out[COL_DISTANCE] = joined[COL_DISTANCE]
    out[COL_COMPOSITE] = joined[COL_COMPOSITE]
    out[COL_VERSION] = RULE_VERSION

    detail = pd.DataFrame(
        {
            "year": joined["year"],
            "dp_\u533b\u9662\u540d\u79f0": joined[COL_NAME],
            "bz_\u533b\u9662\u540d\u79f0": joined["ENTNAME"],
            "dp_province19": joined["dp_province19"],
            "dp_city19": joined["dp_city19"],
            "dp_county19": joined["dp_county19"],
            "bz_spatial_province": joined["_province_display"],
            "bz_spatial_city": joined["_city_display"],
            "bz_spatial_county": joined["_county_display"],
            "dp_lon_wgs": joined["dp_lon_wgs"],
            "dp_lat_wgs": joined["dp_lat_wgs"],
            "bz_lon_wgs": joined["_bz_lon"],
            "bz_lat_wgs": joined["_bz_lat"],
            COL_RULE: joined[COL_RULE],
            COL_NAME_SCORE: joined[COL_NAME_SCORE],
            COL_DISTANCE: joined[COL_DISTANCE],
            COL_COMPOSITE: joined[COL_COMPOSITE],
            "bz_v1_status": np.where(
                joined["_v1_bz_index"].notna(),
                "previously_unmatched_bz",
                "already_matched_bz_reused",
            ),
            "_bz_uid": joined["_bz_uid"],
            "_v1_bz_index": joined["_v1_bz_index"],
            COL_VERSION: RULE_VERSION,
        }
    )
    multiplicity = detail.groupby("_bz_uid")["_bz_uid"].transform("size")
    detail["dp_rows_matched_to_same_bz"] = multiplicity
    return out, detail


def add_v1_audit(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out[COL_STAGE] = np.where(
        out[COL_SOURCE].eq("both"),
        "\u9996\u8f6e\u5339\u914d",
        "\u672a\u5339\u914d",
    )
    out[COL_RULE] = ""
    out[COL_NAME_SCORE] = np.nan
    out[COL_DISTANCE] = np.nan
    out[COL_COMPOSITE] = np.nan
    out[COL_VERSION] = np.where(
        out[COL_SOURCE].eq("both"),
        "v1_preserved",
        RULE_VERSION,
    )
    return out


def process_year(year: int):
    input_path = V1_DIR / str(year) / f"dp_bz_{year}.csv"
    data = pd.read_csv(input_path, encoding="utf-8-sig", low_memory=False)
    both = data.loc[data[COL_SOURCE].eq("both")].copy()
    dp_only_raw = data.loc[data[COL_SOURCE].eq("dp")].copy()
    bz_only = data.loc[data[COL_SOURCE].eq("bz")].copy()
    dp = prepare_dp(dp_only_raw)
    bz, mapping_stats = load_bz_candidates(year, bz_only)

    print(
        f"{year}: v1 both={len(both):,}, dp={len(dp):,}, bz={len(bz_only):,}",
        flush=True,
    )
    matches = run_second_round(dp, bz)
    new_both, detail = build_new_both(dp, bz, matches)

    matched_dp_uids = set(matches["_dp_uid"].astype(int)) if not matches.empty else set()
    remaining_dp = dp.loc[~dp["_dp_uid"].isin(matched_dp_uids), BASE_COLUMNS].copy()

    used_unmatched_bz_indices = set(
        detail.loc[
            detail["_v1_bz_index"].notna(), "_v1_bz_index"
        ].astype(int)
    ) if not detail.empty else set()
    remaining_bz = bz_only.loc[
        ~bz_only.index.isin(used_unmatched_bz_indices)
    ].copy()

    final = pd.concat(
        [
            add_v1_audit(both),
            new_both,
            add_v1_audit(remaining_dp),
            add_v1_audit(remaining_bz),
        ],
        ignore_index=True,
        sort=False,
    )
    final = final.reindex(columns=BASE_COLUMNS + AUDIT_COLUMNS)

    source_counts = final[COL_SOURCE].value_counts()
    second_unique_bz = int(detail["_bz_uid"].nunique()) if not detail.empty else 0
    many_to_one = (
        int((detail.groupby("_bz_uid").size() > 1).sum())
        if not detail.empty
        else 0
    )
    reused_first_matched_bz = (
        int(
            detail.loc[
                detail["bz_v1_status"].eq("already_matched_bz_reused"),
                "_bz_uid",
            ].nunique()
        )
        if not detail.empty
        else 0
    )
    summary = {
        "year": year,
        "v1_total_rows": int(len(data)),
        "v1_both_rows": int(len(both)),
        "v1_dp_only_rows": int(len(dp_only_raw)),
        "v1_bz_only_rows": int(len(bz_only)),
        "second_round_matched_dp_rows": int(len(matches)),
        "second_round_unique_bz_rows": second_unique_bz,
        "second_round_bz_previously_unmatched_used": int(
            len(used_unmatched_bz_indices)
        ),
        "second_round_already_matched_bz_reused": reused_first_matched_bz,
        "second_round_many_to_one_bz_rows": many_to_one,
        "second_round_dp_match_rate": (
            len(matches) / len(dp_only_raw) if len(dp_only_raw) else 0.0
        ),
        "final_total_rows": int(len(final)),
        "final_both_rows": int(source_counts.get("both", 0)),
        "final_dp_only_rows": int(source_counts.get("dp", 0)),
        "final_bz_only_rows": int(source_counts.get("bz", 0)),
        "final_dp_match_rate": (
            source_counts.get("both", 0)
            / (source_counts.get("both", 0) + source_counts.get("dp", 0))
            if source_counts.get("both", 0) + source_counts.get("dp", 0)
            else 0.0
        ),
        "row_balance_check": int(
            len(data) - len(used_unmatched_bz_indices) - len(final)
        ),
        **mapping_stats,
        "rule_version": RULE_VERSION,
    }

    year_dir = V2_DIR / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)
    final.to_csv(
        year_dir / f"dp_bz_{year}_v2.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame([summary]).to_csv(
        year_dir / f"dp_bz_{year}_v2_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    detail.drop(columns=["_bz_uid", "_v1_bz_index"], errors="ignore").to_csv(
        year_dir / f"dp_bz_{year}_second_round_matches_v2.csv",
        index=False,
        encoding="utf-8-sig",
    )
    print(
        f"  second matched={len(matches):,}, final both={summary['final_both_rows']:,}, "
        f"dp-only={summary['final_dp_only_rows']:,}, bz-only={summary['final_bz_only_rows']:,}",
        flush=True,
    )
    return final, detail, summary


def main() -> None:
    V2_DIR.mkdir(parents=True, exist_ok=True)
    all_final = []
    all_detail = []
    summaries = []
    for year in YEARS:
        final, detail, summary = process_year(year)
        all_final.append(final)
        if not detail.empty:
            all_detail.append(detail.drop(columns=["_bz_uid", "_v1_bz_index"], errors="ignore"))
        summaries.append(summary)

    combined = pd.concat(all_final, ignore_index=True, sort=False)
    detail_combined = (
        pd.concat(all_detail, ignore_index=True, sort=False)
        if all_detail
        else pd.DataFrame()
    )
    summary_df = pd.DataFrame(summaries)
    total = {
        "year": "ALL",
        "v1_total_rows": int(summary_df["v1_total_rows"].sum()),
        "v1_both_rows": int(summary_df["v1_both_rows"].sum()),
        "v1_dp_only_rows": int(summary_df["v1_dp_only_rows"].sum()),
        "v1_bz_only_rows": int(summary_df["v1_bz_only_rows"].sum()),
        "second_round_matched_dp_rows": int(
            summary_df["second_round_matched_dp_rows"].sum()
        ),
        "second_round_unique_bz_rows": int(
            summary_df["second_round_unique_bz_rows"].sum()
        ),
        "second_round_bz_previously_unmatched_used": int(
            summary_df["second_round_bz_previously_unmatched_used"].sum()
        ),
        "second_round_already_matched_bz_reused": int(
            summary_df["second_round_already_matched_bz_reused"].sum()
        ),
        "second_round_many_to_one_bz_rows": int(
            summary_df["second_round_many_to_one_bz_rows"].sum()
        ),
        "second_round_dp_match_rate": (
            summary_df["second_round_matched_dp_rows"].sum()
            / summary_df["v1_dp_only_rows"].sum()
        ),
        "final_total_rows": int(summary_df["final_total_rows"].sum()),
        "final_both_rows": int(summary_df["final_both_rows"].sum()),
        "final_dp_only_rows": int(summary_df["final_dp_only_rows"].sum()),
        "final_bz_only_rows": int(summary_df["final_bz_only_rows"].sum()),
        "final_dp_match_rate": (
            summary_df["final_both_rows"].sum()
            / (
                summary_df["final_both_rows"].sum()
                + summary_df["final_dp_only_rows"].sum()
            )
        ),
        "row_balance_check": int(summary_df["row_balance_check"].sum()),
        "bz_source_rows": int(summary_df["bz_source_rows"].sum()),
        "bz_only_rows": int(summary_df["bz_only_rows"].sum()),
        "bz_only_exact_source_mapping": int(
            summary_df["bz_only_exact_source_mapping"].sum()
        ),
        "bz_only_fallback_source_mapping": int(
            summary_df["bz_only_fallback_source_mapping"].sum()
        ),
        "bz_only_unmapped": int(summary_df["bz_only_unmapped"].sum()),
        "bz_candidates_missing_coord": int(
            summary_df["bz_candidates_missing_coord"].sum()
        ),
        "bz_candidates_disallowed_noise": int(
            summary_df["bz_candidates_disallowed_noise"].sum()
        ),
        "rule_version": RULE_VERSION,
    }
    summary_all = pd.concat(
        [summary_df, pd.DataFrame([total])],
        ignore_index=True,
        sort=False,
    )

    combined.to_csv(
        V2_DIR / "dp_bz_year_v2.csv",
        index=False,
        encoding="utf-8-sig",
    )
    detail_combined.to_csv(
        V2_DIR / "dp_bz_second_round_matches_v2.csv",
        index=False,
        encoding="utf-8-sig",
    )
    summary_all.to_csv(
        V2_DIR / "dp_bz_year_v2_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    readme = [
        "DP-BZ final merged hospital data v2.",
        f"Rule version: {RULE_VERSION}.",
        "V1 matches are preserved. Second-round matching is applied only to V1 DP-only rows.",
        "Candidate BZ rows include both previously unmatched BZ rows and BZ rows already used in V1.",
        "One DP row matches at most one BZ row; one BZ row may match multiple DP branches.",
        "Second-round evidence combines normalized/aggressive names, region consistency, coordinates, and specialty-conflict checks.",
        "Main output: dp_bz_year_v2.csv.",
        "Audit output: dp_bz_second_round_matches_v2.csv.",
        "Summary output: dp_bz_year_v2_summary.csv.",
    ]
    (V2_DIR / "README_dp_bz_v2.txt").write_text(
        "\n".join(readme),
        encoding="utf-8-sig",
    )
    print(summary_all.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
