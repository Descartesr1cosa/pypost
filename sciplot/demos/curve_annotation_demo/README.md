# Formula and text annotation demo

This self-contained data set is synthetic. It demonstrates stable annotation
IDs across two panels, Mathtext, ordinary text, a data-coordinate arrow, and a
figure-coordinate footer.

```bash
pypost demo init curve-annotations --dest annotated-figure
pypost plot annotated-figure/annotations.yml
pypost edit annotated-figure/annotations.yml
```

`coords: data` uses physical axis values, `coords: axes` uses fractions of an
individual panel (`[0, 0]` bottom-left, `[1, 1]` top-right), and `coords:
figure` uses fractions of the whole canvas. Drag annotations in the editor and
press **Ctrl+S**; only their positions are saved to `layout.json`.

`example-layout.json` demonstrates the portable JSON format. Copy it to
`layout.json` and rerun `pypost plot annotations.yml` to apply the saved visual
positions without changing the synthetic CSV values.
