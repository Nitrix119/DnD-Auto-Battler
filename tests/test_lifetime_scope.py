"""Lifetime scopes + grant handles (Phase 2, §4.2).

The ownership primitive that retires the string-tag cleanup: a scope owns the
revoke handles produced under it and tears them down in reverse, once. See
:mod:`src.spells.lifetime`.
"""

from src.models.lifetime import RevokeHandle, LifetimeScope, LifetimeKind


class TestRevokeHandle:

    def test_dispose_runs_once(self):
        calls = []
        h = RevokeHandle(lambda: calls.append(1), label="mod")
        assert not h.disposed
        h.dispose()
        h.dispose()  # idempotent
        assert calls == [1]
        assert h.disposed


class TestLifetimeScope:

    def test_dispose_walks_handles_in_reverse(self):
        order = []
        scope = LifetimeScope(kind=LifetimeKind.CONCENTRATION, source="Shield of Faith")
        scope.add(RevokeHandle(lambda: order.append("a"), "a"))
        scope.add(RevokeHandle(lambda: order.append("b"), "b"))
        scope.add(RevokeHandle(lambda: order.append("c"), "c"))
        scope.dispose()
        assert order == ["c", "b", "a"]  # reverse insertion order

    def test_dispose_is_idempotent(self):
        calls = []
        scope = LifetimeScope()
        scope.add(RevokeHandle(lambda: calls.append(1)))
        scope.dispose()
        scope.dispose()
        assert calls == [1]
        assert scope.disposed

    def test_add_ignores_none(self):
        scope = LifetimeScope()
        assert scope.add(None) is None
        scope.dispose()  # no crash

    def test_grant_after_dispose_is_revoked_immediately(self):
        calls = []
        scope = LifetimeScope()
        scope.dispose()
        h = scope.add(RevokeHandle(lambda: calls.append(1)))
        assert calls == [1]  # revoked at once — the lifetime is already over
        assert h.disposed

    def test_kind_and_source_recorded(self):
        scope = LifetimeScope(kind=LifetimeKind.CONCENTRATION, source="Bless")
        assert scope.kind is LifetimeKind.CONCENTRATION
        assert scope.source == "Bless"


class TestScopeCountdown:

    def test_untimed_scope_never_expires(self):
        scope = LifetimeScope()
        assert scope.rounds_remaining is None
        assert scope.tick() is False
        assert scope.tick() is False

    def test_timed_scope_expires_after_its_rounds(self):
        scope = LifetimeScope(rounds_remaining=2)
        assert scope.tick() is False  # 2 -> 1
        assert scope.tick() is True   # 1 -> 0, expired
        assert scope.rounds_remaining == 0

    def test_disposed_scope_tick_is_a_noop(self):
        scope = LifetimeScope(rounds_remaining=1)
        scope.dispose()
        assert scope.tick() is False
