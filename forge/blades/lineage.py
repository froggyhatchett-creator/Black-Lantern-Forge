"""Blade lineage and classification (Step 5A), including the bayonet groundwork.

Every blade family declares a BladeClass:
  * its lineage (short_blade or sword)
  * its edge (double or single)
  * the grips it affords: one-handed, hand-and-a-half, two-handed (grip_hands maps a grip
    length to one of these, and generation rejects a grip outside the family's set)
  * the attachment roles it supports today
Packages expose these as tags; the contract doesn't change.

Bayonet groundwork. This is architecture only; nothing here mounts anything.
  * A bayonet belongs to the blade lineage, closest to the dagger / short blade, and isn't a
    separate firearm architecture. BAYONET_LINEAGE records that. It is EXPERIMENTAL and not
    registered in forge.catalog: no generator, no asset type, no package.
  * MountSpec is the schema a future bayonet would carry to describe how it mounts: socket,
    plug or lug, with the bore and offset dimensions. It can be validated now and is never
    exported in Step 5A.
  * Reserved socket names, so a future muzzle attachment fits Contract v1's socket_* rule
    without a contract change:
      socket_mount    on the bayonet: the point that meets the muzzle
      socket_muzzle   on a future firearm: where a bayonet attaches
    No Step 5A package carries either.
Deferred: firearm sockets, mounting to pistols or rifles, dynamic attachment composition.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType

from forge.errors import GenerationError

LINEAGES = ("short_blade", "sword")
EDGES = ("double", "single")
HANDS = ("one", "hand_and_half", "two")
ATTACHMENT_ROLES = ("handheld", "bayonet")          # "bayonet" is reserved: no family supports it in 5A
MOUNT_TYPES = ("socket", "plug", "lug")
RESERVED_SOCKETS = MappingProxyType({
    "socket_mount": "bayonet side: the point that meets the muzzle (future)",
    "socket_muzzle": "firearm side: where a bayonet attaches (future)",
})


@dataclass(frozen=True)
class BladeClass:
    lineage: str
    edge: str
    hands: tuple[str, ...]                # the grips this family affords (see grip_hands)
    attachment_roles: tuple[str, ...]
    bayonet_lineage_parent: bool          # True: a future bayonet lineage derives from this family

    def __post_init__(self) -> None:
        if self.lineage not in LINEAGES or self.edge not in EDGES:
            raise GenerationError(f"invalid blade class {self!r}")
        if not self.hands or any(h not in HANDS for h in self.hands):
            raise GenerationError(f"invalid hands {self.hands!r}")
        if not self.attachment_roles or any(r not in ATTACHMENT_ROLES for r in self.attachment_roles):
            raise GenerationError(f"invalid attachment roles {self.attachment_roles!r}")


@dataclass(frozen=True)
class MountSpec:
    """How a future bayonet would mount on a muzzle (schema only; not generated, not exported)."""
    mount_type: str                 # socket | plug | lug
    bore_diameter: float            # meters; the muzzle (socket) or bore (plug) it fits
    ring_inner_diameter: float      # meters; socket/lug ring; 0.0 for a plug bayonet
    offset: float                   # meters; lateral offset of the blade from the bore axis

    def validate(self) -> "MountSpec":
        if self.mount_type not in MOUNT_TYPES:
            raise GenerationError(f"mount_type {self.mount_type!r} not in {MOUNT_TYPES}")
        for name in ("bore_diameter", "ring_inner_diameter", "offset"):
            value = getattr(self, name)
            if type(value) is not float or not math.isfinite(value) or value < 0.0:
                raise GenerationError(f"{name} must be a finite, non-negative float in meters; got {value!r}")
        if not 0.008 <= self.bore_diameter <= 0.025:
            raise GenerationError(f"bore_diameter {self.bore_diameter!r} m outside [0.008, 0.025]")
        if self.mount_type == "plug":
            if self.ring_inner_diameter != 0.0:
                raise GenerationError("a plug bayonet has no ring")
        elif not self.bore_diameter < self.ring_inner_diameter <= self.bore_diameter + 0.012:
            raise GenerationError("a socket or lug ring must fit around the muzzle")
        if self.offset > 0.04:
            raise GenerationError(f"offset {self.offset!r} m is implausibly large")
        return self


@dataclass(frozen=True)
class Lineage:
    lineage_id: str
    parent_family: str
    status: str                     # "experimental": defined, not registered, not produced
    blade_class: BladeClass


BLADE_CLASSES = MappingProxyType({
    "dagger": BladeClass("short_blade", "double", ("one",), ("handheld",), bayonet_lineage_parent=True),
    "long_sword": BladeClass("sword", "double", ("hand_and_half",), ("handheld",), bayonet_lineage_parent=False),
    "curved_sword": BladeClass("sword", "single", ("one", "hand_and_half"), ("handheld",),
                               bayonet_lineage_parent=False),
    "great_sword": BladeClass("sword", "double", ("two",), ("handheld",), bayonet_lineage_parent=False),
})
BAYONET_LINEAGE = Lineage(
    lineage_id="bayonet", parent_family="dagger", status="experimental",
    blade_class=BladeClass("short_blade", "double", ("one",), ("bayonet",), bayonet_lineage_parent=False),
)


def grip_hands(grip_length: float) -> str:
    """Handedness a grip of this length affords: one hand per ~0.10-0.12 m of grip."""
    if grip_length < 0.15:
        return "one"
    if grip_length < 0.26:
        return "hand_and_half"
    return "two"
