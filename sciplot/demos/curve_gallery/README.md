# 1-D Feature Gallery

All data are small, deterministic synthetic values. Run `pypost demo run
curve-gallery` to create PDF, SVG, and PNG outputs. For an editable project:

```bash
pypost demo init curve-gallery --dest gallery-project
pypost curve compare --config gallery-project/gallery.yml
```

`gallery.yml` is a 2×2 overview and `panels/` contains four smaller,
independent configurations that use `../gallery.csv`:

- **A — `line_scatter.yml`:** line, scatter, color, marker and compact legend;
  suitable for comparing a model with measured samples.
- **B — `uncertainty.yml`:** uncertainty band plus error bars; use it when
  reporting confidence intervals or experimental uncertainty.
- **C — `loglog.yml`:** positive log–log data with major/minor grids; use it
  for scale-law or multi-decade responses.
- **D — `symlog_inset.yml`:** signed residuals on a symlog axis and a small
  inset moved away from the most informative data; use it for deviations that
  cross zero.

Each file names its local output. Edit its `axes`, `style`, and `plot.figure`
settings before rerunning the same one-line command.
