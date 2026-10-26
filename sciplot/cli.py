"""``pypost`` command line interface."""
from __future__ import annotations
import argparse
from pathlib import Path
from .curve import compare
from .inspect import inspect_path
from .q import batch, camera_editor, extract, load_config, render
from .workflow import load_data, read_yaml, save_data


def _config(value: str): return Path(value).resolve()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _demos() -> dict[str, tuple[str, Path]]:
    root = _project_root()
    return {
        "curve-comparison": ("Self-contained synthetic three-curve comparison", root / "examples" / "assets" / "curve_demo" / "curve_comparison.yml"),
        "q-surface": ("Supplied Q surface with reproducible camera and scene", root / "examples" / "assets" / "q_demo" / "q_surface.yml"),
    }


def _doctor() -> str:
    import sys
    import pyvista as pv
    import vtk
    from .plotting import Plot3D
    lines = [f"Python: {sys.version.split()[0]}", f"PyVista: {pv.__version__}", f"VTK: {vtk.vtkVersion.GetVTKVersion()}",
             f"Off-screen rendering candidate: {'yes' if Plot3D.offscreen_available() else 'no'}"]
    for name, (_, config) in _demos().items():
        lines.append(f"demo {name}: {'ready' if config.is_file() else 'MISSING'} ({config})")
    if not Plot3D.offscreen_available():
        lines.append("rendering note: set DISPLAY or install/configure EGL or OSMesa for `pypost q render`.")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pypost", description="Reproducible CFD post-processing workflows")
    commands = parser.add_subparsers(dest="command", required=True)
    convert_p = commands.add_parser("convert", help="Convert source data into a standard internal format")
    convert_p.add_argument("--config", required=True)
    inspect_p = commands.add_parser("inspect", help="Show fields, ranges, and mesh summary")
    inspect_p.add_argument("data_path")
    demo_p = commands.add_parser("demo", help="Discover and run bundled self-contained workflows").add_subparsers(dest="demo_command", required=True)
    demo_p.add_parser("list", help="List bundled demos")
    demo_run = demo_p.add_parser("run", help="Run a bundled demo using the normal core workflow")
    demo_run.add_argument("name", choices=tuple(_demos()))
    commands.add_parser("doctor", help="Report versions, demo assets, and rendering prerequisites")
    curve_p = commands.add_parser("curve", help="One-dimensional curve workflows").add_subparsers(dest="curve_command", required=True)
    curve_compare = curve_p.add_parser("compare", help="Compare multiple standard CSV curves")
    curve_compare.add_argument("--config", required=True)
    q_p = commands.add_parser("q", help="Q-criterion surface and scene workflows").add_subparsers(dest="q_command", required=True)
    for name, help_text in (("extract", "Extract/cache a Q isosurface"), ("camera", "Interactively edit camera JSON"), ("render", "Render one Q scene"), ("batch", "Render configured time steps in isolated subprocesses")):
        item = q_p.add_parser(name, help=help_text); item.add_argument("--config", required=True)
        if name in {"extract", "camera", "render"}: item.add_argument("--time", type=float)
        if name == "extract": item.add_argument("--force", action="store_true")
        if name == "render": item.add_argument("--resume", action="store_true")
        if name == "batch": item.add_argument("--resume", action="store_true"); item.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "inspect": print(inspect_path(args.data_path)); return 0
    if args.command == "doctor": print(_doctor()); return 0
    if args.command == "demo":
        demos = _demos()
        if args.demo_command == "list":
            for name, (description, config) in demos.items(): print(f"{name}: {description} ({config})")
            return 0
        description, config_path = demos[args.name]
        if not config_path.is_file(): raise FileNotFoundError(f"Demo configuration missing: {config_path}")
        if args.name == "curve-comparison": print(compare(read_yaml(config_path), config_path.parent)); return 0
        config = load_config(config_path); print(render(config, config_path.parent, config.get("time"))); return 0
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
    if args.q_command == "camera": camera_editor(config, base, args.time); return 0
    if args.q_command == "render": print(render(config, base, args.time, args.resume)); return 0
    failures = batch(config_path, config, base, args.resume, args.dry_run)
    if failures: print(f"Failed times: {failures}"); return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
