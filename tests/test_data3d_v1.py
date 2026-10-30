"""Contract tests for the self-contained Data3D v1 `.vtu` protocol."""
from __future__ import annotations

import numpy as np
import pytest

pv = pytest.importorskip("pyvista")

from sciplot import Data3D, inspect_dataset, save_dataset, validate_dataset
from sciplot.data.data3d_protocol import METADATA_ARRAY, metadata_from_mesh


def _volume() -> Data3D:
    # A tetrahedron avoids structured-grid assumptions and exercises true FE
    # connectivity, PointData and mandatory block provenance.
    mesh = pv.UnstructuredGrid(
        np.asarray([4, 0, 1, 2, 3]), np.asarray([pv.CellType.TETRA], dtype=np.uint8),
        np.asarray([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]], dtype=np.float64),
    )
    mesh.point_data["p"] = np.asarray([1., 2., 3., 4.])
    mesh.point_data["B"] = np.asarray([[1., 0., 0.]] * 4)
    mesh.cell_data["SourceBlockId"] = np.asarray([17], dtype=np.int32)
    metadata = Data3D.standard_metadata(
        physical_time=12.5, time_unit="s", coordinate_unit="m",
        source={"name": "synthetic-converter", "version": "test"},
        fields={
            "p": {"kind": "scalar", "components": 1, "unit": "Pa", "provenance": "native", "description": "pressure"},
            "B": {"kind": "vector", "components": 3, "unit": "T", "provenance": "reconstructed",
                  "component_system": "Cartesian", "description": "magnetic field"},
        },
        cell_fields={"SourceBlockId": {"role": "source_block_id"}},
        normalization={"length_ref": {"value": 1.0, "unit": "m"}},
        conversion={"global_unique_nodes": 4, "merged_interface_aliases": 0},
    )
    return Data3D(mesh, source="synthetic", time=12.5, metadata=metadata)


@pytest.mark.parametrize("binary", [True, False])
def test_data3d_v1_round_trips_embedded_metadata_without_sidecar(tmp_path, binary):
    target = _volume().save_data3d_v1(tmp_path / "case.vtu", binary=binary)
    assert target.exists()
    assert not target.with_suffix(".vtu.pypost.json").exists()
    restored = Data3D.from_file(target)
    assert restored.is_data3d_v1 and restored.time == 12.5
    assert restored.metadata["coordinates"]["unit"] == "m"
    assert restored.field_info[0].shape[0] == restored.mesh.n_points
    result = validate_dataset(target, deep=True)
    assert result["valid"], result["issues"]
    assert result["checksums"]["sha256"]
    report = inspect_dataset(target)
    assert report["physical_time"] == 12.5
    assert next(x for x in report["fields"] if x["name"] == "B")["unit"] == "T"


def test_save_dataset_preserves_v1_as_single_file(tmp_path):
    target = save_dataset(_volume(), tmp_path / "case.vtu")
    assert target.exists() and not target.with_suffix(".vtu.pypost.json").exists()
    assert metadata_from_mesh(pv.read(target))["format_version"] == 1


def test_validator_rejects_missing_provenance_or_degenerate_cell(tmp_path):
    data = _volume()
    bad_metadata = dict(data.metadata)
    bad_metadata["node_identity"] = {"contract": "coordinate_deduplicated"}
    bad = Data3D(data.mesh, metadata=bad_metadata)
    with pytest.raises(ValueError, match="global_unique"):
        bad.save_data3d_v1(tmp_path / "bad.vtu")

    # Directly saved malformed VTK must also be rejected by the independent
    # reader/validator, not merely blocked by the writer.
    mesh = data.mesh.copy(deep=True)
    mesh.field_data[METADATA_ARRAY] = np.frombuffer(
        b'{"format":"pypost-data3d","format_version":1}', dtype=np.uint8
    ).copy()
    malformed = tmp_path / "malformed.vtu"
    mesh.save(malformed)
    result = validate_dataset(malformed)
    assert not result["valid"]
    assert any("missing required keys" in issue for issue in result["issues"])
