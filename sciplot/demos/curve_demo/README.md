# Curve comparison demo / 数值化论文曲线示例

`curve_comparison.yml` contains only scientific data choices, axis labels, and
outputs. `style.yml` contains visual styling and `layout.yml` contains physical
millimetre/percent geometry. All three files are plain numerical YAML, so the
same result can be regenerated without an editor session.

```bash
pypost plot curve_comparison.yml
pypost check-figure curve_comparison.yml
pypost style export paper-1d --out my-style.yml
pypost layout export paper-1d --out my-layout.yml
```

`pypost edit curve_comparison.yml` is a data browser: Pan/Zoom/Home are useful
for inspection but never overwrite final x/y limits or layout.

中文：`curve_comparison.yml` 管理科学内容，`style.yml` 管理视觉风格，
`layout.yml` 管理毫米、百分比和 pt 的页面几何。编辑窗口只浏览数据，最终图完全由
可读 YAML 数值复现。

The three CSV files are small, explicitly synthetic, dimensionless drag curves.

For an editable starter project (recommended):

```bash
pypost demo init curve-comparison --dest my-plot
pypost curve compare --config my-plot/plot.yml
```

Edit `reference.csv`, `medium.csv`, `coarse.csv`, or `plot.yml`; the command
creates local PDF and SVG files. The YAML demonstrates a scaled uncertainty
band, line, and scatter curve through the same `Plot1D` API used by Python
callers. `pypost demo run curve-comparison` is a read-only quick preview.
