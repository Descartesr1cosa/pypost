import numpy as np
from sciplot import Data1D


def test_openfoam_style_table_is_named_and_sorted(tmp_path):
    path = tmp_path / "line.xy"
    path.write_text("# x p Ux\n1 20 3\n0 10 2\n")
    data = Data1D.from_file(path)
    assert data.x_name == "x"
    assert list(data.fields) == ["p", "Ux"]
    assert np.allclose(data.x, [0, 1])
    assert np.allclose(data.fields["p"], [10, 20])
