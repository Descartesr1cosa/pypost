"""Run: python examples/example_3d.py (uses off-screen rendering)."""
from pathlib import Path
import numpy as np
import pyvista as pv
from sciplot import Data3D, Plot3D

out = Path("output"); out.mkdir(exist_ok=True)
grid = pv.ImageData(dimensions=(31, 31, 31), spacing=(.1, .1, .1), origin=(-1.5, -1.5, -1.5))
xyz = grid.points
grid.point_data["p"] = np.exp(-3 * (xyz**2).sum(axis=1))
data = Data3D(grid)
data.save(out / "example_3d.vti")
if not Plot3D.offscreen_available():
    print("Wrote output/example_3d.vti; PNG skipped: install EGL/OSMesa or run with an X display.")
    raise SystemExit(0)
plot = Plot3D(window_size=(800, 600), background="white")
plot.slice(data, origin=(0, 0, 0), normal=(1, 1, 0), field="p", cmap="turbo")
plot.contour(data, "p", isosurfaces=[.2, .5], opacity=.55)
plot.screenshot(out / "example_3d.png")
plot.close()
