"""Entity grant handles + concentration as a first-class lifetime (Phase 2, §4.2).

Grants now return identity-based revoke handles (no string tags), and
concentration is a :class:`LifetimeScope` the entity owns — beginning a new one
disposes the old atomically, and ending it revokes exactly what it granted.
"""

from src.models import AbilityScores, StatBlock, Entity
from src.models.condition import Condition, ConditionType
from src.models.stat_modifier import StatModifier
from src.models.lifetime import LifetimeScope, LifetimeKind


def _entity(hp=30, ac=12):
    sb = StatBlock(
        name="E",
        ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp,
        armor_class=ac,
    )
    return Entity(sb)


class TestGrantHandles:

    def test_add_stat_modifier_handle_removes_by_identity(self):
        e = _entity(ac=12)
        h = e.add_stat_modifier(
            StatModifier(stat="ac", value=2, source="Bless", effect_name="")
        )
        assert e.ac == 14
        h.dispose()
        assert e.ac == 12  # exactly the granted modifier gone
        h.dispose()  # idempotent

    def test_two_modifiers_same_source_dispose_independently(self):
        # The string-tag failure mode: two grants sharing a name. Identity handles
        # revoke exactly one each, never both.
        e = _entity(ac=10)
        h1 = e.add_stat_modifier(
            StatModifier(stat="ac", value=1, source="x", effect_name="x")
        )
        h2 = e.add_stat_modifier(
            StatModifier(stat="ac", value=1, source="x", effect_name="x")
        )
        assert e.ac == 12
        h1.dispose()
        assert e.ac == 11  # only one removed
        h2.dispose()
        assert e.ac == 10

    def test_add_condition_handle_removes_by_identity(self):
        e = _entity()
        h = e.add_condition(Condition(condition_type=ConditionType.PRONE))
        assert any(
            c.condition_type is ConditionType.PRONE for c in e.get_active_conditions()
        )
        h.dispose()
        assert not e.get_active_conditions()

    def test_temp_hp_handle_clears_its_grant(self):
        e = _entity()
        assert e.temporary_hp == 0
        h = e.add_temporary_hp(10)
        assert e.temporary_hp == 10
        h.dispose()
        assert e.temporary_hp == 0


class TestConcentrationLifetime:

    def test_begin_concentration_sets_scope_and_has_concentration(self):
        e = _entity()
        scope = LifetimeScope(kind=LifetimeKind.CONCENTRATION, source="Shield of Faith")
        e.begin_concentration(scope)
        assert e.has_concentration
        assert e.concentration_scope is scope

    def test_new_concentration_disposes_the_old_atomically(self):
        caster = _entity()
        target = _entity(ac=12)
        # First concentration: +2 AC on the target, owned by the caster's scope.
        s1 = LifetimeScope(kind=LifetimeKind.CONCENTRATION, source="Shield of Faith")
        s1.add(
            target.add_stat_modifier(
                StatModifier(stat="ac", value=2, source="SoF", effect_name="")
            )
        )
        caster.begin_concentration(s1)
        assert target.ac == 14

        # Casting a second concentration spell drops the first and its grant.
        s2 = LifetimeScope(kind=LifetimeKind.CONCENTRATION, source="Bless")
        caster.begin_concentration(s2)
        assert s1.disposed
        assert target.ac == 12  # the first spell's AC bonus is gone
        assert caster.concentration_scope is s2

    def test_end_concentration_disposes_scope_and_clears_state(self):
        caster = _entity()
        target = _entity(ac=12)
        s = LifetimeScope(kind=LifetimeKind.CONCENTRATION, source="SoF")
        s.add(
            target.add_stat_modifier(
                StatModifier(stat="ac", value=2, source="SoF", effect_name="")
            )
        )
        caster.begin_concentration(s)
        caster.end_concentration()
        assert not caster.has_concentration
        assert caster.concentration_scope is None
        assert target.ac == 12

    def test_tick_disposes_an_expired_duration_scope(self):
        holder = _entity(ac=12)
        scope = LifetimeScope(kind=LifetimeKind.ROUNDS, rounds_remaining=2)
        scope.add(
            holder.add_stat_modifier(
                StatModifier(stat="ac", value=2, source="Buff", effect_name="")
            )
        )
        holder.lifetimes.append(scope)
        assert holder.ac == 14

        holder.tick_lifetimes()          # 2 -> 1
        assert holder.ac == 14 and holder.lifetimes
        holder.tick_lifetimes()          # 1 -> 0: expired, disposed, dropped
        assert holder.ac == 12
        assert holder.lifetimes == []

    def test_tick_expires_a_concentration_duration(self):
        caster = _entity()
        scope = LifetimeScope(kind=LifetimeKind.CONCENTRATION, rounds_remaining=1)
        caster.begin_concentration(scope)
        assert caster.has_concentration
        caster.tick_lifetimes()          # 1 -> 0: concentration ends
        assert not caster.has_concentration
        assert caster.concentration_scope is None

    def test_scope_concentration_supersedes_legacy_string_concentration(self):
        # A legacy string-tagged concentration in progress, then a new-engine scope
        # concentration begins — the legacy one is torn down too.
        caster = _entity()
        target = _entity(ac=12)
        target.add_stat_modifier(
            StatModifier(stat="ac", value=3, source="Old", effect_name="old")
        )
        caster.concentrating_on = "old"
        caster.concentration_target = target
        assert caster.has_concentration and target.ac == 15

        caster.begin_concentration(LifetimeScope(kind=LifetimeKind.CONCENTRATION))
        assert caster.concentrating_on is None
        assert target.ac == 12  # legacy grant cleaned up via remove_effect
