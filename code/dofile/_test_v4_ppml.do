clear all
set more off
global ROOT "D:\Hospital_Pharmacy program"
global DATA "$ROOT\data\hospital_pharmacy"
global OUTROOT "$ROOT\output\regression"
global OUT "$OUTROOT\hospital_v4"
use "$DATA\hospital_pharm_restaurant_panel_2012_2019_with_ntl.dta", clear
isid hospital_id year
capture drop public
gen byte public = (public_flag == 1) if !missing(public_flag)
capture drop county_id_num
capture confirm numeric variable county_id
if _rc {
    destring county_id, gen(county_id_num) ignore(" ")
}
else {
    gen double county_id_num = county_id
}
gen long prov_id = floor(county_id_num / 10000)
capture drop post_policy ddd rel
gen byte post_policy = (year >= policy_year) if !missing(year, policy_year)
gen byte ddd = public * post_policy
gen rel = year - policy_year
capture drop ln_ntl_mean_1_2km
gen ln_ntl_mean_1_2km = ln_ntl_mean_2km
gen byte sample_hospital = inrange(year, 2012, 2019) & (missing(policy_year) | policy_year != 2012) & !missing(county_id_num)
local radii "1km 2km 3km 1_2km"
eststo clear
foreach r of local radii {
    ppmlhdfe pharm_`r' ddd post_policy ln_ntl_mean_`r' if sample_hospital, absorb(hospital_id prov_id#year) cluster(county_id_num)
    estimates store pp_`r'
}
esttab pp_1km pp_2km pp_3km pp_1_2km using "$OUT\_test_ppml_pharm_count.rtf", replace se b(%9.3fc) scalars(N) nocons keep(ddd ln_ntl_mean_1km ln_ntl_mean_2km ln_ntl_mean_3km ln_ntl_mean_1_2km)
exit, clear
