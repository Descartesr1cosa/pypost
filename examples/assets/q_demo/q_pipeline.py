"""Prepare one Q surface on a cluster and batch-render using a local camera.json.

Examples:
  python q_pipeline.py --case /path/to/case sample
  python q_pipeline.py --case /path/to/case batch
  python q_pipeline.py --case /path/to/case one --time 60.5

Set Q_USE_OSMESA=1 before launch if your cluster has working OSMesa software rendering.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

# Cluster-only opt-in. Local interactive camera editor never sets these variables.
if os.environ.get("Q_USE_OSMESA") == "1":
    os.environ.setdefault("VTK_DEFAULT_OPENGL_WINDOW", "vtkOSOpenGLRenderWindow")
    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")

from q_scene import load_settings, add_q_scene, load_camera


def get_reader(case: Path):
    import pyvista as pv

    foam_file = case / "case.foam"
    foam_file.touch(exist_ok=True)
    reader = pv.POpenFOAMReader(str(foam_file))
    reader.disable_all_patch_arrays()
    reader.enable_patch_array("internalMesh")
    reader.cell_to_point_creation = True
    return reader


def cache_filename(case: Path, t: float, cfg: dict):
    iso = format(float(cfg["q_iso"]), ".10g")
    return case / "q_cache" / f"Q_iso{iso}_t{t:.6f}.vtp"


def build_surface(case: Path, t: float, cfg: dict):
    """Heavy step: read CFD volume fields and save lightweight contour geometry."""
    import numpy as np
    import pyvista as pv

    cache = cache_filename(case, t, cfg)
    if cache.exists() and cache.stat().st_size > 128:
        print(f"[cache] {cache.name}", flush=True)
        return cache

    print(f"[read] OpenFOAM t={t:.6f}", flush=True)
    reader = get_reader(case)
    reader.set_active_time_value(float(t))
    blocks = reader.read()
    mesh = blocks["internalMesh"]

    # Q and U may originate from cell-centered OpenFOAM data.
    if "U" not in mesh.point_data or (
        "Q" in mesh.cell_data and "Q" not in mesh.point_data
    ):
        mesh = mesh.cell_data_to_point_data()

    if "U" not in mesh.point_data:
        raise ValueError(f"Velocity U missing at t={t}; fields: {mesh.array_names}")

    if "Q" not in mesh.point_data:
        print("[compute] Q from U gradient (VTK)", flush=True)
        mesh = mesh.compute_derivative(
            scalars="U", gradient=False, qcriterion="Q", preference="point"
        )

    q = np.asarray(mesh.point_data["Q"])
    print(f"[Q] min={np.nanmin(q):.5g}, max={np.nanmax(q):.5g}", flush=True)
    mesh.point_data["speed"] = np.linalg.norm(
        np.asarray(mesh.point_data["U"]), axis=1
    )
    del q

    print(f"[contour] iso={cfg['q_iso']}", flush=True)
    surface = mesh.contour(isosurfaces=[float(cfg["q_iso"])], scalars="Q")
    if surface.n_points == 0:
        raise ValueError(f"No contour at t={t}, Q_ISO={cfg['q_iso']}")

    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_name(cache.stem + ".partial.vtp")
    print(f"[save] {cache.name}: {surface.n_cells:,} cells", flush=True)
    surface.save(str(temporary), binary=True)
    temporary.replace(cache)
    return cache


def render_one(case: Path, t: float, cfg: dict, camera_path: Path):
    import pyvista as pv

    cache = build_surface(case, t, cfg)
    surface = pv.read(str(cache))

    output = case / "plots_pyvista" / f"Q_t{t:.6f}.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    # Only remove an old output after successful mesh preparation.
    if output.is_file():
        output.unlink()

    plotter = pv.Plotter(off_screen=True, window_size=cfg["image_size"])
    try:
        add_q_scene(plotter, surface, cfg, t)
        load_camera(plotter, camera_path)
        print(f"[render] {output.name}", flush=True)
        plotter.screenshot(str(output))
    finally:
        plotter.close()
    print(f"[done] {output}", flush=True)


def valid_png(path: Path):
    if not path.is_file() or path.stat().st_size < 128:
        return False
    with path.open("rb") as f:
        if f.read(8) != b"\x89PNG\r\n\x1a\n":
            return False
        f.seek(-12, 2)
        return f.read(12) == b"\x00\x00\x00\x00IEND\xaeB`\x82"


def do_batch(case: Path, cfg: dict, settings_path: Path, camera_path: Path):
    if not camera_path.is_file():
        raise FileNotFoundError(f"Upload camera.json first: {camera_path}")
    reader = get_reader(case)
    times = sorted(set(float(t) for t in reader.time_values))
    selected = [
        t for t in times if float(cfg["start_time"]) - 1e-8 <= t <= float(cfg["end_time"]) + 1e-8
    ]
    if not selected:
        raise RuntimeError(f"No timesteps in [{cfg['start_time']}, {cfg['end_time']}]")
    print(f"Found {len(selected)} steps: {selected[0]} -> {selected[-1]}", flush=True)

    logs = case / "q_export_logs"
    logs.mkdir(exist_ok=True)
    failures = []
    for i, t in enumerate(selected, 1):
        output = case / "plots_pyvista" / f"Q_t{t:.6f}.png"
        if valid_png(output):
            print(f"[{i}/{len(selected)}] SKIP {output.name}", flush=True)
            continue

        ok = False
        for attempt in range(1, int(cfg.get("max_retries", 3)) + 1):
            print(f"[{i}/{len(selected)}] t={t:.6f}, attempt={attempt}", flush=True)
            log = logs / f"Q_t{t:.6f}.log"
            cmd = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--case", str(case),
                "--settings", str(settings_path),
                "--camera", str(camera_path),
                "one", "--time", repr(t),
            ]
            with log.open("a", encoding="utf-8") as log_stream:
                log_stream.write(f"\n--- attempt {attempt} ---\n")
                log_stream.flush()
                try:
                    status = subprocess.run(
                        cmd, cwd=case, stdout=log_stream, stderr=subprocess.STDOUT,
                        timeout=900, check=False
                    ).returncode
                except subprocess.TimeoutExpired:
                    status = "TIMEOUT"
                    log_stream.write("Timed out\n")
            if status == 0 and valid_png(output):
                print(f"[OK] {output.name}", flush=True)
                ok = True
                break
            print(f"[FAILED] {t:.6f} returncode={status}; log={log}", flush=True)
            if attempt < int(cfg.get("max_retries", 3)):
                time.sleep(2)
        if not ok:
            failures.append(t)

    print(f"Done. Failed time steps ({len(failures)}): {failures}", flush=True)
    if failures:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=Path.cwd(), help="OpenFOAM case directory")
    parser.add_argument("--settings", type=Path, default=Path(__file__).with_name("q_settings.json"))
    parser.add_argument("--camera", type=Path, default=Path(__file__).with_name("camera.json"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sample", help="Prepare one .vtp without rendering")
    one = commands.add_parser("one", help="Render one time step with the saved camera")
    one.add_argument("--time", type=float, required=True)
    commands.add_parser("batch", help="Batch render all steps with retry and resume")
    args = parser.parse_args()

    case = args.case.expanduser().resolve()
    settings_path = args.settings.expanduser().resolve()
    camera_path = args.camera.expanduser().resolve()
    cfg = load_settings(settings_path)

    if args.command == "sample":
        cache = build_surface(case, float(cfg["sample_time"]), cfg)
        sample = Path(__file__).with_name("Q_sample.vtp")
        if sample.resolve() != cache.resolve():
            shutil.copy2(cache, sample)
        print(f"Sample ready: {sample}", flush=True)
    elif args.command == "one":
        render_one(case, args.time, cfg, camera_path)
    else:
        do_batch(case, cfg, settings_path, camera_path)


if __name__ == "__main__":
    main()
