*===============================================================================
* 02_county_all_regressions.do
*
* County-level staggered DID regressions
*不去除policy_year=2012的
*以政策年份的后一年为有效政策时点

* This file follows the CS_v5.do style:
*   Part 0. Check required Stata packages.
*   Part 1. Prepare county-level controls.
*   Part 2. Merge pharmacy panel with controls and create variables.
*   Part 3. Descriptive statistics and sample diagnostics.
*   Part 4. Staggered TWFE DID.
*   Part 4A. Annual changes in pharmacy outcomes.
*   Part 4B. Distance from pharmacies to the nearest hospital.
*   Part 4C. Continuous DID by public-hospital intensity.
*   Part 5. PPML count regressions.
*   Part 6. Chain vs non-chain outcomes.
*   Part 7. TWFE event-study diagnostics.
*   Part 8. CSDID robustness.
*   Part 9. Five-estimator event-study robustness.
*
*===============================================================================

clear all
set more off
set linesize 255

global ROOT "D:\Hospital_Pharmacy program"
global DATA "$ROOT\data\processed\hospital_pharmacy\county_pharmacy_panel"
global OUTROOT "$ROOT\output\regression"
global OUT "$OUTROOT\county_v2"

capture mkdir "$OUTROOT"
capture mkdir "$OUT"

cap log close
log using "$OUT\02_county_all_regressions.log", replace text

*-------------------------------------------------------------------------------
* Part 0. Required user-written commands
*-------------------------------------------------------------------------------

* These packages are used for high-dimensional FE regressions, table export,
* coefficient plots, staggered DID, and PPML. If one is missing, the do-file
* stops immediately so the error is easy to locate.
foreach cmd in reghdfe ivreghdfe ivreg2 ranktest esttab eststo estpost ///
    coefplot csdid ppmlhdfe eventstudyinteract event_plot stackedev ///
    did_imputation {
    capture which `cmd'
    if _rc {
        di as error "`cmd' is required. Install it before running this file."
        if "`cmd'" == "did_imputation" {
            di as error "Install Borusyak-Jaravel-Spiess with: ssc install did_imputation, replace"
        }
        exit 111
    }
}

*-------------------------------------------------------------------------------
* Part 1. Prepare county-level controls
*-------------------------------------------------------------------------------

tempfile controls

* county_panel_1020.dta contains population, nighttime lights, and roads.
* Its county code is pac19; we rename/round it into county_id for merging.
use "$ROOT\data\processed\controls\county_panel_1020.dta", clear
gen long county_id = round(pac19)
replace year = round(year)

keep county_id year province city county ///
    pop pop_hukou pop_urban ///
    nl_mean nl_sum ln_nl_mean ln_nl_sum ///
    road_den road_den_intracity road_den_national ///
    county_area county_area_sqm

drop if missing(county_id) | missing(year)
duplicates drop county_id year, force
isid county_id year
save `controls', replace

*-------------------------------------------------------------------------------
* Part 2. Merge pharmacy panel with controls and create variables
*-------------------------------------------------------------------------------

use "$DATA\county_pharmacy_panel_all_years.dta", clear
isid county_id year

* Optional distance outcomes created by coordinates_distance_v2.ipynb.
* If the main county panel has not yet been regenerated, merge the standalone
* distance panel so this do-file can still run after the new notebook cell.
capture confirm variable mean_nearest_hospital_km
if _rc {
    capture confirm file "$DATA\county_pharmacy_nearest_hospital_distance_all_years.dta"
    if !_rc {
        merge 1:1 county_id year using ///
            "$DATA\county_pharmacy_nearest_hospital_distance_all_years.dta", ///
            keep(master match) gen(merge_distance)

        preserve
            contract year merge_distance
            sort year merge_distance
            export delimited using "$OUT\merge_distance_by_year.csv", replace
        restore
    }
}

merge 1:1 county_id year using `controls', keep(master match) gen(merge_controls)

* Export merge diagnostics: this shows which years have matched controls.
preserve
    contract year merge_controls
    sort year merge_controls
    export delimited using "$OUT\merge_controls_by_year.csv", replace
restore

* Merge cnadmin-crosswalked 1950s epidemiology-station IVs.
capture confirm file "$DATA\epi_50s_iv_pac19_cnadmin.dta"
if _rc {
    di as error "Required IV file not found: $DATA\epi_50s_iv_pac19_cnadmin.dta"
    di as error "Run dofile\build_epi_50s_iv_cnadmin.py before this regression file."
    exit 111
}
merge m:1 county_id using "$DATA\epi_50s_iv_pac19_cnadmin.dta", ///
    keep(master match) keepusing(epi_fnd_50s epi_cnt_1959 epi_yrs_50s ///
        epi_any_50s ln_epi_cnt_1959_1p ln_epi_yrs_50s_1p ///
        n_gb86_sources epi_iv_crosswalk_method) gen(merge_epi_50s_iv)

preserve
    contract year merge_epi_50s_iv
    sort year merge_epi_50s_iv
    export delimited using "$OUT\merge_epi_50s_iv_cnadmin_by_year.csv", replace
restore

replace policy_year = round(policy_year)
replace year = round(year)
 //不去除政策年份为2012年的区县


gen long prov_id = floor(county_id / 10000)
gen long city_id = floor(county_id / 100)
gen int t = year - 2011

capture confirm variable public_hospital_count
if _rc {
    capture confirm variable hospital_公立
    if !_rc {
        gen public_hospital_count = hospital_公立
    }
    else {
        di as error "Public hospital count variable is required but was not found."
        exit 111
    }
}

* 2.1 Standard staggered DID variables.
* Version v2 treats the reform as becoming effective in the year after policy_year.
* Thus counties with policy_year == 2012 enter as effective-policy-year 2013 cohorts.
gen int effective_policy_year = policy_year + 1 if !missing(policy_year)
gen byte post_policy = (year >= effective_policy_year) ///
    if !missing(year, effective_policy_year)
gen byte did = post_policy

gen rel = year - effective_policy_year


* 2.2 Outcomes.
* pharmacy_count: county pharmacy stock/count.
* ln_pharmacy: log count. Zero-count counties are set to missing.
* ln_pharmacy_plus1: inverse-hyperbolic-style robustness that keeps zero-count
* counties in the log specification by using ln(count + 1).
* has_pharmacy: extensive margin.
gen ln_pharmacy = ln(pharmacy_count)
gen ln_pharmacy_plus1 = ln(pharmacy_count + 1)
gen has_pharmacy = (pharmacy_count > 0) if !missing(pharmacy_count)

sort county_id year
by county_id: gen d_pharmacy_count = pharmacy_count - pharmacy_count[_n-1] ///
    if year == year[_n-1] + 1
by county_id: gen d_ln_pharmacy = ln_pharmacy - ln_pharmacy[_n-1] ///
    if year == year[_n-1] + 1 & !missing(ln_pharmacy, ln_pharmacy[_n-1])

gen nonchain_pharmacy_count = pharmacy_count - chain_pharmacy_count
replace nonchain_pharmacy_count = . if nonchain_pharmacy_count < 0

capture confirm variable pharmacy_within_2km
if !_rc {
    replace pharmacy_within_2km = 0 if missing(pharmacy_within_2km)
    replace pharmacy_over_2km = 0 if missing(pharmacy_over_2km)
    capture confirm variable share_pharmacy_within_2km
    if _rc {
        gen share_pharmacy_within_2km = ///
            pharmacy_within_2km / (pharmacy_within_2km + pharmacy_over_2km)
    }
    replace share_pharmacy_within_2km = . ///
        if pharmacy_within_2km + pharmacy_over_2km == 0
}

capture confirm variable pharmacy_2km_public_hosp
if !_rc {
    replace pharmacy_2km_public_hosp = 0 ///
        if missing(pharmacy_2km_public_hosp)
    capture confirm variable share_2km_public_hosp
    if _rc {
        gen share_2km_public_hosp = ///
            pharmacy_2km_public_hosp / pharmacy_count
    }
    replace share_2km_public_hosp = . ///
        if pharmacy_count == 0
}

capture confirm variable pharmacy_2km_private_hosp
if !_rc {
    replace pharmacy_2km_private_hosp = 0 ///
        if missing(pharmacy_2km_private_hosp)
    capture confirm variable share_2km_private_hosp
    if _rc {
        gen share_2km_private_hosp = ///
            pharmacy_2km_private_hosp / pharmacy_count
    }
    replace share_2km_private_hosp = . ///
        if pharmacy_count == 0
}

* 2.3 Controls.
* Main controls: population, nighttime lights, and road density.
gen ln_pop = ln(pop + 1)
gen ln_road_den = ln(road_den + 1)

sort county_id year
by county_id: egen public_hospital_2012 = ///
    max(cond(year == 2012, public_hospital_count, .))
by county_id: gen public_hospital_base = public_hospital_2012
by county_id: replace public_hospital_base = public_hospital_count[1] ///
    if missing(public_hospital_base)
gen ln_public_hospital_base = ln(public_hospital_base + 1)
gen did_ln_public_hospital = post_policy * ln_public_hospital_base
gen double z_epi_cnt_1959 = post_policy * epi_cnt_1959
gen double z_epi_yrs_50s = post_policy * epi_yrs_50s

label variable epi_cnt_1959 "Epidemiology stations in 1959, 1986-to-2019 crosswalk"
label variable epi_yrs_50s "1950s epidemiology station-years, 1986-to-2019 crosswalk"
label variable z_epi_cnt_1959 "Post x epidemiology stations in 1959"
label variable z_epi_yrs_50s "Post x 1950s epidemiology station-years"


global ctrl_road "ln_pop ln_nl_mean ln_road_den"
global ctrl_noroad "ln_pop ln_nl_mean"

* Road density is mostly usable through 2019, so sample_road ends in 2019.
* Keep 2012 policy-year cohorts; with one-year delay they first become treated in 2013.
gen byte sample_road = ///
    inrange(year, 2012, 2019) & ///
    effective_policy_year >= 2013 & ///
    !missing(county_id, year, effective_policy_year, pharmacy_count, ///
        ln_pop, ln_nl_mean, ln_road_den)

gen byte sample_noroad = ///
    inrange(year, 2012, 2020) & ///
    effective_policy_year >= 2013 & ///
    !missing(county_id, year, effective_policy_year, pharmacy_count, ///
        ln_pop, ln_nl_mean)
gen byte sample_contdid = ///
    sample_road & !missing(post_policy, ln_public_hospital_base, ///
        did_ln_public_hospital)
gen byte sample_contdid_iv = sample_contdid & ///
    !missing(epi_cnt_1959, epi_yrs_50s, z_epi_cnt_1959, z_epi_yrs_50s)

gen byte sample_change = sample_road & !missing(d_pharmacy_count)
gen byte sample_change_ln = sample_road & !missing(d_ln_pharmacy)

* Robustness samples used to diagnose whether pre-trends are driven by limited
* support in early/late cohorts or by unbalanced county histories.
bysort county_id: egen n_sample_road = total(sample_road)
gen byte sample_balanced = sample_road & n_sample_road == 8
gen byte sample_midcohort = sample_road & ///
    inrange(effective_policy_year, 2015, 2017)

gen byte sample_dist_mean = sample_road
capture confirm variable mean_nearest_hospital_km
if !_rc {
    replace sample_dist_mean = sample_road & !missing(mean_nearest_hospital_km)
}

gen byte sample_dist_bins = sample_road
capture confirm variable pharmacy_within_2km
if !_rc {
    replace sample_dist_bins = sample_road & ///
        !missing(pharmacy_within_2km, pharmacy_over_2km)
}

gen byte sample_dist_public = sample_road
capture confirm variable mean_nearest_public_hosp_km
if !_rc {
    replace sample_dist_public = sample_road & ///
        !missing(mean_nearest_public_hosp_km, ///
            pharmacy_2km_public_hosp)
}

gen byte sample_dist_private = sample_road
capture confirm variable mean_nearest_private_hosp_km
if !_rc {
    replace sample_dist_private = sample_road & ///
        !missing(mean_nearest_private_hosp_km, ///
            pharmacy_2km_private_hosp)
}

xtset county_id year

*-------------------------------------------------------------------------------
* Part 3. Descriptive statistics and sample diagnostics
*-------------------------------------------------------------------------------

* Raw cohort-level pre-trends. These are descriptive diagnostics analogous to
* the event-study checks below, and help identify whether significant leads are
* coming from particular treatment cohorts.
preserve
    keep if sample_road
    collapse (mean) pharmacy_count ln_pharmacy_plus1 ///
             (count) counties=county_id, by(effective_policy_year year)
    export delimited using "$OUT\raw_pretrend_by_cohort_county.csv", replace

    twoway ///
        (line pharmacy_count year if effective_policy_year == 2015, ///
            lcolor(navy) lwidth(medthick)) ///
        (line pharmacy_count year if effective_policy_year == 2016, ///
            lcolor(maroon) lwidth(medthick)) ///
        (line pharmacy_count year if effective_policy_year == 2017, ///
            lcolor(forest_green) lwidth(medthick)) ///
        (line pharmacy_count year if effective_policy_year == 2018, ///
            lcolor(orange) lwidth(medthick)), ///
        legend(order(1 "2015 cohort" 2 "2016 cohort" ///
                     3 "2017 cohort" 4 "2018 cohort") rows(1)) ///
        title("Raw pre-trends by treatment cohort: pharmacy count") ///
        xtitle("Year") ytitle("Mean pharmacy count") ///
        graphregion(color(white)) plotregion(color(white)) bgcolor(white)
    graph export "$OUT\raw_pretrend_by_cohort_count.png", replace width(2400)

    twoway ///
        (line ln_pharmacy_plus1 year if effective_policy_year == 2015, ///
            lcolor(navy) lwidth(medthick)) ///
        (line ln_pharmacy_plus1 year if effective_policy_year == 2016, ///
            lcolor(maroon) lwidth(medthick)) ///
        (line ln_pharmacy_plus1 year if effective_policy_year == 2017, ///
            lcolor(forest_green) lwidth(medthick)) ///
        (line ln_pharmacy_plus1 year if effective_policy_year == 2018, ///
            lcolor(orange) lwidth(medthick)), ///
        legend(order(1 "2015 cohort" 2 "2016 cohort" ///
                     3 "2017 cohort" 4 "2018 cohort") rows(1)) ///
        title("Raw pre-trends by treatment cohort: ln(count + 1)") ///
        xtitle("Year") ytitle("Mean ln(pharmacy count + 1)") ///
        graphregion(color(white)) plotregion(color(white)) bgcolor(white)
    graph export "$OUT\raw_pretrend_by_cohort_ln_plus1.png", replace width(2400)
restore

eststo clear
estpost summarize pharmacy_count ln_pharmacy ln_pharmacy_plus1 has_pharmacy ///
    d_pharmacy_count d_ln_pharmacy ///
    chain_pharmacy_count nonchain_pharmacy_count ///
    did ln_pop ln_nl_mean ln_road_den ///
    sample_balanced sample_midcohort if sample_road, detail
esttab using "$OUT\desc_county.rtf", replace ///
    cells("count mean sd min p25 p50 p75 max") ///
    noobs nomtitle nonumber ///
    title("County-level descriptive statistics")

*-------------------------------------------------------------------------------
* Part 4. Staggered TWFE DID: county reform timing
*-------------------------------------------------------------------------------

* Main county model:
*   outcome_ct = beta * did_ct + controls_ct + county FE + year FE.
*
* Interpretation:
*   county pharmacy supply after reform relative to before reform, using
*   staggered reform timing across counties.
eststo clear
eststo c1: reghdfe pharmacy_count did if sample_road, ///
    absorb(county_id year) cluster(county_id)
eststo c2: reghdfe pharmacy_count did $ctrl_road if sample_road, ///
    absorb(county_id year) cluster(county_id)

esttab c1 c2 using "$OUT\twfe_count_county.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(did ln_pop ln_nl_mean ln_road_den) ///
    mtitles("FE" "+ controls" "2012-2020 no road") ///
    title("County staggered TWFE DID: pharmacy count")

* Robustness checks motivated by the significant event-study leads:
*   (i) exclude very early/late cohorts,
*   (ii) use a balanced 2012-2019 panel,
*   (iii) absorb province-by-year shocks.
eststo clear
eststo rb_c_mid: reghdfe pharmacy_count did $ctrl_road ///
    if sample_midcohort, absorb(county_id year) cluster(county_id)
eststo rb_l_mid: reghdfe ln_pharmacy_plus1 did $ctrl_road ///
    if sample_midcohort, absorb(county_id year) cluster(county_id)
eststo rb_c_bal: reghdfe pharmacy_count did $ctrl_road ///
    if sample_balanced, absorb(county_id year) cluster(county_id)
eststo rb_l_bal: reghdfe ln_pharmacy_plus1 did $ctrl_road ///
    if sample_balanced, absorb(county_id year) cluster(county_id)
eststo rb_c_py: reghdfe pharmacy_count did $ctrl_road ///
    if sample_road, absorb(county_id prov_id#year) cluster(county_id)
eststo rb_l_py: reghdfe ln_pharmacy_plus1 did $ctrl_road ///
    if sample_road, absorb(county_id prov_id#year) cluster(county_id)

esttab rb_c_mid rb_l_mid rb_c_bal rb_l_bal rb_c_py rb_l_py ///
    using "$OUT\twfe_pretrend_robustness_county.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(did ln_pop ln_nl_mean ln_road_den) ///
    mtitles("count mid" "ln+1 mid" "count balanced" "ln+1 balanced" ///
            "count prov-year" "ln+1 prov-year") ///
    title("County TWFE robustness for pre-trend diagnostics")

* Alternative outcomes: log count and extensive margin.
eststo clear
eststo lp1: reghdfe ln_pharmacy_plus1 did $ctrl_road if sample_road, ///
    absorb(county_id year) cluster(county_id)
eststo l1: reghdfe ln_pharmacy did $ctrl_road if sample_road, ///
    absorb(county_id year) cluster(county_id)
eststo h1: reghdfe has_pharmacy did $ctrl_road if sample_road, ///
    absorb(county_id year) cluster(county_id)

esttab lp1 l1 h1 using "$OUT\twfe_ln_has_county.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(did ln_pop ln_nl_mean ln_road_den) ///
    mtitles("ln(count+1) FE" "ln count FE" "has pharmacy FE") ///
    title("County staggered TWFE DID: log and extensive margin")

*-------------------------------------------------------------------------------
* Part 4A. Annual changes in pharmacy outcomes
*-------------------------------------------------------------------------------

eststo clear
eststo dc1: reghdfe d_pharmacy_count did $ctrl_road if sample_change, ///
    absorb(county_id year) cluster(county_id)
eststo dl1: reghdfe d_ln_pharmacy did $ctrl_road if sample_change_ln, ///
    absorb(county_id year) cluster(county_id)

esttab dc1 dl1 using "$OUT\twfe_change_county.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(did ln_pop ln_nl_mean ln_road_den) ///
    mtitles("d count FE" "d ln count FE") ///
    title("County staggered TWFE DID: annual pharmacy changes")

*-------------------------------------------------------------------------------
* Part 4B. Distance from pharmacies to the nearest hospital
*-------------------------------------------------------------------------------

* These outcomes test whether pharmacies move closer to or farther from hospitals
* after reform. Distances are pharmacy-level nearest-hospital distances averaged
* to the county-year level; 2km bins mirror the common near/far split.
capture confirm variable mean_nearest_hospital_km
if !_rc {
    eststo clear
    eststo md1: reghdfe mean_nearest_hospital_km did $ctrl_road ///
        if sample_dist_mean, absorb(county_id year) cluster(county_id)

    esttab md1 using "$OUT\twfe_nearest_hospital_distance_county.rtf", replace ///
        se b(%9.3fc) r2 scalars(N) nocons ///
        keep(did ln_pop ln_nl_mean ln_road_den) ///
        mtitles("mean km FE") ///
        title("County TWFE DID: pharmacy distance to nearest hospital")
}

capture confirm variable pharmacy_within_2km
if !_rc {
    eststo clear
    eststo n1: reghdfe pharmacy_within_2km did $ctrl_road ///
        if sample_dist_bins, absorb(county_id year) cluster(county_id)
    eststo f1: reghdfe pharmacy_over_2km did $ctrl_road ///
        if sample_dist_bins, absorb(county_id year) cluster(county_id)

    esttab n1 f1 using "$OUT\twfe_distance_bins_county.rtf", replace ///
        se b(%9.3fc) r2 scalars(N) nocons ///
        keep(did ln_pop ln_nl_mean ln_road_den) ///
        mtitles("<=2km count FE" ">2km count FE") ///
        title("County TWFE DID: pharmacy count by distance to nearest hospital")

    eststo clear
    eststo s1: reghdfe share_pharmacy_within_2km did $ctrl_road ///
        if sample_dist_bins, absorb(county_id year) cluster(county_id)

    esttab s1 using "$OUT\twfe_share_within_2km_county.rtf", replace ///
        se b(%9.3fc) r2 scalars(N) nocons ///
        keep(did ln_pop ln_nl_mean ln_road_den) ///
        mtitles("share FE") ///
        title("County TWFE DID: share of pharmacies within 2km of nearest hospital")
}

capture confirm variable mean_nearest_public_hosp_km mean_nearest_private_hosp_km
if !_rc {
    eststo clear
    eststo pd1: reghdfe mean_nearest_public_hosp_km did $ctrl_road ///
        if sample_dist_public, absorb(county_id year) cluster(county_id)
    eststo vd1: reghdfe mean_nearest_private_hosp_km did $ctrl_road ///
        if sample_dist_private, absorb(county_id year) cluster(county_id)

    esttab pd1 vd1 using "$OUT\twfe_public_private_hospital_distance_county.rtf", replace ///
        se b(%9.3fc) r2 scalars(N) nocons ///
        keep(did ln_pop ln_nl_mean ln_road_den) ///
        mtitles("public km FE" "private km FE") ///
        title("County TWFE DID: pharmacy distance to nearest public/private hospital")
}

capture confirm variable pharmacy_2km_public_hosp pharmacy_2km_private_hosp ///
    share_2km_public_hosp share_2km_private_hosp
if !_rc {
    eststo clear
    eststo pc1: reghdfe pharmacy_2km_public_hosp did $ctrl_road ///
        if sample_dist_public, absorb(county_id year) cluster(county_id)
    eststo vc1: reghdfe pharmacy_2km_private_hosp did $ctrl_road ///
        if sample_dist_private, absorb(county_id year) cluster(county_id)

    esttab pc1 vc1 using "$OUT\twfe_public_private_2km_county.rtf", replace ///
        se b(%9.3fc) r2 scalars(N) nocons ///
        keep(did ln_pop ln_nl_mean ln_road_den) ///
        mtitles("public <=2km FE" "private <=2km FE") ///
        title("County TWFE DID: pharmacies within 2km of public/private hospitals")

    eststo clear
    eststo ps1: reghdfe share_2km_public_hosp did $ctrl_road ///
        if sample_dist_public, absorb(county_id year) cluster(county_id)
    eststo vs1: reghdfe share_2km_private_hosp did $ctrl_road ///
        if sample_dist_private, absorb(county_id year) cluster(county_id)

    esttab ps1 vs1 using "$OUT\twfe_public_private_2km_share_county.rtf", replace ///
        se b(%9.3fc) r2 scalars(N) nocons ///
        keep(did ln_pop ln_nl_mean ln_road_den) ///
        mtitles("public share FE" "private share FE") ///
        title("County TWFE DID: share of pharmacies within 2km of public/private hospitals")
}

*-------------------------------------------------------------------------------
* Part 4C. Continuous DID by public-hospital intensity
*-------------------------------------------------------------------------------

* Treatment intensity is the county's baseline public-hospital stock:
* ln(public hospitals in 2012 + 1). The interaction asks whether the post-reform
* pharmacy response is larger in counties with more public hospitals ex ante.
eststo clear
eststo cd1: reghdfe pharmacy_count  did_ln_public_hospital ///
    $ctrl_road if sample_contdid, ///
    absorb(county_id year) cluster(county_id)
eststo cd2: reghdfe ln_pharmacy  did_ln_public_hospital ///
    $ctrl_road if sample_contdid, ///
    absorb(county_id year) cluster(county_id)

esttab cd1 cd2 using "$OUT\continuous_did_public_hospital_county.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(did_ln_public_hospital ln_pop ln_nl_mean ln_road_den) ///
    mtitles("count FE" "ln count FE") ///
    title("County continuous DID by baseline public-hospital intensity")

* IV version: the endogenous continuous DID term is instrumented by the
* post-policy interaction with the county's 1950s epidemiology-station stock.
eststo clear
eststo iv_cd1: ivreghdfe pharmacy_count $ctrl_road ///
    (did_ln_public_hospital = z_epi_cnt_1959) ///
    if sample_contdid_iv, absorb(county_id year) cluster(county_id) first
eststo iv_cd2: ivreghdfe ln_pharmacy $ctrl_road ///
    (did_ln_public_hospital = z_epi_cnt_1959) ///
    if sample_contdid_iv, absorb(county_id year) cluster(county_id) first
eststo iv_cd3: ivreghdfe pharmacy_count $ctrl_road ///
    (did_ln_public_hospital = z_epi_yrs_50s) ///
    if sample_contdid_iv, absorb(county_id year) cluster(county_id) first
eststo iv_cd4: ivreghdfe ln_pharmacy $ctrl_road ///
    (did_ln_public_hospital = z_epi_yrs_50s) ///
    if sample_contdid_iv, absorb(county_id year) cluster(county_id) first

esttab iv_cd1 iv_cd2 iv_cd3 iv_cd4 ///
    using "$OUT\continuous_did_public_hospital_iv_epi50s.rtf", replace ///
    se b(%9.3fc) scalars(N widstat) nocons ///
    keep(did_ln_public_hospital ln_pop ln_nl_mean ln_road_den) ///
    mtitles("count IV: 1959 stock" "ln count IV: 1959 stock" ///
        "count IV: station-years" "ln count IV: station-years") ///
    title("County continuous DID IV: 1950s epidemiology-station instruments")

*-------------------------------------------------------------------------------
* Part 5. PPML count models
*-------------------------------------------------------------------------------

* PPML keeps zero pharmacy counts and is a natural robustness check for count
* outcomes.
eststo clear
eststo pp1: ppmlhdfe pharmacy_count did $ctrl_road if sample_road, ///
    absorb(county_id year) cluster(county_id)

esttab pp1 using "$OUT\ppml_count_county.rtf", replace ///
    se b(%9.3fc) scalars(N) nocons ///
    keep(did ln_pop ln_nl_mean ln_road_den) ///
    mtitles("FE") ///
    title("County PPML: pharmacy count")

*-------------------------------------------------------------------------------
* Part 6. Chain and non-chain outcomes
*-------------------------------------------------------------------------------

* Mechanism-style split:
*   chain_pharmacy_count vs nonchain_pharmacy_count, plus chain_share.
eststo clear
eststo ch1: reghdfe chain_pharmacy_count did $ctrl_road if sample_road, ///
    absorb(county_id year) cluster(county_id)
eststo nch1: reghdfe nonchain_pharmacy_count did $ctrl_road if sample_road, ///
    absorb(county_id year) cluster(county_id)
eststo sh1: reghdfe chain_share did $ctrl_road if sample_road, ///
    absorb(county_id year) cluster(county_id)

esttab ch1 nch1 sh1 using "$OUT\chain_nonchain_county.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(did ln_pop ln_nl_mean ln_road_den) ///
    mtitles("chain" "nonchain" "share") ///
    title("County chain and non-chain pharmacy outcomes")

*-------------------------------------------------------------------------------
* Part 7. TWFE event-study diagnostics
*-------------------------------------------------------------------------------

* Event study uses rel = year - effective_policy_year.
* rel = -1 is the omitted benchmark.
* Pre-period coefficients are used to assess whether treated and comparison
* counties had similar pre-trends.
forvalues k = 2/4 {
    capture drop ev_m`k'
    gen byte ev_m`k' = (rel == -`k')
}
capture drop ev_0
gen byte ev_0 = (rel == 0)
forvalues k = 1/5 {
    capture drop ev_p`k'
    gen byte ev_p`k' = (rel == `k')
}

* TWFE event-study figures use the same binned event-time specification as the
* five-estimator robustness plots: rel=-1 is omitted, rel<=-5 and rel>=3 are
* pooled into the endpoints.
capture drop F5event F4event F3event F2event L0event L1event L2event L3event
gen byte F5event = (rel <= -5) if !missing(rel)
gen byte F4event = (rel == -4) if !missing(rel)
gen byte F3event = (rel == -3) if !missing(rel)
gen byte F2event = (rel == -2) if !missing(rel)
gen byte L0event = (rel == 0) if !missing(rel)
gen byte L1event = (rel == 1) if !missing(rel)
gen byte L2event = (rel == 2) if !missing(rel)
gen byte L3event = (rel >= 3) if !missing(rel)
foreach v in F5event F4event F3event F2event L0event L1event L2event L3event {
    replace `v' = 0 if missing(`v')
}

foreach y in pharmacy_count ln_pharmacy {
    reghdfe `y' F5event F4event F3event F2event L0event L1event L2event L3event ///
        $ctrl_road if sample_road, absorb(county_id year) cluster(county_id)
    capture noisily test F5event F4event F3event F2event
    if _rc {
        estadd scalar pretrend_p = .
    }
    else {
        estadd scalar pretrend_p = r(p)
    }
    eststo twfe_event_`y'

    coefplot twfe_event_`y', ///
        keep(F5event F4event F3event F2event L0event L1event L2event L3event) ///
        vertical ///
        xlabel(1 "<= -5" 2 "-4" 3 "-3" 4 "-2" 5 "0" 6 "1" 7 "2" 8 ">= 3") ///
        xline(4.5, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("County TWFE event study: `y'") ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        name(twfe_event_`y', replace)
    graph export "$OUT\twfe_event_`y'.png", replace
}

esttab twfe_event_pharmacy_count twfe_event_ln_pharmacy ///
    using "$OUT\twfe_event_stock_county.rtf", replace ///
    se b(%9.3fc) r2 scalars(N pretrend_p) nocons ///
    keep(F5event F4event F3event F2event L0event L1event L2event L3event ///
         ln_pop ln_nl_mean ln_road_den) ///
    mtitles("pharmacy count" "ln pharmacy") ///
    title("County TWFE event study: stock outcomes")

* Continuous-DID event study. Each event-time indicator is interacted with the
* county's baseline public-hospital intensity, ln(public hospitals in 2012 + 1).
* Relative year -1 is omitted, matching the standard TWFE event-study above.
capture drop cdev_m4 cdev_m3 cdev_m2 cdev_0 cdev_p1 cdev_p2 cdev_p3 cdev_p4 cdev_p5
gen double cdev_m4 = ev_m4 * ln_public_hospital_base
gen double cdev_m3 = ev_m3 * ln_public_hospital_base
gen double cdev_m2 = ev_m2 * ln_public_hospital_base
gen double cdev_0  = ev_0  * ln_public_hospital_base
gen double cdev_p1 = ev_p1 * ln_public_hospital_base
gen double cdev_p2 = ev_p2 * ln_public_hospital_base
gen double cdev_p3 = ev_p3 * ln_public_hospital_base
gen double cdev_p4 = ev_p4 * ln_public_hospital_base
gen double cdev_p5 = ev_p5 * ln_public_hospital_base

* IV event-study instruments. The time-invariant 1950s epidemiology-station
* stock is interacted with the same event-time indicators as the endogenous
* continuous-DID event terms.
capture drop zcdev_m4 zcdev_m3 zcdev_m2 zcdev_0 zcdev_p1 zcdev_p2 zcdev_p3 zcdev_p4 zcdev_p5
gen double zcdev_m4 = ev_m4 * epi_cnt_1959
gen double zcdev_m3 = ev_m3 * epi_cnt_1959
gen double zcdev_m2 = ev_m2 * epi_cnt_1959
gen double zcdev_0  = ev_0  * epi_cnt_1959
gen double zcdev_p1 = ev_p1 * epi_cnt_1959
gen double zcdev_p2 = ev_p2 * epi_cnt_1959
gen double zcdev_p3 = ev_p3 * epi_cnt_1959
gen double zcdev_p4 = ev_p4 * epi_cnt_1959
gen double zcdev_p5 = ev_p5 * epi_cnt_1959

gen byte sample_contdid_event_iv = sample_contdid & ///
    !missing(epi_cnt_1959, cdev_m4, cdev_m3, cdev_m2, cdev_0, ///
        cdev_p1, cdev_p2, cdev_p3, cdev_p4, cdev_p5, ///
        zcdev_m4, zcdev_m3, zcdev_m2, zcdev_0, zcdev_p1, ///
        zcdev_p2, zcdev_p3, zcdev_p4, zcdev_p5)

foreach y in pharmacy_count ln_pharmacy {
    local ystub "`y'"
    if "`y'" == "pharmacy_count" {
        local ystub "count"
    }
    if "`y'" == "ln_pharmacy" {
        local ystub "ln_count"
    }

    reghdfe `y' cdev_m4 cdev_m3 cdev_m2 cdev_0 cdev_p1 cdev_p2 cdev_p3 cdev_p4 cdev_p5 ///
        $ctrl_road if sample_contdid, absorb(county_id year) cluster(county_id)
    capture noisily test cdev_m4 cdev_m3 cdev_m2
    if _rc {
        estadd scalar pretrend_p = .
    }
    else {
        estadd scalar pretrend_p = r(p)
    }
    eststo cdes_`ystub'

    esttab cdes_`ystub' using "$OUT\continuous_did_event_`ystub'.rtf", replace ///
        se b(%9.3fc) r2 scalars(N pretrend_p) nocons ///
        keep(cdev_m4 cdev_m3 cdev_m2 cdev_0 cdev_p1 cdev_p2 cdev_p3 cdev_p4 cdev_p5 ln_pop ln_nl_mean ln_road_den) ///
        title("County continuous DID event study: `y'")

    coefplot cdes_`ystub', ///
        keep(cdev_m4 cdev_m3 cdev_m2 cdev_0 cdev_p1 cdev_p2 cdev_p3 cdev_p4 cdev_p5) ///
        vertical ///
        xlabel(1 "-4" 2 "-3" 3 "-2" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
        xline(4, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("County continuous DID event study: `y'") ///
        xtitle("Years relative to reform") ///
        ytitle("Coefficient on baseline public-hospital intensity") ///
        name(cdes_`ystub', replace)
    graph export "$OUT\continuous_did_event_`ystub'.png", replace
}

foreach y in pharmacy_count ln_pharmacy {
    local ystub "`y'"
    if "`y'" == "pharmacy_count" {
        local ystub "count"
    }
    if "`y'" == "ln_pharmacy" {
        local ystub "ln_count"
    }

    ivreghdfe `y' $ctrl_road ///
        (cdev_m4 cdev_m3 cdev_m2 cdev_0 cdev_p1 cdev_p2 cdev_p3 cdev_p4 cdev_p5 = ///
         zcdev_m4 zcdev_m3 zcdev_m2 zcdev_0 zcdev_p1 zcdev_p2 zcdev_p3 zcdev_p4 zcdev_p5) ///
        if sample_contdid_event_iv, absorb(county_id year) cluster(county_id)
    capture noisily test cdev_m4 cdev_m3 cdev_m2
    if _rc {
        estadd scalar pretrend_p = .
    }
    else {
        estadd scalar pretrend_p = r(p)
    }
    eststo iv_cdes_`ystub'

    esttab iv_cdes_`ystub' using "$OUT\continuous_did_event_iv_`ystub'.rtf", replace ///
        se b(%9.3fc) scalars(N widstat pretrend_p) nocons ///
        keep(cdev_m4 cdev_m3 cdev_m2 cdev_0 cdev_p1 cdev_p2 cdev_p3 cdev_p4 cdev_p5 ///
             ln_pop ln_nl_mean ln_road_den) ///
        title("County IV continuous DID event study: `y'")

    coefplot iv_cdes_`ystub', ///
        keep(cdev_m4 cdev_m3 cdev_m2 cdev_0 cdev_p1 cdev_p2 cdev_p3 cdev_p4 cdev_p5) ///
        vertical ///
        xlabel(1 "-4" 2 "-3" 3 "-2" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
        xline(4, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("County IV continuous DID event study: `y'") ///
        xtitle("Years relative to reform") ///
        ytitle("IV coefficient on baseline public-hospital intensity") ///
        name(iv_cdes_`ystub', replace)
    graph export "$OUT\continuous_did_event_iv_`ystub'.png", replace
}

* Annual-change event study. This uses the first-difference outcome from Part 4A
* and the same omitted event year (-1) as the stock event-study graphs.
eststo clear
reghdfe d_pharmacy_count ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5 ///
    $ctrl_road if sample_change, absorb(county_id year) cluster(county_id)
capture noisily test ev_m4 ev_m3 ev_m2
if _rc {
    estadd scalar pretrend_p = .
}
else {
    estadd scalar pretrend_p = r(p)
}
eststo twfe_event_d_pharmacy_count

esttab twfe_event_d_pharmacy_count using "$OUT\twfe_event_d_pharmacy_count.rtf", replace ///
    se b(%9.3fc) r2 scalars(N pretrend_p) nocons ///
    keep(ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5 ln_pop ln_nl_mean ln_road_den) ///
    title("County TWFE event study: annual change in pharmacy count")

coefplot twfe_event_d_pharmacy_count, ///
    keep(ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5) ///
    vertical ///
    xlabel(1 "-4" 2 "-3" 3 "-2" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
    xline(4, lcolor(red) lpattern(dash)) ///
    yline(0, lcolor(red)) ///
    recast(scatter) ciopts(recast(rcap)) msize(small) ///
    title("County TWFE event study: annual change in count") ///
    xtitle("Years relative to reform") ytitle("Coefficient") ///
    name(twfe_event_d_pharmacy_count, replace)
graph export "$OUT\twfe_event_d_pharmacy_count.png", replace
* Binned TWFE event study, window [-3,+3]. The tails are pooled into
* <= -3 and >= +3, while rel = -1 remains the omitted benchmark.
capture drop bin_m3 bin_m2 bin_0 bin_p1 bin_p2 bin_p3
gen byte bin_m3 = (rel <= -3) if !missing(rel)
gen byte bin_m2 = (rel == -2) if !missing(rel)
gen byte bin_0  = (rel == 0)  if !missing(rel)
gen byte bin_p1 = (rel == 1)  if !missing(rel)
gen byte bin_p2 = (rel == 2)  if !missing(rel)
gen byte bin_p3 = (rel >= 3)  if !missing(rel)
foreach v in bin_m3 bin_m2 bin_0 bin_p1 bin_p2 bin_p3 {
    replace `v' = 0 if missing(`v')
}

foreach y in pharmacy_count ln_pharmacy {
    local ystub "`y'"
    if "`y'" == "pharmacy_count" {
        local ystub "count"
    }
    if "`y'" == "ln_pharmacy" {
        local ystub "ln_count"
    }

    reghdfe `y' bin_m3 bin_m2 bin_0 bin_p1 bin_p2 bin_p3 ///
        $ctrl_road if sample_road, absorb(county_id year) cluster(county_id)
    capture noisily test bin_m3 bin_m2
    if _rc {
        estadd scalar pretrend_p = .
    }
    else {
        estadd scalar pretrend_p = r(p)
    }
    eststo twfeb_m3p3_`ystub'

    esttab twfeb_m3p3_`ystub' using "$OUT\twfe_event_binned_m3p3_`ystub'.rtf", replace ///
        se b(%9.3fc) r2 scalars(N pretrend_p) nocons ///
        keep(bin_m3 bin_m2 bin_0 bin_p1 bin_p2 bin_p3 ln_pop ln_nl_mean ln_road_den) ///
        title("County binned TWFE event study [-3,+3]: `y'")

    coefplot twfeb_m3p3_`ystub', ///
        keep(bin_m3 bin_m2 bin_0 bin_p1 bin_p2 bin_p3) ///
        vertical ///
        xlabel(1 "<= -3" 2 "-2" 3 "0" 4 "1" 5 "2" 6 ">= 3") ///
        xline(2.5, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("County binned TWFE event study [-3,+3]: `y'") ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        name(twfeb_m3p3_`ystub', replace)
    graph export "$OUT\twfe_event_binned_m3p3_`ystub'.png", replace
}

eststo clear
reghdfe d_pharmacy_count bin_m3 bin_m2 bin_0 bin_p1 bin_p2 bin_p3 ///
    $ctrl_road if sample_change, absorb(county_id year) cluster(county_id)
capture noisily test bin_m3 bin_m2
if _rc {
    estadd scalar pretrend_p = .
}
else {
    estadd scalar pretrend_p = r(p)
}
eststo twfeb_m3p3_d_pharmacy_count

esttab twfeb_m3p3_d_pharmacy_count using "$OUT\twfe_event_binned_m3p3_d_pharmacy_count.rtf", replace ///
    se b(%9.3fc) r2 scalars(N pretrend_p) nocons ///
    keep(bin_m3 bin_m2 bin_0 bin_p1 bin_p2 bin_p3 ln_pop ln_nl_mean ln_road_den) ///
    title("County binned TWFE event study [-3,+3]: annual change in pharmacy count")

coefplot twfeb_m3p3_d_pharmacy_count, ///
    keep(bin_m3 bin_m2 bin_0 bin_p1 bin_p2 bin_p3) ///
    vertical ///
    xlabel(1 "<= -3" 2 "-2" 3 "0" 4 "1" 5 "2" 6 ">= 3") ///
    xline(2.5, lcolor(red) lpattern(dash)) ///
    yline(0, lcolor(red)) ///
    recast(scatter) ciopts(recast(rcap)) msize(small) ///
    title("County binned TWFE event study [-3,+3]: annual change in count") ///
    xtitle("Years relative to reform") ytitle("Coefficient") ///
    name(twfeb_m3p3_d_pharmacy_count, replace)
graph export "$OUT\twfe_event_binned_m3p3_d_pharmacy_count.png", replace



*-------------------------------------------------------------------------------
* Part 8. CSDID robustness
*-------------------------------------------------------------------------------

* CSDID is a staggered-DID robustness check. notyet uses not-yet-treated
* counties as controls.
foreach y in pharmacy_count ln_pharmacy {
    csdid `y' $ctrl_road if sample_road, ///
        ivar(county_id) time(year) gvar(effective_policy_year) ///
        method(dripw) vce(cluster county_id) notyet
    estat simple
    estat event, window(-5 3) drop(Tm1) estore(cs_`y')
    capture noisily estat pretrend

    event_plot cs_`y', ///
        stub_lag(Tp#) stub_lead(Tm#) ///
        trimlag(3) trimlead(5) together plottype(scatter) ciplottype(rcap) ///
        lag_opt(msymbol(X) mcolor(orange) color(orange) msize(small)) ///
        lag_ci_opt(color(orange%45) lwidth(thin)) ///
        graph_opt( ///
            title("County CSDID event study: `y'") ///
            xtitle("Years relative to reform") ///
            ytitle("ATT") ///
            xlabel(-5(1)3) ///
            xline(-0.5, lcolor(red) lpattern(dash)) ///
            yline(0, lcolor(red)) ///
            name(cs_`y', replace) ///
            graphregion(color(white)) plotregion(color(white)) bgcolor(white) ///
        )
    graph export "$OUT\csdid_event_`y'.png", replace
}

* CSDID event study for annual pharmacy-count changes.
capture noisily csdid d_pharmacy_count $ctrl_road if sample_change, ///
    ivar(county_id) time(year) gvar(effective_policy_year) ///
    method(dripw) vce(cluster county_id) notyet
if _rc {
    di as error "CSDID annual-change event study failed; continuing without csdid_event_d_pharmacy_count.png."
}
else {
    estat simple
    estat event, window(-5 3) drop(Tm1) estore(cs_d_pharmacy_count)
    capture noisily estat pretrend

    event_plot cs_d_pharmacy_count, ///
        stub_lag(Tp#) stub_lead(Tm#) ///
        trimlag(3) trimlead(5) together plottype(scatter) ciplottype(rcap) ///
        lag_opt(msymbol(X) mcolor(orange) color(orange) msize(small)) ///
        lag_ci_opt(color(orange%45) lwidth(thin)) ///
        graph_opt( ///
            title("County CSDID event study: annual change in count") ///
            xtitle("Years relative to reform") ///
            ytitle("ATT") ///
            xlabel(-5(1)3) ///
            xline(-0.5, lcolor(red) lpattern(dash)) ///
            yline(0, lcolor(red)) ///
            name(cs_d_pharmacy_count, replace) ///
            graphregion(color(white)) plotregion(color(white)) bgcolor(white) ///
        )
    graph export "$OUT\csdid_event_d_pharmacy_count.png", replace
}

*-------------------------------------------------------------------------------
* Part 9. Five-estimator event-study robustness
*-------------------------------------------------------------------------------

* This figure follows the comparison 
* Sun-Abraham, Cengiz stacked event study,
* Borusyak-Jaravel-Spiess imputation, Callaway-Sant'Anna, and TWFE.
* County-level reforms are all eventually treated in this sample. For estimators
* that need clean controls, the last-treated counties are used as controls and
* observations at/after the last-treated cohort's treatment year are excluded.
*
* Relative periods earlier than -5 and later than +3 are binned into -5 and +3.
* Period -1 is the omitted benchmark for the dummy-based estimators.
summ effective_policy_year if sample_road, meanonly
local last_policy_year = r(max)

capture drop F5event F4event F3event F2event L0event L1event L2event L3event
gen byte F5event = (rel <= -5) if !missing(rel)
gen byte F4event = (rel == -4) if !missing(rel)
gen byte F3event = (rel == -3) if !missing(rel)
gen byte F2event = (rel == -2) if !missing(rel)
gen byte L0event = (rel == 0) if !missing(rel)
gen byte L1event = (rel == 1) if !missing(rel)
gen byte L2event = (rel == 2) if !missing(rel)
gen byte L3event = (rel >= 3) if !missing(rel)
foreach v in F5event F4event F3event F2event L0event L1event L2event L3event {
    replace `v' = 0 if missing(`v')
}

capture drop last_treat_control sa_cohort stack_cohort
gen byte last_treat_control = (effective_policy_year == `last_policy_year') if sample_road
gen int sa_cohort = effective_policy_year
gen int stack_cohort = effective_policy_year
replace stack_cohort = . if last_treat_control == 1

foreach v in F5event F4event F3event F2event L0event L1event L2event L3event {
    capture drop sa_`v' st_`v'
    gen byte sa_`v' = `v'
    gen byte st_`v' = `v'
    replace sa_`v' = 0 if last_treat_control == 1
    replace st_`v' = 0 if last_treat_control == 1
}

preserve
    keep if sample_road
    gen rel_5_3 = rel
    replace rel_5_3 = -5 if rel_5_3 < -5
    replace rel_5_3 = 3 if rel_5_3 > 3
    contract effective_policy_year rel_5_3
    sort effective_policy_year rel_5_3
    export delimited using "$OUT\event_5estimators_support_county.csv", replace
restore

tempfile fiveest_base_panel
save `fiveest_base_panel', replace

foreach y in pharmacy_count ln_pharmacy {
    use `fiveest_base_panel', clear

    local ystub "`y'"
    local ytitle "ATT"
    if "`y'" == "pharmacy_count" {
        local ystub "count"
        local ytitle "ATT on pharmacy count"
    }
    if "`y'" == "ln_pharmacy" {
        local ystub "ln_count"
        local ytitle "ATT on ln pharmacy count"
    }

    * Borusyak, Jaravel, and Spiess (2021): imputation estimator.
    * The SE weight iteration can be slow in this county panel. First try
    * stricter iteration settings; if SE convergence still fails, keep the
    * BJS point estimates with nose so the robustness figure is still produced.
    capture noisily did_imputation `y' county_id year effective_policy_year if sample_road, ///
        horizons(0/3) pretrend(5) autosample ///
        controls($ctrl_road) cluster(county_id) tol(0.0001) maxit(10000)
    if _rc {
        di as error "BJS standard errors did not converge for `y'; rerunning with nose."
        did_imputation `y' county_id year effective_policy_year if sample_road, ///
            horizons(0/3) pretrend(5) autosample ///
            controls($ctrl_road) cluster(county_id) nose
    }
    estimates store bjs_`ystub'

    * Callaway and Sant'Anna (2021): group-time ATT, not-yet-treated controls.
    csdid `y' $ctrl_road if sample_road, ///
        ivar(county_id) time(year) gvar(effective_policy_year) ///
        method(dripw) vce(cluster county_id) notyet
    estat event, window(-5 3) drop(Tm1) estore(cs_rob_`ystub')
    capture noisily estat pretrend

    * Sun and Abraham (2021): interaction-weighted estimator.
    * Last-treated counties are controls, so their treatment year is excluded.
    eventstudyinteract `y' ///
        sa_F5event sa_F4event sa_F3event sa_F2event ///
        sa_L0event sa_L1event sa_L2event sa_L3event ///
        if sample_road & year < `last_policy_year', ///
        cohort(sa_cohort) control_cohort(last_treat_control) ///
        covariates($ctrl_road) absorb(county_id year) ///
        vce(cluster county_id)
    matrix b_sa_`ystub' = e(b_iw)
    matrix V_sa_`ystub' = e(V_iw)

    * Conventional TWFE event-study, shown for comparison.
    reghdfe `y' F5event F4event F3event F2event ///
        L0event L1event L2event L3event ///
        $ctrl_road if sample_road, absorb(county_id year) cluster(county_id)
    estimates store twfe_rob_`ystub'

    * Cengiz et al. (2019): stacked event-study design.
    * stackedev rewrites the active dataset, so isolate it from the main panel.
    preserve
        stackedev `y' ///
            st_F5event st_F4event st_F3event st_F2event ///
            st_L0event st_L1event st_L2event st_L3event ///
            if sample_road & year < `last_policy_year', ///
            cohort(stack_cohort) time(year) never_treat(last_treat_control) ///
            unit_fe(county_id) clust_unit(county_id) covariates($ctrl_road)
        estimates store stack_`ystub'
    restore

    * The odd-numbered plot layers are the point estimates in event_plot:
    *   1 BJS, 3 Callaway-Sant'Anna, 5 Sun-Abraham, 7 Cengiz stacked, 9 TWFE.
    * Use those layers in legend(order()) so the legend shows the marker icons,
    * not only the confidence-interval caps.
    event_plot bjs_`ystub' cs_rob_`ystub' b_sa_`ystub'#V_sa_`ystub' stack_`ystub' twfe_rob_`ystub', ///
        stub_lag(tau# Tp# sa_L#event st_L#event L#event) ///
        stub_lead(pre# Tm# sa_F#event st_F#event F#event) ///
        trimlag(3) trimlead(5) together plottype(scatter) ciplottype(rcap) ///
        perturb(-0.24 -0.12 0 0.12 0.24) ///
        lag_opt1(msymbol(circle) mcolor(red) color(red) msize(small)) ///
        lag_ci_opt1(color(red%45) lwidth(thin)) ///
        lag_opt2(msymbol(X) mcolor(orange) color(orange) msize(small)) ///
        lag_ci_opt2(color(orange%45) lwidth(thin)) ///
        lag_opt3(msymbol(diamond_hollow) mcolor(green) color(green) msize(small)) ///
        lag_ci_opt3(color(green%45) lwidth(thin)) ///
        lag_opt4(msymbol(triangle_hollow) mcolor(blue) color(blue) msize(small)) ///
        lag_ci_opt4(color(blue%45) lwidth(thin)) ///
        lag_opt5(msymbol(plus) mcolor(black) color(black) msize(small)) ///
        lag_ci_opt5(color(black%45) lwidth(thin)) ///
        graph_opt( ///
            title("") ///
            xtitle("Years relative to reform", size(small)) ///
            ytitle("Coefficients", size(small)) ///
            xlabel(-5(1)3, labsize(small)) ///
            ylabel(, labsize(small) angle(horizontal)) ///
            xline(-0.5, lcolor(gs8) lpattern(dash)) ///
            yline(0, lcolor(gs8)) ///
            name(event_5est_`ystub', replace) ///
            graphregion(color(white) margin(small)) ///
            plotregion(color(white) margin(small)) bgcolor(white) ///
            legend(on order(5 "Sun and Abraham (2021)" ///
                            7 "Cengiz et al. (2019)" ///
                            1 "Borusyak et al. (2021)" ///
                            3 "Callaway and Sant'Anna (2021)" ///
                            9 "TWFE") ///
                   rows(2) position(6) ring(1) size(vsmall) ///
                   symxsize(*0.6) keygap(*0.4) colgap(*0.7) ///
                   region(lstyle(none) fcolor(none))) ///
        )
    graph export "$OUT\event_5estimators_`ystub'.png", replace width(2400)
}

log close
