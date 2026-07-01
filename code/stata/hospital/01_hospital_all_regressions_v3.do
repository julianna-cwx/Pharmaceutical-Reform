*===============================================================================
* 01_hospital_all_regressions_v3.do
*
* What this file does:
*   Part 0. Check required Stata packages.
*   Part 1. Load hospital-year panel and create variables.
*   Part 2. Descriptive statistics and sample diagnostics.
*   Part 3. Main DDD regressions.
*   Part 4. TWFE benchmark regressions.
*   Part 5. PPML count regressions.
*   Part 6. Chain vs non-chain pharmacy regressions.
*   Part 7. DDD event-study graphs.
*   Part 8. CSDID robustness checks.
*
* This v3 file merges the complete original hospital-level workflow with the
* v2 full-sample short-window TWFE event-study diagnostics. Score-subsample
* regressions are intentionally removed.

*===============================================================================

clear all
set more off
set linesize 255

global ROOT "D:\Hospital_Pharmacy program"
global DATA "$ROOT\data\processed\hospital_pharmacy\hospital_with_pharmacy_counts_registered"
global OUTROOT "$ROOT\output\regression"
global OUT "$OUTROOT\hospital_v3"

capture mkdir "$OUTROOT"
capture mkdir "$OUT"

cap log close
log using "$OUT\01_hospital_all_regressions_v3.log", replace text

*-------------------------------------------------------------------------------
* Part 0. Required user-written commands
*-------------------------------------------------------------------------------

foreach cmd in reghdfe esttab eststo estpost coefplot csdid ppmlhdfe {
    capture which `cmd'
    if _rc {
        di as error "`cmd' is required. Install it before running this file."
        exit 111
    }
}

*-------------------------------------------------------------------------------
* Part 1. Load data and construct variables
*-------------------------------------------------------------------------------

use "$DATA\hospital_pharmacy_2012_2022.dta", clear
isid id year
xtset id year

* 1.1 Public/private hospital indicator.
* In this dataset the 24th variable is the ownership type variable.
* We avoid typing the Chinese value "public" directly in executable code because
* Stata/Windows encoding can sometimes read Chinese characters inconsistently.
* uchar(20844)+uchar(31435) is the Chinese string for "public".
capture confirm variable public
if _rc {
    unab allvars : _all
    local ownvar : word 24 of `allvars'
    local public_text = uchar(20844) + uchar(31435)
    gen byte public = (ustrtrim(`ownvar') == "`public_text'")
}

replace policy_year = round(policy_year)
replace year = round(year)

* 1.2 Area identifiers and time trend.

gen long prov_id = floor(county_id / 10000)
gen long city_id = floor(county_id / 100)
gen int t = year - 2011

* 1.3 Treatment variables.
* post_policy: local reform has started.
* ddd: public hospitals after reform. This is the main coefficient.
gen byte post_policy = (year >= policy_year) if !missing(year, policy_year)
gen byte ddd = public * post_policy
gen rel = year - policy_year

* 1.4 Outcomes and controls.
* keep four distance bands: 500m, 1km, 2km, and 3km.
* ln1p_pharmacy = ln(count+1), keeping zero-count observations.
* ln_pharmacy = ln(count), so zero-count observations do not stay in sample.
* has_pharmacy is the extensive-margin outcome.
* ln_ntl_mean controls for local nighttime-light intensity.
foreach r in 500m 1km 2km 3km {
    capture drop ln1p_pharmacy_`r' ln_pharmacy_`r' has_pharmacy_`r'
    gen ln1p_pharmacy_`r' = ln(pharmacy_count_`r' + 1)
    gen ln_pharmacy_`r' = ln(pharmacy_count_`r')
    gen has_pharmacy_`r' = (pharmacy_count_`r' > 0) if !missing(pharmacy_count_`r')

    capture drop nonchain_pharmacy_count_`r'
    gen nonchain_pharmacy_count_`r' = pharmacy_count_`r' - chain_pharmacy_count_`r'
    replace nonchain_pharmacy_count_`r' = . if nonchain_pharmacy_count_`r' < 0
}

foreach r in 1km 2km 3km {
    capture drop ln_ntl_mean_`r'
    gen ln_ntl_mean_`r' = ln(ntl_mean_`r' + 1)
}

* The local GEE NTL extract currently has 1km/2km/3km radii only.
* For 500m outcome regressions, use the 1km NTL control as the closest proxy.
capture drop ln_ntl_mean_500m
gen ln_ntl_mean_500m = ln_ntl_mean_1km
label var ln_ntl_mean_500m "ln(NTL mean+1), 1km proxy for 500m"

gen byte sample_hospital = inrange(year, 2012, 2022) ///
    & (missing(policy_year) | policy_year != 2012)

label var ddd "Public hospital x post"
label var sample_hospital "Hospital estimation sample"

*-------------------------------------------------------------------------------
* Part 2. Descriptive statistics and sample diagnostics
*-------------------------------------------------------------------------------

* This table checks how many public and non-public hospitals enter each year.
preserve
    contract year public if sample_hospital
    sort year public
    export delimited using "$OUT\sample_composition_hospital.csv", replace
restore

eststo clear
estpost summarize pharmacy_count_500m pharmacy_count_1km pharmacy_count_2km pharmacy_count_3km ///
    ln1p_pharmacy_500m ln1p_pharmacy_1km ln1p_pharmacy_2km ln1p_pharmacy_3km ///
    ln_pharmacy_500m ln_pharmacy_1km ln_pharmacy_2km ln_pharmacy_3km ///
    has_pharmacy_500m has_pharmacy_1km has_pharmacy_2km has_pharmacy_3km ///
    public post_policy ddd if sample_hospital, detail
esttab using "$OUT\desc_hospital.rtf", replace ///
    cells("count mean sd min p25 p50 p75 max") ///
    noobs nomtitle nonumber ///
    title("Hospital-level descriptive statistics")

*-------------------------------------------------------------------------------
* Part 3. DDD main regressions: count, log, extensive margin
*-------------------------------------------------------------------------------

* Main specification:
*   outcome_hct = beta * ddd_hct + controls_hct
*                 + hospital FE + province-year FE + error_hct
*
* Interpretation of beta:
*   after the reform, how much more/less did pharmacies around public hospitals
*   change relative to pharmacies around non-public hospitals in the same broad
*   province-year environment?
*

eststo clear
foreach r in 500m 1km 2km 3km {
    eststo c`r': reghdfe pharmacy_count_`r' ddd  ///
        if sample_hospital, absorb(id year) cluster(county_id)
}
esttab c500m c1km c2km c3km using "$OUT\ddd_count.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd) ///
    mtitles("500m" "1km" "2km" "3km") ///
    title("Hospital DDD: pharmacy count")
	
eststo clear
foreach r in 500m 1km 2km 3km {
    eststo c`r': reghdfe pharmacy_count_`r' ddd ln_ntl_mean_`r'  ///
        if sample_hospital, absorb(id year) cluster(county_id)
}
esttab c500m c1km c2km c3km using "$OUT\ddd_count.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd) ///
    mtitles("500m" "1km" "2km" "3km") ///
    title("Hospital DDD: pharmacy count")
	
eststo clear
foreach r in 500m 1km 2km 3km {
    eststo c`r': reghdfe pharmacy_count_`r' ddd ln_ntl_mean_`r' ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
}
esttab c500m c1km c2km c3km using "$OUT\ddd_count2.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd ln_ntl_mean_500m ln_ntl_mean_1km ln_ntl_mean_2km ln_ntl_mean_3km) ///
    mtitles("500m" "1km" "2km" "3km") ///
    title("Hospital DDD: pharmacy count")
	
eststo clear
foreach r in 500m 1km 2km 3km {
    eststo l`r': reghdfe ln1p_pharmacy_`r' ddd  ///
        if sample_hospital, absorb(id year) cluster(county_id)
}
esttab l500m l1km l2km l3km using "$OUT\ddd_ln1p.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd) ///
    mtitles("500m" "1km" "2km" "3km") ///
    title("Hospital DDD: ln(count+1)")	
	

eststo clear
foreach r in 500m 1km 2km 3km {
    eststo l`r': reghdfe ln1p_pharmacy_`r' ddd ln_ntl_mean_`r' ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
}
esttab l500m l1km l2km l3km using "$OUT\ddd_ln1p.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd ln_ntl_mean_500m ln_ntl_mean_1km ln_ntl_mean_2km ln_ntl_mean_3km) ///
    mtitles("500m" "1km" "2km" "3km") ///
    title("Hospital DDD: ln(count+1)")

eststo clear
foreach r in 500m 1km 2km 3km {
    eststo h`r': reghdfe has_pharmacy_`r' ddd ln_ntl_mean_`r' ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
}
esttab h500m h1km h2km h3km using "$OUT\ddd_has.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd ln_ntl_mean_500m ln_ntl_mean_1km ln_ntl_mean_2km ln_ntl_mean_3km) ///
    mtitles("500m" "1km" "2km" "3km") ///
    title("Hospital DDD: has pharmacy")

*-------------------------------------------------------------------------------
* Part 4. TWFE benchmarks
*-------------------------------------------------------------------------------

* These are benchmark specifications similar to CS_v5.do:
*   - hospital FE + year FE;
*   - hospital FE + province-year FE.
* The coefficient is still ddd.
eststo clear
foreach r in 500m 1km 2km 3km {
    eststo tw`r'a: reghdfe pharmacy_count_`r' ddd post_policy ln_ntl_mean_`r' ///
        if sample_hospital, absorb(id year) cluster(county_id)
    eststo tw`r'b: reghdfe pharmacy_count_`r' ddd ln_ntl_mean_`r' ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
}
esttab tw500ma tw500mb tw1kma tw1kmb tw2kma tw2kmb tw3kma tw3kmb using "$OUT\twfe_count_hospital.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd post_policy ln_ntl_mean_500m ln_ntl_mean_1km ln_ntl_mean_2km ln_ntl_mean_3km) ///
    mtitles("500m: id+year" "500m: prov-year" "1km: id+year" "1km: prov-year" ///
            "2km: id+year" "2km: prov-year" "3km: id+year" "3km: prov-year") ///
    title("Hospital TWFE benchmarks")

eststo clear
foreach r in 500m 1km 2km 3km {
    eststo twl1p`r'a: reghdfe ln1p_pharmacy_`r' ddd post_policy ln_ntl_mean_`r' ///
        if sample_hospital, absorb(id year) cluster(county_id)
    eststo twl1p`r'b: reghdfe ln1p_pharmacy_`r' ddd post_policy ln_ntl_mean_`r' ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
}
esttab twl1p500ma twl1p500mb twl1p1kma twl1p1kmb twl1p2kma twl1p2kmb twl1p3kma twl1p3kmb using "$OUT\twfe_ln1p_hospital.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd post_policy ln_ntl_mean_500m ln_ntl_mean_1km ln_ntl_mean_2km ln_ntl_mean_3km) ///
    mtitles("500m: id+year" "500m: prov-year" "1km: id+year" "1km: prov-year" ///
            "2km: id+year" "2km: prov-year" "3km: id+year" "3km: prov-year") ///
    title("Hospital TWFE benchmarks: ln(count+1)")

eststo clear
foreach r in 500m 1km 2km 3km {
    eststo twln`r'a: reghdfe ln_pharmacy_`r' ddd post_policy ln_ntl_mean_`r' ///
        if sample_hospital, absorb(id year) cluster(county_id)
    eststo twln`r'b: reghdfe ln_pharmacy_`r' ddd post_policy ln_ntl_mean_`r' ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
}
esttab twln500ma twln500mb twln1kma twln1kmb twln2kma twln2kmb twln3kma twln3kmb using "$OUT\twfe_ln_hospital.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd post_policy ln_ntl_mean_500m ln_ntl_mean_1km ln_ntl_mean_2km ln_ntl_mean_3km) ///
    mtitles("500m: id+year" "500m: prov-year" "1km: id+year" "1km: prov-year" ///
            "2km: id+year" "2km: prov-year" "3km: id+year" "3km: prov-year") ///
    title("Hospital TWFE benchmarks: ln(count)")

eststo clear
foreach r in 500m 1km 2km 3km {
    eststo twh`r'a: reghdfe has_pharmacy_`r' ddd post_policy ln_ntl_mean_`r' ///
        if sample_hospital, absorb(id year) cluster(county_id)
    eststo twh`r'b: reghdfe has_pharmacy_`r' ddd post_policy ln_ntl_mean_`r' ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
}
esttab twh500ma twh500mb twh1kma twh1kmb twh2kma twh2kmb twh3kma twh3kmb using "$OUT\twfe_has_hospital.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd post_policy ln_ntl_mean_500m ln_ntl_mean_1km ln_ntl_mean_2km ln_ntl_mean_3km) ///
    mtitles("500m: id+year" "500m: prov-year" "1km: id+year" "1km: prov-year" ///
            "2km: id+year" "2km: prov-year" "3km: id+year" "3km: prov-year") ///
    title("Hospital TWFE benchmarks: has pharmacy")

*-------------------------------------------------------------------------------
* Part 5. PPML count regressions
*-------------------------------------------------------------------------------

* PPML is useful for nonnegative count outcomes and keeps zero pharmacy counts.
* The coefficient is semi-elasticity-like, not the same scale as OLS levels.
eststo clear
foreach r in 500m 1km 2km 3km {
    eststo pp`r': ppmlhdfe pharmacy_count_`r' ddd post_policy ln_ntl_mean_`r' ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
}
esttab pp500m pp1km pp2km pp3km using "$OUT\ppml_count_hospital.rtf", replace ///
    se b(%9.3fc) scalars(N) nocons ///
    keep(ddd ln_ntl_mean_500m ln_ntl_mean_1km ln_ntl_mean_2km ln_ntl_mean_3km) ///
    mtitles("500m" "1km" "2km" "3km") ///
    title("Hospital PPML: pharmacy count")

*-------------------------------------------------------------------------------
* Part 6. Chain vs non-chain split
*-------------------------------------------------------------------------------

* This split asks whether the response is mainly from chain pharmacies or
* non-chain pharmacies.
eststo clear
foreach r in 500m 1km 2km 3km {
    eststo ch`r': reghdfe chain_pharmacy_count_`r' ddd post_policy ln_ntl_mean_`r' ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
    eststo nch`r': reghdfe nonchain_pharmacy_count_`r' ddd ln_ntl_mean_`r' ///
        if sample_hospital, absorb(id prov_id#year) cluster(county_id)
}
esttab ch500m nch500m ch1km nch1km ch2km nch2km ch3km nch3km using "$OUT\ddd_chain_nonchain_hospital.rtf", replace ///
    se b(%9.3fc) r2 scalars(N) nocons ///
    keep(ddd ln_ntl_mean_500m ln_ntl_mean_1km ln_ntl_mean_2km ln_ntl_mean_3km) ///
    mtitles("chain 500m" "nonchain 500m" "chain 1km" "nonchain 1km" ///
            "chain 2km" "nonchain 2km" "chain 3km" "nonchain 3km") ///
    title("Hospital DDD: chain vs non-chain pharmacies")

*-------------------------------------------------------------------------------
* Part 7. DDD event-study diagnostics
*-------------------------------------------------------------------------------

* Event study:
*   rel = year - policy_year.
*   rel = -1 is omitted as the benchmark year.
* Pre-period coefficients should be close to zero if pre-trends are similar.
forvalues k = 2/4 {
    capture drop ev_m`k'
    gen byte ev_m`k' = public * (rel == -`k')
}
capture drop ev_0
gen byte ev_0 = public * (rel == 0)
forvalues k = 1/5 {
    capture drop ev_p`k'
    gen byte ev_p`k' = public * (rel == `k')
}

foreach r in 500m 1km 2km 3km {
    reghdfe pharmacy_count_`r' ///
        ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5 post_policy ///
        ln_ntl_mean_`r' if sample_hospital, ///
        absorb(id prov_id#year) cluster(county_id)
    eststo ddd_event_`r'

    coefplot ddd_event_`r', ///
        keep(ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5) ///
        vertical ///
        xlabel(1 "-4" 2 "-3" 3 "-2" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
        xline(4, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital DDD event study: `r'") ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        name(ddd_event_`r', replace)
    graph export "$OUT\ddd_event_count_`r'.png", replace
}

foreach r in 500m 1km 2km 3km {
    reghdfe ln1p_pharmacy_`r' ///
        ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5 post_policy ///
        ln_ntl_mean_`r' if sample_hospital, ///
        absorb(id prov_id#year) cluster(county_id)
    eststo ddd_event_ln1p_`r'

    coefplot ddd_event_ln1p_`r', ///
        keep(ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5) ///
        vertical ///
        xlabel(1 "-4" 2 "-3" 3 "-2" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
        xline(4, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital DDD event study, ln(count+1): `r'") ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        name(ddd_event_ln1p_`r', replace)
    graph export "$OUT\ddd_event_ln1p_`r'.png", replace
}

foreach r in 500m 1km 2km 3km {
    reghdfe ln_pharmacy_`r' ///
        ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5 post_policy ///
        ln_ntl_mean_`r' if sample_hospital, ///
        absorb(id prov_id#year) cluster(county_id)
    eststo ddd_event_ln_`r'

    coefplot ddd_event_ln_`r', ///
        keep(ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5) ///
        vertical ///
        xlabel(1 "-4" 2 "-3" 3 "-2" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
        xline(4, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital DDD event study, ln(count): `r'") ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        name(ddd_event_ln_`r', replace)
    graph export "$OUT\ddd_event_ln_`r'.png", replace
}

foreach r in 500m 1km 2km 3km {
    reghdfe has_pharmacy_`r' ///
        ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5 post_policy ///
        ln_ntl_mean_`r' if sample_hospital, ///
        absorb(id prov_id#year) cluster(county_id)
    eststo ddd_event_has_`r'

    coefplot ddd_event_has_`r', ///
        keep(ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5) ///
        vertical ///
        xlabel(1 "-4" 2 "-3" 3 "-2" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
        xline(4, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital DDD event study, has pharmacy: `r'") ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        name(ddd_event_has_`r', replace)
    graph export "$OUT\ddd_event_has_`r'.png", replace
}

* 7.1 Alternative event-study diagnostics for the main count outcome.
* These variants probe whether the poor pre-trends are driven by distant leads,
* the omitted relative year, or the province-year fixed-effect structure.

* Variant A: bin distant pre-periods, rel <= -4.
capture drop evbin_m4 evbin_m3 evbin_m2 evbin_0 evbin_p1 evbin_p2 evbin_p3 evbin_p4 evbin_p5
gen byte evbin_m4 = public * (rel <= -4)
gen byte evbin_m3 = public * (rel == -3)
gen byte evbin_m2 = public * (rel == -2)
gen byte evbin_0  = public * (rel == 0)
forvalues k = 1/5 {
    gen byte evbin_p`k' = public * (rel == `k')
}

foreach r in 500m 1km 2km 3km {
    reghdfe pharmacy_count_`r' ///
        evbin_m4 evbin_m3 evbin_m2 evbin_0 evbin_p1 evbin_p2 evbin_p3 evbin_p4 evbin_p5 post_policy ///
        ln_ntl_mean_`r' if sample_hospital, ///
        absorb(id prov_id#year) cluster(county_id)
    eststo ddd_event_binpre_`r'

    coefplot ddd_event_binpre_`r', ///
        keep(evbin_m4 evbin_m3 evbin_m2 evbin_0 evbin_p1 evbin_p2 evbin_p3 evbin_p4 evbin_p5) ///
        vertical ///
        xlabel(1 "<=-4" 2 "-3" 3 "-2" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
        xline(4, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital DDD event study, binned leads: `r'") ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        name(ddd_event_binpre_`r', replace)
    graph export "$OUT\ddd_event_count_binpre_`r'.png", replace
}

* Variant B: restrict/display the window to rel = -3 to +3.
capture drop evwin_m3 evwin_m2 evwin_0 evwin_p1 evwin_p2 evwin_p3
gen byte evwin_m3 = public * (rel == -3)
gen byte evwin_m2 = public * (rel == -2)
gen byte evwin_0  = public * (rel == 0)
forvalues k = 1/3 {
    gen byte evwin_p`k' = public * (rel == `k')
}

foreach r in 500m 1km 2km 3km {
    reghdfe pharmacy_count_`r' ///
        evwin_m3 evwin_m2 evwin_0 evwin_p1 evwin_p2 evwin_p3 post_policy ///
        ln_ntl_mean_`r' if sample_hospital & inrange(rel, -3, 3), ///
        absorb(id prov_id#year) cluster(county_id)
    eststo ddd_event_window_`r'

    coefplot ddd_event_window_`r', ///
        keep(evwin_m3 evwin_m2 evwin_0 evwin_p1 evwin_p2 evwin_p3) ///
        vertical ///
        xlabel(1 "-3" 2 "-2" 3 "0" 4 "1" 5 "2" 6 "3") ///
        xline(3, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital DDD event study, window -3 to +3: `r'") ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        name(ddd_event_window_`r', replace)
    graph export "$OUT\ddd_event_count_window_m3_p3_`r'.png", replace
}

* Variant C: use rel = -2 as the omitted benchmark year.
capture drop evbase2_m4 evbase2_m3 evbase2_m1 evbase2_0 evbase2_p1 evbase2_p2 evbase2_p3 evbase2_p4 evbase2_p5
gen byte evbase2_m4 = public * (rel <= -4)
gen byte evbase2_m3 = public * (rel == -3)
gen byte evbase2_m1 = public * (rel == -1)
gen byte evbase2_0  = public * (rel == 0)
forvalues k = 1/5 {
    gen byte evbase2_p`k' = public * (rel == `k')
}

foreach r in 500m 1km 2km 3km {
    reghdfe pharmacy_count_`r' ///
        evbase2_m4 evbase2_m3 evbase2_m1 evbase2_0 evbase2_p1 evbase2_p2 evbase2_p3 evbase2_p4 evbase2_p5 post_policy ///
        ln_ntl_mean_`r' if sample_hospital, ///
        absorb(id prov_id#year) cluster(county_id)
    eststo ddd_event_base2_`r'

    coefplot ddd_event_base2_`r', ///
        keep(evbase2_m4 evbase2_m3 evbase2_m1 evbase2_0 evbase2_p1 evbase2_p2 evbase2_p3 evbase2_p4 evbase2_p5) ///
        vertical ///
        xlabel(1 "<=-4" 2 "-3" 3 "-1" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
        xline(4, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital DDD event study, base year -2: `r'") ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        name(ddd_event_base2_`r', replace)
    graph export "$OUT\ddd_event_count_base_m2_`r'.png", replace
}

* Variant D: fixed-effect comparison using hospital FE + year FE.
foreach r in 500m 1km 2km 3km {
    reghdfe pharmacy_count_`r' ///
        ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5 post_policy ///
        ln_ntl_mean_`r' if sample_hospital, ///
        absorb(id year) cluster(county_id)
    eststo ddd_event_idyear_`r'

    coefplot ddd_event_idyear_`r', ///
        keep(ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5) ///
        vertical ///
        xlabel(1 "-4" 2 "-3" 3 "-2" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
        xline(4, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital DDD event study, id+year FE: `r'") ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        name(ddd_event_idyear_`r', replace)
    graph export "$OUT\ddd_event_count_idyear_`r'.png", replace
}

* Variant E: PPML event study for count outcomes.
foreach r in 500m 1km 2km 3km {
    ppmlhdfe pharmacy_count_`r' ///
        ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5 post_policy ///
        ln_ntl_mean_`r' if sample_hospital, ///
        absorb(id prov_id#year) cluster(county_id)
    eststo ppml_event_`r'

    coefplot ppml_event_`r', ///
        keep(ev_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_p4 ev_p5) ///
        vertical ///
        xlabel(1 "-4" 2 "-3" 3 "-2" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
        xline(4, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital PPML event study: `r'") ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        name(ppml_event_`r', replace)
    graph export "$OUT\ppml_event_count_`r'.png", replace
}

* Variant F: PPML event study, restricted/displayed window rel = -3 to +3.
foreach r in 500m 1km 2km 3km {
    ppmlhdfe pharmacy_count_`r' ///
        evwin_m3 evwin_m2 evwin_0 evwin_p1 evwin_p2 evwin_p3 post_policy ///
        ln_ntl_mean_`r' if sample_hospital & inrange(rel, -3, 3), ///
        absorb(id prov_id#year) cluster(county_id)
    eststo ppml_event_window_`r'

    coefplot ppml_event_window_`r', ///
        keep(evwin_m3 evwin_m2 evwin_0 evwin_p1 evwin_p2 evwin_p3) ///
        vertical ///
        xlabel(1 "-3" 2 "-2" 3 "0" 4 "1" 5 "2" 6 "3") ///
        xline(3, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital PPML event study, window -3 to +3: `r'") ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        name(ppml_event_window_`r', replace)
    graph export "$OUT\ppml_event_count_window_m3_p3_`r'.png", replace
}

* 7.2 v2 full-sample short-window TWFE event-study diagnostics.
* This reproduces the v2 event-study setup without score subsamples:
*   rel <= -3 is binned as the far pre-period;
*   rel = -1 is omitted as the benchmark;
*   rel = 0, 1, 2, 3 are post/event-year coefficients.
capture drop ev_le_m3 ev_v2_m2 ev_v2_0 ev_v2_p1 ev_v2_p2 ev_v2_p3
gen byte ev_le_m3 = public * (rel <= -3)
gen byte ev_v2_m2 = public * (rel == -2)
gen byte ev_v2_0  = public * (rel == 0)
forvalues k = 1/3 {
    gen byte ev_v2_p`k' = public * (rel == `k')
}

foreach ytype in count ln1p ln has {
    if "`ytype'" == "count" {
        local yprefix pharmacy_count
        local ytitle "pharmacy count"
    }
    else if "`ytype'" == "ln1p" {
        local yprefix ln1p_pharmacy
        local ytitle "ln(count+1)"
    }
    else if "`ytype'" == "ln" {
        local yprefix ln_pharmacy
        local ytitle "ln(count)"
    }
    else {
        local yprefix has_pharmacy
        local ytitle "has pharmacy"
    }

    foreach r in 500m 1km 2km 3km {
        reghdfe `yprefix'_`r' ///
            ev_le_m3 ev_v2_m2 ev_v2_0 ev_v2_p1 ev_v2_p2 ev_v2_p3 post_policy ///
            ln_ntl_mean_`r' if sample_hospital & rel <= 3, ///
            absorb(id prov_id#year) cluster(county_id)
        eststo evv2_`ytype'_`r'

        coefplot evv2_`ytype'_`r', ///
            keep(ev_le_m3 ev_v2_m2 ev_v2_0 ev_v2_p1 ev_v2_p2 ev_v2_p3) ///
            vertical ///
            xlabel(1 "<=-3" 2 "-2" 3 "0" 4 "1" 5 "2" 6 "3") ///
            xline(3, lcolor(red) lpattern(dash)) ///
            yline(0, lcolor(red)) ///
            recast(scatter) ciopts(recast(rcap)) msize(small) ///
            title("Hospital TWFE event study, `ytitle': `r'") ///
            xtitle("Years relative to reform") ytitle("Coefficient") ///
            name(evv2_`ytype'_`r', replace)
        graph export "$OUT\twfe_event_`ytype'_lem3_p3_`r'.png", replace
    }
}

* Fixed-effect comparison for the v2 short-window count outcome:
* hospital FE + year FE instead of hospital FE + province-year FE.
foreach r in 500m 1km 2km 3km {
    reghdfe pharmacy_count_`r' ///
        ev_le_m3 ev_v2_m2 ev_v2_0 ev_v2_p1 ev_v2_p2 ev_v2_p3 post_policy ///
        ln_ntl_mean_`r' if sample_hospital & rel <= 3, ///
        absorb(id year) cluster(county_id)
    eststo evv2_idy_`r'

    coefplot evv2_idy_`r', ///
        keep(ev_le_m3 ev_v2_m2 ev_v2_0 ev_v2_p1 ev_v2_p2 ev_v2_p3) ///
        vertical ///
        xlabel(1 "<=-3" 2 "-2" 3 "0" 4 "1" 5 "2" 6 "3") ///
        xline(3, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital TWFE event study, count, id+year FE: `r'") ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        name(evv2_idy_`r', replace)
    graph export "$OUT\twfe_event_count_idyear_lem3_p3_`r'.png", replace
}

*-------------------------------------------------------------------------------
* Part 8. CSDID robustness
*-------------------------------------------------------------------------------

* CSDID robustness:
*   public hospitals are treated in their policy_year;
*   non-public hospitals are coded as never treated (g_csdid = 0).
* This estimator is used because staggered treatment timing can bias standard
* TWFE when treatment effects are heterogeneous across cohorts/time.
gen g_csdid = policy_year if public == 1
replace g_csdid = 0 if public == 0
replace g_csdid = . if policy_year <= 2012

foreach r in 500m 1km 2km 3km {
    csdid pharmacy_count_`r' post_policy ln_ntl_mean_`r' if sample_hospital, ///
        ivar(id) time(year) gvar(g_csdid) ///
        method(dripw) vce(cluster county_id)
    estat simple
    estat event, window(-4 5) drop(Tm1) estore(cs_hospital_`r')
    estat event, window(-3 3) drop(Tm1) estore(cs_hosp_win_`r')

    coefplot cs_hospital_`r', ///
        keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4 Tp5) ///
        vertical ///
        xlabel(1 "-4" 2 "-3" 3 "-2" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
        xline(4, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital CSDID event study: `r'") ///
        xtitle("Years relative to reform") ytitle("ATT") ///
        name(cs_hospital_`r', replace)
    graph export "$OUT\csdid_event_count_`r'.png", replace

    coefplot cs_hosp_win_`r', ///
        keep(Tm3 Tm2 Tp0 Tp1 Tp2 Tp3) ///
        vertical ///
        xlabel(1 "-3" 2 "-2" 3 "0" 4 "1" 5 "2" 6 "3") ///
        xline(3, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital CSDID event study, window -3 to +3: `r'") ///
        xtitle("Years relative to reform") ytitle("ATT") ///
        name(cs_hosp_win_`r', replace)
    graph export "$OUT\csdid_event_count_window_m3_p3_`r'.png", replace
}

foreach r in 500m 1km 2km 3km {
    csdid ln1p_pharmacy_`r' post_policy ln_ntl_mean_`r' if sample_hospital, ///
        ivar(id) time(year) gvar(g_csdid) ///
        method(dripw) vce(cluster county_id)
    estat simple
    estat event, window(-4 5) drop(Tm1) estore(cs_hospital_ln1p_`r')
    estat event, window(-3 3) drop(Tm1) estore(cs_ln1p_win_`r')

    coefplot cs_hospital_ln1p_`r', ///
        keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4 Tp5) ///
        vertical ///
        xlabel(1 "-4" 2 "-3" 3 "-2" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
        xline(4, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital CSDID event study, ln(count+1): `r'") ///
        xtitle("Years relative to reform") ytitle("ATT") ///
        name(cs_hospital_ln1p_`r', replace)
    graph export "$OUT\csdid_event_ln1p_`r'.png", replace

    coefplot cs_ln1p_win_`r', ///
        keep(Tm3 Tm2 Tp0 Tp1 Tp2 Tp3) ///
        vertical ///
        xlabel(1 "-3" 2 "-2" 3 "0" 4 "1" 5 "2" 6 "3") ///
        xline(3, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital CSDID event study, ln(count+1), window -3 to +3: `r'") ///
        xtitle("Years relative to reform") ytitle("ATT") ///
        name(cs_ln1p_win_`r', replace)
    graph export "$OUT\csdid_event_ln1p_window_m3_p3_`r'.png", replace
}

foreach r in 500m 1km 2km 3km {
    csdid ln_pharmacy_`r' post_policy ln_ntl_mean_`r' if sample_hospital, ///
        ivar(id) time(year) gvar(g_csdid) ///
        method(dripw) vce(cluster county_id)
    estat simple
    estat event, window(-4 5) drop(Tm1) estore(cs_hospital_ln_`r')
    estat event, window(-3 3) drop(Tm1) estore(cs_ln_win_`r')

    coefplot cs_hospital_ln_`r', ///
        keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4 Tp5) ///
        vertical ///
        xlabel(1 "-4" 2 "-3" 3 "-2" 4 "0" 5 "1" 6 "2" 7 "3" 8 "4" 9 "5") ///
        xline(4, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital CSDID event study, ln(count): `r'") ///
        xtitle("Years relative to reform") ytitle("ATT") ///
        name(cs_hospital_ln_`r', replace)
    graph export "$OUT\csdid_event_ln_`r'.png", replace

    coefplot cs_ln_win_`r', ///
        keep(Tm3 Tm2 Tp0 Tp1 Tp2 Tp3) ///
        vertical ///
        xlabel(1 "-3" 2 "-2" 3 "0" 4 "1" 5 "2" 6 "3") ///
        xline(3, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(red)) ///
        recast(scatter) ciopts(recast(rcap)) msize(small) ///
        title("Hospital CSDID event study, ln(count), window -3 to +3: `r'") ///
        xtitle("Years relative to reform") ytitle("ATT") ///
        name(cs_ln_win_`r', replace)
    graph export "$OUT\csdid_event_ln_window_m3_p3_`r'.png", replace
}

log close
