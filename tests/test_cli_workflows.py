import json
import os
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from sciplot import Data1D
from sciplot import Data3D
from sciplot.inspect import inspect_path
from sciplot.provenance import vtk_dependency_signature
from sciplot.q import apply_camera, batch, camera_from_file, extract, load_config, render_fingerprint, save_camera, select_dataset


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
    assert record["velocity_input_location"] == "point"
    assert record["velocity_cell_to_point"] is False
    assert record["gradient_algorithm"] == "vtk.compute_derivative(qcriterion)"


def test_q_record_marks_cell_velocity_interpolation(tmp_path):
    mesh = pv.ImageData(dimensions=(6, 6, 6), spacing=(.2, .2, .2))
    x, y, z = mesh.cell_centers().points.T
    mesh.cell_data["U"] = np.c_[-y * (1 + z), x * (1 + z), np.zeros_like(z)]
    point_mesh = mesh.cell_data_to_point_data(pass_cell_data=True)
    probe = point_mesh.compute_derivative(scalars="U", gradient=False, qcriterion="Q", preference="point")
    values = np.asarray(probe.point_data["Q"])
    source = tmp_path / "cell_velocity.vti"; mesh.save(source)
    config = {"input": {"path": str(source)}, "processing": {"velocity_field": "U", "velocity_location": "cell", "q_field": "Q", "iso": float((values.min() + values.max()) / 2)},
              "output": {"surface": str(tmp_path / "cell_velocity.vtp")}}
    extract(config)
    record = json.loads((tmp_path / "cell_velocity.vtp.pypost.json").read_text())
    assert record["velocity_input_location"] == "cell"
    assert record["velocity_cell_to_point"] is True


def test_q_for_rigid_rotation_matches_analytic_q_one():
    mesh = pv.ImageData(dimensions=(5, 5, 5), spacing=(.25, .25, .25))
    x, y, z = mesh.points.T
    mesh.point_data["U"] = np.c_[-y, x, np.zeros_like(z)]  # omega = 1
    q = mesh.compute_derivative(scalars="U", gradient=False, qcriterion="Q", preference="point").point_data["Q"]
    assert np.allclose(q, 1.0, atol=1e-12)


def test_multiblock_requires_internal_mesh_or_explicit_selector(tmp_path):
    internal = pv.ImageData(dimensions=(5, 5, 5), spacing=(.25, .25, .25))
    internal.point_data["Q"] = np.sum((internal.points - .5) ** 2, axis=1)
    boundary = pv.Sphere(); boundary.point_data["Q"] = np.zeros(boundary.n_points)
    blocks = pv.MultiBlock(); blocks["boundaryPatch"] = boundary; blocks["internalMesh"] = internal
    assert select_dataset(blocks) is internal
    assert select_dataset(blocks, "boundaryPatch") is boundary
    path = tmp_path / "case.vtm"; blocks.save(path)
    config = {"input": {"path": str(path), "block": "internalMesh"}, "processing": {"q_field": "Q", "location": "point", "iso": .2},
              "output": {"surface": str(tmp_path / "surface.vtp")}}
    assert extract(config).is_file()
    assert len(vtk_dependency_signature(path)["dependencies"]) >= 2


def test_q_extract_resolves_standard_time_index(tmp_path):
    mesh = pv.ImageData(dimensions=(5, 5, 5), spacing=(.25, .25, .25))
    mesh.point_data["Q"] = np.sum((mesh.points - .5) ** 2, axis=1)
    source = tmp_path / "step.vti"; mesh.save(source)
    index = tmp_path / "times.json"; Data3D.save_time_index(index, [{"time": 2.5, "path": "step.vti"}])
    config = {"input": {"time_index": str(index)}, "processing": {"q_field": "Q", "location": "point", "iso": .2},
              "output": {"surface": str(tmp_path / "surface_{time:.1f}.vtp")}}
    output = extract(config, time=2.5)
    assert output.name == "surface_2.5.vtp" and output.is_file()


def test_q_config_can_use_existing_surface(tmp_path):
    sample = tmp_path / "surface.vtp"
    pv.Sphere().save(sample)
    config = tmp_path / "q.yml"
    config.write_text(f"input: {{surface: '{sample}'}}\nscene: {{color_field: Normals}}\n")
    assert load_config(config)["input"]["surface"] == str(sample)


def test_batch_dry_run_does_not_spawn_or_write(tmp_path, capsys):
    config_path = tmp_path / "q.yml"
    config = {"times": [1.0, 2.0], "input": {"surface": "sample.vtp"}, "output": {"image": "q_{time}.png"}, "batch": {"manifest": "manifest.json"}}
    assert batch(config_path, config, tmp_path, resume=True, dry_run=True) == []
    assert "sciplot.cli q render" in capsys.readouterr().out
    assert not (tmp_path / "manifest.json").exists()


def test_batch_rejects_overwriting_time_outputs(tmp_path):
    config = {"times": [1.0, 2.0], "input": {"surface": "sample.vtp"}, "output": {"image": "same.png"}}
    with pytest.raises(ValueError, match="not unique"):
        batch(tmp_path / "q.yml", config, tmp_path, resume=True, dry_run=True)


def test_3d_time_index_keeps_explicit_sorted_times(tmp_path):
    path = tmp_path / "times.json"
    Data3D.save_time_index(path, [{"time": 2, "path": "two.vtu"}, {"time": 1, "path": "one.vtu"}])
    assert [step["time"] for step in Data3D.load_time_index(path)["steps"]] == [1.0, 2.0]


def test_time_index_paths_remain_valid_after_moving_directory(tmp_path):
    original = tmp_path / "original"; original.mkdir()
    mesh = pv.ImageData(dimensions=(3, 3, 3)); mesh.point_data["Q"] = np.arange(mesh.n_points)
    volume = original / "step.vti"; mesh.save(volume)
    index = original / "times.json"; Data3D.save_time_index(index, [{"time": 1.0, "path": volume}])
    assert Data3D.load_time_index(index)["steps"][0]["path"] == "step.vti"
    moved = tmp_path / "moved"; original.rename(moved)
    config = {"input": {"time_index": str(moved / "times.json")}, "processing": {"q_field": "Q", "location": "point", "iso": 5},
              "output": {"surface": str(moved / "surface.vtp")}}
    assert extract(config, time=1.0).is_file()


def test_convert_series_forwards_each_item_time(monkeypatch, tmp_path):
    from sciplot import cli
    seen = []
    class FakeData:
        metadata = {}
    monkeypatch.setattr(cli, "load_data", lambda spec: seen.append(dict(spec)) or FakeData())
    monkeypatch.setattr(cli, "save_data", lambda data, path: None)
    config = tmp_path / "series.yml"
    config.write_text("input: {dimension: 3}\nseries:\n  - time: 1.0\n    input: {path: same.foam}\n    output: one.vtu\n  - time: 2.0\n    input: {path: same.foam}\n    output: two.vtu\noutput: {index: times.json}\n")
    assert cli.main(["convert", "--config", str(config)]) == 0
    assert [spec["time"] for spec in seen] == [1.0, 2.0]
    assert all(spec["path"].name == "same.foam" for spec in seen)


def test_openfoam_reader_receives_requested_time(monkeypatch, tmp_path):
    import pyvista as pv
    received = []
    class FakeReader:
        time_values = [1.0, 2.0]
        def __init__(self, path): self.path = path
        def set_active_time_value(self, value): received.append(value)
        def read(self): return pv.MultiBlock()
    monkeypatch.setattr(pv, "OpenFOAMReader", FakeReader)
    marker = tmp_path / "same.foam"; marker.touch()
    Data3D.from_file(marker, time=1.0)
    Data3D.from_file(marker, time=2.0)
    assert received == [1.0, 2.0]


def test_camera_json_round_trip(tmp_path):
    camera = SimpleNamespace(position=(1, 2, 3), focal_point=(0, 0, 0), up=(0, 0, 1), parallel_projection=True,
                             parallel_scale=3.5, view_angle=30.0)
    plotter = SimpleNamespace(camera=camera)
    target = save_camera(plotter, tmp_path / "camera.json")
    loaded = camera_from_file(target)
    recipient = SimpleNamespace(camera=SimpleNamespace(), camera_position=None, reset_camera_clipping_range=lambda: None)
    apply_camera(recipient, loaded)
    assert recipient.camera_position == [[1.0, 2.0, 3.0], [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]]


def test_render_fingerprint_changes_for_scene_or_camera(tmp_path):
    surface = tmp_path / "surface.vtp"; pv.Sphere().save(surface)
    camera = tmp_path / "camera.json"; camera.write_text(json.dumps({"position": [1, 1, 1]}))
    initial = render_fingerprint(surface, camera, {"colormap": "viridis"}, 1.0)
    assert initial != render_fingerprint(surface, camera, {"colormap": "coolwarm"}, 1.0)
    camera.write_text(json.dumps({"position": [2, 1, 1]}))
    assert initial != render_fingerprint(surface, camera, {"colormap": "viridis"}, 1.0)
