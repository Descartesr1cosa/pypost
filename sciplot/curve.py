"""Declarative, non-interpolating curve comparison and panel layouts."""
from __future__ import annotations
from copy import deepcopy
import os
from pathlib import Path
from typing import Any
import matplotlib.pyplot as plt
import numpy as np
from .data import Data1D
from .plotting import Plot1D


def _value(spec: dict[str, Any], name: str, default=0.0) -> float:
    return float(spec.get(name, spec.get("transform", {}).get(name, default)))


def _curve(plot: Plot1D, item: dict[str, Any], base: Path):
    source = Path(item["path"]); source = source if source.is_absolute() else base / source
    data = Data1D.from_file(source, x=item.get("x")); field = item["y"]
    xfun = lambda v: Plot1D.transformed(v, _value(item, "x_scale", 1), _value(item, "x_offset", 0))
    yfun = lambda v: Plot1D.transformed(v, _value(item, "y_scale", 1), _value(item, "y_offset", 0))
    style, label, kind = dict(item.get("style", {})), item.get("label", source.stem), item.get("kind", "line")
    if kind == "line": return plot.line(data, field, label, xfun, yfun, **style)
    if kind == "scatter": return plot.scatter(data, field, label, xfun, yfun, **style)
    if kind == "band": return plot.band(data, item["lower"], item["upper"], label, xfun, yfun, **style)
    if kind == "errorbar":
        error = item.get("yerr")
        if isinstance(error, str): error = np.asarray(data.fields[error]) * _value(item, "y_scale", 1)
        elif error is not None: error = np.asarray(error) * _value(item, "y_scale", 1)
        return plot.errorbar(data, field, error, label, xfun, yfun, **style)
    raise ValueError("curve kind must be line, scatter, errorbar, or band")


def _panel(plot: Plot1D, spec: dict[str, Any], base: Path):
    for item in spec.get("datasets", []): _curve(plot, item, base)
    axes = spec.get("axes", spec.get("plot", {}).get("axes", {}))
    legend = axes.get("legend", bool(spec.get("datasets")))
    kwargs = deepcopy(legend) if isinstance(legend, dict) else {"loc": axes.get("legend_loc", "best")}
    plot.set_axes(xlabel=axes.get("xlabel"), ylabel=axes.get("ylabel"), title=axes.get("title"), xlim=axes.get("xlim"), ylim=axes.get("ylim"),
                  xticks=axes.get("xticks"), yticks=axes.get("yticks"), legend=bool(legend), legend_kwargs=kwargs,
                  xscale=axes.get("xscale", "linear"), yscale=axes.get("yscale", "linear"), xscale_kwargs=axes.get("xscale_kwargs"), yscale_kwargs=axes.get("yscale_kwargs"),
                  tick_params=axes.get("tick_params"), minor_ticks=axes.get("minor_ticks", False), scientific=axes.get("scientific"))
    grid = axes.get("grid")
    if isinstance(grid, dict): plot.grid(grid.get("major"), grid.get("minor"))
    elif grid: plot.grid(True)
    if spec.get("panel_label"): plot.panel_label(spec["panel_label"])
    for item in spec.get("hlines", []): plot.hline(item["y"], **{k:v for k,v in item.items() if k != "y"})
    inset = spec.get("inset")
    if inset:
        child = plot.inset(inset.get("bounds", [0.55, 0.08, "40%", "40%"]))
        child_spec = {**inset, "datasets": inset.get("datasets", spec.get("datasets", [])), "inset": None}
        _panel(child, child_spec, base)


def compare(config: dict[str, Any], base: str | Path = ".", output: str | Path | None = None, show: bool = False) -> Path:
    """Render a single comparison or YAML ``panels`` grid without interpolating."""
    base = Path(base); plot_cfg = config.get("plot", config); figure = plot_cfg.get("figure", {}); panels = config.get("panels")
    if panels:
        size = tuple(figure.get("size", (6.4, 4.2))); size = tuple(x / 25.4 for x in size) if figure.get("size_unit") == "mm" else size
        fig, axes = plt.subplots(int(figure.get("nrows", 1)), int(figure.get("ncols", len(panels))), figsize=size, dpi=figure.get("dpi"), sharex=figure.get("sharex", False), sharey=figure.get("sharey", False), squeeze=False, constrained_layout=figure.get("constrained_layout", False))
        for axis, panel in zip(axes.flat, panels): _panel(Plot1D(ax=axis, style=plot_cfg.get("style")), panel, base)
        for axis in list(axes.flat)[len(panels):]: axis.set_visible(False)
        renderer = Plot1D(ax=axes.flat[0], style=plot_cfg.get("style")); renderer.fig = fig
    else:
        renderer = Plot1D(figsize=tuple(figure.get("size", (6.4, 4.2))), size_unit=figure.get("size_unit", "in"), dpi=figure.get("dpi"), style=plot_cfg.get("style")); _panel(renderer, config, base)
    outputs = [Path(v) for v in (plot_cfg.get("outputs") or [plot_cfg.get("output", "curve_compare.png")])]
    if output is not None: outputs = [Path(output)]
    outputs = [p if p.is_absolute() else base / p for p in outputs]
    for path in outputs: path.parent.mkdir(parents=True, exist_ok=True); renderer.save(path, dpi=figure.get("dpi"), tight=bool(figure.get("tight", False)))
    if show:
        if not os.environ.get("DISPLAY"): raise RuntimeError("Interactive preview requires a graphical DISPLAY.")
        plt.show()
    return outputs[0]
