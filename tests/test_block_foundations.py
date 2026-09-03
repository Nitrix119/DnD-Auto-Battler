"""Foundations of the block-based spell system (Phase 1, slice 1).

The Block value type, the BlockContract (reads/writes/target arity), and the
BlockRegistry that replaces the old if/elif dispatch + rule action-verbs with one
catalogue. Pure scaffolding — no evaluator, no behaviour change yet.
"""

import pytest

from src.spells import (
    Block,
    BlockContract,
    TargetArity,
    BlockRegistry,
    RegisteredBlock,
    REGISTRY,
)
from src.spells.block import parse_program


# ── Block parsing ───────────────────────────────────────────────────────────────

class TestBlockParsing:

    def test_parses_type_and_args(self):
        b = Block.from_dict({"block": "damage", "damage_type": "FIRE", "formula": "8d6"})
        assert b.type == "damage"
        assert b.args == {"damage_type": "FIRE", "formula": "8d6"}
        assert b.then == ()

    def test_parses_nested_then_recursively(self):
        b = Block.from_dict({
            "block": "for_each_target",
            "then": [
                {"block": "attack_roll", "attack_bonus": "use_caster_bonus"},
                {"block": "damage", "formula": "2d6", "damage_type": "FIRE"},
            ],
        })
        assert b.type == "for_each_target"
        assert [c.type for c in b.then] == ["attack_roll", "damage"]
        assert b.then[1].get("formula") == "2d6"
        # `then` is not left in args.
        assert "then" not in b.args

    def test_get_reads_args(self):
        b = Block.from_dict({"block": "damage", "formula": "1d6"})
        assert b.get("formula") == "1d6"
        assert b.get("missing", "default") == "default"

    def test_missing_type_raises(self):
        with pytest.raises(ValueError):
            Block.from_dict({"damage_type": "FIRE"})

    def test_non_dict_raises(self):
        with pytest.raises(ValueError):
            Block.from_dict("damage")

    def test_non_list_then_raises(self):
        with pytest.raises(ValueError):
            Block.from_dict({"block": "for_each_target", "then": {"block": "damage"}})

    def test_block_is_immutable(self):
        b = Block.from_dict({"block": "damage"})
        with pytest.raises(Exception):
            b.type = "healing"  # frozen dataclass

    def test_parse_program(self):
        prog = parse_program([
            {"block": "attack_roll"},
            {"block": "damage", "formula": "1d6", "damage_type": "FORCE"},
        ])
        assert [b.type for b in prog] == ["attack_roll", "damage"]

    def test_parse_program_empty_and_none(self):
        assert parse_program([]) == []
        assert parse_program(None) == []

    def test_parse_program_non_list_raises(self):
        with pytest.raises(ValueError):
            parse_program({"block": "damage"})


# ── Contract / arity ────────────────────────────────────────────────────────────

class TestContract:

    def test_defaults_to_single_arity(self):
        c = BlockContract()
        assert c.target_arity is TargetArity.SINGLE
        assert c.reads == () and c.writes == ()

    def test_arity_members(self):
        assert {a.value for a in TargetArity} == {"single", "caster", "set"}

    def test_contract_carries_reads_writes(self):
        c = BlockContract(reads=("hit",), writes=("damage_dealt",),
                          target_arity=TargetArity.SINGLE)
        assert c.reads == ("hit",)
        assert c.writes == ("damage_dealt",)


# ── Registry ────────────────────────────────────────────────────────────────────

def _noop(block, inv):
    return None


class TestRegistry:

    def test_register_and_get(self):
        reg = BlockRegistry()
        contract = BlockContract(writes=("damage_dealt",))
        reg.register("damage", _noop, contract)
        got = reg.get("damage")
        assert isinstance(got, RegisteredBlock)
        assert got.handler is _noop
        assert got.contract is contract

    def test_is_registered_and_types(self):
        reg = BlockRegistry()
        assert not reg.is_registered("damage")
        reg.register("damage", _noop, BlockContract())
        assert reg.is_registered("damage")
        assert reg.types() == frozenset({"damage"})

    def test_duplicate_registration_raises(self):
        reg = BlockRegistry()
        reg.register("damage", _noop, BlockContract())
        with pytest.raises(ValueError):
            reg.register("damage", _noop, BlockContract())

    def test_unknown_block_raises_naming_valid_types(self):
        reg = BlockRegistry()
        reg.register("damage", _noop, BlockContract())
        with pytest.raises(KeyError) as exc:
            reg.get("smite")
        assert "damage" in str(exc.value)

    def test_default_registry_is_a_registry(self):
        assert isinstance(REGISTRY, BlockRegistry)
