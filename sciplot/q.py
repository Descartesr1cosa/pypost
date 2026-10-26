"""Reusable Q-criterion extraction, camera handling, and rendering workflow.

Q calculated here uses VTK's velocity-gradient implementation.  It is recorded
in metadata because it need not equal an OpenFOAM solver's discretized gradient.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

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
        return _path(path_value, base, time), time
    index_path = _path(index_value, base)
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
    return _path(source, base, time) if source else None


def surface_path(config: dict[str, Any], base: Path, time: float | None = None) -> Path:
    output = config.get("output", {}).get("surface")
    if output:
        return _path(output, base, time)
    input_cfg = config.get("input", {})
    if not input_cfg.get("path") and not input_cfg.get("time_index"):
        raise ValueError("q extract requires input.path or input.surface")
    stamp = "" if time is None else f"_t{time:.6f}"
    return _path(f"q_surface{stamp}.vtp", base)


def processing_fingerprint(config: dict[str, Any], source: Path, time: float | None) -> str:
    signature = vtk_dependency_signature(source) if source.suffix.lower() == ".vtm" else file_signature(source)
    return fingerprint({"format_version": FORMAT_VERSION, "source": signature, "time": time,
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
    algorithm = "input-field"
    if location == "cell":
        mesh = mesh.cell_data_to_point_data(pass_cell_data=True)
        location = "point"
        algorithm = "input-field-cell-to-point-for-contour"
    if location is None:
        velocity = proc.get("velocity_field", "U")
        velocity_location = _array_location(mesh, velocity, proc.get("velocity_location"))
        if velocity_location == "cell":
            mesh = mesh.cell_data_to_point_data(pass_cell_data=True)
        if velocity not in mesh.point_data:
            raise ValueError(f"Cannot compute Q: point velocity {velocity!r} unavailable after conversion")
        mesh = mesh.compute_derivative(scalars=velocity, gradient=False, qcriterion=q_name, preference="point")
        algorithm = "vtk.compute_derivative(qcriterion); velocity gradient may differ from OpenFOAM discretization"
    velocity = proc.get("velocity_field", "U")
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
                          "iso": iso, "algorithm": algorithm, "field_location": location})
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


def render_fingerprint(surface: Path, camera_path: Path, scene: dict[str, Any], time: float | None) -> str:
    """Fingerprint presentation inputs independently from Q extraction inputs."""
    return fingerprint({"surface": file_signature(surface), "camera": file_signature(camera_path), "scene": scene,
                        "time": time, "image_size": scene.get("image_size", [1280, 720])})


def render(config: dict[str, Any], base: str | Path = ".", time: float | None = None, resume: bool = False) -> Path:
    from .plotting import Plot3D
    base = Path(base); time = time if time is not None else config.get("time")
    surface = surface_input(config, base, time) or extract(config, base, time)
    camera_path = _path(config.get("camera", config.get("scene", {}).get("camera", "camera.json")), base, time)
    output = _path(config.get("output", {}).get("image", "q.png"), base, time)
    scene = config.get("scene", {})
    key = render_fingerprint(surface, camera_path, scene, time)
    if resume and output.is_file() and (read_record(output) or {}).get("fingerprint") == key:
        return output
    if not Plot3D.offscreen_available():
        raise RuntimeError("Off-screen VTK rendering is unavailable (need DISPLAY, EGL, or OSMesa). Use `pypost q camera` on a desktop or configure EGL/OSMesa.")
    import pyvista as pv
    output.parent.mkdir(parents=True, exist_ok=True)
    plotter = pv.Plotter(off_screen=True, window_size=tuple(scene.get("image_size", [1280, 720])))
    try:
        add_scene(plotter, pv.read(surface), scene, time)
        apply_camera(plotter, camera_from_file(camera_path))
        plotter.screenshot(output)
    finally:
        plotter.close()
    write_record(output, {"kind": "q-render", "format_version": FORMAT_VERSION, "fingerprint": key,
                          "surface": file_signature(surface), "camera": file_signature(camera_path), "scene": scene, "time": time})
    return output


def camera_editor(config: dict[str, Any], base: str | Path = ".", time: float | None = None) -> None:
    """Open a desktop editor; press P to persist the full camera state."""
    import pyvista as pv
    base = Path(base); time = time if time is not None else config.get("time")
    surface = surface_input(config, base, time) or extract(config, base, time)
    target = _path(config.get("camera", "camera.json"), base, time)
    plotter = pv.Plotter(off_screen=False, window_size=tuple(config.get("scene", {}).get("image_size", [1280, 720])))
    add_scene(plotter, pv.read(surface), config.get("scene", {}), time)
    if target.is_file(): apply_camera(plotter, camera_from_file(target))
    plotter.add_key_event("p", lambda: save_camera(plotter, target))
    print("Mouse: rotate/pan/zoom; press P to save camera.")
    plotter.show()


def batch(config_path: Path, config: dict[str, Any], base: Path, resume: bool, dry_run: bool) -> list[float]:
    times = config.get("times", config.get("processing", {}).get("times", []))
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
