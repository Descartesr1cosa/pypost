"""Run: python examples/example_1d.py"""
from pathlib import Path
import numpy as np
from sciplot import Data1D, Plot1D

out = Path("output"); out.mkdir(exist_ok=True)
x = np.linspace(0, 2 * np.pi, 200)
simulation = Data1D.from_arrays(x, {"u": np.sin(x)})
experiment = Data1D.from_arrays(x[::12], {"u": np.sin(x[::12]) + 0.04 * np.cos(3*x[::12])})
plot = Plot1D(style="paper")
plot.line(simulation, "u", label="simulation", color="C0")
plot.line(experiment, "u", label="experiment", linestyle="none", marker="o", color="C1")
plot.set_axes(xlabel=r"$x$", ylabel=r"$u$", legend=True)
plot.save(out / "example_1d.pdf")
