"""Portable, data-free layout state for one-dimensional figures.

The JSON schema intentionally contains only numbers, strings and lists.  It
never serializes Matplotlib objects or executable expressions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


FORMAT = "pypost-1d-layout"
VERSION = 1


def _pair(value: Any, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"layout {name} must be a two-number list")
    return [float(value[0]), float(value[1])]


def _bounds(value: Any, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"layout {name} must be a four-number list")
    return [float(x) for x in value]


def validate_layout(layout: dict[str, Any]) -> dict[str, Any]:
    """Validate a layout document before it can affect a figure."""
    if not isinstance(layout, dict):
        raise ValueError("layout JSON must be an object")
    if layout.get("format") != FORMAT or layout.get("version") != VERSION:
        raise ValueError(f"Unsupported layout JSON; expected format={FORMAT!r}, version={VERSION}")
    result: dict[str, Any] = {"format": FORMAT, "version": VERSION, "figure": {}, "panels": {}, "annotations": {}}
    figure = layout.get("figure", {})
    if not isinstance(figure, dict):
        raise ValueError("layout figure must be an object")
    if "margins" in figure:
        margins = figure["margins"]
        if not isinstance(margins, dict) or set(margins) - {"left", "right", "bottom", "top", "wspace", "hspace"}:
            raise ValueError("layout figure.margins has unsupported keys")
        result["figure"]["margins"] = {key: float(value) for key, value in margins.items()}
    panels = layout.get("panels", {})
    if not isinstance(panels, dict):
        raise ValueError("layout panels must be an object keyed by stable panel IDs")
    for panel_id, state in panels.items():
        if not isinstance(panel_id, str) or not isinstance(state, dict):
            raise ValueError("each layout panel needs a string ID and object state")
        unknown = set(state) - {"axes", "xlabel", "ylabel", "title", "legend", "xlim", "ylim"}
        if unknown: raise ValueError(f"layout panel {panel_id!r} has unknown keys: {sorted(unknown)}")
        clean: dict[str, Any] = {}
        if "axes" in state: clean["axes"] = _bounds(state["axes"], f"panels.{panel_id}.axes")
        for name in ("xlabel", "ylabel", "title", "xlim", "ylim"):
            if name in state: clean[name] = _pair(state[name], f"panels.{panel_id}.{name}")
        if "legend" in state:
            legend = state["legend"]
            if not isinstance(legend, dict) or set(legend) - {"bbox", "loc"}:
                raise ValueError(f"layout panel {panel_id!r} has invalid legend state")
            clean["legend"] = {"bbox": _bounds(legend["bbox"], f"panels.{panel_id}.legend.bbox"),
                               "loc": legend.get("loc", "upper left")}
        result["panels"][panel_id] = clean
    annotations = layout.get("annotations", {})
    if not isinstance(annotations, dict): raise ValueError("layout annotations must be an object keyed by annotation ID")
    for annotation_id, state in annotations.items():
        if not isinstance(annotation_id, str) or not isinstance(state, dict):
            raise ValueError("each layout annotation needs a string ID and object state")
        if set(state) - {"panel", "coords", "xy"}: raise ValueError(f"layout annotation {annotation_id!r} has unsupported keys")
        coords = state.get("coords", "axes")
        if coords not in {"data", "axes", "figure"}: raise ValueError(f"layout annotation {annotation_id!r} has invalid coords")
        result["annotations"][annotation_id] = {"panel": str(state.get("panel", "panel-0")), "coords": coords,
                                                  "xy": _pair(state.get("xy"), f"annotations.{annotation_id}.xy")}
    return result


def load_layout(path: str | Path) -> dict[str, Any] | None:
    """Return ``None`` for an absent optional override, otherwise validate it."""
    path = Path(path)
    if not path.is_file(): return None
    try:
        return validate_layout(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Invalid layout JSON {path}: {exc}") from exc


def write_layout(path: str | Path, layout: dict[str, Any]) -> Path:
    path = Path(path)
    valid = validate_layout(layout)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(valid, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _axes_position(ax, artist) -> list[float]:
    explicit = getattr(artist, "_pypost_layout_position", None)
    if explicit is not None: return [float(explicit[0]), float(explicit[1])]
    renderer = ax.figure.canvas.get_renderer()
    box = artist.get_window_extent(renderer=renderer)
    x, y = ax.transAxes.inverted().transform((box.x0 + box.width / 2, box.y0 + box.height / 2))
    return [float(x), float(y)]


def capture_layout(fig, panels: dict[str, Any], annotations: dict[str, Any]) -> dict[str, Any]:
    """Capture visual state using stable IDs, after forcing a canvas draw."""
    fig.canvas.draw()
    result: dict[str, Any] = {"format": FORMAT, "version": VERSION, "figure": {"margins": {}}, "panels": {}, "annotations": {}}
    params = fig.subplotpars
    result["figure"]["margins"] = {key: float(getattr(params, key)) for key in ("left", "right", "bottom", "top", "wspace", "hspace")}
    for panel_id, ax in panels.items():
        state: dict[str, Any] = {"axes": [float(v) for v in ax.get_position().bounds],
                                 "xlabel": _axes_position(ax, ax.xaxis.label),
                                 "ylabel": _axes_position(ax, ax.yaxis.label),
                                 "title": _axes_position(ax, ax.title),
                                 "xlim": [float(v) for v in ax.get_xlim()], "ylim": [float(v) for v in ax.get_ylim()]}
        legend = ax.get_legend()
        if legend is not None:
            box = legend.get_window_extent(fig.canvas.get_renderer())
            p0 = ax.transAxes.inverted().transform((box.x0, box.y0))
            p1 = ax.transAxes.inverted().transform((box.x1, box.y1))
            state["legend"] = {"bbox": [float(p0[0]), float(p0[1]), float(p1[0] - p0[0]), float(p1[1] - p0[1])], "loc": "upper left"}
        result["panels"][panel_id] = state
    for annotation_id, artist in annotations.items():
        spec = getattr(artist, "_pypost_annotation", {})
        xy = artist.get_position()
        result["annotations"][annotation_id] = {"panel": spec["panel"], "coords": spec["coords"], "xy": [float(xy[0]), float(xy[1])]}
    return validate_layout(result)


def apply_layout(fig, panels: dict[str, Any], annotations: dict[str, Any], layout: dict[str, Any]) -> None:
    """Apply a validated layout; unknown panel/annotation IDs are actionable errors."""
    layout = validate_layout(layout)
    margins = layout["figure"].get("margins")
    if margins:
        fig.set_layout_engine(None)
        fig.subplots_adjust(**margins)
    for panel_id, state in layout["panels"].items():
        if panel_id not in panels: raise ValueError(f"layout refers to missing panel ID {panel_id!r}")
        ax = panels[panel_id]
        if "axes" in state: ax.set_position(state["axes"])
        if "xlabel" in state:
            ax.xaxis.set_label_coords(*state["xlabel"]); ax.xaxis.label._pypost_layout_position = state["xlabel"]
        if "ylabel" in state:
            ax.yaxis.set_label_coords(*state["ylabel"]); ax.yaxis.label._pypost_layout_position = state["ylabel"]
        if "title" in state:
            ax.title.set_position(state["title"]); ax.title._pypost_layout_position = state["title"]
        if "xlim" in state: ax.set_xlim(state["xlim"])
        if "ylim" in state: ax.set_ylim(state["ylim"])
        if "legend" in state:
            legend = ax.get_legend()
            if legend is None: raise ValueError(f"layout refers to a legend missing from {panel_id!r}")
            legend.set_bbox_to_anchor(state["legend"]["bbox"], transform=ax.transAxes)
            legend._loc = 2  # Matplotlib's public setter is unavailable across supported versions.
    for annotation_id, state in layout["annotations"].items():
        if annotation_id not in annotations: raise ValueError(f"layout refers to missing annotation ID {annotation_id!r}")
        artist = annotations[annotation_id]
        spec = getattr(artist, "_pypost_annotation")
        if state["panel"] != spec["panel"] or state["coords"] != spec["coords"]:
            raise ValueError(f"layout annotation {annotation_id!r} no longer matches its YAML panel/coords")
        artist.set_position(state["xy"])
    fig.canvas.draw_idle()
