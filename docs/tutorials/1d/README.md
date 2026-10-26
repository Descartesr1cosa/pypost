# 1D plotting tutorial / 一维曲线绘图入门

## English

This tutorial is for researchers who can edit CSV and YAML files but do not
know Matplotlib. You do not need to modify the `sciplot` Python source. The
bundled values are explicitly marked **synthetic**; the workflow is the same
for experimental data and sampled CFD results.

### 0. Install and check the environment

```bash
python -m pip install sciplot
pypost doctor
pypost demo list
```

The output reports Python, PyVista and VTK versions, plus the status of each
demo. PDF/SVG/PNG export for 1-D curves works on terminals and headless
servers. A graphical `DISPLAY` is needed only for `--show` previews and 3-D
rendering.

If `pypost: command not found` appears, the installation Python is probably
not the Python used by the current shell. Install with `python -m pip`, then
activate the relevant virtual environment or reopen the terminal.

### 1. Copy an editable example project

Do not edit files inside the installed package. Copy the official Quick Start
to a writable directory instead:

```bash
pypost demo init curve-comparison --dest my-plot
find my-plot -maxdepth 1 -type f
pypost curve compare --config my-plot/plot.yml
```

Expected files include `plot.yml`, `reference.csv`, `medium.csv`, `coarse.csv`
and `README.md`. The command creates `curve_comparison.pdf` and
`curve_comparison.svg` in `my-plot/`. Paths are relative to the YAML file, so
the entire directory is portable. Add a PNG output and `dpi: 300` in YAML when
you need a raster figure.

`demo init` never overwrites an existing destination. Pick a new `--dest` if
the directory already exists.

### 2. Prepare a CSV file

Create, for example, `my-plot/new_case.csv`:

```csv
time,Cd,uncertainty
0.0,0.61,0.02
0.5,0.58,0.02
1.0,0.55,0.03
```

The coordinate need not be called `time`, but the `x` and `y` YAML values must
match CSV headers exactly. Comma CSV, whitespace/TAB TXT, and OpenFOAM
`postProcessing`-style tables with a comment header such as `# time Cd` are
accepted. Add a new dataset to `plot.yml`:

```yaml
  - path: new_case.csv
    x: time
    y: Cd
    label: new case
    style: {color: '#009e73', linestyle: '-.', linewidth: 1.5}
```

Curves may have different sampling positions and lengths. pypost does not
silently interpolate, resample, or align them.

### 3. Adjust a figure in YAML

Copy this minimal template. Scale and offset modify the plotted numbers, not
only the axis label:

```yaml
datasets:
  - path: new_case.csv
    x: time
    y: Cd
    y_scale: 1.0
    y_offset: 0.0
    label: new case
    style: {color: '#0072b2', linewidth: 1.6, marker: o, markersize: 3}
plot:
  style: paper
  outputs: [figure.pdf, figure.svg, figure.png]
  figure: {size: [88, 62], size_unit: mm, dpi: 300, tight: false}
  axes:
    xlabel: '$t$ [s]'
    ylabel: '$C_d$'
    xlim: [0, 1]
    ylim: [0.4, 0.7]
    legend: {loc: upper right, frameon: false}
    minor_ticks: true
    grid: {major: {alpha: 0.25}, minor: {alpha: 0.10, linestyle: ':'}}
```

Temporarily change the output without editing YAML:

```bash
pypost curve compare --config my-plot/plot.yml --output submission.pdf
```

The CLI override has priority for that invocation only and never rewrites the
configuration. On a desktop you can preview with `--show`; on a headless
server, omit `--show` and export files normally.

### 4. Separate raw CFD conversion from plotting

The CFD demo converts raw tables once and then plots standardized CSV files:

```bash
pypost demo init cfd-curve-workflow --dest cfd-plot
cd cfd-plot
pypost convert --config convert_case_a.yml
pypost convert --config convert_case_b.yml
pypost curve compare --config compare.yml
```

The conversion commands create `standardized/case_a.csv` and
`standardized/case_b.csv` with JSON metadata sidecars. The last command reads
only those normalized files and writes `cfd_coefficients.pdf` and `.svg`.
Change `compare.yml` and rerun only the final command to restyle the plot.

### 5. Learn one feature at a time

The Feature Gallery contains one 2×2 overview and four focused configurations:

```bash
pypost demo init curve-gallery --dest gallery-project
pypost curve compare --config gallery-project/panels/line_scatter.yml
pypost curve compare --config gallery-project/panels/uncertainty.yml
pypost curve compare --config gallery-project/panels/loglog.yml
pypost curve compare --config gallery-project/panels/symlog_inset.yml
```

They demonstrate model-versus-measurement scatter, uncertainty bands and error
bars, log–log axes for strictly positive values, and symlog residuals crossing
zero with an inset. Start from the closest example and replace `path`, `x`,
and `y`. See the [parameter quick reference](quick-reference.md) for all
common controls.

### 6. Common messages and fixes

| Message | Cause and fix |
| --- | --- |
| `Curve input file not found` | Correct `datasets[].path`; relative paths start from the YAML directory, not the terminal directory. |
| `Column '...' was not found` | Make `x` or `y` match the CSV header exactly, including case and spaces. |
| `Unknown top-level curve YAML key` | Correct a key such as `dataset` to `datasets`, using the allowed-key list in the message. |
| `Cannot use a log ... axis` | Log axes require strictly positive values. Use `symlog` or inspect transformed values after scale/offset. |
| `Cannot save figure` | Create the output directory or choose a writable `plot.outputs` path. |
| `Interactive preview requires a graphical DISPLAY` | Remove `--show` on a headless server; normal export still works. |

Once you can replace CSV files, edit YAML, and export PDF/SVG/PNG reliably,
there is no need to learn the library internals.

## 中文

本教程面向只会编辑 CSV 和 YAML 的科研用户。你不需要学习
Matplotlib，也不需要改动 `sciplot` 的 Python 源码。下面的例子使用明确标注为
**synthetic（合成）** 的小数据；你的工作流与真实实验、CFD 采样数据相同。

## 0. 安装并检查环境

```bash
python -m pip install sciplot
pypost doctor
pypost demo list
```

预计输出包括 Python、PyVista、VTK 版本和 demo 状态。对于一维曲线，终端或
无显示服务器也可以输出 PDF/SVG/PNG；`DISPLAY` 只影响 `--show` 预览和三维
渲染。

常见错误：`pypost: command not found` 通常表示安装使用的 Python 与当前终端
不同。请改用 `python -m pip install sciplot`，重新打开终端，或激活对应虚拟环境。

## 1. 复制一份可编辑的示例

不要修改安装包里的文件。先复制官方 Quick Start 到你的工作目录：

```bash
pypost demo init curve-comparison --dest my-plot
find my-plot -maxdepth 1 -type f
```

预计得到 `my-plot/plot.yml`、`reference.csv`、`medium.csv`、`coarse.csv` 和
`README.md`。`plot.yml` 使用相对路径，因此整个目录可以移动或交给同事。

```bash
pypost curve compare --config my-plot/plot.yml
```

预计输出：`my-plot/curve_comparison.pdf` 和 `my-plot/curve_comparison.svg`。
PDF/SVG 适合论文排版，文字和线条保持矢量；需要位图时，在 YAML 的 `outputs`
中加上 `curve_comparison.png`，并设置 `dpi: 300`。

若提示目标目录已存在，请选择新目录名；初始化命令刻意不覆盖已有工作。

## 2. 准备自己的 CSV

最小 CSV 是一行列名和数值表，例如 `my-plot/new_case.csv`：

```csv
time,Cd,uncertainty
0.0,0.61,0.02
0.5,0.58,0.02
1.0,0.55,0.03
```

第一列不一定叫 `time`，但 YAML 中的 `x` 和 `y` 必须与列名完全一致。逗号 CSV、
空格或 TAB 分隔的 TXT 都可读取；OpenFOAM `postProcessing` 风格表格可以用注释
行（例如 `# time Cd`）作为列名。

把下面项目加入 `plot.yml` 的 `datasets:` 列表：

```yaml
  - path: new_case.csv
    x: time
    y: Cd
    label: new case
    style: {color: '#009e73', linestyle: '-.', linewidth: 1.5}
```

不同曲线可以有不同采样时间或长度。pypost 不会悄悄插值、重采样或对齐数据。

## 3. 用 YAML 调整图形

以下是可直接复制的小模板。数值变换会改变实际绘制的数据，不只是改标签：

```yaml
datasets:
  - path: new_case.csv
    x: time
    y: Cd
    y_scale: 1.0
    y_offset: 0.0
    label: new case
    style: {color: '#0072b2', linewidth: 1.6, marker: o, markersize: 3}
plot:
  style: paper
  outputs: [figure.pdf, figure.svg, figure.png]
  figure: {size: [88, 62], size_unit: mm, dpi: 300, tight: false}
  axes:
    xlabel: '$t$ [s]'
    ylabel: '$C_d$'
    xlim: [0, 1]
    ylim: [0.4, 0.7]
    legend: {loc: upper right, frameon: false}
    minor_ticks: true
    grid: {major: {alpha: 0.25}, minor: {alpha: 0.10, linestyle: ':'}}
```

运行时临时换输出名而不改 YAML：

```bash
pypost curve compare --config my-plot/plot.yml --output submission.pdf
```

命令行 `--output` 优先于 YAML，但不会写回配置文件。桌面环境可用 `--show` 预览：

```bash
pypost curve compare --config my-plot/plot.yml --show
```

无图形显示环境下请去掉 `--show`，PDF/SVG/PNG 导出仍然正常。

## 4. 从原始 CFD 表到可重复作图

CFD demo 将转换和绘图拆开，因此更换颜色或坐标范围时无需再次读取原始数据：

```bash
pypost demo init cfd-curve-workflow --dest cfd-plot
cd cfd-plot
pypost convert --config convert_case_a.yml
pypost convert --config convert_case_b.yml
pypost curve compare --config compare.yml
```

前两步生成 `standardized/case_a.csv`、`standardized/case_b.csv` 及 JSON 元数据。
最后一步只读取这些标准 CSV，输出 `cfd_coefficients.pdf` 与 `.svg`。此后只编辑
`compare.yml` 并重跑最后一条命令即可。

## 5. 学习一个功能，再用到自己的图

Feature Gallery 提供整张 2×2 图和四个小配置：

```bash
pypost demo init curve-gallery --dest gallery-project
pypost curve compare --config gallery-project/panels/line_scatter.yml
pypost curve compare --config gallery-project/panels/uncertainty.yml
pypost curve compare --config gallery-project/panels/loglog.yml
pypost curve compare --config gallery-project/panels/symlog_inset.yml
```

它们依次演示：模型与实验散点、误差带和误差棒、全正数据的 log–log、跨零残差的
symlog 与局部 inset。先挑最像自己问题的一个文件，再替换 `path`、`x`、`y`。

完整参数请看 [参数速查表](quick-reference.md)。

## 6. 常见报错与修复

| 提示 | 原因与修复 |
| --- | --- |
| `Curve input file not found` | `datasets[].path` 写错；它相对 YAML 文件所在目录，而非当前终端目录。 |
| `Column '...' was not found` | `x` 或 `y` 与 CSV 表头不一致；检查大小写、空格和第一行列名。 |
| `Unknown top-level curve YAML key` | 常见拼写错误，例如 `dataset` 应为 `datasets`；按提示中的允许键修改。 |
| `Cannot use a log ... axis` | log 只能绘制严格正数；使用 `symlog`，或检查 scale/offset 后的数据。 |
| `Cannot save figure` | 创建输出目录，或将 `plot.outputs` 改到有写权限的目录。 |
| `Interactive preview requires a graphical DISPLAY` | 服务器没有桌面显示；移除 `--show`，直接导出文件。 |

这一流程的完成标准很简单：只要能替换 CSV、修改 YAML，并稳定导出 PDF/SVG/PNG，
就不需要学习库内部 API。
