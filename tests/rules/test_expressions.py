"""Tests for AST-based expression validation in src/rules/expressions.py."""

import types
import pytest

import src.rules.expressions as expr_mod
from src.rules.expressions import _validate_ast, _validated_cache, evaluate, resolve


def setup_function():
    """Clear the validation cache before each test to ensure isolation."""
    _validated_cache.clear()


# ── Accepted expressions ──────────────────────────────────────────────────────

class TestValidateAstAccepted:
    """All expressions that appear in real data files must pass validation."""

    def setup_method(self):
        _validated_cache.clear()

    def test_chained_attribute(self):
        _validate_ast("event.defender.has_concentration")

    def test_builtin_call_with_floor_div(self):
        _validate_ast("max(10, event.total // 2)")

    def test_equality_comparison(self):
        _validate_ast("event.attacker == entity")

    def test_three_level_attribute(self):
        _validate_ast("event.defender == instance_fields.charmer")

    def test_unary_not(self):
        _validate_ast("not save_success")

    def test_bool_and_comparison(self):
        _validate_ast("event.attacker == entity and event.defender.hp < event.defender.max_hp")

    def test_gt_comparison(self):
        _validate_ast("entity.temporary_hp > 0")

    def test_subscript_then_attribute(self):
        _validate_ast("event.action.damage[0].damage_type")

    def test_bare_true(self):
        _validate_ast("True")

    def test_integer_literal(self):
        _validate_ast("0")

    def test_lte_comparison(self):
        _validate_ast("entity.temporary_hp <= 0")

    def test_bool_or(self):
        _validate_ast("event.attacker == entity or event.defender == entity")

    def test_not_equal(self):
        _validate_ast("event.type != other")

    def test_gte_comparison(self):
        _validate_ast("entity.hp >= 10")

    def test_arithmetic_add(self):
        _validate_ast("event.hp + 5")

    def test_arithmetic_sub(self):
        _validate_ast("event.total - 1")

    def test_arithmetic_mult(self):
        _validate_ast("event.total * 2")

    def test_arithmetic_div(self):
        _validate_ast("event.total / 2")

    def test_arithmetic_mod(self):
        _validate_ast("event.total % 3")

    def test_safe_builtin_min(self):
        _validate_ast("min(event.hp, 10)")

    def test_safe_builtin_abs(self):
        _validate_ast("abs(event.delta)")

    def test_safe_builtin_int(self):
        _validate_ast("int(event.value)")

    def test_safe_builtin_round(self):
        _validate_ast("round(event.value)")

    def test_safe_builtin_bool(self):
        _validate_ast("bool(event.flag)")

    def test_safe_builtin_len(self):
        _validate_ast("len(event.targets)")

    def test_safe_builtin_hasattr(self):
        _validate_ast('hasattr(event, "defender")')


# ── Rejected expressions ──────────────────────────────────────────────────────

class TestValidateAstRejected:
    """Dangerous expressions must raise ValueError before eval() is reached."""

    def setup_method(self):
        _validated_cache.clear()

    def test_dunder_attribute(self):
        with pytest.raises(ValueError, match="__class__"):
            _validate_ast("event.__class__")

    def test_dunder_mro_traversal(self):
        with pytest.raises(ValueError, match="__class__"):
            _validate_ast("event.__class__.__mro__")

    def test_subclasses_traversal(self):
        with pytest.raises(ValueError):
            _validate_ast("event.__class__.__subclasses__()")

    def test_bare_dunder_name(self):
        with pytest.raises(ValueError, match="__import__"):
            _validate_ast('__import__("os")')

    def test_bare_class_name(self):
        with pytest.raises(ValueError, match="__class__"):
            _validate_ast("__class__")

    def test_unapproved_function_open(self):
        with pytest.raises(ValueError, match="'open'"):
            _validate_ast('open("file")')

    def test_unapproved_function_print(self):
        with pytest.raises(ValueError, match="'print'"):
            _validate_ast('print("hi")')

    def test_method_call_on_attribute(self):
        with pytest.raises(ValueError, match="method calls"):
            _validate_ast("event.attacker.some_method()")

    def test_lambda(self):
        with pytest.raises(ValueError, match="Lambda"):
            _validate_ast("lambda x: x")

    def test_list_comprehension(self):
        with pytest.raises(ValueError, match="ListComp"):
            _validate_ast("[x for x in event.list]")

    def test_walrus_operator(self):
        with pytest.raises(ValueError, match="NamedExpr"):
            _validate_ast("(x := 5)")

    def test_single_underscore_attribute(self):
        with pytest.raises(ValueError, match="_internal"):
            _validate_ast("event._internal")

    def test_error_contains_expression(self):
        with pytest.raises(ValueError) as exc_info:
            _validate_ast('open("x")')
        assert 'open("x")' in str(exc_info.value)

    def test_syntax_error(self):
        with pytest.raises(ValueError, match="syntax error"):
            _validate_ast("event.hp +* 2")


# ── Caching behaviour ─────────────────────────────────────────────────────────

class TestValidateAstCaching:

    def setup_method(self):
        _validated_cache.clear()

    def test_valid_expression_added_to_cache(self):
        expr = "event.hp > 0"
        _validate_ast(expr)
        assert expr in _validated_cache

    def test_same_expression_cached_on_second_call(self):
        expr = "event.hp > 0"
        _validate_ast(expr)
        _validate_ast(expr)  # should not raise
        assert expr in _validated_cache

    def test_different_expressions_both_cached(self):
        _validate_ast("event.hp > 0")
        _validate_ast("event.total // 2")
        assert "event.hp > 0" in _validated_cache
        assert "event.total // 2" in _validated_cache

    def test_rejected_expression_not_cached(self):
        with pytest.raises(ValueError):
            _validate_ast("event.__class__")
        assert "event.__class__" not in _validated_cache


# ── Integration: evaluate() ───────────────────────────────────────────────────

class TestEvaluateIntegration:

    def setup_method(self):
        _validated_cache.clear()

    def test_evaluate_rejects_dangerous_string(self):
        ctx = {}
        with pytest.raises(ValueError):
            evaluate("event.__class__", ctx)

    def test_evaluate_code_object_bypasses_string_check(self):
        """Pre-compiled code objects (from Rule.__post_init__) must work."""
        code = compile("1 + 1", "<test>", "eval")
        assert evaluate(code, {}) == 2

    def test_evaluate_valid_string(self):
        from types import SimpleNamespace
        ctx = {"event": SimpleNamespace(hp=15), **expr_mod.SAFE_BUILTINS}
        assert evaluate("event.hp > 0", ctx) is True

    def test_evaluate_builtin_call(self):
        ctx = {**expr_mod.SAFE_BUILTINS}
        assert evaluate("max(3, 7)", ctx) == 7


# ── Integration: resolve() ────────────────────────────────────────────────────

class TestResolveIntegration:

    def setup_method(self):
        _validated_cache.clear()

    def test_resolve_string_validates(self):
        with pytest.raises(ValueError):
            resolve("event.__class__", {})

    def test_resolve_non_string_passthrough(self):
        assert resolve(42, {}) == 42
        assert resolve(None, {}) is None
        assert resolve(True, {}) is True

    def test_resolve_valid_string(self):
        from types import SimpleNamespace
        ctx = {"event": SimpleNamespace(hp=5), **expr_mod.SAFE_BUILTINS}
        assert resolve("event.hp", ctx) == 5
