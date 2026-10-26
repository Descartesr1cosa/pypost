"""Shared scene construction for the local camera editor and cluster exporter."""
from __future__ import annotations

import json
from pathlib import Path


def load_settings(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def add_q_scene(plotter, surface, cfg: dict, t: float | None = None):
    """Keep scene geometry and render style identical on local/cluster machines."""
    import pyvista as pv

    if "speed" not in surface.point_data and "speed" not in surface.cell_data:
        raise ValueError("Surface lacks the 'speed' array needed for coloring")

    plotter.set_background("white")
    plotter.add_mesh(
        surface,
        scalars="speed",
        cmap=cfg["colormap"],
        clim=cfg["speed_range"],
        smooth_shading=False,  # faster for dense contour surfaces
        show_scalar_bar=True,
        scalar_bar_args={
            "title": "|U|",
            "title_font_size": int(cfg["font_size"]),
            "label_font_size": max(10, int(cfg["font_size"]) - 3),
            "color": "black",
        },
    )

    if cfg.get("show_sphere", True):
        sphere = pv.Sphere(
            center=cfg["sphere_center"],
            radius=float(cfg["sphere_radius"]),
            theta_resolution=48,
            phi_resolution=32,
        )
        plotter.add_mesh(sphere, color="lightgray", smooth_shading=True)

    if t is not None:
        plotter.add_text(
            f"t* = {t:.3f}",
            position="upper_left",
            font_size=max(10, int(cfg["font_size"]) - 2),
            color="black",
        )


def choose_initial_camera(plotter, surface, cfg: dict):
    """Default viewpoint for +X streamwise flow, -Y observer, Z vertical."""
    x0, x1, y0, y1, z0, z1 = map(float, surface.bounds)
    sc = cfg["sphere_center"]
    rad = float(cfg["sphere_radius"]) if cfg.get("show_sphere", True) else 0.0

    xmin, xmax = min(x0, sc[0] - rad), max(x1, sc[0] + rad)
    ymin, ymax = min(y0, sc[1] - rad), max(y1, sc[1] + rad)
    zmin, zmax = min(z0, sc[2] - rad), max(z1, sc[2] + rad)
    sx, sy, sz = xmax - xmin, ymax - ymin, zmax - zmin
    extent = max(sx, sy, sz, 1.0)
    focal = ((xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2)

    # Along -Y: world +X points right on screen when view-up is world +Z.
    position = (focal[0], focal[1] - 3.0 * extent, focal[2] + 0.20 * extent)
    plotter.camera_position = [position, focal, (0.0, 0.0, 1.0)]
    plotter.enable_parallel_projection()
    image_width, image_height = cfg["image_size"]
    aspect = image_width / image_height
    plotter.camera.parallel_scale = 0.58 * max(sz, sx / aspect, 0.5)
    plotter.reset_camera_clipping_range()


def load_camera(plotter, camera_file: str | Path):
    """Apply the exact camera recorded by the interactive local editor."""
    with Path(camera_file).open(encoding="utf-8") as f:
        camera = json.load(f)
    plotter.camera_position = [
        camera["position"], camera["focal_point"], camera["viewup"]
    ]
    plotter.camera.parallel_projection = bool(camera["parallel_projection"])
    plotter.camera.parallel_scale = float(camera["parallel_scale"])
    if "view_angle" in camera:
        plotter.camera.view_angle = float(camera["view_angle"])
    plotter.reset_camera_clipping_range()


def save_camera(plotter, camera_file: str | Path):
    """Store view orientation, framing and projection as portable JSON."""
    cam = plotter.camera
    camera = {
        "position": list(map(float, cam.position)),
        "focal_point": list(map(float, cam.focal_point)),
        "viewup": list(map(float, cam.up)),
        "parallel_projection": bool(cam.parallel_projection),
        "parallel_scale": float(cam.parallel_scale),
        "view_angle": float(cam.view_angle),
    }
    Path(camera_file).write_text(
        json.dumps(camera, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Saved camera: {Path(camera_file).resolve()}", flush=True)
