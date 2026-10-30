#!/usr/bin/env python
"""Normalize raw input described by YAML and write reusable processed data.

Run: python examples/python_api/convert_data.py convert.yml
"""
from __future__ import annotations
import sys
from pathlib import Path

# Keep this documented checkout example runnable without an editable install;
# package installation remains preferred for normal users.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from sciplot.workflow import load_data, read_yaml, save_data


def main(config_path: str) -> None:
    config = read_yaml(config_path)
    data = load_data(config["input"])
    target = config["output"]["path"]
    save_data(data, target)
    print(f"Wrote {target}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: convert_data.py CONFIG.yml")
    main(sys.argv[1])
