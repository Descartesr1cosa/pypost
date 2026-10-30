"""YAML front-end tests use a tiny manifest and never access user case data."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from examples.converters.mercury import converter


def _case(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "case"
    static = root / "DATA_bin"; data = root / "DATA_archive" / "step"
    static.mkdir(parents=True); data.mkdir(parents=True)
    manifest = {
        "format_name": "MPCNS_PostData", "format_version": 3,
        "endianness": "little", "float_type": "float64", "index_type": "int64",
        "number_of_ranks": 1,
        "fields": [{"name": name} for name in ("Badd_xi", "Badd_eta", "Badd_zeta")],
        "files": {key: [f"{key}.bin"] for key in ("geometry", "topology", "reconstruction", "constant_field")},
        "existing_dynamic_data": {"fields": [{"name": field} for field in ("B_xi", "B_eta", "B_zeta", "U_H", "U_Na")]},
    }
    (static / "manifest.json").write_text(json.dumps(manifest))
    for name in ("geometry.bin", "topology.bin", "reconstruction.bin", "constant_field.bin"):
        (static / name).write_bytes(b"stub")
    (data / "flow_field0000.bin").write_bytes(b"stub")
    return root, data


def _write_config(tmp_path: Path, root: Path, **updates) -> Path:
    config = {
        "kind": "mercury-data3d", "paths": {"data_root": str(root)},
        "input": {"static_dir": "DATA_bin", "data_dir": "DATA_archive/step"},
        "fields": ["B_induced"], "output": {"path": "processed/result.vtu"},
        "runtime": {"memory_budget_gb": 2, "temp_dir": "processed/tmp"},
    }
    config.update(updates)
    path = tmp_path / "mercury.yml"; path.write_text(yaml.safe_dump(config, sort_keys=False))
    return path


def test_mercury_yaml_resolves_all_relative_paths_from_data_root(tmp_path):
    root, _ = _case(tmp_path)
    request = converter.load_yaml_config(_write_config(tmp_path, root))
    assert request["static_dir"] == root / "DATA_bin"
    assert request["data_dir"] == root / "DATA_archive" / "step"
    assert request["output"] == root / "processed" / "result.vtu"
    assert request["temp_dir"] == root / "processed" / "tmp"


def test_mercury_yaml_preflight_passes_existing_converter_arguments(tmp_path, monkeypatch):
    root, _ = _case(tmp_path)
    config = _write_config(tmp_path, root)
    called = {}

    def fake_convert(**kwargs):
        called.update(kwargs)
        return kwargs["output"]

    monkeypatch.setattr("examples.converters.mercury.low_memory.convert", fake_convert)
    assert converter.convert_from_config(config) == root / "processed" / "result.vtu"
    assert called["fields"] == ["B_induced"]
    assert called["memory_budget_gb"] == 2
    assert called["temp_dir"] == root / "processed" / "tmp"


def test_mercury_yaml_passes_region_and_extended_fields_to_the_single_backend(tmp_path, monkeypatch):
    root, _ = _case(tmp_path)
    config = _write_config(tmp_path, root, fields=["B_total", "E_generalized"], region="fluid")
    called = {}

    def fake_convert(**kwargs):
        called.update(kwargs)
        return kwargs["output"]

    from examples.converters.mercury import low_memory
    monkeypatch.setattr(low_memory, "convert", fake_convert)
    assert converter.convert_from_config(config) == root / "processed" / "result.vtu"
    assert called["fields"] == ["B_total", "E_generalized"] and called["region"] == "fluid"


def test_fluid_only_fields_are_never_written_over_solid_cells():
    from examples.converters.mercury.low_memory import resolve_region
    assert resolve_region(["H_density", "B_total"], "auto") == "fluid"
    assert resolve_region(["B_total", "J_induced"], "auto") == "all"
    assert resolve_region(["B_total"], "solid") == "solid"
    for name in ("H_pressure", "E_Hall"):
        with pytest.raises(ValueError, match="undefined in Solid"):
            resolve_region([name], "all")


def test_mercury_yaml_rejects_bad_output_and_missing_fields_before_conversion(tmp_path):
    root, _ = _case(tmp_path)
    bad_output = _write_config(tmp_path, root, output={"path": "processed"})
    with pytest.raises(ValueError, match=".vtu"):
        converter.convert_from_config(bad_output)
    missing = _write_config(tmp_path, root, fields=["not_a_mercury_field"])
    with pytest.raises(ValueError, match="Unknown output fields"):
        converter.convert_from_config(missing)


def test_mercury_yaml_rejects_output_directory_existing_result_and_unavailable_raw_field(tmp_path):
    root, _ = _case(tmp_path)
    output_dir = root / "processed"; output_dir.mkdir()
    directory = _write_config(tmp_path, root, output={"path": "processed"})
    with pytest.raises(ValueError, match=".vtu"):
        converter.convert_from_config(directory)
    result = output_dir / "result.vtu"; result.write_bytes(b"existing")
    existing = _write_config(tmp_path, root)
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        converter.convert_from_config(existing)
    unavailable = _write_config(tmp_path, root, fields=["H_density"])
    # Remove H raw state from the synthetic manifest while keeping B valid.
    manifest_path = root / "DATA_bin" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["existing_dynamic_data"]["fields"] = [{"name": name} for name in ("B_xi", "B_eta", "B_zeta", "U_Na")]
    manifest_path.write_text(json.dumps(manifest))
    result.unlink()
    with pytest.raises(ValueError, match="does not provide raw field"):
        converter.convert_from_config(unavailable)


def test_nondimensional_twins_and_dependencies():
    from examples.converters.mercury import low_memory as lm
    assert lm.with_nondimensional(["B_total", "plasma_beta"], "both") == ["B_total", "B_total_nd", "plasma_beta"]
    assert lm.with_nondimensional(["B_total", "plasma_beta"], "only") == ["B_total_nd", "plasma_beta"]
    assert lm.with_nondimensional(["H_density"], "none") == ["H_density"]
    with pytest.raises(ValueError):
        lm.with_nondimensional(["H_density"], "sometimes")
    # twins share the dimensional field's solver ingredients and fluid-only domain
    assert lm.raw_fields("E_Hall_nd") == lm.raw_fields("E_Hall") == {"U_H", "U_Na", "B_xi", "B_eta", "B_zeta"}
    assert lm.raw_fields("magnetic_pressure") == {"B_xi", "B_eta", "B_zeta"} and lm.needs_constant_fields("magnetic_pressure")
    assert lm.resolve_region(["magnetic_pressure_nd", "J_induced_nd"], "auto") == "all"
    assert lm.resolve_region(["dynamic_pressure_nd"], "auto") == "fluid"


def test_nondimensional_scales_match_manifest_references():
    from examples.converters.mercury.low_memory import nondimensional_scales
    norm = {"density_ref": 2.0, "velocity_ref": 1e5, "pressure_ref": 4.0, "magnetic_field_ref": 1e-9,
            "current_density_ref": 1e-10, "electric_field_ref": 1e-4, "temperature_ref": 100.0, "length_ref": 2.0}
    scales = nondimensional_scales(norm, {"particle_mass_H": 1e-27})
    assert scales["pressure"]["to_nondimensional"] == pytest.approx(1e-9 / 4.0)       # nPa -> Pa / ref
    assert scales["velocity"]["to_nondimensional"] == pytest.approx(1e3 / 1e5)        # km/s -> m/s / ref
    assert scales["magnetic_field"]["to_nondimensional"] == pytest.approx(1.0)        # nT -> T / 1e-9
    assert scales["number_density"]["to_nondimensional"] == pytest.approx(1e6 * 1e-27 / 2.0)


def test_curvilinear_gradient_is_exact_on_a_skewed_grid():
    import numpy as np
    from examples.converters.mercury.low_memory import _curvilinear_gradient
    xi, eta, zeta = np.meshgrid(*[np.arange(n, dtype=float) for n in (7, 8, 9)], indexing="ij")
    xyz = np.stack([xi + 0.4 * eta, 0.5 * xi + eta + 0.2 * zeta, 0.3 * eta + zeta + 0.001 * xi ** 2], axis=-1)
    exact = np.array([1.0, -2.0, 0.5])
    np.testing.assert_allclose(_curvilinear_gradient(xyz, xyz @ exact), np.broadcast_to(exact, xyz.shape), atol=1e-12)


def test_hall_model_switch_keeps_data_and_solver_variants():
    from examples.converters.mercury import low_memory as lm
    fields = ["E_motional", "E_Hall", "E_generalized", "B_total"]
    assert lm.with_hall_model(fields, "data") == fields
    assert lm.with_hall_model(fields, "solver") == ["E_motional", "E_Hall_solver", "E_generalized_solver", "B_total"]
    assert lm.with_hall_model(fields, "both") == ["E_motional", "E_Hall", "E_Hall_solver", "E_generalized", "E_generalized_solver", "B_total"]
    assert lm.with_nondimensional(["E_Hall_solver", "hall_taper", "ion_Hall_force"], "both") == [
        "E_Hall_solver", "E_Hall_solver_nd", "hall_taper", "ion_Hall_force", "ion_Hall_force_nd"]
    with pytest.raises(ValueError):
        lm.with_hall_model(fields, "maybe")


def test_solver_model_fields_demand_case_parameters_instead_of_guessing():
    from examples.converters.mercury import low_memory as lm
    assert lm.check_solver_model(["E_Hall", "B_total"], None) is None            # data-only requests need nothing
    for name in ("E_Hall_solver", "hall_taper", "ion_Hall_force_nd", "electron_number_density_reg"):
        with pytest.raises(ValueError, match="solver_model"):
            lm.check_solver_model([name], {"hall_taper_r_min": 1.3})
    model = lm.check_solver_model(["E_Hall_solver"], {"hall_taper_r_min": 1.3, "hall_taper_r_max": 1.7, "ne_hall_floor": 0.01})
    assert model == {"hall_taper_r_min": 1.3, "hall_taper_r_max": 1.7, "ne_hall_floor": 0.01}
    assert lm.resolve_region(["hall_taper"], "auto") == "all" and lm.resolve_region(["E_Hall_solver"], "auto") == "fluid"
    assert lm.raw_fields("E_Hall_solver") == lm.raw_fields("E_Hall") and "ctr" in lm._NEEDS["E_Hall_solver"]


def test_yaml_hall_model_expands_fields_and_passes_solver_model(tmp_path):
    root, _ = _case(tmp_path)
    config = _write_config(tmp_path, root, fields=["E_Hall"], hall_model="both",
                           solver_model={"hall_taper_r_min": 1.3, "hall_taper_r_max": 1.7, "ne_hall_floor": 0.01})
    request = converter.load_yaml_config(config)
    assert request["fields"] == ["E_Hall", "E_Hall_solver"] and request["solver_model"]["ne_hall_floor"] == 0.01
    missing = _write_config(tmp_path, root, fields=["E_Hall"], hall_model="solver")
    with pytest.raises(ValueError, match="solver_model"):
        converter.validate_conversion_request(**{k: converter.load_yaml_config(missing)[k] for k in converter._REQUEST_KEYS})
