"""Tests for the InformationPolicy value object and HP bucketing."""

import pytest

from src.arena.information_policy import (
    FULL_INFORMATION,
    HP_BUCKETED,
    HP_HIDDEN,
    InformationPolicy,
    bucket_hp,
)


def test_full_information_reveals_everything():
    p = FULL_INFORMATION
    assert p.reveal_enemy_hp
    assert p.shows_hp
    assert p.reveal_enemy_ac
    assert p.reveal_enemy_resources
    assert p.reveal_enemy_conditions
    assert p.reveal_enemy_spell_slots


def test_hidden_hp_display_disables_shows_hp():
    assert not InformationPolicy(hp_display=HP_HIDDEN).shows_hp


def test_reveal_flag_overrides_display():
    # Even with an exact display, turning HP off hides it entirely.
    assert not InformationPolicy(reveal_enemy_hp=False).shows_hp


def test_invalid_hp_display_rejected():
    with pytest.raises(ValueError):
        InformationPolicy(hp_display="fuzzy")


@pytest.mark.parametrize(
    "current, maximum, expected",
    [
        (30, 30, "healthy"),
        (16, 30, "healthy"),
        (15, 30, "bloodied"),
        (8, 30, "bloodied"),
        (7, 30, "critical"),
        (1, 30, "critical"),
    ],
)
def test_bucket_hp(current, maximum, expected):
    assert bucket_hp(current, maximum) == expected


def test_bucketed_policy_is_constructible():
    p = InformationPolicy(hp_display=HP_BUCKETED)
    assert p.shows_hp
    assert p.hp_display == HP_BUCKETED
