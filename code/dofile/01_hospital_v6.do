* 01_hospital_v6.do -- standalone paper replication, hospital sample 2013-2018.
* Run directly: do "D:/Hospital_Pharmacy program/code/dofile/01_hospital_v6.do"
* Sections: baseline ring and cumulative DID/event studies; stacked-DID and
* other robustness checks; gross pharmacy entry/exit; 2010-census county
* heterogeneity; general-versus-specialist hospitals; tier effects; explicit
* manuscript Tables 1--3; placebos; residential proximity; migration; and
* population coverage.
* Optional arguments override the output folder and input panel, respectively.
* Replication target: Wenxia Chen_Pharmacies at the Hospital Gate.pdf.
* Event-time audit: legacy numbers use year-policy_year; post is year>policy_year.
* Consequently legacy k=0 is adoption year and k=1 is first treated year.
version 17
clear all
set more off
set varabbrev off
set linesize 255
args outputdir inputdata
if `"`outputdir'"'=="" local outputdir "D:/Hospital_Pharmacy program/results/results_v6_paper_replication"
if `"`inputdata'"'=="" local inputdata "D:/Hospital_Pharmacy program/data/hospital_pharmacy/hosp_pharm_panel/hosp_pharm_v5_xqdistance.dta"
global RP `"`outputdir'"'
capture mkdir "$RP"
capture log close _all
log using "$RP/replication.log", replace text
which reghdfe
which esttab
which coefplot
use `"`inputdata'"', clear
keep if inrange(year,2013,2018)
drop if missing(hospital_group)
isid hospital_id year
merge 1:1 hospital_id year using ///
 "D:/Hospital_Pharmacy program/data/hospital_pharmacy/hosp_pharm_panel/hospital_pharmacy_population_accessibility.dta", ///
 keepusing(h200_ann_covpop h500_ann_covpop h1000_ann_covpop ///
           h200_p13_covpop h500_p13_covpop h1000_p13_covpop)
tab _merge
assert _merge==3
drop _merge
merge 1:1 hospital_id year using ///
 "D:/Hospital_Pharmacy program/data/hospital_pharmacy/hosp_pharm_panel/hospital_pharmacy_migration_distances.dta", ///
 keepusing(move_threshold_m mig_n_* mig_dxq_* mig_dhosp_*)
tab _merge
assert _merge==3
drop _merge
* Prepared from the annual DZDP shop-id panels. Year 2013 has no lag year and
* is therefore master-only; gross flows are available for 2014--2018.
merge 1:1 hospital_id year using ///
 "D:/Hospital_Pharmacy program/results/additional_hospital_analysis/hospital_pharmacy_gross_flows.dta"
tab _merge
assert inlist(_merge,1,3)
drop _merge
* Chain/non-chain pharmacy stocks constructed from the source is_chains flag.
* Rebuild with code/python/build_hospital_pharmacy_chain_counts.py.
merge 1:1 hospital_id year using ///
 "D:/Hospital_Pharmacy program/data/hospital_pharmacy/hosp_pharm_panel/hospital_pharmacy_chain_counts.dta"
tab _merge
assert _merge==3
drop _merge
* Time-invariant 2010 census characteristics and name-based hospital type.
* Rebuild this file with code/python/prepare_hospital_additional_analysis.py
* whenever the census workbook or hospital classification file changes.
merge m:1 hospital_id using ///
 "D:/Hospital_Pharmacy program/results/additional_hospital_analysis/hospital_characteristics.dta"
tab _merge
assert _merge==3
drop _merge
gen byte pub=(strtrim(public)=="公立") if inlist(strtrim(public),"公立","民营")
egen long cid=group(spatial_province spatial_city spatial_county), missing
egen long cyt=group(cid year)
gen byte post=(year>policy_year) if !missing(policy_year)
gen byte did=pub*post if !missing(pub,post)
gen byte dn=(hospital_group==2)*post if !missing(post)
gen byte dt=pub*(is_tcm==1)*post if !missing(pub,is_tcm,post)
gen byte public_tcm=pub*(is_tcm==1) if !missing(pub,is_tcm)
gen byte dnon=pub*(is_tcm==0)*post if !missing(pub,is_tcm,post)
xtset hospital_id year
foreach basis in ann p13 {
 foreach r in 200 500 1000 {
  label variable h`r'_`basis'_covpop "Population covered by pharmacies within hospital `r'm"
  gen double ln_h`r'_`basis'_covpop=ln(1+h`r'_`basis'_covpop)
  gen double d_h`r'_`basis'_covpop=D.h`r'_`basis'_covpop
  gen double dln_h`r'_`basis'_covpop=D.ln_h`r'_`basis'_covpop
 }
}
foreach r in 200 500 800 1000 {
 gen double ne`r'=D.pharm_`r'm
 gen double ysne`r'=D.ys_`r'm
 gen double ne_chain_`r'=D.pharm_chain_`r'm
 gen double ne_nonchain_`r'=D.pharm_nonchain_`r'm
}
foreach r in 200 500 1000 {
 gen double dxq_stock_`r'=D.mean_xqdist_stock_`r'm
}
foreach band in 200 200_500 500_1000 {
 gen double dxq_ring_`band'=D.mean_xqdist_ring_`band'm
}
gen double st_gate=pharm_200m
gen double st_near=pharm_500m-pharm_200m
gen double st_outer=pharm_1000m-pharm_500m
gen double st_total=pharm_1000m
foreach band in gate near outer total {
 assert st_`band'>=0 if !missing(st_`band')
 gen double ne_`band'=D.st_`band'
}
assert abs(ne_gate+ne_near+ne_outer-ne_total)<1e-9 if !missing(ne_total)
gen double ys_st_gate=ys_200m
gen double ys_st_near=ys_500m-ys_200m
gen double ys_st_outer=ys_1000m-ys_500m
gen double ys_st_total=ys_1000m
foreach band in gate near outer total {
 assert ys_st_`band'>=0 if !missing(ys_st_`band')
 gen double ys_ne_`band'=D.ys_st_`band'
}
assert abs(ys_ne_gate+ys_ne_near+ys_ne_outer-ys_ne_total)<1e-9 if !missing(ys_ne_total)
gen int rel=year-policy_year if pub==1 & !missing(policy_year)
gen byte em4=(rel<=-4 & !missing(rel)) if !missing(pub)
gen byte em3=(rel==-3) if !missing(pub)
gen byte em2=(rel==-2) if !missing(pub)
gen byte e0=(rel==0) if !missing(pub)
gen byte ep1=(rel==1) if !missing(pub)
gen byte ep2=(rel==2) if !missing(pub)
gen byte ep3=(rel==3) if !missing(pub)
gen byte ep4=(rel>=4 & !missing(rel)) if !missing(pub)
local events em4 em3 em2 e0 ep1 ep2 ep3 ep4
tempname res ev desc
postfile `res' str24 model str12 band str24 term double b double se double p double N double mean double pretrend using "$RP/estimates.dta", replace
postfile `ev' str24 model str12 band int k double b double se double p double N double pretrend using "$RP/events.dta", replace
postfile `desc' str32 variable double N double mean double sd double min double max using "$RP/descriptives.dta", replace

* The ys_ne and ys_st outcomes repeat the pharmacy specifications on an
* unrelated establishment category. A null DID supports the placebo check.
foreach outcome in ne st ys_ne ys_st {
 foreach band in gate near outer total {
  quietly reghdfe `outcome'_`band' did if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
  esttab using "$RP/`outcome'_`band'.rtf", replace rtf ///
   keep(did) b(3) se(3) star(* 0.10 ** 0.05 *** 0.01) ///
   stats(N r2_within r2_a, labels("Observations" "Within R-squared" "Adjusted R-squared")) ///
   title("DID regression: `outcome'_`band'")
  local n=e(N)
  local b=_b[did]
  local se=_se[did]
  local p=2*ttail(e(df_r),abs(`b'/`se'))
  quietly summarize `outcome'_`band' if e(sample)
  local mean=r(mean)
  if "`outcome'_`band'"=="ne_gate" {
   gen byte net_sample=e(sample)
   foreach v in pub public_tcm grade1_hospital grade2_hospital grade3_hospital pharm_200m pharm_500m pharm_800m pharm_1000m ne200 ne500 ne800 ne1000 ys_200m ys_500m ys_800m ys_1000m ysne200 ysne500 ysne800 ysne1000 nearest_pharmacy_m {
    if inlist("`v'","grade1_hospital","grade2_hospital","grade3_hospital") quietly summarize `v' if net_sample & inlist(hospital_level_final,1,2,3)
    else quietly summarize `v' if net_sample
    post `desc' ("`v'") (r(N)) (r(mean)) (r(sd)) (r(min)) (r(max))
   }
   assert `n'==74924
  }
  quietly reghdfe `outcome'_`band' `events' if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
  quietly test em4 em3 em2
  local pre=r(p)
  post `res' ("ring_`outcome'") ("`band'") ("did") (`b') (`se') (`p') (`n') (`mean') (`pre')
  local j=0
  foreach v of local events {
   local ++j
   local k: word `j' of -4 -3 -2 0 1 2 3 4
   if _se[`v']>0 {
    post `ev' ("ring_`outcome'") ("`band'") (`k') (_b[`v']) (_se[`v']) (2*ttail(e(df_r),abs(_b[`v']/_se[`v']))) (e(N)) (`pre')
   }
  }
  post `ev' ("ring_`outcome'") ("`band'") (-1) (0) (0) (.) (e(N)) (`pre')
 }
}
postclose `desc'

* Cohort-by-calendar-year post cells; each coefficient and its full covariance
* enter the count-weighted lincom. This is the paper's saturated OLS check,
* not an implementation of did_imputation or a guarantee against contamination.
local cells
forvalues g=2012/2017 {
 forvalues t=2013/2018 {
  if `t'>`g' {
   gen byte cc`g'_`t'=pub==1 & policy_year==`g' & year==`t'
   local cells `cells' cc`g'_`t'
  }
 }
}
foreach r in 200 500 800 1000 {
 quietly reghdfe ne`r' did if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
 post `res' ("cumulative") ("`r'") ("baseline") (_b[did]) (_se[did]) (2*ttail(e(df_r),abs(_b[did]/_se[did]))) (e(N)) (.) (.)
 quietly reghdfe ne`r' dn, absorb(hospital_id cyt) vce(cluster cid)
 post `res' ("cumulative") ("`r'") ("non_tcm") (_b[dn]) (_se[dn]) (2*ttail(e(df_r),abs(_b[dn]/_se[dn]))) (e(N)) (.) (.)
 quietly reghdfe ne`r' dnon dt if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
 foreach v in dnon dt {
  post `res' ("cumulative") ("`r'") ("`v'") (_b[`v']) (_se[`v']) (2*ttail(e(df_r),abs(_b[`v']/_se[`v']))) (e(N)) (.) (.)
 }
 quietly reghdfe ne`r' `cells' if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
 local n=e(N)
 quietly count if e(sample) & did==1
 local total=r(N)
 local expr "0"
 foreach v of local cells {
  quietly count if e(sample) & `v'==1
  if r(N)>0 local expr "`expr'+(`r(N)'/`total')*`v'"
 }
 quietly lincom `expr'
 post `res' ("cumulative") ("`r'") ("cohort") (r(estimate)) (r(se)) (r(p)) (`n') (.) (.)
}

*===============================================================================
* Gross entry and exit. Entry is a shop_id observed in t but not t-1; exit is
* observed in t-1 but not t. These are platform appearance/disappearance
* measures, not administrative business registrations or closures.
*===============================================================================
foreach flow in entry exit {
 foreach r in 200 500 800 1000 {
  local y gross_`flow'_`r'm
  quietly reghdfe `y' did if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
  local n=e(N)
  local b=_b[did]
  local se=_se[did]
  local p=2*ttail(e(df_r),abs(`b'/`se'))
  quietly summarize `y' if e(sample)
  post `res' ("gross_`flow'") ("`r'") ("did") (`b') (`se') (`p') (`n') (r(mean)) (.)

  quietly reghdfe `y' `events' if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
  quietly test em4 em3 em2
  local pre=r(p)
  local j=0
  foreach v of local events {
   local ++j
   local k: word `j' of -4 -3 -2 0 1 2 3 4
   if _se[`v']>0 {
    post `ev' ("gross_`flow'") ("`r'") (`k') (_b[`v']) (_se[`v']) ///
     (2*ttail(e(df_r),abs(_b[`v']/_se[`v']))) (e(N)) (`pre')
   }
  }
  post `ev' ("gross_`flow'") ("`r'") (-1) (0) (0) (.) (e(N)) (`pre')
  if inlist(`r',200,500) {
   local pretxt: display %4.3f `pre'
   estimates store gross_event_`flow'_`r'
   coefplot gross_event_`flow'_`r', ///
    keep(em4 em3 em2 e0 ep1 ep2 ep3 ep4) ///
    coeflabels(em4="<=-4" em3="-3" em2="-2" e0="0" ///
     ep1="1" ep2="2" ep3="3" ep4=">=4") ///
    vertical yline(0,lcolor(gs8)) xline(3.5,lcolor(red) lpattern(dash)) ///
    recast(scatter) ciopts(recast(rcap)) graphregion(color(white)) ///
    title("Gross `flow': `r' m") subtitle("Joint lead test: p = `pretxt'") ///
    xtitle("Years relative to policy year; -1 omitted") ytitle("Coefficient") ///
    name(gross_event_`flow'_`r',replace)
   graph export "$RP/gross_event_`flow'_`r'm.pdf", replace as(pdf)
  }
 }
 graph combine gross_event_`flow'_200 gross_event_`flow'_500, cols(2) ///
  ycommon graphregion(color(white)) title("Gross pharmacy `flow'") ///
  name(gross_event_`flow'_combined,replace)
 graph export "$RP/gross_event_`flow'_combined.pdf", replace as(pdf)
}

*===============================================================================
* Pharmacy-type heterogeneity: use annual changes in chain and non-chain
* pharmacy counts as separate outcomes. Each model uses the baseline hospital
* and county-by-year fixed effects. is_chains does not identify chain size, so
* this comparison is chain versus non-chain, not large versus small chains.
*===============================================================================
foreach type in chain nonchain {
 eststo clear
 local models
 foreach r in 200 500 800 1000 {
  local y ne_`type'_`r'
  quietly reghdfe `y' did if !missing(pub), ///
   absorb(hospital_id cyt) vce(cluster cid)
  estimates store pharmtype_`type'_`r'
  local models `models' pharmtype_`type'_`r'
  quietly summarize `y' if e(sample)
  post `res' ("pharmacy_type") ("`r'") ("`type'") ///
   (_b[did]) (_se[did]) (2*ttail(e(df_r),abs(_b[did]/_se[did]))) ///
   (e(N)) (r(mean)) (.)
 }
 local typetitle "Chain pharmacies"
 if "`type'"=="nonchain" local typetitle "Non-chain pharmacies"
 esttab `models' using "$RP/pharmacy_type_`type'.rtf", replace rtf ///
  keep(did) coeflabels(did "Post reform x public hospital") ///
  b(3) se(3) star(* 0.10 ** 0.05 *** 0.01) ///
  mtitles("200 m" "500 m" "800 m" "1,000 m") ///
  stats(N r2_within r2_a, ///
   labels("Observations" "Within R-squared" "Adjusted R-squared")) ///
  title("DID outcome: annual net change in `typetitle'") ///
  addnote("Hospital and county-by-year fixed effects; standard errors clustered by county." ///
   "Chain status uses the source is_chains classification.")
}

*===============================================================================
* County heterogeneity using time-invariant 2010 census characteristics.
* Each characteristic is standardized over the common nonmissing hospital-year
* sample. did_z is the change in the DID effect for a one-SD increase. The DID
* coefficient is the effect at the sample-mean characteristic. Models are run
* one characteristic at a time because urbanization, education, and density are
* strongly correlated.
*===============================================================================
local hetvars elderly_share2010 urban_share2010 avg_education2010 ln_population_density2010
local hetnames elderly urban education density
local hi=0
foreach x of local hetvars {
 local ++hi
 local hname: word `hi' of `hetnames'
 capture drop z_het did_z
 quietly summarize `x' if !missing(pub,`x')
 gen double z_het=(`x'-r(mean))/r(sd) if !missing(`x')
 gen double did_z=did*z_het if !missing(did,z_het)
 foreach r in 200 500 800 1000 {
  quietly reghdfe ne`r' did did_z if !missing(pub,z_het), absorb(hospital_id cyt) vce(cluster cid)
  local n=e(N)
  quietly summarize ne`r' if e(sample)
  local mean=r(mean)
  foreach v in did did_z {
   post `res' ("het_`hname'") ("`r'") ("`v'") (_b[`v']) (_se[`v']) ///
    (2*ttail(e(df_r),abs(_b[`v']/_se[`v']))) (`n') (`mean') (.)
  }
  quietly lincom did-did_z
  post `res' ("het_`hname'") ("`r'") ("effect_minus1sd") ///
   (r(estimate)) (r(se)) (r(p)) (`n') (`mean') (.)
  quietly lincom did+did_z
  post `res' ("het_`hname'") ("`r'") ("effect_plus1sd") ///
   (r(estimate)) (r(se)) (r(p)) (`n') (`mean') (.)
 }
}

*===============================================================================
* General versus specialist hospitals. Restrict to the two classified groups;
* general hospitals are the reference. The interaction coefficient is the
* specialist-minus-general difference, while lincom gives the specialist effect.
*===============================================================================
gen double did_specialist=did*hospital_specialist if !missing(did,hospital_specialist)
foreach r in 200 500 800 1000 {
 quietly reghdfe ne`r' did did_specialist if !missing(pub,hospital_specialist), ///
  absorb(hospital_id cyt) vce(cluster cid)
 local n=e(N)
 quietly summarize ne`r' if e(sample)
 local mean=r(mean)
 post `res' ("hospital_type") ("`r'") ("general") ///
  (_b[did]) (_se[did]) (2*ttail(e(df_r),abs(_b[did]/_se[did]))) (`n') (`mean') (.)
 quietly lincom did+did_specialist
 post `res' ("hospital_type") ("`r'") ("specialist") ///
  (r(estimate)) (r(se)) (r(p)) (`n') (`mean') (.)
 post `res' ("hospital_type") ("`r'") ("specialist_minus_general") ///
  (_b[did_specialist]) (_se[did_specialist]) ///
  (2*ttail(e(df_r),abs(_b[did_specialist]/_se[did_specialist]))) (`n') (`mean') (.)
}

*===============================================================================
* Stacked DID robustness, integrated from 01_hospital_v5.do.
*
* The first actually treated year is policy_year+1 because post is defined as
* year>policy_year. Each stack contains one public-hospital treatment cohort
* and never-treated non-public hospitals, retaining only geographic groups
* containing both treated and comparison hospitals. Fixed effects are stack x
* hospital and stack x geographic-group x year; standard errors are clustered
* by the original geographic group. Event time -1 is the omitted period.
*===============================================================================
tempfile stacked_panel
local first_stack 1
forvalues g=2014/2018 {
 preserve
  keep if !missing(pub,cid,hospital_id,year)
  gen int first_treat=policy_year+1 if pub==1 & !missing(policy_year)
  keep if pub==0 | (pub==1 & first_treat==`g')
  gen int stack_cohort=`g'
  gen byte stack_treat=(pub==1 & first_treat==`g')
  bysort cid: egen byte stack_has_treated=max(stack_treat)
  bysort cid: egen byte stack_has_control=max(stack_treat==0)
  keep if stack_has_treated==1 & stack_has_control==1
  drop stack_has_treated stack_has_control
  gen int stack_rel=year-`g'
  gen byte stack_post=(year>=`g')
  gen byte stack_did=stack_treat*stack_post
  if `first_stack' {
   save `stacked_panel', replace
   local first_stack 0
  }
  else {
   append using `stacked_panel'
   save `stacked_panel', replace
  }
 restore
}

preserve
 use `stacked_panel', clear
 egen long stack_hospital=group(stack_cohort hospital_id)
 egen long stack_cyt=group(stack_cohort cid year)

 * Balance treated and control hospitals within each cohort stack so that the
 * repeatedly used non-public group does not dominate because it is larger.
 bysort stack_cohort hospital_id: gen byte stack_hosp_tag=(_n==1)
 bysort stack_cohort: egen double stack_nt=total(stack_hosp_tag*stack_treat)
 bysort stack_cohort: egen double stack_nc=total(stack_hosp_tag*(1-stack_treat))
 gen double stack_w=1 if stack_treat==1
 replace stack_w=stack_nt/stack_nc if stack_treat==0
 assert stack_w>0 & !missing(stack_w)

 gen byte stack_em4=(stack_rel<=-4)*stack_treat
 gen byte stack_em3=(stack_rel==-3)*stack_treat
 gen byte stack_em2=(stack_rel==-2)*stack_treat
 gen byte stack_e0=(stack_rel==0)*stack_treat
 gen byte stack_ep1=(stack_rel==1)*stack_treat
 gen byte stack_ep2=(stack_rel==2)*stack_treat
 gen byte stack_ep3=(stack_rel==3)*stack_treat
 gen byte stack_ep4=(stack_rel>=4)*stack_treat
 local stack_events stack_em4 stack_em3 stack_em2 stack_e0 stack_ep1 stack_ep2 stack_ep3 stack_ep4

 foreach outcome in ne st {
  estimates clear
  local stack_models
  local outcome_title "Annual net pharmacy entry"
  if "`outcome'"=="st" local outcome_title "Active pharmacy stock"
  foreach r in 200 500 800 1000 {
   local y ne`r'
   if "`outcome'"=="st" local y pharm_`r'm

   quietly reghdfe `y' stack_did [aw=stack_w], ///
    absorb(stack_hospital stack_cyt) vce(cluster cid)
   estimates store stack_base_`outcome'_`r'
   local stack_models `stack_models' stack_base_`outcome'_`r'
   local n=e(N)
   local b=_b[stack_did]
   local se=_se[stack_did]
   local p=2*ttail(e(df_r),abs(`b'/`se'))
   quietly summarize `y' if e(sample) [aw=stack_w]
   local mean=r(mean)

   quietly reghdfe `y' `stack_events' [aw=stack_w], ///
    absorb(stack_hospital stack_cyt) vce(cluster cid)
   estimates store stack_event_`outcome'_`r'
   quietly test stack_em4 stack_em3 stack_em2
   local pre=r(p)
   post `res' ("stacked_`outcome'") ("`r'") ("did") (`b') (`se') (`p') (`n') (`mean') (`pre')

   local j=0
   foreach v of local stack_events {
    local ++j
    local k: word `j' of -4 -3 -2 0 1 2 3 4
    if _se[`v']>0 {
     post `ev' ("stacked_`outcome'") ("`r'") (`k') (_b[`v']) (_se[`v']) ///
      (2*ttail(e(df_r),abs(_b[`v']/_se[`v']))) (e(N)) (`pre')
    }
   }
   post `ev' ("stacked_`outcome'") ("`r'") (-1) (0) (0) (.) (e(N)) (`pre')

   coefplot stack_event_`outcome'_`r', ///
    keep(stack_em4 stack_em3 stack_em2 stack_e0 stack_ep1 stack_ep2 stack_ep3 stack_ep4) ///
    coeflabels(stack_em4="<=-4" stack_em3="-3" stack_em2="-2" stack_e0="0" ///
     stack_ep1="1" stack_ep2="2" stack_ep3="3" stack_ep4=">=4") ///
    vertical yline(0, lcolor(gs8)) xline(3.5, lcolor(red) lpattern(dash)) ///
    recast(scatter) ciopts(recast(rcap)) graphregion(color(white)) ///
    title("`outcome_title': `r' m") ///
    subtitle("Stack x geographic-group x year fixed effects") ///
    xtitle("Years relative to first treated year; -1 omitted") ytitle("Coefficient") ///
    name(stack_event_`outcome'_`r', replace)
   graph export "$RP/stacked_event_`outcome'_`r'm.png", replace width(2000)
   graph export "$RP/stacked_event_`outcome'_`r'm.pdf", replace as(pdf)
  }

  esttab `stack_models' using "$RP/stacked_did_`outcome'.rtf", replace ///
   label se b(%9.3f) star(* 0.10 ** 0.05 *** 0.01) nocons keep(stack_did) ///
   mtitles("200 m" "500 m" "800 m" "1,000 m") ///
   stats(N r2_within, labels("Observations" "Within R-squared")) ///
   title("Stacked DID with stack-by-geographic-group-by-year fixed effects")
  graph combine stack_event_`outcome'_200 stack_event_`outcome'_500 ///
   stack_event_`outcome'_800 stack_event_`outcome'_1000, cols(2) ///
   graphregion(color(white)) title("Stacked DID: `outcome_title'") ///
   name(stack_event_`outcome'_combined, replace)
  graph export "$RP/stacked_event_`outcome'_combined.png", replace width(2600)
  graph export "$RP/stacked_event_`outcome'_combined.pdf", replace as(pdf)
 }
restore

* Population accessibility around hospitals. For each radius, the outcome is
* WorldPop population in the union of fixed 500 m buffers around pharmacies
* located within that distance of the hospital. Overlaps are counted once.
* p13 holds the 2013 population surface fixed and therefore isolates changes
* in pharmacy spatial coverage; ann uses each year's population surface.
foreach basis in p13 ann {
 eststo clear
 foreach r in 200 500 1000 {
  quietly reghdfe h`r'_`basis'_covpop did if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
  estimates store pop_`basis'_`r'
  quietly summarize h`r'_`basis'_covpop if e(sample)
  estadd scalar depmean=r(mean)
  local n=e(N)
  local b=_b[did]
  local se=_se[did]
  local p=2*ttail(e(df_r),abs(`b'/`se'))

  quietly reghdfe h`r'_`basis'_covpop `events' if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
  quietly test em4 em3 em2
  local pre=r(p)
  post `res' ("pop_coverage") ("`r'") ("`basis'_level") (`b') (`se') (`p') (`n') (.) (`pre')

  quietly reghdfe d_h`r'_`basis'_covpop did if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
  post `res' ("pop_coverage") ("`r'") ("`basis'_change") (_b[did]) (_se[did]) (2*ttail(e(df_r),abs(_b[did]/_se[did]))) (e(N)) (.) (.)

  quietly reghdfe ln_h`r'_`basis'_covpop did if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
  post `res' ("pop_coverage") ("`r'") ("`basis'_lnlevel") (_b[did]) (_se[did]) (2*ttail(e(df_r),abs(_b[did]/_se[did]))) (e(N)) (.) (.)
 }
 esttab pop_`basis'_200 pop_`basis'_500 pop_`basis'_1000 using "$RP/population_coverage_`basis'.rtf", replace rtf ///
  keep(did) b(2) se(2) star(* 0.10 ** 0.05 *** 0.01) ///
  mtitles("Hospital 200m" "Hospital 500m" "Hospital 1000m") ///
  stats(depmean N r2_within r2_a, fmt(2 0 3 3) labels("Outcome mean" "Observations" "Within R-squared" "Adjusted R-squared")) ///
  title("DID: population covered by 500m pharmacy service areas (`basis')") ///
  addnote("Hospital and county-by-year fixed effects; standard errors clustered by county." "p13 fixes population at its 2013 distribution; ann uses annual population.")
}

* Placebo cumulative-radius robustness: repeat every pharmacy-count-change
* specification with the change in nearby wellness-establishment counts.
foreach r in 200 500 800 1000 {
 quietly reghdfe ysne`r' did if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
 esttab using "$RP/placebo_cumulative_`r'.rtf", replace rtf ///
  keep(did) b(3) se(3) star(* 0.10 ** 0.05 *** 0.01) ///
  stats(N r2_within r2_a, labels("Observations" "Within R-squared" "Adjusted R-squared")) ///
  title("Placebo DID: wellness establishments within `r' meters")
 post `res' ("placebo_cumulative") ("`r'") ("baseline") (_b[did]) (_se[did]) (2*ttail(e(df_r),abs(_b[did]/_se[did]))) (e(N)) (.) (.)
 quietly reghdfe ysne`r' dn, absorb(hospital_id cyt) vce(cluster cid)
 post `res' ("placebo_cumulative") ("`r'") ("non_tcm") (_b[dn]) (_se[dn]) (2*ttail(e(df_r),abs(_b[dn]/_se[dn]))) (e(N)) (.) (.)
 quietly reghdfe ysne`r' dnon dt if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
 foreach v in dnon dt {
  post `res' ("placebo_cumulative") ("`r'") ("`v'") (_b[`v']) (_se[`v']) (2*ttail(e(df_r),abs(_b[`v']/_se[`v']))) (e(N)) (.) (.)
 }
 quietly reghdfe ysne`r' `cells' if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
 local n=e(N)
 quietly count if e(sample) & did==1
 local total=r(N)
 local expr "0"
 foreach v of local cells {
  quietly count if e(sample) & `v'==1
  if r(N)>0 local expr "`expr'+(`r(N)'/`total')*`v'"
 }
 quietly lincom `expr'
 post `res' ("placebo_cumulative") ("`r'") ("cohort") (r(estimate)) (r(se)) (r(p)) (`n') (.) (.)
}

* Pharmacy-to-nearest-community distance. Outcomes are first differences in
* the hospital-year mean distance (meters). Stock columns use cumulative
* hospital radii; ring columns use mutually exclusive hospital-distance bands.
* A positive DID coefficient means nearby pharmacies became farther from their
* nearest residential community on average.
eststo clear
foreach r in 200 500 1000 {
 local y dxq_stock_`r'
 quietly reghdfe `y' did if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
 estimates store xq_stock_`r'
 quietly summarize `y' if e(sample)
 post `res' ("xq_stock_change") ("`r'") ("did") (_b[did]) (_se[did]) ///
  (2*ttail(e(df_r),abs(_b[did]/_se[did]))) (e(N)) (r(mean)) (.)
}
esttab xq_stock_200 xq_stock_500 xq_stock_1000 using "$RP/xiaoqu_distance_stock.rtf", replace rtf ///
 keep(did) b(3) se(3) star(* 0.10 ** 0.05 *** 0.01) ///
 mtitles("Within 200m" "Within 500m" "Within 1000m") ///
 stats(N r2_within r2_a, labels("Observations" "Within R-squared" "Adjusted R-squared")) ///
 title("DID: change in mean pharmacy-to-nearest-community distance (stock)") ///
 addnote("Outcomes are year-on-year changes in meters. Hospital and county-by-year fixed effects; SEs clustered by county.")

eststo clear
foreach band in 200 200_500 500_1000 {
 local y dxq_ring_`band'
 quietly reghdfe `y' did if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
 estimates store xq_ring_`band'
 quietly summarize `y' if e(sample)
 post `res' ("xq_ring_change") ("`band'") ("did") (_b[did]) (_se[did]) ///
  (2*ttail(e(df_r),abs(_b[did]/_se[did]))) (e(N)) (r(mean)) (.)
}
esttab xq_ring_200 xq_ring_200_500 xq_ring_500_1000 using "$RP/xiaoqu_distance_ring.rtf", replace rtf ///
 keep(did) b(3) se(3) star(* 0.10 ** 0.05 *** 0.01) ///
 mtitles("0-200m" "200-500m" "500-1000m") ///
 stats(N r2_within r2_a, labels("Observations" "Within R-squared" "Adjusted R-squared")) ///
 title("DID: change in mean pharmacy-to-nearest-community distance (rings)") ///
 addnote("Outcomes are year-on-year changes in meters. Hospital and county-by-year fixed effects; SEs clustered by county.")

* Relocating pharmacies only. The outcomes are already old-to-new location
* changes, evaluated against the same destination-year sets of communities and
* hospitals; do not difference them again. Positive dxq means farther from the
* nearest community, while negative dhosp means closer to the nearest hospital.
foreach scope in stock ring {
 local bands "200 500 1000"
 if "`scope'"=="ring" local bands "200 200_500 500_1000"
 foreach target in dxq dhosp {
  eststo clear
  local models
  foreach band of local bands {
   local y mig_`target'_`scope'_`band'm
   quietly reghdfe `y' did if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
   estimates store mig_`target'_`scope'_`band'
   local models `models' mig_`target'_`scope'_`band'
   quietly summarize `y' if e(sample)
   post `res' ("mig_`target'_`scope'") ("`band'") ("did") (_b[did]) (_se[did]) ///
    (2*ttail(e(df_r),abs(_b[did]/_se[did]))) (e(N)) (r(mean)) (.)
  }
  local targettitle "nearest community"
  local signnote "Positive coefficients mean relocation farther from communities."
  if "`target'"=="dhosp" {
   local targettitle "nearest hospital"
   local signnote "Negative coefficients mean relocation closer to hospitals."
  }
  local mtitles `""0-200m" "200-500m" "500-1000m""'
  if "`scope'"=="stock" local mtitles `""Within 200m" "Within 500m" "Within 1000m""'
  esttab `models' using "$RP/migration_`target'_`scope'.rtf", replace rtf ///
   keep(did) b(3) se(3) star(* 0.10 ** 0.05 *** 0.01) ///
   mtitles(`mtitles') ///
   stats(N r2_within r2_a, labels("Observations" "Within R-squared" "Adjusted R-squared")) ///
   title("DID: relocating pharmacies, change in distance to `targettitle' (`scope')") ///
   addnote("Changes are destination minus origin in meters; migration threshold is 100m. `signnote'")
 }
}

* Public versus non-public tertiary hospitals. Restricting the sample to
* grade-3 hospitals makes non-public tertiary hospitals the untreated control;
* did=Public x Post identifies the differential change at public tertiary hospitals.
foreach outcome in ne st {
 foreach r in 200 500 800 1000 {
  local y ne`r'
  if "`outcome'"=="st" local y pharm_`r'm
  quietly reghdfe `y' did if hospital_level_final==3 & !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
  local n=e(N)
  local b=_b[did]
  local se=_se[did]
  local p=2*ttail(e(df_r),abs(`b'/`se'))
  quietly summarize `y' if e(sample)
  local mean=r(mean)
  esttab using "$RP/grade3_public_vs_nonpublic_`outcome'_`r'.rtf", replace rtf ///
   keep(did) b(3) se(3) star(* 0.10 ** 0.05 *** 0.01) ///
   stats(N r2_within r2_a, labels("Observations" "Within R-squared" "Adjusted R-squared")) ///
   title("Public versus non-public tertiary hospitals: `outcome', `r' meters")
  quietly reghdfe `y' `events' if hospital_level_final==3 & !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
  quietly test em4 em3 em2
  local pre=r(p)
  esttab using "$RP/grade3_public_vs_nonpublic_`outcome'_`r'_event.rtf", replace rtf ///
   keep(`events') b(3) se(3) star(* 0.10 ** 0.05 *** 0.01) ///
   stats(N r2_within r2_a, labels("Observations" "Within R-squared" "Adjusted R-squared")) ///
   title("Event study: public versus non-public tertiary hospitals, `outcome', `r' meters")
  post `res' ("grade3_compare_`outcome'") ("`r'") ("did") (`b') (`se') (`p') (`n') (`mean') (`pre')
  local j=0
  foreach v of local events {
   local ++j
   local k: word `j' of -4 -3 -2 0 1 2 3 4
   if _se[`v']>0 {
    post `ev' ("grade3_compare_`outcome'") ("`r'") (`k') (_b[`v']) (_se[`v']) (2*ttail(e(df_r),abs(_b[`v']/_se[`v']))) (e(N)) (`pre')
   }
  }
  post `ev' ("grade3_compare_`outcome'") ("`r'") (-1) (0) (0) (.) (e(N)) (`pre')
 }
}

gen byte d2=did*(hospital_level_final==2) if !missing(did,hospital_level_final)
gen byte d3=did*(hospital_level_final==3) if !missing(did,hospital_level_final)
foreach outcome in ne st {
 foreach r in 200 500 800 1000 {
  local y ne`r'
  if "`outcome'"=="st" local y pharm_`r'm
  quietly reghdfe `y' did d2 d3 if !missing(pub) & inlist(hospital_level_final,1,2,3), absorb(hospital_id cyt) vce(cluster cid)
  esttab using "$RP/tier_`outcome'_`r'.rtf", replace rtf ///
   keep(did d2 d3) b(3) se(3) star(* 0.10 ** 0.05 *** 0.01) ///
   stats(N r2_within r2_a, labels("Observations" "Within R-squared" "Adjusted R-squared")) ///
   title("Hospital-tier DID: `outcome', `r' meters")
  local n=e(N)
  forvalues q=1/3 {
   local expr "did"
   if `q'>1 local expr "did+d`q'"
   quietly lincom `expr'
   post `res' ("tier_`outcome'") ("`r'") ("grade`q'") (r(estimate)) (r(se)) (r(p)) (`n') (.) (.)
  }
  quietly lincom d3
  post `res' ("tier_`outcome'") ("`r'") ("grade3_minus_grade1") (r(estimate)) (r(se)) (r(p)) (`n') (.) (.)
  * Tier-specific dynamics in the same pooled interaction model.
  local tevents `events'
  foreach v of local events {
   capture drop `v'g2 `v'g3
   gen byte `v'g2=`v'*(hospital_level_final==2)
   gen byte `v'g3=`v'*(hospital_level_final==3)
   local tevents `tevents' `v'g2 `v'g3
  }
  quietly reghdfe `y' `tevents' if !missing(pub) & inlist(hospital_level_final,1,2,3), absorb(hospital_id cyt) vce(cluster cid)
  forvalues q=1/3 {
   if `q'==1 quietly test em4 em3 em2
   else quietly test (em4+em4g`q'=0) (em3+em3g`q'=0) (em2+em2g`q'=0)
   local pre=r(p)
   local j=0
   foreach v of local events {
    local ++j
    local k: word `j' of -4 -3 -2 0 1 2 3 4
    local expr "`v'"
    if `q'>1 local expr "`v'+`v'g`q'"
    quietly lincom `expr'
    if r(se)>0 post `ev' ("tier_`outcome'_g`q'") ("`r'") (`k') (r(estimate)) (r(se)) (r(p)) (e(N)) (`pre')
   }
   post `ev' ("tier_`outcome'_g`q'") ("`r'") (-1) (0) (0) (.) (e(N)) (`pre')
  }
 }
}

* Panel C: cells are tier x cohort x post-calendar-year, with tier-year FE.
local tcells
forvalues q=1/3 {
 foreach v of local cells {
  gen byte t`q'_`v'=`v'*(hospital_level_final==`q')
  local tcells `tcells' t`q'_`v'
 }
}
foreach r in 200 500 800 1000 {
 quietly reghdfe pharm_`r'm `tcells' if !missing(pub) & inlist(hospital_level_final,1,2,3), absorb(hospital_id cyt hospital_level_final#year) vce(cluster cid)
 esttab using "$RP/tier_cohort_`r'.rtf", replace rtf ///
  keep(`tcells') b(3) se(3) star(* 0.10 ** 0.05 *** 0.01) ///
  stats(N r2_within r2_a, labels("Observations" "Within R-squared" "Adjusted R-squared")) ///
  title("Tier-by-cohort-cell regression: `r' meters")
 local n=e(N)
 forvalues q=1/3 {
  quietly count if e(sample) & did==1 & hospital_level_final==`q'
  local total=r(N)
  local expr`q' "0"
  foreach v of local cells {
   quietly count if e(sample) & t`q'_`v'==1
   if r(N)>0 local expr`q' "`expr`q''+(`r(N)'/`total')*t`q'_`v'"
  }
  quietly lincom `expr`q''
  post `res' ("tier_cohort") ("`r'") ("grade`q'") (r(estimate)) (r(se)) (r(p)) (`n') (.) (.)
 }
 quietly lincom (`expr3')-(`expr1')
 post `res' ("tier_cohort") ("`r'") ("grade3_minus_grade1") (r(estimate)) (r(se)) (r(p)) (`n') (.) (.)
}

*===============================================================================
* Explicit manuscript Tables 1--3 replication outputs, integrated from v5.
* These make the main hospital-level audit independent of slide-building code.
*===============================================================================

* Table 1: summary statistics in the net-entry estimation sample.
tempname tab1
postfile `tab1' str40 variable double N mean sd min max using "$RP/table1_reproduced.dta", replace
foreach v in pub public_tcm grade1_hospital grade2_hospital grade3_hospital pharm_200m pharm_500m pharm_800m pharm_1000m ne200 ne500 ne800 ne1000 nearest_pharmacy_m {
 if inlist("`v'","grade1_hospital","grade2_hospital","grade3_hospital") quietly summarize `v' if net_sample & inlist(hospital_level_final,1,2,3)
 else quietly summarize `v' if net_sample
 local scale=1
 if "`v'"=="nearest_pharmacy_m" local scale=1000
 post `tab1' ("`v'") (r(N)) (r(mean)/`scale') (r(sd)/`scale') (r(min)/`scale') (r(max)/`scale')
}
postclose `tab1'

* Table 2: mutually exclusive distance rings and joint lead tests.
tempname tab2
postfile `tab2' str8 panel str8 band double b se mean pretrend N using "$RP/table2_reproduced.dta", replace
foreach outcome in ne st {
 foreach band in gate near outer total {
  quietly reghdfe `outcome'_`band' did if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
  local b=_b[did]
  local se=_se[did]
  local n=e(N)
  quietly summarize `outcome'_`band' if e(sample)
  local mean=r(mean)
  local pre=.
  if "`outcome'"=="ne" {
   quietly reghdfe `outcome'_`band' `events' if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
   quietly test em4 em3 em2
   local pre=r(p)
  }
  post `tab2' ("`outcome'") ("`band'") (`b') (`se') (`mean') (`pre') (`n')
 }
}
postclose `tab2'

* Table 3: alternative estimators and treatment definitions.
tempname tab3
postfile `tab3' str24 specification int radius double b se pretrend N using "$RP/table3_reproduced.dta", replace
foreach r in 200 500 800 1000 {
 quietly reghdfe ne`r' did if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
 local n=e(N)
 local bb=_b[did]
 local ss=_se[did]
 quietly reghdfe ne`r' `events' if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
 quietly test em4 em3 em2
 local pre=r(p)
 post `tab3' ("baseline") (`r') (`bb') (`ss') (`pre') (`n')

 quietly reghdfe ne`r' `cells' if !missing(did), absorb(hospital_id cyt) vce(cluster cid)
 local n=e(N)
 quietly count if e(sample) & did==1
 local total=r(N)
 local expr "0"
 foreach v of local cells {
  quietly count if e(sample) & `v'==1
  if r(N)>0 local expr "`expr'+(`r(N)'/`total')*`v'"
 }
 quietly lincom `expr'
 post `tab3' ("cohort_saturated") (`r') (r(estimate)) (r(se)) (.) (`n')

 quietly reghdfe ne`r' dn, absorb(hospital_id cyt) vce(cluster cid)
 post `tab3' ("public_non_tcm_treated") (`r') (_b[dn]) (_se[dn]) (.) (e(N))

 quietly reghdfe ne`r' dnon dt if !missing(pub), absorb(hospital_id cyt) vce(cluster cid)
 post `tab3' ("public_non_tcm") (`r') (_b[dnon]) (_se[dnon]) (.) (e(N))
 post `tab3' ("public_tcm") (`r') (_b[dt]) (_se[dt]) (.) (e(N))
}
postclose `tab3'

foreach f in table1_reproduced table2_reproduced table3_reproduced {
 preserve
  use "$RP/`f'.dta", clear
  export delimited using "$RP/`f'.csv", replace
 restore
}
postclose `res'
postclose `ev'
foreach f in estimates events descriptives {
 use "$RP/`f'.dta", clear
 export delimited using "$RP/`f'.csv", replace
}
display as result "FULL_HOSPITAL_REPLICATION_ESTIMATION_COMPLETE"
* Windows Stata /e ignores shell commands in batch mode. Run the external
* audit after estimation to compare the fresh output with the manuscript.
display as text "Outputs include pharmacy estimates and wellness-establishment placebo estimates."
log close
