"""``pypost`` command line interface."""
from __future__ import annotations
import argparse
from pathlib import Path
from .curve import compare
from .inspect import inspect_path
from .q import batch, camera_editor, extract, load_config, render
from .workflow import load_data, read_yaml, save_data


def _config(value: str): return Path(value).resolve()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pypost", description="Reproducible CFD post-processing workflows")
    commands = parser.add_subparsers(dest="command", required=True)
    convert_p = commands.add_parser("convert", help="Convert source data into a standard internal format")
    convert_p.add_argument("--config", required=True)
    inspect_p = commands.add_parser("inspect", help="Show fields, ranges, and mesh summary")
    inspect_p.add_argument("data_path")
    curve_p = commands.add_parser("curve", help="One-dimensional curve workflows").add_subparsers(dest="curve_command", required=True)
    curve_compare = curve_p.add_parser("compare", help="Compare multiple standard CSV curves")
    curve_compare.add_argument("--config", required=True)
    q_p = commands.add_parser("q", help="Q-criterion surface and scene workflows").add_subparsers(dest="q_command", required=True)
    for name, help_text in (("extract", "Extract/cache a Q isosurface"), ("camera", "Interactively edit camera JSON"), ("render", "Render one Q scene"), ("batch", "Render configured time steps in isolated subprocesses")):
        item = q_p.add_parser(name, help=help_text); item.add_argument("--config", required=True)
        if name in {"extract", "render"}: item.add_argument("--time", type=float)
        if name == "extract": item.add_argument("--force", action="store_true")
        if name == "render": item.add_argument("--resume", action="store_true")
        if name == "batch": item.add_argument("--resume", action="store_true"); item.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "inspect": print(inspect_path(args.data_path)); return 0
    if args.command == "convert":
        config_path = _config(args.config); config = read_yaml(config_path)
        if "series" in config:
            from .data import Data3D
            steps = []
            for item in config["series"]:
                spec = dict(config.get("input", {})); spec.update(item.get("input", item))
                source = Path(spec["path"]); spec["path"] = source if source.is_absolute() else config_path.parent / source
                if str(spec.get("dimension", "3")).lower().replace("d", "") != "3":
                    raise ValueError("convert.series currently supports only normalized 3-D VTK data")
                target_value = item.get("output", item.get("target"))
                if not target_value: raise ValueError("Each convert.series item needs output: PATH")
                target = Path(target_value); target = target if target.is_absolute() else config_path.parent / target
                data = load_data(spec); data.metadata.update({"raw_source": str(spec["path"]), "internal_format_version": 1})
                save_data(data, target)
                steps.append({"time": item["time"], "path": str(target)})
            index_value = config.get("output", {}).get("index")
            if not index_value: raise ValueError("convert.series requires output.index")
            index = Path(index_value); index = index if index.is_absolute() else config_path.parent / index
            Data3D.save_time_index(index, steps, {"conversion_options": config.get("options", {})})
            print(index); return 0
        spec = dict(config["input"])
        input_path = Path(spec["path"])
        spec["path"] = input_path if input_path.is_absolute() else config_path.parent / input_path
        data = load_data(spec)
        if hasattr(data, "metadata"):
            data.metadata.update({"raw_source": str(spec["path"]), "source_format": input_path.suffix.lstrip("."),
                                  "conversion_options": config.get("options", {}), "internal_format_version": 1})
        output_spec = Path(config["output"]["path"])
        save_data(data, output_spec if output_spec.is_absolute() else config_path.parent / output_spec)
        return 0
    if args.command == "curve":
        config_path = _config(args.config); print(compare(read_yaml(config_path), config_path.parent)); return 0
    config_path = _config(args.config); config = load_config(config_path); base = config_path.parent
    if args.q_command == "extract": print(extract(config, base, args.time, args.force)); return 0
    if args.q_command == "camera": camera_editor(config, base); return 0
    if args.q_command == "render": print(render(config, base, args.time, args.resume)); return 0
    failures = batch(config_path, config, base, args.resume, args.dry_run)
    if failures: print(f"Failed times: {failures}"); return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
