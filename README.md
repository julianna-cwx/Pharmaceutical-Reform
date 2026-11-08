# 医院零加成改革与零售药店空间配置

> 最后整理：2026-11-06  
> 项目目录：`D:\Hospital_Pharmacy program`  
> 当前范围：仅医院层面分析  
> 当前状态：论文初稿暂不修改；文件整理已完成；v6 已于 2026-11-06 完整试运行并完成复现审计

## 1. 新手先看：三个核心文件

| 用途 | 文件 | 绝对路径 |
|---|---|---|
| 最新医院分析面板 | `hosp_pharm_v5_xqdistance.dta` | `D:\Hospital_Pharmacy program\data\hospital_pharmacy\hosp_pharm_panel\hosp_pharm_v5_xqdistance.dta` |
| 最新医院面板处理代码 | `hosp_pharm_panel_v3.ipynb` | `D:\Hospital_Pharmacy program\code\python\hosp_pharm_panel_v3.ipynb` |
| 最新、唯一主回归代码 | `01_hospital_v6.do` | `D:\Hospital_Pharmacy program\code\dofile\01_hospital_v6.do` |

正式结果目录：

`D:\Hospital_Pharmacy program\results\results_v6_paper_replication\`

该目录是 2026-11-06 使用精简后 v6 完整运行得到的最新结果，包含 stacked DID、迁移药店、论文主表 1–3、运行日志和复现审计。旧的重复结果目录已删除。

v6 运行日志保存在：

`D:\Hospital_Pharmacy program\code\dofile\01_hospital_v6.log`

分析面板文件名保留了历史命名，但它是 v6 当前实际读取的最新面板。不要只根据文件名中的版本号判断是否过期。

## 2. 研究问题与核心结论

项目研究中国公立医院取消药品加成后，零售药店是否向公立医院门口集中，以及这种变化是否因医院等级而不同。

医院层面主规格为：

```text
Y_hlt = β(Public_h × Post_lt) + Hospital FE + Local-area×Year FE + ε_hlt
```

- `Public_h`：医院是否为公立医院。
- `Post_lt`：医院所在地区进入政策实施后的完整年份。
- 医院固定效应控制医院不随时间变化的特征。
- 地区×年固定效应控制同一地区、同一年共同经历的变化。
- 标准误按政策实施地区聚类。

当前最稳定的结果：

1. 改革后，公立医院门口 0–200 米内的药店净进入显著增加。
2. 500–1,000 米外环的药店净进入减少。
3. 1 公里内总量变化较小且不精确，主要表现为空间重配。
4. 药店增加主要集中在三级医院周边；一级医院较大半径内药店存量下降。
5. 迁移药店在医院门口附近有向医院靠近的迹象。

## 3. 当前保留的数据

### 3.1 最终医院分析面板

目录：`data/hospital_pharmacy/hosp_pharm_panel/`

- `hosp_pharm_v5.csv`：完整 CSV 面板。
- `hosp_pharm_v5.dta`：Stata 版本主面板。
- `hosp_pharm_v5_xqdistance.dta`：当前 v6 默认输入，增加药店到住宅小区距离变量。

### 3.2 医院年度面板

目录：`data/hospital/hosp_panel/hosp_year/`

当前年度文件为 `hospital_v4_2013.csv` 至 `hospital_v4_2018.csv`。这些文件记录每年有效医院、医院属性、坐标、AOI 和政策匹配信息，是医院—药店面板的直接上游，不应删除。

### 3.3 最终年度药店

目录：`data/pharmacy/pharm_final/`

当前年度药店文件为 `dzdp_pharmacies_final_YYYY.csv`。它们是计算医院周边药店数量、净进入和迁移的核心输入，不应删除。

### 3.4 住宅小区与迁移药店

- `data/xiaoqu/`：年度住宅小区 POI 原始数据。
- `data/xiaoqu/residential_cache/`：住宅小区坐标缓存。
- `data/pharmacy/pharm_xiaoqu/`：药店到最近住宅小区的距离。
- `data/pharmacy/pharmacy_migration/`：相邻年份同一药店的迁移记录。
- `hospital_pharmacy_migration_distances.csv/.dta`：医院—年迁移距离指标。

### 3.5 人口覆盖数据

- `data/pop/`：WorldPop 人口栅格，体量很大，不应删除。
- `hospital_pharmacy_population_accessibility.csv/.dta`：医院周边药店服务圈覆盖人口。
- `population_accessibility_checkpoints/`：人口覆盖计算检查点，重算成本较高，暂时保留。

## 4. 数据如何生成

主入口：`code/python/hosp_pharm_panel_v3.ipynb`

### 第一步：读取医院总表

入口文件：

`data/hospital/AOI/hosp_real_final_clean_v3_aoi_qcc_with_hospital_level.csv`

主要字段包括医院名称、地址、经营状态、成立和注销日期、所有制、中医医院标记、医院等级、注册资本、企业规模、行政区、坐标和 AOI 边界。

### 第二步：统一医院坐标

代码将地图坐标转换为 WGS84，并检查缺失、异常范围和转换质量。有医院 AOI 边界时，距离优先按药店到医院边界计算；没有 AOI 时使用医院中心点。

### 第三步：构造医院年度面板

根据医院成立、注销、吊销和停业日期，判断医院在 2013–2018 年各年是否有效。同时生成或匹配公立属性、中医医院标记、医院等级、政策年份、空间标识、坐标和 AOI。

### 第四步：计算医院周边设施

逐年读取最终药店和养生机构，计算每家医院：

- 200、500、800、1,000 米内的设施数量；
- 0–200、200–500、500–1,000 米互斥环带数量；
- 最近药店距离和 1 公里内平均药店距离；
- 距离衰减加权药店数；
- 本年存量减上年存量得到的年度净进入。

### 第五步：计算药店到住宅小区的距离

代码从年度 POI 数据中提取住宅小区坐标，计算每家药店到最近住宅小区的距离，再按医院周边累计半径和互斥环带聚合。某一范围内没有药店时保留为缺失，不将其记为 0。

### 第六步：计算人口覆盖与迁移指标

- `pharmacy_population_accessibility.py`：计算医院周边药店 500 米服务圈并集覆盖的人口。
- `pharmacy_migration_distances.py`：识别相邻年度移动至少 100 米的同一药店，并计算迁移前后到最近医院和最近住宅小区的距离变化。

### 第七步：导出分析面板

notebook 导出 CSV 和 Stata 面板。Stata 版本会将部分中文字段改为 ASCII 名称，并保留适合 Stata 的日期和字符串类型。

## 5. `01_hospital_v6.do` 的功能

`01_hospital_v6.do` 是当前唯一需要继续维护的医院主回归文件。

### 5.1 输入

默认主面板：`hosp_pharm_v5_xqdistance.dta`

附加合并文件：

- `hospital_pharmacy_population_accessibility.dta`
- `hospital_pharmacy_migration_distances.dta`

每次合并都检查 `_merge`，并要求医院 ID 与年份完全匹配。

### 5.2 主变量

- `pub`：公立医院标记。
- `post`：`year > policy_year`。
- `did`：`pub × post`。
- `ne200`、`ne500`、`ne800`、`ne1000`：累计半径内药店年度净进入。
- `ne_gate`、`ne_near`、`ne_outer`、`ne_total`：互斥环带与 1 公里总范围的净进入。
- `st_gate`、`st_near`、`st_outer`、`st_total`：药店存量。
- `em4` 至 `ep4`：事件研究变量，`k=-1` 为省略基期。

政策采用年是事件时间 `k=0`，第一个完整处理年是 `k=1`。

### 5.3 回归模块

v6 依次运行：

1. 互斥距离环带的药店净进入和存量回归。
2. 主规格事件研究和政策前联合检验。
3. 累计半径结果及不同处理定义。
4. Cohort-by-calendar-year 饱和模型。
5. 加权 stacked DID 及事件研究图。
6. 医院周边药店覆盖人口。
7. 养生机构安慰剂。
8. 药店到住宅小区的距离变化。
9. 迁移药店到最近医院和最近住宅小区的距离变化。
10. 三级医院内部的公立/非公立比较。
11. 一级、二级、三级医院异质性。
12. 论文主表 1–3 的独立复现和审计输出。

### 5.4 输出

默认结果目录：`results/results_v6_paper_replication/`

关键输出：

- `estimates.csv/.dta`：各模型主系数。
- `events.csv/.dta`：事件研究系数。
- `descriptives.csv/.dta`：描述性统计。
- `table1_reproduced.csv/.dta`：主样本描述性统计。
- `table2_reproduced.csv/.dta`：互斥环带主结果。
- `table3_reproduced.csv/.dta`：替代估计量和处理定义。
- `stacked_did_ne.rtf`、`stacked_did_st.rtf`：stacked DID 表。
- `stacked_event_*.png/.pdf`：stacked DID 事件研究图。
- 其他 `.rtf`：各项医院层面回归表。
- `replication.log`：完整 Stata 运行日志。

## 6. 当前主要结果

### 6.1 互斥环带

| 结果 | 0–200m | 200–500m | 500–1,000m | 0–1,000m |
|---|---:|---:|---:|---:|
| 年度净进入 DID | 0.155*** (0.028) | 0.030 (0.044) | -0.145* (0.087) | 0.040 (0.114) |
| 活跃药店存量 DID | 0.217*** (0.027) | 0.073* (0.042) | -0.200** (0.085) | 0.090 (0.112) |
| 净进入政策前联合检验 p 值 | 0.137 | 0.795 | 0.936 | 0.785 |

结论：药店向公立医院门口集中，但医院周边 1 公里内总量没有显著变化。

### 6.2 医院等级

| 医院等级 | 200m | 500m | 800m | 1,000m |
|---|---:|---:|---:|---:|
| 一级医院 | 0.006 | -0.123* | -0.532*** | -0.786*** |
| 二级医院 | 0.228*** | 0.367*** | 0.319*** | 0.231 |
| 三级医院 | 0.420*** | 0.596*** | 0.579*** | 0.614*** |

结论：药店供给增加主要集中在三级医院，一级医院较大范围内药店存量下降。

### 6.3 住宅小区与迁移药店

- 200–500 米环带内，药店到最近住宅小区的平均距离下降约 59 米。
- 0–200 米门口范围内，迁移药店相对向最近医院靠近约 98 米。
- 迁移药店到最近住宅小区的变化不精确。

因此，可以说药店向医院门口靠近，但不能据此断言药店普遍远离居民区。

## 7. 如何从头复现

### 7.1 软件要求

Python 主要依赖 `pandas`、`numpy` 和 `scipy`。空间数据还依赖 QGIS/GDAL：

```text
D:\Latex\bin\python-qgis-ltr.bat
D:\Latex\bin\ogr2ogr.exe
```

Stata 建议使用 Stata 17 或更高兼容版本，并安装：

- `reghdfe`
- `ftools`
- `estout` / `esttab`
- `coefplot`

### 7.2 推荐运行顺序

1. 检查医院总表、年度药店、住宅小区和人口栅格是否存在。
2. 从头运行 `hosp_pharm_panel_v3.ipynb`。
3. 检查医院年度面板是否完整。
4. 检查最终分析面板中的 `hospital_id year` 是否唯一。
5. 检查人口覆盖和迁移距离文件是否与主面板完全匹配。
6. 运行 `code/dofile/01_hospital_v6.do`。
7. 检查 `replication.log` 末尾是否出现 `FULL_HOSPITAL_REPLICATION_ESTIMATION_COMPLETE`。
8. 对照三个 `table*_reproduced.csv` 核查主结果。

精简后的 v6 已使用独立目录完整运行。以后再次试运行仍建议指定新的输出目录：

```stata
do "D:/Hospital_Pharmacy program/code/dofile/01_hospital_v6.do" ///
   "D:/Hospital_Pharmacy program/results/results_v6_test"
```

核对无误后，再把新目录设为正式结果。

### 7.3 2026-11-06 复现审计结论

本次运行正常结束，日志包含 `FULL_HOSPITAL_REPLICATION_ESTIMATION_COMPLETE`，未发现 Stata 错误码。

可以复现的部分：

- 论文主样本描述性统计全部一致。
- 互斥环带净进入和存量的系数、标准误、样本量、结果均值及净进入政策前联合检验一致。
- 基准累计半径结果、非中医医院处理和中医/非中医分组一致。
- 医院等级净进入、存量以及三级减一级的主效应一致。

尚不能视为复现成功的部分：

- 论文中的 cohort-saturated 一行与当前代码重建值不一致。
- cohort-saturated 的医院等级分组结果不一致。
- 共计 20 组队列饱和系数或标准误未达到论文三位小数精度。

例如，200 米 cohort-saturated 结果，论文报告为 `0.147 (0.028)`，当前代码重建为 `0.122 (0.025)`。归档中的早期审计也得到同一个重建值，说明差异不是本次代码精简造成的。需要找到论文结果对应的原始队列饱和程序、支持样本和共线单元处理规则后，才能完成这一部分的最终复现。

## 8. 文件整理状态

### 8.1 已归档

旧医院面板、旧结果、专题试跑结果和被当前代码取代的医院脚本已移动到：

`D:\Hospital_Pharmacy program\archive\2026-11-06\`

归档文件已设置为只读。归档不是删除；如需恢复，应复制回工作目录，不要直接在归档内编辑。

### 8.2 已清理

已删除：

- 所有 `.pyc` 和 `__pycache__/`。
- `paper/` 下 LaTeX 编译中间文件。
- `paper/_compile_output*`、`paper/_slides_check*`、`paper/_template_compile_check/`。
- `tmp/` 下临时审阅、渲染和幻灯片检查文件。
- `code/dofile/` 下以 `_` 开头的一次性检查 dofile 和日志。

相应模式已加入 `.gitignore`，避免再次混入项目。

### 8.3 不要删除

- 最新年度医院面板。
- 最新年度药店。
- 当前三个主分析面板。
- 医院所有制、等级、AOI、坐标和政策年份的人工核查结果。
- WorldPop 和住宅小区原始数据。
- 当前 v3 notebook、v6 dofile 和它们调用的独立 Python 脚本。
- 正式结果目录和运行日志。

## 9. AOI 数据位置

医院 AOI 数据已统一保存到：

`D:\Hospital_Pharmacy program\data\hospital\AOI\`

最新 notebook 读取：

`data/hospital/AOI/hosp_real_final_clean_v3_aoi_qcc_with_hospital_level.csv`

工作区内保留的 Python 代码已同步更新到新路径。顶层旧 `data/AOI/` 经 24 个文件的 SHA-256 逐一校验后已删除；校验时新旧文件内容全部一致。以后新增脚本统一使用 `data/hospital/AOI/`。

## 10. 接手检查清单

- [ ] 三个核心文件都存在。
- [ ] 医院年度面板覆盖 2013–2018 年。
- [ ] 年度药店文件覆盖 2013–2018 年。
- [ ] 主面板中 `hospital_id year` 唯一。
- [ ] v6 所需两个附加 DTA 文件存在且能完全合并。
- [ ] Stata 用户命令已经安装。
- [ ] v6 使用单独的新结果目录试运行。
- [ ] 日志末尾出现完成标记。
- [ ] 主表数值与本 README 中的基准结果一致。
- [ ] 确认结果后再考虑更新论文初稿。

当前工作原则：**先稳定复现医院面板和 v6 回归，再修改论文。**
