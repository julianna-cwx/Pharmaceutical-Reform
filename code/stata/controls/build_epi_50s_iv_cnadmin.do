version 17.0
clear all
set more off

* Wrapper for the Python implementation. The cnadmin ado itself failed in this
* Windows/Stata setup because its embedded Python block was parsed with broken
* indentation, so the Python script reads cnadmin_data.maint directly and applies
* the same 1986-to-2019 tracing plus 1/N split weights.

global ROOT "D:\Hospital_Pharmacy program"
global DATA "$ROOT\data\processed\hospital_pharmacy\county_pharmacy_panel"
global OUT  "$ROOT\output\regression\controls"

capture mkdir "$OUT"

capture noisily python script "$ROOT\code\python\controls\build_epi_50s_iv_cnadmin.py"
if _rc {
    di as error "Stata's Python runner could not execute the IV builder."
    di as error "Run this from PowerShell instead:"
    di as error `"python "$ROOT\code\python\controls\build_epi_50s_iv_cnadmin.py""'
    exit _rc
}

capture confirm file "$DATA\epi_50s_iv_pac19_cnadmin.dta"
if _rc {
    di as error "Expected output not found: $DATA\epi_50s_iv_pac19_cnadmin.dta"
    exit 601
}

use "$DATA\epi_50s_iv_pac19_cnadmin.dta", clear
describe
summarize epi_cnt_1959 epi_yrs_50s epi_any_50s n_gb86_sources

di as result "Built IV file: $DATA\epi_50s_iv_pac19_cnadmin.dta"
di as result "Crosswalk diagnostics: $OUT\epi_50s_cnadmin_match_quality.csv"
