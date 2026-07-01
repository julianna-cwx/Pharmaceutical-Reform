{smcl}
{* *! version 1.0.2 20mar2026}{...}
{vieweralsosee "[D] merge" "help merge"}{...}
{vieweralsosee "[D] joinby" "help joinby"}{...}
{viewerjumpto "Syntax" "cnadmin##syntax"}{...}
{viewerjumpto "Description" "cnadmin##description"}{...}
{viewerjumpto "Requirements" "cnadmin##requirements"}{...}
{viewerjumpto "Data Source" "cnadmin##datasource"}{...}
{viewerjumpto "Options" "cnadmin##options"}{...}
{viewerjumpto "Generated Variables" "cnadmin##generated"}{...}
{viewerjumpto "Examples" "cnadmin##examples"}{...}
{viewerjumpto "Author" "cnadmin##author"}{...}
{viewerjumpto "Acknowledgments" "cnadmin##acknowledgments"}{...}

{title:Title}

{pstd}
    {hi:cnadmin} {hline 2} Matching Chinese Administrative Divisions Across Years

{marker syntax}{...}
{title:Syntax}

{p 8 15 2}
{cmd:cnadmin}
{it:from_year}
{it:to_year}
{it:source_var}
[{cmd:,} {it:options}]

{p 4 4 2}
where:

{p 8 8 2}
{it:from_year} is the origin year of the administrative divisions in your 
dataset (e.g., 2000).{p_end}

{p 8 8 2}
{it:to_year} is the target year you want to map the divisions to (e.g., 2020). 
Backward tracing is fully supported if {it:to_year} < {it:from_year}.{p_end}

{p 8 8 2}
{it:source_var} is the {help varname} containing the origin county administrative 
codes (or county names if {bf:byname} is specified).{p_end}


{synoptset 28 tabbed}{...}
{synopthdr}
{synoptline}
{syntab:Target Variables}
{synopt:{opth code(newvar)}}specify name for the generated target code 
variable; default is {it:code_to} (e.g., code_2020){p_end}
{synopt:{opth prov:ince(newvar)}}specify name for the generated target 
province variable; default is {it:prov_to} (e.g., prov_2020){p_end}
{synopt:{opth pref:ecture(newvar)}}specify name for the generated target 
prefecture (city) variable; default is {it:pref_to} (e.g., pref_2020){p_end}
{synopt:{opth coun:ty(newvar)}}specify name for the generated target 
county variable; default is {it:coun_to} (e.g., coun_2020){p_end}

{syntab:Name-based Matching (Alternative to Code)}
{synopt:{opt byn:ame}}indicate that {it:source_var} contains county names 
(strings) instead of GB codes{p_end}
{synopt:{opth inprov:ince(varname)}}specify the origin province name 
variable; highly recommended with {bf:byname} to anchor homonyms{p_end}
{synopt:{opth inpref:ecture(varname)}}specify the origin prefecture 
name variable; highly recommended with {bf:byname}{p_end}

{syntab:Output Control}
{synopt:{opt noori:gin}}suppress the creation of the origin-year 
administrative variables{p_end}
{synopt:{opt nowei:ght}}suppress the creation of the {it:weight} 
(apportionment weight) variable{p_end}
{synopt:{opt nogen:erate}}suppress the creation of the {it:_type} 
(match quality) variable{p_end}
{synoptline}
{p2colreset}{...}


{marker description}{...}
{title:Description}

{p 4 4 2}
In Chinese empirical research, matching administrative divisions across different 
years is a challenge due to frequent boundary changes, such as 
county-to-district upgrades (撤县设区), mergers, and complex splits. Simple 1:1 
matching often leads to severe data attrition in panel datasets. 

{p 4 4 2}
{cmd:cnadmin} solves this problem by automatically tracking the historical 
changes of any administrative code or name, generating accurate crosswalks 
and weights for complex splits.

{p 4 4 2}
{bf:How it works (Python Engine):}
{break}{cmd:cnadmin} achieves its high performance 
by leveraging the Python integration feature introduced in Stata 16. The 
command models China's administrative changes as a historical timeline 
network (a Directed Acyclic Graph). When you query a mapping from one year 
to another, the Python engine searches through this network to trace the 
complete lineage of the divisions. It dynamically "connects the dots" 
across multiple intermediate changes (e.g., A changes to B in 2005, then B 
changes to C in 2015), ensuring no historical steps are lost.

{p 4 4 2}
{bf:Key features:}
{break}  - {bf:Forward & Backward Tracing:} Map historical data to modern boundaries, 
or trace modern data back to historical boundaries across any specified years.
{break}  - {bf:Split Weighting:} Generates a 1/N weight variable when a historical 
county is split into N modern districts, maintaining spatial attribute conservation.
{break}  - {bf:Name Resolution:} Automatically extracts the historically accurate 
names for any code at the specified target year.

{p 4 4 2}
{bf:▲Notice▲:}
{break}1. Names of any administrative divisions should be written in {bf:full Chinese} characters.
{break}2. When a prefecture-level division does not exist for a county 
(e.g., municipalities and province-administered counties), use "直辖".
Examples: Dongcheng District, Beijing City (北京市东城区); 
Jiyuan City, Henan Province (河南省济源市); Xiantao City, Hubei 
Province (湖北省仙桃市); Wenchang City, Hainan Province (海南省文昌市).
Attention should be paid to this especially when using the {opt byname} 
option with province and prefecture anchor variables.
{break}3. Data covers 1981—2025, with each year reflecting 
administrative divisions as of December 31st.


{marker requirements}{...}
{title:Requirements & Setup}

{p 4 4 2}
{cmd:cnadmin} relies on Stata's Python integration and requires the following setup:

{p 4 4 2}
1. {bf:Stata Version:} Requires Stata version 16.0 or higher.
{break}2. {bf:Python Environment:} You must have Python installed on your computer. 
If Stata does not automatically detect it, you can manually set the Python path 
in Stata by running:
{break}   {cmd:. set python_exec "C:\path\to\your\python.exe", permanently}
{break}3. {bf:Python Dependencies:} The background script relies on the {cmd:pandas} 
library for data manipulation. You can install it quickly by typing the following 
into your Stata command window:
{break}   {cmd:. shell pip install pandas}
{break}4. {bf:Data File:} The underlying database file {cmd:cnadmin_data.maint} must 
be accessible in Stata's system path (e.g., inside your {it:ado/personal} folder) 
or installed simultaneously via {cmd:net install}.


{marker datasource}{...}
{title:Data Source}

{p 4 4 2}
The accuracy of {cmd:cnadmin} fundamentally relies on its underlying tracking 
database of China's administrative divisions ({it:cnadmin_data.maint}), which is 
essentially a {it:csv} file.

{p 4 4 2}
The core historical change logs and GB/T 2260 
code mappings are sourced from the open-source repository 
maintained at: {browse "https://github.com/yescallop/areacodes":yescallop/areacodes}.


{marker options}{...}
{title:Options}

{dlgtab:Target Variables}

{phang}
{opth code(newvar)} specifies the name for the generated target-year administrative 
code variable. If omitted, the command defaults to {it:code_to} (e.g., {it:code_2020}).

{phang}
{opth province(newvar)}, {opth prefecture(newvar)}, and 
{opth county(newvar)} allow you to customize the variable names for 
the generated target-year administrative names. If omitted, the command defaults 
to dynamic names such as {it:prov_2020}, {it:pref_2020}, and {it:coun_2020} 
(based on your {it:to_year} input).

{dlgtab:Name-based Matching}

{phang}
{bf:byname} alters the core behavior of the command. By default, {cmd:cnadmin} 
assumes {it:source_var} contains 6-digit administrative codes. If your dataset 
only has Chinese strings for county names (e.g., "东城区"), specify this option.

{phang}
{opth inprovince(varname)} and {opth inprefecture(varname)} are strongly 
advised when using {bf:byname}. China has numerous homonymous jurisdictions 
across different provinces (e.g., "鼓楼区" exists in Nanjing, Fuzhou, and Xuzhou). 
Providing the origin province and city variables anchors the match and prevents 
catastrophic Cartesian misallocation.

{dlgtab:Output Control}

{phang}
{opt noorigin} prevents the command from adding 
the origin-year administrative variables (e.g., {it:code_2000}, {it:prov_2000}) 
to your dataset. Useful when you only want to append the target-year mapping and 
keep the dataset clean.

{phang}
{opt noweight}  prevents the command from adding 
the {it:weight} variable to your dataset. Useful when you only need jurisdiction 
mappings and do not intend to calculate apportioned aggregates.

{phang}
{opt nogenerate} prevents the command from adding 
the {it:_type} variable to your dataset. The matching quality report will still 
be printed in the Stata console.


{marker generated}{...}
{title:Generated Variables}

{p 4 4 2}
Unless suppressed by options, running {cmd:cnadmin} automatically generates the 
following new variables in your dataset:

{phang}{bf:Target Code} (default {it:code_to}, e.g., code_2020): The 6-digit 
administrative code in the target year (specified via the {opt code()} option).

{phang}{bf:Target Province} (default {it:prov_to}, e.g., prov_2020): The name 
of the province in the target year (specified via the {opt province()} option).

{phang}{bf:Target Prefecture} (default {it:pref_to}, e.g., pref_2020): The name 
of the prefecture (City) in the target year (specified via the {opt prefecture()} option).

{phang}{bf:Target County} (default {it:coun_to}, e.g., coun_2020): The name 
of the county/district in the target year (specified via the {opt county()} option).

{phang}{bf:Origin Code / Name Variables}: The unique origin-year administrative 
attributes identified based on your {it:from_year} input 
(e.g., {it:code_2000}, {it:prov_2000}, {it:pref_2000}, {it:coun_2000}). 
{break}  - When matching by code (default): generates Origin Province, Prefecture, and County names.
{break}  - When matching {opt byname}: generates Origin Code, and (if corresponding anchor variables are omitted) Origin Province and Prefecture names.

{phang}{bf:weight}: A numeric float. Equals 1.0 for 1:1 matches. For 1-to-N splits, 
it equals 1/N.

{phang}{bf:_type}: An integer indicating the lineage quality of the observation. 

{phang2}{bf:0} = Unmatched (Orphan/Zombie code).{p_end}
{phang2}{bf:1} = Perfect Match (Stable polygon, no code or name change).{p_end}
{phang2}{bf:2} = Renamed/Changed (1:1 mapping, but code/name altered, e.g., upgraded).{p_end}
{phang2}{bf:3} = Complex Match (1-to-N splits or multi-lineage, check weights).{p_end}


{marker examples}{...}
{title:Examples}

{p 4 4 2}
{bf:1. Basic Forward Code Matching}

{p 8 8 2}Map historical 2000 census county codes to modern 2020 district codes:{p_end}
{p 8 12 2}{cmd:. cnadmin 2000 2020 countycode_2000, code(countycode_2020)}{p_end}

{p 4 4 2}
{bf:2. Backward Tracing with Custom Variables and Clean Output}

{p 8 8 2}Trace 2020 firm locations back to 2010 boundaries for a DID policy evaluation:{p_end}
{p 8 12 2}{cmd:. cnadmin 2020 2010 current_code, code(hist_code) prov(p_name) pref(c_name) coun(d_name) nogen noori}{p_end}

{p 4 4 2}
{bf:3. Name-based Matching with Anchors}

{p 8 8 2}When codes are missing, use strings to match, anchoring with province and city variables:{p_end}
{p 8 12 2}{cmd:. cnadmin 2000 2020 counname, byname inprov(provname) inpref(cityname) code(code_2020)}{p_end}


{marker author}{...}
{title:Author}

{p 4 4 2}
Qiteng Wang
{break}Business School, Nanjing University
{break}Email: {browse "mailto:qitengwang@foxmail.com":qitengwang@foxmail.com}
{break}GitHub: {browse "https://github.com/Taboo725/cnadmin":https://github.com/Taboo725/cnadmin}
{p_end}

{p 4 4 2}
If you encounter any bugs or have suggestions, please open an issue on GitHub.
{p_end}


{marker acknowledgments}{...}
{title:Acknowledgments}

{p 4 4 2}
I express my deepest gratitude to the contributors of the {browse "https://github.com/yescallop/areacodes":areacodes repository} 
for their meticulous efforts in digitizing and standardizing decades of Chinese 
civil affairs data. Users are encouraged to visit their repository for updates 
on the raw data structure.
{p_end}