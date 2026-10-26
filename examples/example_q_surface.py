"""Render the supplied Q_sample.vtp with its reproducible saved camera."""
from pathlib import Path
from sciplot.q import load_config, render

root = Path(__file__).parents[1]
config_path = root / "configs" / "examples" / "q_surface.yml"
print(render(load_config(config_path), config_path.parent, time=60.5))
