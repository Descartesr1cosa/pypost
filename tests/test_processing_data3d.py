"""Analytic-field coverage for generic Data3D v1 processing."""
from __future__ import annotations

import numpy as np
import pytest

pv = pytest.importorskip("pyvista")

from sciplot import Data3D, load_dataset
from sciplot.cli import main
from sciplot.processing import SliceData, derive_field, extract_slice, sample_line


def _volume() -> Data3D:
    mesh = pv.ImageData(dimensions=(5, 5, 5), spacing=(.25, .25, .25)).cast_to_unstructured_grid()
    x, y, z = mesh.points.T
    mesh.point_data["f"] = 1 + 2 * x - 3 * y + 4 * z
    mesh.point_data["V"] = np.c_[x, y, z]
    mesh.cell_data["SourceBlockId"] = np.zeros(mesh.n_cells, dtype=np.int32)
    metadata = Data3D.standard_metadata(
        physical_time=2.0, time_unit="s", coordinate_unit="m", source={"name": "analytic", "version": "1"},
        fields={"f": {"kind": "scalar", "components": 1, "unit": "Pa", "description": "linear scalar", "provenance": "native"},
                "V": {"kind": "vector", "components": 3, "unit": "m/s", "description": "Cartesian position vector", "provenance": "native", "component_system": "Cartesian"}},
        cell_fields={"SourceBlockId": {"role": "source_block_id"}}, normalization={}, conversion={},
    )
    return Data3D(mesh, time=2.0, metadata=metadata)


def test_pointwise_algebra_does_not_mutate_volume():
    data = _volume()
    magnitude = derive_field(data, name="Vmag", operation="magnitude", field="V")
    component = derive_field(data, name="Vy", operation="component", field="V", component="y")
    doubled = derive_field(data, name="twice", operation="add", left="f", right="f")
    dot = derive_field(data, name="v2", operation="dot", left="V", right="V")
    assert "Vmag" not in data.mesh.point_data
    np.testing.assert_allclose(magnitude.values, np.linalg.norm(data.mesh.point_data["V"], axis=1))
    np.testing.assert_allclose(component.values, data.mesh.points[:, 1])
    np.testing.assert_allclose(doubled.values, 2 * data.mesh.point_data["f"])
    np.testing.assert_allclose(dot.values, magnitude.values ** 2)


def test_slice_and_line_preserve_analytic_interpolation_and_validity(tmp_path):
    data = _volume()
    mag = derive_field(data, name="Vmag", operation="magnitude", field="V")
    sliced = extract_slice(data, origin=[0, 0, .5], normal=[0, 0, 1], u_direction=[1, 0, 0], fields=["f", "V", "Vmag"], derived={"Vmag": mag})
    assert sliced.mesh.n_points and sliced.mesh.n_cells
    points = np.asarray(sliced.mesh.points)
    np.testing.assert_allclose(points[:, 2], .5, atol=1e-12)
    np.testing.assert_allclose(sliced.mesh.point_data["f"], 1 + 2 * points[:, 0] - 3 * points[:, 1] + 4 * points[:, 2], atol=1e-12)
    assert sliced.project_vector("V").shape == (sliced.mesh.n_points, 2)
    vtp = sliced.save(tmp_path / "plane.vtp")
    assert SliceData.from_file(vtp).metadata["physical_time"] == 2.0
    empty = extract_slice(data, origin=[0, 0, 2], normal=[0, 0, 1], fields=["f"])
    assert empty.mesh.n_points == 0 and empty.mesh.n_cells == 0

    line = sample_line(data, start=[-.25, .5, .5], end=[1.25, .5, .5], n_points=7, fields=["f", "V", "Vmag"], derived={"Vmag": mag})
    assert not line.sort and set(("x", "y", "z", "valid", "V_x", "V_y", "V_z")) <= set(line.fields)
    valid = line.fields["valid"].astype(bool)
    assert valid.any() and (~valid).any()
    np.testing.assert_allclose(line.fields["f"][valid], 1 + 2 * line.fields["x"][valid] - 3 * line.fields["y"][valid] + 4 * line.fields["z"][valid])
    assert np.isnan(line.fields["f"][~valid]).all()


def test_yaml_workflow_writes_reusable_slice_and_line(tmp_path):
    source = _volume(); volume = source.save_data3d_v1(tmp_path / "volume.vtu")
    config = tmp_path / "process.yml"
    config.write_text("""kind: data3d-process
input: {path: volume.vtu}
derived:
  - {name: Vmag, operation: magnitude, field: V}
slices:
  - name: xy
    origin: [0, 0, 0.5]
    normal: [0, 0, 1]
    fields: [f, Vmag]
    output: plane.vtp
lines:
  - name: diagonal
    start: [0, 0, 0]
    end: [1, 1, 1]
    n_points: 9
    fields: [f, V, Vmag]
    output: line.npz
""")
    assert main(["process", str(config)]) == 0
    outputs = {"xy": tmp_path / "plane.vtp", "diagonal": tmp_path / "line.npz"}
    assert outputs["xy"].is_file() and outputs["diagonal"].is_file()
    line = load_dataset(outputs["diagonal"])
    assert line.x_name == "s" and "V_x" in line.fields and line.metadata["operation"]["name"] == "sample_line"


def test_derived_fields_can_reference_normalization_stored_in_the_file():
    data = _volume()
    data.metadata["normalization"] = {"pressure_ref": 4.0, "physical_constants": {"mu0": 2.0}, "label": "x"}
    scaled = derive_field(data, name="f_si", operation="multiply", left="f", right="@pressure_ref")
    np.testing.assert_allclose(scaled.values, 4.0 * np.asarray(data.mesh.point_data["f"]))
    assert scaled.descriptor["unit"] == "Pa" and scaled.dependencies == ("f",)
    nested = derive_field(data, name="f_mu", operation="divide", left="f", right="@physical_constants.mu0")
    np.testing.assert_allclose(nested.values, np.asarray(data.mesh.point_data["f"]) / 2.0)
    with pytest.raises(KeyError, match="no entry"):
        derive_field(data, name="bad", operation="multiply", left="f", right="@missing_ref")
    with pytest.raises(TypeError, match="not a number"):
        derive_field(data, name="bad", operation="multiply", left="f", right="@label")


def test_slice_and_line_outputs_carry_normalization():
    data = _volume()
    data.metadata["normalization"] = {"pressure_ref": 4.0}
    assert extract_slice(data, origin=[.5, .5, .5], normal=[0, 0, 1], fields=["f"]).metadata["normalization"] == {"pressure_ref": 4.0}
    line = sample_line(data, start=[0, .5, .5], end=[1, .5, .5], n_points=3, fields=["f"])
    assert line.metadata["normalization"] == {"pressure_ref": 4.0}
