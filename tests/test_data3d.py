import pytest
pv = pytest.importorskip("pyvista")
from sciplot import Data3D


def test_point_and_cell_data_have_separate_locations(tmp_path):
    mesh = pv.ImageData(dimensions=(3, 3, 3))
    mesh.point_data["point_p"] = range(mesh.n_points)
    mesh.cell_data["cell_p"] = range(mesh.n_cells)
    data = Data3D(mesh)
    assert data.location_of("point_p") == "point"
    assert data.location_of("cell_p") == "cell"
    target = tmp_path / "mesh.vti"
    data.save(target)
    assert target.exists()
