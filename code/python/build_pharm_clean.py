from __future__ import annotations

from pathlib import Path

import pandas as pd


BASE_DIR = Path(r"D:\Hospital_Pharmacy program")
INPUT_DIR = BASE_DIR / "data" / "pharmacy" / "pharm_final"
OUTPUT_DIR = BASE_DIR / "data" / "pharmacy" / "pharm_clean"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

YEARS = range(2012, 2020)
SCORE_COL = "pharmacy_realness_score_100"
DROP_COLS = [
    "is_real_prediction",
    "prediction_confidence",
    "prediction_label",
    "is_fake_pharmacy",
    "fake_reason",
]


def read_csv_auto(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            return pd.read_csv(path, encoding=encoding, low_memory=False)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Unable to read {path}")


def process_year(year: int) -> dict[str, object]:
    in_path = INPUT_DIR / f"renew_pharmacy_dzdp_pharmacies_{year}.csv"
    if not in_path.exists():
        raise FileNotFoundError(in_path)

    df = read_csv_auto(in_path)
    if SCORE_COL not in df.columns:
        raise KeyError(f"{SCORE_COL} not found in {in_path}")

    score = pd.to_numeric(df[SCORE_COL], errors="coerce")
    cleaned = df.loc[score.gt(50)].copy()
    cleaned["is_real_pharmacy"] = 1
    cleaned["realness_label"] = "真药店"
    cleaned = cleaned.drop(columns=[col for col in DROP_COLS if col in cleaned.columns])

    out_path = OUTPUT_DIR / in_path.name
    cleaned.to_csv(out_path, index=False, encoding="utf-8-sig")

    removed_rows = len(df) - len(cleaned)
    summary = {
        "year": year,
        "input_rows": len(df),
        "removed_score_le_50": removed_rows,
        "clean_rows": len(cleaned),
        "min_score_clean": pd.to_numeric(cleaned[SCORE_COL], errors="coerce").min() if len(cleaned) else pd.NA,
        "max_score_clean": pd.to_numeric(cleaned[SCORE_COL], errors="coerce").max() if len(cleaned) else pd.NA,
        "output_file": str(out_path),
    }
    print(
        f"{year}: input={len(df):,}, removed_score<=50={removed_rows:,}, "
        f"clean={len(cleaned):,}, saved={out_path}"
    )
    return summary


def main() -> None:
    summaries = [process_year(year) for year in YEARS]
    summary = pd.DataFrame(summaries)
    summary_path = OUTPUT_DIR / "pharm_clean_summary_2012_2019.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"saved summary: {summary_path}")


if __name__ == "__main__":
    main()
