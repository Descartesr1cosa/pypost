# Numerical 1-D publication plots / 数值化 1D 论文出图

The default `paper-1d` profile produces a restrained, colour-blind-friendly
scientific line plot. It is inspired by common journal practice, not an
official template for any journal.

```yaml
# plot.yml: scientific content only
kind: curve
datasets:
  - {path: force.npz, x: time, y: Cd, label: '$C_D$'}
axes:
  xlabel: '$t$ [s]'
  ylabel: Coefficient
  xlim: [0, 10]
plot:
  profile: paper-1d
  style_file: style.yml       # optional
  layout_file: layout.yml     # optional
  outputs: [figure.pdf, figure.png]
```

```bash
pypost plot plot.yml
pypost check-figure plot.yml --report publication-report.json
pypost style export paper-1d --out style.yml
pypost layout export paper-1d --out layout.yml
```

`style.yml` owns font, colour, line, marker, tick, grid and legend appearance.
`layout.yml` owns Figure size, percent margins, label gaps in pt, and legend
anchors. Percent margins are relative to the full Figure; `percent_axes`
legend anchors are relative to an Axes. Do not move these parameters into
`plot.yml`.

```yaml
version: 1
mode: fixed                 # fixed numeric layout, or auto for constrained layout
figure: {width: 120, height: 80, unit: mm}
margins: {unit: percent, left: 15, right: 5, bottom: 18, top: 6}
labels:
  xlabel: {gap: {value: 7, unit: pt}}
  ylabel: {gap: {value: 8, unit: pt}}
legend: {position: upper_right, anchor: [95, 95], anchor_unit: percent_axes}
publication: {placement_width_mm: 90, min_text_pt: 8, font_policy: auto}
```

Publication scale is `placement_width_mm / export_width_mm`, and final font
size is `export_font_pt * scale`. `auto` enlarges insufficient visible text
before layout, `warn` writes failures to the report, and `error` stops output.
Mathtext is checked at parent font size; subscripts and fractions can be
smaller and are reported with that limitation.

`pypost edit plot.yml` is intentionally a **data browser**. The native toolbar
Pan/Zoom/Home controls only the current observation; it cannot save xlim,
ylim, label, legend, annotation, or margin positions. Edit YAML numbers for
final publication output.

---

# 中文说明

默认 `paper-1d` profile 提供稳定、色盲相对友好的论文曲线风格。`plot.yml`
只放数据、变量、物理坐标范围、标签、公式和输出；`style.yml` 只放字体、颜色、线型、
marker、刻度、网格和图例视觉风格；`layout.yml` 只放毫米尺寸、百分比边距、pt 标签距离
和多 panel 几何。

出版检查中，缩放比例为 `最终放置宽度 / 导出宽度`，最终字号为 `导出字号 × 缩放比例`。
`font_policy: auto` 会在布局前提高不足字号；`warn` 只报告；`error` 拒绝不合格输出。

`pypost edit plot.yml` 仅用于浏览数据：工具栏的平移、缩放和 Home 都不会写回 YAML。
所有最终 xlim、ylim、legend、边距和标签参数应直接用 YAML 数字定义。
