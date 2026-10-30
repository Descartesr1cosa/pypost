"""Equivalent Python call for examples/workflows/curve/compare_curves.yml."""
from pathlib import Path
from sciplot.curve import compare
from sciplot.workflow import read_yaml

root = Path(__file__).parents[2]
config = root / "examples" / "workflows" / "curve" / "compare_curves.yml"
print(compare(read_yaml(config), config.parent))
