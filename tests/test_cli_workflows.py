import json
import subprocess
import sys

import numpy as np
import pytest

from sciplot import Data1D
from sciplot import Data3D
from sciplot.inspect import inspect_path
from sciplot.q import batch, extract, load_config


def test_normalized_csv_round_trips_metadata(tmp_path):
    target = tmp_path / "curve.csv"
    Data1D.from_arrays([0, 1], {"p": [3, 4]}, x_name="s", x_unit="m",
                       field_units={"p": "Pa"}, metadata={"case": "tiny"}).save_csv(target)
    reread = Data1D.from_file(target)
    assert reread.x_name == "s"
    assert reread.field_units == {"p": "Pa"}
    assert reread.metadata["case"] == "tiny"
    assert "rows: 2" in inspect_path(target)


def test_convert_cli_writes_standard_metadata(tmp_path):
    raw = tmp_path / "raw.xy"; raw.write_text("# s u\n0 1\n1 2\n")
    config = tmp_path / "convert.yml"
    config.write_text("input: {dimension: 1, path: raw.xy}\noutput: {path: standard.csv}\n")
    root = __import__("pathlib").Path(__file__).parents[1]
    subprocess.run([sys.executable, "-m", "sciplot.cli", "convert", "--config", str(config)], cwd=root, check=True)
    record = json.loads((tmp_path / "standard.csv.json").read_text())
    assert record["metadata"]["internal_format_version"] == 1
    assert record["metadata"]["raw_source"].endswith("raw.xy")


pv = pytest.importorskip("pyvista")


def test_q_extract_cache_invalidation_and_input_q(tmp_path):
    mesh = pv.ImageData(dimensions=(5, 5, 5), spacing=(.25, .25, .25))
    points = mesh.points
    mesh.point_data["Q"] = np.sum((points - .5) ** 2, axis=1)
    source = tmp_path / "volume.vti"; mesh.save(source)
    config = {"input": {"path": str(source)}, "processing": {"q_field": "Q", "location": "point", "iso": .2},
              "output": {"surface": str(tmp_path / "surface.vtp")}}
    first = extract(config)
    initial = json.loads((tmp_path / "surface.vtp.pypost.json").read_text())["fingerprint"]
    assert first.exists() and pv.read(first).n_points > 0
    assert extract(config) == first
    config["processing"]["iso"] = .15
    extract(config)
    changed = json.loads((tmp_path / "surface.vtp.pypost.json").read_text())["fingerprint"]
    assert changed != initial


def test_q_extract_can_compute_vtk_q_from_synthetic_velocity(tmp_path):
    mesh = pv.ImageData(dimensions=(6, 6, 6), spacing=(.2, .2, .2))
    x, y, z = mesh.points.T
    # Smooth non-uniform rotational field gives a non-constant VTK Q field.
    mesh.point_data["U"] = np.c_[-y * (1 + z), x * (1 + z), np.zeros_like(z)]
    probe = mesh.compute_derivative(scalars="U", gradient=False, qcriterion="Q", preference="point")
    q = np.asarray(probe.point_data["Q"])
    source = tmp_path / "synthetic.vti"; mesh.save(source)
    config = {"input": {"path": str(source)}, "processing": {"velocity_field": "U", "velocity_location": "point", "q_field": "Q", "iso": float((q.min() + q.max()) / 2)},
              "output": {"surface": str(tmp_path / "computed.vtp")}}
    result = extract(config)
    record = json.loads((tmp_path / "computed.vtp.pypost.json").read_text())
    assert pv.read(result).n_points > 0
    assert record["algorithm"].startswith("vtk.compute_derivative")


def test_q_config_can_use_existing_surface(tmp_path):
    sample = tmp_path / "surface.vtp"
    pv.Sphere().save(sample)
    config = tmp_path / "q.yml"
    config.write_text(f"input: {{surface: '{sample}'}}\nscene: {{color_field: Normals}}\n")
    assert load_config(config)["input"]["surface"] == str(sample)


def test_batch_dry_run_does_not_spawn_or_write(tmp_path, capsys):
    config_path = tmp_path / "q.yml"
    config = {"times": [1.0, 2.0], "input": {"surface": "sample.vtp"}, "batch": {"manifest": "manifest.json"}}
    assert batch(config_path, config, tmp_path, resume=True, dry_run=True) == []
    assert "sciplot.cli q render" in capsys.readouterr().out
    assert not (tmp_path / "manifest.json").exists()


def test_3d_time_index_keeps_explicit_sorted_times(tmp_path):
    path = tmp_path / "times.json"
    Data3D.save_time_index(path, [{"time": 2, "path": "two.vtu"}, {"time": 1, "path": "one.vtu"}])
    assert [step["time"] for step in Data3D.load_time_index(path)["steps"]] == [1.0, 2.0]
