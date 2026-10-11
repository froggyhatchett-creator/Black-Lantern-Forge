"""Environment preconditions for Forge's determinism contract.

Forge's byte-stability claim rests on two properties of the running Python:
  1. floats are IEEE-754 binary64 (correctly rounded + - * / sqrt), and
  2. float formatting uses CPython's correctly rounded "short" repr algorithm.
Both hold on every mainstream CPython build. If either is missing, Forge
refuses to generate rather than emit output that might silently differ.
"""

from __future__ import annotations

import sys

from forge.errors import EnvironmentNotSupportedError


def float_environment_problems() -> list[str]:
    problems = []
    fi = sys.float_info
    if (fi.mant_dig, fi.max_exp, fi.min_exp, fi.radix) != (53, 1024, -1021, 2):
        problems.append(f"float is not IEEE-754 binary64: {fi}")
    if sys.float_repr_style != "short":
        problems.append(f"sys.float_repr_style is {sys.float_repr_style!r}, expected 'short'")
    return problems


def require_supported_float_environment() -> None:
    problems = float_environment_problems()
    if problems:
        raise EnvironmentNotSupportedError(
            "Forge determinism contract cannot be honored here: " + "; ".join(problems)
        )
