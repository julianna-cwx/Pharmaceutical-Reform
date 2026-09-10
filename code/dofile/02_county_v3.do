****This do file is to  baseline regress Pharmaceutical Reform on Pharmacies in county level****
* setting
clear
cd "D:\Hospital_Pharmacy program\data\hospital_pharmacy\county_pharm_panel"
set linesize 255
set more off
cap log close 
log using ".\paper_`c(current_date)'.log", replace text

clear
use ".\county_pharm_panel.dta",clear
destring county_id, gen(county_id_num)
gen long prov_id = floor(county_id_num / 10000) if !missing(county_id_num)

gen post= (year >policy_year)
gen treat=!missing(policy_year)
gen did=post*treat

gen ln1_county_pharmacy_count =ln(county_pharmacy_count+1)


gen int rel = year - policy_year if !missing(policy_year)
gen byte ev_le_m4 = (rel <= -4) if !missing(rel)
gen byte ev_m3 = (rel == -3) if !missing(rel)
gen byte ev_m2 = (rel == -2) if !missing(rel)
gen byte ev_0 = (rel == 0) if !missing(rel)
gen byte ev_p1 = (rel == 1) if !missing(rel)
gen byte ev_p2 = (rel == 2) if !missing(rel)
gen byte ev_p3 = (rel == 3) if !missing(rel)
gen byte ev_ge_p4 = (rel >= 4) if !missing(rel)



****TWFE******省份年份固定效应****
eststo clear
qui eststo:reghdfe county_pharmacy_count did ,absorb(county_id_num prov_id#year) cluster (county_id_num)
qui eststo:reghdfe county_pharmacy_count did ln_pop ln_nl_mean,absorb(county_id_num prov_id#year) cluster (county_id_num)
qui eststo:reghdfe ln_county_pharmacy_count did,absorb(county_id_num prov_id#year) cluster (county_id_num)
qui eststo:reghdfe ln_county_pharmacy_count did ln_pop ln_nl_mean,absorb(county_id_num prov_id#year) cluster (county_id_num)
qui eststo:reghdfe ln1_county_pharmacy_count did,absorb(county_id_num prov_id#year) cluster (county_id_num)
qui eststo:reghdfe ln1_county_pharmacy_count did ln_pop ln_nl_mean,absorb(county_id_num prov_id#year) cluster (county_id_num)
esttab  using regbaseline.rtf,replace keep(did ln_pop ln_nl_mean) nogaps compress ///
b(%12.3f) se(%12.3f)  s(N r2)  star(* 0.1 ** 0.05 *** 0.01)

****平行趋势检验*****
eststo clear
eststo evt_total_pharm_count: reghdfe county_pharmacy_count ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4 ln_pop ln_nl_mean, absorb(county_id_num prov_id#year) vce(cluster county_id_num)
test ev_le_m4 ev_m3 ev_m2
estadd scalar pretrend_p = r(p)
eststo evt_total_pharm_ln: reghdfe ln_county_pharmacy_count ev_le_m4 ev_m3 ev_m2 ev_0 ev_p1 ev_p2 ev_p3 ev_ge_p4 ln_pop ln_nl_mean, absorb(county_id_num prov_id#year) vce(cluster county_id_num)
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


***CSDID*****
gen int g_csdid=policy_year

eststo clear
csdid county_pharmacy_count,ivar(county_id_num) time(year) gvar(g_csdid) controlgroup(notyettreated)
estat simple

estat event, window(-5 5) estore(cse_total_pharm_count)

coefplot cse_total_pharm_count, ///
    keep(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4) ///
    order(Tm4 Tm3 Tm2 Tp0 Tp1 Tp2 Tp3 Tp4) ///
    vertical ///
    coeflabels( ///
        Tm4="-4" ///
        Tm3="-3" ///
        Tm2="-2" ///
        Tp0="0" ///
        Tp1="1" ///
        Tp2="2" ///
        Tp3="3" ///
        Tp4="4" ///
    ) ///
    xline(3.5, lcolor(red) lpattern(dash)) ///
    yline(0, lcolor(gs8)) ///
    recast(scatter) ///
    ciopts(recast(rcap)) ///
    title("County CSDID event: pharmacy count") ///
    xtitle("Years relative to reform") ///
    ytitle("ATT") ///
    graphregion(color(white)) ///
    plotregion(color(white)) ///
    name(cse_county_pharm_count, replace)
	
	
*****PPML******
eststo clear
eststo ppml_total_count: ppmlhdfe county_pharmacy_count did ln_pop ln_nl_mean,absorb(county_id_num prov_id#year) vce(cluster county_id_num)

esttab ppml_total_count using ///
    "$outdir\ppml_main_county_pharmacy_count.rtf", ///
    replace label se b(%9.3f) ///
    star(* 0.10 ** 0.05 *** 0.01) ///
    nocons keep(did ln_pop ln_nl_mean) ///
    stats(N, labels("Observations")) ///
    title("County PPMLHDFE: Total Pharmacy Count")
	
****near phamrmacies ******
eststo clear
qui eststo: reghdfe pharm_nearest_pub_le2km did ln_pop ln_nl_mean, absorb(county_id_num prov_id#year) vce(cluster county_id_num)
qui eststo: reghdfe pharm_nearest_pub_le1km did ln_pop ln_nl_mean, absorb(county_id_num prov_id#year) vce(cluster county_id_num)
qui eststo: reghdfe pharm_nearest_pub_le500m did ln_pop ln_nl_mean, absorb(county_id_num prov_id#year) vce(cluster county_id_num)
esttab  using neartwfe.rtf,replace keep(did ln_pop ln_nl_mean) nogaps compress ///
b(%12.3f) se(%12.3f)  s(N r2)  star(* 0.1 ** 0.05 *** 0.01)

eststo clear
qui eststo: ppmlhdfe pharm_nearest_pub_le2km did ln_pop ln_nl_mean, absorb(county_id_num prov_id#year) vce(cluster county_id_num)
qui eststo: ppmlhdfe pharm_nearest_pub_le1km did ln_pop ln_nl_mean, absorb(county_id_num prov_id#year) vce(cluster county_id_num)
qui eststo: ppmlhdfe pharm_nearest_pub_le500m did ln_pop ln_nl_mean, absorb(county_id_num prov_id#year) vce(cluster county_id_num)
esttab  using nearppml.rtf,replace keep(did ln_pop ln_nl_mean) nogaps compress ///
b(%12.3f) se(%12.3f)  s(N r2)  star(* 0.1 ** 0.05 *** 0.01)

eststo clear
csdid  pharm_nearest_pub_le2km,ivar(county_id_num) time(year) gvar(g_csdid) controlgroup(notyettreated)
estat simple
csdid  pharm_nearest_pub_le1km,ivar(county_id_num) time(year) gvar(g_csdid) controlgroup(notyettreated)
estat simple
csdid  pharm_nearest_pub_le500m,ivar(county_id_num) time(year) gvar(g_csdid) controlgroup(notyettreated)
estat simple
	