"""Run from a writable directory: python path/to/examples/python_api/example_2d.py."""
from pathlib import Path
import numpy as np
from sciplot import Data2D, Plot2D

out = Path("output"); out.mkdir(exist_ok=True)
rng = np.random.default_rng(8)
points = rng.uniform([-2, -1], [2, 1], size=(700, 2))
p = np.exp(-(points**2).sum(axis=1)) * np.cos(3 * points[:, 0])
data = Data2D.from_arrays(points, {"p": p})
plot = Plot2D(style="paper")
plot.contourf(data, "p", levels=24, cmap="turbo", colorbar_label=r"$p$")
plot.contour(data, "p", levels=[-0.4, 0, 0.4], colors="black", linewidths=.6)
plot.set_axes(xlabel=r"$x/L$", ylabel=r"$y/L$", xlim=(-2, 2), ylim=(-1, 1))
plot.save(out / "example_2d.png", dpi=200)
