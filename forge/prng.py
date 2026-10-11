"""Deterministic PRNG: PCG32 (PCG-XSH-RR, 64-bit state, 32-bit output).

Reference: M. E. O'Neill, "PCG: A Family of Simple Fast Space-Efficient
Statistically Good Algorithms for Random Number Generation" (2014), and the
minimal C implementation at https://www.pcg-random.org/download.html.
This module reproduces `pcg32_srandom_r`, `pcg32_random_r`, and
`pcg32_boundedrand_r` bit-for-bit (verified by a known-answer test).

Why PCG32: tiny, fully specified, integer-only (no platform float behavior in
the core), supports independent streams, and has published reference vectors.

Every procedural decision in Forge draws from an explicit PCG32 instance.
Forge never touches Python's `random` module, `hash()`, time, PIDs, or the OS
entropy pool.
"""

from __future__ import annotations

from typing import Sequence, TypeVar

MASK32 = (1 << 32) - 1
MASK64 = (1 << 64) - 1
PCG32_MULTIPLIER = 6364136223846793005
_TWO_POW_32 = 4294967296.0  # exact in binary64

FNV1A64_OFFSET = 0xCBF29CE484222325
FNV1A64_PRIME = 0x100000001B3

T = TypeVar("T")


def _require_u64(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int; got {type(value).__name__}: {value!r}")
    if not 0 <= value <= MASK64:
        raise ValueError(f"{name} must be in [0, 2**64-1]; got {value}")
    return int(value)


class PCG32:
    """PCG-XSH-RR 64/32. State is private to the instance; nothing is global."""

    __slots__ = ("_state", "_inc")

    def __init__(self, initstate: int, initseq: int) -> None:
        initstate = _require_u64("initstate", initstate)
        initseq = _require_u64("initseq", initseq)
        # pcg32_srandom_r
        self._state = 0
        self._inc = ((initseq << 1) | 1) & MASK64
        self._step()
        self._state = (self._state + initstate) & MASK64
        self._step()

    def _step(self) -> None:
        self._state = (self._state * PCG32_MULTIPLIER + self._inc) & MASK64

    def next_u32(self) -> int:
        """Uniform integer in [0, 2**32 - 1]. (pcg32_random_r)"""
        old = self._state
        self._step()
        xorshifted = (((old >> 18) ^ old) >> 27) & MASK32
        rot = old >> 59
        return ((xorshifted >> rot) | (xorshifted << ((-rot) & 31))) & MASK32

    def next_bounded(self, bound: int) -> int:
        """Unbiased integer in [0, bound). (pcg32_boundedrand_r, rejection sampling)"""
        if isinstance(bound, bool) or not isinstance(bound, int):
            raise TypeError(f"bound must be an int; got {type(bound).__name__}: {bound!r}")
        if not 1 <= bound <= (1 << 32):
            raise ValueError(f"bound must be in [1, 2**32]; got {bound}")
        threshold = ((1 << 32) - bound) % bound
        while True:
            r = self.next_u32()
            if r >= threshold:
                return r % bound

    def next_float(self) -> float:
        """Float in [0, 1) with 32 bits of resolution.

        u32 / 2**32 is exact in IEEE-754 binary64, so this is bit-identical on
        every conforming platform.
        """
        return self.next_u32() / _TWO_POW_32

    def uniform(self, lo: float, hi: float) -> float:
        """Float in [lo, hi]. One draw. Result is lo + (hi - lo) * u."""
        if not (isinstance(lo, float) and isinstance(hi, float)):
            raise TypeError(f"uniform bounds must be floats; got {lo!r}, {hi!r}")
        if not (lo <= hi) or lo != lo or hi != hi or abs(lo) == float("inf") or abs(hi) == float("inf"):
            raise ValueError(f"uniform requires finite lo <= hi; got [{lo!r}, {hi!r}]")
        return lo + (hi - lo) * self.next_float()

    def choice(self, options: Sequence[T]) -> T:
        """One element of a non-empty sequence. One bounded draw."""
        if len(options) == 0:
            raise ValueError("choice() requires a non-empty sequence")
        return options[self.next_bounded(len(options))]

    def snapshot(self) -> tuple[int, int]:
        """(state, increment) for debugging and tests. Read-only view."""
        return (self._state, self._inc)


def fnv1a64(data: bytes) -> int:
    """64-bit FNV-1a. Used to turn stream labels into PCG stream selectors.

    Chosen over Python's hash(), which is salted per process (PYTHONHASHSEED).
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError(f"fnv1a64 expects bytes; got {type(data).__name__}")
    h = FNV1A64_OFFSET
    for byte in data:
        h ^= byte
        h = (h * FNV1A64_PRIME) & MASK64
    return h


def stream_id(label: str) -> int:
    """Stable 64-bit PCG stream selector for an ASCII label."""
    if not isinstance(label, str) or not label or not label.isascii():
        raise ValueError(f"stream label must be a non-empty ASCII string; got {label!r}")
    return fnv1a64(label.encode("ascii"))


def derive_stream(seed: int, label: str) -> PCG32:
    """Independent PCG32 stream for (seed, label).

    Each sword component gets its own labelled stream, so adding or removing a
    draw in one component (in a future generator version) cannot shift the
    random values another component receives.
    """
    return PCG32(initstate=seed, initseq=stream_id(label))
