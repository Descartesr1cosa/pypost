"""Small, deterministic provenance helpers shared by CLI workflows."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any


FORMAT_VERSION = 1


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def fingerprint(value: Any) -> str:
    payload = json.dumps(jsonable(value), sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def file_signature(path: str | Path) -> dict[str, Any]:
    path = Path(path).resolve()
    stat = path.stat()
    # mtime and size make cache checks cheap; an optional content hash would be
    # excessive for CFD volumes and is intentionally not the default.
    return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def sidecar(path: str | Path) -> Path:
    path = Path(path)
    return path.with_suffix(path.suffix + ".pypost.json")


def read_record(path: str | Path) -> dict[str, Any] | None:
    target = sidecar(path)
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def write_record(path: str | Path, record: dict[str, Any]) -> None:
    target = sidecar(path)
    target.write_text(json.dumps(jsonable(record), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
