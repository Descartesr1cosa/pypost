"""Declarative, non-interpolating 1-D curve comparison."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import numpy as np

from .data import Data1D
from .plotting import Plot1D


def _scale(spec: dict[str, Any], key: str) -> float:
    return float(spec.get(f"{key}_scale", spec.get("scale", {}).get(key, 1.0)))


def compare(config: dict[str, Any], base: str | Path = ".") -> Path:
    """Render curves described by ``datasets`` without silently aligning grids."""
    base = Path(base)
    plot_cfg = config.get("plot", config)
    figure = plot_cfg.get("figure", {})
    output = Path(plot_cfg.get("output", "curve_compare.png"))
    if not output.is_absolute():
        output = base / output
    renderer = Plot1D(figsize=tuple(figure.get("size", (6.4, 4.2))), dpi=figure.get("dpi"))
    for item in config.get("datasets", []):
        source = Path(item["path"])
        if not source.is_absolute():
            source = base / source
        data = Data1D.from_file(source, x=item.get("x"))
        field = item["y"]
        if field not in data.fields:
            raise KeyError(f"{field!r} not found in {source}; available: {list(data.fields)}")
        x = data.x * _scale(item, "x")
        y = data.fields[field] * _scale(item, "y")
        style = dict(item.get("style", {}))
        label = item.get("label", source.stem)
        mode = item.get("kind", "line")
        if mode == "scatter":
            renderer.ax.scatter(x, y, label=label, **style)
        elif mode == "errorbar":
            error = item.get("yerr")
            if isinstance(error, str):
                error = data.fields[error] * _scale(item, "y")
            renderer.ax.errorbar(x, y, yerr=error, label=label, **style)
        elif mode == "band":
            lower, upper = item["lower"], item["upper"]
            renderer.ax.fill_between(x, data.fields[lower], data.fields[upper], label=label, **style)
        elif mode == "line":
            renderer.ax.plot(x, y, label=label, **style)
        else:
            raise ValueError("curve kind must be line, scatter, errorbar, or band")
    axes = plot_cfg.get("axes", {})
    renderer.set_axes(
        xlabel=axes.get("xlabel"), ylabel=axes.get("ylabel"), title=axes.get("title"),
        xlim=axes.get("xlim"), ylim=axes.get("ylim"), xticks=axes.get("xticks"),
        yticks=axes.get("yticks"), legend=axes.get("legend", bool(config.get("datasets"))),
        legend_kwargs=axes.get("legend_kwargs", {"loc": axes.get("legend_loc", "best"), "fontsize": axes.get("legend_fontsize")}),
    )
    if axes.get("grid", False):
        renderer.ax.grid(True, **(axes["grid"] if isinstance(axes["grid"], dict) else {}))
    output.parent.mkdir(parents=True, exist_ok=True)
    renderer.save(output, dpi=figure.get("dpi"), bbox_inches="tight")
    return output
