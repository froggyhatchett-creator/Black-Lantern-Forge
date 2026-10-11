"""Known coordinate conventions, by explicit identifier.

A convention definition is persisted verbatim in asset records and must match
exactly on load. Asset types reference one by id (AssetDescriptor.convention_id).
Definitions are frozen: a changed convention is a new id.
"""

from __future__ import annotations

from types import MappingProxyType

_RH_Y_UP_METERS_GRIP_ORIGIN_V1 = {
    "id": "forge.rh-y-up-meters.grip-origin.v1",
    "handedness": "right",
    "up_axis": "+Y",
    "units": "meters",
    "origin": "grip_center",
    "blade_tip_axis": "+Y",
    "front_face_winding": "counter_clockwise",
}

CONVENTIONS = MappingProxyType({
    _RH_Y_UP_METERS_GRIP_ORIGIN_V1["id"]: MappingProxyType(dict(_RH_Y_UP_METERS_GRIP_ORIGIN_V1)),
})

# Step 2 name, kept so existing imports (forge.record.CONVENTIONS_V1) keep working.
CONVENTIONS_V1 = dict(_RH_Y_UP_METERS_GRIP_ORIGIN_V1)


def convention_dict(convention_id: str) -> dict:
    """A fresh, mutable copy of a known convention (for writing into a record)."""
    return dict(CONVENTIONS[convention_id])
