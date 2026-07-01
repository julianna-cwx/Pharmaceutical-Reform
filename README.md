# Pharmaceutical Reform

This repository contains code and paper artifacts for the hospital-pharmacy reform project.

## Project Structure

```text
Hospital_Pharmacy/
├── code/
│   ├── stata/      # Stata regression and control-variable scripts
│   └── python/     # Python notebooks/scripts for matching, distance, and data construction
├── data/
│   ├── raw/        # Local raw data, ignored by Git
│   └── processed/  # Local processed data, ignored by Git
├── paper/          # Manuscript and slides
├── figures/        # Exported figures for the paper/results
├── tables/         # Exported regression tables
├── output/         # Logs and intermediate outputs, ignored by Git
├── README.md
└── .gitignore
```

## Main Workflow

1. Build hospital-pharmacy panels with `code/python/hospital_pharmacy/coordinates_distance_v2.ipynb`.
2. Add 500m pharmacy counts with `code/python/hospital_pharmacy/build_registered_500m_counts.py`.
3. Build county-level epidemiology-station IV controls with `code/stata/controls/build_epi_50s_iv_cnadmin.do`.
4. Run hospital-level regressions with `code/stata/hospital/01_hospital_all_regressions_v3.do`.
5. Run county-level regressions with `code/stata/county/02_county_all_regressions_v2.do`.
6. Run AOI hospital-boundary regressions with `code/stata/hospital_aoi/hospital_aoi_regressions.do`.

## Data Policy

Large raw and processed data files are intentionally excluded from GitHub. Keep them locally under `data/raw/` and `data/processed/`.

Unused or historical files were moved outside the repository to `D:\nouse`.
