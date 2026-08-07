"""Tests for the seedable shared RNG (E11) and multi-term formula rolling."""

from src.utils import dice


class TestSeedRng:
    def test_seeding_makes_rolls_reproducible(self):
        dice.seed_rng(1234)
        a = [dice.roll_d20() for _ in range(10)]
        dice.seed_rng(1234)
        b = [dice.roll_d20() for _ in range(10)]
        assert a == b

    def test_different_seeds_differ(self):
        dice.seed_rng(1)
        a = [dice.roll_d20() for _ in range(20)]
        dice.seed_rng(2)
        b = [dice.roll_d20() for _ in range(20)]
        assert a != b

    def test_roll_dice_is_seeded_too(self):
        dice.seed_rng(99)
        a = dice.roll_dice(5, 6)
        dice.seed_rng(99)
        b = dice.roll_dice(5, 6)
        assert a == b

    def test_reseed_none_restores_nondeterminism(self):
        # Sanity: seeding with None should not raise and returns valid rolls.
        dice.seed_rng(None)
        assert 1 <= dice.roll_d20() <= 20

    def teardown_method(self):
        # Leave the RNG unseeded so other tests are unaffected.
        dice.seed_rng(None)


class TestMultiTermFormulas:
    def test_multi_term_formula_rolls_in_range(self):
        dice.seed_rng(7)
        # 2d6+1d8+5 → min 2+1+5=8, max 12+8+5=25
        total = dice.roll_formula("2d6+1d8+5")
        assert 8 <= total <= 25

    def test_seeded_multi_term_is_reproducible(self):
        dice.seed_rng(42)
        a = dice.roll_formula("3d8+6")
        dice.seed_rng(42)
        b = dice.roll_formula("3d8+6")
        assert a == b

    def teardown_method(self):
        dice.seed_rng(None)
