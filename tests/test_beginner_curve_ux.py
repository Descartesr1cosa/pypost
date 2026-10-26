"""Regression tests for the documented no-Matplotlib 1-D workflow."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import pytest

from sciplot.cli import main
from sciplot.curve import compare


def test_demo_init_creates_editable_project_and_safe_destination(tmp_path):
    project = tmp_path / "my-plot"
    assert main(["demo", "init", "curve-comparison", "--dest", str(project)]) == 0
    assert (project / "plot.yml").is_file()
    assert not (project / "curve_comparison.yml").exists()
    with pytest.raises(FileExistsError, match="will not overwrite"):
        main(["demo", "init", "curve-comparison", "--dest", str(project)])


def test_curve_errors_explain_path_columns_yaml_and_log_data(tmp_path):
    base = {"datasets": [{"path": "missing.csv", "x": "time", "y": "Cd"}]}
    with pytest.raises(FileNotFoundError, match=r"datasets\[\].path"):
        compare(base, tmp_path)
    data = tmp_path / "data.csv"; data.write_text("time,Cd\n0,-1\n1,2\n")
    with pytest.raises(KeyError, match=r"datasets\[\].x"):
        compare({"datasets": [{"path": "data.csv", "x": "wrong", "y": "Cd"}]}, tmp_path)
    with pytest.raises(KeyError, match="Unknown top-level"):
        compare({"dataset": []}, tmp_path)
    with pytest.raises(ValueError, match="Choose symlog"):
        compare({"datasets": [{"path": "data.csv", "x": "time", "y": "Cd"}], "plot": {"axes": {"yscale": "log"}}}, tmp_path)


def test_gallery_small_configs_are_directly_runnable(tmp_path):
    from pathlib import Path
    import shutil
    source = Path(__file__).parents[1] / "sciplot" / "demos" / "curve_gallery"
    project = tmp_path / "gallery"; shutil.copytree(source, project)
    for name in ("line_scatter.yml", "uncertainty.yml", "loglog.yml", "symlog_inset.yml"):
        assert main(["curve", "compare", "--config", str(project / "panels" / name)]) == 0
    assert len(list((project / "panels").glob("panel_*.pdf"))) == 4
