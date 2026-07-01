*! Version:     1.0.2
*! Author:      Qiteng Wang
*! Affiliation: Business School, Nanjing University
*! E-mail:      qitengwang@foxmail.com 
*! Date:        2026/03/20                   

program define cnadmin
    version 16.0
    
    syntax anything , [CODE(name) PROVince(name) PREFecture(name) COUNty(name) BYName INPROVince(varname) INPREFecture(varname) NOGenerate NOWEIght NOORIgin]
    
    tokenize `"`anything'"'
    local from `1'
    local to `2'
    local source_var `3' 
    
    if "`source_var'" == "" | `"`4'"' != "" {
        display as error "Syntax error or missing parameters!"
        display as error "Usage: cnadmin from_year to_year source_var [, code(var) byname inprov(var) inpref(var) prov(var) pref(var) coun(var) nogen nowei noori]"
        exit 198
    }
    
    confirm integer number `from'
    confirm integer number `to'
    confirm variable `source_var'
    
    * Set default dynamic names for target variables
    if "`code'" == "" local code "code_`to'"
    if "`province'" == "" local province "prov_`to'"
    if "`prefecture'" == "" local prefecture "pref_`to'"
    if "`county'" == "" local county "coun_`to'"
    
    cap findfile "cnadmin_data.maint"
    if _rc {
        display as error "[Fatal Error] Required database file (cnadmin_data.maint) not found."
        display as error "Please ensure the package is fully installed. If testing manually, place 'cnadmin_data.maint' in your Stata ado/personal directory."
        exit 198
    }
    local csv_path "`r(fn)'" 
    
    tempfile cw_csv
    
    if "`byname'" != "" {
        display as text "Building temporal network: Matching by {bf:Name} (`from' -> `to')..."
        if "`inprovince'" == "" & "`inprefecture'" == "" {
            display as error "{bf:[Warning]} You are matching by county name solely!"
            display as error "Homonymous counties exist across China. Specifying inprov() or inpref() is strongly recommended to avoid Cartesian misallocation."
        }
    }
    else {
        display as text "Building temporal network: Matching by {bf:Code} (`from' -> `to')..."
    }
    
    python: build_crosswalk(r"""`csv_path'""", r"""`cw_csv'""", `from', `to')
    
    preserve
    
    cap import delimited "`cw_csv'", clear stringcols(_all) encoding("utf-8")
    if _rc {
        display as error "Merge aborted: Python backend failed to generate the crosswalk file. Check data format."
        restore
        exit 198
    }
    
    quietly count
    if r(N) == 0 {
        display as text "Warning: No transition records found. The sample might be empty for the specified years."
        restore
        exit 0
    }
    
    if "`byname'" != "" {
        rename name_from `source_var'
        local join_keys "`source_var'"
        
        if "`inprefecture'" != "" {
            rename city_from `inprefecture'
            local join_keys "`inprefecture' `join_keys'"
        }
        else {
            qui rename city_from pref_`from'
        }
        
        if "`inprovince'" != "" {
            rename prov_from `inprovince'
            local join_keys "`inprovince' `join_keys'"
        }
        else {
            qui rename prov_from prov_`from'
        }
        
        qui rename code_from code_`from'
    }
    else {
        rename code_from `source_var'
        local join_keys "`source_var'"
        
        qui rename name_from coun_`from'
        qui rename city_from pref_`from'
        qui rename prov_from prov_`from'
    }
    
    if "`code'" != "code_to" {
        qui rename code_to `code'
    }
    qui rename prov_to `province'
    qui rename city_to `prefecture'
    qui rename name_to `county'
    
    qui destring weight, replace
    qui destring _type, replace
    
    tempfile crosswalk_dta
    qui save `crosswalk_dta', replace
    restore
    
    qui cap tostring `source_var', replace
    
    qui joinby `join_keys' using `crosswalk_dta', unmatched(master)
    
    qui replace _type = 0 if _merge == 1
    
    cap label drop match_lbl
    qui label define match_lbl 0 "Unmatched" 1 "Perfect Match" 2 "Renamed/Changed" 3 "Complex/Split"
    qui label values _type match_lbl
    
    quietly count if _type == 1
    local match_1 = r(N)
    quietly count if _type == 2
    local match_2 = r(N)
    quietly count if _type == 3
    local match_3 = r(N)
    quietly count if _type == 0
    local match_0 = r(N)
    
    * Formatted, precise, and orderly console output
    display as result "--------------------------------------------------------"
    display as text   "  Cross-period Match Quality Report (`from' -> `to')"
    display as result "--------------------------------------------------------"
    display as text   "  0: Unmatched origin (dropped)     : " as error  %8.0fc `match_0'
    display as text   "  1: Perfect match (stable)         : " as result %8.0fc `match_1'
    display as text   "  2: Renamed/changed (1:1 mapped)   : " as result %8.0fc `match_2'
    display as text   "  3: Complex match (split/merged)   : " as result %8.0fc `match_3'
    display as result "--------------------------------------------------------"
    
    drop _merge
    
    if "`nogenerate'" != "" {
        cap drop _type
    }
    if "`noweight'" != "" {
        cap drop weight
    }
    if "`noorigin'" != "" {
        if "`byname'" == "" {
            cap drop coun_`from'
            cap drop pref_`from'
            cap drop prov_`from'
        }
        else {
            cap drop code_`from'
            if "`inprefecture'" == "" cap drop pref_`from'
            if "`inprovince'" == "" cap drop prov_`from'
        }
    }
end

* ======================================================================
* Background Python Engine
* ======================================================================
python
import sys
import traceback
import pandas as pd
import collections

def build_crosswalk(csv_path, out_path, start_year, end_year):
    try:
        try:
            df = pd.read_csv(csv_path, dtype=str, encoding='utf-8-sig')
        except UnicodeDecodeError:
            df = pd.read_csv(csv_path, dtype=str, encoding='gbk')

        df.columns = df.columns.str.strip()
        required_cols = ['代码', '一级行政区', '二级行政区', '名称', '状态', '启用时间', '变更/弃用时间', '新代码']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            print(">>> Data Column Missing Error: Required columns are absent - " + str(missing_cols))
            return

        def to_int(x):
            try: return int(float(x))
            except: return None

        df['start_yr'] = df['启用时间'].apply(to_int)
        df['end_yr'] = df['变更/弃用时间'].apply(to_int)

        events = collections.defaultdict(lambda: collections.defaultdict(list))
        rev_events = collections.defaultdict(lambda: collections.defaultdict(list))
        death_years = {}
        birth_years = {}
        code_info_history = collections.defaultdict(list)
        base_codes = set()

        for _, row in df.iterrows():
            c = str(row['代码']).strip()
            if c and c != 'nan':
                base_codes.add(c)
                
            prov = str(row['一级行政区']).strip()
            city = str(row['二级行政区']).strip()
            n = str(row['名称']).strip()
            
            if prov == 'nan': prov = ""
            if city == 'nan': city = ""
            if n == 'nan': n = ""
            
            status = str(row['状态']).strip()
            sy = row['start_yr']
            ey = row['end_yr']
            
            if pd.notna(sy):
                if c not in birth_years or sy < birth_years[c]:
                    birth_years[c] = sy
                    
            code_info_history[c].append((sy, ey if pd.notna(ey) else 9999, prov, city, n))
            
            if status == '弃用' and pd.notna(ey):
                death_years[c] = ey
                
            nc_str = str(row['新代码']).strip()
            if nc_str and nc_str not in ['nan', 'None', '']:
                parts = nc_str.split(';')
                for p in parts:
                    p = p.strip()
                    if '[' in p:
                        target = p.split('[')[0]
                        year = int(p.split('[')[1].replace(']', ''))
                    else:
                        target = p
                        year = ey if pd.notna(ey) else 9999
                    
                    if year != 9999:
                        events[c][year].append(target)
                        rev_events[target][year].append(c)

        def trace_forward(c, curr_yr, target_yr):
            valid_years = sorted([y for y in events[c].keys() if curr_yr < y <= target_yr])
            if not valid_years:
                if c not in death_years or death_years[c] > target_yr:
                    return [c]
                else:
                    return []
            ny = valid_years[0]
            targets = events[c][ny]
            res = []
            for t in targets:
                res.extend(trace_forward(t, ny, target_yr))
            died = (c in death_years and death_years[c] == ny)
            if not died:
                res.extend(trace_forward(c, ny, target_yr))
            return list(set(res))

        def trace_backward(c, curr_yr, target_yr):
            valid_years = sorted([y for y in rev_events[c].keys() if target_yr < y <= curr_yr], reverse=True)
            if not valid_years:
                b_yr = birth_years.get(c, 0)
                d_yr = death_years.get(c, 9999)
                if (pd.notna(b_yr) and b_yr <= target_yr) and (target_yr < d_yr):
                    return [c]
                else:
                    return []
            ny = valid_years[0]
            sources = rev_events[c][ny]
            res = []
            for s in sources:
                res.extend(trace_backward(s, ny - 1, target_yr))
            b_yr = birth_years.get(c, 0)
            if pd.notna(b_yr) and b_yr < ny:
                res.extend(trace_backward(c, ny - 1, target_yr))
            return list(set(res))

        def get_info(code, target_yr):
            hist = code_info_history.get(code, [])
            for s_yr, e_yr, prov, city, n in hist:
                if pd.notna(s_yr) and s_yr <= target_yr and target_yr <= e_yr:
                    return prov, city, n
            if hist:
                last = sorted(hist, key=lambda x: x[1])[-1]
                return last[2], last[3], last[4]
            return "", "", ""

        crosswalk = []
        is_forward = (start_year <= end_year)

        for bc in base_codes:
            if is_forward:
                final_codes = trace_forward(bc, start_year, end_year)
            else:
                final_codes = trace_backward(bc, start_year, end_year)
            for fc in final_codes:
                crosswalk.append({'code_from': bc, 'code_to': fc})

        cw_df = pd.DataFrame(crosswalk)

        if not cw_df.empty:
            cw_df['weight'] = 1.0 / cw_df.groupby('code_from')['code_to'].transform('count')
            
            info_from = cw_df['code_from'].apply(lambda x: get_info(x, start_year)).tolist()
            info_to = cw_df['code_to'].apply(lambda x: get_info(x, end_year)).tolist()
            
            cw_df['prov_from'] = [i[0] for i in info_from]
            cw_df['city_from'] = [i[1] for i in info_from]
            cw_df['name_from'] = [i[2] for i in info_from]
            
            cw_df['prov_to'] = [i[0] for i in info_to]
            cw_df['city_to'] = [i[1] for i in info_to]
            cw_df['name_to'] = [i[2] for i in info_to]

            counts = cw_df.groupby('code_from').size().to_dict()
            
            def get_match_type(idx, r):
                if counts[r['code_from']] > 1:
                    return 3
                elif r['code_from'] == r['code_to'] and info_from[idx][2] == info_to[idx][2]:
                    return 1
                else:
                    return 2

            cw_df['_type'] = [get_match_type(i, r) for i, r in cw_df.iterrows()]
            
            cols_to_keep = ['code_from', 'prov_from', 'city_from', 'name_from', 'code_to', 'prov_to', 'city_to', 'name_to', 'weight', '_type']
            cw_df = cw_df[cols_to_keep]
            
            cw_df.to_csv(out_path, index=False, encoding='utf-8')
        else:
            pd.DataFrame(columns=['code_from', 'prov_from', 'city_from', 'name_from', 'code_to', 'prov_to', 'city_to', 'name_to', 'weight', '_type']).to_csv(out_path, index=False, encoding='utf-8')

    except Exception as e:
        err_msg = traceback.format_exc()
        print("\n================ PYTHON CORE CRASH ================")
        print(err_msg)
        print("=================================================\n")
end