import numpy as np
from sciplot import Data2D


def test_non_regular_points_and_line_sampling():
    points = np.array([[0, 0], [1, 0], [0, 1], [1, 1], [.3, .6]])
    data = Data2D.from_arrays(points, {"f": points[:, 0] + 2 * points[:, 1]})
    distance, values = data.sample_line("f", (0, 0), (1, 1), n=7)
    assert distance.shape == values.shape == (7,)
    assert np.allclose(values, np.linspace(0, 3, 7))


def test_cell_and_point_fields_stay_distinct():
    data = Data2D(np.array([[0., 0.], [1., 0.]]), {"point_f": [1, 2]},
                  np.array([[.5, .2]]), {"cell_f": [9]})
    assert data.field("point_f")[2] == "point"
    assert data.field("cell_f")[2] == "cell"
