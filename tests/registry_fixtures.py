"""Registry fixtures for the Step 2.5 tests (not a test module).

TEST_TETRA is a deliberately tiny, test-only asset family. It is NOT shipped and
NOT in forge.catalog. It exists to answer the anti-abstraction question:
can a new family be added by implementing a generator + presentation adapter
and registering explicit versioned entries, with zero edits to the generic
loader, hashing core, preview dispatch, or CLI routing? The tests exercise
exactly that path.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import ClassVar

from forge import catalog
from forge.hashing import geometry_sha256, materials_sha256, normals_sha256
from forge.mesh import Mesh
from forge.presentation.materials import Material, PatinaPattern
from forge.presentation.model import ComponentPresentation, PresentedSword
from forge.presentation.normals import raw_face_normals
from forge.prng import derive_stream
from forge.registry import (
    AssetDescriptor,
    AssetEntry,
    GeneratorEntry,
    PresentationEntry,
    build_registry,
)
from forge.sword import generate_sword


@dataclass(frozen=True)
class TetraAsset:
    seed: int
    generator_version: int
    size: float
    components: tuple
    asset_type: ClassVar[str] = "test_tetra"
    generator: ClassVar[str] = "test.tetra"

    @property
    def component_names(self):
        return tuple(m.name for m in self.components)

    @property
    def vertex_count(self):
        return 4

    @property
    def triangle_count(self):
        return 4

    def to_dict(self):
        return {"asset_type": self.asset_type, "generator": self.generator,
                "generator_version": self.generator_version, "seed": self.seed, "params": {"size": self.size}}


def generate_tetra_v1(seed: int) -> TetraAsset:
    s = derive_stream(seed, "test.tetra.body").uniform(0.05, 0.2)
    positions = ((0.0, 0.0, 0.0), (s, 0.0, 0.0), (0.0, s, 0.0), (0.0, 0.0, s))
    triangles = ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3))
    return TetraAsset(seed, 1, s, (Mesh("body", positions, triangles),))


def derive_tetra_v1(asset, versions):
    mesh = asset.components[0]
    normals = []
    for n in raw_face_normals(mesh):
        length = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
        normals.append((n[0] / length, n[1] / length, n[2] / length))
    material = Material("body", "flat_gray", (0.5, 0.5, 0.5), 0.0, 0.5,
                        PatinaPattern(seed=asset.seed & 0xFFFFFFFF, strength=0.1))
    comp = ComponentPresentation("body", tuple(normals), ((0, 0, 0), (1, 1, 1), (2, 2, 2), (3, 3, 3)),
                                 ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)), ((0, 1, 2),) * 4, material)
    return PresentedSword(asset, versions, (comp,))


def _geometry(asset, presented):
    return geometry_sha256(asset)


def _normals(asset, presented):
    return normals_sha256(presented)


def _materials(asset, presented):
    return materials_sha256(presented)


TETRA_ASSET = AssetEntry(
    descriptor=AssetDescriptor(
        asset_type="test_tetra", display_name="test tetrahedron", generator_id="test.tetra",
        presentation_id="test.presentation", export_formats=(), preview_id="forge.preview",
        record_versions=(1,), convention_id="forge.rh-y-up-meters.grip-origin.v1", components=("body",)),
    integrity=(("geometry_sha256", _geometry), ("normals_sha256", _normals), ("materials_sha256", _materials)),
    summary_lines=lambda asset: (f"  size               {asset.size:.4f} m",),
)
TETRA_GENERATORS = (GeneratorEntry("test.tetra", 1, "test_tetra", generate_tetra_v1),)
TETRA_PRESENTATIONS = (PresentationEntry("test.presentation", 1, 1, 1, 1, (1,), derive_tetra_v1),)


def production_tables():
    return dict(assets=catalog.ASSETS, generators=catalog.GENERATORS, presentations=catalog.PRESENTATIONS,
                exporters=catalog.EXPORTERS, previews=catalog.PREVIEWS)


def registry_with_tetra():
    t = production_tables()
    return build_registry(assets=t["assets"] + (TETRA_ASSET,), generators=t["generators"] + TETRA_GENERATORS,
                          presentations=t["presentations"] + TETRA_PRESENTATIONS,
                          exporters=t["exporters"], previews=t["previews"])


def reversed_registry():
    """Same entries as production, every table in reverse insertion order."""
    t = production_tables()
    return build_registry(**{k: tuple(reversed(v)) for k, v in t.items()})


def fake_sword_v2(seed: int):
    """A pretend forge.sword v2 (test only): v1 geometry relabelled as version 2."""
    return dataclasses.replace(generate_sword(seed, 1), generator_version=2)


def registry_with_sword_v2():
    t = production_tables()
    return build_registry(**{**t, "generators": t["generators"] + (
        GeneratorEntry("forge.sword", 2, "short_sword", fake_sword_v2),)})


class Spy:
    """Counts calls and forwards to a wrapped callable."""

    def __init__(self, fn):
        self.fn, self.calls = fn, 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.fn(*args, **kwargs)


def spying_registry():
    """Production short_sword entries, with generator/derive/export/preview wrapped in call counters."""
    t = production_tables()
    gen_spy = Spy(t["generators"][0].generate)
    pres_spy = Spy(t["presentations"][0].derive)
    export_spies = [Spy(e.write) for e in t["exporters"]]
    preview_spy = Spy(t["previews"][0].render)
    reg = build_registry(
        assets=t["assets"][:1],          # Step 5A: the catalog has more families; the spies wrap short_sword's
        generators=(dataclasses.replace(t["generators"][0], generate=gen_spy),),
        presentations=(dataclasses.replace(t["presentations"][0], derive=pres_spy),),
        exporters=tuple(dataclasses.replace(e, write=s) for e, s in zip(t["exporters"], export_spies)),
        previews=(dataclasses.replace(t["previews"][0], render=preview_spy),),
    )
    return reg, {"generate": gen_spy, "derive": pres_spy, "export": export_spies, "preview": preview_spy}

