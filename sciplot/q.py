"""Reusable Q-criterion extraction, camera handling, and rendering workflow.

Q calculated here uses VTK's velocity-gradient implementation.  It is recorded
in metadata because it need not equal an OpenFOAM solver's discretized gradient.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from copy import deepcopy

import numpy as np

from .data import Data3D
from .provenance import FORMAT_VERSION, file_signature, fingerprint, read_record, vtk_dependency_signature, write_record


def load_config(path: str | Path) -> dict[str, Any]:
    from .workflow import read_yaml
    config = read_yaml(path)
    config.setdefault("processing", {})
    config.setdefault("scene", {})
    config.setdefault("output", {})
    return config


def _path(value: str | Path, base: Path, time: float | None = None) -> Path:
    value = str(value)
    if time is not None:
        value = value.format(time=time)
    result = Path(value)
    return result if result.is_absolute() else base / result


VIEW_FORMAT = "pypost-q-view"
VIEW_VERSION = 1


def _data_base(config: dict[str, Any], base: Path) -> Path:
    """Return the optional, portable root for full scientific data.

    Preview packages keep presentation files beside one another, while their
    full-resolution data commonly remains on a cluster filesystem.  A relative
    ``data_root`` is deliberately resolved from the YAML file and may be
    changed after transfer without touching the presentation state.
    """
    value = config.get("data_root")
    if not value:
        return base
    expanded = os.path.expandvars(str(value))
    return _path(expanded, base)


def _data_path(value: str | Path, config: dict[str, Any], base: Path, time: float | None = None) -> Path:
    return _path(value, _data_base(config, base), time)


def _relative(path: Path, parent: Path) -> str:
    """A manifest/config reference that remains relative and editable."""
    return os.path.relpath(Path(path).resolve(), Path(parent).resolve())


def _iter_datasets(mesh, prefix: str = ""):
    import pyvista as pv
    if not isinstance(mesh, pv.MultiBlock):
        yield prefix or "root", mesh
        return
    for index, block in enumerate(mesh):
        if block is None:
            continue
        name = mesh.get_block_name(index) or str(index)
        path = f"{prefix}/{name}" if prefix else name
        yield from _iter_datasets(block, path)


def select_dataset(mesh, selector: str | int | None = None):
    """Select a named leaf from MultiBlock rather than guessing its first block.

    With no selector, only a unique block named ``internalMesh`` is accepted.
    A selector can be a leaf name (``internalMesh``), full path
    (``regionA/internalMesh``), or numeric top-level block index.
    """
    import pyvista as pv
    if not isinstance(mesh, pv.MultiBlock):
        return mesh
    choices = list(_iter_datasets(mesh))
    if isinstance(selector, int):
        if selector < 0 or selector >= mesh.n_blocks or not isinstance(mesh[selector], pv.DataSet):
            raise KeyError(f"Invalid top-level DataSet block index {selector}")
        return mesh[selector]
    selector = "internalMesh" if selector is None else str(selector)
    matches = [(name, value) for name, value in choices if name == selector or name.rsplit("/", 1)[-1] == selector]
    if len(matches) == 1:
        return matches[0][1]
    available = [name for name, _ in choices]
    if not matches:
        raise KeyError(f"MultiBlock selector {selector!r} not found; available DataSet blocks: {available}")
    raise KeyError(f"MultiBlock selector {selector!r} is ambiguous; use one of: {[name for name, _ in matches]}")


def _time_index_source(config: dict[str, Any], base: Path, time: float | None) -> tuple[Path, float | None]:
    input_cfg = config.get("input", {})
    index_value = input_cfg.get("time_index")
    path_value = input_cfg.get("path")
    if index_value is None and path_value and str(path_value).lower().endswith(".json"):
        index_value = path_value
    if not index_value:
        if not path_value:
            raise ValueError("q extract requires input.path, input.time_index, or input.surface")
        return _data_path(path_value, config, base, time), time
    index_path = _data_path(index_value, config, base)
    index = Data3D.load_time_index(index_path)
    requested = time if time is not None else input_cfg.get("time")
    if requested is None:
        raise ValueError("Q extraction from a time index requires --time or input.time")
    tolerance = float(input_cfg.get("time_tolerance", 1e-9))
    matches = [step for step in index["steps"] if abs(float(step["time"]) - float(requested)) <= tolerance]
    if len(matches) != 1:
        available = [step["time"] for step in index["steps"]]
        raise KeyError(f"Time {requested} not uniquely present in {index_path}; available: {available}")
    source = Path(matches[0]["path"])
    if not source.is_absolute():
        source = index_path.parent / source
    return source, float(matches[0]["time"])


def _array_location(mesh, name: str, requested: str | None = None) -> str:
    found = [where for where, arrays in (("point", mesh.point_data), ("cell", mesh.cell_data)) if name in arrays]
    if requested:
        if requested not in found:
            raise KeyError(f"{name!r} is not available in requested {requested} data; found {found}")
        return requested
    if len(found) != 1:
        raise KeyError(f"{name!r} is absent or ambiguous across PointData/CellData: {found}; set processing.location")
    return found[0]


def surface_input(config: dict[str, Any], base: Path, time: float | None = None) -> Path | None:
    source = config.get("input", {}).get("surface")
    return _data_path(source, config, base, time) if source else None


def surface_path(config: dict[str, Any], base: Path, time: float | None = None) -> Path:
    output = config.get("output", {}).get("surface")
    if output:
        return _data_path(output, config, base, time)
    input_cfg = config.get("input", {})
    if not input_cfg.get("path") and not input_cfg.get("time_index"):
        raise ValueError("q extract requires input.path or input.surface")
    stamp = "" if time is None else f"_t{time:.6f}"
    return _data_path(f"q_surface{stamp}.vtp", config, base)


def processing_fingerprint(config: dict[str, Any], source: Path, time: float | None) -> str:
    signature = vtk_dependency_signature(source) if source.suffix.lower() == ".vtm" else file_signature(source)
    return fingerprint({"format_version": FORMAT_VERSION, "source": signature, "time": time,
                        "q_algorithm": "vtk.compute_derivative(qcriterion)",
                        "processing": config.get("processing", {}), "input": config.get("input", {})})


def extract(config: dict[str, Any], base: str | Path = ".", time: float | None = None, force: bool = False) -> Path:
    """Extract a Q isosurface and cache it only for an identical physical job."""
    base = Path(base); time = time if time is not None else config.get("time")
    ready = surface_input(config, base, time)
    if ready and ready.suffix.lower() == ".vtp" and not config.get("input", {}).get("path"):
        return ready
    source, resolved_time = _time_index_source(config, base, time)
    time = resolved_time
    target = surface_path(config, base, time)
    key = processing_fingerprint(config, source, time)
    record = read_record(target)
    if not force and target.is_file() and record and record.get("fingerprint") == key:
        return target
    input_cfg = config.get("input", {})
    selector = input_cfg.get("block", input_cfg.get("region", config["processing"].get("block")))
    mesh = select_dataset(Data3D.from_file(source, time=time).mesh, selector).copy()
    proc = config["processing"]
    q_name = proc.get("q_field", "Q")
    location = _array_location(mesh, q_name, proc.get("location")) if q_name in mesh.array_names else None
    q_input_location = location
    q_cell_to_point = False
    velocity = proc.get("velocity_field", "U")
    velocity_input_location = None
    velocity_cell_to_point = False
    algorithm = "input-field"
    if location == "cell":
        mesh = mesh.cell_data_to_point_data(pass_cell_data=True)
        location = "point"
        q_cell_to_point = True
        algorithm = "input-field-cell-to-point-for-contour"
    if location is None:
        velocity_location = _array_location(mesh, velocity, proc.get("velocity_location"))
        velocity_input_location = velocity_location
        if velocity_location == "cell":
            mesh = mesh.cell_data_to_point_data(pass_cell_data=True)
            velocity_cell_to_point = True
        if velocity not in mesh.point_data:
            raise ValueError(f"Cannot compute Q: point velocity {velocity!r} unavailable after conversion")
        mesh = mesh.compute_derivative(scalars=velocity, gradient=False, qcriterion=q_name, preference="point")
        algorithm = "vtk.compute_derivative(qcriterion); velocity gradient may differ from OpenFOAM discretization"
    if velocity in mesh.point_data and proc.get("speed_field", "speed") not in mesh.point_data:
        mesh.point_data[proc.get("speed_field", "speed")] = np.linalg.norm(np.asarray(mesh.point_data[velocity]), axis=1)
    iso = float(proc.get("iso", proc.get("q_iso", 0.0)))
    surface = mesh.contour(isosurfaces=[iso], scalars=q_name)
    if surface.n_points == 0:
        raise ValueError(f"No Q isosurface at {iso}; Q range is {np.nanmin(mesh.point_data[q_name]):.6g}..{np.nanmax(mesh.point_data[q_name]):.6g}")
    target.parent.mkdir(parents=True, exist_ok=True)
    surface.save(target, binary=True)
    write_record(target, {"kind": "q-surface", "format_version": FORMAT_VERSION, "fingerprint": key,
                          "source": vtk_dependency_signature(source) if source.suffix.lower() == ".vtm" else file_signature(source), "time": time, "q_field": q_name,
                          "iso": iso, "algorithm": algorithm, "field_location": location,
                          "q_input_location": q_input_location, "q_cell_to_point": q_cell_to_point,
                          "velocity_field": velocity, "velocity_input_location": velocity_input_location,
                          "velocity_cell_to_point": velocity_cell_to_point,
                          "gradient_algorithm": "vtk.compute_derivative(qcriterion)" if q_input_location is None else None})
    return target


def camera_from_file(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {"position", "focal_point", "viewup", "parallel_projection", "parallel_scale", "view_angle"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"Camera is missing: {sorted(missing)}")
    return data


def apply_camera(plotter, camera: dict[str, Any]) -> None:
    plotter.camera_position = [camera["position"], camera["focal_point"], camera["viewup"]]
    plotter.camera.parallel_projection = bool(camera["parallel_projection"])
    plotter.camera.parallel_scale = float(camera["parallel_scale"])
    plotter.camera.view_angle = float(camera["view_angle"])
    plotter.reset_camera_clipping_range()


def save_camera(plotter, path: str | Path) -> Path:
    camera = plotter.camera
    data = {"position": list(map(float, camera.position)), "focal_point": list(map(float, camera.focal_point)),
            "viewup": list(map(float, camera.up)), "parallel_projection": bool(camera.parallel_projection),
            "parallel_scale": float(camera.parallel_scale), "view_angle": float(camera.view_angle)}
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _default_camera() -> dict[str, Any]:
    return {"position": [1.0, 1.0, 1.0], "focal_point": [0.0, 0.0, 0.0],
            "viewup": [0.0, 0.0, 1.0], "parallel_projection": False,
            "parallel_scale": 1.0, "view_angle": 30.0}


def _camera_value(value: Any, base: Path, time: float | None = None) -> dict[str, Any]:
    if isinstance(value, dict):
        missing = {"position", "focal_point", "viewup", "parallel_projection", "parallel_scale", "view_angle"} - value.keys()
        if missing:
            raise ValueError(f"Camera is missing: {sorted(missing)}")
        return deepcopy(value)
    if value:
        return camera_from_file(_path(value, base, time))
    return _default_camera()


def _view_path(config: dict[str, Any], base: Path) -> Path | None:
    value = config.get("view") or config.get("presentation", {}).get("view")
    return _path(value, base) if value else None


def load_view(path: str | Path) -> dict[str, Any]:
    """Load only versioned, declarative Q presentation state."""
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid Q view JSON: {path}") from exc
    if value.get("format") != VIEW_FORMAT or value.get("version") != VIEW_VERSION:
        raise ValueError(f"Unsupported Q view format in {path}; expected {VIEW_FORMAT} v{VIEW_VERSION}")
    if not isinstance(value.get("camera"), dict) or not isinstance(value.get("scene", {}), dict):
        raise ValueError(f"Q view {path} needs object-valued camera and scene")
    _camera_value(value["camera"], path.parent)
    return value


def write_view(path: str | Path, camera: dict[str, Any], scene: dict[str, Any]) -> Path:
    """Persist portable visual state, never mesh/data paths or VTK objects."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    _camera_value(camera, path.parent)
    payload = {"format": VIEW_FORMAT, "version": VIEW_VERSION,
               "camera": camera, "scene": scene}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _presentation(config: dict[str, Any], base: Path, time: float | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge a view overlay into declarative scene defaults without data work."""
    scene = deepcopy(config.get("scene", {}))
    camera = _camera_value(config.get("camera", scene.pop("camera", None)), base, time)
    view_path = _view_path(config, base)
    if view_path and view_path.is_file():
        view = load_view(view_path)
        scene.update(deepcopy(view.get("scene", {})))
        camera = deepcopy(view["camera"])
    return scene, camera


def _write_yaml(path: Path, value: dict[str, Any]) -> Path:
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _preview_surface(config: dict[str, Any], base: Path) -> Path | None:
    value = config.get("preview", {}).get("surface")
    return _path(value, base) if value else None


def _decimate_preview(surface, options: dict[str, Any]):
    """Return a separate, display-only copy while retaining scalar arrays."""
    maximum = options.get("max_points")
    target_mb = options.get("target_size_mb")
    if maximum is None and target_mb is not None:
        # Geometry byte size scales approximately with points for a surface.
        maximum = max(100, int(surface.n_points * float(target_mb) * 1024 * 1024 / max(surface.n_points * 48, 1)))
    maximum = int(maximum) if maximum is not None else 100_000
    if surface.n_points <= maximum:
        return surface.copy(deep=True), {"method": "copy", "max_points": maximum, "input_points": int(surface.n_points), "output_points": int(surface.n_points)}
    reduction = max(0.0, min(0.99, 1.0 - maximum / float(surface.n_points)))
    try:
        preview = surface.decimate_pro(reduction, preserve_topology=True)
    except TypeError:  # PyVista versions differ in their optional arguments.
        preview = surface.decimate_pro(reduction)
    return preview, {"method": "vtk.decimate_pro", "max_points": maximum, "reduction": reduction,
                     "input_points": int(surface.n_points), "output_points": int(preview.n_points)}


def prepare(config: dict[str, Any], base: str | Path = ".", out: str | Path = "preview",
            time: float | None = None, force: bool = False) -> Path:
    """Create a movable desktop preview package from full Q data.

    The package deliberately contains only simplified geometry and presentation
    state.  Its scene stores a relative ``data_root`` mapping back to the
    full-resolution derived surface, so a later Freeze never renders preview
    geometry as scientific output.
    """
    import pyvista as pv
    base = Path(base); out = Path(out)
    if not out.is_absolute(): out = base / out
    time = time if time is not None else config.get("time")
    full_surface = surface_input(config, base, time) or extract(config, base, time, force=force)
    full_surface = Path(full_surface)
    if not full_surface.is_file():
        raise FileNotFoundError(f"Full Q surface not found: {full_surface}")
    out.mkdir(parents=True, exist_ok=True)
    preview, strategy = _decimate_preview(pv.read(full_surface), config.get("preview", {}))
    color_field = config.get("scene", {}).get("color_field", config.get("scene", {}).get("scalars", "speed"))
    if color_field not in preview.point_data and color_field not in preview.cell_data:
        raise KeyError(f"Preview surface lacks required coloring field {color_field!r}")
    preview_path = out / "preview.vtp"; preview.save(preview_path, binary=True)
    source_root = full_surface.parent.resolve()
    scene_config = {
        "kind": "q", "workflow": "prepare-edit-freeze-v1",
        "data_root": _relative(source_root, out),
        "input": {"surface": full_surface.name},
        "time": time, "processing": deepcopy(config.get("processing", {})),
        "derived": {"surface": full_surface.name,
                    "fingerprint": (read_record(full_surface) or {}).get("fingerprint")},
        "scene": deepcopy(config.get("scene", {})),
        "output": {"image": "render.png"}, "preview": {"surface": "preview.vtp", "strategy": strategy},
        "view": "view.json",
    }
    camera = _camera_value(config.get("camera", config.get("scene", {}).get("camera")), base, time)
    write_view(out / "view.json", camera, scene_config["scene"])
    _write_yaml(out / "scene.yml", scene_config)
    dependency = vtk_dependency_signature(full_surface) if full_surface.suffix.lower() == ".vtm" else file_signature(full_surface)
    manifest = {"format": "pypost-preview-package", "format_version": 1,
                "data_protocol_version": FORMAT_VERSION, "physical_time": time,
                "full_data": {"kind": "derived-q-surface", "path": _relative(full_surface, out), "signature": dependency},
                "preview_data": {"path": "preview.vtp", "strategy": strategy, "signature": file_signature(preview_path)},
                "presentation": {"scene": "scene.yml", "view": "view.json"},
                "software": {"python": sys.version.split()[0], "pypost_format_version": FORMAT_VERSION}}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def freeze(scene_path: str | Path, out: str | Path) -> Path:
    """Merge scene defaults and a view overlay into portable final Q YAML."""
    scene_path = Path(scene_path); base = scene_path.parent
    config = load_config(scene_path)
    if config.get("kind") != "q":
        raise ValueError("freeze expects a Q preview scene with kind: q")
    full_surface = surface_input(config, base, config.get("time"))
    if not full_surface or not full_surface.is_file():
        raise FileNotFoundError("Freeze cannot find the full-resolution input.surface; set data_root or restore the data dependency.")
    preview = _preview_surface(config, base)
    if preview and full_surface.resolve() == preview.resolve():
        raise ValueError("Refusing to freeze preview.vtp as final scientific source")
    # Q extraction options are physical/derived-data state, not presentation
    # state.  A changed threshold must be Prepared again instead of producing
    # a misleading final YAML over a stale surface.
    record = read_record(full_surface) or {}
    expected_iso = config.get("processing", {}).get("iso", config.get("processing", {}).get("q_iso"))
    if expected_iso is not None and record.get("iso") is not None and float(expected_iso) != float(record["iso"]):
        raise ValueError("Q threshold differs from the prepared full surface; update the source Q configuration and run `pypost prepare` again.")
    expected_fingerprint = config.get("derived", {}).get("fingerprint")
    if expected_fingerprint and record.get("fingerprint") and expected_fingerprint != record["fingerprint"]:
        raise ValueError("The prepared full Q surface changed; run `pypost prepare` again before Freeze.")
    view_path = _view_path(config, base)
    if not view_path or not view_path.is_file():
        raise FileNotFoundError("Freeze needs view.json; run prepare or restore the presentation state first.")
    view = load_view(view_path)
    target = Path(out)
    if not target.is_absolute(): target = Path.cwd() / target
    target.parent.mkdir(parents=True, exist_ok=True)
    final = deepcopy(config)
    final.pop("preview", None); final.pop("view", None); final.pop("derived", None)
    final["workflow"] = "q-final-v1"
    final["scene"].update(deepcopy(view["scene"]))
    final["camera"] = deepcopy(view["camera"])
    # Rebase relative data mapping for the new final.yml location.  No desktop
    # absolute path leaks into the frozen configuration.
    final["data_root"] = _relative(full_surface.parent, target.parent)
    final["input"] = {"surface": full_surface.name}
    _write_yaml(target, final)
    return target


def add_scene(plotter, surface, scene: dict[str, Any], time: float | None = None) -> None:
    import pyvista as pv
    plotter.set_background(scene.get("background", "white"))
    scalars = scene.get("color_field", scene.get("scalars", "speed"))
    if scalars not in surface.point_data and scalars not in surface.cell_data:
        raise KeyError(f"Surface does not contain color field {scalars!r}")
    scalar_bar = scene.get("scalar_bar", True)
    plotter.add_mesh(surface, scalars=scalars, cmap=scene.get("colormap", "coolwarm"),
                     clim=scene.get("color_limits", scene.get("clim")), opacity=float(scene.get("opacity", 1.0)),
                     show_scalar_bar=scalar_bar, scalar_bar_args=scene.get("scalar_bar_args", {}))
    sphere = scene.get("sphere")
    if sphere or scene.get("show_sphere", False):
        sphere = sphere or {"center": scene.get("sphere_center", [0, 0, 0]), "radius": scene.get("sphere_radius", .5)}
        plotter.add_mesh(pv.Sphere(center=sphere.get("center", [0, 0, 0]), radius=float(sphere.get("radius", .5))),
                         color=sphere.get("color", "lightgray"))
    if time is not None and scene.get("time_label", True):
        plotter.add_text(scene.get("time_format", "t = {time:.3f}").format(time=time), position="upper_left",
                         font_size=int(scene.get("font_size", 14)), color=scene.get("text_color", "black"))


def render_fingerprint(surface: Path, camera_path: Path | dict[str, Any], scene: dict[str, Any], time: float | None) -> str:
    """Fingerprint presentation inputs independently from Q extraction inputs."""
    camera = file_signature(camera_path) if isinstance(camera_path, Path) else camera_path
    return fingerprint({"surface": file_signature(surface), "camera": camera, "scene": scene,
                        "time": time, "image_size": scene.get("image_size", [1280, 720])})


def render(config: dict[str, Any], base: str | Path = ".", time: float | None = None, resume: bool = False) -> Path:
    from .plotting import Plot3D
    base = Path(base); time = time if time is not None else config.get("time")
    surface = surface_input(config, base, time) or extract(config, base, time)
    scene, camera = _presentation(config, base, time)
    output = _path(config.get("output", {}).get("image", "q.png"), base, time)
    key = render_fingerprint(surface, camera, scene, time)
    if resume and output.is_file() and (read_record(output) or {}).get("fingerprint") == key:
        return output
    if not Plot3D.offscreen_available():
        raise RuntimeError("Off-screen VTK rendering is unavailable (need DISPLAY, EGL, or OSMesa). Use `pypost q camera` on a desktop or configure EGL/OSMesa.")
    import pyvista as pv
    output.parent.mkdir(parents=True, exist_ok=True)
    plotter = pv.Plotter(off_screen=True, window_size=tuple(scene.get("image_size", [1280, 720])))
    try:
        add_scene(plotter, pv.read(surface), scene, time)
        apply_camera(plotter, camera)
        plotter.screenshot(output)
    finally:
        plotter.close()
    write_record(output, {"kind": "q-render", "format_version": FORMAT_VERSION, "fingerprint": key,
                          "surface": file_signature(surface), "camera": camera, "scene": scene, "time": time})
    return output


def camera_editor(config: dict[str, Any], base: str | Path = ".", time: float | None = None) -> None:
    """Open a small native Q editor; it persists visual state, never data."""
    import pyvista as pv
    base = Path(base); time = time if time is not None else config.get("time")
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise RuntimeError("`pypost edit` for Q scenes requires a graphical DISPLAY. Use `pypost prepare` and edit view.json/YAML on a desktop.")
    # A prepared scene intentionally opens its local simplified geometry.  The
    # legacy camera command continues to use the full surface.
    surface = _preview_surface(config, base) or surface_input(config, base, time) or extract(config, base, time)
    target = _view_path(config, base)
    legacy_camera = target is None
    if target is None:
        target = _path(config.get("camera", "camera.json"), base, time)
    scene, camera = _presentation(config, base, time)
    plotter = pv.Plotter(off_screen=False, window_size=tuple(config.get("scene", {}).get("image_size", [1280, 720])))
    add_scene(plotter, pv.read(surface), scene, time)
    apply_camera(plotter, camera)

    def persist():
        saved = save_camera(plotter, target) if legacy_camera else write_view(target, camera_from_plotter(plotter), scene)
        print(f"Saved presentation state: {saved}")

    # Native mouse controls perform rotate/pan/zoom.  The keys provide a small
    # dependency-free control surface; less common text/size controls remain
    # declarative YAML edits as documented.
    colormaps = ["coolwarm", "viridis", "plasma", "turbo"]
    def cycle_colormap():
        current = scene.get("colormap", "coolwarm")
        scene["colormap"] = colormaps[(colormaps.index(current) + 1) % len(colormaps)] if current in colormaps else colormaps[0]
        print(f"colormap: {scene['colormap']} (press P to save)")
    def toggle_background():
        scene["background"] = "black" if scene.get("background", "white") == "white" else "white"
        plotter.set_background(scene["background"]); plotter.render()
    def opacity(delta: float):
        scene["opacity"] = min(1.0, max(0.05, float(scene.get("opacity", 1.0)) + delta))
        print(f"opacity: {scene['opacity']:.2f} (press P to save)")
    def scalar_bar():
        scene["scalar_bar"] = not bool(scene.get("scalar_bar", True))
        print(f"scalar bar on next reopen/render: {scene['scalar_bar']} (press P to save)")
    plotter.add_key_event("p", persist); plotter.add_key_event("m", cycle_colormap)
    plotter.add_key_event("b", toggle_background); plotter.add_key_event("plus", lambda: opacity(.05))
    plotter.add_key_event("minus", lambda: opacity(-.05)); plotter.add_key_event("s", scalar_bar)
    print("Mouse: rotate/pan/zoom. P: save; M: colormap; B: background; +/-: opacity; S: scalar-bar state.")
    plotter.show()


def camera_from_plotter(plotter) -> dict[str, Any]:
    camera = plotter.camera
    return {"position": list(map(float, camera.position)), "focal_point": list(map(float, camera.focal_point)),
            "viewup": list(map(float, camera.up)), "parallel_projection": bool(camera.parallel_projection),
            "parallel_scale": float(camera.parallel_scale), "view_angle": float(camera.view_angle)}


def batch(config_path: Path, config: dict[str, Any], base: Path, resume: bool, dry_run: bool) -> list[float]:
    times = config.get("times", config.get("processing", {}).get("times", []))
    if not times and config.get("kind") == "q" and config.get("time") is not None:
        times = [config["time"]]
    if not times:
        raise ValueError("q batch needs a `times: [..]` list (or processing.times)")
    numeric_times = [float(value) for value in times]
    image_paths = [_path(config.get("output", {}).get("image", "q.png"), base, value) for value in numeric_times]
    duplicates = {str(path) for path in image_paths if image_paths.count(path) > 1}
    if duplicates:
        raise ValueError(f"Q batch image outputs are not unique: {sorted(duplicates)}; include '{{time}}' in output.image")
    if not config.get("input", {}).get("surface"):
        surface_paths = [surface_path(config, base, value) for value in numeric_times]
        duplicates = {str(path) for path in surface_paths if surface_paths.count(path) > 1}
        if duplicates:
            raise ValueError(f"Q batch surface outputs are not unique: {sorted(duplicates)}; include '{{time}}' in output.surface")
    failures = []
    retries = int(config.get("batch", {}).get("retries", 1)); timeout = float(config.get("batch", {}).get("timeout", 900))
    log_dir = _path(config.get("batch", {}).get("log_dir", "q_logs"), base)
    manifest_path = _path(config.get("batch", {}).get("manifest", "q_manifest.json"), base)
    manifest: dict[str, Any] = {"format_version": FORMAT_VERSION, "config": str(config_path), "tasks": {}}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.setdefault("tasks", {})
        except json.JSONDecodeError:
            pass
    if not dry_run:
        log_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
    for time in numeric_times:
        command = [sys.executable, "-m", "sciplot.cli", "q", "render", "--config", str(config_path), "--time", str(time)]
        if resume: command.append("--resume")
        task_id = f"{time:.12g}"
        if dry_run:
            print(" ".join(command)); continue
        log_path = log_dir / f"q_t{time:.6f}.log"
        task = manifest["tasks"].setdefault(task_id, {"time": time, "attempts": []})
        ok = False
        for attempt in range(retries + 1):
            status: int | str
            try:
                with log_path.open("a", encoding="utf-8") as log:
                    log.write(f"\n--- attempt {attempt + 1} ---\n")
                    status = subprocess.run(command, cwd=base, timeout=timeout, stdout=log, stderr=subprocess.STDOUT).returncode
            except subprocess.TimeoutExpired:
                status = "timeout"
                with log_path.open("a", encoding="utf-8") as log:
                    log.write(f"Timed out after {timeout} seconds\n")
            task["attempts"].append({"attempt": attempt + 1, "status": status, "log": str(log_path)})
            if status == 0:
                task["status"] = "ok"; ok = True; break
        if not ok:
            task["status"] = "failed"; failures.append(time)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return failures
