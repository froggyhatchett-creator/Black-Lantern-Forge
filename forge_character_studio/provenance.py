"""Provenance record for third-party base mesh assets (CC0-only for now)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from forge.hashing import canonical_json

ALLOWED_LICENSE_IDS = ("CC0-1.0",)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _require_text(name: str, value: object) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty string; got {value!r}")


def _require_sha256(value: object) -> None:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ValueError("archive_sha256 must be 64 lowercase hex characters")


@dataclass(frozen=True)
class BaseMeshRef:
    """Minimal base mesh reference embedded in a recipe or a stamped mesh."""

    source_name: str
    version: str
    archive_sha256: str

    def __post_init__(self) -> None:
        _require_text("source_name", self.source_name)
        _require_text("version", self.version)
        _require_sha256(self.archive_sha256)


@dataclass(frozen=True)
class BaseMeshProvenance:
    """Full provenance record for a base mesh archive."""

    source_name: str
    source_url: str
    version: str
    license_id: str
    archive_sha256: str
    retrieved_date: str

    def __post_init__(self) -> None:
        if self.license_id not in ALLOWED_LICENSE_IDS:
            raise ValueError(f"license_id {self.license_id!r} is not in the allowlist {ALLOWED_LICENSE_IDS}")
        _require_sha256(self.archive_sha256)
        for name in ("source_name", "source_url", "version", "retrieved_date"):
            _require_text(name, getattr(self, name))


_FIELDS = {"source_name", "source_url", "version", "license_id", "archive_sha256", "retrieved_date"}


def save_provenance(record: BaseMeshProvenance, path: str | Path) -> Path:
    path = Path(path)
    if path.suffix.lower() != ".json":
        raise ValueError("base mesh provenance path must end in .json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json({
        "source_name": record.source_name,
        "source_url": record.source_url,
        "version": record.version,
        "license_id": record.license_id,
        "archive_sha256": record.archive_sha256,
        "retrieved_date": record.retrieved_date,
    }) + b"\n")
    return path


def load_provenance(path: str | Path) -> BaseMeshProvenance:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read base mesh provenance: {exc}") from exc
    if not isinstance(data, dict) or set(data) != _FIELDS:
        raise ValueError("base mesh provenance has missing or unknown fields")
    return BaseMeshProvenance(**data)
