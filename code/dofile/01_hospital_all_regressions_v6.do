*===============================================================================
* 01_hospital_v3.do
*This do file is to  baseline regress Pharmaceutical Reform on Pharmacies in hospital level****
* setting
clear
cd "D:\Hospital_Pharmacy program\data\hospital_pharmacy\hosp_pharm_panel"
set linesize 255
set more off
cap log close 
log using ".\paper_`c(current_date)'.log", replace text

*===============================================================================

use ".\hospital_pharm_panel.dta", clear

destring county_id, gen(county_id_num)
gen long prov_id = floor(county_id / 10000) if !missing(county_id)
gen long city_id = floor(county_id / 100) if !missing(county_id)
gen byte public_num = (public_flag == 1) if !missing(public_flag)
gen byte post= (year >policy_year) if !missing(year, policy_year)
gen byte ddd = public_num * post if !missing(public_num, post)

gen int rel = year - policy_year if !missing(year, policy_year)

gen ln_pharm_500m = ln(pharm_500m) if pharm_500m > 0 & !missing(pharm_500m)
gen ln_pharm_1km = ln(pharm_1km) if pharm_1km > 0 & !missing(pharm_1km)
gen ln_pharm_2km = ln(pharm_2km) if pharm_2km > 0 & !missing(pharm_2km)

gen int g_csdid = policy_year if public_num == 1 & policy_year > 2012
replace g_csdid = 0 if public_num == 0
gen byte ev_le_m4 = public_num * (rel <= -4) if !missing(public_num, rel)
gen byte ev_m3 = public_num * (rel == -3) if !missing(public_num, rel)
gen byte ev_m2 = public_num * (rel == -2) if !missing(public_num, rel)
gen byte ev_0 = public_num * (rel == 0) if !missing(public_num, rel)
gen byte ev_p1 = public_num * (rel == 1) if !missing(public_num, rel)
gen byte ev_p2 = public_num * (rel == 2) if !missing(public_num, rel)
gen byte ev_p3 = public_num * (rel == 3) if !missing(public_num, rel)
gen byte ev_ge_p4 = public_num * (rel >= 4) if !missing(public_num, rel)


*descriptive statistics for the three hospital buffer outcomes
eststo clear
estpost tabstat pharm_2km pharm_1km pharm_500m ///
    ln_ntl_mean_2km ln_ntl_mean_1km ln_ntl_mean_500m ///
    public_flag private_flag policy_year, ///
    statistics(n mean sd min max) columns(statistics)
tempname hospital_desc_obs
matrix `hospital_desc_obs' = e(count)
estadd matrix observations = `hospital_desc_obs'
esttab using ".\hospital_buffer_descriptive_statistics.rtf", ///
    replace label nonumber noobs nomtitles ///
    cells("observations(fmt(%12.0fc)) mean(fmt(%12.3fc)) sd(fmt(%12.3fc)) min(fmt(%12.3fc)) max(fmt(%12.3fc))") ///
    collabels("Observations" "Mean" "SD" "Min" "Max") ///
    title("Hospital-buffer descriptive statistics")

*===============================================================================
******TWFE*****
*===============================================================================

eststo clear
qui eststo: reghdfe pharm_500m ddd post ln_ntl_mean_500m , absorb(hospital_id year) vce(cluster county_id)
qui eststo: reghdfe pharm_1km ddd post ln_ntl_mean_1km, absorb(hospital_id year) vce(cluster county_id)
qui eststo: reghdfe pharm_2km ddd post ln_ntl_mean_2km,absorb(hospital_id year) vce(cluster county_id)
esttab using ".\twfe_main_pharm_count.rtf", replace label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons keep(ddd post ln_ntl_mean*) ///
    mtitles("2km: main" "1km: robustness" "500m: robustness") title("Hospital TWFE: pharmacy count")

******省份-年份固定效应******
eststo clear
qui eststo: reghdfe pharm_500m ddd post ln_ntl_mean_500m , absorb(hospital_id prov_id#year) vce(cluster county_id)
qui eststo: reghdfe pharm_1km ddd post ln_ntl_mean_1km, absorb(hospital_id prov_id#year) vce(cluster county_id)
qui eststo: reghdfe pharm_2km ddd post ln_ntl_mean_2km,absorb(hospital_id prov_id#year) vce(cluster county_id)
esttab using ".\twfe_main_pharm_count2.rtf", replace label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons keep(ddd post ln_ntl_mean*) ///
    mtitles("2km: main" "1km: robustness" "500m: robustness") title("Hospital TWFE: pharmacy count")
	

*******ln pharmacy count******

eststo clear
qui eststo: reghdfe ln_pharm_500m ddd post ln_ntl_mean_500m , absorb(hospital_id year) vce(cluster county_id)
qui eststo: reghdfe ln_pharm_1km ddd post ln_ntl_mean_1km, absorb(hospital_id year) vce(cluster county_id)
qui eststo: reghdfe ln_pharm_2km ddd post ln_ntl_mean_2km,absorb(hospital_id year) vce(cluster county_id)
esttab using ".\twfe_main_ln_pharm_count.rtf", replace label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons keep(ddd post ln_ntl_mean*) ///
    mtitles("2km: main" "1km: robustness" "500m: robustness") title("Hospital TWFE: pharmacy count")

eststo clear
qui eststo: reghdfe ln_pharm_500m ddd post ln_ntl_mean_500m , absorb(hospital_id prov_id#year) vce(cluster county_id)
qui eststo: reghdfe ln_pharm_1km ddd post ln_ntl_mean_1km, absorb(hospital_id prov_id#year) vce(cluster county_id)
qui eststo: reghdfe ln_pharm_2km ddd post ln_ntl_mean_2km,absorb(hospital_id prov_id#year) vce(cluster county_id)
esttab using ".\twfe_main_ln_pharm_count2.rtf", replace label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons keep(ddd post ln_ntl_mean*) ///
    mtitles("2km: main" "1km: robustness" "500m: robustness") title("Hospital TWFE: pharmacy count")
	

*===============================================================================
* Pharmacy TWFE event studies: 2km primary, 1km/500m robustness
*===============================================================================

* Hospital TWFE event: pharmacy count
eststo clear
eststo twe_pharm_count_500m: reghdfe pharm_500m ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4 post_policy ln_ntl_mean_500m if sample_hospital, ///
    absorb(hospital_id year) vce(cluster county_id_num)
test ev_le_m4 ev_m3 ev_m2
estadd scalar pretrend_p = r(p)
coefplot twe_pharm_count_500m, keep(ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4) vertical ///
    coeflabels(ev_le_m4="<=-4" ev_m3="-3" ev_m2="-2" ev_0="0" ev_p1="1" ev_p2="2" ev_p3="3" ev_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Hospital TWFE event: pharmacy count, 500m") xtitle("Years relative to reform; -1 omitted") ytitle("Coefficient") name(twe_pharm_count_500m, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\hospital_v6\twfe_event_pharm_count_500m.png", replace width(2000)

eststo twe_pharm_count_1km: reghdfe pharm_1km ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4 post_policy ln_ntl_mean_1km if sample_hospital, ///
    absorb(hospital_id year) vce(cluster county_id_num)
test ev_le_m4 ev_m3 ev_m2
estadd scalar pretrend_p = r(p)
coefplot twe_pharm_count_1km, keep(ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4) vertical ///
    coeflabels(ev_le_m4="<=-4" ev_m3="-3" ev_m2="-2" ev_0="0" ev_p1="1" ev_p2="2" ev_p3="3" ev_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Hospital TWFE event: pharmacy count, 1km") xtitle("Years relative to reform; -1 omitted") ytitle("Coefficient") name(twe_pharm_count_1km, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\hospital_v6\twfe_event_pharm_count_1km.png", replace width(2000)

eststo twe_pharm_count_2km: reghdfe pharm_2km ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4 post_policy ln_ntl_mean_2km if sample_hospital, ///
    absorb(hospital_id year) vce(cluster county_id_num)
test ev_le_m4 ev_m3 ev_m2
estadd scalar pretrend_p = r(p)
coefplot twe_pharm_count_2km, keep(ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4) vertical ///
    coeflabels(ev_le_m4="<=-4" ev_m3="-3" ev_m2="-2" ev_0="0" ev_p1="1" ev_p2="2" ev_p3="3" ev_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Hospital TWFE event: pharmacy count, 2km") xtitle("Years relative to reform; -1 omitted") ytitle("Coefficient") name(twe_pharm_count_2km, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\hospital_v6\twfe_event_pharm_count_2km.png", replace width(2000)

esttab twe_pharm_count_2km twe_pharm_count_1km twe_pharm_count_500m using "D:\Hospital_Pharmacy program\output\regression\hospital_v6\twfe_event_pharm_count.rtf", replace ///
    label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons keep(ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4) ///
    mtitles("2km: main" "1km: robustness" "500m: robustness") stats(N r2_within pretrend_p, labels("Observations" "Within R-squared" "Pretrend p-value")) ///
    title("Hospital TWFE event study: pharmacy count")

* Hospital TWFE event: ln pharmacy count
eststo clear
eststo twe_pharm_ln_500m: reghdfe ln_pharm_500m ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4 post_policy ln_ntl_mean_500m if sample_hospital, ///
    absorb(hospital_id prov_id#year) vce(cluster county_id_num)
test ev_le_m4 ev_m3 ev_m2
estadd scalar pretrend_p = r(p)
coefplot twe_pharm_ln_500m, keep(ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4) vertical ///
    coeflabels(ev_le_m4="<=-4" ev_m3="-3" ev_m2="-2" ev_0="0" ev_p1="1" ev_p2="2" ev_p3="3" ev_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Hospital TWFE event: ln pharmacy count, 500m") xtitle("Years relative to reform; -1 omitted") ytitle("Coefficient") name(twe_pharm_ln_500m, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\hospital_v6\twfe_event_pharm_ln_500m.png", replace width(2000)

eststo twe_pharm_ln_1km: reghdfe ln_pharm_1km ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4 post_policy ln_ntl_mean_1km if sample_hospital, ///
    absorb(hospital_id prov_id#year) vce(cluster county_id_num)
test ev_le_m4 ev_m3 ev_m2
estadd scalar pretrend_p = r(p)
coefplot twe_pharm_ln_1km, keep(ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4) vertical ///
    coeflabels(ev_le_m4="<=-4" ev_m3="-3" ev_m2="-2" ev_0="0" ev_p1="1" ev_p2="2" ev_p3="3" ev_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Hospital TWFE event: ln pharmacy count, 1km") xtitle("Years relative to reform; -1 omitted") ytitle("Coefficient") name(twe_pharm_ln_1km, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\hospital_v6\twfe_event_pharm_ln_1km.png", replace width(2000)

eststo twe_pharm_ln_2km: reghdfe ln_pharm_2km ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4 post_policy ln_ntl_mean_2km if sample_hospital, ///
    absorb(hospital_id prov_id#year) vce(cluster county_id_num)
test ev_le_m4 ev_m3 ev_m2
estadd scalar pretrend_p = r(p)
coefplot twe_pharm_ln_2km, keep(ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4) vertical ///
    coeflabels(ev_le_m4="<=-4" ev_m3="-3" ev_m2="-2" ev_0="0" ev_p1="1" ev_p2="2" ev_p3="3" ev_ge_p4=">=4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Hospital TWFE event: ln pharmacy count, 2km") xtitle("Years relative to reform; -1 omitted") ytitle("Coefficient") name(twe_pharm_ln_2km, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\hospital_v6\twfe_event_pharm_ln_2km.png", replace width(2000)
esttab twe_pharm_ln_2km twe_pharm_ln_1km twe_pharm_ln_500m using "D:\Hospital_Pharmacy program\output\regression\hospital_v6\twfe_event_pharm_ln.rtf", replace ///
    label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons keep(ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4) ///
    mtitles("2km: main" "1km: robustness" "500m: robustness") stats(N r2_within pretrend_p, labels("Observations" "Within R-squared" "Pretrend p-value")) ///
    title("Hospital TWFE event study: ln pharmacy count")

*===============================================================================
* Pharmacy CSDID: 2km primary, 1km/500m robustness
*===============================================================================

* Hospital CSDID pharmacy count
eststo clear
csdid pharm_500m ln_ntl_mean_500m if sample_hospital, ivar(hospital_id) time(year) gvar(g_csdid) ///
    method(dripw) notyet vce(cluster county_id_num)
capture noisily estat pretrend
estat simple, estore(cs_pharm_count_500m)

estat event, window(-4 4) estore(cse_pharm_count_500m)
coefplot cse_pharm_count_500m, keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4) vertical ///
    coeflabels(Tm4="-4" Tm3="-3" Tm2="-2" Tp0="0" Tp1="1" Tp2="2" Tp3="3" Tp4="4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Hospital CSDID pharmacy count, 500m") xtitle("Years relative to reform; -1 omitted") ytitle("ATT") name(cse_pharm_count_500m, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\hospital_v6\csdid_event_pharm_count_500m.png", replace width(2000)

csdid pharm_1km ln_ntl_mean_1km if sample_hospital, ivar(hospital_id) time(year) gvar(g_csdid) ///
    method(dripw) notyet vce(cluster county_id_num)
capture noisily estat pretrend
estat simple, estore(cs_pharm_count_1km)
estat event, window(-4 4) estore(cse_pharm_count_1km)
coefplot cse_pharm_count_1km, keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4) vertical ///
    coeflabels(Tm4="-4" Tm3="-3" Tm2="-2" Tp0="0" Tp1="1" Tp2="2" Tp3="3" Tp4="4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Hospital CSDID pharmacy count, 1km") xtitle("Years relative to reform; -1 omitted") ytitle("ATT") name(cse_pharm_count_1km, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\hospital_v6\csdid_event_pharm_count_1km.png", replace width(2000)

csdid pharm_2km ln_ntl_mean_2km if sample_hospital, ivar(hospital_id) time(year) gvar(g_csdid) ///
    method(dripw) notyet vce(cluster county_id_num)
capture noisily estat pretrend
estat simple, estore(cs_pharm_count_2km)
estat event, window(-4 4) estore(cse_pharm_count_2km)
coefplot cse_pharm_count_2km, keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4) vertical ///
    coeflabels(Tm4="-4" Tm3="-3" Tm2="-2" Tp0="0" Tp1="1" Tp2="2" Tp3="3" Tp4="4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Hospital CSDID pharmacy count, 2km") xtitle("Years relative to reform; -1 omitted") ytitle("ATT") name(cse_pharm_count_2km, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\hospital_v6\csdid_event_pharm_count_2km.png", replace width(2000)
esttab cs_pharm_count_2km cs_pharm_count_1km cs_pharm_count_500m using "D:\Hospital_Pharmacy program\output\regression\hospital_v6\csdid_att_pharm_count.rtf", replace se b(%9.3f) ///
    star(* 0.10 ** 0.05 *** 0.01) nocons keep(ATT) mtitles("2km: main" "1km: robustness" "500m: robustness") title("Hospital CSDID pharmacy count: overall ATT")
esttab cse_pharm_count_2km cse_pharm_count_1km cse_pharm_count_500m using "D:\Hospital_Pharmacy program\output\regression\hospital_v6\csdid_event_pharm_count.rtf", replace se b(%9.3f) ///
    star(* 0.10 ** 0.05 *** 0.01) nocons keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4) ///
    mtitles("2km: main" "1km: robustness" "500m: robustness") title("Hospital CSDID pharmacy count: event study")

* Hospital CSDID ln pharmacy count
eststo clear
csdid ln_pharm_500m ln_ntl_mean_500m if sample_hospital, ivar(hospital_id) time(year) gvar(g_csdid) ///
    method(dripw) notyet vce(cluster county_id_num)
capture noisily estat pretrend
estat simple, estore(cs_pharm_ln_500m)
estat event, window(-4 4) estore(cse_pharm_ln_500m)
coefplot cse_pharm_ln_500m, keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4) vertical ///
    coeflabels(Tm4="-4" Tm3="-3" Tm2="-2" Tp0="0" Tp1="1" Tp2="2" Tp3="3" Tp4="4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Hospital CSDID ln pharmacy count, 500m") xtitle("Years relative to reform; -1 omitted") ytitle("ATT") name(cse_pharm_ln_500m, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\hospital_v6\csdid_event_pharm_ln_500m.png", replace width(2000)

csdid ln_pharm_1km ln_ntl_mean_1km if sample_hospital, ivar(hospital_id) time(year) gvar(g_csdid) ///
    method(dripw) notyet vce(cluster county_id_num)
capture noisily estat pretrend
estat simple, estore(cs_pharm_ln_1km)
estat event, window(-4 4) estore(cse_pharm_ln_1km)
coefplot cse_pharm_ln_1km, keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4) vertical ///
    coeflabels(Tm4="-4" Tm3="-3" Tm2="-2" Tp0="0" Tp1="1" Tp2="2" Tp3="3" Tp4="4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Hospital CSDID ln pharmacy count, 1km") xtitle("Years relative to reform; -1 omitted") ytitle("ATT") name(cse_pharm_ln_1km, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\hospital_v6\csdid_event_pharm_ln_1km.png", replace width(2000)

csdid ln_pharm_2km ln_ntl_mean_2km if sample_hospital, ivar(hospital_id) time(year) gvar(g_csdid) ///
    method(dripw) notyet vce(cluster county_id_num)
capture noisily estat pretrend
estat simple, estore(cs_pharm_ln_2km)
estat event, window(-4 4) estore(cse_pharm_ln_2km)
coefplot cse_pharm_ln_2km, keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4) vertical ///
    coeflabels(Tm4="-4" Tm3="-3" Tm2="-2" Tp0="0" Tp1="1" Tp2="2" Tp3="3" Tp4="4") ///
    xline(3.5, lcolor(red) lpattern(dash)) yline(0, lcolor(gs8)) recast(scatter) ciopts(recast(rcap)) ///
    title("Hospital CSDID ln pharmacy count, 2km") xtitle("Years relative to reform; -1 omitted") ytitle("ATT") name(cse_pharm_ln_2km, replace)
graph export "D:\Hospital_Pharmacy program\output\regression\hospital_v6\csdid_event_pharm_ln_2km.png", replace width(2000)
esttab cs_pharm_ln_2km cs_pharm_ln_1km cs_pharm_ln_500m using "D:\Hospital_Pharmacy program\output\regression\hospital_v6\csdid_att_pharm_ln.rtf", replace se b(%9.3f) ///
    star(* 0.10 ** 0.05 *** 0.01) nocons keep(ATT) mtitles("2km: main" "1km: robustness" "500m: robustness") title("Hospital CSDID ln pharmacy count: overall ATT")
esttab cse_pharm_ln_2km cse_pharm_ln_1km cse_pharm_ln_500m using "D:\Hospital_Pharmacy program\output\regression\hospital_v6\csdid_event_pharm_ln.rtf", replace se b(%9.3f) ///
    star(* 0.10 ** 0.05 *** 0.01) nocons keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4) ///
    mtitles("2km: main" "1km: robustness" "500m: robustness") title("Hospital CSDID ln pharmacy count: event study")

*===============================================================================
* PPML for raw count outcomes
* Pharmacy count levels only; annual changes can be negative and are not PPML outcomes.
*===============================================================================

* Hospital PPML main: pharmacy count

eststo clear
eststo ppml_main_pharm_count_500m: ppmlhdfe pharm_500m ddd post_policy ln_ntl_mean_500m if sample_hospital, ///
    absorb(hospital_id year) vce(cluster county_id_num)
eststo ppml_main_pharm_count_1km: ppmlhdfe pharm_1km ddd post_policy ln_ntl_mean_1km if sample_hospital, ///
    absorb(hospital_id year) vce(cluster county_id_num)
eststo ppml_main_pharm_count_2km: ppmlhdfe pharm_2km ddd post_policy ln_ntl_mean_2km if sample_hospital, ///
    absorb(hospital_id year) vce(cluster county_id_num)
esttab ppml_main_pharm_count_2km ppml_main_pharm_count_1km ppml_main_pharm_count_500m using "D:\Hospital_Pharmacy program\output\regression\hospital_v6\ppml_main_pharm_count.rtf", replace label se b(%9.3f) ///
    star(* 0.10 ** 0.05 *** 0.01) nocons keep(ddd post_policy) mtitles("2km: main" "1km: robustness" "500m: robustness") ///
    stats(N, labels("Observations")) title("Hospital PPML: pharmacy count")
	
eststo clear
eststo ppml_main_pharm_count_500m: ppmlhdfe pharm_500m ddd post_policy ln_ntl_mean_500m if sample_hospital, ///
    absorb(hospital_id prov_id#year) vce(cluster county_id_num)
eststo ppml_main_pharm_count_1km: ppmlhdfe pharm_1km ddd post_policy ln_ntl_mean_1km if sample_hospital, ///
    absorb(hospital_id prov_id#year) vce(cluster county_id_num)
eststo ppml_main_pharm_count_2km: ppmlhdfe pharm_2km ddd post_policy ln_ntl_mean_2km if sample_hospital, ///
    absorb(hospital_id prov_id#year) vce(cluster county_id_num)
esttab ppml_main_pharm_count_2km ppml_main_pharm_count_1km ppml_main_pharm_count_500m using "D:\Hospital_Pharmacy program\output\regression\hospital_v6\ppml_main_pharm_count2.rtf", replace label se b(%9.3f) ///
    star(* 0.10 ** 0.05 *** 0.01) nocons keep(ddd post_policy) mtitles("2km: main" "1km: robustness" "500m: robustness") ///
    stats(N, labels("Observations")) title("Hospital PPML with province-by-year FE: pharmacy count")

di as result "Hospital analyses completed successfully."
di as result "Hospital-buffer pharmacy counts: 2km primary; 1km and 500m robustness."
di as result "Outputs: D:\Hospital_Pharmacy program\output\regression\hospital_v6"
log close
