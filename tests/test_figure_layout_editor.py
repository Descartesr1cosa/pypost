"""Non-desktop coverage for portable 1-D layout and annotation state."""
from __future__ import annotations

import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import numpy as np
import pytest

from sciplot.cli import main
from sciplot.curve import build_figure, compare
from sciplot.plotting import figure_editor
from sciplot.plotting.figure_editor import FigureEditor, ensure_interactive_backend
from sciplot.plotting.layout import apply_layout, capture_layout, load_layout, write_layout


def _config(output: str = "figure.png"):
    return {
        "kind": "curve",
        "datasets": [{"path": "data.csv", "x": "time", "y": "Cd", "label": "case", "style": {"color": "#0072b2"}}],
        "annotations": [{"id": "formula", "text": "$C_D=2F_D/(\\rho U^2 A)$", "coords": "axes", "xy": [0.55, 0.80], "fontsize": 10},
                        {"id": "arrow", "text": "minimum", "coords": "axes", "xy": [0.2, 0.2],
                         "arrow": {"xy": [1.0, 0.5], "coords": "data"}}],
        "plot": {"layout": {"mode": "auto", "overrides": "layout.json"}, "outputs": [output],
                 "axes": {"xlabel": "time", "ylabel": "$C_D$", "xlabelpad": 5,
                          "legend": {"loc": "upper right", "frameon": False}, "grid": {"major": {"alpha": .2}}}},
    }


def test_new_plot_cli_matches_compatible_curve_command(tmp_path):
    data = tmp_path / "data.csv"; data.write_text("time,Cd\n0,1\n1,.5\n")
    config = _config("old.pdf")
    config_path = tmp_path / "plot.yml"
    import yaml
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    assert main(["curve", "compare", "--config", str(config_path)]) == 0
    assert main(["plot", str(config_path), "--output", str(tmp_path / "new.pdf")]) == 0
    old = tmp_path / "old.pdf"; new = tmp_path / "new.pdf"
    assert old.is_file() and new.is_file() and old.stat().st_size > 100 and new.stat().st_size > 100
    _, panels, annotations, _, _ = build_figure(config, tmp_path)
    np.testing.assert_allclose(panels["panel-0"].lines[0].get_ydata(), [1, .5])
    assert set(annotations) == {"formula", "arrow"}


def test_layout_json_round_trip_only_changes_visual_state(tmp_path):
    (tmp_path / "data.csv").write_text("time,Cd\n0,1\n1,.5\n")
    renderer, panels, annotations, _, defaults = build_figure(_config(), tmp_path)
    before = panels["panel-0"].lines[0].get_ydata().copy()
    editor = FigureEditor(renderer.fig, panels, annotations, tmp_path / "layout.json", defaults)
    editor.move("panel-0:xlabel", (0.45, -0.20))
    editor.move("annotation:formula", (0.35, 0.70))
    editor.set_margins(left=.20, right=.95, bottom=.22, top=.93)
    target = editor.save()
    saved = load_layout(target)
    assert saved is not None and saved["annotations"]["formula"]["xy"] == [.35, .70]
    assert saved["panels"]["panel-0"]["xlabel"] == pytest.approx([.45, -.20])
    np.testing.assert_allclose(before, panels["panel-0"].lines[0].get_ydata())
    editor.restore_yaml_defaults()
    assert renderer.fig.get_layout_engine() is not None
    renderer2, panels2, annotations2, _, _ = build_figure(_config(), tmp_path)
    apply_layout(renderer2.fig, panels2, annotations2, saved)
    assert annotations2["formula"].get_position() == pytest.approx((.35, .70))
    np.testing.assert_allclose(before, panels2["panel-0"].lines[0].get_ydata())


def test_missing_and_invalid_layout_files_are_explicit(tmp_path):
    (tmp_path / "data.csv").write_text("time,Cd\n0,1\n1,.5\n")
    # A declared but absent optional JSON file preserves normal rendering.
    assert compare(_config(), tmp_path).is_file()
    invalid = tmp_path / "layout.json"; invalid.write_text(json.dumps({"format": "wrong", "version": 1}))
    with pytest.raises(ValueError, match="Invalid layout JSON"):
        build_figure(_config(), tmp_path)


def test_annotation_demo_exports_all_vector_and_raster_formats(tmp_path):
    root = Path(__file__).parents[1] / "sciplot" / "demos" / "curve_annotation_demo"
    import yaml
    config = yaml.safe_load((root / "annotations.yml").read_text())
    config["plot"]["outputs"] = [str(tmp_path / f"annotated.{suffix}") for suffix in ("pdf", "svg", "png")]
    renderer, panels, annotations, _, _ = build_figure(config, root)
    assert set(panels) == {"drag", "lift"}
    assert set(annotations) == {"drag_formula", "separation_note", "figure_note"}
    assert compare(config, root).is_file()
    assert all((tmp_path / f"annotated.{suffix}").is_file() for suffix in ("pdf", "svg", "png"))


def test_edit_reports_headless_requirement(tmp_path, monkeypatch):
    (tmp_path / "data.csv").write_text("time,Cd\n0,1\n")
    import yaml
    config_path = tmp_path / "plot.yml"; config_path.write_text(yaml.safe_dump(_config()))
    monkeypatch.delenv("DISPLAY", raising=False); monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    with pytest.raises(RuntimeError, match="requires a graphical desktop session"):
        main(["edit", str(config_path)])


def test_windows_selects_tk_without_x11_display(monkeypatch):
    """Windows must never depend on Linux's DISPLAY/WAYLAND variables."""
    selected = []
    monkeypatch.setattr(figure_editor, "_activate_backend", lambda matplotlib, candidate, probes: selected.append(candidate) or candidate == "TkAgg")
    assert ensure_interactive_backend(platform="win32", environ={}) == "tkagg"
    assert selected == ["TkAgg"]


def test_macos_prefers_native_backend_without_x11_display(monkeypatch):
    selected = []
    monkeypatch.setattr(figure_editor, "_activate_backend", lambda matplotlib, candidate, probes: selected.append(candidate) or candidate == "MacOSX")
    assert ensure_interactive_backend(platform="darwin", environ={}) == "macosx"
    assert selected == ["MacOSX"]


def test_linux_requires_display_before_attempting_gui_backend(monkeypatch):
    attempted = []
    monkeypatch.setattr(figure_editor, "_activate_backend", lambda *args: attempted.append(args) or True)
    with pytest.raises(RuntimeError, match="DISPLAY or WAYLAND_DISPLAY"):
        ensure_interactive_backend(platform="linux", environ={})
    assert not attempted


def test_backend_error_explains_tk_and_qt_remedies(monkeypatch):
    monkeypatch.setattr(figure_editor, "_activate_backend", lambda *args: False)
    with pytest.raises(RuntimeError, match="python -m tkinter.*PyQt6/PySide6"):
        ensure_interactive_backend(platform="win32", environ={})


def test_windows_agg_environment_never_switches_to_tk(monkeypatch):
    attempted = []
    monkeypatch.setattr(figure_editor, "_activate_backend", lambda *args: attempted.append(args) or True)
    with pytest.raises(RuntimeError, match="configured for headless Agg"):
        ensure_interactive_backend(platform="win32", environ={"MPLBACKEND": "Agg"})
    assert not attempted


def test_macos_stale_tk_backend_does_not_precede_native_backend(monkeypatch):
    import matplotlib as mpl
    monkeypatch.setattr(mpl, "get_backend", lambda: "TkAgg")
    selected = []
    monkeypatch.setattr(figure_editor, "_activate_backend", lambda matplotlib, candidate, probes: selected.append(candidate) or candidate == "MacOSX")
    assert ensure_interactive_backend(platform="darwin", environ={}) == "macosx"
    assert selected == ["MacOSX"]
