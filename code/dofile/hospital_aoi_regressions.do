*===============================================================================
* What this file does:
*   Hospital-level reform regressions using matched 2023 AOI hospital boundaries.
*
* Input:
*   county_pharmacy_panel\hospital_aoi_pharmacy_panel_2012_2022.csv
*
* Key design:
*   - Hospital spatial unit is fixed by the matched 2023 AOI boundary.
*   - Pharmacy outcomes are recomputed yearly from each year's pharmacy data.
*   - Regression unit is AOI hospital x year.
*   - Main coefficient is ddd = public hospital x post-policy.
*===============================================================================

clear all
set more off
set linesize 255

global ROOT "D:\Hospital_Pharmacy program"
global DATA "$ROOT\data\processed\hospital_pharmacy\county_pharmacy_panel"
global OUTROOT "$ROOT\output\regression"
global OUT "$OUTROOT\hospital_aoi"

capture mkdir "$OUTROOT"
capture mkdir "$OUT"

cap log close
log using "$OUT\hospital_aoi_regressions.log", replace text

*-------------------------------------------------------------------------------
* Part 0. Required user-written commands
*-------------------------------------------------------------------------------

foreach cmd in reghdfe esttab eststo estpost coefplot ppmlhdfe {
    capture which `cmd'
    if _rc {
        di as error "`cmd' is required. Install it before running this file."
        exit 111
    }
}

*-------------------------------------------------------------------------------
* Part 1. Load matched AOI hospital-year panel
*-------------------------------------------------------------------------------

import delimited using "$DATA\hospital_aoi_pharmacy_panel_2012_2022.csv", ///
    clear varnames(1) encoding("UTF-8") bindquote(strict)

foreach v in aoi_hospital_id registered_id year county_id public policy_year ///
    post_policy ddd rel score match_score match_distance_m {
    capture confirm variable `v'
    if !_rc {
        capture confirm string variable `v'
        if !_rc {
            destring `v', replace force
        }
    }
}

foreach r in 500m 1km 2km 3km {
    foreach v in pharmacy_count_`r' chain_pharmacy_count_`r' ///
        nonchain_pharmacy_count_`r' chain_share_`r' {
        capture confirm variable `v'
        if !_rc {
            capture confirm string variable `v'
            if !_rc {
                destring `v', replace force
            }
        }
    }
}

foreach r in 1km 2km 3km {
    foreach v in ntl_mean_`r' ntl_sum_`r' {
        capture confirm variable `v'
        if !_rc {
            capture confirm string variable `v'
            if !_rc {
                destring `v', replace force
            }
        }
    }
}

drop if missing(aoi_hospital_id, registered_id, year)
isid aoi_hospital_id year
xtset aoi_hospital_id year
xtdescribe

gen long county_id_long = round(county_id)
replace county_id_long = . if missing(county_id)
gen long prov_id = floor(county_id_long / 10000) if !missing(county_id_long)
gen long city_id = floor(county_id_long / 100) if !missing(county_id_long)

replace policy_year = round(policy_year)
replace year = round(year)

capture drop post_policy_calc ddd_calc rel_calc
gen byte post_policy_calc = (year >= policy_year) if !missing(year, policy_year)
gen byte ddd_calc = public * post_policy_calc if !missing(public, post_policy_calc)
gen rel_calc = year - policy_year if !missing(year, policy_year)

replace post_policy = post_policy_calc if missing(post_policy)
replace ddd = ddd_calc if missing(ddd)
replace rel = rel_calc if missing(rel)

foreach r in 500m 1km 2km 3km {
    capture drop ln1p_pharmacy_`r' ln_pharmacy_`r' has_pharmacy_`r'
    gen double ln1p_pharmacy_`r' = ln(pharmacy_count_`r' + 1)
    gen double ln_pharmacy_`r' = ln(pharmacy_count_`r') if pharmacy_count_`r' > 0
    gen byte has_pharmacy_`r' = (pharmacy_count_`r' > 0) if !missing(pharmacy_count_`r')

    capture drop ln1p_chain_pharmacy_`r' ln1p_nonchain_pharmacy_`r'
    gen double ln1p_chain_pharmacy_`r' = ln(chain_pharmacy_count_`r' + 1)
    gen double ln1p_nonchain_pharmacy_`r' = ln(nonchain_pharmacy_count_`r' + 1)
}

foreach r in 1km 2km 3km {
    capture drop ln_ntl_mean_`r'
    gen double ln_ntl_mean_`r' = ln(ntl_mean_`r' + 1) if !missing(ntl_mean_`r')
}

gen byte sample_hospital = inrange(year, 2012, 2022) ///
    & !missing(aoi_hospital_id, year, public, policy_year, county_id_long)

label var ddd "Public hospital x post"
label var post_policy "Post policy"
label var sample_hospital "Matched AOI hospital sample"

save "$DATA\hospital_aoi_pharmacy_panel_2012_2022.dta", replace

*-------------------------------------------------------------------------------
* Part 2. Sample diagnostics and descriptive statistics
*-------------------------------------------------------------------------------

preserve
    contract year public if sample_hospital
    sort year public
    export delimited using "$OUT\sample_composition_hospital_aoi.csv", replace
restore

preserve
    keep if sample_hospital == 1
    collapse (count) obs=aoi_hospital_id ///
        (mean) pharmacy_count_500m pharmacy_count_1km pharmacy_count_2km pharmacy_count_3km ///
               ln1p_pharmacy_500m ln1p_pharmacy_1km ln1p_pharmacy_2km ln1p_pharmacy_3km ///
               has_pharmacy_500m has_pharmacy_1km has_pharmacy_2km has_pharmacy_3km ///
               public post_policy ddd, by(year)
    export delimited using "$OUT\desc_by_year_hospital_aoi.csv", replace
restore

eststo clear
estpost summarize pharmacy_count_500m pharmacy_count_1km pharmacy_count_2km pharmacy_count_3km ///
    ln1p_pharmacy_500m ln1p_pharmacy_1km ln1p_pharmacy_2km ln1p_pharmacy_3km ///
    has_pharmacy_500m has_pharmacy_1km has_pharmacy_2km has_pharmacy_3km ///
    public post_policy ddd if sample_hospital, detail
esttab using "$OUT\desc_hospital_aoi.rtf", replace ///
    cells("count mean sd min p25 p50 p75 max") ///
    noobs nomtitle nonumber ///
    title("Matched AOI hospital-level descriptive statistics")

*-------------------------------------------------------------------------------
* Part 3. Main DDD regressions: pharmacy counts around AOI boundaries
*-------------------------------------------------------------------------------

eststo clear
foreach r in 500m 1km 2km 3km {
    eststo c_`r': reghdfe pharmacy_count_`r' ddd post_policy ///
        if sample_hospital, absorb(aoi_hospital_id year) vce(cluster county_id_long)
}
esttab c_500m c_1km c_2km c_3km using "$OUT\ddd_count_hospital_aoi.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd post_policy) ///
    mtitles("500m" "1km" "2km" "3km") ///
    title("AOI Hospital DDD: pharmacy count")

eststo clear
foreach r in 500m 1km 2km 3km {
    eststo l1p_`r': reghdfe ln1p_pharmacy_`r' ddd post_policy ///
        if sample_hospital, absorb(aoi_hospital_id year) vce(cluster county_id_long)
}
esttab l1p_500m l1p_1km l1p_2km l1p_3km using "$OUT\ddd_ln1p_hospital_aoi.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd post_policy) ///
    mtitles("500m" "1km" "2km" "3km") ///
    title("AOI Hospital DDD: ln(count+1)")
	
eststo clear
foreach r in 500m 1km 2km 3km {
    eststo l_`r': reghdfe ln_pharmacy_`r' ddd post_policy ///
        if sample_hospital, absorb(aoi_hospital_id year) vce(cluster county_id_long)
}
esttab l_500m l_1km l_2km l_3km using "$OUT\ddd_ln_hospital_aoi.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd post_policy) ///
    mtitles("500m" "1km" "2km" "3km") ///
    title("AOI Hospital DDD: ln(count)")

eststo clear
foreach r in 500m 1km 2km 3km {
    eststo h_`r': reghdfe has_pharmacy_`r' ddd post_policy ///
        if sample_hospital, absorb(aoi_hospital_id year) vce(cluster county_id_long)
}
esttab h_500m h_1km h_2km h_3km using "$OUT\ddd_has_hospital_aoi.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd post_policy ) ///
    mtitles("500m" "1km" "2km" "3km") ///
    title("AOI Hospital DDD: has pharmacy")

*-------------------------------------------------------------------------------
* Part 4. Province-year fixed-effect benchmark regressions
*-------------------------------------------------------------------------------

eststo clear
foreach r in 500m 1km 2km 3km {
    eststo tw_`r': reghdfe pharmacy_count_`r' ddd post_policy ///
        if sample_hospital, absorb(aoi_hospital_id prov_id#year) vce(cluster county_id_long)
}
esttab tw_500m tw_1km tw_2km tw_3km using "$OUT\twfe_count_hospital_aoi.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd post_policy) ///
    mtitles("500m" "1km" "2km" "3km") ///
    title("AOI Hospital TWFE: pharmacy count")

eststo clear
foreach r in 500m 1km 2km 3km {
    eststo twl_`r': reghdfe ln1p_pharmacy_`r' ddd post_policy ///
        if sample_hospital, absorb(aoi_hospital_id prov_id#year) vce(cluster county_id_long)
}
esttab twl_500m twl_1km twl_2km twl_3km using "$OUT\twfe_ln1p_hospital_aoi.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd post_policy) ///
    mtitles("500m" "1km" "2km" "3km") ///
    title("AOI Hospital TWFE: ln(count+1)")

* Controls using registered hospital NTL variables are available for 1km/2km/3km.
eststo clear
foreach r in 1km 2km 3km {
    eststo ctrl_`r': reghdfe pharmacy_count_`r' ddd post_policy ln_ntl_mean_`r' ///
        if sample_hospital, absorb(aoi_hospital_id prov_id#year) vce(cluster county_id_long)
}
esttab ctrl_1km ctrl_2km ctrl_3km using "$OUT\twfe_count_hospital_aoi_ntl.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd post_policy ln_ntl_mean_1km ln_ntl_mean_2km ln_ntl_mean_3km) ///
    mtitles("1km" "2km" "3km") ///
    title("AOI Hospital TWFE: pharmacy count with NTL controls")

*-------------------------------------------------------------------------------
* Part 5. Chain vs non-chain split
*-------------------------------------------------------------------------------

eststo clear
foreach r in 500m 1km 2km 3km {
    eststo ch_`r': reghdfe chain_pharmacy_count_`r' ddd post_policy ///
        if sample_hospital, absorb(aoi_hospital_id prov_id#year) vce(cluster county_id_long)
    eststo nch_`r': reghdfe nonchain_pharmacy_count_`r' ddd post_policy ///
        if sample_hospital, absorb(aoi_hospital_id prov_id#year) vce(cluster county_id_long)
}
esttab ch_500m nch_500m ch_1km nch_1km ch_2km nch_2km ch_3km nch_3km ///
    using "$OUT\chain_nonchain_hospital_aoi.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd post_policy) ///
    mtitles("chain 500m" "nonchain 500m" "chain 1km" "nonchain 1km" ///
            "chain 2km" "nonchain 2km" "chain 3km" "nonchain 3km") ///
    title("AOI Hospital DDD: chain vs non-chain pharmacies")

*-------------------------------------------------------------------------------
* Part 6. PPML count regressions
*-------------------------------------------------------------------------------

eststo clear
foreach r in 500m 1km 2km 3km {
    eststo pp_`r': ppmlhdfe pharmacy_count_`r' ddd post_policy ///
        if sample_hospital, absorb(aoi_hospital_id prov_id#year) cluster(county_id_long)
}
esttab pp_500m pp_1km pp_2km pp_3km using "$OUT\ppml_count_hospital_aoi.rtf", replace ///
    se b(%9.3fc) scalars(N) nocons ///
    keep(ddd post_policy) ///
    mtitles("500m" "1km" "2km" "3km") ///
    title("AOI Hospital PPML: pharmacy count")

*-------------------------------------------------------------------------------
* Part 7. Event-study diagnostics
*-------------------------------------------------------------------------------

capture drop ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5
gen byte ev_m4 = public * (rel <= -4) if !missing(rel, public)
gen byte ev_m3 = public * (rel == -3) if !missing(rel, public)
gen byte ev_m2 = public * (rel == -2) if !missing(rel, public)
gen byte ev_0  = public * (rel == 0)  if !missing(rel, public)
forvalues k = 1/5 {
    gen byte ev_p`k' = public * (rel == `k') if !missing(rel, public)
}

foreach r in 500m 1km 2km 3km {
    reghdfe pharmacy_count_`r' ///
        ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5 post_policy ///
        if sample_hospital, absorb(aoi_hospital_id prov_id#year) vce(cluster county_id_long)
    eststo event_`r'

    coefplot event_`r', ///
        keep(ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5) ///
        vertical ///
        xlabel(1 "<=-4" 2 "-3" 3 "-2" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
        xline(4, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("AOI hospital event study: `r'") ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        name(event_aoi_`r', replace)
    graph export "$OUT\event_count_hospital_aoi_`r'.png", replace
}

log close
