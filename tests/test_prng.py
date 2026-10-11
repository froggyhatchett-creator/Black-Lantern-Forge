"""PCG32 correctness: reference vectors, ranges, streams, input validation."""

import unittest

from forge.prng import PCG32, derive_stream, fnv1a64, stream_id
from forge.sword.v1 import STREAM_LABELS


class TestPCG32ReferenceVectors(unittest.TestCase):
    """Known answers from the reference C implementation's pcg32-demo
    (pcg32_srandom_r(&rng, 42u, 54u), "Round 1")."""

    def test_raw_u32_matches_reference(self):
        rng = PCG32(42, 54)
        got = [rng.next_u32() for _ in range(6)]
        self.assertEqual(got, [0xA15C02B7, 0x7B47F409, 0xBA1D3330, 0x83D2F293, 0xBFA4784B, 0xCBED606E])

    def test_bounded_draws_match_reference_coins_and_rolls(self):
        rng = PCG32(42, 54)
        for _ in range(6):
            rng.next_u32()
        coins = "".join("H" if rng.next_bounded(2) else "T" for _ in range(65))
        rolls = [rng.next_bounded(6) + 1 for _ in range(33)]
        self.assertEqual(coins, "HHTTTHTHHHTHTTTHHHHHTTTHHHTHTHTHTTHTTTHHHHHHTTTTHHTTTTTHTTTTTTTHT")
        self.assertEqual(rolls, [3, 4, 1, 1, 2, 2, 3, 2, 4, 3, 2, 4, 3, 3, 5, 2, 3,
                                 1, 3, 1, 5, 1, 4, 1, 5, 6, 4, 6, 6, 2, 6, 3, 3])


class TestPCG32Behavior(unittest.TestCase):
    def test_same_seed_same_sequence(self):
        a, b = PCG32(7, 9), PCG32(7, 9)
        self.assertEqual([a.next_u32() for _ in range(100)], [b.next_u32() for _ in range(100)])

    def test_different_seed_or_stream_differs(self):
        r1, r2, r3 = PCG32(7, 9), PCG32(8, 9), PCG32(7, 10)
        s1 = [r1.next_u32() for _ in range(16)]
        self.assertNotEqual(s1, [r2.next_u32() for _ in range(16)])
        self.assertNotEqual(s1, [r3.next_u32() for _ in range(16)])

    def test_instances_do_not_share_state(self):
        a, b = PCG32(1, 2), PCG32(1, 2)
        interleaved = []
        for _ in range(10):
            interleaved.append(a.next_u32())
            b.next_u32()
        fresh = PCG32(1, 2)
        self.assertEqual(interleaved, [fresh.next_u32() for _ in range(10)])

    def test_bounded_stays_in_range(self):
        rng = PCG32(123, 456)
        for bound in (1, 2, 3, 7, 1000, (1 << 31) + 1, 1 << 32):
            for _ in range(200):
                v = rng.next_bounded(bound)
                self.assertTrue(0 <= v < bound, (bound, v))

    def test_float_in_unit_interval_and_uniform_in_bounds(self):
        rng = PCG32(5, 6)
        for _ in range(2000):
            f = rng.next_float()
            self.assertTrue(0.0 <= f < 1.0)
            u = rng.uniform(0.25, 0.5)
            self.assertTrue(0.25 <= u <= 0.5)

    def test_choice_covers_options(self):
        rng = PCG32(11, 12)
        seen = {rng.choice(("a", "b", "c")) for _ in range(200)}
        self.assertEqual(seen, {"a", "b", "c"})

    def test_rejects_invalid_arguments(self):
        for bad in (-1, 1 << 64, 1.0, "1", None, True):
            with self.assertRaises((TypeError, ValueError), msg=repr(bad)):
                PCG32(bad, 0)
            with self.assertRaises((TypeError, ValueError), msg=repr(bad)):
                PCG32(0, bad)
        rng = PCG32(0, 0)
        for bad in (0, -1, (1 << 32) + 1, 2.0, True):
            with self.assertRaises((TypeError, ValueError), msg=repr(bad)):
                rng.next_bounded(bad)
        for lo, hi in ((1.0, 0.0), (float("nan"), 1.0), (0.0, float("inf")), (0, 1)):
            with self.assertRaises((TypeError, ValueError), msg=repr((lo, hi))):
                rng.uniform(lo, hi)
        with self.assertRaises(ValueError):
            rng.choice(())


class TestStreams(unittest.TestCase):
    def test_fnv1a64_reference_vectors(self):
        self.assertEqual(fnv1a64(b""), 0xCBF29CE484222325)
        self.assertEqual(fnv1a64(b"a"), 0xAF63DC4C8601EC8C)
        self.assertEqual(fnv1a64(b"foobar"), 0x85944171F73967E8)

    def test_component_stream_ids_are_distinct(self):
        ids = [stream_id(label) for label in STREAM_LABELS.values()]
        self.assertEqual(len(set(ids)), len(ids))

    def test_derived_streams_are_reproducible_and_independent(self):
        a = derive_stream(99, "forge.sword.blade")
        b = derive_stream(99, "forge.sword.blade")
        c = derive_stream(99, "forge.sword.guard")
        sa = [a.next_u32() for _ in range(8)]
        self.assertEqual(sa, [b.next_u32() for _ in range(8)])
        self.assertNotEqual(sa, [c.next_u32() for _ in range(8)])

    def test_stream_label_validation(self):
        for bad in ("", "bläde", None, 5):
            with self.assertRaises(ValueError):
                stream_id(bad)


if __name__ == "__main__":
    unittest.main()
