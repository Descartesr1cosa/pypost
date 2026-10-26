# Figure layout editor demo

All values are synthetic. Automatic layout is the default, so the long x label
is exported without clipping while the figure retains its requested 88 × 68 mm
size. It starts near the lower edge but remains within the canvas; drag it
closer or change a margin to see the editor's clipping feedback.

```bash
pypost demo init curve-layout --dest layout-project
cd layout-project
pypost plot layout.yml
pypost edit layout.yml
```

In the editor, drag the x/y label, title or legend; use the companion margin
sliders if needed; press **Ctrl+S** to write `layout.json`. `pypost plot
layout.yml` then loads that JSON automatically. Press **R** in the editor to
restore the YAML defaults. Delete `layout.json` to return to automatic layout.
The JSON contains visual positions only, never the CSV values.

`example-layout.json` is a small portable reference state. Copy it to
`layout.json` to see a saved manual margin and x-label position, then rerun
`pypost plot layout.yml`.
