import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

from sciplot.curve import compare


def test_band_is_scaled_with_y_values_and_paper_style(tmp_path):
    data = tmp_path / "curve.csv"
    data.write_text("x,y,lo,hi\n0,1,.5,1.5\n1,2,1.5,2.5\n")
    target = tmp_path / "curve.svg"
    config = {"datasets": [{"path": "curve.csv", "x": "x", "y": "y", "kind": "band", "lower": "lo", "upper": "hi", "y_scale": 10}],
              "plot": {"style": "paper", "outputs": [str(target)], "axes": {"grid": True}}}
    compare(config, tmp_path)
    vertices = plt.gca().collections[0].get_paths()[0].vertices[:, 1]
    assert np.nanmin(vertices) == 5 and np.nanmax(vertices) == 25
    assert target.is_file() and plt.gca().figure.dpi == 300


def test_bundled_curve_demo_generates_pdf_and_svg(tmp_path):
    root = __import__("pathlib").Path(__file__).parents[1]
    config_path = root / "examples" / "assets" / "curve_demo" / "curve_comparison.yml"
    config = yaml.safe_load(config_path.read_text())
    config["plot"]["outputs"] = [str(tmp_path / "demo.pdf"), str(tmp_path / "demo.svg")]
    result = compare(config, config_path.parent)
    assert result.suffix == ".pdf"
    assert (tmp_path / "demo.pdf").is_file() and (tmp_path / "demo.svg").is_file()
