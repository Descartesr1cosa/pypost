from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]


def test_yaml_conversion_then_calculation_and_plot(tmp_path):
    raw = tmp_path / "raw.xy"
    raw.write_text("# x p\n0 1000\n1 2000\n")
    converted = tmp_path / "converted.csv"
    convert_config = tmp_path / "convert.yml"
    convert_config.write_text(f"input: {{dimension: 1, path: '{raw}'}}\noutput: {{path: '{converted}'}}\n")
    subprocess.run([sys.executable, ROOT / "examples" / "python_api" / "convert_data.py", convert_config], check=True, cwd=ROOT)
    image = tmp_path / "pressure.png"
    plot_config = tmp_path / "plot.yml"
    plot_config.write_text(
        f"input: {{dimension: 1, path: '{converted}'}}\n"
        "calculations:\n  - {field: p, output: p_kpa, operation: scale, factor: 0.001}\n"
        f"plot: {{dimension: '1', field: p_kpa, output: '{image}'}}\n"
    )
    subprocess.run([sys.executable, ROOT / "examples" / "python_api" / "calculate_and_plot.py", plot_config], check=True, cwd=ROOT)
    assert converted.exists() and image.stat().st_size > 0
