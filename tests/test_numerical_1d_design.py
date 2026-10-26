"""Numerical-only publication configuration coverage for the redesigned 1-D UI."""
from __future__ import annotations

import json
import matplotlib
matplotlib.use("Agg")
import numpy as np
import pytest

from sciplot.cli import main
from sciplot.curve import build_figure, check_figure, compare
from sciplot.plotting.paper1d import apply_layout, figure_size, profile_files, publication_report


def _minimal(tmp_path, extra=""):
    (tmp_path / "force.csv").write_text("time,Cd,Cl\n0,0.3,0.1\n1,0.4,0.2\n2,0.35,0.15\n")
    path = tmp_path / "plot.yml"
    path.write_text("kind: curve\ndatasets:\n  - {path: force.csv, x: time, y: Cd, label: '$C_D$'}\naxes:\n  xlabel: '$t$ [s]'\n  ylabel: Coefficient\n  xlim: [0, 2]\nplot:\n  outputs: [figure.pdf, figure.svg, figure.png]\n" + extra)
    return path


def test_minimal_plot_uses_paper_profile_and_stable_auto_cycle(tmp_path):
    path = _minimal(tmp_path)
    assert main(["plot", str(path)]) == 0
    assert all((tmp_path / f"figure.{suffix}").is_file() for suffix in ("pdf", "svg", "png"))
    config = __import__("sciplot.workflow", fromlist=["read_yaml"]).read_yaml(path)
    config["datasets"].append({"path": "force.csv", "x": "time", "y": "Cl", "label": "Cl"})
    renderer, panels, *_ = build_figure(config, tmp_path)
    lines = panels["panel-0"].lines
    assert [line.get_color() for line in lines] == ["#0072B2", "#D55E00"]
    assert tuple(panels["panel-0"].get_xlim()) == (0, 2)  # explicit physics range is never expanded
    assert renderer._pypost_font_info["actual"]


def test_percent_layout_and_physical_figure_size(tmp_path):
    _, layout = profile_files()
    layout.update({"mode": "fixed", "figure": {"width": 180, "height": 90, "unit": "mm"},
                   "margins": {"unit": "percent", "left": 10, "right": 5, "bottom": 20, "top": 8, "wspace": 0, "hspace": 0}})
    assert figure_size(layout)[:2] == pytest.approx((180 / 25.4, 90 / 25.4))
    path = _minimal(tmp_path, "  layout_file: layout.yml\n")
    import yaml
    (tmp_path / "layout.yml").write_text(yaml.safe_dump(layout))
    renderer, panels, *_ = build_figure(__import__("sciplot.workflow", fromlist=["read_yaml"]).read_yaml(path), tmp_path)
    assert renderer.fig.get_size_inches() == pytest.approx((180 / 25.4, 90 / 25.4))
    bounds = panels["panel-0"].get_position().bounds
    assert bounds[0] == pytest.approx(.10) and bounds[1] == pytest.approx(.20)


def test_publication_scale_auto_warn_error_and_cli_report(tmp_path):
    path = _minimal(tmp_path, "  publication: {scale: 0.5, min_text_pt: 8, font_policy: auto, report: publication-report.json}\n")
    config = __import__("sciplot.workflow", fromlist=["read_yaml"]).read_yaml(path)
    assert compare(config, tmp_path).is_file()
    report = json.loads((tmp_path / "publication-report.json").read_text())
    assert report["overall"] == "PASS" and all(row["final_pt"] >= 8 for row in report["objects"])
    assert main(["check-figure", str(path), "--report", "checked.json"]) == 0
    assert (tmp_path / "checked.json").is_file()
    config["plot"]["publication"] = {"scale": .5, "min_text_pt": 50, "font_policy": "error"}
    with pytest.raises(ValueError, match="Publication font check failed"):
        build_figure(config, tmp_path)


def test_profile_exports_are_human_readable_and_standard_npz_plots(tmp_path):
    assert main(["style", "export", "paper-1d", "--out", str(tmp_path / "style.yml")]) == 0
    assert main(["layout", "export", "paper-1d", "--out", str(tmp_path / "layout.yml")]) == 0
    assert "colors:" in (tmp_path / "style.yml").read_text()
    assert "margins:" in (tmp_path / "layout.yml").read_text()


def test_explicit_ticks_are_not_replaced_by_nice_locator(tmp_path):
    path = _minimal(tmp_path, "axes:\n  xlim: [0, 2]\n  xticks: [0, 0.7, 2]\n  yticks: [0.3, 0.4]\n")
    # Replace the default axes mapping rather than relying on duplicate YAML keys.
    path.write_text("kind: curve\ndatasets:\n  - {path: force.csv, x: time, y: Cd}\naxes: {xlabel: t, ylabel: Cd, xlim: [0, 2], xticks: [0, 0.7, 2], yticks: [0.3, 0.4]}\nplot: {outputs: [figure.png]}\n")
    config = __import__("sciplot.workflow", fromlist=["read_yaml"]).read_yaml(path)
    _, panels, *_ = build_figure(config, tmp_path)
    np.testing.assert_allclose(panels["panel-0"].get_xticks(), [0, .7, 2])
    np.testing.assert_allclose(panels["panel-0"].get_yticks(), [.3, .4])
    np.testing.assert_allclose(panels["panel-0"].get_xlim(), [0, 2])
