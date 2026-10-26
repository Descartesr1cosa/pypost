"""Round-trip and validation coverage for the public standard data protocol."""
from __future__ import annotations

import json

import numpy as np
import pytest

from sciplot import Data1D, Data2D, Data3D, inspect_dataset, load_dataset, save_dataset, validate_dataset
from sciplot.cli import main


def test_1d_binary_round_trip_preserves_dtype_vector_shape_metadata_and_order(tmp_path):
    original = Data1D(np.array([2, 0, 1], dtype=np.float32),
                      {"U": np.array([[2, 3], [0, 1], [1, 2]], dtype=np.float32),
                       "p": np.array([20, 0, 10], dtype=np.int16)}, x_name="time", x_unit="s",
                      field_units={"p": "Pa"}, metadata={"source": "synthetic"}, sort=False)
    target = save_dataset(original, tmp_path / "line.npz")
    restored = load_dataset(target)
    assert restored.sort is False
    assert restored.x.dtype == np.dtype("float32") and restored.fields["U"].shape == (3, 2)
    assert restored.fields["p"].dtype == np.dtype("int16")
    np.testing.assert_array_equal(restored.x, original.x)
    np.testing.assert_array_equal(restored.fields["U"], original.fields["U"])
    assert restored.metadata == original.metadata and restored.field_units == {"p": "Pa"}
    report = inspect_dataset(target)
    assert report["encoding"] == "binary" and report["fields"][0]["components"] == 2


def test_1d_ascii_round_trip_and_vector_csv_rejection(tmp_path):
    data = Data1D.from_arrays([0., 1.], {"Cd": [.6, .5]}, x_name="time", x_unit="s", metadata={"case": "ascii"})
    target = save_dataset(data, tmp_path / "line.csv", encoding="ascii")
    restored = load_dataset(target)
    np.testing.assert_allclose(restored.fields["Cd"], data.fields["Cd"])
    assert restored.x_unit == "s"
    assert json.loads(target.with_suffix(".csv.json").read_text())["encoding"] == "ascii"
    vector = Data1D.from_arrays([0, 1], {"U": [[1, 2], [3, 4]]})
    with pytest.raises(ValueError, match="scalar 1-D"):
        save_dataset(vector, tmp_path / "vector.csv", encoding="ascii")


def test_standard_1d_npz_is_usable_by_existing_yaml_plot_cli(tmp_path):
    data = Data1D(np.array([0., 1.], dtype=np.float32), {"Cd": np.array([.6, .5], dtype=np.float32)}, x_name="time", sort=False)
    save_dataset(data, tmp_path / "line.npz")
    config = tmp_path / "plot.yml"
    config.write_text("datasets:\n  - {path: line.npz, x: time, y: Cd}\nplot:\n  outputs: [line.pdf]\n  axes: {xlabel: time, ylabel: Cd}\n")
    assert main(["plot", str(config)]) == 0
    assert (tmp_path / "line.pdf").is_file()


def test_2d_npz_round_trip_preserves_connectivity_and_locations(tmp_path):
    points = np.array([[0., 0.], [1., 0.], [0., 1.]], dtype=np.float32)
    data = Data2D(points, {"p": np.array([1, 2, 3], dtype=np.float32)}, np.array([[1 / 3, 1 / 3]], dtype=np.float32),
                  {"tau": np.array([[1., 2.]], dtype=np.float32)}, {"plane": {"origin": [0, 0, 0], "basis_u": [1, 0, 0], "basis_v": [0, 1, 0]}},
                  connectivity=np.array([3, 0, 1, 2]), cell_types=np.array([5], dtype=np.uint8))
    target = save_dataset(data, tmp_path / "slice.npz")
    restored = load_dataset(target)
    np.testing.assert_array_equal(restored.connectivity, [3, 0, 1, 2])
    assert restored.cell_fields["tau"].shape == (1, 2)
    result = validate_dataset(target, deep=True)
    assert result["valid"] and result["report"]["topology"]["connectivity"]
    assert result["checksums"]["sha256"]


def test_2d_vtk_ascii_preserves_connectivity_when_mesh_storage_is_requested(tmp_path):
    data = Data2D(np.array([[0., 0.], [1., 0.], [0., 1.]]), {"p": [1., 2., 3.]},
                  np.array([[1 / 3, 1 / 3]]), {"tau": [4.]}, connectivity=np.array([3, 0, 1, 2]))
    target = save_dataset(data, tmp_path / "slice.vtu", encoding="ascii")
    restored = load_dataset(target)
    np.testing.assert_array_equal(restored.connectivity, [3, 0, 1, 2])
    assert inspect_dataset(target)["encoding"] == "ascii"


pv = pytest.importorskip("pyvista")


def test_3d_point_cell_and_multiblock_dependency_reports(tmp_path):
    mesh = pv.ImageData(dimensions=(3, 3, 3))
    mesh.point_data["p"] = np.arange(mesh.n_points, dtype=np.float32)
    mesh.cell_data["U"] = np.ones((mesh.n_cells, 3), dtype=np.float32)
    binary = save_dataset(Data3D(mesh, metadata={"case": "tiny"}), tmp_path / "volume.vti")
    ascii_target = save_dataset(Data3D(mesh), tmp_path / "volume_ascii.vti", encoding="ascii")
    assert load_dataset(binary).location_of("p") == "point"
    report = inspect_dataset(ascii_target)
    assert report["encoding"] == "ascii"
    assert {(field["name"], field["location"]) for field in report["fields"]} >= {("p", "point"), ("U", "cell")}
    blocks = pv.MultiBlock(); blocks["internalMesh"] = mesh
    target = save_dataset(Data3D(blocks), tmp_path / "case.vtm")
    result = validate_dataset(target, deep=True)
    assert result["valid"] and len(result["report"]["dependencies"]) >= 2


def test_corrupt_or_invalid_data_reports_specific_failure_and_cli(tmp_path, capsys):
    broken = tmp_path / "broken.npz"; broken.write_bytes(b"not an npz archive")
    result = validate_dataset(broken)
    assert not result["valid"] and result["issues"]
    missing = tmp_path / "missing-field.npz"
    np.savez_compressed(missing, __pypost_header__=json.dumps({"format": "pypost-dataset", "format_version": 1, "dimension": "1d", "encoding": "binary",
                                                                 "coordinate": {"name": "time"}}),
                        x=np.array([0., 1.]), field_names=np.array(["Cd"]))
    result = validate_dataset(missing)
    assert not result["valid"] and "field__Cd" in result["issues"][0]
    data = Data1D.from_arrays([0, 1], {"p": [1, 2]})
    target = save_dataset(data, tmp_path / "valid.npz")
    assert main(["validate", str(target), "--deep"]) == 0
    output = capsys.readouterr().out
    assert '"valid": true' in output and "sha256" in output
    inf = Data1D.from_arrays([0, 1], {"p": [1., np.inf]})
    with pytest.raises(ValueError, match="rejects Inf"):
        save_dataset(inf, tmp_path / "inf.npz")
