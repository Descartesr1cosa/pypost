"""Run on a desktop computer: rotate the sample and press P to save the camera."""
from __future__ import annotations

import argparse
from pathlib import Path

import pyvista as pv
from q_scene import load_settings, add_q_scene, choose_initial_camera, load_camera, save_camera


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", type=Path, default=Path("Q_sample.vtp"))
    parser.add_argument("--settings", type=Path, default=Path("q_settings.json"))
    parser.add_argument("--camera", type=Path, default=Path("camera.json"))
    args = parser.parse_args()
    cfg = load_settings(args.settings)
    surface = pv.read(str(args.surface))
    print(f"Sample: {surface.n_points:,} points, {surface.n_cells:,} cells")

    plotter = pv.Plotter(off_screen=False, window_size=cfg["image_size"])
    add_q_scene(plotter, surface, cfg, cfg["sample_time"])
    if args.camera.is_file():
        load_camera(plotter, args.camera)
        print("Existing camera.json loaded; you can refine it.")
    else:
        choose_initial_camera(plotter, surface, cfg)

    def on_press_p():
        save_camera(plotter, args.camera)
        print("You may close the window and upload camera.json to the cluster.")

    plotter.add_key_event("p", on_press_p)
    print("Mouse left: rotate; middle: pan; wheel: zoom; P: save camera")
    plotter.show()


if __name__ == "__main__":
    main()
