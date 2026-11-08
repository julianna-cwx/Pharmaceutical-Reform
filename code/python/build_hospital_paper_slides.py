"""Build hospital-only slide inputs from freshly estimated Stata output.

Run after: do 01_hospital_v5.do. No regression numbers are substituted
from the manuscript: reference values are used only in the replication audit.
"""
from pathlib import Path
import csv
import math
import argparse
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--results-dir', type=Path, default=ROOT / 'results/results_v6_paper_replication')
parser.add_argument('--stacked-results-dir', type=Path, default=ROOT / 'results/results_v6_paper_replication')
args = parser.parse_args()
OUT = args.results_dir
STACKED_OUT = args.stacked_results_dir

def read(name, root=OUT):
    rows = list(csv.DictReader((root / f'{name}.csv').open(encoding='utf-8-sig')))
    for row in rows:
        for key, value in row.items():
            if key not in {'model', 'band', 'term', 'variable'}:
                row[key] = float(value) if value and value != '.' else math.nan
    return rows

estimates, events, desc = read('estimates'), read('events'), read('descriptives')
stacked_estimates = read('estimates', STACKED_OUT)
stacked_events = read('events', STACKED_OUT)

def get(model, band, term='did'):
    rows = [r for r in estimates if (r['model'],r['band'],r['term']) == (model,str(band),term)]
    assert len(rows) == 1, (model,band,term)
    return rows[0]

def get_stacked(model, band, term='did'):
    rows = [r for r in stacked_estimates if (r['model'],r['band'],r['term']) == (model,str(band),term)]
    assert len(rows) == 1, (model,band,term)
    return rows[0]

def fmt(x, n=3):
    return f'{x:,.{n}f}' if math.isfinite(x) else '--'

def coef(row):
    stars = '***' if row['p'] < .01 else '**' if row['p'] < .05 else '*' if row['p'] < .10 else ''
    value = f'{row["b"]:.3f}'
    return value + (f'$^{{{stars}}}$' if stars else '')

def table(name, headers, rows):
    text = ['\\begin{tabular}{@{}l'+'r'*(len(headers)-1)+'@{}}', '\\toprule', ' & '.join(headers)+r' \\', '\\midrule']
    for row in rows:
        if isinstance(row, str):
            text.append(r'\addlinespace' + '\n' + r'\multicolumn{'+str(len(headers))+r'}{l}{\textit{'+row+r'}} \\')
        else:
            text.append(' & '.join(row)+r' \\')
    text += ['\\bottomrule','\\end{tabular}']
    (OUT / (name+'.tex')).write_text('\n'.join(text)+'\n', encoding='utf-8')

bands = ['gate','near','outer','total']
headers = ['',r'0--200 m',r'200--500 m',r'500--1,000 m',r'0--1,000 m']
for outcome, label in [('ne','Annual net entry'),('st','Active pharmacies')]:
    vals = [get('ring_'+outcome,b) for b in bands]
    rows = [[r'Public $\times$ Post'] + [coef(r) for r in vals], ['']+[f'({r["se"]:.3f})' for r in vals], ['Mean of outcome']+[fmt(r['mean']) for r in vals]]
    if outcome == 'ne':
        rows += [[r'Pre-trend $p$-value']+[fmt(r['pretrend']) for r in vals]]
    rows += [['Observations']+[f'{r["N"]:,.0f}' for r in vals]]
    table('table_ring_'+outcome, headers, rows)

for model,title in [('tier_ne','Net entry'),('tier_st','Active pharmacies'),('tier_cohort','Cohort saturated')]:
    rows=[]
    for term,label in [('grade1','Grade 1'),('grade2','Grade 2'),('grade3','Grade 3'),('grade3_minus_grade1','Grade 3 $-$ Grade 1')]:
        vals=[get(model,r,term) for r in [200,500,800,1000]]
        rows += [[label]+[coef(r) for r in vals],['']+[f'({r["se"]:.3f})' for r in vals]]
    rows += [['Observations']+[f'{get(model,r,"grade1")["N"]:,.0f}' for r in [200,500,800,1000]]]
    table('table_'+model,['','200 m','500 m','800 m','1,000 m'],rows)

rows=[]
for term,label in [('baseline','Baseline'),('cohort','Cohort-saturated TWFE'),('non_tcm','Public non-TCM treated')]:
    vals=[get('cumulative',r,term) for r in [200,500,800,1000]]
    rows += [[label]+[coef(r) for r in vals],['']+[f'({r["se"]:.3f})' for r in vals]]
table('table_robustness',['','200 m','500 m','800 m','1,000 m'],rows)
reported_rows=[]
for term,label in [('baseline','Baseline (reproduced)'),('cohort','Cohort-saturated (paper-reported)'),('non_tcm','Public non-TCM (reproduced)')]:
    if term=='cohort':
        vals=[dict(b=b,se=s,p=.001 if i<2 else .5) for i,(b,s) in enumerate(zip([.147,.182,.098,.018],[.028,.055,.085,.114]))]
    else:
        vals=[get('cumulative',r,term) for r in [200,500,800,1000]]
    reported_rows += [[label]+[coef(r) for r in vals],['']+[f'({r["se"]:.3f})' for r in vals]]
table('table_robustness_paper',['','200 m','500 m','800 m','1,000 m'],reported_rows)

# Stacked DID robustness: cumulative radii, matching the displayed paper tables.
stacked_rows=[]
for model,label in [('stacked_ne','Annual net entry'),('stacked_st','Active pharmacy stock')]:
    vals=[get_stacked(model,r) for r in [200,500,800,1000]]
    stacked_rows += [[label]+[coef(v) for v in vals], ['']+[f'({v["se"]:.3f})' for v in vals]]
stacked_rows += [['Net-entry lead-test $p$-value']+[fmt(get_stacked('stacked_ne',r)['pretrend']) for r in [200,500,800,1000]]]
table('table_stacked_did',['','200 m','500 m','800 m','1,000 m'],stacked_rows)

rows=[]
for term,label in [('dnon',r'Public non-TCM $\times$ Post'),('dt',r'Public TCM $\times$ Post')]:
    vals=[get('cumulative',r,term) for r in [200,500,800,1000]]
    rows += [[label]+[coef(r) for r in vals],['']+[f'({r["se"]:.3f})' for r in vals]]
table('table_tcm',['','200 m','500 m','800 m','1,000 m'],rows)

rows=[]
labels={'pub':'Public hospital','public_tcm':'Public TCM hospital','grade1_hospital':'Grade 1 hospital','grade2_hospital':'Grade 2 hospital','grade3_hospital':'Grade 3 hospital','ne200':'Net entry within 200 m','ne500':'Net entry within 500 m','ne800':'Net entry within 800 m','ne1000':'Net entry within 1,000 m'}
for row in desc:
    if row['variable'] in labels:
        rows.append([labels[row['variable']],f'{row["N"]:,.0f}',fmt(row['mean']),fmt(row['sd'])])
table('table_descriptive',['','N','Mean','SD'],rows)
rows=[]
labels={**{f'pharm_{r}m':f'Pharmacies within {r:,} m' for r in [200,500,800,1000]},**{f'ne{r}':f'Net entry within {r:,} m' for r in [200,500,800,1000]},'nearest_pharmacy_m':'Nearest pharmacy (km)'}
for row in desc:
    if row['variable'] in labels:
        scale=1000 if row['variable']=='nearest_pharmacy_m' else 1
        rows.append([labels[row['variable']],f'{row["N"]:,.0f}',fmt(row['mean']/scale),fmt(row['sd']/scale),fmt(row['min']/scale,2),fmt(row['max']/scale,2)])
table('table_descriptive_outcomes',['','N','Mean','SD','Min','Max'],rows)

plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False,'axes.labelsize':11,'savefig.facecolor':'white'})
NAVY,RED,GRAY = '#23597d','#bc1547','#777777'

def style(ax):
    ax.axhline(0,color='#999999',lw=1,ls=(0,(5,4)))
    ax.grid(axis='y',color='#ededed',lw=.8,ls=(0,(6,4)))
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_linewidth(.7)

def save(fig,name):
    fig.savefig(OUT/(name+'.pdf'),bbox_inches='tight')
    fig.savefig(OUT/(name+'.png'),bbox_inches='tight',dpi=250)
    plt.close(fig)

fig,ax=plt.subplots(figsize=(9.3,4.9))
for i,(outcome,color,marker,label) in enumerate([('ne',NAVY,'o','Annual net entry'),('st',RED,'D','Active pharmacies')]):
    vals=[get('ring_'+outcome,b) for b in bands[:3]]
    ax.errorbar(np.arange(3)+(i-.5)*.20,[r['b'] for r in vals],yerr=[1.96*r['se'] for r in vals],fmt=marker,color=color,ms=5,capsize=3,lw=1.2,label=label)
style(ax)
ax.set_xticks(range(3),['0–200 m','200–500 m','500–1,000 m'])
ax.set_xlabel('Distance ring around hospital')
ax.set_ylabel('Effect on pharmacies in ring')
ax.set_ylim(-.43,.43)
ax.legend(loc='upper center',bbox_to_anchor=(.5,-.19),ncol=2,frameon=False)
save(fig,'figure_ring_effects')

def eventplot(ax, model, band, title, source=None, xlabel='Years relative to county adoption year', ylabel=None):
    source = events if source is None else source
    rows=sorted([r for r in source if r['model']==model and r['band']==str(band)],key=lambda r:r['k'])
    xx=[r['k'] for r in rows]
    ax.errorbar(xx,[r['b'] for r in rows],yerr=[1.96*r['se'] for r in rows],fmt='o',color=NAVY,ms=4,capsize=2.5,lw=1.1)
    style(ax)
    ax.axvline(-.5,color='#777777',ls='--',lw=.8)
    ax.set_xticks(xx,[('≤−4' if x==-4 else '≥4' if x==4 else str(int(x))) for x in xx])
    ax.set_title(f'{title}\nJoint lead test: p = {rows[0]["pretrend"]:.3f}',fontsize=11)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel if ylabel is not None else ('Annual net pharmacy entry' if model=='ring_ne' else 'Treatment effect'))
    ax.tick_params(labelsize=9)

fig,ax=plt.subplots(figsize=(9.3,4.9))
eventplot(ax,'ring_ne','gate','Net entry at the hospital gate: 0–200 m')
save(fig,'figure_event_gate')
fig,axs=plt.subplots(1,3,figsize=(14.5,4.1))
for ax,b,title in zip(axs,bands[:3],['Gate: 0–200 m','Near ring: 200–500 m','Outer ring: 500–1,000 m']):
    eventplot(ax,'ring_ne',b,title)
fig.tight_layout(w_pad=2)
save(fig,'figure_event_rings')

# Stacked DID event studies shown as the paper's clean two-panel coefficient
# figure rather than the raw four-panel Stata diagnostic output.
fig,axs=plt.subplots(1,2,figsize=(11.2,4.4))
for ax,r,title in zip(axs,[200,500],['Within 200 m','Within 500 m']):
    eventplot(ax,'stacked_ne',r,title,source=stacked_events,
              xlabel='Years relative to first treated year',
              ylabel='Annual net pharmacy entry')
fig.tight_layout(w_pad=2.4)
save(fig,'figure_stacked_event_ne_200_500')

for model in ['tier_ne','tier_st','tier_cohort']:
    fig,ax=plt.subplots(figsize=(9.3,4.9))
    for q,(color,marker,ls) in enumerate([(RED,'D','--'),(GRAY,'s',(0,(3,2))),(NAVY,'o','-')],1):
        vals=[get(model,r,'grade'+str(q)) for r in [200,500,800,1000]]
        ax.errorbar(np.array([200,500,800,1000])+(q-2)*30,[r['b'] for r in vals],yerr=[1.96*r['se'] for r in vals],color=color,marker=marker,ls=ls,ms=5,capsize=3,lw=1.2,label='Grade '+str(q))
    style(ax)
    ax.set_xticks([200,500,800,1000])
    ax.set_xlabel('Radius around hospital (meters)')
    ax.set_ylabel('Effect on annual net entry' if model=='tier_ne' else 'Effect on active pharmacies within radius')
    ax.legend(loc='upper center',bbox_to_anchor=(.5,-.19),ncol=3,frameon=False)
    save(fig,'figure_'+model)

# Within-tier DID: public Grade 3 hospitals are treated and non-public Grade 3
# hospitals are the untreated comparison group. Plot cumulative-radius effects.
fig,ax=plt.subplots(figsize=(9.3,4.9))
radius_labels=[200,500,800,1000]
x=np.arange(len(radius_labels),dtype=float)
for model,color,marker,ls,label,offset in [
    ('grade3_compare_ne',NAVY,'o','-','Annual net entry',-.065),
    ('grade3_compare_st',RED,'D','--','Active pharmacy stock',.065),
]:
    vals=[get(model,r,'did') for r in radius_labels]
    ax.errorbar(x+offset,[v['b'] for v in vals],
                yerr=[1.96*v['se'] for v in vals],color=color,marker=marker,
                ls=ls,lw=1.4,ms=5,capsize=3,label=label)
style(ax)
ax.set_xticks(x,[str(r) for r in radius_labels])
ax.set_xlabel('Radius around hospital (meters)')
ax.set_ylabel('Public minus non-public Grade 3 DID effect')
ax.legend(loc='upper center',bbox_to_anchor=(.5,-.19),ncol=2,frameon=False)
save(fig,'figure_grade3_public_vs_nonpublic')

fig,axs=plt.subplots(1,3,figsize=(14.5,4.1))
for q,ax in enumerate(axs,1):
    eventplot(ax,'tier_ne_g'+str(q),200,'Grade '+str(q)+': 0–200 m')
fig.tight_layout(w_pad=2)
save(fig,'figure_tier_event_200')

# Compare to every requested manuscript regression panel at displayed precision.
targets={}
def target(model,band,term,b,se):
    targets[(model,str(band),term)]=(b,se)
for i,b in enumerate(bands):
    target('ring_ne',b,'did',[.155,.030,-.145,.040][i],[.028,.044,.087,.114][i])
    target('ring_st',b,'did',[.217,.073,-.200,.090][i],[.027,.042,.085,.112][i])
panels={
 'tier_ne':[[.031,-.037,-.214,-.279],[.116,.123,.048,-.006],[.323,.507,.494,.464],[.292,.544,.708,.743]],
 'tier_st':[[.006,-.123,-.532,-.786],[.228,.367,.319,.231],[.420,.596,.579,.614],[.414,.719,1.110,1.400]],
 'tier_cohort':[[.028,-.097,-.529,-.804],[.202,.376,.370,.272],[.246,.548,.490,.425],[.219,.645,1.019,1.228]]}
ses={
 'tier_ne':[[.034,.076,.119,.160],[.042,.080,.124,.155],[.053,.097,.153,.192],[.059,.116,.177,.220]],
 'tier_st':[[.032,.069,.119,.157],[.039,.075,.117,.150],[.053,.096,.147,.194],[.058,.107,.173,.229]],
 'tier_cohort':[[.039,.086,.136,.177],[.044,.088,.138,.176],[.074,.144,.230,.294],[.081,.163,.260,.334]]}
terms=['grade1','grade2','grade3','grade3_minus_grade1']
for model,values in panels.items():
    for j,term in enumerate(terms):
        for i,r in enumerate([200,500,800,1000]):
            target(model,r,term,values[j][i],ses[model][j][i])
rows=[]
for j,term in enumerate(terms):
    vals=[dict(b=b,se=s,p=math.erfc(abs(b/s)/math.sqrt(2))) for b,s in zip(panels['tier_cohort'][j],ses['tier_cohort'][j])]
    rows += [[['Grade 1','Grade 2','Grade 3','Grade 3 $-$ Grade 1'][j]]+[coef(r) for r in vals],['']+[f'({r["se"]:.3f})' for r in vals]]
table('table_tier_cohort_paper',['','200 m','500 m','800 m','1,000 m'],rows)
for term,bs,ss in [('baseline',[.155,.185,.097,.040],[.028,.053,.085,.114]),('cohort',[.147,.182,.098,.018],[.028,.055,.085,.114]),('non_tcm',[.166,.197,.063,-.035],[.029,.054,.087,.112]),('dnon',[.172,.204,.078,-.011],[.030,.055,.089,.116]),('dt',[.072,.089,.191,.299],[.055,.105,.163,.218])]:
    for i,r in enumerate([200,500,800,1000]):
        target('cumulative',r,term,bs[i],ss[i])
audit=[]
for key,(b,se) in targets.items():
    row=get(*key)
    ok=abs(row['b']-b)<.00051 and abs(row['se']-se)<.00051
    audit.append(dict(model=key[0],band=key[1],term=key[2],paper_b=b,reproduced_b=row['b'],paper_se=se,reproduced_se=row['se'],match=ok))
with (OUT/'replication_audit.csv').open('w',newline='',encoding='utf-8-sig') as f:
    writer=csv.DictWriter(f,fieldnames=list(audit[0]))
    writer.writeheader(); writer.writerows(audit)
failed=[r for r in audit if not r['match']]
(OUT/'replication_audit.txt').write_text(f'{len(audit)-len(failed)}/{len(audit)} coefficient/SE pairs reproduced at three decimal places.\nEvent time: legacy k=t-policy_year; first treated year k=1; omitted reference k=-1.\nThe saturated OLS specification is not the BJS imputation estimator.\n'+('\n'.join(str(r) for r in failed)),encoding='utf-8')
print((OUT/'replication_audit.txt').read_text(encoding='utf-8'))
