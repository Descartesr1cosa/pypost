"""``pypost`` command line interface."""
from __future__ import annotations
import argparse
from copy import deepcopy
from pathlib import Path
import shutil
from .inspect import inspect_path
from .workflow import load_data, read_yaml, save_data


def _config(value: str): return Path(value).resolve()


def _compare(*args, **kwargs):
    """Lazy import keeps `pypost edit` free to select a GUI backend first."""
    from .curve import compare
    return compare(*args, **kwargs)


def _q_workflow():
    """Delay PyVista/plot imports until a Q command actually needs them."""
    from .q import batch, camera_editor, extract, load_config, render
    return batch, camera_editor, extract, load_config, render


def _project_root() -> Path:
    """Return package-owned demo assets in both editable and wheel installs."""
    return Path(__file__).resolve().parent


def _demos() -> dict[str, tuple[str, Path]]:
    root = _project_root()
    return {
        "curve-comparison": ("Self-contained synthetic three-curve comparison", root / "demos" / "curve_demo" / "curve_comparison.yml"),
        "curve-layout": ("Editable automatic/manual layout demonstration", root / "demos" / "curve_layout_demo" / "layout.yml"),
        "curve-annotations": ("Mathtext, text, arrow, and multi-panel annotation demonstration", root / "demos" / "curve_annotation_demo" / "annotations.yml"),
        "curve-gallery": ("Synthetic 2x2 scientific plotting feature gallery", root / "demos" / "curve_gallery" / "gallery.yml"),
        "cfd-curve-workflow": ("Raw OpenFOAM-style curve conversion and paper plot", root / "demos" / "cfd_curve_demo" / "workflow.yml"),
        "q-surface": ("Supplied Q surface with reproducible camera and scene", root / "demos" / "q_demo" / "q_surface.yml"),
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


def _copy_demo_project(name: str, destination: str | Path) -> Path:
    """Copy an editable curve demo without ever modifying package resources."""
    if name not in {"curve-comparison", "curve-layout", "curve-annotations", "curve-gallery", "cfd-curve-workflow"}:
        raise ValueError(f"Demo {name!r} cannot be initialized as an editable 1-D project.")
    source = _demos()[name][1].parent
    target = Path(destination).expanduser()
    if target.exists():
        raise FileExistsError(
            f"Destination already exists: {target}. Choose a new --dest directory; "
            "pypost will not overwrite your work."
        )
    shutil.copytree(source, target)
    # A short, memorable filename makes the beginner command in the tutorial
    # work exactly as printed while retaining the original bundled resource.
    if name == "curve-comparison":
        (target / "curve_comparison.yml").rename(target / "plot.yml")
    return target


def _convert_from_config(config_path: Path) -> Path:
    """Run the ordinary single-input conversion used by CLI and demos."""
    config = read_yaml(config_path)
    spec = dict(config["input"])
    if "path" not in spec:
        raise KeyError("Conversion YAML needs input.path. Example: input: {dimension: 1, path: raw.xy}")
    input_path = Path(spec["path"])
    spec["path"] = input_path if input_path.is_absolute() else config_path.parent / input_path
    if not spec["path"].is_file():
        raise FileNotFoundError(
            f"Input data file not found: {spec['path']}. Check input.path relative to {config_path.parent}."
        )
    data = load_data(spec)
    if hasattr(data, "metadata"):
        data.metadata.update({"raw_source": str(spec["path"]), "source_format": input_path.suffix.lstrip("."),
                              "conversion_options": config.get("options", {}), "internal_format_version": 1})
    try:
        output_spec = Path(config["output"]["path"])
    except KeyError as exc:
        raise KeyError("Conversion YAML needs output.path. Example: output: {path: standardized/case.csv}") from exc
    target = output_spec if output_spec.is_absolute() else config_path.parent / output_spec
    try:
        save_data(data, target)
    except OSError as exc:
        raise OSError(f"Cannot write normalized data to {target}. Check output.path and directory permissions.") from exc
    return target


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
    demo_init = demo_p.add_parser("init", help="Copy an editable 1-D demo project into a new directory")
    demo_init.add_argument("name", choices=("curve-comparison", "curve-layout", "curve-annotations", "curve-gallery", "cfd-curve-workflow"))
    demo_init.add_argument("--dest", required=True, help="New writable project directory (must not already exist)")
    commands.add_parser("doctor", help="Report versions, demo assets, and rendering prerequisites")
    plot_p = commands.add_parser("plot", help="Render a 1-D YAML figure without opening a GUI")
    plot_p.add_argument("config", help="1-D curve YAML file")
    plot_p.add_argument("--output", help="Override output path without modifying YAML")
    plot_p.add_argument("--show", action="store_true", help="Preview interactively when DISPLAY is available")
    edit_p = commands.add_parser("edit", help="Interactively adjust a 1-D figure layout and save JSON")
    edit_p.add_argument("config", help="1-D curve YAML file")
    edit_p.add_argument("--layout", help="JSON path to save instead of plot.layout.overrides")
    curve_p = commands.add_parser("curve", help="One-dimensional curve workflows").add_subparsers(dest="curve_command", required=True)
    curve_compare = curve_p.add_parser("compare", help="Compare multiple standard CSV curves")
    curve_compare.add_argument("--config", required=True)
    curve_compare.add_argument("--output", help="Override output path without modifying YAML")
    curve_compare.add_argument("--show", action="store_true", help="Preview interactively when DISPLAY is available")
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
        if args.demo_command == "init":
            target = _copy_demo_project(args.name, args.dest)
            config_name = "plot.yml" if args.name == "curve-comparison" else _demos()[args.name][1].name
            print(f"Editable demo created: {target}\nNext: pypost plot {target / config_name}")
            return 0
        description, config_path = demos[args.name]
        if not config_path.is_file(): raise FileNotFoundError(f"Demo configuration missing: {config_path}")
        output_dir = Path.cwd() / "pypost-demo-output"
        if args.name in {"curve-comparison", "curve-layout", "curve-annotations", "curve-gallery"}:
            config = deepcopy(read_yaml(config_path))
            stem = {"curve-comparison": "curve_comparison", "curve-layout": "curve_layout",
                    "curve-annotations": "curve_annotations", "curve-gallery": "curve_gallery"}[args.name]
            config.setdefault("plot", {})["outputs"] = [str(output_dir / f"{stem}.pdf"), str(output_dir / f"{stem}.svg"), str(output_dir / f"{stem}.png")]
            print(_compare(config, config_path.parent)); return 0
        if args.name == "cfd-curve-workflow":
            # Stage package-owned files first, then execute their unmodified,
            # standalone YAML files. This is the same workflow a user gets
            # with `pypost demo init`, not a hidden path-alias implementation.
            project = output_dir / "cfd-curve-workflow"
            shutil.copytree(config_path.parent, project, dirs_exist_ok=True)
            workflow = read_yaml(project / config_path.name)
            for conversion in workflow["convert_configs"]:
                _convert_from_config(project / conversion)
            print(_compare(read_yaml(project / workflow["plot_config"]), project)); return 0
        _, _, _, load_config, render = _q_workflow()
        config = load_config(config_path)
        config.setdefault("output", {})["image"] = str(output_dir / "q_surface.png")
        print(render(config, config_path.parent, config.get("time"))); return 0
    if args.command == "convert":
        config_path = _config(args.config); config = read_yaml(config_path)
        if "series" in config:
            from .data import Data3D
            steps = []
            for item in config["series"]:
                spec = dict(config.get("input", {})); spec.update(item.get("input", item))
                # A series item owns its physical time even when it has a
                # nested input mapping; Data3D.from_file forwards this to an
                # OpenFOAM reader rather than merely recording it in JSON.
                spec["time"] = item["time"]
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
        _convert_from_config(config_path)
        return 0
    if args.command == "curve":
        config_path = _config(args.config); print(_compare(read_yaml(config_path), config_path.parent, args.output, args.show)); return 0
    if args.command == "plot":
        config_path = _config(args.config); print(_compare(read_yaml(config_path), config_path.parent, args.output, args.show)); return 0
    if args.command == "edit":
        # This intentionally occurs before importing curve.py/pyplot.
        from .plotting.figure_editor import ensure_interactive_backend
        ensure_interactive_backend()
        from .curve import build_figure
        from .plotting.figure_editor import open_editor
        config_path = _config(args.config); config = read_yaml(config_path)
        renderer, panels, annotations, plot_cfg, defaults = build_figure(config, config_path.parent)
        layout = args.layout or plot_cfg.get("layout", {}).get("overrides")
        target = Path(layout) if layout else config_path.with_suffix(".layout.json")
        if not target.is_absolute(): target = config_path.parent / target
        open_editor(renderer.fig, panels, annotations, target, defaults)
        return 0
    batch, camera_editor, extract, load_config, render = _q_workflow()
    config_path = _config(args.config); config = load_config(config_path); base = config_path.parent
    if args.q_command == "extract": print(extract(config, base, args.time, args.force)); return 0
    if args.q_command == "camera": camera_editor(config, base, args.time); return 0
    if args.q_command == "render": print(render(config, base, args.time, args.resume)); return 0
    failures = batch(config_path, config, base, args.resume, args.dry_run)
    if failures: print(f"Failed times: {failures}"); return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
