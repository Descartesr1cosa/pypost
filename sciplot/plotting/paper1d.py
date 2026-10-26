"""Numerical configuration, publication style, and validation for 1-D plots.

This module intentionally contains no GUI state.  A paper figure is fully
defined by YAML numbers and can therefore be rebuilt on another machine.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
import warnings

import matplotlib as mpl
from matplotlib import font_manager
from matplotlib.ticker import MaxNLocator, LogLocator
import yaml


MM_PER_INCH = 25.4
PT_PER_INCH = 72.0
PROFILE_NAME = "paper-1d"

PAPER_1D_STYLE: dict[str, Any] = {
    "version": 1,
    "fonts": {"families": ["Times New Roman", "STIX Two Text", "STIXGeneral", "DejaVu Serif"],
              "mathtext": "stix", "size_pt": 10, "label_size_pt": 10, "title_size_pt": 11,
              "legend_size_pt": 9},
    "cycles": {"colors": ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000", "#999999"],
               "linestyles": ["-", "--", "-.", ":"], "markers": ["o", "s", "^", "D", "v", "P", "X", "*"]},
    "lines": {"width_pt": 1.25, "marker_size_pt": 5.0},
    "axes": {"line_width_pt": 0.8},
    "ticks": {"direction": "in", "major_length_pt": 4, "minor_length_pt": 2, "width_pt": 0.8,
              "minor": True, "scientific": {"limits": [-3, 3]}},
    "grid": {"major": {"alpha": 0.18, "linewidth": 0.5}, "minor": False},
    "legend": {"frameon": False},
    "limits": {"nice_limits": True, "include_endpoints": True, "target_ticks": 5},
}

PAPER_1D_LAYOUT: dict[str, Any] = {
    "version": 1,
    "mode": "auto",
    "figure": {"width": 120, "height": 80, "unit": "mm", "dpi": 300},
    "margins": {"unit": "percent", "left": 15, "right": 5, "bottom": 18, "top": 7, "wspace": 8, "hspace": 10},
    "labels": {"xlabel": {"gap": {"value": 7, "unit": "pt"}},
               "ylabel": {"gap": {"value": 8, "unit": "pt"}},
               "title": {"gap": {"value": 6, "unit": "pt"}}},
    "legend": {"position": "best"},
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def profile_files(name: str = PROFILE_NAME) -> tuple[dict[str, Any], dict[str, Any]]:
    if name != PROFILE_NAME:
        raise ValueError(f"Unknown 1-D profile {name!r}; choose {PROFILE_NAME!r}")
    return deepcopy(PAPER_1D_STYLE), deepcopy(PAPER_1D_LAYOUT)


def export_profile(kind: str, path: str | Path, profile: str = PROFILE_NAME) -> Path:
    style, layout = profile_files(profile)
    if kind == "style": value = style
    elif kind == "layout": value = layout
    else: raise ValueError("Profile export kind must be style or layout")
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _read_mapping(path: Path, name: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid {name} YAML {path}: {exc}") from exc
    if not isinstance(value, dict): raise ValueError(f"{name} YAML must contain a mapping: {path}")
    return value


def resolve_configuration(config: dict[str, Any], base: str | Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return effective plot/style/layout mappings with one source per concern."""
    base = Path(base); plot = deepcopy(config.get("plot", {}))
    profile = plot.get("profile", PROFILE_NAME)
    style, layout = profile_files(profile)
    for key, target in (("style_file", "style"), ("layout_file", "layout")):
        value = plot.get(key)
        if value:
            path = Path(value); path = path if path.is_absolute() else base / path
            if not path.is_file(): raise FileNotFoundError(f"{target}.yml not found: {path}")
            loaded = _read_mapping(path, target)
            if target == "style": style = _merge(style, loaded)
            else: layout = _merge(layout, loaded)
    # Legacy in-plot layout remains a low-risk compatibility overlay, but new
    # configs should keep physical geometry in layout.yml.
    if isinstance(plot.get("layout"), dict): layout = _merge(layout, plot["layout"])
    return plot, style, layout


def _resolved_font(style: dict[str, Any]) -> tuple[str, str]:
    requested = list(style.get("fonts", {}).get("families", PAPER_1D_STYLE["fonts"]["families"]))
    for family in requested:
        try:
            path = font_manager.findfont(font_manager.FontProperties(family=family), fallback_to_default=False)
            actual = font_manager.FontProperties(fname=path).get_name()
            return family, actual
        except ValueError:
            continue
    path = font_manager.findfont(font_manager.FontProperties(family="DejaVu Serif"))
    return requested[0] if requested else "DejaVu Serif", font_manager.FontProperties(fname=path).get_name()


def rc_values(style: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    fonts, lines, axes, ticks = style.get("fonts", {}), style.get("lines", {}), style.get("axes", {}), style.get("ticks", {})
    requested, actual = _resolved_font(style)
    if requested != actual:
        warnings.warn(f"paper-1d requested font {requested!r}; using installed fallback {actual!r}", stacklevel=2)
    rc = {"font.family": actual, "font.size": float(fonts.get("size_pt", 10)),
          "mathtext.fontset": fonts.get("mathtext", "stix"), "axes.labelsize": float(fonts.get("label_size_pt", 10)),
          "axes.titlesize": float(fonts.get("title_size_pt", 11)), "legend.fontsize": float(fonts.get("legend_size_pt", 9)),
          "lines.linewidth": float(lines.get("width_pt", 1.25)), "lines.markersize": float(lines.get("marker_size_pt", 5)),
          "axes.linewidth": float(axes.get("line_width_pt", .8)), "xtick.direction": ticks.get("direction", "in"),
          "ytick.direction": ticks.get("direction", "in"), "xtick.major.size": float(ticks.get("major_length_pt", 4)),
          "ytick.major.size": float(ticks.get("major_length_pt", 4)), "xtick.minor.size": float(ticks.get("minor_length_pt", 2)),
          "ytick.minor.size": float(ticks.get("minor_length_pt", 2)), "xtick.major.width": float(ticks.get("width_pt", .8)),
          "ytick.major.width": float(ticks.get("width_pt", .8))}
    return rc, {"requested": requested, "actual": actual}


def figure_size(layout: dict[str, Any]) -> tuple[float, float, int | None]:
    figure = layout.get("figure", {})
    width, height, unit = float(figure.get("width", 120)), float(figure.get("height", 80)), figure.get("unit", "mm")
    if unit == "mm": width, height = width / MM_PER_INCH, height / MM_PER_INCH
    elif unit != "in": raise ValueError("layout.figure.unit must be mm or in")
    if width <= 0 or height <= 0: raise ValueError("layout.figure width and height must be positive")
    return width, height, figure.get("dpi")


def _gap(value: Any) -> float:
    if value is None: return 0.0
    if isinstance(value, (int, float)): return float(value)
    if not isinstance(value, dict): raise ValueError("layout label gap must be a number or {value, unit}")
    unit = value.get("unit", "pt")
    if unit != "pt": raise ValueError("layout label gaps currently use typographic pt")
    return float(value.get("value", 0))


def apply_layout(fig, axes: list[Any], layout: dict[str, Any]) -> None:
    mode = layout.get("mode", "auto")
    if mode not in {"auto", "fixed"}: raise ValueError("layout.mode must be auto or fixed")
    if mode == "auto":
        fig.set_layout_engine("constrained")
    else:
        fig.set_layout_engine(None)
        margins = layout.get("margins", {}); unit = margins.get("unit", "percent")
        if unit != "percent": raise ValueError("layout.margins.unit must be percent (relative to Figure)")
        values = {key: float(margins.get(key, PAPER_1D_LAYOUT["margins"].get(key, 0))) / 100 for key in ("left", "bottom", "wspace", "hspace")}
        values["right"] = 1 - float(margins.get("right", PAPER_1D_LAYOUT["margins"]["right"])) / 100
        values["top"] = 1 - float(margins.get("top", PAPER_1D_LAYOUT["margins"]["top"])) / 100
        if not (0 <= values["left"] < values["right"] <= 1 and 0 <= values["bottom"] < values["top"] <= 1):
            raise ValueError("layout margins must leave a positive Figure area")
        fig.subplots_adjust(**values)
    labels = layout.get("labels", {})
    for ax in axes:
        ax.xaxis.labelpad = _gap(labels.get("xlabel", {}).get("gap"))
        ax.yaxis.labelpad = _gap(labels.get("ylabel", {}).get("gap"))
        ax.set_title(ax.get_title(), pad=_gap(labels.get("title", {}).get("gap")))
    panel_positions = layout.get("panels", {})
    for index, ax in enumerate(axes):
        entry = panel_positions.get(f"panel-{index}", {})
        if entry.get("position"):
            values = [float(v) / 100 for v in entry["position"]]
            if len(values) != 4: raise ValueError("layout.panels.*.position must be [left, bottom, width, height] in percent Figure")
            ax.set_position(values)


def legend_kwargs(layout: dict[str, Any], style: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    result = dict(style.get("legend", {})); result.update(fallback or {})
    spec = layout.get("legend", {})
    position = spec.get("position")
    if position: result["loc"] = position.replace("_", " ")
    if "anchor" in spec:
        anchor = [float(v) for v in spec["anchor"]]
        unit = spec.get("anchor_unit", "percent_axes")
        if unit == "percent_axes": anchor = [v / 100 for v in anchor]
        elif unit != "axes": raise ValueError("layout.legend.anchor_unit must be percent_axes or axes")
        result["bbox_to_anchor"] = anchor
    return result


def apply_nice_ticks(ax, style: dict[str, Any], explicit_x: bool, explicit_y: bool) -> None:
    limits = style.get("limits", {})
    if not limits.get("nice_limits", True): return
    count = int(limits.get("target_ticks", 5)); steps = [1, 2, 2.5, 5, 10]
    if not explicit_x:
        if ax.get_xscale() == "linear": ax.xaxis.set_major_locator(MaxNLocator(nbins=count, steps=steps))
        elif ax.get_xscale() == "log": ax.xaxis.set_major_locator(LogLocator(base=10))
    if not explicit_y:
        if ax.get_yscale() == "linear": ax.yaxis.set_major_locator(MaxNLocator(nbins=count, steps=steps))
        elif ax.get_yscale() == "log": ax.yaxis.set_major_locator(LogLocator(base=10))


def _visible_text(fig) -> list[tuple[str, Any]]:
    entries: list[tuple[str, Any]] = []
    for index, ax in enumerate(fig.axes):
        entries.extend([(f"panel-{index} x label", ax.xaxis.label), (f"panel-{index} y label", ax.yaxis.label), (f"panel-{index} title", ax.title),
                        (f"panel-{index} x offset", ax.xaxis.get_offset_text()), (f"panel-{index} y offset", ax.yaxis.get_offset_text())])
        entries.extend((f"panel-{index} x tick", value) for value in ax.get_xticklabels(minor=False) + ax.get_xticklabels(minor=True))
        entries.extend((f"panel-{index} y tick", value) for value in ax.get_yticklabels(minor=False) + ax.get_yticklabels(minor=True))
        legend = ax.get_legend()
        if legend: entries.extend((f"panel-{index} legend", value) for value in legend.get_texts())
        entries.extend((f"panel-{index} annotation", value) for value in ax.texts)
    entries.extend(("figure text", value) for value in fig.texts)
    return [(name, artist) for name, artist in entries if artist.get_visible() and artist.get_text()]


def publication_report(fig, publication: dict[str, Any] | None, font_info: dict[str, str]) -> dict[str, Any] | None:
    if not publication: return None
    export_width = fig.get_figwidth() * MM_PER_INCH
    placement = publication.get("placement_width_mm")
    has_scale = "scale" in publication
    if placement is not None and has_scale: raise ValueError("publication accepts placement_width_mm or scale, not both")
    scale = float(publication["scale"]) if has_scale else float(placement) / export_width if placement is not None else 1.0
    if scale <= 0: raise ValueError("publication scale must be positive")
    minimum = float(publication.get("min_text_pt", 8)); policy = publication.get("font_policy", "warn")
    if policy not in {"auto", "warn", "error"}: raise ValueError("publication.font_policy must be auto, warn, or error")
    required_export = minimum / scale
    entries = _visible_text(fig)
    if policy == "auto":
        for _, artist in entries:
            if artist.get_fontsize() < required_export: artist.set_fontsize(required_export)
    rows = []
    for name, artist in _visible_text(fig):
        size = float(artist.get_fontsize()); final = size * scale
        rows.append({"object": name, "text": artist.get_text(), "export_pt": size, "final_pt": final,
                     "status": "PASS" if final + 1e-9 >= minimum else "FAIL"})
    failed = [row for row in rows if row["status"] == "FAIL"]
    mathtext = any("$" in row["text"] for row in rows)
    report = {"export_width_mm": export_width, "placement_width_mm": placement, "scale": scale,
              "min_text_pt": minimum, "font_policy": policy, "font": font_info, "objects": rows,
              "overall": "FAIL" if failed else "PASS", "mathtext_note": "Parent text font sizes are checked; Mathtext sub/superscripts may render smaller." if mathtext else None}
    if failed and policy == "error":
        raise ValueError("Publication font check failed: " + ", ".join(f"{row['object']}={row['final_pt']:.2g}pt" for row in failed[:5]))
    if failed and policy == "warn": warnings.warn("Publication font check failed; see publication report.", stacklevel=2)
    return report


def write_publication_report(path: str | Path, report: dict[str, Any]) -> Path:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
