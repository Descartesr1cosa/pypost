# 1D YAML 参数速查表 / quick reference

所有路径默认相对于 YAML 配置文件。`pypost curve compare --config plot.yml`
只读取配置；`--output other.pdf` 只在本次运行覆盖输出，不会改写 YAML。

| 位置 | 参数（默认） | 最小示例 | 说明 |
| --- | --- | --- | --- |
| 每条曲线 | `path`, `x`, `y`（必填） | `path: run.csv, x: time, y: Cd` | CSV/TXT 路径和列名。不同曲线可有不同 x。 |
| 每条曲线 | `kind: line` | `kind: scatter` | 可选 `line`、`scatter`、`errorbar`、`band`。 |
| 每条曲线 | `label` | `label: case A` | 图例文字；未设置时使用文件名。 |
| 每条曲线 | `style: {}` | `style: {color: C0, linestyle: --, linewidth: 1.5}` | 常用：`color`、`linestyle`、`linewidth`、`marker`、`markersize`、`alpha`、`zorder`；scatter 用 `s` 控制面积。 |
| 误差棒 | `yerr` | `kind: errorbar, yerr: sigma` | 可以是 CSV 列名或数值；误差只乘 `y_scale`，不会加 `y_offset`。 |
| 误差带 | `lower`, `upper` | `kind: band, lower: low, upper: high` | 两个 CSV 列名；会应用与主 y 相同的 scale/offset。 |
| 数值变换 | `x_scale`, `x_offset`, `y_scale`, `y_offset`（1,0,1,0） | `y_scale: 1000` | 实际改变绘制数值。不要把单位转换只写在标签里。 |
| 图形 | `plot.style: default` | `style: paper` | `paper` 使用适合论文的局部字体和线宽；不污染全局 Matplotlib 设置。 |
| 尺寸 | `figure.size`（6.4×4.2 in） | `size: [88, 62], size_unit: mm` | `in` 或 `mm`；`tight: false` 保持指定物理尺寸。 |
| 输出 | `outputs`（`curve_compare.png`） | `outputs: [fig.pdf, fig.svg, fig.png]` | PDF/SVG 为矢量；PNG 用 `figure.dpi`（例如 300）。 |
| 简化命令 | `pypost plot CONFIG` | `pypost plot plot.yml` | 与 `curve compare` 使用同一渲染逻辑；旧命令仍兼容。 |
| 布局 | `layout.mode: auto` | `layout: {mode: auto, overrides: layout.json}` | 默认自动排版。`manual` 才可使用 `margins`，JSON 不保存数据。 |
| label 位置 | `xlabelpad`、`ylabelpad` | `xlabel_position: [0.5, -0.15]` | position 使用 Axes 相对坐标；用 `pypost edit` 可鼠标调整。 |
| 标注 | `annotations` | `id: note, text: '$C_D$', coords: axes, xy: [.5, .8]` | 支持普通文字/Mathtext、data/axes/figure 坐标和 `arrow`。 |
| 坐标轴 | `xlabel`, `ylabel`, `title` | `xlabel: '$t$ [s]'` | Mathtext 可直接使用 `$...$`，不要求安装 TeX。 |
| 范围/刻度 | `xlim`, `ylim`, `xticks`, `yticks` | `xlim: [0, 10]` | 数组或 YAML 列表。 |
| 坐标轴 | `xscale`, `yscale`（`linear`） | `yscale: log` | 支持 `linear`、`log`、`symlog`；symlog 可配 `yscale_kwargs: {linthresh: 0.01}`。 |
| 刻度 | `minor_ticks: false` | `minor_ticks: true` | `tick_params: {direction: in, length: 4, width: 0.8}` 可调方向/长度/线宽。 |
| 科学计数法 | `scientific` | `scientific: {limits: [-2, 2]}` | 通常用于线性/symlog 轴。对全正多数量级数据，优先使用 log–log。 |
| 图例 | `legend: false` | `legend: {loc: upper right, frameon: false, ncol: 2, fontsize: 8}` | `legend: true` 采用默认位置；图例字典可完整控制常用选项。 |
| 网格 | `grid: false` | `grid: {major: {alpha: 0.25}, minor: {alpha: 0.1, linestyle: ':'}}` | 主、次网格可独立设置。 |
| 多 panel | `panels` | `plot.figure: {nrows: 2, ncols: 2}` | 每个 panel 可有单独 datasets/axes；完整范例见 Feature Gallery。 |
| inset | `inset` | `bounds: [0.58, 0.54, '34%', '32%']` | bounds 是相对主轴的位置和宽高；避免遮挡要比较的数据。 |

最小完整模板：

```yaml
datasets:
  - {path: data.csv, x: time, y: Cd, label: baseline, style: {color: '#0072b2'}}
plot:
  style: paper
  outputs: [figure.pdf, figure.svg]
  axes:
    xlabel: '$t$ [s]'
    ylabel: '$C_d$'
    legend: {loc: best, frameon: false}
```
