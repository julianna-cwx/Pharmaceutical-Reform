# Integrated Regression Files

This folder now has three integrated do-files:

1. `01_hospital_all_regressions.do`
2. `02_county_all_regressions.do`
3. `03_pilot_county_short_window.do`

## 1. Hospital-Level Regressions

File: `01_hospital_all_regressions.do`

Input data:

- `hospital_with_pharmacy_counts_registered/hospital_pharmacy_2012_2022.dta`

Unit:

- Hospital-year, 2012-2022.

Key variables:

- Outcomes: `pharmacy_count_1km`, `pharmacy_count_2km`, `pharmacy_count_3km`.
- Transformations: `ln(count+1)`, `has_pharmacy`.
- Treatment timing: `policy_year`.
- Treatment group: public hospitals.
- Core treatment variable: `ddd = public hospital x post_policy`.

Empirical logic:

- The main specification follows a DDD-style design inspired by Chen, Wang, and Yue (2026).
- It compares public and non-public hospitals before and after the local reform year.
- Hospital fixed effects absorb time-invariant hospital differences.
- Province-year fixed effects absorb province-level shocks in each year.
- County-level clustered standard errors are used.

Models included:

- DDD main regressions.
- TWFE benchmark regressions.
- PPML count regressions.
- Chain vs non-chain split.
- DDD event-study diagnostics.
- CSDID robustness.

Output folder:

- `integrated_results/hospital`

## 2. County-Level Full-Sample Regressions

File: `02_county_all_regressions.do`

Input data:

- `county_pharmacy_panel/county_pharmacy_panel_all_years.dta`
- `county_panel_1020.dta`

Unit:

- County-year.

Main sample:

- 2012-2019 with population, nighttime-light, and road-density controls.
- A wider 2012-2020 no-road-control sample is also exported.

Key variables:

- Outcomes: `pharmacy_count`, annual change in `pharmacy_count`, `ln(count+1)`, `has_pharmacy`.
- Treatment timing: `policy_year`.
- Standard DID variable: `did = 1[year >= policy_year]`.
- DDD exposure variables:
  - `ddd_any = county has public hospital x post_policy`.
  - `ddd_share = county public-hospital share x post_policy`.

Empirical logic:

- The main county-level design uses staggered reform timing across counties.
- The DDD exposure regressions ask whether counties with stronger public-hospital exposure change differently after reform.
- Controls include population, nighttime lights, and road density.
- County fixed effects and year/province-year fixed effects are used depending on specification.

Models included:

- Standard staggered TWFE DID.
- Annual-change regressions.
- DDD exposure regressions.
- PPML count regressions.
- Chain vs non-chain split.
- TWFE event-study diagnostics.
- CSDID robustness.

Output folder:

- `integrated_results/county`

## 3. Pilot-County Short-Window Regressions

File: `03_pilot_county_short_window.do`

Input data:

- `county_pharmacy_panel/county_pharmacy_panel_all_years.dta`
- `county_panel_1020.dta`

Unit:

- County-year, 2012-2015.

Sample:

- Treated pilot cohorts: counties with `policy_year == 2012` or `policy_year == 2014`.
- Clean controls: counties with `policy_year > 2015`.

Important identification note:

- The data start in 2012, so the 2012 pilot cohort has no observed pre-treatment year.
- TWFE includes both 2012 and 2014 pilot cohorts.
- CSDID and pre-trend diagnostics focus on the 2014 cohort versus clean controls.

Models included:

- Short-window TWFE DID.
- PPML count regressions.
- TWFE event-study diagnostics.
- CSDID robustness for the identifiable 2014 pilot cohort.

Output folder:

- `integrated_results/pilot_county`

