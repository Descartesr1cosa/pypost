"""Equivalent Python call for configs/examples/compare_curves.yml."""
from pathlib import Path
from sciplot.curve import compare
from sciplot.workflow import read_yaml

root = Path(__file__).parents[1]
config = root / "configs" / "examples" / "compare_curves.yml"
print(compare(read_yaml(config), config.parent))
