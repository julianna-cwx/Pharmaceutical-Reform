*===============================================================================
* 02_county_all_regressions_v2.do
* Pharmacy is the main outcome.
* Main mechanism outcomes split unique geocoded pharmacies into <=2km and >2km
* from the nearest active public hospital in the same county.
* Counts within 500m and 1km are distance-threshold robustness checks only.
* Hospital-centered pharmacy sums and restaurant outcomes are excluded.

* All count logs are ln(count), without adding 1.
*===============================================================================
version 17
clear all
set more off
set linesize 255

capture mkdir "D:\Hospital_Pharmacy program\output\regression"
capture mkdir "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid"
capture log close _all
log using "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\02_county_all_regressions_v2.log", replace text

* Load the analysis-ready county panel
use "D:\Hospital_Pharmacy program\data\hospital_pharmacy\county_pharm_panel\county_pharm_panel.dta", clear
isid county_id year
capture confirm numeric variable county_id
if _rc {
    destring county_id, gen(county_id_num)
}
else {
    gen long county_id_num = county_id
}
isid county_id_num year

gen long prov_id = floor(county_id_num / 10000) if !missing(county_id_num)
gen byte merge_policy = cond(missing(policy_year), 1, 3)
gen int g_csdid = policy_year if !missing(policy_year) & policy_year >= 2012
replace g_csdid = 0 if missing(policy_year)
gen byte post_policy = (year >= policy_year) if !missing(policy_year)
replace post_policy = 0 if missing(policy_year)

gen int rel = year - policy_year if !missing(policy_year)
gen byte sample_county = inrange(year, 2012, 2019) ///
    & (missing(policy_year) | policy_year >= 2012) ///
    & pharmacy_observed == 1 ///
    & !missing(county_id_num, prov_id, ln_pop, ln_nl_mean, post_policy)

confirm variable pharm_nearest_pub_total
assert pharm_nearest_pub_total >= 0 if !missing(pharm_nearest_pub_total)

foreach scope in le500m le1km le2km gt2km {
    confirm variable pharm_nearest_pub_`scope'
    assert pharm_nearest_pub_`scope' >= 0 ///
        if !missing(pharm_nearest_pub_`scope')
}

assert pharm_nearest_pub_le2km + pharm_nearest_pub_gt2km ///
    == pharm_nearest_pub_total if !missing(pharm_nearest_pub_total)
assert pharm_nearest_pub_le500m <= pharm_nearest_pub_le1km ///
    if !missing(pharm_nearest_pub_le500m, pharm_nearest_pub_le1km)
assert pharm_nearest_pub_le1km <= pharm_nearest_pub_le2km ///
    if !missing(pharm_nearest_pub_le1km, pharm_nearest_pub_le2km)

label variable pharm_nearest_pub_le500m "Unique pharmacies <=500m from nearest same-county public hospital"
label variable pharm_nearest_pub_le1km "Unique pharmacies <=1km from nearest same-county public hospital"
label variable pharm_nearest_pub_le2km "Unique pharmacies <=2km from nearest same-county public hospital"
label variable pharm_nearest_pub_gt2km "Unique pharmacies >2km from all same-county public hospitals"
label variable pharm_nearest_pub_total "Unique geocoded county pharmacies"


gen byte ev_le_m4 = (rel <= -4) if !missing(rel)
gen byte ev_m3 = (rel == -3) if !missing(rel)
gen byte ev_m2 = (rel == -2) if !missing(rel)
gen byte ev_0 = (rel == 0) if !missing(rel)
gen byte ev_p1 = (rel == 1) if !missing(rel)
gen byte ev_p2 = (rel == 2) if !missing(rel)
gen byte ev_p3 = (rel == 3) if !missing(rel)
gen byte ev_ge_p4 = (rel >= 4) if !missing(rel)

replace ev_le_m4 = 0 if merge_policy == 1
replace ev_m3 = 0 if merge_policy == 1
replace ev_m2 = 0 if merge_policy == 1
replace ev_0 = 0 if merge_policy == 1
replace ev_p1 = 0 if merge_policy == 1
replace ev_p2 = 0 if merge_policy == 1
replace ev_p3 = 0 if merge_policy == 1
replace ev_ge_p4 = 0 if merge_policy == 1

quietly count if sample_county
di as result "Main sample observations: " r(N)
egen byte tag_sample_county = tag(county_id_num) if sample_county
quietly count if tag_sample_county == 1
di as result "Counties in main sample: " r(N)
drop tag_sample_county

global outdir "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid"


****************************************************
* 1. Descriptive statistics
****************************************************

gen double population_10000 = exp(ln_pop) / 10000 if !missing(ln_pop)

label variable population_10000 ///
    "County population (10,000 persons)"
local descriptive_vars ///
    county_pharmacy_count ///
    ln_county_pharmacy_count ///
    hospital_count ///
    public_hospital_count ///
    private_hospital_count ///
    pharm_nearest_pub_total ///
    pharm_nearest_pub_le500m ///
    pharm_nearest_pub_le1km ///
    pharm_nearest_pub_le2km ///
    pharm_nearest_pub_gt2km ///
    population_10000 ///
    ln_pop ///
    ln_nl_mean ///
    policy_year

* Store one complete set of descriptive statistics.
estpost tabstat `descriptive_vars' if sample_county, ///
    statistics(n mean sd min max) ///
    columns(statistics)

* Rename the posted count matrix so the RTF code reads "observations".
tempname descriptive_observations
matrix `descriptive_observations' = e(count)
estadd matrix observations = `descriptive_observations'

* Export RTF table
esttab using "$outdir\county_pharmacy_descriptive_statistics2.rtf", ///
    replace ///
    cells("observations(fmt(%12.0fc)) mean(fmt(%12.3fc)) sd(fmt(%12.3fc)) min(fmt(%12.3fc)) max(fmt(%12.3fc))") ///
    collabels("Observations" "Mean" "SD" "Min" "Max") ///
    nonumber ///
    noobs ///
    nomtitle ///
    title("Table 1. Descriptive Statistics") ///
    label

****************************************************
* 2. Treatment-control trend comparison
* Average total county pharmacy count by year
****************************************************

preserve
keep if sample_county
gen byte ever_reformed = !missing(policy_year)

collapse ///
    (count) counties=county_pharmacy_count ///
    (mean) average_pharmacy_count=county_pharmacy_count, ///
    by(year ever_reformed)

sort ever_reformed year

label variable year "Year"
label variable ever_reformed "Reform county"
label variable counties "Counties"
label variable average_pharmacy_count "Average pharmacy count"

format year ever_reformed counties %12.0f
format average_pharmacy_count %12.3f

twoway ///
    (connected average_pharmacy_count year if ever_reformed == 1, ///
        lcolor(navy) mcolor(navy) msymbol(O) lwidth(medthick)) ///
    (connected average_pharmacy_count year if ever_reformed == 0, ///
        lcolor(maroon) mcolor(maroon) msymbol(T) ///
        lpattern(dash) lwidth(medthick)), ///
    xlabel(2012(1)2019) ///
    ylabel(, angle(0) grid glcolor(gs14)) ///
    xtitle("Year") ///
    ytitle("Average total number of pharmacies") ///
    title("Total pharmacy trends: treatment vs. control counties") ///
    legend(order(1 "Treatment group" 2 "Control group") ///
        rows(1) position(6)) ///
    note("Treatment counties have a nonmissing policy year; control counties never reform.", ///
        size(vsmall)) ///
    graphregion(color(white)) plotregion(color(white)) ///
    name(pharm_tc_trend, replace)

graph export "$outdir\county_control_trend.png", ///
    replace width(2400)
restore

*===============================================================================
* Empirical specifications
*===============================================================================

* County main TWFE DID: pharmacy outcomes
eststo clear
eststo total_pharm_count: reghdfe county_pharmacy_count post_policy ln_pop ln_nl_mean if sample_county, absorb(county_id_num year) vce(cluster county_id_num)
eststo total_pharm_ln: reghdfe ln_county_pharmacy_count post_policy ln_pop ln_nl_mean if sample_county, absorb(county_id_num year) vce(cluster county_id_num)
esttab total_pharm_count total_pharm_ln using "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\twfe_main_county_pharmacy.rtf", replace ///
    label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons keep(post_policy ln_pop ln_nl_mean) ///
    mtitles("Pharmacy count" "ln pharmacy count") stats(N r2_within, labels("Observations" "Within R-squared")) ///
    title("County TWFE main: county-wide pharmacy outcomes")

eststo clear
eststo total_pharm_count: reghdfe county_pharmacy_count post_policy  ln_pop ln_nl_mean if sample_county, absorb(county_id_num prov_id#year) vce(cluster county_id_num)
eststo total_pharm_ln: reghdfe ln_county_pharmacy_count post_policy ln_pop ln_nl_mean if sample_county, absorb(county_id_num prov_id#year) vce(cluster county_id_num)
esttab total_pharm_count total_pharm_ln using "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\twfe_main_county_pharmacy2.rtf", replace ///
    label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons keep(post_policy ln_pop ln_nl_mean) ///
    mtitles("Pharmacy count" "ln pharmacy count") stats(N r2_within, labels("Observations" "Within R-squared")) ///
    title("County TWFE main: county-wide pharmacy outcomes")

* County continuous DID IV: instrument baseline public-hospital intensity
* with 1950s epidemiology-station exposure interacted with post-policy timing.
capture confirm variable epi_cnt_1959
if _rc {
    di as error "epi_cnt_1959 is missing. Rerun county_pharm_panel.ipynb to merge the IV variables."
    exit 459
}
capture confirm variable epi_yrs_50s
if _rc {
    di as error "epi_yrs_50s is missing. Rerun county_pharm_panel.ipynb to merge the IV variables."
    exit 459
}

bysort county_id_num: egen double public_hospital_base = max(cond(year == 2012, public_hospital_count, .))
gen double ln_public_hospital_base = ln(public_hospital_base + 1) if !missing(public_hospital_base)
gen double did_ln_public_hospital = post_policy * ln_public_hospital_base
gen double z_did_epi_cnt_1959 = post_policy * epi_cnt_1959
gen double z_did_epi_yrs_50s = post_policy * epi_yrs_50s
gen byte sample_iv_county = sample_county ///
    & !missing(county_pharmacy_count, ln_county_pharmacy_count, ln_pop, ln_nl_mean, ///
        did_ln_public_hospital, z_did_epi_cnt_1959, z_did_epi_yrs_50s)
label variable ln_public_hospital_base "ln baseline public hospitals, 2012 + 1"
label variable did_ln_public_hospital "Post x ln baseline public hospitals"
label variable z_did_epi_cnt_1959 "Post x 1959 epidemiology-station stock"
label variable z_did_epi_yrs_50s "Post x 1950s epidemiology station-years"

quietly count if sample_iv_county
di as result "County IV sample observations: " r(N)

eststo clear
eststo iv_stock_count: ivreghdfe county_pharmacy_count ln_pop ln_nl_mean ///
    (did_ln_public_hospital = z_did_epi_cnt_1959) if sample_iv_county, ///
    absorb(county_id_num prov_id#year) cluster(county_id_num) first
tempname kp_stock_count
capture scalar `kp_stock_count' = e(widstat)
if _rc estadd scalar kp_f = .
else estadd scalar kp_f = `kp_stock_count'

eststo iv_stock_ln: ivreghdfe ln_county_pharmacy_count ln_pop ln_nl_mean ///
    (did_ln_public_hospital = z_did_epi_cnt_1959) if sample_iv_county, ///
    absorb(county_id_num prov_id#year) cluster(county_id_num) first
tempname kp_stock_ln
capture scalar `kp_stock_ln' = e(widstat)
if _rc estadd scalar kp_f = .
else estadd scalar kp_f = `kp_stock_ln'

eststo iv_years_count: ivreghdfe county_pharmacy_count ln_pop ln_nl_mean ///
    (did_ln_public_hospital = z_did_epi_yrs_50s) if sample_iv_county, ///
    absorb(county_id_num prov_id#year) cluster(county_id_num) first
tempname kp_years_count
capture scalar `kp_years_count' = e(widstat)
if _rc estadd scalar kp_f = .
else estadd scalar kp_f = `kp_years_count'

eststo iv_years_ln: ivreghdfe ln_county_pharmacy_count ln_pop ln_nl_mean ///
    (did_ln_public_hospital = z_did_epi_yrs_50s) if sample_iv_county, ///
    absorb(county_id_num prov_id#year) cluster(county_id_num) first
tempname kp_years_ln
capture scalar `kp_years_ln' = e(widstat)
if _rc estadd scalar kp_f = .
else estadd scalar kp_f = `kp_years_ln'

esttab iv_stock_count iv_stock_ln iv_years_count iv_years_ln using "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\iv_county_pharmacy_epi50s.rtf", replace ///
    label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons ///
    keep(did_ln_public_hospital ln_pop ln_nl_mean) ///
    mtitles("Count: stock IV" "ln count: stock IV" "Count: station-years IV" "ln count: station-years IV") ///
    stats(N kp_f, labels("Observations" "Kleibergen-Paap F")) ///
    title("County continuous DID IV: 1950s epidemiology-station instruments")

* Reduced-form event studies for the IV-DID parallel-trends assessment.
* Event time -1 is omitted. Leads should be jointly zero under parallel trends
* and no anticipation. These tests are diagnostics, not proof of exclusion.
local iv_event_suffixes "le_m4 m3 m2 0 p1 p2 p3 ge_p4"
local iv_event_dummies  "ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4"

local position = 1
foreach suffix of local iv_event_suffixes {
    local event_dummy : word `position' of `iv_event_dummies'
    gen double rf_stock_`suffix' = `event_dummy' * epi_cnt_1959 ///
        if sample_iv_county
    gen double rf_years_`suffix' = `event_dummy' * epi_yrs_50s ///
        if sample_iv_county
    local position = `position' + 1
}

label variable rf_stock_le_m4 "<=-4 x 1959 epidemiology-station stock"
label variable rf_stock_m3 "-3 x 1959 epidemiology-station stock"
label variable rf_stock_m2 "-2 x 1959 epidemiology-station stock"
label variable rf_stock_0 "0 x 1959 epidemiology-station stock"
label variable rf_stock_p1 "1 x 1959 epidemiology-station stock"
label variable rf_stock_p2 "2 x 1959 epidemiology-station stock"
label variable rf_stock_p3 "3 x 1959 epidemiology-station stock"
label variable rf_stock_ge_p4 ">=4 x 1959 epidemiology-station stock"

label variable rf_years_le_m4 "<=-4 x 1950s epidemiology station-years"
label variable rf_years_m3 "-3 x 1950s epidemiology station-years"
label variable rf_years_m2 "-2 x 1950s epidemiology station-years"
label variable rf_years_0 "0 x 1950s epidemiology station-years"
label variable rf_years_p1 "1 x 1950s epidemiology station-years"
label variable rf_years_p2 "2 x 1950s epidemiology station-years"
label variable rf_years_p3 "3 x 1950s epidemiology station-years"
label variable rf_years_ge_p4 ">=4 x 1950s epidemiology station-years"

local rf_stock_vars ///
    rf_stock_le_m4 rf_stock_m3 rf_stock_m2 rf_stock_0 ///
    rf_stock_p1 rf_stock_p2 rf_stock_p3 rf_stock_ge_p4
local rf_years_vars ///
    rf_years_le_m4 rf_years_m3 rf_years_m2 rf_years_0 ///
    rf_years_p1 rf_years_p2 rf_years_p3 rf_years_ge_p4

eststo clear
quietly reghdfe county_pharmacy_count `rf_stock_vars' ///
    ln_pop ln_nl_mean if sample_iv_county, ///
    absorb(county_id_num prov_id#year) vce(cluster county_id_num)
test rf_stock_le_m4 rf_stock_m3 rf_stock_m2
estadd scalar pretrend_p = r(p)
eststo rf_stock_count

quietly reghdfe ln_county_pharmacy_count `rf_stock_vars' ///
    ln_pop ln_nl_mean if sample_iv_county, ///
    absorb(county_id_num prov_id#year) vce(cluster county_id_num)
test rf_stock_le_m4 rf_stock_m3 rf_stock_m2
estadd scalar pretrend_p = r(p)
eststo rf_stock_ln

quietly reghdfe county_pharmacy_count `rf_years_vars' ///
    ln_pop ln_nl_mean if sample_iv_county, ///
    absorb(county_id_num prov_id#year) vce(cluster county_id_num)
test rf_years_le_m4 rf_years_m3 rf_years_m2
estadd scalar pretrend_p = r(p)
eststo rf_years_count

quietly reghdfe ln_county_pharmacy_count `rf_years_vars' ///
    ln_pop ln_nl_mean if sample_iv_county, ///
    absorb(county_id_num prov_id#year) vce(cluster county_id_num)
test rf_years_le_m4 rf_years_m3 rf_years_m2
estadd scalar pretrend_p = r(p)
eststo rf_years_ln

esttab rf_stock_count rf_stock_ln rf_years_count rf_years_ln using ///
    "$outdir\iv_reduced_form_event_epi50s.rtf", replace ///
    label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons ///
    keep(`rf_stock_vars' `rf_years_vars') ///
    mtitles("Count: stock exposure" "ln count: stock exposure" ///
        "Count: station-years exposure" "ln count: station-years exposure") ///
    stats(N pretrend_p, ///
        labels("Observations" "Joint pretrend p-value")) ///
    title("IV-DID Reduced-form Event Studies; Event Time -1 Omitted")

coefplot rf_stock_count, keep(`rf_stock_vars') vertical ///
    coeflabels(rf_stock_le_m4="<=-4" rf_stock_m3="-3" rf_stock_m2="-2" ///
        rf_stock_0="0" rf_stock_p1="1" rf_stock_p2="2" ///
        rf_stock_p3="3" rf_stock_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) ///
    yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Reduced form: pharmacy count, stock exposure") ///
    xtitle("Years relative to reform; -1 omitted") ///
    ytitle("Coefficient on event time x instrument exposure") ///
    note("95% CIs; county-clustered SEs. Pretrend p-value reported in RTF table.", ///
        size(vsmall)) ///
    graphregion(color(white)) plotregion(color(white)) ///
    name(rf_event_stock_count, replace)
graph export "$outdir\iv_rf_event_stock_count.png", replace width(2400)

coefplot rf_stock_ln, keep(`rf_stock_vars') vertical ///
    coeflabels(rf_stock_le_m4="<=-4" rf_stock_m3="-3" rf_stock_m2="-2" ///
        rf_stock_0="0" rf_stock_p1="1" rf_stock_p2="2" ///
        rf_stock_p3="3" rf_stock_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) ///
    yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Reduced form: ln pharmacy count, stock exposure") ///
    xtitle("Years relative to reform; -1 omitted") ///
    ytitle("Coefficient on event time x instrument exposure") ///
    note("95% CIs; county-clustered SEs. Pretrend p-value reported in RTF table.", ///
        size(vsmall)) ///
    graphregion(color(white)) plotregion(color(white)) ///
    name(rf_event_stock_ln, replace)
graph export "$outdir\iv_rf_event_stock_ln.png", replace width(2400)

coefplot rf_years_count, keep(`rf_years_vars') vertical ///
    coeflabels(rf_years_le_m4="<=-4" rf_years_m3="-3" rf_years_m2="-2" ///
        rf_years_0="0" rf_years_p1="1" rf_years_p2="2" ///
        rf_years_p3="3" rf_years_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) ///
    yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Reduced form: pharmacy count, station-years exposure") ///
    xtitle("Years relative to reform; -1 omitted") ///
    ytitle("Coefficient on event time x instrument exposure") ///
    note("95% CIs; county-clustered SEs. Pretrend p-value reported in RTF table.", ///
        size(vsmall)) ///
    graphregion(color(white)) plotregion(color(white)) ///
    name(rf_event_years_count, replace)
graph export "$outdir\iv_rf_event_years_count.png", replace width(2400)

coefplot rf_years_ln, keep(`rf_years_vars') vertical ///
    coeflabels(rf_years_le_m4="<=-4" rf_years_m3="-3" rf_years_m2="-2" ///
        rf_years_0="0" rf_years_p1="1" rf_years_p2="2" ///
        rf_years_p3="3" rf_years_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) ///
    yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Reduced form: ln pharmacy count, station-years exposure") ///
    xtitle("Years relative to reform; -1 omitted") ///
    ytitle("Coefficient on event time x instrument exposure") ///
    note("95% CIs; county-clustered SEs. Pretrend p-value reported in RTF table.", ///
        size(vsmall)) ///
    graphregion(color(white)) plotregion(color(white)) ///
    name(rf_event_years_ln, replace)
graph export "$outdir\iv_rf_event_years_ln.png", replace width(2400)

* County mechanism TWFE: unique pharmacies within and beyond 2 km
eststo clear
eststo mech_pharm_le2km: reghdfe pharm_nearest_pub_le2km post_policy ln_pop ln_nl_mean if sample_county, ///
    absorb(county_id_num prov_id#year) vce(cluster county_id_num)
eststo mech_pharm_gt2km: reghdfe pharm_nearest_pub_gt2km post_policy ln_pop ln_nl_mean if sample_county, ///
    absorb(county_id_num prov_id#year) vce(cluster county_id_num)
esttab mech_pharm_le2km mech_pharm_gt2km using "$outdir\twfe_mechanism_pharmacy_2km.rtf", replace ///
    label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons ///
    keep(post_policy ln_pop ln_nl_mean) mtitles("<=2km" ">2km") ///
    stats(N r2_within, labels("Observations" "Within R-squared")) ///
    title("County TWFE mechanism: unique pharmacies by 2 km threshold")

* Distance-threshold robustness: unique pharmacies within 500 m and 1 km
eststo clear
eststo rob_pharm_le500m: reghdfe pharm_nearest_pub_le500m post_policy ln_pop ln_nl_mean if sample_county, ///
    absorb(county_id_num prov_id#year) vce(cluster county_id_num)
eststo rob_pharm_le1km: reghdfe pharm_nearest_pub_le1km post_policy ln_pop ln_nl_mean if sample_county, ///
    absorb(county_id_num prov_id#year) vce(cluster county_id_num)
esttab rob_pharm_le500m rob_pharm_le1km using "$outdir\twfe_mechanism_distance_robustness.rtf", replace ///
    label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons ///
    keep(post_policy ln_pop ln_nl_mean) mtitles("<=500m" "<=1km") ///
    stats(N r2_within, labels("Observations" "Within R-squared")) ///
    title("County TWFE robustness: alternative near-hospital thresholds")

* County TWFE event studies: pharmacy outcomes only
eststo clear
eststo evt_total_pharm_count: reghdfe county_pharmacy_count ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4 ln_pop ln_nl_mean if sample_county, absorb(county_id_num prov_id#year) vce(cluster county_id_num)
test ev_le_m4 ev_m3 ev_m2
estadd scalar pretrend_p = r(p)
eststo evt_total_pharm_ln: reghdfe ln_county_pharmacy_count ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4 ln_pop ln_nl_mean if sample_county, absorb(county_id_num prov_id#year) vce(cluster county_id_num)
test ev_le_m4 ev_m3 ev_m2
estadd scalar pretrend_p = r(p)
esttab evt_total_pharm_count evt_total_pharm_ln using "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\twfe_event_county_pharmacy.rtf", replace ///
    label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons keep(ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4) ///
    mtitles("Pharmacy count" "ln pharmacy count") stats(N r2_within pretrend_p, labels("Observations" "Within R-squared" "Pretrend p-value")) ///
    title("County TWFE event: county-wide pharmacy outcomes")

coefplot evt_total_pharm_count, keep(ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4) vertical ///
    coeflabels(ev_le_m4="<=-4" ev_m3="-3" ev_m2="-2" ev_0="0" ev_p1="1" ev_p2="2" ev_p3="3" ev_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("County TWFE event: pharmacy count") xtitle("Years relative to reform; -1 omitted") ytitle("Coefficient") ///
    graphregion(color(white)) plotregion(color(white)) name(evt_total_pharm_count, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\twfe_event_county_pharmacy_count.png", replace width(2200)


coefplot evt_total_pharm_ln, keep(ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4) vertical ///
    coeflabels(ev_le_m4="<=-4" ev_m3="-3" ev_m2="-2" ev_0="0" ev_p1="1" ev_p2="2" ev_p3="3" ev_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("County TWFE event: ln pharmacy count") xtitle("Years relative to reform; -1 omitted") ytitle("Coefficient") ///
    graphregion(color(white)) plotregion(color(white)) name(evt_total_pharm_ln, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\twfe_event_county_pharmacy_ln.png", replace width(2200)



* County TWFE mechanism event studies: <=2km and >2km
eststo clear
eststo evt_mech_le2km: reghdfe pharm_nearest_pub_le2km ///
    ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4 ///
    ln_pop ln_nl_mean if sample_county, ///
    absorb(county_id_num prov_id#year) vce(cluster county_id_num)
test ev_le_m4 ev_m3 ev_m2
estadd scalar pretrend_p = r(p)
coefplot evt_mech_le2km, keep(ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4) vertical ///
    coeflabels(ev_le_m4="<=-4" ev_m3="-3" ev_m2="-2" ev_0="0" ev_p1="1" ev_p2="2" ev_p3="3" ev_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) ///
    recast(scatter) ciopts(recast(rcap)) ///
    title("County TWFE event: unique pharmacies <=2km") ///
    xtitle("Years relative to reform; -1 omitted") ytitle("Coefficient") ///
    graphregion(color(white)) plotregion(color(white)) name(evt_mech_le2km, replace)
graph export "$outdir\twfe_event_mechanism_le2km.png", replace width(2200)

eststo evt_mech_gt2km: reghdfe pharm_nearest_pub_gt2km ///
    ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4 ///
    ln_pop ln_nl_mean if sample_county, ///
    absorb(county_id_num prov_id#year) vce(cluster county_id_num)
test ev_le_m4 ev_m3 ev_m2
estadd scalar pretrend_p = r(p)
coefplot evt_mech_gt2km, keep(ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4) vertical ///
    coeflabels(ev_le_m4="<=-4" ev_m3="-3" ev_m2="-2" ev_0="0" ev_p1="1" ev_p2="2" ev_p3="3" ev_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) ///
    recast(scatter) ciopts(recast(rcap)) ///
    title("County TWFE event: unique pharmacies >2km") ///
    xtitle("Years relative to reform; -1 omitted") ytitle("Coefficient") ///
    graphregion(color(white)) plotregion(color(white)) name(evt_mech_gt2km, replace)
graph export "$outdir\twfe_event_mechanism_gt2km.png", replace width(2200)

esttab evt_mech_le2km evt_mech_gt2km using "$outdir\twfe_event_mechanism_pharmacy_2km.rtf", replace ///
    label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons ///
    keep(ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4) ///
    mtitles("<=2km" ">2km") ///
    stats(N r2_within pretrend_p, labels("Observations" "Within R-squared" "Pretrend p-value")) ///
    title("County TWFE event: unique pharmacies by 2 km threshold")

*===============================================================================
* PPMLHDFE: pharmacy counts
* Retains zero-count observations and estimates proportional effects.
* Fixed effects and clustering match the preferred county TWFE specification.
*===============================================================================

capture which ppmlhdfe
if _rc {
    di as error "PPML regressions require ppmlhdfe."
    di as error "Install it once with: ssc install ppmlhdfe"
    exit 111
}

local ppml_event_vars ///
    ev_le_m4 ev_m3 ev_m2 ///
    ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4

****************************************************
* PPML main effects
****************************************************

* County-wide pharmacy count
eststo clear
eststo ppml_total_count: ppmlhdfe ///
    county_pharmacy_count post_policy ln_pop ln_nl_mean ///
    if sample_county, ///
    absorb(county_id_num prov_id#year) ///
    vce(cluster county_id_num)

esttab ppml_total_count using ///
    "$outdir\ppml_main_county_pharmacy_count.rtf", ///
    replace label se b(%9.3f) ///
    star(* 0.10 ** 0.05 *** 0.01) ///
    nocons keep(post_policy ln_pop ln_nl_mean) ///
    stats(N, labels("Observations")) ///
    title("County PPMLHDFE: Total Pharmacy Count")

* Mechanism outcomes: unique pharmacies within and beyond 2 km
eststo clear
eststo ppml_mech_le2km: ppmlhdfe ///
    pharm_nearest_pub_le2km post_policy ln_pop ln_nl_mean if sample_county, ///
    absorb(county_id_num prov_id#year) vce(cluster county_id_num)
eststo ppml_mech_gt2km: ppmlhdfe ///
    pharm_nearest_pub_gt2km post_policy ln_pop ln_nl_mean if sample_county, ///
    absorb(county_id_num prov_id#year) vce(cluster county_id_num)
esttab ppml_mech_le2km ppml_mech_gt2km using ///
    "$outdir\ppml_mechanism_pharmacy_2km.rtf", ///
    replace label se b(%9.3f) ///
    star(* 0.10 ** 0.05 *** 0.01) ///
    nocons keep(post_policy ln_pop ln_nl_mean) ///
    mtitles("<=2km" ">2km") ///
    stats(N, labels("Observations")) ///
    title("County PPMLHDFE mechanism: unique pharmacies by 2 km threshold")

* Distance-threshold robustness: within 500 m and 1 km
eststo clear
eststo ppml_rob_le500m: ppmlhdfe ///
    pharm_nearest_pub_le500m post_policy ln_pop ln_nl_mean if sample_county, ///
    absorb(county_id_num prov_id#year) vce(cluster county_id_num)
eststo ppml_rob_le1km: ppmlhdfe ///
    pharm_nearest_pub_le1km post_policy ln_pop ln_nl_mean if sample_county, ///
    absorb(county_id_num prov_id#year) vce(cluster county_id_num)
esttab ppml_rob_le500m ppml_rob_le1km using ///
    "$outdir\ppml_mechanism_distance_robustness.rtf", ///
    replace label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) ///
    nocons keep(post_policy ln_pop ln_nl_mean) mtitles("<=500m" "<=1km") ///
    stats(N, labels("Observations")) ///
    title("County PPMLHDFE robustness: alternative near-hospital thresholds")

****************************************************
* PPML event studies
* Event time -1 is the omitted reference period.
****************************************************

* County-wide pharmacy count
eststo clear
eststo ppml_evt_total_count: ppmlhdfe ///
    county_pharmacy_count `ppml_event_vars' ln_pop ln_nl_mean ///
    if sample_county, ///
    absorb(county_id_num prov_id#year) ///
    vce(cluster county_id_num)

capture noisily test ev_le_m4 ev_m3 ev_m2
if !_rc {
    estadd scalar pretrend_p = r(p)
}
else {
    estadd scalar pretrend_p = .
}

esttab ppml_evt_total_count using ///
    "$outdir\ppml_event_county_pharmacy_count.rtf", ///
    replace label se b(%9.3f) ///
    star(* 0.10 ** 0.05 *** 0.01) nocons ///
    keep(`ppml_event_vars', relax) ///
    stats(N pretrend_p, ///
        labels("Observations" "Pretrend p-value")) ///
    title("County PPMLHDFE Event Study: Total Pharmacy Count")

coefplot ppml_evt_total_count, ///
    keep(`ppml_event_vars') vertical ///
    coeflabels(ev_le_m4="<=-4" ev_m3="-3" ev_m2="-2" ///
        ev_0="0" ev_p1="1" ev_p2="2" ev_p3="3" ev_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) ///
    yline(0, lcolor(gs8)) recast(scatter) ///
    ciopts(recast(rcap)) ///
    title("County PPMLHDFE event: total pharmacy count") ///
    xtitle("Years relative to reform; -1 omitted") ///
    ytitle("Coefficient") ///
    graphregion(color(white)) plotregion(color(white)) ///
    name(ppml_evt_total_count, replace)

graph export ///
    "$outdir\ppml_event_county_pharmacy_count.png", ///
    replace width(2200)

* Mechanism outcomes: unique pharmacies within and beyond 2 km
eststo clear
foreach side in le2km gt2km {
    eststo ppml_evt_`side': ppmlhdfe ///
        pharm_nearest_pub_`side' ///
        `ppml_event_vars' ln_pop ln_nl_mean if sample_county, ///
        absorb(county_id_num prov_id#year) ///
        vce(cluster county_id_num)

    capture noisily test ev_le_m4 ev_m3 ev_m2
    if !_rc {
        estadd scalar pretrend_p = r(p)
    }
    else {
        estadd scalar pretrend_p = .
    }

    coefplot ppml_evt_`side', ///
        keep(`ppml_event_vars') vertical ///
        coeflabels(ev_le_m4="<=-4" ev_m3="-3" ev_m2="-2" ///
            ev_0="0" ev_p1="1" ev_p2="2" ///
            ev_p3="3" ev_ge_p4=">=4") ///
        xline(3.5, lcolor(red) lpattern(dash)) ///
        yline(0, lcolor(gs8)) recast(scatter) ///
        ciopts(recast(rcap)) ///
        title("County PPMLHDFE event: pharmacies `side'") ///
        xtitle("Years relative to reform; -1 omitted") ///
        ytitle("Coefficient") ///
        graphregion(color(white)) plotregion(color(white)) ///
        name(ppml_evt_`side', replace)

    graph export ///
        "$outdir\ppml_event_mechanism_`side'.png", ///
        replace width(2000)
}

esttab ///
    ppml_evt_le2km ppml_evt_gt2km using ///
    "$outdir\ppml_event_mechanism_pharmacy_2km.rtf", ///
    replace label se b(%9.3f) ///
    star(* 0.10 ** 0.05 *** 0.01) nocons ///
    keep(`ppml_event_vars', relax) ///
    mtitles("<=2km" ">2km") ///
    stats(N pretrend_p, ///
        labels("Observations" "Pretrend p-value")) ///
    title("County PPMLHDFE event: unique pharmacies by 2 km threshold")

* County-wide CSDID: pharmacy outcomes only
eststo clear
csdid county_pharmacy_count ln_pop ln_nl_mean if sample_county, ivar(county_id_num) time(year) gvar(g_csdid) method(dripw) notyet vce(cluster county_id_num)
capture noisily estat pretrend
estat simple, estore(cst_pharm_count)

estat event, window(-4 4) estore(cse_total_pharm_count)

csdid ln_county_pharmacy_count ln_pop ln_nl_mean if sample_county, ivar(county_id_num) time(year) gvar(g_csdid) method(dripw) notyet vce(cluster county_id_num)
capture noisily estat pretrend
estat simple, estore(cst_pharm_ln)

estat event, window(-4 4) estore(cse_total_pharm_ln)
esttab cst_pharm_count cst_pharm_ln using "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\csdid_att_county_pharmacy.rtf", replace ///
    se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons keep(ATT) mtitles("Pharmacy count" "ln pharmacy count") ///
    title("County CSDID ATT: county-wide pharmacy outcomes")
esttab cse_total_pharm_count cse_total_pharm_ln using "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\csdid_event_county_pharmacy.rtf", replace ///
    se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons ///
    keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4, relax) ///
    mtitles("Pharmacy count" "ln pharmacy count") ///
    title("County CSDID event: county-wide pharmacy outcomes")

coefplot cse_total_pharm_count, keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4) vertical ///
    coeflabels(Tm4="-4" Tm3="-3" Tm2="-2" Tp0="0" Tp1="1" Tp2="2" Tp3="3" Tp4="4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("County CSDID event: pharmacy count") xtitle("Years relative to reform; -1 omitted") ytitle("ATT") ///
    graphregion(color(white)) plotregion(color(white)) name(cse_county_pharm_count, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\csdid_event_county_pharmacy_count.png", replace width(2200)

coefplot cse_total_pharm_ln, keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4) vertical ///
    coeflabels(Tm4="-4" Tm3="-3" Tm2="-2" Tp0="0" Tp1="1" Tp2="2" Tp3="3" Tp4="4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("County CSDID event: ln pharmacy count") xtitle("Years relative to reform; -1 omitted") ytitle("ATT") ///
    graphregion(color(white)) plotregion(color(white)) name(cse_county_pharm_ln, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\csdid_event_county_pharmacy_ln.png", replace width(2200)

graph combine cse_county_pharm_count cse_county_pharm_ln, cols(2) imargin(tiny) ///
    title("County-wide pharmacy outcomes: CSDID event studies") ///
    graphregion(color(white)) name(csdid_evt_county_combined, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\csdid_event_county_pharmacy_combined.png", replace width(3200)

* County CSDID mechanism: unique pharmacies within and beyond 2 km
eststo clear
csdid pharm_nearest_pub_le2km ln_pop ln_nl_mean if sample_county, ///
    ivar(county_id_num) time(year) gvar(g_csdid) ///
    method(dripw) notyet vce(cluster county_id_num)
capture noisily estat pretrend
estat simple, estore(cs_mech_le2km)
estat event, window(-4 4) estore(cse_mech_le2km)
coefplot cse_mech_le2km, keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4) vertical ///
    coeflabels(Tm4="-4" Tm3="-3" Tm2="-2" Tp0="0" Tp1="1" Tp2="2" Tp3="3" Tp4="4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) ///
    recast(scatter) ciopts(recast(rcap)) ///
    title("County CSDID event: unique pharmacies <=2km") ///
    xtitle("Years relative to reform; -1 omitted") ytitle("ATT") ///
    graphregion(color(white)) plotregion(color(white)) name(cse_mech_le2km, replace)
graph export "$outdir\csdid_event_mechanism_le2km.png", replace width(2200)

csdid pharm_nearest_pub_gt2km ln_pop ln_nl_mean if sample_county, ///
    ivar(county_id_num) time(year) gvar(g_csdid) ///
    method(dripw) notyet vce(cluster county_id_num)
capture noisily estat pretrend
estat simple, estore(cs_mech_gt2km)
estat event, window(-4 4) estore(cse_mech_gt2km)
coefplot cse_mech_gt2km, keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4) vertical ///
    coeflabels(Tm4="-4" Tm3="-3" Tm2="-2" Tp0="0" Tp1="1" Tp2="2" Tp3="3" Tp4="4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) ///
    recast(scatter) ciopts(recast(rcap)) ///
    title("County CSDID event: unique pharmacies >2km") ///
    xtitle("Years relative to reform; -1 omitted") ytitle("ATT") ///
    graphregion(color(white)) plotregion(color(white)) name(cse_mech_gt2km, replace)
graph export "$outdir\csdid_event_mechanism_gt2km.png", replace width(2200)

esttab cs_mech_le2km cs_mech_gt2km using "$outdir\csdid_att_mechanism_pharmacy_2km.rtf", replace ///
    se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons keep(ATT) ///
    mtitles("<=2km" ">2km") ///
    title("County CSDID ATT: unique pharmacies by 2 km threshold")
esttab cse_mech_le2km cse_mech_gt2km using "$outdir\csdid_event_mechanism_pharmacy_2km.rtf", replace ///
    se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons ///
    keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4, relax) ///
    mtitles("<=2km" ">2km") ///
    title("County CSDID event: unique pharmacies by 2 km threshold")

* CSDID distance-threshold robustness: <=500m and <=1km, ATT only
eststo clear
csdid pharm_nearest_pub_le500m ln_pop ln_nl_mean if sample_county, ///
    ivar(county_id_num) time(year) gvar(g_csdid) ///
    method(dripw) notyet vce(cluster county_id_num)
estat simple, estore(cs_rob_le500m)
csdid pharm_nearest_pub_le1km ln_pop ln_nl_mean if sample_county, ///
    ivar(county_id_num) time(year) gvar(g_csdid) ///
    method(dripw) notyet vce(cluster county_id_num)
estat simple, estore(cs_rob_le1km)
esttab cs_rob_le500m cs_rob_le1km using "$outdir\csdid_att_mechanism_distance_robustness.rtf", replace ///
    se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons keep(ATT) ///
    mtitles("<=500m" "<=1km") ///
    title("County CSDID robustness: alternative near-hospital thresholds")

*===============================================================================
* Sun and Abraham (2021) interaction-weighted event studies
* Reference design: Pharmaceutical Reform and Provider Supply (2025), Figure 2.
* Event window is <=-5, -4, -3, -2, omitted -1, 0, 1, 2, and >=3.
* The estimation sample is balanced over 2012-2019 and uses never-treated
* counties as the control cohort. All confidence intervals are 95 percent and
* standard errors are clustered by county.
*===============================================================================
gen int cohort_sa = policy_year if merge_policy == 3 & policy_year > 2012
gen byte never_sa = merge_policy == 1
bysort county_id_num: egen byte sa_periods = total(sample_county)

* Counties treated in 2012 have no observed t=-1 period because the panel
* begins in 2012. Exclude this left-censored cohort from the Sun-Abraham
* sample; do not reclassify it as never treated.
gen byte sample_sa = sample_county & sa_periods == 8 ///
    & (never_sa == 1 | !missing(cohort_sa))

assert missing(cohort_sa) if never_sa == 1
assert !missing(cohort_sa) | never_sa == 1 if sample_sa

gen byte sa_le_m5 = (rel <= -5) if sample_sa & !missing(cohort_sa)
gen byte sa_m4 = (rel == -4) if sample_sa & !missing(cohort_sa)
gen byte sa_m3 = (rel == -3) if sample_sa & !missing(cohort_sa)
gen byte sa_m2 = (rel == -2) if sample_sa & !missing(cohort_sa)
gen byte sa_p0 = (rel == 0) if sample_sa & !missing(cohort_sa)
gen byte sa_p1 = (rel == 1) if sample_sa & !missing(cohort_sa)
gen byte sa_p2 = (rel == 2) if sample_sa & !missing(cohort_sa)
gen byte sa_ge_p3 = (rel >= 3) if sample_sa & !missing(cohort_sa)
foreach variable in sa_le_m5 sa_m4 sa_m3 sa_m2 sa_p0 sa_p1 sa_p2 sa_ge_p3 {
    replace `variable' = 0 if sample_sa & never_sa == 1
}

quietly count if sample_sa
di as result "Sun-Abraham balanced-sample observations: " r(N)
egen byte tag_sa_county = tag(county_id_num) if sample_sa
quietly count if tag_sa_county == 1
di as result "Sun-Abraham balanced-sample counties: " r(N)
drop tag_sa_county

capture program drop sa_event_graph
program define sa_event_graph, eclass
    version 17
    syntax varname(numeric), STEM(name)
    local outcome `varlist'
    local outcome_label : variable label `outcome'
    if `"`outcome_label'"' == "" local outcome_label "`outcome'"

    quietly eventstudyinteract `outcome' ///
        sa_le_m5 sa_m4 sa_m3 sa_m2 sa_p0 sa_p1 sa_p2 sa_ge_p3 ///
        if sample_sa, cohort(cohort_sa) control_cohort(never_sa) ///
        covariates(ln_pop ln_nl_mean) absorb(county_id_num prov_id#year) ///
        vce(cluster county_id_num)

    tempname sa_b sa_V sa_se sa_plot
    matrix `sa_b' = e(b_iw)
    matrix `sa_V' = e(V_iw)
    matrix `sa_se' = J(1, colsof(`sa_b'), .)
    forvalues column = 1/`=colsof(`sa_b')' {
        matrix `sa_se'[1, `column'] = sqrt(`sa_V'[`column', `column'])
    }
    local coefficient_names : colnames `sa_b'
    matrix colnames `sa_se' = `coefficient_names'
    matrix `sa_plot' = `sa_b' \ `sa_se'

    ereturn post `sa_b' `sa_V'
    capture noisily test sa_le_m5 sa_m4 sa_m3 sa_m2
    if !_rc di as result "Sun-Abraham pretrend p-value (`outcome'): " %6.4f r(p)

    quietly reghdfe `outcome' ///
        sa_le_m5 sa_m4 sa_m3 sa_m2 sa_p0 sa_p1 sa_p2 sa_ge_p3 ///
        ln_pop ln_nl_mean if sample_sa, ///
        absorb(county_id_num prov_id#year) vce(cluster county_id_num)
    estimates store __twfe_sa

    coefplot ///
        (matrix(`sa_plot'[1]), se(`sa_plot'[2]) label("Sun and Abraham (2021)") ///
            msymbol(Dh) mcolor(forest_green) ciopts(recast(rcap) lcolor(forest_green))) ///
        (__twfe_sa, label("TWFE") msymbol(plus) mcolor(black) ///
            ciopts(recast(rcap) lcolor(black))), ///
        keep(sa_le_m5 sa_m4 sa_m3 sa_m2 sa_p0 sa_p1 sa_p2 sa_ge_p3) ///
        order(sa_le_m5 sa_m4 sa_m3 sa_m2 sa_p0 sa_p1 sa_p2 sa_ge_p3) ///
        relocate(sa_le_m5=1 sa_m4=2 sa_m3=3 sa_m2=4 ///
            sa_p0=6 sa_p1=7 sa_p2=8 sa_ge_p3=9) ///
        coeflabels(sa_le_m5="<=-5" sa_m4="-4" sa_m3="-3" sa_m2="-2" ///
            sa_p0="0" sa_p1="1" sa_p2="2" sa_ge_p3=">=3") ///
        vertical xline(5.5, lcolor(gs7) lpattern(dash)) ///
        yline(0, lcolor(gs8)) xlabel(1 "<=-5" 2 "-4" 3 "-3" 4 "-2" ///
            5 "-1" 6 "0" 7 "1" 8 "2" 9 ">=3") ///
        ylabel(, angle(0) grid glcolor(gs14)) ///
        xtitle("Years relative to reform; -1 omitted") ytitle("Coefficient") ///
        title("`outcome_label'", size(medsmall)) ///
        subtitle("Sun-Abraham interaction-weighted event study", size(small)) ///
        note("95% confidence intervals; county-clustered standard errors.", size(vsmall)) ///
        legend(order(2 "Sun and Abraham (2021)" 4 "TWFE") rows(1) position(6)) ///
        graphregion(color(white)) plotregion(color(white)) ///
        name(`stem', replace)

    graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid/`stem'.png", replace width(2400)
    graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid/`stem'.pdf", replace
    estimates drop __twfe_sa
end

* County-wide main outcomes
sa_event_graph county_pharmacy_count, stem(sa_county_pharm_count)
sa_event_graph ln_county_pharmacy_count, stem(sa_county_pharm_ln)
graph combine sa_county_pharm_count sa_county_pharm_ln, cols(2) imargin(tiny) ///
    title("County-wide pharmacy outcomes: Sun-Abraham event studies") ///
    graphregion(color(white)) name(sa_county_pharm_combined, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\sa_county_pharm_combined.png", replace width(3200)
graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\sa_county_pharm_combined.pdf", replace

* Mechanism outcomes: mutually exclusive 2km groups
sa_event_graph pharm_nearest_pub_le2km, stem(sa_mech_le2km)
sa_event_graph pharm_nearest_pub_gt2km, stem(sa_mech_gt2km)
graph combine sa_mech_le2km sa_mech_gt2km, cols(2) imargin(tiny) ///
    title("County pharmacy location: Sun-Abraham event studies") ///
    graphregion(color(white)) name(sa_mech_2km_combined, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\sa_mechanism_pharmacy_2km_combined.png", replace width(3400)
graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\sa_mechanism_pharmacy_2km_combined.pdf", replace

*===============================================================================
* Multi-estimator event-study comparison, following the layout of Figure 2
* Sun-Abraham; Cengiz et al.; Borusyak-Jaravel-Spiess;
* Callaway-Sant'Anna; and conventional TWFE.
* Exact event periods -5 through +3 are used so all methods share one x-axis.
*===============================================================================
gen byte cmp_m5 = (rel == -5) if sample_sa & !missing(cohort_sa)
gen byte cmp_m4 = (rel == -4) if sample_sa & !missing(cohort_sa)
gen byte cmp_m3 = (rel == -3) if sample_sa & !missing(cohort_sa)
gen byte cmp_m2 = (rel == -2) if sample_sa & !missing(cohort_sa)
gen byte cmp_p0 = (rel == 0) if sample_sa & !missing(cohort_sa)
gen byte cmp_p1 = (rel == 1) if sample_sa & !missing(cohort_sa)
gen byte cmp_p2 = (rel == 2) if sample_sa & !missing(cohort_sa)
gen byte cmp_p3 = (rel == 3) if sample_sa & !missing(cohort_sa)
foreach variable in cmp_m5 cmp_m4 cmp_m3 cmp_m2 cmp_p0 cmp_p1 cmp_p2 cmp_p3 {
    replace `variable' = 0 if sample_sa & never_sa == 1
}

capture program drop multi_event_graph
program define multi_event_graph, eclass
    version 17
    syntax varname(numeric), STEM(name)
    local outcome `varlist'
    local outcome_label : variable label `outcome'
    if `"`outcome_label'"' == "" local outcome_label "`outcome'"
    local event_names "event_m5 event_m4 event_m3 event_m2 event_m1 event_p0 event_p1 event_p2 event_p3"
    local pre_dummies "cmp_m5 cmp_m4 cmp_m3 cmp_m2"
    local post_dummies "cmp_p0 cmp_p1 cmp_p2 cmp_p3"

    tempname b_sa se_sa raw_b_sa raw_V_sa ///
        b_cengiz se_cengiz b_bjs se_bjs ///
        b_cs se_cs b_twfe se_twfe
    foreach matrix_name in b_sa se_sa b_cengiz se_cengiz b_bjs se_bjs ///
        b_cs se_cs b_twfe se_twfe {
        matrix ``matrix_name'' = J(1, 9, .)
        matrix colnames ``matrix_name'' = `event_names'
    }
    foreach matrix_name in b_sa se_sa b_cengiz se_cengiz b_twfe se_twfe {
        matrix ``matrix_name''[1, 5] = 0
    }

    * Sun and Abraham (2021): interaction-weighted cohort effects
    quietly eventstudyinteract `outcome' `pre_dummies' `post_dummies' ///
        if sample_sa, cohort(cohort_sa) control_cohort(never_sa) ///
        covariates(ln_pop ln_nl_mean) absorb(county_id_num year) ///
        vce(cluster county_id_num)
    matrix `raw_b_sa' = e(b_iw)
    matrix `raw_V_sa' = e(V_iw)
    local position = 1
    foreach coefficient of local pre_dummies {
        local source_column = colnumb(`raw_b_sa', "`coefficient'")
        matrix `b_sa'[1, `position'] = `raw_b_sa'[1, `source_column']
        matrix `se_sa'[1, `position'] = sqrt(`raw_V_sa'[`source_column', `source_column'])
        local position = `position' + 1
    }
    local position = 6
    foreach coefficient of local post_dummies {
        local source_column = colnumb(`raw_b_sa', "`coefficient'")
        matrix `b_sa'[1, `position'] = `raw_b_sa'[1, `source_column']
        matrix `se_sa'[1, `position'] = sqrt(`raw_V_sa'[`source_column', `source_column'])
        local position = `position' + 1
    }

    * Cengiz et al. (2019): stacked cohort-specific event studies
    preserve
        keep if sample_sa
        quietly stackedev `outcome' `pre_dummies' `post_dummies', ///
            cohort(cohort_sa) time(year) never_treat(never_sa) ///
            unit_fe(county_id_num) clust_unit(county_id_num) ///
            covariates(ln_pop ln_nl_mean)
        local position = 1
        foreach coefficient of local pre_dummies {
            matrix `b_cengiz'[1, `position'] = _b[`coefficient']
            matrix `se_cengiz'[1, `position'] = _se[`coefficient']
            local position = `position' + 1
        }
        local position = 6
        foreach coefficient of local post_dummies {
            matrix `b_cengiz'[1, `position'] = _b[`coefficient']
            matrix `se_cengiz'[1, `position'] = _se[`coefficient']
            local position = `position' + 1
        }
    restore

    * Borusyak, Jaravel, and Spiess (2021): imputation estimator
    preserve
        quietly did_imputation `outcome' county_id_num year cohort_sa if sample_sa, ///
            horizons(0/3) pretrends(5) autosample minn(0) ///
            controls(ln_pop ln_nl_mean) fe(county_id_num year) ///
            cluster(county_id_num) tol(0.001) maxit(2000)
        local position = 1
        forvalues lead = 5(-1)1 {
            matrix `b_bjs'[1, `position'] = _b[pre`lead']
            matrix `se_bjs'[1, `position'] = _se[pre`lead']
            local position = `position' + 1
        }
        local position = 6
        forvalues lag = 0/3 {
            matrix `b_bjs'[1, `position'] = _b[tau`lag']
            matrix `se_bjs'[1, `position'] = _se[tau`lag']
            local position = `position' + 1
        }
    restore

    * Callaway and Sant'Anna (2021): doubly robust group-time ATT
    preserve
        capture estimates drop __cs_event
        quietly csdid `outcome' ln_pop ln_nl_mean if sample_sa, ///
            ivar(county_id_num) time(year) gvar(g_csdid) ///
            method(dripw) notyet vce(cluster county_id_num)
        quietly estat event, window(-5 3) estore(__cs_event)
        estimates restore __cs_event
        local position = 1
        forvalues lead = 5(-1)1 {
            capture matrix `b_cs'[1, `position'] = _b[Tm`lead']
            if !_rc {
                matrix `se_cs'[1, `position'] = _se[Tm`lead']
            }
            local position = `position' + 1
        }
        local position = 6
        forvalues lag = 0/3 {
            capture matrix `b_cs'[1, `position'] = _b[Tp`lag']
            if !_rc {
                matrix `se_cs'[1, `position'] = _se[Tp`lag']
            }
            local position = `position' + 1
        }
        estimates drop __cs_event
    restore

    * Conventional TWFE, with event time -1 normalized to zero
    quietly reghdfe `outcome' `pre_dummies' `post_dummies' ///
        ln_pop ln_nl_mean if sample_sa, ///
        absorb(county_id_num year) vce(cluster county_id_num)
    local position = 1
    foreach coefficient of local pre_dummies {
        matrix `b_twfe'[1, `position'] = _b[`coefficient']
        matrix `se_twfe'[1, `position'] = _se[`coefficient']
        local position = `position' + 1
    }
    local position = 6
    foreach coefficient of local post_dummies {
        matrix `b_twfe'[1, `position'] = _b[`coefficient']
        matrix `se_twfe'[1, `position'] = _se[`coefficient']
        local position = `position' + 1
    }

    coefplot ///
        (matrix(`b_sa'), se(`se_sa') label("Sun and Abraham (2021)") ///
            offset(-0.24) msymbol(Dh) mcolor(forest_green) ///
            ciopts(recast(rcap) lcolor(forest_green) lwidth(vthin))) ///
        (matrix(`b_cengiz'), se(`se_cengiz') label("Cengiz et al. (2019)") ///
            offset(-0.12) msymbol(Th) mcolor(navy) ///
            ciopts(recast(rcap) lcolor(navy) lwidth(vthin))) ///
        (matrix(`b_bjs'), se(`se_bjs') label("Borusyak et al. (2021)") ///
            offset(0) msymbol(O) mcolor(red) ///
            ciopts(recast(rcap) lcolor(red) lwidth(vthin))) ///
        (matrix(`b_cs'), se(`se_cs') label("Callaway and Sant'Anna (2021)") ///
            offset(0.12) msymbol(X) mcolor(orange) ///
            ciopts(recast(rcap) lcolor(orange) lwidth(vthin))) ///
        (matrix(`b_twfe'), se(`se_twfe') label("TWFE") ///
            offset(0.24) msymbol(plus) mcolor(black) ///
            ciopts(recast(rcap) lcolor(black) lwidth(vthin))), ///
        keep(`event_names') order(`event_names') vertical ///
        coeflabels(event_m5="-5" event_m4="-4" event_m3="-3" event_m2="-2" ///
            event_m1="-1" event_p0="0" event_p1="1" event_p2="2" event_p3="3") ///
        xline(5.5, lcolor(gs7) lpattern(dash)) yline(0, lcolor(gs8)) ///
        ylabel(, angle(0) grid glcolor(gs14)) ///
        xtitle("Years relative to reform") ytitle("Coefficient") ///
        title("`outcome_label'", size(medsmall)) ///
        subtitle("Event-study estimates across staggered-DID methods", size(small)) ///
        note("95% confidence intervals; county-clustered standard errors; method-specific estimands.", size(tiny)) ///
        legend(order(2 "Sun and Abraham (2021)" 4 "Cengiz et al. (2019)" ///
            6 "Borusyak et al. (2021)" 8 "Callaway and Sant'Anna (2021)" ///
            10 "TWFE") cols(1) position(11) ring(0) size(vsmall)) ///
        graphregion(color(white)) plotregion(color(white)) ///
        name(`stem', replace)

    graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid/`stem'.png", replace width(2600)
    graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid/`stem'.pdf", replace
end

* County-wide outcomes: Figure 2-style five-estimator comparison
multi_event_graph county_pharmacy_count, stem(multi_county_pharm_count)
multi_event_graph ln_county_pharmacy_count, stem(multi_county_pharm_ln)
graph combine multi_county_pharm_count multi_county_pharm_ln, cols(2) imargin(tiny) ///
    title("County-wide pharmacy outcomes: multi-estimator event studies") ///
    graphregion(color(white)) name(multi_county_pharm_combined, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\multi_county_pharm_combined.png", replace width(3400)
graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\multi_county_pharm_combined.pdf", replace

* Mechanism outcomes: mutually exclusive 2km groups
multi_event_graph pharm_nearest_pub_le2km, stem(multi_mech_le2km)
multi_event_graph pharm_nearest_pub_gt2km, stem(multi_mech_gt2km)
graph combine multi_mech_le2km multi_mech_gt2km, cols(2) imargin(tiny) ///
    title("County pharmacy location: multi-estimator event studies") ///
    graphregion(color(white)) name(multi_mech_2km_combined, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\multi_mechanism_pharmacy_2km_combined.png", replace width(3600)
graph export "D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid\multi_mechanism_pharmacy_2km_combined.pdf", replace

di as result "County analyses completed successfully."
di as result "Mechanism outcomes: unique geocoded pharmacies within and beyond 2km of public hospitals."
di as result "Distance robustness outcomes: unique geocoded pharmacies within 500m and 1km."
di as result "Sun-Abraham event-study graphs: PNG and PDF formats."
di as result "Multi-estimator event-study graphs: Sun-Abraham, Cengiz, Borusyak, Callaway-Sant'Anna, and TWFE."
di as result "Outputs: D:\Hospital_Pharmacy program\output\regression\county_v2_ln_event_csdid"
log close
