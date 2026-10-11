"""Seed validation. The only way a seed enters Forge.

Policy (identical for every entry point):
  * A seed is a plain Python int in [0, 2**64 - 1].
  * bool is rejected even though it subclasses int (True is not a seed).
  * float, str, None, Decimal, numpy integers, etc. are rejected. No coercion.
  * Every rejection raises InvalidSeedError (a ValueError) with the offending value.
"""

from __future__ import annotations

import re

from forge.errors import InvalidSeedError

SEED_MIN = 0
SEED_MAX = (1 << 64) - 1

_DECIMAL_SEED = re.compile(r"[0-9]{1,20}")  # ASCII digits only; 2**64-1 has 20 digits


def validate_seed(seed: object) -> int:
    """Return `seed` as a plain int, or raise InvalidSeedError."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise InvalidSeedError(
            f"seed must be an int in [0, 2**64-1]; got {type(seed).__name__}: {seed!r}"
        )
    if seed < SEED_MIN or seed > SEED_MAX:
        raise InvalidSeedError(f"seed must be in [0, 2**64-1]; got {seed}")
    return int(seed)  # normalize int subclasses (e.g. IntEnum) to plain int


def parse_seed(text: object) -> int:
    """Parse a seed from text (CLI use). Accepts ASCII decimal digits only.

    Rejects signs, whitespace, underscores, hex, and non-ASCII digits, all of
    which Python's int() would otherwise accept or interpret.
    """
    if not isinstance(text, str) or _DECIMAL_SEED.fullmatch(text) is None:
        raise InvalidSeedError(
            f"seed must be a decimal integer in [0, 2**64-1] (digits only); got {text!r}"
        )
    return validate_seed(int(text))
