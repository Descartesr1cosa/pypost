#!/usr/bin/env python3
"""Convert one MPCNS Mercury restart into a self-contained Data3D v1 file.

This is intentionally outside ``sciplot`` and self-contained: it reads the
documented MPCNS v3 wire format directly, so generic pypost workflows never
learn the Mercury binary, ghost, DEC, Hodge, or topology-alias formats, and no
external Mercury post-processing package is needed.

The converter uses the solver-provided owner maps and reconstruction operators;
it never deduplicates nodes by coordinates and never averages interface values.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

import yaml

# Permit the documented command to run from an editable repository checkout;
# installed packages already resolve normally and are not shadowed otherwise.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from .low_memory import REGIONS, SUPPORTED_FIELDS, resolve_region


_B = {"B_xi", "B_eta", "B_zeta"}
_IONS = {"U_H", "U_Na"}
# Restart fields each output needs; B_additive comes from the static Badd constants.
_RAW_FIELDS = {
    "B_induced": _B, "B_additive": set(), "B_total": _B, "J_induced": _B,
    "H_density": {"U_H"}, "H_velocity": {"U_H"}, "H_pressure": {"U_H"},
    "Na_density": {"U_Na"}, "Na_velocity": {"U_Na"}, "Na_pressure": {"U_Na"},
    "E_motional": _B | _IONS, "E_Hall": _B | _IONS, "E_ambipolar": _IONS, "E_generalized": _B | _IONS,
}
_DEFAULT_FIELDS = ("B_induced", "H_density", "H_velocity", "H_pressure", "Na_density", "Na_velocity", "Na_pressure")
_CONSTANT_FIELDS = {"B_additive", "B_total", "E_motional", "E_Hall", "E_generalized"}
assert set(_RAW_FIELDS) == set(SUPPORTED_FIELDS)


def _resolve(value: str | Path, base: Path) -> Path:
    """Resolve a configured path with no dependence on the current directory."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def load_yaml_config(path: str | Path) -> dict[str, Any]:
    """Load and normalize one ``kind: mercury-data3d`` configuration.

    ``paths.data_root`` is relative to this YAML file.  Every relative input,
    output, and temporary path is then relative to that resolved root.
    """
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Mercury configuration does not exist: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("kind") != "mercury-data3d":
        raise ValueError("Mercury YAML requires `kind: mercury-data3d`")
    try:
        root = _resolve(raw["paths"]["data_root"], config_path.parent).resolve()
        input_cfg = raw["input"]
        output_cfg = raw["output"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Mercury YAML requires paths.data_root, input, and output.path") from exc
    fields = raw.get("fields")
    if not isinstance(fields, list) or not fields or not all(isinstance(item, str) for item in fields):
        raise ValueError("Mercury YAML fields must be a non-empty list of field names")
    if not isinstance(input_cfg, dict) or not input_cfg.get("static_dir") or not input_cfg.get("data_dir"):
        raise ValueError("Mercury YAML requires non-empty input.static_dir and input.data_dir")
    if not isinstance(output_cfg, dict) or not output_cfg.get("path"):
        raise ValueError("Mercury YAML requires a non-empty output.path")
    runtime = raw.get("runtime", {})
    if not isinstance(runtime, dict):
        raise ValueError("Mercury YAML runtime must be a mapping")
    return {
        "config_path": config_path,
        "data_root": root,
        "static_dir": _resolve(input_cfg.get("static_dir", ""), root).resolve(),
        "data_dir": _resolve(input_cfg.get("data_dir", ""), root).resolve(),
        "output": _resolve(output_cfg.get("path", ""), root).resolve(),
        "fields": fields,
        "temp_dir": _resolve(runtime["temp_dir"], root).resolve() if runtime.get("temp_dir") else None,
        "memory_budget_gb": runtime.get("memory_budget_gb", 4.0),
        "region": str(raw.get("region", "auto")),
        "keep_temp": bool(runtime.get("keep_temp", False)),
        "verify_readback": bool(runtime.get("verify_readback", False)),
        "overwrite": bool(output_cfg.get("overwrite", False)),
    }


def validate_conversion_request(*, static_dir: Path, data_dir: Path, output: Path, fields: list[str],
                                temp_dir: Path | None, memory_budget_gb: float | None,
                                overwrite: bool = False, region: str = "auto") -> None:
    """Reject configuration/path errors before a rank file is streamed."""
    from .streaming import load_manifest

    unknown = sorted(set(fields) - set(SUPPORTED_FIELDS))
    if unknown:
        raise ValueError(f"Unknown output fields: {unknown}; choose from {list(SUPPORTED_FIELDS)}")
    if len(set(fields)) != len(fields):
        raise ValueError("Mercury YAML fields must not contain duplicates")
    resolve_region(fields, region)
    if memory_budget_gb is not None and float(memory_budget_gb) <= 0:
        raise ValueError("runtime.memory_budget_gb must be positive")
    if output.suffix.lower() != ".vtu":
        raise ValueError(f"Output must be a .vtu file path, not {output}")
    if output.exists() and output.is_dir():
        raise IsADirectoryError(f"Output must be a .vtu file, not an existing directory: {output}")
    if output.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing output: {output}; set output.overwrite: true explicitly")
    if not static_dir.is_dir() or not data_dir.is_dir():
        raise FileNotFoundError(f"Mercury input directories must exist: static={static_dir}, data={data_dir}")
    for protected in (static_dir, data_dir):
        if output == protected or protected in output.parents:
            raise ValueError(f"Output must be outside Mercury input directory: {protected}")
        if temp_dir is not None and (temp_dir == protected or protected in temp_dir.parents):
            raise ValueError(f"runtime.temp_dir must be outside Mercury input directory: {protected}")
    manifest = load_manifest(static_dir)
    try:
        ranks, files = int(manifest["number_of_ranks"]), manifest["files"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Mercury manifest lacks a valid number_of_ranks/files mapping") from exc
    if ranks <= 0 or not isinstance(files, dict):
        raise ValueError("Mercury manifest must declare at least one rank and its static files")
    categories = ["geometry", "topology", "reconstruction"]
    if set(fields) & _CONSTANT_FIELDS:
        categories.append("constant_field")
    for category in categories:
        entries = files.get(category)
        if not isinstance(entries, list) or len(entries) != ranks:
            raise ValueError(f"Mercury manifest has invalid {category} rank list")
        missing = next((static_dir / item for item in entries if not (static_dir / item).is_file()), None)
        if missing:
            raise FileNotFoundError(f"Mercury static input is missing: {missing}")
    missing_restart = next((data_dir / f"flow_field{rank:04d}.bin" for rank in range(ranks)
                            if not (data_dir / f"flow_field{rank:04d}.bin").is_file()), None)
    if missing_restart:
        raise FileNotFoundError(f"Mercury restart input is missing: {missing_restart}")
    available = {str(item.get("name")) for item in manifest.get("existing_dynamic_data", {}).get("fields", [])}
    required = set().union(*(_RAW_FIELDS[field] for field in fields))
    if set(fields) & _CONSTANT_FIELDS:
        constants = {str(item.get("name")) for item in manifest.get("fields", [])}
        if missing := sorted({"Badd_xi", "Badd_eta", "Badd_zeta"} - constants):
            raise ValueError(f"Mercury manifest lacks additive-field constants required by {fields}: {missing}")
    if missing := sorted(required - available):
        raise ValueError(f"Mercury manifest does not provide raw field(s) required by {fields}: {missing}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if temp_dir is not None:
        if temp_dir.exists() and not temp_dir.is_dir():
            raise NotADirectoryError(f"runtime.temp_dir is not a directory: {temp_dir}")
        temp_dir.mkdir(parents=True, exist_ok=True)


_REQUEST_KEYS = ("static_dir", "data_dir", "output", "fields", "temp_dir", "memory_budget_gb", "overwrite", "region")
_CONVERT_KEYS = ("static_dir", "data_dir", "output", "fields", "temp_dir", "memory_budget_gb", "region", "keep_temp", "verify_readback")


def convert_from_config(path: str | Path) -> Path:
    """Run the low-memory converter from a normalized YAML request."""
    request = load_yaml_config(path)
    validate_conversion_request(**{key: request[key] for key in _REQUEST_KEYS})
    from .low_memory import convert
    return convert(**{key: request[key] for key in _CONVERT_KEYS})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="mercury-data3d YAML configuration (recommended)")
    parser.add_argument("--static-dir", type=Path, help="Mercury DATA_bin directory containing manifest.json")
    parser.add_argument("--data-dir", type=Path, help="One restart directory containing flow_field####.bin")
    parser.add_argument("--output", type=Path, help="Output Data3D v1 .vtu")
    parser.add_argument("--fields", default=",".join(_DEFAULT_FIELDS),
                        help=f"Comma-separated Data3D fields from {', '.join(SUPPORTED_FIELDS)}; use --fields B_induced for the smallest output")
    parser.add_argument("--region", default="auto", choices=REGIONS,
                        help="Output cells: auto (Fluid when any Fluid-only field is requested, else all), fluid, solid, or all")
    parser.add_argument("--temp-dir", type=Path, help="Directory for disk-backed temporary buffers")
    parser.add_argument("--memory-budget-gb", type=float, default=4.0, help="Hard observed-RSS ceiling (default: 4 GiB)")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary buffers and diagnostics.json after completion/failure")
    parser.add_argument("--verify-readback", action="store_true", help="Use PyVista to reopen the final temporary VTU; may need output-sized RAM")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing .vtu result")
    args = parser.parse_args(argv)
    if args.config:
        if any(value is not None for value in (args.static_dir, args.data_dir, args.output)):
            parser.error("--config cannot be combined with --static-dir, --data-dir, or --output")
        print(convert_from_config(args.config))
        return 0
    if any(value is None for value in (args.static_dir, args.data_dir, args.output)):
        parser.error("use --config CONFIG.yml or supply --static-dir, --data-dir, and --output")
    request = {"static_dir": args.static_dir.resolve(), "data_dir": args.data_dir.resolve(), "output": args.output.resolve(),
               "fields": [item.strip() for item in args.fields.split(",") if item.strip()],
               "temp_dir": args.temp_dir.resolve() if args.temp_dir else None, "memory_budget_gb": args.memory_budget_gb,
               "overwrite": args.overwrite, "region": args.region, "keep_temp": args.keep_temp, "verify_readback": args.verify_readback}
    validate_conversion_request(**{key: request[key] for key in _REQUEST_KEYS})
    from .low_memory import convert
    print(convert(**{key: request[key] for key in _CONVERT_KEYS}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
