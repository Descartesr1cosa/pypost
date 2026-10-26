# Curve comparison demo

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
