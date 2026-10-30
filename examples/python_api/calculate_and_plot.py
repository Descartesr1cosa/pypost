#!/usr/bin/env python
"""Run YAML-declared calculations and create a visual output.

Run: python scripts/calculate_and_plot.py configs/plot.yml
"""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from sciplot import Plot1D, Plot2D, Plot3D
from sciplot.workflow import apply_calculations, load_data, read_yaml, save_data


def main(config_path: str) -> None:
    config = read_yaml(config_path)
    data = apply_calculations(load_data(config["input"]), config.get("calculations", []))
    if "processed_output" in config:
        save_data(data, config["processed_output"])
    plot_spec = config["plot"]
    dimension, field, output = str(plot_spec["dimension"]), plot_spec["field"], plot_spec["output"]
    common = {k: plot_spec[k] for k in ("cmap", "vmin", "vmax") if k in plot_spec}
    if dimension == "1":
        plot = Plot1D(figsize=plot_spec.get("figsize", (6.4, 4.2)), style=plot_spec.get("style"))
        plot.line(data, field, label=plot_spec.get("label"), **plot_spec.get("line", {}))
        plot.set_axes(**plot_spec.get("axes", {}))
        plot.save(output, dpi=plot_spec.get("dpi"))
    elif dimension == "2":
        plot = Plot2D(figsize=plot_spec.get("figsize", (6.4, 4.8)), style=plot_spec.get("style"))
        plot.contourf(data, field, levels=plot_spec.get("levels", 20), **common)
        if "contours" in plot_spec:
            plot.contour(data, field, levels=plot_spec["contours"], colors="black")
        plot.set_axes(**plot_spec.get("axes", {}))
        plot.save(output, dpi=plot_spec.get("dpi"))
    elif dimension == "3":
        plot = Plot3D(window_size=tuple(plot_spec.get("window_size", (1024, 768))), background=plot_spec.get("background", "white"))
        if "slice" in plot_spec:
            plot.slice(data, field=field, **plot_spec["slice"], **common)
        else:
            plot.surface(data, field=field, **common)
        plot.screenshot(output); plot.close()
    else:
        raise ValueError("plot.dimension must be '1', '2', or '3'")
    print(f"Wrote {output}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: calculate_and_plot.py CONFIG.yml")
    main(sys.argv[1])
