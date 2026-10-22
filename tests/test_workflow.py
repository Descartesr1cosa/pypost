import numpy as np
from sciplot import Data1D
from sciplot.workflow import apply_calculations, read_yaml


def test_yaml_and_safe_calculation(tmp_path):
    path = tmp_path / "job.yml"
    path.write_text("input: {dimension: 1, path: data.csv}\n")
    assert read_yaml(path)["input"]["dimension"] == 1
    data = apply_calculations(Data1D.from_arrays([0, 1], {"p": [1000, 2000]}),
                              [{"field": "p", "output": "p_kpa", "operation": "scale", "factor": .001}])
    assert np.allclose(data.fields["p_kpa"], [1, 2])
