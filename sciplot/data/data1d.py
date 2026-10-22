"""Readers and containers for sampled one-dimensional data."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
import re
import numpy as np
import pandas as pd


def _tokens(line: str) -> list[str]:
    return [x for x in re.split(r"[\s,;]+", line.strip().strip("#").strip()) if x]


def _is_number_row(tokens: list[str]) -> bool:
    try:
        [float(x) for x in tokens]
        return bool(tokens)
    except ValueError:
        return False


@dataclass
class Data1D:
    """Sampled data with one coordinate and named, same-length fields."""
    x: np.ndarray
    fields: dict[str, np.ndarray]
    x_name: str = "x"
    x_unit: str | None = None
    field_units: dict[str, str] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.x = np.asarray(self.x, dtype=float).reshape(-1)
        self.fields = {str(k): np.asarray(v).reshape(-1) for k, v in self.fields.items()}
        if not self.fields:
            raise ValueError("Data1D requires at least one field")
        if any(len(v) != len(self.x) for v in self.fields.values()):
            raise ValueError("Each field must have the same length as x")
        order = np.argsort(self.x)
        self.x = self.x[order]
        self.fields = {k: v[order] for k, v in self.fields.items()}

    @classmethod
    def from_arrays(cls, x, fields: Mapping[str, object], **kwargs) -> "Data1D":
        return cls(x=np.asarray(x), fields=dict(fields), **kwargs)

    @classmethod
    def from_file(cls, path: str | Path, x: str | int | None = None,
                  units: Mapping[str, str] | None = None, **kwargs) -> "Data1D":
        """Read CSV, whitespace/TAB TXT, or OpenFOAM sampled tables.

        A final comment line such as ``# x p Ux`` is used as the header when
        data rows themselves have no header, as OpenFOAM postProcessing often does.
        """
        path = Path(path)
        lines = path.read_text().splitlines()
        content = [(i, _tokens(line)) for i, line in enumerate(lines)
                   if line.strip() and not line.lstrip().startswith("#")]
        if not content or not _is_number_row(content[0][1]):
            frame = pd.read_csv(path, sep=None, engine="python", comment="#")
        else:
            comments = [_tokens(line) for line in lines[:content[0][0]]
                        if line.lstrip().startswith("#")]
            header = comments[-1] if comments and len(comments[-1]) == len(content[0][1]) else None
            frame = pd.read_csv(path, sep=r"[\s,;]+", engine="python", comment="#", header=None)
            frame.columns = header or [f"column_{i}" for i in range(frame.shape[1])]
        frame = frame.apply(pd.to_numeric, errors="raise")
        x_name = frame.columns[0] if x is None else (frame.columns[x] if isinstance(x, int) else x)
        if x_name not in frame:
            raise KeyError(f"Coordinate {x_name!r} not in {list(frame.columns)}")
        return cls(frame[x_name].to_numpy(),
                   {str(c): frame[c].to_numpy() for c in frame.columns if c != x_name},
                   x_name=str(x_name), field_units=dict(units or {}),
                   metadata={"source": str(path)}, **kwargs)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame({self.x_name: self.x, **self.fields})

    def save_csv(self, path: str | Path) -> None:
        self.to_frame().to_csv(path, index=False)
