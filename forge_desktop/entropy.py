"""The desktop shell's only source of randomness: the Random Seed button.

This is a UI convenience and NOT part of deterministic generation. The value it
returns is shown in the seed field and from then on is just an explicit seed
like any other. Nothing in the Forge core (the `forge` package) ever calls this,
and a guard test keeps entropy confined to this one module.
"""

from __future__ import annotations

import secrets

SEED_BITS = 64


def random_seed() -> int:
    """A uniformly random seed in [0, 2**64 - 1] from the OS's CSPRNG."""
    return secrets.randbits(SEED_BITS)
