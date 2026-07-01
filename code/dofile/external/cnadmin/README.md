<div align="center">

<h1>
  <span>cnadmin</span>
</h1>
<p>
  <span>一个用于中国行政区划跨期匹配的Stata命令。</span>
</p>

<!-- icon -->
![GitHub release (latest by date)](https://img.shields.io/github/v/release/Taboo725/cnadmin?label=last%20version)
![GitHub Release Date](https://img.shields.io/github/release-date/Taboo725/cnadmin)
![StataMin](https://img.shields.io/badge/stata-%3E%3D%2016.0-blue)

<!-- language -->
简体中文 | [English](README_en.md) 

</div>

**`cnadmin`** 是一个基于 Python 图网络算法的 Stata 外部命令，专门用于解决中国实证研究中跨年行政区划匹配的问题。

在中国面板数据（Panel Data）的构建过程中，频繁的行政区划变更（如撤县设区、拆分、合并）使得跨年份的数据匹配极其困难。简单的 1:1 匹配往往会导致严重的样本流失（Attrition Bias）。`cnadmin` 通过底层时间线网络，能够自动追溯区划沿革，生成准确的过渡映射表（Crosswalk），并为拆分样本提供折算权重。

## 🌟 核心特性

- **双向时间推演：** 既支持将历史行政区划数据（如 2000 年）顺推至现代，也支持将现代行政区划数据（如 2020 年）逆推回历史。
- **空间权重拆分：** 当历史上的一个县在现代被拆分为 N 个区时，程序会自动生成 `1/N` 的折算权重（`weight`）。实证研究者可借此对 GDP、人口等总量指标进行平分加总，保证数据的空间守恒。
- **动态名称提取：** 自动匹配并生成目标年份下极其准确的省级、地级、县级三级规范中文名称。
- **支持名称匹配：** 在缺乏行政代码（GB Code）时，支持直接使用纯中文名称匹配，并提供省、市联合锚定功能，彻底防范“同名区县”（如多地级市均有“鼓楼区”）带来的笛卡尔错配。

## 🛠️ 环境依赖

`cnadmin` 利用了 Stata 内置的 Python 引擎。使用前请确保：
1. **Stata 版本：** 16.0 及以上版本。
2. **Python 环境：** 电脑已安装 Python。（若 Stata 未自动识别，可在 Stata 中运行 `set python_exec "你的python.exe路径", permanently` 进行绑定）。
3. **依赖包：** 需要 `pandas` 库。可在 Stata 命令窗口中直接运行以下代码安装：
   ```stata
   shell pip install pandas
   ```

## 📦 安装方法

您可以直接通过 GitHub 链接在 Stata 中一键安装最新版本：

```stata
net install cnadmin, from("https://raw.githubusercontent.com/Taboo725/cnadmin/main") replace
```

## 🚀 快速开始与使用示例

**1. 基础顺向代码匹配** 将 2000 年的历史普查县级代码映射到 2020 年的区划代码：
```stata
cnadmin 2000 2020 countycode_2000, code(countycode_2020)
```

**2. 逆向回溯与纯净输出** 将 2020 年的企业微观位置逆向追溯到 2010 年的边界（常用于 DID 政策评估），自定义生成的变量名，并隐藏内部匹配状态提示：
```stata
cnadmin 2020 2010 mod_code, code(hist_code) prov(p_name) pref(c_name) coun(d_name) nogen
```

**3. 基于中文名称的双重锚定匹配** 当数据集中缺少代码时，直接使用中文名称进行映射，并用原始省、市变量进行联合锚定以防止同名区县误匹配：
```stata
cnadmin 2000 2020 counname, byname inprov(provname) inpref(cityname) code(code_2020)
```


## 📖 官方帮助文档
安装完成后，您可以在 Stata 中随时输入以下命令查看详尽的英文官方帮助文档：
```stata
help cnadmin
```

## 🙏 数据来源与致谢

本工具底层所依赖的中国行政区划沿革数据库与 GB/T 2260 代码映射表，使用了 GitHub 优秀的开源项目 [yescallop/areacodes](https://github.com/yescallop/areacodes)。在此向该仓库的贡献者们致以最诚挚的感谢，是他们长期对中国行政区划的整理和维护让本工具成为可能。