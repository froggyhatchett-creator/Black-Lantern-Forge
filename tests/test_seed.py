"""Seed validation: one policy, one exception type, every entry point."""

import enum
import unittest
from decimal import Decimal

from forge import InvalidSeedError, generate_sword
from forge.seed import SEED_MAX, parse_seed, validate_seed
from forge_test_support import VERSION

INVALID_SEEDS = [
    -1, -(1 << 64), 1 << 64, (1 << 64) + 1,      # out of range
    True, False,                                 # bool is not a seed
    1.0, 0.0, float("nan"), float("inf"),        # floats, even integral ones
    "42", b"42", None, Decimal(42), [42], (42,), # other types
]


class TestSeedValidation(unittest.TestCase):
    def test_boundary_seeds_are_accepted(self):
        self.assertEqual(validate_seed(0), 0)
        self.assertEqual(validate_seed(SEED_MAX), (1 << 64) - 1)

    def test_int_subclass_is_normalized_to_plain_int(self):
        class Seeds(enum.IntEnum):
            A = 7
        out = validate_seed(Seeds.A)
        self.assertIs(type(out), int)
        self.assertEqual(out, 7)

    def test_invalid_seeds_raise_invalid_seed_error(self):
        for bad in INVALID_SEEDS:
            with self.subTest(seed=bad):
                with self.assertRaises(InvalidSeedError) as ctx:
                    validate_seed(bad)
                self.assertIsInstance(ctx.exception, ValueError)
                self.assertIn("seed", str(ctx.exception))

    def test_generate_sword_rejects_invalid_seeds_the_same_way(self):
        for bad in INVALID_SEEDS:
            with self.subTest(seed=bad):
                with self.assertRaises(InvalidSeedError):
                    generate_sword(bad, VERSION)

    def test_extreme_valid_seeds_generate(self):
        for seed in (0, 1, SEED_MAX - 1, SEED_MAX):
            with self.subTest(seed=seed):
                self.assertEqual(generate_sword(seed, VERSION).seed, seed)


class TestParseSeed(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_seed("0"), 0)
        self.assertEqual(parse_seed("1337"), 1337)
        self.assertEqual(parse_seed("007"), 7)
        self.assertEqual(parse_seed(str(SEED_MAX)), SEED_MAX)

    def test_invalid(self):
        bad_inputs = ["", " 42", "42 ", "+42", "-1", "4_2", "0x10", "1e3", "1.0", "abc",
                      "١٢",  # Arabic-Indic digits: int() accepts these, Forge does not
                      str(SEED_MAX + 1), "9" * 25, None, 42]
        for bad in bad_inputs:
            with self.subTest(text=bad):
                with self.assertRaises(InvalidSeedError):
                    parse_seed(bad)


if __name__ == "__main__":
    unittest.main()
