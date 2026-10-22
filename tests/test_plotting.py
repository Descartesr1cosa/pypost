import matplotlib
matplotlib.use("Agg")
import numpy as np
from sciplot import Data1D, Data2D, Plot1D, Plot2D


def test_1d_and_2d_images_are_written(tmp_path):
    p1 = Plot1D(); p1.line(Data1D.from_arrays([0, 1], {"u": [0, 1]}), "u")
    p1.save(tmp_path / "line.png")
    points = np.array([[0, 0], [1, 0], [0, 1], [1, 1], [.3, .4]])
    p2 = Plot2D(); p2.contourf(Data2D.from_arrays(points, {"p": points[:, 0]}), "p")
    p2.save(tmp_path / "contour.svg")
    assert (tmp_path / "line.png").stat().st_size > 0
    assert (tmp_path / "contour.svg").stat().st_size > 0
