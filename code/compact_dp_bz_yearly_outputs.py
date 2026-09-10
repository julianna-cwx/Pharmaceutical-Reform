from __future__ import annotations

from pathlib import Path
import shutil

import pandas as pd


OUT_DIR = Path(r"D:\Hospital_Pharmacy program\data\hospital\hosp_dp\diff_dp_bz")
YEARS = list(range(2012, 2020))

OUTPUT_COLUMNS = [
    "year",
    "医院名称",
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
    "合并后的数据来源",
]


def read_existing(path: Path, usecols: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=usecols)
    header = pd.read_csv(path, encoding="utf-8-sig", nrows=0).columns
    cols = [col for col in usecols if col in header]
    return pd.read_csv(path, encoding="utf-8-sig", usecols=cols, low_memory=False)


def first_nonempty(left: pd.Series, right: pd.Series) -> pd.Series:
    left_text = left.astype("string")
    right_text = right.astype("string")
    return left_text.where(left_text.notna() & left_text.ne(""), right_text)


def build_year(year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    year_dir = OUT_DIR / str(year)
    matched_cols = [
        "dp_year",
        "dp_name",
        "dp_province19",
        "dp_city19",
        "dp_county19",
        "dp_lon_wgs",
        "dp_lat_wgs",
        "bz_ENTNAME",
        "bz_year",
        "bz_public",
        "bz_lon",
        "bz_spatial_province",
        "bz_spatial_city",
        "bz_spatial_county",
    ]
    dp_cols = [
        "dp_year",
        "dp_name",
        "dp_province19",
        "dp_city19",
        "dp_county19",
        "dp_lon_wgs",
        "dp_lat_wgs",
    ]
    bz_cols = [
        "bz_year",
        "bz_ENTNAME",
        "bz_public",
        "bz_lon",
        "bz_spatial_province",
        "bz_spatial_city",
        "bz_spatial_county",
    ]

    matched = read_existing(year_dir / "matched_both.csv", matched_cols)
    dp_only = read_existing(year_dir / "only_dp_missing_hosp_year.csv", dp_cols)
    bz_only = read_existing(year_dir / "only_hosp_year_missing_dp.csv", bz_cols)

    frames = []
    if not matched.empty:
        out = pd.DataFrame()
        out["year"] = pd.to_numeric(matched.get("dp_year"), errors="coerce").fillna(year).astype("Int64")
        out["医院名称"] = first_nonempty(matched.get("bz_ENTNAME", pd.Series(index=matched.index, dtype="object")), matched.get("dp_name", pd.Series(index=matched.index, dtype="object")))
        out["bz_public"] = matched.get("bz_public")
        out["bz_lon"] = matched.get("bz_lon")
        out["bz_spatial_province"] = matched.get("bz_spatial_province")
        out["bz_spatial_city"] = matched.get("bz_spatial_city")
        out["bz_spatial_county"] = matched.get("bz_spatial_county")
        out["dp_province19"] = matched.get("dp_province19")
        out["dp_city19"] = matched.get("dp_city19")
        out["dp_county19"] = matched.get("dp_county19")
        out["dp_lon_wgs"] = matched.get("dp_lon_wgs")
        out["dp_lat_wgs"] = matched.get("dp_lat_wgs")
        out["合并后的数据来源"] = "both"
        frames.append(out)

    if not dp_only.empty:
        out = pd.DataFrame()
        out["year"] = pd.to_numeric(dp_only.get("dp_year"), errors="coerce").fillna(year).astype("Int64")
        out["医院名称"] = dp_only.get("dp_name")
        out["bz_public"] = pd.NA
        out["bz_lon"] = pd.NA
        out["bz_spatial_province"] = pd.NA
        out["bz_spatial_city"] = pd.NA
        out["bz_spatial_county"] = pd.NA
        out["dp_province19"] = dp_only.get("dp_province19")
        out["dp_city19"] = dp_only.get("dp_city19")
        out["dp_county19"] = dp_only.get("dp_county19")
        out["dp_lon_wgs"] = dp_only.get("dp_lon_wgs")
        out["dp_lat_wgs"] = dp_only.get("dp_lat_wgs")
        out["合并后的数据来源"] = "dp"
        frames.append(out)

    if not bz_only.empty:
        out = pd.DataFrame()
        out["year"] = pd.to_numeric(bz_only.get("bz_year"), errors="coerce").fillna(year).astype("Int64")
        out["医院名称"] = bz_only.get("bz_ENTNAME")
        out["bz_public"] = bz_only.get("bz_public")
        out["bz_lon"] = bz_only.get("bz_lon")
        out["bz_spatial_province"] = bz_only.get("bz_spatial_province")
        out["bz_spatial_city"] = bz_only.get("bz_spatial_city")
        out["bz_spatial_county"] = bz_only.get("bz_spatial_county")
        out["dp_province19"] = pd.NA
        out["dp_city19"] = pd.NA
        out["dp_county19"] = pd.NA
        out["dp_lon_wgs"] = pd.NA
        out["dp_lat_wgs"] = pd.NA
        out["合并后的数据来源"] = "bz"
        frames.append(out)

    compact = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
    compact = compact.reindex(columns=OUTPUT_COLUMNS)
    summary = compact.groupby("合并后的数据来源", dropna=False).size().reset_index(name="rows")
    summary.insert(0, "year", year)
    return compact, summary


def remove_redundant_files() -> None:
    keep_top = {
        "dp_bz_year.csv",
        "dp_bz_year_summary.csv",
        "README_dp_bz_year.txt",
    }
    for child in OUT_DIR.iterdir():
        if child.is_file() and child.name not in keep_top:
            child.unlink()
        elif child.is_dir() and child.name.isdigit():
            year = child.name
            keep_year = {
                f"dp_bz_{year}.csv",
                f"dp_bz_{year}_summary.csv",
            }
            for item in child.iterdir():
                if item.is_file() and item.name not in keep_year:
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)


def main() -> None:
    all_frames = []
    summaries = []
    for year in YEARS:
        year_dir = OUT_DIR / str(year)
        if not year_dir.exists():
            raise FileNotFoundError(f"Missing year directory: {year_dir}")
        compact, summary = build_year(year)
        compact.to_csv(year_dir / f"dp_bz_{year}.csv", index=False, encoding="utf-8-sig")
        summary.to_csv(year_dir / f"dp_bz_{year}_summary.csv", index=False, encoding="utf-8-sig")
        all_frames.append(compact)
        summaries.append(summary)
        print(year, len(compact), summary.to_dict("records"), flush=True)

    all_data = pd.concat(all_frames, ignore_index=True, sort=False)
    all_summary = pd.concat(summaries, ignore_index=True, sort=False)
    total_summary = all_data.groupby("合并后的数据来源", dropna=False).size().reset_index(name="rows")
    total_summary.insert(0, "year", "ALL")
    all_summary = pd.concat([all_summary, total_summary], ignore_index=True, sort=False)

    all_data.to_csv(OUT_DIR / "dp_bz_year.csv", index=False, encoding="utf-8-sig")
    all_summary.to_csv(OUT_DIR / "dp_bz_year_summary.csv", index=False, encoding="utf-8-sig")

    readme = [
        "Simplified DP-BZ yearly merged hospital output.",
        "Columns: year, hospital name, selected BZ fields, selected DP fields, merged source.",
        "Source values: both = matched in DP and BZ; dp = only in DP; bz = only in BZ.",
        "Each yearly folder uses its actual year in the file names.",
        "Top-level dp_bz_year.csv combines all years.",
    ]
    (OUT_DIR / "README_dp_bz_year.txt").write_text("\n".join(readme), encoding="utf-8-sig")
    remove_redundant_files()
    print("Wrote", OUT_DIR / "dp_bz_year.csv", len(all_data), flush=True)
    print(all_summary.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
