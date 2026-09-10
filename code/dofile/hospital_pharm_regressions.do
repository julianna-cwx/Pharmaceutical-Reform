*===============================================================================
* hospital_pharm_regressions.do
*
* Hospital-level regressions using the new 2012-2019 hospital-pharmacy-
* restaurant panel.
*
* Main question:
*   Does the reform affect pharmacy counts around hospitals?
*   As a comparison/placebo-style outcome, does the reform also affect
*   restaurant counts around hospitals?
*
* Inputs:
*   D:\Hospital_Pharmacy program\data\hospital_pharmacy\hosp_pharm_panel\
*       hospital_pharm_restaurant_panel_2012_2019.dta
*
* Outputs:
*   D:\Hospital_Pharmacy program\output\regression\hospital_pharm_regressions
*===============================================================================

clear all
set more off
set linesize 255

global ROOT "D:\Hospital_Pharmacy program"
global DATA "$ROOT\data\hospital_pharmacy\hosp_pharm_panel"
global OUTROOT "$ROOT\output\regression"
global OUT "$OUTROOT\hospital_pharm_regressions"

capture mkdir "$OUTROOT"
capture mkdir "$OUT"

cap log close
log using "$OUT\hospital_pharm_regressions.log", replace text

*-------------------------------------------------------------------------------
* Part 0. Required user-written commands
*-------------------------------------------------------------------------------

foreach cmd in reghdfe esttab eststo estpost ppmlhdfe coefplot {
    capture which `cmd'
    if _rc {
        di as error "`cmd' is required. Install it before running this file."
        exit 111
    }
}

*-------------------------------------------------------------------------------
* Part 1. Load hospital-level panel and construct variables
*-------------------------------------------------------------------------------

capture confirm file "$DATA\hospital_pharm_restaurant_panel_2012_2019.dta"
if !_rc {
    use "$DATA\hospital_pharm_restaurant_panel_2012_2019.dta", clear
}
else {
    import delimited "$DATA\hospital_pharm_restaurant_panel_2012_2019.csv", ///
        clear varnames(1) encoding("utf-8")
    save "$DATA\hospital_pharm_restaurant_panel_2012_2019.dta", replace
}

* Convert key identifiers to numeric if needed.
capture drop id
capture confirm numeric variable companyid
if _rc {
    destring companyid, gen(companyid_num) force
    egen long id = group(companyid) if missing(companyid_num)
    replace id = companyid_num if !missing(companyid_num)
    drop companyid_num
}
else {
    gen double id = companyid
}

capture confirm numeric variable county_id
if _rc {
    destring county_id, gen(county_id_num) force
    drop county_id
    rename county_id_num county_id
}

replace year = round(year)
replace policy_year = round(policy_year) if !missing(policy_year)

isid id year
xtset id year

gen long prov_id = floor(county_id / 10000) if !missing(county_id)
gen long city_id = floor(county_id / 100) if !missing(county_id)

* Treatment variables.
capture drop post_policy_reg ddd rel
gen byte post_policy_reg = (year >= policy_year) if !missing(year, policy_year)
replace post_policy_reg = 0 if missing(post_policy_reg)
gen byte ddd = public_flag * post_policy_reg if !missing(public_flag, post_policy_reg)
gen rel = year - policy_year if !missing(year, policy_year)

* Main estimation sample:
*   - 2012-2019 only;
*   - drop 2012 reform cohorts because no pre-period exists in this panel;
*   - require valid coordinates and county for clustering.
capture drop sample_hospital
gen byte sample_hospital = inrange(year, 2012, 2019) ///
    & has_valid_coord == 1 ///
    & !missing(id, county_id, public_flag) ///
    & (missing(policy_year) | policy_year != 2012)

label var ddd "Public hospital x post reform"
label var post_policy_reg "Post reform"
label var sample_hospital "Hospital regression sample"

local radii "1km 2km 3km 1_2km 2_3km"
local cumulative "1km 2km 3km"

* Outcomes and transformations.
foreach y in pharmacy restaurant {
    foreach r of local radii {
        capture confirm variable `y'_`r'
        if !_rc {
            capture drop ln1p_`y'_`r' has_`y'_`r'
            gen ln1p_`y'_`r' = ln(`y'_`r' + 1) if !missing(`y'_`r')
            gen byte has_`y'_`r' = (`y'_`r' > 0) if !missing(`y'_`r')
            label var ln1p_`y'_`r' "ln(1+`y' count), `r'"
            label var has_`y'_`r' "Any `y', `r'"
        }
    }
}

foreach r of local radii {
    capture drop nonchain_pharmacy_`r'
    gen nonchain_pharmacy_`r' = pharmacy_`r' - chain_pharmacy_`r' ///
        if !missing(pharmacy_`r', chain_pharmacy_`r')
    replace nonchain_pharmacy_`r' = . if nonchain_pharmacy_`r' < 0
    label var nonchain_pharmacy_`r' "Non-chain pharmacy count, `r'"
}

compress

*-------------------------------------------------------------------------------
* Part 2. Descriptive statistics and sample diagnostics
*-------------------------------------------------------------------------------

preserve
    contract year public_flag if sample_hospital
    sort year public_flag
    export delimited using "$OUT\sample_composition_hospital.csv", replace
restore

eststo clear
estpost summarize ///
    pharmacy_1km pharmacy_2km pharmacy_3km pharmacy_1_2km pharmacy_2_3km ///
    restaurant_1km restaurant_2km restaurant_3km restaurant_1_2km restaurant_2_3km ///
    chain_pharmacy_1km chain_pharmacy_2km chain_pharmacy_3km ///
    chain_share_1km chain_share_2km chain_share_3km ///
    public_flag post_policy_reg ddd if sample_hospital, detail
esttab using "$OUT\desc_hospital_panel.rtf", replace ///
    cells("count mean sd min p25 p50 p75 max") ///
    noobs nomtitle nonumber ///
    title("Hospital-level descriptive statistics, 2012-2019")

*-------------------------------------------------------------------------------
* Part 3. DDD regressions: pharmacy and restaurant counts
*-------------------------------------------------------------------------------

* Specification A: hospital FE + year FE.
eststo clear
foreach r of local radii {
    eststo ph_a_`r': reghdfe pharmacy_`r' ddd ///
        if sample_hospital, absorb(id year) cluster(county_id)
    eststo rt_a_`r': reghdfe restaurant_`r' ddd ///
        if sample_hospital, absorb(id year) cluster(county_id)
}
esttab ph_a_1km rt_a_1km ph_a_2km rt_a_2km ph_a_3km rt_a_3km ///
    ph_a_1_2km rt_a_1_2km ph_a_2_3km rt_a_2_3km ///
    using "$OUT\ddd_count_id_year.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons keep(ddd) ///
    mtitles("Pharm 1km" "Rest 1km" "Pharm 2km" "Rest 2km" ///
            "Pharm 3km" "Rest 3km" "Pharm 1-2km" "Rest 1-2km" ///
            "Pharm 2-3km" "Rest 2-3km") ///
    title("Hospital DDD: pharmacy and restaurant counts, id + year FE")

* Specification B: hospital FE + province-year FE.
eststo clear
foreach r of local radii {
    eststo ph_b_`r': reghdfe pharmacy_`r' ddd ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
    eststo rt_b_`r': reghdfe restaurant_`r' ddd ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
}
esttab ph_b_1km rt_b_1km ph_b_2km rt_b_2km ph_b_3km rt_b_3km ///
    ph_b_1_2km rt_b_1_2km ph_b_2_3km rt_b_2_3km ///
    using "$OUT\ddd_count_prov_year.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons keep(ddd) ///
    mtitles("Pharm 1km" "Rest 1km" "Pharm 2km" "Rest 2km" ///
            "Pharm 3km" "Rest 3km" "Pharm 1-2km" "Rest 1-2km" ///
            "Pharm 2-3km" "Rest 2-3km") ///
    title("Hospital DDD: pharmacy and restaurant counts, id + province-year FE")

*-------------------------------------------------------------------------------
* Part 4. Log outcomes and extensive-margin outcomes
*-------------------------------------------------------------------------------

eststo clear
foreach r of local radii {
    eststo lph_`r': reghdfe ln1p_pharmacy_`r' ddd ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
    eststo lrt_`r': reghdfe ln1p_restaurant_`r' ddd ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
}
esttab lph_1km lrt_1km lph_2km lrt_2km lph_3km lrt_3km ///
    lph_1_2km lrt_1_2km lph_2_3km lrt_2_3km ///
    using "$OUT\ddd_ln1p_prov_year.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons keep(ddd) ///
    mtitles("Pharm 1km" "Rest 1km" "Pharm 2km" "Rest 2km" ///
            "Pharm 3km" "Rest 3km" "Pharm 1-2km" "Rest 1-2km" ///
            "Pharm 2-3km" "Rest 2-3km") ///
    title("Hospital DDD: ln(count+1), id + province-year FE")

eststo clear
foreach r of local radii {
    eststo hph_`r': reghdfe has_pharmacy_`r' ddd ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
    eststo hrt_`r': reghdfe has_restaurant_`r' ddd ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
}
esttab hph_1km hrt_1km hph_2km hrt_2km hph_3km hrt_3km ///
    hph_1_2km hrt_1_2km hph_2_3km hrt_2_3km ///
    using "$OUT\ddd_has_prov_year.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons keep(ddd) ///
    mtitles("Pharm 1km" "Rest 1km" "Pharm 2km" "Rest 2km" ///
            "Pharm 3km" "Rest 3km" "Pharm 1-2km" "Rest 1-2km" ///
            "Pharm 2-3km" "Rest 2-3km") ///
    title("Hospital DDD: extensive margin, id + province-year FE")

*-------------------------------------------------------------------------------
* Part 5. Chain vs non-chain pharmacy split
*-------------------------------------------------------------------------------

eststo clear
foreach r of local radii {
    eststo ch_`r': reghdfe chain_pharmacy_`r' ddd ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
    eststo nch_`r': reghdfe nonchain_pharmacy_`r' ddd ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
}
esttab ch_1km nch_1km ch_2km nch_2km ch_3km nch_3km ///
    ch_1_2km nch_1_2km ch_2_3km nch_2_3km ///
    using "$OUT\ddd_chain_nonchain_prov_year.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons keep(ddd) ///
    mtitles("Chain 1km" "Nonchain 1km" "Chain 2km" "Nonchain 2km" ///
            "Chain 3km" "Nonchain 3km" "Chain 1-2km" "Nonchain 1-2km" ///
            "Chain 2-3km" "Nonchain 2-3km") ///
    title("Hospital DDD: chain vs non-chain pharmacies")

*-------------------------------------------------------------------------------
* Part 6. PPML count regressions
*-------------------------------------------------------------------------------

eststo clear
foreach r of local radii {
    eststo pph_`r': ppmlhdfe pharmacy_`r' ddd ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
    eststo prt_`r': ppmlhdfe restaurant_`r' ddd ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
}
esttab pph_1km prt_1km pph_2km prt_2km pph_3km prt_3km ///
    pph_1_2km prt_1_2km pph_2_3km prt_2_3km ///
    using "$OUT\ppml_count_prov_year.rtf", replace ///
    se b(%9.3fc) scalars(N) nocons keep(ddd) ///
    mtitles("Pharm 1km" "Rest 1km" "Pharm 2km" "Rest 2km" ///
            "Pharm 3km" "Rest 3km" "Pharm 1-2km" "Rest 1-2km" ///
            "Pharm 2-3km" "Rest 2-3km") ///
    title("Hospital PPML: pharmacy and restaurant counts")

*-------------------------------------------------------------------------------
* Part 7. Short-window event-study diagnostics for cumulative radii
*-------------------------------------------------------------------------------

capture drop ev_le_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3
gen byte ev_le_m3 = public_flag * (rel <= -3) if !missing(rel)
gen byte ev_m2    = public_flag * (rel == -2) if !missing(rel)
gen byte ev_0     = public_flag * (rel == 0) if !missing(rel)
forvalues k = 1/3 {
    gen byte ev_p`k' = public_flag * (rel == `k') if !missing(rel)
}

foreach y in pharmacy restaurant {
    foreach r of local cumulative {
        reghdfe `y'_`r' ///
            ev_le_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ///
            if sample_hospital & rel <= 3, ///
            absorb(id prov_id#year) cluster(county_id)
        eststo ev_`y'_`r'

        coefplot ev_`y'_`r', ///
            keep(ev_le_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3) ///
            vertical ///
            xlabel(1 "<=-3" 2 "-2" 3 "0" 4 "1" 5 "2" 6 "3") ///
            xline(3, lcolor(red) lpattern(dash)) ///
            yline(0, lcolor(red)) ///
            recast(scatter) ciopts(recast(rcap)) msize(small) ///
            title("Hospital event study: `y' `r'") ///
            xtitle("Years relative to reform") ytitle("Coefficient") ///
            name(ev_`y'_`r', replace)
        graph export "$OUT\event_`y'_`r'.png", replace
    }
}

log close
