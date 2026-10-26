"""Acceptance check for the ordinary wheel, not only editable installs."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import zipfile
import yaml


def test_wheel_contains_cli_and_bundled_demos(tmp_path):
    root = Path(__file__).parents[1]
    wheel_dir = tmp_path / "wheel"
    # Keep build isolation enabled: this is the same PEP 517 path used by a
    # new user and ensures build-system requirements are actually honoured.
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", ".", "-w", wheel_dir], cwd=root, check=True)
    wheel = next(wheel_dir.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    assert any(name.endswith("sciplot/demos/curve_demo/curve_comparison.yml") for name in names)
    assert any(name.endswith("sciplot/demos/curve_gallery/gallery.yml") for name in names)
    assert any(name.endswith("sciplot/demos/curve_gallery/panels/loglog.yml") for name in names)
    assert any(name.endswith("sciplot/demos/cfd_curve_demo/workflow.yml") for name in names)
    assert any(name.endswith("sciplot/demos/q_demo/Q_sample.vtp") for name in names)
    assert any(name.endswith("entry_points.txt") for name in names)
    target = tmp_path / "installed"
    # --target keeps the project test interpreter's editable installation
    # intact while exercising the wheel's installed package resources.
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--target", target, wheel], check=True)
    env = dict(os.environ, PYTHONPATH=str(target))
    result = subprocess.run([sys.executable, "-m", "sciplot.cli", "demo", "list"], env=env, text=True, capture_output=True, check=True)
    assert "curve-comparison" in result.stdout and "q-surface" in result.stdout
    subprocess.run([sys.executable, "-m", "sciplot.cli", "demo", "run", "curve-comparison"], cwd=tmp_path, env=env, check=True)
    assert (tmp_path / "pypost-demo-output" / "curve_comparison.pdf").is_file()
    assert (tmp_path / "pypost-demo-output" / "curve_comparison.svg").is_file()
    subprocess.run([sys.executable, "-m", "sciplot.cli", "demo", "run", "curve-gallery"], cwd=tmp_path, env=env, check=True)
    subprocess.run([sys.executable, "-m", "sciplot.cli", "demo", "run", "cfd-curve-workflow"], cwd=tmp_path, env=env, check=True)
    assert (tmp_path / "pypost-demo-output" / "curve_gallery.png").is_file()
    assert (tmp_path / "pypost-demo-output" / "cfd-curve-workflow" / "cfd_coefficients.svg").is_file()

    # A normal wheel user starts in an arbitrary writable directory.  Exercise
    # the documented copy/edit/run loop rather than package-owned resources.
    project = tmp_path / "my-plot"
    subprocess.run([sys.executable, "-m", "sciplot.cli", "demo", "init", "curve-comparison", "--dest", str(project)], env=env, check=True)
    assert (project / "plot.yml").is_file()
    (project / "replacement.csv").write_text("step,drag\n0,0.7\n1,0.5\n")
    config = yaml.safe_load((project / "plot.yml").read_text())
    config["datasets"] = [{"path": "replacement.csv", "x": "step", "y": "drag", "label": "replacement",
                           "style": {"color": "#009e73", "linestyle": "--"}}]
    config["plot"]["axes"].update({"xlim": [0, 1], "ylim": [0.4, 0.8], "legend": {"loc": "upper right", "frameon": False}})
    config["plot"]["outputs"] = ["edited.pdf", "edited.svg", "edited.png"]
    (project / "plot.yml").write_text(yaml.safe_dump(config, sort_keys=False))
    subprocess.run([sys.executable, "-m", "sciplot.cli", "curve", "compare", "--config", str(project / "plot.yml")], cwd=tmp_path, env=env, check=True)
    assert all((project / f"edited.{suffix}").is_file() for suffix in ("pdf", "svg", "png"))

    cfd_project = tmp_path / "cfd-plot"
    subprocess.run([sys.executable, "-m", "sciplot.cli", "demo", "init", "cfd-curve-workflow", "--dest", str(cfd_project)], env=env, check=True)
    for config_name in ("convert_case_a.yml", "convert_case_b.yml"):
        subprocess.run([sys.executable, "-m", "sciplot.cli", "convert", "--config", str(cfd_project / config_name)], cwd=tmp_path, env=env, check=True)
    subprocess.run([sys.executable, "-m", "sciplot.cli", "curve", "compare", "--config", str(cfd_project / "compare.yml")], cwd=tmp_path, env=env, check=True)
    assert (cfd_project / "standardized" / "case_a.csv").is_file()
    assert (cfd_project / "cfd_coefficients.pdf").is_file()
