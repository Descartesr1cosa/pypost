#!/usr/bin/env python
"""Normalize raw input described by YAML and write reusable processed data.

Run: python scripts/convert_data.py configs/convert.yml
"""
from __future__ import annotations
import sys
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
