"""Tests that StatBlockLoader reports friendly errors on malformed content.

Regression coverage for E4: enum typos previously raised a bare ``KeyError``
with no hint, and malformed JSON raised a raw ``json.JSONDecodeError`` — both
unhelpful for the hand/LLM-authored-JSON workflow this project is built around.
"""

import pytest

from src.loaders.stat_block_loader import StatBlockLoader


def _creature(**overrides):
    data = {"name": "T", "abilities": {}, "hit_points_max": 10, "armor_class": 10}
    data.update(overrides)
    return data


class TestFriendlyEnumErrors:
    def test_bad_attack_damage_type(self):
        data = _creature(actions=[{
            "name": "Bite", "type": "attack",
            "damage": [{"type": "SLASH", "amount": 3}],  # not a DamageType
        }])
        with pytest.raises(ValueError) as exc:
            StatBlockLoader.from_dict(data)
        assert "SLASH" in str(exc.value)
        assert "valid values" in str(exc.value).lower()

    def test_bad_targeting_type(self):
        data = _creature(actions=[{
            "name": "Zap", "type": "spell", "targeting_type": "everywhere",
        }])
        with pytest.raises(ValueError) as exc:
            StatBlockLoader.from_dict(data)
        assert "everywhere" in str(exc.value)

    def test_bad_spell_range_type(self):
        data = _creature(actions=[{
            "name": "Zap", "type": "spell",
            "spell_range": {"type": "lightyears"},
        }])
        with pytest.raises(ValueError) as exc:
            StatBlockLoader.from_dict(data)
        assert "lightyears" in str(exc.value)

    def test_bad_aoe_shape(self):
        data = _creature(actions=[{
            "name": "Zap", "type": "spell", "targeting_type": "aoe",
            "aoe": {"shape": "blob", "size_ft": 10},
        }])
        with pytest.raises(ValueError) as exc:
            StatBlockLoader.from_dict(data)
        assert "blob" in str(exc.value)


class TestDamageFormulaValidation:
    def _attack_with_formula(self, formula):
        return _creature(actions=[{
            "name": "Hit", "type": "attack",
            "damage": [{"type": "SLASHING", "formula": formula}],
        }])

    def test_multi_term_formula_accepted(self):
        # E5: previously rejected by the single-term regex.
        sb = StatBlockLoader.from_dict(self._attack_with_formula("2d6+1d8+5"))
        assert sb.actions[0].damage[0].formula == "2d6+1d8+5"

    def test_simple_formula_still_accepted(self):
        sb = StatBlockLoader.from_dict(self._attack_with_formula("3d8+6"))
        assert sb.actions[0].damage[0].formula == "3d8+6"

    def test_garbage_formula_still_rejected(self):
        with pytest.raises(ValueError) as exc:
            StatBlockLoader.from_dict(self._attack_with_formula("2d6+garbage"))
        assert "formula" in str(exc.value).lower()


class TestFriendlyJsonErrors:
    def test_malformed_creature_json_names_the_file(self, tmp_path):
        bad = tmp_path / "broken.json"
        bad.write_text("{ not valid json ", encoding="utf-8")
        with pytest.raises(ValueError) as exc:
            StatBlockLoader.load_from_json(str(bad))
        assert "broken.json" in str(exc.value)

    def test_malformed_spell_json_names_the_file(self, tmp_path):
        bad = tmp_path / "spell_broken.json"
        bad.write_text("{ oops", encoding="utf-8")
        with pytest.raises(ValueError) as exc:
            StatBlockLoader.load_spell_from_json(str(bad))
        assert "spell_broken.json" in str(exc.value)
