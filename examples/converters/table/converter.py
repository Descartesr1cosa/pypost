"""Example external-table converter using only the public pypost I/O API."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from sciplot import Data1D, load_dataset, save_dataset, validate_dataset


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Convert a named TXT/CSV table to pypost standard 1-D data")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, help="binary .npz output")
    parser.add_argument("--x", default="time", help="coordinate column name")
    parser.add_argument("--ascii", type=Path, help="optional scalar CSV standard-data copy")
    parser.add_argument("--export", type=Path, help="optional scalar CSV re-export from standard data")
    args = parser.parse_args(argv)

    # Data1D.from_file handles CSV, whitespace, and OpenFOAM-style comment headers.
    parsed = Data1D.from_file(args.input, x=args.x)
    data = Data1D(parsed.x, parsed.fields, x_name=parsed.x_name, x_unit=parsed.x_unit,
                  field_units=parsed.field_units, metadata={"external_source": str(args.input),
                  "converter": "convert_table_to_pypost.py"}, sort=False)
    binary = save_dataset(data, args.output, encoding="binary")
    restored = load_dataset(binary)
    np.testing.assert_array_equal(restored.x, data.x)
    for name in data.fields: np.testing.assert_array_equal(restored.fields[name], data.fields[name])
    if args.ascii: save_dataset(data, args.ascii, encoding="ascii")
    if args.export: restored.to_frame().to_csv(args.export, index=False)
    result = validate_dataset(binary, deep=True)
    if not result["valid"]: raise RuntimeError("standard dataset failed validation: " + "; ".join(result["issues"]))
    print(binary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
