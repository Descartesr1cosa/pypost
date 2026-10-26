"""Headless coverage for the portable Q Prepare/Edit/Freeze boundary."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from sciplot.cli import main
from sciplot.q import extract, freeze, load_view, prepare, write_view
from sciplot.workflow import read_yaml


pv = pytest.importorskip("pyvista")


def _camera():
    return {"position": [2, 2, 2], "focal_point": [0, 0, 0], "viewup": [0, 0, 1],
            "parallel_projection": False, "parallel_scale": 1.0, "view_angle": 30.0}


def _surface(path: Path):
    mesh = pv.Sphere(theta_resolution=36, phi_resolution=36)
    mesh.point_data["speed"] = np.linalg.norm(mesh.points, axis=1)
    mesh.save(path)


def test_prepare_freeze_keeps_full_and_preview_data_separate(tmp_path):
    full = tmp_path / "full.vtp"; _surface(full)
    config = {"input": {"surface": "full.vtp"}, "time": 60.5, "camera": _camera(),
              "scene": {"color_field": "speed", "colormap": "viridis", "image_size": [320, 240]},
              "preview": {"max_points": 100}}
    package = prepare(config, tmp_path, "preview")
    assert {path.name for path in package.iterdir()} >= {"scene.yml", "preview.vtp", "view.json", "manifest.json"}
    assert pv.read(package / "preview.vtp").n_points <= 110
    assert pv.read(full).n_points > pv.read(package / "preview.vtp").n_points
    manifest = json.loads((package / "manifest.json").read_text())
    assert manifest["full_data"]["kind"] == "derived-q-surface"
    assert manifest["preview_data"]["path"] == "preview.vtp"
    final = freeze(package / "scene.yml", tmp_path / "final.yml")
    text = final.read_text()
    assert "preview.vtp" not in text
    assert "data_root:" in text and "input:" in text
    frozen = __import__("sciplot.workflow", fromlist=["read_yaml"]).read_yaml(final)
    assert frozen["camera"] == _camera()


def test_view_round_trip_and_preview_directory_can_move(tmp_path):
    full = tmp_path / "surface.vtp"; _surface(full)
    package = prepare({"input": {"surface": "surface.vtp"}, "camera": _camera(), "scene": {"color_field": "speed"}}, tmp_path, "preview")
    state = load_view(package / "view.json")
    state["scene"]["background"] = "black"
    state["camera"]["position"] = [3, 2, 1]
    write_view(package / "view.json", state["camera"], state["scene"])
    moved = tmp_path / "other" / "preview"; moved.parent.mkdir(); package.rename(moved)
    restored = load_view(moved / "view.json")
    assert restored["camera"]["position"] == [3, 2, 1]
    # The presentation package is independently editable/readable after a
    # transfer.  A later Freeze intentionally requires a configured full-data
    # root, rather than quietly falling back to preview.vtp.
    with pytest.raises(FileNotFoundError, match="full-resolution"):
        freeze(moved / "scene.yml", tmp_path / "missing-final.yml")


def test_prepare_runs_q_extraction_for_synthetic_volume_and_camera_does_not_reextract(tmp_path):
    volume = pv.ImageData(dimensions=(8, 8, 8), spacing=(.2, .2, .2))
    x, y, z = volume.points.T
    volume.point_data["U"] = np.c_[-y * (1 + z), x * (1 + z), np.zeros_like(z)]
    probe = volume.compute_derivative(scalars="U", gradient=False, qcriterion="Q", preference="point")
    q = np.asarray(probe.point_data["Q"])
    source = tmp_path / "velocity.vti"; volume.save(source)
    config = {"input": {"path": "velocity.vti"}, "camera": _camera(),
              "processing": {"velocity_field": "U", "velocity_location": "point", "q_field": "Q", "iso": float((q.min() + q.max()) / 2)},
              "scene": {"color_field": "speed"}, "output": {"surface": "full_q.vtp"}}
    package = prepare(config, tmp_path, "preview")
    full = tmp_path / "full_q.vtp"
    fingerprint = json.loads(full.with_suffix(".vtp.pypost.json").read_text())["fingerprint"]
    state = load_view(package / "view.json"); state["camera"]["position"] = [4, 3, 2]
    write_view(package / "view.json", state["camera"], state["scene"])
    freeze(package / "scene.yml", tmp_path / "final.yml")
    assert json.loads(full.with_suffix(".vtp.pypost.json").read_text())["fingerprint"] == fingerprint
    # Changing a Q threshold has a different derived-data identity and needs
    # explicit Prepare, not a silent presentation-only re-render.
    changed = dict(config); changed["processing"] = dict(config["processing"], iso=config["processing"]["iso"] * .9)
    extract(changed, tmp_path)
    assert json.loads(full.with_suffix(".vtp.pypost.json").read_text())["fingerprint"] != fingerprint


def test_freeze_requires_reprepare_when_q_threshold_was_edited(tmp_path):
    full = tmp_path / "full.vtp"; _surface(full)
    full.with_suffix(".vtp.pypost.json").write_text(json.dumps({"iso": .2, "fingerprint": "derived-a"}))
    package = prepare({"input": {"surface": "full.vtp"}, "camera": _camera(),
                       "processing": {"iso": 0.2}, "scene": {"color_field": "speed"}}, tmp_path, "preview")
    scene = read_yaml(package / "scene.yml")
    scene["processing"]["iso"] = 0.3
    import yaml
    (package / "scene.yml").write_text(yaml.safe_dump(scene, sort_keys=False))
    with pytest.raises(ValueError, match="run `pypost prepare` again"):
        freeze(package / "scene.yml", tmp_path / "final.yml")


def test_cli_prepare_freeze_and_headless_edit_message(tmp_path, monkeypatch):
    full = tmp_path / "full.vtp"; _surface(full)
    config = tmp_path / "q.yml"
    config.write_text("input: {surface: full.vtp}\ncamera: " + json.dumps(_camera()) + "\nscene: {color_field: speed}\n")
    assert main(["prepare", str(config), "--out", str(tmp_path / "preview")]) == 0
    assert main(["freeze", str(tmp_path / "preview" / "scene.yml"), "--out", str(tmp_path / "final.yml")]) == 0
    monkeypatch.delenv("DISPLAY", raising=False); monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    with pytest.raises(RuntimeError, match="graphical DISPLAY"):
        main(["edit", str(tmp_path / "preview" / "scene.yml")])

