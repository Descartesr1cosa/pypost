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

### 4. Render simply, then edit only the layout

For ordinary 1-D YAML, use the short command below. It uses exactly the same
renderer as the compatible `pypost curve compare --config plot.yml` command:

```bash
pypost plot my-plot/plot.yml
pypost edit my-plot/plot.yml
```

`plot` is non-interactive and works on headless systems. `edit` requires a
desktop `DISPLAY`; it opens the final figure plus a small margin-control window.
Drag an x/y label, title, legend, text, formula, or arrow annotation. Use the
native toolbar to pan/zoom, use margin sliders for manual layout, press
**Ctrl+S** to save, and press **R** to restore the YAML defaults.

Add this to YAML so the saved visual state is reused automatically:

```yaml
plot:
  layout:
    mode: auto                 # default; keeps labels within the canvas
    overrides: layout.json     # optional until the editor first saves it
```

`mode: manual` enables `margins: {left: 0.18, right: 0.96, bottom: 0.18,
top: 0.94}`. Do not mix manual margins with `mode: auto`. `layout.json` stores
only figure/panel bounds, label/title/legend positions, annotation positions,
and optional axis limits; it never stores CSV data or Python objects.

Try the focused layout example:

```bash
pypost demo init curve-layout --dest layout-project
pypost plot layout-project/layout.yml
pypost edit layout-project/layout.yml
```

### 5. Add ordinary text, Mathtext formulas, and arrows

Annotations can be global or placed in a particular multi-panel ID:

```yaml
annotations:
  - id: drag_formula
    panel: drag
    text: '$C_D = \frac{2F_D}{\rho U_\infty^2 A}$'
    coords: axes
    xy: [0.55, 0.80]
    fontsize: 11
    color: black
  - id: minimum_note
    panel: drag
    text: minimum drag
    coords: axes
    xy: [0.25, 0.20]
    arrow: {xy: [1.0, 0.52], coords: data, style: {arrowstyle: '->'}}
```

`coords: data` uses physical plotted values; `coords: axes` is a fraction of
the selected panel (`[0, 0]` bottom-left and `[1, 1]` top-right); `coords:
figure` is a fraction of the whole canvas. Mathtext works by default without a
system LaTeX installation. Annotation IDs must be unique because the editor
uses them to restore saved positions.

```bash
pypost demo init curve-annotations --dest annotated-figure
pypost plot annotated-figure/annotations.yml
```

### 6. Separate raw CFD conversion from plotting

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

### 7. Learn one feature at a time

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

### 8. Common messages and fixes

| Message | Cause and fix |
| --- | --- |
| `Curve input file not found` | Correct `datasets[].path`; relative paths start from the YAML directory, not the terminal directory. |
| `Column '...' was not found` | Make `x` or `y` match the CSV header exactly, including case and spaces. |
| `Unknown top-level curve YAML key` | Correct a key such as `dataset` to `datasets`, using the allowed-key list in the message. |
| `Cannot use a log ... axis` | Log axes require strictly positive values. Use `symlog` or inspect transformed values after scale/offset. |
| `Cannot save figure` | Create the output directory or choose a writable `plot.outputs` path. |
| `Interactive preview requires a graphical DISPLAY` | Remove `--show` on a headless server; normal export still works. |
| ``pypost edit` requires a graphical DISPLAY` | Start the editor from a desktop session with Tk or Qt available; use `pypost plot` on a server. |

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

## 4. 用简化命令出图，再交互调整排版

对于普通一维 YAML，优先使用短命令；它与兼容接口
`pypost curve compare --config plot.yml` 复用同一套渲染逻辑：

```bash
pypost plot my-plot/plot.yml
pypost edit my-plot/plot.yml
```

`plot` 无界面渲染，适合服务器；`edit` 需要有 `DISPLAY` 的桌面环境。编辑器会显示
最终图和一个小的边距控制窗口：可拖动 x/y label、title、legend、文字、公式和箭头；
可用原生工具栏缩放/平移；可用滑块调整边距；按 **Ctrl+S** 保存，按 **R** 恢复 YAML
默认排版。

在 YAML 中加入以下配置，之后普通 `pypost plot` 会自动重用保存的视觉状态：

```yaml
plot:
  layout:
    mode: auto                 # 默认，自动避免 label 越出画布
    overrides: layout.json     # 编辑器首次保存前不存在也没有问题
```

`mode: manual` 可配合 `margins: {left: 0.18, right: 0.96, bottom: 0.18,
top: 0.94}` 使用；不要把手动边距与 `mode: auto` 混用。`layout.json` 只保存画布/
panel 范围、label/title/legend 位置、标注位置和可选坐标范围，不会保存 CSV 数值或
Matplotlib Artist 对象。

可运行独立的排版示例：

```bash
pypost demo init curve-layout --dest layout-project
pypost plot layout-project/layout.yml
pypost edit layout-project/layout.yml
```

## 5. 添加文字、Mathtext 公式和箭头

标注可写在根级 `annotations`，也可用稳定 panel ID 指定多 panel 中的目标：

```yaml
annotations:
  - id: drag_formula
    panel: drag
    text: '$C_D = \frac{2F_D}{\rho U_\infty^2 A}$'
    coords: axes
    xy: [0.55, 0.80]
    fontsize: 11
    color: black
  - id: minimum_note
    panel: drag
    text: minimum drag
    coords: axes
    xy: [0.25, 0.20]
    arrow: {xy: [1.0, 0.52], coords: data, style: {arrowstyle: '->'}}
```

`coords: data` 是物理坐标；`coords: axes` 是指定 panel 的相对坐标（`[0,0]` 为左下，
`[1,1]` 为右上）；`coords: figure` 是整张画布相对坐标。默认 Mathtext 不依赖系统
LaTeX。annotation ID 必须唯一，编辑器依靠它恢复保存的位置。

```bash
pypost demo init curve-annotations --dest annotated-figure
pypost plot annotated-figure/annotations.yml
```

## 6. 从原始 CFD 表到可重复作图

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

## 7. 学习一个功能，再用到自己的图

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

## 8. 常见报错与修复

| 提示 | 原因与修复 |
| --- | --- |
| `Curve input file not found` | `datasets[].path` 写错；它相对 YAML 文件所在目录，而非当前终端目录。 |
| `Column '...' was not found` | `x` 或 `y` 与 CSV 表头不一致；检查大小写、空格和第一行列名。 |
| `Unknown top-level curve YAML key` | 常见拼写错误，例如 `dataset` 应为 `datasets`；按提示中的允许键修改。 |
| `Cannot use a log ... axis` | log 只能绘制严格正数；使用 `symlog`，或检查 scale/offset 后的数据。 |
| `Cannot save figure` | 创建输出目录，或将 `plot.outputs` 改到有写权限的目录。 |
| `Interactive preview requires a graphical DISPLAY` | 服务器没有桌面显示；移除 `--show`，直接导出文件。 |
| ``pypost edit` requires a graphical DISPLAY` | 请在有桌面显示、并具备 Tk 或 Qt 的环境启动编辑器；服务器上用 `pypost plot`。 |

这一流程的完成标准很简单：只要能替换 CSV、修改 YAML，并稳定导出 PDF/SVG/PNG，
就不需要学习库内部 API。
