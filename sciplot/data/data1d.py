"""Readers and containers for sampled one-dimensional data."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
import json
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
    sort: bool = True

    def __post_init__(self):
        # Keep an incoming float32/float64 dtype and vector component axis.
        # Readers retain the historical sorted behavior; strict NPZ loading
        # opts out explicitly so storage never reorders a recorded sample.
        self.x = np.asarray(self.x).reshape(-1)
        if not np.issubdtype(self.x.dtype, np.number):
            raise TypeError(f"Data1D coordinate must be numeric, got {self.x.dtype}")
        self.fields = {str(k): _field_array(v) for k, v in self.fields.items()}
        if not self.fields:
            raise ValueError("Data1D requires at least one field")
        if any(v.shape[0] != len(self.x) for v in self.fields.values()):
            raise ValueError("Each field must have the same length as x")
        if self.sort:
            order = np.argsort(self.x, kind="stable")
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
        sidecar = path.with_suffix(path.suffix + ".json")
        stored = {}
        if sidecar.is_file():
            try:
                stored = json.loads(sidecar.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid 1-D metadata sidecar: {sidecar}") from exc
        metadata = dict(stored.get("metadata", {}))
        metadata["source"] = str(path)
        combined_units = dict(stored.get("field_units", {}))
        combined_units.update(units or {})
        return cls(frame[x_name].to_numpy(),
                   {str(c): frame[c].to_numpy() for c in frame.columns if c != x_name},
                   x_name=str(stored.get("x_name", x_name)),
                   x_unit=stored.get("x_unit"), field_units=combined_units,
                   metadata=metadata, **kwargs)

    def to_frame(self) -> pd.DataFrame:
        vector = [name for name, values in self.fields.items() if values.ndim != 1]
        if vector:
            raise ValueError("CSV stores scalar 1-D fields only; use save_dataset(..., '.npz') for vector/tensor fields: " + ", ".join(vector))
        return pd.DataFrame({self.x_name: self.x, **self.fields})

    def save_csv(self, path: str | Path, metadata: bool = True) -> None:
        """Save the portable CSV representation and its optional JSON sidecar.

        The CSV remains a plain table for spreadsheet interoperability.  Units,
        provenance and normalization notes deliberately live beside it instead
        of being hidden in a non-standard CSV dialect.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.to_frame().to_csv(path, index=False)
        if metadata:
            record = {
                "format": "pypost-1d",
                "format_version": 1,
                "x_name": self.x_name,
                "x_unit": self.x_unit,
                "field_units": self.field_units,
                "metadata": self.metadata,
            }
            path.with_suffix(path.suffix + ".json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )


def _field_array(values: object) -> np.ndarray:
    array = np.asarray(values)
    if array.ndim == 0: return array.reshape(1)
    if not np.issubdtype(array.dtype, np.number):
        raise TypeError(f"Data1D field must be numeric, got {array.dtype}")
    return array
