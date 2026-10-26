"""Declarative, non-interpolating curve comparison and panel layouts."""
from __future__ import annotations
from copy import deepcopy
import os
from pathlib import Path
from typing import Any
import warnings
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from .data import Data1D
from .io import load_dataset
from .plotting import Plot1D
from .plotting.layout import apply_layout, capture_layout, load_layout
from .plotting.paper1d import (apply_layout as apply_numerical_layout, apply_nice_ticks,
                               figure_size, legend_kwargs, publication_report,
                               rc_values, resolve_configuration, write_publication_report)


def _value(spec: dict[str, Any], name: str, default=0.0) -> float:
    return float(spec.get(name, spec.get("transform", {}).get(name, default)))


def _curve(plot: Plot1D, item: dict[str, Any], base: Path, axes: dict[str, Any] | None = None,
           cycle: dict[str, Any] | None = None, index: int = 0):
    allowed = {"path", "x", "y", "label", "kind", "lower", "upper", "yerr", "style",
               "x_scale", "x_offset", "y_scale", "y_offset", "transform"}
    unknown = set(item) - allowed
    if unknown:
        raise KeyError(
            f"Unknown dataset YAML key(s): {sorted(unknown)}. Common keys are path, x, y, "
            "label, kind, style, x_scale, and y_scale."
        )
    for required in ("path", "x", "y"):
        if required not in item:
            raise KeyError(
                f"Each dataset needs {required!r}. Add it under datasets (for example, "
                "{path: data.csv, x: time, y: Cd})."
            )
    source = Path(item["path"]); source = source if source.is_absolute() else base / source
    if not source.is_file():
        raise FileNotFoundError(
            f"Curve input file not found: {source}. Check datasets[].path; relative paths start at {base}."
        )
    try:
        data = load_dataset(source) if source.suffix.lower() == ".npz" else Data1D.from_file(source, x=item["x"])
        if not isinstance(data, Data1D):
            raise TypeError(f"Curve dataset {source} is not 1-D standard data")
    except KeyError as exc:
        raise KeyError(
            f"CSV column error in {source.name}: {exc}. Check datasets[].x and the CSV header."
        ) from exc
    field = item["y"]
    if field not in data.fields:
        raise KeyError(
            f"Column {field!r} was not found in {source.name}. Available columns: "
            f"{[data.x_name, *data.fields]}. Check datasets[].y."
        )
    xfun = lambda v: Plot1D.transformed(v, _value(item, "x_scale", 1), _value(item, "x_offset", 0))
    yfun = lambda v: Plot1D.transformed(v, _value(item, "y_scale", 1), _value(item, "y_offset", 0))
    axes = axes or {}
    for label, values, scale in (("x", xfun(data.x), axes.get("xscale", "linear")),
                                 ("y", yfun(data.fields[field]), axes.get("yscale", "linear"))):
        if scale == "log" and np.any(np.asarray(values) <= 0):
            raise ValueError(
                f"Cannot use a log {label}-axis with zero or negative values in {source.name}. "
                f"Choose symlog or adjust {label}_scale/{label}_offset."
            )
    style, label, kind = dict(item.get("style", {})), item.get("label", source.stem), item.get("kind", "line")
    # Stable combinations make a minimal YAML deterministic without forcing
    # markers onto dense continuous lines.
    if cycle:
        colors, linestyles, markers = cycle.get("colors", []), cycle.get("linestyles", []), cycle.get("markers", [])
        if colors: style.setdefault("color", colors[index % len(colors)])
        if linestyles and kind == "line":
            # First curves differ in both hue and dash pattern (blue/solid,
            # red/dashed, green/dash-dot, purple/dotted). Subsequent cycles
            # rotate again instead of producing eight indistinguishable solids.
            style.setdefault("linestyle", linestyles[(index + index // max(len(colors), 1)) % len(linestyles)])
        if markers and kind in {"scatter", "errorbar"}: style.setdefault("marker", markers[index % len(markers)])
    if kind == "line": return plot.line(data, field, label, xfun, yfun, **style)
    if kind == "scatter": return plot.scatter(data, field, label, xfun, yfun, **style)
    if kind == "band": return plot.band(data, item["lower"], item["upper"], label, xfun, yfun, **style)
    if kind == "errorbar":
        error = item.get("yerr")
        if isinstance(error, str): error = np.asarray(data.fields[error]) * _value(item, "y_scale", 1)
        elif error is not None: error = np.asarray(error) * _value(item, "y_scale", 1)
        return plot.errorbar(data, field, error, label, xfun, yfun, **style)
    raise ValueError("curve kind must be line, scatter, errorbar, or band")


def _annotation_transform(fig, ax, coords: str):
    if coords == "data": return ax.transData
    if coords == "axes": return ax.transAxes
    if coords == "figure": return fig.transFigure
    raise ValueError("annotation coords must be data, axes, or figure")


def _add_annotations(fig, panels: dict[str, Any], specs: list[dict[str, Any]], annotations: dict[str, Any]) -> None:
    """Create text/Mathtext annotations with IDs independent of artist objects."""
    for spec in specs:
        if not isinstance(spec, dict): raise TypeError("Each annotation must be a YAML mapping")
        for key in ("id", "text", "xy"):
            if key not in spec: raise KeyError(f"Annotation needs {key!r}; IDs make saved layouts portable.")
        annotation_id = str(spec["id"])
        if annotation_id in annotations: raise ValueError(f"Duplicate annotation ID: {annotation_id!r}")
        panel_id = str(spec.get("panel", "panel-0"))
        if panel_id not in panels: raise ValueError(f"Annotation {annotation_id!r} refers to missing panel {panel_id!r}")
        coords = str(spec.get("coords", "axes")); ax = panels[panel_id]
        xy = tuple(float(v) for v in spec["xy"])
        if len(xy) != 2: raise ValueError(f"Annotation {annotation_id!r} xy must contain two numbers")
        properties = {key: value for key, value in spec.items()
                      if key not in {"id", "text", "xy", "coords", "panel", "arrow"}}
        arrow = spec.get("arrow")
        transform = _annotation_transform(fig, ax, coords)
        if arrow:
            if not isinstance(arrow, dict) or "xy" not in arrow:
                raise ValueError(f"Annotation {annotation_id!r} arrow needs target xy")
            target_coords = str(arrow.get("coords", "data"))
            target = tuple(float(v) for v in arrow["xy"])
            arrowprops = dict(arrow.get("style", {"arrowstyle": "->"}))
            artist = ax.annotate(str(spec["text"]), xy=target, xytext=xy,
                                 xycoords=_annotation_transform(fig, ax, target_coords), textcoords=transform,
                                 arrowprops=arrowprops, **properties)
        else:
            artist = ax.text(*xy, str(spec["text"]), transform=transform, **properties)
        artist.set_gid(f"annotation:{annotation_id}")
        artist._pypost_annotation = {"panel": panel_id, "coords": coords}
        annotations[annotation_id] = artist


def _panel(plot: Plot1D, spec: dict[str, Any], base: Path, panel_id: str, panels: dict[str, Any], annotations: dict[str, Any],
           style_cfg: dict[str, Any] | None = None, layout_cfg: dict[str, Any] | None = None):
    axes = spec.get("axes", spec.get("plot", {}).get("axes", {}))
    if not isinstance(axes, dict):
        raise TypeError("axes must be a YAML mapping, for example: axes: {xlabel: time, ylabel: Cd}.")
    for index, item in enumerate(spec.get("datasets", [])):
        _curve(plot, item, base, axes, (style_cfg or {}).get("cycles"), index)
    legend = axes.get("legend", bool(spec.get("datasets")))
    kwargs = deepcopy(legend) if isinstance(legend, dict) else {"loc": axes.get("legend_loc", "best")}
    kwargs = legend_kwargs(layout_cfg or {}, style_cfg or {}, kwargs)
    plot.set_axes(xlabel=axes.get("xlabel"), ylabel=axes.get("ylabel"), title=axes.get("title"), xlim=axes.get("xlim"), ylim=axes.get("ylim"),
                  xticks=axes.get("xticks"), yticks=axes.get("yticks"), legend=bool(legend), legend_kwargs=kwargs,
                  xscale=axes.get("xscale", "linear"), yscale=axes.get("yscale", "linear"), xscale_kwargs=axes.get("xscale_kwargs"), yscale_kwargs=axes.get("yscale_kwargs"),
                  tick_params=axes.get("tick_params"), minor_ticks=axes.get("minor_ticks", (style_cfg or {}).get("ticks", {}).get("minor", False)), scientific=axes.get("scientific", (style_cfg or {}).get("ticks", {}).get("scientific")),
                  xlabelpad=axes.get("xlabelpad"), ylabelpad=axes.get("ylabelpad"))
    if axes.get("xlabel_position") is not None:
        plot.ax.xaxis.set_label_coords(*axes["xlabel_position"]); plot.ax.xaxis.label._pypost_layout_position = axes["xlabel_position"]
    if axes.get("ylabel_position") is not None:
        plot.ax.yaxis.set_label_coords(*axes["ylabel_position"]); plot.ax.yaxis.label._pypost_layout_position = axes["ylabel_position"]
    if axes.get("title_position") is not None:
        plot.ax.title.set_position(axes["title_position"]); plot.ax.title._pypost_layout_position = axes["title_position"]
    grid = axes.get("grid")
    if isinstance(grid, dict): plot.grid(grid.get("major"), grid.get("minor"))
    elif grid: plot.grid(True)
    elif style_cfg and style_cfg.get("grid", {}).get("major"): plot.grid(style_cfg["grid"]["major"], style_cfg["grid"].get("minor"))
    apply_nice_ticks(plot.ax, style_cfg or {}, axes.get("xlim") is not None, axes.get("ylim") is not None,
                     axes.get("xticks") is not None, axes.get("yticks") is not None)
    if spec.get("panel_label"): plot.panel_label(spec["panel_label"])
    for item in spec.get("hlines", []): plot.hline(item["y"], **{k:v for k,v in item.items() if k != "y"})
    inset = spec.get("inset")
    if inset:
        child = plot.inset(inset.get("bounds", [0.55, 0.08, "40%", "40%"]),
                           axes_kwargs=inset.get("style"))
        child_spec = {**inset, "datasets": inset.get("datasets", spec.get("datasets", [])), "inset": None}
        _panel(child, child_spec, base, f"{panel_id}.inset", panels, annotations, style_cfg, layout_cfg)
    panels[panel_id] = plot.ax
    _add_annotations(plot.fig, panels, spec.get("annotations", []), annotations)


def _layout_options(plot_cfg: dict[str, Any]) -> tuple[str, dict[str, float], str | None]:
    layout = plot_cfg.get("layout", {})
    if layout is None: layout = {}
    if not isinstance(layout, dict): raise TypeError("plot.layout must be a YAML mapping")
    mode = layout.get("mode", "auto")
    if mode not in {"auto", "manual"}: raise ValueError("plot.layout.mode must be auto or manual")
    margins = dict(layout.get("margins", {}))
    margins.update({key: layout[key] for key in ("left", "right", "bottom", "top", "wspace", "hspace") if key in layout})
    if mode == "auto" and margins:
        raise ValueError("plot.layout.mode auto cannot use manual margins; set mode: manual instead")
    if set(margins) - {"left", "right", "bottom", "top", "wspace", "hspace"}:
        raise ValueError("plot.layout.margins supports left, right, bottom, top, wspace, hspace")
    return mode, {key: float(value) for key, value in margins.items()}, layout.get("overrides")


def build_figure(config: dict[str, Any], base: str | Path = "."):
    """Build a curve figure once for render, preview, and interactive editing."""
    if not isinstance(config, dict):
        raise TypeError("Curve YAML must contain a mapping. Start with datasets: or panels:.")
    allowed = {"kind", "datasets", "plot", "panels", "axes", "panel_label", "hlines", "inset", "annotations"}
    unexpected = set(config) - allowed
    if unexpected:
        raise KeyError(f"Unknown top-level curve YAML key(s): {sorted(unexpected)}. Allowed keys: {sorted(allowed)}.")
    if config.get("kind", "curve") != "curve": raise ValueError("pypost plot currently supports kind: curve only")
    base = Path(base); plot_cfg, style_cfg, numerical_layout = resolve_configuration(config, base)
    rc, font_info = rc_values(style_cfg)
    # Retain the old in-plot layout shorthand only when no modern layout file
    # is selected. The canonical numerical layout comes from layout.yml.
    figure = plot_cfg.get("figure", {}); panels_spec = config.get("panels")
    mode, margins, override = _layout_options(plot_cfg)
    if plot_cfg.get("layout_file") or plot_cfg.get("profile", "paper-1d") == "paper-1d":
        mode, margins = numerical_layout.get("mode", "auto"), {}
    constrained = mode == "auto"
    panels: dict[str, Any] = {}; annotations: dict[str, Any] = {}
    with mpl.rc_context(rc):
        if figure.get("size"):
            width, height = tuple(figure["size"])
            if figure.get("size_unit", "in") == "mm": width, height = width / 25.4, height / 25.4
            dpi = figure.get("dpi")
        else:
            width, height, dpi = figure_size(numerical_layout)
        if panels_spec:
            fig, axes = plt.subplots(int(figure.get("nrows", 1)), int(figure.get("ncols", len(panels_spec))), figsize=(width, height), dpi=dpi, sharex=figure.get("sharex", False), sharey=figure.get("sharey", False), squeeze=False, constrained_layout=False)
            for index, (axis, panel) in enumerate(zip(axes.flat, panels_spec)):
                panel_id = str(panel.get("id", f"panel-{index}"))
                if panel_id in panels: raise ValueError(f"Duplicate panel ID: {panel_id!r}")
                _panel(Plot1D(ax=axis, style=rc), panel, base, panel_id, panels, annotations, style_cfg, numerical_layout)
            for axis in list(axes.flat)[len(panels_spec):]: axis.set_visible(False)
            renderer = Plot1D(ax=axes.flat[0], style=rc); renderer.fig = fig
        else:
            renderer = Plot1D(figsize=(width, height), dpi=dpi, style=rc)
            # Root annotations are added once after the panel exists.  Panel-local
            # annotations remain available in multi-panel specifications.
            panel_spec = dict(config); panel_spec.pop("annotations", None)
            if isinstance(plot_cfg.get("axes"), dict):
                panel_spec["axes"] = {**panel_spec.get("axes", {}), **plot_cfg["axes"]}
            _panel(renderer, panel_spec, base, "panel-0", panels, annotations, style_cfg, numerical_layout)
        active_axes = list(panels.values())
        if plot_cfg.get("profile", "paper-1d") == "paper-1d" or plot_cfg.get("layout_file"):
            apply_numerical_layout(renderer.fig, active_axes, numerical_layout)
        elif mode == "manual": renderer.fig.subplots_adjust(**margins)
    _add_annotations(renderer.fig, panels, config.get("annotations", []), annotations)
    renderer._pypost_style = style_cfg; renderer._pypost_layout = numerical_layout; renderer._pypost_font_info = font_info
    publication = plot_cfg.get("publication", numerical_layout.get("publication"))
    renderer._pypost_publication = publication_report(renderer.fig, publication, font_info)
    default_layout = capture_layout(renderer.fig, panels, annotations)
    if override:
        path = Path(override); path = path if path.is_absolute() else base / path
        saved = load_layout(path)
        if saved is not None: apply_layout(renderer.fig, panels, annotations, saved)
    return renderer, panels, annotations, plot_cfg, default_layout


def _warn_if_clipped(fig) -> None:
    fig.canvas.draw()
    canvas = fig.bbox
    clipped = []
    # Tick labels can intentionally extend a fraction beyond an Axes; report
    # only user-facing labels, titles, fig.text and explicit annotations.
    artists = list(fig.texts)
    for ax in fig.axes:
        artists.extend((ax.xaxis.label, ax.yaxis.label, ax.title))
        artists.extend(item for item in ax.texts if hasattr(item, "_pypost_annotation"))
    for artist in artists:
        if not artist.get_visible() or not artist.get_text(): continue
        box = artist.get_window_extent(fig.canvas.get_renderer())
        if box.x0 < canvas.x0 - 1 or box.y0 < canvas.y0 - 1 or box.x1 > canvas.x1 + 1 or box.y1 > canvas.y1 + 1:
            clipped.append(artist.get_text())
    if clipped:
        warnings.warn("Some figure text extends outside the canvas; use plot.layout.mode: auto, "
                      "increase margins, or adjust label positions: " + ", ".join(repr(text) for text in clipped[:3]), stacklevel=2)


def compare(config: dict[str, Any], base: str | Path = ".", output: str | Path | None = None, show: bool = False) -> Path:
    """Render a single comparison or YAML ``panels`` grid without interpolating."""
    base = Path(base); renderer, _, _, plot_cfg, _ = build_figure(config, base); figure = plot_cfg.get("figure", {})
    outputs = [Path(v) for v in (plot_cfg.get("outputs") or [plot_cfg.get("output", "curve_compare.png")])]
    if output is not None: outputs = [Path(output)]
    outputs = [p if p.is_absolute() else base / p for p in outputs]
    _warn_if_clipped(renderer.fig)
    report = getattr(renderer, "_pypost_publication", None)
    publication_cfg = plot_cfg.get("publication", getattr(renderer, "_pypost_layout", {}).get("publication", {}))
    report_path = publication_cfg.get("report") if isinstance(publication_cfg, dict) else None
    if report_path:
        target = Path(report_path); target = target if target.is_absolute() else base / target
        write_publication_report(target, report)
    if figure.get("tight") and publication_cfg:
        warnings.warn("tight output can change the physical bounding box; publication width in the report refers to the declared Figure size.", stacklevel=2)
    for path in outputs:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            renderer.save(path, dpi=figure.get("dpi"), tight=bool(figure.get("tight", False)))
        except OSError as exc:
            raise OSError(f"Cannot save figure to {path}. Check plot.outputs and directory permissions.") from exc
    if show:
        if not os.environ.get("DISPLAY"): raise RuntimeError("Interactive preview requires a graphical DISPLAY.")
        plt.show()
    return outputs[0]


def check_figure(config: dict[str, Any], base: str | Path = ".") -> dict[str, Any]:
    """Build once and return a deterministic publication-size report without saving images."""
    renderer, _, _, _, _ = build_figure(config, base)
    report = getattr(renderer, "_pypost_publication", None)
    if report is None:
        report = publication_report(renderer.fig, {"scale": 1.0, "min_text_pt": 0, "font_policy": "warn"}, renderer._pypost_font_info)
    return report
