"""Small, dependency-free-from-Mercury coverage for the streamed VTU writer."""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("pyvista")

from examples.converters.mercury.streaming import write_vtu

from sciplot import Data3D, validate_dataset


def _map(path, dtype, shape, values):
    result = np.memmap(path, dtype=dtype, mode="w+", shape=shape)
    result[...] = values
    return result


def test_appended_raw_writer_round_trips_self_contained_data3d_v1(tmp_path):
    points = _map(tmp_path / "points", "float64", (4, 3), [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]])
    scalar = _map(tmp_path / "p", "float64", 4, [1, 2, 3, 4])
    cells = _map(tmp_path / "cells", "int64", 4, [0, 1, 2, 3])
    offsets = _map(tmp_path / "offsets", "int64", 1, [4])
    types = _map(tmp_path / "types", "uint8", 1, [10])
    block = _map(tmp_path / "block", "int64", 1, [7])
    metadata = Data3D.standard_metadata(
        physical_time=1.0, time_unit="s", coordinate_unit="m", source={"name": "test", "version": "1"},
        fields={"p": {"kind": "scalar", "components": 1, "unit": "Pa", "description": "pressure", "provenance": "native"}},
        cell_fields={"SourceBlockId": {"role": "source_block_id"}}, normalization={}, conversion={},
    )
    output = tmp_path / "streamed.vtu"
    write_vtu(output, metadata=metadata, points=points, fields={"p": scalar}, cells=cells, offsets=offsets, types=types,
              cell_data={"SourceBlockId": block})
    restored = Data3D.from_file(output)
    assert restored.is_data3d_v1 and restored.mesh.n_points == 4 and restored.mesh.n_cells == 1
    assert validate_dataset(output, deep=True)["valid"]
