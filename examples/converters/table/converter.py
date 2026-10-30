"""Example external-table converter using only the public pypost I/O API."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

import numpy as np

from sciplot import Data1D, load_dataset, save_dataset, validate_dataset


def _resolve(value: str | Path, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def convert_table(input_path: Path, output: Path, *, x: str = "time", ascii_path: Path | None = None,
                  export: Path | None = None) -> Path:
    """Convert a table using only public Data1D I/O and verify round-trip."""
    if not input_path.is_file():
        raise FileNotFoundError(f"Input table does not exist: {input_path}")
    if output.suffix.lower() != ".npz":
        raise ValueError(f"Table converter output must be .npz: {output}")
    if output.exists() and output.is_dir():
        raise IsADirectoryError(f"Output must be a file, not directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Data1D.from_file handles CSV, whitespace, and OpenFOAM-style comment headers.
    parsed = Data1D.from_file(input_path, x=x)
    data = Data1D(parsed.x, parsed.fields, x_name=parsed.x_name, x_unit=parsed.x_unit,
                  field_units=parsed.field_units, metadata={"external_source": str(input_path),
                  "converter": "examples.converters.table"}, sort=False)
    binary = save_dataset(data, output, encoding="binary")
    restored = load_dataset(binary)
    np.testing.assert_array_equal(restored.x, data.x)
    for name in data.fields:
        np.testing.assert_array_equal(restored.fields[name], data.fields[name])
    if ascii_path:
        save_dataset(data, ascii_path, encoding="ascii")
    if export:
        restored.to_frame().to_csv(export, index=False)
    result = validate_dataset(binary, deep=True)
    if not result["valid"]:
        raise RuntimeError("standard dataset failed validation: " + "; ".join(result["issues"]))
    return binary


def convert_from_config(path: str | Path) -> Path:
    config_path = Path(path).expanduser().resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("kind") != "table-data1d":
        raise ValueError("Table YAML requires `kind: table-data1d`")
    try:
        input_cfg, output_cfg = config["input"], config["output"]
        input_path = _resolve(input_cfg["path"], config_path.parent)
        output = _resolve(output_cfg["path"], config_path.parent)
    except (KeyError, TypeError) as exc:
        raise ValueError("Table YAML requires input.path and output.path") from exc
    optional = config.get("exports", {})
    return convert_table(input_path, output, x=str(input_cfg.get("x", "time")),
                         ascii_path=_resolve(optional["ascii"], config_path.parent) if optional.get("ascii") else None,
                         export=_resolve(optional["csv"], config_path.parent) if optional.get("csv") else None)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Convert a named TXT/CSV table to pypost standard 1-D data")
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("output", type=Path, nargs="?", help="binary .npz output")
    parser.add_argument("--config", type=Path, help="table-data1d YAML configuration")
    parser.add_argument("--x", default="time", help="coordinate column name")
    parser.add_argument("--ascii", type=Path, help="optional scalar CSV standard-data copy")
    parser.add_argument("--export", type=Path, help="optional scalar CSV re-export from standard data")
    args = parser.parse_args(argv)
    if args.config:
        if args.input or args.output:
            parser.error("--config cannot be combined with positional input/output")
        print(convert_from_config(args.config))
        return 0
    if not args.input or not args.output:
        parser.error("use --config CONFIG.yml or INPUT OUTPUT")
    print(convert_table(args.input, args.output, x=args.x, ascii_path=args.ascii, export=args.export))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
