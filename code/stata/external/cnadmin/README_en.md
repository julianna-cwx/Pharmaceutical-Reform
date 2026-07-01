<div align="center">

<h1>
  <span>cnadmin</span>
</h1>
<p>
  <span>A Stata command matching Chinese administrative divisions across years.</span>
</p>

<!-- icon -->
![GitHub release (latest by date)](https://img.shields.io/github/v/release/Taboo725/cnadmin?label=last%20version)
![GitHub Release Date](https://img.shields.io/github/release-date/Taboo725/cnadmin)
![StataMin](https://img.shields.io/badge/stata-%3E%3D%2016.0-blue)

<!-- language -->
[简体中文](README.md) | English

</div>

**`cnadmin`** is a Stata command powered by Python that resolves the problem of interannual administrative division matching in Chinese empirical panel data. 

In Chinese economic and sociological research, matching administrative divisions (counties/districts) across different years is notoriously difficult due to frequent boundary changes, such as county-to-district upgrades (撤县设区), mergers, and complex splits. Simple 1:1 matching often leads to severe data attrition. `cnadmin` solves this by automatically tracking historical lineage, generating accurate crosswalks, and computing proper apportionment weights.

## 🌟 Key Features

- **Forward & Backward Tracing:** Map historical administrative divisions data (e.g., 2000) to modern boundaries (e.g., 2020), or trace modern administrative divisions data back to historical boundaries.
- **Split Weighting:** When a historical county is split into N modern districts, it automatically generates a `1/N` weight variable, maintaining spatial attribute conservation for aggregate variables (e.g., population, GDP).
- **Name Resolution:** Automatically extracts the historically accurate province, prefecture (city), and county names for any code at the specified target year.
- **Name-based Matching:** Supports matching by Chinese string names with province and prefecture anchor variables to prevent homonymous jurisdiction confusion.

## 🛠️ Requirements & Setup

`cnadmin` relies on Stata's native Python integration.
1. **Stata Version:** Stata 16.0 or higher.
2. **Python Environment:** A configured Python environment. (If not automatically detected, use `set python_exec "path\to\python.exe", permanently` in Stata).
3. **Dependencies:** The `pandas` library. Install it via Stata console:
   ```stata
   shell pip install pandas
   ```

## 📦 Installation

You can install the latest version directly from this GitHub repository. Just type the following in your Stata command window:

```stata
net install cnadmin, from("https://raw.githubusercontent.com/Taboo725/cnadmin/main") replace
```

## 🚀 Quick Start & Examples

**1. Basic Forward Code Matching** Map historical 2000 census county codes to modern 2020 district codes:
```stata
cnadmin 2000 2020 countycode_2000, code(countycode_2020)
```

**2. Backward Tracing with Custom Variables and Clean Output** Trace 2020 firm locations back to 2010 boundaries for a DID policy evaluation, suppressing the `_type` quality variable:
```stata
cnadmin 2020 2010 mod_code, code(hist_code) prov(p_name) pref(c_name) coun(d_name) nogen
```

**3. Name-based Matching with Anchors** When GB codes are missing, use strings to match, anchoring with province and city variables to avoid homonym confusion:
```stata
cnadmin 2000 2020 counname, byname inprov(provname) inpref(cityname) code(code_2020)
```


## 📖 Full Documentation
After installation, you can access the detailed official help file within Stata by typing:
```stata
help cnadmin
```

## 🙏 Data Source & Acknowledgments

The core historical change logs and GB/T 2260 code mappings are sourced from the excellent open-source repository maintained at [yescallop/areacodes](https://github.com/yescallop/areacodes). I express my deepest gratitude to their contributors for standardizing decades of Chinese administrative divisions data.