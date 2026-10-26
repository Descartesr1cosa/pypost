# Q-criterion workflow: cluster → desktop → cluster

> The formal implementation is `sciplot.q` and is run with `pypost q ...`.
> `q_pipeline.py`, `q_scene.py`, and `camera_editor.py` are retained solely as
> camera.zip reference material. Use `q_surface.yml` or `q_batch.yml` in this
> directory for the supported demo workflow.

## Files

- `q_pipeline.py`: cluster-side extraction and batch rendering
- `camera_editor.py`: local desktop mouse-driven view adjustment
- `q_scene.py`: shared scene appearance and camera import/export
- `q_settings.json`: editable settings

## 1. Cluster, extract **one** timestep (no OpenGL rendering required)

Edit `q_settings.json` first: `sample_time`, `q_iso`, `sphere_center`, `sphere_radius`, `speed_range`, etc. Sphere should match the actual geometry and is a *visual representation*; not extracted from the actual mesh.

```bash
python q_pipeline.py --case /workspace/tCOM/Temp_trans sample
```

This generates `Q_sample.vtp` adjacent to `q_pipeline.py`. It also caches the isosurface under the case's `q_cache/` directory. `.vtp` stores the *iso-surface* and speed array, not the full CFD domain. Use the same `q_iso` for batch rendering.

## 2. Download and adjust on your desktop

Copy the following files to a desktop directory:

- `Q_sample.vtp`
- `camera_editor.py`
- `q_scene.py`
- `q_settings.json`

Install on your desktop:

```bash
python -m pip install pyvista numpy
python camera_editor.py
```

Use the mouse: left drag = orbit, middle drag = pan, wheel = zoom. **Press P to write `camera.json`.** Do not close without pressing P. Adjust your view with an image aspect ratio matching `image_size` in the shared settings.

For a real OpenFOAM sphere, ensure `sphere_center` and `sphere_radius` are correct. Initial view assumes the incoming flow is along **+X** and Z is vertical; mouse editing can correct any orientation.

## 3. Upload and batch render on the cluster

Copy **only `camera.json`** back to the same folder containing `q_pipeline.py` and `q_settings.json`. The `.vtp` sample does **not** need to be uploaded again.

```bash
python q_pipeline.py --case /workspace/tCOM/Temp_trans one --time 60.5
python q_pipeline.py --case /workspace/tCOM/Temp_trans batch
```

Outputs: `<case>/plots_pyvista/Q_t<time>.png`.

Each time step runs in an independent subprocess, with retries and PNG resume. Extracted surfaces are cached under `<case>/q_cache/`, so changing the view and running again does **not** require reprocessing existing cached Q contours, if you first remove old PNG files.

For a cluster with OSMesa configured:

```bash
Q_USE_OSMESA=1 python q_pipeline.py --case /workspace/tCOM/Temp_trans batch
```

For Xvfb (no OSMesa needed), for instance:

```bash
xvfb-run -a python q_pipeline.py --case /workspace/tCOM/Temp_trans batch
```

Use whichever headless rendering method you have already confirmed works. `q_pipeline.py sample` does not invoke rendering.

## Notes

- The initial +X camera assumption is for convenience. The saved `camera.json` will be authoritative in batch.
- The sphere is procedural. If the sphere geometry in your case differs, change the config or replace the geometry loading logic.
- `q_settings.json` must be **identical** on both cluster and local machine to avoid changes in color, sphere geometry and framing.
- The same `image_size` aspect ratio is important for matching framing. Window resize on desktop can change the apparent framing; save and check a single cluster PNG before batch.
- Set `q_iso` and color range once and keep them the same across all time steps.
- `Q` may be read from the OpenFOAM case or computed from the velocity field using VTK gradients; the discretizations may differ.
- OpenFOAM case should expose `internalMesh` and `U`; `case.foam` is created automatically.
