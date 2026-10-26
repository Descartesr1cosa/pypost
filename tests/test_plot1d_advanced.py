import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sciplot import Data1D, Plot1D
from sciplot.curve import compare


def test_external_axes_panels_inset_and_local_style(tmp_path):
    before = matplotlib.rcParams["figure.dpi"]
    fig, axes = plt.subplots(2, 2)
    data = Data1D.from_arrays([0, 1, 2], {"u": [1, 2, 3]})
    plot = Plot1D(ax=axes[0, 0], style="paper")
    plot.line(data, "u"); plot.panel_label("A")
    inset = plot.inset([.5, .1, "40%", "40%"]); inset.scatter(data, "u")
    assert plot.fig is fig and len(fig.axes) == 5
    assert matplotlib.rcParams["figure.dpi"] == before


def test_transforms_errorbar_and_axis_modes(tmp_path):
    plt.close("all")
    data = tmp_path / "d.csv"; data.write_text("x,y,e\n0,1,.2\n2,3,.4\n")
    output = tmp_path / "plot.png"
    config = {"datasets": [{"path": "d.csv", "x": "x", "y": "y", "kind": "errorbar", "yerr": "e", "x_scale": 2, "x_offset": 1, "y_scale": 10, "y_offset": 5}],
              "plot": {"output": str(output), "axes": {"xscale": "symlog", "xscale_kwargs": {"linthresh": 1}, "yscale": "log", "minor_ticks": True, "scientific": {"limits": [-2, 2]}}}}
    compare(config, tmp_path)
    axis = plt.gca(); line = axis.lines[0]
    assert np.allclose(line.get_xdata(), [1, 5]) and np.allclose(line.get_ydata(), [15, 35])
    assert axis.get_xscale() == "symlog" and axis.get_yscale() == "log" and output.is_file()


def test_different_curve_lengths_and_vector_exports(tmp_path):
    plt.close("all")
    (tmp_path / "a.csv").write_text("x,y\n0,0\n1,1\n")
    (tmp_path / "b.csv").write_text("x,y\n.2,2\n.8,3\n1.4,4\n")
    config = {"datasets": [{"path": "a.csv", "x": "x", "y": "y"}, {"path": "b.csv", "x": "x", "y": "y"}],
              "plot": {"outputs": [str(tmp_path / "x.pdf"), str(tmp_path / "x.svg"), str(tmp_path / "x.png")], "figure": {"size": [100, 60], "size_unit": "mm", "dpi": 144}, "axes": {"tick_params": {"direction": "in", "length": 4, "width": .8}}}}
    compare(config, tmp_path)
    assert len(plt.gca().lines) == 2
    assert all((tmp_path / f"x.{kind}").stat().st_size > 100 for kind in ("pdf", "svg", "png"))
    assert np.allclose(plt.gca().figure.get_size_inches(), [100 / 25.4, 60 / 25.4])


def test_cli_output_override_and_headless_preview(tmp_path, monkeypatch):
    import pytest
    from sciplot.cli import main
    (tmp_path / "a.csv").write_text("x,y\n0,1\n1,2\n")
    config = tmp_path / "c.yml"; config.write_text("datasets: [{path: a.csv, x: x, y: y}]\nplot: {output: original.pdf}\n")
    target = tmp_path / "override.svg"
    assert main(["curve", "compare", "--config", str(config), "--output", str(target)]) == 0
    assert target.is_file() and not (tmp_path / "original.pdf").exists()
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(RuntimeError, match="DISPLAY"):
        main(["curve", "compare", "--config", str(config), "--show"])
