# sciplot / pypost

`sciplot` remains the Python package name. `pypost` is the command-line tool
for reproducible CFD post-processing: convert raw data once, inspect the
normalized output, then independently process and render it.

```bash
pypost convert --config configs/convert_1d.yml
pypost inspect output/line_p.csv
pypost curve compare --config configs/examples/compare_curves.yml
pypost q extract --config configs/examples/q_extract.yml --time 60.5
pypost q camera --config configs/examples/q_surface.yml
pypost q render --config configs/examples/q_surface.yml --time 60.5
```

## Bundled demos and environment checks

The official demos are self-contained: they do not read `pypost_examples/` or
another external case directory.

```bash
pypost doctor
pypost demo list
pypost demo run curve-comparison  # writes PDF and SVG
pypost demo run q-surface         # writes PNG when EGL/OSMesa/DISPLAY works
pypost q batch --config examples/assets/q_demo/q_batch.yml --dry-run
```

The curve input and preview PDF/SVG live in `examples/assets/curve_demo/` and
are explicitly labelled synthetic. The Q demo in `examples/assets/q_demo/`
uses the supplied lightweight `.vtp` surface and saved camera; its legacy
camera.zip scripts remain reference material only. `q camera --config ...
--time 60.5` opens the same scene configuration later used by `q render`.

For a normalized time series, point Q at its index rather than an original
case. Selection is explicit for MultiBlock data, so a boundary patch is never
mistaken for the internal volume:

```yaml
input:
  time_index: output/volume_times.json
  block: internalMesh       # or regionA/internalMesh
processing:
  velocity_field: U
  velocity_location: point
  iso: 0.01
output:
  surface: output/q_t{time:.3f}.vtp
  image: output/q_t{time:.3f}.png
```

`pypost q extract --config q.yml --time 60.5` resolves the matching index
entry. `q batch` rejects non-unique time-step surface or image paths before
starting subprocesses.

## Five-minute 1-D Quick Start

```bash
pypost demo list
pypost demo run curve-comparison
pypost demo run curve-gallery
pypost demo run cfd-curve-workflow
```

For a project you can edit without touching installed package files:

```bash
pypost demo init curve-comparison --dest my-plot
pypost curve compare --config my-plot/plot.yml
```

The Chinese-first beginner tutorial, including CSV/YAML examples, common error
messages, a CFD conversion workflow, and a parameter cheat sheet, is in
[`docs/tutorials/1d/`](docs/tutorials/1d/README.md). The Feature Gallery also
has four small standalone configs under `curve_gallery/panels/` for
line/scatter, uncertainty, log-log, and symlog/inset plots.

Each command writes reproducible artifacts to `pypost-demo-output/` in the
current working directory. The three curve demos are self-contained and their
data are explicitly synthetic. The gallery preview is available at
[`sciplot/demos/curve_gallery/preview.png`](sciplot/demos/curve_gallery/preview.png).

Use YAML for normal work, without editing library code:

```bash
pypost curve compare --config compare.yml --output paper_figure.pdf
pypost curve compare --config compare.yml --show  # desktop DISPLAY only
```

CLI options override YAML but never rewrite it. A minimal configuration is:

```yaml
datasets:
  - path: normalized_case_a.csv
    x: time
    y: Cd
    x_scale: 1.0
    y_scale: 1.0
    y_offset: 0.0
    label: case A
    style: {color: '#0072b2', linewidth: 1.5}
plot:
  style: paper
  outputs: [paper_figure.pdf, paper_figure.svg, paper_figure.png]
  figure: {size: [88, 62], size_unit: mm, dpi: 300, tight: false}
  axes:
    xlabel: '$t$ [s]'
    ylabel: '$C_d$'
    legend: {loc: upper right, frameon: false, ncol: 1}
    minor_ticks: true
    grid: {major: {alpha: 0.25}, minor: {alpha: 0.10, linestyle: ':'}}
```

`Plot1D` supports `line`, `scatter`, `errorbar`, `band`, external Matplotlib
Axes, panel labels, reference lines, annotations, and inset axes. Values—not
only labels—are transformed by `x_scale`/`x_offset` and
`y_scale`/`y_offset`; error magnitudes are scaled but never offset. Curves are
not interpolated or aligned implicitly. `default` and `paper` styles are local
to each Plot1D instance and do not alter global Matplotlib settings.

```python
import matplotlib.pyplot as plt
from sciplot import Plot1D

fig, axes = plt.subplots(2, 2, sharex=True)
plot = Plot1D(ax=axes[0, 0], style="paper")
plot.line(data, "Cd", label="case A")
plot.hline(0.6, color="0.4", linestyle="--")
plot.panel_label("A")
plot.set_axes(xlabel="$t$", ylabel="$C_d$", minor_ticks=True)
```

For a raw-CFD workflow, see `sciplot/demos/cfd_curve_demo/`: raw sampled
tables become independent standard CSV + JSON sidecars first, and the plotting
YAML can then be adjusted and rerun without converting the raw data again.

1-D normalized data is a CSV plus optional `.csv.json` sidecar for units and
provenance.  3-D data stays in VTK XML (`.vtu`, `.vts`, `.vti`, `.vtm`); point
and cell arrays are never silently merged. Q surfaces are `.vtp` files and do
not represent their original volume fields.

`configs/examples/q_surface.yml` uses the included `Q_sample.vtp`, saved
camera, and scene configuration. It can be edited locally with `q camera`
(mouse to adjust, **P** to save). Off-screen rendering requires a working
DISPLAY, EGL, or OSMesa backend; the command reports this explicitly when one
is unavailable. Q extraction records whether it used an input Q field or VTK's
velocity-gradient calculation. Cache sidecars include input signatures and
processing settings; render sidecars additionally include camera and scene
settings, so visual changes re-render without recalculating the surface.

For time-series work, use a `{time:.3f}` placeholder in surface/image output
paths and put `times: [60.0, 60.5]` in the Q config. `pypost q batch --config
... --resume` invokes each time step in a fresh subprocess, retries failures,
applies the configured timeout, and writes `q_logs/` plus `q_manifest.json`.

一个轻量、脚本驱动的 CFD 科研数据处理与绘图工具包。第一版重点是：1D/2D/3D 数据容器彼此独立，读取/转换、计算、绘图可单独运行；2D 不假定规则网格；3D 始终区分 PointData 和 CellData。

## 安装

项目已约定使用本地虚拟环境 `.env`：

```bash
python3 -m venv .env
. .env/bin/activate
pip install -r requirements.txt
pip install -e '.[dev]'  # runtime package plus pytest for local/CI tests
```

## 直接作图

```python
from sciplot import Data2D, Plot2D

data = Data2D.from_vtk("slice.vtu")       # 保留 PointData 与 CellData
plot = Plot2D(style="paper")
plot.contourf(data, field="p", cmap="turbo", vmin=0, vmax=100)
plot.contour(data, field="p", levels=[20, 40, 60, 80], colors="black")
plot.set_axes(xlabel=r"$x/L$", ylabel=r"$y/L$", xlim=(-2, 5), ylim=(-3, 3))
plot.save("pressure.pdf")
```

对实际坐标归一化，传入会改变坐标值的 `coordinate_transform`，而不是只改标签：

```python
plot.contourf(data, "p", coordinate_transform=lambda xy: xy / 0.05)
```

## YAML 后处理流程

转换和计算/绘图是两个独立入口；模板位于 `configs/`。先将原始表格、VTK 或 OpenFOAM 结果规范化并保存：

```bash
python scripts/convert_data.py configs/convert_1d.yml
python scripts/calculate_and_plot.py configs/plot_1d.yml
```

`convert_data.py` 支持：

- `dimension: 1`：CSV/TXT/OpenFOAM `postProcessing` 采样表格 -> CSV；自动使用注释中的列名（例如 `# x p Ux`）。
- `dimension: 2`：二维 VTK -> `.npz`，其中 PointData、CellData 和 cell centers 分别保存。
- `dimension: 3`：`.vtu`/`.vti`/`.vtm` 或 `.foam` -> ParaView 可读的 VTK XML 文件。

`calculate_and_plot.py` 的 `calculations` 可安全地执行 `scale`、`offset`、`magnitude`；不执行 YAML 中的任意 Python。3D 计算必须明确写 `location: point` 或 `location: cell`，避免隐式混合数据位置。完整字段见 [`configs/plot_1d.yml`](configs/plot_1d.yml)。

## 三个可执行示例

```bash
python examples/example_1d.py
python examples/example_2d.py
python examples/example_3d.py
```

输出在 `output/`。3D 示例使用 PyVista 离屏渲染，生成 PNG 和 VTK ImageData。在无显示服务的 Linux 容器中，它会始终生成 `.vti`，并在缺少 EGL/OSMesa 时安全跳过 PNG、提示所需系统渲染库；有 X/EGL/OSMesa 的工作站会生成二者。

## 数据模型与限制

- `Data1D`：`x`、按名称组织的 fields、单位和元数据；按 x 排序。
- `Data2D`：散点/非规则网格上的 `point_fields`，以及单独的 `cell_fields`/`cell_centers`；云图采用 Matplotlib 三角剖分，截线采用 SciPy 插值。
- `Data3D`：持有 PyVista mesh 或 MultiBlock；`field_info`/`location_of()` 显式报告 point/cell 位置。`face`、`edge` 是为后续扩展预留的位置类型，第一版不导出交错量。

随附的 OpenFOAM 样例现在包含 `polyMesh` 和时刻字段，但缺少 OpenFOAM reader 所需的完整 `constant/` case 目录，因此不能作为 ParaView/OpenFOAM 的端到端读取集成测试。标准 VTK、合成 1D/2D/3D 数据、Q 解析解及图像输出均有测试覆盖。

## 测试

```bash
pytest -q
```
