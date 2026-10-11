"""Asset records: persisted, reproducible recipes (record_version 1).

A record says HOW to reproduce an asset. It stores no geometry: the registered
generator is the geometry authority. Reload parses, validates, regenerates,
re-derives presentation, and verifies every expectation the record carries.
Nothing is repaired, upgraded, or defaulted silently.

This module is generic (Step 2.5). Every asset-specific decision comes from the
registry:

  asset_type          -> AssetEntry (unknown = UnknownAssetTypeError, before any generation)
  generator + version -> GeneratorEntry (descriptor.generator_id must match)
  presentation_*      -> PresentationEntry (descriptor.presentation_id); its pinned
                         normals/uv/material versions must match the record exactly
  materials keys      -> descriptor.components
  conventions         -> forge.conventions[descriptor.convention_id], exact match
  preview             -> descriptor.preview_id + presentation preview_versions
  integrity keys      -> AssetEntry.integrity (+ record_content_sha256)

Schema (record_version 1). Every key is required unless marked optional:

  record_format      "black-lantern-forge/asset-record"
  record_version     1
  asset_type         registered asset type, e.g. "short_sword"
  generator          the asset type's generator id, e.g. "forge.sword"
  generator_version  registered version of that generator
  seed               decimal string in [0, 2**64-1] (a string because JSON numbers
                     above 2**53 are not portable)
  conventions        exactly the asset type's convention definition
  presentation       {presentation_version, normals_version, uv_version,
                      material_version, materials: {<component>: {...}}}
  preview            optional {preview_version, view, width, height, ssaa,
                      pixels_sha256 (optional)}
  integrity          optional {any of the asset's hash keys, record_content_sha256}
  info               optional free-form object. Informational, ignored on
                     load, excluded from every hash.

No timestamps are written, so saving the same asset twice yields byte-identical files.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from forge.catalog import REGISTRY
from forge.conventions import CONVENTIONS, CONVENTIONS_V1, convention_dict
from forge.errors import (
    InvalidSeedError,
    RecordFormatError,
    RecordIntegrityError,
    RenderError,
    UnknownGeneratorError,
)
from forge.hashing import canonical_sha256
from forge.presentation.model import PresentationVersions, PresentedSword
from forge.registry import Registry, generate_asset, integrity_hashes, present_asset, preview_for
from forge.render.settings import PreviewSettings
from forge.seed import parse_seed
from forge.versioning import require_version

RECORD_FORMAT = "black-lantern-forge/asset-record"
WRITTEN_RECORD_VERSION = 1   # the schema build_record emits (pinned; see _SCHEMAS for what loads)
MAX_RECORD_BYTES = 1_000_000
RECORD_CONTENT_KEY = "record_content_sha256"
KNOWN_CONVENTIONS = CONVENTIONS  # Step 2 name

_TOP_REQUIRED = {"record_format", "record_version", "asset_type", "generator", "generator_version",
                 "seed", "conventions", "presentation"}
_TOP_OPTIONAL = {"preview", "integrity", "info"}
_PRESENTATION_KEYS = {"presentation_version", "normals_version", "uv_version", "material_version", "materials"}
_PREVIEW_REQUIRED = {"preview_version", "view", "width", "height", "ssaa"}
_HEX64 = re.compile(r"[0-9a-f]{64}")


# ------------------------------------------------------------------ building

def compute_integrity(presented: PresentedSword, registry: Registry = REGISTRY) -> dict:
    """The asset type's registered integrity hashes for this presented asset."""
    return integrity_hashes(registry, presented)


def record_content_sha256(record: dict) -> str:
    """Canonical hash of everything authoritative in a record: all fields except
    `info` and `integrity.record_content_sha256` itself."""
    content = copy.deepcopy(record)
    content.pop("info", None)
    if "integrity" in content:
        integrity = dict(content["integrity"])
        integrity.pop(RECORD_CONTENT_KEY, None)
        if integrity:
            content["integrity"] = integrity
        else:
            del content["integrity"]
    return canonical_sha256(content)


def build_record(presented: PresentedSword, preview=None, include_integrity: bool = True,
                 forge_version: str | None = None, *, registry: Registry = REGISTRY) -> dict:
    """Build a record dict. `preview` may be a PreviewImage (settings + pixel hash) or PreviewSettings."""
    asset = presented.asset
    d = registry.asset(asset.asset_type).descriptor
    record = {
        "record_format": RECORD_FORMAT,
        "record_version": WRITTEN_RECORD_VERSION,
        "asset_type": d.asset_type,
        "generator": d.generator_id,
        "generator_version": asset.generator_version,
        "seed": str(asset.seed),
        "conventions": convention_dict(d.convention_id),
        "presentation": {**presented.versions.to_dict(), "materials": presented.materials},
    }
    if preview is not None:
        if isinstance(preview, PreviewSettings):
            record["preview"] = preview.to_dict()
        else:  # PreviewImage
            record["preview"] = {**preview.settings.to_dict(), "pixels_sha256": preview.pixels_sha256}
    if include_integrity:
        record["integrity"] = compute_integrity(presented, registry)
        record["integrity"][RECORD_CONTENT_KEY] = record_content_sha256(record)
    if forge_version is None:
        from forge import __version__ as forge_version
    record["info"] = {"forge_version": forge_version,
                      "note": "informational only; ignored on load and excluded from every hash"}
    validate_record(record, registry=registry)  # never emit a record Forge itself would refuse
    return record


def dumps_record(record: dict) -> str:
    return json.dumps(record, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


def save_record(record: dict, path: str | Path, *, registry: Registry = REGISTRY) -> Path:
    path = Path(path)
    if path.suffix.lower() != ".json":
        raise RecordFormatError(f"record path must end in .json; got {str(path)!r}")
    validate_record(record, registry=registry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dumps_record(record).encode("ascii"))
    return path


# ------------------------------------------------------------------ parsing

def _reject_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise RecordFormatError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def _reject_constant(name):
    raise RecordFormatError(f"non-finite number {name} is not allowed in a record")


def parse_record_text(text: str) -> dict:
    if not isinstance(text, str):
        raise RecordFormatError(f"record text must be str; got {type(text).__name__}")
    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise RecordFormatError(f"record is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RecordFormatError(f"record must be a JSON object; got {type(data).__name__}")
    return data


def read_record_file(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise RecordFormatError(f"record file not found: {str(path)!r}")
    raw = path.read_bytes()
    if len(raw) > MAX_RECORD_BYTES:
        raise RecordFormatError(f"record file is {len(raw)} bytes; limit is {MAX_RECORD_BYTES}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RecordFormatError(f"record file is not UTF-8: {exc}") from exc
    return parse_record_text(text)


# ------------------------------------------------------------------ validation

def _keys(obj, where: str, required: set, optional: set = frozenset()) -> None:
    if not isinstance(obj, dict):
        raise RecordFormatError(f"{where} must be a JSON object; got {type(obj).__name__}")
    missing = sorted(required - obj.keys())
    unknown = sorted(obj.keys() - required - optional)
    if missing:
        raise RecordFormatError(f"{where} is missing required field(s) {missing}")
    if unknown:
        raise RecordFormatError(f"{where} has unknown field(s) {unknown}")


def _hex(where: str, value: object) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise RecordFormatError(f"{where} must be a 64-character lowercase hex SHA-256; got {value!r}")
    return value


@dataclass(frozen=True)
class RecordSpec:
    """A structurally valid record, decoded. Not yet verified against regeneration."""
    seed: int
    generator_version: int
    versions: PresentationVersions
    materials: dict
    preview: PreviewSettings | None
    expected_pixels_sha256: str | None
    integrity: dict
    raw: dict
    asset_type: str


def _validate_v1(data: dict, registry: Registry) -> RecordSpec:
    entry = registry.asset(data["asset_type"])          # unknown -> UnknownAssetTypeError, before generation
    d = entry.descriptor
    require_version("record_version", data["record_version"], d.record_versions)

    if data["generator"] != d.generator_id:
        known = data["generator"] in registry.generator_ids() if isinstance(data["generator"], str) else False
        raise UnknownGeneratorError(
            f"generator {data['generator']!r} " + ("does not produce" if known else "is not registered for")
            + f" asset_type {d.asset_type!r}; expected {d.generator_id!r}")
    generator = registry.generator(d.generator_id, data["generator_version"])

    if not isinstance(data["seed"], str):
        raise InvalidSeedError(f"record seed must be a decimal string; got {type(data['seed']).__name__}: "
                               f"{data['seed']!r}")
    seed = parse_seed(data["seed"])

    conv = data["conventions"]
    if not isinstance(conv, dict) or conv.get("id") not in CONVENTIONS:
        raise RecordFormatError(f"unknown coordinate convention {conv.get('id') if isinstance(conv, dict) else conv!r}; "
                                f"known: {sorted(CONVENTIONS)}")
    if conv != dict(CONVENTIONS[conv["id"]]):
        raise RecordFormatError(f"conventions do not match the definition of {conv['id']!r}: "
                                f"expected {dict(CONVENTIONS[conv['id']])}, got {conv}")
    if conv["id"] != d.convention_id:
        raise RecordFormatError(f"coordinate convention {conv['id']!r} is not the convention of asset_type "
                                f"{d.asset_type!r} ({d.convention_id!r})")

    pres = data["presentation"]
    _keys(pres, "presentation", _PRESENTATION_KEYS)
    family = registry.presentation(d.presentation_id, pres["presentation_version"])
    versions = PresentationVersions(
        presentation_version=family.presentation_version,
        normals_version=require_version("normals_version", pres["normals_version"], (family.normals_version,)),
        uv_version=require_version("uv_version", pres["uv_version"], (family.uv_version,)),
        material_version=require_version("material_version", pres["material_version"], (family.material_version,)),
    )
    materials = pres["materials"]
    _keys(materials, "presentation.materials", set(d.components))
    for name in d.components:
        if not isinstance(materials[name], dict):
            raise RecordFormatError(f"presentation.materials.{name} must be a JSON object")

    preview, expected_pixels = None, None
    if "preview" in data:
        pv = data["preview"]
        _keys(pv, "preview", _PREVIEW_REQUIRED, {"pixels_sha256"})
        try:  # an unsupported preview_version propagates as UnsupportedVersionError
            preview = PreviewSettings(pv["preview_version"], pv["view"], pv["width"], pv["height"], pv["ssaa"])
        except RenderError as exc:
            raise RecordFormatError(f"preview settings invalid: {exc}") from exc
        preview_for(registry, d.asset_type, family.presentation_version, preview.preview_version)
        if "pixels_sha256" in pv:
            expected_pixels = _hex("preview.pixels_sha256", pv["pixels_sha256"])

    integrity = {}
    if "integrity" in data:
        allowed = {key for key, _ in entry.integrity} | {RECORD_CONTENT_KEY}
        _keys(data["integrity"], "integrity", set(), allowed)
        for key, value in data["integrity"].items():
            integrity[key] = _hex(f"integrity.{key}", value)

    if "info" in data and not isinstance(data["info"], dict):
        raise RecordFormatError("info must be a JSON object when present")

    return RecordSpec(seed, generator.generator_version, versions, materials, preview, expected_pixels,
                      integrity, data, d.asset_type)


# record_version -> schema validator. Explicit; no implicit "latest".
_SCHEMAS = MappingProxyType({1: _validate_v1})
SUPPORTED_RECORD_VERSIONS = tuple(sorted(_SCHEMAS))


def validate_record(data: object, *, registry: Registry = REGISTRY) -> RecordSpec:
    """Structural validation through the registry. Raises RecordFormatError (incl.
    UnknownAssetTypeError / UnknownGeneratorError), UnsupportedVersionError,
    UnsupportedGeneratorVersionError, or InvalidSeedError. Never repairs."""
    _keys(data, "record", _TOP_REQUIRED, _TOP_OPTIONAL)
    if data["record_format"] != RECORD_FORMAT:
        raise RecordFormatError(f"record_format must be {RECORD_FORMAT!r}; got {data['record_format']!r}")
    version = require_version("record_version", data["record_version"], SUPPORTED_RECORD_VERSIONS)
    return _SCHEMAS[version](data, registry)


# ------------------------------------------------------------------ reproduction

def _first_difference(expected, actual, path: str):
    if type(expected) is not type(actual):
        return path, expected, actual
    if isinstance(expected, dict):
        for key in sorted(expected.keys() | actual.keys()):
            if key not in expected or key not in actual:
                return f"{path}.{key}", expected.get(key, "<missing>"), actual.get(key, "<missing>")
            diff = _first_difference(expected[key], actual[key], f"{path}.{key}")
            if diff:
                return diff
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}.length", len(expected), len(actual)
        for i, (e, a) in enumerate(zip(expected, actual)):
            diff = _first_difference(e, a, f"{path}[{i}]")
            if diff:
                return diff
        return None
    return None if expected == actual else (path, expected, actual)


@dataclass(frozen=True)
class LoadedAsset:
    spec: RecordSpec
    asset: object
    presented: PresentedSword
    verified: tuple[str, ...]  # names of the checks that passed

    @property
    def record_content_sha256(self) -> str:
        return record_content_sha256(self.spec.raw)


def reproduce(spec: RecordSpec, *, registry: Registry = REGISTRY) -> LoadedAsset:
    """Regenerate through the registry and verify every expectation in the record."""
    verified = []
    stated = spec.integrity.get(RECORD_CONTENT_KEY)
    if stated is not None:
        actual = record_content_sha256(spec.raw)
        if actual != stated:
            raise RecordIntegrityError(
                f"record content changed since it was saved: record_content_sha256 is {stated}, "
                f"content hashes to {actual}")
        verified.append(RECORD_CONTENT_KEY)

    asset = generate_asset(registry, spec.asset_type, spec.seed, spec.generator_version)
    presented = present_asset(registry, asset, spec.versions)

    diff = _first_difference(spec.materials, presented.materials, "presentation.materials")
    if diff:
        path, expected, actual = diff
        raise RecordIntegrityError(
            f"material state does not reproduce: {path} is {expected!r} in the record but "
            f"regenerates as {actual!r}")
    verified.append("materials")

    for key, value in integrity_hashes(registry, presented).items():   # asset entry's declared order
        if key not in spec.integrity:
            continue
        if spec.integrity[key] != value:
            raise RecordIntegrityError(f"{key} mismatch: record says {spec.integrity[key]}, regenerated {value}")
        verified.append(key)
    return LoadedAsset(spec, asset, presented, tuple(verified))


def load_record(path: str | Path, *, registry: Registry = REGISTRY) -> LoadedAsset:
    return reproduce(validate_record(read_record_file(path), registry=registry), registry=registry)


def loads_record(text: str, *, registry: Registry = REGISTRY) -> LoadedAsset:
    return reproduce(validate_record(parse_record_text(text), registry=registry), registry=registry)


__all__ = [
    "CONVENTIONS_V1", "KNOWN_CONVENTIONS", "MAX_RECORD_BYTES", "RECORD_FORMAT", "SUPPORTED_RECORD_VERSIONS",
    "LoadedAsset", "RecordSpec", "build_record", "compute_integrity", "dumps_record", "load_record",
    "loads_record", "parse_record_text", "read_record_file", "record_content_sha256", "reproduce",
    "save_record", "validate_record",
]

